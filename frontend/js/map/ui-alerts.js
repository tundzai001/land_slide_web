// =========================================================================
// IMU DRIFT CALCULATION
// =========================================================================
function updateImuDrift(rollVal, pitchVal) {
    if (rollVal === null || rollVal === undefined || pitchVal === null || pitchVal === undefined || isNaN(Number.parseFloat(rollVal)) || isNaN(Number.parseFloat(pitchVal))) {
        setText('val-imu-drift-len', '-- cm');
        setText('val-imu-drift-dir', '(--)');
        return;
    }
    const r = Number.parseFloat(rollVal) || 0;
    const p = Number.parseFloat(pitchVal) || 0;
    const r_rad = r * Math.PI / 180;
    const p_rad = p * Math.PI / 180;

    // Using 1.0 meter (1000mm) as virtual pole length
    // Use sin for spatial spherical coordinates instead of tan to prevent overestimation
    const total_tilt_rad = Math.sqrt(r_rad * r_rad + p_rad * p_rad);
    const drift = 1000 * Math.sin(total_tilt_rad);

    const dx = 1000 * Math.sin(r_rad);
    const dy = 1000 * Math.sin(p_rad);

    let dir_text = "--";
    if (drift > 0.1) {
        let angle_deg = Math.atan2(dy, dx) * 180 / Math.PI;
        if (angle_deg < 0) angle_deg += 360;
        const dirs = ["Đ", "ĐB", "B", "TB", "T", "TN", "N", "ĐN"];
        const idx = Math.round(angle_deg / 45) % 8;
        dir_text = dirs[idx];
    }

    animateValue('val-imu-drift-len', drift / 10, 1, ' cm', true);
    setText('val-imu-drift-dir', `(${dir_text})`);
}

// =========================================================================
// SMOOTH ANIMATED VALUE SYSTEM
// =========================================================================

// Store previous numeric values for lerp interpolation
const _prevValues = {};
// Store ongoing animation frame IDs to cancel previous animations
const _animFrames = {};

/**
 * Smoothly animate a sensor value from its current displayed number to a new value.
 * Uses requestAnimationFrame for 60fps lerp interpolation.
 *
 * @param {string} id - DOM element ID
 * @param {number|string|null} newValue - New numeric value
 * @param {number} decimals - Decimal places to display
 * @param {string} unit - Unit string (e.g. 'mm/s', '°')
 * @param {boolean} textOnly - If true, set innerText instead of innerHTML (for elements without unit spans)
 */
function animateValue(id, newValue, decimals = 2, unit = '', textOnly = false) {
    const el = document.getElementById(id);
    if (!el) return;

    const numVal = Number.parseFloat(newValue);
    if (isNaN(numVal) || newValue === null || newValue === undefined) {
        // Non-numeric → direct set
        if (textOnly) {
            el.innerText = `--${unit}`;
        } else {
            el.innerHTML = `--<span class="sensor-unit">${unit}</span>`;
        }
        return;
    }

    const detailVisible = document.getElementById('detail-sidebar')?.classList.contains('active');
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    if (!detailVisible || document.hidden || mapInteractionActive || reduceMotion) {
        if (_animFrames[id]) {
            cancelAnimationFrame(_animFrames[id]);
            delete _animFrames[id];
        }
        _prevValues[id] = numVal;
        if (textOnly) {
            el.textContent = `${numVal.toFixed(decimals)}${unit}`;
        } else {
            setHTML(id, `${numVal.toFixed(decimals)}<span class="sensor-unit">${unit}</span>`);
        }
        return;
    }

    const prevVal = _prevValues[id];

    // If no previous value or same value, just set directly (no animation needed)
    if (prevVal === undefined || prevVal === numVal) {
        _prevValues[id] = numVal;
        if (textOnly) {
            el.innerText = `${numVal.toFixed(decimals)}${unit}`;
        } else {
            el.innerHTML = `${numVal.toFixed(decimals)}<span class="sensor-unit">${unit}</span>`;
        }
        return;
    }

    // Cancel any ongoing animation for this element
    if (_animFrames[id]) {
        cancelAnimationFrame(_animFrames[id]);
    }

    // Trigger CSS glow effect on the parent sensor-item
    flashUpdate(el);

    const startVal = prevVal;
    const diff = numVal - startVal;
    const duration = 220;
    const startTime = performance.now();

    function step(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);

        // Ease-out cubic for smooth deceleration
        const eased = 1 - Math.pow(1 - progress, 3);
        const currentVal = startVal + diff * eased;

        if (textOnly) {
            el.innerText = `${currentVal.toFixed(decimals)}${unit}`;
        } else {
            el.innerHTML = `${currentVal.toFixed(decimals)}<span class="sensor-unit">${unit}</span>`;
        }

        if (progress < 1) {
            _animFrames[id] = requestAnimationFrame(step);
        } else {
            _prevValues[id] = numVal;
            delete _animFrames[id];
        }
    }

    _prevValues[id] = numVal;
    _animFrames[id] = requestAnimationFrame(step);
}

