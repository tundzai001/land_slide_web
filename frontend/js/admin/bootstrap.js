
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

    const token = localStorage.getItem('token') || sessionStorage.getItem('token');
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

            if (user.role === 'admin') {
                const systemTab = document.getElementById('system-tab');
                if (systemTab) {
                    systemTab.style.display = 'block';
                    console.log('[ADMIN] System tab enabled');
                }
            }
        }
    } catch (e) {
        console.error('[ADMIN] Error updating admin UI:', e);
    }
}

window.bootstrapAdminManager = bootstrapAdminManager;

