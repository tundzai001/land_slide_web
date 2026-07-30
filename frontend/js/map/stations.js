// =====================================================
// OTHER FUNCTIONS
// =====================================================

function switchMapTiles(theme) {
    if (!map) return;
    const key = theme === 'dark' ? 'dark' : 'light';
    if (currentTileLayer) {
        map.removeLayer(currentTileLayer);
    }
    currentTileLayer = L.tileLayer(TILE_URLS[key], TILE_OPTIONS[key]).addTo(map);
}

function createStationClusterGroup() {
    return L.layerGroup();
}

function initMap() {
    try {
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
        map.on('moveend zoomend', endMapInteraction);

        stationClusterGroup = createStationClusterGroup();
        map.addLayer(stationClusterGroup);



        const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
        switchMapTiles(currentTheme);

        // Auto-switch tiles on theme change
        window.addEventListener('themeChanged', (e) => {
            switchMapTiles(e.detail?.theme || document.documentElement.getAttribute('data-theme'));
        });

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
    return Number.isFinite(Number(location?.lat)) && Number.isFinite(Number(location?.lon));
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
                gnss_clusters: project.gnss_clusters,
            })),
            stations: allStations.map(station => [
                station.id,
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
        }
        clusterPolylines = [];
        
        const colors = ['#10b981', '#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b'];
        let colorIdx = 0;

        projects.forEach(proj => {
            if (!proj.gnss_clusters || !Array.isArray(proj.gnss_clusters)) return;
            
            proj.gnss_clusters.forEach(c => {
                const stationTokens = getClusterStationTokens(c);
                const clusterMembers = stationTokens
                    .map(findStationByClusterToken)
                    .filter(station => station && hasValidLatLon(station.location));
                const stationIds = clusterMembers.map(station => station.id);
                
                const isTotal = c.cluster_type === 'total';
                if (clusterMembers.length < 2) return;
                
                const latlngs = [];
                const clusterStations = [];
                clusterMembers.forEach(st => {
                    latlngs.push([Number(st.location.lat), Number(st.location.lon)]);
                    clusterStations.push(st.name || st.station_code || String(st.id));
                });
                
                if (latlngs.length >= 2) {
                    const multiLatLngs = []; for (let i = 0; i < latlngs.length; i++) { for (let j = i + 1; j < latlngs.length; j++) { multiLatLngs.push([latlngs[i], latlngs[j]]); } } const polyline = L.polyline(multiLatLngs, {
                        color: isTotal ? '#f43f5e' : colors[colorIdx % colors.length],
                        weight: isTotal ? 4 : 3,
                        opacity: isTotal ? 0.15 : 0.7,
                        dashArray: isTotal ? '10, 20' : '5, 10'
                    });
                    
                    // Hitbox invisible polyline to make clicking easier
                    const hitbox = L.polyline(multiLatLngs, {
                        color: 'transparent',
                        weight: 20,
                        opacity: 0
                    });

                    const clickHandler = (e) => {
                        showAdjustmentPopup(proj.id, isTotal ? `${proj.name} (Cụm Tổng)` : proj.name, stationIds, clusterStations, e.latlng);
                    };

                    polyline.on('click', clickHandler);
                    hitbox.on('click', clickHandler);
                    
                    if (leafletMap) {
                        polyline.addTo(leafletMap);
                        hitbox.addTo(leafletMap);
                    }
                    clusterPolylines.push(polyline);
                    clusterPolylines.push(hitbox);
                    if (!isTotal) colorIdx++;
                }
            });
        });
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

function showAdjustmentPopup(projectId, projectName, stationIds, clusterStations, latlng) {
    const leafletMap = getLeafletMap();
    if (!leafletMap) return;
    
    const popupContent = document.createElement('div');
    popupContent.className = 'text-center p-2';
    popupContent.innerHTML = `
        <h6 class="mb-2 fw-bold" style="color: #10b981;">${projectName}</h6>
        <div class="small mb-3 text-secondary">Cụm: ${clusterStations.join(', ')}</div>
        <button class="btn btn-sm btn-success w-100" id="btn-start-adjustment-${projectId}">
            <i class="bi bi-play-fill"></i> Bắt đầu Bình sai
        </button>
    `;
    
    const popup = L.popup()
        .setLatLng(latlng)
        .setContent(popupContent)
        .openOn(leafletMap);
        
    setTimeout(() => {
        const btn = document.getElementById(`btn-start-adjustment-${projectId}`);
        if (btn) {
            btn.addEventListener('click', () => {
                leafletMap.closePopup(popup);
                requestGnssAdjustment(projectId, stationIds);
            });
        }
    }, 100);
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

        stations.forEach(station => {
            if (station.location && station.location.lat && station.location.lon) {
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
            if (currentStationData && currentStationData.id === station.id) {
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
        loadProjectsAndClusters();

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

    const level = chosen.riskUi.normalized === 'CRITICAL' ? 'CRITICAL' : 'WARNING';
    const cachedAlert = latestAlertByStation[stationId];
    const candidateAlert = cachedAlert ? { ...cachedAlert, level } : {
        station_id: stationId,
        level,
        message: chosen.riskUi.normalized === 'CRITICAL'
            ? 'Critical risk detected from station state. Press Track to monitor now.'
            : 'Warning risk detected from station state. Press Track to monitor now.'
    };
    const candidateKey = buildAlertKey(candidateAlert);
    if (candidateKey && acknowledgedAlertKeyByStation[stationId] === candidateKey) return;

    showAlertBanner(candidateAlert, { silent: true });
}

// ✅ Silently re-fetch current station detail to refresh per-sensor is_online status
async function refreshCurrentStationDetail() {
    if (!currentStationData) return;
    const sidebar = document.getElementById('detail-sidebar');
    if (!sidebar || !sidebar.classList.contains('active')) return;

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
    if (window.renderReactStationList?.(stations)) return;
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
        if (child.dataset && child.dataset.stationId && !currentIds.has(child.dataset.stationId)) {
            container.removeChild(child);
        }
    });

    const emptyPlaceholder = container.querySelector('.text-center.text-muted');
    if (emptyPlaceholder) emptyPlaceholder.remove();

    stations.forEach(st => {
        const riskUi = getRiskPresentation(st.risk_level, st.status);
        const badgeClass = getRiskBadgeClass(riskUi.className);
        
        let div = container.querySelector(`div[data-station-id="${st.id}"]`);
        
        if (div) {
            const badge = div.querySelector('.badge');
            if (badge) {
                const targetClass = `badge ${badgeClass}`;
                if (badge.className !== targetClass) badge.className = targetClass;
                if (badge.textContent.trim() !== riskUi.display) badge.textContent = riskUi.display;
            }
        } else {
            div = document.createElement('div');
            div.className = 'station-item';
            div.dataset.stationId = st.id;
            div.innerHTML = `
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <div class="fw-bold" style="color: var(--text-primary)">${st.name}</div>
                        <small style="color: var(--text-secondary)">${st.station_code}</small>
                    </div>
                    <span id="list-badge-${st.id}" class="badge ${badgeClass}">
                        ${riskUi.display}
                    </span>
                </div>
            `;
            div.addEventListener('click', () => {
                selectStation(st.id);
                if (window.innerWidth < 768) {
                    const sidebar = document.getElementById('station-list-sidebar');
                    if (sidebar) sidebar.classList.add('hidden');
                }
            });
            container.appendChild(div);
        }
    });
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

        if (stationClusterGroup) {
            stationClusterGroup.addLayer(marker);
        }

        marker.on('click', () => selectStation(station.id));
        markers[station.id] = marker;
    }
}
