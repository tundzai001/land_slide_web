/* Compile JSX away from the UI thread while preserving Babel Standalone at runtime. */
let loadedBabelUrl = null;

self.addEventListener('message', (event) => {
    const { id, babelUrl, source, filename, options } = event.data || {};
    if (!id || !source) return;

    try {
        if (!self.Babel || loadedBabelUrl !== babelUrl) {
            importScripts(babelUrl);
            loadedBabelUrl = babelUrl;
        }
        const compiled = self.Babel.transform(source, {
            ...(options || {}),
            filename: filename || 'react-runtime.jsx',
            sourceMaps: false,
        });
        self.postMessage({ id, code: compiled.code });
    } catch (error) {
        self.postMessage({
            id,
            error: error?.stack || error?.message || String(error),
        });
    }
});
