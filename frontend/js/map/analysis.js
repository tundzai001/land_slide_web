// =========================================================================
// COMBINED LONG-TERM CHART (GNSS + IMU on dual Y-axes)
// =========================================================================
function renderCombinedLongTermChart(data) {
    const ctx = document.getElementById('chart-longterm-combined');
    if (!ctx) return;

    if (charts['chart-longterm-combined']) {
        charts['chart-longterm-combined'].destroy();
    }

    const datasets = [];
    let allLabels = [];
    let hasGnss = false;
    let hasImu = false;

    // GNSS displacement → left Y-axis
    const gnss = data.gnss;
    if (gnss && gnss.status === 'success' && gnss.time_series && gnss.time_series.labels.length > 0) {
        allLabels = gnss.time_series.labels;
        hasGnss = true;
        datasets.push({
            label: 'GNSS Displacement (mm)',
            data: gnss.time_series.displacement,
            borderColor: '#0ea5e9',
            backgroundColor: 'rgba(14, 165, 233, 0.08)',
            tension: 0.4,
            borderWidth: 2.5,
            fill: true,
            pointRadius: 3,
            pointHoverRadius: 5,
            yAxisID: 'y-gnss'
        });
    }

    // IMU roll/pitch → right Y-axis
    const imu = data.imu;
    if (imu && imu.status === 'success' && imu.time_series) {
        hasImu = true;
        // Use IMU labels if no GNSS labels, or merge
        if (allLabels.length === 0) {
            allLabels = imu.time_series.labels;
        }

        datasets.push({
            label: 'Roll (°)',
            data: imu.time_series.roll,
            borderColor: '#f59e0b',
            backgroundColor: 'transparent',
            tension: 0.4,
            borderWidth: 2,
            borderDash: [5, 3],
            fill: false,
            pointRadius: 2,
            pointHoverRadius: 4,
            yAxisID: 'y-imu'
        });

        datasets.push({
            label: 'Pitch (°)',
            data: imu.time_series.pitch,
            borderColor: '#8b5cf6',
            backgroundColor: 'transparent',
            tension: 0.4,
            borderWidth: 2,
            borderDash: [5, 3],
            fill: false,
            pointRadius: 2,
            pointHoverRadius: 4,
            yAxisID: 'y-imu'
        });
    }

    if (datasets.length === 0) return;

    // Build scales
    const scales = {
        x: {
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: 'var(--text-secondary)', maxRotation: 45 }
        }
    };

    if (hasGnss) {
        scales['y-gnss'] = {
            type: 'linear',
            position: 'left',
            title: { display: true, text: 'Displacement (mm)', color: '#0ea5e9' },
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: '#0ea5e9', callback: v => v + ' mm' }
        };
    }

    if (hasImu) {
        scales['y-imu'] = {
            type: 'linear',
            position: hasGnss ? 'right' : 'left',
            title: { display: true, text: 'Góc nghiêng (°)', color: '#f59e0b' },
            grid: { drawOnChartArea: !hasGnss, color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: '#f59e0b', callback: v => v + '°' }
        };
    }

    // If only IMU (no GNSS), reassign yAxisID to y-imu for consistency
    if (!hasGnss && hasImu) {
        datasets.forEach(ds => { ds.yAxisID = 'y-imu'; });
    }

    charts['chart-longterm-combined'] = new Chart(ctx, {
        type: 'line',
        data: { labels: allLabels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    display: true,
                    labels: { color: 'var(--text-primary)', usePointStyle: true, padding: 16 }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.85)',
                    padding: 12,
                    titleFont: { weight: 'bold' }
                }
            },
            scales
        }
    });
}



function showLongTermError(message) {
    document.getElementById('longterm-loading').style.display = 'none';
    document.getElementById('longterm-content').style.display = 'none';
    document.getElementById('longterm-error').style.display = 'block';

    const errorMessageEl = document.getElementById('error-message');
    if (errorMessageEl) {
        errorMessageEl.textContent = message;
    }
}