/**
 * Trigger CSS glow flash on a value element's parent sensor-item.
 */
function flashUpdate(el) {
    // Find closest sensor-item parent for the glow effect
    const sensorItem = el.closest('.sensor-item') || el.closest('.axis-value');
    if (sensorItem) {
        sensorItem.classList.remove('value-updated');
        requestAnimationFrame(() => sensorItem.classList.add('value-updated'));
    }
}

function filterStations(searchTerm) {
    const term = String(searchTerm || '').trim().toLocaleLowerCase('vi');
    const statusFilter = document.getElementById('station-status-filter')?.value || 'all';
    const items = document.querySelectorAll('.station-item');
    let visibleCount = 0;
    items.forEach(item => {
        const text = item.textContent.toLocaleLowerCase('vi');
        const state = item.dataset.state;
        const connection = item.dataset.connection;
        const matchesStatus = statusFilter === 'all'
            || (statusFilter === 'online' && connection === 'online')
            || (statusFilter === 'alert' && ['medium', 'critical'].includes(state))
            || (statusFilter === 'offline' && ['offline', 'stale'].includes(connection));
        item.hidden = !text.includes(term) || !matchesStatus;
        if (!item.hidden) visibleCount += 1;
    });
    const result = document.getElementById('station-filter-result');
    if (result) result.textContent = `${visibleCount} trạm`;
    const empty = document.getElementById('station-filter-empty');
    if (empty) empty.hidden = visibleCount !== 0;
}

// =========================================================================
// SIREN TOGGLE BUTTON STATE MANAGEMENT
// =========================================================================

/**
 * Cập nhật trạng thái nút còi
 * @param {'idle'|'alerting'|'muted'|'offline'} state
 *   - idle: xám, disabled (mặc định, chưa có cảnh báo)
 *   - alerting: đỏ, nhấp nháy (đang cảnh báo, bấm để tắt còi)
 *   - muted: xanh (đã tắt còi, bấm để bật lại)
 *   - offline: xám đen, disabled (thiết bị Pi mất kết nối)
 */
function setSirenButtonState(state, target = null) {
    const sirenSection = document.getElementById('siren-sidebar-section');

    const btns = target
        ? document.querySelectorAll(`.btn-siren-toggle[data-target="${target}"]`)
        : document.querySelectorAll('.btn-siren-toggle');

    btns.forEach(btn => {
        btn.setAttribute('data-siren-state', state);
        const iconBase = btn.getAttribute('data-target') === 'pi_center' ? 'Center' : 'Point';

        switch (state) {
            case 'idle':
                btn.disabled = true;
                btn.classList.remove('btn-danger', 'btn-success');
                btn.classList.add('disabled', 'btn-secondary');
                btn.style.opacity = '0.5';
                btn.innerHTML = `<i class="bi bi-volume-mute-fill me-1"></i>${iconBase}`;
                break;
            case 'alerting':
                btn.disabled = false;
                btn.classList.remove('disabled', 'btn-success', 'btn-secondary');
                btn.classList.add('btn-danger');
                btn.style.opacity = '1';
                btn.innerHTML = `<i class="bi bi-volume-mute-fill me-1"></i>Mute ${iconBase}`;
                break;
            case 'muted':
                btn.disabled = false;
                btn.classList.remove('disabled', 'btn-danger', 'btn-secondary');
                btn.classList.add('btn-success');
                btn.style.opacity = '1';
                btn.innerHTML = `<i class="bi bi-volume-up-fill me-1"></i>On ${iconBase}`;
                break;
            case 'offline':
                btn.disabled = true;
                btn.classList.remove('btn-danger', 'btn-success');
                btn.classList.add('btn-secondary', 'disabled');
                btn.style.opacity = '0.5';
                btn.innerHTML = `<i class="bi bi-plug-fill me-1"></i>Offline`;
                break;
        }
    });
}

