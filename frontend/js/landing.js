(() => {
    'use strict';
    const html = document.documentElement;
    const menuButton = document.getElementById('menu-button');
    const menu = document.getElementById('mobile-menu');
    const themeButton = document.getElementById('theme-button');
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'light' || savedTheme === 'dark') html.dataset.theme = savedTheme;
    function syncThemeLabel() {
        const dark = html.dataset.theme !== 'light';
        themeButton.textContent = dark ? '☼' : '☾';
        themeButton.setAttribute('aria-label', dark ? 'Chuyển giao diện sáng' : 'Chuyển giao diện tối');
    }
    syncThemeLabel();
    themeButton.addEventListener('click', () => {
        html.dataset.theme = html.dataset.theme === 'light' ? 'dark' : 'light';
        localStorage.setItem('theme', html.dataset.theme);
        syncThemeLabel();
    });
    function closeMenu() { menu.hidden = true; menuButton.setAttribute('aria-expanded', 'false'); document.body.style.overflow = ''; }
    menuButton.addEventListener('click', () => {
        const open = menu.hidden;
        menu.hidden = !open;
        menuButton.setAttribute('aria-expanded', String(open));
        document.body.style.overflow = open ? 'hidden' : '';
    });
    menu.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMenu));
    addEventListener('resize', () => { if (innerWidth >= 1024) closeMenu(); }, {passive: true});
    addEventListener('scroll', () => document.getElementById('site-header').classList.toggle('scrolled', scrollY > 12), {passive: true});

    async function syncAuthLinks() {
        const links = document.querySelectorAll('[data-auth-link]');
        if (!links.length || !window.authSession) return;
        const session = await window.authSession.inspect();
        if (session.status !== 'authenticated') return;
        const canManage = session.user?.role === 'admin' || session.user?.role === 'operator';
        links.forEach(link => {
            link.href = canManage ? '/management' : '/map';
            link.textContent = canManage ? 'Quản trị hệ thống' : 'Mở bản đồ';
        });
    }

    const number = new Intl.NumberFormat('vi-VN');
    async function loadSummary() {
        try {
            const response = await fetch('/api/public/dashboard-summary', {signal: AbortSignal.timeout(10000)});
            if (!response.ok) throw new Error();
            const data = await response.json();
            for (const key of ['total','online','offline','stale']) document.getElementById(`stations-${key}`).textContent = number.format(data.stations[key] || 0);
            document.getElementById('summary-updated').textContent = `Cập nhật ${new Intl.DateTimeFormat('vi-VN',{dateStyle:'short',timeStyle:'short'}).format(new Date(data.updated_at))}`;
        } catch (_) {
            document.getElementById('summary-updated').textContent = 'Chưa thể cập nhật dữ liệu';
        }
    }
    loadSummary();
    void syncAuthLinks();
})();
