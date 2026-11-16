async function loadLongTermAnalysis(options = {}) {
    console.log('📊 [MAP] Loading long-term analysis...');

    if (!currentStationData) {
        console.error('❌ [MAP] No station selected');
        return null;
    }
    try { await window.loadFeatureLibrary?.('chart'); }
    catch (err) {
        console.debug('Không thể tải thư viện biểu đồ:', err);
        showLongTermError('Không thể tải thư viện biểu đồ.');
        return null;
    }

    const requestSequence = ++longTermRequestSequence;
    longTermRequestController?.abort();
    longTermRequestController = new AbortController();

    const stationId = currentStationData.id;
    const includeCorrelation = options.includeCorrelation === true || isRainCorrelationAiEnabled;

    // Get selected days from range selector
    const activeBtn = document.querySelector('#longterm-range-selector .btn.active');
    const days = activeBtn ? Number.parseFloat(activeBtn.dataset.days) || 30 : 30;

    document.getElementById('longterm-loading').style.display = 'block';
    document.getElementById('longterm-content').style.display = 'none';
    document.getElementById('longterm-error').style.display = 'none';
    updateRainCorrelationAiControls();

    try {
        const params = new URLSearchParams({
            days: String(days),
            include_correlation: includeCorrelation ? 'true' : 'false',
            correlation_model: 'slide_model'
        });
        const res = await fetch(`/api/stations/${stationId}/long-term-analysis?${params.toString()}`, {
            signal: longTermRequestController.signal,
        });

        if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || 'Failed to load analysis');
        }

        const data = await res.json();

        if (requestSequence !== longTermRequestSequence || currentStationData?.id !== stationId) return null;

        renderLongTermAnalysis(data);
        return data;

    } catch (e) {
        if (e.name === 'AbortError') return null;
        console.error('❌ [MAP] Error loading long-term analysis:', e);
        showLongTermError(e.message);
        return null;
    } finally {
        if (requestSequence === longTermRequestSequence) {
            rainCorrelationAiRunning = false;
            longTermRequestController = null;
            updateRainCorrelationAiControls();
        }
    }
}

// Store last analysis data for re-rendering on time range change
let _lastLongTermData = null;

function renderLongTermAnalysis(data) {
    document.getElementById('longterm-loading').style.display = 'none';
    document.getElementById('longterm-content').style.display = 'block';
    document.getElementById('longterm-error').style.display = 'none';

    _lastLongTermData = data;
    updateRainCorrelationAiControls(data.rainfall_correlation);

    // === GNSS Section ===
    const gnss = data.gnss;
    const sourceNoteEl = document.getElementById('lt-gnss-source-note');
    if (gnss?.status === 'success') {
        const analysis = gnss.analysis;

        const warningEl = document.getElementById('longterm-warning');
        const warningTextEl = document.getElementById('warning-text');
        const reliabilityNoteEl = document.getElementById('lt-reliability-note');
        const reliabilityTextEl = document.getElementById('lt-reliability-text');

        if (gnss.risk_level === 'CRITICAL' || gnss.risk_level === 'WARNING') {
            warningEl.style.display = 'block';
            warningEl.className = `alert ${gnss.risk_level === 'CRITICAL' ? 'alert-danger' : 'alert-warning'} mb-3`;
            warningTextEl.textContent = sanitizeLongTermText(gnss.warning_message);
        } else if (gnss.risk_level === 'INFO') {
            warningEl.style.display = 'block';
            warningEl.className = `alert alert-success mb-3`;
            warningTextEl.textContent = sanitizeLongTermText(gnss.warning_message);
        } else {
            warningEl.style.display = 'none';
        }

        const velocityDisplay = formatLongTermVelocityDisplay(analysis);
        setText('lt-velocity', velocityDisplay.text);
        setText('lt-velocity-ci', velocityDisplay.ciText);
        setText('lt-classification', analysis.classification || 'N/A');

        // Use auto cm/mm formatting
        setText('lt-total-disp', formatDisplacementString(analysis.total_displacement_mm, 1));

        setText('lt-duration', formatDurationString(analysis.duration_days));

        if (analysis.velocity_reliable === false) {
            reliabilityNoteEl.style.display = 'flex';
            reliabilityTextEl.textContent = analysis.reliability_message || 'Chưa đủ thời lượng quan sát.';
        } else {
            reliabilityNoteEl.style.display = 'none';
            reliabilityTextEl.textContent = '';
        }

        if (sourceNoteEl) {
            if (gnss.source === 'daily_summary_rollup') {
                sourceNoteEl.style.display = 'block';
                sourceNoteEl.innerHTML = '<i class="bi bi-calendar-week me-2"></i>GNSS đang phân tích từ dữ liệu tổng hợp ngày (daily summary). Dữ liệu raw cũ có thể đã được dọn để tối ưu hệ thống.';
            } else {
                sourceNoteEl.style.display = 'block';
                sourceNoteEl.innerHTML = '<i class="bi bi-broadcast me-2"></i>GNSS đang phân tích trực tiếp từ dữ liệu raw theo thời gian thực.';
            }
        }

        const trendIcons = { 'accelerating': '', 'stable': '', 'decelerating': '' };
        const trendTexts = { 'accelerating': 'Đang tăng tốc', 'stable': 'Ổn định', 'decelerating': 'Đang giảm tốc' };

        document.getElementById('trend-icon').textContent = trendIcons[analysis.trend] || '';
        document.getElementById('trend-value').textContent = trendTexts[analysis.trend] || 'Không xác định';

        const cusumBadge = document.getElementById('cusum-badge');
        const cusumMessage = document.getElementById('cusum-message');
        if (analysis.cusum_change) {
            cusumBadge.style.display = 'inline-block';
            cusumMessage.textContent = analysis.cusum_message || 'Có thay đổi xu hướng';
            cusumMessage.style.display = 'inline-block';
        } else {
            cusumBadge.style.display = 'none';
            cusumMessage.style.display = 'none';
        }
    } else {
        const warningEl = document.getElementById('longterm-warning');
        const reliabilityNoteEl = document.getElementById('lt-reliability-note');
        const reliabilityTextEl = document.getElementById('lt-reliability-text');
        if (warningEl) warningEl.style.display = 'none';
        if (reliabilityNoteEl) reliabilityNoteEl.style.display = 'none';
        if (reliabilityTextEl) reliabilityTextEl.textContent = '';
        if (sourceNoteEl) {
            sourceNoteEl.style.display = 'none';
            sourceNoteEl.textContent = '';
        }
        setText('lt-velocity', 'N/A');
        setText('lt-velocity-ci', '(Chưa có thông tin)');
        setText('lt-classification', 'N/A');
        setText('lt-total-disp', 'N/A');
        setText('lt-duration', 'N/A');
        document.getElementById('cusum-badge').style.display = 'none';
        document.getElementById('cusum-message').style.display = 'none';
    }

    // === IMU Section ===
    renderImuLongTermSection(data.imu);

    // === Combined Chart ===
    renderCombinedLongTermChart(data);

    // === 3D Simulations ===
    void init3DVisualizations(data);

    // === NEW: Inverse Velocity (Fukuzono) ===
    renderInverseVelocitySection(data);

    // === NEW: Rainfall-Displacement Correlation ===
    renderRainfallCorrelationSection(data);

    // Multi-Window section removed per user request

    // === Cross-Sensor Consensus ===
    renderCrossConsensusSection(data);
}

