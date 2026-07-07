# Nâng cấp Luồng Xử lý GNSS & Bình sai theo Cụm

Kế hoạch này giải quyết yêu cầu hỗ trợ xử lý đồng thời `GNGGA` và `AGRICA`, cho phép gộp các rover thành từng cụm để bình sai, và giải quyết bài toán truyền tọa độ rover cho lệnh "set base" của phần mềm CASTER.

## Phương án Gửi Lệnh Set Base (Backend làm máy chủ điều phối)
1. **Lấy Tọa độ**: Backend phân tích bản tin `GNGGA` để trích xuất tọa độ tuyệt đối (lat, lon, h) của rover.
2. **Truyền Lệnh sang CASTER**: Backend sẽ gọi một API (sẽ được xây dựng thêm trong CASTER) để truyền lệnh set base kèm tọa độ.
3. **CASTER Xử lý Lệnh**: API trong CASTER sẽ gọi thẳng hàm `ProcessSet` để rover nhận lệnh.

## Cần Người dùng Đánh giá (Giải quyết vấn đề "Độ trễ mất Fix")

## 2. Kế hoạch Bình sai & Xử lý Độ trễ khi đổi Base (Giải pháp Giữ Toạ độ Cố định - Hold Coor)

Ý kiến của bạn cực kỳ chính xác và thực tế: **Khi Rover đang ở trạng thái Hold Fix cũ, toạ độ tính toán của nó vẫn đạt độ chính xác cao**. Vì vậy, thay vì phải định tuyến phức tạp, ta có thể áp dụng giải pháp **Giữ toạ độ cố định ban đầu (Hold Coor)** để tính toán vị trí tạm thời và các đường baseline giữa các Rover với nhau:

### Cơ chế hoạt động của giải pháp Hold Coor:

1. **Khóa gốc ban đầu (Lock Origin):**
   - Khi hệ thống bắt đầu chạy ở trạng thái ổn định, mọi Rover đều được khóa gốc tọa độ tuyệt đối trong không gian ECEF (gọi là $\vec{Pos}_{origin\_i}$).
2. **Khi Rover B chuyển thành Base mới:**
   - Hệ thống sẽ **giữ (hold) toạ độ cuối cùng cực kỳ chính xác** của Rover B ngay trước khi chuyển giao ($\vec{Pos}_{B\_held}$). Toạ độ này coi như toạ độ mốc của Base mới.
3. **Tính toán toạ độ và baseline tạm thời trong lúc chuyển tiếp:**
   - **Với Rover A chưa chuyển Base (vẫn nhận Base gốc X):** Ta tính toạ độ hiện tại của nó dựa vào Base X:
     $$\vec{Pos}_{A} = \vec{Pos}_{X} + \vec{b}_{AX}$$
   - **Với Rover A đã chuyển sang Base mới B:** Ta tính toạ độ của nó dựa vào Base B (sử dụng toạ độ đang được hold của B):
     $$\vec{Pos}_{A} = \vec{Pos}_{B\_held} + \vec{b}_{AB}$$
   - **Tính baseline tạm thời giữa các Rover (ví dụ A và B):**
     $$\vec{b}_{AB\_temporary} = \vec{Pos}_{B\_held} - \vec{Pos}_{A}$$
     (Baseline này hoàn toàn chính xác ở mức milimet vì được suy ra từ các vector RTK Fixed chuẩn xác).

### Ưu điểm vượt trội:
- **Không lo độ trễ chuyển giao:** Kể cả khi quá trình Rover nhận Base mới kéo dài tới 5 phút, toạ độ của toàn bộ các Rover trong mạng lưới vẫn được cập nhật liên tục và chính xác dựa vào mối liên kết toán học.
- **Tính toán được baseline giữa các Rover:** Tự động suy ra khoảng cách tương đối giữa các Rover tạm thời mà không cần chúng phải trực tiếp nhận RTK của nhau.

## Các Công việc Kỹ thuật Tiếp theo

### Backend - GNSS Processor & Runtime
- Cập nhật cấu trúc dữ liệu để lưu trữ `origin_ecef` và `last_known_ecef` của từng trạm.
- Triển khai logic tính toán toạ độ dựa trên Base tương ứng mà Rover đang kết nối tại epoch đó.
- Xuất kết quả tọa độ và baseline tạm thời phục vụ cho việc bình sai cụm ECEF.

### 2. Backend - Adjustment Runtime
- Sửa đổi `AgricaAdjustmentRuntime`: 
  - Nhận input là tọa độ ECEF cho các điểm.
  - Các vector baseline được truyền vào đã được gắn sẵn `from_point` (do Backend quản lý).
  - Phân nhóm dựa theo cấu hình cụm và chạy bình sai 3D ECEF.

### 3. Backend - API & Database
- Cập nhật Database Model / API Endpoints của `Project` để lưu trữ cấu hình `gnss_clusters`.
- Đảm bảo cấu hình này được truyền xuống `mqtt_bridge.py`.

### 4. Frontend - Admin Settings
- Thêm một component giao diện mới trong trang Cài đặt Dự án để định nghĩa các **Cụm Bình sai GNSS** (GNSS Adjustment Clusters).
