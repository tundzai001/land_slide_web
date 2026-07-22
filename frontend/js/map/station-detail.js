// =====================================================
// SIREN POPUP HELPER — Dùng bởi selectStation và Track button
// =====================================================
function _showSirenIfAlerting(stationId, data) {
    const sirenSection = document.getElementById('siren-sidebar-section');

    // Only show siren controls for admin and operator roles
    const user = window.authManager?.getUserInfo();
    const userRole = user?.role;
    if (userRole !== 'admin' && userRole !== 'operator') {
        if (sirenSection) sirenSection.style.display = 'none';
        return;
    }

    // Always visible for admin/operator (grey when idle, red when alerting)
    if (sirenSection) sirenSection.style.display = '';

    const risk = data.risk_assessment?.overall_risk || data.risk_level;
    const isAlerting = (risk === 'EXTREME' || risk === 'CRITICAL') && data.status !== 'offline';

    // Default statuses based on pi_devices array from station detail API
    let pointDeviceStatus = 'idle';
    let centerDeviceStatus = 'idle';

    if (data.pi_devices && Array.isArray(data.pi_devices)) {
        const pPoint = data.pi_devices.find(d => d.device_type === 'pi_point');
        const pCenter = data.pi_devices.find(d => d.device_type === 'pi_center');

        if (pPoint && !pPoint.is_online) pointDeviceStatus = 'offline';
        if (pCenter && !pCenter.is_online) centerDeviceStatus = 'offline';
        // If there is no pi_point or pi_center registered for this station, maybe set to offline?
        // But let's only override if explicitly offline to be safe.
    }

    if (isAlerting) {
        currentAlertStationId = stationId;
        const sirenBtns = document.querySelectorAll('.btn-siren-toggle');
        if (sirenBtns.length > 0) {
            sirenBtns.forEach(b => {
                const target = b.getAttribute('data-target');
                let currentState = b.getAttribute('data-siren-state');

                // Determine target default status (might be offline)
                const isOffline = target === 'pi_center' ? centerDeviceStatus === 'offline' : pointDeviceStatus === 'offline';

                if (isOffline) {
                    setSirenButtonState('offline', target);
                } else {
                    // If online, transition idle to alerting, keep muted as is
                    if (currentState === 'idle' || currentState === 'offline') currentState = 'alerting';
                    setSirenButtonState(currentState, target);
                }
            });
        }
    } else {
        if (currentAlertStationId === stationId) {
            currentAlertStationId = null;
        }

        // Apply idle or offline if not alerting
        setSirenButtonState(centerDeviceStatus === 'offline' ? 'offline' : 'idle', 'pi_center');
        setSirenButtonState(pointDeviceStatus === 'offline' ? 'offline' : 'idle', 'pi_point');
    }
}

async function fetchStationDetail(stationId, { includeHistory = false, signal } = {}) {
    const url = `/api/stations/${stationId}/detail?include_history=${includeHistory ? 'true' : 'false'}`;
    const requestOptions = signal ? { signal } : {};
    const response = window.authManager?.isAuthenticated?.()
        ? await window.authManager.apiFetch(url, requestOptions)
        : await fetch(url, requestOptions);
    if (!response?.ok) throw new Error('Failed to load station detail');
    return response.json();
}

function focusMapOnStation(stationId, skipZoom = false) {
    const marker = markers[stationId];
    const leafletMap = getLeafletMap();
    if (skipZoom || !marker || !leafletMap) return Promise.resolve();

    const target = marker.getLatLng();
    const currentZoom = leafletMap.getZoom();
    if (currentZoom >= 15 && leafletMap.getCenter().distanceTo(target) < 3) {
        return Promise.resolve();
    }

    return new Promise(resolve => {
        let finished = false;
        const finish = () => {
            if (finished) return;
            finished = true;
            clearTimeout(timeoutId);
            leafletMap.off('moveend', finish);
            resolve();
        };
        const timeoutId = setTimeout(finish, 700);
        leafletMap.once('moveend', finish);
        const innerBounds = leafletMap.getBounds().pad(-0.18);
        if (currentZoom >= 15 && innerBounds.isValid() && innerBounds.contains(target)) {
            leafletMap.panTo(target, { animate: true, duration: 0.25, easeLinearity: 0.35 });
        } else {
            leafletMap.flyTo(target, 16, { duration: 0.45, easeLinearity: 0.35 });
        }
    });
}