// =========================================================================
// INVERSE VELOCITY (FUKUZONO) SECTION
// =========================================================================
function renderInverseVelocitySection(data) {
    const section = document.getElementById('inverse-velocity-section');
    if (!section) return;

    const invVel = data.gnss?.inverse_velocity;
    if (!invVel || !invVel.available) {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';

    // Warning
    const warningEl = document.getElementById('inv-vel-warning');
    const warningTextEl = document.getElementById('inv-vel-warning-text');
    if (invVel.predicted_failure) {
        warningEl.style.display = 'block';
        warningTextEl.textContent = sanitizeLongTermText(invVel.message);
    } else {
        warningEl.style.display = 'none';
    }

    // Metrics
    setText('inv-vel-prediction', invVel.predicted_failure
        ? `Có — ${invVel.predicted_failure_date ? new Date(invVel.predicted_failure_date).toLocaleDateString('vi-VN') : ''}`
        : 'Không');
    setText('inv-vel-days', invVel.predicted_failure
        ? `~${invVel.days_to_failure} ngày`
        : 'N/A');
    setText('inv-vel-r2', invVel.r_squared !== undefined ? invVel.r_squared.toFixed(4) : '--');
    setText('inv-vel-confidence', invVel.confidence
        ? (invVel.confidence === 'high' ? 'Cao' : 'Trung bình')
        : sanitizeLongTermText(invVel.message) || '--');

    // Chart
    if (invVel.time_series) {
        const ctx = document.getElementById('chart-inverse-velocity');
        if (!ctx) return;
        if (charts['chart-inverse-velocity']) {
            charts['chart-inverse-velocity'].destroy();
        }

        charts['chart-inverse-velocity'] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: invVel.time_series.labels,
                datasets: [
                    {
                        label: 'hệ số (thời gian thực)',
                        data: invVel.time_series.inverse_velocity,
                        borderColor: '#ef4444',
                        backgroundColor: 'rgba(239, 68, 68, 0.1)',
                        tension: 0.3,
                        borderWidth: 2,
                        pointRadius: 3,
                        fill: true
                    },
                    {
                        label: 'Đường xu hướng',
                        data: invVel.time_series.trend_line,
                        borderColor: '#fbbf24',
                        borderWidth: 2,
                        borderDash: [8, 4],
                        pointRadius: 0,
                        fill: false
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        labels: { color: 'var(--text-primary)', usePointStyle: true }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(0,0,0,0.85)',
                        padding: 12
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: 'var(--text-secondary)' }
                    },
                    y: {
                        title: { display: true, text: '1/Velocity (day/mm)', color: '#ef4444' },
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: '#ef4444' }
                    }
                }
            }
        });
    }
}

