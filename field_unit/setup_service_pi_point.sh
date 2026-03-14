#!/bin/bash
# Install systemd service for field_unit/pi_point.py
# Usage:
#   sudo bash setup_service_pi_point.sh [base_dir] [service_user] [python_bin]

set -euo pipefail

BASE_DIR=${1:-$(cd "$(dirname "$0")" && pwd)}
DEFAULT_USER=${SUDO_USER:-$(id -un)}
SERVICE_USER=${2:-${DEFAULT_USER}}
SERVICE_NAME="landslide-pi-point.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"

if [[ -f "${BASE_DIR}/pi_point.py" ]]; then
  SCRIPT_PATH="${BASE_DIR}/pi_point.py"
  WORK_DIR="${BASE_DIR}"
elif [[ -f "${BASE_DIR}/field_unit/pi_point.py" ]]; then
  SCRIPT_PATH="${BASE_DIR}/field_unit/pi_point.py"
  WORK_DIR="${BASE_DIR}/field_unit"
else
  echo "Script not found. Tried:" >&2
  echo "  - ${BASE_DIR}/pi_point.py" >&2
  echo "  - ${BASE_DIR}/field_unit/pi_point.py" >&2
  exit 1
fi

if [[ -n "${3:-}" ]]; then
  PYTHON_BIN="${3}"
elif [[ -x "${WORK_DIR}/venv/bin/python" ]]; then
  PYTHON_BIN="${WORK_DIR}/venv/bin/python"
else
  PYTHON_BIN=$(command -v python3 || command -v python || true)
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "Python not found. Install python3 first." >&2
  exit 1
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python executable not found or not executable: ${PYTHON_BIN}" >&2
  exit 1
fi

echo "Installing ${SERVICE_NAME}"
echo "Base dir: ${BASE_DIR}"
echo "Work dir: ${WORK_DIR}"
echo "Script: ${SCRIPT_PATH}"
echo "Python: ${PYTHON_BIN}"
echo "User: ${SERVICE_USER}"

cat > "${SERVICE_PATH}" <<EOF
[Unit]
Description=Landslide Field Unit - Pi Point
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${WORK_DIR}
ExecStart=${PYTHON_BIN} ${SCRIPT_PATH}
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "Done. Check status with: systemctl status ${SERVICE_NAME}"
