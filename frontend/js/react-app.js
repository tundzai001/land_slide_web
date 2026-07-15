const { useEffect, useMemo, useState } = React;

const ROUTES = new Set(['map', 'login', 'admin']);
const EMBEDDED_ROOT_APP = window.LANDING_EMBEDDED_APP === true;
const VIEW_PATHS = {
    map: '/',
    login: '/',
    admin: '/management',
};
const scriptPromises = new Map();
const loadedStylesheets = new Set();
const legacyBootedViews = new Set();
const ROUTE_STYLES = {
    map: ['/css/map.css?v=react-spa-13', '/css/digital-twin.css?v=react-spa-12', '/css/rescue-markers.css?v=react-spa-12', '/css/map-responsive.css?v=react-spa-12'],
    admin: ['/css/admin.css?v=react-spa-12', '/css/admin-responsive.css?v=react-spa-12'],
    login: ['/css/login.css'],
};

function navDebug(label, data = {}) {
    console.log(`[SPA-NAV] ${label}`, {
        path: window.location.pathname,
        search: window.location.search,
        hash: window.location.hash,
        ...data,
    });
}

function getInitialView() {
    if (EMBEDDED_ROOT_APP) {
        const embeddedView = window.LANDING_EMBEDDED_VIEW || 'map';
        navDebug('getInitialView embedded', { view: embeddedView });
        return embeddedView;
    }

    const path = window.location.pathname.replace(/\/+$/, '') || '/';
    if (path === '/map') {
        navDebug('getInitialView path', { view: 'map' });
        return 'map';
    }
    if (path === '/management' || path === '/admin') {
        navDebug('getInitialView path', { view: 'admin' });
        return 'admin';
    }

    const params = new URLSearchParams(window.location.search);
    const view = params.get('view');
    if (ROUTES.has(view)) {
        navDebug('getInitialView query', { view });
        return view;
    }
    navDebug('getInitialView fallback', { view: 'map' });
    return 'map';
}

function setDocumentView(view) {
    navDebug('setDocumentView', { view });
    document.documentElement.dataset.appView = view;
    document.body.className = '';
}

function appNavigate(view, options = {}) {
    const next = ROUTES.has(view) ? view : 'map';
    const url = VIEW_PATHS[next] || VIEW_PATHS.map;
    navDebug('appNavigate start', { requestedView: view, next, url, options });
    if (options.replace) {
        window.history.replaceState({ view: next }, '', url);
    } else {
        window.history.pushState({ view: next }, '', url);
    }
    navDebug('appNavigate dispatch', { next, url });
    window.dispatchEvent(new CustomEvent('spa:navigate', { detail: { view: next } }));
}

document.addEventListener('click', (event) => {
    const link = event.target.closest?.('a[href="/"], a[href="/map"], a[data-map-home]');
    const anyLink = event.target.closest?.('a');
    const button = event.target.closest?.('button');
    if (anyLink || button) {
        navDebug('capture click', {
            tag: anyLink ? 'a' : 'button',
            text: (anyLink || button).textContent?.trim()?.slice(0, 80),
            href: anyLink?.getAttribute('href') || null,
            id: (anyLink || button).id || null,
            className: (anyLink || button).className || null,
            matchedMapBack: !!link,
        });
    }
    if (!link || !window.location.pathname.startsWith('/management')) return;
    event.preventDefault();
    event.stopPropagation();
    navDebug('intercept management to map', {
        href: link.getAttribute('href'),
        text: link.textContent?.trim(),
    });
    appNavigate('map');
}, true);

window.addEventListener('beforeunload', () => {
    if (window.location.pathname.startsWith('/management') && !window.SPA_SUPPRESS_AUTO_MAP_ON_LANDING) {
        sessionStorage.setItem('openMapAfterManagement', 'true');
        navDebug('beforeunload set openMapAfterManagement');
        return;
    }
    navDebug('beforeunload');
});

