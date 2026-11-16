// =====================================================
// OTHER FUNCTIONS
// =====================================================

function switchMapTiles() {
    if (!map) return;
    if (currentTileLayer) {
        map.removeLayer(currentTileLayer);
    }
    currentTileLayer = L.tileLayer(MAP_BASEMAPS[activeBasemap].url, { ...TILE_OPTIONS.light, attribution: '© Google Maps' });
    const layer = currentTileLayer;
    const status = document.getElementById('basemap-status');
    if (status) status.textContent = `Đang tải ${MAP_BASEMAPS[activeBasemap].label.toLowerCase()}…`;
    let failed = false;
    layer.on('tileerror', () => {
        failed = true;
        if (layer === currentTileLayer && status) status.textContent = 'Một số ô nền chưa tải được. Thử đổi nền hoặc tải lại.';
    });
    layer.on('load', () => {
        if (layer === currentTileLayer && status && !failed) status.textContent = MAP_BASEMAPS[activeBasemap].label;
    });
    layer.addTo(map);
    layer.bringToBack();
}

function createStationClusterGroup() {
    return L.layerGroup();
}

let projectMapGroups = [];
let projectOverviewInitialized = false;
let projectDashboardViewer = null;
let projectDashboardTrigger = null;
let projectDashboardRequest = 0;
let projectDashboardDemRequest = 0;

function ensureProjectDashboard() {
    let panel = document.getElementById('project-dashboard');
    if (panel) return panel;
    document.body.insertAdjacentHTML('beforeend', `
        <aside class="project-dashboard-panel" id="project-dashboard" role="dialog" aria-modal="false" aria-label="Bảng điều khiển dự án" aria-hidden="true" inert>
            <header class="project-dashboard-header">
                <div>
                    <p class="project-dashboard-eyebrow">Tổng quan dự án</p>
                    <h2 id="project-dashboard-name"></h2>
                    <p class="project-dashboard-location" id="project-dashboard-location"></p>
                </div>
                <button type="button" class="project-dashboard-close" id="project-dashboard-close" aria-label="Đóng bảng dự án"><i class="bi bi-x-lg" aria-hidden="true"></i></button>
            </header>
            <div class="project-dashboard-content">
                <div class="project-dashboard-summary">
                    <span><strong id="project-dashboard-stations">0</strong> trạm</span>
                    <span id="project-dashboard-dem-badge">Chưa có mô hình DEM</span>
                </div>
                <section class="project-dashboard-terrain" aria-labelledby="project-dashboard-terrain-title">
                    <div class="project-dashboard-terrain-head">
                        <div><h3 id="project-dashboard-terrain-title">Địa hình số của công trình</h3><p id="project-dashboard-terrain-description">DEM · EPSG:32648 · ô lưới theo file</p></div>
                        <select class="project-dashboard-dem-select" id="project-dashboard-dem-select" aria-label="Chọn khu địa hình" hidden></select>
                    </div>
                    <div class="project-dashboard-terrain-body">
                        <div class="project-dashboard-message" id="project-dashboard-message" role="status" aria-live="polite"><i class="bi bi-mountains" aria-hidden="true"></i><span></span></div>
                        <div class="dem-grid-viewport project-dashboard-dem-viewport" id="project-dashboard-viewport" hidden><canvas id="project-dashboard-canvas" aria-label="Mô hình địa hình số của dự án"></canvas></div>
                        <div class="project-dashboard-controls">
                            <p>Kéo để xoay · cuộn để zoom mô hình 3D</p>
                            <div class="dem-grid-toolbar" aria-label="Điều khiển mô hình DEM">
                                <button type="button" data-dem-action="out" aria-label="Thu nhỏ mô hình">−</button>
                                <button type="button" data-dem-action="fit" aria-label="Vừa khung mô hình"><i class="bi bi-arrows-angle-contract" aria-hidden="true"></i></button>
                                <button type="button" data-dem-action="in" aria-label="Phóng to mô hình">+</button>
                            </div>
                        </div>
                        <p class="project-dashboard-status" id="project-dashboard-status" aria-live="polite"></p>
                    </div>
                </section>
            </div>
        </aside>`);
    panel = document.getElementById('project-dashboard');
    panel.querySelector('#project-dashboard-close').addEventListener('click', closeProjectDashboard);
    panel.querySelectorAll('[data-dem-action]').forEach(button => button.addEventListener('click', () => {
        const action = button.dataset.demAction;
        if (action === 'in') projectDashboardViewer?.zoomIn();
        else if (action === 'out') projectDashboardViewer?.zoomOut();
        else projectDashboardViewer?.fit();
    }));
    panel.addEventListener('keydown', event => {
        if (event.key === 'Escape') closeProjectDashboard();
    });
    return panel;
}

function closeProjectDashboard() {
    projectDashboardRequest += 1;
    const panel = document.getElementById('project-dashboard');
    if (!panel) return;
    panel.classList.remove('is-open');
    panel.setAttribute('aria-hidden', 'true');
    panel.inert = true;
    projectDashboardViewer?.destroy();
    projectDashboardViewer = null;
    projectDashboardTrigger?.focus?.({ preventScroll: true });
    projectDashboardTrigger = null;
}

