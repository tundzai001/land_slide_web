# Kế hoạch Kiểm tra và Cập nhật GNSS Auto Adjustment & Logic Bình Sai

Dựa vào việc kiểm tra lỗi và nội dung phản hồi trong `log.txt`, tôi đã xác định được 3 nhóm vấn đề chính dẫn đến hiện tượng bạn gặp phải. Dưới đây là phân tích và kế hoạch khắc phục chi tiết.

## 🔴 1. Tại sao Auto Adjustment thất bại (Thư mục adjustments trống)?

**Nguyên nhân:**
Quá trình lập lịch bình sai tự động (`app/infrastructure/scheduler.py`) luôn bị kẹt ở bước "preflight" kiểm tra rover. Lỗi cụ thể là:
`ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection`
Lỗi này xảy ra bên trong `ensure_rover_streams_ready` -> `_query_client_table` (file `round_robin.py`), khi hệ thống cố gắng kết nối tới cổng HTTP (NTRIP_PORT, thường là 2101) của AICaster để lấy `clienttable`. Nếu AICaster không chạy, sai port, hoặc kết nối bị từ chối, toàn bộ tiến trình Auto Adjustment sẽ bị hủy bỏ (Abort) và báo lỗi, dẫn đến thư mục `adjustments` không có file kết quả.

**Cách khắc phục:**
1. Thêm cơ chế Fallback (Bỏ qua nếu `allow_unavailable=True`) trong `_fetch_active_client_candidates` và `ensure_rover_streams_ready`. Nếu không thể kết nối tới AICaster, thay vì quăng lỗi `RuntimeError` gây chết tiến trình, hệ thống chỉ cần log lỗi và đánh dấu các trạm là "không thể điều khiển" (uncontrollable) nhưng vẫn cho phép phần bình sai tiếp tục chạy với các dữ liệu đã có.
2. Cần kiểm tra lại cấu hình AICaster (`settings.NTRIP_PORT`, `settings.NTRIP_HOST`) xem service này có đang hoạt động trên máy chủ không.

## 🔴 2. Tại sao file `gnss_raw_...xlsx` chỉ có vài kết quả và ghi đè liên tục?

**Nguyên nhân:**
Hàm `_append_raw_gnss_to_excel` (trong `reporting.py`, được gọi bởi `mqtt_bridge.py`) đang thực hiện việc mở file Excel, đọc toàn bộ vào bộ nhớ (`openpyxl.load_workbook`), thêm 1 dòng log, rồi lưu lại toàn bộ file *cho mỗi một gói tin MQTT nhận được*.
Việc này cực kỳ tốn tài nguyên và block Event Loop của server. Hơn nữa, nếu hàm này gặp lỗi (ví dụ file đang bị khóa do ghi/đọc đồng thời), nó sẽ nhảy vào nhánh `except Exception:` và **tạo mới một Workbook tinh khôi**, xóa sạch toàn bộ dữ liệu trước đó! Đó là lý do file xlsx "trông rất lạ", thường chỉ còn đúng 1 dòng mới nhất.

**Cách khắc phục:**
Đổi định dạng lưu Raw GNSS từ `.xlsx` sang `.csv`. File CSV có chế độ `append` (`a`) cực kỳ nhẹ, nhanh, không bao giờ bị mất dữ liệu cũ và không block Event Loop.
Ví dụ: thay vì tạo các sheet, hệ thống sẽ mở file `.csv` ở chế độ append và ghi trực tiếp dòng string vào.

## 🔴 3. Sửa các lỗi logic cốt lõi (Ghi trong `log.txt`)

Các lỗi P0/P1 do bạn ghi nhận trong `log.txt` đều chính xác, và tôi sẽ tiến hành cập nhật mã nguồn `gnss_processor.py` để xử lý dứt điểm:

