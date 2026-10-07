# Kiểm tra tải DB quan trắc — 07/10/2026

Phạm vi: đường MQTT → bộ đệm → lưu DB/spool, danh sách DB, trạng thái trạm, chi tiết trạm, lịch sử biểu đồ và xuất dữ liệu. Không kết nối hoặc thay đổi dữ liệu PostgreSQL production. Không đổi schema, index hay xóa dữ liệu cũ.

## Các vấn đề đã sửa

| Vấn đề | Cách sửa |
| --- | --- |
| Danh sách/thống kê DB mặc định chỉ tính bốn sensor cũ | Dùng đủ 14 loại từ danh mục chung; các stream GNSS nội bộ vẫn tách riêng. |
| JSON dạng sóng bị kéo qua nhiều cửa sổ sắp xếp lịch sử | Chỉ xếp hạng ID, timestamp và ba giá trị số; lấy JSON ở bước cuối sau chọn mẫu. |
| Biểu đồ lịch sử tải mảng waveform không cần dùng | Loại waveform trong SQL của API lịch sử và lịch sử đi kèm chi tiết. Mẫu mới nhất, bản ghi gốc và export giữ đầy đủ waveform. |
| Giới hạn lịch sử có thể trả tới khoảng gấp đôi giá trị yêu cầu | Tính tối đa tám điểm ứng viên/bucket và chặn số điểm đầu ra theo từng sensor. Mặc định 500, tối đa 2.000 mỗi loại. |
| Danh sách trạng thái trạm đọc toàn bộ cache JSON | Chỉ đọc station_id, sensor_type, timestamp. |
| Mỗi gói waveform ép flush riêng | Giữ mọi gói trong buffer, gom theo vòng flush 5 giây sẵn có. Không bỏ mẫu waveform theo chu kỳ sensor chậm. |
| Lệnh insert/upsert có thể quá nhiều tham số khi thêm nhiều sensor | Chia cả SensorData và LatestSensorCache thành lệnh tối đa 256 hàng, dùng chung transaction cho mỗi đợt ghi. |
| DB lỗi khiến dữ liệu vừa có trên đĩa vừa giữ trùng RAM | Spool nhận quyền lưu/replay các batch ghi đĩa thành công. Chỉ bản ghi chưa ghi đĩa được giữ RAM để thử lại. |
| Spool bị từ chối hoặc ghi đĩa lỗi có thể gắn nhầm ID bền vững | Bỏ ID spool trên batch chưa ghi thành công; giữ bản ghi để thử lại. Lỗi đĩa được bắt và ghi log. |
| Đọc/thống kê/xóa batch spool tải cả file vào RAM | Duyệt từng envelope; pending dừng đúng giới hạn; thống kê và rewrite không giữ toàn bộ file trong RAM. Batch spool mới tối đa 256 hàng; replay một envelope mỗi lượt. |
| Gateway gửi lại cùng mẫu nhưng thời điểm nhận khác nhau | Sensor mới dùng measured_at hoặc thời điểm bắt đầu waveform để tạo ingest_id ổn định; bỏ received_at khỏi identity. Mẫu không có thời điểm đo tiếp tục dùng fallback cũ. |
| Payload bất thường quá lớn | Sensor mới từ chối gói MQTT trên 256 KiB trước parse JSON. Waveform giới hạn 1–1024 mẫu/trục, ba trục bằng chiều dài. |

Giá trị invalid giữ trong JSON để truy vết, các cột số chỉ mục không đưa vào thống kê hợp lệ. Null không được giả thành zero trong bước chọn cực trị lịch sử. Giãn kế giữ toàn bộ tối đa 64 điểm trong JSON, không thêm hàng DB riêng cho từng điểm.

## Kiểm tra thực hiện

- DB SQLite **tạm trên đĩa**, dùng bảng và writer production: ghi/đọc đủ 14 sensor, danh sách DB mặc định có đủ loại mới, export có writer tương ứng, giãn kế giữ đủ 64 điểm.
- 1.000 gói waveform, mỗi trục 1.024 mẫu: API lịch sử và phần history của chi tiết không chứa waveform; latest và bản ghi gốc vẫn giữ đủ mảng. Thử limit 1, 7, 8, 50, 500 và giữ đúng giới hạn từng loại.
- PostgreSQL: compile truy vấn history/JSONB; xác nhận JSON chỉ xuất hiện ở bước lấy payload cuối. Giả lập 700 bản ghi: insert và cache upsert chia 256 + 256 + 188, mỗi đợt một commit.
- DB lỗi, spool đầy, đĩa lỗi, đọc lại spool sau restart, acknowledge batch, bản tin gửi lại: kiểm tra dữ liệu giữ nguyên và các nhánh retry.
- Kiểm tra UI Chromium, bao gồm chọn/lưu nhiều loại sensor, dữ liệu zero/stale/invalid, ba trục, nhiều điểm giãn kế, waveform và dọn chart.

