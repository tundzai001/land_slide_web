#!/bin/bash
# Setup script to install Pi audio player as a systemd service
# Usage: sudo bash setup_service.sh /path/to/repo

REPO_DIR=${1:-$(pwd)}
PYTHON=$(which python3 || which python)
SERVICE_PATH=/etc/systemd/system/landslide-audio.service

if [[ -z "$PYTHON" ]]; then
  echo "Python not found. Install python3 first." && exit 1
fi

echo "Creating audio directory in home..."
mkdir -p /root/landslide_audio || true

echo "Copying pi_audio_player.py to /opt/landslide"
mkdir -p /opt/landslide
cp "$REPO_DIR/field_unit/pi_audio_player.py" /opt/landslide/pi_audio_player.py
chmod +x /opt/landslide/pi_audio_player.py

cat > $SERVICE_PATH <<EOF
[Unit]
Description=Landslide Pi Audio Player
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/landslide
ExecStart=$PYTHON /opt/landslide/pi_audio_player.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable landslide-audio.service
systemctl start landslide-audio.service

echo "Service installed and started. Check status with: systemctl status landslide-audio.service"