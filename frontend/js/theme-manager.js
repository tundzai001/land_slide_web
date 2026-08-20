// =============================================
// THEME MANAGER - Light Mode Default ( frontend/js/theme-manager.js )
// =============================================

class ThemeManager {
    constructor() {
        this.theme = this.getInitialTheme();
        this.toggleButton = null;
        this.delegatedListenerReady = false;
        this.init();
    }

    getInitialTheme() {
        // 1. Check localStorage
        const saved = localStorage.getItem('theme');
        if (saved) return saved;

        // 2. Default to LIGHT (changed from dark)
        return 'light';
    }

    init() {
        this.applyTheme(this.theme);
        this.createToggleButton();
        this.setupDelegatedToggle();
        this.watchSystemTheme();
        this.updateFavicon();
    }

    applyTheme(theme) {
        console.log('🎨 Switching to:', theme);

        // Add transition class BEFORE changing theme
        document.body.classList.add('theme-switching');

        // Force layout calculation to ensure transition is applied
        void document.body.offsetHeight;

        // Apply theme
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);
        this.theme = theme;

        // Update icons and favicon
        this.updateToggleIcon();
        this.updateFavicon();

        // Remove transition class after completion (slightly longer for smoothness)
        setTimeout(() => {
            document.body.classList.remove('theme-switching');
            console.log('✅ Theme applied:', theme);
        }, 100);

        // Dispatch event
        window.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme } }));
    }

    toggle() {
        const newTheme = this.theme === 'dark' ? 'light' : 'dark';
        this.applyTheme(newTheme);

        // Animate the button
        if (this.toggleButton) {
            this.toggleButton.style.transform = 'scale(0.9) rotate(180deg)';
            setTimeout(() => {
                this.toggleButton.style.transform = '';
            }, 300);
        }
    }

    createToggleButton() {
        // Check if floating button already exists
        if (document.querySelector('.theme-toggle')) {
            this.toggleButton = document.querySelector('.theme-toggle');
            this.updateToggleIcon();
        }

        // Also wire up navbar toggle button (#theme-toggle-btn)
        const navToggle = document.getElementById('theme-toggle-btn');
        if (navToggle) {
            this.navToggleButton = navToggle;
        }

        // Also wire up admin page mini toggle (.theme-toggle-mini)  
        const miniToggle = document.querySelector('.theme-toggle-mini');
        if (miniToggle) {
            this.miniToggleButton = miniToggle;
        }

        // Create floating button if none found anywhere
        if (!this.toggleButton && !navToggle && !miniToggle) {
            const button = document.createElement('button');
            button.className = 'theme-toggle';
            button.setAttribute('aria-label', 'Chuyển giao diện sáng tối');
            button.innerHTML = '<i class="bi bi-sun-fill"></i>';
            button.onclick = () => this.toggle();

            document.body.appendChild(button);
            this.toggleButton = button;
        }

        this.updateToggleIcon();
    }

    setupDelegatedToggle() {
        if (this.delegatedListenerReady) return;
        this.delegatedListenerReady = true;

        document.addEventListener('click', (event) => {
            const toggle = event.target.closest?.('#theme-toggle-btn, .theme-toggle-mini, .theme-toggle');
            if (!toggle) return;

            event.preventDefault();
            this.toggleButton = toggle.classList.contains('theme-toggle') ? toggle : this.toggleButton;
            this.navToggleButton = toggle.id === 'theme-toggle-btn' ? toggle : this.navToggleButton;
            this.miniToggleButton = toggle.classList.contains('theme-toggle-mini') ? toggle : this.miniToggleButton;
            this.toggle();
        });
    }

    updateToggleIcon() {
        const iconClass = this.theme === 'light' ? 'bi bi-moon-stars-fill' : 'bi bi-sun-fill';

        // Update floating toggle button
        if (this.toggleButton) {
            const icon = this.toggleButton.querySelector('i');
            if (icon) icon.className = iconClass;
        }

        // Update navbar toggle (#theme-toggle-btn)
        const navToggle = this.navToggleButton || document.getElementById('theme-toggle-btn');
        if (navToggle) {
            const icon = navToggle.querySelector('i');
            if (icon) icon.className = iconClass;
        }

        // Update admin mini toggle (.theme-toggle-mini)
        const miniToggle = this.miniToggleButton || document.querySelector('.theme-toggle-mini');
        if (miniToggle) {
            const icon = miniToggle.querySelector('i');
            if (icon) icon.className = iconClass;
        }
    }

    updateFavicon() {
        const favicon = document.querySelector('link[rel="icon"]');
        if (favicon) {
            // Optional: different favicons for themes
        }
    }

    watchSystemTheme() {
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

        mediaQuery.addEventListener('change', (e) => {
            // Only auto-switch if user hasn't manually set a preference
            if (!localStorage.getItem('theme')) {
                this.applyTheme(e.matches ? 'dark' : 'light');
            }
        });
    }

    // Public API
    getCurrentTheme() {
        return this.theme;
    }

    setTheme(theme) {
        if (theme === 'dark' || theme === 'light') {
            this.applyTheme(theme);
        }
    }
}

// Initialize and expose globally
window.themeManager = new ThemeManager();

// Smooth scroll utility
window.smoothScroll = function (target) {
    const element = typeof target === 'string' ? document.querySelector(target) : target;
    if (!element) return;

    element.scrollIntoView({
        behavior: 'smooth',
        block: 'start'
    });
};