// =========================================================================
// RAINFALL-DISPLACEMENT CORRELATION SECTION
// =========================================================================
function renderRainfallCorrelationSection(data) {
    const section = document.getElementById('rainfall-correlation-section');
    if (!section) return;

    const rainCorr = data.rainfall_correlation;

    // Nếu chưa bật AI Slide model thì ẩn section (chỉ hiện khi user đã bấm nút)
    if (!isRainCorrelationAiEnabled) {
        section.style.display = 'none';
        return;
    }

    if (!rainCorr || !rainCorr.available) {
        // Show the section with an informative status message instead of hiding it
        const msg = (rainCorr && rainCorr.message)
            ? rainCorr.message
            : 'Không đủ dữ liệu để chạy Slide model. Cần ít nhất 3 ngày chung giữa GNSS và cảm biến mưa.';
        section.style.display = 'block';
        section.innerHTML = `
            <h5 class="mb-3 text-info border-bottom pb-2">
                <i class="bi bi-cloud-rain me-2"></i>Tương quan Mưa - Dịch chuyển (Slide model v2)
            </h5>
            <div class="alert alert-warning d-flex align-items-start gap-2 mb-0" role="alert">
                <i class="bi bi-exclamation-triangle-fill flex-shrink-0 mt-1"></i>
                <div>
                    <strong>Không thể chạy phân tích Slide model</strong><br>
                    <span class="small">${msg}</span>
                </div>
            </div>`;
        return;
    }

    // Restore full section HTML in case it was replaced by the error state
    if (!document.getElementById('rain-correlation')) {
        section.innerHTML = `
            <h5 class="mb-3 text-info border-bottom pb-2">
                <i class="bi bi-cloud-rain me-2"></i>Tương quan Mưa - Dịch chuyển (Slide model v2)
            </h5>
            <div class="row g-3 mb-3">
                <div class="col-md-2 col-6">
                    <div class="longterm-metric-card">
                        <div class="text-muted small">Hệ số r</div>
                        <div class="fs-4 fw-bold text-info mt-1" id="rain-correlation">--</div>
                    </div>
                </div>
                <div class="col-md-2 col-6">
                    <div class="longterm-metric-card">
                        <div class="text-muted small">R²</div>
                        <div class="fs-5 fw-bold mt-1" id="rain-r2">--</div>
                    </div>
                </div>
                <div class="col-md-2 col-6">
                    <div class="longterm-metric-card">
                        <div class="text-muted small">Lag</div>
                        <div class="fs-5 fw-bold mt-1" id="rain-lag">--</div>
                    </div>
                </div>
                <div class="col-md-2 col-6">
                    <div class="longterm-metric-card">
                        <div class="text-muted small">Trigger</div>
                        <div class="fs-5 fw-bold mt-1" id="rain-trigger">--</div>
                    </div>
                </div>
                <div class="col-md-2 col-6">
                    <div class="longterm-metric-card">
                        <div class="text-muted small">Mức tương quan</div>
                        <div class="fs-5 fw-bold mt-1" id="rain-strength">--</div>
                    </div>
                </div>
                <div class="col-md-2 col-6">
                    <div class="longterm-metric-card">
                        <div class="text-muted small">Độ nhạy</div>
                        <div class="fs-5 fw-bold mt-1" id="rain-sensitivity">--</div>
                    </div>
                </div>
                <div class="col-md-12">
                    <div class="longterm-metric-card">
                        <div class="text-muted small">Nhận xét rủi ro</div>
                        <div class="fs-6 mt-1" id="rain-assessment">--</div>
                    </div>
                </div>
            </div>
            <div class="row g-3">
                <div class="col-md-6">
                    <div class="chart-box border-0 shadow-sm">
                        <div class="chart-title"><i class="bi bi-moisture me-2"></i>Mưa tích lũy vs Dịch chuyển tích lũy</div>
                        <div style="height: 350px; padding: 10px;">
                            <canvas id="chart-rainfall-correlation"></canvas>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="chart-box border-0 shadow-sm">
                        <div class="chart-title"><i class="bi bi-graph-up-arrow me-2"></i>Slide model Index vs Dịch chuyển ngày</div>
                        <div style="height: 350px; padding: 10px;">
                            <canvas id="chart-sm-model-index"></canvas>
                        </div>
                    </div>
                </div>
            </div>`;
    }

    section.style.display = 'block';

    // Metrics
    const corrVal = rainCorr.correlation;
    const corrColor = Math.abs(corrVal) >= 0.6 ? 'text-danger' : Math.abs(corrVal) >= 0.4 ? 'text-warning' : 'text-info';
    const corrEl = document.getElementById('rain-correlation');
    if (corrEl) {
        corrEl.textContent = corrVal.toFixed(4);
        corrEl.className = `fs-4 fw-bold mt-1 ${corrColor}`;
    }
    setText('rain-strength', rainCorr.strength || '--');
    setText('rain-r2', rainCorr.r_squared != null ? rainCorr.r_squared.toFixed(4) : '--');
    setText('rain-lag', rainCorr.lag_days != null ? `${rainCorr.lag_days} ngày` : '--');

    // Trigger with color
    const triggerEl = document.getElementById('rain-trigger');
    if (triggerEl) {
        const tp = String(rainCorr.trigger_potential || 'LOW').toUpperCase();
        triggerEl.textContent = tp;
        triggerEl.className = 'fs-5 fw-bold mt-1 ' + (tp === 'HIGH' ? 'text-danger' : tp === 'MEDIUM' ? 'text-warning' : 'text-success');
    }

    // Sensitivity
    setText('rain-sensitivity', rainCorr.sensitivity_mm_per_mm != null
        ? `${rainCorr.sensitivity_mm_per_mm} mm/mm` : '--');

    // Assessment — prioritize risk_message if present
    setText('rain-assessment', rainCorr.risk_message || rainCorr.assessment || '--');

    // Chart 1: Dual-axis — cumulative displacement + cumulative/daily rainfall
    if (rainCorr.time_series) {
        const ctx = document.getElementById('chart-rainfall-correlation');
        if (ctx) {
            if (charts['chart-rainfall-correlation']) {
                charts['chart-rainfall-correlation'].destroy();
            }

            charts['chart-rainfall-correlation'] = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: rainCorr.time_series.labels,
                    datasets: [
                        {
                            label: 'Dịch chuyển tích lũy (mm)',
                            data: rainCorr.time_series.cumulative_displacement_mm,
                            borderColor: '#0ea5e9',
                            backgroundColor: 'rgba(14, 165, 233, 0.08)',
                            tension: 0.4,
                            borderWidth: 2.5,
                            fill: true,
                            pointRadius: 2,
                            yAxisID: 'y-disp'
                        },
                        {
                            label: 'Mưa tích lũy (mm)',
                            data: rainCorr.time_series.cumulative_rainfall_mm,
                            borderColor: '#10b981',
                            backgroundColor: 'transparent',
                            tension: 0.4,
                            borderWidth: 2,
                            borderDash: [5, 3],
                            fill: false,
                            pointRadius: 2,
                            yAxisID: 'y-rain'
                        },
                        {
                            label: 'Mưa ngày (mm)',
                            type: 'bar',
                            data: rainCorr.time_series.daily_rainfall_mm,
                            backgroundColor: 'rgba(59, 130, 246, 0.3)',
                            borderColor: '#3b82f6',
                            borderWidth: 1,
                            yAxisID: 'y-rain'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    plugins: {
                        legend: {
                            labels: { color: 'var(--text-primary)', usePointStyle: true, padding: 16 }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0,0,0,0.85)',
                            padding: 12
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(255,255,255,0.05)' },
                            ticks: { color: 'var(--text-secondary)', maxRotation: 45 }
                        },
                        'y-disp': {
                            type: 'linear',
                            position: 'left',
                            title: { display: true, text: 'Dịch chuyển (mm)', color: '#0ea5e9' },
                            grid: { color: 'rgba(255,255,255,0.05)' },
                            ticks: { color: '#0ea5e9' }
                        },
                        'y-rain': {
                            type: 'linear',
                            position: 'right',
                            title: { display: true, text: 'Lượng mưa (mm)', color: '#10b981' },
                            grid: { drawOnChartArea: false },
                            ticks: { color: '#10b981' }
                        }
                    }
                }
            });
        }

        // Chart 2: Slide model Index vs Daily Displacement
        const ctx2 = document.getElementById('chart-sm-model-index');
        if (ctx2 && rainCorr.time_series.slide_model_index) {
            if (charts['chart-sm-model-index']) {
                charts['chart-sm-model-index'].destroy();
            }

            charts['chart-sm-model-index'] = new Chart(ctx2, {
                type: 'line',
                data: {
                    labels: rainCorr.time_series.labels,
                    datasets: [
                        {
                            label: 'Slide model Index',
                            data: rainCorr.time_series.slide_model_index,
                            borderColor: '#f59e0b',
                            backgroundColor: 'rgba(245, 158, 11, 0.1)',
                            tension: 0.4,
                            borderWidth: 2.5,
                            fill: true,
                            pointRadius: 2,
                            yAxisID: 'y-idx'
                        },
                        {
                            label: 'Dịch chuyển ngày (mm)',
                            data: rainCorr.time_series.daily_displacement_mm,
                            borderColor: '#ec4899',
                            backgroundColor: 'rgba(236, 72, 153, 0.08)',
                            tension: 0.3,
                            borderWidth: 2,
                            fill: true,
                            pointRadius: 2,
                            yAxisID: 'y-disp2'
                        },
                        {
                            label: 'Mưa hiệu dụng ngắn (mm)',
                            data: rainCorr.time_series.effective_rainfall_short_mm,
                            borderColor: 'rgba(34, 197, 94, 0.6)',
                            borderWidth: 1.5,
                            borderDash: [4, 2],
                            pointRadius: 0,
                            fill: false,
                            yAxisID: 'y-idx'
                        },
                        {
                            label: 'Mưa hiệu dụng dài (mm)',
                            data: rainCorr.time_series.effective_rainfall_long_mm,
                            borderColor: 'rgba(99, 102, 241, 0.6)',
                            borderWidth: 1.5,
                            borderDash: [8, 4],
                            pointRadius: 0,
                            fill: false,
                            yAxisID: 'y-idx'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    plugins: {
                        legend: {
                            labels: { color: 'var(--text-primary)', usePointStyle: true, padding: 12, font: { size: 11 } }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0,0,0,0.85)',
                            padding: 12
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(255,255,255,0.05)' },
                            ticks: { color: 'var(--text-secondary)', maxRotation: 45 }
                        },
                        'y-idx': {
                            type: 'linear',
                            position: 'left',
                            title: { display: true, text: 'Slide model Index', color: '#f59e0b' },
                            grid: { color: 'rgba(255,255,255,0.05)' },
                            ticks: { color: '#f59e0b' }
                        },
                        'y-disp2': {
                            type: 'linear',
                            position: 'right',
                            title: { display: true, text: 'Dịch chuyển ngày (mm)', color: '#ec4899' },
                            grid: { drawOnChartArea: false },
                            ticks: { color: '#ec4899' }
                        }
                    }
                }
            });
        }
    }
}