## Thử tải tổng hợp

SQLite local, một trạm, 14 loại, 100.000 bản ghi số; không phải mô phỏng toàn bộ hệ thống production hoặc tải đồng thời nhiều người dùng.

| Đại lượng | Kết quả |
| --- | --- |
| Ghi 100.000 bản ghi bằng transaction fixture | 0,662 giây |
| Truy vấn history, limit 500 mỗi loại | 0,974 giây |
| Số điểm trả về | 5.092 tổng, tối đa 369 mỗi loại |
| JSON kết quả | 421.946 byte |

Thời gian ghi fixture không phải benchmark toàn pipeline MQTT. Số điểm history có thể ít hơn limit vì một hàng đồng thời là điểm đầu/cuối hoặc cực trị. Cực trị dùng ba cột chỉ mục số, không bảo đảm bắt toàn bộ đỉnh của mọi điểm giãn kế.

## Dung lượng và giới hạn còn lại

Ví dụ một gói ba trục × 1.024 mẫu, 250 Hz, các số 0,01 / −0,02 / 0,03: JSON khoảng 16.477 byte. Ghi liên tục tương đương **347,6 MB payload/ngày/cảm biến**, khoảng 126,9 GB/năm và 1,27 TB/10 năm. Đây là phép tính payload JSON trước nén; không phải số đo dung lượng PostgreSQL. DB còn có index, WAL, backup; mức nén phụ thuộc tín hiệu. Không cộng kiểu 250 hàng DB/giây: một hàng chứa một gói nhiều mẫu.

Web hiện lưu waveform trong SensorData. Chưa có kho waveform dài hạn riêng, phân vùng/retention cho waveform, tự ghép sự kiện hay chuyển raw sang kho tệp. Với yêu cầu ghi liên tục nhiều năm cần chốt số thiết bị, tần số, độ dài sự kiện và chính sách lưu trước khi xác nhận cấu hình lưu trữ.

Buffer bình thường có cửa sổ chưa commit khoảng 5 giây, có thể lâu hơn khi DB chậm. Spool bảo vệ các batch ghi DB thất bại, không cam kết không mất dữ liệu khi tiến trình mất điện trước flush. Spool mặc định 256 MiB; khi DB và spool đều không dùng được, RAM vẫn giữ dữ liệu để tránh chủ động bỏ mẫu và có thể tăng theo thời gian. Cần giám sát DB/spool/đĩa; chưa có backpressure toàn tuyến để bảo đảm chạy vô hạn khi storage lỗi.

Chưa đo PostgreSQL production, dung lượng đĩa thực, kết nối đồng thời, WAL/I/O hoặc thông lượng gateway thật. Các kết quả local không xác nhận năng lực lưu 10 năm hoặc khả năng chịu mọi mức tải.

## Chạy lại

Cài các dependency backend trong môi trường test riêng; SQLite test nằm trong thư mục tạm và được dọn khi kết thúc.

```sh
PYTHONPATH=backend python -m pytest -q backend/tests/test_monitoring_database.py backend/tests/test_monitoring_persistence.py backend/tests/test_monitoring_sensors.py backend/tests/test_mqtt_persistence_buffer.py backend/tests/test_ingest_spool.py backend/tests/test_database_admin_runtime.py backend/tests/test_excel_export.py backend/tests/test_xlsx_sensor_writers.py backend/tests/test_alert_persistence_contract.py backend/tests/test_mqtt_transport_lifecycle.py backend/tests/test_app_composition.py backend/tests/test_mqtt_topics.py
PYTHONPATH=backend python -m pytest -q backend/tests/test_gnss_integrity.py backend/tests/test_gnss_adjustment_excel_report.py
PYTHONPATH=backend python scripts/benchmark-monitoring-db.py
npx playwright test tests/ui/monitoring-sensors.spec.js --project=chromium --workers=1
```

Lượt kiểm tra DB/API: 47 test và 10 subtest qua. Lượt hồi quy GNSS kèm DB: 69 test và 2 subtest qua (có kiểm tra DB lặp trong hai lượt). UI: 5 test qua. Các cảnh báo Pydantic Config kiểu cũ vẫn tồn tại, không liên quan thay đổi lưu dữ liệu này.

Truy vấn history vẫn phải quét và chọn mẫu trong khoảng thời gian yêu cầu; giới hạn đầu ra không giới hạn số hàng DB phải xử lý. Với hàng triệu mẫu hoặc nhiều truy vấn đồng thời, cần đo PostgreSQL và cân nhắc rollup/phân vùng theo số đo thực tế. Không dùng thời gian SQLite local làm cam kết độ trễ production.
