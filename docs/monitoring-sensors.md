# Quan trắc đa cảm biến

Phạm vi: giữ mô hình trạm hiện tại, mỗi trạm tối đa một thiết bị cho mỗi loại. Không tự tạo điểm đo hoặc cấu hình thiết bị vật lý. Danh mục dựa trên HSYC Gói quan trắc, mục 7.1, 7.3 và phụ lục thiết bị/phần mềm (trang 43–44, 51). Trạm chỉ có cảm biến mới cần nhập tọa độ để hiển thị trên bản đồ.

Danh mục dùng chung nằm tại `backend/app/shared/sensor_catalog.json`. Build frontend nhúng danh mục vào shared bundle; backend đọc cùng tệp. Không đổi schema cơ sở dữ liệu hoặc MQTT topic hiện hữu. Build bằng `npm run build:frontend` sau khi đổi danh mục.

## Hợp đồng MQTT

Gateway gửi JSON với số hữu hạn đã hiệu chuẩn theo đơn vị sau. `unit` có thể bỏ qua khi gateway bảo đảm đơn vị chuẩn; nếu cung cấp sai đơn vị, mẫu bị từ chối. Không tự diễn giải số đếm dây rung, điện áp, hệ số hiệu chuẩn hoặc thanh ghi Modbus.

| Loại | Trường JSON | Đơn vị |
| --- | --- | --- |
| `piezometer` | `pressure` | kPa |
| `jointmeter` | `displacement` | mm |
| `pendulum` | `x`, `y` | mm |
| `tiltmeter` | `x`, `y`, `z` | ° |
| `seepage` | `flow` | L/s |
| `accelerometer` | `x`, `y`, `z` | m/s² |
| `stress` | `stress` | kPa |
| `temperature` | `temperature` | °C |
| `strain` | `strain` | µε |
| `extensometer` | `points`: đối tượng tên điểm → chuyển vị | mm |

Ví dụ: `{"pressure":123.4,"unit":"kPa"}` hoặc `{"points":{"A1":0.12,"A2":-0.08},"unit":"mm"}`. Giãn kế nhận 1–64 điểm, tên điểm dài tối đa 80 ký tự. Cảm biến nhiều trục phải có đủ trục. Mẫu thiếu dữ liệu, NaN, Infinity, boolean và chuỗi số bị từ chối, không thay thành 0. Tên trường và trục là hợp đồng tích hợp phần mềm, cần ánh xạ theo tài liệu thiết bị thực tế.

## Luồng dữ liệu

Cấu hình nhiều loại tại bước Kết nối & định vị, nhập MQTT topic/broker và tọa độ riêng. Backend nhận dữ liệu, cập nhật cache, lưu lịch sử theo chu kỳ mặc định hệ thống, phát realtime. Loại mới mặc định mất kết nối sau 300 giây không có mẫu hợp lệ trong cache. Thẻ hiển thị rõ dữ liệu cuối khi mất kết nối. Biểu đồ dùng đơn vị riêng, hỗ trợ nhiều trục/điểm; Data Explorer và chức năng xuất dữ liệu hỗ trợ các loại mới. Giãn kế giữ toàn bộ điểm trong JSON; cột chỉ mục số lưu tối đa năm điểm đầu.

Ngưỡng và thuật toán cảnh báo của các cảm biến mới chưa được triển khai. Không dùng ngưỡng sạt lở/IMU thay cho tiêu chí an toàn đập. Cần yêu cầu kỹ thuật, quy trình vận hành, hệ số hiệu chuẩn và mẫu giao thức của từng thiết bị để tích hợp phần cứng, cấu hình cảnh báo và nghiệm thu. Thay đổi này không xác nhận đáp ứng toàn bộ HSYC (Modbus/OPC UA, lưu trữ 10 năm, khôi phục, bản quyền và nghiệm thu thực địa).

## Kiểm tra

- `PYTHONPATH=backend python3 -m unittest backend.tests.test_monitoring_sensors backend.tests.test_xlsx_sensor_writers`
- `npx playwright test tests/ui/monitoring-sensors.spec.js --project=chromium --workers=1`
- `npm run build:frontend`

Các kiểm tra dùng dữ liệu tổng hợp và trình duyệt local, không kết nối thiết bị hoặc cơ sở dữ liệu production.

## Hiển thị và lưu theo từng cảm biến

