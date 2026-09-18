"""MQTT connection, callback, and NTRIP-route transport behavior."""
import asyncio
import logging
import re
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
                    logger.error("MQTT background task failed: %s", exc)

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
                    logger.error("MQTT async task %s failed: %s", label, exc)

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
            logger.error(f"❌ [FORWARD] Failed to connect to external broker {host}:{port}: {e}")
            return None

    def on_connect(self, client, userdata, flags, rc, properties=None):
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

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        if not isinstance(userdata, tuple) or len(userdata) < 5:
            # Default client
            if reason_code != 0:
                logger.warning(f"⚠️ Default MQTT disconnect: rc={reason_code}. Reconnecting...")
                try:
                    client.reconnect()
                    logger.info("✅ Default MQTT Reconnected successfully")
                except Exception as e:
                    logger.error(f"❌ Default Reconnect failed: {e}. Will retry in 5s...")
                    if self.loop and self.loop.is_running():
                        self.loop.call_later(5, self._retry_connect)
            else:
                logger.info("✅ Default MQTT Disconnected gracefully")
            return

        broker_key = userdata
        if reason_code != 0:
            logger.warning(f"⚠️ MQTT disconnect from {broker_key[0]}:{broker_key[1]}: rc={reason_code}. Reconnecting...")
            try:
                client.reconnect()
                logger.info(f"✅ MQTT Reconnected to {broker_key[0]}:{broker_key[1]} successfully")
            except Exception as e:
                logger.error(f"❌ Reconnect to {broker_key[0]}:{broker_key[1]} failed: {e}.")
        else:
            logger.info(f"✅ MQTT Disconnected from {broker_key[0]}:{broker_key[1]} gracefully")

    def _retry_connect(self):
        try:
            self.client.reconnect()
            logger.info("✅ MQTT Reconnected after retry")
        except Exception as e:
            logger.error(f"❌ Retry failed: {e}. Next retry in 10s...")
            self.loop.call_later(10, self._retry_connect)

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

    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            
            if topic.startswith("command/ntrip/"):
                self._handle_ntrip_command(msg)
                return
            
            # Resolve the correct broker key for lookup
            if isinstance(userdata, tuple) and len(userdata) >= 5:
                broker_key = userdata
            else:
                # Default client's broker key
                broker_key = (
                    self.runtime_mqtt["broker"],
                    self.runtime_mqtt["port"],
                    self.runtime_mqtt["user"] or None,
                    self.runtime_mqtt["password"] or None,
                    False
                )
                
            info = self.topic_map.get((broker_key, topic))
            if not info:
                # Fallback to check with TLS=True in case default client gets hit
                info = self.topic_map.get(((broker_key[0], broker_key[1], broker_key[2], broker_key[3], True), topic))
                
            if not info:
                if self._diag_should_log(f"unknown_topic:{broker_key}:{topic}", 60):
                    logger.warning(f"[MQTT] Received message from {broker_key[0]}:{broker_key[1]} on unknown topic: {topic}")
                return

            sensor_type = (info or {}).get('type')
            if sensor_type == 'gnss':
                station_code = (info or {}).get('station_code')
                if station_code:
                    from app.mqtt.ntrip_pusher import ntrip_manager
                    ntrip_manager.feed_data(station_code, msg.payload)
                # Inspect the original bytes before text decoding. RTCM is binary
                # and is intentionally discarded by the normal sensor pipeline.
                self.round_robin_manager.observe_gnss_payload(info, msg.payload)
                    
            try:
                if sensor_type == 'gnss':
                    # Decode full text payload, retaining AGRICA and other sentences
                    payload_str = msg.payload.decode('utf-8', errors='ignore')
                    decrypted_payload = payload_str.strip()
                else:
                    payload_str = msg.payload.decode('utf-8')
                    decrypted_payload = payload_str.strip()

                if sensor_type == 'gnss' and not decrypted_payload:
                    # Silently return on empty/binary frames to avoid console flooding
                    return

                if sensor_type == 'gnss':
                    # SET socket data only proves that AICaster echoed the bytes.
                    # Receiver acceptance is reported on this rover's own GNSS
                    # MQTT topic as: exact command echo, then OK/ERROR.
                    self.round_robin_manager.add_receiver_command_payload(
                        decrypted_payload,
                        info,
                        topic,
                    )
                
            except UnicodeDecodeError:
                return # Bỏ qua dữ liệu nhị phân (RTCM)

            if not decrypted_payload:
                return
            
            self._submit_threadsafe(
                self.process_pipeline(info, decrypted_payload),
                "sensor-pipeline",
            )
        except Exception as e:
            logger.error(f"Error in on_message: {e}")

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
                if station_code:
                    if self.loop and self.loop.is_running():
                        self._submit_threadsafe(
                            ntrip_manager.stop_pusher(station_code),
                            "ntrip-route-stop",
                        )
        except Exception as e:
            logger.error(f"[NTRIP COMMAND] Error processing command: {e}")

    async def _start_round_robin_ntrip_route(
        self,
        station_code: str,
        host: str,
        port: int,
        mountpoint: str,
        password: str,
    ) -> bool:
        """Open every SOURCE target and wait for all caster handshakes."""

        from app.mqtt.ntrip_pusher import ntrip_manager

        mapped_topics = sorted({
            topic
            for (_broker_key, topic), info in self.topic_map.items()
            if str((info or {}).get("station_code") or "").casefold() == str(station_code).casefold()
            and (info or {}).get("type") == "gnss"
        })
        configured_hosts = list(
            dict.fromkeys(
                [str(host).strip()]
                + [
                    str(item).strip()
                    for item in getattr(
                        self.round_robin_manager, "caster_hosts", []
                    )
                ]
            )
        )
        configured_hosts = [item for item in configured_hosts if item]
        failures = []
        for source_host in configured_hosts:
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
                if source_host != host:
                    logger.warning(
                        "[Round-Robin RTCM] station=%s SOURCE failed over from %s to %s",
                        station_code,
                        host,
                        source_host,
                    )
                return True
            except Exception as exc:
                failures.append(f"{source_host}:{port} ({exc})")
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

        detail = "; ".join(failures) or "no NTRIP SOURCE host is configured"
        raise RuntimeError(
            f"All NTRIP SOURCE hosts failed for {station_code}: {detail}; "
            f"mapped_mqtt_topics={mapped_topics}"
        )

    async def _wait_round_robin_ntrip_route(
        self,
        station_code: str,
        timeout: float = 25.0,
    ) -> None:
        """Require the first valid RTCM frame on every primed mountpoint."""

        from app.mqtt.ntrip_pusher import ntrip_manager

        try:
            await ntrip_manager.wait_for_rtcm(station_code, timeout=timeout)
        except Exception:
            logger.error(
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

        try:
            self.client.connect(self.runtime_mqtt["broker"], self.runtime_mqtt["port"], 60)
            self.client.loop_start()
            self._track_background_task(self.reload_topics_from_db())
            self._track_background_task(self._flush_loop())  # ✅ Khởi động flush buffer
            self._track_background_task(self._drain_ingest_spool_loop())
            logger.info("✅ MQTT Bridge started successfully.")
        except Exception as e:
            logger.error(f"❌ Failed to start MQTT Bridge: {e}")

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

    def _get_client_for_station(self, station_id: int) -> mqtt.Client:
        """Return the station's dynamic client, falling back to the main client."""
        broker_key = self._station_brokers.get(station_id)
        if broker_key and broker_key in self._sub_clients:
            return self._sub_clients[broker_key]
        return self.client
