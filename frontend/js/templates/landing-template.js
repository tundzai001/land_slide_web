export function renderLandingTemplate(logoUrl = '/assets/aitogy.png') {
    return `
    <div class="noise-overlay" aria-hidden="true"></div>
    <div class="scroll-progress" aria-hidden="true"><span class="scroll-progress-fill"></span></div>
    <a class="skip-link" href="#main">Bỏ qua đến nội dung chính</a>
    <header class="site-header">
        <div class="header-inner">
            <a class="brand" href="/" aria-label="Aitogy Landslide Monitor — Trang chủ"><span class="brand-plate"><img src="${logoUrl}" width="759" height="329" alt="Aitogy"></span><span class="brand-rule" aria-hidden="true"></span><span class="brand-product"><strong>Landslide</strong><small>Monitor</small></span></a>
            <nav class="desktop-nav" aria-label="Điều hướng chính"><a href="#story"><span>01</span> Hành trình tín hiệu</a><a href="#network"><span>02</span> Trạng thái mạng</a><a href="#response"><span>03</span> Hành động</a></nav>
            <div class="header-actions">
                <button class="icon-button" id="theme-toggle" type="button" aria-label="Chuyển giao diện tối"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v2m0 14v2m9-9h-2M5 12H3m15.36-6.36-1.42 1.42M7.06 16.94l-1.42 1.42m12.72 0-1.42-1.42M7.06 7.06 5.64 5.64"/><circle cx="12" cy="12" r="4"/></svg></button>
                <a class="button button-ghost login-link" id="auth-link" href="/login?return_to=%2Fmanagement">Đăng nhập</a><a class="button button-primary header-cta" href="/map">Mở bản đồ</a>
                <button class="menu-button" id="menu-toggle" type="button" aria-expanded="false" aria-controls="mobile-menu" aria-label="Mở trình đơn"><span></span><span></span><span></span></button>
            </div>
        </div>
        <nav class="mobile-menu" id="mobile-menu" aria-label="Điều hướng di động" hidden><a href="#story">Hành trình tín hiệu</a><a href="#network">Trạng thái mạng</a><a href="#response">Hành động</a><a href="/map">Mở bản đồ realtime</a><a href="/login?return_to=%2Fmanagement">Đăng nhập</a></nav>
    </header>

    <main id="main">
        <section class="hero" aria-labelledby="hero-title">
            <div class="hero-grid" aria-hidden="true"></div>
            <div class="hero-aurora hero-aurora-a" aria-hidden="true"></div><div class="hero-aurora hero-aurora-b" aria-hidden="true"></div>
            <div class="hero-copy">
                <p class="eyebrow hero-kicker"><span class="live-dot"></span>Hệ thống quan trắc địa kỹ thuật · Mô hình 3D</p>
                <h1 id="hero-title"><span>Nhìn thấy chuyển động.</span><br><em>Trước khi thành rủi ro.</em></h1>
                <p class="hero-lead">Từ những vi dịch chuyển cấp milimét trong lòng sườn dốc đến bản sao số 3D thời gian thực — hợp nhất GNSS RTK, IMU lỗ khoan, lượng mưa và áp lực nước ngầm để cảnh báo sớm có căn cứ.</p>
                <div class="hero-actions"><a class="button button-primary button-large" href="/map">Xem bản đồ realtime <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5"/></svg></a><a class="button button-ghost button-large" href="#story">Cuộn xem câu chuyện 3D</a></div>
                <div class="signal-proof" aria-label="Ba bước vận hành"><span><b>01</b> Phát hiện ±2mm</span><i></i><span><b>02</b> Xác minh đa tầng</span><i></i><span><b>03</b> Phản ứng tức thời</span></div>
            </div>
            <div class="hero-visual" aria-label="Mô hình địa hình quan trắc ba chiều dựng bằng Blender">
                <div class="sensor-legend" aria-hidden="true"><span data-sensor="gnss"><i></i>GNSS RTK</span><span data-sensor="imu"><i></i>IMU Lỗ khoan</span><span data-sensor="rain"><i></i>Trạm mưa</span><span data-sensor="water"><i></i>Nước ngầm</span></div>
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
                <div class="floating-status"><span class="status-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="m6 12 4 4 8-9"/></svg></span><div><small>Mô hình địa chất 3D thời gian thực</small><strong id="hero-live-readout">GNSS RTK Fixed · 4 trạm đồng bộ</strong></div></div>
                <p class="visual-note"><span></span>BLENDER GLB · GNSS · IMU · PIEZOMETER</p>
            </div>
            <a class="scroll-cue" href="#story"><span>Cuộn xuống để lướt theo hành trình tín hiệu 3D</span><i aria-hidden="true"></i></a>
        </section>

        <section class="story" id="story" data-step="0" aria-labelledby="story-title">
            <div class="story-shell">
                <div class="story-copy">
                    <header class="story-heading">
                        <p class="overline">Hành trình kể chuyện động 3D · 04 Giai đoạn</p>
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
                                <p class="chapter-label">Phát hiện · Vi dịch chuyển khởi phát</p>
                                <h3>Chuyển động bắt đầu rất nhỏ.</h3>
                                <p>Tại đới trượt sườn giữa, trạm GNSS RTK ghi nhận dịch chuyển cấp milimét trong khi chuỗi cảm biến IMU lỗ khoan phát hiện biến dạng uốn dọc theo mặt trượt ngầm.</p>
                                <div class="chapter-telemetry" aria-label="Thông số giai đoạn phát hiện">
                                    <div class="telemetry-chip"><span>GNSS Rover S2</span><strong>+4.2 mm E · -1.8 mm Z</strong></div>
                                    <div class="telemetry-chip"><span>IMU Lỗ khoan (-6m)</span><strong>+0.14° nghiêng trục X</strong></div>
                                </div>
                            </div>
                        </article>
                        <article data-story-step="1">
                            <span class="chapter-number">02 / 04</span>
                            <div>
                                <p class="chapter-label">Bối cảnh · Tương quan thủy văn &amp; địa chất</p>
                                <h3>Không một cảm biến nào kể hết câu chuyện.</h3>
                                <p>Mưa lớn kéo dài làm nước thấm qua tầng đất phong hóa. Giếng quan trắc Piezometer ghi nhận mực nước ngầm dâng cao, làm tăng áp lực nước lỗ rỗng ngay sát mặt trượt.</p>
                                <div class="chapter-telemetry" aria-label="Thông số giai đoạn bối cảnh">
                                    <div class="telemetry-chip"><span>Cường độ mưa</span><strong>68 mm/h · Tích lũy 184 mm</strong></div>
                                    <div class="telemetry-chip"><span>Mực nước ngầm</span><strong>Dâng +1.45 m (Áp lực cao)</strong></div>
                                </div>
                            </div>
                        </article>
                        <article data-story-step="2">
                            <span class="chapter-number">03 / 04</span>
                            <div>
                                <p class="chapter-label">Xác minh · Hợp nhất &amp; Bình sai cụm trạm</p>
                                <h3>Tách nhiễu khỏi tín hiệu cần chú ý.</h3>
                                <p>Hệ thống tự động bình sai đường cơ sở từ trạm Base CORS trên đá gốc tới 3 trạm Rover, đối chiếu chéo với IMU và áp lực nước để khoanh vùng khối trượt thực tế.</p>
                                <div class="chapter-telemetry" aria-label="Thông số giai đoạn xác minh">
                                    <div class="telemetry-chip"><span>Tương quan đa cảm biến</span><strong>98.4% · Đã lọc nhiễu</strong></div>
                                    <div class="telemetry-chip"><span>Phân loại sự kiện</span><strong class="text-amber">CẦN XÁC MINH KHẨN</strong></div>
                                </div>
                            </div>
                        </article>
                        <article data-story-step="3">
                            <span class="chapter-number">04 / 04</span>
                            <div>
                                <p class="chapter-label">Phản ứng · Cảnh báo sớm &amp; Điều phối</p>
                                <h3>Đúng thông tin, đến đúng người.</h3>
                                <p>Tín hiệu đã kiểm chứng hội tụ về trung tâm điều hành Operations Hub và kích hoạt cổng cảnh báo trên tuyến đường đèo dưới chân taluy trước khi sạt lở xảy ra.</p>
                                <div class="chapter-telemetry" aria-label="Thông số giai đoạn phản ứng">
                                    <div class="telemetry-chip"><span>Operations Node</span><strong class="text-lime">ĐÃ TIẾP NHẬN (&lt; 1.2s)</strong></div>
                                    <div class="telemetry-chip"><span>Hành lang bảo vệ</span><strong>Cảnh báo tuyến đường chân dốc</strong></div>
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
                        <span data-kind="imu">IMU Lỗ khoan</span>
                        <span data-kind="rain">Lượng mưa</span>
                        <span data-kind="water">Nước ngầm</span>
                        <span data-kind="fusion">Hợp nhất 3D</span>
                    </div>
                    <div class="stage-callouts" id="stage-callouts" aria-hidden="true">
                        <div class="callout-pin is-active" data-pin="gnss_mid"><i></i><div><small>GNSS ROVER S2</small><strong id="pin-gnss-val">Δ +4.2 mm</strong></div></div>
                        <div class="callout-pin is-active" data-pin="imu_borehole"><i></i><div><small>IMU LỖ KHOAN</small><strong id="pin-imu-val">+0.14° mặt trượt</strong></div></div>
                        <div class="callout-pin" data-pin="rain_gauge"><i></i><div><small>TRẠM MƯA</small><strong id="pin-rain-val">68 mm/h</strong></div></div>
                        <div class="callout-pin" data-pin="piezometer"><i></i><div><small>PIEZOMETER</small><strong id="pin-water-val">Nước +1.45 m</strong></div></div>
                        <div class="callout-pin" data-pin="ops_hub"><i></i><div><small>OPERATIONS HUB</small><strong id="pin-ops-val">Đã kích hoạt</strong></div></div>
                    </div>
                    <div class="stage-hud" aria-hidden="true">
                        <div class="hud-top"><span>SECTOR 07 / BLENDER 3D TWIN</span><span id="hud-camera-mode">CAM 01 · CẬN CẢNH ĐỚI TRƯỢT</span></div>
                        <div class="story-progress"><span></span></div>
                        <div class="story-caption">
                            <div><span>Trạng thái mô phỏng địa kỹ thuật</span><strong id="story-caption">Phát hiện · Vector dịch chuyển GNSS + IMU</strong></div>
                            <span class="story-step-badge" id="story-step-badge">BƯỚC 01 / 04</span>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <hr class="section-divider reveal" aria-hidden="true">

        <section class="network-section" id="network" aria-labelledby="network-title">
            <div class="section-index" aria-hidden="true">02 — NETWORK PULSE</div>
            <div class="section-intro reveal"><div><p class="overline">Bức tranh đang diễn ra</p><h2 id="network-title">Không phải một bản báo cáo.<br><em>Là trạng thái ngay lúc này.</em></h2></div><div class="updated" id="metrics-status" role="status" aria-live="polite"><span aria-hidden="true"></span><span>Đang tải trạng thái mạng…</span><button type="button" id="metrics-retry" hidden>Thử lại</button></div></div>
            <div class="metric-grid" id="metric-grid" aria-live="polite" aria-busy="true"><article class="metric-card metric-total reveal"><span class="card-shine" aria-hidden="true"></span><span>Toàn mạng</span><strong id="stations-total">—</strong><p>điểm được quản lý</p><i aria-hidden="true"></i></article><article class="metric-card metric-online reveal"><span class="card-shine" aria-hidden="true"></span><span>Đang trực tuyến</span><strong id="stations-online">—</strong><p>đang gửi dữ liệu</p><i aria-hidden="true"></i></article><article class="metric-card metric-stale reveal"><span class="card-shine" aria-hidden="true"></span><span>Cần chú ý</span><strong id="stations-stale">—</strong><p>luồng dữ liệu chậm</p><i aria-hidden="true"></i></article><article class="metric-card metric-offline reveal"><span class="card-shine" aria-hidden="true"></span><span>Ngoại tuyến</span><strong id="stations-offline">—</strong><p>chưa có tín hiệu</p><i aria-hidden="true"></i></article></div>
            <p class="data-note reveal">Dữ liệu mạng được lấy trực tiếp từ hệ thống vận hành. Trạng thái luôn đi kèm thời điểm cập nhật và khả năng thử lại.</p>
        </section>

        <hr class="section-divider reveal" aria-hidden="true">

        <section class="final-cta reveal" id="response" aria-labelledby="cta-title">
            <div class="cta-contours" aria-hidden="true"><span></span><span></span><span></span></div>
            <div class="cta-copy"><p class="overline">Từ nhận biết đến hành động</p><h2 id="cta-title">Thấy toàn cảnh.<br><em>Đi đúng bước tiếp theo.</em></h2><p>Mở không gian vận hành để xem từng khu vực, từng điểm quan trắc và trạng thái mới nhất.</p><div class="hero-actions"><a class="button button-inverse button-large" href="/map">Mở bản đồ realtime <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5"/></svg></a><a class="button button-outline button-large" href="/login?return_to=%2Fmanagement">Đăng nhập vận hành</a></div></div>
            <div class="cta-meta" aria-hidden="true"><span>AITOGY / LANDSLIDE MONITOR</span><span>CONTINUOUS OBSERVATION</span></div>
        </section>
    </main>

    <footer class="site-footer">
        <div class="footer-intro"><a class="brand footer-brand" href="/"><span class="brand-plate"><img src="${logoUrl}" width="759" height="329" alt="Aitogy"></span><span class="brand-product"><strong>Landslide</strong><small>Monitor</small></span></a><p>Quan trắc liên tục để hành động sớm hơn.</p></div>
        <address class="footer-contact" aria-label="Thông tin liên hệ Aitogy"><strong>Liên hệ Aitogy</strong><a href="tel:+84912844919"><span>Điện thoại</span>+84 912 844 919</a><a href="mailto:aitogyaitogy@gmail.com"><span>Email</span>aitogyaitogy@gmail.com</a><a href="https://www.google.com/maps/search/?api=1&amp;query=S%E1%BB%91%2016B%20Ng%C3%B5%20187%20ph%E1%BB%91%20Mai%20D%E1%BB%8Bch%2C%20Ph%C6%B0%E1%BB%9Dng%20Ph%C3%BA%20Di%E1%BB%85n%2C%20H%C3%A0%20N%E1%BB%99i" target="_blank" rel="noopener noreferrer"><span>Địa chỉ</span>Số 16B Ngõ 187 phố Mai Dịch, Phường Phú Diễn, Hà Nội</a></address>
        <div class="footer-meta"><a href="https://www.facebook.com/profile.php?id=100062949955358" target="_blank" rel="noopener noreferrer">Facebook</a><span>© 2026 Aitogy</span></div>
    </footer>
    <div class="quality-toast" id="quality-toast" aria-live="polite" hidden><button class="toast-dismiss" type="button" aria-label="Đóng">×</button><p></p><button type="button" class="toast-action">Bật chế độ tiết kiệm</button></div>`;
}