Gateway gửi giá trị đã quy đổi. Web giữ nguyên độ chính xác trong JSON; số chữ số trên thẻ chỉ phục vụ đọc nhanh, không thể hiện độ chính xác thiết bị. Không tự tính áp lực → cột nước, biến dạng → ứng suất, góc → chuyển vị hoặc cao độ nước → lưu lượng khi thiếu mô hình và thông số thực tế.

| Cảm biến | Hiển thị / biểu đồ | Dữ liệu cần giữ và quy ước |
| --- | --- | --- |
| GNSS | Vị trí, chuyển vị, vận tốc và chất lượng nghiệm trong bảng GNSS hiện có | Tọa độ, hệ quy chiếu, mốc gốc, các thành phần chuyển vị/vận tốc, fix và chất lượng. Giữ pipeline cũ; vị trí ENU và chuyển vị phải phân biệt đơn vị cm/mm theo trường hiện có. |
| Mưa | Cường độ mm/h; số tích lũy trong dữ liệu và xuất hiện có | Cường độ, tích lũy mm, thời gian và quy tắc reset. Không cộng số tích lũy của các bản tin. |
| Mực nước | Mực nước m theo thời gian | Giá trị và mốc cao độ/quy ước đo. Khoảng cách đến mặt nước không tự gọi là cao độ. |
| IMU | Roll, pitch, yaw theo baseline hiện có | Góc tương đối, baseline, gia tốc và pin nếu có. Không dùng IMU thay cho giãn kế/đo nghiêng chuyên dụng. |
| Áp lực thấm | Áp lực kPa; nhiệt độ °C khi gửi | `pressure`, `temperature`; vị trí, mã hiệu chuẩn, mốc tham chiếu. Phân biệt áp lực tương đối/tuyệt đối trong tài liệu thiết bị. |
| Khe co giãn | Độ mở khe mm có dấu | `displacement`, nhiệt độ; mốc ban đầu và chiều dương. Không tự lấy mẫu đầu làm zero. |
| Đo dọi | Chuyển vị X/Y mm, biểu đồ từng trục | `x`, `y`; hệ trục, mốc đọc, vị trí và loại lắp đặt trong hồ sơ thiết bị. |
| Đo nghiêng | Góc X/Y/Z °, biểu đồ từng trục | `x`, `y`, `z`, nhiệt độ; hướng lắp và mốc. Không suy ra chuyển vị khi thiếu hình học. |
| Lưu lượng thấm | L/s; cột nước m khi gửi | `flow`, `head`, nhiệt độ; gateway chịu trách nhiệm đường quy đổi theo máng/đập tràn thực tế. |
| Gia tốc/rung chấn | Giá trị tức thời X/Y/Z m/s² và dạng sóng từng trục theo ms; số mẫu, Hz, thời điểm bắt đầu, đỉnh trị tuyệt đối | Ba giá trị tức thời; từng gói dạng sóng đủ 3 trục, tần số, thời điểm bắt đầu, sự kiện và thứ tự gói. Đỉnh trên UI chỉ tính cho gói đang xem. Không suy ra PGA toàn sự kiện từ một gói. |
| Ứng suất | kPa theo thời gian; nhiệt độ nếu có | `stress`, nhiệt độ; vị trí, phương đo và hiệu chuẩn. Không tự suy từ strain. |
| Nhiệt độ | °C theo thời gian | `temperature`, vị trí và hiệu chuẩn. Không đổi số thiếu thành 0. |
| Biến dạng | µε có dấu; nhiệt độ nếu có | `strain`, nhiệt độ; mốc, hướng đo, mã hiệu chuẩn. Hồ sơ gateway cần nói rõ đã bù nhiệt hay chưa. |
| Giãn kế đa điểm | mm từng điểm neo, mỗi điểm một đường riêng | `points` giữ toàn bộ tên/giá trị; mốc, thứ tự/độ sâu điểm neo trong hồ sơ thiết bị, nhiệt độ nếu có. Không lấy trung bình các điểm thay số đo. |

Các thẻ cảm biến mới có nhãn đại lượng và đơn vị riêng. Kết nối chỉ nói “Đang nhận dữ liệu”; chất lượng hiển thị riêng, không suy ra an toàn công trình. `invalid` vẫn giữ bản ghi để truy vết nhưng UI hiện “—” và biểu đồ để trống tại mẫu đó. `suspect` vẫn hiển thị với nhãn cần kiểm tra. Thiếu `quality` là chưa xác định.

### Trường bổ sung trong MQTT cho 10 loại mới

