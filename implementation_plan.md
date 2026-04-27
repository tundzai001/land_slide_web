# Kế hoạch Triển khai: Hệ Thống Mô Phỏng Sạt Lở 3D — LS-RAPID Digital Twin (Ultra-Premium)

## Tổng quan

Xây dựng một **Digital Twin 3D thời gian thực** mô phỏng toàn bộ quá trình sạt lở đất — từ trạng thái ổn định, qua giai đoạn phá hoại lũy tiến (progressive failure), đến chuyển động khối trượt và lắng đọng cuối cùng — dựa trên nền tảng vật lý chuẩn xác của mô hình **LS-RAPID (Sassa, 2004)**.

Hệ thống không chỉ là hiệu ứng hình ảnh đẹp mắt, mà phản ánh đúng các phương trình cơ học đất (Mohr-Coulomb, Terzaghi Effective Stress), động lực học chất lưu mảnh vụn (Debris Flow Dynamics), và tương tác phá hủy với cơ sở hạ tầng xung quanh.

---

## Proposed Changes

### 1. Frontend — Trang Digital Twin 3D

#### [NEW] `frontend/pages/digital-twin.html`
- Trang fullscreen chuyên dụng, giao diện **Dark Mode Sci-Fi / Glassmorphism**.
- Layout: Canvas WebGL chiếm ~75% màn hình, Control Panel bên trái ~25%.

#### [NEW] `frontend/css/digital-twin.css`
- Thiết kế HUD (Heads-Up Display) kiểu phi hành gia:
  - Gauge hình tròn cho **Factor of Safety (FoS)** — xanh khi FoS > 1.5, vàng khi 1.0–1.5, đỏ nhấp nháy khi < 1.0.
  - Timeline bar (Play / Pause / Tua) ở dưới cùng.
  - Panel thông số LS-RAPID bên trái với các slider tương tác.
  - Bảng thống kê thiệt hại (số nhà bị phá hủy, diện tích cây bị cuốn, khối lượng vật liệu di chuyển).

---

### 2. Frontend — Engine 3D (Three.js)

#### [NEW] `frontend/js/engine/scene-manager.js`
**Quản lý Scene, Camera, Lighting, Post-Processing:**
- **Camera**: OrbitControls + Cinematic Mode (tự động bay theo khối trượt khi simulation chạy).
- **Lighting**: DirectionalLight (mặt trời) với Shadow Map chất lượng cao + AmbientLight cho fill. Ánh sáng thay đổi theo thời gian trong ngày (sunrise → noon → sunset tông màu khác nhau).
- **Post-Processing (EffectComposer)**:
  - SSAO (Screen Space Ambient Occlusion) — tăng chiều sâu hình ảnh.
  - Bloom — phát sáng cho hiệu ứng cảnh báo, lửa.
  - Camera Shake — rung lắc khi khối đất bắt đầu trượt.
  - Motion Blur — khi debris di chuyển nhanh.
  - Fog / Atmospheric Scattering — sương mù cho chiều sâu cảnh.

#### [NEW] `frontend/js/engine/terrain-generator.js`
**Sinh Địa hình 3D Procedural chân thực:**
- Sử dụng **Fractal Brownian Motion (fBM)** với nhiều octave Perlin Noise để tạo sườn dốc đồi núi tự nhiên.
- Texture multi-layer dựa trên độ cao và độ dốc:
  - Đỉnh cao: Đá trơ (Rock texture).
  - Sườn dốc: Đất mùn + cỏ thưa.
  - Chân đồi / thung lũng: Cỏ xanh + đất phì nhiêu.
- **Wetness Map Shader**: Khi mưa, bề mặt đất dần chuyển sang tông sẫm + phản xạ specular tăng (bề mặt ướt bóng loáng). Controlled bằng uniform `u_wetness` từ 0.0 → 1.0.

