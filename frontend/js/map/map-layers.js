// =====================================================
// RESCUE MARKER MANAGEMENT
// =====================================================

function setupMarkerLayerControls() {
    const layerStation = document.getElementById('layer-station');
    const layerRescue = document.getElementById('layer-rescue');
    const layerCors = document.getElementById('layer-cors');
    const layerHeatmap = document.getElementById('layer-heatmap');

    if (layerStation) {
        layerStation.addEventListener('change', () => {
            showStationMarkers = layerStation.checked;
            setMapState({ layers: { stations: showStationMarkers } });
            toggleStationMarkersDisplay();
            updateUIVisibilityBasedOnLayers();
        });
    }

    if (layerRescue) {
        layerRescue.addEventListener('change', () => {
            showRescueMarkers = layerRescue.checked;
            setMapState({ layers: { rescue: showRescueMarkers } });
            toggleRescueMarkersDisplay();
            updateUIVisibilityBasedOnLayers();
        });
    }

    layerCors?.addEventListener('change', () => {
        showCorsBaseMarkers = layerCors.checked;
        setMapState({ layers: { cors: showCorsBaseMarkers } });
        toggleStationMarkersDisplay();
    });
    layerHeatmap?.addEventListener('change', () => {
        if (layerHeatmap.checked !== heatmapVisible) void toggleHeatmap();
    });

    // Bases stay enabled, but appear only when viewing project details.
    showStationMarkers = true;
    showRescueMarkers = window.rescueFeatureEnabled !== false;
    showCorsBaseMarkers = true;
    if (layerStation) layerStation.checked = true;
    if (layerRescue) layerRescue.checked = true;
    if (layerCors) layerCors.checked = true;

    toggleStationMarkersDisplay();
    toggleRescueMarkersDisplay();
    updateUIVisibilityBasedOnLayers();
}

function updateUIVisibilityBasedOnLayers() {
    const stationSidebar = document.getElementById('station-list-sidebar');
    const detailSidebar = document.getElementById('detail-sidebar');
    const chartsPanel = document.getElementById('charts-panel');
    const longtermOverlay = document.getElementById('longterm-overlay');
    const alertBanner = document.getElementById('alert-banner');

    // Nếu chỉ xem phần cứu hộ, ẩn các info trạm
    if (!showStationMarkers && showRescueMarkers) {
        if (stationSidebar) {
            setStationListSidebarOpen(stationSidebar, false);
            stationSidebar.classList.add('force-hidden');
        }

        setDetailSidebarOpen(detailSidebar, false);
        setChartsPanelOpen(chartsPanel, false);
        if (longtermOverlay) longtermOverlay.classList.remove('active');
        if (alertBanner) alertBanner.classList.remove('show', 'level-warning', 'level-critical');

        document.body.classList.add('rescue-mode-active');
    } else {
        if (stationSidebar) {
            stationSidebar.classList.remove('force-hidden');
            setStationListSidebarOpen(stationSidebar, false);
        }
        document.body.classList.remove('rescue-mode-active');
    }
}

function getLeafletMap() {
    if (map && typeof map.addLayer === 'function') return map;
    if (window.map && typeof window.map.addLayer === 'function') return window.map;
    return null;
}

function beginMapInteraction() {
    mapInteractionDepth += 1;
    if (mapInteractionActive) return;
    mapInteractionActive = true;
    getLeafletMap()?.getContainer?.()?.classList.add('map-is-moving');
    document.body.classList.add('map-is-moving');
}

function endMapInteraction() {
    mapInteractionDepth = Math.max(0, mapInteractionDepth - 1);
    if (mapInteractionDepth > 0 || !mapInteractionActive) return;
    mapInteractionActive = false;
    getLeafletMap()?.getContainer?.()?.classList.remove('map-is-moving');
    document.body.classList.remove('map-is-moving');
    requestAnimationFrame(() => {
        if (pendingStationsReload) {
            pendingStationsReload = false;
            void loadStations();
        }
        if (pendingProjectsReload) {
            pendingProjectsReload = false;
            void loadProjectsAndClusters();
        }
        if (pendingRescueMarkersReload) {
            pendingRescueMarkersReload = false;
            void loadRescueMarkers();
        }
        if (pendingCorsBaseReload) {
            pendingCorsBaseReload = false;
            void loadCorsBaseStations();
        }
    });
}

