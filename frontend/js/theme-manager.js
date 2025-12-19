// =============================================
// THEME MANAGER - Light Mode Default ( frontend/js/theme-manager.js )
// =============================================

class ThemeManager {
    constructor() {
        this.theme = this.getInitialTheme();
        this.toggleButton = null;
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
        this.watchSystemTheme();
        this.updateFavicon();
    }

    applyTheme(theme) {
        // Add switching class to prevent flicker
        document.body.classList.add('theme-switching');
        
        // Apply theme
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);
        this.theme = theme;
        
        // Update button icon
        this.updateToggleIcon();
        this.updateFavicon();
        
        // Remove switching class after transition
        setTimeout(() => {
            document.body.classList.remove('theme-switching');
        }, 50);

        // Dispatch event for other components
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
        // Check if button already exists
        if (document.querySelector('.theme-toggle')) {
            this.toggleButton = document.querySelector('.theme-toggle');
            this.updateToggleIcon();
            this.toggleButton.onclick = () => this.toggle();
            return;
        }

        // Create new button
        const button = document.createElement('button');
        button.className = 'theme-toggle';
        button.setAttribute('aria-label', 'Toggle theme');
        button.innerHTML = '<i class="bi bi-sun-fill"></i>';
        button.onclick = () => this.toggle();
        
        document.body.appendChild(button);
        this.toggleButton = button;
        
        this.updateToggleIcon();
    }

    updateToggleIcon() {
        if (!this.toggleButton) return;
        
        const icon = this.toggleButton.querySelector('i');
        if (!icon) return;
        
        // ✅ Updated: Light mode shows sun (current), click to go dark (moon)
        if (this.theme === 'light') {
            icon.className = 'bi bi-moon-stars-fill'; // Show moon = can switch to dark
        } else {
            icon.className = 'bi bi-sun-fill'; // Show sun = can switch to light
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
window.smoothScroll = function(target) {
    const element = typeof target === 'string' ? document.querySelector(target) : target;
    if (!element) return;
    
    element.scrollIntoView({
        behavior: 'smooth',
        block: 'start'
    });
};