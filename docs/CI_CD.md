# Kiểm tra và phát hành

Workflow `.github/workflows/quality.yml` chạy khi có pull request và khi đẩy lên `main`:

- Backend: Python 3.11, các phụ thuộc backend và gateway, toàn bộ `backend/tests`.
- Frontend: `npm ci`, build production, xác nhận `frontend/dist` đã được commit đúng với mã nguồn, rồi chạy kiểm thử tương tác Chromium cho bản đồ, Heatmap, điều hướng và theme.
- SonarQube Cloud: quét mã và chờ kết quả quality gate bằng secret `SONAR_TOKEN`.
- Sau khi cả ba job qua trên `main`, workflow tạo artifact `monitoring-release-<commit>` chứa mã backend, tài nguyên frontend và field unit đã được kiểm tra. Artifact được giữ 14 ngày.

Backend CI dùng khóa ký dành riêng cho test và URL DB giả trên cổng đóng; các bài kiểm thử thay thế kết nối bằng mock hoặc SQLite tạm. Không cần `.env` hay secret production. Chế độ production được giữ để kiểm tra cookie và các kiểm soát bảo mật đúng với môi trường triển khai.

Build frontend bỏ qua file ẩn của máy phát triển và manifest không chứa thời gian hiện tại. Cùng mã nguồn và lockfile phải sinh cùng tài nguyên trên máy phát triển và runner GitHub; bước đối chiếu tài nguyên vẫn bắt buộc.

Artifact là gói sẵn sàng để triển khai theo quy trình vận hành hiện có. Workflow hiện chưa tự ghi vào máy chủ production vì repo chưa cấu hình runner hoặc thông tin kết nối triển khai. Khi triển khai, cần giữ cấu hình/secret ngoài gói phát hành và kiểm tra `/api/health/live`, `/api/health/ready` sau khi khởi động.