// =========================================================================
// ALERT BANNER SYSTEM
// =========================================================================

let currentAlertStationId = null;
let lastAlertKey = null;
let latestAlertByStation = {};
let alertBannerSnoozeUntil = {};
let acknowledgedAlertKeyByStation = {};
let bannerSuppressedUntilByStation = {};

// Map sensor_type từ backend → id của sensor card trong HTML
const SENSOR_CARD_IDS = {
    gnss: 'sensor-card-gnss',
    rain: 'sensor-card-rain',
    water: 'sensor-card-water',
    imu: 'sensor-card-imu',
};

function setSensorCardAlert(sensorType, level) {
    const cardId = SENSOR_CARD_IDS[sensorType];
    if (!cardId) return;
    const card = document.getElementById(cardId);
    if (!card) return;
    card.classList.remove('sensor-alert-warning', 'sensor-alert-critical');
    const effectiveLevel = String(sensorType || '').toLowerCase() === 'imu' ? 'CRITICAL' : level;
    const normalized = normalizeAlertLevel(effectiveLevel);
    if (normalized === 'WARNING') {
        card.classList.add('sensor-alert-warning');
    } else if (normalized === 'CRITICAL') {
        card.classList.add('sensor-alert-critical');
    }
}

function clearAllSensorCardAlerts() {
    Object.values(SENSOR_CARD_IDS).forEach(id => {
        const card = document.getElementById(id);
        if (card) card.classList.remove('sensor-alert-warning', 'sensor-alert-critical');
    });
}

function applySensorCardAlertsFromAssessment(data) {
    clearAllSensorCardAlerts();
    const activeAlerts = data?.risk_assessment?.active_alerts || [];
    activeAlerts.forEach(alert => {
        const sensorType = mapAlertCategoryToSensorType(alert.category);
        if (SENSOR_CARD_IDS[sensorType]) {
            setSensorCardAlert(sensorType, alert.level || data?.risk_assessment?.overall_risk || 'WARNING');
        }
    });
}

function showAlertBanner(alertData, options = {}) {
    if (currentMapMode === 'rescue') return;

    const banner = document.getElementById('alert-banner');
    if (!banner) return;

    const safeAlertData = normalizeIncomingAlert(alertData);
    if (isBannerSuppressed(safeAlertData.station_id)) return;

    // ✅ Lookup station info từ allStations (đã load sẵn)
    const station = allStations.find(s => s.id === safeAlertData.station_id);
    const stationName = station?.name || `Station #${safeAlertData.station_id}`;
    const stationCode = station?.station_code || '';

    const normalizedLevel = normalizeAlertLevel(safeAlertData.level || safeAlertData.risk_level);
    const alertKey = buildAlertKey(safeAlertData);

    // Cập nhật nội dung — luôn phản ánh mức cảnh báo hiện tại
    updateAlertBannerTheme(normalizedLevel);

    document.getElementById('alert-title').textContent =
        options.silent ? `⚠️ ALERT (persistent)` : `${normalizedLevel} ALERT!`;

    document.getElementById('alert-station').textContent =
        `Station: ${stationName} (${stationCode})`;

    document.getElementById('alert-message').textContent =
        ` • ${safeAlertData.message || 'Anomaly detected!'}`;

    // Lưu station ID
    currentAlertStationId = safeAlertData.station_id;
    alertBannerSnoozeUntil[safeAlertData.station_id] = 0;
    banner.dataset.alertKey = alertKey;

    // Hiển thị banner (không auto-dismiss, user phải ấn X hoặc Theo dõi)
    // Lưu ý: siren button state được quản lý bởi _showSirenIfAlerting / WS handler,
    // không set ở đây để tránh override trạng thái offline của từng pi device.
    banner.classList.add('show');
}

