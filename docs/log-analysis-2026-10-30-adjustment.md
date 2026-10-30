# Lỗi bình sai trong bản log Downloads ngày 30/10/2026

## Nguồn bằng chứng

Đã đọc toàn bộ `~/Downloads/landslide_system.log`, giữ nguyên file gốc.
Đây là bản mới hơn bản Desktop được phân tích trước đó.

- Dung lượng: 110.856.727 byte, 596.723 dòng khi đọc bằng Python universal newlines.
- Khoảng thời gian: 03/10/2026 01:49:49,151–30/10/2026 22:50:40,941.
- SHA-256: `d0135b82aed3c11126fcdbd1031974482c733ed51090422d0063b11063ed3fe2`.
- Riêng ngày 30/10: 1.599 INFO, 52 WARNING, 15 ERROR, không có CRITICAL.
  Traceback nhiều dòng không được tính thành bản ghi mới.

## CP03/CP08: SOURCE bị chuyển sang caster không có rover

Chuỗi sự kiện của project `-4001`, Cụm 1:

1. 20:00:31: khóa BASE QN.CamPha tại `aitogy.click:2101/QN.CP`.
   Phiên AICaster của CP08 và CP03 đều được tìm thấy trên `.click`.
2. 20:00:33,039: WEB CORS báo đã gửi/lưu cấu hình tắt S2 của BASE cố định.
3. 20:00:33,086: SOURCE tại `.click/QN.CP` bị từ chối với
   `ERROR - Mountpoint already in using`.
4. 20:00:33,336: MQTT transport tự chuyển SOURCE sang `.com.vn/QN.CP`
   rồi trả thành công. Không có bước chuyển phiên NTRIP của rover sang caster đó.
5. 20:00:36,558: log xác nhận đã gửi RTCM, nhưng diagnostics ghi đích `.com.vn`,
   trong khi tiến trình vẫn mô tả route `.click` là đã hoạt động.
6. 20:00:37–20:04:48: CP03 vẫn có vector khớp BASE cố định; sai số so với
   BASE tạm khoảng 126 m. Không có mẫu cạnh chéo hợp lệ.
7. Khi CP03 làm BASE tạm, lỗi lặp lại. AGRICA của CP08 vẫn báo tọa độ BASE
   cố định, cách BASE tạm CP03 khoảng 273,18 m.
8. 20:11:13: cả hai lượt không tạo được cạnh chéo; mạng `CP03 | CP08`
   rời rạc nên chu kỳ thất bại. Log có ACK khôi phục ROVER cho cả hai trạm.

Lỗi mã nguồn đã xác nhận: `_start_round_robin_ntrip_route` coi SOURCE thành công
ở caster khác là thành công cho route được chọn. Điều này còn nuốt lỗi
mountpoint bận, khiến cơ chế chờ nhả mountpoint trong receiver không được chạy.

Thông báo configure-service thành công chưa chứng minh socket SOURCE cũ đã
đóng. Log không đủ xác định vì sao mountpoint chưa được nhả: độ trễ áp dụng,
cấu hình thiết bị hoặc nguồn phát khác. Không coi việc bỏ fallback là bằng
chứng đã giải quyết được nguyên nhân giữ mountpoint ngoài server.

Đối chiếu mã nguồn CORS tại `cors_dashboard/backend/app/device_command_routes.py`
và `command_dispatcher.py`: endpoint lưu cấu hình, gửi `DEPLOY_SERVICE_CONFIG`
qua MQTT hoặc WebSocket, rồi trả `service_config_sent_and_saved`. Dispatcher
không chờ ACK áp dụng cấu hình từ thiết bị. Do đó dòng `hard-disabled` trong
Monitoring khẳng định quá sớm; bản sửa đổi log thành đã gửi yêu cầu và đang
chờ nhả mountpoint. Không sửa hoặc triển khai repo CORS trong đợt này.

### Đối chiếu app.log của CORS và telemetry trực tiếp

Đã đọc toàn bộ `~/Desktop/app.log`: 16.334.481 byte, 143.827 dòng,
từ 30/10/2026 00:25:38,817 đến 23:13:00,277. SHA-256:
`074da15df96dbc2f9feeca07826d77b04091d718fe145f3cf026101305b2b832`.

Log CORS có đủ tám request configure-service cho serial
`1000000098400b4b` tại 20:00:32,961; 20:02:37,306; 20:03:11,915;
20:05:15,306; 20:05:55,056; 20:08:00,634; 20:08:35,837;
20:10:40,400. Tất cả trả HTTP 200 và ghi đã lưu service config.

Ở lượt đầu, CORS trả 200 lúc 20:00:33,039; SOURCE trên `.click` đã bị từ
chối lúc 20:00:33,086, chỉ 47 ms sau đó. Transport chuyển sang `.com.vn`
ngay thay vì chờ thiết bị áp dụng lệnh và đóng SOURCE cũ. Vì vậy log không
chứng minh lệnh tắt bị mất; lỗi nhảy caster xảy ra trước khi workflow có thể
kiểm chứng việc tắt. Cơ chế retry đúng caster là cần thiết cho đường điều
khiển bất đồng bộ này.