function resetRainfallCorrelationUi() {
    const section = document.getElementById('rainfall-correlation-section');
    if (section) {
        section.style.display = 'none';
    }
    if (charts['chart-rainfall-correlation']) {
        charts['chart-rainfall-correlation'].destroy();
        delete charts['chart-rainfall-correlation'];
    }
    if (charts['chart-sm-model-index']) {
        charts['chart-sm-model-index'].destroy();
        delete charts['chart-sm-model-index'];
    }
}

function updateRainCorrelationAiControls(rainCorr = null) {
    const runBtn = document.getElementById('btn-run-rain-correlation');
    const hintEl = document.getElementById('rain-correlation-hint');
    if (!runBtn || !hintEl) return;

    const canRun = !!currentStationData;
    runBtn.disabled = !canRun || rainCorrelationAiRunning;

    if (rainCorrelationAiRunning) {
        runBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Đang chạy Slide model...';
        hintEl.textContent = 'Hệ thống đang phân tích tương quan mưa - dịch chuyển bằng Slide model.';
        return;
    }

    runBtn.innerHTML = '<i class="bi bi-stars me-2"></i>Chạy AI Slide model';

    if (!isRainCorrelationAiEnabled) {
        hintEl.textContent = 'Tương quan mưa - dịch chuyển chỉ phân tích khi bạn bấm nút AI Slide model.';
        return;
    }

    if (rainCorr?.available) {
        hintEl.textContent = 'Đã chạy AI Slide model thành công cho khoảng thời gian đang chọn.';
        return;
    }

    hintEl.textContent = rainCorr?.message || 'Đã gửi yêu cầu AI Slide model, nhưng chưa có đủ dữ liệu để tính.';
}

function closeSlideModelResultPopup() {
    const overlay = document.getElementById('sm-model-popup-overlay');
    if (!overlay) return;
    overlay.classList.remove('active');
    overlay.setAttribute('aria-hidden', 'true');
}