async function loadStationHistoryAndRenderCharts() {
    const stationId = Number(currentStationData?.id || 0);
    if (!stationId) return;
    const chartsPanel = document.getElementById('charts-panel');
    const chartsButton = document.getElementById('btn-show-charts');
    const cached = stationHistoryCache.get(stationId);
    if (cached && Date.now() - cached.loadedAt < STATION_HISTORY_CACHE_MS) {
        renderCharts(cached.data);
        return;
    }

    stationHistoryController?.abort();
    stationHistoryController = new AbortController();
    chartsPanel?.classList.add('station-history-loading');
    if (chartsButton) chartsButton.disabled = true;
    try {
        const data = await fetchStationDetail(stationId, {
            includeHistory: true,
            signal: stationHistoryController.signal,
        });
        if (Number(currentStationData?.id || 0) !== stationId) return;
        stationHistoryCache.set(stationId, { data, loadedAt: Date.now() });
        currentStationData = data;
        renderCharts(data);
    } catch (error) {
        if (error?.name !== 'AbortError') {
            console.error('[MAP] Error loading station history:', error);
            window.toast?.error('Failed to load chart history');
        }
    } finally {
        chartsPanel?.classList.remove('station-history-loading');
        if (chartsButton) chartsButton.disabled = false;
    }
}

async function selectStation(stationId, options = {}) {
    if (currentMapMode === 'rescue') {
        return;
    }

    const { skipZoom = false, skipSiren = false, skipBannerRestore = false } = options;
    const selectionId = ++stationSelectionSequence;
    stationSelectionController?.abort();
    stationHistoryController?.abort();
    stationSelectionController = new AbortController();
    console.log(`🎯 [MAP] Selecting station: ${stationId}`, options);

    const sidebar = document.getElementById('detail-sidebar');
    if (sidebar) {
        sidebar.classList.add('station-selecting');
        sidebar.classList.add('active');
        sidebar.setAttribute('aria-busy', 'true');
    }
    const stationSummary = allStations.find(station => Number(station.id) === Number(stationId));
    if (stationSummary) {
        setText('st-name', stationSummary.name);
        setText('st-code', stationSummary.station_code);
    }
    const focusPromise = focusMapOnStation(stationId, skipZoom);

    try {
        const cached = stationDetailCache.get(Number(stationId));
        const dataPromise = cached && Date.now() - cached.loadedAt < STATION_DETAIL_CACHE_MS
            ? Promise.resolve(cached.data)
            : fetchStationDetail(stationId, { signal: stationSelectionController.signal });
        const [data] = await Promise.all([dataPromise, focusPromise]);
        if (selectionId !== stationSelectionSequence) return;
        stationDetailCache.set(Number(stationId), { data, loadedAt: Date.now() });
        currentStationData = data;
        await new Promise(resolve => requestAnimationFrame(resolve));
        if (selectionId !== stationSelectionSequence) return;
        updateSidebarUI(data);
        applySensorCardAlertsFromAssessment(data);

        // ✅ Siren popup logic — có thể bị skip bởi caller (ví dụ: Track button tự quản lý)
        if (!skipSiren) {
            _showSirenIfAlerting(stationId, data);
        }

        // ✅ Restore alert banner + siren buttons im lặng nếu trạm đang có alert từ DB (sau reload)
        const _banner = document.getElementById('alert-banner');
        const _riskLevel = data.risk_assessment?.overall_risk || data.risk_level || 'LOW';
        const _riskBand = normalizeRiskLevel(_riskLevel, data.status);
        const _activeAlerts = data.risk_assessment?.active_alerts || [];
        if (!_banner?.classList.contains('show') &&
            !skipBannerRestore &&
            !isBannerSuppressed(data.id) &&
            (_riskBand === 'MEDIUM' || _riskBand === 'CRITICAL') &&
            _activeAlerts.length > 0 &&
            data.status !== 'offline') {
            const _topAlert = _activeAlerts.find(a => a.level === 'CRITICAL') || _activeAlerts[0];
            // Show banner (silent — không kêu còi browser)
            showAlertBanner({
                station_id: data.id,
                level: _topAlert.level,
                message: _topAlert.message,
                sensor_type: mapAlertCategoryToSensorType(_topAlert.category)
            }, { silent: true });
            // Sync siren buttons đúng per-device (đã handle offline/online trong _showSirenIfAlerting)
            _showSirenIfAlerting(data.id, data);
        }

    } catch (e) {
        if (e?.name !== 'AbortError') {
            console.error('❌ [MAP] Error loading station detail:', e);
            window.toast?.error('Failed to load station info');
        }
    } finally {
        if (selectionId === stationSelectionSequence) {
            requestAnimationFrame(() => {
                sidebar?.classList.remove('station-selecting');
                sidebar?.setAttribute('aria-busy', 'false');
            });
        }
    }
}

