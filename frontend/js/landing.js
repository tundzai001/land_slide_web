(() => {
    'use strict';

    const $ = (selector, root = document) => root.querySelector(selector);
    const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');

    function setTheme(theme) {
        document.documentElement.dataset.theme = theme;
        localStorage.setItem('theme', theme);
        $('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#071a1c' : '#f4f8f7');
        const button = $('#theme-toggle');
        button?.setAttribute('aria-label', theme === 'dark' ? 'Chuyển giao diện sáng' : 'Chuyển giao diện tối');
        window.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme } }));
    }

    function setupHeader() {
        const header = $('.site-header');
        const menu = $('#mobile-menu');
        const toggle = $('#menu-toggle');
        let lastFocused = null;
        let scrollFrame = 0;
        const focusable = () => $$('a[href], button:not([disabled])', menu);
        const close = () => {
            if (menu.hidden) return;
            menu.hidden = true;
            toggle.setAttribute('aria-expanded', 'false');
            toggle.setAttribute('aria-label', 'Mở trình đơn');
            document.body.classList.remove('menu-open');
            (lastFocused || toggle).focus();
        };
        const open = () => {
            lastFocused = document.activeElement;
            menu.hidden = false;
            toggle.setAttribute('aria-expanded', 'true');
            toggle.setAttribute('aria-label', 'Đóng trình đơn');
            document.body.classList.add('menu-open');
            focusable()[0]?.focus();
        };
        toggle?.addEventListener('click', () => menu.hidden ? open() : close());
        menu?.addEventListener('click', event => { if (event.target.closest('a')) close(); });
        document.addEventListener('keydown', event => {
            if (menu?.hidden) return;
            if (event.key === 'Escape') return close();
            if (event.key !== 'Tab') return;
            const items = focusable();
            if (!items.length) return;
            const first = items[0], last = items[items.length - 1];
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        });
        $('#theme-toggle')?.addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
        addEventListener('scroll', () => {
            if (scrollFrame) return;
            scrollFrame = requestAnimationFrame(() => { scrollFrame = 0; header?.classList.toggle('scrolled', scrollY > 12); });
        }, { passive: true });
    }

    async function setupAuthLink() {
        const session = await window.authSession?.inspect?.();
        if (session?.status !== 'authenticated') return;
        const canManage = ['admin', 'operator'].includes(session.user?.role);
        const href = canManage ? '/management' : '/map';
        const label = canManage ? 'Quản trị hệ thống' : 'Mở bản đồ';
        $$('#auth-link, .mobile-menu a[href^="/login"], .final-cta a[href^="/login"]').forEach(link => { link.href = href; link.textContent = label; });
    }

    function setupReveal() {
        const elements = $$('.reveal');
        if (reducedMotion.matches || !('IntersectionObserver' in window)) {
            elements.forEach(element => element.classList.add('is-visible'));
            return;
        }
        document.documentElement.classList.add('reveal-ready');
        const observer = new IntersectionObserver(entries => entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
        }), { threshold: .12, rootMargin: '0px 0px -40px' });
        elements.forEach(element => observer.observe(element));
    }

    function setupMetrics() {
        const keys = ['total', 'online', 'stale', 'offline'];
        const grid = $('#metric-grid');
        const status = $('#metrics-status');
        const statusText = $('span:nth-child(2)', status);
        const retry = $('#metrics-retry');
        let controller;
        const setState = (state, message, retryable = false) => {
            status.dataset.state = state;
            statusText.textContent = message;
            retry.hidden = !retryable;
            grid.setAttribute('aria-busy', state === 'loading' ? 'true' : 'false');
        };
        const load = async () => {
            controller?.abort();
            controller = new AbortController();
            setState('loading', 'Đang tải trạng thái mạng…');
            keys.forEach(key => { $(`#stations-${key}`).textContent = '—'; });
            try {
                const timeout = setTimeout(() => controller.abort(), 10000);
                const response = await fetch('/api/public/dashboard-summary', { signal: controller.signal, cache: 'no-store' });
                clearTimeout(timeout);
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                const stations = data?.stations || {};
                if (!Number(stations.total)) {
                    keys.forEach(key => { $(`#stations-${key}`).textContent = '0'; });
                    setState('empty', 'Chưa có trạm quan trắc trong mạng');
                    return;
                }
                const format = new Intl.NumberFormat('vi-VN');
                keys.forEach(key => { $(`#stations-${key}`).textContent = Number.isFinite(Number(stations[key])) ? format.format(Number(stations[key])) : '—'; });
                const updatedAt = new Date(data.updated_at);
                const stale = !Number.isFinite(updatedAt.getTime()) || Date.now() - updatedAt.getTime() > 15 * 60 * 1000;
                const formatted = Number.isFinite(updatedAt.getTime()) ? new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', timeStyle: 'short' }).format(updatedAt) : 'không rõ thời điểm';
                setState(stale ? 'stale' : 'ready', stale ? `Dữ liệu có thể đã cũ · ${formatted}` : `Cập nhật ${formatted}`, stale);
            } catch (error) {
                if (error.name === 'AbortError' && controller.signal.aborted) setState('error', 'Không thể tải trạng thái mạng', true);
                else setState('error', 'Mất kết nối dữ liệu trực tiếp', true);
            }
        };
        retry.addEventListener('click', load);
        load();
    }

    function canUseStory3D(canvas) {
        if (!canvas || innerWidth < 1024 || reducedMotion.matches || navigator.connection?.saveData) return false;
        try { const probe = document.createElement('canvas'); return Boolean(probe.getContext('webgl2') || probe.getContext('webgl')); }
        catch (_) { return false; }
    }

    function smoothstep(value) {
        const clamped = Math.max(0, Math.min(1, value));
        return clamped * clamped * (3 - 2 * clamped);
    }

    function updateStoryStagePose(story, progress) {
        const stage = $('.story-stage', story);
        if (!stage) return;
        if (!story.classList.contains('story-enhanced')) {
            stage.style.removeProperty('--stage-scale');
            stage.style.removeProperty('--stage-x');
            stage.style.removeProperty('--stage-y');
            stage.style.removeProperty('--stage-radius');
            stage.dataset.pose = 'static';
            return;
        }
        // The stage itself morphs between chapters.  Three.js enriches the
        // scene inside it; it is not allowed to hide a stationary outer card.
        const poses = [
            { scale: .86, x: 0, y: 0, radius: 22 },
            { scale: 1.12, x: -.08, y: -.04, radius: 0 },
            { scale: .91, x: .08, y: .02, radius: 28 },
            { scale: 1.04, x: 0, y: .08, radius: 16 },
        ];
        const segment = Math.min(3, Math.max(0, progress * 4));
        const index = Math.min(2, Math.floor(segment));
        const amount = smoothstep(segment - index);
        const from = poses[index];
        const to = poses[index + 1];
        const lerp = (a, b) => a + (b - a) * amount;
        stage.style.setProperty('--stage-scale', lerp(from.scale, to.scale).toFixed(4));
        stage.style.setProperty('--stage-x', `${(lerp(from.x, to.x) * 100).toFixed(2)}%`);
        stage.style.setProperty('--stage-y', `${(lerp(from.y, to.y) * 100).toFixed(2)}%`);
        stage.style.setProperty('--stage-radius', `${lerp(from.radius, to.radius).toFixed(1)}px`);
        const glows = [
            ['rgba(45,212,191,.14)', '68%', '24%'],
            ['rgba(56,189,248,.2)', '52%', '38%'],
            ['rgba(245,158,11,.2)', '70%', '30%'],
            ['rgba(45,212,191,.24)', '78%', '18%'],
        ];
        const glow = glows[index];
        stage.style.setProperty('--stage-glow', glow[0]);
        stage.style.setProperty('--stage-glow-x', glow[1]);
        stage.style.setProperty('--stage-glow-y', glow[2]);
        stage.dataset.pose = String(progress >= .875 ? 3 : index);
    }

    async function createStoryController(canvas) {
        const THREE = await import('https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js');
        const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'low-power' });
        renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
        renderer.setClearColor(0x000000, 0);
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(42, 1, .1, 100);
        camera.position.set(0, 5.8, 9.5);
        camera.lookAt(0, 0, 0);
        scene.add(new THREE.HemisphereLight(0xb8fff4, 0x082b2b, 2.4));
        const key = new THREE.DirectionalLight(0xffffff, 2.1); key.position.set(3, 7, 5); scene.add(key);

        const terrainGeometry = new THREE.PlaneGeometry(12, 8, 24, 16);
        terrainGeometry.rotateX(-Math.PI / 2);
        const positions = terrainGeometry.attributes.position;
        for (let i = 0; i < positions.count; i++) {
            const x = positions.getX(i), z = positions.getZ(i);
            positions.setY(i, Math.sin(x * .65) * .55 + Math.cos(z * .9) * .35 + Math.sin((x + z) * 1.6) * .12);
        }
        terrainGeometry.computeVertexNormals();
        const terrain = new THREE.Mesh(terrainGeometry, new THREE.MeshStandardMaterial({ color: 0x0b766d, roughness: .9, flatShading: true, transparent: true, opacity: .88 }));
        scene.add(terrain);

        const sensorGeometry = new THREE.CylinderGeometry(.08, .11, .8, 8);
        const sensorPositions = [[-2.8,.55,-1.2],[-.8,.6,.5],[1.6,.45,-.4],[3,.65,1.25]];
        const sensorMaterials = sensorPositions.map(() => new THREE.MeshStandardMaterial({ color: 0xcffdf6, emissive: 0x0f766e, emissiveIntensity: .45 }));
        const sensors = sensorPositions.map((point, index) => { const mesh = new THREE.Mesh(sensorGeometry, sensorMaterials[index]); mesh.position.set(...point); scene.add(mesh); return mesh; });
        const node = new THREE.Mesh(new THREE.SphereGeometry(.24, 16, 12), new THREE.MeshStandardMaterial({ color: 0x2dd4bf, emissive: 0x0d9488, emissiveIntensity: 1 })); node.position.set(3.4, 1.2, -2); scene.add(node);
        const clusterRing = new THREE.Mesh(new THREE.RingGeometry(.55, .62, 32), new THREE.MeshBasicMaterial({ color: 0xffb020, transparent: true, opacity: 0, side: THREE.DoubleSide }));
        clusterRing.rotation.x = -Math.PI / 2; clusterRing.position.set(1.6, .08, -.4); scene.add(clusterRing);
        const networkPoints = [];
        sensorPositions.forEach(([x, y, z]) => { networkPoints.push(new THREE.Vector3(x, y + .1, z), new THREE.Vector3(3.4, 1.2, -2)); });
        const network = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(networkPoints), new THREE.LineBasicMaterial({ color: 0x5eead4, transparent: true, opacity: 0 })); scene.add(network);
        const acknowledgement = new THREE.Mesh(new THREE.RingGeometry(.26, .33, 32), new THREE.MeshBasicMaterial({ color: 0x5eead4, transparent: true, opacity: 0, side: THREE.DoubleSide }));
        acknowledgement.rotation.x = -Math.PI / 2; acknowledgement.position.set(3.4, .08, -2); scene.add(acknowledgement);
        const water = new THREE.Mesh(new THREE.PlaneGeometry(5, 2.5), new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0 })); water.rotation.x = -Math.PI / 2; water.position.set(-1, .1, 1.9); scene.add(water);
        const rainGeometry = new THREE.BufferGeometry();
        const rainPoints = new Float32Array(180 * 3);
        for (let i = 0; i < rainPoints.length; i += 3) { rainPoints[i] = (Math.random() - .5) * 11; rainPoints[i + 1] = Math.random() * 5; rainPoints[i + 2] = (Math.random() - .5) * 7; }
        rainGeometry.setAttribute('position', new THREE.BufferAttribute(rainPoints, 3));
        const rain = new THREE.Points(rainGeometry, new THREE.PointsMaterial({ color: 0x7dd3fc, size: .035, transparent: true, opacity: 0 })); scene.add(rain);
        const vectorGeometry = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-.8,.7,.5), new THREE.Vector3(-.1,.85,.15)]);
        const vector = new THREE.Line(vectorGeometry, new THREE.LineBasicMaterial({ color: 0xffb020, transparent: true, opacity: .9 })); scene.add(vector);

        let visible = true, destroyed = false, progress = 0;
        const resize = () => {
            const width = canvas.clientWidth, height = canvas.clientHeight;
            if (!width || !height) return;
            renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix(); render();
        };
        const render = () => { if (!destroyed && visible && !document.hidden) renderer.render(scene, camera); };
        const setProgress = value => {
            progress = Math.max(0, Math.min(1, value));
            const smooth = progress * progress * (3 - 2 * progress);
            const context = Math.max(0, Math.min(1, (smooth - .14) / .3));
            const corroborated = Math.max(0, Math.min(1, (smooth - .46) / .18));
            const response = Math.max(0, Math.min(1, (smooth - .7) / .2));
            camera.position.x = -smooth * 1.45; camera.position.z = 9.5 + smooth * 3.4; camera.position.y = 5.8 + smooth * 1.45;
            camera.lookAt(response * 1.05, .08, response * -.75);
            rain.material.opacity = context * .62;
            water.material.opacity = context * .34;
            terrain.material.opacity = .88 - Math.max(0, smooth - .48) * .25;
            sensors.forEach((sensor, index) => {
                sensor.scale.setScalar(1 + Math.max(0, smooth - .55) * (index === 2 ? .58 : .12));
                sensorMaterials[index].color.setHex(corroborated && index >= 1 ? 0xffb020 : 0xcffdf6);
                sensorMaterials[index].emissive.setHex(corroborated && index >= 1 ? 0xb45309 : 0x0f766e);
                sensorMaterials[index].emissiveIntensity = .45 + response * .35;
            });
            clusterRing.material.opacity = corroborated * .9;
            clusterRing.scale.setScalar(.85 + corroborated * .45);
            network.material.opacity = response * .72;
            acknowledgement.material.opacity = response * .96;
            acknowledgement.scale.setScalar(.75 + response * 1.8);
            node.material.emissiveIntensity = .7 + response * 3.2;
            vector.material.opacity = Math.max(.1, 1 - smooth * 1.1);
            render();
        };
        const resizeObserver = new ResizeObserver(resize); resizeObserver.observe(canvas);
        const visibilityObserver = new IntersectionObserver(entries => { visible = entries[0]?.isIntersecting ?? true; if (visible) render(); }, { rootMargin: '100px' }); visibilityObserver.observe(canvas);
        const onVisibility = () => { if (!document.hidden) render(); };
        const onTheme = () => { terrain.material.color.set(document.documentElement.dataset.theme === 'dark' ? 0x0d5f59 : 0x16877d); render(); };
        document.addEventListener('visibilitychange', onVisibility); window.addEventListener('themeChanged', onTheme);
        const destroy = () => {
            if (destroyed) return; destroyed = true;
            resizeObserver.disconnect(); visibilityObserver.disconnect(); document.removeEventListener('visibilitychange', onVisibility); window.removeEventListener('themeChanged', onTheme);
            scene.traverse(object => { object.geometry?.dispose?.(); if (Array.isArray(object.material)) object.material.forEach(material => material.dispose()); else object.material?.dispose?.(); });
            renderer.dispose(); renderer.forceContextLoss();
        };
        canvas.addEventListener('webglcontextlost', event => { event.preventDefault(); canvas.hidden = true; destroy(); }, { once: true });
        resize(); setProgress(progress);
        return { setProgress, destroy };
    }

    function setupStory() {
        const story = $('#story'), canvas = $('#story-canvas'), caption = $('#story-caption');
        if (!story) return;
        const captions = ['Phát hiện · Vector dịch chuyển', 'Bối cảnh · Mưa, nước và IMU', 'Làm rõ · Cần xác minh', 'Phản ứng · Đã tiếp nhận'];
        let frame = 0, controller = null, loading = false;
        // The sticky story is a CSS/poster experience first.  Three.js is an
        // enhancement, so a blocked CDN or unavailable WebGL must not turn the
        // desktop story into a static card or a long list of unrelated blocks.
        const desktopStory = innerWidth >= 1024 && !reducedMotion.matches;
        if (desktopStory) story.classList.add('story-enhanced');
        const update = () => {
            frame = 0;
            const rect = story.getBoundingClientRect();
            const range = Math.max(1, story.offsetHeight - innerHeight);
            const progress = Math.max(0, Math.min(1, -rect.top / range));
            const step = Math.min(3, Math.floor(progress * 4));
            story.style.setProperty('--story-progress', progress.toFixed(4));
            story.dataset.step = String(step);
            caption.textContent = captions[step];
            updateStoryStagePose(story, progress);
            controller?.setProgress(progress);
        };
        const queue = () => { if (!frame) frame = requestAnimationFrame(update); };
        addEventListener('scroll', queue, { passive: true }); addEventListener('resize', queue); update();
        if (canUseStory3D(canvas) && 'IntersectionObserver' in window) {
            const near = new IntersectionObserver(async entries => {
                if (!entries.some(entry => entry.isIntersecting) || controller || loading) return;
                loading = true; near.disconnect();
                try {
                    controller = await createStoryController(canvas);
                    canvas.classList.add('is-ready');
                    update();
                }
                catch (_) { canvas.hidden = true; }
            }, { rootMargin: '750px 0px' });
            near.observe(story);
        } else canvas.hidden = true;
        addEventListener('pagehide', () => controller?.destroy(), { once: true });
    }

    setupHeader();
    setupReveal();
    setupMetrics();
    setupStory();
    setupAuthLink().catch(() => {});
})();
