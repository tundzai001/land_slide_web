# Vận hành và tích hợp Landslide Monitor

## Phạm vi và kiến trúc

Thiết bị hiện tại tiếp tục gửi dữ liệu lên MQTT. Không cần nhập địa chỉ Modbus/OPC UA cho các thiết bị này. Bridge công nghiệp là chương trình tùy chọn chạy tại gateway hiện trường: đọc Modbus RTU/TCP hoặc OPC UA, ánh xạ số liệu, rồi publish vào đúng MQTT topic đã cấu hình trong hệ thống. Backend dùng chung bộ xử lý, lưu dữ liệu, cảnh báo và WebSocket hiện có.

Mở **Quản trị → Vận hành** bằng tài khoản Admin. API tương ứng ở `/api/admin/operations`; tài liệu OpenAPI ở `/docs`. Các thao tác cần `Authorization: Bearer <token>`. Operator/viewer không có quyền quản trị các mục này.

## Đọc tài liệu

Cuối cột trái, chọn **Hướng dẫn tích hợp** để tải PDF này hoặc **Hướng dẫn sử dụng** để tải cẩm nang thao tác web. Thiết bị gửi MQTT tiếp tục dùng cấu hình trạm hiện có.

## Lưu mô hình DEM dự án

Danh mục DEM (tên khu, mã mô hình và thông số lưới) được lưu trong bảng `global_configs` của CONFIG PostgreSQL; nội dung `.asc` lưu ngoài thư mục mã nguồn để tránh làm phình CSDL và không mất khi cập nhật code. Windows mặc định dùng `%PROGRAMDATA%\Aitogy\Landslide\project_dems`; đặt `PROJECT_DEM_DIR` để chuyển sang ổ dữ liệu khác và cấp quyền ghi cho tài khoản chạy backend. Sao lưu thư mục này cùng bản backup PostgreSQL.

`web.config` nâng trần IIS request filtering lên mức tối đa của IIS. Nếu upload trả HTTP 413, tìm dòng `Project DEM upload received` trong log backend cùng thời điểm: có dòng này thì request đã tới ứng dụng; không có thì IIS hoặc proxy chặn trước FastAPI. Khi đó kiểm tra IIS Failed Request Tracing (HTTP 413.1) và cấu hình proxy tại máy chủ, rồi recycle tiến trình sau khi sửa cấu hình.

## Sao lưu nóng

Chạy ứng dụng một worker như cấu hình hiện tại: vòng đời MQTT và các daemon được khởi tạo theo process. Dùng nhiều worker sẽ nhân đôi các daemon này; cần thiết kế leader/lease trước khi scale.

Trước khi bật tính năng này, cập nhật schema bằng `cd backend && alembic upgrade head`. Migration chỉ thêm hai bảng log và một bảng cài đặt trong DATA PostgreSQL; không sửa dữ liệu quan trắc hiện có. Máy chủ cần `pg_dump` và `pg_restore` trong PATH, cùng phiên bản chính với PostgreSQL. Tài khoản backup phải đọc được ba CSDL; restore cần quyền `CREATEDB`.