function getGnssVelocity(gnssLatest) {
    if (!gnssLatest) return null;
    const data = gnssLatest.data || gnssLatest;
    const toFinite = (value) => {
        const num = Number(value);
        return Number.isFinite(num) ? num : null;
    };

    const velE = toFinite(data.vel_e);
    const velN = toFinite(data.vel_n);
    if (velE !== null && velN !== null) {
        return Math.sqrt(Math.pow(velE, 2) + Math.pow(velN, 2));
    }

    for (const key of ['velocity_mm_s', 'speed_2d_mm_s', 'speed_mm_s']) {
        const value = toFinite(data[key]);
        if (value !== null) return value;
    }

    for (const key of ['speed_2d', 'velocity', 'speed']) {
        const value = toFinite(data[key]);
        if (value !== null) return value * 1000;
    }

    return null;
}

function safeNumber(value, decimals = 2, defaultValue = '--') {
    if (value === null || value === undefined || value === '') {
        return defaultValue;
    }

    const num = parseFloat(value);
    if (isNaN(num)) {
        return defaultValue;
    }

    return num.toFixed(decimals);
}

function formatWaterLevelDisplay(waterLatest) {
    // If sensor is offline or value is fallback, show -- immediately
    if (waterLatest?.is_fallback === true) {
        return `--<span class="sensor-unit">cm</span>`;
    }

    const unitRaw = String(waterLatest?.water_display_unit || '').trim().toLowerCase();
    const displayRaw = parseFloat(waterLatest?.water_display_value);
    let levelCm = null;

    if (!Number.isNaN(displayRaw)) {
        if (unitRaw === 'mm') {
            // Sanity check: if mm unit but value < 10, likely mislabeled as m
            if (displayRaw < 10) {
                levelCm = displayRaw * 100;  // Treat as meters
            } else {
                levelCm = displayRaw / 10;   // Treat as millimeters
            }
        } else if (unitRaw === 'm' || unitRaw === 'meter' || unitRaw === 'meters') {
            levelCm = displayRaw * 100;
        } else if (unitRaw === 'cm') {
            levelCm = displayRaw;
        }
    }

    if (levelCm === null) {
        const cmRaw = parseFloat(waterLatest?.water_level_cm);
        if (!Number.isNaN(cmRaw)) {
            levelCm = cmRaw;
        }
    }

    if (levelCm === null) {
        const meterRaw = parseFloat(waterLatest?.water_level ?? waterLatest?.processed_value_meters);
        if (!Number.isNaN(meterRaw)) {
            levelCm = meterRaw * 100;
        }
    }

    if (levelCm === null) {
        return `--<span class="sensor-unit">cm</span>`;
    }

    if (Math.abs(levelCm) >= 100) {
        return `${safeNumber(levelCm / 100, 2)}<span class="sensor-unit">m</span>`;
    }

    return `${safeNumber(levelCm, 1)}<span class="sensor-unit">cm</span>`;
}

function formatImuDelta(val, axis) {
    const num = parseFloat(val);
    if (isNaN(num)) return '-- cm';
    const dispMm = Math.sin(num * Math.PI / 180) * 0.09 * 1000; // mm
    const sign = dispMm > 0 ? '+' : '';
    // Ưu tiên cm; chỉ dùng mm khi |giá trị| < 1 cm
    const absMm = Math.abs(dispMm);
    const [displayVal, unit] = absMm >= 10
        ? [(dispMm / 10).toFixed(2), 'cm']
        : [dispMm.toFixed(1), 'mm'];
    const threshold = unit === 'cm' ? 0.05 : 0.5;
    const arrows = {
        roll: dispMm > threshold ? ' →' : dispMm < -threshold ? ' ←' : '',
        pitch: dispMm > threshold ? ' ↑' : dispMm < -threshold ? ' ↓' : '',
        yaw: dispMm > threshold ? ' ↻' : dispMm < -threshold ? ' ↺' : '',
    };
    return `${sign}${displayVal} ${unit}${arrows[axis] || ''}`;
}

