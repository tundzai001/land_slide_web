export function renderAboutTemplate(logoUrl = '/assets/aitogy.png') {
    return `
    <div class="noise-overlay" aria-hidden="true"></div>
    <div class="scroll-progress" aria-hidden="true"><span class="scroll-progress-fill"></span></div>
    <a class="skip-link" href="#main">Bỏ qua đến nội dung chính</a>
    <header class="site-header">
        <div class="header-inner">
            <a class="brand" href="/" aria-label="Aitogy Monitoring — Trang chủ"><span class="brand-plate"><img src="${logoUrl}" width="759" height="329" alt="Aitogy"></span><span class="brand-rule" aria-hidden="true"></span><span class="brand-product"><strong>Monitoring</strong><small>Quan trắc</small></span></a>
            <nav class="desktop-nav" aria-label="Điều hướng chính"><a href="/">Trang chủ</a><a href="/about" aria-current="page">Giới thiệu</a><a href="/management">Dashboard</a><a href="/map">Bản đồ</a></nav>
            <div class="header-actions">
                <button class="icon-button theme-switch" id="theme-toggle" type="button" aria-label="Chuyển giao diện tối" aria-pressed="false"><svg class="theme-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20.2 15.6A8.6 8.6 0 0 1 8.4 3.8 8.6 8.6 0 1 0 20.2 15.6Z"/></svg><svg class="theme-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.6"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg></button>
                <a class="button button-ghost login-link" id="auth-link" href="/login?return_to=%2Fmap">Tài khoản</a><a class="button button-primary header-cta" href="/map">Mở bản đồ <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5"/></svg></a>
                <button class="menu-button" id="menu-toggle" type="button" aria-expanded="false" aria-controls="mobile-menu" aria-label="Mở trình đơn"><span></span><span></span><span></span></button>
            </div>
        </div>
        <nav class="mobile-menu" id="mobile-menu" aria-label="Điều hướng di động" hidden><a href="/">Trang chủ</a><a href="/about" aria-current="page">Giới thiệu</a><a href="/management">Dashboard</a><a href="/map">Bản đồ</a><a id="mobile-auth-link" href="/login?return_to=%2Fmap">Tài khoản</a></nav>
    </header>

    <main id="main">
        <section class="hero" aria-labelledby="hero-title">
            <div class="hero-grid" aria-hidden="true"></div>
            <div class="hero-aurora hero-aurora-a" aria-hidden="true"></div><div class="hero-aurora hero-aurora-b" aria-hidden="true"></div>
            <div class="hero-copy">
                <p class="eyebrow hero-kicker"><span class="live-dot"></span>GIỚI THIỆU · AITOGY MONITORING</p>
                <h1 id="hero-title"><span>Hệ thống quan trắc đa cảm biến.</span><br><em>Từ cảm biến đến dữ liệu.</em></h1>
                <p class="hero-lead">Theo dõi đập, công trình và môi trường theo thời gian thực. Kết nối cảm biến, xem lịch sử và phân tích dữ liệu tại từng điểm quan trắc.</p>
                <div class="hero-actions"><a class="button button-primary button-large" href="/map">Xem bản đồ realtime <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5"/></svg></a><a class="button button-ghost button-large" href="#story">Cuộn xem câu chuyện 3D</a></div>
                <ul class="monitoring-scopes" aria-label="Phạm vi quan trắc"><li>Đập &amp; hồ chứa</li><li>Thân &amp; nền đập</li><li>Công trình</li><li>Môi trường</li></ul>
                <div class="signal-proof" aria-label="Ba bước vận hành"><span><b>01</b> Thu thập dữ liệu</span><i></i><span><b>02</b> Theo dõi liên tục</span><i></i><span><b>03</b> Phân tích lịch sử</span></div>
            </div>
            <div class="hero-visual" aria-label="Mô hình địa hình quan trắc ba chiều dựng bằng Blender">
                <div class="sensor-legend" aria-hidden="true"><span data-sensor="gnss"><i></i>GNSS RTK</span><span data-sensor="imu"><i></i>Hộp MEMS IMU</span><span data-sensor="rain"><i></i>Gầu đo mưa</span><span data-sensor="water"><i></i>Piezometer ngầm</span></div>
                <div class="hero-poster" aria-hidden="true">
                    <svg class="poster-diorama" viewBox="0 0 640 480" preserveAspectRatio="xMidYMid slice">
                        <defs>
                            <linearGradient id="slopeTop" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#136f63"/><stop offset="60%" stop-color="#0b4a45"/><stop offset="100%" stop-color="#072c2b"/></linearGradient>
                            <linearGradient id="soilWall" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="#0d4440"/><stop offset="100%" stop-color="#072827"/></linearGradient>
                            <linearGradient id="slipGlow" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#ffb020" stop-opacity="0.75"/><stop offset="100%" stop-color="#ff6b00" stop-opacity="0.2"/></linearGradient>
                        </defs>
                        <polygon points="60,170 270,85 560,195 490,320 220,355 55,265" fill="url(#slopeTop)" stroke="#2dd4bf" stroke-opacity="0.35" stroke-width="1.5"/>
                        <polygon points="55,265 220,355 490,320 490,395 220,430 55,340" fill="url(#soilWall)" stroke="#5eead4" stroke-opacity="0.22"/>
                        <path d="M170,185 C245,155 355,180 390,245 C345,285 235,285 170,235 Z" fill="url(#slipGlow)" stroke="#ffb020" stroke-width="2" stroke-dasharray="6 4"/>
                        <path d="M90,315 Q230,375 445,350" fill="none" stroke="#38bdf8" stroke-width="4" stroke-opacity="0.75"/>
                        <line x1="275" y1="210" x2="275" y2="128" stroke="#dffcf6" stroke-width="3"/>
                        <circle cx="275" cy="124" r="9" fill="#5eead4"/>
                        <line x1="175" y1="158" x2="175" y2="95" stroke="#dffcf6" stroke-width="3"/>
                        <circle cx="175" cy="91" r="8" fill="#d7ef73"/>
                        <line x1="395" y1="245" x2="395" y2="182" stroke="#dffcf6" stroke-width="3"/>
                        <circle cx="395" cy="178" r="8" fill="#5eead4"/>
                    </svg>
                    <span></span><span></span><span></span>
                </div>
                <canvas id="hero-canvas" aria-hidden="true"></canvas>
                <div class="visual-index" aria-hidden="true"><span>BLENDER 3D TWIN · SECTOR 07</span><span>LAT 21.3082° N · LON 103.9188° E</span></div>
                <div class="floating-status"><span class="status-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="m6 12 4 4 8-9"/></svg></span><div><small>Minh họa mạng quan trắc</small><strong id="hero-live-readout">Đa cảm biến · Cùng một hệ thống</strong></div></div>
                <p class="visual-note"><span></span>CHUYỂN VỊ · THẤM · MỰC NƯỚC · RUNG CHẤN</p>
            </div>
            <a class="scroll-cue" href="#story"><span>Cuộn xuống để lướt theo hành trình tín hiệu 3D</span><i aria-hidden="true"></i></a>
        </section>

        <section class="story" id="story" data-step="0" aria-labelledby="story-title">
            <div class="story-shell">
                <div class="story-copy">
                    <header class="story-heading">
                        <p class="overline">Luồng dữ liệu quan trắc · 04 Giai đoạn</p>
                        <h2 id="story-title">Dữ liệu chỉ có ý nghĩa<br>khi dẫn tới quyết định.</h2>
                        <div class="story-stepper" aria-hidden="true">
                            <span class="step-pill" data-step-indicator="0"><b>01</b> Phát hiện</span>
                            <span class="step-pill" data-step-indicator="1"><b>02</b> Bối cảnh</span>
                            <span class="step-pill" data-step-indicator="2"><b>03</b> Xác minh</span>
                            <span class="step-pill" data-step-indicator="3"><b>04</b> Phản ứng</span>
                        </div>
                    </header>
                    <div class="story-chapters">
                        <article data-story-step="0">
                            <span class="chapter-number">01 / 04</span>
                            <div>
                                <p class="chapter-label">Chuyển vị &amp; biến dạng</p>
                                <h3>Theo dõi từng thay đổi của công trình.</h3>
                                <p>Kết hợp GNSS, đo nghiêng, đo dọi, khe co giãn và giãn kế đa điểm để theo dõi chuyển vị, biến dạng tại thân đập và các vị trí quan trắc.</p>
                                <div class="chapter-telemetry" aria-label="Ví dụ dữ liệu chuyển vị">
                                    <div class="telemetry-chip"><span>Ví dụ · GNSS RTK</span><strong>+4.2 mm E · -1.8 mm U</strong></div>
                                    <div class="telemetry-chip"><span>Ví dụ · Đo nghiêng / IMU</span><strong>+0.14° Roll · 0.08g rung chấn</strong></div>
                                </div>
                            </div>
                        </article>
                        <article data-story-step="1">
                            <span class="chapter-number">02 / 04</span>
                            <div>
                                <p class="chapter-label">Thấm, thủy văn &amp; môi trường</p>
                                <h3>Không một cảm biến nào kể hết câu chuyện.</h3>
                                <p>Theo dõi áp lực thấm, lưu lượng thấm, mực nước hồ, lượng mưa và nhiệt độ. Xem từng thông số theo đúng đơn vị và vị trí lắp đặt.</p>
                                <div class="chapter-telemetry" aria-label="Ví dụ dữ liệu thủy văn">
                                    <div class="telemetry-chip"><span>Ví dụ · Lượng mưa</span><strong>68 mm/h · Tích lũy 184 mm</strong></div>
                                    <div class="telemetry-chip"><span>Ví dụ · Mực nước / áp lực thấm</span><strong>Dâng +1.45 m · 42.8 kPa</strong></div>
                                </div>
                            </div>
                        </article>
                        <article data-story-step="2">
                            <span class="chapter-number">03 / 04</span>
                            <div>
                                <p class="chapter-label">Thu thập &amp; lưu trữ tập trung</p>
                                <h3>Mỗi điểm đo có một dòng lịch sử.</h3>
                                <p>Dữ liệu từ các cảm biến được tập hợp theo dự án và trạm. Trạng thái kết nối, thời điểm cập nhật và dữ liệu lịch sử giúp đội ngũ vận hành theo dõi từng điểm đo.</p>
                                <div class="chapter-telemetry" aria-label="Thông số giai đoạn xác minh">
                                    <div class="telemetry-chip"><span>Dữ liệu đa cảm biến</span><strong>Theo dự án và trạm</strong></div>
                                    <div class="telemetry-chip"><span>Trạng thái dữ liệu</span><strong>Thời điểm cập nhật · Kết nối</strong></div>
                                </div>
                            </div>
                        </article>
                        <article data-story-step="3">
                            <span class="chapter-number">04 / 04</span>
                            <div>
                                <p class="chapter-label">Không gian vận hành</p>
                                <h3>Đúng thông tin, đến đúng người.</h3>
                                <p>Xem trạng thái công trình trên bản đồ, theo dõi biểu đồ và truy xuất dữ liệu theo thời gian. Quản lý thiết bị và xuất báo cáo trong cùng một không gian.</p>
                                <div class="chapter-telemetry" aria-label="Thông số giai đoạn phản ứng">
                                    <div class="telemetry-chip"><span>Không gian giám sát</span><strong class="text-lime">Bản đồ · Biểu đồ · Lịch sử</strong></div>
                                    <div class="telemetry-chip"><span>Quản lý dữ liệu</span><strong>Thiết bị · Điểm đo · Báo cáo</strong></div>
                                </div>
                            </div>
                        </article>
                    </div>
                </div>
                <div class="story-stage" data-pose="0">
                    <div class="story-poster" aria-hidden="true">
                        <span class="ridge ridge-back"></span><span class="ridge ridge-front"></span>
                        <i class="sensor sensor-a"></i><i class="sensor sensor-b"></i><i class="sensor sensor-c"></i>
                    </div>
                    <canvas id="story-canvas" aria-hidden="true"></canvas>
                    <div class="stage-sensors" aria-hidden="true">
                        <span data-kind="gnss">GNSS RTK</span>
                        <span data-kind="imu">Hộp MEMS IMU</span>
                        <span data-kind="rain">Gầu đo mưa</span>
                        <span data-kind="water">Piezometer ngầm</span>
                        <span data-kind="fusion">Grafana Center</span>
                    </div>
                    <div class="stage-callouts" id="stage-callouts" aria-hidden="true">
                        <div class="callout-pin is-active" data-pin="gnss_mid"><i></i><div><small>GNSS ROVER S2</small><strong id="pin-gnss-val">Δ +4.2 mm</strong></div></div>
                        <div class="callout-pin is-active" data-pin="imu_borehole"><i></i><div><small>HỘP CẢM BIẾN IMU</small><strong id="pin-imu-val">+0.14° Roll/Pitch</strong></div></div>
                        <div class="callout-pin" data-pin="rain_gauge"><i></i><div><small>GẦU ĐO MƯA LẬT</small><strong id="pin-rain-val">68 mm/h · 0.2mm</strong></div></div>
                        <div class="callout-pin" data-pin="piezometer"><i></i><div><small>PIEZOMETER HỐ KHOAN</small><strong id="pin-water-val">Nước +1.45 m · 42kPa</strong></div></div>
                        <div class="callout-pin" data-pin="ops_hub"><i></i><div><small>DATA CENTER · GRAFANA</small><strong id="pin-ops-val">Đang trực tuyến</strong></div></div>
                    </div>
                    <div class="stage-hud" aria-hidden="true">
                        <div class="hud-top"><span>SECTOR 07 / BLENDER 3D TWIN</span><span id="hud-camera-mode">CAM 01 · CẬN CẢNH GNSS &amp; HỘP IMU</span></div>
                        <div class="story-progress"><span></span></div>
                        <div class="story-caption">
                            <div><span>Minh họa luồng dữ liệu quan trắc</span><strong id="story-caption">Chuyển vị · GNSS, đo nghiêng và biến dạng công trình</strong></div>
                            <span class="story-step-badge" id="story-step-badge">BƯỚC 01 / 04</span>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <hr class="section-divider reveal" aria-hidden="true">

        <section class="network-section" id="network" aria-labelledby="network-title">
            <div class="section-index" aria-hidden="true">02 — NETWORK PULSE</div>
            <div class="section-intro reveal"><div><p class="overline">Dữ liệu vận hành</p><h2 id="network-title">Trạng thái mạng quan trắc</h2></div><div class="updated" id="metrics-status" role="status" aria-live="polite"><span aria-hidden="true"></span><span>Đang tải trạng thái mạng…</span><button type="button" id="metrics-retry" hidden>Thử lại</button></div></div>
            <div class="metric-grid" id="metric-grid" aria-live="polite" aria-busy="true"><article class="metric-card metric-total reveal"><span class="card-shine" aria-hidden="true"></span><span>Toàn mạng</span><strong id="stations-total">—</strong><p>điểm được quản lý</p><i aria-hidden="true"></i></article><article class="metric-card metric-online reveal"><span class="card-shine" aria-hidden="true"></span><span>Đang trực tuyến</span><strong id="stations-online">—</strong><p>đang gửi dữ liệu</p><i aria-hidden="true"></i></article><article class="metric-card metric-stale reveal"><span class="card-shine" aria-hidden="true"></span><span>Cần chú ý</span><strong id="stations-stale">—</strong><p>luồng dữ liệu chậm</p><i aria-hidden="true"></i></article><article class="metric-card metric-offline reveal"><span class="card-shine" aria-hidden="true"></span><span>Ngoại tuyến</span><strong id="stations-offline">—</strong><p>chưa có tín hiệu</p><i aria-hidden="true"></i></article></div>
            <p class="data-note reveal">Dữ liệu mạng được lấy trực tiếp từ hệ thống vận hành. Trạng thái luôn đi kèm thời điểm cập nhật và khả năng thử lại.</p>
        </section>

        <hr class="section-divider reveal" aria-hidden="true">

        <section class="final-cta reveal" id="response" aria-labelledby="cta-title">
            <div class="cta-contours" aria-hidden="true"><span></span><span></span><span></span></div>
            <div class="cta-copy"><p class="overline">Từ nhận biết đến hành động</p><h2 id="cta-title">Truy cập hệ thống quan trắc</h2><p>Mở không gian vận hành để xem từng khu vực, từng điểm quan trắc và trạng thái mới nhất.</p><div class="hero-actions"><a class="button button-inverse button-large" href="/map">Mở bản đồ realtime <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5"/></svg></a><a class="button button-outline button-large" href="/login?return_to=%2Fmap">Đăng nhập vận hành</a></div></div>
            <div class="cta-meta" aria-hidden="true"><span>AITOGY / MONITORING</span><span>CONTINUOUS OBSERVATION</span></div>
        </section>
    </main>

    <footer class="site-footer">
        <div class="footer-intro"><a class="brand footer-brand" href="/"><span class="brand-plate"><img src="${logoUrl}" width="759" height="329" alt="Aitogy"></span><span class="brand-product"><strong>Monitoring</strong><small>Quan trắc</small></span></a><p>Một nền tảng cho quan trắc đập, công trình và môi trường.</p></div>
        <address class="footer-contact" aria-label="Thông tin liên hệ Aitogy"><strong>Liên hệ Aitogy</strong><a href="tel:+84912844919"><span>Điện thoại</span>+84 912 844 919</a><a href="mailto:aitogyaitogy@gmail.com"><span>Email</span>aitogyaitogy@gmail.com</a><a href="https://www.google.com/maps/search/?api=1&amp;query=S%E1%BB%91%2016B%20Ng%C3%B5%20187%20ph%E1%BB%91%20Mai%20D%E1%BB%8Bch%2C%20Ph%C6%B0%E1%BB%9Dng%20Ph%C3%BA%20Di%E1%BB%85n%2C%20H%C3%A0%20N%E1%BB%99i" target="_blank" rel="noopener noreferrer"><span>Địa chỉ</span>Số 16B Ngõ 187 phố Mai Dịch, Phường Phú Diễn, Hà Nội</a></address>
        <div class="footer-meta"><a href="https://www.facebook.com/profile.php?id=100062949955358" target="_blank" rel="noopener noreferrer">Facebook</a><span>© 2026 Aitogy</span></div>
    </footer>
    <div class="quality-toast" id="quality-toast" aria-live="polite" hidden><button class="toast-dismiss" type="button" aria-label="Đóng">×</button><p></p><button type="button" class="toast-action">Bật chế độ tiết kiệm</button></div>`;
}