async function openProjectDashboard(project, center, trigger) {
    const requestId = ++projectDashboardRequest;
    const leafletMap = getLeafletMap();
    const panel = ensureProjectDashboard();
    projectDashboardTrigger = trigger;
    projectDashboardViewer?.destroy();
    projectDashboardViewer = null;
    const location = project.location;
    const dems = Array.isArray(project.dems) ? project.dems : [];
    document.getElementById('project-dashboard-name').textContent = project.name || 'Dự án';
    document.getElementById('project-dashboard-location').textContent = location?.address
        ? `${location.address} · ${Number(center[0]).toFixed(6)}, ${Number(center[1]).toFixed(6)}`
        : `Vị trí dự án · ${Number(center[0]).toFixed(6)}, ${Number(center[1]).toFixed(6)}`;
    const stationCount = allStations.filter(station => String(station.project_id) === String(project.id)).length;
    document.getElementById('project-dashboard-stations').textContent = String(stationCount);
    document.getElementById('project-dashboard-dem-badge').textContent = dems.length
        ? `${dems.length} khu địa hình` : 'Chưa có mô hình DEM';
    const message = document.getElementById('project-dashboard-message');
    const messageText = message.querySelector('span');
    const viewport = document.getElementById('project-dashboard-viewport');
    const status = document.getElementById('project-dashboard-status');
    viewport.hidden = true;
    message.hidden = false;
    status.textContent = '';
    messageText.textContent = dems.length ? 'Đang tải mô hình địa hình…' : 'Dự án này chưa có DEM. Tải mô hình lên trong trang Quản lý dự án để xem địa hình tại đây.';
    const demSelect = document.getElementById('project-dashboard-dem-select');
    demSelect.replaceChildren(...dems.map(model => {
        const option = document.createElement('option');
        option.value = model.id;
        option.textContent = model.name;
        return option;
    }));
    demSelect.hidden = dems.length < 2;
    demSelect.onchange = () => loadProjectDashboardDem(project, demSelect.value, requestId);

    const currentZoom = leafletMap.getZoom();
    const targetZoom = Math.max(currentZoom, 14);
    const animate = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const moved = Math.abs(leafletMap.getCenter().lat - center[0]) > 0.00001
        || Math.abs(leafletMap.getCenter().lng - center[1]) > 0.00001
        || Math.abs(currentZoom - targetZoom) > 0.01;
    if (moved && animate) {
        await new Promise(resolve => {
            const finish = () => resolve();
            leafletMap.once('moveend', finish);
            leafletMap.flyTo(center, targetZoom, { animate: true, duration: 1.05 });
            window.setTimeout(finish, 1300);
        });
    } else if (moved) leafletMap.setView(center, targetZoom, { animate: false });
    if (requestId !== projectDashboardRequest) return;

    panel.inert = false;
    panel.setAttribute('aria-hidden', 'false');
    panel.classList.add('is-open');
    panel.querySelector('#project-dashboard-close').focus({ preventScroll: true });
    if (window.innerWidth > 700) {
        leafletMap.panBy([Math.min(panel.getBoundingClientRect().width * 0.22, 160), 0], { animate, duration: 0.3 });
    }
    if (dems.length) await loadProjectDashboardDem(project, dems[0].id, requestId);
}

async function loadProjectDashboardDem(project, demId, parentRequest) {
    const requestId = ++projectDashboardDemRequest;
    const panel = document.getElementById('project-dashboard');
    const message = document.getElementById('project-dashboard-message');
    const messageText = message.querySelector('span');
    const viewport = document.getElementById('project-dashboard-viewport');
    const status = document.getElementById('project-dashboard-status');
    const model = (project.dems || []).find(item => item.id === demId);
    document.getElementById('project-dashboard-terrain-description').textContent = `${model?.name || 'DEM'} · EPSG:32648 · mô hình địa hình 3D`;
    projectDashboardViewer?.destroy();
    projectDashboardViewer = null;
    viewport.hidden = true;
    message.hidden = false;
    message.querySelector('i').className = 'bi bi-mountains';
    messageText.textContent = 'Đang tải mô hình địa hình…';
    status.textContent = '';
    try {
        const response = window.authManager?.isAuthenticated?.()
            ? await window.authManager.apiFetch(`/api/projects/${project.id}/dems/${encodeURIComponent(demId)}`)
            : await fetch(`/api/projects/${project.id}/dems/${encodeURIComponent(demId)}`);
        if (!response.ok) throw new Error(response.status === 404 ? 'Không tìm thấy file DEM của khu địa hình.' : `Không tải được mô hình (HTTP ${response.status}).`);
        const grid = window.DemGrid.parse(await response.text());
        if (parentRequest !== projectDashboardRequest || requestId !== projectDashboardDemRequest || !panel.classList.contains('is-open')) return;
        const viewer = await window.DemGrid.mount(document.getElementById('project-dashboard-canvas'), grid);
        if (parentRequest !== projectDashboardRequest || requestId !== projectDashboardDemRequest || !panel.classList.contains('is-open')) {
            viewer.destroy();
            return;
        }
        projectDashboardViewer = viewer;
        viewport.hidden = false;
        message.hidden = true;
        status.textContent = `${grid.ncols} × ${grid.nrows} ô · độ cao ${grid.min.toFixed(1)}–${grid.max.toFixed(1)} m · ô ${grid.cellsize} m`;
    } catch (error) {
        if (parentRequest !== projectDashboardRequest || requestId !== projectDashboardDemRequest) return;
        message.querySelector('i').className = 'bi bi-exclamation-circle';
        messageText.textContent = error.message || 'Không thể đọc mô hình DEM.';
        status.textContent = 'Kiểm tra file ESRI ASCII Grid (.asc) và thử tải lại.';
    }
}