function updateGnssFixBadge(fixMode, fixQuality) {
    const badge = document.getElementById('gnss-fix-badge');
    if (!badge) return;

    const normalizedMode = (fixMode || '').toString().trim().toUpperCase();
    const quality = Number(fixQuality);

    let cls = 'GNSS_UNKNOWN';
    let text = 'NO DATA';

    switch (normalizedMode) {
        case 'GNSS_RTK_FIXED':
        case 'RTK_FIXED':
            cls = 'GNSS_RTK_FIXED';
            text = 'RTK FIXED';
            break;
        case 'GNSS_RTK_FLOAT':
        case 'RTK_FLOAT':
            cls = 'GNSS_RTK_FLOAT';
            text = 'RTK FLOAT';
            break;
        case 'GNSS_DGPS_FLOAT':
        case 'DGPS_FLOAT':
            cls = 'GNSS_DGPS_FLOAT';
            text = 'DGPS FLOAT';
            break;
        case 'GNSS_SINGLE':
        case 'GPS_SINGLE_NO_RTK':
        case 'SINGLE':
        case 'NO_RTK':
            cls = 'GNSS_SINGLE';
            text = 'NO RTK';
            break;
        case 'GNSS_INVALID':
        case 'INVALID':
            cls = 'GNSS_INVALID';
            text = 'INVALID';
            break;
        case 'GNSS_UNKNOWN':
        case 'NO_DATA':
            cls = 'GNSS_UNKNOWN';
            text = 'NO DATA';
            break;
        default:
            if (quality === 4) {
                cls = 'GNSS_RTK_FIXED';
                text = 'RTK FIXED';
            } else if (quality === 5) {
                cls = 'GNSS_RTK_FLOAT';
                text = 'RTK FLOAT';
            } else if (quality === 2) {
                cls = 'GNSS_DGPS_FLOAT';
                text = 'DGPS FLOAT';
            } else if (quality === 1) {
                cls = 'GNSS_SINGLE';
                text = 'NO RTK';
            }
            break;
    }

    badge.className = `gnss-fix-badge ${cls}`;
    badge.textContent = text;
}

function updateImuOfflineBadge(isOnline) {
    const badge = document.getElementById('imu-offline-badge');
    if (!badge) return;
    badge.style.display = isOnline ? 'none' : '';
}

function updateSensorOfflineBadge(sensorType, isOnline) {
    const badge = document.getElementById(`${sensorType}-offline-badge`);
    if (!badge) return;
    badge.style.display = isOnline ? 'none' : '';
}