- **Tạo bản sao lưu** chạy `pg_dump --format=custom` lần lượt cho auth/config/data. PostgreSQL và thu thập MQTT tiếp tục hoạt động; dump vẫn dùng I/O và có thể giữ phiên bản dòng cũ cho tới khi kết thúc.
- Lịch **Hằng ngày/Hằng tuần** bắt đầu tại thời điểm chọn trong giao diện, sau đó mỗi 24 giờ/7 ngày. PostgreSQL khóa lịch để chỉ một worker nhận mỗi kỳ. Nếu một kỳ lỗi, lần thử kế tiếp theo lịch sau; có thể tạo backup thủ công. Giữ mặc định 30 bản tự động (có thể đặt 1–365); retention chỉ xóa bản tự động có chữ ký hợp lệ. Bản thủ công không tự xóa.
- Gói ZIP chứa ba dump PostgreSQL. Hai bảng log và cài đặt nằm trong dump DATA nên không có file SQLite riêng. Manifest kèm SHA-256 và HMAC; đặt `BACKUP_SIGNING_KEY` ngẫu nhiên, riêng biệt và giữ ổn định. HMAC kiểm tra tính toàn vẹn/xuất xứ, **không mã hóa**. Hạn chế ACL thư mục, bật mã hóa ổ đĩa máy chủ và mã hóa bản sao khi chuyển ra ngoài.
- Mặc định Windows: `%PROGRAMDATA%\Aitogy\Landslide\backups`; hệ điều hành khác: `runtime/operations/backups`. Đặt `BACKUP_DIR=backups` trong `backend/.env` để lưu tại `backend/backups`; đường dẫn tương đối luôn tính từ thư mục `backend`, không phụ thuộc thư mục chạy lệnh. Có thể dùng đường dẫn tuyệt đối như `BACKUP_DIR=D:/LandslideBackups`. Khởi động lại backend sau khi đổi. Chỉ cấp quyền cho tài khoản dịch vụ, SYSTEM và quản trị viên; thư mục backup không được phục vụ qua HTTP tĩnh. Sao chép bản đã tải ra nơi lưu độc lập theo RPO/RTO của đơn vị.
- Tác vụ PostgreSQL có giới hạn 6 giờ. Chừa dung lượng cho một bản đầy đủ mới; tác vụ lỗi không thay thế bản cũ.
- Ba CSDL được chụp ở ba thời điểm riêng. Đây không phải một giao dịch snapshot xuyên cả ba CSDL.

## Phục hồi và giới hạn

**Phục hồi vào CSDL riêng** kiểm tra chữ ký, checksum và cấu trúc cả ba dump trước khi chạy `pg_restore` vào ba CSDL mới có tên `recovery_<job>_auth/config/data`. Mỗi restore dùng một transaction; giao diện trả về tên CSDL và trạng thái tác vụ. Có thể phục hồi bản sao trên máy chủ hoặc tải lên bản sao đã ký bởi cùng installation. Upload giới hạn 2 GiB; bản sao lớn hơn phải được quản trị viên đặt trong thư mục sao lưu với tên `<32 ký tự hex>.zip`.

Thu thập MQTT vẫn dùng CSDL đang chạy. Tính năng này **không thay thế CSDL đang chạy**, không tự gộp số liệu, và không cung cấp cam kết “không mất mẫu” khi chuyển đổi CSDL. Bản sao phục hồi có thể dùng để kiểm tra hoặc xuất dữ liệu sau sự cố. Chuyển sang CSDL phục hồi cần kế hoạch cutover/replay riêng và thử nghiệm với tải thực tế. Nếu phục hồi lỗi giữa chừng, tên các CSDL đã tạo được giữ trong kết quả để quản trị viên kiểm tra; không xóa tự động.

Giữ `BACKUP_SIGNING_KEY` an toàn ngoài bản sao. Gói phiên bản 1 cũ vẫn được xác minh bằng `SECRET_KEY`; gói mới dùng khóa backup riêng. Thay khóa sẽ làm gói đã ký bằng khóa đó không xác minh được nếu không còn khóa cũ. Chỉ phục hồi gói do hệ thống này tạo; không chấp nhận SQL tùy ý từ upload.

## Nhật ký

`audit_log`, `operation_log` và `operations_settings` được lưu trong DATA PostgreSQL, cùng database backup với dữ liệu đo. Scheduler dọn log và trạng thái job quá hạn mỗi ngày; mặc định giữ 365 ngày, chỉnh bằng `OPERATIONS_LOG_RETENTION_DAYS` (hiệu lực 30–3650 ngày). Theo dõi dung lượng CSDL.

Audit ghi thời gian, tài khoản, vai trò, IP kết nối trực tiếp, phương thức/đường dẫn API, HTTP status và thay đổi ORM đã commit. Che trường chứa password/secret/token/credential/private_key. Thay đổi bản ghi ghi giá trị cũ/mới; bulk UPDATE/DELETE ghi số dòng và tối đa 100 bản ghi mẫu. SQL thô/TRUNCATE ghi thao tác API, không chụp toàn bộ bảng. Đăng nhập thất bại được ghi 401; không lưu mật khẩu. Đăng xuất ghi sự kiện khi trình duyệt gửi được yêu cầu, còn token JWT vẫn hết hạn theo chính sách hiện có.