function toggleStationMarkersDisplay() {
    const leafletMap = getLeafletMap();
    if (!leafletMap) return;

    if (stationClusterGroup) {
        if (showStationMarkers && !leafletMap.hasLayer(stationClusterGroup)) {
            leafletMap.addLayer(stationClusterGroup);
        } else if (!showStationMarkers && leafletMap.hasLayer(stationClusterGroup)) {
            leafletMap.removeLayer(stationClusterGroup);
        }
    }

    refreshProjectMapVisibility();

}

function toggleRescueMarkersDisplay() {
    Object.values(rescueMarkers).forEach(marker => {
        const leafletMap = getLeafletMap();
        if (leafletMap) {
            if (showRescueMarkers) {
                marker.addTo(leafletMap);
            } else {
                leafletMap.removeLayer(marker);
            }
        }
    });
}

function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function normalizeCorsBaseStations(payload) {
    const rawStations = Array.isArray(payload)
        ? payload
        : (Array.isArray(payload?.value) ? payload.value : []);

    // Base stations: show all valid ones from CORS API
    return rawStations
        .filter(st => st && typeof st === "object" && String(st.name || '').trim())
        .map(st => ({
            ...st,
            name: String(st.name || '').trim(),
            lat: Number(st.lat),
            lon: Number(st.lon),
        }))
        .filter(st => Number.isFinite(st.lat) && Number.isFinite(st.lon));
}

