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

    class MapboxGlobeController {
        map = null;
        container = null;
        active = false;
        spinning = true;
        interacting = false;
        ready = false;
        selectedProvinceCode = '';
        resumeTimer = null;
        spinInterval = null;
        provincesGeoJson = null;

        async init(container) {
            if (this.map) return this.map;
            this.container = container;
            const token = window.mapboxAccessToken;
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
                zoom: 3.2,
                minZoom: 1,
                maxZoom: 18,
                attributionControl: { compact: true },
            });

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
            });

            map.on('movestart', () => {
                this.interacting = true;
                this._stopSpin();
            });

            map.on('moveend', () => {
                clearTimeout(this.resumeTimer);
                this.resumeTimer = setTimeout(() => {
                    this.interacting = false;
                    if (this.spinning && this.active && map.getZoom() < 5) {
                        this._startSpin();
                    }
                }, 1000);
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

            this._installProvinceLayers();
            this._installIslandLayers();
            this._installStationLayers();
        }

        _installProvinceLayers() {
            const map = this.map;
            map.addSource('vietnam-provinces', {
                type: 'geojson',
                data: this.provincesGeoJson || '/api/public/vietnam-provinces-geojson',
            });

            map.addLayer({
                id: 'vietnam-provinces-fill',
                type: 'fill',
                source: 'vietnam-provinces',
                paint: { 'fill-color': '#38bdf8', 'fill-opacity': 0.04 },
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
                paint: { 'fill-color': '#0ea5e9', 'fill-opacity': 0.16 },
            });

            map.addLayer({
                id: 'vietnam-province-selected-line',
                type: 'line',
                source: 'vietnam-provinces',
                filter: selFilter,
                paint: { 'line-color': '#fbbf24', 'line-width': 3.5, 'line-opacity': 1 },
            });

            map.on('click', 'vietnam-provinces-fill', (e) => {
                const feature = e.features?.[0];
                if (!feature?.properties) return;
                const p = feature.properties;
                this.selectProvince(p.code);
            });

            map.on('mouseenter', 'vietnam-provinces-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
            map.on('mouseleave', 'vietnam-provinces-fill', () => { map.getCanvas().style.cursor = ''; });
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
        }

        _installStationLayers() {
            const map = this.map;
            const stations = window.allStations || [];
            map.addSource('station-pins', {
                type: 'geojson',
                data: createStationGeoJson(stations),
            });

            map.addLayer({
                id: 'station-pins-glow',
                type: 'circle',
                source: 'station-pins',
                paint: {
                    'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 8, 8, 14],
                    'circle-color': ['get', 'color'],
                    'circle-opacity': 0.25,
                },
            });

            map.addLayer({
                id: 'station-pins-circle',
                type: 'circle',
                source: 'station-pins',
                paint: {
                    'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 4, 8, 7],
                    'circle-color': ['get', 'color'],
                    'circle-stroke-color': '#ffffff',
                    'circle-stroke-width': 2,
                },
            });

            map.addLayer({
                id: 'station-pins-label',
                type: 'symbol',
                source: 'station-pins',
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

            map.on('click', 'station-pins-circle', (e) => {
                const stationId = e.features?.[0]?.properties?.id;
                if (stationId && typeof window.selectStation === 'function') {
                    void window.selectStation(stationId);
                }
            });

            map.on('mouseenter', 'station-pins-circle', () => { map.getCanvas().style.cursor = 'pointer'; });
            map.on('mouseleave', 'station-pins-circle', () => { map.getCanvas().style.cursor = ''; });
        }

        selectProvince(code) {
            this.selectedProvinceCode = String(code || '');
            const filter = ['==', ['to-string', ['get', 'code']], this.selectedProvinceCode];
            this.map?.setFilter?.('vietnam-province-selected-fill', filter);
            this.map?.setFilter?.('vietnam-province-selected-line', filter);
        }

        updateStations(stations) {
            const source = this.map?.getSource?.('station-pins');
            source?.setData?.(createStationGeoJson(stations));
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
            if (!this.spinning || !this.active || !this.map) return;
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

        setActive(active) {
            this.active = active;
            if (this.container) {
                this.container.classList.toggle('is-hidden', !active);
            }
            if (active) {
                this.map?.resize();
                if (this.map?.getZoom() < 5) this._startSpin();
            } else {
                this._stopSpin();
            }
        }

        flyTo(lat, lon, zoom = 8) {
            this._stopSpin();
            this.map?.flyTo({ center: [lon, lat], zoom, duration: 1500 });
        }
    }

    window.MapboxGlobeController = new MapboxGlobeController();
})();
