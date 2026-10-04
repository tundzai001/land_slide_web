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
                if (['TerrainSurface', 'SlipSurface', 'UnstableWedge', 'GroundwaterTable', 'PiezometerWaterColumn'].includes(obj.name)) {
                    obj.material.transparent = true;
                }
            }
        });

        // Add subtle CAD topographic wireframe on top of the Blender TerrainSurface
        const terrain = nodes.TerrainSurface;
        if (terrain && terrain.geometry) {
            const wireGeo = new THREE.WireframeGeometry(terrain.geometry);
            const wireMat = new THREE.LineBasicMaterial({
                color: 0x5eead4,
                transparent: true,
                opacity: 0.11,
                blending: THREE.AdditiveBlending
            });
            const wireMesh = new THREE.LineSegments(wireGeo, wireMat);
            wireMesh.position.y = 0.012;
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

    // ─── HERO 3D CONTROLLER (Blender GLB Twin + Orbital Constellation) ───
    function createHeroController(canvas) {
        const renderer = createRenderer(canvas);
        const scene = new THREE.Scene();
        scene.fog = new THREE.FogExp2(0x061b1d, 0.032);

        const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
        camera.position.set(-2.6, 4.3, 8.2);

        scene.add(new THREE.HemisphereLight(0xd2fff7, 0x041517, 2.2));
        const sun = new THREE.DirectionalLight(0xf0fdfa, 2.6);
        sun.position.set(-5, 9, 6);
        scene.add(sun);

        const tealRim = new THREE.PointLight(0x2dd4bf, 5.5, 18);
        tealRim.position.set(-4.5, 3.5, -3.5);
        scene.add(tealRim);

        const slipGlow = new THREE.PointLight(0xffb020, 4.2, 12);
        slipGlow.position.set(-0.8, 2.0, 0.5);
        scene.add(slipGlow);

        const worldGroup = new THREE.Group();
        scene.add(worldGroup);

        const anchors = BLENDER_META.anchors;
        const packets = [];
        const satBeams = [];
        let twinNodes = {};

        // Atmospheric floating telemetry dust
        const dustCount = 90;
        const dustPos = new Float32Array(dustCount * 3);
        for (let i = 0; i < dustPos.length; i += 3) {
            dustPos[i] = (Math.random() - 0.5) * 12;
            dustPos[i + 1] = Math.random() * 4.5 - 0.5;
            dustPos[i + 2] = (Math.random() - 0.5) * 9;
        }
        const dustGeo = new THREE.BufferGeometry();
        dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPos, 3));
        const dust = new THREE.Points(dustGeo, new THREE.PointsMaterial({
            color: 0x8af1e2,
            size: 0.045,
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

            // Build telemetry arcs from Rover stations & Base CORS to Operations Hub
            const arcConfigs = [
                [anchors.gnss_base, anchors.gnss_mid, 1.3, 0xd7ef73],
                [anchors.gnss_crown, anchors.ops_hub, 2.1, 0x5eead4],
                [anchors.gnss_mid, anchors.ops_hub, 1.8, 0xffb020],
                [anchors.gnss_toe, anchors.ops_hub, 1.2, 0x5eead4]
            ];
            const packetGeo = new THREE.SphereGeometry(0.065, 10, 10);
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

            // Satellite carrier-phase beams down to stations
            const satNames = ['GNSS_Sat_01', 'GNSS_Sat_02', 'GNSS_Sat_03'];
            const targetAnchors = [anchors.gnss_base, anchors.gnss_mid, anchors.gnss_toe];
            satNames.forEach((name, idx) => {
                const satObj = nodes[name];
                if (!satObj) return;
                const beamGeo = new THREE.BufferGeometry();
                beamGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
                const beam = new THREE.Line(beamGeo, new THREE.LineBasicMaterial({
                    color: idx === 0 ? 0xd7ef73 : 0x5eead4,
                    transparent: true,
                    opacity: 0.24,
                    blending: THREE.AdditiveBlending
                }));
                worldGroup.add(beam);
                satBeams.push({ satObj, target: new THREE.Vector3(...targetAnchors[idx]), beam, phase: idx * 1.1 });
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

            // Animate GNSS satellites & carrier beams
            if (twinNodes.Satellite_Constellation) {
                twinNodes.Satellite_Constellation.position.x = -0.5 + Math.sin(elapsed * 0.45) * 0.35;
                twinNodes.Satellite_Constellation.position.z = Math.cos(elapsed * 0.35) * 0.25;
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
            if (twinNodes.OpsBeaconCore) {
                twinNodes.OpsBeaconCore.rotation.y = elapsed * 0.9;
            }

            camera.position.set(
                -2.6 + progress * 1.1 + pointerX * 0.35,
                4.3 - progress * 0.65 - pointerY * 0.25,
                8.2 - progress * 1.4
            );
            camera.lookAt(-0.3 + progress * 0.3, 0.15, 0.1);

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

    // ─── STORY 3D CONTROLLER (4-Act Blender Scrollytelling Choreography) ───
    function createStoryController(canvas, calloutContainer) {
        const renderer = createRenderer(canvas);
        const scene = new THREE.Scene();
        scene.fog = new THREE.FogExp2(0x061f21, 0.028);

        const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
        scene.add(new THREE.HemisphereLight(0xd0fff6, 0x041618, 2.35));
        const dirLight = new THREE.DirectionalLight(0xffffff, 2.5);
        dirLight.position.set(-4, 10, 6);
        scene.add(dirLight);

        const slipLight = new THREE.PointLight(0xff9e1b, 4.5, 14);
        slipLight.position.set(-0.9, 1.8, 0.5);
        scene.add(slipLight);

        const waterLight = new THREE.PointLight(0x38bdf8, 3.8, 14);
        waterLight.position.set(-1.8, 0.5, 3.6);
        scene.add(waterLight);

        const worldGroup = new THREE.Group();
        scene.add(worldGroup);

        const anchors = BLENDER_META.anchors;
        let twinNodes = {};
        let initialGroundwaterY = 0;
        let initialWedgePos = null;
        let initialMidStationPos = null;
        let initialImuPos = null;

        // 1. Rain Storm Particle System (Act 2: Hydrological Context)
        const rainCount = 220;
        const rainPositions = new Float32Array(rainCount * 3);
        for (let i = 0; i < rainPositions.length; i += 3) {
            rainPositions[i] = (Math.random() - 0.5) * 11;
            rainPositions[i + 1] = Math.random() * 5.2 - 0.2;
            rainPositions[i + 2] = (Math.random() - 0.5) * 8;
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

        // 2. Baseline Triangulation Network (Act 3: Multi-Sensor Verification)
        const baselineGroup = new THREE.Group();
        worldGroup.add(baselineGroup);
        const baselinePairs = [
            [anchors.gnss_base, anchors.gnss_crown, 0.65, 0x5eead4],
            [anchors.gnss_base, anchors.gnss_mid, 0.85, 0xffb020],
            [anchors.gnss_base, anchors.gnss_toe, 1.05, 0x5eead4],
            [anchors.gnss_crown, anchors.gnss_mid, 0.45, 0xffb020],
            [anchors.gnss_mid, anchors.gnss_toe, 0.45, 0xffb020],
            [anchors.imu_borehole, anchors.piezometer, 0.35, 0x38bdf8]
        ];
        const baselineLines = baselinePairs.map(([a, b, h, col]) => {
            const line = createSignalArc(a, b, h, col, 0);
            baselineGroup.add(line);
            return line;
        });

        // 3. Operations Dispatch Arcs & Warning Pulse Rings (Act 4: Response)
        const dispatchGroup = new THREE.Group();
        worldGroup.add(dispatchGroup);
        const dispatchPairs = [
            [anchors.gnss_mid, anchors.ops_hub, 2.2, 0xd7ef73],
            [anchors.gnss_crown, anchors.ops_hub, 2.5, 0x5eead4],
            [anchors.gnss_toe, anchors.ops_hub, 1.5, 0x5eead4],
            [anchors.ops_hub, anchors.highway_gate, 0.9, 0xd7ef73]
        ];
        const dispatchLines = [];
        const dispatchPackets = [];
        const pktGeo = new THREE.SphereGeometry(0.075, 10, 10);
        dispatchPairs.forEach(([a, b, h, col], idx) => {
            const arc = createSignalArc(a, b, h, col, 0);
            dispatchGroup.add(arc);
            dispatchLines.push(arc);
            const pkt = new THREE.Mesh(pktGeo, new THREE.MeshBasicMaterial({
                color: col,
                transparent: true,
                opacity: 0,
                blending: THREE.AdditiveBlending
            }));
            dispatchGroup.add(pkt);
            dispatchPackets.push({ mesh: pkt, curve: arc.userData.curve, speed: 0.42 + idx * 0.08, phase: idx * 0.25 });
        });

        // Expanding safety rings at Operations Hub & Highway Gate
        const safetyRingGeo = new THREE.RingGeometry(0.45, 0.56, 48);
        const opsPulseRing = new THREE.Mesh(safetyRingGeo, new THREE.MeshBasicMaterial({
            color: 0xd7ef73,
            transparent: true,
            opacity: 0,
            side: THREE.DoubleSide,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        }));
        opsPulseRing.rotation.x = -Math.PI / 2;
        opsPulseRing.position.set(anchors.ops_hub[0], anchors.ops_hub[1] - 1.35, anchors.ops_hub[2]);
        worldGroup.add(opsPulseRing);

        // 4. Camera Choreography Splines across the 4 Storytelling Chapters
        const camCurve = new THREE.CatmullRomCurve3([
            new THREE.Vector3(-2.35, 3.15, 5.45), // Step 0: Tight on Upper/Mid Slip Zone & Borehole IMU
            new THREE.Vector3(-2.85, 2.25, 6.55), // Step 1: Front Cutaway Aquifer & Piezometer Well
            new THREE.Vector3(-0.15, 4.75, 7.35), // Step 2: Multi-Station GNSS Baseline Triangulation Overview
            new THREE.Vector3(2.85, 3.55, 6.45),  // Step 3: Operations Command Hub & Highway Warning Corridor
            new THREE.Vector3(3.35, 3.15, 5.85)   // Step 3 End hold
        ]);
        const lookCurve = new THREE.CatmullRomCurve3([
            new THREE.Vector3(-0.95, 0.35, 0.35), // Step 0 target: Mid GNSS + IMU Borehole
            new THREE.Vector3(-1.65, -0.25, 2.15),// Step 1 target: Piezometer + Groundwater Cutaway
            new THREE.Vector3(-0.75, 0.20, 0.15), // Step 2 target: Full Slope Slip Wedge
            new THREE.Vector3(2.35, 0.05, 0.85),  // Step 3 target: Operations Hub + Mountain Highway Gate
            new THREE.Vector3(2.85, 0.15, 0.75)
        ]);

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

        function updateCalloutPins(step) {
            if (!calloutContainer) return;
            const activeMap = {
                0: ['gnss_mid', 'imu_borehole'],
                1: ['rain_gauge', 'piezometer', 'imu_borehole'],
                2: ['gnss_mid', 'imu_borehole', 'piezometer'],
                3: ['ops_hub', 'gnss_mid']
            };
            const activeSet = new Set(activeMap[step] || []);
            Object.entries(pinElements).forEach(([key, el]) => {
                if (!el || !anchors[key]) return;
                projVec.set(...anchors[key]);
                projVec.project(camera);
                const xPct = Math.min(90, Math.max(10, (projVec.x * 0.5 + 0.5) * 100));
                const yPct = Math.min(84, Math.max(16, (-projVec.y * 0.5 + 0.5) * 100));
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
            const wDetect = 1 - gsap.utils.clamp(0, 1, (p - 0.22) / 0.14);
            const wContext = gsap.utils.clamp(0, 1, (p - 0.16) / 0.14) * (1 - gsap.utils.clamp(0, 1, (p - 0.54) / 0.14));
            const wVerify = gsap.utils.clamp(0, 1, (p - 0.44) / 0.14) * (1 - gsap.utils.clamp(0, 1, (p - 0.80) / 0.14));
            const wResponse = gsap.utils.clamp(0, 1, (p - 0.70) / 0.16);

            // 1. Camera Spline Position & Target
            camCurve.getPoint(p, camera.position);
            const lookTarget = lookCurve.getPoint(p);
            camera.lookAt(lookTarget);

            // 2. Terrain Cutaway Translucency (semi-translucent during subsurface chapters 0 & 1)
            if (twinNodes.TerrainSurface) {
                twinNodes.TerrainSurface.material.opacity = 0.66 + 0.24 * Math.max(wVerify, wResponse);
            }

            // 3. Act 1 & 3: Borehole IMU Tilt & Unstable Wedge Shear along Slip Surface
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
                twinNodes.IMU_Borehole_Assembly.rotation.z = -(0.06 * wDetect + 0.14 * wVerify);
            }
            if (twinNodes.SlipSurface?.material) {
                twinNodes.SlipSurface.material.opacity = 0.45 + 0.45 * Math.max(wDetect, wVerify);
            }

            // 4. Act 2: Rain Storm & Rising Subsurface Groundwater Table
            rainMat.opacity = Math.max(0.08, wContext * 0.78 + wVerify * 0.25);
            const waterRise = wContext * 0.34 + wVerify * 0.24 + wResponse * 0.14;
            if (twinNodes.GroundwaterTable) {
                twinNodes.GroundwaterTable.position.y = initialGroundwaterY + waterRise;
                twinNodes.GroundwaterTable.material.opacity = 0.48 + wContext * 0.38;
            }
            if (twinNodes.PiezometerWaterColumn) {
                twinNodes.PiezometerWaterColumn.scale.y = 1 + waterRise * 1.4;
                twinNodes.PiezometerWaterColumn.position.y = waterRise * 0.45;
            }

            // 5. Act 3: Multi-Sensor Baseline Triangulation Lasers
            baselineLines.forEach(line => {
                line.material.opacity = wVerify * 0.78 + wResponse * 0.28;
            });

            // 6. Act 4: Operations Hub Dispatch & Highway Early Warning Gate
            dispatchLines.forEach(line => {
                line.material.opacity = wResponse * 0.85;
            });
            dispatchPackets.forEach(pkt => {
                pkt.mesh.material.opacity = wResponse * 0.95;
                if (wResponse > 0.02) {
                    const t = (elapsed * pkt.speed + pkt.phase) % 1;
                    pkt.curve.getPoint(t, pkt.mesh.position);
                }
            });
            if (wResponse > 0.02) {
                const cycle = (elapsed * 0.65) % 1;
                opsPulseRing.scale.setScalar(0.8 + cycle * 2.4);
                opsPulseRing.material.opacity = wResponse * (1 - cycle) * 0.85;
            } else {
                opsPulseRing.material.opacity = 0;
            }

            updateCalloutPins(step);
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

            if (twinNodes.OpsBeaconCore) {
                twinNodes.OpsBeaconCore.rotation.y = elapsed * 1.1;
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
        if (controller) {
            const sceneState = { progress: 0 };
            ScrollTrigger.create({
                trigger: hero,
                start: 'top top',
                end: 'bottom top',
                scrub: 0.5,
                onUpdate: self => {
                    sceneState.progress = self.progress;
                    controller.setProgress(sceneState.progress);
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
            'Phát hiện · Vector dịch chuyển GNSS + góc nghiêng IMU',
            'Bối cảnh · Lượng mưa thấm sâu + mực nước ngầm dâng cao',
            'Xác minh · Hợp nhất đa cảm biến & bình sai cụm trạm',
            'Phản ứng · Operations Hub tiếp nhận & kích hoạt cảnh báo'
        ];
        const camModes = [
            'CAM 01 · CẬN CẢNH ĐỚI TRƯỢT & LỖ KHOAN IMU',
            'CAM 02 · MẶT CẮT THỦY VĂN & MỰC NƯỚC NGẦM',
            'CAM 03 · TAM GIÁC ĐẠC CỤM TRẠM GNSS RTK',
            'CAM 04 · TRUNG TÂM ĐIỀU HÀNH & HÀNH LANG ĐÈO'
        ];
        const stepBadges = ['BƯỚC 01 / 04', 'BƯỚC 02 / 04', 'BƯỚC 03 / 04', 'BƯỚC 04 / 04'];
        const stageTransforms = [
            { scale: 1.0, x: '0%', y: '0%', radius: '24px' },
            { scale: 1.03, x: '-1.5%', y: '-1%', radius: '18px' },
            { scale: 0.98, x: '1.5%', y: '0.5%', radius: '26px' },
            { scale: 1.01, x: '0%', y: '1%', radius: '20px' }
        ];

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

        const applyStoryProgress = rawProgress => {
            const progress = THREE.MathUtils.clamp(rawProgress, 0, 1);
            const step = Math.min(3, Math.floor(progress * 4));
            story.dataset.step = String(step);
            stage.dataset.pose = String(step);
            story.style.setProperty('--story-progress', progress.toFixed(4));

            const pose = stageTransforms[step];
            stage.style.setProperty('--stage-scale', String(pose.scale));
            stage.style.setProperty('--stage-x', pose.x);
            stage.style.setProperty('--stage-y', pose.y);
            stage.style.setProperty('--stage-radius', pose.radius);

            if (caption) caption.textContent = captions[step];
            if (camMode) camMode.textContent = camModes[step];
            if (stepBadge) stepBadge.textContent = stepBadges[step];

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
