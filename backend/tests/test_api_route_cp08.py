import os
import requests
import time

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api")
USERNAME = os.getenv("ADMIN_USERNAME", "admin")
PASSWORD = os.getenv("ADMIN_PASSWORD", "")

STATION_CODE = "CP08"

def main():
    # 1. Đăng nhập để lấy token
    print(f"Logging in as {USERNAME}...")
    login_data = {
        "username": USERNAME,
        "password": PASSWORD
    }
    # Form data urlencoded cho OAuth2
    login_response = requests.post(f"{BASE_URL}/auth/login", data=login_data)

    if login_response.status_code != 200:
        print("Login failed!", login_response.text)
        print("Vui lòng mở file script này và sửa lại USERNAME / PASSWORD cho đúng.")
        return

    token = login_response.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    print("Login successful! Got token.\n")

    # 2. Gọi API để STOP luồng hiện tại (giải phóng hàng đợi cũ)
    print(f"Stopping existing NTRIP route for {STATION_CODE}...")
    stop_response = requests.post(f"{BASE_URL}/admin/stations/{STATION_CODE}/ntrip_route/stop", headers=headers)
    print(f"Stop response ({stop_response.status_code}):", stop_response.text)
    print("Đợi 2 giây để chắc chắn luồng đã tắt hoàn toàn...\n")
    time.sleep(2)

    # 3. Gọi API để START luồng mới
    print(f"Starting new NTRIP route for {STATION_CODE}...")
    payload = {
        "host": "aitogy.click",
        "port": 2101,
        "mountpoint": "QN.CP",
        "password": "12345"
    }
    start_response = requests.post(
        f"{BASE_URL}/admin/stations/{STATION_CODE}/ntrip_route/start", 
        headers=headers,
        json=payload
    )
    print(f"Start response ({start_response.status_code}):", start_response.text)

if __name__ == "__main__":
    main()