async function loadCorsBaseStations() {
    if (document.hidden) return;
    if (mapInteractionActive) {
        pendingCorsBaseReload = true;
        return;
    }
    if (corsBaseFetchInFlight) return;
    corsBaseFetchInFlight = true;
    try {
        const res = await fetch('/api/public/cors-base-stations', { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const payload = await res.json();
        const stations = normalizeCorsBaseStations(payload);
        if (mapInteractionActive) {
            pendingCorsBaseReload = true;
            return;
        }
        const activeNames = new Set(stations.map(st => st.name));

        Object.entries(corsBaseMarkers).forEach(([name, marker]) => {
            if (!activeNames.has(name)) {
                const leafletMap = getLeafletMap();
                if (leafletMap) leafletMap.removeLayer(marker);
                delete corsBaseMarkers[name];
                delete corsBaseStateCache[name];
            }
        });

        stations.forEach(addOrUpdateCorsBaseMarker);
        console.log(`[CORS-BASE] Loaded ${stations.length} base station marker(s)`, stations.map(st => st.name));
    } catch (error) {
        console.warn('[CORS-BASE] load error:', error);
    } finally {
        corsBaseFetchInFlight = false;
    }
}

function addOrUpdateCorsBaseMarker(station) {
    if (!station?.name || !Number.isFinite(station.lat) || !Number.isFinite(station.lon)) return;

    const stateCacheKey = JSON.stringify([
        station.lat,
        station.lon,
        station.status,
        station.station_online,
        station.is_online,
        station.mountpoint_connected,
        station.ntrip_connected,
        station.failover_active,
        station.mountpoint,
        station.correction_source,
    ]);
    if (corsBaseMarkers[station.name] && corsBaseStateCache[station.name] === stateCacheKey) return;
    corsBaseStateCache[station.name] = stateCacheKey;

    const normalizedStatus = String(station.status || '').trim().toLowerCase();
    const hasExplicitPhysicalState = typeof station.station_online === 'boolean'
        || typeof station.is_online === 'boolean';
    const isStationOnline = station.station_online === true
        || station.is_online === true
        || (!hasExplicitPhysicalState && ['online', 'active', 'connected', 'streaming'].includes(normalizedStatus));
    const isMountpointConnected = station.mountpoint_connected === true
        || (station.mountpoint_connected == null && station.ntrip_connected === true);
    const isFailoverActive = station.failover_active === true;
    const fill = isStationOnline ? '#0ea5e9' : '#ef4444';
    const glow = isStationOnline ? 'rgba(14, 165, 233, 0.55)' : 'rgba(239, 68, 68, 0.50)';
    const safeName = escapeHtml(station.name);
    const safeMountpoint = escapeHtml(station.mountpoint || station.name);
    const safeCorrectionSource = escapeHtml(
        station.correction_source || `${station.name}/S1`
    );
    const stationStateLabel = isStationOnline ? 'ONLINE' : 'OFFLINE';
    const mountpointStateLabel = isMountpointConnected ? 'connected' : 'disconnected';

    const icon = L.divIcon({
        className: 'custom-cors-base-marker',
        html: `
            <div title="${safeName}" style="
                width: 0;
                height: 0;
                border-left: 13px solid transparent;
                border-right: 13px solid transparent;
                border-bottom: 24px solid ${fill};
                filter: drop-shadow(0 0 8px ${glow});
                position: relative;
            ">
                <div style="
                    position: absolute;
                    left: -9px;
                    top: 8px;
                    width: 18px;
                    height: 18px;
                    color: white;
                    font-size: 11px;
                    font-weight: 800;
                    line-height: 18px;
                    text-align: center;
                ">B</div>
            </div>
        `,
        iconSize: [26, 24],
        iconAnchor: [13, 18],
        popupAnchor: [0, -18],
    });

    const popupContent = `
        <div style="
            min-width: 230px;
            overflow: hidden;
            border-radius: 10px;
            background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
            color: #0f172a;
            font-size: 13px;
            line-height: 1.45;
            box-shadow: 0 12px 28px rgba(15, 23, 42, 0.18);
        ">
            <div style="
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 10px 12px;
                color: ${isStationOnline ? '#0369a1' : '#b91c1c'};
                font-weight: 800;
                border-bottom: 1px solid #e2e8f0;
            ">
                <span style="color:${fill};"><i class="bi bi-triangle-fill"></i></span>
                <span>${safeName}</span>
            </div>
            <div style="padding: 10px 12px; display: grid; gap: 7px;">
                <div style="display:flex;justify-content:space-between;gap:14px;">
                    <span style="color:#64748b;">Name</span><strong>${safeName}</strong>
                </div>
                <div style="display:flex;justify-content:space-between;gap:14px;">
                    <span style="color:#64748b;">Lat</span><code style="color:#0f172a;">${station.lat.toFixed(9)}</code>
                </div>
                <div style="display:flex;justify-content:space-between;gap:14px;">
                    <span style="color:#64748b;">Lon</span><code style="color:#0f172a;">${station.lon.toFixed(9)}</code>
                </div>
                <div style="display:flex;justify-content:space-between;gap:14px;">
                    <span style="color:#64748b;">Mountpoint</span><strong>${safeMountpoint}</strong>
                </div>
                <div style="display:flex;justify-content:space-between;gap:14px;align-items:center;">
                    <span style="color:#64748b;">Trạm vật lý</span>
                    <span style="
                        padding: 2px 8px;
                        border-radius: 999px;
                        background: ${isStationOnline ? '#dcfce7' : '#fee2e2'};
                        color: ${isStationOnline ? '#166534' : '#b91c1c'};
                        font-weight: 700;
                    ">${stationStateLabel}</span>
                </div>
                <div style="display:flex;justify-content:space-between;gap:14px;align-items:center;">
                    <span style="color:#64748b;">Mountpoint</span>
                    <span style="
                        padding: 2px 8px;
                        border-radius: 999px;
                        background: ${isMountpointConnected ? '#dcfce7' : '#f1f5f9'};
                        color: ${isMountpointConnected ? '#166534' : '#475569'};
                        font-weight: 700;
                    ">${mountpointStateLabel}</span>
                </div>
                <div style="display:flex;justify-content:space-between;gap:14px;align-items:center;">
                    <span style="color:#64748b;">Nguồn RTCM</span>
                    <strong style="color:${isFailoverActive ? '#d97706' : '#0f172a'};">
                        ${safeCorrectionSource}${isFailoverActive ? ' (backup)' : ''}
                    </strong>
                </div>
            </div>
        </div>
    `;

    if (corsBaseMarkers[station.name]) {
        corsBaseMarkers[station.name]
            .setLatLng([station.lat, station.lon])
            .setIcon(icon)
            .bindTooltip(safeName, { direction: 'top', offset: [0, -18] })
            .bindPopup(popupContent, { maxWidth: 300 });
        return;
    }

    const marker = L.marker([station.lat, station.lon], { icon, zIndexOffset: 300 })
        .bindTooltip(safeName, { direction: 'top', offset: [0, -18] })
        .bindPopup(popupContent, { maxWidth: 300 });

    const leafletMap = getLeafletMap();
    if (showCorsBaseMarkers && projectDetailsVisible && showStationMarkers && leafletMap) {
        marker.addTo(leafletMap);
    }

    corsBaseMarkers[station.name] = marker;
}

async function loadRescueMarkers() {
    if (window.rescueFeatureEnabled === false) return;
    if (document.hidden) return;
    if (mapInteractionActive) {
        pendingRescueMarkersReload = true;
        return;
    }
    if (rescueMarkersFetchInFlight) {
        pendingRescueMarkersReload = true;
        return;
    }
    rescueMarkersFetchInFlight = true;
    try {
        const userRole = window.authManager?.getUserInfo?.()?.role;
        if (!window.authManager || !window.authManager.isAuthenticated() || userRole !== 'admin') {
            Object.values(rescueMarkers).forEach(marker => {
                const leafletMap = getLeafletMap();
                if (leafletMap) leafletMap.removeLayer(marker);
            });
            rescueMarkers = {};
            rescueRequestsData = [];
            rescueMarkersRenderSignature = '';
            return; // Rescue markers are admin-only
        }

        const res = await window.authManager.apiFetch('/api/admin/rescue-requests?limit=100');
        if (!res || !res.ok) return;

        const requests = await res.json();
        if (!Array.isArray(requests)) return;
        if (mapInteractionActive) {
            pendingRescueMarkersReload = true;
            return;
        }
        const nextRenderSignature = JSON.stringify(requests);
        if (nextRenderSignature === rescueMarkersRenderSignature) return;

        rescueRequestsData = requests;
        // Remove old markers
        Object.values(rescueMarkers).forEach(marker => {
            if (window.map) window.map.removeLayer(marker);
        });
        rescueMarkers = {};

        // Add new markers for each rescue request
        requests.forEach(req => {
            if (req.latitude && req.longitude && req.status === 'pending') {
                addRescueMarker(req);
            }
        });
        rescueMarkersRenderSignature = nextRenderSignature;
    } catch (error) {
        console.warn('[MAP] loadRescueMarkers error:', error);
    } finally {
        rescueMarkersFetchInFlight = false;
        if (pendingRescueMarkersReload && !mapInteractionActive) {
            pendingRescueMarkersReload = false;
            setTimeout(loadRescueMarkers, 0);
        }
    }
}

function escapeRescueHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[character]);
}