Trong cửa sổ bình sai, CORS vẫn nhận các request wake QN.CP trên `.click`.
Các dòng `Joined existing pool` chỉ xác nhận phiên wake/lease, không xác
nhận đã phát lệnh bật lại. Không dùng chúng làm bằng chứng wake đã ghi đè
lệnh tắt. Hai lần có activation rõ ràng lúc 20:08:04 và 20:10:44 nằm sau
request khôi phục BASE cố định của Monitoring.

Đã đọc trạng thái hiện tại qua API và luồng WebSocket UI, không gửi lệnh
điều khiển thiết bị:

- QN.CamPha online, agent V2.3.5; server V2.3.6.
- Lỗi sync nhận trực tiếp chỉ nêu chênh lệch phiên bản. Vì vậy cảnh báo
  `Config pending sync` trong ảnh không chứng minh S2 chưa nhận lệnh tắt.
- MQTT và WebSocket của agent đều kết nối; MQTT báo lần kết nối từ
  17:42:46, không có lần mất kết nối được ghi trong telemetry phiên hiện tại.
- Kết quả lệnh gần nhất: `SET_RTCM_STREAM_ACTIVE`, nguồn MQTT, thành công
  lúc 20:10:44. Điều này xác nhận agent nhận được ít nhất lệnh wake cuối
  chu kỳ, không chứng minh toàn bộ lệnh DEPLOY trước đó đã được áp dụng.
- Cấu hình mong muốn và cấu hình agent đang báo đều bật S1/S2, phù hợp với
  trạng thái khôi phục cuối chu kỳ. Không dùng trạng thái hiện tại để suy
  ngược trạng thái S2 lúc 20:00.

Không tìm thấy ACK riêng của tám lệnh DEPLOY trong bản app.log này. Không
kết luận MQTT hỏng, agent bỏ lệnh hay nguồn nào giữ mountpoint chỉ từ các
request HTTP 200. Chưa thay đổi code hoặc cấu hình production của CORS.

## Thay đổi

- Chỉ mở SOURCE trên host/port/mountpoint mà workflow đã chọn.
- Giữ nguyên lỗi từ caster sau khi dọn pusher lỗi. Receiver nhận được lỗi bận
  và dùng cơ chế sẵn có: tối đa 15 lần mở route, nghỉ 1 giây giữa các lần.
- Chỉ gửi SET BASE sau khi SOURCE đúng caster được chấp nhận. Nếu không mở
  được route, workflow khôi phục BASE cố định và bỏ lượt khi receiver còn ROVER.
- Giữ kiểm tra AGRICA và chất lượng cạnh. Một handshake hoặc việc gửi RTCM
  thành công vẫn chưa đủ chứng minh rover đã nhận đúng BASE tạm.

## Đập 1/Đập 4: thiếu rover online

Lúc 20:00:00, kiểm tra đầu vào chỉ thấy:

- Đập 4: `Dap4_1` online, `Dap4_2` offline.
- Đập 1: `Dap1_3` online; `Dap1_4`, `Dap1_1`, `Dap1_2` offline.

Hai cụm bị chặn trước khi bình sai vì mỗi cụm chỉ có một rover online.
Trạng thái này không đủ kết luận thiết bị mất điện hay hỏng: cần kiểm tra
telemetry, MQTT và phiên AICaster thực tế. Code hiện đã xét cả thời gian dữ
liệu DB/buffer và payload MQTT mới nhận. Không hạ điều kiện đủ hai rover.

Các timeout `config undulation` và `saveconfig` trong chu kỳ CP03/CP08 sau đó
có ACK ở lần thử tiếp theo; chúng làm chậm khôi phục, không giải thích việc
RTCM được đẩy sang nhầm caster. Hai lỗi CORS 502 lúc 17:29 và 22:47 cũng có
log kết nối hồi phục; không trùng thời điểm lỗi SOURCE trong chu kỳ 20:00.

## Kiểm chứng và giới hạn

- Trước sửa: regression test tái hiện việc nuốt lỗi mountpoint bận và lỗi
  kết nối khi caster dự phòng chấp nhận SOURCE.
- Sau sửa: 119 kiểm thử và 6 subtest đạt cho MQTT lifecycle/route,
  NTRIP/round-robin, session lifecycle, GNSS adjustment flow, logging và CORS HTTP.
- Test tích hợp callback receiver → MQTT transport xác nhận hai lần SOURCE
  bận, lần thứ ba được chấp nhận trên cùng caster, rồi mới được gửi SET BASE.
- Test thành công vẫn truyền đủ danh sách mountpoint trên caster được chọn.
- Gate bổ sung `test_adjustment_failure_artifacts.py` chưa chạy được trong
  venv hiện tại vì thiếu `openpyxl`; không tính gate này là đạt.
- Chưa triển khai lên Windows server hoặc chạy một chu kỳ trên thiết bị thật.
  Sau triển khai cần thấy SOURCE được chấp nhận trên `.click/QN.CP`, AGRICA
  xác nhận BASE tạm và đủ mẫu cạnh chéo. Nếu vẫn bận hết thời gian chờ, cần
  kiểm tra nguồn đang giữ mountpoint và việc thiết bị áp dụng cấu hình tắt S2.
