// Lightweight entry point: download feature modules in parallel and execute them in order.
(() => {
    if (window.mapBundleReady) return;
    const modules = [
        '/js/map/runtime.js?v=map-split-1',
        '/js/map/realtime.js?v=map-split-1',
        '/js/map/marker-alerts.js?v=map-split-1',
        '/js/map/guest-rescue.js?v=map-split-1',
        '/js/map/map-layers.js?v=map-split-1',
        '/js/map/map-interactions.js?v=map-split-1',
        '/js/map/stations.js?v=map-split-1',
        '/js/map/station-detail.js?v=map-split-1',
        '/js/map/long-term.js?v=map-split-1',
        '/js/map/analysis.js?v=map-split-1',
        '/js/map/ui-alerts.js?v=map-split-1',
        '/js/map/tools.js?v=map-split-1',
    ];

    window.__MAP_BUNDLE_LOADING__ = true;
    const loadModule = (src) => new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.async = false;
        script.onload = resolve;
        script.onerror = () => reject(new Error(`Cannot load map feature module: ${src}`));
        document.body.appendChild(script);
    });

    // Dynamic classic scripts with async=false execute in insertion order while
    // their network requests are allowed to run in parallel.
    window.mapBundleReady = Promise.all(modules.map(loadModule)).then(async () => {
        // stations.js includes an accessible DOM renderer, so production no
        // longer needs to compile JSX in the browser.
        window.__MAP_BUNDLE_LOADING__ = false;
        window.flushMapReadyQueue?.();
    }).catch((error) => {
        window.__MAP_BUNDLE_LOADING__ = false;
        console.error('[MAP] Feature bundle failed:', error);
        throw error;
    });
})();