#### [NEW] `frontend/js/engine/environment-builder.js`
**Xây dựng Cảnh vật Xung quanh — Nhà, Cây, Đường sá, Con người:**
- **Nhà dân (Procedural Houses)**: Sinh ngẫu nhiên các khối hộp có mái (BoxGeometry + roof) với màu sắc đa dạng. Đặt rải rác trên sườn dốc thấp và chân đồi. Sử dụng `InstancedMesh` để render hàng trăm ngôi nhà mà không giảm FPS.
- **Cây cối (Instanced Trees)**: 2 loại — Cây thông (ConeGeometry + CylinderGeometry) và cây bụi (SphereGeometry). Hàng nghìn cây phân bố tự nhiên theo density map (nhiều cây ở sườn dốc, ít ở đỉnh đá).
- **Đường sá**: Plane mỏng uốn lượn theo contour chân đồi, texture nhựa đường.
- **Cột điện / Hàng rào**: Cylinder nhỏ + dây nối, rải dọc đường.
- **Xe cộ / Con người** (tùy chọn): Các khối nhỏ đặt trên đường để tăng tính sống động.

#### [NEW] `frontend/js/engine/physics-engine.js`
**Cốt lõi Vật lý — Triển khai đúng LS-RAPID trên Frontend:**

**A) Tính toán Hệ số An toàn (Factor of Safety):**
Dựa trên công thức Mohr-Coulomb + Terzaghi Effective Stress:
```
FoS = [c' + (γ·z·cos²β - u) · tan(φ')] / [γ·z·sinβ·cosβ + kh·γ·z·cosβ]
```
Trong đó:
- `c'` = Effective cohesion (lực dính hiệu quả, kPa)
- `γ` = Unit weight of soil (trọng lượng riêng đất, kN/m³)
- `z` = Depth of slip surface (chiều sâu mặt trượt, m)
- `β` = Slope angle (góc dốc, °)
- `u` = Pore water pressure = `ru · γ · z` (áp lực nước lỗ rỗng, kPa)
- `ru` = Pore pressure ratio (0.0 → 0.6, tăng dần theo lượng mưa tích lũy)
- `φ'` = Effective friction angle (góc ma sát hiệu quả, °)
- `kh` = Horizontal seismic coefficient (hệ số gia tốc nền ngang, cho mô phỏng động đất)

**B) Trigger Mechanism (Cơ chế Kích hoạt):**
- Khi người dùng kéo thanh trượt "Lượng mưa", hệ thống tính toán:
  1. Lượng mưa hiệu dụng tích lũy (Effective Rainfall) theo mô hình LS-RAPID:
     `R_eff(t) = R(t) + α · R_eff(t-1)` với `α = exp(-ln2 / T_half)`
  2. Áp lực nước lỗ rỗng `u` tăng tỷ lệ thuận với `R_eff` (có trễ thấm).
  3. FoS giảm dần. Khi **FoS < 1.0** → **Trigger sạt lở**.

**C) Mô phỏng Chuyển động Khối trượt (Landslide Motion):**
Sau khi trigger, khối đất chuyển động theo phương trình Newton + ma sát đáy:
```
m · a = m·g·sinβ - τ_base · A - F_drag
```
Trong đó:
- `τ_base` = Shear resistance at steady state (giảm mạnh sau khi hóa lỏng, theo thí nghiệm Ring Shear của Sassa).
- `F_drag` = Lực cản do va chạm với vật cản (nhà, cây).
- Vận tốc cập nhật mỗi frame: `v(t+dt) = v(t) + a·dt`.
- Vị trí cập nhật: `x(t+dt) = x(t) + v·dt`.

**D) Volume Enlargement (Cuốn thêm vật liệu):**
Khi khối trượt di chuyển qua lớp đất không ổn định, nó cuốn thêm vật liệu (entrainment), khối lượng tăng:
```
m(t+dt) = m(t) + ρ · h_entrain · A_front · v · dt
```

