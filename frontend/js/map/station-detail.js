/* global stationHistoryController:writable, currentStationData:writable, stationSelectionSequence:writable, stationSelectionController:writable, realtimeImuTargetQuaternion:writable */
// =====================================================
const CHART_SENSOR_TYPES = Object.freeze(window.sensorTypes?.() || ['gnss', 'rain', 'water', 'imu']);
const CHART_RANGE_OPTIONS = Object.freeze([
    { hours: 24, label: '24 giờ' },
    { hours: 24 * 7, label: '7 ngày' },
    { hours: 24 * 30, label: '30 ngày' },
    { hours: 24 * 365, label: '1 năm' },
]);
let activeChartHours = 24;

function getChartRange(hours = activeChartHours) {
    return CHART_RANGE_OPTIONS.find(option => option.hours === Number(hours)) || CHART_RANGE_OPTIONS[0];
}

function getChartHistoryLimit(hours) {
    if (hours <= 24) return 500;
    if (hours <= 24 * 7) return 1000;
    if (hours <= 24 * 30) return 1500;
    return 2000;
}

function getChartableSensorTypes(data) {
    const sensors = data?.sensors || {};
    return [...CHART_SENSOR_TYPES, ...Object.keys(data?.config?.custom_sensors || {})].filter(sensorType => (
        sensors[sensorType] && typeof sensors[sensorType] === 'object'
    ));
}

function stationSensorCatalog(data) {
    const catalog = window.SensorCatalog || [];
    const custom = Object.values(data?.config?.custom_sensors || {}).filter(spec =>
        spec && /^custom_[0-9a-f]{12}$/.test(spec.key) && Array.isArray(spec.fields)
    );
    return [...catalog, ...custom.filter(spec => !catalog.some(item => item.key === spec.key))];
}

function updateChartRangeControls(hours = activeChartHours) {
    activeChartHours = getChartRange(hours).hours;
    const range = getChartRange(activeChartHours);
    const period = document.querySelector('.charts-period');
    if (period) period.textContent = range.label;
    document.querySelectorAll('[data-chart-hours]').forEach(button => {
        const active = Number(button.dataset.chartHours) === activeChartHours;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
    });
}

function updateChartsAvailability(data) {
    const chartButton = document.getElementById('btn-show-charts');
    const chartPanel = document.getElementById('charts-panel');
    const actionButtons = chartButton?.closest('.action-buttons');
    const longTermButton = document.getElementById('btn-long-term');
    const hasCharts = getChartableSensorTypes(data).length > 0;
    const hasOtherAction = Boolean(
        longTermButton
        && !longTermButton.classList.contains('d-none')
        && longTermButton.style.display !== 'none'
    );

    if (chartButton) {
        chartButton.hidden = !hasCharts;
        chartButton.disabled = !hasCharts;
        chartButton.setAttribute('aria-hidden', String(!hasCharts));
    }
    if (actionButtons) actionButtons.style.display = hasCharts || hasOtherAction ? '' : 'none';

    if (!hasCharts) {
        setChartsPanelOpen(chartPanel, false);
        destroyStationCharts();
    }
}

function _resolvePiDeviceStatuses(data) {
    let pointDeviceStatus = 'idle';
    let centerDeviceStatus = 'idle';
    if (data.pi_devices && Array.isArray(data.pi_devices)) {
        const pPoint = data.pi_devices.find(d => d.device_type === 'pi_point');
        const pCenter = data.pi_devices.find(d => d.device_type === 'pi_center');
        if (pPoint && !pPoint.is_online) pointDeviceStatus = 'offline';
        if (pCenter && !pCenter.is_online) centerDeviceStatus = 'offline';
    }
    return { pointDeviceStatus, centerDeviceStatus };
}

function _updateSirenButtonsForAlert(centerDeviceStatus, pointDeviceStatus) {
    document.querySelectorAll('.btn-siren-toggle').forEach(b => {
        const target = b.dataset.target;
        const isOffline = target === 'pi_center' ? centerDeviceStatus === 'offline' : pointDeviceStatus === 'offline';
        if (isOffline) {
            setSirenButtonState('offline', target);
        } else {
            let currentState = b.dataset.sirenState;
            if (currentState === 'idle' || currentState === 'offline') currentState = 'alerting';
            setSirenButtonState(currentState, target);
        }
    });
}