function safeRescueSourceUrl(value) {
    try {
        const url = new URL(String(value || '').trim());
        return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
    } catch (err) {
        console.debug('Invalid rescue source URL:', err);
        return '';
    }
}

function addRescueMarker(rescueRequest) {
    const {
        id,
        latitude,
        longitude,
        requester_name,
        phone,
        message,
        accuracy_m,
        created_at,
        rescue_type,
        province_city,
        source_link,
        image_url,
    } = rescueRequest;
    if (!id || !latitude || !longitude) return;
    const existingMarker = rescueMarkers[id];
    if (existingMarker) {
        const leafletMap = getLeafletMap();
        if (leafletMap?.hasLayer(existingMarker)) leafletMap.removeLayer(existingMarker);
    }

    const safeSourceLink = safeRescueSourceUrl(source_link);
    const protectedImageUrl = /^\/api\/admin\/rescue-images\/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(String(image_url || ''))
        ? String(image_url)
        : '';

    const icon = L.divIcon({
        className: 'custom-rescue-marker',
        html: `<div style="
            width: 24px; height: 24px;
            background: #dc3545;
            border-radius: 50%;
            border: 3px solid white;
            box-shadow: 0 0 12px rgba(220, 53, 69, 0.7);
            display: flex; align-items: center; justify-content: center;
            font-size: 14px; color: white; font-weight: bold;
        "><i class="bi bi-exclamation-fill" style="font-size: 12px;"></i></div>`,
        iconSize: [24, 24],
        iconAnchor: [12, 12]
    });

    const marker = L.marker([latitude, longitude], { icon })
        .bindTooltip(`${escapeRescueHtml(requester_name || 'SOS')} - ${escapeRescueHtml(phone || 'N/A')}`, {
            direction: 'top',
            offset: [0, -15],
            permanent: false
        });

    // An toàn thêm marker thay vì addLayer(null)
    const leafletMap = getLeafletMap();
    if (showRescueMarkers && leafletMap) {
        marker.addTo(leafletMap);
    }

    const accuracyHtml = accuracy_m ? `<div><strong>Độ chính xác:</strong> ±${accuracy_m}m</div>` : '';
    const sourceLinkHtml = safeSourceLink ? `<div><strong>Nguồn:</strong> <a href="${escapeRescueHtml(safeSourceLink)}" target="_blank" rel="noopener noreferrer">Mở link</a></div>` : '';
    const imageHtml = protectedImageUrl ? `<div style="margin-top:8px;"><img data-auth-src="${escapeRescueHtml(protectedImageUrl)}" alt="evidence" style="width:100%;max-height:180px;object-fit:cover;border-radius:6px;border:1px solid #ddd;"></div>` : '';

    const popupContent = `
        <div class="rescue-popup" style="min-width: 280px;">
            <h6 style="margin: 0 0 10px 0; color: #dc3545;">
                <i class="bi bi-exclamation-circle me-1"></i>Yêu cầu cứu hộ
            </h6>
            <div style="font-size: 13px; line-height: 1.6;">
                <div><strong>ID:</strong> #${escapeRescueHtml(id)}</div>
                <div><strong>Người yêu cầu:</strong> ${escapeRescueHtml(requester_name || '(Không có)')}</div>
                <div><strong>Số điện thoại:</strong> ${escapeRescueHtml(phone || '(Không có)')}</div>
                <div><strong>Phân loại:</strong> ${escapeRescueHtml(rescue_type || '(Không có)')}</div>
                <div><strong>Tỉnh/TP:</strong> ${escapeRescueHtml(province_city || '(Không có)')}</div>
                <div><strong>Vị trí:</strong> ${latitude.toFixed(6)}, ${longitude.toFixed(6)}</div>
                ${accuracyHtml}
                <div><strong>Thời gian:</strong> ${new Date(normalizeEpochMs(created_at)).toLocaleString('vi-VN')}</div>
                ${sourceLinkHtml}
                <div style="margin-top: 8px; padding: 8px; background: #f8f9fa; border-radius: 4px;">
                    <strong style="font-size: 12px;">Tình trạng:</strong>
                    <div style="font-size: 13px; margin-top: 4px; word-wrap: break-word;">
                        ${escapeRescueHtml(message || '(Không có mô tả)')}
                    </div>
                </div>
                ${imageHtml}
                <div style="margin-top: 15px;">
                    <a href="https://www.google.com/maps/dir/?api=1&destination=${latitude},${longitude}"
                       target="_blank" rel="noopener"
                       class="btn btn-sm btn-primary w-100 shadow-sm" style="font-size: 13px; font-weight: 600; border-radius: 6px;">
                       <i class="bi bi-geo-alt-fill me-1"></i>Chỉ đường (Google Maps)
                    </a>
                </div>
            </div>
        </div>
    `;

    marker.bindPopup(popupContent, { maxWidth: 300, maxHeight: 400 });
    marker.on('popupopen', () => {
        const popupElement = marker.getPopup()?.getElement();
        if (popupElement) void window.hydrateAuthenticatedImages?.(popupElement);
    });
    marker.on('click', () => {
        marker.openPopup();
    });

    rescueMarkers[id] = marker;
}