function updateSidebarUI(data) {
    setText('st-name', data.name);
    setText('st-code', data.station_code);

    // ✅ Handle offline_display_enabled to force STALE status and show old data
    const isOfflineDisplayEnabled = ((data.offline_display?.enabled === true) || data.offline_display_enabled === true);
    let effectiveStatus = data.status;
    if (effectiveStatus === 'offline' && isOfflineDisplayEnabled) {
        effectiveStatus = 'stale'; // turn yellow
    }

    const riskEl = document.getElementById('st-risk');
    if (riskEl) {
        const riskUi = getRiskPresentation(data.risk_assessment?.overall_risk || data.risk_level, effectiveStatus);
        riskEl.className = `status-badge ${riskUi.className}`;
        riskEl.innerHTML = `<span class="status-dot"></span> ${riskUi.display}`;
    }

    const gnssLatest = data.sensors?.gnss?.latest;
    const rainLatest = data.sensors?.rain?.latest;
    const waterLatest = data.sensors?.water?.latest;
    const imuLatest = data.sensors?.imu?.latest;
    const stationId = data.id;
    const imuApiTs = Number(data.sensors?.imu?.latest_timestamp || 0);
    const imuRealtimeTs = Number(latestRealtimeSensorTs[`${stationId}_imu`] || 0);
    const latestSensorTs = getLatestSensorTimestamp(data);

    // ✅ Per-sensor online check: nếu sensor đó offline → hiển thị '--' dù trạm vẫn online
    const mqttConnected = data.mqtt_connected !== false;
    renderStaleInfo(data, mqttConnected, latestSensorTs);
    
    // staleDisplay is true if station is stale OR if we forced it to stale because of offline_display_enabled
    const staleDisplay = (effectiveStatus === 'stale' || data.status === 'stale') && isOfflineDisplayEnabled;
    
    const gnssOnline = mqttConnected && effectiveStatus !== 'offline' &&
        ((data.sensors?.gnss?.is_online ?? false) || (staleDisplay && !!gnssLatest));
    const rainOnline = mqttConnected && effectiveStatus !== 'offline' &&
        ((data.sensors?.rain?.is_online ?? false) || (staleDisplay && !!rainLatest));
    const waterOnline = mqttConnected && effectiveStatus !== 'offline' &&
        ((data.sensors?.water?.is_online ?? false) || (staleDisplay && !!waterLatest));
    const imuOnline = mqttConnected && effectiveStatus !== 'offline' &&
        ((data.sensors?.imu?.is_online ?? false) || (staleDisplay && !!imuLatest));

    if (gnssOnline) {
        const gnssFixBadgeEl = document.getElementById('gnss-fix-badge');
        const gnssOfflineBadgeEl = document.getElementById('gnss-offline-badge');
        if (gnssFixBadgeEl) gnssFixBadgeEl.style.display = '';
        if (gnssOfflineBadgeEl) gnssOfflineBadgeEl.style.display = 'none';
        updateGnssFixBadge(gnssLatest?.fix_mode, gnssLatest?.fix_quality);
    } else {
        const gnssFixBadgeEl = document.getElementById('gnss-fix-badge');
        const gnssOfflineBadgeEl = document.getElementById('gnss-offline-badge');
        if (gnssFixBadgeEl) gnssFixBadgeEl.style.display = 'none';
        if (gnssOfflineBadgeEl) gnssOfflineBadgeEl.style.display = '';
    }

    // ✅ POPULATE: Điền dữ liệu Advanced GNSS — luôn hiển thị dữ liệu cuối cùng,
    // kể cả khi sensor offline (tránh bị mất chữ khi refresh)
    // API trả data flat trên gnssLatest, WS cache lưu dưới gnssLatest.data
    const adv = gnssLatest?.data || gnssLatest;
    if (adv && adv.adv_x !== undefined) {
        // Vị trí hiện tại: Lat/Lon/Alt từ GNGGA
        setText('adv-val-lat', (adv.lat || 0).toFixed(6));
        setText('adv-val-lon', (adv.lon || 0).toFixed(6));
        setText('adv-val-alt', (adv.adv_h || adv.h || 0).toFixed(3));
        // Biến dạng lũy kế
        setText('adv-val-dx', (adv.adv_dx || 0).toFixed(2));
        setText('adv-val-dy', (adv.adv_dy || 0).toFixed(2));
        setText('adv-val-dh', (adv.adv_dh || 0).toFixed(2));
        // Vận tốc biến dạng
        setText('adv-val-vdx', (adv.adv_vdx || 0).toFixed(4));
        setText('adv-val-vdy', (adv.adv_vdy || 0).toFixed(4));
        setText('adv-val-vdh', (adv.adv_vdh || 0).toFixed(4));
    }
    updateSensorOfflineBadge('rain', rainOnline);
    updateSensorOfflineBadge('water', waterOnline);
    updateImuOfflineBadge(imuOnline);

    // ✅ Khi toàn trạm offline → hiển thị '--' cho TẤT CẢ sensor
    if (effectiveStatus === 'offline') {
        setHTML('val-gnss-vel', `--<span class="sensor-unit">mm/s</span>`);
        setHTML('val-rain', `--<span class="sensor-unit">mm/h</span>`);
        setHTML('val-water', `--<span class="sensor-unit">cm</span>`);
        setText('val-imu-roll', '--°');
        setText('val-imu-pitch', '--°');
        setText('val-imu-yaw', '--°');
        setText('val-imu-delta-roll', '-- mm');
        setText('val-imu-delta-pitch', '-- mm');
        setText('val-imu-delta-yaw', '-- mm');
        updateImuDrift(null, null);

        // ✅ Khi offline, nút tắt còi chuyển xám (idle)
        setSirenButtonState('idle');

        // Ẩn battery khi offline
        const batteryContainer = document.getElementById('battery-container');
        if (batteryContainer) batteryContainer.style.display = 'none';
    } else {
        // GNSS: chỉ hiện giá trị khi sensor đang online
        if (gnssOnline) {
            const gnssSpeed = getGnssVelocity(gnssLatest);
            setHTML('val-gnss-vel', `${safeNumber(gnssSpeed, 4)}<span class="sensor-unit">mm/s</span>`);
        } else {
            setHTML('val-gnss-vel', `--<span class="sensor-unit">mm/s</span>`);
        }

        // Rain
        if (rainOnline) {
            const rainIntensity = rainLatest?.intensity_mm_h ?? null;
            setHTML('val-rain', `${safeNumber(rainIntensity, 1)}<span class="sensor-unit">mm/h</span>`);
        } else {
            setHTML('val-rain', `--<span class="sensor-unit">mm/h</span>`);
        }

        // Water
        if (waterOnline) {
            setHTML('val-water', formatWaterLevelDisplay(waterLatest));
        } else {
            setHTML('val-water', `--<span class="sensor-unit">cm</span>`);
        }

        // IMU
        if (imuOnline) {
            const useApiImu = !imuRealtimeTs || !imuApiTs || imuApiTs >= imuRealtimeTs;
            console.debug(`🧭 [IMU][MERGE] station=${stationId} api_ts=${imuApiTs || 'none'} ws_ts=${imuRealtimeTs || 'none'} source=${useApiImu ? 'api' : 'ws-cache'}`);

            if (useApiImu) {
                setText('val-imu-roll', `${safeNumber(imuLatest?.raw_roll, 1)}°`);
                setText('val-imu-pitch', `${safeNumber(imuLatest?.raw_pitch, 1)}°`);
                setText('val-imu-yaw', `${safeNumber(imuLatest?.raw_yaw, 1)}°`);
                setText('val-imu-delta-roll', formatImuDelta(imuLatest?.roll, 'roll'));
                setText('val-imu-delta-pitch', formatImuDelta(imuLatest?.pitch, 'pitch'));
                setText('val-imu-delta-yaw', formatImuDelta(imuLatest?.yaw, 'yaw'));
            } else {
                console.warn(`⏭️ [IMU] Skip stale API overwrite station=${stationId} api_ts=${imuApiTs} < ws_ts=${imuRealtimeTs}`);
            }

            // Use backend drift calculation if available
            if (useApiImu) {
                if (imuLatest?.drift_len_mm !== undefined && imuLatest?.drift_dir !== undefined) {
                    setText('val-imu-drift-len', `${safeNumber((parseFloat(imuLatest.drift_len_mm) || 0) / 10, 1)} cm`);
                    setText('val-imu-drift-dir', `(${imuLatest.drift_dir})`);

                    // Update realtime 3D if active
                    if (realtimeImuActive && realtimeImuSensorBlock && _THREE) {
                        const currPitch = (imuLatest.pitch || 0) * Math.PI / 180;
                        const currRoll = (imuLatest.roll || 0) * Math.PI / 180;
                        const targetQuaternion = new _THREE.Quaternion();
                        const euler = new _THREE.Euler(currPitch, 0, currRoll, 'XYZ');
                        targetQuaternion.setFromEuler(euler);
                        realtimeImuTargetQuaternion = targetQuaternion;
                    }
                } else {
                    updateImuDrift(imuLatest?.roll, imuLatest?.pitch);
                }
            }
        } else {
            setText('val-imu-roll', '--°');
            setText('val-imu-pitch', '--°');
            setText('val-imu-yaw', '--°');
            setText('val-imu-delta-roll', '-- mm');
            setText('val-imu-delta-pitch', '-- mm');
            setText('val-imu-delta-yaw', '-- mm');
            updateImuDrift(null, null);
        }

        // ✅ GNSS Adjusted Cache Rendering
        const adjResultsSection = document.getElementById('adj-results-section');
        const adjStatusEl = document.getElementById('adj-process-status');
        const adjTimeEl = document.getElementById('adj-val-time');
        const adjPointsList = document.getElementById('adj-points-list');
        
        const adjCached = data.sensors?.gnss_adjusted;
        if (
            adjCached
            && adjCached.latest
            && isGnssAdjustmentResultRelevant(adjCached.latest, adjCached.latest_timestamp)
        ) {
            const cacheData = adjCached.latest;
            pendingGnssAdjustmentResult = cacheData;
            const terminalVisible = document.getElementById('gnssTerminalModal')?.classList.contains('show');
            if (terminalVisible) window.gnssBoardState?.loadAdjustmentResult?.(cacheData);
            if (adjStatusEl) {
                adjStatusEl.innerHTML = `<span class="text-success fw-bold"><i class="bi bi-check-circle-fill me-1"></i>Bình sai thành công (Đã lưu)</span>`;
            }
            if (adjTimeEl && adjCached.latest_timestamp) {
                adjTimeEl.textContent = new Date(adjCached.latest_timestamp * 1000).toLocaleString();
            }
            if (adjResultsSection) {
                adjResultsSection.style.display = 'block';
            }
            if (adjPointsList) {
                adjPointsList.innerHTML = '';
                
                if (cacheData.points) {
                    for (const [ptName, ptCoords] of Object.entries(cacheData.points)) {
                        const coordinates = getAdjustedPointCoordinates(ptCoords);
                        const item = document.createElement('div');
                        item.className = 'list-group-item bg-transparent text-slate-300 py-1.5 px-0 d-flex justify-content-between align-items-center border-bottom border-white/5';
                        item.innerHTML = `
                            <span class="fw-semibold text-teal-400 font-monospace">${ptName}</span>
                            <span class="text-glow font-monospace text-end" style="font-size:0.68rem; line-height: 1.2;">
                                X: ${formatAdjustedCoordinate(coordinates[0])}<br>
                                Y: ${formatAdjustedCoordinate(coordinates[1])}<br>
                                Z: ${formatAdjustedCoordinate(coordinates[2])}
                            </span>
                        `;
                        adjPointsList.appendChild(item);
                    }
                }
            }
            if (terminalVisible) window.gnssBoardState?.fitToResult?.();
        } else {
            pendingGnssAdjustmentResult = null;
            if (adjResultsSection) adjResultsSection.style.display = 'none';
            if (adjPointsList) adjPointsList.innerHTML = '';
        }

        // ✅ Battery Voltage: chỉ hiển thị khi IMU online và có giá trị > 0
        const batteryContainer = document.getElementById('battery-container');
        const batteryVal = imuLatest?.battery;
        if (imuOnline && batteryVal !== undefined && batteryVal !== null && parseFloat(batteryVal) > 0) {
            if (batteryContainer) batteryContainer.style.display = '';
            setHTML('val-battery', `${safeNumber(batteryVal, 2)}<span class="sensor-unit">V</span>`);
        } else {
            if (batteryContainer) batteryContainer.style.display = 'none';
        }
    }
}

