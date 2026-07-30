/*
 * Runtime JSX loader for the CDN React deployment.
 *
 * The application intentionally keeps Babel Standalone in production. This
 * loader moves transforms to a worker and persists the output so warm loads do
 * not repeat parsing/compilation on the main thread.
 */
(() => {
    if (window.compileAndExecuteReactSource) return;

    const BABEL_URL = 'https://unpkg.com/@babel/standalone/babel.min.js';
    const WORKER_URL = '/js/babel-worker.js?v=react-runtime-1';
    const CACHE_NAME = 'landslide-babel-runtime-v1';
    const pendingExecutions = new Map();
    const pendingWorkerTasks = new Map();
    let worker = null;
    let workerSequence = 0;

    function getWorker() {
        if (worker) return worker;
        if (typeof Worker !== 'function') return null;

        try {
            worker = new Worker(WORKER_URL);
            worker.addEventListener('message', (event) => {
                const task = pendingWorkerTasks.get(event.data?.id);
                if (!task) return;
                pendingWorkerTasks.delete(event.data.id);
                if (event.data.error) task.reject(new Error(event.data.error));
                else task.resolve(event.data.code || '');
            });
            worker.addEventListener('error', (error) => {
                pendingWorkerTasks.forEach(task => task.reject(error));
                pendingWorkerTasks.clear();
                worker?.terminate();
                worker = null;
            });
            return worker;
        } catch (error) {
            console.warn('[BABEL] Worker unavailable; using main-thread fallback.', error);
            worker = null;
            return null;
        }
    }

    function compileInWorker(source, filename, options) {
        const activeWorker = getWorker();
        if (!activeWorker) return Promise.reject(new Error('Babel worker unavailable'));
        const id = `babel-${Date.now()}-${++workerSequence}`;
        return new Promise((resolve, reject) => {
            pendingWorkerTasks.set(id, { resolve, reject });
            activeWorker.postMessage({ id, babelUrl: BABEL_URL, source, filename, options });
        });
    }

    function compileOnMainThread(source, filename, options) {
        if (!window.Babel?.transform) {
            throw new Error('Babel Standalone is not available');
        }
        return window.Babel.transform(source, {
            ...(options || {}),
            filename,
            sourceMaps: false,
        }).code;
    }

    function compiledCacheKey(src, options) {
        const url = new URL(src, window.location.href);
        url.searchParams.set('__compiled_with_babel', window.Babel?.version || 'runtime');
        url.searchParams.set('__preset', JSON.stringify(options?.presets || []));
        return new Request(url.toString(), { method: 'GET' });
    }

    async function readCompiledCache(key) {
        if (!('caches' in window)) return null;
        try {
            const cache = await caches.open(CACHE_NAME);
            const response = await cache.match(key);
            return response ? response.text() : null;
        } catch (error) {
            console.debug('[BABEL] Compiled cache read skipped:', error);
            return null;
        }
    }

    async function writeCompiledCache(key, code) {
        if (!('caches' in window)) return;
        try {
            const cache = await caches.open(CACHE_NAME);
            await cache.put(key, new Response(code, {
                headers: { 'Content-Type': 'application/javascript; charset=utf-8' },
            }));
        } catch (error) {
            console.debug('[BABEL] Compiled cache write skipped:', error);
        }
    }

    function executeCompiledCode(code, src) {
        const script = document.createElement('script');
        script.charset = 'utf-8';
        script.dataset.babelSrc = src;
        script.textContent = `${code}\n//# sourceURL=${new URL(src, window.location.href).pathname}.compiled.js`;
        document.body.appendChild(script);
    }

    async function compileAndExecuteReactSource(src, options = {}) {
        const normalizedOptions = {
            presets: options.presets || [['react', { runtime: 'classic' }]],
        };
        const executionKey = `${src}:${JSON.stringify(normalizedOptions)}`;
        if (pendingExecutions.has(executionKey)) return pendingExecutions.get(executionKey);
        if (document.querySelector(`script[data-babel-src="${CSS.escape(src)}"]`)) return;

        const execution = (async () => {
            const cacheKey = compiledCacheKey(src, normalizedOptions);
            let code = await readCompiledCache(cacheKey);
            if (!code) {
                const response = await fetch(src, { cache: 'no-cache' });
                if (!response.ok) throw new Error(`Cannot load ${src} (${response.status})`);
                const source = await response.text();
                try {
                    code = await compileInWorker(source, src, normalizedOptions);
                } catch (workerError) {
                    console.warn('[BABEL] Worker transform failed; falling back.', workerError);
                    code = compileOnMainThread(source, src, normalizedOptions);
                }
                await writeCompiledCache(cacheKey, code);
            }
            executeCompiledCode(code, src);
        })();

        pendingExecutions.set(executionKey, execution);
        try {
            await execution;
        } finally {
            pendingExecutions.delete(executionKey);
        }
    }

    window.compileAndExecuteReactSource = compileAndExecuteReactSource;
})();