function loadScript(src, opts = {}) {
    const key = `${opts.type || 'script'}:${src}`;
    if (scriptPromises.has(key)) return scriptPromises.get(key);

    const existing = Array.from(document.scripts).find((script) => {
        const scriptUrl = new URL(script.src || '', window.location.href);
        const wantedUrl = new URL(src, window.location.href);
        return scriptUrl.pathname === wantedUrl.pathname && scriptUrl.search === wantedUrl.search;
    });

    if (existing?.dataset.loaded === 'true') {
        const resolved = Promise.resolve();
        scriptPromises.set(key, resolved);
        return resolved;
    }

    const promise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        if (opts.type) script.type = opts.type;
        script.onload = () => {
            script.dataset.loaded = 'true';
            resolve();
        };
        script.onerror = () => reject(new Error(`Cannot load ${src}`));
        document.body.appendChild(script);
    });

    scriptPromises.set(key, promise);
    return promise;
}

function loadStylesheet(href) {
    if (loadedStylesheets.has(href)) return Promise.resolve();

    return new Promise((resolve, reject) => {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = href;
        link.dataset.routeStyle = 'true';
        link.onload = () => {
            loadedStylesheets.add(href);
            resolve();
        };
        link.onerror = () => reject(new Error(`Cannot load ${href}`));
        document.head.appendChild(link);
    });
}

function loadRouteStyles(view) {
    return Promise.all((ROUTE_STYLES[view] || []).map(loadStylesheet));
}

function fireLegacyReady() {
    setTimeout(() => window.authManager?.updateAuthUI?.(), 50);
}

async function bootLegacyPage(view) {
    navDebug('bootLegacyPage start', { view, booted: legacyBootedViews.has(view) });
    if (legacyBootedViews.has(view)) {
        navDebug('bootLegacyPage reload existing view', { view, url: VIEW_PATHS[view] || VIEW_PATHS.map });
        window.location.replace(VIEW_PATHS[view] || VIEW_PATHS.map);
        return;
    }

    if (view === 'map') {
        await loadScript('/js/map-main.js?v=react-spa-20');
        await loadScript('/js/engine/simulation-controller.js', { type: 'module' });
        legacyBootedViews.add(view);
        navDebug('bootLegacyPage done', { view });
        fireLegacyReady();
        return;
    }

    if (view === 'admin') {
        window.togglePasswordVisibility = function togglePasswordVisibility(inputId) {
            const input = document.getElementById(inputId);
            const button = input?.nextElementSibling?.querySelector?.('i');
            if (!input) return;
            input.type = input.type === 'password' ? 'text' : 'password';
            if (button) button.className = input.type === 'password' ? 'bi bi-eye' : 'bi bi-eye-slash';
        };

        await loadScript('/js/toast-notifications.js');
        await loadScript('/js/admin-manager.js?v=react-spa-12');
        await loadScript('/js/db-manager.js?v=export-bg-2');
        await loadScript('/js/system-manager.js');
        await window.bootstrapAdminManager?.();
        window.bootstrapDatabaseManager?.();
        window.bootstrapSystemManager?.();
        legacyBootedViews.add(view);
        navDebug('bootLegacyPage done', { view });
        fireLegacyReady();
    }
}

function LegacyPage({ view }) {
    useEffect(() => {
        navDebug('LegacyPage mount', { view });
        setDocumentView(view);
        const root = document.getElementById('legacy-root');
        root.innerHTML = '<div class="route-loading">Loading...</div>';
        loadRouteStyles(view).then(() => {
            root.innerHTML = window.LegacyTemplates?.[view] || '';
            return bootLegacyPage(view);
        }).catch((error) => {
            console.error(error);
            root.innerHTML = `<div class="p-4 text-danger">Không tải được màn ${view}.</div>`;
        });
        return () => {
            navDebug('LegacyPage cleanup', { view });
            root.innerHTML = '';
        };
    }, [view]);

    return <div id="legacy-root" />;
}