function showSlideModelResultPopup(rainCorr) {
    const overlay = document.getElementById('sm-model-popup-overlay');
    const statusEl = document.getElementById('sm-model-popup-status');
    if (!overlay || !statusEl) return;

    const available = rainCorr?.available === true;
    const corr = Number(rainCorr?.correlation);
    const r2 = Number(rainCorr?.r_squared);
    const lag = Number(rainCorr?.lag_days);
    const trigger = String(rainCorr?.trigger_potential || 'LOW').toUpperCase();

    // --- Tab switching ---
    overlay.querySelectorAll('.sm-model-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            overlay.querySelectorAll('.sm-model-tab').forEach(t => t.classList.remove('active'));
            overlay.querySelectorAll('.sm-model-tab-pane').forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            const target = document.getElementById(tab.dataset.tab);
            if (target) target.classList.add('active');
        });
    });
    // Reset to first tab
    overlay.querySelectorAll('.sm-model-tab').forEach((t, i) => t.classList.toggle('active', i === 0));
    overlay.querySelectorAll('.sm-model-tab-pane').forEach((p, i) => p.classList.toggle('active', i === 0));

    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = val;
        }
    };
    const fmtDate = (d) => {
        if (!d) {
            return '--';
        }
        try {
            const [, m, dd] = d.split('-');
            return `${dd}/${m}`;
        } catch {
            return d;
        }
    };

    if (available) {
        // === Overview tab ===
        setVal('sm-model-popup-r', Number.isFinite(corr) ? corr.toFixed(4) : '--');
        setVal('sm-model-popup-r2', Number.isFinite(r2) ? r2.toFixed(4) : '--');
        setVal('sm-model-popup-lag', Number.isFinite(lag) ? `${lag} ngày` : '--');
        setVal('sm-model-popup-trigger', trigger);
        setVal('sm-model-popup-strength', rainCorr?.strength || '--');
        setVal('sm-model-popup-slope', rainCorr?.slope_mm_day_per_rain_index != null
            ? Number(rainCorr.slope_mm_day_per_rain_index).toFixed(4) : '--');
        setVal('sm-model-popup-message', sanitizeLongTermText(
            rainCorr?.risk_message || rainCorr?.message || rainCorr?.assessment || 'Slide model hoàn tất.'
        ));

        // Status badge
        if (trigger === 'HIGH') {
            statusEl.className = 'sm-model-popup-status status-fail';
            statusEl.textContent = '🚨 TRIGGER: HIGH';
        } else if (trigger === 'MEDIUM') {
            statusEl.className = 'sm-model-popup-status status-warn';
            statusEl.textContent = '⚠️ TRIGGER: MEDIUM';
        } else {
            statusEl.className = 'sm-model-popup-status status-ok';
            statusEl.textContent = '✅ TRIGGER: LOW';
        }

        // === Rain stats tab ===
        const rs = rainCorr?.rain_stats || {};
        setVal('sm-model-rain-total', rs.total_mm != null ? `${rs.total_mm} mm` : '--');
        setVal('sm-model-rain-max', rs.max_daily_mm != null ? `${rs.max_daily_mm} mm` : '--');
        setVal('sm-model-rain-max-day', fmtDate(rs.max_rain_day));
        setVal('sm-model-rain-days', rs.rain_days != null ? `${rs.rain_days} ngày` : '--');
        setVal('sm-model-dry-days', rs.dry_days != null ? `${rs.dry_days} ngày` : '--');
        setVal('sm-model-rain-avg', rs.avg_rain_on_rainy_days_mm != null ? `${rs.avg_rain_on_rainy_days_mm} mm` : '--');
        setVal('sm-model-idx-max', rs.max_slide_model_index != null ? rs.max_slide_model_index.toFixed(2) : '--');
        setVal('sm-model-idx-mean', rs.mean_slide_model_index != null ? rs.mean_slide_model_index.toFixed(2) : '--');
        setVal('sm-model-common-days', rainCorr?.common_days != null ? `${rainCorr.common_days} ngày` : '--');

        // === Displacement stats tab ===
        const ds = rainCorr?.disp_stats || {};
        setVal('sm-model-disp-total', ds.total_mm != null ? `${ds.total_mm} mm` : '--');
        setVal('sm-model-disp-max', ds.max_daily_mm != null ? `${ds.max_daily_mm} mm` : '--');
        setVal('sm-model-disp-max-day', fmtDate(ds.max_disp_day));
        setVal('sm-model-disp-avg', ds.avg_daily_mm != null ? `${ds.avg_daily_mm} mm` : '--');
        setVal('sm-model-disp-rain', ds.disp_during_rain_mm != null ? `${ds.disp_during_rain_mm} mm` : '--');
        setVal('sm-model-disp-dry', ds.disp_during_dry_mm != null ? `${ds.disp_during_dry_mm} mm` : '--');
        setVal('sm-model-accel-ratio', ds.rain_acceleration_ratio != null
            ? `${ds.rain_acceleration_ratio}x` : '--');
        setVal('sm-model-sensitivity', rainCorr?.sensitivity_mm_per_mm != null
            ? `${rainCorr.sensitivity_mm_per_mm} mm/mm` : '--');

        // Lag scan summary
        const lagScan = rainCorr?.lag_scan || [];
        if (lagScan.length > 0) {
            const lagText = lagScan.map(l => `L${l.lag}:${l.correlation}`).join(' | ');
            setVal('sm-model-lag-scan', lagText);
        } else {
            setVal('sm-model-lag-scan', '--');
        }

        // === Events tab: CWD ===
        const cwdEl = document.getElementById('sm-model-cwd-events');
        const cwdEvents = rainCorr?.cwd_events || [];
        if (cwdEl) {
            if (cwdEvents.length > 0) {
                cwdEl.innerHTML = cwdEvents.map(e => `
                    <div class="sm-model-event-item">
                        <div class="sm-model-event-header">
                            <span class="sm-model-event-date">${fmtDate(e.start)} → ${fmtDate(e.end)}</span>
                            <span class="sm-model-event-badge">${e.days} ngày</span>
                        </div>
                        <div class="sm-model-event-stats">
                            <span>🌧️ ${e.total_rain_mm} mm</span>
                            <span>📏 ${e.displacement_mm} mm</span>
                            <span>💧 TB ${e.avg_intensity} mm/ngày</span>
                        </div>
                    </div>
                `).join('');
            } else {
                cwdEl.innerHTML = '<div class="text-muted small">Không có đợt mưa liên tục ≥2 ngày</div>';
            }
        }

        // === Events tab: Peak rain ===
        const peakEl = document.getElementById('sm-model-peak-events');
        const peakEvents = rainCorr?.peak_rain_events || [];
        if (peakEl) {
            if (peakEvents.length > 0) {
                peakEl.innerHTML = peakEvents.map(e => `
                    <div class="sm-model-event-item">
                        <div class="sm-model-event-header">
                            <span class="sm-model-event-date">${fmtDate(e.date)}</span>
                            <span class="sm-model-event-badge sm-model-event-badge-danger">⚡ ${e.rain_mm} mm</span>
                        </div>
                        <div class="sm-model-event-stats">
                            <span>📏 Phản hồi: ${e.disp_response_mm} mm</span>
                            <span>📊 Index: ${e.slide_model_index}</span>
                        </div>
                    </div>
                `).join('');
            } else {
                peakEl.innerHTML = '<div class="text-muted small">Không có ngày mưa ≥20mm trong giai đoạn này</div>';
            }
        }

        // === Risk insights tab ===
        const riskEl = document.getElementById('sm-model-risk-insights');
        const riskInsights = rainCorr?.risk_insights || [];
        if (riskEl) {
            if (riskInsights.length > 0) {
                riskEl.innerHTML = riskInsights.map(msg => `
                    <div class="sm-model-insight-item">${msg}</div>
                `).join('');
            } else {
                riskEl.innerHTML = `<div class="sm-model-insight-item sm-model-insight-ok">
                    ✅ ${rainCorr?.assessment || 'Không phát hiện yếu tố rủi ro đặc biệt từ tương quan mưa.'}
                </div>`;
            }
        }

    } else {
        // Not available — reset all
        ['sm-model-popup-r', 'sm-model-popup-r2', 'sm-model-popup-lag', 'sm-model-popup-trigger',
            'sm-model-popup-strength', 'sm-model-popup-slope'].forEach(id => setVal(id, '--'));
        setVal('sm-model-popup-message', sanitizeLongTermText(
            rainCorr?.message || 'Không thể tạo kết quả Slide model cho khoảng thời gian này.'
        ));
        statusEl.className = 'sm-model-popup-status status-warn';
        statusEl.textContent = '⚠ CHƯA ĐỦ DỮ LIỆU';
    }

    overlay.classList.add('active');
    overlay.setAttribute('aria-hidden', 'false');
}

// Global references for 3D logic
let gnssScene, gnssCamera, gnssRenderer, gnssControls, gnssAnimationId;
let imuScene, imuCamera, imuRenderer, imuControls, imuAnimationId;
let gnssResizeObserver, imuResizeObserver, realtimeImuResizeObserver;
let gnssResizeHandler, imuResizeHandler, realtimeImuResizeHandler;

