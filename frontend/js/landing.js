import './session-state.js';
import * as THREE from 'three';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

(() => {
    'use strict';

    gsap.registerPlugin(ScrollTrigger);

    const $ = (selector, root = document) => root.querySelector(selector);
    const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
    const cleanups = [];

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
                const format = new Intl.NumberFormat('vi-VN');
                keys.forEach(key => { $(`#stations-${key}`).textContent = Number.isFinite(Number(stations[key])) ? format.format(Number(stations[key])) : '—'; });
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
        if (!canvas || reducedMotion.matches || navigator.connection?.saveData || navigator.hardwareConcurrency <= 2) return false;
        try {
            const probe = document.createElement('canvas');
            return Boolean(probe.getContext('webgl2') || probe.getContext('webgl'));
        } catch (_) { return false; }
    }

    function createRenderer(canvas) {
        const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'high-performance' });
        renderer.setPixelRatio(Math.min(devicePixelRatio, 1.6));
        renderer.setClearColor(0x000000, 0);
        renderer.outputColorSpace = THREE.SRGBColorSpace;
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

    function sculptTerrain(width = 14, depth = 10, xSegments = 54, zSegments = 38) {
        const geometry = new THREE.PlaneGeometry(width, depth, xSegments, zSegments);
        geometry.rotateX(-Math.PI / 2);
        const positions = geometry.attributes.position;
        for (let i = 0; i < positions.count; i++) {
            const x = positions.getX(i), z = positions.getZ(i);
            const ridge = Math.sin(x * .55) * .58 + Math.cos(z * .82) * .42;
            const fold = Math.sin((x + z) * 1.4) * .16 + Math.cos((x - z) * 1.1) * .12;
            positions.setY(i, ridge + fold - Math.abs(x) * .025);
        }
        geometry.computeVertexNormals();
        return geometry;
    }

    function createHeroController(canvas) {
        const renderer = createRenderer(canvas);
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(42, 1, .1, 100);
        camera.position.set(0, 1.15, 7.4);
        scene.add(new THREE.AmbientLight(0xcafff5, .42));
        const key = new THREE.PointLight(0x5eead4, 5.8, 18); key.position.set(-3.4, 3.2, 4.4); scene.add(key);
        const rim = new THREE.PointLight(0xd7ef73, 2.4, 14); rim.position.set(3.6, -1.4, 3); scene.add(rim);

        const group = new THREE.Group(); scene.add(group);
        const coreGeometry = new THREE.SphereGeometry(1.05, 48, 32);
        const core = new THREE.Mesh(coreGeometry, new THREE.MeshStandardMaterial({ color:0x062a2c,metalness:.32,roughness:.48,emissive:0x0f766e,emissiveIntensity:.22,transparent:true,opacity:.3 }));
        const wire = new THREE.LineSegments(new THREE.WireframeGeometry(coreGeometry),new THREE.LineBasicMaterial({ color:0x5eead4,transparent:true,opacity:.28,blending:THREE.AdditiveBlending }));
        wire.scale.setScalar(1.012); group.add(core,wire);

        const makeOrbit = (radius,rotation,opacity) => {
            const points = new THREE.EllipseCurve(0,0,radius,radius,0,Math.PI*2).getPoints(160).map(point => new THREE.Vector3(point.x,0,point.y));
            const orbit = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({ color:0x5eead4,transparent:true,opacity,blending:THREE.AdditiveBlending }));
            orbit.rotation.set(...rotation); group.add(orbit); return orbit;
        };
        const orbits = [makeOrbit(1.55,[.78,.2,0],.28),makeOrbit(2.05,[1.28,-.25,.38],.16),makeOrbit(2.55,[1.02,.72,-.28],.1)];
        const satelliteGeometry = new THREE.OctahedronGeometry(.09,0);
        const satellites = [[1.55,.62,.1],[2.05,-.43,1.8],[2.55,.34,2.7]].map(([radius,speed,phase],index) => {
            const pivot = new THREE.Group(); pivot.rotation.copy(orbits[index].rotation); group.add(pivot);
            const satellite = new THREE.Mesh(satelliteGeometry,new THREE.MeshBasicMaterial({ color:index===0?0xd7ef73:0x9ffbed,transparent:true,opacity:.9,blending:THREE.AdditiveBlending }));
            satellite.position.x=radius; pivot.add(satellite);
            const geometry = new THREE.BufferGeometry(); geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(6),3));
            const beam = new THREE.Line(geometry,new THREE.LineBasicMaterial({ color:0x5eead4,transparent:true,opacity:.14,blending:THREE.AdditiveBlending })); group.add(beam);
            return { pivot,satellite,beam,speed,phase };
        });
        const pulseGeometry = new THREE.RingGeometry(1.28,1.31,128);
        const pulses = [0,1].map(index => {
            const pulse = new THREE.Mesh(pulseGeometry,new THREE.MeshBasicMaterial({ color:index?0xd7ef73:0x5eead4,transparent:true,opacity:.2,side:THREE.DoubleSide,depthWrite:false,blending:THREE.AdditiveBlending }));
            pulse.rotation.set(1.08+index*.3,.2,index*.7); pulse.userData.phase=index*.5; group.add(pulse); return pulse;
        });
        const positions = new Float32Array(120*3);
        for(let i=0;i<positions.length;i+=3){ positions[i]=(Math.random()-.5)*7; positions[i+1]=(Math.random()-.5)*5; positions[i+2]=(Math.random()-.5)*4; }
        const particleGeometry = new THREE.BufferGeometry(); particleGeometry.setAttribute('position',new THREE.BufferAttribute(positions,3));
        const particles = new THREE.Points(particleGeometry,new THREE.PointsMaterial({ color:0x8af1e2,size:.025,transparent:true,opacity:.5,depthWrite:false })); group.add(particles);

        const imu = new THREE.Group(); imu.position.set(-1.72,.72,.15); group.add(imu);
        const imuBody = new THREE.Mesh(new THREE.BoxGeometry(.62,.3,.5),new THREE.MeshStandardMaterial({ color:0x102f31,metalness:.55,roughness:.3,emissive:0xff8a3d,emissiveIntensity:.18 }));
        const imuEdges = new THREE.LineSegments(new THREE.EdgesGeometry(imuBody.geometry),new THREE.LineBasicMaterial({ color:0xffb020,transparent:true,opacity:.8 }));
        imu.add(imuBody,imuEdges,new THREE.ArrowHelper(new THREE.Vector3(1,0,0),new THREE.Vector3(),.72,0xff6b00,.12,.08),new THREE.ArrowHelper(new THREE.Vector3(0,1,0),new THREE.Vector3(),.65,0x5eead4,.12,.08));

        const rainGauge = new THREE.Group(); rainGauge.position.set(-1.72,-1.02,.2); group.add(rainGauge);
        const funnel = new THREE.Mesh(new THREE.CylinderGeometry(.38,.12,.34,24,1,true),new THREE.MeshStandardMaterial({ color:0x8af1e2,transparent:true,opacity:.58,metalness:.35,roughness:.25,side:THREE.DoubleSide }));
        const stem = new THREE.Mesh(new THREE.CylinderGeometry(.055,.055,.7,12),new THREE.MeshStandardMaterial({ color:0xdffcf6,emissive:0x0d9488,emissiveIntensity:.45 })); stem.position.y=-.48; rainGauge.add(funnel,stem);
        const dropPositions = new Float32Array(24*3);
        for(let i=0;i<dropPositions.length;i+=3){ dropPositions[i]=(Math.random()-.5)*.65; dropPositions[i+1]=Math.random()*1.9+.25; dropPositions[i+2]=(Math.random()-.5)*.45; }
        const dropGeometry = new THREE.BufferGeometry(); dropGeometry.setAttribute('position',new THREE.BufferAttribute(dropPositions,3));
        const drops = new THREE.Points(dropGeometry,new THREE.PointsMaterial({ color:0x7dd3fc,size:.045,transparent:true,opacity:.72 })); rainGauge.add(drops);

        const well = new THREE.Group(); well.position.set(1.72,-.92,.18); group.add(well);
        const wellShellGeometry = new THREE.CylinderGeometry(.32,.32,1.35,24,1,true);
        const wellShell = new THREE.LineSegments(new THREE.WireframeGeometry(wellShellGeometry),new THREE.LineBasicMaterial({ color:0x8af1e2,transparent:true,opacity:.5 }));
        const waterColumn = new THREE.Mesh(new THREE.CylinderGeometry(.25,.25,.82,24),new THREE.MeshBasicMaterial({ color:0x38bdf8,transparent:true,opacity:.55 })); waterColumn.position.y=-.23;
        const waterRing = new THREE.Mesh(new THREE.RingGeometry(.36,.4,48),new THREE.MeshBasicMaterial({ color:0xd7ef73,transparent:true,opacity:.65,side:THREE.DoubleSide })); waterRing.rotation.x=-Math.PI/2; waterRing.position.y=.7; well.add(wellShell,waterColumn,waterRing);

        [[imu.position,0xffb020],[rainGauge.position,0x7dd3fc],[well.position,0x38bdf8]].forEach(([position,color])=>{
            const connection = new THREE.Line(new THREE.BufferGeometry().setFromPoints([position.clone(),new THREE.Vector3()]),new THREE.LineBasicMaterial({ color,transparent:true,opacity:.2,blending:THREE.AdditiveBlending })); group.add(connection);
        });
        const satelliteWorld = new THREE.Vector3();

        let progress = 0, active = true, destroyed = false, frame = 0;
        const render = () => {
            if (destroyed || !active || document.hidden) return;
            camera.lookAt(0, 0, 0);
            renderer.render(scene, camera);
        };
        const tick = time => {
            frame = 0;
            if (destroyed || !active || document.hidden) return;
            const elapsed=time*.001;
            core.rotation.y+=.009; wire.rotation.y-=.004; particles.rotation.y+=.0007;
            orbits.forEach((orbit,index)=>{ orbit.rotation.z+=.0025+index*.0012; });
            pulses.forEach(pulse=>{ const cycle=(elapsed*.32+pulse.userData.phase)%1; pulse.scale.setScalar(.78+cycle*1.12); pulse.material.opacity=.28*(1-cycle); });
            satellites.forEach(({ pivot,satellite,beam,speed,phase })=>{
                pivot.rotation.y=elapsed*speed+phase; satellite.rotation.x+=.035; satellite.rotation.y+=.028;
                satellite.getWorldPosition(satelliteWorld); const points=beam.geometry.attributes.position;
                points.setXYZ(0,satelliteWorld.x,satelliteWorld.y,satelliteWorld.z); points.setXYZ(1,0,0,0); points.needsUpdate=true;
                beam.material.opacity=.05+Math.max(0,Math.sin(elapsed*2.2+phase))*.2;
            });
            imu.rotation.z=Math.sin(elapsed*.72)*.16; imu.rotation.x=Math.cos(elapsed*.48)*.08;
            const dropAttribute=dropGeometry.attributes.position;
            for(let i=0;i<dropAttribute.count;i++){ const y=dropAttribute.getY(i)-.018; dropAttribute.setY(i,y<.12?2.1:y); } dropAttribute.needsUpdate=true;
            waterColumn.scale.y=.82+Math.sin(elapsed*.55)*.14; waterRing.scale.setScalar(1+Math.sin(elapsed*1.4)*.08);
            group.rotation.y=-progress*.24; group.rotation.x=Math.sin(elapsed*.18)*.025-progress*.08;
            render();
            frame = requestAnimationFrame(tick);
        };
        const setProgress = value => {
            progress = THREE.MathUtils.clamp(value, 0, 1);
            camera.position.x = progress * .6;
            camera.position.y = 1.15 + progress * .35;
            camera.position.z = 7.4 + progress * 1.4;
            const phase = Math.min(3,Math.floor(progress*4));
            imu.scale.setScalar(phase===1?1.2:1);
            rainGauge.scale.setScalar(phase===1?1.16:1);
            well.scale.setScalar(phase===1?1.16:1);
            core.material.emissiveIntensity=phase>=2?.75:.22;
            render();
        };
        const stopResize = watchCanvas(canvas, renderer, camera, render);
        const resume = () => { if (active && !document.hidden && !frame && !destroyed) frame=requestAnimationFrame(tick); };
        const visibility = new IntersectionObserver(entries => { active = entries[0]?.isIntersecting ?? true; if (active) resume(); }, { rootMargin: '120px' });
        visibility.observe(canvas);
        document.addEventListener('visibilitychange',resume);
        frame = requestAnimationFrame(tick);
        canvas.classList.add('is-ready');
        return {
            setProgress,
            destroy() { if (destroyed) return; destroyed = true; cancelAnimationFrame(frame); document.removeEventListener('visibilitychange',resume); visibility.disconnect(); stopResize(); disposeScene(scene, renderer); }
        };
    }

    function createStoryController(canvas) {
        const renderer = createRenderer(canvas);
        const scene = new THREE.Scene();
        scene.fog = new THREE.FogExp2(0x082c2d, .038);
        const camera = new THREE.PerspectiveCamera(42, 1, .1, 100);
        camera.position.set(0, 6.2, 10.2);
        scene.add(new THREE.HemisphereLight(0xb8fff4, 0x061a1b, 2.5));
        const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(3, 8, 5); scene.add(key);

        const terrainGeometry = sculptTerrain(13, 8.5, 42, 28);
        const terrainMaterial = new THREE.MeshStandardMaterial({ color: 0x0b6e66, roughness: .9, flatShading: true, transparent: true, opacity: .92 });
        const terrain = new THREE.Mesh(terrainGeometry, terrainMaterial); scene.add(terrain);
        const wire = new THREE.LineSegments(new THREE.WireframeGeometry(terrainGeometry), new THREE.LineBasicMaterial({ color: 0x8ee8dc, transparent: true, opacity: .1 })); wire.position.y = .012; scene.add(wire);

        const sensorGeometry = new THREE.CylinderGeometry(.075,.1,.76,8);
        const sensorPositions = [[-3,.55,-1.3],[-.9,.68,.55],[1.7,.48,-.45],[3.2,.65,1.2]];
        const sensorMaterials = sensorPositions.map(() => new THREE.MeshStandardMaterial({ color: 0xdffcf6, emissive: 0x0f766e, emissiveIntensity: .55 }));
        const sensors = sensorPositions.map((point, index) => { const mesh = new THREE.Mesh(sensorGeometry, sensorMaterials[index]); mesh.position.set(...point); scene.add(mesh); return mesh; });
        const node = new THREE.Mesh(new THREE.IcosahedronGeometry(.28,1), new THREE.MeshStandardMaterial({ color: 0xd7ef73, emissive: 0x7e9d21, emissiveIntensity: 1.1 })); node.position.set(3.5,1.2,-2); scene.add(node);
        const networkPoints = [];
        sensorPositions.forEach(([x,y,z]) => networkPoints.push(new THREE.Vector3(x,y,z),node.position.clone()));
        const network = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(networkPoints), new THREE.LineBasicMaterial({ color: 0x8af1e2, transparent: true, opacity: 0 })); scene.add(network);
        const clusterRing = new THREE.Mesh(new THREE.RingGeometry(.5,.58,48), new THREE.MeshBasicMaterial({ color: 0xffb020, transparent: true, opacity: 0, side: THREE.DoubleSide })); clusterRing.rotation.x = -Math.PI / 2; clusterRing.position.set(1.7,.08,-.45); scene.add(clusterRing);
        const acknowledgement = new THREE.Mesh(new THREE.RingGeometry(.25,.33,48), new THREE.MeshBasicMaterial({ color: 0xd7ef73, transparent: true, opacity: 0, side: THREE.DoubleSide })); acknowledgement.rotation.x = -Math.PI / 2; acknowledgement.position.set(3.5,.08,-2); scene.add(acknowledgement);
        const water = new THREE.Mesh(new THREE.PlaneGeometry(5.5,2.7), new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0 })); water.rotation.x = -Math.PI / 2; water.position.set(-1,.12,2); scene.add(water);
        const rainGeometry = new THREE.BufferGeometry();
        const rainPoints = new Float32Array(150 * 3);
        for (let i = 0; i < rainPoints.length; i += 3) { rainPoints[i] = (Math.random()-.5)*12; rainPoints[i+1] = Math.random()*5; rainPoints[i+2] = (Math.random()-.5)*8; }
        rainGeometry.setAttribute('position', new THREE.BufferAttribute(rainPoints,3));
        const rain = new THREE.Points(rainGeometry, new THREE.PointsMaterial({ color: 0x7dd3fc,size:.035,transparent:true,opacity:0 })); scene.add(rain);
        const vector = new THREE.ArrowHelper(new THREE.Vector3(.8,.15,-.35).normalize(),new THREE.Vector3(-.9,.8,.55),1.15,0xffb020,.25,.13); scene.add(vector);

        const imuModule = new THREE.Group(); imuModule.position.set(-.9,1.12,.55); scene.add(imuModule);
        const imuBox = new THREE.Mesh(new THREE.BoxGeometry(.72,.34,.58),new THREE.MeshStandardMaterial({ color:0x163b3d,metalness:.48,roughness:.34,emissive:0xff8a3d,emissiveIntensity:.2 }));
        const imuOutline = new THREE.LineSegments(new THREE.EdgesGeometry(imuBox.geometry),new THREE.LineBasicMaterial({ color:0xffb020 }));
        imuModule.add(imuBox,imuOutline,new THREE.ArrowHelper(new THREE.Vector3(1,0,0),new THREE.Vector3(),.85,0xff6b00,.13,.08),new THREE.ArrowHelper(new THREE.Vector3(0,1,0),new THREE.Vector3(),.75,0x5eead4,.13,.08));

        const piezometer = new THREE.Group(); piezometer.position.set(-2.45,.54,1.55); scene.add(piezometer);
        const pipe = new THREE.LineSegments(new THREE.WireframeGeometry(new THREE.CylinderGeometry(.24,.24,1.5,20,1,true)),new THREE.LineBasicMaterial({ color:0x7dd3fc,transparent:true,opacity:.68 }));
        const level = new THREE.Mesh(new THREE.CylinderGeometry(.19,.19,1.1,20),new THREE.MeshBasicMaterial({ color:0x38bdf8,transparent:true,opacity:.55 })); level.position.y=-.2; piezometer.add(pipe,level);

        const collector = new THREE.Mesh(new THREE.CylinderGeometry(.34,.11,.32,20,1,true),new THREE.MeshStandardMaterial({ color:0x8af1e2,transparent:true,opacity:.22,side:THREE.DoubleSide }));
        collector.position.set(-3.45,.98,.55); scene.add(collector);

        let visible = true, destroyed = false;
        const render = () => { if (!destroyed && visible && !document.hidden) renderer.render(scene,camera); };
        const setProgress = value => {
            const progress = THREE.MathUtils.clamp(value,0,1);
            const context = gsap.utils.clamp(0,1,(progress-.16)/.22);
            const corroborated = gsap.utils.clamp(0,1,(progress-.47)/.15);
            const response = gsap.utils.clamp(0,1,(progress-.72)/.18);
            camera.position.set(-progress*1.5,6.2+progress*1.3,10.2+progress*3.2);
            camera.lookAt(response*1.05,.08,response*-.75);
            terrain.rotation.y = -progress*.09; terrainMaterial.opacity = .92-progress*.18;
            rain.material.opacity = context*.55; water.material.opacity = context*.3;
            collector.material.opacity=.22+context*.72;
            imuModule.rotation.z=-.05+context*.12+corroborated*.2; imuModule.rotation.x=context*.08;
            level.scale.y=.28+context*.9; level.position.y=-.7+context*.48;
            sensors.forEach((sensor,index) => {
                sensor.scale.setScalar(1+corroborated*(index===2?.62:.12));
                sensorMaterials[index].color.setHex(corroborated && index>=1 ? 0xffb020 : 0xdffcf6);
                sensorMaterials[index].emissive.setHex(corroborated && index>=1 ? 0xb45309 : 0x0f766e);
            });
            clusterRing.material.opacity = corroborated*.9; clusterRing.scale.setScalar(.8+corroborated*.55);
            network.material.opacity = response*.76; acknowledgement.material.opacity = response*.96; acknowledgement.scale.setScalar(.7+response*2.2);
            node.material.emissiveIntensity = .8+response*3; vector.visible = progress < .52;
            render();
        };
        const stopResize = watchCanvas(canvas,renderer,camera,render);
        const visibility = new IntersectionObserver(entries => { visible = entries[0]?.isIntersecting ?? true; if (visible) render(); }, { rootMargin:'120px' }); visibility.observe(canvas);
        canvas.classList.add('is-ready'); setProgress(0);
        return { setProgress, destroy() { if (destroyed) return; destroyed=true; visibility.disconnect(); stopResize(); disposeScene(scene,renderer); } };
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
            ScrollTrigger.create({ trigger: hero, start: 'top top', end: 'bottom top', scrub: .8, onUpdate: self => { sceneState.progress = self.progress; controller.setProgress(sceneState.progress); } });
        }
    }

    function setupReveals() {
        if (reducedMotion.matches) {
            $$('.reveal').forEach(element => element.classList.add('is-visible'));
            return;
        }
        document.documentElement.classList.add('gsap-ready');
        $$('.reveal').forEach(element => {
            gsap.fromTo(element,{ autoAlpha:0,y:22 },{ autoAlpha:1,y:0,duration:.55,ease:'power2.out',scrollTrigger:{ trigger:element,start:'top 88%',once:true },onStart:()=>element.classList.add('is-visible'),onComplete:()=>element.classList.add('is-visible') });
        });
    }

    function setupStory() {
        const story = $('#story'), stage = $('.story-stage',story), canvas = $('#story-canvas');
        const articles = $$('[data-story-step]',story), caption = $('#story-caption');
        if (!story || !stage || !articles.length) return;
        const captions = ['Phát hiện · GNSS + góc nghiêng IMU','Bối cảnh · Mưa + mực nước ngầm','Xác minh · Hợp nhất đa cảm biến','Phản ứng · Đã tiếp nhận'];
        if (innerWidth < 901 || reducedMotion.matches) { canvas.hidden = true; return; }
        story.classList.add('story-enhanced');
        let controller = null;
        if (canUse3D(canvas)) {
            try { controller = createStoryController(canvas); cleanups.push(() => controller.destroy()); }
            catch (_) { canvas.hidden = true; }
        } else canvas.hidden = true;

        gsap.set(articles,{ autoAlpha:0,y:24 });
        gsap.set(articles[0],{ autoAlpha:1,y:0 });
        articles.forEach((article,index) => article.setAttribute('aria-hidden',index===0?'false':'true'));
        const timeline = gsap.timeline({ defaults:{ ease:'power2.out' } });
        articles.slice(1).forEach((article,index) => {
            const boundary = index+1;
            timeline.to(articles[index],{ autoAlpha:0,y:-18,duration:.18,ease:'power1.in' },boundary-.1)
                .to(article,{ autoAlpha:1,y:0,duration:.26 },boundary-.04);
        });
        timeline.to(stage,{ '--stage-scale':1.07,'--stage-x':'-3%','--stage-y':'-2%','--stage-radius':'8px',duration:.64,ease:'sine.inOut' },.68)
            .to(stage,{ '--stage-scale':.94,'--stage-x':'4%','--stage-y':'1%','--stage-radius':'28px',duration:.64,ease:'sine.inOut' },1.68)
            .to(stage,{ '--stage-scale':1.02,'--stage-x':'0%','--stage-y':'2%','--stage-radius':'18px',duration:.64,ease:'sine.inOut' },2.68)
            .to({}, { duration:1 },3);
        const trigger = ScrollTrigger.create({
            trigger:story,start:'top top',end:'bottom bottom',animation:timeline,scrub:.85,
            onUpdate:self => {
                const progress = self.progress;
                const step = Math.min(3,Math.floor(progress*4));
                story.dataset.step = String(step); stage.dataset.pose = String(step);
                story.style.setProperty('--story-progress',progress.toFixed(4));
                caption.textContent = captions[step]; controller?.setProgress(progress);
                articles.forEach((article,index) => article.setAttribute('aria-hidden',index===step?'false':'true'));
            }
        });
        cleanups.push(() => trigger.kill());
    }

    function setupFinalMotion() {
        if (reducedMotion.matches) return;
        gsap.to('.cta-contours span',{ rotate:'+=18',scale:1.08,stagger:.08,ease:'none',scrollTrigger:{ trigger:'.final-cta',start:'top bottom',end:'bottom top',scrub:1 } });
    }

    function setupPageMotion() {
        if (reducedMotion.matches) return;
        gsap.to('.scroll-progress-fill',{ scaleY:1,ease:'none',scrollTrigger:{ start:'top top',end:'max',scrub:.2 } });
        gsap.to('.hero-grid',{ yPercent:-12,ease:'none',scrollTrigger:{ trigger:'.hero',start:'top top',end:'bottom top',scrub:1 } });
        gsap.to('.hero-aurora-a',{ yPercent:-24,xPercent:8,ease:'none',scrollTrigger:{ start:'top top',end:'max',scrub:1.2 } });
        gsap.to('.hero-aurora-b',{ yPercent:-14,xPercent:-10,ease:'none',scrollTrigger:{ start:'top top',end:'max',scrub:1.5 } });
    }

    setupHeader();
    setupMetrics();
    setupHero();
    setupReveals();
    setupStory();
    setupFinalMotion();
    setupPageMotion();
    setupAuthLink().catch(() => {});
    addEventListener('load',() => ScrollTrigger.refresh(),{ once:true });
    addEventListener('pagehide',() => cleanups.splice(0).forEach(cleanup => cleanup()),{ once:true });
})();
