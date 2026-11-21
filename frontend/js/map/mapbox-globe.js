/* global mapboxgl */
// =====================================================
// MAPBOX 3D GLOBE CONTROLLER
// =====================================================
(() => {
    'use strict';

    let sdkLoadingPromise = null;

    function loadMapboxSdk() {
        if (typeof window !== 'undefined' && window.mapboxgl) {
            return Promise.resolve(window.mapboxgl);
        }
        if (!sdkLoadingPromise) {
            sdkLoadingPromise = new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = '/assets/mapbox-gl-sdk.min.js';
                script.async = true;
                script.onload = () => resolve(window.mapboxgl);
                script.onerror = () => {
                    sdkLoadingPromise = null;
                    script.remove();
                    reject(new Error('Không thể tải Mapbox GL SDK'));
                };
                document.head.appendChild(script);
            });
        }
        return sdkLoadingPromise;
    }

    const ISLAND_FEATURES = Object.freeze([
        { type: 'Feature', properties: { name: 'Quần đảo Hoàng Sa\n(VIỆT NAM)' }, geometry: { type: 'Point', coordinates: [112.02, 16.53] } },
        { type: 'Feature', properties: { name: 'Quần đảo Trường Sa\n(VIỆT NAM)' }, geometry: { type: 'Point', coordinates: [114.25, 9.88] } },
        { type: 'Feature', properties: { name: 'Biển Đông' }, geometry: { type: 'Point', coordinates: [113.0, 13.2] } },
    ]);

    function escapeHtml(str) {
        return String(str ?? '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#39;');
    }

    function pointInRing(pt, ring) {
        let inside = false;
        const x = pt[0];
        const y = pt[1];
        for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
            const xi = ring[i][0];
            const yi = ring[i][1];
            const xj = ring[j][0];
            const yj = ring[j][1];
            const intersect = ((yi > y) !== (yj > y)) && (x < ((xj - xi) * (y - yi)) / (yj - yi) + xi);
            if (intersect) inside = !inside;
        }
        return inside;
    }

    function pointInPolygonCoords(pt, rings) {
        if (!rings?.[0] || !pointInRing(pt, rings[0])) return false;
        for (let i = 1; i < rings.length; i++) {
            if (pointInRing(pt, rings[i])) return false;
        }
        return true;
    }

    function pointInGeometry(pt, geom) {
        if (!geom?.coordinates) return false;
        if (geom.type === 'Polygon') {
            return pointInPolygonCoords(pt, geom.coordinates);
        }
        if (geom.type === 'MultiPolygon') {
            for (const polygonCoords of geom.coordinates) {
                if (pointInPolygonCoords(pt, polygonCoords)) return true;
            }
        }
        return false;
    }

    function renderProvincePopupHtml(feature, stations = []) {
        const p = feature?.properties || {};
        const inProvince = (stations || []).filter(s => {
            const lat = Number(s?.location?.lat ?? s?.latitude);
            const lon = Number(s?.location?.lon ?? s?.longitude);
            if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
            return pointInGeometry([lon, lat], feature.geometry);
        });

        const safeCount = inProvince.filter(s => (s.status || 'safe') === 'safe').length;
        const alertCount = inProvince.filter(s => s.status === 'warning' || s.status === 'critical').length;

        const areaStr = p.areaKm2 ? `${Number(p.areaKm2).toLocaleString('vi-VN')} km²` : '--';
        const postalStr = p.postalCodePrefix || '--';

        let stationText = '<span style="color:#22c55e;font-weight:700;">0 trạm</span>';
        if (inProvince.length > 0) {
            stationText = `<span style="color:#22c55e;font-weight:700;">${safeCount} an toàn</span> / ` +
                `<span style="color:#f59e0b;font-weight:700;">${alertCount} cảnh báo</span> / ` +
                `<span style="color:#64748b;">${inProvince.length} tổng</span>`;
        }

        return `
            <div class="station-map-popup">
                <div class="station-map-popup-title">${escapeHtml(p.fullName || p.name || 'Tỉnh / Thành')}</div>
                <div style="font-size:0.75rem;color:#64748b;margin-bottom:6px;">${escapeHtml(p.fullNameEn || p.nameEn || '')}</div>
                <div class="station-map-popup-grid">
                    <span class="station-map-popup-label">Mã hành chính</span>
                    <span class="station-map-popup-value">${escapeHtml(p.code || '--')}</span>
                    <span class="station-map-popup-label">Mã bưu chính</span>
                    <span class="station-map-popup-value">${escapeHtml(postalStr)}</span>
                    <span class="station-map-popup-label">Diện tích</span>
                    <span class="station-map-popup-value">${escapeHtml(areaStr)}</span>
                    <span class="station-map-popup-label">Trạm quan trắc</span>
                    <span class="station-map-popup-value">${stationText}</span>
                </div>
            </div>
        `;
    }

    function resolveStationColor(status) {
        if (status === 'critical') return '#ef4444';
        if (status === 'warning') return '#f59e0b';
        if (status === 'offline') return '#94a3b8';
        return '#22c55e';
    }

    function createStationGeoJson(stations = []) {
        const features = (stations || [])
            .filter(item => item?.location?.lat && item?.location?.lon)
            .map(item => {
                const status = item.status || 'safe';
                const color = resolveStationColor(status);
                return {
                    type: 'Feature',
                    properties: {
                        id: item.id,
                        code: item.station_code || String(item.id),
                        name: item.name || '',
                        status,
                        color,
                    },
                    geometry: {
                        type: 'Point',
                        coordinates: [Number(item.location.lon), Number(item.location.lat)],
                    },
                };
            });
        return { type: 'FeatureCollection', features };
    }

    function resolveProjectCenter(project, allStations = []) {
        const stations = (allStations || []).filter(station => (
            String(station.project_id) === String(project.id) &&
            station.location?.lat != null && station.location?.lon != null
        ));
        const points = stations.map(station => [Number(station.location.lat), Number(station.location.lon)]);
        const dems = Array.isArray(project.dems) ? project.dems : [];

        let demCenter = null;
        if (!points.length && !(project.location?.lat != null && project.location?.lon != null)) {
            demCenter = typeof window._computeDemCenter === 'function' ? window._computeDemCenter(dems) : null;
        }

        if (!points.length && !(project.location?.lat != null && project.location?.lon != null) && !demCenter) {
            return null;
        }

        const center = (project.location?.lat != null && project.location?.lon != null)
            ? [Number(project.location.lat), Number(project.location.lon)]
            : (demCenter || points.reduce((sum, p) => [sum[0] + p[0], sum[1] + p[1]], [0, 0]).map(v => v / points.length));

        return {
            center,
            stationCount: stations.length,
            demCount: dems.length,
        };
    }

    function createProjectMarkerElement(project, stationCount, demCount) {
        const el = document.createElement('div');
        el.className = 'project-map-marker';
        el.style.width = '52px';
        el.style.height = '60px';
        el.style.cursor = 'pointer';
        el.setAttribute('role', 'button');
        el.setAttribute('tabindex', '0');
        const name = String(project.name || 'Dự án');
        const countLabel = stationCount || (demCount ? '3D' : 0);
        el.setAttribute('aria-label', `${name}: xem toàn bộ ${stationCount} trạm cảm biến`);
        el.innerHTML = '<span class="project-map-halo" aria-hidden="true"></span>' +
            '<span class="project-map-point" aria-hidden="true">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M4 20V8l8-4 8 4v12H4Z"/>' +
            '<path d="M9 20v-5h6v5M8 10h.01M12 10h.01M16 10h.01"/>' +
            '</svg></span>' +
            `<span class="project-map-count" aria-hidden="true">${countLabel}</span>`;
        return el;
    }

    function createProjectTooltip(project, stationCount) {
        const name = String(project.name || 'Dự án');
        const tooltipPopup = new window.mapboxgl.Popup({
            offset: [0, -56],
            closeButton: false,
            closeOnClick: false,
            className: 'project-map-mapbox-popup',
        });
        const tooltipContent = document.createElement('div');
        tooltipContent.className = 'project-map-tooltip';
        const titleEl = document.createElement('strong');
        titleEl.textContent = name;
        const hintEl = document.createElement('span');
        hintEl.textContent = stationCount
            ? `${stationCount} trạm · Bấm để mở dashboard`
            : 'Mô hình DEM 3D · Bấm để xem địa hình';
        tooltipContent.append(titleEl, hintEl);
        tooltipPopup.setDOMContent(tooltipContent);
        return tooltipPopup;
    }

    class MapboxGlobeController {
        map = null;
        container = null;
        active = false;
        spinning = true;
        interacting = false;
        ready = false;
        projection = 'globe';
        selectedProvinceCode = '';
        resumeTimer = null;
        spinInterval = null;
        provincesGeoJson = null;
        popup = null;
        projects = [];
        projectMarkers = [];
        suppressProvinceClick = false;

        async init(container) {
            if (this.map) return this.map;
            this.container = container;

            let token = window.mapboxAccessToken;
            if (!token?.startsWith('pk.')) {
                try {
                    const res = await fetch('/api/public/map-config');
                    if (res.ok) {
                        const cfg = await res.json();
                        token = cfg?.mapbox_public_token || cfg?.mapbox_token || '';
                        if (token?.startsWith('pk.')) {
                            window.mapboxAccessToken = token;
                        }
                    }
                } catch {
                    // ignore
                }
            }

            if (!token?.startsWith('pk.')) {
                throw new Error('Chưa cấu hình token Mapbox hợp lệ.');
            }

            const sdk = await loadMapboxSdk();
            if (!sdk?.supported?.()) {
                throw new Error('Trình duyệt chưa hỗ trợ WebGL 3D.');
            }

            this.map = new sdk.Map({
                container,
                accessToken: token,
                style: 'mapbox://styles/mapbox/satellite-streets-v12',
                projection: 'globe',
                center: [108.2, 16.0],
                zoom: 4.8,
                minZoom: 0,
                maxZoom: 19,
                maxPitch: 65,
                renderWorldCopies: false,
                attributionControl: { compact: true },
                antialias: false,
                fadeDuration: 300,
            });

            this.map.scrollZoom.setWheelZoomRate(1 / 200);
            this.map.addControl(new sdk.NavigationControl({ visualizePitch: true }), 'top-right');
            this._setupEvents();
            return this.map;
        }

        _setupEvents() {
            const map = this.map;
            map.on('style.load', () => this._onStyleLoad());
            map.on('load', () => {
                this.ready = true;
                this._startSpin();
                if (this.projects.length === 0 && window.allProjects?.length) {
                    this.projects = window.allProjects;
                }
                this._renderProjectMarkers();
            });
            map.on('zoom', () => {
                this._updateMarkersVisibility();
            });

            const pause = () => {
                this.interacting = true;
                this._stopSpin();
                clearTimeout(this.resumeTimer);
            };

            const resume = () => {
                clearTimeout(this.resumeTimer);
                this.resumeTimer = setTimeout(() => {
                    this.interacting = false;
                    if (this.spinning && this.active && this.projection === 'globe' && map.getZoom() < 5) {
                        this._startSpin();
                    }
                }, 650);
            };

            map.on('movestart', pause);
            map.on('moveend', resume);

            const canvas = map.getCanvas();
            canvas.addEventListener('pointerdown', pause);
            canvas.addEventListener('wheel', resume, { passive: true });
            window.addEventListener('pointerup', resume);

            map.on('click', (e) => {
                const activeLayers = ['vietnam-provinces-fill', 'station-pins-circle', 'station-clusters', 'vietnam-island-labels']
                    .filter(id => map.getLayer(id));
                if (activeLayers.length === 0) return;
                const features = map.queryRenderedFeatures(e.point, { layers: activeLayers });
                if (!features || features.length === 0) {
                    this.clearProvinceSelection();
                    this.popup?.remove();
                }
            });
        }

        _onStyleLoad() {
            const map = this.map;
            map.setFog({
                color: 'rgb(186, 210, 235)',
                'high-color': 'rgb(36, 92, 223)',
                'horizon-blend': 0.002,
                'space-color': 'rgb(11, 11, 25)',
                'star-intensity': 0.0,
            });

            void this._installProvinceLayers();
            this._installIslandLayers();
            this._installStationLayers();
        }

        async _loadProvincesData() {
            if (this.provincesGeoJson) return this.provincesGeoJson;
            try {
                const res = await fetch('/api/public/vietnam-provinces-geojson');
                if (res.ok) {
                    this.provincesGeoJson = await res.json();
                }
            } catch {
                // ignore
            }
            return this.provincesGeoJson;
        }

        async _installProvinceLayers() {
            const map = this.map;
            const data = await this._loadProvincesData();
            if (map.getSource('vietnam-provinces')) return;

            map.addSource('vietnam-provinces', {
                type: 'geojson',
                data: data || '/api/public/vietnam-provinces-geojson',
            });

            map.addLayer({
                id: 'vietnam-provinces-fill',
                type: 'fill',
                source: 'vietnam-provinces',
                paint: { 'fill-color': '#38bdf8', 'fill-opacity': 0.05 },
            });

            map.addLayer({
                id: 'vietnam-provinces-halo',
                type: 'line',
                source: 'vietnam-provinces',
                paint: { 'line-color': '#0c2540', 'line-width': 4, 'line-opacity': 0.6 },
            });

            map.addLayer({
                id: 'vietnam-provinces-line',
                type: 'line',
                source: 'vietnam-provinces',
                paint: {
                    'line-color': '#38bdf8',
                    'line-width': ['interpolate', ['linear'], ['zoom'], 2, 1.2, 7, 2.5],
                    'line-opacity': 0.95,
                },
            });

            const selFilter = ['==', ['to-string', ['get', 'code']], this.selectedProvinceCode || ''];
            map.addLayer({
                id: 'vietnam-province-selected-fill',
                type: 'fill',
                source: 'vietnam-provinces',
                filter: selFilter,
                paint: { 'fill-color': '#0ea5e9', 'fill-opacity': 0.18 },
            });

            map.addLayer({
                id: 'vietnam-province-selected-line',
                type: 'line',
                source: 'vietnam-provinces',
                filter: selFilter,
                paint: { 'line-color': '#fbbf24', 'line-width': 3.5, 'line-opacity': 1 },
            });

            map.on('click', 'vietnam-provinces-fill', (e) => {
                if (this.suppressProvinceClick || map.getZoom() >= 10.5) return;
                if (this._isInteractiveFeatureHit(e.point)) return;
                const feature = e.features?.[0];
                if (!feature?.properties) return;
                this.fitProvince(feature.properties.code, { lngLat: e.lngLat, fit: false });
            });

            map.on('mouseenter', 'vietnam-provinces-fill', () => {
                if (map.getZoom() < 10.5) {
                    map.getCanvas().style.cursor = 'pointer';
                }
            });
            map.on('mouseleave', 'vietnam-provinces-fill', () => {
                map.getCanvas().style.cursor = '';
            });
        }

        _isInteractiveFeatureHit(point) {
            const map = this.map;
            if (!map) return false;
            const interactiveLayers = ['station-clusters', 'station-pins-circle', 'station-pins-glow', 'station-pins-label', 'vietnam-island-labels']
                .filter(id => map.getLayer(id));
            if (interactiveLayers.length === 0) return false;
            const bbox = [
                [point.x - 8, point.y - 8],
                [point.x + 8, point.y + 8],
            ];
            const hitFeatures = map.queryRenderedFeatures(bbox, { layers: interactiveLayers });
            return Boolean(hitFeatures && hitFeatures.length > 0);
        }

        _installIslandLayers() {
            const map = this.map;
            map.addSource('vietnam-islands', {
                type: 'geojson',
                data: { type: 'FeatureCollection', features: [...ISLAND_FEATURES] },
            });

            map.addLayer({
                id: 'vietnam-island-labels',
                type: 'symbol',
                source: 'vietnam-islands',
                minzoom: 2,
                layout: {
                    'text-field': ['get', 'name'],
                    'text-size': ['interpolate', ['linear'], ['zoom'], 2, 11, 7, 15],
                    'text-anchor': 'center',
                    'text-line-height': 1.3,
                    'text-allow-overlap': true,
                },
                paint: {
                    'text-color': '#ffffff',
                    'text-halo-color': '#0369a1',
                    'text-halo-width': 2.5,
                },
            });

            map.on('click', 'vietnam-island-labels', (e) => {
                const p = e.features?.[0]?.properties;
                if (!p) return;
                const name = String(p.name || '').replaceAll('\n', ' - ');
                const desc = name.includes('Hoàng Sa') || name.includes('Trường Sa')
                    ? 'Quần đảo thuộc chủ quyền thiêng liêng của nước Cộng hòa Xã hội Chủ nghĩa Việt Nam.'
                    : 'Vùng biển chủ quyền thuộc quyền tài phán của Việt Nam.';
                this._showTextPopup(e.lngLat, name, desc);
            });
        }

        _installStationLayers() {
            const map = this.map;
            const stations = window.allStations || [];
            map.addSource('station-pins', {
                type: 'geojson',
                data: createStationGeoJson(stations),
                cluster: true,
                clusterMaxZoom: 14,
                clusterRadius: 50,
            });

            // Cluster glow
            map.addLayer({
                id: 'station-clusters-glow',
                type: 'circle',
                source: 'station-pins',
                minzoom: 10,
                filter: ['has', 'point_count'],
                paint: {
                    'circle-radius': [
                        'step',
                        ['get', 'point_count'],
                        22,
                        10, 28,
                        30, 34,
                    ],
                    'circle-color': '#0284c7',
                    'circle-opacity': 0.25,
                },
            });

            // Cluster circle
            map.addLayer({
                id: 'station-clusters',
                type: 'circle',
                source: 'station-pins',
                minzoom: 10,
                filter: ['has', 'point_count'],
                paint: {
                    'circle-radius': [
                        'step',
                        ['get', 'point_count'],
                        16,
                        10, 20,
                        30, 24,
                    ],
                    'circle-color': [
                        'step',
                        ['get', 'point_count'],
                        '#0284c7',
                        10, '#0ea5e9',
                        30, '#059669',
                    ],
                    'circle-stroke-width': 2.5,
                    'circle-stroke-color': '#ffffff',
                    'circle-opacity': 0.95,
                },
            });

            // Cluster count label
            map.addLayer({
                id: 'station-cluster-count',
                type: 'symbol',
                source: 'station-pins',
                minzoom: 10,
                filter: ['has', 'point_count'],
                layout: {
                    'text-field': '{point_count_abbreviated}',
                    'text-size': 12,
                },
                paint: {
                    'text-color': '#ffffff',
                },
            });

            // Unclustered station pins glow
            map.addLayer({
                id: 'station-pins-glow',
                type: 'circle',
                source: 'station-pins',
                minzoom: 10,
                filter: ['!', ['has', 'point_count']],
                paint: {
                    'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 8, 8, 14],
                    'circle-color': ['get', 'color'],
                    'circle-opacity': 0.25,
                },
            });

            // Unclustered station pins circle
            map.addLayer({
                id: 'station-pins-circle',
                type: 'circle',
                source: 'station-pins',
                minzoom: 10,
                filter: ['!', ['has', 'point_count']],
                paint: {
                    'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 4, 8, 7],
                    'circle-color': ['get', 'color'],
                    'circle-stroke-color': '#ffffff',
                    'circle-stroke-width': 2,
                },
            });

            // Unclustered station pins label
            map.addLayer({
                id: 'station-pins-label',
                type: 'symbol',
                source: 'station-pins',
                filter: ['!', ['has', 'point_count']],
                minzoom: 6,
                layout: {
                    'text-field': ['get', 'code'],
                    'text-size': 11,
                    'text-offset': [0, 1.2],
                    'text-anchor': 'top',
                },
                paint: {
                    'text-color': '#f8fafc',
                    'text-halo-color': '#0f172a',
                    'text-halo-width': 2,
                },
            });

            // Click cluster to zoom in
            map.on('click', 'station-clusters', (e) => {
                this.clearProvinceSelection();
                this.popup?.remove();
                this.suppressProvinceClick = true;
                setTimeout(() => { this.suppressProvinceClick = false; }, 350);
                const features = map.queryRenderedFeatures(e.point, { layers: ['station-clusters'] });
                const clusterId = features[0]?.properties?.cluster_id;
                const source = map.getSource('station-pins');
                if (!source || clusterId === undefined) return;
                source.getClusterExpansionZoom(clusterId, (err, zoom) => {
                    if (err) return;
                    this._stopSpin();
                    map.easeTo({
                        center: features[0].geometry.coordinates,
                        zoom: zoom + 0.5,
                        duration: 600,
                    });
                });
            });
            map.on('mouseenter', 'station-clusters', () => { map.getCanvas().style.cursor = 'pointer'; });
            map.on('mouseleave', 'station-clusters', () => { map.getCanvas().style.cursor = ''; });

            // Click individual station pin
            map.on('click', 'station-pins-circle', (e) => {
                this.clearProvinceSelection();
                this.popup?.remove();
                this.suppressProvinceClick = true;
                setTimeout(() => { this.suppressProvinceClick = false; }, 350);
                const stationId = e.features?.[0]?.properties?.id;
                if (stationId && typeof window.selectStation === 'function') {
                    void window.selectStation(stationId);
                }
            });

            map.on('mouseenter', 'station-pins-circle', () => { map.getCanvas().style.cursor = 'pointer'; });
            map.on('mouseleave', 'station-pins-circle', () => { map.getCanvas().style.cursor = ''; });
        }

        fitProvince(code, options = {}) {
            const feature = this.provincesGeoJson?.features?.find(item => String(item.properties.code) === String(code));
            if (!feature) return;

            const points = [];
            const collect = val => {
                if (typeof val[0] === 'number') points.push(val);
                else val.forEach(collect);
            };
            collect(feature.geometry.coordinates);

            this.selectedProvinceCode = String(code);
            for (const id of ['vietnam-province-selected-fill', 'vietnam-province-selected-line']) {
                if (this.map?.getLayer(id)) {
                    this.map.setFilter(id, ['==', ['to-string', ['get', 'code']], this.selectedProvinceCode]);
                }
            }

            let west = Infinity;
            let east = -Infinity;
            let south = Infinity;
            let north = -Infinity;
            for (const [lon, lat] of points) {
                west = Math.min(west, lon);
                east = Math.max(east, lon);
                south = Math.min(south, lat);
                north = Math.max(north, lat);
            }

            if (options.fit) {
                this._stopSpin();
                this.map?.fitBounds([[west, south], [east, north]], { padding: 60, maxZoom: 11, duration: 900 });
            }

            const content = document.createElement('div');
            content.className = 'station-map-popup';
            content.innerHTML = renderProvincePopupHtml(feature, window.allStations || []);

            const zoomBtn = document.createElement('button');
            zoomBtn.type = 'button';
            zoomBtn.className = 'btn btn-sm btn-outline-info w-100 mt-2';
            zoomBtn.textContent = 'Phóng tới tỉnh / thành';
            zoomBtn.addEventListener('click', () => {
                this.fitProvince(code, { fit: true, lngLat: options.lngLat });
            });
            content.appendChild(zoomBtn);

            const targetPos = options.lngLat || [(west + east) / 2, (south + north) / 2];
            this._showPopup(content, targetPos);
        }

        clearProvinceSelection() {
            this.selectedProvinceCode = '';
            for (const id of ['vietnam-province-selected-fill', 'vietnam-province-selected-line']) {
                if (this.map?.getLayer(id)) {
                    this.map.setFilter(id, ['==', ['to-string', ['get', 'code']], '']);
                }
            }
        }

        _showPopup(content, lngLat) {
            this.popup?.remove();
            if (typeof window.mapboxgl?.Popup !== 'function' || !this.map) return;
            this.popup = new window.mapboxgl.Popup({ offset: 12, maxWidth: '340px', focusAfterOpen: false })
                .setLngLat(lngLat)
                .setDOMContent(content)
                .addTo(this.map);
            this.popup.on('close', () => {
                this.clearProvinceSelection();
            });
            const closeBtn = this.popup.getElement()?.querySelector('.mapboxgl-popup-close-button');
            closeBtn?.removeAttribute('aria-hidden');
            closeBtn?.setAttribute('aria-label', 'Đóng thông tin');
        }

        _showTextPopup(lngLat, title, desc) {
            this.clearProvinceSelection();
            const content = document.createElement('div');
            content.className = 'station-map-popup';
            const titleEl = document.createElement('div');
            titleEl.className = 'station-map-popup-title';
            titleEl.textContent = title;
            const descEl = document.createElement('p');
            descEl.className = 'small text-muted mb-0 mt-1';
            descEl.textContent = desc;
            content.appendChild(titleEl);
            content.appendChild(descEl);
            this._showPopup(content, lngLat);
        }

        updateStations(stations) {
            const source = this.map?.getSource?.('station-pins');
            source?.setData?.(createStationGeoJson(stations));
            if (this.ready) {
                this._renderProjectMarkers();
            }
        }

        updateProjects(projects) {
            this.projects = Array.isArray(projects) ? projects : [];
            if (this.ready) {
                this._renderProjectMarkers();
            }
        }

        _renderProjectMarkers() {
            if (!this.map || !this.ready || typeof window.mapboxgl?.Marker !== 'function') return;

            for (const item of this.projectMarkers) {
                item.tooltipPopup?.remove();
                item.marker?.remove();
            }
            this.projectMarkers = [];

            const projects = this.projects.length > 0 ? this.projects : (window.allProjects || []);
            const allStations = window.allStations || [];

            for (const project of projects) {
                const resolved = resolveProjectCenter(project, allStations);
                if (!resolved) continue;

                const { center, stationCount, demCount } = resolved;
                const [lat, lon] = center;
                if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;

                const el = createProjectMarkerElement(project, stationCount, demCount);
                const tooltipPopup = createProjectTooltip(project, stationCount);

                el.addEventListener('mouseenter', () => {
                    tooltipPopup.setLngLat([lon, lat]).addTo(this.map);
                });
                el.addEventListener('mouseleave', () => {
                    tooltipPopup.remove();
                });

                const handleProjectClick = (evt) => {
                    evt?.stopPropagation?.();
                    this.clearProvinceSelection();
                    this.popup?.remove();
                    this.suppressProvinceClick = true;
                    setTimeout(() => { this.suppressProvinceClick = false; }, 350);
                    tooltipPopup.remove();
                    this._stopSpin();
                    this.map?.flyTo({
                        center: [lon, lat],
                        zoom: Math.max(this.map.getZoom(), 14),
                        duration: 1200,
                    });
                    document.getElementById('station-list-sidebar')?.classList.remove('is-open');
                    document.getElementById('detail-sidebar')?.classList.remove('is-open');
                    document.getElementById('gnss-advanced-sidepanel')?.classList.remove('is-open');
                    document.getElementById('charts-panel')?.classList.remove('is-open');
                    document.getElementById('longterm-overlay')?.classList.remove('active');

                    if (typeof window.openProjectDashboard === 'function') {
                        void window.openProjectDashboard(project, [lat, lon], el);
                    }
                };

                el.addEventListener('click', handleProjectClick);
                el.addEventListener('keydown', (e) => {
                    if (['Enter', ' '].includes(e.key)) {
                        e.preventDefault();
                        handleProjectClick(e);
                    }
                });

                const marker = new window.mapboxgl.Marker({ element: el, anchor: 'bottom' })
                    .setLngLat([lon, lat])
                    .addTo(this.map);

                this.projectMarkers.push({
                    marker,
                    el,
                    tooltipPopup,
                    project,
                    center: [lat, lon],
                    stationCount,
                });
            }

            this._updateMarkersVisibility();
        }

        _updateMarkersVisibility() {
            if (!this.map) return;
            const zoom = this.map.getZoom();
            for (const item of this.projectMarkers) {
                const hide = item.stationCount > 0 && zoom >= 13;
                item.el.style.display = hide ? 'none' : '';
            }
        }

        setProvincesVisible(visible) {
            const visibility = visible ? 'visible' : 'none';
            for (const id of ['vietnam-provinces-fill', 'vietnam-provinces-halo', 'vietnam-provinces-line']) {
                if (this.map?.getLayer(id)) {
                    this.map.setLayoutProperty(id, 'visibility', visibility);
                }
            }
        }

        _startSpin() {
            this._stopSpin();
            if (!this.spinning || !this.active || this.projection !== 'globe' || !this.map) return;
            this.spinInterval = setInterval(() => {
                if (!this.map || this.interacting || this.map.getZoom() >= 5) return;
                const center = this.map.getCenter();
                center.lng -= 0.15;
                this.map.easeTo({ center, duration: 1000, easing: n => n });
            }, 1000);
        }

        _stopSpin() {
            if (this.spinInterval) {
                clearInterval(this.spinInterval);
                this.spinInterval = null;
            }
        }

        setProjection(proj) {
            this.projection = proj;
            this.map?.setProjection(proj);
            if (proj !== 'globe') {
                this._stopSpin();
            } else if (this.active && (this.map?.getZoom() ?? 0) < 5) {
                this._startSpin();
            }
        }

        focusGlobe() {
            this.interacting = false;
            this.map?.stop();
            this.map?.flyTo({
                center: [108.2, 16.0],
                zoom: 1.8,
                pitch: 0,
                bearing: 0,
                duration: 1800,
            });
        }

        focusVietnam() {
            this.interacting = false;
            this.map?.stop();
            this.map?.flyTo({
                center: [108.2, 16.2],
                zoom: 5.6,
                pitch: 0,
                bearing: 0,
                duration: 1500,
            });
        }

        zoomIn() {
            this.map?.zoomIn({ duration: 300 });
        }

        zoomOut() {
            this.map?.zoomOut({ duration: 300 });
        }

        setActive(active) {
            this.active = active;
            if (this.container) {
                this.container.classList.toggle('is-hidden', !active);
            }
            if (active) {
                this.map?.resize();
                if (this.map?.getZoom() < 5 && this.projection === 'globe') this._startSpin();
            } else {
                this.clearProvinceSelection();
                this.popup?.remove();
                this._stopSpin();
            }
        }

        flyTo(lat, lon, zoom = 8) {
            this._stopSpin();
            this.map?.flyTo({ center: [lon, lat], zoom, duration: 1500 });
        }
    }

    window.pointInGeometry = pointInGeometry;
    window.renderProvincePopupHtml = renderProvincePopupHtml;
    window.MapboxGlobeController = new MapboxGlobeController();
})();