function disposeThreeInstance(scene, renderer, controls) {
    controls?.dispose?.();
    scene?.traverse?.(object => {
        object.geometry?.dispose?.();
        if (Array.isArray(object.material)) object.material.forEach(material => material?.dispose?.());
        else object.material?.dispose?.();
    });
    renderer?.dispose?.();
    renderer?.forceContextLoss?.();
    renderer?.domElement?.remove?.();
}

function disposeGnss3D() {
    if (gnssAnimationId) cancelAnimationFrame(gnssAnimationId);
    if (gnssResizeHandler) window.removeEventListener('resize', gnssResizeHandler);
    gnssResizeObserver?.disconnect?.();
    disposeThreeInstance(gnssScene, gnssRenderer, gnssControls);
    gnssScene = gnssCamera = gnssRenderer = gnssControls = gnssAnimationId = gnssResizeObserver = gnssResizeHandler = null;
}

function disposeImu3D() {
    if (imuAnimationId) cancelAnimationFrame(imuAnimationId);
    if (imuResizeHandler) window.removeEventListener('resize', imuResizeHandler);
    imuResizeObserver?.disconnect?.();
    disposeThreeInstance(imuScene, imuRenderer, imuControls);
    imuScene = imuCamera = imuRenderer = imuControls = imuAnimationId = imuResizeObserver = imuResizeHandler = null;
}

function disposeRealtimeImu3D() {
    if (realtimeImuAnimationId) cancelAnimationFrame(realtimeImuAnimationId);
    if (realtimeImuResizeHandler) window.removeEventListener('resize', realtimeImuResizeHandler);
    realtimeImuResizeObserver?.disconnect?.();
    disposeThreeInstance(realtimeImuScene, realtimeImuRenderer, realtimeImuControls);
    realtimeImuScene = realtimeImuCamera = realtimeImuRenderer = realtimeImuControls = realtimeImuAnimationId = null;
    realtimeImuResizeObserver = realtimeImuResizeHandler = realtimeImuSensorBlock = realtimeImuTargetQuaternion = null;
}

function stopLongTerm3DAnimations() {
    disposeGnss3D();
    disposeImu3D();
    disposeRealtimeImu3D();
}

// Helper: wait until a container has non-zero dimensions (handles CSS transitions/display:none)
function waitForContainerSize(container, timeoutMs = 3000) {
    return new Promise((resolve) => {
        if (container.clientWidth > 0 && container.clientHeight > 0) {
            resolve(true);
            return;
        }
        const start = Date.now();
        const check = () => {
            if (container.clientWidth > 0 && container.clientHeight > 0) {
                resolve(true);
            } else if (Date.now() - start > timeoutMs) {
                console.warn('[3D] Container still has 0 size after timeout, using fallback');
                resolve(false);
            } else {
                requestAnimationFrame(check);
            }
        };
        requestAnimationFrame(check);
    });
}

// Helper: get container dimensions with fallback
function getContainerDims(container) {
    let w = container.clientWidth;
    let h = container.clientHeight;
    if (w <= 0 || h <= 0) {
        // Fallback: use style dimensions or parent
        const rect = container.getBoundingClientRect();
        w = rect.width > 0 ? rect.width : 600;
        h = rect.height > 0 ? rect.height : 350;
    }
    return { w, h };
}

async function init3DVisualizations(data) {
    try {
        const THREE = await import('three');
        _THREE = THREE; // Cache for realtime updates
        const { OrbitControls } = await import('three/addons/controls/OrbitControls.js');

        // GNSS
        if (data?.gnss?.status === 'success' && data.gnss.time_series) {
            const gnssLoading = document.getElementById('gnss-3d-loading');
            if (gnssLoading) gnssLoading.style.display = 'block';
            const gnssContainer = document.getElementById('container-3d-gnss');
            // Wait for container to become visible (overlay transition)
            await waitForContainerSize(gnssContainer, 2000);
            setTimeout(() => {
                initGNSS3D(data.gnss.time_series, THREE, OrbitControls);
                if (gnssLoading) gnssLoading.style.display = 'none';
            }, 100);
        } else {
            const cGnss = document.getElementById('container-3d-gnss');
            if (cGnss) cGnss.innerHTML = '<div class="text-muted d-flex h-100 align-items-center justify-content-center">Không có dữ liệu GNSS 3D</div>';
        }

        // IMU
        if (data?.imu?.status === 'success' && data.imu.time_series) {
            const imuLoading = document.getElementById('imu-3d-loading');
            if (imuLoading) imuLoading.style.display = 'block';
            const imuContainer = document.getElementById('container-3d-imu');
            // Wait for container to become visible (overlay transition)
            await waitForContainerSize(imuContainer, 2000);
            setTimeout(() => {
                initIMU3D(data.imu.time_series, THREE, OrbitControls);
                if (imuLoading) imuLoading.style.display = 'none';
            }, 100);
        } else {
            const cImu = document.getElementById('container-3d-imu');
            if (cImu) cImu.innerHTML = '<div class="text-muted d-flex h-100 align-items-center justify-content-center">Không có dữ liệu IMU 3D</div>';
        }

    } catch (error) {
        console.error("Failed to load Three.js:", error);
    }
}

