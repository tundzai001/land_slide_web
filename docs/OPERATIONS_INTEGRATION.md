# Vận hành và tích hợp Landslide Monitor

## Phạm vi và kiến trúc

Thiết bị hiện tại tiếp tục gửi dữ liệu lên MQTT. Không cần nhập địa chỉ Modbus/OPC UA cho các thiết bị này. Bridge công nghiệp là chương trình tùy chọn chạy tại gateway hiện trường: đọc Modbus RTU/TCP hoặc OPC UA, ánh xạ số liệu, rồi publish vào đúng MQTT topic đã cấu hình trong hệ thống. Backend dùng chung bộ xử lý, lưu dữ liệu, cảnh báo và WebSocket hiện có.

Mở **Quản trị → Vận hành** bằng tài khoản Admin. API tương ứng ở `/api/admin/operations`; tài liệu OpenAPI ở `/docs`. Các thao tác cần `Authorization: Bearer <token>`. Operator/viewer không có quyền quản trị các mục này.

## Sao lưu nóng

Máy chủ phải có `pg_dump` và `pg_restore` trong PATH, tương thích phiên bản PostgreSQL đang chạy. Tài khoản kết nối phải được đọc toàn bộ ba CSDL; phục hồi cần quyền `CREATEDB`.

- **Tạo bản sao lưu** chạy `pg_dump --format=custom` lần lượt cho auth/config/data. PostgreSQL tiếp tục nhận ghi trong lúc dump.
- Lịch **Hằng ngày/Hằng tuần** bắt đầu tại thời điểm chọn trong giao diện, sau đó mỗi 24 giờ/7 ngày. Thời điểm được lưu bằng Unix timestamp. Khi máy chủ ngừng hoạt động, lần quá hạn chạy sau khi khởi động lại. Một lịch lỗi chờ kỳ kế tiếp; có thể thử thủ công.
- Gói ZIP có ba dump PostgreSQL, snapshot SQLite online của nhật ký/cấu hình vận hành, manifest SHA-256 và chữ ký HMAC bằng `SECRET_KEY`. Đây là kiểm tra tính toàn vẹn/xuất xứ, không mã hóa. Bản sao chứa dữ liệu và thông tin xác thực nên chỉ Admin được tải.
- Ba CSDL được chụp ở ba thời điểm riêng. Đây không phải một giao dịch snapshot xuyên cả ba CSDL.
- Thư mục mặc định: `runtime/operations/backups`. Đặt `OPERATIONS_DIR` trên ổ đĩa bền vững, quyền truy cập chỉ cho tài khoản dịch vụ. Giữ bản sao ngoại tuyến theo chính sách lưu trữ của đơn vị.
- Chỉ chạy một tiến trình sở hữu lịch sao lưu trên cùng thư mục operations. Không chạy nhiều scheduler chia sẻ thư mục này. Phải giám sát dung lượng; bản sao không tự xóa.

## Phục hồi và giới hạn

**Phục hồi vào CSDL riêng** thực sự chạy `pg_restore` vào ba CSDL mới có tên `recovery_<job>_auth/config/data`. Giao diện trả về tên CSDL và trạng thái tác vụ. Có thể phục hồi bản sao trên máy chủ hoặc tải lên bản sao đã ký bởi cùng installation. Upload giới hạn 2 GiB; bản sao lớn hơn phải được quản trị viên đặt trong thư mục sao lưu với tên `<32 ký tự hex>.zip`.

Thu thập MQTT vẫn dùng CSDL đang chạy. Tính năng này **không thay thế CSDL đang chạy**, không tự gộp số liệu, và không cung cấp cam kết “không mất mẫu” khi chuyển đổi CSDL. Bản sao phục hồi có thể dùng để kiểm tra hoặc xuất dữ liệu sau sự cố. Chuyển sang CSDL phục hồi cần kế hoạch cutover/replay riêng và thử nghiệm với tải thực tế. Nếu phục hồi lỗi giữa chừng, tên các CSDL đã tạo được giữ trong kết quả để quản trị viên kiểm tra; không xóa tự động.