// =========================================================================
// MULTI-WINDOW ANALYSIS SECTION (CALENDAR INTERVALS)
// =========================================================================
function formatDisplacementString(valMm, decimals = 1) {
    const val = Number(valMm);
    if (!Number.isFinite(val)) return '--';
    if (Math.abs(val) >= 10) {
        return `${(val / 10).toFixed(decimals)} cm`;
    }
    return `${val.toFixed(decimals)} mm`;
}

function formatRateWithUnit(valueMm, periodLabel) {
    const absValue = Math.abs(valueMm);
    if (absValue >= 1000) {
        return { value: valueMm / 1000, unit: `m/${periodLabel}`, decimals: 2 };
    }
    if (absValue >= 10) {
        return { value: valueMm / 10, unit: `cm/${periodLabel}`, decimals: 2 };
    }
    return { value: valueMm, unit: `mm/${periodLabel}`, decimals: 2 };
}

function formatLongTermVelocityDisplay(metrics) {
    if (metrics && metrics.velocity_reliable === false) {
        const minDurationDays = parseFloat(metrics.min_reliable_duration_days) || (1 / 24);
        return {
            text: `Chờ đủ ${formatDurationString(minDurationDays)}`,
            ciText: `(${metrics.reliability_message || 'Chưa đủ thời lượng quan sát để kết luận vận tốc trung bình.'})`
        };
    }

    const durationDays = parseFloat(metrics?.duration_days) || 0;
    const mmYear = parseFloat(metrics?.velocity_mm_year) || 0;
    const mmDay = parseFloat(metrics?.velocity_mm_day) || (mmYear / 365);
    const mmSecond = parseFloat(metrics?.velocity_mm_second) || (mmDay / 86400);
    const ciYear = parseFloat(metrics?.velocity_ci_95) || 0;

    let primary;
    let ciValue;

    if (durationDays > 0 && durationDays < (1 / 24)) {
        if (Math.abs(mmSecond) >= 1) {
            primary = formatRateWithUnit(mmSecond, 's');
            ciValue = ciYear / 31536000;
        } else {
            primary = formatRateWithUnit(mmDay / 24, 'giờ');
            ciValue = ciYear / 8760;
        }
    } else if (durationDays > 0 && durationDays < 1) {
        primary = formatRateWithUnit(mmDay / 24, 'giờ');
        ciValue = ciYear / 8760;
    } else if (durationDays > 0 && durationDays < 30) {
        primary = formatRateWithUnit(mmDay, 'ngày');
        ciValue = ciYear / 365;
    } else {
        primary = formatRateWithUnit(mmYear, 'năm');
        ciValue = ciYear;
    }

    return {
        text: `${primary.value.toFixed(primary.decimals)} ${primary.unit}`,
        ciText: `(Độ tin cậy xu hướng OLS: ±${Math.abs(ciValue / (primary.unit.startsWith('m/') ? 1000 : primary.unit.startsWith('cm/') ? 10 : 1)).toFixed(primary.decimals)} ${primary.unit})`
    };
}

