const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('theme', theme);
    $('meta[name="theme-color"]')?.setAttribute('content', getComputedStyle(document.documentElement).getPropertyValue('--bg').trim());
    $('#theme-toggle')?.setAttribute('aria-label', theme === 'dark' ? 'Chuyển giao diện sáng' : 'Chuyển giao diện tối');
    $('#theme-toggle')?.setAttribute('aria-pressed', String(theme === 'dark'));
    dispatchEvent(new CustomEvent('themeChanged', { detail: { theme } }));
}

function setupAuthLinks() {
    const links = [$('#auth-link'), $('#mobile-auth-link')].filter(Boolean);
    let checking = false;
    const refresh = async () => {
        if (checking) return;
        checking = true;
        try {
            const response = await fetch('/api/auth/me', { credentials:'same-origin', cache:'no-store', signal:AbortSignal.timeout(8000) });
            let label, href;
            if (response.ok) {
                const user = await response.json();
                label = user.full_name || user.username || 'Tài khoản';
                href = '/management';
            } else if (response.status === 401 || response.status === 403) {
                label = 'Đăng nhập';
                href = '/login?return_to=%2Fmap';
            } else return;
            for (const link of links) {
                link.textContent = label;
                link.href = href;
            }
        } catch (err) {
            console.debug('Session status unavailable:', err);
        } finally { checking = false; }
    };
    void refresh();
    addEventListener('pageshow', event => { if (event.persisted) void refresh(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh(); });
}

function setupHeader() {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
    setupAuthLinks();
    const header = $('.site-header');
    const menu = $('#mobile-menu');
    const toggle = $('#menu-toggle');
    let lastFocused = null;
    const focusable = () => $$('a[href], button:not([disabled])', menu);
    const close = () => {
        if (!menu || menu.hidden) return;
        menu.hidden = true;
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-label', 'Mở trình đơn');
        document.body.classList.remove('menu-open');
        (lastFocused || toggle).focus();
    };
    const open = () => {
        lastFocused = document.activeElement;
        menu.hidden = false;
        toggle.setAttribute('aria-expanded', 'true');
        toggle.setAttribute('aria-label', 'Đóng trình đơn');
        document.body.classList.add('menu-open');
        focusable()[0]?.focus();
    };
    toggle?.addEventListener('click', () => menu.hidden ? open() : close());
    menu?.addEventListener('click', event => { if (event.target.closest('a')) close(); });
    document.addEventListener('keydown', event => {
        if (menu?.hidden) return;
        if (event.key === 'Escape') return close();
        if (event.key !== 'Tab') return;
        const items = focusable();
        if (!items.length) return;
        const first = items[0], last = items.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    $('#theme-toggle')?.addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
    let headerScrolled = false;
    const syncHeader = () => {
        const next = scrollY > 12;
        if (next !== headerScrolled) {
            headerScrolled = next;
            header?.classList.toggle('scrolled', next);
        }
    };
    addEventListener('scroll', syncHeader, { passive: true });
    syncHeader();
}

function setupMetrics() {
    const keys = ['total', 'online', 'stale', 'offline'];
    const grid = $('#metric-grid');
    const status = $('#metrics-status');
    const statusText = $('span:nth-child(2)', status);
    const retry = $('#metrics-retry');
    let controller;
    const setState = (state, message, retryable = false) => {
        status.dataset.state = state;
        statusText.textContent = message;
        retry.hidden = !retryable;
        grid.setAttribute('aria-busy', state === 'loading' ? 'true' : 'false');
    };
    const load = async () => {
        controller?.abort();
        controller = new AbortController();
        setState('loading', 'Đang tải trạng thái mạng…');
        keys.forEach(key => { $(`#stations-${key}`).textContent = '—'; });
        let timeout;
        try {
            timeout = setTimeout(() => controller.abort(), 10000);
            const response = await fetch('/api/public/dashboard-summary', { signal: controller.signal, cache: 'no-store' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            const stations = data?.stations || {};
            if (!Number(stations.total)) {
                keys.forEach(key => { $(`#stations-${key}`).textContent = '0'; });
                setState('empty', 'Chưa có trạm quan trắc trong mạng');
                return;
            }
            keys.forEach(key => {
                const el = $(`#stations-${key}`);
                const val = Number(stations[key]);
                if (el) el.textContent = Number.isFinite(val) ? new Intl.NumberFormat('vi-VN').format(val) : '—';
            });
            const updatedAt = new Date(data.updated_at);
            const stale = !Number.isFinite(updatedAt.getTime()) || Date.now() - updatedAt.getTime() > 15 * 60 * 1000;
            const formatted = Number.isFinite(updatedAt.getTime()) ? new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', timeStyle: 'short' }).format(updatedAt) : 'không rõ thời điểm';
            setState(stale ? 'stale' : 'ready', stale ? `Dữ liệu có thể đã cũ · ${formatted}` : `Cập nhật ${formatted}`, stale);
        } catch (error) {
            setState('error', error.name === 'AbortError' ? 'Không thể tải trạng thái mạng' : 'Mất kết nối dữ liệu trực tiếp', true);
        } finally { clearTimeout(timeout); }
    };
    retry?.addEventListener('click', load);
    void load();
}


export { setupHeader, setupMetrics };