#### [NEW] `frontend/js/engine/destruction-system.js`
**Hệ thống Phá hủy Vật lý khi Khối trượt Tương tác Cảnh vật:**
- **Collision Detection**: Bounding Box của khối trượt (debris front) kiểm tra va chạm với mỗi Object (nhà, cây).
- **Nhà bị phá hủy**: Khi động năng khối trượt `(0.5·m·v²)` > ngưỡng chịu lực của nhà → nhà bị "fracture" thành nhiều mảnh nhỏ (chia mesh thành sub-meshes rồi cho rơi tự do theo trọng lực + cuốn theo dòng chảy).
- **Cây bị bật gốc**: Cây nghiêng dần rồi đổ theo hướng dòng chảy (rotation animation + cuốn trôi).
- **Đường sá bị vùi lấp**: Texture đường chuyển sang texture bùn/đất đá.
- **Bảng thống kê thiệt hại**: Cập nhật real-time — số nhà sập, số cây đổ, khối lượng vật liệu đã di chuyển (tấn), diện tích vùi lấp (m²).

#### [NEW] `frontend/js/engine/particle-system.js`
**Hệ thống Hạt cho Hiệu ứng Đặc biệt:**
- **Debris Particles**: Hàng chục nghìn hạt nhỏ (đất đá) dùng `InstancedMesh` + cập nhật position trong vertex shader cho hiệu năng tối đa.
- **Dust Cloud (Khói bụi)**: Particle lớn, mờ dần, bay lên khi khối đất đập xuống.
- **Rain Particles**: Hạt mưa rơi từ trên xuống, va chạm bề mặt tạo splash nhỏ. Cường độ (số hạt/giây) tỷ lệ với thanh trượt mưa trên UI.
- **Water Flow (Nước chảy)**: Particle mô phỏng nước chảy tràn bề mặt sau mưa lớn.

#### [NEW] `frontend/js/engine/weather-system.js`
**Hệ thống Thời tiết Động:**
- **Mưa**: Điều khiển bằng slider. Từ 0mm → 200mm/h:
  - 0: Trời nắng, bóng rõ.
  - 20: Mưa nhẹ, mây xám.
  - 80: Mưa vừa, sấm sét (flash light ngẫu nhiên).
  - 150+: Mưa rất to, fog dày đặc, tầm nhìn giảm.
- **Skybox thay đổi**: Từ xanh trong → xám → đen theo cường độ mưa.
- **Wetness shader**: Bề mặt đất chuyển từ khô → ướt → bùn lầy.

#### [NEW] `frontend/js/engine/simulation-controller.js`
**Bộ điều khiển Tổng hợp:**
- Quản lý vòng lặp mô phỏng (simulation loop) riêng biệt với render loop.
- **Timeline**: Play / Pause / Speed (1x, 2x, 5x, 10x).
- **Trạng thái Mô phỏng**: 
  1. `STABLE` — FoS > 1.0, cảnh yên bình.
  2. `WARNING` — FoS 1.0–1.2, cảnh báo vàng, đất bắt đầu nứt (crack lines trên terrain).
  3. `CRITICAL` — FoS < 1.0, cảnh báo đỏ, camera shake nhẹ.
  4. `SLIDING` — Khối đất đang trượt, phá hủy đang xảy ra.
  5. `DEPOSITED` — Khối đất dừng lại, bụi lắng, thống kê thiệt hại hiển thị.

---

### 3. Backend — Engine Vật lý LS-RAPID

#### [NEW] `backend/simulation/ls_rapid_engine.py`
**Solver mô phỏng chạy trên server (tuỳ chọn nâng cao):**
- Chạy mô phỏng LS-RAPID trên lưới ô vuông (Grid-based Column Model) theo đúng paper của Sassa.
- Tính toán lưới áp lực nước lỗ rỗng từ mô hình thấm mưa (Green-Ampt infiltration).
- Trả về mảng `{x, y, z, vx, vy, mass}[]` cho mỗi timestep.
- Endpoint REST: `POST /api/simulation/run` nhận thông số và trả kết quả.

#### [MODIFY] `backend/app/main.py`
- Thêm route `/api/simulation/run` để nhận thông số từ frontend, chạy solver, trả kết quả JSON.
- Thêm route `/api/simulation/presets` để trả về bộ thông số mẫu (Đất sét, Đất cát, Đá phong hóa...).

---

### 4. Tích hợp Dữ liệu Thực từ Hệ thống Giám sát