function destroyStationCharts() {
    ['chart-gnss', 'chart-rain', 'chart-water', 'chart-imu'].forEach(id => {
        if (!charts[id]) return;
        charts[id].destroy();
        delete charts[id];
    });
}

function renderCharts(data) {
    if (!data.sensors) return;

    console.log('📊 [CHARTS] Rendering charts for station devices...');

    // Show charts based on DEVICE presence, not data existence
    const allChartIds = ['chart-box-gnss', 'chart-box-rain', 'chart-box-water', 'chart-box-imu'];
    const activeChartBoxIds = [];

    // GNSS
    if (data.sensors.gnss) {
        activeChartBoxIds.push('chart-box-gnss');
        const history = data.sensors.gnss.history || [];
        // Compute velocity from vel_e/vel_n components (đã qua bộ lọc zeroing, khớp sidebar)
        const gnssHistory = history.map(h => ({
            timestamp: h.timestamp,
            data: {
                ...h.data,
                _chart_velocity: getGnssVelocity(h.data)
            }
        })).filter(h => h.data._chart_velocity !== null);
        renderChart('chart-gnss', gnssHistory, '_chart_velocity', '#fa5252', 'Velocity (mm/s)');
    }

    // Rain
    if (data.sensors.rain) {
        activeChartBoxIds.push('chart-box-rain');
        const history = data.sensors.rain.history || [];
        renderChart('chart-rain', history, 'intensity_mm_h', '#06b6d4', 'Intensity (mm/h)');
    }

    // Water
    if (data.sensors.water) {
        activeChartBoxIds.push('chart-box-water');
        const history = data.sensors.water.history || [];
        renderChart('chart-water', history, 'water_level', '#10b981', 'Level (m)');
    }

    // IMU (3-axis)
    if (data.sensors.imu) {
        activeChartBoxIds.push('chart-box-imu');
        renderImuChart(data.sensors.imu.history || []);
    }

    // Show/hide chart boxes
    allChartIds.forEach(chartBoxId => {
        const chartBox = document.getElementById(chartBoxId);
        if (chartBox) {
            chartBox.style.display = activeChartBoxIds.includes(chartBoxId) ? 'block' : 'none';
        }
    });

    // Show empty state if no sensors at all
    const emptyState = document.getElementById('charts-empty-state');
    if (emptyState) {
        emptyState.style.display = activeChartBoxIds.length === 0 ? 'block' : 'none';
    }

    console.log(`✅ [CHARTS] Rendered ${activeChartBoxIds.length} charts`);
}