### P0: Reference shift bypass spike gate (Lỗi nguy hiểm nhất)
**Vấn đề:** Nếu một sự kiện chuyển đổi CORS gây ra bước nhảy (shift) 10cm, nhỏ hơn ngưỡng `max_step_distance_m` (ví dụ 20cm), thì `is_spike` sẽ bằng `False`. Khối mã tái lập toạ độ (nằm trong `if is_spike:`) sẽ bị bỏ qua, và 10cm này sẽ bị đưa thẳng vào bộ lọc vận tốc (velocity) và dịch chuyển (displacement), khiến hệ thống tưởng đất đang trượt thật.
**Giải pháp:** Đưa logic kiểm tra và thiết lập `REFERENCE_TRANSITION` lên vị trí sớm nhất có thể. Nếu sự kiện chuyển trạm phát sinh (`event_ts` hợp lệ), lập tức gom các sample tiếp theo lại mà KHÔNG ĐI QUA bước `spike gate`. Cấu trúc lại luồng: `Incoming Fixed -> Event Recent? -> Reference Transition -> Spike Gate`.

### P1: Origin 60 mẫu không liên tục
**Vấn đề:** Các mẫu ORIGIN hiện không bắt buộc phải đến liên tiếp trong một khoảng thời gian nhất định (nếu HDOP kém, code chỉ chờ chứ không clear mẫu cũ).
**Giải pháp:** Đã có logic kiểm tra `max_gap_s` nhưng chưa bao gồm reset khi HDOP kém (low quality). Tôi sẽ bổ sung logic clear origin candidates nếu sample không đạt chất lượng kéo dài.

### P1: Event chưa gắn chặt với shift onset
**Vấn đề:** Điều kiện `event xảy ra trong 5 phút gần đây` khiến chuyển vị thật cũng bị nuốt nếu xảy ra ngay sau sự kiện đổi CORS.
**Giải pháp:** Thay vì so sánh `event_ts` với `current time (ts)`, sẽ lưu `self._shift_started_at` và so sánh khoảng cách giữa sự kiện (event_ts) và thời điểm bắt đầu shift (shift_started_at).

### P1: Persistent shift chưa trả về cấu trúc
**Vấn đề:** Cấu trúc JSON trả về khi bị cách ly chỉ có đoạn text, không có giá trị shift_e, shift_n, shift_u để báo cho bộ phận giám sát.
**Giải pháp:** Trả về dict hoàn chỉnh trong trường `data` có chứa `shift_e_m`, `shift_n_m`, v.v...

### P1/P2: Các vấn đề khác
* Thêm kiểm tra `PROCESS_MAX_HDOP` và `PROCESS_MIN_SATS` ngay đầu hàm `_handle_processing`.
* Sửa sai type `gnss_status` thay vì `origin_status` ở giai đoạn `WAITING_FOR_QUALITY`.
* Áp dụng `REACQUIRE_MAX_SPREAD_XY_M = 0.03` và `U_M = 0.05` thay thế cho ngưỡng spike cũ khi gom stable cluster để khôi phục (reacquire).
* Dọn dẹp code rác/biến không dùng.

---

> [!CAUTION]
> **User Review Required**
> 1. Việc chuyển file raw log GNSS từ Excel (`.xlsx`) sang CSV (`.csv`) sẽ thay đổi thói quen của người xem một chút (vẫn mở bằng Excel bình thường nhưng nhẹ và nhanh hơn hàng trăm lần). Bạn đồng ý với việc thay đổi này chứ?
> 2. Kế hoạch này sẽ sửa sâu vào thuật toán bình sai/lọc toạ độ của GNSS. Hãy xem qua phần 3 ở trên xem tôi có hiểu đúng ý bạn ở file `log.txt` chưa nhé.

Hãy nhấn Proceed (Chấp nhận) kế hoạch để tôi bắt đầu viết mã khắc phục, đồng thời tôi sẽ copy một bản kế hoạch này (dạng `.md`) ra Desktop cho bạn theo đúng yêu cầu!
