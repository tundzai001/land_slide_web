// =============================================
// NAV MANAGER - Quản lý Navbar & Sidebars (frontend/js/nav-manager.js)
// =============================================

class NavManager {
    constructor() {
        this.init();
    }

    init() {
        console.log('🧭 [NAV] Initializing nav manager...');
        
        // Setup toggle buttons
        this.setupToggleButtons();
        
        // Update theme icon
        this.updateThemeIcon();
        
        // ✅ Show admin button if user is admin
        this.updateAdminButton();
        
        // Listen to theme changes
        window.addEventListener('themeChanged', () => {
            this.updateThemeIcon();
        });
        
        console.log('✅ [NAV] Nav manager initialized');
    }

    setupToggleButtons() {
        // Toggle station list sidebar
        const toggleListBtn = document.getElementById('toggle-list-btn');
        const stationSidebar = document.getElementById('station-list-sidebar');
        const closeListBtn = document.getElementById('close-list-btn');
        
        if (toggleListBtn && stationSidebar) {
            toggleListBtn.addEventListener('click', () => {
                stationSidebar.classList.toggle('active');
            });
            console.log('✅ [NAV] Toggle list button connected');
        }
        
        if (closeListBtn && stationSidebar) {
            closeListBtn.addEventListener('click', () => {
                stationSidebar.classList.remove('active');
            });
            console.log('✅ [NAV] Close list button connected');
        }
        
        // Close detail sidebar
        const closeDetailBtn = document.getElementById('close-btn');
        const detailSidebar = document.getElementById('detail-sidebar');
        
        if (closeDetailBtn && detailSidebar) {
            closeDetailBtn.addEventListener('click', () => {
                detailSidebar.classList.remove('active');
            });
            console.log('✅ [NAV] Close detail button connected');
        }
        
        // Auth button
        const authBtn = document.getElementById('auth-btn');
        if (authBtn) {
            authBtn.addEventListener('click', () => {
                if (window.authManager && window.authManager.isAuthenticated()) {
                    window.authManager.logout();
                } else {
                    window.location.href = '/pages/login.html';
                }
            });
            console.log('✅ [NAV] Auth button connected');
        }
        
        // Search functionality
        const searchInput = document.getElementById('search-station');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.filterStations(e.target.value);
            });
            console.log('✅ [NAV] Search input connected');
        }
    }

    // ✅ NEW: Update admin button visibility
    updateAdminButton() {
        const adminBtn = document.getElementById('admin-nav-btn');
        
        if (!adminBtn) {
            console.log('ℹ️ [NAV] Admin button not found in DOM');
            return;
        }
        
        // Check if authManager is available
        if (!window.authManager) {
            console.log('⚠️ [NAV] AuthManager not available yet, will retry...');
            // Retry after a short delay
            setTimeout(() => this.updateAdminButton(), 500);
            return;
        }
        
        const user = window.authManager.getUserInfo();
        
        if (user && user.role === 'admin') {
            adminBtn.style.display = 'inline-flex'; // Use inline-flex for proper icon+text alignment
            console.log('✅ [NAV] Admin button shown for:', user.sub);
        } else {
            adminBtn.style.display = 'none';
            console.log('🔒 [NAV] Admin button hidden (not admin)');
        }
    }

    filterStations(searchTerm) {
        const stations = document.querySelectorAll('.station-item');
        const term = searchTerm.toLowerCase();
        
        stations.forEach(station => {
            const text = station.textContent.toLowerCase();
            if (text.includes(term)) {
                station.style.display = 'block';
            } else {
                station.style.display = 'none';
            }
        });
    }

    updateThemeIcon() {
        const themeBtn = document.getElementById('theme-toggle-btn');
        if (!themeBtn) return;
        
        const icon = themeBtn.querySelector('i');
        if (!icon) return;
        
        const currentTheme = window.themeManager ? window.themeManager.getCurrentTheme() : 'light';
        
        if (currentTheme === 'light') {
            icon.className = 'bi bi-moon-stars-fill';
        } else {
            icon.className = 'bi bi-sun-fill';
        }
    }

    openDetailSidebar(stationData) {
        const sidebar = document.getElementById('detail-sidebar');
        if (sidebar) {
            sidebar.classList.add('active');
        }
    }

    closeDetailSidebar() {
        const sidebar = document.getElementById('detail-sidebar');
        if (sidebar) {
            sidebar.classList.remove('active');
        }
    }

    closeStationList() {
        const sidebar = document.getElementById('station-list-sidebar');
        if (sidebar) {
            sidebar.classList.remove('active');
        }
    }
}

// Initialize globally
window.navManager = new NavManager();

// Export for use in other scripts
window.addEventListener('DOMContentLoaded', () => {
    console.log('🧭 [NAV] DOM Content Loaded');
    
    // Update auth button text
    if (window.authManager) {
        const user = window.authManager.getUserInfo();
        const authBtn = document.getElementById('auth-btn');
        
        if (authBtn && user) {
            authBtn.innerHTML = `<i class="bi bi-person-check me-1"></i> ${user.sub}`;
            authBtn.classList.remove('btn-primary');
            authBtn.classList.add('btn-outline-danger');
        }
        
        // ✅ Update admin button visibility
        if (window.navManager) {
            window.navManager.updateAdminButton();
        }
    }
});