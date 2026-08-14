
// =========================================================================
// INITIALIZATION
// =========================================================================
async function bootstrapAdminManager() {
    const hasAdminDom = document.getElementById('projects-content-area');
    if (hasAdminDom && !window.adminManager) {
        window.adminManager = new AdminManager();
    } else if (!hasAdminDom) {
        return;
    }

    const token = window.authSession?.getToken();
    if (!token) return;

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
