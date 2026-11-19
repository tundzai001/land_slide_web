"""GNSS RTK forwarding to local or external MQTT brokers."""

from __future__ import annotations

import json
import logging
import copy

from app.features.operations.forwarding import approved

logger = logging.getLogger(__name__)


class SensorForwardingMixin:
    def _filter_forwarding_payload(self, payload: dict, fields_cfg: dict):
        if not fields_cfg or "data" not in payload:
            return
        mapping = {
            "X": ["adv_x"], "Y": ["adv_y"], "H": ["adv_h", "h", "lat", "lon"],
            "dX": ["adv_dx", "pos_e"], "dY": ["adv_dy", "pos_n"], "dH": ["adv_dh", "pos_u"],
            "VdX": ["adv_vdx"], "VdY": ["adv_vdy"], "VdH": ["adv_vdh"]
        }
        data_part = payload["data"]
        for ui_key, is_enabled in fields_cfg.items():
            if not is_enabled and ui_key in mapping:
                for json_key in mapping[ui_key]:
                    data_part.pop(json_key, None)

    def _publish_forwarding_payload(self, fwd_cfg: dict, target_topic: str, payload: dict, station_id: int):
        fwd_host = fwd_cfg.get("host")
        fwd_port = fwd_cfg.get("port", 1883)
        fwd_user = fwd_cfg.get("username")
        fwd_pass = fwd_cfg.get("password")
        if fwd_host:
            pub_client = self._get_fwd_client(fwd_host, int(fwd_port), fwd_user, fwd_pass)
            if pub_client:
                pub_client.publish(target_topic, json.dumps(payload))
                logger.debug(f"🌐 [FORWARD-EXT] Published 1Hz data to {fwd_host}:{fwd_port} -> {target_topic}")
            else:
                logger.warning(f"⚠️ [FORWARD-EXT] Skipping publish: External broker {fwd_host} unavailable")
        else:
            self._get_client_for_station(station_id).publish(target_topic, json.dumps(payload))
            logger.debug(f"📤 [FORWARD-LOCAL] Published 1Hz data to {target_topic}")

    def _forward_gnss(
        self, info: dict, station_id: int, sensor_type: str, processed_data: dict
    ) -> None:
        if sensor_type != "gnss" or not processed_data.get("forwarding_data"):
            return
        fwd_cfg = info.get("forwarding", {})
        if not approved(station_id, fwd_cfg) or not fwd_cfg.get("rtk_topic"):
            return
        try:
            target_topic = fwd_cfg["rtk_topic"]
            payload = copy.deepcopy(processed_data["forwarding_data"])
            self._filter_forwarding_payload(payload, fwd_cfg.get("fields", {}))
            self._publish_forwarding_payload(fwd_cfg, target_topic, payload, station_id)
        except Exception as ex:
            logger.exception(f"❌ [FORWARD] Error publishing: {ex}")
