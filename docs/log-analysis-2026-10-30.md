# Phân tích landslide_system.log ngày 30/10/2026

## Phạm vi và bằng chứng

Đã đọc toàn bộ bản `landslide_system.log` được cung cấp trên Desktop, không phải
file cùng tên trong thư mục dự án. Giữ nguyên file gốc.

- Dung lượng: 110.719.023 byte, khoảng 105,59 MiB.
- Khoảng thời gian: 03/10/2026 01:49:49,151 đến 30/10/2026 18:35:30,754.
- 399.742 bản ghi có timestamp: 204.627 INFO, 185.823 WARNING,
  9.266 ERROR và 26 CRITICAL. Traceback nhiều dòng không được tính thành bản ghi mới.
- SHA-256: `a70c33f80a6a0c080f71f5dc0716c43c9f1c40498e61c98155bbdedb1ed2b758`.

Các kết luận dưới đây mô tả bản log đã cung cấp. Không có lỗi mới trong đoạn cuối
không chứng minh mọi thiết bị hoặc mọi tác vụ nền đang hoạt động đúng.

## Các nhóm lỗi chính

| Nhóm | Bằng chứng | Đánh giá |
| --- | --- | --- |
| MQTT khởi động thất bại | `WinError 10061` lúc 30/10 16:22:03 | Đã có bản sửa để mỗi broker thử lại độc lập. Log xác nhận broker mặc định và các client `.asia`/`.click` kết nối thành công lúc 16:50:38–16:50:39. |
| WEB CORS trả 502 | Ngày 30/10 có warning lúc 17:29:59; có `connection recovered` lúc 17:33:18 | Sự cố upstream tạm thời đã hồi phục trong bản log. Daemon hiện có backoff và giới hạn tần suất warning; không bỏ kiểm tra upstream. |
| Cạn pool PostgreSQL | 1.275 dòng có `QueuePool limit`, gồm cả thông báo và traceback; lần cuối 23/10 12:15:22 | Chưa thấy lặp lại sau mốc này trong log. Startup ngày 30/10 xác nhận pool size=10, overflow=10. Không tăng pool thêm chỉ để che tình trạng quá tải cũ. |
| Suppress/refresh alert bị timeout | `Error suppressing alerts` xuất hiện lần cuối 24/10 10:53:56 | Có lỗi vận hành cũ; chưa đủ bằng chứng kết luận lỗi còn tái hiện trên mã hiện tại. |
| Race TLS/asyncpg | `InvalidStateError` lần cuối 21/10 11:41:45; `unexpected connection_lost` lần cuối 21/10 16:05:04 | Startup 30/10 xác nhận asyncpg 0.31.0 và compatibility fix đã bật. |
| Thiếu WebSocket library | 4.143 warning, lần cuối 06/10 23:20:36 | Không xuất hiện lại ở phần log mới. Repo hiện pin `websockets`, và server chọn backend WebSocket rõ ràng. |
| Reference GNSS cũ/không được phép tự reacquire | 46.180 dòng `Stale reference after reject`, 23.140 dòng `Reacquire REFUSED`; lần cuối 06/10 | Đây là bảo vệ origin/chuyển dịch, không được sửa bằng cách tự nhận origin mới hoặc bỏ quality gate. Các thông báo này không xuất hiện ở đoạn cuối của bản log. |
| Caster từ chối SET hoặc trả rỗng | 574 thông báo; lần cuối 28/10 12:22:55 | Lỗi kênh điều khiển thiết bị cần phân biệt với kết nối MQTT. TCP hoặc Caster echo không chứng minh receiver đã nhận lệnh. |
| Không nhận ACK lệnh receiver | 3.440 thông báo; lần cuối 29/10 00:13:01, gồm `config undulation`, `saveconfig`, `unlogall` | Giữ nguyên yêu cầu ACK từ receiver. Bổ sung station/caster/mountpoint/lần thử vào log để truy ra đúng thiết bị. |
| Khôi phục ROVER không được xác minh | 26 CRITICAL; lần cuối 25/10 20:05:58; liên quan Dap1_1–Dap1_4 | Cần xác minh chế độ và correction source thực tế trước khi chạy bình sai tiếp. Bản log không đủ chứng minh khôi phục đã hoàn tất. Không phát lệnh thay đổi thiết bị trong đợt phân tích này. |
| HTTP request không hợp lệ | 1.365 warning toàn kỳ, 3 warning ngày 30/10; lần cuối 18:04:17 | Uvicorn đã từ chối request không hợp lệ. Chưa có bằng chứng đây là lỗi nghiệp vụ; không tắt warning toàn cục. |
| Mật khẩu MQTT cũ | Startup ngày 30/10 cảnh báo credential từng có trong source history | Cần đổi đồng bộ broker và các client/thiết bị. Không đổi một phía vì sẽ làm mất kết nối. Không đưa credential vào báo cáo. |

Ngày 30/10 có một ERROR và sáu WARNING trong toàn bản log. ERROR duy nhất là
MQTT lúc 16:22, trước mốc kết nối lại thành công. Điều này không làm mất ý nghĩa
của các lỗi receiver/khôi phục ROVER ở những ngày trước.

## Thay đổi mã nguồn sau phân tích

1. Thay `FileHandler` không giới hạn bằng `RotatingFileHandler`: file hoạt động
   khoảng 10 MiB, giữ năm bản `.1`–`.5`. Khi cấu hình logging lại, đóng handler
   cũ để tránh giữ handle file trên Windows.
2. Bảo toàn log cũ: nếu file hiện tại đã lớn, bản ghi kế tiếp chuyển toàn bộ file
   đó sang `.1`, không cắt mất nội dung. Vì vậy bản archive cũ có thể lớn hơn
   10 MiB cho đến khi hết vòng lưu giữ; các file mới được xoay theo giới hạn.
3. Chỉ đọc tối đa 2 KiB body lỗi CORS, bỏ HTML proxy khỏi thông báo lỗi và gom
   thông báo thành một dòng tối đa 500 ký tự. Vẫn giữ mã HTTP, endpoint và chi tiết
   validation dạng JSON/text. Đóng HTTP response sau khi đọc.
4. Log timeout lệnh receiver có station code, host/port thực sự dùng, mountpoint,
   command và số lần thử. Không thay đổi ACK, retry, điều kiện restore hoặc
   quality gate của GNSS.

Không xóa file Desktop, không sửa dữ liệu/origin GNSS, không phát lệnh tới
receiver và không coi việc giảm log là bằng chứng thiết bị đã hồi phục.

## Kiểm chứng và áp dụng

- 69 kiểm thử và hai subtest đạt cho NTRIP/round-robin, MQTT lifecycle, logging
  và CORS HTTP ở lần kiểm tra chính.
- Sau khi bổ sung bảo toàn chi tiết validation CORS, sáu kiểm thử logging/CORS
  đạt, gồm rollover, giới hạn archive, UTF-8, đóng handler cũ, redaction và
  giữ nguyên nội dung log lịch sử.
- Gate `test_cors_failover_daemon.py` chưa chạy được trong venv kiểm thử hiện tại
  do thiếu module `jwt`; không tính gate này là đạt. Daemon không bị thay đổi.
- Các thay đổi logging chưa được triển khai lên Windows server. Cần cập nhật
  mã nguồn và khởi động lại backend để áp dụng handler mới.
- Đối chiếu receiver bằng telemetry/ACK thực tế trước chu kỳ bình sai tiếp theo;
  không dùng các bản ghi lịch sử hoặc kết nối TCP để xác nhận chế độ ROVER.