function getProjectMapPadding() {
    const leafletMap = getLeafletMap();
    const size = leafletMap.getSize();
    const topBar = document.querySelector('.top-navbar');
    const bottomNav = document.getElementById('map-bottom-nav');
    const mapRect = leafletMap.getContainer().getBoundingClientRect();
    const top = topBar ? Math.max(0, topBar.getBoundingClientRect().bottom - mapRect.top) : 0;
    const bottom = bottomNav && getComputedStyle(bottomNav).display !== 'none'
        ? Math.max(0, mapRect.bottom - bottomNav.getBoundingClientRect().top) : 0;
    return {
        paddingTopLeft: [Math.min(60, size.x / 8), Math.min(top + 40, size.y / 3)],
        paddingBottomRight: [Math.min(90, size.x / 5), Math.min(bottom + 60, size.y / 3)],
    };
}

function refreshProjectMapVisibility() {
    const leafletMap = getLeafletMap();
    if (!leafletMap || !stationClusterGroup) return;
    const zoom = leafletMap.getZoom();
    const visibleStations = new Set();
    const detailedProjects = new Set();
    const padding = getProjectMapPadding();
    projectMapGroups.forEach(group => {
        const detailZoom = Math.min(13, leafletMap.getBoundsZoom(group.bounds, false, [
            padding.paddingTopLeft[0] + padding.paddingBottomRight[0],
            padding.paddingTopLeft[1] + padding.paddingBottomRight[1],
        ]));
        const detailed = group.stationIds.length > 0 && zoom >= detailZoom;
        if (detailed) {
            detailedProjects.add(String(group.id));
            group.stationIds.forEach(id => visibleStations.add(String(id)));
        }
        if (showStationMarkers && !detailed) {
            if (!leafletMap.hasLayer(group.marker)) group.marker.addTo(leafletMap);
        } else {
            leafletMap.removeLayer(group.marker);
        }
    });
    allStations.forEach(station => {
        const marker = markers[station.id];
        if (!marker) return;
        const detailed = visibleStations.has(String(station.id)) || zoom >= 13;
        if (showStationMarkers && detailed) stationClusterGroup.addLayer(marker);
        else stationClusterGroup.removeLayer(marker);
    });
    clusterPolylines.forEach(line => {
        if (showStationMarkers && (detailedProjects.has(String(line.projectId)) || zoom >= 13)) {
            if (!leafletMap.hasLayer(line)) line.addTo(leafletMap);
        } else leafletMap.removeLayer(line);
    });
    projectDetailsVisible = zoom >= 13 || detailedProjects.size > 0;
    Object.values(corsBaseMarkers).forEach(marker => {
        if (showCorsBaseMarkers && projectDetailsVisible && showStationMarkers) {
            if (!leafletMap.hasLayer(marker)) marker.addTo(leafletMap);
        } else leafletMap.removeLayer(marker);
    });
}

function _computeDemCenter(dems) {
    if (!Array.isArray(dems) || dems.length === 0) return null;
    const dem = dems[0];
    if (dem?.xllcorner != null && dem?.yllcorner != null && dem?.ncols && dem?.nrows && dem?.cellsize && window.DemGrid?.utm48ToWgs84) {
        const easting = Number(dem.xllcorner) + (Number(dem.ncols) * Number(dem.cellsize)) / 2;
        const northing = Number(dem.yllcorner) + (Number(dem.nrows) * Number(dem.cellsize)) / 2;
        const wgs = window.DemGrid.utm48ToWgs84(easting, northing);
        if (Number.isFinite(wgs.lat) && Number.isFinite(wgs.lon)) {
            return [wgs.lat, wgs.lon];
        }
    }
    return null;
}

