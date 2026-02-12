Pi Field Unit provisioning and audio player

Overview:
- Use `pi_bootstrap.py` to register and provision a Pi with the backend.
- `pi_audio_player.py` plays audio files received via MQTT or WebSocket.

Quick start on Pi:

1. Install dependencies

```bash
sudo apt update
sudo apt install -y python3-pip mpg123
pip3 install paho-mqtt requests websocket-client
```

2. Copy audio files to `~/landslide_audio/` or let `pi_bootstrap.py` download them during provisioning.

3. Run bootstrap (example):

```bash
sudo python3 field_unit/pi_bootstrap.py --backend "https://your-backend:8000" --device-code "PI-001" --name "Field Pi 1" --poll
```

4. After provisioning `systemd` unit is created at `/etc/systemd/system/landslide-audio.service` and enabled. Start it with:

```bash
sudo systemctl start landslide-audio.service
sudo systemctl status landslide-audio.service
```

Configuration files:
- Local device config: `~/.landslide_device.json`
- Audio files: `~/landslide_audio/`

Security notes:
- Use HTTPS for backend and secure MQTT (TLS) in production.
- Keep enrollment tokens short-lived and rotate if compromised.
