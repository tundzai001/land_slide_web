// Lightweight entry point: feature modules are loaded sequentially to preserve the legacy global API.
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

    window.mapBundleReady = modules.reduce(
        (ready, src) => ready.then(() => loadModule(src)),
        Promise.resolve(),
    ).then(() => {
        window.__MAP_BUNDLE_LOADING__ = false;
        window.flushMapReadyQueue?.();
    }).catch((error) => {
        window.__MAP_BUNDLE_LOADING__ = false;
        console.error('[MAP] Feature bundle failed:', error);
        throw error;
    });
})();