function _bindProjectMarkerEvents(marker, project, bounds, center, stations, name) {
    marker.on('tooltipopen', () => {
        const leafletMap = getLeafletMap();
        const popup = marker.getTooltip();
        const x = leafletMap.latLngToContainerPoint(marker.getLatLng()).x;
        const halfWidth = popup.getElement().offsetWidth / 2;
        const shift = Math.max(12 + halfWidth - x, Math.min(0, leafletMap.getSize().x - 12 - halfWidth - x));
        popup.options.offset = [shift, -60];
        popup.update();
    });
    marker.on('add', () => {
        marker.getElement()?.setAttribute('aria-label', `${name}: xem toàn bộ ${stations.length} trạm cảm biến`);
    });
    marker.on('keydown', event => {
        if (!['Enter', ' '].includes(event.originalEvent.key)) return;
        L.DomEvent.stop(event.originalEvent);
        marker.fire('click');
    });
    marker.on('click', () => {
        if (!Array.isArray(project.dems) || project.dems.length === 0) {
            const leafletMap = getLeafletMap();
            leafletMap.flyToBounds(bounds, {
                ...getProjectMapPadding(),
                maxZoom: 16,
                animate: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
                duration: 1.2,
            });
            return;
        }
        setStationListSidebarOpen(document.getElementById('station-list-sidebar'), false);
        setDetailSidebarOpen(document.getElementById('detail-sidebar'), false);
        setGnssAdvancedPanelOpen(document.getElementById('gnss-advanced-sidepanel'), false);
        setChartsPanelOpen(document.getElementById('charts-panel'), false);
        document.getElementById('longterm-overlay')?.classList.remove('active');
        void openProjectDashboard(project, center, marker.getElement());
    });
}

function createProjectMapGroup(project) {
    const stations = allStations.filter(station => (
        String(station.project_id) === String(project.id) && hasValidLatLon(station.location)
    ));
    const points = stations.map(station => [Number(station.location.lat), Number(station.location.lon)]);
    const dems = Array.isArray(project.dems) ? project.dems : [];
    const demCenter = (!points.length && !hasValidLatLon(project.location)) ? _computeDemCenter(dems) : null;

    if (!points.length && !hasValidLatLon(project.location) && !demCenter) return null;
    const center = hasValidLatLon(project.location)
        ? [Number(project.location.lat), Number(project.location.lon)]
        : (demCenter || points.reduce((sum, point) => [sum[0] + point[0], sum[1] + point[1]], [0, 0])
            .map(value => value / points.length));
    const bounds = L.latLngBounds(points.length ? points : [center]);
    const name = String(project.name || 'Dự án');
    const tooltip = document.createElement('span');
    const title = document.createElement('strong');
    title.textContent = name;
    const hint = document.createElement('span');
    hint.textContent = stations.length ? `${stations.length} trạm · Bấm để mở dashboard` : 'Mô hình DEM 3D · Bấm để xem địa hình';
    tooltip.append(title, hint);
    const marker = L.marker(center, {
        title: name,
        alt: `${name}: xem toàn bộ ${stations.length} trạm cảm biến`,
        icon: L.divIcon({
            className: 'project-map-marker',
            html: `<span class="project-map-halo" aria-hidden="true"></span><span class="project-map-point" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V8l8-4 8 4v12H4Z"/><path d="M9 20v-5h6v5M8 10h.01M12 10h.01M16 10h.01"/></svg></span><span class="project-map-count" aria-hidden="true">${stations.length || (dems.length ? '3D' : 0)}</span>`,
            iconSize: [52, 60],
            iconAnchor: [26, 54],
        }),
    }).bindTooltip(tooltip, { direction: 'top', offset: [0, -60], opacity: 1, className: 'project-map-tooltip' });

    _bindProjectMarkerEvents(marker, project, bounds, center, stations, name);
    return { id: project.id, marker, bounds, stationIds: stations.map(station => station.id) };
}

function initMap() {
    try {
        projectOverviewInitialized = false;
        map = L.map('map', {
            zoomControl: false,
            attributionControl: false,
            maxZoom: 18,
            preferCanvas: true,
            fadeAnimation: false,
            markerZoomAnimation: false,
            wheelDebounceTime: 40,
            wheelPxPerZoomLevel: 90,
            inertia: true,
            inertiaDeceleration: 3000,
        }).setView([16.047079, 108.206230], 6);
        window.map = map;

        map.on('movestart zoomstart', beginMapInteraction);
        map.on('movestart', () => { projectOverviewInitialized = true; });
        map.on('moveend zoomend', endMapInteraction);
        map.on('zoomend resize', refreshProjectMapVisibility);

        stationClusterGroup = createStationClusterGroup();
        map.addLayer(stationClusterGroup);

        // Leaflet resolves path clicks by pane stacking. Aggregate project
        // edges must stay below ordinary cluster edges when their geometry
        // overlaps, otherwise the aggregate hitbox steals every click.
        const totalClusterPane = map.createPane('gnssTotalClusterPane');
        totalClusterPane.style.zIndex = '390';
        const normalClusterPane = map.createPane('gnssNormalClusterPane');
        normalClusterPane.style.zIndex = '410';



        // Keep the selected basemap when UI theme changes.
        switchMapTiles();

        console.log('✅ [MAP] Leaflet map initialized');
    } catch (error) {
        console.error('❌ [MAP] Failed to initialize map:', error);
    }
}

function getClusterStationTokens(clusterConfig) {
    if (Array.isArray(clusterConfig)) return clusterConfig;
    if (clusterConfig && Array.isArray(clusterConfig.stations)) return clusterConfig.stations;
    return [];
}

function findStationByClusterToken(token) {
    const tokenText = String(token).trim();
    return allStations.find(station => (
        String(station.id) === tokenText ||
        String(station.station_code || '').trim() === tokenText ||
        String(station.name || '').trim() === tokenText
    ));
}