// SIREN POPUP HELPER — Dùng bởi selectStation và Track button
// =====================================================
function _showSirenIfAlerting(stationId, data) {
    const sirenSection = document.getElementById('siren-sidebar-section');
    const user = window.authManager?.getUserInfo();
    const userRole = user?.role;
    if (userRole !== 'admin' && userRole !== 'operator') {
        if (sirenSection) sirenSection.style.display = 'none';
        return;
    }
    if (sirenSection) sirenSection.style.display = '';

    const risk = data.risk_assessment?.overall_risk || data.risk_level;
    const isAlerting = (risk === 'EXTREME' || risk === 'CRITICAL') && data.status === 'online';
    const { pointDeviceStatus, centerDeviceStatus } = _resolvePiDeviceStatuses(data);

    if (isAlerting) {
        window.currentAlertStationId = stationId;
        _updateSirenButtonsForAlert(centerDeviceStatus, pointDeviceStatus);
    } else {
        if (window.currentAlertStationId === stationId) {
            window.currentAlertStationId = null;
        }
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

async function fetchStationHistory(stationId, { hours = activeChartHours, sensorTypes = [], signal } = {}) {
    const params = new URLSearchParams({
        hours: String(hours),
        limit: String(getChartHistoryLimit(hours)),
    });
    if (sensorTypes.length) params.set('sensor_types', sensorTypes.join(','));
    const url = `/api/stations/${stationId}/history?${params.toString()}`;
    const requestOptions = signal ? { signal } : {};
    const response = window.authManager?.isAuthenticated?.()
        ? await window.authManager.apiFetch(url, requestOptions)
        : await fetch(url, requestOptions);
    if (!response?.ok) throw new Error('Failed to load station history');
    return response.json();
}

function focusMapOnStation(stationId, skipZoom = false) {
    if (window.MapboxGlobeController?.active && !skipZoom) {
        const station = (allStations || []).find(s => Number(s.id) === Number(stationId));
        const lat = Number(station?.location?.lat ?? station?.latitude);
        const lon = Number(station?.location?.lon ?? station?.longitude);
        if (Number.isFinite(lat) && Number.isFinite(lon)) {
            window.MapboxGlobeController.flyTo(lat, lon, 14);
        }
    }

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

function _setChartControlsLoading(isLoading, chartsButton, chartsPanel) {
    if (isLoading) {
        chartsPanel?.classList.add('station-history-loading');
        setChartWorkspaceStatus('Đang tải lịch sử cảm biến…', 'loading');
    } else {
        chartsPanel?.classList.remove('station-history-loading');
    }
    if (chartsButton) chartsButton.disabled = isLoading;
    document.querySelectorAll('[data-chart-hours]').forEach(button => { button.disabled = isLoading; });
}

function _mergeStationSensorHistory(currentData, historyPayload, sensorTypes, rangeLabel) {
    const data = {
        ...currentData,
        _chartRangeLabel: rangeLabel,
        sensors: Object.fromEntries(Object.entries(currentData.sensors).map(([type, sensor]) => [
            type, sensorTypes.includes(type) ? { ...sensor, history: [] } : sensor
        ])),
    };
    Object.entries(historyPayload.sensors || {}).forEach(([sensorType, sensorHistory]) => {
        if (!sensorTypes.includes(sensorType)) return;
        data.sensors[sensorType] = {
            ...data.sensors[sensorType],
            history: sensorHistory.history || [],
        };
    });
    return data;
}

function _handleStationHistoryError(error, controller, range, chartsPanel) {
    if (stationHistoryController !== controller || controller.signal.aborted || error?.name === 'AbortError') return;
    console.error('[MAP] Error loading station history:', error);
    const retained = Object.values(charts).some(chart => chart.data.datasets.some(dataset => dataset.data.length));
    let retainedMsg = '';
    if (retained) {
        const rangeSuffix = chartsPanel?.dataset.rangeLabel ? ` (${chartsPanel.dataset.rangeLabel})` : '';
        retainedMsg = ` Đang giữ dữ liệu đã tải${rangeSuffix}; chưa cập nhật.`;
    }
    setChartWorkspaceStatus(`Không tải được dữ liệu ${range.label}.${retainedMsg} Bấm tải lại để thử tiếp.`, 'error');
    window.toast?.error('Không tải được lịch sử biểu đồ');
}

async function loadStationHistoryAndRenderCharts({ hours = activeChartHours, force = false } = {}) {
    const stationId = Number(currentStationData?.id || 0);
    if (!stationId) return;
    const range = getChartRange(hours);
    const sensorTypes = getChartableSensorTypes(currentStationData);
    updateChartRangeControls(range.hours);
    if (!sensorTypes.length) {
        updateChartsAvailability(currentStationData);
        return;
    }
    const chartsPanel = document.getElementById('charts-panel');
    const chartsButton = document.getElementById('btn-show-charts');
    const cacheKey = `${stationId}:${range.hours}`;
    const cached = stationHistoryCache.get(cacheKey);
    stationHistoryController?.abort();
    const controller = new AbortController();
    stationHistoryController = controller;
    if (!force && cached && Date.now() - cached.loadedAt < STATION_HISTORY_CACHE_MS) {
        renderCharts(cached.data);
        _setChartControlsLoading(false, chartsButton, chartsPanel);
        return;
    }

    _setChartControlsLoading(true, chartsButton, chartsPanel);
    try {
        const historyPayload = await fetchStationHistory(stationId, {
            hours: range.hours,
            sensorTypes,
            signal: controller.signal,
        });
        if (controller.signal.aborted || stationHistoryController !== controller || Number(currentStationData?.id || 0) !== stationId) return;
        const data = _mergeStationSensorHistory(currentStationData, historyPayload, sensorTypes, range.label);
        stationHistoryCache.set(cacheKey, { data, loadedAt: Date.now() });
        currentStationData = data;
        renderCharts(data);
    } catch (error) {
        _handleStationHistoryError(error, controller, range, chartsPanel);
    } finally {
        if (stationHistoryController === controller) {
            _setChartControlsLoading(false, chartsButton, chartsPanel);
        }
    }
}

function _updateStationItemSelection(stationId) {
    document.querySelectorAll('.station-item[data-station-id]').forEach(item => {
        const selected = Number(item.dataset.stationId) === Number(stationId);
        item.classList.toggle('selected', selected);
        if (selected) item.setAttribute('aria-current', 'true');
        else item.removeAttribute('aria-current');
    });
}

function _restoreSilentAlertBanner(data, skipBannerRestore) {
    const _banner = document.getElementById('alert-banner');
    const _riskLevel = data.risk_assessment?.overall_risk || data.risk_level || 'LOW';
    const _riskBand = normalizeRiskLevel(_riskLevel, data.status);
    const _activeAlerts = data.risk_assessment?.active_alerts || [];
    const _freshAlerts = data.risk_assessment?.fresh_alerts || _activeAlerts.filter(alert => !alert?.stale);
    const _staleAlerts = data.risk_assessment?.stale_alerts || _activeAlerts.filter(alert => alert?.stale);
    const _canRestoreFresh = (_riskBand === 'MEDIUM' || _riskBand === 'CRITICAL') &&
        _freshAlerts.length > 0 && data.status !== 'offline';
    const _canRestoreStale = _riskBand === 'STALE' && _staleAlerts.length > 0 && data.status === 'stale';

    if (!_banner?.classList.contains('show') &&
        !skipBannerRestore &&
        !isBannerSuppressed(data.id) &&
        (_canRestoreFresh || _canRestoreStale)) {
        const _alertsForBanner = _canRestoreFresh ? _freshAlerts : _staleAlerts;
        const _topAlert = _alertsForBanner.find(a => a.level === 'CRITICAL') || _alertsForBanner[0];
        showAlertBanner({
            station_id: data.id,
            level: _topAlert.level,
            message: _topAlert.stale ? `Chưa xác minh sau mất kết nối: ${_topAlert.message}` : _topAlert.message,
            sensor_type: mapAlertCategoryToSensorType(_topAlert.category)
        }, { silent: true });
        _showSirenIfAlerting(data.id, data);
    }
}

async function selectStation(stationId, options = {}) {
    if (currentMapMode === 'rescue') {
        return;
    }
    if (window.MapboxGlobeController) {
        window.MapboxGlobeController.clearProvinceSelection?.();
        window.MapboxGlobeController.popup?.remove?.();
    }
    const chartsPanel = document.getElementById('charts-panel');
    setChartsPanelOpen(chartsPanel, false);
    destroyStationCharts();
    const advancedPanel = document.getElementById('gnss-advanced-sidepanel');
    if (advancedPanel?.classList.contains('active') && Number(currentStationData?.id) !== Number(stationId)) {
        setGnssAdvancedPanelOpen(advancedPanel, false);
    }
    setMapState({ selectedStation: Number(stationId) });

    _updateStationItemSelection(stationId);

    const { skipZoom = false, skipSiren = false, skipBannerRestore = false } = options;
    const selectionId = ++stationSelectionSequence;
    stationSelectionController?.abort();
    stationHistoryController?.abort();
    stationSelectionController = new AbortController();
    syncWebSocketSubscription(stationId);
    console.log(`🎯 [MAP] Selecting station: ${stationId}`, options);

    const sidebar = document.getElementById('detail-sidebar');
    if (sidebar) {
        sidebar.scrollTop = 0;
        sidebar.classList.add('station-selecting');
        setDetailSidebarOpen(sidebar, true);
        sidebar.setAttribute('aria-busy', 'true');
    }
    resetStationSensorCards();
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
        _restoreSilentAlertBanner(data, skipBannerRestore);

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

function formatGnssVelocityValue(value, _data, decimals = 4) {
    return safeNumber(value, decimals);
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
    const velU = toFinite(data.vel_u);
    if (velE !== null && velN !== null) {
        if (velU !== null) {
            return Math.sqrt(Math.pow(velE, 2) + Math.pow(velN, 2) + Math.pow(velU, 2));
        }
        return Math.sqrt(Math.pow(velE, 2) + Math.pow(velN, 2));
    }

    for (const key of ['velocity_3d_mm_s', 'velocity_mm_s', 'speed_2d_mm_s', 'speed_mm_s']) {
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

    const num = Number.parseFloat(value);
    if (Number.isNaN(num)) {
        return defaultValue;
    }

    return num.toFixed(decimals);
}

function _parseWaterLevelFromDisplay(displayRaw, unitRaw) {
    if (Number.isNaN(displayRaw)) return null;
    if (unitRaw === 'mm') {
        return displayRaw < 10 ? displayRaw * 100 : displayRaw / 10;
    }
    if (unitRaw === 'm' || unitRaw === 'meter' || unitRaw === 'meters') {
        return displayRaw * 100;
    }
    if (unitRaw === 'cm') {
        return displayRaw;
    }
    return null;
}

function _parseWaterLevelFallback(waterLatest) {
    const cmRaw = Number.parseFloat(waterLatest?.water_level_cm);
    if (!Number.isNaN(cmRaw)) return cmRaw;
    const meterRaw = Number.parseFloat(waterLatest?.water_level ?? waterLatest?.processed_value_meters);
    if (!Number.isNaN(meterRaw)) return meterRaw * 100;
    return null;
}

function formatWaterLevelDisplay(waterLatest) {
    if (waterLatest?.is_fallback === true) {
        return `--<span class="sensor-unit">cm</span>`;
    }

    const unitRaw = String(waterLatest?.water_display_unit || '').trim().toLowerCase();
    const displayRaw = Number.parseFloat(waterLatest?.water_display_value);
    const levelCm = _parseWaterLevelFromDisplay(displayRaw, unitRaw) ?? _parseWaterLevelFallback(waterLatest);

    if (levelCm === null) {
        return `--<span class="sensor-unit">cm</span>`;
    }

    if (Math.abs(levelCm) >= 100) {
        return `${safeNumber(levelCm / 100, 2)}<span class="sensor-unit">m</span>`;
    }

    return `${safeNumber(levelCm, 1)}<span class="sensor-unit">cm</span>`;
}

function formatImuDelta(val, axis) {
    const num = Number.parseFloat(val);
    if (Number.isNaN(num)) return '-- cm';
    const dispMm = Math.sin(num * Math.PI / 180) * 0.09 * 1000; // mm
    const sign = dispMm > 0 ? '+' : '';
    // Ưu tiên cm; chỉ dùng mm khi |giá trị| < 1 cm
    const absMm = Math.abs(dispMm);
    let displayVal;
    let unit;
    if (absMm >= 10) {
        displayVal = (dispMm / 10).toFixed(2);
        unit = 'cm';
    } else {
        displayVal = dispMm.toFixed(1);
        unit = 'mm';
    }
    const threshold = unit === 'cm' ? 0.05 : 0.5;
    const positiveArrows = { roll: ' →', pitch: ' ↑', yaw: ' ↻' };
    const negativeArrows = { roll: ' ←', pitch: ' ↓', yaw: ' ↺' };
    let arrow = '';
    if (dispMm > threshold) {
        arrow = positiveArrows[axis] || '';
    } else if (dispMm < -threshold) {
        arrow = negativeArrows[axis] || '';
    }
    return `${sign}${displayVal} ${unit}${arrow}`;
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

function updateGnssIntegrityStatus(payload) {
    const integrity = payload?.integrity || payload?.data || payload;
    if (!integrity?.integrity_state) return;

    const section = document.getElementById('gnss-integrity-section');
    const badge = document.getElementById('gnss-integrity-badge');
    const shiftGrid = document.getElementById('gnss-integrity-shift-grid');
    if (!section || !badge) return;

    const state = String(integrity.integrity_state).toUpperCase();
    const presentation = {
        TRACKING_NORMAL: ['normal', 'THEO DÕI BÌNH THƯỜNG'],
        REFERENCE_TRANSITION: ['transition', 'ĐANG KIỂM TRA MỐC'],
        TRACKING_REACQUIRED: ['reacquired', 'ĐÃ BÙ MỐC THAM CHIẾU'],
        UNVERIFIED_POSITION_SHIFT: ['unverified', 'DỊCH CHUYỂN CHƯA XÁC MINH'],
        UNTRUSTED_GEOMETRY: ['geometry', 'LOẠI DO HÌNH HỌC'],
    }[state] || ['unknown', state.replaceAll('_', ' ')];
    const metric = (value, suffix = 'm') => Number.isFinite(Number(value)) ? `${Number(value).toFixed(3)} ${suffix}` : '--';
    const eventTs = Number(integrity.reference_event_timestamp);
    const normalTracking = state === 'TRACKING_NORMAL';

    section.dataset.state = presentation[0];
    badge.textContent = presentation[1];
    setText(
        'gnss-integrity-message',
        normalTracking
            ? 'Tọa độ đạt điều kiện theo dõi; chưa có sự kiện mốc hoặc dịch chuyển cần bù.'
            : payload?.message || integrity.message || 'Đang cập nhật đánh giá toàn vẹn GNSS.'
    );
    if (shiftGrid) shiftGrid.hidden = normalTracking;
    setText('gnss-shift-e', metric(integrity.shift_e_m));
    setText('gnss-shift-n', metric(integrity.shift_n_m));
    setText('gnss-shift-u', metric(integrity.shift_u_m));
    setText('gnss-shift-mag', Number.isFinite(Number(integrity.shift_2d_m))
        ? `${metric(integrity.shift_2d_m)} / ${metric(integrity.shift_3d_m)}` : '--');
    setText('gnss-shift-spread', Number.isFinite(Number(integrity.spread_xy_m))
        ? `${metric(integrity.spread_xy_m)} / ${metric(integrity.spread_u_m)}` : '--');
    setText('gnss-shift-duration', Number.isFinite(Number(integrity.duration_s)) ? `${Number(integrity.duration_s).toFixed(1)} s` : '--');
    let refEventText = 'Không có';
    if (integrity.reference_event_verified) {
        const timeSuffix = Number.isFinite(eventTs)
            ? ` · ${new Date(normalizeEpochMs(eventTs)).toLocaleTimeString('vi-VN')}`
            : '';
        refEventText = `Đã xác minh${timeSuffix}`;
    } else if (integrity.possible_ground_movement) {
        refEventText = 'Chưa xác minh · có thể là chuyển vị đất';
    }
    setText('gnss-reference-event', refEventText);
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

function clearGnssEvaluationSummary() {
    const summary = document.getElementById('gnss-eval-summary');
    if (!summary) return;
    summary.replaceChildren();
    summary.style.display = 'none';
}

function resetStationSensorCards() {
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
    updateGnssFixBadge('NO_DATA', 0);
    document.getElementById('gnss-fix-badge')?.style.setProperty('display', '');
    ['gnss', 'rain', 'water', 'imu'].forEach(sensorType => {
        document.getElementById(`${sensorType}-offline-badge`)?.style.setProperty('display', 'none');
    });
    clearGnssEvaluationSummary();
}

function _renderSensorCardStatusText(sensor, mqttConnected) {
    if (!sensor.latest) return 'Chưa có dữ liệu';
    if (sensor.is_online && mqttConnected) return 'Đang nhận dữ liệu';
    return 'Dữ liệu cuối · mất kết nối';
}

function _renderSensorCardMetrics(card, spec, sensor) {
    const metrics = spec.key === 'extensometer'
        ? Object.keys(sensor.latest?.points || {}).map(field => ({field, label: `Điểm ${field}`, unit: spec.unit, decimals:3}))
        : (spec.metrics || spec.fields.map(field => ({field, label: field.toUpperCase(), unit: spec.unit, decimals:4})));
    const optional = (spec.optional_metrics || []).filter(metric => sensor.latest?.[metric.field] !== undefined);
    for (const metric of [...metrics, ...optional]) {
        const field = metric.field;
        const row = document.createElement('div');
        const value = spec.key === 'extensometer' ? sensor.latest.points[field] : sensor.latest?.[field];
        const actualValue = optional.includes(metric) ? sensor.latest?.[field] : value;
        const numeric = sensor.latest?.quality !== 'invalid' && typeof actualValue === 'number' && Number.isFinite(actualValue);
        row.textContent = `${metric.label}: ${numeric ? actualValue.toLocaleString('vi-VN', {maximumFractionDigits: metric.decimals}) : '—'} ${metric.unit}`;
        card.append(row);
    }
}

function _renderSensorCardDetails(card, spec, sensor) {
    for (const text of [spec.note, sensor.latest?.location_label, sensor.latest?.axis_convention,
        sensor.latest?.reference_id && `Mốc: ${sensor.latest.reference_id}`,
        sensor.latest?.serial_number && `Thiết bị: ${sensor.latest.serial_number}`,
        sensor.latest?.calibration_id && `Hiệu chuẩn: ${sensor.latest.calibration_id}`,
        sensor.latest?.event_id && `Sự kiện: ${sensor.latest.event_id}`]) {
        if (!text) continue;
        const detail = document.createElement('small');
        detail.textContent = text;
        card.append(detail);
    }
    if (sensor.latest?.measured_at) {
        const measured = document.createElement('small');
        measured.textContent = `Đo: ${new Date(sensor.latest.measured_at * 1000).toLocaleString('vi-VN')}`;
        card.append(measured);
    }
    if (sensor.latest_timestamp) {
        const timestamp = document.createElement('small');
        timestamp.textContent = `Nhận: ${new Date(sensor.latest_timestamp * 1000).toLocaleString('vi-VN')}`;
        card.append(timestamp);
    }
}

function _buildMonitoringSensorCard(spec, sensor, mqttConnected) {
    const card = document.createElement('section');
    card.className = 'monitoring-value-card';

    const title = document.createElement('strong');
    title.textContent = spec.label;
    card.append(title);

    const status = document.createElement('small');
    status.textContent = _renderSensorCardStatusText(sensor, mqttConnected);
    card.append(status);

    const quality = document.createElement('small');
    quality.textContent = ({valid:'Chất lượng: hợp lệ', suspect:'Chất lượng: cần kiểm tra', invalid:'Chất lượng: không hợp lệ'})[sensor.latest?.quality] || 'Chất lượng: chưa xác định';
    card.append(quality);

    _renderSensorCardMetrics(card, spec, sensor);
    _renderSensorCardDetails(card, spec, sensor);
    return card;
}

function renderMonitoringSensors(data) {
    const container = document.getElementById('monitoring-sensor-values');
    if (!container) return;
    container.replaceChildren();
    const mqttConnected = data.mqtt_connected !== false;
    for (const spec of stationSensorCatalog(data).filter(sensor => !sensor.legacy)) {
        const sensor = data.sensors?.[spec.key];
        if (sensor) {
            container.append(_buildMonitoringSensorCard(spec, sensor, mqttConnected));
        }
    }
}

function _determineSensorOnlineStates(data, effectiveStatus, isOfflineDisplayEnabled) {
    const gnssLatest = data.sensors?.gnss?.latest;
    const rainLatest = data.sensors?.rain?.latest;
    const waterLatest = data.sensors?.water?.latest;
    const imuLatest = data.sensors?.imu?.latest;
    const mqttConnected = data.mqtt_connected !== false;
    const isStationOffline = effectiveStatus === 'offline';
    const staleDisplay = (effectiveStatus === 'stale' || data.status === 'stale') && isOfflineDisplayEnabled;
    return {
        gnssOnline: mqttConnected && !isStationOffline && ((data.sensors?.gnss?.is_online ?? false) || (staleDisplay && !!gnssLatest)),
        rainOnline: mqttConnected && !isStationOffline && ((data.sensors?.rain?.is_online ?? false) || (staleDisplay && !!rainLatest)),
        waterOnline: mqttConnected && !isStationOffline && ((data.sensors?.water?.is_online ?? false) || (staleDisplay && !!waterLatest)),
        imuOnline: mqttConnected && !isStationOffline && ((data.sensors?.imu?.is_online ?? false) || (staleDisplay && !!imuLatest)),
    };
}

function _renderAdvancedGnssSidebar(adv, gnssOnline) {
    const gnssFixBadgeEl = document.getElementById('gnss-fix-badge');
    const gnssOfflineBadgeEl = document.getElementById('gnss-offline-badge');
    if (gnssOnline) {
        if (gnssFixBadgeEl) gnssFixBadgeEl.style.display = '';
        if (gnssOfflineBadgeEl) gnssOfflineBadgeEl.style.display = 'none';
        updateGnssFixBadge(adv?.fix_mode, adv?.fix_quality);
    } else {
        if (gnssFixBadgeEl) gnssFixBadgeEl.style.display = 'none';
        if (gnssOfflineBadgeEl) gnssOfflineBadgeEl.style.display = '';
    }
    updateGnssIntegrityStatus(adv);
    if (adv) {
        setText('adv-val-raw-ve', safeNumber(adv.raw_vel_e_mm_s, 4));
        setText('adv-val-raw-vn', safeNumber(adv.raw_vel_n_mm_s, 4));
        setText('adv-val-raw-vu', safeNumber(adv.raw_vel_u_mm_s, 4));
        setText('adv-val-raw-2d', safeNumber(adv.raw_speed_2d_mm_s, 4));
        setText('adv-val-filt-ve', formatGnssVelocityValue(adv.vel_e, adv, 4));
        setText('adv-val-filt-vn', formatGnssVelocityValue(adv.vel_n, adv, 4));
        setText('adv-val-filt-vu', formatGnssVelocityValue(adv.vel_u, adv, 4));
        setText('adv-val-filt-2d', formatGnssVelocityValue(adv.speed_2d_mm_s, adv, 4));
    }
    if (adv?.adv_x !== undefined) {
        setText('adv-val-lat', safeNumber(adv.adv_x, 3));
        setText('adv-val-lon', safeNumber(adv.adv_y, 3));
        setText('adv-val-alt', safeNumber(adv.adv_h ?? adv.h, 3));
        setText('adv-val-dx', safeNumber(adv.adv_dx, 2));
        setText('adv-val-dy', safeNumber(adv.adv_dy, 2));
        setText('adv-val-dh', safeNumber(adv.adv_dh, 2));
        setText('adv-val-vdx', formatGnssVelocityValue(adv.adv_vdx, adv, 4));
        setText('adv-val-vdy', formatGnssVelocityValue(adv.adv_vdy, adv, 4));
        setText('adv-val-vdh', formatGnssVelocityValue(adv.adv_vdh, adv, 4));
    }
}

function _renderSidebarSensorsOffline() {
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
    setSirenButtonState('idle');
    const batteryContainer = document.getElementById('battery-container');
    if (batteryContainer) batteryContainer.style.display = 'none';
}

function _renderSidebarSensorsOnline(data, states) {
    const { gnssOnline, rainOnline, waterOnline, imuOnline } = states;
    const gnssLatest = data.sensors?.gnss?.latest;
    const rainLatest = data.sensors?.rain?.latest;
    const waterLatest = data.sensors?.water?.latest;
    const imuLatest = data.sensors?.imu?.latest;
    const stationId = data.id;

    if (gnssOnline) {
        const gnssSpeed = getGnssVelocity(gnssLatest);
        setHTML('val-gnss-vel', `${safeNumber(gnssSpeed, 4)}<span class="sensor-unit">mm/s</span>`);
    } else {
        setHTML('val-gnss-vel', `--<span class="sensor-unit">mm/s</span>`);
    }

    if (rainOnline) {
        setHTML('val-rain', `${safeNumber(rainLatest?.intensity_mm_h ?? null, 1)}<span class="sensor-unit">mm/h</span>`);
    } else {
        setHTML('val-rain', `--<span class="sensor-unit">mm/h</span>`);
    }

    if (waterOnline) {
        setHTML('val-water', formatWaterLevelDisplay(waterLatest));
    } else {
        setHTML('val-water', `--<span class="sensor-unit">cm</span>`);
    }

    _renderSidebarImuSensor(stationId, data, imuLatest, imuOnline);
}

function _renderSidebarImuSensor(stationId, data, imuLatest, imuOnline) {
    if (!imuOnline) {
        setText('val-imu-roll', '--°');
        setText('val-imu-pitch', '--°');
        setText('val-imu-yaw', '--°');
        setText('val-imu-delta-roll', '-- mm');
        setText('val-imu-delta-pitch', '-- mm');
        setText('val-imu-delta-yaw', '-- mm');
        updateImuDrift(null, null);
        return;
    }
    const imuApiTs = Number(data.sensors?.imu?.latest_timestamp || 0);
    const imuRealtimeTs = Number(latestRealtimeSensorTs[`${stationId}_imu`] || 0);
    const useApiImu = !imuRealtimeTs || !imuApiTs || imuApiTs >= imuRealtimeTs;
    if (useApiImu) {
        setText('val-imu-roll', `${safeNumber(imuLatest?.raw_roll, 1)}°`);
        setText('val-imu-pitch', `${safeNumber(imuLatest?.raw_pitch, 1)}°`);
        setText('val-imu-yaw', `${safeNumber(imuLatest?.raw_yaw, 1)}°`);
        setText('val-imu-delta-roll', formatImuDelta(imuLatest?.roll, 'roll'));
        setText('val-imu-delta-pitch', formatImuDelta(imuLatest?.pitch, 'pitch'));
        setText('val-imu-delta-yaw', formatImuDelta(imuLatest?.yaw, 'yaw'));
        _updateImuDriftAnd3D(imuLatest);
    }
}

function _updateImuDriftAnd3D(imuLatest) {
    if (imuLatest?.drift_len_mm !== undefined && imuLatest?.drift_dir !== undefined) {
        const driftLengthMm = Number(imuLatest.drift_len_mm);
        setText(
            'val-imu-drift-len',
            Number.isFinite(driftLengthMm) ? `${safeNumber(driftLengthMm / 10, 1)} cm` : '-- cm'
        );
        setText('val-imu-drift-dir', `(${imuLatest.drift_dir})`);
        if (realtimeImuActive && realtimeImuSensorBlock && _THREE) {
            const pitch = Number(imuLatest.pitch);
            const roll = Number(imuLatest.roll);
            if (Number.isFinite(pitch) && Number.isFinite(roll)) {
                const targetQuaternion = new _THREE.Quaternion();
                targetQuaternion.setFromEuler(new _THREE.Euler(pitch * Math.PI / 180, 0, roll * Math.PI / 180, 'XYZ'));
                realtimeImuTargetQuaternion = targetQuaternion;
            }
        }
    } else {
        updateImuDrift(imuLatest?.roll, imuLatest?.pitch);
    }
}

function _populateAdjustedPointsList(adjPointsList, points) {
    adjPointsList.innerHTML = '';
    if (!points) return;
    for (const [ptName, ptCoords] of Object.entries(points)) {
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

function _renderBatteryStatus(imuLatest, imuOnline) {
    const batteryContainer = document.getElementById('battery-container');
    const batteryVal = imuLatest?.battery;
    if (imuOnline && batteryVal !== undefined && batteryVal !== null && Number.parseFloat(batteryVal) > 0) {
        if (batteryContainer) batteryContainer.style.display = '';
        setHTML('val-battery', `${safeNumber(batteryVal, 2)}<span class="sensor-unit">V</span>`);
    } else if (batteryContainer) {
        batteryContainer.style.display = 'none';
    }
}

function _applyGnssAdjustmentSectionUI(adjCached, cacheData, elements) {
    const { adjResultsSection, adjStatusEl, adjTimeEl, adjPointsList } = elements;
    window.pendingGnssAdjustmentResult = cacheData;
    const terminalVisible = document.getElementById('gnssTerminalModal')?.classList.contains('show');
    if (terminalVisible) window.gnssBoardState?.loadAdjustmentResult?.(cacheData);
    if (adjStatusEl) {
        adjStatusEl.innerHTML = `<span class="text-success fw-bold"><i class="bi bi-check-circle-fill me-1"></i>Bình sai thành công (Đã lưu)</span>`;
    }
    if (adjTimeEl && adjCached.latest_timestamp) {
        adjTimeEl.textContent = new Date(normalizeEpochMs(adjCached.latest_timestamp)).toLocaleString();
    }
    if (adjResultsSection) adjResultsSection.style.display = 'block';
    if (adjPointsList) _populateAdjustedPointsList(adjPointsList, cacheData.points);
    if (terminalVisible) window.gnssBoardState?.fitToResult?.();
}

function _clearGnssAdjustmentSectionUI(elements) {
    window.pendingGnssAdjustmentResult = null;
    if (elements.adjResultsSection) elements.adjResultsSection.style.display = 'none';
    if (elements.adjPointsList) elements.adjPointsList.innerHTML = '';
}

function _renderSidebarGnssAdjustedSection(data, imuLatest, imuOnline) {
    const elements = {
        adjResultsSection: document.getElementById('adj-results-section'),
        adjStatusEl: document.getElementById('adj-process-status'),
        adjTimeEl: document.getElementById('adj-val-time'),
        adjPointsList: document.getElementById('adj-points-list'),
    };
    const adjCached = data.sensors?.gnss_adjusted;
    if (adjCached?.latest && isGnssAdjustmentResultRelevant(adjCached.latest, adjCached.latest_timestamp)) {
        _applyGnssAdjustmentSectionUI(adjCached, adjCached.latest, elements);
    } else {
        _clearGnssAdjustmentSectionUI(elements);
    }

    _renderBatteryStatus(imuLatest, imuOnline);
}

function _renderStationRiskBadge(data, effectiveStatus) {
    const riskEl = document.getElementById('st-risk');
    if (!riskEl) return;
    const riskUi = getRiskPresentation(data.risk_assessment?.overall_risk || data.risk_level, effectiveStatus);
    riskEl.className = `status-badge ${riskUi.className}`;
    riskEl.innerHTML = `<span class="status-dot"></span> ${riskUi.display}`;
}

function _resolveEffectiveStatus(data) {
    const isOfflineDisplayEnabled = ((data.offline_display?.enabled === true) || data.offline_display_enabled === true);
    if (data.status === 'offline' && isOfflineDisplayEnabled) {
        return { effectiveStatus: 'stale', isOfflineDisplayEnabled };
    }
    return { effectiveStatus: data.status, isOfflineDisplayEnabled };
}

function updateSidebarUI(data) {
    renderMonitoringSensors(data);
    clearGnssEvaluationSummary();
    updateChartsAvailability(data);
    setText('st-name', data.name);
    setText('st-code', data.station_code);

    const { effectiveStatus, isOfflineDisplayEnabled } = _resolveEffectiveStatus(data);
    _renderStationRiskBadge(data, effectiveStatus);

    void window.restoreGnssAdjustmentStatus?.(data.project_id);
    renderStaleInfo(data, data.mqtt_connected !== false, getLatestSensorTimestamp(data));

    const onlineStates = _determineSensorOnlineStates(data, effectiveStatus, isOfflineDisplayEnabled);
    const gnssLatest = data.sensors?.gnss?.latest;
    _renderAdvancedGnssSidebar(gnssLatest?.data || gnssLatest, onlineStates.gnssOnline);
    updateSensorOfflineBadge('rain', onlineStates.rainOnline);
    updateSensorOfflineBadge('water', onlineStates.waterOnline);
    updateImuOfflineBadge(onlineStates.imuOnline);

    if (effectiveStatus === 'offline') {
        _renderSidebarSensorsOffline();
    } else {
        _renderSidebarSensorsOnline(data, onlineStates);
    }
    _renderSidebarGnssAdjustedSection(data, data.sensors?.imu?.latest, onlineStates.imuOnline);
}

function destroyStationCharts() {
    Object.keys(charts).forEach(id => {
        if (!charts[id]) return;
        charts[id].destroy();
        delete charts[id];
    });
}

function renderAccelerometerWaveform(sensor) {
    const container = document.getElementById('accelerometer-waveform-charts');
    if (!container) return;
    Object.keys(charts).filter(id => id.startsWith('chart-waveform-')).forEach(id => {
        charts[id].destroy(); delete charts[id];
    });
    container.replaceChildren();
    const latest = sensor?.latest;
    const wave = latest?.waveform;
    if (!wave || latest.quality === 'invalid') return;
    for (const axis of ['x', 'y', 'z']) {
        const values = wave[axis];
        if (!Array.isArray(values) || !values.length || wave.sample_rate_hz <= 0) continue;
        const box = document.createElement('div');
        box.className = 'chart-box';
        const title = document.createElement('div');
        title.className = 'chart-title';
        const eventSuffix = latest.event_id ? ` · ${latest.event_id}` : '';
        title.textContent = `Dạng sóng ${axis.toUpperCase()} · ${wave.sample_rate_hz} Hz${eventSuffix}`;
        const summary = document.createElement('small');
        summary.textContent = `${values.length} mẫu · ${(values.length / wave.sample_rate_hz).toLocaleString('vi-VN')} s · Đỉnh |a|: ${Math.max(...values.map(Math.abs)).toLocaleString('vi-VN', {maximumFractionDigits:3})} m/s² · Bắt đầu: ${new Date(wave.start_at * 1000).toLocaleString('vi-VN')}`;
        const wrap = document.createElement('div');
        wrap.className = 'chart-canvas-wrap';
        const canvas = document.createElement('canvas');
        canvas.id = `chart-waveform-${axis}`;
        canvas.setAttribute('role', 'img');
        canvas.setAttribute('aria-label', `${title.textContent}. ${summary.textContent}`);
        wrap.append(canvas); box.append(title, summary, wrap); container.append(box);
        charts[canvas.id] = new Chart(canvas, {
            type:'line',
            data:{datasets:[{label:`Gia tốc ${axis.toUpperCase()} (m/s²)`, data:values.map((value, index) => ({x:index * 1000 / wave.sample_rate_hz,y:value})), borderColor:'#0f766e', borderWidth:1.5, pointRadius:0}]},
            options:{animation:false, responsive:true, maintainAspectRatio:false, scales:{x:{type:'linear', title:{display:true,text:'Thời gian trong gói (ms)'}},y:{title:{display:true,text:'m/s²'}}}}
        });
    }
}

function _renderCustomSensorsCharts(data, customChartAnchor) {
    Object.keys(charts).filter(id => id.startsWith('chart-custom_')).forEach(id => { charts[id].destroy(); delete charts[id]; });
    document.querySelectorAll('[data-custom-sensor-chart]').forEach(box => box.remove());
    for (const spec of stationSensorCatalog(data).filter(sensor => sensor.key.startsWith('custom_'))) {
        for (const field of spec.fields) {
            if (!/^[a-z_]+$/.test(field)) continue;
            const box = document.createElement('div');
            box.className = 'chart-box';
            box.id = `chart-box-${spec.key}-${field}`;
            box.dataset.customSensorChart = '';
            const title = document.createElement('div');
            title.className = 'chart-title';
            const unitSuffix = spec.unit ? ` (${spec.unit})` : '';
            title.textContent = `${spec.label}${unitSuffix}`;
            const wrap = document.createElement('div');
            wrap.className = 'chart-canvas-wrap';
            const canvas = document.createElement('canvas');
            canvas.id = `chart-${spec.key}-${field}`;
            wrap.append(canvas); box.append(title, wrap);
            customChartAnchor?.before(box);
        }
    }
}

function _renderCoreSensorCharts(data, activeChartBoxIds) {
    if (data.sensors.gnss) {
        activeChartBoxIds.push('chart-box-gnss');
        const history = data.sensors.gnss.history || [];
        const gnssHistory = history.map(h => ({
            timestamp: h.timestamp,
            data: {
                ...h.data,
                _chart_velocity: getGnssVelocity(h.data)
            }
        })).filter(h => h.data._chart_velocity !== null);
        renderChart('chart-gnss', gnssHistory, '_chart_velocity', '#0f766e', 'Vận tốc (mm/s)');
    }
    if (data.sensors.rain) {
        activeChartBoxIds.push('chart-box-rain');
        renderChart('chart-rain', data.sensors.rain.history || [], 'intensity_mm_h', '#06b6d4', 'Cường độ mưa (mm/h)');
    }
    if (data.sensors.water) {
        activeChartBoxIds.push('chart-box-water');
        renderChart('chart-water', data.sensors.water.history || [], 'water_level', '#10b981', 'Mực nước (m)');
    }
    if (data.sensors.imu) {
        activeChartBoxIds.push('chart-box-imu');
        renderImuChart(data.sensors.imu.history || []);
    }
}

function _renderCatalogSensorCharts(data, allChartIds, activeChartBoxIds) {
    for (const spec of stationSensorCatalog(data).filter(sensor => !sensor.legacy && sensor.key !== 'extensometer')) {
        for (const field of spec.fields) {
            const boxId = `chart-box-${spec.key}-${field}`;
            allChartIds.push(boxId);
            if (data.sensors[spec.key]) {
                activeChartBoxIds.push(boxId);
                const metric = spec.metrics?.find(metric => metric.field === field);
                const history = (data.sensors[spec.key].history || []).map(row => ({timestamp: row.data?.measured_at || row.timestamp, data: row.data?.quality === 'invalid' ? {} : row.data}));
                renderChart(`chart-${spec.key}-${field}`, history, field, '#0f766e', `${metric?.label || spec.label} (${spec.unit})`);
            }
        }
    }
}

function _renderExtensometerCharts(data, activeChartBoxIds) {
    const extensometerContainer = document.getElementById('extensometer-charts');
    if (!extensometerContainer) return;
    Object.keys(charts).filter(id => id.startsWith('chart-extensometer-')).forEach(id => { charts[id].destroy(); delete charts[id]; });
    extensometerContainer.replaceChildren();
    const sensor = data.sensors.extensometer;
    const history = sensor?.history || [];
    const points = [...new Set([...Object.keys(sensor?.latest?.points || {}), ...history.flatMap(row => Object.keys(row.data?.points || {}))])];
    points.forEach((point, index) => {
        const box = document.createElement('div');
        box.className = 'chart-box';
        const title = document.createElement('div');
        title.className = 'chart-title';
        title.textContent = `Giãn kế · ${point} (mm)`;
        const wrap = document.createElement('div');
        wrap.className = 'chart-canvas-wrap';
        const canvas = document.createElement('canvas');
        canvas.id = `chart-extensometer-${index}`;
        canvas.dataset.point = point;
        wrap.append(canvas); box.append(title, wrap); extensometerContainer.append(box);
        activeChartBoxIds.push(canvas.id);
        renderChart(canvas.id, history.map(row => ({timestamp: row.data?.measured_at || row.timestamp, data: {value: row.data?.quality === 'invalid' ? null : row.data?.points?.[point]}})), 'value', '#0f766e', `${point} (mm)`);
    });
}

function renderCharts(data) {
    if (!data.sensors) return;

    const customChartAnchor = document.getElementById('extensometer-charts');
    _renderCustomSensorsCharts(data, customChartAnchor);

    updateChartsAvailability(data);
    updateChartRangeControls();
    renderAccelerometerWaveform(data.sensors.accelerometer);

    console.log('📊 [CHARTS] Rendering charts for station devices...');

    const allChartIds = ['chart-box-gnss', 'chart-box-rain', 'chart-box-water', 'chart-box-imu'];
    const activeChartBoxIds = [];

    _renderCoreSensorCharts(data, activeChartBoxIds);
    _renderCatalogSensorCharts(data, allChartIds, activeChartBoxIds);
    _renderExtensometerCharts(data, activeChartBoxIds);

    const pointMeta = document.getElementById('charts-point-meta');
    if (pointMeta) {
        const totalPoints = getChartableSensorTypes(data).reduce(
            (total, sensorType) => total + Number(data.sensors?.[sensorType]?.history?.length || 0),
            0,
        );
        pointMeta.textContent = totalPoints ? `${totalPoints.toLocaleString('vi-VN')} điểm đã tải` : 'Chưa có dữ liệu trong khoảng này';
    }

    allChartIds.forEach(chartBoxId => {
        const chartBox = document.getElementById(chartBoxId);
        if (chartBox) {
            chartBox.style.display = activeChartBoxIds.includes(chartBoxId) ? 'block' : 'none';
        }
    });

    const emptyState = document.getElementById('charts-empty-state');
    if (emptyState) {
        emptyState.style.display = activeChartBoxIds.length === 0 ? 'block' : 'none';
    }

    enhanceChartWorkspace(data);
    console.log(`✅ [CHARTS] Rendered ${activeChartBoxIds.length} charts`);
}

function buildChartTimeLabels(history) {
    const timestamps = (history || [])
        .map(item => normalizeEpochMs(item.timestamp))
        .filter(Number.isFinite);
    const spanMs = timestamps.length > 1
        ? Math.max(...timestamps) - Math.min(...timestamps)
        : 0;
    const showSeconds = spanMs > 0 && spanMs <= 10 * 60 * 1000;
    const showDate = spanMs > 36 * 60 * 60 * 1000;
    return (history || []).map(item => {
        const date = new Date(normalizeEpochMs(item.timestamp));
        if (showDate) {
            return date.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' });
        }
        return date.toLocaleTimeString('vi-VN', {
            hour: '2-digit',
            minute: '2-digit',
            ...(showSeconds ? { second: '2-digit' } : {}),
            hour12: false,
        });
    });
}

function _resolveChartItemTimestampTitle(items, fallbackHistory = []) {
    if (!items?.length) return '';
    const idx = items[0].dataIndex;
    const chartInst = items[0].chart;
    const ts = chartInst?._monitoringTimestamps?.[idx];
    if (Number.isFinite(ts)) {
        return formatChartTimestamp(ts);
    }
    const raw = fallbackHistory[idx]?.timestamp;
    const norm = normalizeEpochMs(raw);
    if (Number.isFinite(norm)) {
        return formatChartTimestamp(norm);
    }
    const fallback = chartInst?.data?.labels?.[idx];
    return fallback || 'Thời gian quan trắc';
}

function _updateChartStatsElements(id, numericValues) {
    const hasValues = numericValues.length > 0;
    const maxVal = hasValues ? Math.max(...numericValues).toFixed(2) : '--';
    const minVal = hasValues ? Math.min(...numericValues).toFixed(2) : '--';
    const avgVal = hasValues ? (numericValues.reduce((a, b) => a + b, 0) / numericValues.length).toFixed(2) : '--';
    const latestVal = hasValues ? numericValues[numericValues.length - 1].toFixed(2) : '--';

    const elLatest = document.getElementById(`stat-${id}-latest`);
    const elMax = document.getElementById(`stat-${id}-max`);
    const elMin = document.getElementById(`stat-${id}-min`);
    const elAvg = document.getElementById(`stat-${id}-avg`);
    if (elLatest) elLatest.innerText = latestVal;
    if (elMax) elMax.innerText = maxVal;
    if (elMin) elMin.innerText = minVal;
    if (elAvg) elAvg.innerText = avgVal;
}

function _parseHexColorRgb(color, defaultRgb = [13, 110, 253]) {
    if (color.startsWith('#') && color.length === 7) {
        return [
            Number.parseInt(color.slice(1, 3), 16),
            Number.parseInt(color.slice(3, 5), 16),
            Number.parseInt(color.slice(5, 7), 16),
        ];
    }
    return defaultRgb;
}

function renderChart(id, history, key, color, label) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const labels = buildChartTimeLabels(history);
    const values = (history || []).map(h => {
        const val = h.data?.[key];
        if (val === null || val === undefined || val === '') return null;
        const num = Number.parseFloat(val);
        return Number.isFinite(num) ? num : null;
    });
    const numericValues = values.filter(value => value !== null);
    _updateChartStatsElements(id, numericValues);

    if (charts[id]) {
        charts[id].destroy();
    }

    // Theme-aware colors
    const isDark = document.documentElement.dataset.theme === 'dark';
    const gridColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)';
    const tickColor = isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.4)';
    const [r, g, b] = _parseHexColorRgb(color);
    let gradient = ctx.createLinearGradient(0, 0, 0, 300);
    gradient.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.20)`);
    gradient.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0.0)`);

    const showPoints = values.length <= 140;
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
                tension: 0,
                borderWidth: 1.8,
                pointRadius: showPoints ? 1.8 : 0,
                pointHoverRadius: 4,
                pointBackgroundColor: color,
                pointBorderColor: '#fff',
                pointBorderWidth: 1.5,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            normalized: true,
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
                    callbacks: { title: items => _resolveChartItemTimestampTitle(items, history) },
                }
            },
            scales: {
                    x: { 
                        display: true,
                        grid: { display: false },
                        ticks: {
                            color: tickColor,
                            maxTicksLimit: 8,
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
                    beginAtZero: id === 'chart-gnss' || id === 'chart-rain'
                }
            }
        }
    });
    charts[id]._monitoringTimestamps = history.map(row => normalizeEpochMs(row.timestamp));
}

