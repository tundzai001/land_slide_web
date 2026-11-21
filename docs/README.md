# Tài liệu Hệ thống Aitogy Landslide Monitor

Danh mục tài liệu kỹ thuật, hướng dẫn vận hành và cấu hình triển khai của hệ thống.

---

## 1. Hướng dẫn Người dùng & Vận hành
- [USER_GUIDE.md](USER_GUIDE.md) ([Bản PDF](USER_GUIDE.pdf)): Hướng dẫn sử dụng giao diện bản đồ, phân tích chuỗi đo, quản trị dự án, trạm và người dùng.
- [OPERATIONS_INTEGRATION.md](OPERATIONS_INTEGRATION.md) ([Bản PDF](OPERATIONS_INTEGRATION.pdf)): Hướng dẫn tích hợp gateway hiện trường, giao thức Modbus / OPC UA sang MQTT, và kịch bản vận hành.

## 2. Kỹ thuật GNSS & Cảm biến
- [monitoring-sensors.md](monitoring-sensors.md): Quy chuẩn danh mục cảm biến (GNSS, IMU, Mưa, Mực nước), topic MQTT, định dạng payload và xử lý chuỗi đo.
- [GNSS_MONITORING_RECOVERY.md](GNSS_MONITORING_RECOVERY.md): Quy trình hiệu chuẩn lại toạ độ gốc (Origin) và xử lý độ lệch baseline khi đổi trạm mốc CORS.
- [idle-rover-recovery.md](idle-rover-recovery.md): Cơ chế tự động phát hiện và thu hồi trạng thái rover nhàn rỗi sau chu kỳ bình sai.
- [project-map-position.md](project-map-position.md): Quy tắc xác định tâm và bounding box hiển thị bản đồ dự án.

## 3. Hạ tầng & Triển khai
- [CI_CD.md](CI_CD.md): Quy trình kiểm thử tự động (Pytest, Playwright, SonarCloud) và đóng gói release trên GitHub Actions.
- [monitoring-storage-audit.md](monitoring-storage-audit.md): Tiêu chuẩn lưu trữ bền vững PostgreSQL, spool đệm sự cố và kiểm toán dung lượng.
- [rescue-feature-flag.md](rescue-feature-flag.md): Cấu hình cổng tiếp nhận yêu cầu cứu nạn khẩn cấp.

## 4. Thiết kế & Kiến trúc Giao diện
- [UI_UX_MASTER_PLAN.md](UI_UX_MASTER_PLAN.md): Nguyên tắc thiết kế giao diện (Dark/Light theme, bố cục responsive, hiệu năng Three.js và khả năng tiếp cận).