function hasValidLatLon(location) {
    return location?.lat != null && location?.lon != null
        && typeof location.lat !== 'boolean' && typeof location.lon !== 'boolean'
        && String(location.lat).trim() !== '' && String(location.lon).trim() !== ''
        && Number.isFinite(Number(location.lat)) && Number.isFinite(Number(location.lon))
        && Math.abs(Number(location.lat)) <= 90 && Math.abs(Number(location.lon)) <= 180
        && !(Number(location.lat) === 0 && Number(location.lon) === 0);
}

function isClusterSubset(subset, superset) {
    if (!superset?.isTotal || superset === subset) return false;
    for (const id of subset.stationIds) {
        if (!superset.stationIdSet?.has(Number(id))) return false;
    }
    return true;
}

function _renderClusterSegment(cluster, proj, drawableClusters, colors, colorIdx, leafletMap) {
    const { isTotal, latlngs } = cluster;
    if (latlngs.length < 2) return colorIdx;
    const multiLatLngs = [];
    for (let i = 0; i < latlngs.length; i++) {
        for (let j = i + 1; j < latlngs.length; j++) {
            multiLatLngs.push([latlngs[i], latlngs[j]]);
        }
    }
    const polyline = L.polyline(multiLatLngs, {
        color: isTotal ? '#f43f5e' : colors[colorIdx % colors.length],
        weight: isTotal ? 4 : 3,
        opacity: isTotal ? 0.15 : 0.7,
        dashArray: isTotal ? '10, 20' : '5, 10',
        pane: isTotal ? 'gnssTotalClusterPane' : 'gnssNormalClusterPane'
    });
    const hitbox = L.polyline(multiLatLngs, {
        color: 'transparent',
        weight: 20,
        opacity: 0,
        pane: isTotal ? 'gnssTotalClusterPane' : 'gnssNormalClusterPane'
    });
    polyline.projectId = proj.id;
    hitbox.projectId = proj.id;

    const clickHandler = (e) => {
        const choices = isTotal ? [cluster] : [
            cluster,
            ...drawableClusters.filter(candidate => isClusterSubset(cluster, candidate)),
        ];
        showAdjustmentPopup(proj.id, proj.name, choices, e.latlng);
    };

    polyline.on('click', clickHandler);
    hitbox.on('click', clickHandler);

    if (leafletMap) {
        polyline.addTo(leafletMap);
        hitbox.addTo(leafletMap);
    }
    clusterPolylines.push(polyline, hitbox);
    return isTotal ? colorIdx : colorIdx + 1;
}

async function loadProjectsAndClusters() {
    if (mapInteractionActive) {
        pendingProjectsReload = true;
        return;
    }
    if (projectsFetchInFlight) {
        pendingProjectsReload = true;
        return;
    }
    projectsFetchInFlight = true;
    try {
        const res = window.authManager?.isAuthenticated?.()
            ? await window.authManager.apiFetch('/api/projects')
            : await fetch('/api/projects');
        if (!res.ok) return;
        const projects = await res.json();
        if (mapInteractionActive) {
            pendingProjectsReload = true;
            return;
        }
        const nextRenderSignature = JSON.stringify({
            projects: projects.map(project => ({
                id: project.id,
                name: project.name,
                location: project.location,
                has_dem: project.has_dem,
                dems: project.dems,
                gnss_clusters: project.gnss_clusters,
            })),
            stations: allStations.map(station => [
                station.id,
                station.project_id,
                station.station_code,
                station.name,
                station.location?.lat,
                station.location?.lon,
            ]),
        });
        if (nextRenderSignature === clusterRenderSignature) return;
        
        const leafletMap = getLeafletMap();
        if (leafletMap) {
            clusterPolylines.forEach(p => leafletMap.removeLayer(p));
            projectMapGroups.forEach(group => leafletMap.removeLayer(group.marker));
        }
        clusterPolylines = [];
        projectMapGroups = projects.map(createProjectMapGroup).filter(Boolean);
        
        const colors = ['#10b981', '#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b'];
        let colorIdx = 0;

        projects.forEach(proj => {
            if (!proj.gnss_clusters || !Array.isArray(proj.gnss_clusters)) return;
            
            // Also render totals first for deterministic ordering in Canvas mode.
            const orderedClusters = [...proj.gnss_clusters].sort((left, right) => (
                Number(left?.cluster_type !== 'total') - Number(right?.cluster_type !== 'total')
            ));
            const drawableClusters = orderedClusters.map(c => {
                const stationTokens = getClusterStationTokens(c);
                const clusterMembers = stationTokens
                    .map(findStationByClusterToken)
                    .filter(station => station && hasValidLatLon(station.location));
                const stationIds = clusterMembers.map(station => station.id);
                const isTotal = c.cluster_type === 'total';
                const defaultLabel = isTotal ? 'Cụm tổng' : 'Cụm quan trắc';
                return {
                    config: c,
                    isTotal,
                    stationIds,
                    stationIdSet: new Set(stationIds.map(Number)),
                    stationNames: clusterMembers.map(st => st.name || st.station_code || String(st.id)),
                    latlngs: clusterMembers.map(st => [Number(st.location.lat), Number(st.location.lon)]),
                    label: String(c.name || defaultLabel),
                };
            }).filter(cluster => cluster.latlngs.length >= 2);

            drawableClusters.forEach(cluster => {
                colorIdx = _renderClusterSegment(cluster, proj, drawableClusters, colors, colorIdx, leafletMap);
            });
        });
        if (!projectOverviewInitialized && projectMapGroups.length && leafletMap) {
            projectOverviewInitialized = true;
            leafletMap.fitBounds(L.latLngBounds(projectMapGroups.map(group => group.marker.getLatLng())), {
                ...getProjectMapPadding(), maxZoom: 8, animate: false,
            });
        }
        refreshProjectMapVisibility();
        clusterRenderSignature = nextRenderSignature;
    } catch (e) {
        console.error('Error loading projects and clusters:', e);
    } finally {
        projectsFetchInFlight = false;
        if (pendingProjectsReload && !mapInteractionActive) {
            pendingProjectsReload = false;
            setTimeout(loadProjectsAndClusters, 0);
        }
    }
}

