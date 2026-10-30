# MQTT đang chạy nhưng danh sách trạm báo Offline

## Bằng chứng trực tiếp

Đã subscribe thụ động các topic `device/<IMEI>/upload` trên `aitogy.click:1883`
theo mapping người vận hành cung cấp. Không gửi lệnh cấu hình receiver.
Trong cửa sổ đo 10 giây ngày 30/10/2026:

| Trạm | IMEI | MQTT messages | GGA | AGRICA | GGA fix cuối |
| --- | --- | ---: | ---: | ---: | ---: |
| CP03 | 860549070374074 | 59 | 10 | 10 | 4 |
| CP05 | 860549070085472 | 33 | 10 | 0 | 4 |
| CP06 | 860549070084194 | 58 | 10 | 10 | 4 |
| CP08 | 860549070084095 | 58 | 10 | 10 | 4 |

CP01, CP02, CP04 và CP07 không có message trong cửa sổ đo này.
Không đưa topic của thiết bị có IMEI kết thúc bằng 338 vào nhóm CP.
Lần đo tiếp theo trong 8 giây xác nhận cả bốn CP đều có tám câu GGA đầy đủ
ngay trong từng MQTT message; không có bằng chứng mất GGA do chia fragment
trong lần đo đó.

Log Monitoring đã cung cấp xác nhận mapping CP05 → GNSS device 18,
station 15, topic `device/860549070085472/upload`; CP06 → device 16,
station 13, topic `device/860549070084194/upload`. Cả hai được subscribe
trên `aitogy.click:1883` lúc 30/10 16:50:39.

## Lỗi trong code

Pipeline đã cập nhật `Device.last_data_time` và buffer heartbeat khi nhận
text MQTT, trước khi xử lý vị trí. Tuy nhiên query danh sách trạm chỉ xét
timestamp của `LatestSensorCache` hoặc lịch sử `SensorData`, bỏ qua heartbeat.
Vì vậy việc không có bản ghi xử lý mới có thể bị diễn giải thành mất kết nối.
Đường đọc chi tiết trạm có cùng cách tính Online dựa riêng vào cache phép đo.

Ngoài ra, GNSS payload không giải mã được thành text bị trả về ngay trong
transport. Bộ theo dõi stream của round-robin vẫn thấy bytes đó, nhưng
heartbeat device/station chưa được cập nhật ở nhánh này.

Các lỗi code này đã được tái hiện bằng kiểm thử. Chưa đọc được API Monitoring
production vì endpoint yêu cầu phiên đăng nhập; browser connector hiện không
khả dụng. Vì vậy không khẳng định đã xác định được lý do cụ thể khiến cache
phép đo CP05/CP06 trên server không cập nhật. GGA FIX=4 cũng chưa chứng minh
phép đo vượt qua mọi quality/integrity gate của hệ thống.

## Bản sửa

- Query Online dùng thời gian mới nhất giữa dữ liệu xử lý, heartbeat device
  trong DB và heartbeat còn chờ flush. Áp dụng chung cho danh sách dự án,
  danh sách trạm và dashboard summary.
- Chi tiết trạm dùng cùng heartbeat để tính Online và trả thêm
  `last_received_timestamp`. Giữ nguyên `latest_timestamp`, dữ liệu vị trí,
  chất lượng và trạng thái kiểm định của phép đo.
- GNSS binary không có text vẫn cập nhật heartbeat; không tạo phép đo vị trí.
- Giữ nguyên offline timeout từng loại cảm biến. Trạm ngừng gửi sẽ hết Online
  khi vượt timeout.

CP05 chỉ được xác nhận đang kết nối và gửi GGA FIXED. Chưa thấy AGRICA trong
cửa sổ đo, nên không coi badge Online là xác nhận đủ dữ liệu bình sai.

## Kiểm chứng

86 kiểm thử và 13 subtest đạt cho MQTT lifecycle/heartbeat, station list/detail,
truy vấn dữ liệu với SQLite cô lập, bộ lọc rover online và NTRIP/round-robin.
Regression test xác nhận CP03/CP05/CP06/CP08 Online khi có dữ liệu hoặc heartbeat
mới; cả nhóm Offline sau timeout nếu không có dữ liệu tiếp; phép đo cũ không
được thay timestamp bằng heartbeat.

Chưa triển khai bản sửa lên server và chưa xác nhận badge production đã đổi.
Không thay đổi frontend, mapping trạm, origin GNSS hoặc cấu hình thiết bị.
