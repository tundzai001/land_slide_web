/* Route bootstrap without a browser-side JSX compiler. Legacy DOM ids remain unchanged. */
(() => {
    'use strict';

    const root = document.getElementById('app-root');
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'light' || savedTheme === 'dark') document.documentElement.dataset.theme = savedTheme;
    const loaded = new Map();
    const CDN = {
        iconsCss: 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css',
        bootstrapCss: 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
        bootstrapJs: 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js',
        sweetalert: 'https://cdn.jsdelivr.net/npm/sweetalert2@11',
        leafletCss: 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
        clusterCss: 'https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css',
        clusterDefaultCss: 'https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css',
        leaflet: 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
        cluster: 'https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js',
        heat: 'https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js',
        chart: 'https://cdn.jsdelivr.net/npm/chart.js',
        qr: 'https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js',
        pdf: 'https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js'
    };

    function loadStyle(href) {
        const key = `css:${href}`;
        if (loaded.has(key)) return loaded.get(key);
        const promise = new Promise((resolve, reject) => {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = href;
            link.onload = resolve;
            link.onerror = () => reject(new Error(`Không tải được ${href}`));
            document.head.appendChild(link);
        });
        loaded.set(key, promise);
        return promise;
    }

    function loadScript(src, type) {
        const key = `js:${src}`;
        if (loaded.has(key)) return loaded.get(key);
        const promise = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = src;
            script.async = false;
            if (type) script.type = type;
            script.onload = resolve;
            script.onerror = () => reject(new Error(`Không tải được ${src}`));
            document.body.appendChild(script);
        });
        loaded.set(key, promise);
        return promise;
    }

    window.loadFeatureLibrary = async function loadFeatureLibrary(name) {
        if (name === 'qr') return loadScript(CDN.qr);
        if (name === 'pdf') return loadScript(CDN.pdf);
        if (name === 'chart') return loadScript(CDN.chart);
        if (name === 'heat') return loadScript(CDN.heat);
        if (name === 'digital-twin') return loadScript('/assets/digital-twin.min.js?v=__BUILD_VERSION__', 'module');
        throw new Error(`Thư viện không được hỗ trợ: ${name}`);
    };

    function safeReturnTo() {
        const value = new URLSearchParams(location.search).get('return_to');
        return value === '/management' || value === '/map' ? value : '/map';
    }

    function renderLogin() {
        document.documentElement.dataset.appView = 'login';
        document.title = 'Đăng nhập · Monitoring';
        root.innerHTML = `
        <main class="login-page">
            <section class="login-visual" aria-hidden="true">
                <div class="login-brand">
                    <span class="app-brand-plate"><img src="/assets/aitogy.png?v=__BUILD_VERSION__" width="759" height="329" alt="Aitogy"></span>
                    <span class="app-brand-product"><strong>Monitoring</strong><small>Quan trắc</small></span>
                </div>
                <div class="login-network login-capabilities">
                    <span class="login-capabilities-title">AITOGY MONITORING</span>
                    <div><i class="bi bi-map" aria-hidden="true"></i><span><strong>Bản đồ quan trắc</strong><small>Vị trí trạm và trạng thái kết nối</small></span></div>
                    <div><i class="bi bi-graph-up" aria-hidden="true"></i><span><strong>Dữ liệu &amp; phân tích</strong><small>Số liệu hiện tại và lịch sử quan trắc</small></span></div>
                    <div><i class="bi bi-sliders" aria-hidden="true"></i><span><strong>Quản lý vận hành</strong><small>Dự án, thiết bị và quyền truy cập</small></span></div>
                </div>
                <div class="login-visual-copy">
                    <div class="login-kicker">Không gian điều hành</div>
                    <h1>Quan trắc công trình<br>và môi trường.</h1>
                    <p>Quản lý dự án, trạm và cảm biến. Theo dõi dữ liệu quan trắc đập, công trình và môi trường trong cùng một không gian.</p>
                </div>
            </section>
            <section class="login-panel">
                <div class="login-form-wrap">
                    <div class="login-toolbar">
                        <a href="/" class="login-back"><i class="bi bi-arrow-left"></i><span>Về trang chủ</span></a>
                        <button type="button" class="login-theme" id="login-theme" aria-label="Chuyển giao diện tối" aria-pressed="false"><svg class="theme-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20.2 15.6A8.6 8.6 0 0 1 8.4 3.8 8.6 8.6 0 1 0 20.2 15.6Z"/></svg><svg class="theme-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.6"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg></button>
                    </div>
                    <div class="login-card">
                        <div class="login-card-head">
                            <div class="login-icon"><i class="bi bi-shield-lock"></i></div>
                            <div class="login-heading-copy"><span>Cổng vận hành</span><h2>Đăng nhập hệ thống</h2><p class="login-subtitle">Sử dụng tài khoản được cấp để mở bản đồ quan trắc.</p></div>
                        </div>
                        <form id="login-form" class="login-form" novalidate>
                            <label class="login-field" for="login-username"><span>Tài khoản</span><div class="login-input-shell"><i class="bi bi-person"></i><input id="login-username" name="username" autocomplete="username" placeholder="Nhập tài khoản" required autofocus></div></label>
                            <label class="login-field" for="login-password"><span>Mật khẩu</span><div class="login-password-row"><i class="bi bi-key"></i><input id="login-password" name="password" type="password" autocomplete="current-password" placeholder="Nhập mật khẩu" required><button id="toggle-password" type="button" aria-label="Hiện mật khẩu"><i class="bi bi-eye"></i></button></div></label>
                            <label class="login-check"><input id="login-remember" type="checkbox" checked><span>Ghi nhớ đăng nhập trên thiết bị này</span></label>
                            <div id="login-error" class="login-error" role="alert" aria-live="assertive" hidden><i class="bi bi-exclamation-circle"></i><span></span></div>
                            <button id="login-submit" class="login-submit" type="submit"><span>Đăng nhập</span><i class="bi bi-arrow-right"></i></button>
                        </form>
                        <p class="login-security-note"><i class="bi bi-lock"></i> Aitogy Monitoring · Truy cập theo phân quyền</p>
                    </div>
                </div>
            </section>
        </main>`;
        const password = document.getElementById('login-password');
        const themeButton = document.getElementById('login-theme');
        const updateThemeButton = () => {
            const isDark = document.documentElement.dataset.theme === 'dark';
            themeButton.setAttribute('aria-label', `Chuyển giao diện ${isDark ? 'sáng' : 'tối'}`);
            themeButton.setAttribute('aria-pressed', String(isDark));
        };
        updateThemeButton();
        themeButton.addEventListener('click', () => {
            const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
            document.documentElement.dataset.theme = next;
            localStorage.setItem('theme', next);
            updateThemeButton();
        });
        document.getElementById('toggle-password').addEventListener('click', (event) => {
            const visible = password.type === 'text';
            password.type = visible ? 'password' : 'text';
            event.currentTarget.setAttribute('aria-label', visible ? 'Hiện mật khẩu' : 'Ẩn mật khẩu');
            event.currentTarget.querySelector('i').className = visible ? 'bi bi-eye' : 'bi bi-eye-slash';
        });
        document.getElementById('login-form').addEventListener('submit', async (event) => {
            event.preventDefault();
            const error = document.getElementById('login-error');
            const submit = document.getElementById('login-submit');
            const username = document.getElementById('login-username');
            error.hidden = true;
            username.removeAttribute('aria-invalid');
            password.removeAttribute('aria-invalid');
            if (!username.value.trim() || !password.value) {
                error.querySelector('span').textContent = 'Vui lòng nhập tài khoản và mật khẩu.';
                error.hidden = false;
                (!username.value.trim() ? username : password).setAttribute('aria-invalid', 'true');
                (!username.value.trim() ? username : password).focus();
                return;
            }
            submit.disabled = true;
            submit.setAttribute('aria-busy', 'true');
            submit.querySelector('span').textContent = 'Đang đăng nhập…';
            submit.querySelector('i').className = 'spinner-border spinner-border-sm';
            try {
                const body = new URLSearchParams({username: username.value.trim(), password: password.value});
                if (document.getElementById('login-remember').checked) body.set('scope', 'remember_me');
                const response = await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-Session-Mode': 'cookie'}, body, signal: AbortSignal.timeout(15000)});
                if (!response.ok) throw new Error(response.status === 401 ? 'Tài khoản hoặc mật khẩu không đúng.' : 'Không thể đăng nhập. Vui lòng thử lại.');
                location.replace(safeReturnTo());
            } catch (reason) {
                error.querySelector('span').textContent = reason.name === 'TimeoutError' ? 'Máy chủ phản hồi quá chậm. Vui lòng thử lại.' : reason.message;
                error.hidden = false;
            } finally {
                submit.disabled = false;
                submit.removeAttribute('aria-busy');
                submit.querySelector('span').textContent = 'Đăng nhập';
                submit.querySelector('i').className = 'bi bi-arrow-right';
            }
        });
    }

    const sharedStyles = [CDN.iconsCss, CDN.bootstrapCss];
    const mapStyles = ['/assets/map.min.css?v=__BUILD_VERSION__'];
    const adminStyles = ['/assets/admin.min.css?v=__BUILD_VERSION__'];

    async function loadOrdered(items) { for (const item of items) await loadScript(item); }
    function setupAdminMobileNavigation() {
        const navigation = document.getElementById('mobile-bottom-nav');
        if (!navigation) return;
        navigation.innerHTML = `
            <button type="button" data-tab="tab-projects"><i class="bi bi-folder"></i><span>Dự án</span></button>
            <button type="button" data-tab="tab-pi"><i class="bi bi-cpu"></i><span>Thiết bị</span></button>
            <button type="button" data-tab="tab-rescue"><i class="bi bi-life-preserver"></i><span>Cứu hộ</span></button>
            <button type="button" data-tab="tab-database"><i class="bi bi-database"></i><span>Dữ liệu</span></button>
            <button type="button" data-more><i class="bi bi-grid"></i><span>Thêm</span></button>
            <div class="admin-more-sheet" hidden>
                <button type="button" data-tab="tab-users"><i class="bi bi-people"></i> Người dùng</button>
                <button type="button" data-tab="tab-simulations"><i class="bi bi-boxes"></i> Simulation audit</button>
                <button type="button" data-tab="tab-operations"><i class="bi bi-journal-check"></i> Vận hành</button>
                <button type="button" data-logout-action><i class="bi bi-box-arrow-right"></i> Đăng xuất</button>
            </div>`;
        if (window.rescueFeatureEnabled === false) navigation.querySelector('[data-tab="tab-rescue"]')?.remove();
        const more = navigation.querySelector('.admin-more-sheet');
        navigation.addEventListener('click', (event) => {
            const button = event.target.closest('button');
            if (!button) return;
            if ('more' in button.dataset) { more.hidden = !more.hidden; return; }
            if ('themeAction' in button.dataset) { document.getElementById('theme-toggle')?.click(); more.hidden = true; return; }
            if ('logoutAction' in button.dataset) { document.getElementById('logout-btn')?.click(); return; }
            const tab = button.dataset.tab;
            if (tab) {
                window.adminManager?.switchTab(tab, button);
                more.hidden = true;
            }
        });
    }
    function setupAdminResponsiveTables() {
        const annotate = () => {
            document.querySelectorAll('.custom-table table').forEach(table => {
                const labels = Array.from(table.querySelectorAll('thead th')).map(cell => cell.textContent.trim());
                table.querySelectorAll('tbody tr').forEach(row => {
                    Array.from(row.children).forEach((cell, index) => {
                        if (!cell.dataset.label) cell.dataset.label = labels[index] || '';
                    });
                });
            });
        };
        annotate();
        new MutationObserver(annotate).observe(document.getElementById('admin-tab-content'), {childList: true, subtree: true});
    }
    function setupAdminDrawerAccessibility() {
        const drawers = [
            ['rescue-inspector', '.rescue-case'],
            ['db-inspector', '.db-row'],
        ];
        const triggers = new Map();
        document.addEventListener('click', event => {
            drawers.forEach(([id, selector]) => {
                if (event.target.closest(selector)) triggers.set(id, event.target.closest(selector));
            });
        }, true);
        document.addEventListener('keydown', event => {
            const entry = drawers.find(([id]) => document.getElementById(id)?.classList.contains('open'));
            if (!entry) return;
            const drawer = document.getElementById(entry[0]);
            if (event.key === 'Escape') {
                event.preventDefault();
                drawer.querySelector('header button')?.click();
                triggers.get(entry[0])?.focus?.({ preventScroll: true });
                return;
            }
            if (event.key !== 'Tab') return;
            const focusable = Array.from(drawer.querySelectorAll('a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])')).filter(element => element.offsetParent !== null);
            if (!focusable.length) return;
            const first = focusable[0], last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        });
    }
    async function bootLegacy(view) {
        document.documentElement.dataset.appView = view;
        if (view === 'admin') root.dataset.privateContent = '';
        else delete root.dataset.privateContent;
        document.title = view === 'map' ? 'Bản đồ realtime · Monitoring' : 'Quản trị · Monitoring';
        const rescueAvailability = fetch('/api/public/rescue-config', {
            cache: 'no-store', signal: AbortSignal.timeout(3000),
        }).then(response => response.ok ? response.json() : null)
          .then(config => config?.enabled === true).catch(() => false);
        await Promise.all((view === 'map' ? mapStyles : adminStyles).concat(sharedStyles).map(loadStyle));
        window.rescueFeatureEnabled = await rescueAvailability;
        await loadScript('/assets/shared.min.js?v=__BUILD_VERSION__');
        await loadScript(CDN.bootstrapJs);
        await loadScript(CDN.sweetalert);
        if (view === 'map') {
            await loadStyle(CDN.leafletCss); await loadStyle(CDN.clusterCss); await loadStyle(CDN.clusterDefaultCss);
            await loadScript(CDN.leaflet); await loadScript(CDN.cluster);
            window.__MAP_BUNDLE_LOADING__ = true;
            await loadScript('/assets/map-app.min.js?v=__BUILD_VERSION__');
            root.innerHTML = window.LegacyTemplates.map;
            window.themeManager?.updateToggleIcon();
            if (!window.rescueFeatureEnabled) {
                root.querySelector('.layer-toggle-switch')?.remove();
                root.querySelector('#layer-rescue')?.closest('label')?.remove();
                root.querySelectorAll('[data-map-action="rescue"], #btn-guest-rescue, #guestRescueModal').forEach(element => element.remove());
            }
            window.__MAP_BUNDLE_LOADING__ = false;
            window.flushMapReadyQueue?.();
        } else {
            await loadScript('/assets/admin-app.min.js?v=__BUILD_VERSION__');
            root.innerHTML = window.LegacyTemplates.admin;
            window.themeManager?.updateToggleIcon();
            if (!window.rescueFeatureEnabled) {
                root.querySelector('[data-tab="tab-rescue"]')?.closest('.nav-item')?.remove();
                root.querySelector('#tab-rescue')?.remove();
            }
            root.querySelector('#session-manager-btn')?.addEventListener('click', () => void window.authManager?.openSessions());
            setupAdminMobileNavigation();
            setupAdminResponsiveTables();
            setupAdminDrawerAccessibility();
            await window.bootstrapAdminManager?.();
            window.bootstrapDatabaseManager?.();
        }
        setTimeout(() => window.authManager?.updateAuthUI?.(), 50);
    }

    async function start() {
        let end = location.pathname.length;
        while (end > 0 && location.pathname[end - 1] === '/') end -= 1;
        const path = location.pathname.slice(0, end) || '/';
        if (path === '/login') {
            const session = await window.authSession.inspect();
            if (session.status === 'authenticated') {
                location.replace(safeReturnTo());
                return;
            }
            await loadStyle('/assets/login.min.css?v=__BUILD_VERSION__');
            loadStyle(CDN.iconsCss).catch(() => {});
            renderLogin();
            return;
        }
        const session = await window.authSession.inspect();
        if (session.status === 'anonymous') {
            location.replace(`/login?return_to=${encodeURIComponent(path === '/management' || path === '/admin' ? '/management' : '/map')}`);
            return;
        }
        if (session.status === 'unavailable') {
            root.innerHTML = '<main class="route-error"><h1>Không thể kiểm tra phiên đăng nhập</h1><p>Máy chủ chưa phản hồi. Thử lại sau ít phút.</p><button type="button" id="retry-session">Thử lại</button></main>';
            root.querySelector('#retry-session')?.addEventListener('click', () => location.reload());
            return;
        }
        const view = path === '/management' || path === '/admin' ? 'admin' : 'map';
        await bootLegacy(view);
    }

    start().catch((error) => {
        console.error(error);
        root.innerHTML = '<main class="route-error"><h1>Không thể tải giao diện</h1><p id="route-error-detail"></p><button type="button" id="retry-route">Thử lại</button></main>';
        root.querySelector('#route-error-detail').textContent = String(error.message || error);
        root.querySelector('#retry-route').addEventListener('click', () => location.reload());
    });
})();