function showAdjustmentPopup(projectId, projectName, clusters, latlng) {
    const leafletMap = getLeafletMap();
    if (!leafletMap) return;

    const popupContent = document.createElement('div');
    popupContent.className = 'text-center p-2';
    const title = document.createElement('h6');
    title.className = 'mb-2 fw-bold';
    title.style.color = '#10b981';
    title.textContent = projectName;
    popupContent.appendChild(title);

    const hint = document.createElement('div');
    hint.className = 'small mb-2 text-secondary';
    hint.textContent = clusters.length > 1
        ? 'Đường này thuộc nhiều cụm. Chọn cụm cần bình sai:'
        : 'Chọn để bắt đầu bình sai:';
    popupContent.appendChild(hint);

    const actions = document.createElement('div');
    actions.className = 'd-grid gap-2';
    clusters.forEach(cluster => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `btn btn-sm w-100 ${cluster.isTotal ? 'btn-outline-danger' : 'btn-success'}`;
        button.textContent = `${cluster.isTotal ? 'Cụm tổng' : 'Cụm'} · ${cluster.label}`;
        button.title = cluster.stationNames.join(', ');
        button.addEventListener('click', () => {
            leafletMap.closePopup(popup);
            requestGnssAdjustment(projectId, cluster.stationIds);
        });
        actions.appendChild(button);
    });
    popupContent.appendChild(actions);

    const popup = L.popup()
        .setLatLng(latlng)
        .setContent(popupContent)
        .openOn(leafletMap);
}

async function loadStations() {
    if (document.hidden) return;
    if (mapInteractionActive) {
        pendingStationsReload = true;
        return;
    }
    if (stationsFetchInFlight) {
        pendingStationsReload = true;
        return;
    }
    stationsFetchInFlight = true;
    try {
        const res = window.authManager?.isAuthenticated?.()
            ? await window.authManager.apiFetch('/api/stations')
            : await fetch('/api/stations');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const stations = await res.json();
        if (mapInteractionActive) {
            pendingStationsReload = true;
            return;
        }
        allStations = stations;
        if (typeof window !== 'undefined') window.allStations = stations;
        refreshHeatmapData();

        const validStationIds = new Set(stations.filter(station => hasValidLatLon(station.location)).map(station => String(station.id)));
        Object.entries(markers).forEach(([id, marker]) => {
            if (validStationIds.has(id)) return;
            stationClusterGroup?.removeLayer(marker);
            delete markers[id];
            delete stationStateCache[id];
            delete markerAlertState[id];
        });
        stations.forEach(station => {
            if (hasValidLatLon(station.location)) {
                updateMarker(station);
            }

            // ✅ Sync marker blinking state từ risk_level API (restore sau reload)
            const _isAlertingRisk = normalizeRiskLevel(station.risk_level, station.status) === 'CRITICAL'
                && station.status !== 'offline';
            if (_isAlertingRisk && !markerAlertState[station.id]) {
                setMarkerAlert(station.id, true);
            } else if (!_isAlertingRisk && markerAlertState[station.id]) {
                clearMarkerAlert(station.id);
            }

            // ✅ THÊM: Nếu trạm đang xem bị đổi status (ví dụ offline/online, hoặc đổi risk_level)
            if (currentStationData?.id === station.id) {
                if (currentStationData.status !== station.status || currentStationData.risk_level !== station.risk_level) {
                    console.log(`🔄 [STATE] Station ${station.id} changed state: ${currentStationData.status}->${station.status}, updating UI...`);
                    currentStationData.status = station.status;
                    currentStationData.risk_level = station.risk_level;
                    if (currentStationData.risk_assessment) {
                        currentStationData.risk_assessment.overall_risk = station.risk_level;
                    }
                    updateSidebarUI(currentStationData);
                }
            }
        });

        renderStationList(stations);
        ensureGlobalAlertBannerFromStations(stations);
        refreshProjectMapVisibility();
        void loadProjectsAndClusters();

    } catch (e) {
        console.error('❌ [MAP] Error loading stations:', e);
    } finally {
        stationsFetchInFlight = false;
        if (pendingStationsReload && !mapInteractionActive) {
            pendingStationsReload = false;
            setTimeout(loadStations, 0);
        }
    }
}

