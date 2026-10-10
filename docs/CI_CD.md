# Kiểm tra và phát hành

Workflow `.github/workflows/quality.yml` chạy khi có pull request và khi đẩy lên `main`:

- Backend: Python 3.11, các phụ thuộc backend và gateway, toàn bộ `backend/tests`.
- Frontend: `npm ci`, build production, xác nhận `frontend/dist` đã được commit đúng với mã nguồn, rồi chạy kiểm thử tương tác Chromium cho bản đồ, Heatmap, điều hướng và theme.
- Sau khi cả hai job qua trên `main`, workflow tạo artifact `monitoring-release-<commit>` chứa mã backend, tài nguyên frontend và field unit đã được kiểm tra. Artifact được giữ 14 ngày.

Artifact là gói sẵn sàng để triển khai theo quy trình vận hành hiện có. Workflow hiện chưa tự ghi vào máy chủ production vì repo chưa cấu hình runner hoặc thông tin kết nối triển khai. Khi triển khai, cần giữ cấu hình/secret ngoài gói phát hành và kiểm tra `/api/health/live`, `/api/health/ready` sau khi khởi động.