#### [MODIFY] `frontend/js/map-main.js`
- Thêm nút **"🌋 Mô phỏng 3D"** vào sidebar chi tiết trạm.
- Khi nhấn, mở `digital-twin.html` và tự động truyền:
  - Thông số mưa hiện tại / 24h qua từ sensor.
  - Dữ liệu dịch chuyển GNSS và ls_rapid_index.
  - Config LS-RAPID (half-life, weight...) từ cấu hình trạm.

---

## Verification Plan

### Performance Tests
- FPS > 45 trên GPU tầm trung (GTX 1650 / Intel UHD 630) với 500 nhà + 2000 cây + 50,000 particles.
- Không rò rỉ bộ nhớ WebGL sau 10 phút chạy liên tục.

### Manual Verification
1. Mở Digital Twin → Cảnh 3D hiển thị: sườn đồi có nhà cửa, cây cối, đường sá, xe cộ sống động.
2. Kéo slider mưa từ 0 → 200mm/h: Mưa rơi tăng dần, đất ướt dần, sương mù dày.
3. FoS Gauge giảm dần từ xanh → vàng → đỏ.
4. Khi FoS < 1.0: Tiếng nứt đất, camera rung, vết nứt xuất hiện trên mặt đất.
5. Khối đất trượt xuống: Cuốn trôi nhà cửa (vỡ nát), bật gốc cây cối, bụi mù trời.
6. Dừng lại ở chân đồi, bảng thống kê thiệt hại hiện lên.

---

## 5. Cập nhật: Nhúng Trực tiếp vào Map (Overlay Mode)

Dựa theo yêu cầu mới, Digital Twin sẽ không chạy ở trang riêng biệt `digital-twin.html` nữa, mà sẽ được **nhúng trực tiếp vào `map.html`** dưới dạng một popup/overlay toàn màn hình (fullscreen overlay).

### Yêu cầu Thiết kế (User Review Required)
> [!IMPORTANT]
> Việc nhúng một engine 3D nặng vào một trang có sẵn bản đồ 2D (Leaflet) và hàng loạt biểu đồ (Chart.js) cần quản lý bộ nhớ cẩn thận để tránh rò rỉ (memory leaks) và crash trình duyệt.
>
> 1. **Kiến trúc Overlay**: Sẽ tạo một thẻ `<div id="dt-overlay" class="dt-fullscreen-overlay">` trong `map.html`. Mặc định ẩn (`display: none`).
> 2. **Trì hoãn Khởi tạo (Lazy Init)**: Engine Three.js chỉ khởi tạo (khởi động WebGL context, tạo geometry) khi người dùng nhấn nút "Mô phỏng 3D".
> 3. **Giải phóng Bộ nhớ (Dispose)**: Khi nhấn nút "Đóng", ta phải gọi các hàm `dispose()` của Three.js (materials, geometries, renderer) để giải phóng GPU memory, nếu không mở ra đóng lại nhiều lần sẽ giật lag.

### Proposed Changes

#### [MODIFY] `frontend/pages/map.html`
- Chèn khối HTML giao diện HUD và cấu trúc của `digital-twin.html` vào bên trong một container overlay.
- Đổi nút "Mô phỏng 3D" từ thẻ `<a>` (chuyển trang) sang thẻ `<button>` để trigger JavaScript mở overlay.

#### [MODIFY] `frontend/css/digital-twin.css`
- Chỉnh sửa CSS selector để các thành phần HUD (Gauges, Panels, Header) hiển thị đúng trong môi trường `map.html` (tránh xung đột CSS với các thành phần hiện tại).
- Thêm style cho overlay container (fullscreen, z-index rất cao).

#### [MODIFY] `frontend/js/engine/simulation-controller.js`
- Thay vì tự động chạy ngay khi load trang (`window.addEventListener('DOMContentLoaded')`), sẽ xuất (export) ra các hàm `openDigitalTwin()` và `closeDigitalTwin()`.
- Thêm logic dọn dẹp WebGL context khi đóng màn hình.

### Open Questions
> [!QUESTION]
> Bạn có muốn truyền các thông số thực tế từ trạm mà bạn vừa click (ví dụ: lượng mưa hiện tại, thông số sạt lở) trực tiếp vào thanh trượt của mô phỏng 3D khi overlay bật lên không? Hay để giá trị mặc định cho người dùng tự kéo?