function initGNSS3D(timeSeries, THREE, OrbitControls) {
    const container = document.getElementById('container-3d-gnss');
    if (!container) return;

    // Cleanup previous
    disposeGnss3D();
    container.innerHTML = '';

    gnssScene = new THREE.Scene();
    gnssScene.background = new THREE.Color(0x0a0e17);

    const dims = getContainerDims(container);
    const aspect = dims.w / dims.h;
    gnssCamera = new THREE.PerspectiveCamera(50, aspect, 0.1, 1000);
    gnssCamera.position.set(10, 10, 10);

    gnssRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    gnssRenderer.setSize(dims.w, dims.h);
    container.appendChild(gnssRenderer.domElement);

    gnssControls = new OrbitControls(gnssCamera, gnssRenderer.domElement);
    gnssControls.enableDamping = true;
    gnssControls.dampingFactor = 0.05;

    // Grid and Axes
    const gridHelper = new THREE.GridHelper(50, 50, 0x444444, 0x222222);
    gnssScene.add(gridHelper);

    const axesHelper = new THREE.AxesHelper(5);
    // Red=X(East), Green=Y(Up), Blue=Z(North)
    gnssScene.add(axesHelper);

    // Data points
    const e = timeSeries.e || [];
    const n = timeSeries.n || [];
    const u = timeSeries.u || [];

    // Default fallback if e,n,u missing
    if (!e.length && timeSeries.displacement) {
        // Just make a dummy random path if backend didn't update yet
        for (let i = 0; i < timeSeries.displacement.length; i++) {
            e.push(i * 2); n.push(Math.sin(i) * 2); u.push(Math.cos(i) * 2);
        }
    }

    if (e.length === 0) return;

    // Normalize scale to fit nicely in view
    let maxVal = 0.01;
    for (let i = 0; i < e.length; i++) {
        maxVal = Math.max(maxVal, Math.abs(e[i]), Math.abs(n[i]), Math.abs(u[i]));
    }
    const scaleFactor = 5 / maxVal;

    // Create Path Line
    const points = [];
    for (let i = 0; i < e.length; i++) {
        // Note: in ThreeJS, Y is up. Data usually has E=X, N=Y, U=Z or similar.
        // We'll map E -> X, U -> Y, N -> Z (standard right handed, Y up)
        points.push(new THREE.Vector3(e[i] * scaleFactor, u[i] * scaleFactor, -n[i] * scaleFactor));
    }

    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({ color: 0x0ea5e9, linewidth: 2 });
    const line = new THREE.Line(geometry, material);
    gnssScene.add(line);

    // Current point sphere
    const sphereGeo = new THREE.SphereGeometry(0.3, 16, 16);
    const sphereMat = new THREE.MeshBasicMaterial({ color: 0xff0000 });
    const sphere = new THREE.Mesh(sphereGeo, sphereMat);
    gnssScene.add(sphere);

    // Analysis mode: keep marker at the latest GNSS position (no autoplay movement).
    if (points.length > 0) {
        sphere.position.copy(points.at(-1));
    }

    function animate() {
        gnssAnimationId = requestAnimationFrame(animate);

        gnssControls.update();
        gnssRenderer.render(gnssScene, gnssCamera);
    }
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
        gnssControls.update();
        gnssRenderer.render(gnssScene, gnssCamera);
    } else animate();

    // Resize handler + ResizeObserver for proper sizing after CSS transitions
    function handleGnssResize() {
        if (!container || !gnssRenderer || !gnssCamera) return;
        const d = getContainerDims(container);
        gnssCamera.aspect = d.w / d.h;
        gnssCamera.updateProjectionMatrix();
        gnssRenderer.setSize(d.w, d.h);
    }
    window.addEventListener('resize', handleGnssResize);
    gnssResizeHandler = handleGnssResize;
    if (typeof ResizeObserver !== 'undefined') {
        gnssResizeObserver = new ResizeObserver(() => handleGnssResize());
        gnssResizeObserver.observe(container);
    }
}