- `measured_at`: UNIX seconds UTC, có thể có phần thập phân; thời điểm đo tại gateway.
- `received_at`: do server thêm khi nhận. Timestamp chỉ mục DB và bộ lọc lịch sử vẫn dùng thời điểm nhận để tương thích hệ thống cũ. Biểu đồ mới ưu tiên thời điểm đo nếu có.
- `quality`: `valid`, `suspect`, `invalid`, `unknown`. Chất lượng do gateway quyết định; không phải phân loại nguy hiểm.
- `model`, `serial_number`, `calibration_id`, `reference_id`, `location_label`, `axis_convention`, `event_id`: chuỗi không rỗng, tối đa 160 ký tự; chỉ lưu khi gateway cung cấp. Thẻ hiện vị trí, hệ trục, mốc, serial, mã hiệu chuẩn và sự kiện.
- `sequence`: số nguyên không âm, thứ tự bản tin/gói để truy vết; hiện chưa tự phát hiện thiếu gói hoặc lắp ráp sự kiện.
- `temperature`: °C tùy chọn cho các loại mới trừ nhiệt độ và gia tốc. `head`: m tùy chọn cho lưu lượng thấm. Giá trị bổ sung cũng phải là số hữu hạn.

Ví dụ:

```json
{"pressure":123.456789,"unit":"kPa","temperature":28.5,"measured_at":1791331200.125,"quality":"valid","serial_number":"PZ-01","calibration_id":"CAL-2026-01","reference_id":"ZERO-2026-01","location_label":"Mặt cắt A, nền đập","sequence":10}
```

### Dạng sóng rung chấn

```json
{"x":0.01,"y":-0.02,"z":0.03,"unit":"m/s²","quality":"valid","event_id":"EV-01","sequence":0,"waveform":{"start_at":1791331200.125,"sample_rate_hz":250,"x":[0,0.01],"y":[0,-0.02],"z":[0,0.03]}}
```

`waveform` có 1–1024 mẫu **mỗi trục**, ba trục cùng số mẫu; Hz phải >0 và ≤10000. Gateway chia bản ghi dài thành nhiều gói với `start_at`, `event_id`, `sequence` tương ứng; gửi đầy đủ dữ liệu trước/sau kích hoạt. Giới hạn này là giới hạn gói của web, không phải thời lượng tối đa sự kiện. Ba trường tức thời X/Y/Z vẫn bắt buộc. Web giữ từng gói trong buffer, ghi theo vòng flush 5 giây hiện có và chia lệnh ghi tối đa 256 bản ghi; không áp dụng chu kỳ bỏ mẫu cho gói dạng sóng. Dạng sóng được giữ nguyên trong JSON DB và các cột JSON xuất dữ liệu, không làm tròn hoặc thay bằng đỉnh. Biểu đồ đang xem chỉ hiện gói mới nhất, không lắp ráp toàn sự kiện.

Các số đo chậm vẫn theo chu kỳ lưu mặc định; timeout mặc định 300 giây cho loại mới, có thể chỉnh bằng `offline_thresholds` trong cấu hình trạm. Chu kỳ lưu, chu kỳ gateway và timeout cần chốt theo thiết bị/vận hành thực tế; UI chưa có trình chỉnh riêng cho từng loại mới. Chưa bổ sung báo động an toàn đập, kiểm tra mất gói, đồng bộ đồng hồ gateway, kho dạng sóng dài hạn hay nghiệm thu ghi liên tục 250 Hz.

### Cơ sở kỹ thuật

HSYC là nguồn danh mục và yêu cầu rung chấn. Tài liệu [GEOKON strain gages](https://www.geokon.com/content/manuals/4200-4202-4204-4210_Strain_Gages.pdf) phân biệt cách diễn giải biến dạng và ảnh hưởng nhiệt; [GEOKON liquid level sensor](https://www.geokon.com/content/manuals/4675_Liquid_Level_Sensor.pdf) mô tả quy đổi theo ứng dụng đo lưu lượng. Vì vậy web nhận giá trị kỹ thuật từ gateway và giữ mã hiệu chuẩn/mốc, không áp dụng một công thức quy đổi chung cho mọi thiết bị.

## Kiểm tra tải DB bổ sung

Xem [báo cáo kiểm tra DB](monitoring-storage-audit.md) về truy vấn lịch sử, giới hạn gói/lệnh ghi, chuyển dữ liệu xuống spool khi DB lỗi, thử nghiệm DB tạm và ước lượng lưu dạng sóng. Dữ liệu lịch sử để vẽ chỉ trả đại lượng/metadata, không trả mảng waveform; mẫu mới nhất vẫn có dạng sóng và DB/export giữ nguyên bản ghi đầy đủ.