function ensureGlobalAlertBannerFromStations(stations) {
    const banner = document.getElementById('alert-banner');
    if (!banner || banner.classList.contains('show')) return;
    if (!Array.isArray(stations) || stations.length === 0) return;

    const candidates = stations
        .map(st => {
            const riskUi = getRiskPresentation(st.risk_level, st.status);
            return { station: st, riskUi };
        })
        .filter(item => item.riskUi.normalized === 'CRITICAL' || item.riskUi.normalized === 'MEDIUM')
        .sort((a, b) => (a.riskUi.normalized === 'CRITICAL' ? -1 : 1));

    if (candidates.length === 0) return;

    const chosen = candidates[0];
    const stationId = chosen.station.id;
    const snoozeUntil = Number(alertBannerSnoozeUntil[stationId] || 0);
    if (Date.now() < snoozeUntil) return;
    if (isBannerSuppressed(stationId)) return;

    const isCritical = chosen.riskUi.normalized === 'CRITICAL';
    const level = isCritical ? 'CRITICAL' : 'WARNING';
    const fallbackMessage = isCritical
        ? 'Critical risk detected from station state. Press Track to monitor now.'
        : 'Warning risk detected from station state. Press Track to monitor now.';
    const cachedAlert = latestAlertByStation[stationId];
    const candidateAlert = cachedAlert ? { ...cachedAlert, level } : {
        station_id: stationId,
        level,
        message: fallbackMessage
    };
    const candidateKey = buildAlertKey(candidateAlert);
    if (candidateKey && acknowledgedAlertKeyByStation[stationId] === candidateKey) return;

    showAlertBanner(candidateAlert, { silent: true });
}

// ✅ Silently re-fetch current station detail to refresh per-sensor is_online status
async function refreshCurrentStationDetail() {
    if (!currentStationData) return;
    const sidebar = document.getElementById('detail-sidebar');
    if (!sidebar?.classList.contains('active')) return;

    try {
        const res = window.authManager?.isAuthenticated?.()
            ? await window.authManager.apiFetch(`/api/stations/${currentStationData.id}/detail?include_history=false`)
            : await fetch(`/api/stations/${currentStationData.id}/detail?include_history=false`);
        if (!res.ok) return;
        const data = await res.json();
        const stationId = data.id;
        const apiImuTs = Number(data.sensors?.imu?.latest_timestamp || 0);
        const wsImuTs = Number(latestRealtimeSensorTs[`${stationId}_imu`] || 0);
        console.debug(`🔍 [IMU][REFRESH] station=${stationId} api_ts=${apiImuTs || 'none'} ws_ts=${wsImuTs || 'none'}`);
        currentStationData = data;
        stationDetailCache.set(Number(stationId), { data, loadedAt: Date.now() });
        updateSidebarUI(currentStationData);
        console.log(`🔄 [MAP] Refreshed detail for station ${currentStationData.id}`);
    } catch (e) {
        console.warn('⚠️ [MAP] Silent detail refresh failed:', e);
    }
}

function renderStationList(stations) {
    const container = document.getElementById('station-list-container');
    if (!container) return;

    if (stations.length === 0) {
        container.innerHTML = `
                    <div class="text-center text-muted mt-4">
                        <i class="bi bi-inbox fs-1"></i>
                        <p class="mt-2">Chưa có trạm nào</p>
                    </div>
                `;
        return;
    }

    const currentIds = new Set(stations.map(st => st.id.toString()));
    
    Array.from(container.children).forEach(child => {
        if (child.dataset?.stationId && !currentIds.has(child.dataset.stationId)) {
            child.remove();
        }
    });

    const emptyPlaceholder = container.querySelector('.text-center.text-muted');
    if (emptyPlaceholder) emptyPlaceholder.remove();

    stations.forEach(st => {
        const riskUi = getRiskPresentation(st.risk_level, st.status);
        const badgeClass = getRiskBadgeClass(riskUi.className);
        const riskLabel = getStationListRiskLabel(riskUi.normalized);
        
        let div = container.querySelector(`[data-station-id="${st.id}"]`);
        
        if (div) {
            const badge = div.querySelector('.badge');
            if (badge) {
                const targetClass = `badge station-status ${badgeClass}`;
                if (badge.className !== targetClass) badge.className = targetClass;
                if (badge.textContent.trim() !== riskLabel) badge.textContent = riskLabel;
            }
            div.dataset.state = riskUi.normalized.toLowerCase();
            div.dataset.connection = getStationListConnection(st, riskUi);
            div.setAttribute('aria-label', `${st.name}: ${riskLabel}`);
            const name = div.querySelector('.station-item-name');
            const code = div.querySelector('.station-item-code');
            if (name) name.textContent = st.name;
            if (code) code.textContent = st.station_code || 'Chưa có mã';
        } else {
            div = document.createElement('button');
            div.type = 'button';
            div.className = 'station-item';
            div.dataset.stationId = st.id;
            div.dataset.state = riskUi.normalized.toLowerCase();
            div.dataset.connection = getStationListConnection(st, riskUi);
            div.setAttribute('aria-label', `${st.name}: ${riskLabel}`);
            div.innerHTML = `
                <span class="station-state-mark" aria-hidden="true"><i class="bi bi-broadcast-pin"></i></span>
                <span class="station-item-copy">
                    <strong class="station-item-name">${escapeHtml(st.name)}</strong>
                    <small class="station-item-code">${escapeHtml(st.station_code || 'Chưa có mã')}</small>
                </span>
                <span id="list-badge-${st.id}" class="badge station-status ${badgeClass}">${riskLabel}</span>
                <i class="bi bi-chevron-right station-item-chevron" aria-hidden="true"></i>
            `;
            div.addEventListener('click', () => {
                void selectStation(st.id);
                if (window.innerWidth < 768) {
                    const sidebar = document.getElementById('station-list-sidebar');
                    setStationListSidebarOpen(sidebar, false);
                }
            });
            container.appendChild(div);
        }
    });
    if (typeof filterStations === 'function') {
        filterStations(document.getElementById('search-station')?.value || '');
    }
}

