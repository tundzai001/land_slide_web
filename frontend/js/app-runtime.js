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
        if (name === 'digital-twin') return loadScript('/assets/digital-twin.min.js?v=__BUILD_VERSION__', 'module');
        throw new Error(`Thư viện không được hỗ trợ: ${name}`);
    };

    function safeReturnTo() {
        const value = new URLSearchParams(location.search).get('return_to');
        return value && value.startsWith('/') && !value.startsWith('//') ? value : '/management';
    }

    function renderLogin() {
        document.documentElement.dataset.appView = 'login';
        document.title = 'Đăng nhập · Landslide Monitor';
        root.innerHTML = `
        <main class="login-page">
            <section class="login-visual" aria-hidden="true">
                <div class="login-brand"><span class="login-brand-icon">⌁</span><span>Landslide Monitor</span></div>
                <div class="login-visual-copy"><div class="login-kicker">TRUNG TÂM GIÁM SÁT</div>
                    <h1>Quản lý vận hành hệ thống quan trắc</h1>
                    <p>Theo dõi trạm, cấu hình cảnh báo và phân quyền truy cập trong một giao diện duy nhất.</p>
                </div>
            </section>
            <section class="login-panel">
                <div class="login-form-wrap">
                    <div class="login-toolbar"><a href="/" class="login-back">← <span>Về trang chủ</span></a><button type="button" class="login-back" id="login-theme" aria-label="Đổi giao diện">◐</button></div>
                    <div class="login-card">
                        <div class="login-card-head"><div class="login-icon">♙</div><div><h2>Đăng nhập</h2><p class="login-subtitle">Truy cập hệ thống giám sát</p></div></div>
                        <form id="login-form" class="login-form" novalidate>
                            <label class="login-field" for="login-username"><span>Tài khoản</span><input id="login-username" name="username" autocomplete="username" required autofocus></label>
                            <label class="login-field" for="login-password"><span>Mật khẩu</span><div class="login-password-row"><input id="login-password" name="password" type="password" autocomplete="current-password" required><button id="toggle-password" type="button" aria-label="Hiện mật khẩu">◉</button></div></label>
                            <label class="login-check"><input id="login-remember" type="checkbox" checked><span>Ghi nhớ đăng nhập</span></label>
                            <div id="login-error" class="login-error" role="alert" hidden></div>
                            <button id="login-submit" class="login-submit" type="submit">Đăng nhập</button>
                        </form>
                    </div>
                </div>
            </section>
        </main>`;
        const password = document.getElementById('login-password');
        document.getElementById('login-theme').addEventListener('click', () => {
            const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
            document.documentElement.dataset.theme = next;
            localStorage.setItem('theme', next);
        });
        document.getElementById('toggle-password').addEventListener('click', (event) => {
            const visible = password.type === 'text';
            password.type = visible ? 'password' : 'text';
            event.currentTarget.setAttribute('aria-label', visible ? 'Hiện mật khẩu' : 'Ẩn mật khẩu');
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
                error.textContent = 'Vui lòng nhập tài khoản và mật khẩu.';
                error.hidden = false;
                (!username.value.trim() ? username : password).setAttribute('aria-invalid', 'true');
                (!username.value.trim() ? username : password).focus();
                return;
            }
            submit.disabled = true;
            submit.textContent = 'Đang đăng nhập…';
            try {
                const body = new URLSearchParams({username: username.value.trim(), password: password.value});
                if (document.getElementById('login-remember').checked) body.set('scope', 'remember_me');
                const response = await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body, signal: AbortSignal.timeout(15000)});
                if (!response.ok) throw new Error(response.status === 401 ? 'Tài khoản hoặc mật khẩu không đúng.' : 'Không thể đăng nhập. Vui lòng thử lại.');
                const data = await response.json();
                window.authSession.storeToken(data.access_token, document.getElementById('login-remember').checked);
                location.replace(safeReturnTo());
            } catch (reason) {
                error.textContent = reason.name === 'TimeoutError' ? 'Máy chủ phản hồi quá chậm. Vui lòng thử lại.' : reason.message;
                error.hidden = false;
            } finally {
                submit.disabled = false;
                submit.textContent = 'Đăng nhập';
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
                <button type="button" data-logout-action><i class="bi bi-box-arrow-right"></i> Đăng xuất</button>
            </div>`;
        const more = navigation.querySelector('.admin-more-sheet');
        navigation.addEventListener('click', (event) => {
            const button = event.target.closest('button');
            if (!button) return;
            if (button.hasAttribute('data-more')) { more.hidden = !more.hidden; return; }
            if (button.hasAttribute('data-theme-action')) { document.getElementById('theme-toggle')?.click(); more.hidden = true; return; }
            if (button.hasAttribute('data-logout-action')) { document.getElementById('logout-btn')?.click(); return; }
            const tab = button.dataset.tab;
            if (tab) {
                window.adminManager?.switchTab(tab, button);
                if (tab === 'tab-pi') window.adminManager?.loadPiDevices?.();
                if (tab === 'tab-rescue') window.adminManager?.loadRescueRequests?.();
                navigation.querySelectorAll(':scope > button').forEach(item => item.classList.toggle('active', item === button));
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
    async function bootLegacy(view) {
        document.documentElement.dataset.appView = view;
        document.title = view === 'map' ? 'Bản đồ realtime · Landslide Monitor' : 'Quản trị · Landslide Monitor';
        await Promise.all((view === 'map' ? mapStyles : adminStyles).concat(sharedStyles).map(loadStyle));
        await loadScript('/assets/shared.min.js?v=__BUILD_VERSION__');
        await loadScript(CDN.bootstrapJs);
        await loadScript(CDN.sweetalert);
        if (view === 'map') {
            await loadStyle(CDN.leafletCss); await loadStyle(CDN.clusterCss); await loadStyle(CDN.clusterDefaultCss);
            await loadScript(CDN.leaflet); await Promise.all([loadScript(CDN.cluster), loadScript(CDN.heat), loadScript(CDN.chart)]);
            window.__MAP_BUNDLE_LOADING__ = true;
            await loadScript('/assets/map-app.min.js?v=__BUILD_VERSION__');
            root.innerHTML = window.LegacyTemplates.map;
            window.__MAP_BUNDLE_LOADING__ = false;
            window.flushMapReadyQueue?.();
        } else {
            document.documentElement.setAttribute('data-theme', 'light');
            await loadScript('/assets/admin-app.min.js?v=__BUILD_VERSION__');
            root.innerHTML = window.LegacyTemplates.admin;
            setupAdminMobileNavigation();
            setupAdminResponsiveTables();
            await window.bootstrapAdminManager?.();
            window.bootstrapDatabaseManager?.();
        }
        setTimeout(() => window.authManager?.updateAuthUI?.(), 50);
    }

    async function start() {
        const path = location.pathname.replace(/\/+$/, '') || '/';
        if (path === '/login') {
            const session = await window.authSession.inspect();
            if (session.status === 'authenticated' || session.status === 'unavailable') {
                location.replace(safeReturnTo());
                return;
            }
            await loadStyle('/assets/login.min.css?v=__BUILD_VERSION__');
            renderLogin();
            return;
        }
        const view = path === '/management' || path === '/admin' ? 'admin' : 'map';
        await bootLegacy(view);
    }

    start().catch((error) => {
        console.error(error);
        root.innerHTML = `<main class="route-error"><h1>Không thể tải giao diện</h1><p>${String(error.message || error)}</p><button type="button" onclick="location.reload()">Thử lại</button></main>`;
    });
})();