function initIMU3D(timeSeries, THREE, OrbitControls) {
    const container = document.getElementById('container-3d-imu');
    if (!container) return;

    disposeImu3D();
    container.innerHTML = '';

    imuScene = new THREE.Scene();
    // Premium dark gradient background - we'll just use a color but add fog
    imuScene.background = new THREE.Color(0x0b0e14);
    imuScene.fog = new THREE.FogExp2(0x0b0e14, 0.03);

    const dims = getContainerDims(container);
    const aspect = dims.w / dims.h;
    imuCamera = new THREE.PerspectiveCamera(45, aspect, 0.1, 100);
    imuCamera.position.set(5, 6, 8);

    imuRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    imuRenderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    imuRenderer.setSize(dims.w, dims.h);
    imuRenderer.shadowMap.enabled = true;
    imuRenderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container.appendChild(imuRenderer.domElement);

    imuControls = new OrbitControls(imuCamera, imuRenderer.domElement);
    imuControls.enableDamping = true;
    imuControls.dampingFactor = 0.05;
    imuControls.maxPolarAngle = Math.PI / 2 + 0.1; // Limit below ground
    imuControls.minDistance = 3;
    imuControls.maxDistance = 15;

    // Advanced Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    imuScene.add(ambientLight);

    const hemiLight = new THREE.HemisphereLight(0xddeeff, 0x0f0e1d, 0.5);
    imuScene.add(hemiLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
    dirLight.position.set(5, 10, 7);
    dirLight.castShadow = true;
    dirLight.shadow.mapSize.width = 1024;
    dirLight.shadow.mapSize.height = 1024;
    dirLight.shadow.camera.near = 0.5;
    dirLight.shadow.camera.far = 25;
    dirLight.shadow.camera.left = -5;
    dirLight.shadow.camera.right = 5;
    dirLight.shadow.camera.top = 5;
    dirLight.shadow.camera.bottom = -5;
    dirLight.shadow.bias = -0.001;
    imuScene.add(dirLight);

    const pointLight = new THREE.PointLight(0x00e5ff, 2, 8);
    pointLight.position.set(0, 1.5, 0);
    imuScene.add(pointLight);

    // Floor with grid
    const floorGeo = new THREE.PlaneGeometry(30, 30);
    const floorMat = new THREE.MeshStandardMaterial({
        color: 0x0b0e14,
        roughness: 0.8,
        metalness: 0.2
    });
    const floor = new THREE.Mesh(floorGeo, floorMat);
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -1.5;
    floor.receiveShadow = true;
    imuScene.add(floor);

    const grid = new THREE.GridHelper(30, 30, 0x00e5ff, 0x222233);
    grid.position.y = -1.49;
    grid.material.opacity = 0.15;
    grid.material.transparent = true;
    imuScene.add(grid);

    // ==========================================
    // REALISTIC IMU BLACK BOX MOUNT DESIGN
    // ==========================================
    const sensorBlock = new THREE.Group();

    // 1. Silver Base Plate (Circular)
    const plateRadius = 2.0;
    const plateThickness = 0.1;
    const plateGeo = new THREE.CylinderGeometry(plateRadius, plateRadius, plateThickness, 32);
    const plateMat = new THREE.MeshStandardMaterial({
        color: 0xcccccc, // Silver
        metalness: 0.8,
        roughness: 0.3
    });
    const plate = new THREE.Mesh(plateGeo, plateMat);
    plate.position.y = plateThickness / 2;
    plate.castShadow = true;
    plate.receiveShadow = true;
    sensorBlock.add(plate);

    // 2. The Black IMU Box (Main Sensor)
    const boxWidth = 2.2;
    const boxHeight = 1.0;
    const boxDepth = 2.2;
    const boxGeo = new THREE.BoxGeometry(boxWidth, boxHeight, boxDepth);
    const boxMat = new THREE.MeshStandardMaterial({
        color: 0x111111, // Flat black
        metalness: 0.2,
        roughness: 0.8,
        bumpScale: 0.02
    });
    const imuBox = new THREE.Mesh(boxGeo, boxMat);
    imuBox.position.y = plateThickness + boxHeight / 2;
    imuBox.castShadow = true;
    imuBox.receiveShadow = true;
    sensorBlock.add(imuBox);

    // 3. Direction Indicator (Simple white arrow on top of black box)
    const arrowGeo = new THREE.ConeGeometry(0.15, 0.4, 16);
    const arrowMat = new THREE.MeshStandardMaterial({ color: 0xffffff });
    const arrow = new THREE.Mesh(arrowGeo, arrowMat);
    // Point it forward (along Z axis)
    arrow.rotation.x = Math.PI / 2;
    arrow.position.set(0, plateThickness + boxHeight + 0.05, boxDepth / 2 - 0.3);
    sensorBlock.add(arrow);

    // 4. Mounting Screws on the plate
    // 4. Mounting Screws on the plate — cardinal positions (N/S/E/W)
    const screwGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.15, 16);
    const screwMat = new THREE.MeshStandardMaterial({ color: 0x999999, metalness: 0.9, roughness: 0.2 });
    const screwRadius = plateRadius - 0.3;

    for (let i = 0; i < 4; i++) {
        const angle = (i * Math.PI) / 2; // 0°, 90°, 180°, 270° → mỗi mặt
        const screw = new THREE.Mesh(screwGeo, screwMat);
        screw.position.set(Math.cos(angle) * screwRadius, plateThickness, Math.sin(angle) * screwRadius);
        sensorBlock.add(screw);
    }

    // 5. Add visual XYZ axis indicators
    const origin = new THREE.Vector3(0, plateThickness + boxHeight + 0.2, 0);
    const xArrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), origin, 1.2, 0xff2a5f, 0.2, 0.15); // Red X
    const yArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), origin, 1.2, 0x00e5ff, 0.2, 0.15); // Cyan Y (Up)
    const zArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), origin, 1.2, 0x00ff88, 0.2, 0.15); // Green Z
    sensorBlock.add(xArrow, yArrow, zArrow);

    imuScene.add(sensorBlock);

    // ==========================================
    // GUY WIRES — 4 cáp neo thể hiện hướng lệch
    // ==========================================
    const _gwDist = 5.5;
    const _gwFloor = -1.49;
    const _gwScrewR = plateRadius - 0.3;
    const _gwSpecs = [
        { local: new THREE.Vector3(_gwScrewR, plateThickness, 0), anchor: [_gwDist, _gwFloor, 0], color: 0xff6b35 }, // Roll+
        { local: new THREE.Vector3(-_gwScrewR, plateThickness, 0), anchor: [-_gwDist, _gwFloor, 0], color: 0xff6b35 }, // Roll-
        { local: new THREE.Vector3(0, plateThickness, _gwScrewR), anchor: [0, _gwFloor, _gwDist], color: 0x00d4ff }, // Pitch+
        { local: new THREE.Vector3(0, plateThickness, -_gwScrewR), anchor: [0, _gwFloor, -_gwDist], color: 0x00d4ff }, // Pitch-
    ];
    const imuWires = _gwSpecs.map(spec => {
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
        const mat = new THREE.LineBasicMaterial({ color: spec.color, linewidth: 2 });
        const line = new THREE.Line(geo, mat);
        imuScene.add(line);
        // Anchor peg
        const peg = new THREE.Mesh(
            new THREE.CylinderGeometry(0.08, 0.08, 0.25, 8),
            new THREE.MeshStandardMaterial({ color: spec.color, metalness: 0.7, roughness: 0.3, emissive: spec.color, emissiveIntensity: 0.25 })
        );
        peg.position.set(spec.anchor[0], _gwFloor + 0.12, spec.anchor[2]);
        imuScene.add(peg);
        return { line, local: spec.local, anchor: new THREE.Vector3(...spec.anchor) };
    });

    // Data parsing (backend sends 'rolls'/'pitches' plural)
    const rollData = timeSeries.rolls || timeSeries.roll || [];
    const pitchData = timeSeries.pitches || timeSeries.pitch || [];

    // Analysis mode: use the latest tilt sample and keep IMU model static.
    const hasTilt = rollData.length > 0 && pitchData.length > 0;
    if (hasTilt) {
        const lastIdx = Math.min(rollData.length, pitchData.length) - 1;
        const finalPitch = (pitchData[lastIdx] || 0) * Math.PI / 180;
        const finalRoll = (rollData[lastIdx] || 0) * Math.PI / 180;
        const finalQ = new THREE.Quaternion();
        finalQ.setFromEuler(new THREE.Euler(finalPitch, 0, finalRoll, 'XYZ'));
        sensorBlock.quaternion.copy(finalQ);
    }

    function animate() {
        if (!matchMedia('(prefers-reduced-motion: reduce)').matches) imuAnimationId = requestAnimationFrame(animate);

        // Cập nhật guy wires
        sensorBlock.updateMatrixWorld();
        imuWires.forEach(w => {
            const wp = w.local.clone().applyMatrix4(sensorBlock.matrixWorld);
            const attr = w.line.geometry.attributes.position;
            attr.setXYZ(0, wp.x, wp.y, wp.z);
            attr.setXYZ(1, w.anchor.x, w.anchor.y, w.anchor.z);
            attr.needsUpdate = true;
        });
        imuControls.update();
        imuRenderer.render(imuScene, imuCamera);
    }
    animate();

    // Resize handler + ResizeObserver for proper sizing after CSS transitions
    function handleImuResize() {
        if (!container || !imuRenderer || !imuCamera) return;
        const d = getContainerDims(container);
        imuCamera.aspect = d.w / d.h;
        imuCamera.updateProjectionMatrix();
        imuRenderer.setSize(d.w, d.h);
    }
    window.addEventListener('resize', handleImuResize);
    imuResizeHandler = handleImuResize;
    if (typeof ResizeObserver !== 'undefined') {
        imuResizeObserver = new ResizeObserver(() => handleImuResize());
        imuResizeObserver.observe(container);
    }
}