Giữ `SECRET_KEY` an toàn ngoài bản sao. Sau khi thay khóa, bản sao có chữ ký cũ cần xác minh bằng khóa cũ trên môi trường khôi phục được kiểm soát. Chỉ phục hồi gói do hệ thống này tạo; không chấp nhận SQL tùy ý từ upload.

## Nhật ký

`audit_log` và `operation_log` được lưu trong SQLite WAL ở `OPERATIONS_DIR/journal.sqlite3`, độc lập với PostgreSQL quan trắc. Không cần migration CSDL đang chạy. Gói sao lưu có snapshot nhật ký bằng SQLite online backup. Khi phục hồi, bản nhật ký được đặt riêng tại `backups/recovery_<job>_journal.sqlite3`, không thay thế nhật ký đang hoạt động.

Audit ghi thời gian, tài khoản, vai trò, IP kết nối trực tiếp, phương thức/đường dẫn API, HTTP status và thay đổi ORM đã commit. Che trường chứa password/secret/token/credential/private_key. Thay đổi bản ghi ghi giá trị cũ/mới; bulk UPDATE/DELETE ghi số dòng và tối đa 100 bản ghi mẫu. SQL thô/TRUNCATE ghi thao tác API, không chụp toàn bộ bảng. Đăng nhập thất bại được ghi 401; không lưu mật khẩu. Đăng xuất ghi sự kiện khi trình duyệt gửi được yêu cầu, còn token JWT vẫn hết hạn theo chính sách hiện có.

Nhật ký vận hành ghi trạng thái backup, restore, NTP và vòng đời dịch vụ. Lọc theo loại, tài khoản, khoảng thời gian và phân trang. Journal không phải kho bất biến chống sửa bởi quản trị viên hệ điều hành. Nếu journal không ghi được, ứng dụng phát log CRITICAL; theo dõi ổ đĩa và log dịch vụ. Thao tác DB và nhật ký thuộc hai CSDL, không có giao dịch nguyên tử chung.

## NTP

Trang Vận hành lưu máy chủ NTP, gửi phép đo UDP/123 khi Admin bấm kiểm tra, hiển thị offset, thời gian khứ hồi, stratum và thời điểm kiểm tra. Phản hồi phải khớp originate timestamp, server mode và trạng thái đồng bộ hợp lệ.

API chỉ **đo độ lệch**, không đổi đồng hồ OS. Tải cấu hình chrony và áp dụng bằng công cụ quản trị hệ điều hành của máy chủ/gateway. Kiểm tra trạng thái đồng bộ thực bằng `chronyc tracking` và `chronyc sources -v` trên Linux. Cần cho phép UDP/123 đến máy chủ NTP được chọn. Không coi một phép đo thành công là bằng chứng OS đã đồng bộ.

## Modbus/OPC UA qua gateway MQTT

1. Giữ cấu hình thiết bị và MQTT topic hiện có trong trang trạm.
2. Chọn thiết bị ở trang Vận hành, chọn giao thức tại hiện trường. Địa chỉ IP/serial/node ID ở đây thuộc gateway, không phải kết nối từ backend tới thiết bị.
3. Cấu hình `points`: tên trường, địa chỉ thanh ghi 0-based hoặc OPC UA node ID, kiểu dữ liệu, thứ tự word/byte, scale và offset. Modbus hỗ trợ đọc holding/input registers, uint16/int16/uint32/int32/float32/float64. Bridge chỉ đọc.
4. Nước cần `water_level` theo mét; mưa cần `rainfall_mm`; IMU cần đủ `roll`, `pitch`, `yaw` theo độ. GNSS tiếp tục dùng bộ nhận MQTT/NMEA hiện có.
5. Đặt `enabled: true`, lưu và tải JSON của thiết bị. Việc lưu không tự triển khai lên gateway.
6. Trên gateway, cài `python -m pip install -r field_unit/requirements-industrial.txt`, đặt `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_CLIENT_ID` riêng cho gateway. Khi dùng TLS, đặt `MQTT_TLS_CA` tới CA tin cậy.
7. Chạy `python field_unit/industrial_bridge.py --config gateway-device-7.json`. Dùng trình quản lý dịch vụ của gateway để tự khởi động lại.