function getStationListRiskLabel(level) {
    return {
        LOW: 'An toàn',
        MEDIUM: 'Cảnh báo',
        CRITICAL: 'Nguy hiểm',
        STALE: 'Mất tín hiệu',
        OFFLINE: 'Ngoại tuyến',
    }[level] || 'An toàn';
}

function getStationListConnection(station, riskUi) {
    if (riskUi.normalized === 'OFFLINE') return 'offline';
    if (riskUi.normalized === 'STALE') return 'stale';
    return String(station.status || '').toLowerCase() === 'offline' ? 'offline' : 'online';
}

function getRiskBadgeClass(level) {
    const classes = {
        'CRITICAL': 'bg-danger',
        'EXTREME': 'bg-danger',
        'MEDIUM': 'bg-warning text-dark',
        'HIGH': 'bg-warning text-dark',
        'WARNING': 'bg-warning text-dark',
        'STALE': 'bg-warning text-dark',
        'LOW': 'bg-success',
        'OFFLINE': 'bg-secondary'
    };
    return classes[level] || 'bg-success';
}

// ✅ BOOST 3: Cache trạng thái marker để tránh vẽ lại không cần thiết
let stationStateCache = {};

function updateMarker(station) {
    if (!hasValidLatLon(station.location)) return;
    const colors = {
        'CRITICAL': '#fa5252',
        'MEDIUM': '#ffd43b',
        'STALE': '#f59e0b',
        'LOW': '#51cf66',
        'OFFLINE': '#6c757d'
    };

    let currentLevel = normalizeRiskLevel(station.risk_level, station.status);
    if (!colors[currentLevel]) currentLevel = 'LOW';

    const color = colors[currentLevel] || '#adb5bd';
    const shouldPulse = currentLevel === 'CRITICAL';

    // ✅ KIỂM TRA CACHE: Nếu trạng thái không đổi thì KHÔNG LÀM GÌ CẢ
    const cacheKey = `${station.id}_${currentLevel}_${station.status}_${station.location.lat}_${station.location.lon}`;
    if (stationStateCache[station.id] === cacheKey) {
        return; // Dữ liệu y hệt cũ -> Bỏ qua, không vẽ lại (Giảm tải CPU)
    }

    // Cập nhật Cache mới
    stationStateCache[station.id] = cacheKey;

    // ✅ Tạo HTML string cho divIcon (giúp Leaflet giữ nguyên class khi re-render)
    const pulseClass = shouldPulse ? ' marker-alert-pulse' : '';
    const iconHtml = `<div class="marker-circle${pulseClass}" style="
                width: 18px; height: 18px; box-sizing: border-box; background: ${color};
                border-radius: 50%; border: 2px solid white;
                box-shadow: 0 0 8px rgba(0,0,0,0.5);
                transition: background 0.3s ease;
            "></div>`;

    if (markers[station.id]) {
        markers[station.id].setLatLng([station.location.lat, station.location.lon]);

        // ✅ Cập nhật icon mới với HTML string (giữ pulse class)
        const newIcon = L.divIcon({
            className: 'custom-map-marker',
            html: iconHtml,
            iconSize: [18, 18],
            iconAnchor: [9, 9]
        });
        markers[station.id].setIcon(newIcon);
    } else {
        const icon = L.divIcon({
            className: 'custom-map-marker',
            html: iconHtml,
            iconSize: [18, 18],
            iconAnchor: [9, 9]
        });

        const marker = L.marker([station.location.lat, station.location.lon], { icon })
            .bindTooltip(station.name, { direction: 'top', offset: [0, -10] });

        if (stationClusterGroup && showStationMarkers && getLeafletMap()?.getZoom() >= 13) {
            stationClusterGroup.addLayer(marker);
        }

        marker.on('click', () => selectStation(station.id));
        markers[station.id] = marker;
    }
}