async function initRealtimeIMU3D(initialRoll, initialPitch) {
    const container = document.getElementById('realtime-imu-3d-scene');
    if (!container) return;

    disposeRealtimeImu3D();
    container.innerHTML = '';

    try {
        const THREE = await import('three');
        _THREE = THREE; // Cache for realtime updates
        const { OrbitControls } = await import('three/addons/controls/OrbitControls.js');

        realtimeImuScene = new THREE.Scene();
        realtimeImuScene.background = new THREE.Color(0x0b0e14);
        realtimeImuScene.fog = new THREE.FogExp2(0x0b0e14, 0.03);

        // Wait for wrapper to be visible before measuring
        await waitForContainerSize(container, 2000);
        const dims = getContainerDims(container);
        const aspect = dims.w / dims.h;
        realtimeImuCamera = new THREE.PerspectiveCamera(45, aspect, 0.1, 100);
        realtimeImuCamera.position.set(5, 6, 8);

        realtimeImuRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        realtimeImuRenderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
        realtimeImuRenderer.setSize(dims.w, dims.h);
        realtimeImuRenderer.shadowMap.enabled = true;
        realtimeImuRenderer.shadowMap.type = THREE.PCFSoftShadowMap;
        container.appendChild(realtimeImuRenderer.domElement);

        realtimeImuControls = new OrbitControls(realtimeImuCamera, realtimeImuRenderer.domElement);
        realtimeImuControls.enableDamping = true;
        realtimeImuControls.dampingFactor = 0.05;
        realtimeImuControls.maxPolarAngle = Math.PI / 2 + 0.1;
        realtimeImuControls.minDistance = 3;
        realtimeImuControls.maxDistance = 15;

        // Advanced Lighting
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
        realtimeImuScene.add(ambientLight);

        const hemiLight = new THREE.HemisphereLight(0xddeeff, 0x0f0e1d, 0.5);
        realtimeImuScene.add(hemiLight);

        const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
        dirLight.position.set(5, 10, 7);
        dirLight.castShadow = true;
        realtimeImuScene.add(dirLight);

        const pointLight = new THREE.PointLight(0x00e5ff, 2, 8);
        pointLight.position.set(0, 1.5, 0);
        realtimeImuScene.add(pointLight);

        // Floor
        const floorGeo = new THREE.PlaneGeometry(30, 30);
        const floorMat = new THREE.MeshStandardMaterial({
            color: 0x0b0e14, roughness: 0.8, metalness: 0.2
        });
        const floor = new THREE.Mesh(floorGeo, floorMat);
        floor.rotation.x = -Math.PI / 2;
        floor.position.y = -1.5;
        floor.receiveShadow = true;
        realtimeImuScene.add(floor);

        const grid = new THREE.GridHelper(30, 30, 0x00e5ff, 0x222233);
        grid.position.y = -1.49;
        grid.material.opacity = 0.15;
        grid.material.transparent = true;
        realtimeImuScene.add(grid);

        // Realistic IMU mounting
        realtimeImuSensorBlock = new THREE.Group();

        // Base Plate
        const plateRadius = 2.0;
        const plateThickness = 0.1;
        const plateGeo = new THREE.CylinderGeometry(plateRadius, plateRadius, plateThickness, 32);
        const plateMat = new THREE.MeshStandardMaterial({ color: 0xcccccc, metalness: 0.8, roughness: 0.3 });
        const plate = new THREE.Mesh(plateGeo, plateMat);
        plate.position.y = plateThickness / 2;
        plate.castShadow = true;
        plate.receiveShadow = true;
        realtimeImuSensorBlock.add(plate);

        // IMU Box
        const boxWidth = 2.2;
        const boxHeight = 1.0;
        const boxDepth = 2.2;
        const boxGeo = new THREE.BoxGeometry(boxWidth, boxHeight, boxDepth);
        const boxMat = new THREE.MeshStandardMaterial({ color: 0x111111, metalness: 0.2, roughness: 0.8 });
        const imuBox = new THREE.Mesh(boxGeo, boxMat);
        imuBox.position.y = plateThickness + boxHeight / 2;
        imuBox.castShadow = true;
        imuBox.receiveShadow = true;
        realtimeImuSensorBlock.add(imuBox);

        // Arrow
        const arrowGeo = new THREE.ConeGeometry(0.15, 0.4, 16);
        const arrowMat = new THREE.MeshStandardMaterial({ color: 0xffffff });
        const arrow = new THREE.Mesh(arrowGeo, arrowMat);
        arrow.rotation.x = Math.PI / 2;
        arrow.position.set(0, plateThickness + boxHeight + 0.05, boxDepth / 2 - 0.3);
        realtimeImuSensorBlock.add(arrow);

        // Screws
        // Screws — cardinal positions
        const screwGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.15, 16);
        const screwMat = new THREE.MeshStandardMaterial({ color: 0x999999, metalness: 0.9, roughness: 0.2 });
        const screwRadius = plateRadius - 0.3;
        for (let i = 0; i < 4; i++) {
            const angle = (i * Math.PI) / 2;
            const screw = new THREE.Mesh(screwGeo, screwMat);
            screw.position.set(Math.cos(angle) * screwRadius, plateThickness, Math.sin(angle) * screwRadius);
            realtimeImuSensorBlock.add(screw);
        }

        // Axes Support
        const origin = new THREE.Vector3(0, plateThickness + boxHeight + 0.2, 0);
        const xArrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), origin, 1.2, 0xff2a5f, 0.2, 0.15);
        const yArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), origin, 1.2, 0x00e5ff, 0.2, 0.15);
        const zArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), origin, 1.2, 0x00ff88, 0.2, 0.15);
        realtimeImuSensorBlock.add(xArrow, yArrow, zArrow);

        realtimeImuScene.add(realtimeImuSensorBlock);

        // ==========================================
        // GUY WIRES — 4 cáp neo realtime
        // ==========================================
        const _rtGwDist = 5.5;
        const _rtGwFloor = -1.49;
        const _rtGwScrewR = plateRadius - 0.3;
        const _rtGwSpecs = [
            { local: new THREE.Vector3(_rtGwScrewR, plateThickness, 0), anchor: [_rtGwDist, _rtGwFloor, 0], color: 0xff6b35 },
            { local: new THREE.Vector3(-_rtGwScrewR, plateThickness, 0), anchor: [-_rtGwDist, _rtGwFloor, 0], color: 0xff6b35 },
            { local: new THREE.Vector3(0, plateThickness, _rtGwScrewR), anchor: [0, _rtGwFloor, _rtGwDist], color: 0x00d4ff },
            { local: new THREE.Vector3(0, plateThickness, -_rtGwScrewR), anchor: [0, _rtGwFloor, -_rtGwDist], color: 0x00d4ff },
        ];
        const rtImuWires = _rtGwSpecs.map(spec => {
            const geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
            const mat = new THREE.LineBasicMaterial({ color: spec.color, linewidth: 2 });
            const line = new THREE.Line(geo, mat);
            realtimeImuScene.add(line);
            const peg = new THREE.Mesh(
                new THREE.CylinderGeometry(0.08, 0.08, 0.25, 8),
                new THREE.MeshStandardMaterial({ color: spec.color, metalness: 0.7, roughness: 0.3, emissive: spec.color, emissiveIntensity: 0.25 })
            );
            peg.position.set(spec.anchor[0], _rtGwFloor + 0.12, spec.anchor[2]);
            realtimeImuScene.add(peg);
            return { line, local: spec.local, anchor: new THREE.Vector3(...spec.anchor) };
        });

        // Initial orientation
        const currPitch = initialPitch * Math.PI / 180;
        const currRoll = initialRoll * Math.PI / 180;
        realtimeImuTargetQuaternion = new THREE.Quaternion();
        const euler = new THREE.Euler(currPitch, 0, currRoll, 'XYZ');
        realtimeImuTargetQuaternion.setFromEuler(euler);

        function animate() {
            if (!matchMedia('(prefers-reduced-motion: reduce)').matches) realtimeImuAnimationId = requestAnimationFrame(animate);

            if (realtimeImuTargetQuaternion) {
                realtimeImuSensorBlock.quaternion.slerp(realtimeImuTargetQuaternion, 0.1);
            }

            // Cập nhật guy wires realtime
            realtimeImuSensorBlock.updateMatrixWorld();
            rtImuWires.forEach(w => {
                const wp = w.local.clone().applyMatrix4(realtimeImuSensorBlock.matrixWorld);
                const attr = w.line.geometry.attributes.position;
                attr.setXYZ(0, wp.x, wp.y, wp.z);
                attr.setXYZ(1, w.anchor.x, w.anchor.y, w.anchor.z);
                attr.needsUpdate = true;
            });
            realtimeImuControls.update();
            realtimeImuRenderer.render(realtimeImuScene, realtimeImuCamera);
        }
        animate();

        // Resize handler + ResizeObserver for proper sizing
        function handleRealtimeImuResize() {
            if (!container || !realtimeImuRenderer || !realtimeImuCamera) return;
            const d = getContainerDims(container);
            realtimeImuCamera.aspect = d.w / d.h;
            realtimeImuCamera.updateProjectionMatrix();
            realtimeImuRenderer.setSize(d.w, d.h);
        }
        window.addEventListener('resize', handleRealtimeImuResize);
        realtimeImuResizeHandler = handleRealtimeImuResize;
        if (typeof ResizeObserver !== 'undefined') {
            realtimeImuResizeObserver = new ResizeObserver(() => handleRealtimeImuResize());
            realtimeImuResizeObserver.observe(container);
        }

    } catch (e) {
        console.error("ThreeJS not loaded for realtime IMU", e);
    }
}