function renderImuChart(history) {
    const ctx = document.getElementById('chart-imu');
    if (!ctx) return;

    const labels = buildChartTimeLabels(history);

    const metricOrNull = value => {
        if (value == null || value === '') return null;
        const number = Number(value);
        return Number.isFinite(number) ? number : null;
    };
    const rollData = (history || []).map(h => metricOrNull(h.data?.roll));
    const pitchData = (history || []).map(h => metricOrNull(h.data?.pitch));
    const yawData = (history || []).map(h => metricOrNull(h.data?.yaw));

    if (charts['chart-imu']) {
        charts['chart-imu'].destroy();
    }

    // Theme-aware colors
    const isDark = document.documentElement.dataset.theme === 'dark';
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
                },
                tooltip: {
                    backgroundColor: isDark ? 'rgba(15, 23, 42, 0.9)' : 'rgba(255, 255, 255, 0.9)',
                    titleColor: isDark ? '#fff' : '#1e293b',
                    bodyColor: isDark ? '#cbd5e1' : '#475569',
                    borderColor: isDark ? '#334155' : '#e2e8f0',
                    borderWidth: 1,
                    padding: 10,
                    boxPadding: 4,
                    usePointStyle: true,
                    callbacks: { title: items => _resolveChartItemTimestampTitle(items, history) }
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
    charts['chart-imu']._monitoringTimestamps = history.map(row => normalizeEpochMs(row.timestamp));
}

if (typeof window !== 'undefined') {
    window._updateChartStatsElements = _updateChartStatsElements;
}
