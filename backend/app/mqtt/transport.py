"""MQTT connection, callback, and NTRIP-route transport behavior."""
import asyncio
import logging
import re
import time
from typing import Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MQTTTransportMixin:
    def _track_background_task(self, coroutine):
        task = self.loop.create_task(coroutine)
        self._background_tasks.add(task)

        def consume_result(done_task):
            self._background_tasks.discard(done_task)
            if done_task.cancelled():
                return
            try:
                done_task.result()
            except Exception as exc:
                if not self._stopping:
                    logger.exception("MQTT background task failed: %s", exc)

        task.add_done_callback(consume_result)
        return task

    def _submit_threadsafe(self, coroutine, label: str):
        if self._stopping or not self.loop or not self.loop.is_running():
            coroutine.close()
            return None
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        self._threadsafe_futures.add(future)

        def consume_result(done_future):
            self._threadsafe_futures.discard(done_future)
            if done_future.cancelled():
                return
            try:
                done_future.result()
            except Exception as exc:
                if not self._stopping:
                    logger.exception("MQTT async task %s failed: %s", label, exc)

        future.add_done_callback(consume_result)
        return future

    def _get_fwd_client(self, host: str, port: int, user: Optional[str], password: Optional[str]):
        """Get or create a persistent MQTT client for external forwarding."""
        key = (host, port, user, password)
        if key in self._fwd_clients:
            client = self._fwd_clients[key]
            if client.is_connected():
                return client
            try:
                client.reconnect()
                return client
            except Exception:
                pass

        try:
            logger.info(f"🌐 [FORWARD] Creating new external MQTT client for {host}:{port}")
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            if user:
                client.username_pw_set(user, password)
            client.connect(host, port, 60)
            client.loop_start()
            self._fwd_clients[key] = client
            return client
        except Exception as e:
            logger.exception(f"❌ [FORWARD] Failed to connect to external broker {host}:{port}: {e}")
            return None

    def on_connect(self, client, userdata, _flags, rc, _properties=None):
        if not isinstance(userdata, tuple) or len(userdata) < 5:
            # Default client
            if rc == 0:
                logger.info("✅ Default MQTT Connected to Broker.")
                client.subscribe("command/ntrip/#")
            else:
                logger.error(f"❌ Default MQTT Connection failed: rc={rc}")
            return

        broker_key = userdata
        if rc == 0:
            logger.info(f"✅ MQTT Connected to Broker {broker_key[0]}:{broker_key[1]}.")
            topics = self._client_topics.get(broker_key, set())
            for topic in topics:
                client.subscribe(topic)
                logger.info(f"   ✓ Subscribed: {topic} on {broker_key[0]}:{broker_key[1]}")
        else:
            logger.error(f"❌ MQTT Connection to {broker_key[0]}:{broker_key[1]} failed: rc={rc}")

    def on_disconnect(self, _client, userdata, _disconnect_flags, reason_code, _properties):
        if isinstance(userdata, tuple) and len(userdata) >= 5:
            host, port = userdata[:2]
        else:
            host, port = self.runtime_mqtt["broker"], self.runtime_mqtt["port"]
        # Paho's network loop owns reconnection, including the first attempt.
        if reason_code != 0 and not self._stopping:
            logger.warning("MQTT disconnected from %s:%s: rc=%s; network loop will retry", host, port, reason_code)
        else:
            logger.info("MQTT disconnected from %s:%s", host, port)

    def on_connect_fail(self, _client, userdata):
        if isinstance(userdata, tuple) and len(userdata) >= 5:
            host, port = userdata[:2]
        else:
            host, port = self.runtime_mqtt["broker"], self.runtime_mqtt["port"]
        logger.warning("MQTT TCP connection failed to %s:%s; network loop will retry", host, port)

    def _extract_gga_from_payload(self, payload_bytes: bytes) -> Optional[str]:
        """Extract a single NMEA GGA sentence from mixed binary/text payload."""
        if not payload_bytes:
            return None

        gga_regex = re.compile(rb'\$G[NP]GGA,[^\r\n*]*(?:\*[0-9A-Fa-f]{2})?')

        match = gga_regex.search(payload_bytes)
        if not match and b'\x00' in payload_bytes:
            # Some encoders interleave NULL bytes; remove them and retry.
            compact_bytes = payload_bytes.replace(b'\x00', b'')
            match = gga_regex.search(compact_bytes)

        if not match:
            return None

        return match.group(0).decode('ascii', errors='ignore').strip()

    def _resolve_topic_info(self, userdata, topic):
        if isinstance(userdata, tuple) and len(userdata) >= 5:
            broker_key = userdata
        else:
            broker_key = (
                self.runtime_mqtt["broker"],
                self.runtime_mqtt["port"],
                self.runtime_mqtt["user"] or None,
                self.runtime_mqtt["password"] or None,
                False
            )
        info = self.topic_map.get((broker_key, topic))
        if not info:
            tls_key = (broker_key[0], broker_key[1], broker_key[2], broker_key[3], True)
            info = self.topic_map.get((tls_key, topic))
        return info, broker_key

    @staticmethod
    def _decode_incoming_payload(sensor_type, payload_bytes):
        try:
            if sensor_type == 'gnss':
                return payload_bytes.decode('utf-8', errors='ignore').strip()
            return payload_bytes.decode('utf-8').strip()
        except UnicodeDecodeError:
            return None

    def _handle_gnss_message(self, info, msg, decrypted_payload, topic):
        station_code = (info or {}).get('station_code')
        if station_code:
            from app.mqtt.ntrip_pusher import ntrip_manager
            ntrip_manager.feed_data(station_code, msg.payload)
        self.round_robin_manager.observe_gnss_payload(info, msg.payload)

        if not decrypted_payload and msg.payload:
            self._submit_threadsafe(
                self._touch_online_heartbeat(info["device_id"], info["station_id"], int(time.time())),
                "gnss-heartbeat",
            )
        elif decrypted_payload:
            self.round_robin_manager.add_receiver_command_payload(
                decrypted_payload,
                info,
                topic,
            )

    def on_message(self, _client, userdata, msg):
        try:
            topic = msg.topic
            if topic.startswith("command/ntrip/"):
                self._handle_ntrip_command(msg)
                return

            info, broker_key = self._resolve_topic_info(userdata, topic)
            if not info:
                if self._diag_should_log(f"unknown_topic:{broker_key}:{topic}", 60):
                    logger.warning(f"[MQTT] Received message from {broker_key[0]}:{broker_key[1]} on unknown topic: {topic}")
                return

            sensor_type = (info or {}).get('type')
            decrypted_payload = self._decode_incoming_payload(sensor_type, msg.payload)

            if sensor_type == 'gnss':
                self._handle_gnss_message(info, msg, decrypted_payload, topic)
                if not decrypted_payload:
                    return

            if not decrypted_payload:
                return

            self._submit_threadsafe(
                self.process_pipeline(info, decrypted_payload),
                "sensor-pipeline",
            )
        except Exception as e:
            logger.exception(f"Error in on_message: {e}")

    def _handle_ntrip_command(self, msg):
        try:
            import json
            payload = json.loads(msg.payload.decode('utf-8'))
            from app.mqtt.ntrip_pusher import ntrip_manager
            import asyncio
            if msg.topic == "command/ntrip/route/start":
                route_payload = payload.get("ntrip_route") if isinstance(payload.get("ntrip_route"), dict) else payload
                station_code = route_payload.get("station_code")
                mountpoint = route_payload.get("mountpoint")
                if not station_code and isinstance(mountpoint, str) and mountpoint.endswith("_BASE"):
                    station_code = mountpoint[:-5]
                host = (
                    route_payload.get("host")
                    or route_payload.get("target_host")
                    or next(
                        (
                            item.strip()
                            for item in settings.NTRIP_HOSTS.split(",")
                            if item.strip()
                        ),
                        "",
                    )
                )
                port = int(
                    route_payload.get("port")
                    or route_payload.get("target_port")
                    or settings.NTRIP_PORT
                )
                password = route_payload.get("password")
                if password is None:
                    password = settings.NTRIP_PASSWORD
                if station_code and mountpoint and host:
                    if self.loop and self.loop.is_running():
                        self._submit_threadsafe(
                            ntrip_manager.start_pusher(station_code, host, port, mountpoint, password),
                            "ntrip-route-start",
                        )
                else:
                    logger.warning("[NTRIP COMMAND] Ignored start route missing station_code or mountpoint: %s", payload)
            elif msg.topic == "command/ntrip/route/stop":
                station_code = payload.get("station_code")
                if station_code and self.loop and self.loop.is_running():
                    self._submit_threadsafe(
                        ntrip_manager.stop_pusher(station_code),
                        "ntrip-route-stop",
                    )
        except Exception as e:
            logger.exception(f"[NTRIP COMMAND] Error processing command: {e}")

    async def _start_round_robin_ntrip_route(
        self,
        station_code: str,
        host: str,
        port: int,
        mountpoint: str,
        password: str,
    ) -> bool:
        """Open all mountpoints on the caster selected for the rover clients."""

        from app.mqtt.ntrip_pusher import ntrip_manager

        mapped_topics = sorted({
            topic
            for (_broker_key, topic), info in self.topic_map.items()
            if str((info or {}).get("station_code") or "").casefold() == str(station_code).casefold()
            and (info or {}).get("type") == "gnss"
        })
        # A SOURCE handshake on another caster does not move the rover clients.
        # Propagate failure so the receiver flow waits for this mountpoint's
        # release before sending SET BASE, or safely skips the rotation.
        source_host = str(host).strip()
        logger.info(
            "[Round-Robin RTCM] station=%s source_target=%s:%s/%s mqtt_topics=%s",
            station_code,
            source_host,
            port,
            mountpoint,
            mapped_topics,
        )
        try:
            await ntrip_manager.start_pusher(
                station_code, source_host, port, mountpoint, password
            )
        except Exception as exc:
            diagnostics = ntrip_manager.get_diagnostics(station_code)
            diagnostics["mapped_mqtt_topics"] = mapped_topics
            logger.warning(
                "[Round-Robin RTCM] station=%s source_target=%s failed: %s diagnostics=%s",
                station_code,
                source_host,
                exc,
                diagnostics,
            )
            await ntrip_manager.stop_pusher(station_code)
            raise
        return True

    async def _wait_round_robin_ntrip_route(
        self,
        station_code: str,
    ) -> None:
        """Require the first valid RTCM frame on every primed mountpoint."""

        from app.mqtt.ntrip_pusher import ntrip_manager

        try:
            async with asyncio.timeout(25.0):
                await ntrip_manager.wait_for_rtcm(station_code)
        except Exception:
            logger.exception(
                "[Round-Robin RTCM] station=%s fanout verification failed diagnostics=%s",
                station_code,
                ntrip_manager.get_diagnostics(station_code),
            )
            raise
        logger.info(
            "[Round-Robin RTCM] station=%s fanout verified diagnostics=%s",
            station_code,
            ntrip_manager.get_diagnostics(station_code),
        )

    async def _stop_round_robin_ntrip_route(self, station_code: str) -> None:
        from app.mqtt.ntrip_pusher import ntrip_manager

        await ntrip_manager.stop_pusher(station_code)

    def start(self):
        logger.info("🚀 Starting MQTT Bridge inside FastAPI...")
        try:
            self.loop = asyncio.get_running_loop()
            self._stopping = False
        except RuntimeError:
            logger.error("❌ No running event loop found!")
            return

        # Device brokers and durable writes must run even if the default broker is down.
        self._track_background_task(self.reload_topics_from_db())
        self._track_background_task(self._flush_loop())
        self._track_background_task(self._drain_ingest_spool_loop())
        self._track_background_task(self._idle_rover_guard_loop())
        try:
            self.client.connect_async(self.runtime_mqtt["broker"], self.runtime_mqtt["port"], 60)
            self.client.loop_start()
            logger.info("MQTT network loop started for %s:%s; awaiting broker connection", self.runtime_mqtt["broker"], self.runtime_mqtt["port"])
        except Exception as e:
            logger.exception(f"❌ Failed to start MQTT Bridge: {e}")

    async def stop(self):
        logger.info("🛑 Stopping MQTT Bridge...")
        self._stopping = True
        try:
            self.client.loop_stop()
            self.client.disconnect()
        finally:
            # Give the durable batch path one bounded final attempt before
            # cancelling background tasks and disposing database pools.
            try:
                await asyncio.wait_for(self._flush_write_buffer(), timeout=5.0)
            except Exception as exc:
                logger.warning("Final MQTT persistence flush deferred: %s", exc)
            pending_futures = list(self._threadsafe_futures)
            for future in pending_futures:
                future.cancel()
            if pending_futures:
                await asyncio.gather(
                    *(asyncio.wrap_future(future) for future in pending_futures),
                    return_exceptions=True,
                )

            pending_tasks = list(self._background_tasks)
            for task in pending_tasks:
                task.cancel()
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            self._threadsafe_futures.clear()
            self._background_tasks.clear()

    async def reset_gnss_origin(self, device_id: int, station_id: Optional[int] = None):
        """Calibrate tracking offset while preserving the survey origin."""
        proc_key = f"device_{device_id}"
        processor = self.processors_cache.get(proc_key)
        if processor and hasattr(processor, "recalibrate_tracking_offset"):
            result = await processor.recalibrate_tracking_offset(station_id=station_id)
            logger.info(f"🎯 [BRIDGE] Calibrated tracking offset for device {device_id}")
            return result
        return None

    async def relock_gnss_origin(
        self,
        device_id: int,
        *,
        station_id: int,
        actor: str,
    ):
        """Relock one device's immutable monitoring origin from stable live fixes."""
        processor = self.processors_cache.get(f"device_{device_id}")
        if not processor or not hasattr(processor, "relock_origin"):
            raise RuntimeError("GNSS processor is not ready; wait for live RTK FIXED data")
        return await processor.relock_origin(station_id=station_id, actor=actor)

    def _get_client_for_station(self, station_id: int) -> mqtt.Client:
        """Return the station's dynamic client, falling back to the main client."""
        broker_key = self._station_brokers.get(station_id)
        if broker_key and broker_key in self._sub_clients:
            return self._sub_clients[broker_key]
        return self.client