function renderChart(id, history, key, color, label) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const labels = (history || []).map(h => {
        const date = new Date(h.timestamp * 1000);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });

    const values = (history || []).map(h => {
        const val = h.data?.[key];
        if (val === null || val === undefined || val === '') return null;
        const num = parseFloat(val);
        return Number.isFinite(num) ? num : null;
    });
    const numericValues = values.filter(value => value !== null);

    // Cập nhật chỉ số thống kê
    if (numericValues.length > 0) {
        const maxVal = Math.max(...numericValues);
        const minVal = Math.min(...numericValues);
        const avgVal = numericValues.reduce((a, b) => a + b, 0) / numericValues.length;
        const latestVal = numericValues[numericValues.length - 1];

        const elLatest = document.getElementById(`stat-${id}-latest`);
        const elMax = document.getElementById(`stat-${id}-max`);
        const elMin = document.getElementById(`stat-${id}-min`);
        const elAvg = document.getElementById(`stat-${id}-avg`);

        if (elLatest) elLatest.innerText = latestVal.toFixed(2);
        if (elMax) elMax.innerText = maxVal.toFixed(2);
        if (elMin) elMin.innerText = minVal.toFixed(2);
        if (elAvg) elAvg.innerText = avgVal.toFixed(2);
    } else {
        const elLatest = document.getElementById(`stat-${id}-latest`);
        const elMax = document.getElementById(`stat-${id}-max`);
        const elMin = document.getElementById(`stat-${id}-min`);
        const elAvg = document.getElementById(`stat-${id}-avg`);
        
        if (elLatest) elLatest.innerText = '--';
        if (elMax) elMax.innerText = '--';
        if (elMin) elMin.innerText = '--';
        if (elAvg) elAvg.innerText = '--';
    }

    if (charts[id]) {
        charts[id].destroy();
    }

    // Theme-aware colors
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const gridColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)';
    const tickColor = isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.4)';

    // Extract RGB from hex for gradient
    let r = 13, g = 110, b = 253; // Default blue
    if (color.startsWith('#') && color.length === 7) {
        r = parseInt(color.slice(1, 3), 16);
        g = parseInt(color.slice(3, 5), 16);
        b = parseInt(color.slice(5, 7), 16);
    }
    
    let gradient = ctx.createLinearGradient(0, 0, 0, 300);
    gradient.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.5)`);
    gradient.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0.0)`);

    charts[id] = new Chart(canvas, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: label,
                data: values,
                borderColor: color,
                backgroundColor: gradient,
                fill: true,
                tension: 0.4,
                borderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 4,
                pointBackgroundColor: color,
                pointBorderColor: '#fff',
                pointBorderWidth: 1.5,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: { 
                legend: { display: false },
                tooltip: {
                    backgroundColor: isDark ? 'rgba(15, 23, 42, 0.9)' : 'rgba(255, 255, 255, 0.9)',
                    titleColor: isDark ? '#fff' : '#1e293b',
                    bodyColor: isDark ? '#cbd5e1' : '#475569',
                    borderColor: isDark ? '#334155' : '#e2e8f0',
                    borderWidth: 1,
                    padding: 10,
                    boxPadding: 4,
                    usePointStyle: true,
                }
            },
            scales: {
                x: { 
                    display: true,
                    grid: { display: false },
                    ticks: {
                        color: tickColor,
                        maxTicksLimit: 6,
                        maxRotation: 0
                    }
                },
                y: {
                    grid: { 
                        color: gridColor,
                        borderDash: [5, 5],
                        drawBorder: false
                    },
                    ticks: { 
                        color: tickColor,
                        padding: 8
                    },
                    beginAtZero: true
                }
            }
        }
    });
}