function LoginView({ returnView = null }) {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [rememberMe, setRememberMe] = useState(true);
    const [showPassword, setShowPassword] = useState(false);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        setDocumentView('login');
        loadRouteStyles('login').catch(console.error);
    }, []);

    async function handleSubmit(event) {
        event.preventDefault();
        setError('');
        setLoading(true);

        try {
            const result = await window.authManager.login(username.trim(), password, rememberMe);
            if (!result.success) throw new Error(result.error || 'Đăng nhập thất bại');
            sessionStorage.setItem('justLoggedIn', 'true');
            sessionStorage.removeItem('loginReturnView');
            if (returnView) {
                appNavigate(returnView, { replace: true });
                window.location.reload();
            } else {
                window.location.replace('/');
            }
        } catch (err) {
            setError(err.message || 'Đăng nhập thất bại');
        } finally {
            setLoading(false);
        }
    }

    return (
        <main className="login-page">
            <section className="login-visual" aria-hidden="true">
                <div className="login-brand">
                    <span className="login-brand-icon"><i className="bi bi-activity" /></span>
                    <span>Landslide Monitor</span>
                </div>
                <div className="login-visual-copy">
                    <div className="login-kicker">Monitoring Console</div>
                    <h1>Quản lý vận hành hệ thống quan trắc</h1>
                    <p>Theo dõi trạm, cấu hình cảnh báo và phân quyền truy cập trong một giao diện duy nhất.</p>
                </div>
            </section>

            <section className="login-panel">
                <div className="login-form-wrap">
                    <button type="button" onClick={() => {
                        if (returnView) appNavigate(returnView);
                        else window.location.href = '/';
                    }} className="login-back">
                        <i className="bi bi-arrow-left" />
                        <span>{returnView === 'map' ? 'Quay lại bản đồ' : 'Quay lại'}</span>
                    </button>

                    <div className="login-card">
                        <div className="login-card-head">
                            <div className="login-icon">
                                <i className="bi bi-shield-lock-fill" />
                            </div>
                            <div>
                                <h2>Đăng nhập</h2>
                                <p className="login-subtitle">Truy cập hệ thống giám sát</p>
                            </div>
                        </div>

                        <form onSubmit={handleSubmit} className="login-form">
                            <label className="login-field">
                                <span>Tài khoản</span>
                                <input value={username} onChange={(e) => setUsername(e.target.value)} className="login-input" autoFocus required />
                            </label>

                            <label className="login-field">
                                <span>Mật khẩu</span>
                                <div className="login-password-row">
                                    <input type={showPassword ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} required />
                                    <button type="button" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'}>
                                        <i className={`bi ${showPassword ? 'bi-eye-slash' : 'bi-eye'}`} />
                                    </button>
                                </div>
                            </label>

                            <label className="login-check">
                                <input type="checkbox" checked={rememberMe} onChange={(e) => setRememberMe(e.target.checked)} />
                                <span>Ghi nhớ đăng nhập</span>
                            </label>

                            {error && (
                                <div className="login-error">
                                    <i className="bi bi-exclamation-circle" />{error}
                                </div>
                            )}

                            <button disabled={loading} className="login-submit">
                                {loading ? 'Đang xử lý...' : 'Đăng nhập'}
                            </button>
                        </form>
                    </div>
                </div>
            </section>
        </main>
    );
}

function App() {
    const [view, setView] = useState(getInitialView);
    const [stylesReady, setStylesReady] = useState(false);
    const returnView = useMemo(() => {
        const params = new URLSearchParams(window.location.search);
        const value = sessionStorage.getItem('loginReturnView') || params.get('returnView');
        return ROUTES.has(value) && value !== 'login' ? value : null;
    }, [view]);

    useEffect(() => {
        navDebug('App listeners mount', { initialView: view });
        const onPopState = () => {
            const nextView = getInitialView();
            navDebug('popstate', { nextView });
            setView(nextView);
        };
        const onNavigate = (event) => {
            navDebug('spa:navigate received', { detail: event.detail });
            setView(event.detail.view);
        };
        window.addEventListener('popstate', onPopState);
        window.addEventListener('spa:navigate', onNavigate);
        return () => {
            window.removeEventListener('popstate', onPopState);
            window.removeEventListener('spa:navigate', onNavigate);
        };
    }, []);

    useEffect(() => {
        navDebug('App view effect', { view });
        let cancelled = false;
        setStylesReady(false);
        loadRouteStyles(view)
            .then(() => {
                if (!cancelled) setStylesReady(true);
            })
            .catch((error) => {
                console.error(error);
                if (!cancelled) setStylesReady(true);
            });
        return () => {
            cancelled = true;
        };
    }, [view]);

    if (!stylesReady) return <div className="route-loading">Loading...</div>;
    if (view === 'login') return <LoginView returnView={returnView} />;
    return <LegacyPage view={view} />;
}

window.appNavigate = appNavigate;
ReactDOM.createRoot(document.getElementById('app-root')).render(<App />);