Nhật ký vận hành ghi trạng thái backup, restore, NTP và vòng đời dịch vụ. Lọc theo loại, tài khoản, khoảng thời gian và phân trang. Đây không phải kho bất biến chống sửa bởi tài khoản CSDL hoặc quản trị hệ điều hành. Ghi audit xảy ra sau request, trong giao dịch riêng với thay đổi nghiệp vụ. Nếu DATA DB không ghi được, ứng dụng phát log CRITICAL; theo dõi cảnh báo DB và dung lượng.

## NTP

Trang Vận hành đọc máy chủ NTP từ `NTP_SERVER` trong môi trường triển khai, gửi phép đo UDP/123 khi Admin bấm kiểm tra, hiển thị offset, thời gian khứ hồi, stratum và thời điểm kiểm tra. Phản hồi phải khớp originate timestamp, server mode và trạng thái đồng bộ hợp lệ.

API chỉ **đo độ lệch**, không đổi đồng hồ OS. Cấu hình dịch vụ thời gian bằng công cụ quản trị hệ điều hành của máy chủ/gateway. Kiểm tra trạng thái đồng bộ thực bằng `chronyc tracking` và `chronyc sources -v` trên Linux. Cần cho phép UDP/123 đến máy chủ NTP được chọn. Không coi một phép đo thành công là bằng chứng OS đã đồng bộ.

## Modbus/OPC UA qua gateway MQTT

1. Giữ cấu hình thiết bị và MQTT topic hiện có trong trang trạm.
2. Nếu cần tích hợp thiết bị Modbus/OPC UA mới, kỹ thuật viên chuẩn bị tệp JSON cho bridge tại gateway. Địa chỉ IP/serial/node ID thuộc mạng hiện trường, không phải kết nối từ backend tới thiết bị.
3. Cấu hình `points`: tên trường, địa chỉ thanh ghi 0-based hoặc OPC UA node ID, kiểu dữ liệu, thứ tự word/byte, scale và offset. Modbus hỗ trợ đọc holding/input registers, uint16/int16/uint32/int32/float32/float64. Bridge chỉ đọc.
4. Nước cần `water_level` theo mét; mưa cần `rainfall_mm`; IMU cần đủ `roll`, `pitch`, `yaw` theo độ. GNSS tiếp tục dùng bộ nhận MQTT/NMEA hiện có.
5. Tệp JSON gồm `version: 1` và danh sách `devices`; mỗi thiết bị có `device_id`, `sensor_type`, `topic`, `profile`. Đặt `enabled: true` trong profile và triển khai tệp lên gateway.
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

## Cấu hình thời gian máy chủ

`NTP_SERVER=pool.ntp.org` được đọc từ `backend/.env` hoặc biến môi trường lúc khởi động. Giao diện hiển thị nguồn này ở chế độ chỉ đọc; sau khi sửa cấu hình cần khởi động lại dịch vụ. Cấu hình `ntp_config` cũ trong PostgreSQL không còn được sử dụng. PostgreSQL chỉ lưu phép đo gần nhất (`ntp_status`) và nhật ký kiểm tra.

Nút “Kiểm tra độ lệch” gửi phép đo NTP tới nguồn đã cấu hình, không thay đổi đồng hồ hệ điều hành. Trên Windows, Windows Time quản lý đồng bộ; kiểm tra bằng `w32tm /query /status` và `w32tm /query /configuration`. Trên Linux, dùng chrony/systemd-timesyncd. Đổi `NTP_SERVER` trong ứng dụng không tự đổi nguồn của dịch vụ thời gian hệ điều hành.

### Môi trường Python riêng trên Windows

Server Landslide dùng môi trường riêng ở `C:\ProgramData\Aitogy\Landslide\venv`, cài từ `backend/requirements.txt`. Không dùng Python packages chung với ứng dụng khác: phiên bản `paho-mqtt` phải là 2.1.0 để hỗ trợ `CallbackAPIVersion.VERSION2`.

Chạy migration bằng `C:\ProgramData\Aitogy\Landslide\venv\Scripts\python.exe -m alembic upgrade head` tại thư mục `backend`. Lệnh khởi động trong `C:\ProgramData\Aitogy\Landslide\run.cmd` dùng đường dẫn Python tuyệt đối; tác vụ `LandslideWebVisible` mở CMD trong phiên desktop Administrator đang đăng nhập. Khi cập nhật dependencies, chạy pip bằng chính Python trong môi trường này.