function renderImuChart(history) {
    const ctx = document.getElementById('chart-imu');
    if (!ctx) return;

    const labels = (history || []).map(h => {
        const date = new Date(h.timestamp * 1000);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });

    const rollData = (history || []).map(h => parseFloat(h.data?.roll) || 0);
    const pitchData = (history || []).map(h => parseFloat(h.data?.pitch) || 0);
    const yawData = (history || []).map(h => parseFloat(h.data?.yaw) || 0);

    if (charts['chart-imu']) {
        charts['chart-imu'].destroy();
    }

    // Theme-aware colors
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const gridColor = isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)';
    const tickColor = isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.5)';
    const legendColor = isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.6)';

    charts['chart-imu'] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Roll (°)',
                    data: rollData,
                    borderColor: '#ff6384',
                    backgroundColor: 'rgba(255, 99, 132, 0.08)',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                    fill: true
                },
                {
                    label: 'Pitch (°)',
                    data: pitchData,
                    borderColor: '#4bc0c0',
                    backgroundColor: 'rgba(75, 192, 192, 0.08)',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                    fill: true
                },
                {
                    label: 'Yaw (°)',
                    data: yawData,
                    borderColor: '#36a2eb',
                    backgroundColor: 'rgba(54, 162, 235, 0.08)',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    display: true,
                    labels: {
                        color: legendColor,
                        usePointStyle: true,
                        pointStyle: 'circle',
                        font: { size: 11 }
                    }
                }
            },
            scales: {
                x: { display: false },
                y: {
                    grid: { color: gridColor },
                    ticks: {
                        color: tickColor,
                        callback: (v) => v + '°'
                    }
                }
            }
        }
    });
}