function updateRescueMarkerFromWebSocket(message) {
    if (message.type !== 'rescue_request') return;
    rescueMarkersRenderSignature = '';

    if (message.status === 'pending') {
        addRescueMarker(message);
        // Only push to data array if it doesn't exist
        if (!rescueRequestsData.some(r => r.id === message.id)) {
            rescueRequestsData.push(message);
        }
    } else if (message.id && rescueMarkers[message.id]) {
        const leafletMap = getLeafletMap();
        if (leafletMap) leafletMap.removeLayer(rescueMarkers[message.id]);
        delete rescueMarkers[message.id];
    }
}

function setupBasemapControls() {
    const toggle = document.getElementById('basemap-toggle');
    const popover = document.getElementById('basemap-popover');
    if (!toggle || !popover) return;
    const close = (restoreFocus = false) => {
        popover.hidden = true;
        toggle.setAttribute('aria-expanded', 'false');
        if (restoreFocus) toggle.focus();
    };
    const sync = () => {
        popover.querySelectorAll('input[name="basemap"]').forEach(input => { input.checked = input.value === activeBasemap; });
        toggle.setAttribute('aria-label', `Đổi nền bản đồ: ${MAP_BASEMAPS[activeBasemap].label}`);
    };
    sync();
    toggle.addEventListener('click', () => {
        popover.hidden = !popover.hidden;
        toggle.setAttribute('aria-expanded', String(!popover.hidden));
        if (!popover.hidden) {
            const layers = document.getElementById('layer-popover');
            if (layers) layers.hidden = true;
            document.getElementById('layer-popover-toggle')?.setAttribute('aria-expanded', 'false');
            popover.querySelector('input:checked')?.focus();
        }
    });
    popover.addEventListener('change', event => {
        const value = event.target.value;
        if (!Object.hasOwn(MAP_BASEMAPS, value) || value === activeBasemap) return;
        activeBasemap = value;
        try { localStorage.setItem('monitoring-basemap', value); } catch (err) { console.debug('Cannot persist basemap choice:', err); }
        switchMapTiles();
        sync();
    });
    document.addEventListener('click', event => {
        if (!event.target.closest('.basemap-control')) close();
    });
    popover.addEventListener('keydown', event => {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true); }
    });
}
