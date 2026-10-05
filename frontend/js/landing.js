import './session-state.js';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { BLENDER_META, decodeBlenderGLB } from './blender-assets.js';
import { renderLandingTemplate } from './templates/landing-template.js';

(() => {
    'use strict';

    gsap.registerPlugin(ScrollTrigger);

    const $ = (selector, root = document) => root.querySelector(selector);
    const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

    const mountRoot = document.getElementById('landing-root');
    if (mountRoot && !document.getElementById('main')) {
        const iconHref = $('link[rel="icon"]')?.getAttribute('href') || '/assets/aitogy.png';
        mountRoot.innerHTML = renderLandingTemplate(iconHref);
    }
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
    const cleanups = [];

    let currentQualityTier = 'high';
    const cpuCores = navigator.hardwareConcurrency || 4;
    if (navigator.connection?.saveData || reducedMotion.matches) {
        currentQualityTier = 'lite';
    } else if (cpuCores <= 4) {
        currentQualityTier = 'balanced';
    }

    let lenis = null;
    if (!reducedMotion.matches && typeof window.Lenis !== 'undefined') {
        lenis = new window.Lenis({
            duration: 1.15,
            easing: t => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
            smoothWheel: true
        });
        lenis.on('scroll', ScrollTrigger.update);
        const rafCb = time => lenis.raf(time * 1000);
        gsap.ticker.add(rafCb);
        gsap.ticker.lagSmoothing(0);
        document.addEventListener('click', event => {
            const anchor = event.target.closest('a[href^="#"]');
            if (anchor) {
                const targetId = anchor.getAttribute('href');
                if (targetId && targetId !== '#') {
                    event.preventDefault();
                    lenis.scrollTo(targetId, { offset: 0 });
                }
            }
        });
        cleanups.push(() => {
            lenis.destroy();
            gsap.ticker.remove(rafCb);
        });
    }

    function setTheme(theme) {
        document.documentElement.dataset.theme = theme;
        localStorage.setItem('theme', theme);
        $('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#071a1c' : '#f2f4ec');
        $('#theme-toggle')?.setAttribute('aria-label', theme === 'dark' ? 'Chuyển giao diện sáng' : 'Chuyển giao diện tối');
        dispatchEvent(new CustomEvent('themeChanged', { detail: { theme } }));
    }

    function setupHeader() {
        const header = $('.site-header');
        const menu = $('#mobile-menu');
        const toggle = $('#menu-toggle');
        let lastFocused = null;
        const focusable = () => $$('a[href], button:not([disabled])', menu);
        const close = () => {
            if (!menu || menu.hidden) return;
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
            const first = items[0], last = items.at(-1);
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        });
        $('#theme-toggle')?.addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
        const syncHeader = () => header?.classList.toggle('scrolled', scrollY > 12);
        addEventListener('scroll', syncHeader, { passive: true });
        syncHeader();
    }

    async function setupAuthLink() {
        const session = await window.authSession?.inspect?.();
        if (session?.status !== 'authenticated') return;
        const canManage = ['admin', 'operator'].includes(session.user?.role);
        const href = canManage ? '/management' : '/map';
        const label = canManage ? 'Quản trị hệ thống' : 'Mở bản đồ';
        $$('#auth-link, .mobile-menu a[href^="/login"], .final-cta a[href^="/login"]').forEach(link => { link.href = href; link.textContent = label; });
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
            let timeout;
            try {
                timeout = setTimeout(() => controller.abort(), 10000);
                const response = await fetch('/api/public/dashboard-summary', { signal: controller.signal, cache: 'no-store' });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                const stations = data?.stations || {};
                if (!Number(stations.total)) {
                    keys.forEach(key => { $(`#stations-${key}`).textContent = '0'; });
                    setState('empty', 'Chưa có trạm quan trắc trong mạng');
                    return;
                }
                const animateScramble = (el, finalVal, duration = 900) => {
                    if (!el) return;
                    if (!Number.isFinite(finalVal) || reducedMotion.matches) {
                        el.textContent = Number.isFinite(finalVal) ? new Intl.NumberFormat('vi-VN').format(finalVal) : '—';
                        return;
                    }
                    const finalStr = new Intl.NumberFormat('vi-VN').format(finalVal);
                    el.textContent = finalStr;
                    const chars = '0123456789';
                    const startTime = performance.now();
                    const tick = now => {
                        const elapsed = now - startTime;
                        const progress = Math.min(1, elapsed / duration);
                        if (progress >= 1) {
                            el.textContent = finalStr;
                            return;
                        }
                        const lockCount = Math.max(1, Math.floor(progress * finalStr.length));
                        let out = '';
                        for (let i = 0; i < finalStr.length; i++) {
                            if (i < lockCount || finalStr[i] === '.' || finalStr[i] === ',' || finalStr[i] === ' ') {
                                out += finalStr[i];
                            } else {
                                out += chars[Math.floor(Math.random() * chars.length)];
                            }
                        }
                        el.textContent = out;
                        requestAnimationFrame(tick);
                    };
                    requestAnimationFrame(tick);
                };
                keys.forEach(key => {
                    const el = $(`#stations-${key}`);
                    const val = Number(stations[key]);
                    if (Number.isFinite(val)) animateScramble(el, val);
                    else if (el) el.textContent = '—';
                });
                const updatedAt = new Date(data.updated_at);
                const stale = !Number.isFinite(updatedAt.getTime()) || Date.now() - updatedAt.getTime() > 15 * 60 * 1000;
                const formatted = Number.isFinite(updatedAt.getTime()) ? new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', timeStyle: 'short' }).format(updatedAt) : 'không rõ thời điểm';
                setState(stale ? 'stale' : 'ready', stale ? `Dữ liệu có thể đã cũ · ${formatted}` : `Cập nhật ${formatted}`, stale);
            } catch (error) {
                setState('error', error.name === 'AbortError' ? 'Không thể tải trạng thái mạng' : 'Mất kết nối dữ liệu trực tiếp', true);
            } finally { clearTimeout(timeout); }
        };
        retry?.addEventListener('click', load);
        load();
    }

    function canUse3D(canvas) {
        if (!canvas || reducedMotion.matches || navigator.connection?.saveData) return false;
        try {
            const probe = document.createElement('canvas');
            return Boolean(probe.getContext('webgl2') || probe.getContext('webgl'));
        } catch (_) { return false; }
    }

    function createRenderer(canvas) {
        const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: currentQualityTier !== 'lite', powerPreference: 'high-performance' });
        const maxRatio = currentQualityTier === 'high' ? 1.65 : (currentQualityTier === 'balanced' ? 1.35 : 1.0);
        renderer.setPixelRatio(Math.min(devicePixelRatio, maxRatio));
        renderer.setClearColor(0x000000, 0);
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.18;
        return renderer;
    }

    function watchCanvas(canvas, renderer, camera, render) {
        const resize = () => {
            const width = canvas.clientWidth, height = canvas.clientHeight;
            if (!width || !height) return;
            renderer.setSize(width, height, false);
            camera.aspect = width / height;
            camera.updateProjectionMatrix();
            render();
        };
        const observer = new ResizeObserver(resize);
        observer.observe(canvas.parentElement || canvas);
        resize();
        return () => observer.disconnect();
    }

    function disposeScene(scene, renderer) {
        scene.traverse(object => {
            object.geometry?.dispose?.();
            if (Array.isArray(object.material)) object.material.forEach(material => material.dispose());
            else object.material?.dispose?.();
        });
        renderer.dispose();
        renderer.forceContextLoss();
    }

    // ─── Shared Blender GLB Loader Cache ───
    let blenderScenePromise = null;
    function getBlenderTemplate() {
        if (!blenderScenePromise) {
            blenderScenePromise = new Promise((resolve, reject) => {
                try {
                    const loader = new GLTFLoader();
                    const buffer = decodeBlenderGLB();
                    loader.parse(buffer, '', gltf => resolve(gltf.scene), reject);
                } catch (err) {
                    reject(err);
                }
            });
        }
        return blenderScenePromise;
    }

    function instantiateBlenderTwin(template) {
        const root = template.clone(true);
        const nodes = {};
        root.traverse(obj => {
            if (obj.name) nodes[obj.name] = obj;
            if (obj.isMesh && obj.material) {
                obj.material = obj.material.clone();
                if (obj.geometry?.attributes?.color) {
                    obj.material.vertexColors = true;
                }
                if (['TerrainSurface', 'SlipSurface', 'UnstableWedge', 'GroundwaterTable', 'PiezometerWaterColumn'].includes(obj.name)) {
                    obj.material.transparent = true;
                }
            }
        });

        // Add subtle CAD topographic shimmer on top of the Blender TerrainSurface
        const terrain = nodes.TerrainSurface;
        if (terrain && terrain.geometry) {
            const wireGeo = new THREE.WireframeGeometry(terrain.geometry);
            const wireMat = new THREE.LineBasicMaterial({
                color: 0x5eead4,
                transparent: true,
                opacity: 0.024,
                blending: THREE.AdditiveBlending
            });
            const wireMesh = new THREE.LineSegments(wireGeo, wireMat);
            wireMesh.position.y = 0.008;
            terrain.add(wireMesh);
            nodes.TerrainWire = wireMesh;
        }
        return { root, nodes };
    }

    function createSignalArc(startArr, endArr, arcHeight = 1.6, color = 0x5eead4, opacity = 0.45) {
        const p0 = new THREE.Vector3(...startArr);
        const p2 = new THREE.Vector3(...endArr);
        const mid = p0.clone().add(p2).multiplyScalar(0.5);
        mid.y += arcHeight;
        const curve = new THREE.QuadraticBezierCurve3(p0, mid, p2);
        const points = curve.getPoints(44);
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const material = new THREE.LineBasicMaterial({
            color,
            transparent: true,
            opacity,
            blending: THREE.AdditiveBlending
        });
        const line = new THREE.Line(geometry, material);
        line.userData.curve = curve;
        return line;
    }

    function sampleRoadElevation(ry) {
        const prof = BLENDER_META.roadProfile;
        if (!Array.isArray(prof) || prof.length < 2) {
            return -0.58 + 0.08 * (ry / 5.4);
        }
        const t = THREE.MathUtils.clamp((ry + 5.0) / 10.0, 0, 1) * (prof.length - 1);
        const i0 = Math.floor(t);
        const i1 = Math.min(prof.length - 1, i0 + 1);
        const frac = t - i0;
        return prof[i0] * (1 - frac) + prof[i1] * frac;
    }

    function setupLivingTwinDynamics(nodes) {
        // 1. 12 Moving Highway Vehicles (6 Northbound in right lane +0.21, 6 Southbound in left lane -0.21)
        const vehicleConfigs = [
            // Northbound (+Y_blender / -Z_three, right lane +0.21)
            { name: 'Vehicle_01_PoliceCruiser', ry0: -4.45, laneX: 0.21, north: true, speed: 0.92, police: true },
            { name: 'Vehicle_02_RescueBoxTruck', ry0: -2.80, laneX: 0.215, north: true, speed: 0.92, rescue: true },
            { name: 'Vehicle_04_GeoFieldPickup', ry0: -1.15, laneX: 0.21, north: true, speed: 0.92 },
            { name: 'Vehicle_05_TelemetryMinivan', ry0: 0.50, laneX: 0.21, north: true, speed: 0.92 },
            { name: 'Vehicle_08_SportCoupe', ry0: 2.15, laneX: 0.21, north: true, speed: 0.92 },
            { name: 'Vehicle_11_PatrolInterceptor', ry0: 3.80, laneX: 0.21, north: true, speed: 0.92, police: true },
            // Southbound (-Y_blender / +Z_three, left lane -0.21)
            { name: 'Vehicle_07_SedanDaily', ry0: -3.95, laneX: -0.21, north: false, speed: 0.86 },
            { name: 'Vehicle_03_CivilianCharger', ry0: -2.30, laneX: -0.21, north: false, speed: 0.86 },
            { name: 'Vehicle_10_SurveyStriped', ry0: -0.65, laneX: -0.21, north: false, speed: 0.86 },
            { name: 'Vehicle_09_AlpineTourer', ry0: 1.00, laneX: -0.21, north: false, speed: 0.86 },
            { name: 'Vehicle_06_EngineeringVan', ry0: 2.65, laneX: -0.21, north: false, speed: 0.86 },
            { name: 'Vehicle_12_HeavyUtilityTruck', ry0: 4.30, laneX: -0.21, north: false, speed: 0.86, rescue: true }
        ];

        // In local car coordinates, front bumper (headlights) is at +Z.
        // Rotating ConeGeometry by -PI/2 around X puts the apex at -Z (bumper) and flares the wide beam toward +Z (ahead of car).
        const headConeGeo = new THREE.ConeGeometry(0.14, 0.48, 12, 1, true);
        headConeGeo.rotateX(-Math.PI / 2);
        const headConeMat = new THREE.MeshBasicMaterial({
            color: 0xfef08a,
            transparent: true,
            opacity: 0.22,
            side: THREE.DoubleSide,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });
        const strobeSphereGeo = new THREE.SphereGeometry(0.042, 8, 8);
        const redStrobeMat = new THREE.MeshBasicMaterial({
            color: 0xff1744,
            transparent: true,
            opacity: 0.95,
            blending: THREE.AdditiveBlending
        });
        const blueStrobeMat = new THREE.MeshBasicMaterial({
            color: 0x00b0ff,
            transparent: true,
            opacity: 0.95,
            blending: THREE.AdditiveBlending
        });
        const amberStrobeMat = new THREE.MeshBasicMaterial({
            color: 0xffab00,
            transparent: true,
            opacity: 0.95,
            blending: THREE.AdditiveBlending
        });

        const activeVehicles = [];
        vehicleConfigs.forEach(cfg => {
            const obj = nodes[cfg.name];
            if (!obj) return;
            const beamCone = new THREE.Mesh(headConeGeo, headConeMat);
            beamCone.position.set(0, 0.055, 0.46);
            obj.add(beamCone);

            let redLamp = null, blueLamp = null, amberLamp = null;
            if (cfg.police) {
                redLamp = new THREE.Mesh(strobeSphereGeo, redStrobeMat.clone());
                redLamp.position.set(-0.06, 0.24, 0.0);
                blueLamp = new THREE.Mesh(strobeSphereGeo, blueStrobeMat.clone());
                blueLamp.position.set(0.06, 0.24, 0.0);
                obj.add(redLamp, blueLamp);
            } else if (cfg.rescue) {
                amberLamp = new THREE.Mesh(strobeSphereGeo, amberStrobeMat.clone());
                amberLamp.position.set(0.0, 0.31, 0.15);
                obj.add(amberLamp);
            }
            activeVehicles.push({ ...cfg, obj, redLamp, blueLamp, amberLamp });
        });

        // 2. Attach Volumetric Searchlight & LiDAR Scan Cones to Both Rescue Helicopters & Quadcopter Drones
        const heli1 = nodes.Rescue_Helicopter_01;
        const heli1Rotor = nodes.Rescue_Helicopter_01_Rotor;
        const heli1Tail = nodes.Rescue_Helicopter_01_TailRotor;
        const heli2 = nodes.Rescue_Helicopter_02;
        const heli2Rotor = nodes.Rescue_Helicopter_02_Rotor;
        const heli2Tail = nodes.Rescue_Helicopter_02_TailRotor;

        let heliBeam1 = null, heliBeam2 = null;
        const heliConeGeo = new THREE.ConeGeometry(0.62, 1.95, 24, 1, true);
        if (heli1) {
            const hMat1 = new THREE.MeshBasicMaterial({
                color: 0x38bdf8,
                transparent: true,
                opacity: 0.20,
                side: THREE.DoubleSide,
                blending: THREE.AdditiveBlending,
                depthWrite: false
            });
            heliBeam1 = new THREE.Mesh(heliConeGeo, hMat1);
            heliBeam1.position.set(0, -1.05, 0.22);
            heli1.add(heliBeam1);
        }
        if (heli2) {
            const hMat2 = new THREE.MeshBasicMaterial({
                color: 0xfef08a,
                transparent: true,
                opacity: 0.18,
                side: THREE.DoubleSide,
                blending: THREE.AdditiveBlending,
                depthWrite: false
            });
            heliBeam2 = new THREE.Mesh(heliConeGeo, hMat2);
            heliBeam2.position.set(0, -1.00, 0.18);
            heli2.add(heliBeam2);
        }

        const drone = nodes.OpsSurveyDrone;
        const drone2 = nodes.OpsRescueDrone;
        let lidarCone = null, lidarCone2 = null;
        const lidarGeo = new THREE.ConeGeometry(0.42, 1.05, 20, 1, true);
        if (drone) {
            const lidarMat = new THREE.MeshBasicMaterial({
                color: 0x22d3ee,
                transparent: true,
                opacity: 0.22,
                side: THREE.DoubleSide,
                blending: THREE.AdditiveBlending,
                depthWrite: false
            });
            lidarCone = new THREE.Mesh(lidarGeo, lidarMat);
            lidarCone.position.set(0, -0.54, 0);
            drone.add(lidarCone);
        }
        if (drone2) {
            const lidarMat2 = new THREE.MeshBasicMaterial({
                color: 0xd7ef73,
                transparent: true,
                opacity: 0.20,
                side: THREE.DoubleSide,
                blending: THREE.AdditiveBlending,
                depthWrite: false
            });
            lidarCone2 = new THREE.Mesh(lidarGeo, lidarMat2);
            lidarCone2.position.set(0, -0.54, 0);
            drone2.add(lidarCone2);
        }

        // 3. Create Live 60 FPS Animated Grafana & WebGIS Command Center CanvasTexture for OpsVideoWall_Screen & OpsDeskMonitors
        let grafanaCanvas = null;
        let grafanaCtx = null;
        let grafanaTex = null;
        let lastGrafanaDraw = -1;
        if (typeof document !== 'undefined' && (nodes.OpsVideoWall_Screen || nodes.OpsDeskMonitors)) {
            grafanaCanvas = document.createElement('canvas');
            grafanaCanvas.width = 1024;
            grafanaCanvas.height = 384;
            grafanaCtx = grafanaCanvas.getContext('2d');
            if (grafanaCtx) {
                grafanaTex = new THREE.CanvasTexture(grafanaCanvas);
                grafanaTex.flipY = false;
                if (THREE.SRGBColorSpace) grafanaTex.colorSpace = THREE.SRGBColorSpace;
                const liveScreenMat = new THREE.MeshBasicMaterial({
                    map: grafanaTex,
                    toneMapped: false
                });
                if (nodes.OpsVideoWall_Screen) nodes.OpsVideoWall_Screen.material = liveScreenMat;
                if (nodes.OpsDeskMonitors) nodes.OpsDeskMonitors.material = liveScreenMat;
            }
        }

        function drawLiveGrafanaDashboard(elapsed) {
            if (!grafanaCtx || !grafanaTex) return;
            if (elapsed - lastGrafanaDraw < 0.04) return;
            lastGrafanaDraw = elapsed;
            const ctx = grafanaCtx;
            const W = 1024, H = 384;

            // Deep Grafana dark-slate background
            ctx.fillStyle = '#070e1b';
            ctx.fillRect(0, 0, W, H);

            // Top Grafana Global Navbar
            ctx.fillStyle = '#0e192d';
            ctx.fillRect(0, 0, W, 30);
            ctx.fillStyle = '#ff780a';
            ctx.beginPath();
            ctx.arc(20, 15, 7, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = '#e2f8f5';
            ctx.font = 'bold 12px monospace';
            ctx.fillText('GRAFANA LIVE // AITOGY DIGITAL TWIN · SECTOR 07', 35, 19);
            ctx.fillStyle = '#22c55e';
            ctx.fillText('● STREAMING 20Hz · RTK FIXED', 430, 19);
            ctx.fillStyle = '#38bdf8';
            const pktCount = 4820 + Math.floor(elapsed * 8);
            ctx.fillText(`PKT #${pktCount} | Δt 12ms | FoS 1.18`, 745, 19);

            const drawPanel = (x, y, w, h, title, badge, accent) => {
                ctx.fillStyle = '#0c1628';
                ctx.fillRect(x, y, w, h);
                ctx.strokeStyle = '#1e3454';
                ctx.lineWidth = 1.5;
                ctx.strokeRect(x, y, w, h);
                ctx.fillStyle = '#112038';
                ctx.fillRect(x + 1, y + 1, w - 2, 22);
                ctx.fillStyle = accent;
                ctx.fillRect(x + 1, y + 1, 4, 22);
                ctx.fillStyle = '#bae6fd';
                ctx.font = 'bold 10.5px monospace';
                ctx.fillText(title, x + 10, y + 15);
                ctx.fillStyle = accent;
                ctx.textAlign = 'right';
                ctx.fillText(badge, x + w - 8, y + 15);
                ctx.textAlign = 'left';
                ctx.strokeStyle = 'rgba(56, 189, 248, 0.09)';
                ctx.lineWidth = 1;
                for (let gy = y + 42; gy < y + h - 8; gy += 24) {
                    ctx.beginPath();
                    ctx.moveTo(x + 6, gy);
                    ctx.lineTo(x + w - 6, gy);
                    ctx.stroke();
                }
                for (let gx = x + 36; gx < x + w - 8; gx += 42) {
                    ctx.beginPath();
                    ctx.moveTo(gx, y + 24);
                    ctx.lineTo(gx, y + h - 6);
                    ctx.stroke();
                }
            };

            // 1. Top-Left Panel: GNSS RTK 3D Displacement (ΔE, ΔN, ΔU)
            const s2Val = (4.2 + Math.sin(elapsed * 1.8) * 0.4).toFixed(1);
            drawPanel(12, 36, 264, 162, 'GNSS RTK · ΔE/ΔN/ΔU (mm)', `+${s2Val}mm`, '#2dd4bf');
            const seriesSpecs = [
                { col: '#f59e0b', fill: 'rgba(245, 158, 11, 0.16)', base: 145, amp: 24, freq: 2.2, speed: 2.0 },
                { col: '#2dd4bf', fill: 'rgba(45, 212, 191, 0.12)', base: 158, amp: 14, freq: 3.1, speed: 2.6 },
                { col: '#a3e635', fill: null, base: 174, amp: 7, freq: 1.7, speed: 1.5 }
            ];
            seriesSpecs.forEach(s => {
                ctx.beginPath();
                for (let i = 0; i <= 48; i++) {
                    const px = 20 + (i / 48) * 248;
                    const t = i / 48;
                    const py = s.base - t * s.amp - Math.sin(t * 7.5 - elapsed * s.speed) * 9 - Math.cos(t * 15 - elapsed * 3.2) * 3;
                    if (i === 0) ctx.moveTo(px, py);
                    else ctx.lineTo(px, py);
                }
                ctx.strokeStyle = s.col;
                ctx.lineWidth = 2.2;
                ctx.stroke();
                if (s.fill) {
                    ctx.lineTo(268, 190);
                    ctx.lineTo(20, 190);
                    ctx.closePath();
                    ctx.fillStyle = s.fill;
                    ctx.fill();
                }
            });

            // 2. Bottom-Left Panel: Surface MEMS IMU 6-DoF Box (Roll / Pitch / Vibration)
            const imuRoll = (0.14 + Math.sin(elapsed * 3.2) * 0.03).toFixed(2);
            drawPanel(12, 206, 264, 166, 'MEMS IMU 6-DoF · ROLL/PITCH', `+${imuRoll}°`, '#f59e0b');
            [['#f97316', 292, 18, 4.8], ['#38bdf8', 316, 12, 3.6]].forEach(([col, yMid, amp, spd], idx) => {
                ctx.beginPath();
                for (let i = 0; i <= 54; i++) {
                    const px = 20 + (i / 54) * 248;
                    const t = i / 54;
                    const py = yMid + Math.sin(t * 18 - elapsed * spd) * amp * (0.45 + 0.55 * t) + Math.cos(t * 35 + elapsed * 6.0 + idx) * 4;
                    if (i === 0) ctx.moveTo(px, py);
                    else ctx.lineTo(px, py);
                }
                ctx.strokeStyle = col;
                ctx.lineWidth = 2.0;
                ctx.stroke();
            });

            // 3. Center-Left Top Panel: Grafana Arc Gauges (FoS & Pore Water Pressure)
            const kpaVal = (42.8 + Math.sin(elapsed * 1.5) * 1.6).toFixed(1);
            drawPanel(284, 36, 220, 162, 'SAFETY FACTOR & PORE kPa', 'LIVE', '#a3e635');
            const drawGauge = (cx, cy, r, frac, label, valText, col) => {
                ctx.lineWidth = 10;
                ctx.strokeStyle = '#1a2c47';
                ctx.beginPath();
                ctx.arc(cx, cy, r, Math.PI * 0.8, Math.PI * 2.2);
                ctx.stroke();
                ctx.strokeStyle = col;
                ctx.beginPath();
                ctx.arc(cx, cy, r, Math.PI * 0.8, Math.PI * (0.8 + 1.4 * frac));
                ctx.stroke();
                ctx.fillStyle = '#f8fafc';
                ctx.font = 'bold 14px monospace';
                ctx.textAlign = 'center';
                ctx.fillText(valText, cx, cy + 4);
                ctx.fillStyle = '#94a3b8';
                ctx.font = '10px monospace';
                ctx.fillText(label, cx, cy + 24);
                ctx.textAlign = 'left';
            };
            const fosDynamic = (1.18 + Math.sin(elapsed * 1.2) * 0.03).toFixed(2);
            drawGauge(342, 128, 36, 0.62 + Math.sin(elapsed * 1.2) * 0.04, 'FoS Index', fosDynamic, '#f59e0b');
            drawGauge(446, 128, 36, 0.74 + Math.sin(elapsed * 1.5) * 0.05, 'Pore kPa', `${kpaVal}`, '#38bdf8');

            // 4. Center-Right Top Panel: WebGIS Slope Heatmap & Active Sensor Nodes
            drawPanel(512, 36, 224, 162, 'WEBGIS · SLIP ZONE HEATMAP', '5 NODES', '#38bdf8');
            const hCx = 624, hCy = 126;
            const pulseR = 1 + Math.sin(elapsed * 3.0) * 0.06;
            [
                [68, 'rgba(20, 184, 166, 0.24)'],
                [48, 'rgba(234, 179, 8, 0.32)'],
                [30, 'rgba(249, 115, 22, 0.45)'],
                [16, 'rgba(239, 68, 68, 0.65)']
            ].forEach(([rad, fillCol]) => {
                ctx.fillStyle = fillCol;
                ctx.beginPath();
                ctx.ellipse(hCx, hCy, rad * pulseR, rad * 0.58 * pulseR, -0.18, 0, Math.PI * 2);
                ctx.fill();
            });
            [
                [568, 104, 'S1'],
                [616, 122, 'S2'],
                [604, 142, 'IMU'],
                [558, 148, 'RAIN'],
                [652, 152, 'PIEZO']
            ].forEach(([nx, ny, tag], idx) => {
                const blink = 0.5 + 0.5 * Math.sin(elapsed * 5.0 + idx * 1.3);
                ctx.fillStyle = `rgba(163, 230, 53, ${0.35 + blink * 0.65})`;
                ctx.beginPath();
                ctx.arc(nx, ny, 5 + blink * 2, 0, Math.PI * 2);
                ctx.fill();
                ctx.fillStyle = '#e2e8f0';
                ctx.font = 'bold 9px monospace';
                ctx.fillText(tag, nx + 7, ny + 3);
            });

            // 5. Center Bottom Wide Panel: AI Multi-Sensor Fusion & Live Telemetry Packet Ticker
            drawPanel(284, 206, 452, 166, 'AI FUSION · EARLY WARNING & PACKET STREAM', '98.4% CONF', '#2dd4bf');
            ctx.setLineDash([7, 5]);
            ctx.strokeStyle = '#ef4444';
            ctx.lineWidth = 1.6;
            ctx.beginPath();
            ctx.moveTo(294, 258);
            ctx.lineTo(726, 258);
            ctx.stroke();
            ctx.setLineDash([]);

            ctx.beginPath();
            for (let i = 0; i <= 64; i++) {
                const px = 294 + (i / 64) * 432;
                const t = i / 64;
                const py = 338 - Math.pow(t, 1.25) * 66 - Math.sin(t * 10 - elapsed * 2.8) * 8;
                if (i === 0) ctx.moveTo(px, py);
                else ctx.lineTo(px, py);
            }
            ctx.strokeStyle = '#2dd4bf';
            ctx.lineWidth = 2.5;
            ctx.stroke();
            ctx.lineTo(726, 344);
            ctx.lineTo(294, 344);
            ctx.closePath();
            ctx.fillStyle = 'rgba(45, 212, 191, 0.18)';
            ctx.fill();

            // Live Packet Log Bar at bottom of Center Panel
            ctx.fillStyle = '#081120';
            ctx.fillRect(292, 346, 436, 20);
            ctx.fillStyle = '#a3e635';
            ctx.font = '10px monospace';
            const tickerShift = Math.floor(elapsed * 3) % 4;
            const logs = [
                `[PKT#${pktCount} GNSS_S2 ΔE=+${s2Val}mm]  [PKT#${pktCount + 1} IMU Roll=+${imuRoll}°]`,
                `[PKT#${pktCount + 1} RAIN_TB 0.2mm/tip]  [PKT#${pktCount + 2} PIEZO ${kpaVal}kPa]`,
                `[PKT#${pktCount + 2} CORS_RTK FIXED]     [PKT#${pktCount + 3} AI_FUSION FoS=${fosDynamic}]`,
                `[PKT#${pktCount + 3} PIEZO +1.45m H2O]   [PKT#${pktCount + 4} GATE_WARN ACTIVE]`
            ];
            ctx.fillText(logs[tickerShift], 298, 360);

            // 6. Top-Right Panel: Tipping-Bucket Rainfall Histogram (0.2 mm / tip)
            drawPanel(744, 36, 268, 162, 'TIPPING-BUCKET RAIN (mm/h)', '68.4 mm/h', '#38bdf8');
            for (let b = 0; b < 16; b++) {
                const bx = 756 + b * 15.5;
                const bh = 24 + 86 * (0.38 + 0.62 * Math.abs(Math.sin(b * 0.55 - elapsed * 1.4)));
                ctx.fillStyle = '#0284c7';
                ctx.fillRect(bx, 190 - bh, 10.5, bh);
                ctx.fillStyle = '#7dd3fc';
                ctx.fillRect(bx, 190 - bh, 10.5, 4);
            }

            // 7. Bottom-Right Panel: Borehole Piezometer & Subsurface Groundwater Flow
            drawPanel(744, 206, 268, 166, 'PIEZOMETER & GROUNDWATER', '+1.45 m', '#38bdf8');
            ctx.beginPath();
            for (let i = 0; i <= 48; i++) {
                const px = 754 + (i / 48) * 248;
                const t = i / 48;
                const py = 342 - Math.pow(t, 1.1) * 76 - Math.sin(t * 9 - elapsed * 2.4) * 6;
                if (i === 0) ctx.moveTo(px, py);
                else ctx.lineTo(px, py);
            }
            ctx.strokeStyle = '#38bdf8';
            ctx.lineWidth = 2.4;
            ctx.stroke();
            ctx.lineTo(1002, 364);
            ctx.lineTo(754, 364);
            ctx.closePath();
            ctx.fillStyle = 'rgba(56, 189, 248, 0.25)';
            ctx.fill();

            grafanaTex.needsUpdate = true;
        }
        drawLiveGrafanaDashboard(0);

        // 4. Attach Floating HUD Label Sprites to the 3D DataPacket_* Capsules in the GLB Scene
        const glbPacketCurves = [
            { p0: new THREE.Vector3(-4.35, 3.08, -1.15), p2: new THREE.Vector3(5.15, 2.15, -0.07), arcH: 2.35, label: 'PKT·GNSS S1', col: '#2dd4bf' },
            { p0: new THREE.Vector3(-1.05, 1.88, 0.45), p2: new THREE.Vector3(3.87, 1.65, 0.00), arcH: 1.95, label: 'PKT·GNSS S2', col: '#a3e635' },
            { p0: new THREE.Vector3(-1.42, 1.80, 0.72), p2: new THREE.Vector3(4.30, 1.49, 0.90), arcH: 1.85, label: 'PKT·MEMS IMU', col: '#f59e0b' },
            { p0: new THREE.Vector3(-3.15, 2.22, 1.85), p2: new THREE.Vector3(4.70, 1.49, 0.90), arcH: 1.95, label: 'PKT·RAIN 0.2mm', col: '#38bdf8' },
            { p0: new THREE.Vector3(-1.75, 1.82, 2.28), p2: new THREE.Vector3(5.15, 1.33, 2.03), arcH: 1.75, label: 'PKT·PIEZO kPa', col: '#38bdf8' }
        ];
        const glbPackets = [];
        glbPacketCurves.forEach((spec, lIdx) => {
            const p1 = spec.p0.clone().add(spec.p2).multiplyScalar(0.5);
            p1.y += spec.arcH;
            for (let pSub = 0; pSub < 2; pSub++) {
                const pktObj = nodes[`DataPacket_${lIdx}_${pSub}`];
                if (!pktObj) continue;
                if (typeof document !== 'undefined' && pSub === 0) {
                    const tagCanvas = document.createElement('canvas');
                    tagCanvas.width = 256;
                    tagCanvas.height = 64;
                    const tCtx = tagCanvas.getContext('2d');
                    if (tCtx) {
                        tCtx.fillStyle = 'rgba(7, 18, 32, 0.88)';
                        tCtx.fillRect(4, 8, 248, 48);
                        tCtx.strokeStyle = spec.col;
                        tCtx.lineWidth = 3;
                        tCtx.strokeRect(4, 8, 248, 48);
                        tCtx.fillStyle = spec.col;
                        tCtx.font = 'bold 24px monospace';
                        tCtx.textAlign = 'center';
                        tCtx.fillText(spec.label, 128, 40);
                        const tagTex = new THREE.CanvasTexture(tagCanvas);
                        const sprMat = new THREE.SpriteMaterial({
                            map: tagTex,
                            transparent: true,
                            depthTest: false
                        });
                        const spr = new THREE.Sprite(sprMat);
                        spr.scale.set(0.68, 0.17, 1);
                        spr.position.set(0, 0.22, 0);
                        pktObj.add(spr);
                    }
                }
                glbPackets.push({
                    obj: pktObj,
                    p0: spec.p0,
                    p1,
                    p2: spec.p2,
                    speed: 0.34 + lIdx * 0.04,
                    phase: (lIdx * 0.19 + pSub * 0.5) % 1.0
                });
            }
        });

        const span = 10.0;
        const halfDepth = 5.4;
        return {
            update(elapsed) {
                drawLiveGrafanaDashboard(elapsed);

                // Animate Surface MEMS IMU Box Tilting & 3-Axis Orthogonal Gyroscope Gimbal Rings
                if (nodes.IMU_Casing) {
                    nodes.IMU_Casing.rotation.x = Math.sin(elapsed * 3.4) * 0.14;
                    nodes.IMU_Casing.rotation.z = Math.cos(elapsed * 2.8) * 0.16;
                }
                if (nodes.IMU_Gimbal_Roll) {
                    nodes.IMU_Gimbal_Roll.rotation.x = Math.sin(elapsed * 3.4) * 0.35;
                }
                if (nodes.IMU_Gimbal_Pitch) {
                    nodes.IMU_Gimbal_Pitch.rotation.z = Math.cos(elapsed * 2.8) * 0.35;
                }
                if (nodes.IMU_Gimbal_Yaw) {
                    nodes.IMU_Gimbal_Yaw.rotation.y = elapsed * 1.8;
                }

                // Animate Tipping-Bucket Rain Gauge Seesaw & Falling Rain Drops
                if (nodes.Rain_TippingBucket) {
                    const targetTilt = Math.sin(elapsed * 3.6) >= 0 ? 0.34 : -0.34;
                    nodes.Rain_TippingBucket.rotation.z += (targetTilt - nodes.Rain_TippingBucket.rotation.z) * 0.25;
                }
                if (nodes.Rain_FallingDrops) {
                    nodes.Rain_FallingDrops.position.y = -((elapsed * 1.6) % 1.0) * 0.15;
                }

                // Animate Underground Groundwater Flow Streamlines & Droplets Past the Suspended Borehole Piezometer Probe
                if (nodes.Piezo_WaterFlowParticles) {
                    nodes.Piezo_WaterFlowParticles.position.x = ((elapsed * 0.95) % 1.0 - 0.5) * 0.32;
                }
                if (nodes.Piezometer_Probe) {
                    nodes.Piezometer_Probe.position.y = Math.sin(elapsed * 3.0) * 0.015;
                }

                // Animate 10 3D Data Packet Capsules Streaming Along Telemetry Conduits into the Data Center
                glbPackets.forEach(pk => {
                    const t = (elapsed * pk.speed + pk.phase) % 1.0;
                    const inv = 1.0 - t;
                    pk.obj.position.set(
                        inv * inv * pk.p0.x + 2 * inv * t * pk.p1.x + t * t * pk.p2.x,
                        inv * inv * pk.p0.y + 2 * inv * t * pk.p1.y + t * t * pk.p2.y,
                        inv * inv * pk.p0.z + 2 * inv * t * pk.p1.z + t * t * pk.p2.z
                    );
                    pk.obj.rotation.y = elapsed * 2.5;
                });

                // Move all 12 vehicles continuously along the curved 10.8m mountain highway in their exact forward lane direction
                activeVehicles.forEach(v => {
                    const dir = v.north ? 1.0 : -1.0;
                    const rawRy = (((v.ry0 + 5.0 + dir * elapsed * v.speed) % span) + span) % span - 5.0;
                    const rc = 2.65 + 0.24 * Math.sin((rawRy / halfDepth) * 1.5);
                    const vx = rc + v.laneX;
                    const vz = sampleRoadElevation(rawRy) + 0.030;
                    const dxDy = 0.24 * (1.5 / halfDepth) * Math.cos((rawRy / halfDepth) * 1.5);
                    const yaw = v.north ? Math.atan2(dxDy, -1.0) : Math.atan2(-dxDy, 1.0);

                    v.obj.position.set(vx, vz, -rawRy);
                    v.obj.rotation.set(0, yaw, 0);

                    if (v.redLamp && v.blueLamp) {
                        const flash = Math.sin(elapsed * 22.0) > 0;
                        v.redLamp.scale.setScalar(flash ? 1.5 : 0.55);
                        v.blueLamp.scale.setScalar(flash ? 0.55 : 1.5);
                    }
                    if (v.amberLamp) {
                        const pulse = 0.75 + Math.abs(Math.sin(elapsed * 14.0)) * 0.80;
                        v.amberLamp.scale.setScalar(pulse);
                    }
                });

                // Fly Both AW101 Rescue Helicopters & Spin Main + Tail Rotors at High Speed
                if (heli1) {
                    const hAng = elapsed * 0.38;
                    const hx = -0.35 + Math.cos(hAng) * 1.95;
                    const hy = -0.25 + Math.sin(hAng * 2.0) * 1.15;
                    const hz = 2.78 + Math.sin(hAng * 1.5) * 0.16;
                    const vx = -Math.sin(hAng) * 1.95;
                    const vzThree = -Math.cos(hAng * 2.0) * 2.30;
                    const hyaw = Math.atan2(vx, vzThree);
                    heli1.position.set(hx, hz, -hy);
                    heli1.rotation.set(0.09, hyaw, Math.sin(hAng) * 0.12);
                    if (heliBeam1) {
                        heliBeam1.material.opacity = 0.14 + Math.abs(Math.sin(elapsed * 2.8)) * 0.12;
                    }
                }
                if (heli1Rotor) {
                    heli1Rotor.rotation.y = elapsed * 24.0;
                }
                if (heli1Tail) {
                    heli1Tail.rotation.x = elapsed * 32.0;
                }

                if (heli2) {
                    const hAng2 = elapsed * 0.34 + 1.2;
                    const hx2 = 4.05 + Math.sin(hAng2) * 1.10;
                    const hy2 = -0.85 + Math.cos(hAng2) * 0.95;
                    const hz2 = 2.18 + Math.cos(hAng2 * 2.0) * 0.12;
                    const vx2 = Math.cos(hAng2) * 1.10;
                    const vzThree2 = Math.sin(hAng2) * 0.95;
                    const hyaw2 = Math.atan2(vx2, vzThree2);
                    heli2.position.set(hx2, hz2, -hy2);
                    heli2.rotation.set(0.07, hyaw2, -Math.cos(hAng2) * 0.10);
                    if (heliBeam2) {
                        heliBeam2.material.opacity = 0.12 + Math.abs(Math.cos(elapsed * 2.5)) * 0.10;
                    }
                }
                if (heli2Rotor) {
                    heli2Rotor.rotation.y = -elapsed * 24.0;
                }
                if (heli2Tail) {
                    heli2Tail.rotation.x = -elapsed * 32.0;
                }

                // Rotate Data Center Phased-Array Doppler Radar, Dual Ku-Band Dishes & Control Room 3D Hologram
                if (nodes.OpsBeaconCore) {
                    nodes.OpsBeaconCore.rotation.y = elapsed * 2.2;
                }
                if (nodes.OpsTrackingDish) {
                    nodes.OpsTrackingDish.rotation.y = Math.sin(elapsed * 0.65) * 0.55;
                    nodes.OpsTrackingDish.rotation.x = Math.cos(elapsed * 0.42) * 0.08;
                }
                if (nodes.OpsSecondaryDish) {
                    nodes.OpsSecondaryDish.rotation.y = -Math.sin(elapsed * 0.52) * 0.48;
                    nodes.OpsSecondaryDish.rotation.x = Math.sin(elapsed * 0.38) * 0.07;
                }
                if (nodes.OpsHoloTerrain) {
                    nodes.OpsHoloTerrain.rotation.y = elapsed * 0.95;
                    nodes.OpsHoloTerrain.position.y = 0.51 + Math.sin(elapsed * 2.4) * 0.016;
                }

                // Fly Autonomous Survey Quadcopter Drones across the Data Center & Landslide Slip Zone
                if (drone) {
                    const dAng = elapsed * 0.55;
                    const bx = 2.15 + Math.cos(dAng) * 2.35;
                    const by = -0.65 + Math.sin(dAng * 2.0) * 0.85;
                    const bz = 1.15 + Math.sin(dAng * 1.5) * 0.18 + (bx < 1.2 ? (1.2 - bx) * 0.25 : 0);
                    drone.position.set(bx, bz, -by);
                    drone.rotation.set(
                        Math.cos(dAng * 2.0) * 0.10,
                        dAng + Math.PI * 0.5,
                        Math.sin(dAng) * 0.12
                    );
                    if (lidarCone) {
                        lidarCone.material.opacity = 0.15 + Math.abs(Math.sin(elapsed * 3.5)) * 0.12;
                    }
                }
                if (drone2) {
                    const dAng2 = elapsed * 0.48 + 1.4;
                    const bx2 = -1.35 + Math.sin(dAng2) * 1.85;
                    const by2 = 0.65 + Math.cos(dAng2 * 2.0) * 0.95;
                    const bz2 = 1.55 + Math.cos(dAng2 * 1.4) * 0.16 + Math.max(0, -bx2 * 0.22);
                    drone2.position.set(bx2, bz2, -by2);
                    drone2.rotation.set(
                        Math.sin(dAng2 * 2.0) * 0.09,
                        -dAng2,
                        Math.cos(dAng2) * 0.10
                    );
                    if (lidarCone2) {
                        lidarCone2.material.opacity = 0.14 + Math.abs(Math.cos(elapsed * 3.2)) * 0.12;
                    }
                }
            }
        };
    }

    // ─── HERO 3D CONTROLLER (Blender GLB Twin + Orbital Constellation) ───
    function createHeroController(canvas) {
        const renderer = createRenderer(canvas);
        const scene = new THREE.Scene();
        scene.fog = new THREE.FogExp2(0x061b1d, 0.018);

        const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 140);
        camera.position.set(-1.65, 4.95, 10.85);

        scene.add(new THREE.HemisphereLight(0xd2fff7, 0x041517, 2.25));
        const sun = new THREE.DirectionalLight(0xf0fdfa, 2.65);
        sun.position.set(-6, 11, 8);
        scene.add(sun);

        const tealRim = new THREE.PointLight(0x2dd4bf, 6.0, 24);
        tealRim.position.set(-5.5, 4.5, -4.5);
        scene.add(tealRim);

        const slipGlow = new THREE.PointLight(0xffb020, 4.8, 16);
        slipGlow.position.set(-1.1, 2.2, 0.6);
        scene.add(slipGlow);

        const worldGroup = new THREE.Group();
        scene.add(worldGroup);

        const anchors = BLENDER_META.anchors;
        const packets = [];
        const satBeams = [];
        let twinNodes = {};
        let livingDynamics = null;

        // Atmospheric floating telemetry dust
        const dustCount = 110;
        const dustPos = new Float32Array(dustCount * 3);
        for (let i = 0; i < dustPos.length; i += 3) {
            dustPos[i] = (Math.random() - 0.5) * 16;
            dustPos[i + 1] = Math.random() * 5.5 - 0.5;
            dustPos[i + 2] = (Math.random() - 0.5) * 12;
        }
        const dustGeo = new THREE.BufferGeometry();
        dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPos, 3));
        const dust = new THREE.Points(dustGeo, new THREE.PointsMaterial({
            color: 0x8af1e2,
            size: 0.048,
            transparent: true,
            opacity: 0.55,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        }));
        worldGroup.add(dust);

        // Load Blender GLB Scene
        getBlenderTemplate().then(template => {
            if (destroyed) return;
            const { root, nodes } = instantiateBlenderTwin(template);
            twinNodes = nodes;
            if (nodes.TerrainSurface) nodes.TerrainSurface.material.opacity = 0.90;
            worldGroup.add(root);
            livingDynamics = setupLivingTwinDynamics(nodes);

            // Build telemetry arcs from Rover stations & Base CORS to Operations Hub
            const arcConfigs = [
                [anchors.gnss_base, anchors.gnss_mid, 1.5, 0xd7ef73],
                [anchors.gnss_crown, anchors.ops_hub, 2.4, 0x5eead4],
                [anchors.gnss_mid, anchors.ops_hub, 2.0, 0xffb020],
                [anchors.gnss_toe, anchors.ops_hub, 1.4, 0x5eead4]
            ];
            const packetGeo = new THREE.SphereGeometry(0.075, 10, 10);
            arcConfigs.forEach(([from, to, h, col], idx) => {
                const arc = createSignalArc(from, to, h, col, 0.42);
                worldGroup.add(arc);
                const packet = new THREE.Mesh(packetGeo, new THREE.MeshBasicMaterial({
                    color: col,
                    transparent: true,
                    opacity: 0.95,
                    blending: THREE.AdditiveBlending
                }));
                worldGroup.add(packet);
                packets.push({ mesh: packet, curve: arc.userData.curve, speed: 0.28 + idx * 0.06, phase: idx * 0.25 });
            });

            // Satellite carrier-phase beams down to stations from all 8 NASA/CubeSat satellites
            const satNames = [
                'GNSS_Sat_01', 'GNSS_Sat_02', 'GNSS_Sat_03', 'GNSS_Sat_04',
                'GNSS_Sat_05', 'GNSS_Sat_06', 'GNSS_Sat_07', 'GNSS_Sat_08'
            ];
            const targetAnchors = [
                anchors.gnss_base,
                anchors.gnss_mid,
                anchors.gnss_toe,
                anchors.ops_hub,
                anchors.gnss_crown,
                anchors.gnss_mid,
                anchors.gnss_base,
                anchors.ops_hub
            ];
            satNames.forEach((name, idx) => {
                const satObj = nodes[name];
                if (!satObj) return;
                const beamGeo = new THREE.BufferGeometry();
                beamGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
                const beam = new THREE.Line(beamGeo, new THREE.LineBasicMaterial({
                    color: idx % 2 === 0 ? 0xd7ef73 : 0x5eead4,
                    transparent: true,
                    opacity: 0.24,
                    blending: THREE.AdditiveBlending
                }));
                worldGroup.add(beam);
                satBeams.push({ satObj, target: new THREE.Vector3(...targetAnchors[idx]), beam, phase: idx * 0.85 });
            });

            canvas.classList.add('is-ready');
            render();
        }).catch(() => {});

        let progress = 0, pointerX = 0, pointerY = 0, active = true, destroyed = false, frame = 0;
        const satWorldPos = new THREE.Vector3();

        const onPointerMove = e => {
            const rect = canvas.getBoundingClientRect();
            if (!rect.width || !rect.height) return;
            pointerX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
            pointerY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
        };
        const heroVisual = canvas.parentElement;
        heroVisual?.addEventListener('pointermove', onPointerMove, { passive: true });

        const render = () => {
            if (destroyed || !active || document.hidden) return;
            renderer.render(scene, camera);
        };

        const tick = time => {
            frame = 0;
            if (destroyed || !active || document.hidden) return;
            const elapsed = time * 0.001;

            // Gentle orbital breathing + pointer parallax + scroll dolly
            worldGroup.rotation.y = Math.sin(elapsed * 0.22) * 0.08 + pointerX * 0.14 - progress * 0.32;
            worldGroup.rotation.x = pointerY * 0.06 + progress * 0.08;
            dust.rotation.y = elapsed * 0.03;

            // Animate data packets along telemetry arcs
            packets.forEach(p => {
                const t = (elapsed * p.speed + p.phase) % 1;
                p.curve.getPoint(t, p.mesh.position);
            });

            // Animate high-altitude GNSS satellites & carrier beams
            if (twinNodes.Satellite_Constellation) {
                twinNodes.Satellite_Constellation.position.x = -0.15 + Math.sin(elapsed * 0.45) * 0.42;
                twinNodes.Satellite_Constellation.position.z = Math.cos(elapsed * 0.35) * 0.28;
            }
            satBeams.forEach(({ satObj, target, beam, phase }) => {
                satObj.rotation.y += 0.008;
                satObj.getWorldPosition(satWorldPos);
                worldGroup.worldToLocal(satWorldPos);
                const posAttr = beam.geometry.attributes.position;
                posAttr.setXYZ(0, satWorldPos.x, satWorldPos.y, satWorldPos.z);
                posAttr.setXYZ(1, target.x, target.y, target.z);
                posAttr.needsUpdate = true;
                beam.material.opacity = 0.14 + Math.max(0, Math.sin(elapsed * 2.4 + phase)) * 0.22;
            });

            // Pulse GNSS station rings & slip surface
            ['GNSS_Station_Crown_Ring', 'GNSS_Station_Mid_Ring', 'GNSS_Station_Toe_Ring', 'GNSS_Base_CORS_Ring'].forEach((rName, idx) => {
                const ring = twinNodes[rName];
                if (ring) {
                    const s = 1 + Math.sin(elapsed * 2.2 + idx) * 0.12;
                    ring.scale.set(s, 1, s);
                }
            });
            if (twinNodes.DisplacementVectorArrow) {
                twinNodes.DisplacementVectorArrow.position.x = Math.sin(elapsed * 2.8) * 0.06;
            }
            livingDynamics?.update(elapsed);

            camera.position.set(
                -1.65 + progress * 1.15 + pointerX * 0.42,
                4.95 - progress * 0.65 - pointerY * 0.26,
                10.85 - progress * 1.65
            );
            camera.lookAt(0.18 + progress * 0.30, 1.28, 0.10);

            render();
            frame = requestAnimationFrame(tick);
        };

        const setProgress = value => {
            progress = THREE.MathUtils.clamp(value, 0, 1);
            render();
        };

        const stopResize = watchCanvas(canvas, renderer, camera, render);
        const resume = () => { if (active && !document.hidden && !frame && !destroyed) frame = requestAnimationFrame(tick); };
        const visibility = new IntersectionObserver(entries => {
            active = entries[0]?.isIntersecting ?? true;
            if (active) resume();
        }, { rootMargin: '120px' });
        visibility.observe(canvas);
        document.addEventListener('visibilitychange', resume);
        frame = requestAnimationFrame(tick);
        canvas.classList.add('is-ready');

        return {
            setProgress,
            destroy() {
                if (destroyed) return;
                destroyed = true;
                cancelAnimationFrame(frame);
                heroVisual?.removeEventListener('pointermove', onPointerMove);
                document.removeEventListener('visibilitychange', resume);
                visibility.disconnect();
                stopResize();
                disposeScene(scene, renderer);
            }
        };
    }

    // ─── STORY 3D CONTROLLER (Cinematic Video-Demo Flythrough: Sensor-by-Sensor -> Zoom Out -> Follow Data -> Door Opens -> Control Room) ───
    function createStoryController(canvas, calloutContainer) {
        const renderer = createRenderer(canvas);
        const scene = new THREE.Scene();
        scene.fog = new THREE.FogExp2(0x061f21, 0.015);

        const camera = new THREE.PerspectiveCamera(42, 1, 0.08, 140);
        scene.add(new THREE.HemisphereLight(0xd0fff6, 0x041618, 2.35));
        const dirLight = new THREE.DirectionalLight(0xffffff, 2.5);
        dirLight.position.set(-5, 12, 8);
        scene.add(dirLight);

        const slipLight = new THREE.PointLight(0xff9e1b, 4.8, 18);
        slipLight.position.set(-1.1, 2.1, 0.6);
        scene.add(slipLight);

        const waterLight = new THREE.PointLight(0x38bdf8, 4.2, 18);
        waterLight.position.set(-2.2, 0.6, 4.8);
        scene.add(waterLight);

        // Interior Control Room Illumination (lights up the 5-screen command wall, operator desks & 3D hologram!)
        const controlRoomLight = new THREE.PointLight(0x2dd4bf, 5.8, 12);
        controlRoomLight.position.set(5.15, 0.92, 0.68);
        scene.add(controlRoomLight);

        const worldGroup = new THREE.Group();
        scene.add(worldGroup);

        const anchors = BLENDER_META.anchors;
        const opsEntranceAnchor = anchors.ops_entrance || [5.15, 0.455, 2.07];
        const opsHoloAnchor = anchors.ops_holo_table || [5.15, 0.455, 0.73];
        const opsControlAnchor = anchors.ops_control_room || [5.15, 0.635, 0.19];

        let twinNodes = {};
        let initialGroundwaterY = 0;
        let initialWedgePos = null;
        let initialMidStationPos = null;
        let initialImuPos = null;

        // 1. Rain Storm Particle System (Act 2: Hydrological Context)
        const rainCount = 260;
        const rainPositions = new Float32Array(rainCount * 3);
        for (let i = 0; i < rainPositions.length; i += 3) {
            rainPositions[i] = (Math.random() - 0.5) * 15;
            rainPositions[i + 1] = Math.random() * 5.8 - 0.2;
            rainPositions[i + 2] = (Math.random() - 0.5) * 11;
        }
        const rainGeo = new THREE.BufferGeometry();
        rainGeo.setAttribute('position', new THREE.BufferAttribute(rainPositions, 3));
        const rainMat = new THREE.PointsMaterial({
            color: 0x7dd3fc,
            size: 0.055,
            transparent: true,
            opacity: 0,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });
        const rainSystem = new THREE.Points(rainGeo, rainMat);
        worldGroup.add(rainSystem);

        // 2. Active Sensor Data-Capture Laser Halo (Moves from device to device as camera samples each station!)
        const activeScanGroup = new THREE.Group();
        const scanCylGeo = new THREE.CylinderGeometry(0.46, 0.46, 0.95, 32, 1, true);
        const scanCylMat = new THREE.MeshBasicMaterial({
            color: 0x5eead4,
            transparent: true,
            opacity: 0,
            side: THREE.DoubleSide,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });
        const scanCylMesh = new THREE.Mesh(scanCylGeo, scanCylMat);
        const scanRingGeo = new THREE.RingGeometry(0.48, 0.62, 40);
        const scanRingMat = new THREE.MeshBasicMaterial({
            color: 0xd7ef73,
            transparent: true,
            opacity: 0,
            side: THREE.DoubleSide,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });
        const scanRingMesh = new THREE.Mesh(scanRingGeo, scanRingMat);
        scanRingMesh.rotation.x = -Math.PI / 2;
        activeScanGroup.add(scanCylMesh, scanRingMesh);
        worldGroup.add(activeScanGroup);

        // 3. Baseline Triangulation Network (Act 3: Zoom-Out Multi-Sensor Fusion)
        const baselineGroup = new THREE.Group();
        worldGroup.add(baselineGroup);
        const baselinePairs = [
            [anchors.gnss_base, anchors.gnss_crown, 0.85, 0x5eead4],
            [anchors.gnss_base, anchors.gnss_mid, 1.05, 0xffb020],
            [anchors.gnss_base, anchors.gnss_toe, 1.25, 0x5eead4],
            [anchors.gnss_crown, anchors.gnss_mid, 0.55, 0xffb020],
            [anchors.gnss_mid, anchors.gnss_toe, 0.55, 0xffb020],
            [anchors.imu_borehole, anchors.piezometer, 0.45, 0x38bdf8],
            [anchors.rain_gauge, anchors.piezometer, 0.55, 0x38bdf8]
        ];
        const baselineLines = baselinePairs.map(([a, b, h, col]) => {
            const line = createSignalArc(a, b, h, col, 0);
            baselineGroup.add(line);
            return line;
        });

        // 4. Operations Dispatch Arcs & Hero Data Packets Streaming to the Data Center Rooftop Receiver Array!
        const opsRoofReceiver = [5.15, 1.48, 0.90];
        const dispatchGroup = new THREE.Group();
        worldGroup.add(dispatchGroup);
        const dispatchPairs = [
            [anchors.gnss_crown, opsRoofReceiver, 2.55, 0x5eead4],
            [anchors.gnss_mid, opsRoofReceiver, 2.05, 0xffb020],
            [anchors.imu_borehole, opsRoofReceiver, 1.95, 0xd7ef73],
            [anchors.rain_gauge, opsRoofReceiver, 2.15, 0x38bdf8],
            [anchors.piezometer, opsRoofReceiver, 1.85, 0x38bdf8],
            [opsRoofReceiver, anchors.highway_gate, 1.15, 0xd7ef73]
        ];
        const dispatchLines = [];
        const dispatchPackets = [];
        const pktGeo = new THREE.SphereGeometry(0.105, 14, 14);
        dispatchPairs.forEach(([a, b, h, col], idx) => {
            const arc = createSignalArc(a, b, h, col, 0.38);
            dispatchGroup.add(arc);
            dispatchLines.push(arc);
            const pkt = new THREE.Mesh(pktGeo, new THREE.MeshBasicMaterial({
                color: col,
                transparent: true,
                opacity: 0.85,
                blending: THREE.AdditiveBlending
            }));
            dispatchGroup.add(pkt);
            dispatchPackets.push({ mesh: pkt, curve: arc.userData.curve, speed: 0.38 + idx * 0.05, phase: idx * 0.18 });
        });

        // Expanding safety rings at Operations Center Entrance & Highway Gate
        const safetyRingGeo = new THREE.RingGeometry(0.45, 0.58, 48);
        const opsPulseRing = new THREE.Mesh(safetyRingGeo, new THREE.MeshBasicMaterial({
            color: 0xd7ef73,
            transparent: true,
            opacity: 0,
            side: THREE.DoubleSide,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        }));
        opsPulseRing.rotation.x = -Math.PI / 2;
        opsPulseRing.position.set(opsEntranceAnchor[0], opsEntranceAnchor[1] - 0.25, opsEntranceAnchor[2]);
        worldGroup.add(opsPulseRing);

        // 5. 12-Point Cinematic Video-Demo Camera Choreography:
        //    [0..1] Gentle Slower Dwell on GNSS RTK Stations (Carrier-Phase ΔE/ΔN/ΔU & CORS Differential Waves)
        //    [2..3] Close-Up Inspection of Surface MEMS IMU 6-DoF Box & 3-Axis Gyroscope Gimbal Rings
        //    [4]    Close-Up Inspection of Cutaway Tipping-Bucket Rain Gauge (Falling Rain & Seesaw Bucket)
        //    [5..6] Close-Up Inspection of Open-Cutaway Borehole Piezometer, Lowered Sensor Probe & Flowing Groundwater
        //    [7..8] Wide Zoom-Out Panorama & Chasing Labeled Data Packets ([PKT GNSS], [PKT IMU], [PKT RAIN], [PKT PIEZO])
        //    [9..11] Arrive at Modern Glass Data Center (Sliding Doors Open!) -> Fly Inside Control Room to Live Grafana Video Wall!
        const camCurve = new THREE.CatmullRomCurve3([
            new THREE.Vector3(-1.55, 2.48, 2.05),  // 0.00: Gentle arrival at GNSS RTK Rover S2 & Crown RTK Link
            new THREE.Vector3(-1.25, 2.22, 1.68),  // 0.09: Slow dwell around GNSS RTK Antenna Phase Center & ΔE/ΔN/ΔU Triad
            new THREE.Vector3(-2.05, 2.02, 1.62),  // 0.18: Unobstructed close-up on Surface MEMS IMU 6-DoF Box & 3 Gyroscope Gimbals
            new THREE.Vector3(-2.12, 1.98, 1.66),  // 0.27: Dwell on MEMS IMU Box Tilting & Downslope Shear Vector
            new THREE.Vector3(-3.38, 2.18, 2.72),  // 0.36: Close-up on Cutaway Tipping-Bucket Rain Gauge & Seesaw Bucket
            new THREE.Vector3(-2.05, 1.38, 4.35),  // 0.45: Full view of Open-Cutaway Borehole Piezometer, Winch & Lowered Probe
            new THREE.Vector3(-1.92, 1.32, 4.25),  // 0.55: Dwell on Underground Groundwater Table & Horizontal Water Flow Streamlines
            new THREE.Vector3(-0.65, 4.85, 9.95),  // 0.64: BIG ZOOM-OUT — All Sensors & 8 Satellites Launching Labeled Data Packets
            new THREE.Vector3(2.55, 2.15, 5.15),   // 0.73: CHASING PACKETS — Flying Alongside Labeled Telemetry Packets to Data Center
            new THREE.Vector3(4.95, 0.62, 3.25),   // 0.82: DATA CENTER ENTRANCE — Glass Sliding Doors Open Wide in Front of Camera
            new THREE.Vector3(4.95, 0.62, 2.08),   // 0.91: DOORWAY THRESHOLD — Flying Through Open Glass Doors Into Control Room
            new THREE.Vector3(4.92, 0.62, 1.68)    // 1.00: AI CONTROL ROOM — Centered in Right Viewport Facing Live 60FPS Grafana Wall
        ]);
        const lookCurve = new THREE.CatmullRomCurve3([
            new THREE.Vector3(-1.35, 1.92, 0.35),  // 0.00: Look at GNSS RTK Rover S2 & Crown Baseline
            new THREE.Vector3(-1.22, 1.88, 0.45),  // 0.09: Lock onto GNSS RTK Radome & ΔE/ΔN/ΔU Vector Triad
            new THREE.Vector3(-1.58, 1.68, 0.72),  // 0.18: Center Surface MEMS IMU Box, 6-DoF Chip & Gimbal Rings in open right stage
            new THREE.Vector3(-1.56, 1.66, 0.72),  // 0.27: Dwell on MEMS IMU Box & Shear Acceleration Vector
            new THREE.Vector3(-3.32, 1.76, 1.85),  // 0.36: Center Rain Gauge Collector Funnel, Dripping Drops & Tipping Bucket
            new THREE.Vector3(-2.05, 0.62, 2.28),  // 0.45: Center Slotted Borehole Pipe, Suspended Probe & Groundwater Table above HUD
            new THREE.Vector3(-1.98, 0.58, 2.28),  // 0.55: Lock onto Horizontal Groundwater Flow Streamlines Passing Sensor Probe
            new THREE.Vector3(0.15, 1.38, 0.45),   // 0.64: Look across Full Mountain Slope & Labeled Telemetry Packet Streams
            new THREE.Vector3(4.85, 0.72, 1.45),   // 0.73: Look ahead at Modern 2-Story Glass Data Center Building
            new THREE.Vector3(4.85, 0.58, 0.45),   // 0.82: Look through Opening Sliding Glass Doors into Control Room
            new THREE.Vector3(4.80, 0.60, 0.18),   // 0.91: Look at Curved 3-Panel Grafana Video Wall & 3D Hologram Table
            new THREE.Vector3(4.78, 0.60, 0.18)    // 1.00: Lock onto Live 60FPS Grafana & WebGIS Command Video Wall
        ]);

        const storySatBeams = [];
        const storySatWorldPos = new THREE.Vector3();
        let livingDynamics = null;

        // Load Blender GLB Scene
        getBlenderTemplate().then(template => {
            if (destroyed) return;
            const { root, nodes } = instantiateBlenderTwin(template);
            twinNodes = nodes;
            if (nodes.GroundwaterTable) initialGroundwaterY = nodes.GroundwaterTable.position.y;
            if (nodes.UnstableWedge) initialWedgePos = nodes.UnstableWedge.position.clone();
            if (nodes.GNSS_Station_Mid) initialMidStationPos = nodes.GNSS_Station_Mid.position.clone();
            if (nodes.IMU_Borehole_Assembly) initialImuPos = nodes.IMU_Borehole_Assembly.position.clone();
            worldGroup.add(root);
            livingDynamics = setupLivingTwinDynamics(nodes);

            const satNames = [
                'GNSS_Sat_01', 'GNSS_Sat_02', 'GNSS_Sat_03', 'GNSS_Sat_04',
                'GNSS_Sat_05', 'GNSS_Sat_06', 'GNSS_Sat_07', 'GNSS_Sat_08'
            ];
            const targetAnchors = [
                anchors.gnss_base,
                anchors.gnss_mid,
                anchors.gnss_toe,
                anchors.ops_hub,
                anchors.gnss_crown,
                anchors.gnss_mid,
                anchors.gnss_base,
                anchors.ops_hub
            ];
            satNames.forEach((name, idx) => {
                const satObj = nodes[name];
                if (!satObj) return;
                const beamGeo = new THREE.BufferGeometry();
                beamGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
                const beam = new THREE.Line(beamGeo, new THREE.LineBasicMaterial({
                    color: idx % 2 === 0 ? 0xd7ef73 : 0x5eead4,
                    transparent: true,
                    opacity: 0.22,
                    blending: THREE.AdditiveBlending
                }));
                worldGroup.add(beam);
                storySatBeams.push({ satObj, target: new THREE.Vector3(...targetAnchors[idx]), beam, phase: idx * 0.85 });
            });

            canvas.classList.add('is-ready');
            applyProgressState(targetProgress, 0);
            render();
        }).catch(() => {});

        const pinElements = calloutContainer ? {
            gnss_mid: $('[data-pin="gnss_mid"]', calloutContainer),
            imu_borehole: $('[data-pin="imu_borehole"]', calloutContainer),
            rain_gauge: $('[data-pin="rain_gauge"]', calloutContainer),
            piezometer: $('[data-pin="piezometer"]', calloutContainer),
            ops_hub: $('[data-pin="ops_hub"]', calloutContainer)
        } : {};
        const projVec = new THREE.Vector3();

        const pinOffsets = {
            gnss_mid: [3.5, -5.5],
            imu_borehole: [-4.5, 6.5],
            rain_gauge: [-6.0, -4.0],
            piezometer: [-3.5, 5.5],
            ops_hub: [0.0, -4.5]
        };

        function updateCalloutPins(step, p) {
            if (!calloutContainer) return;
            const activeMap = {
                0: ['gnss_mid', 'imu_borehole'],
                1: ['rain_gauge', 'piezometer'],
                2: ['gnss_mid', 'imu_borehole', 'piezometer', 'ops_hub'],
                3: ['ops_hub']
            };
            const activeSet = new Set(activeMap[step] || []);
            Object.entries(pinElements).forEach(([key, el]) => {
                if (!el) return;
                const targetCoord = (key === 'ops_hub' && p > 0.74) ? opsControlAnchor : anchors[key];
                if (!targetCoord) return;
                projVec.set(...targetCoord);
                projVec.project(camera);
                const [ox, oy] = pinOffsets[key] || [0, 0];
                const xPct = Math.min(91, Math.max(43, (projVec.x * 0.5 + 0.5) * 100 + ox));
                const yPct = Math.min(82, Math.max(18, (-projVec.y * 0.5 + 0.5) * 100 + oy));
                el.style.left = `${xPct.toFixed(1)}%`;
                el.style.top = `${yPct.toFixed(1)}%`;
                el.classList.toggle('is-active', activeSet.has(key));
            });
        }

        let targetProgress = 0, currentProgress = 0, visible = true, destroyed = false, frame = 0;

        function applyProgressState(progress, elapsed = 0) {
            const p = THREE.MathUtils.clamp(progress, 0, 1);
            const step = Math.min(3, Math.floor(p * 4));

            // Smooth weights for each storytelling act
            const wDetect = 1 - gsap.utils.clamp(0, 1, (p - 0.24) / 0.12);
            const wContext = gsap.utils.clamp(0, 1, (p - 0.20) / 0.12) * (1 - gsap.utils.clamp(0, 1, (p - 0.56) / 0.12));
            const wVerify = gsap.utils.clamp(0, 1, (p - 0.46) / 0.12) * (1 - gsap.utils.clamp(0, 1, (p - 0.80) / 0.12));
            const wResponse = gsap.utils.clamp(0, 1, (p - 0.64) / 0.18);

            // 1. Camera Spline Position & Target
            camCurve.getPoint(p, camera.position);
            const lookTarget = lookCurve.getPoint(p);
            camera.lookAt(lookTarget);

            // 2. Active Device Scanning Halo (highlights whichever sensor the camera is currently inspecting in Acts 1 & 2)
            let scanTarget = null;
            let scanColor = 0x5eead4;
            if (p < 0.14) {
                scanTarget = anchors.gnss_mid;
                scanColor = 0xd7ef73;
            } else if (p < 0.30) {
                scanTarget = anchors.imu_borehole;
                scanColor = 0xffb020;
            } else if (p < 0.41) {
                scanTarget = anchors.rain_gauge;
                scanColor = 0x38bdf8;
            } else if (p < 0.58) {
                scanTarget = anchors.piezometer;
                scanColor = 0x38bdf8;
            }
            if (scanTarget) {
                activeScanGroup.position.set(scanTarget[0], scanTarget[1] - 0.45, scanTarget[2]);
                const pulse = 0.85 + Math.sin(elapsed * 5.0) * 0.18;
                scanRingMesh.scale.setScalar(pulse);
                scanCylMesh.position.y = 0.35 + Math.sin(elapsed * 4.0) * 0.15;
                scanCylMat.color.setHex(scanColor);
                scanCylMat.opacity = 0.05 + Math.abs(Math.sin(elapsed * 4.0)) * 0.05;
                scanRingMat.opacity = 0.65;
            } else {
                scanCylMat.opacity = 0;
                scanRingMat.opacity = 0;
            }

            // 3. Terrain Cutaway Translucency (keep terrain crisp so open cutaway trench & surface sensors stand out)
            if (twinNodes.TerrainSurface) {
                twinNodes.TerrainSurface.material.opacity = 0.84 + 0.12 * Math.max(wVerify, wResponse);
            }

            // 4. Act 1 & 3: Surface MEMS IMU Box Vibration & Unstable Wedge Shear along Slip Surface
            const shearAmount = 0.04 * wDetect + 0.14 * wVerify + 0.08 * wResponse;
            if (twinNodes.UnstableWedge && initialWedgePos) {
                twinNodes.UnstableWedge.position.x = initialWedgePos.x + shearAmount;
                twinNodes.UnstableWedge.position.y = initialWedgePos.y - shearAmount * 0.36;
            }
            if (twinNodes.GNSS_Station_Mid && initialMidStationPos) {
                twinNodes.GNSS_Station_Mid.position.x = initialMidStationPos.x + shearAmount;
                twinNodes.GNSS_Station_Mid.position.y = initialMidStationPos.y - shearAmount * 0.36;
            }
            if (twinNodes.IMU_Borehole_Assembly && initialImuPos) {
                twinNodes.IMU_Borehole_Assembly.position.x = initialImuPos.x + shearAmount;
                twinNodes.IMU_Borehole_Assembly.position.y = initialImuPos.y - shearAmount * 0.36;
            }
            if (twinNodes.SlipSurface?.material) {
                twinNodes.SlipSurface.material.opacity = 0.45 + 0.45 * Math.max(wDetect, wVerify);
            }

            // 5. Act 2: Rain Storm & Rising Subsurface Groundwater Table in Open Cutaway Trench
            rainMat.opacity = Math.max(0.14, wContext * 0.86 + wVerify * 0.28);
            const waterRise = wContext * 0.26 + wVerify * 0.18 + wResponse * 0.12;
            if (twinNodes.GroundwaterTable) {
                twinNodes.GroundwaterTable.position.y = initialGroundwaterY + waterRise;
                twinNodes.GroundwaterTable.material.opacity = 0.55 + wContext * 0.35;
            }
            if (twinNodes.PiezometerWaterColumn) {
                twinNodes.PiezometerWaterColumn.scale.y = 1 + waterRise * 0.65;
                twinNodes.PiezometerWaterColumn.position.y = waterRise * 0.22;
            }

            // 6. Act 3: Multi-Sensor Baseline Triangulation Lasers & Satellite Carrier Beams
            baselineLines.forEach(line => {
                line.material.opacity = 0.22 + wVerify * 0.68 + wResponse * 0.28;
            });
            if (twinNodes.Satellite_Constellation) {
                twinNodes.Satellite_Constellation.position.x = -0.2 + Math.sin(elapsed * 0.42) * 0.28;
            }
            storySatBeams.forEach(({ satObj, target, beam, phase }) => {
                satObj.rotation.y += 0.007;
                satObj.getWorldPosition(storySatWorldPos);
                worldGroup.worldToLocal(storySatWorldPos);
                const posAttr = beam.geometry.attributes.position;
                posAttr.setXYZ(0, storySatWorldPos.x, storySatWorldPos.y, storySatWorldPos.z);
                posAttr.setXYZ(1, target.x, target.y, target.z);
                posAttr.needsUpdate = true;
                beam.material.opacity = (0.18 + wVerify * 0.32 + wResponse * 0.16) + Math.max(0, Math.sin(elapsed * 2.4 + phase)) * 0.16;
            });

            // 7. Always-Visible Telemetry Data Packets + Motorized Sliding Entrance Doors Opening + Control Room Interior!
            const streamWeight = Math.max(0.45, wVerify * 0.92, wResponse);
            dispatchLines.forEach(line => {
                line.material.opacity = streamWeight * 0.78;
            });
            dispatchPackets.forEach(pkt => {
                pkt.mesh.material.opacity = Math.min(1.0, streamWeight * 1.1);
                const t = (elapsed * pkt.speed + pkt.phase) % 1;
                pkt.curve.getPoint(t, pkt.mesh.position);
            });

            // Slide Operations Center Entrance Doors (OpsDoor_Left & OpsDoor_Right) wide open as camera approaches (p = 0.68 -> 0.81)!
            const doorRaw = gsap.utils.clamp(0, 1, (p - 0.68) / 0.13);
            const doorEase = doorRaw * doorRaw * (3 - 2 * doorRaw);
            if (twinNodes.OpsDoor_Left) {
                twinNodes.OpsDoor_Left.position.x = -0.56 * doorEase;
            }
            if (twinNodes.OpsDoor_Right) {
                twinNodes.OpsDoor_Right.position.x = 0.56 * doorEase;
            }
            controlRoomLight.intensity = 3.8 + doorEase * 4.5;

            if (streamWeight > 0.02) {
                const cycle = (elapsed * 0.65) % 1;
                opsPulseRing.scale.setScalar(0.8 + cycle * 2.2);
                opsPulseRing.material.opacity = streamWeight * (1 - cycle) * 0.85;
            } else {
                opsPulseRing.material.opacity = 0;
            }

            livingDynamics?.update(elapsed);
            updateCalloutPins(step, p);
        }

        const render = () => {
            if (!destroyed && visible && !document.hidden) {
                renderer.render(scene, camera);
            }
        };

        const tick = time => {
            frame = 0;
            if (destroyed || !visible || document.hidden) return;
            const elapsed = time * 0.001;

            // Smoothly interpolate 3D camera toward target scroll progress
            currentProgress += (targetProgress - currentProgress) * 0.16;
            if (Math.abs(targetProgress - currentProgress) < 0.0005) {
                currentProgress = targetProgress;
            }

            // Animate falling rain particles when visible
            if (rainMat.opacity > 0.05) {
                const pos = rainGeo.attributes.position;
                for (let i = 0; i < pos.count; i++) {
                    const y = pos.getY(i) - 0.065;
                    pos.setY(i, y < -0.4 ? 4.8 : y);
                }
                pos.needsUpdate = true;
            }

            applyProgressState(currentProgress, elapsed);
            render();
            frame = requestAnimationFrame(tick);
        };

        const setProgress = value => {
            const clamped = THREE.MathUtils.clamp(value, 0, 1);
            // If scroll jumped significantly (e.g. programmatic scrollTo or chapter click), snap closer immediately
            if (Math.abs(clamped - currentProgress) > 0.18) {
                currentProgress = clamped;
            }
            targetProgress = clamped;
            applyProgressState(currentProgress, performance.now() * 0.001);
            render();
        };

        const stopResize = watchCanvas(canvas, renderer, camera, render);
        const resume = () => { if (visible && !document.hidden && !frame && !destroyed) frame = requestAnimationFrame(tick); };
        const visibility = new IntersectionObserver(entries => {
            visible = entries[0]?.isIntersecting ?? true;
            if (visible) resume();
        }, { rootMargin: '120px' });
        visibility.observe(canvas);
        document.addEventListener('visibilitychange', resume);
        frame = requestAnimationFrame(tick);
        canvas.classList.add('is-ready');
        setProgress(0);

        return {
            setProgress,
            destroy() {
                if (destroyed) return;
                destroyed = true;
                cancelAnimationFrame(frame);
                document.removeEventListener('visibilitychange', resume);
                visibility.disconnect();
                stopResize();
                disposeScene(scene, renderer);
            }
        };
    }

    function setupHero() {
        const hero = $('.hero');
        const heroVisual = $('.hero-visual', hero);
        const heroCopy = $('.hero-copy', hero);
        const canvas = $('#hero-canvas');
        let controller = null;
        if (canUse3D(canvas)) {
            try { controller = createHeroController(canvas); cleanups.push(() => controller.destroy()); }
            catch (_) { canvas.hidden = true; }
        } else if (canvas) canvas.hidden = true;
        if (reducedMotion.matches) return;
        const intro = gsap.timeline({ defaults: { ease: 'power3.out' } });
        intro.from('.site-header', { y: -22, autoAlpha: 0, duration: .55 })
            .from('.hero-kicker', { y: 16, autoAlpha: 0, duration: .45 }, .12)
            .from('#hero-title span, #hero-title em', { yPercent: 55, autoAlpha: 0, duration: .78, stagger: .1 }, .2)
            .from('.hero-lead, .hero-actions, .signal-proof', { y: 22, autoAlpha: 0, duration: .55, stagger: .08 }, .48)
            .from('.hero-visual', { xPercent: 7, scale: .96, autoAlpha: 0, duration: .9 }, .18)
            .from('.floating-status', { y: 16, autoAlpha: 0, duration: .45 }, .76);
        if (controller || heroVisual) {
            const sceneState = { progress: 0 };
            ScrollTrigger.create({
                trigger: hero,
                start: 'top top',
                end: 'bottom top',
                scrub: 0.45,
                onUpdate: self => {
                    const p = self.progress;
                    sceneState.progress = p;
                    controller?.setProgress(p);
                    if (heroVisual && innerWidth >= 901) {
                        const zoom = 1 + p * 0.15;
                        const shiftX = -p * 11;
                        const shiftY = p * 6;
                        heroVisual.style.transform = p > 0.002 ? `translate3d(${shiftX.toFixed(2)}%, ${shiftY.toFixed(2)}%, 0) scale(${zoom.toFixed(3)})` : '';
                    }
                    if (heroCopy && innerWidth >= 901) {
                        heroCopy.style.transform = p > 0.002 ? `translate3d(0, ${(-p * 36).toFixed(1)}px, 0)` : '';
                        heroCopy.style.opacity = p > 0.002 ? String(Math.max(0.18, 1 - p * 0.78)) : '';
                    }
                }
            });
        }
    }

    function setupReveals() {
        if (reducedMotion.matches) {
            $$('.reveal').forEach(element => element.classList.add('is-visible'));
            $$('.section-divider').forEach(divider => divider.style.transform = 'scaleX(1)');
            return;
        }
        document.documentElement.classList.add('gsap-ready');
        $$('.reveal').forEach(element => {
            gsap.fromTo(element, { autoAlpha: 0, y: 22 }, {
                autoAlpha: 1,
                y: 0,
                duration: .55,
                ease: 'power2.out',
                scrollTrigger: { trigger: element, start: 'top 88%', once: true },
                onStart: () => element.classList.add('is-visible'),
                onComplete: () => element.classList.add('is-visible')
            });
        });
        $$('.section-divider').forEach(divider => {
            gsap.fromTo(divider, { scaleX: 0 }, {
                scaleX: 1,
                duration: 1.1,
                ease: 'power2.inOut',
                scrollTrigger: { trigger: divider, start: 'top 92%', once: true }
            });
        });
    }

    function setupStory() {
        const story = $('#story');
        const stage = $('.story-stage', story);
        const canvas = $('#story-canvas');
        const callouts = $('#stage-callouts', story);
        const articles = $$('[data-story-step]', story);
        const caption = $('#story-caption');
        const camMode = $('#hud-camera-mode');
        const stepBadge = $('#story-step-badge');
        if (!story || !stage || !articles.length) return;

        const captions = [
            'Thiết bị 01 · Trạm GNSS RTK (ΔE/ΔN/ΔU) & Hộp cảm biến MEMS IMU 6 trục trên mặt dốc',
            'Thiết bị 02 · Gầu đo mưa lật (0.2mm) & Cảm biến Piezometer thả giếng khoan đón dòng nước ngầm',
            'Xác minh · Zoom toàn cảnh & bám theo các gói tin Telemetry [PKT] bay về Toà nhà Data Center',
            'Phòng điều hành · Mở cửa kính Toà nhà Data Center & Màn hình Grafana + WebGIS thời gian thực'
        ];
        const stepBadges = ['BƯỚC 01 / 04', 'BƯỚC 02 / 04', 'BƯỚC 03 / 04', 'BƯỚC 04 / 04'];
        const stageTransforms = [
            { scale: 1.00, x: 0.0, y: 0.0, radius: 20 },
            { scale: 1.02, x: -0.6, y: -0.4, radius: 18 },
            { scale: 0.99, x: 0.6, y: 0.3, radius: 22 },
            { scale: 1.01, x: 0.0, y: 0.4, radius: 18 }
        ];

        const getDetailedCamHud = p => {
            if (p < 0.14) return 'CAM 01A · DỪNG NHỊP QUAN SÁT TRẠM GNSS RTK (ΔE/ΔN/ΔU)';
            if (p < 0.29) return 'CAM 01B · CẬN CẢNH HỘP CẢM BIẾN MEMS IMU 6 TRỤC & CON QUAY';
            if (p < 0.41) return 'CAM 02A · CẬN CẢNH GẦU ĐO MƯA LẬT 2 NGĂN (0.2MM/LẦN LẬT)';
            if (p < 0.58) return 'CAM 02B · MẶT CẮT HỐ KHOAN PIEZOMETER & DÒNG THẤM NƯỚC NGẦM';
            if (p < 0.69) return 'CAM 03A · ZOOM TOÀN CẢNH 8 VỆ TINH & ĐƯỜNG TRUYỀN GÓI TIN [PKT]';
            if (p < 0.79) return 'CAM 03B · BAY BÁM THEO GÓI TIN TELEMETRY VỀ DATA CENTER';
            if (p < 0.89) return 'CAM 04A · TIẾP CẬN TOÀ NHÀ DATA CENTER & MỞ CỬA KÍNH TRƯỢT';
            return 'CAM 04B · PHÒNG ĐIỀU HÀNH AI · MÀN HÌNH GRAFANA & WEBGIS LIVE';
        };

        if (innerWidth < 901 || reducedMotion.matches) {
            if (canvas) canvas.hidden = true;
            return;
        }

        story.classList.add('story-enhanced');
        let controller = null;
        if (canUse3D(canvas)) {
            try {
                controller = createStoryController(canvas, callouts);
                cleanups.push(() => controller.destroy());
            } catch (_) {
                canvas.hidden = true;
            }
        } else if (canvas) {
            canvas.hidden = true;
        }

        const pinOpsVal = $('#pin-ops-val', story);

        const applyStoryProgress = rawProgress => {
            const progress = THREE.MathUtils.clamp(rawProgress, 0, 1);
            const step = Math.min(3, Math.floor(progress * 4));
            story.dataset.step = String(step);
            stage.dataset.pose = String(step);
            story.style.setProperty('--story-progress', progress.toFixed(4));

            // Smooth zoom-out expansion as user scrolls from Hero right-card into the full-bleed Story theater
            const entryRaw = THREE.MathUtils.clamp(
                (window.scrollY - (story.offsetTop - innerHeight * 0.88)) / Math.max(1, innerHeight * 0.92),
                0,
                1
            );
            const zoomEase = entryRaw * entryRaw * (3 - 2 * entryRaw);
            const pose = stageTransforms[step];
            const curScale = 0.60 + (pose.scale - 0.60) * zoomEase;
            const curX = 18.0 * (1 - zoomEase) + pose.x * zoomEase;
            const curY = -3.5 * (1 - zoomEase) + pose.y * zoomEase;
            const curRadius = 28 * (1 - zoomEase) + pose.radius * zoomEase;

            stage.style.setProperty('--stage-scale', curScale.toFixed(3));
            stage.style.setProperty('--stage-x', `${curX.toFixed(2)}%`);
            stage.style.setProperty('--stage-y', `${curY.toFixed(2)}%`);
            stage.style.setProperty('--stage-radius', `${curRadius.toFixed(1)}px`);
            story.style.setProperty('--hud-opacity', zoomEase.toFixed(3));

            if (caption) caption.textContent = captions[step];
            if (camMode) camMode.textContent = getDetailedCamHud(progress);
            if (stepBadge) stepBadge.textContent = stepBadges[step];
            if (pinOpsVal) {
                pinOpsVal.textContent = progress > 0.84
                    ? 'Control Room · 5 Màn hình Live'
                    : (progress > 0.68 ? 'Đang mở cửa cổng chính…' : 'Đang nhận luồng gói tin');
            }

            articles.forEach((article, index) => {
                article.setAttribute('aria-hidden', index === step ? 'false' : 'true');
            });

            controller?.setProgress(progress);
        };

        const computeScrollProgress = () => {
            const totalScrollable = Math.max(1, story.offsetHeight - innerHeight);
            return (window.scrollY - story.offsetTop) / totalScrollable;
        };

        const onNativeScroll = () => {
            applyStoryProgress(computeScrollProgress());
        };
        addEventListener('scroll', onNativeScroll, { passive: true });
        cleanups.push(() => removeEventListener('scroll', onNativeScroll));

        const trigger = ScrollTrigger.create({
            trigger: story,
            start: 'top top',
            end: 'bottom bottom',
            onUpdate: self => applyStoryProgress(self.progress)
        });
        cleanups.push(() => trigger.kill());

        applyStoryProgress(computeScrollProgress());
    }

    function setupFinalMotion() {
        if (reducedMotion.matches) return;
        gsap.to('.cta-contours span', {
            rotate: '+=18',
            scale: 1.08,
            stagger: .08,
            ease: 'none',
            scrollTrigger: { trigger: '.final-cta', start: 'top bottom', end: 'bottom top', scrub: 1 }
        });
    }

    function setupPageMotion() {
        if (reducedMotion.matches) return;
        gsap.to('.scroll-progress-fill', { scaleY: 1, ease: 'none', scrollTrigger: { start: 'top top', end: 'max', scrub: .2 } });
        gsap.to('.hero-grid', { yPercent: -12, ease: 'none', scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: 1 } });
        gsap.to('.hero-aurora-a', { yPercent: -24, xPercent: 8, ease: 'none', scrollTrigger: { start: 'top top', end: 'max', scrub: 1.2 } });
        gsap.to('.hero-aurora-b', { yPercent: -14, xPercent: -10, ease: 'none', scrollTrigger: { start: 'top top', end: 'max', scrub: 1.5 } });
    }

    function setupCardTilt() {
        if (reducedMotion.matches || matchMedia('(hover: none)').matches) return;
        $$('.metric-card').forEach(card => {
            const shine = $('.card-shine', card);
            let bounds = null;
            const onEnter = () => { bounds = card.getBoundingClientRect(); };
            const onMove = event => {
                if (!bounds) bounds = card.getBoundingClientRect();
                const x = (event.clientX - bounds.left) / bounds.width - 0.5;
                const y = (event.clientY - bounds.top) / bounds.height - 0.5;
                gsap.to(card, {
                    rotateX: -y * 12,
                    rotateY: x * 12,
                    z: 6,
                    duration: 0.25,
                    ease: 'power1.out',
                    transformPerspective: 800
                });
                if (shine) {
                    const px = Math.round((x + 0.5) * 100);
                    const py = Math.round((y + 0.5) * 100);
                    shine.style.background = `radial-gradient(circle at ${px}% ${py}%, rgba(13,148,136,.22) 0%, transparent 60%)`;
                }
            };
            const onLeave = () => {
                bounds = null;
                gsap.to(card, { rotateX: 0, rotateY: 0, z: 0, duration: 0.45, ease: 'power2.out' });
            };
            card.addEventListener('mouseenter', onEnter);
            card.addEventListener('mousemove', onMove);
            card.addEventListener('mouseleave', onLeave);
            cleanups.push(() => {
                card.removeEventListener('mouseenter', onEnter);
                card.removeEventListener('mousemove', onMove);
                card.removeEventListener('mouseleave', onLeave);
            });
        });
    }

    function setupMagneticButtons() {
        if (reducedMotion.matches || matchMedia('(hover: none)').matches) return;
        const targets = $$('.hero-actions .button, .header-cta, .final-cta .button');
        targets.forEach(btn => {
            let bounds = null;
            const onEnter = () => { bounds = btn.getBoundingClientRect(); };
            const onMove = event => {
                if (!bounds) bounds = btn.getBoundingClientRect();
                const dx = (event.clientX - (bounds.left + bounds.width / 2)) * 0.28;
                const dy = (event.clientY - (bounds.top + bounds.height / 2)) * 0.28;
                gsap.to(btn, { x: dx, y: dy, scale: 1.04, duration: 0.25, ease: 'power1.out' });
            };
            const onLeave = () => {
                bounds = null;
                gsap.to(btn, { x: 0, y: 0, scale: 1, duration: 0.65, ease: 'elastic.out(1.1, 0.4)' });
            };
            btn.addEventListener('mouseenter', onEnter);
            btn.addEventListener('mousemove', onMove);
            btn.addEventListener('mouseleave', onLeave);
            cleanups.push(() => {
                btn.removeEventListener('mouseenter', onEnter);
                btn.removeEventListener('mousemove', onMove);
                btn.removeEventListener('mouseleave', onLeave);
            });
        });
    }

    function setupPerformanceGuard() {
        if (reducedMotion.matches || currentQualityTier === 'lite') return;
        const toast = $('#quality-toast');
        if (!toast) return;
        const toastText = $('p', toast);
        const toastBtn = $('.toast-action', toast);
        const toastClose = $('.toast-dismiss', toast);

        let lastTime = performance.now();
        let frames = 0;
        let slowCount = 0;
        let monitoring = true;

        const hideToast = () => {
            toast.classList.remove('is-visible');
            toast.hidden = true;
        };

        const checkFPS = now => {
            if (!monitoring) return;
            frames++;
            if (now - lastTime >= 3500) {
                const fps = Math.round((frames * 1000) / (now - lastTime));
                frames = 0;
                lastTime = now;
                if (fps < 32) {
                    slowCount++;
                    if (slowCount >= 2 && currentQualityTier !== 'lite') {
                        if (toastText) toastText.textContent = 'Thiết bị đang chạy chậm. Bạn có muốn giảm hiệu ứng để mượt hơn?';
                        if (toastBtn) toastBtn.textContent = 'Bật chế độ tiết kiệm (Lite)';
                        toast.hidden = false;
                        toast.classList.add('is-visible');
                        monitoring = false;
                        return;
                    }
                } else {
                    slowCount = Math.max(0, slowCount - 1);
                }
            }
            requestAnimationFrame(checkFPS);
        };
        requestAnimationFrame(checkFPS);
        cleanups.push(() => { monitoring = false; });

        toastBtn?.addEventListener('click', () => {
            currentQualityTier = 'lite';
            hideToast();
            dispatchEvent(new CustomEvent('qualityTierChanged', { detail: { tier: 'lite' } }));
        });
        toastClose?.addEventListener('click', hideToast);
    }

    setupHeader();
    setupMetrics();
    setupHero();
    setupReveals();
    setupStory();
    setupFinalMotion();
    setupPageMotion();
    setupCardTilt();
    setupMagneticButtons();
    setupPerformanceGuard();
    setupAuthLink().catch(() => {});
    addEventListener('load', () => ScrollTrigger.refresh(), { once: true });
    addEventListener('pagehide', () => cleanups.splice(0).forEach(cleanup => cleanup()), { once: true });
})();
