
// =========================================================================
// INITIALIZATION
// =========================================================================
async function bootstrapAdminManager() {
    const hasAdminDom = document.getElementById('projects-content-area');
    if (!hasAdminDom) {
        return;
    }

    const token = window.authSession?.getToken();
    if (!token) return;

    // app-runtime can mount the management shell before auth.js finishes its
    // first /api/auth/me call.  Wait for the authoritative user scope before
    // constructing managers, otherwise a viewer briefly triggers admin-only
    // loaders and sockets.
    if (!window.authManager?.getUserInfo?.()) {
        await new Promise(resolve => {
            let settled = false;
            const done = () => {
                if (settled) return;
                settled = true;
                window.removeEventListener('auth:ready', done);
                resolve();
            };
            window.addEventListener('auth:ready', done, { once: true });
            setTimeout(done, 10000);
        });
    }
    if (!window.authManager?.getUserInfo?.() && !window.authManager?.user) return;
    if (!window.adminManager) {
        window.adminManager = new AdminManager();
    }

    try {
        let user = window.authManager?.getUserInfo() || window.authManager?.user;

        if (!user) {
            const res = await fetch('/api/auth/me', { headers: { 'Authorization': `Bearer ${token}` } });
            if (res.ok) user = await res.json();
        }

        if (user) {
            const usernameEl = document.querySelector('.user-profile span');
            if (usernameEl) usernameEl.textContent = user.full_name || user.username;

        }
    } catch (e) {
        console.error('[ADMIN] Error updating admin UI:', e);
    }
}

window.bootstrapAdminManager = bootstrapAdminManager;