// =====================================================
// ALERT SOUND MANAGER
// Phát âm thanh liên tục (loop) khi WARNING hoặc CRITICAL.
// Chỉ dừng khi tất cả trạm trở về trạng thái bình thường.
// WARNING  → /static/sounds/system_health_warning.mp3 (loop)
// CRITICAL → /static/sounds/siren.mp3                 (loop)
// =====================================================
const AlertSoundManager = (() => {
    const SOUND_WARNING = '/static/sounds/siren.mp3';
    const SOUND_CRITICAL = '/static/sounds/siren.mp3';

    // Trạng thái âm thanh hiện tại: null | 'WARNING' | 'CRITICAL'
    let _currentLevel = null;
    let _audio = null;
    let _unlocked = false;

    // Theo dõi mức cảnh báo của từng trạm: { stationId: 'WARNING'|'CRITICAL'|null }
    const _stationLevels = {};

    function _getSoundFile(level) {
        return level === 'CRITICAL' ? SOUND_CRITICAL : SOUND_WARNING;
    }

    function _getHighestLevel() {
        const levels = Object.values(_stationLevels).filter(Boolean);
        if (levels.includes('CRITICAL')) return 'CRITICAL';
        if (levels.includes('WARNING')) return 'WARNING';
        return null;
    }

    function _stopAudio() {
        if (_audio) {
            try {
                _audio.pause();
                _audio.src = '';
            } catch (_) { }
            _audio = null;
        }
        _currentLevel = null;
    }

    function _startAudio(level) {
        const src = _getSoundFile(level);
        // Nếu đang phát đúng cấp độ rồi thì không làm gì
        if (_audio && _currentLevel === level) return;
        // Dừng âm thanh hiện tại trước
        _stopAudio();

        _currentLevel = level;
        _audio = new Audio(src);
        _audio.loop = true; // Phát liên tục

        _audio.play().catch(e => {
            console.warn('[AlertSoundManager] Autoplay blocked:', e);
            if (navigator.vibrate) navigator.vibrate([300, 140, 300]);
            window.toast?.warning(
                'Trình duyệt đang chặn âm thanh tự động. Hãy chạm màn hình một lần để bật còi cảnh báo.'
            );
            _audio = null;
            _currentLevel = null;
        });
        console.log(`🔊 [AlertSoundManager] Playing ${level} sound (loop):`, src);
    }

    /** Cập nhật trạng thái cảnh báo của một trạm và điều chỉnh âm thanh. */
    function setStationAlert(stationId, level) {
        // level: 'WARNING', 'CRITICAL', hoặc null (bình thường)
        if (level) {
            _stationLevels[stationId] = level;
        } else {
            delete _stationLevels[stationId];
        }
        _syncSound();
    }

    /** Xóa cảnh báo cho một trạm (về bình thường). */
    function clearStationAlert(stationId) {
        delete _stationLevels[stationId];
        _syncSound();
    }

    /** Đồng bộ âm thanh với mức cảnh báo cao nhất hiện có. */
    function _syncSound() {
        const highest = _getHighestLevel();
        if (!highest) {
            // Không còn trạm nào đang báo → dừng âm thanh
            if (_audio) {
                console.log('✅ [AlertSoundManager] All stations normal — stopping sound.');
                _stopAudio();
            }
        } else if (highest !== _currentLevel) {
            // Chuyển cấp độ (ví dụ WARNING → CRITICAL hoặc ngược lại)
            _startAudio(highest);
        }
        // Nếu highest === _currentLevel → âm thanh đang đúng, không làm gì
    }

    /** Unlock AudioContext sau tương tác người dùng lần đầu. */
    function unlock() {
        if (_unlocked) return;
        _unlocked = true;
        // Nếu đang có cảnh báo mà chưa phát được, thử lại
        const highest = _getHighestLevel();
        if (highest && !_audio) {
            _startAudio(highest);
        }
    }

    /** Tắt thủ công (nút Mute), không xóa trạng thái cảnh báo. */
    function mute() {
        _stopAudio();
        console.log('🔇 [AlertSoundManager] Muted by user.');
    }

    return { setStationAlert, clearStationAlert, unlock, mute };
})();

