/* Shared ESRI ASCII DEM renderer and UTM 48N cell picker. */
(() => {
    'use strict';

    const colorStops = [
        [0.00, [24, 55, 68]],
        [0.24, [40, 105, 99]],
        [0.50, [110, 151, 112]],
        [0.73, [202, 186, 121]],
        [1.00, [238, 226, 191]],
    ];

    function parse(text) {
        const source = String(text || '').replace(/^\uFEFF/, '');
        const lines = [];
        let cursor = 0;
        for (let i = 0; i < 6; i += 1) {
            const end = source.indexOf('\n', cursor);
            if (end < 0) throw new Error('File DEM thiếu dữ liệu.');
            lines.push(source.slice(cursor, end).trim());
            cursor = end + 1;
        }
        const header = {};
        for (const line of lines.slice(0, 6)) {
            const [key, value] = line.trim().split(/\s+/);
            if (!key || value == null) throw new Error('Tiêu đề DEM không đúng định dạng ESRI ASCII Grid.');
            header[key.toLowerCase()] = Number(value);
        }
        const ncols = header.ncols;
        const nrows = header.nrows;
        const cellsize = header.cellsize;
        const nodata = header.nodata_value;
        const xKey = Object.hasOwn(header, 'xllcorner') ? 'xllcorner' : 'xllcenter';
        const yKey = Object.hasOwn(header, 'yllcorner') ? 'yllcorner' : 'yllcenter';
        if (!Number.isInteger(ncols) || !Number.isInteger(nrows) || ncols < 1 || nrows < 1 || ncols * nrows > 10000000
            || !Number.isFinite(cellsize) || cellsize <= 0 || !Number.isFinite(nodata)
            || !Number.isFinite(header[xKey]) || !Number.isFinite(header[yKey])) {
            throw new Error('Thông số lưới hoặc tọa độ DEM không hợp lệ.');
        }
        const xllcorner = header[xKey] - (xKey === 'xllcenter' ? cellsize / 2 : 0);
        const yllcorner = header[yKey] - (yKey === 'yllcenter' ? cellsize / 2 : 0);
        const expected = ncols * nrows;
        const values = new Float32Array(expected);
        let min = Infinity;
        let max = -Infinity;
        const tokens = /\S+/g;
        tokens.lastIndex = cursor;
        let i = 0;
        let match;
        while ((match = tokens.exec(source))) {
            if (i >= expected) throw new Error('Số ô dữ liệu không khớp kích thước DEM.');
            const value = Number(match[0]);
            if (!Number.isFinite(value)) throw new Error('DEM chứa giá trị không hợp lệ.');
            values[i] = value;
            if (value !== nodata) { min = Math.min(min, value); max = Math.max(max, value); }
            i += 1;
        }
        if (i !== expected) throw new Error('Số ô dữ liệu không khớp kích thước DEM.');
        if (!Number.isFinite(min)) throw new Error('DEM không có độ cao hợp lệ.');
        return { ncols, nrows, cellsize, nodata, xllcorner, yllcorner, values, min, max, crs: 'EPSG:32648' };
    }

    function utm48ToWgs84(easting, northing) {
        const a = 6378137;
        const eccentricity = 0.00669437999014;
        const secondEccentricity = eccentricity / (1 - eccentricity);
        const k0 = 0.9996;
        const x = easting - 500000;
        const meridian = northing / k0;
        const mu = meridian / (a * (1 - eccentricity / 4 - 3 * eccentricity ** 2 / 64 - 5 * eccentricity ** 3 / 256));
        const e1 = (1 - Math.sqrt(1 - eccentricity)) / (1 + Math.sqrt(1 - eccentricity));
        const phi1 = mu
            + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * Math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * Math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * Math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * Math.sin(8 * mu);
        const sin = Math.sin(phi1);
        const cos = Math.cos(phi1);
        const tan = Math.tan(phi1);
        const n1 = a / Math.sqrt(1 - eccentricity * sin ** 2);
        const t1 = tan ** 2;
        const c1 = secondEccentricity * cos ** 2;
        const r1 = a * (1 - eccentricity) / (1 - eccentricity * sin ** 2) ** 1.5;
        const d = x / (n1 * k0);
        const latitude = phi1 - (n1 * tan / r1) * (d ** 2 / 2
            - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * secondEccentricity) * d ** 4 / 24
            + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * secondEccentricity - 3 * c1 ** 2) * d ** 6 / 720);
        const longitude = 105 * Math.PI / 180 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
            + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * secondEccentricity + 24 * t1 ** 2) * d ** 5 / 120) / cos;
        return { lat: latitude * 180 / Math.PI, lon: longitude * 180 / Math.PI };
    }

    function wgs84ToUtm48(lat, lon) {
        const a = 6378137;
        const f = 1 / 298.257223563;
        const e2 = 2 * f - f * f;
        const ePrime2 = e2 / (1 - e2);
        const k0 = 0.9996;
        const phi = lat * Math.PI / 180;
        const lambda = lon * Math.PI / 180;
        const lambda0 = 105 * Math.PI / 180;
        const dLambda = lambda - lambda0;
        const sinPhi = Math.sin(phi);
        const cosPhi = Math.cos(phi);
        const tanPhi = Math.tan(phi);
        const N = a / Math.sqrt(1 - e2 * sinPhi * sinPhi);
        const T = tanPhi * tanPhi;
        const C = ePrime2 * cosPhi * cosPhi;
        const A = cosPhi * dLambda;
        const M = a * ((1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 * e2 * e2 / 256) * phi
            - (3 * e2 / 8 + 3 * e2 * e2 / 32 + 45 * e2 * e2 * e2 / 1024) * Math.sin(2 * phi)
            + (15 * e2 * e2 / 256 + 45 * e2 * e2 * e2 / 1024) * Math.sin(4 * phi)
            - (35 * e2 * e2 * e2 / 3072) * Math.sin(6 * phi));
        const easting = 500000 + k0 * N * (A + (1 - T + C) * Math.pow(A, 3) / 6
            + (5 - 18 * T + T * T + 72 * C - 58 * ePrime2) * Math.pow(A, 5) / 120);
        const northing = k0 * (M + N * tanPhi * (A * A / 2
            + (5 - T + 9 * C + 4 * C * C) * Math.pow(A, 4) / 24
            + (61 - 58 * T + T * T + 600 * C - 330 * ePrime2) * Math.pow(A, 6) / 720));
        return { easting, northing };
    }

    async function mount(canvas, grid, { onSelect = null, selectable = false } = {}) {
        const [THREE, { OrbitControls }] = await Promise.all([
            import('three'),
            import('three/addons/controls/OrbitControls.js'),
        ]);
        const listeners = new AbortController();
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x0f252c);
        const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.15;

        const target = new THREE.Vector3(0, 0, 0);
        const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100000);
        const controls = new OrbitControls(camera, canvas);
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;
        controls.target.copy(target);
        scene.add(new THREE.HemisphereLight(0xd9f4ff, 0x253c35, 2.0));
        const sun = new THREE.DirectionalLight(0xffedc5, 2.7);
        sun.position.set(-1, 2, 1.4);
        scene.add(sun);
        const fill = new THREE.DirectionalLight(0x74c8c6, 1.0);
        fill.position.set(1, 0.5, -1);
        scene.add(fill);

        // Keep enough mesh detail for close inspection without overloading the GPU.
        const step = Math.max(1, Math.ceil(Math.max(grid.ncols, grid.nrows) / 1024));
        const columns = Math.ceil((grid.ncols - 1) / step) + 1;
        const rows = Math.ceil((grid.nrows - 1) / step) + 1;
        const width = (grid.ncols - 1) * grid.cellsize;
        const depth = (grid.nrows - 1) * grid.cellsize;
        const relief = Math.max(grid.max - grid.min, grid.cellsize);
        const verticalScale = Math.max(1, Math.min(5, Math.max(width, depth) / relief * 0.16));
        const positions = new Float32Array(columns * rows * 3);
        const colors = new Float32Array(columns * rows * 3);
        const valid = new Uint8Array(columns * rows);
        const color = new THREE.Color();
        const stops = colorStops.map(([t, rgb]) => [t, new THREE.Color().setRGB(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, THREE.SRGBColorSpace)]);
        const sampleRows = new Uint32Array(rows);
        const sampleColumns = new Uint32Array(columns);
        for (let r = 0; r < rows; r += 1) sampleRows[r] = Math.min(grid.nrows - 1, r * step);
        for (let c = 0; c < columns; c += 1) sampleColumns[c] = Math.min(grid.ncols - 1, c * step);
        for (let r = 0; r < rows; r += 1) {
            for (let c = 0; c < columns; c += 1) {
                const vertex = r * columns + c;
                const sourceRow = sampleRows[r];
                const sourceColumn = sampleColumns[c];
                const elevation = grid.values[sourceRow * grid.ncols + sourceColumn];
                const validVertex = elevation !== grid.nodata;
                valid[vertex] = validVertex ? 1 : 0;
                positions[vertex * 3] = (sourceColumn - (grid.ncols - 1) / 2) * grid.cellsize;
                positions[vertex * 3 + 1] = validVertex ? (elevation - grid.min) * verticalScale : 0;
                positions[vertex * 3 + 2] = (sourceRow - (grid.nrows - 1) / 2) * grid.cellsize;
                const t = Math.max(0, Math.min(1, (elevation - grid.min) / Math.max(grid.max - grid.min, 0.001)));
                let stop = stops.findIndex(([limit]) => limit >= t);
                if (stop <= 0) color.copy(stops[0][1]);
                else {
                    const [lo, lowColor] = stops[stop - 1];
                    const [hi, highColor] = stops[stop];
                    color.copy(lowColor).lerp(highColor, (t - lo) / (hi - lo));
                }
                color.toArray(colors, vertex * 3);
            }
        }
        const indices = [];
        for (let r = 0; r < rows - 1; r += 1) {
            for (let c = 0; c < columns - 1; c += 1) {
                const a = r * columns + c;
                const b = a + 1;
                const d = a + columns;
                const e = d + 1;
                if (valid[a] && valid[b] && valid[d]) indices.push(a, d, b);
                if (valid[b] && valid[d] && valid[e]) indices.push(b, d, e);
            }
        }
        const terrainGeometry = new THREE.BufferGeometry();
        terrainGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        terrainGeometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
        terrainGeometry.setIndex(indices);
        terrainGeometry.computeVertexNormals();
        const terrain = new THREE.Mesh(terrainGeometry, new THREE.MeshStandardMaterial({
            vertexColors: true, roughness: 0.88, metalness: 0, side: THREE.DoubleSide,
        }));
        scene.add(terrain);

        const marker = new THREE.Group();
        const cellMarker = new THREE.Mesh(
            new THREE.PlaneGeometry(grid.cellsize * 0.92, grid.cellsize * 0.92),
            new THREE.MeshBasicMaterial({ color: 0xffd166, transparent: true, opacity: 0.42, side: THREE.DoubleSide, depthWrite: false }),
        );
        cellMarker.rotation.x = -Math.PI / 2;
        const markerOutline = new THREE.LineSegments(
            new THREE.EdgesGeometry(new THREE.PlaneGeometry(grid.cellsize * 0.92, grid.cellsize * 0.92)),
            new THREE.LineBasicMaterial({ color: 0xffefb0, depthTest: false }),
        );
        markerOutline.rotation.x = -Math.PI / 2;
        marker.add(cellMarker, markerOutline);
        marker.visible = false;
        scene.add(marker);
        const raycaster = new THREE.Raycaster();
        const pointer = new THREE.Vector2();
        const state = { selected: null, destroyed: false };
        const requestRender = () => { if (!state.destroyed) renderer.render(scene, camera); };

        function pointAt(row, column) {
            const boundedRow = Math.max(0, Math.min(grid.nrows - 1, row));
            const boundedColumn = Math.max(0, Math.min(grid.ncols - 1, column));
            const elevation = grid.values[boundedRow * grid.ncols + boundedColumn];
            if (elevation === grid.nodata) return null;
            return {
                row: boundedRow, column: boundedColumn,
                easting: grid.xllcorner + (boundedColumn + 0.5) * grid.cellsize,
                northing: grid.yllcorner + (grid.nrows - boundedRow - 0.5) * grid.cellsize,
                elevation,
                x: (boundedColumn - (grid.ncols - 1) / 2) * grid.cellsize,
                y: (elevation - grid.min) * verticalScale,
                z: (boundedRow - (grid.nrows - 1) / 2) * grid.cellsize,
                ...utm48ToWgs84(
                    grid.xllcorner + (boundedColumn + 0.5) * grid.cellsize,
                    grid.yllcorner + (grid.nrows - boundedRow - 0.5) * grid.cellsize,
                ),
            };
        }

        function setSelected(point) {
            state.selected = point;
            if (point) {
                marker.position.set(point.x, point.y + Math.max(grid.cellsize * 0.04, relief * verticalScale * 0.001), point.z);
                marker.visible = true;
            } else marker.visible = false;
            requestRender();
        }

        const fit = () => {
            const span = Math.max(width, depth, relief * verticalScale, 1);
            const distance = span / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) * 1.12;
            target.set(0, Math.max(0, relief * verticalScale * 0.24), 0);
            controls.target.copy(target);
            camera.position.copy(target).add(new THREE.Vector3(distance * 0.95, distance * 0.9, distance * 1.15));
            camera.near = Math.max(0.01, distance / 1000);
            camera.far = distance * 20;
            camera.updateProjectionMatrix();
            controls.update();
            requestRender();
        };

        let pointerStart = null;
        canvas.addEventListener('pointerdown', event => {
            pointerStart = event.isPrimary && event.button === 0 ? { x: event.clientX, y: event.clientY } : null;
        }, { signal: listeners.signal });
        canvas.addEventListener('pointerup', event => {
            if (!selectable || !onSelect || !event.isPrimary || event.button !== 0) return;
            if (!pointerStart || Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) > 5) return;
            const box = canvas.getBoundingClientRect();
            pointer.set((event.clientX - box.left) / box.width * 2 - 1, -((event.clientY - box.top) / box.height) * 2 + 1);
            raycaster.setFromCamera(pointer, camera);
            const hit = raycaster.intersectObject(terrain, false)[0];
            if (!hit) return;
            const column = Math.round(hit.point.x / grid.cellsize + (grid.ncols - 1) / 2);
            const row = Math.round(hit.point.z / grid.cellsize + (grid.nrows - 1) / 2);
            const point = pointAt(row, column);
            if (!point) return;
            setSelected(point);
            onSelect(point, { commit: true, source: 'pointer' });
            pointerStart = null;
        }, { signal: listeners.signal });
        canvas.addEventListener('pointercancel', () => { pointerStart = null; }, { signal: listeners.signal });
        canvas.addEventListener('keydown', event => {
            if (!selectable || !onSelect) return;
            const moves = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
            if (moves[event.key]) {
                event.preventDefault();
                const current = state.selected || pointAt(Math.floor(grid.nrows / 2), Math.floor(grid.ncols / 2));
                if (!current) return;
                const point = pointAt(current.row + moves[event.key][0], current.column + moves[event.key][1]);
                if (point) { setSelected(point); onSelect(point, { commit: false, source: 'keyboard' }); }
            } else if (event.key === 'Enter' && state.selected) {
                event.preventDefault();
                onSelect(state.selected, { commit: true, source: 'keyboard' });
            }
        }, { signal: listeners.signal });

        controls.addEventListener('change', requestRender);
        const resizeObserver = new ResizeObserver(() => {
            const box = canvas.getBoundingClientRect();
            if (!box.width || !box.height) return;
            renderer.setSize(box.width, box.height, false);
            camera.aspect = box.width / box.height;
            camera.updateProjectionMatrix();
            requestRender();
        });
        resizeObserver.observe(canvas);
        fit();
        renderer.setAnimationLoop(() => {
            controls.update();
            renderer.render(scene, camera);
        });

        return {
            zoomIn() { camera.position.sub(controls.target).multiplyScalar(0.8).add(controls.target); controls.update(); },
            zoomOut() { camera.position.sub(controls.target).multiplyScalar(1.25).add(controls.target); controls.update(); },
            fit,
            destroy() {
                state.destroyed = true;
                renderer.setAnimationLoop(null);
                resizeObserver.disconnect();
                listeners.abort();
                controls.dispose();
                terrainGeometry.dispose();
                terrain.material.dispose();
                cellMarker.geometry.dispose();
                cellMarker.material.dispose();
                markerOutline.geometry.dispose();
                markerOutline.material.dispose();
                renderer.dispose();
            },
        };
    }

    window.DemGrid = { parse, mount, utm48ToWgs84, wgs84ToUtm48 };
})();
