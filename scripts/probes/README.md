# Công cụ Chẩn đoán & Probe Hiện trường (Field Probes)

Thư mục này chứa các kịch bản probe và dữ liệu mẫu phục vụ kiểm tra, chẩn đoán trực tiếp với trạm GNSS và MQTT broker hiện trường.

---

## Danh mục Script Probe
- **`live_qn_adjustment_probe.py`**: Chạy thử nghiệm chu trình bình sai GNSS cho dự án Mông Dương - Quảng Ninh (`CP01` - `CP08`).
- **`live_full_adjustment_probe.py`**: Kiểm thử toàn trình chu trình Round-Robin đối với cụm Đập 1 / Đập 4 (Sin Quyền).
- **`live_base_output_probe.py`**: Kiểm tra điều khiển BASE output với cơ chế bảo đảm an toàn hoàn trả về trạng thái ROVER.
- **`live_gnss_probe.py`**: Lắng nghe và kiểm tra tính hợp lệ RTCM3 / AGRICA trực tiếp từ các topic thiết bị.
- **`live_mqtt_gnss_discovery.py`**: Dò tìm các topic thiết bị đang phát dữ liệu trên MQTT broker.
- **`compare_agrica.py`**: Đối chiếu dữ liệu chuỗi AGRICA giữa các trạm.
- **`mqtt_parser.py`**: Bộ phân tích mẫu chuỗi `$GNGGA` và `#AGRICA` từ MQTT payload.

## Dữ liệu Mẫu (Test Fixtures)
- **`agrica_structure.txt`**: Đặc tả cấu trúc các trường trong bản tin `#AGRICA`.
- **`mqtt_device_capture.json`**: Mẫu dữ liệu thô thu thập từ thiết bị thực tế để test offline.
- **`mqtt_device_sentences.txt`**: Tập câu NMEA / AGRICA mẫu được trích xuất.
