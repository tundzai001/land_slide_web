# Bình sai lưới GNSS bằng Python

Đây là bản viết lại phần bình sai cạnh GNSS 3D từ project C# `WF_GNSS_Adj`. Mã tập trung vào mô hình toán và kiểm soát chất lượng; không mang theo WinForms, RTKLIB, MQTT hay phần chuyển hệ tọa độ không liên quan.

## Mô hình

- Hệ tọa độ và vector cạnh thống nhất theo thứ tự **North, East, Height (N/E/H)**, đơn vị mét.
- Điểm khống chế được xem là cố định tuyệt đối.
- Mỗi cạnh nhận độ lệch chuẩn riêng cho N/E/H hoặc ma trận hiệp phương sai 3×3 đầy đủ.
- Nghiệm bình sai được tính bằng weighted least squares sau khi làm trắng quan sát, dùng `numpy.linalg.lstsq` (SVD), không nghịch đảo trực tiếp ma trận chuẩn.
- Kết quả gồm tọa độ và sai số điểm, số hiệu chỉnh cạnh, phần dư chuẩn hóa, độ dư thành phần, bậc tự do, hệ số phương sai hậu nghiệm và condition number.
- Kiểm định Chi-square hai phía đánh giá toàn bộ mô hình trọng số tiên nghiệm; Data Snooping dùng phần dư chuẩn hóa tiên nghiệm để chỉ ra thành phần N/E/H cần kiểm tra.
- Chương trình từ chối dữ liệu thiếu điểm gốc, thành phần mạng không nối tới điểm gốc, hiệp phương sai không xác định dương, thiếu trị đo hoặc ma trận thiếu hạng.

Phương trình quan sát là:

```text
d_observed + v = (X_to + x_to) - (X_from + x_from)
```

## Cài đặt và chạy

Từ thư mục này:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\gnss-adjust.exe ..\..\Dataset\slbs.txt -o report.txt --json result.json
```

Không cần cài package ở chế độ editable nếu chỉ chạy trực tiếp:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m gnss_adjustment ..\..\Dataset\slbs.txt -o report.txt
```

Chạy kiểm thử:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Dữ liệu đầu vào

### Text tương thích project C#

Parser đọc trực tiếp định dạng đang có trong `Dataset/slbs.txt`: một bảng điểm bắt đầu bằng header chứa `Point_name`, sau đó là bảng cạnh bắt đầu bằng header chứa `From_Point`. Dòng điểm có từ khóa `fix`, `fixed` hoặc `control` sẽ là điểm khống chế.

```text
#Stt Point_name North(m) East(m) H(m) N-std E-std H-std
1 P0 1000.0 2000.0 10.0 0 0 0 fixed
2 P1 1100.0 2050.0 12.0 0.01 0.01 0.02
#Stt From_Point To_Point d_north d_east dH dn_std de_std dH_std
1 P0 P1 100.002 49.998 2.001 0.003 0.003 0.006
```

Sai số gần đúng ghi ở dòng điểm được giữ để tương thích nhưng không dùng làm trọng số; độ chính xác tọa độ sau bình sai phải được suy ra từ mô hình cạnh.

### JSON

JSON phù hợp hơn khi tích hợp API và cho phép hiệp phương sai đầy đủ:

```json
{
  "points": [
    {"name": "P0", "coordinate": [1000, 2000, 10], "fixed": true},
    {"name": "P1", "coordinate": [1100, 2050, 12]}
  ],
  "baselines": [
    {"from": "P0", "to": "P1", "delta": [100.002, 49.998, 2.001], "std": [0.003, 0.003, 0.006]}
  ]
}
```

Thay `std` bằng `covariance` để truyền ma trận 3×3; chỉ được cung cấp một trong hai.

## Kiểm định thống kê

Mặc định chương trình giả thiết hệ số phương sai tiên nghiệm bằng 1, mức ý nghĩa toàn cục 5% và mức ý nghĩa cục bộ hai phía 0.1%:

```powershell
.\.venv\Scripts\python.exe -m gnss_adjustment network.txt `
  --apriori-variance-factor 1.0 `
  --global-alpha 0.05 `
  --local-alpha 0.001
```

Kiểm định toàn cục sử dụng:

```text
T = vᵀ C⁻¹ v / sigma0_apriori² ~ Chi-square(dof)
```

Data Snooping sử dụng từng phần dư chuẩn hóa tiên nghiệm:

```text
w_i = v_i / (sigma0_apriori * sqrt(q_vv_i))
```

và ngưỡng chuẩn hai phía. Chương trình **không tự động xóa trị đo**. Nếu kiểm định toàn cục thất bại và có hàng loạt cờ cục bộ, cần kiểm tra trước tiên mô hình stochastic, đơn vị/cách hiểu sigma, tương quan giữa các thành phần và sai số hệ thống. Chỉ nên loại trị đo khi có bằng chứng đo đạc và chạy lại toàn bộ bình sai sau mỗi quyết định.

## Khác biệt có chủ ý so với C#

Project C# dùng `P = 0.001² / std²`, cộng một hằng số nhỏ vào phương sai rồi nghịch đảo ma trận chuẩn. Bản Python dùng đúng hiệp phương sai khai báo và trả **reference standard deviation không thứ nguyên**. Vì vậy tọa độ/sai số điểm đối chiếu khớp, nhưng số `M` không bị nhân tùy ý với `0.001`. Đây là cách biểu diễn thống kê chuẩn và rõ đơn vị hơn.

Khi cần đối chiếu tuyệt đối với báo cáo cũ, dùng chế độ tương thích:

```powershell
.\.venv\Scripts\python.exe -m gnss_adjustment ..\..\Dataset\slbs1.txt `
  --csharp-compatible -o ..\..\Dataset\slbs1_python_kqbs.txt
```

Chế độ này tái hiện đúng `Pii = 0.001² / (std_i² + 1e-8)` và cách in `M` của `Adj.cs`. Không nên dùng nó cho dự án mới hoặc dữ liệu có covariance đầy đủ; mặc định vẫn là mô hình thống kê chuẩn.

Phần dư chuẩn hóa có trị tuyệt đối lớn (thường xem xét từ khoảng 3 trở lên) là dấu hiệu cần kiểm tra trị đo, nhưng không nên tự động loại cạnh nếu chưa có quy trình kiểm định ngoại lai phù hợp.