function formatDurationString(durationDays) {
    if (!durationDays || durationDays <= 0) return '0 phút';

    if (durationDays < 1 / 24) { // less than 1 hour
        const minutes = Math.round(durationDays * 24 * 60);
        return `${minutes} phút`;
    } else if (durationDays < 1) { // less than 1 day
        const hours = Math.floor(durationDays * 24);
        const minutes = Math.round((durationDays * 24 - hours) * 60);
        return minutes > 0 ? `${hours} giờ ${minutes} phút` : `${hours} giờ`;
    } else { // 1 day or more
        const days = Math.floor(durationDays);
        if (days >= 365) {
            const years = Math.floor(days / 365);
            const remainingDays = days % 365;
            return remainingDays > 0 ? `${years} năm ${remainingDays} ngày` : `${years} năm`;
        } else if (days >= 30) {
            const months = Math.floor(days / 30);
            const remainingDays = days % 30;
            return remainingDays > 0 ? `${months} tháng ${remainingDays} ngày` : `${months} tháng`;
        } else {
            const hours = Math.round((durationDays - days) * 24);
            return hours > 0 && days < 7 ? `${days} ngày ${hours} giờ` : `${days} ngày`;
        }
    }
}

function renderMultiWindowSection(data) {
    const section = document.getElementById('multi-window-section');
    if (!section) return;

    const mw = data.multi_window;
    if (!mw || !mw.available) {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';

    // Acceleration alert
    const alertEl = document.getElementById('multi-window-alert');
    const alertTextEl = document.getElementById('multi-window-alert-text');
    const warningTextEl = document.getElementById('warning-text');
    const warningEl = document.getElementById('longterm-warning');

    if (mw.acceleration_alert) {
        alertEl.style.display = 'block';
        alertEl.className = `alert ${mw.acceleration_alert.type === 'rapid_acceleration' ? 'alert-danger' : 'alert-warning'} mb-3`;
        alertTextEl.textContent = mw.acceleration_alert.message;
    } else {
        alertEl.style.display = 'none';
        alertTextEl.textContent = '';
    }

    // Unify CUSUM and Fukuzono models into overall alert if any
    let unifiedMsg = [];
    if (data.gnss?.analysis?.cusum_change) unifiedMsg.push(data.gnss.analysis.cusum_message);
    if (data.inverse_velocity && data.inverse_velocity.predicted_failure) {
        unifiedMsg.push(`Fukuzono (Ngịch đảo Vận tốc) dự báo sụp lún trong ~${data.inverse_velocity.days_to_failure} ngày.`);
    }
    if (unifiedMsg.length > 0 && warningEl) {
        warningEl.style.display = 'block';
        warningEl.className = 'alert alert-danger mb-3';
        warningTextEl.innerHTML = `<strong>KẾT HỢP PHÂN TÍCH:</strong><br>${unifiedMsg.join('<br>')}`;
    }

    // Window cards
    const cardsContainer = document.getElementById('multi-window-cards');
    if (!cardsContainer) return;

    const typeIcons = { 'day': 'bi-clock-history', 'week': 'bi-calendar-week', 'month': 'bi-calendar-month', 'year': 'bi-calendar3' };
    const trendIcons = { 'accelerating': '↗️', 'stable': '➡️', 'decelerating': '↘️' };
    const trendTexts = { 'accelerating': 'Tăng tốc', 'stable': 'Ổn định', 'decelerating': 'Giảm tốc' };

    cardsContainer.innerHTML = (mw.windows || []).map(w => {
        const icon = typeIcons[w.window_days] || 'bi-calendar';
        const label = w.label || (w.window_days + ' ngày');
        if (w.status === 'preliminary') {
            return `
                <div class="col-md-4 mb-2">
                    <div class="longterm-metric-card h-100 is-preliminary">
                        <div class="text-muted small mb-2"><i class="bi ${icon} me-1"></i>${label}</div>
                        <div class="fs-6 fw-semibold text-secondary">${formatLongTermVelocityDisplay(w).text}</div>
                        <div class="metric-inline-warning"><i class="bi bi-shield-exclamation"></i>Dữ liệu chưa đủ tin cậy</div>
                        <div class="small mt-1">Dịch chuyển đầu-cuối: <strong class="text-info">${formatDisplacementString(w.displacement_mm, 1)}</strong></div>
                        <div class="small text-muted">${formatDurationString(w.duration_days)} quan sát, ${w.data_points} điểm dữ liệu</div>
                        <div class="small text-muted mt-1">${w.reliability_message || 'Chưa đủ thời lượng để kết luận vận tốc.'}</div>
                    </div>
                </div>`;
        }

        if (w.status !== 'success') {
            return `
                <div class="col-md-4 mb-2">
                    <div class="longterm-metric-card text-center opacity-50 h-100">
                        <div class="text-muted small"><i class="bi ${icon} me-1"></i>${label}</div>
                        <div class="fs-6 mt-1">Chưa đủ dữ liệu hoặc chưa qua mốc thời gian</div>
                    </div>
                </div>`;
        }

        return `
            <div class="col-md-4 mb-2">
                <div class="longterm-metric-card h-100">
                    <div class="text-muted small mb-2"><i class="bi ${icon} me-1"></i>${label}</div>
                    <div class="fs-4 fw-bold text-primary">${formatLongTermVelocityDisplay({ velocity_mm_day: w.velocity_mm_day, velocity_mm_year: w.velocity_mm_year, duration_days: w.duration_days }).text}</div>
                    <div class="small mt-1">Dịch chuyển đầu-cuối: <strong class="text-info">${formatDisplacementString(w.displacement_mm, 1)}</strong></div>
                    <div class="small">Xu hướng: ${trendIcons[w.trend] || ''} ${trendTexts[w.trend] || '--'}</div>
                    <div class="small text-muted">${formatDurationString(w.duration_days)} quan sát, ${w.data_points} điểm dữ liệu</div>
                </div>
            </div>`;
    }).join('');
}

// ============================================================================
// CROSS-SENSOR CONSENSUS SECTION
// ============================================================================
function renderCrossConsensusSection(data) {
    const section = document.getElementById('cross-consensus-section');
    if (!section) return;

    const cs = data.cross_sensor_consensus;
    if (!cs || !cs.available) {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';

    const banner = document.getElementById('consensus-banner');
    const badge = document.getElementById('consensus-badge');
    const summaryEl = document.getElementById('consensus-summary');
    const sensorsEl = document.getElementById('consensus-sensors-with-data');
    const trendEl = document.getElementById('consensus-trend-agreement');
    const notesEl = document.getElementById('consensus-notes');

    // Badge + banner colour
    const levelConfig = {
        STRONG: { cls: 'consensus-strong', icon: 'bi-check-circle-fill', label: 'Đồng thuận mạnh' },
        PARTIAL: { cls: 'consensus-partial', icon: 'bi-question-circle-fill', label: 'Đồng thuận một phần' },
        CONFLICT: { cls: 'consensus-conflict', icon: 'bi-exclamation-circle-fill', label: 'Mâu thuẫn cảm biến' },
        NONE: { cls: 'consensus-none', icon: 'bi-dash-circle-fill', label: 'Không có bất thường' },
        UNAVAILABLE: { cls: 'consensus-unknown', icon: 'bi-info-circle-fill', label: 'Chưa đủ dữ liệu' },
    };
    const cfg = levelConfig[cs.consensus_level] || levelConfig.UNAVAILABLE;

    banner.className = `consensus-banner mb-3 ${cfg.cls}`;
    badge.className = `consensus-badge ${cfg.cls}`;
    badge.innerHTML = `<i class="bi ${cfg.icon} me-1"></i>${cfg.label}`;
    summaryEl.textContent = cs.summary || '';

    // Sensor chips
    const sensorLabels = { gnss: 'GNSS', imu: 'IMU', rain: 'Mưa' };
    const alertingSet = new Set(cs.sensors_alerting || []);
    const corrobSet = new Set(cs.sensors_corroborating || []);
    const conflictSet = new Set(cs.sensors_conflicting || []);
    sensorsEl.replaceChildren();
    for (const sensor of cs.sensors_with_data || []) {
        const chip = document.createElement('span');
        chip.className = 'sensor-chip';
        if (conflictSet.has(sensor)) chip.classList.add('sensor-chip-conflict');
        else if (corrobSet.has(sensor)) chip.classList.add('sensor-chip-ok');
        else if (alertingSet.has(sensor)) chip.classList.add('sensor-chip-alert');
        chip.textContent = Object.hasOwn(sensorLabels, sensor) ? sensorLabels[sensor] : String(sensor);
        sensorsEl.append(chip);
    }

    // Trend agreement
    const trendMap = {
        full: { text: 'Cùng xu hướng ✓', cls: 'text-success' },
        partial: { text: 'Một phần cùng hướng', cls: 'text-warning' },
        conflict: { text: 'Ngược hướng ⚠️', cls: 'text-danger' },
    };
    const tm = trendMap[cs.trend_agreement];
    if (tm) {
        trendEl.textContent = tm.text;
        trendEl.className = `fs-5 fw-bold mt-1 ${tm.cls}`;
    } else {
        trendEl.textContent = 'Chưa xác định';
        trendEl.className = 'fs-5 fw-bold mt-1 text-muted';
    }

    // Notes list
    notesEl.replaceChildren();
    for (const note of cs.notes || []) {
        const item = document.createElement('div');
        item.className = 'consensus-note-item';
        const icon = document.createElement('i');
        icon.className = 'bi bi-arrow-right-short me-1';
        item.append(icon, document.createTextNode(String(note)));
        notesEl.append(item);
    }
}

function sanitizeLongTermText(text) {
    return String(text || '')
        .replace(/[📈✅📉🚨]/gu, '')
        .replace(/\s{2,}/g, ' ')
        .trim();
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (!el) return;
    const nextValue = String(val ?? '--');
    if (el.textContent !== nextValue) el.textContent = nextValue;
}

function setHTML(id, html) {
    const el = document.getElementById(id);
    if (el && el.innerHTML !== html) el.innerHTML = html;
}

function getLatestSensorTimestamp(data) {
    const sensors = data?.sensors || {};
    let latestTs = Number(data?.last_update || 0);

    for (const sensor of Object.values(sensors)) {
        const ts = Number(sensor?.latest_timestamp || 0);
        if (ts > latestTs) latestTs = ts;
    }
    return latestTs;
}

function formatAgeFromTimestamp(ts) {
    if (!ts) return '--';
    const now = Math.floor(Date.now() / 1000);
    const diff = Math.max(0, now - Number(ts));

    if (diff < 60) return `${diff} giây trước`;
    if (diff < 3600) return `${Math.floor(diff / 60)} phút trước`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} giờ trước`;
    return `${Math.floor(diff / 86400)} ngày trước`;
}

function renderStaleInfo(data, mqttConnected, latestSensorTs) {
    const staleEl = document.getElementById('st-stale-info');
    if (!staleEl) return;

    if (!latestSensorTs) {
        staleEl.style.display = 'none';
        staleEl.innerHTML = '';
        return;
    }

    const ageText = formatAgeFromTimestamp(latestSensorTs);
    const localTime = new Date(normalizeEpochMs(latestSensorTs)).toLocaleString('vi-VN');

    if (!mqttConnected) {
        staleEl.innerHTML = `<span class="badge-label">MẤT KẾT NỐI</span> Dữ liệu cuối: ${ageText} (${localTime})`;
        staleEl.style.display = 'flex';
        return;
    }

    if (data.status === 'offline') {
        staleEl.innerHTML = `<span class="badge-label">NGOẠI TUYẾN</span> Dữ liệu cuối: ${ageText} (${localTime})`;
        staleEl.style.display = 'flex';
        return;
    }

    staleEl.style.display = 'none';
    staleEl.innerHTML = '';
}