/**
 * Tương thích ngược — các nơi gọi playSiren() sẽ báo CRITICAL cho trạm hiện tại.
 * @param {string|number} [stationId]
 * @param {string} [level='CRITICAL']
 */
function playSiren(stationId, level) {
    const sid = stationId ?? currentAlertStationId;
    const lvl = level ?? 'CRITICAL';
    if (sid != null) {
        AlertSoundManager.setStationAlert(sid, lvl);
    } else {
        // Không biết trạm nào — vẫn kêu CRITICAL nhưng chỉ tạm (sẽ bị dừng khi status cập nhật)
        AlertSoundManager.setStationAlert('_unknown', lvl);
    }
}

function playAlertSound() {
    try {
        // Beep đơn giản dùng Web Audio API (dùng khi autoplay bị block)
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioContext.createOscillator();
        const gainNode = audioContext.createGain();
        oscillator.connect(gainNode);
        gainNode.connect(audioContext.destination);
        oscillator.frequency.value = 800;
        oscillator.type = 'sine';
        gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.5);
        oscillator.start(audioContext.currentTime);
        oscillator.stop(audioContext.currentTime + 0.5);
    } catch (e) {
        console.warn('⚠️ [ALERT] Sound not available:', e);
    }
}

// Setup event listeners cho Alert Banner
runWhenDomReady(() => {
    // Unlock AudioContext sau tương tác người dùng đầu tiên
    const unlockSirenAudio = () => AlertSoundManager.unlock();
    document.addEventListener('touchstart', unlockSirenAudio, { once: true, passive: true });
    document.addEventListener('pointerdown', unlockSirenAudio, { once: true, passive: true });
    document.addEventListener('click', unlockSirenAudio, { once: true, passive: true });

    // Nút "Theo dõi" → Zoom vào trạm + ẩn banner + hiện siren popup sau khi zoom xong
    const btnFollow = document.getElementById('btn-alert-follow');
    if (btnFollow) {
        btnFollow.addEventListener('click', async () => {
            if (!currentAlertStationId) return;

            const alertStationId = currentAlertStationId;
            const currentAlertKey = buildAlertKey(latestAlertByStation[alertStationId] || {
                station_id: alertStationId,
                level: document.getElementById('alert-banner')?.dataset?.alertLevel || 'WARNING'
            });
            if (currentAlertKey) {
                acknowledgedAlertKeyByStation[alertStationId] = currentAlertKey;
            }
            bannerSuppressedUntilByStation[alertStationId] = Date.now() + 5 * 60 * 1000;

            // 1. Ẩn banner ngay
            const banner = document.getElementById('alert-banner');
            if (banner) banner.classList.remove('show');

            // 2. Load dữ liệu trạm (skip zoom và siren — tự quản lý bên dưới)
            await selectStation(alertStationId, { skipZoom: true, skipSiren: true, skipBannerRestore: true });

            // 3. Zoom vào trạm
            if (markers[alertStationId]) {
                map.flyTo(markers[alertStationId].getLatLng(), 16, { duration: 1.5 });

                // 4. Hiện siren popup SAU KHI zoom xong
                map.once('moveend', () => {
                    if (currentStationData && currentStationData.id === alertStationId) {
                        _showSirenIfAlerting(alertStationId, currentStationData);
                    }
                });
            }
        });
    }

    // Nút "Đóng" → Chỉ ẩn banner, không zoom, không ảnh hưởng gì khác
    const btnDismiss = document.getElementById('btn-alert-dismiss');
    if (btnDismiss) {
        btnDismiss.addEventListener('click', () => {
            const banner = document.getElementById('alert-banner');
            if (banner) {
                const stationId = currentAlertStationId;
                if (stationId) {
                    alertBannerSnoozeUntil[stationId] = Date.now() + 10000;
                }
                banner.classList.remove('show');
                banner.classList.remove('level-warning', 'level-critical');
            }
        });
    }
});

window.mapManager = {
    loadLongTermAnalysis,
    safeNumber,
    updateRealtimeSensorValues,
    updateSidebarUI,
    showAlertBanner,
    playAlertSound,
    playSiren,
    setMarkerAlert,
    clearMarkerAlert,
    AlertSoundManager,
    charts
};