Ví dụ profile Modbus TCP cho mực nước (hai thanh ghi float32):

```json
{"protocol":"modbus_tcp","enabled":true,"host":"192.168.10.20","port":502,"unit_id":1,"poll_seconds":5,"points":[{"field":"water_level","address":0,"data_type":"float32","register_type":"holding","word_order":"big","byte_order":"big","scale":1,"offset":0}]}
```

Với OPC UA, dùng endpoint `opc.tcp://...`, `node_id` cho từng trường, và cấu hình `security` theo định dạng của asyncua, ví dụ `Basic256Sha256,SignAndEncrypt,/etc/gateway/client.der,/etc/gateway/client-key.pem,/etc/gateway/server.der`. Chứng chỉ và private key nằm tại gateway; đặt tài khoản trong `OPCUA_USERNAME` / `OPCUA_PASSWORD`. Chỉ môi trường thử nghiệm cô lập được đặt `OPCUA_ALLOW_INSECURE=1`.

Bridge publish JSON bằng MQTT QoS 1, `retain=false`. Khi broker ngắt kết nối, bridge báo lỗi và tạm dừng lấy mẫu đến khi kết nối lại; không có hàng đợi bền vững tại bridge. Đây không phải cam kết thu liên tục khi mạng hiện trường bị đứt. Bộ `ingest_spool` sẵn có ở backend tiếp tục xử lý lỗi ghi CSDL như trước.

## CSV và Excel

Hộp **Xuất dữ liệu** có **CSV** hoặc **CSV + Excel**, giữ bộ lọc dự án/trạm/loại cảm biến/thời gian. Gói ZIP gồm các dataset; lựa chọn CSV + Excel thêm workbook cho từng CSV. Khi đủ 1.048.576 dòng, workbook chuyển sang sheet tiếp theo và lặp header. Chuỗi được ghi dưới dạng văn bản, không thực thi công thức. Trường dài hơn 32.767 ký tự không thể đưa đầy đủ vào Excel: tác vụ báo lỗi và yêu cầu chọn CSV.

API hiện có `/api/admin/db/export-excel/start` thêm trường `format: "csv" | "both"`; tên route được giữ để tương thích. Báo cáo chuyên ngành PDF/Excel hiện có vẫn nằm trong gói nếu chọn dataset tương ứng.

## Chấp thuận chuyển tiếp dữ liệu

Chuyển tiếp RTK mặc định tắt. Cấu hình bật cũ chưa được chấp thuận cũng bị chặn tại điểm publish. Admin nhập số văn bản/nội dung chấp thuận của Chủ đầu tư khi bật hoặc sửa đích/cấu hình chuyển tiếp. Backend ký cấu hình kèm station ID; thay topic, broker, trường dữ liệu hoặc thông số khác sẽ yêu cầu chấp thuận lại. Bản ký không thay thế giá trị pháp lý của văn bản; đơn vị vận hành phải lưu bản văn bản gốc.

## Nguồn tham khảo giao thức

- PostgreSQL pg_dump: https://www.postgresql.org/docs/current/app-pgdump.html
- PostgreSQL pg_restore: https://www.postgresql.org/docs/current/app-pgrestore.html
- PyModbus 3.11.3 client: https://pymodbus.readthedocs.io/en/v3.11.3/source/client.html
- asyncua client: https://opcua-asyncio.readthedocs.io/en/latest/api/asyncua.client.html
