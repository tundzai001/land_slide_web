# Khôi phục rover phát RTCM ngoài phiên bình sai

MQTT Bridge có kiểm tra nền mỗi 5 giây. Chỉ các thiết bị GNSS nằm trong
danh sách rover/stations của cụm dự án mới thuộc phạm vi khôi phục. Không
subscribe topic mới và không thay đổi trạm BASE cố định của CORS.

## Điều kiện và hành động

- Dùng bộ lọc RTCM3 hiện có để ghép fragment và kiểm tra CRC-24Q trên bytes
  MQTT gốc. Byte `0xD3` rời rạc hoặc frame CRC sai không kích hoạt khôi phục.
- Phải có thêm frame hợp lệ qua hai lần kiểm tra liên tiếp; một frame cuối
  của lượt bình sai cũ không đủ kích hoạt.
- Nếu trạm không thuộc phiên bình sai đang hoạt động, tìm phiên điều khiển
  AICaster rồi dùng profile ROVER và cơ chế xác nhận lệnh hiện có.
- Chỉ ghi khôi phục thành công khi chuỗi lệnh được xác nhận, có GGA và AGRICA
  mới sau khi bắt đầu khôi phục, và không còn RTCM trong ít nhất 3 giây nếu
  RTCM còn đến trong lúc gửi lệnh.
- Mỗi trạm nghỉ ít nhất 60 giây sau lần thử hoàn tất, kể cả khi không tìm thấy
  phiên điều khiển hoặc khôi phục thất bại. Không có ACK/live output thì ghi
  lỗi chưa xác minh, không báo thành công.

## Bảo vệ phiên bình sai

Không dựa vào giờ chạy lịch. Phiên chạy tay qua ứng dụng và phiên scheduler
đều được bảo vệ theo roster của session, gồm startup/preflight, thu baseline,
round-robin và tạm dừng. Task vẫn đang cleanup hoặc topology CORS chưa khôi
phục xong cũng được bảo vệ. Phiên đã kết thúc không giữ quyền trên rover mãi.

Startup chờ lần khôi phục nền đang chạy hoàn tất, rồi giữ roster trước await
đầu tiên của preflight. Reservation cũng áp dụng khi chạy lại sau ERROR và
khi roster được dựng lại sau bước loại trạm không điều khiển được. Vì vậy
kiểm tra nền không gửi ROVER chồng lên thao tác SET BASE của một phiên mới.
Khóa được nhả sau từng trạm để một yêu cầu bắt đầu bình sai đang chờ có thể
tiếp tục trước khi kiểm tra nền xử lý trạm kế tiếp.

Đây là phát hiện RTCM phát nhầm ngoài phiên, không phải bộ lập lịch bình sai.
Trạm chỉ gửi GGA nhưng thiếu AGRICA không tự bị gửi lại cấu hình bởi kiểm tra
nền này; preflight lúc bắt đầu bình sai vẫn xử lý trường hợp đó như trước.
Origin, quality gate, dữ liệu chuyển dịch và thông số BASE cố định được giữ
nguyên. Thao tác bình sai ở công cụ bên ngoài không tạo session trong ứng dụng
không thể được nhận diện như một phiên đang được ứng dụng quản lý.

## Vòng đời và kiểm thử

Task khởi chạy cùng MQTT Bridge, hoạt động độc lập với việc broker mặc định
có kết nối hay không, và được hủy/await cùng các task khác khi bridge dừng.

Các kiểm thử hồi quy dùng frame RTCM có CRC thực và phiên điều khiển giả lập:
ghép fragment, từ chối CRC sai, frame đơn cũ, khôi phục một lần cho topic trùng,
cooldown/retry, thiếu phiên điều khiển, phiên tay/lịch/tạm dừng/startup retry,
cleanup, topology chưa trả lại, phiên không liên quan, và cạnh tranh giữa
startup với khôi phục nền. Kiểm tra chuỗi restore không coi ACK đơn thuần là
đủ nếu thiếu GGA/AGRICA mới.

Lần kiểm tra kết hợp cuối cùng: 197 test và 27 subtest đạt, gồm kiểm tra nền,
trạng thái MQTT Online, truy vấn dữ liệu, preflight, scheduler, vòng đời
round-robin, failure artifacts và kiểm định GNSS.

Chưa triển khai hoặc phát lệnh khôi phục tới receiver thật trong đợt này.
Sau cập nhật code và khởi động lại backend, kiểm tra nền sẽ tự hoạt động.
