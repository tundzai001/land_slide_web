"""GNSS RTK forwarding to local or external MQTT brokers."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


class SensorForwardingMixin:
    async def _forward_gnss(
        self, info: dict, station_id: int, sensor_type: str, processed_data: dict
    ) -> None:
        if sensor_type == 'gnss' and processed_data.get('forwarding_data'):
            fwd_cfg = info.get('forwarding', {})
            if fwd_cfg.get('enabled') and fwd_cfg.get('rtk_topic'):
                try:
                    target_topic = fwd_cfg['rtk_topic']
                    # Check for external broker config
                    fwd_host = fwd_cfg.get('host')
                    fwd_port = fwd_cfg.get('port', 1883)
                    fwd_user = fwd_cfg.get('username')
                    fwd_pass = fwd_cfg.get('password')

                    # Take the full payload as structured in gnss_processor.py
                    payload = processed_data['forwarding_data']
                    fields_cfg = fwd_cfg.get('fields', {})

                    if fields_cfg and 'data' in payload:
                        # Map UI toggle names to JSON keys
                        # Format: { 'UI_KEY': ['JSON_KEY1', 'JSON_KEY2', ...] }
                        mapping = {
                            'X':   ['adv_x'],
                            'Y':   ['adv_y'],
                            'H':   ['adv_h', 'h', 'lat', 'lon'], # Lat/Lon/H usually grouped
                            'dX':  ['adv_dx', 'pos_e'],
                            'dY':  ['adv_dy', 'pos_n'],
                            'dH':  ['adv_dh', 'pos_u'],
                            'VdX': ['adv_vdx'],
                            'VdY': ['adv_vdy'],
                            'VdH': ['adv_vdh']
                        }

                        # Filter the 'data' part of the nested payload
                        data_part = payload['data']
                        for ui_key, is_enabled in fields_cfg.items():
                            if not is_enabled and ui_key in mapping:
                                for json_key in mapping[ui_key]:
                                    if json_key in data_part:
                                        del data_part[json_key]

                    # Decice which client to use
                    if fwd_host:
                        pub_client = self._get_fwd_client(fwd_host, int(fwd_port), fwd_user, fwd_pass)
                        if pub_client:
                            pub_client.publish(target_topic, json.dumps(payload))
                            logger.debug(f"🌐 [FORWARD-EXT] Published 1Hz data to {fwd_host}:{fwd_port} -> {target_topic}")
                        else:
                            logger.warning(f"⚠️ [FORWARD-EXT] Skipping publish: External broker {fwd_host} unavailable")
                    else:
                        # Default to local broker
                        self._get_client_for_station(station_id).publish(target_topic, json.dumps(payload))
                        logger.debug(f"📤 [FORWARD-LOCAL] Published 1Hz data to {target_topic}")
                except Exception as ex:
                    logger.error(f"❌ [FORWARD] Error publishing: {ex}")
