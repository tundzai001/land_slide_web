"""
Pi Bootstrap Script
- Registers device with backend (/api/field/register)
- Polls /api/field/<device_code>/config to get provisioning
- Downloads audio files (if URLs provided) into ~/landslide_audio
- Writes local config and enables systemd service to run `pi_audio_player.py`

Usage: sudo python3 pi_bootstrap.py --backend https://your-backend --device-code HW123 --name "Field Pi 1"
"""

import argparse
import json
import os
import sys
import time
import logging
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    print("Please install requests: pip install requests")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - BOOT - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

AUDIO_DIR = Path.home() / "landslide_audio"
LOCAL_CONFIG = Path.home() / ".landslide_device.json"

SYSTEMD_UNIT = "/etc/systemd/system/landslide-audio.service"

def ensure_audio_dir():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def register(backend_url, device_code, name):
    url = urljoin(backend_url, '/api/field/register')
    payload = {'device_code': device_code, 'name': name, 'device_type': 'pi'}
    logger.info(f"Registering device {device_code} -> {url}")
    r = requests.post(url, json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def get_config(backend_url, device_code, token=None):
    params = {}
    if token:
        params['token'] = token
    url = urljoin(backend_url, f'/api/field/{device_code}/config')
    logger.info(f"Fetching config from {url}")
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def download_file(url, dest: Path):
    logger.info(f"Downloading {url} -> {dest}")
    r = requests.get(url, stream=True, timeout=30)
    r.raise_for_status()
    with open(dest, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)


def write_local_config(data: dict):
    with open(LOCAL_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(LOCAL_CONFIG, 0o600)
    logger.info(f"Wrote local config: {LOCAL_CONFIG}")


def create_systemd_unit(python_path: str, workdir: str):
    unit = f"""[Unit]
Description=Landslide Pi Audio Player
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory={workdir}
ExecStart={python_path} {workdir}/field_unit/pi_audio_player.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    try:
        with open(SYSTEMD_UNIT, 'w', encoding='utf-8') as f:
            f.write(unit)
        logger.info(f"Wrote systemd unit: {SYSTEMD_UNIT}")
        os.system('systemctl daemon-reload')
        os.system('systemctl enable landslide-audio.service')
    except PermissionError:
        logger.error('Permission denied writing systemd unit. Run script as root to install service.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', required=True, help='Backend URL, e.g. https://server:8000')
    parser.add_argument('--device-code', required=True)
    parser.add_argument('--name', default='pi-field')
    parser.add_argument('--poll', action='store_true', help='Poll until provisioned')
    args = parser.parse_args()

    ensure_audio_dir()

    try:
        resp = register(args.backend, args.device_code, args.name)
        logger.info(f"Register response: {resp}")
        token = resp.get('enroll_token')

        # immediate fetch
        cfg = None
        try:
            cfg = get_config(args.backend, args.device_code, token=token)
        except Exception as e:
            logger.warning(f"Config fetch failed: {e}")

        if args.poll and not cfg:
            logger.info('Polling for provisioning...')
            for _ in range(60):
                time.sleep(5)
                try:
                    cfg = get_config(args.backend, args.device_code, token=token)
                    if cfg and cfg.get('config', {}).get('provisioned'):
                        break
                except Exception:
                    continue

        if not cfg:
            logger.error('No config received. Exiting.')
            sys.exit(1)

        # download audio files if provided as full URLs
        audio_list = cfg.get('config', {}).get('audio_files') or []
        for a in audio_list:
            if a.startswith('http'):
                dest = AUDIO_DIR / Path(a).name
                if not dest.exists():
                    download_file(a, dest)

        # save local config
        write_local_config(cfg)

        # attempt to create systemd unit
        python_path = sys.executable
        workdir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        create_systemd_unit(python_path, workdir)

        logger.info('Provisioning complete.')
    except Exception as e:
        logger.error(f'Bootstrap failed: {e}')
        sys.exit(1)

if __name__ == '__main__':
    main()