function renderImuLongTermSection(imuData) {
    const nodataEl = document.getElementById('imu-longterm-nodata');
    const contentEl = document.getElementById('imu-longterm-content');

    if (!imuData || imuData.status !== 'success') {
        if (nodataEl) {
            nodataEl.style.display = 'block';
            const msgEl = document.getElementById('imu-nodata-msg');
            if (msgEl) msgEl.textContent = imuData?.message || 'Không đủ dữ liệu IMU để phân tích.';
        }
        if (contentEl) contentEl.style.display = 'none';
        return;
    }

    if (nodataEl) nodataEl.style.display = 'none';
    if (contentEl) contentEl.style.display = 'block';

    const analysis = imuData.analysis;

    // Warning banner
    const warningEl = document.getElementById('imu-longterm-warning');
    const warningTextEl = document.getElementById('imu-warning-text');
    if (imuData.risk_level === 'EXTREME' || imuData.risk_level === 'HIGH' || imuData.risk_level === 'MEDIUM') {
        warningEl.style.display = 'block';
        warningEl.className = `alert ${imuData.risk_level === 'EXTREME' ? 'alert-danger' : 'alert-warning'} mb-3`;
        warningTextEl.textContent = sanitizeLongTermText(imuData.warning_message);
    } else {
        warningEl.style.display = 'none';
    }

    // Metrics
    setText('lt-imu-tilt-change', `${safeNumber(analysis.total_tilt_change_deg, 2)}°`);
    setText('lt-imu-rate', `${safeNumber(analysis.avg_rate_deg_per_day, 4)}°/ngày`);
    setText('lt-imu-max-roll', `${safeNumber(analysis.max_roll_deg, 2)}°`);
    setText('lt-imu-max-pitch', `${safeNumber(analysis.max_pitch_deg, 2)}°`);
    setText('lt-imu-points', analysis.data_points || '--');
    setText('lt-imu-duration', formatDurationString(analysis.duration_days));

    // Trend
    const trendIcons = { 'accelerating': '', 'stable': '', 'decelerating': '' };
    const trendTexts = { 'accelerating': 'Đang tăng tốc', 'stable': 'Ổn định', 'decelerating': 'Đang giảm tốc' };
    document.getElementById('imu-trend-icon').textContent = trendIcons[analysis.trend] || '';
    document.getElementById('imu-trend-value').textContent = trendTexts[analysis.trend] || 'Không xác định';
}
