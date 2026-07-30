// Lightweight entry point for the feature-split administration UI.
(() => {
    if (window.adminBundleReady) return;
    const modules = [
        '/js/admin/core.js?v=admin-split-1',
        '/js/admin/navigation.js?v=admin-split-1',
        '/js/admin/projects.js?v=admin-split-1',
        '/js/admin/project-config.js?v=admin-split-1',
        '/js/admin/stations.js?v=admin-split-1',
        '/js/admin/station-wizard.js?v=admin-split-1',
        '/js/admin/station-presets.js?v=admin-split-1',
        '/js/admin/forwarding-controls.js?v=admin-split-1',
        '/js/admin/velocity.js?v=admin-split-1',
        '/js/admin/origin.js?v=admin-split-1',
        '/js/admin/provisioning.js?v=admin-split-1',
        '/js/admin/users.js?v=admin-split-1',
        '/js/admin/pi-devices.js?v=admin-split-1',
        '/js/admin/pi-center.js?v=admin-split-1',
        '/js/admin/lifecycle.js?v=admin-split-1',
        '/js/admin/bootstrap.js?v=admin-split-1',
    ];

    const loadModule = (src) => new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.async = false;
        script.onload = resolve;
        script.onerror = () => reject(new Error(`Cannot load admin feature module: ${src}`));
        document.body.appendChild(script);
    });

    // Preserve feature execution order with async=false, but start every
    // download immediately to remove the previous sixteen-request waterfall.
    window.adminBundleReady = Promise.all(modules.map(loadModule)).catch((error) => {
        console.error('[ADMIN] Feature bundle failed:', error);
        throw error;
    });
})();
