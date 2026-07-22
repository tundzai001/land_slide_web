function setupEventListeners() {
    console.log('🔧 [MAP] Setting up event listeners...');

    const hamburgerBtn = document.getElementById('navbar-hamburger-btn');
    const sidebarCloseTab = document.getElementById('sidebar-close-tab');
    const stationSidebar = document.getElementById('station-list-sidebar');

    // Hamburger → Toggle sidebar trái
    if (hamburgerBtn && stationSidebar) {
        hamburgerBtn.addEventListener('click', () => {
            if (currentMapMode === 'rescue') return;
            const isHidden = stationSidebar.classList.contains('hidden') || stationSidebar.classList.contains('force-hidden');
            if (isHidden) {
                stationSidebar.classList.remove('hidden');
                stationSidebar.classList.remove('force-hidden');
            } else {
                stationSidebar.classList.add('hidden');
            }
        });
    }

    if (sidebarCloseTab && stationSidebar) {
        sidebarCloseTab.addEventListener('click', () => {
            stationSidebar.classList.add('hidden');
        });
    }

    // === Layer Toggle Switch Logic ===
    const layerModeToggle = document.getElementById('layer-mode-toggle');
    const layerStationCb = document.getElementById('layer-station');
    const layerRescueCb = document.getElementById('layer-rescue');
    if (layerModeToggle && layerStationCb && layerRescueCb) {
        layerModeToggle.addEventListener('change', () => {
            if (layerModeToggle.checked) {
                // Rescue-only mode
                layerStationCb.checked = false;
                layerRescueCb.checked = true;
            } else {
                // Station mode (default: both on)
                layerStationCb.checked = true;
                layerRescueCb.checked = true;
            }
            layerStationCb.dispatchEvent(new Event('change'));
            layerRescueCb.dispatchEvent(new Event('change'));
        });
    }

    // === Custom Glass Zoom Controls ===
    const zoomInBtn = document.getElementById('map-zoom-in');
    const zoomOutBtn = document.getElementById('map-zoom-out');
    if (zoomInBtn && map) {
        zoomInBtn.addEventListener('click', () => map.zoomIn());
    }
    if (zoomOutBtn && map) {
        zoomOutBtn.addEventListener('click', () => map.zoomOut());
    }

    // Đóng detailed sidebar
    const closeDetailBtn = document.getElementById('close-btn');
    const detailSidebar = document.getElementById('detail-sidebar');

    if (closeDetailBtn && detailSidebar) {
        closeDetailBtn.addEventListener('click', () => {
            stationSelectionSequence += 1;
            stationSelectionController?.abort();
            stationHistoryController?.abort();
            detailSidebar.classList.remove('active');
            detailSidebar.classList.remove('station-selecting');
            detailSidebar.setAttribute('aria-busy', 'false');

            // Đóng tất cả panels
            const chartsPanel = document.getElementById('charts-panel');
            const longtermOverlay = document.getElementById('longterm-overlay');
            const advSidepanel = document.getElementById('gnss-advanced-sidepanel');
            if (chartsPanel) {
                chartsPanel.classList.remove('active');
                destroyStationCharts();
            }
            if (longtermOverlay) longtermOverlay.classList.remove('active');
            stopLongTerm3DAnimations();
            if (advSidepanel) advSidepanel.classList.remove('active');

            // Mở lại sidebar trái
            if (stationSidebar && currentMapMode !== 'rescue') {
                stationSidebar.classList.remove('hidden');
                stationSidebar.classList.remove('force-hidden');
            }
        });
    }

    // Theme toggle - handled by theme-manager.js (do NOT add duplicate listener)

    // Search
    const searchInput = document.getElementById('search-station');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            filterStations(e.target.value);
        });
    }

    // ✅ NEW: Xem biểu đồ - Mở panel giữa màn hình
    const btnShowCharts = document.getElementById('btn-show-charts');
    const chartsPanel = document.getElementById('charts-panel');
    const closeChartsBtn = document.getElementById('close-charts-btn');

    if (btnShowCharts && chartsPanel) {
        btnShowCharts.addEventListener('click', async () => {
            chartsPanel.classList.add('active');

            // Close advanced gnss panel if open
            const advSidepanel = document.getElementById('gnss-advanced-sidepanel');
            if (advSidepanel) advSidepanel.classList.remove('active');

            // Đóng sidebar trái khi mở biểu đồ
            if (stationSidebar) {
                stationSidebar.classList.add('hidden');
                stationSidebar.classList.add('force-hidden');
            }

            console.log('📊 [CHARTS] Charts panel opened');

            if (currentStationData) await loadStationHistoryAndRenderCharts();
        });
    }



    // ✅ NEW: Mở Digital Twin 3D
    const btnDigitalTwin = document.getElementById('btn-digital-twin');
    if (btnDigitalTwin) {
        btnDigitalTwin.addEventListener('click', () => {
            if (currentStationData) {
                console.log('🌋 [DIGITAL TWIN] Opening for station:', currentStationData.id);
                const rainData = currentStationData.sensors && currentStationData.sensors.rain && currentStationData.sensors.rain.latest ? currentStationData.sensors.rain.latest.data : null;
                const h24 = rainData ? (rainData.rain_24h || rainData.rain_last_24h || rainData.value || 0) : 0;
                window.openDigitalTwin({
                    id: currentStationData.id,
                    rain: { h24: parseFloat(h24) }
                });
            } else {
                window.openDigitalTwin(null);
            }
        });
    }

    // Advanced GNSS Sidepanel
    const gnssCard = document.getElementById('sensor-card-gnss');
    const advSidepanel = document.getElementById('gnss-advanced-sidepanel');
    const advCloseBtn = document.getElementById('gnss-sidepanel-close');

    if (gnssCard && advSidepanel) {
        console.log('✅ [GNSS] Advanced sidepanel listener attached');
        gnssCard.addEventListener('click', (e) => {
            e.stopPropagation();
            console.log('👆 [GNSS] GNSS Velocity card clicked');
            // Remove expanded mode when just opening from card
            advSidepanel.classList.remove('expanded');
            advSidepanel.classList.toggle('active');
            const isActive = advSidepanel.classList.contains('active');

            // ✅ ĐỒNG BỘ: Đóng Station Sidebar khi mở Advanced GNSS
            if (isActive && stationSidebar) {
                stationSidebar.classList.add('hidden');
                loadLongTermAnalysis(); // Tải Theil-Sen vào cột trái
            }

            console.log('✨ [GNSS] Sidepanel active:', isActive);
        });
    } else {
        console.warn('⚠️ [GNSS] Could not find gnssCard or advSidepanel', { gnssCard: !!gnssCard, advSidepanel: !!advSidepanel });
    }

    if (advCloseBtn && advSidepanel) {
        advCloseBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            advSidepanel.classList.remove('active');
            advSidepanel.classList.remove('expanded');
            const advColRight = advSidepanel.querySelector('.adv-column-right');
            if (advColRight) advColRight.style.display = 'none';
        });
    }

    if (closeChartsBtn && chartsPanel) {
        closeChartsBtn.addEventListener('click', () => {
            chartsPanel.classList.remove('active');
            destroyStationCharts();

            // Chỉ bỏ force-hidden, giữ hidden (sidebar vẫn đóng)
            if (stationSidebar && currentMapMode !== 'rescue') {
                stationSidebar.classList.remove('force-hidden');
            }

            console.log('📊 [CHARTS] Charts panel closed');
        });
    }

    const btnToggleImu3d = document.getElementById('btn-toggle-imu-3d');
    const chartImuWrapper = document.getElementById('chart-imu-wrapper');
    const realtimeImu3dWrapper = document.getElementById('realtime-imu-3d-wrapper');

    if (btnToggleImu3d && chartImuWrapper && realtimeImu3dWrapper) {
        btnToggleImu3d.addEventListener('click', () => {
            realtimeImuActive = !realtimeImuActive;
            if (realtimeImuActive) {
                chartImuWrapper.style.display = 'none';
                realtimeImu3dWrapper.style.display = 'block';
                btnToggleImu3d.innerHTML = '<i class="bi bi-graph-up me-1"></i>2D Chart';
                // Always re-init 3D scene when toggling on to ensure proper sizing
                if (currentStationData && currentStationData.sensors && currentStationData.sensors.imu) {
                    const latest = currentStationData.sensors.imu.latest;
                    if (latest) {
                        // Small delay to let display:block take effect
                        setTimeout(() => {
                            initRealtimeIMU3D(latest.roll || 0, latest.pitch || 0);
                        }, 50);
                    }
                }
            } else {
                realtimeImu3dWrapper.style.display = 'none';
                chartImuWrapper.style.display = 'block';
                btnToggleImu3d.innerHTML = '<i class="bi bi-box me-1"></i>3D View';
                // Cleanup realtime scene on hide
                if (realtimeImuAnimationId) cancelAnimationFrame(realtimeImuAnimationId);
                realtimeImuScene = null;
                realtimeImuRenderer = null;
            }
        });
    }

    // Analysis / Theil-Sen button -> Mở Advanced tab (Chỉ hiển thị Theil-sen, ẩn Bình sai)
    const btnLongTerm = document.getElementById('btn-long-term');
    const longtermOverlay = document.getElementById('longterm-overlay');
    const closeLongtermBtn = document.getElementById('close-longterm-btn');

    if (btnLongTerm && advSidepanel) {
        btnLongTerm.addEventListener('click', () => {
            advSidepanel.classList.remove('expanded');
            advSidepanel.classList.add('active');

            // Đóng sidebar trái
            if (stationSidebar) {
                stationSidebar.classList.add('hidden');
                stationSidebar.classList.add('force-hidden');
            }

            // Cập nhật tên trạm
            const longtermStationName = document.getElementById('longterm-station-name');
            if (longtermStationName && currentStationData) {
                longtermStationName.textContent = `${currentStationData.name} (${currentStationData.station_code})`;
            }

            console.log('📊 [LONGTERM] Analysis overlay opened');

            loadLongTermAnalysis();
        });
    }

    const btnNetworkAdj = document.getElementById('btn-network-adj');
    if (btnNetworkAdj && advSidepanel) {
        btnNetworkAdj.addEventListener('click', () => {
            // Check for offline rovers
            let hasOffline = false;
            if (typeof stationsData !== 'undefined' && Array.isArray(stationsData)) {
                hasOffline = stationsData.some(st => st.status === 'offline' || st.is_offline);
            }
            
            if (hasOffline) {
                const proceed = confirm("Có trạm rover offline, bạn có muốn tiếp tục bình sai không? (Có/Không)");
                if (!proceed) return;
            }

            // Open and Expand Advanced Sidepanel
            advSidepanel.classList.add('active');
            
            // Expand to show right column
            const advColRight = advSidepanel.querySelector('.adv-column-right');
            if (advColRight) {
                advColRight.style.display = 'flex';
                advSidepanel.classList.add('expanded');
            }

            
            // Close left sidebar
            if (stationSidebar) {
                stationSidebar.classList.add('hidden');
                stationSidebar.classList.add('force-hidden');
            }
            
            // Trigger adjustment request
            if (typeof requestGnssAdjustment === 'function') {
                requestGnssAdjustment(currentStationData?.project_id);
            }
        });
    }

    // Quản lý trạng thái vẽ Canvas
    window.gnssBoardState = {
        canvas: null,
        ctx: null,
        points: {},
        baselines: [],
        basePoint: null,
        animationId: null,
        lastAnimationDrawAt: 0,
        viewWidth: 0,
        viewHeight: 0,
        resizeObserver: null,
        observedContainer: null,
        resizePending: true,
        pendingViewWidth: 0,
        pendingViewHeight: 0,
        interactionActive: false,
        backgroundGradient: null,
        roverCount: 0,
        init({ preserve = false } = {}) {
            this.canvas = document.getElementById('gnss-board-canvas');
            if (!this.canvas) return;
            this.ctx = this.canvas.getContext('2d');
            if (!preserve) {
                this.points = {};
                this.baselines = [];
                this.basePoint = null;
                this.roverCount = 0;
                const tableBody = document.getElementById('gnss-baseline-table-body');
                const tooltips = document.getElementById('gnss-board-tooltips');
                if (tableBody) tableBody.innerHTML = '';
                if (tooltips) tooltips.innerHTML = '';
            }
            if (!gnssAdjustmentDebugState.active) {
                gnssAdjustmentDebugState.phase = 'WAITING';
            }
            this.observeContainerResize();
            this.resize(true);
            this.startAnimation();
            refreshGnssAdjustmentDebugUi();
            if (!preserve) {
                const results = document.getElementById('adj-results-section');
                if (results) results.style.display = 'none';
            }
        },
        observeContainerResize() {
            const container = document.getElementById('gnss-board-container');
            if (!container || this.observedContainer === container) return;
            this.resizeObserver?.disconnect?.();
            this.observedContainer = container;
            this.resizePending = true;
            if (typeof ResizeObserver !== 'function') return;
            this.resizeObserver = new ResizeObserver(entries => {
                const entry = entries[entries.length - 1];
                const rect = entry?.contentRect;
                if (rect) {
                    this.pendingViewWidth = Math.floor(rect.width);
                    this.pendingViewHeight = Math.floor(rect.height);
                }
                this.resizePending = true;
            });
            this.resizeObserver.observe(container);
        },
        requestResize() {
            this.resizePending = true;
        },
        resize(force = false) {
            if (!this.canvas) return;
            if (!force && !this.resizePending) return false;
            const container = document.getElementById('gnss-board-container');
            const observedWidth = force ? 0 : this.pendingViewWidth;
            const observedHeight = force ? 0 : this.pendingViewHeight;
            const width = Math.max(320, Math.floor(
                observedWidth || container?.clientWidth || 720
            ));
            const height = Math.max(300, Math.floor(
                observedHeight || container?.clientHeight || 520
            ));
            this.pendingViewWidth = 0;
            this.pendingViewHeight = 0;
            this.resizePending = false;
            const changed = this.canvas.width !== width || this.canvas.height !== height;
            if (changed) {
                this.canvas.width = width;
                this.canvas.height = height;
                this.backgroundGradient = null;
            }
            this.viewWidth = width;
            this.viewHeight = height;
            return changed;
        },
        startAnimation() {
            this.stopAnimation();
            const animate = timestamp => {
                // The board is ambient status UI; 30 FPS keeps the pulse smooth
                // while leaving the main thread available for realtime messages.
                if (timestamp - this.lastAnimationDrawAt >= 32) {
                    this.resize();
                    this.draw(timestamp);
                    this.lastAnimationDrawAt = timestamp;
                }
                this.animationId = requestAnimationFrame(animate);
            };
            this.animationId = requestAnimationFrame(animate);
        },
        stopAnimation() {
            if (this.animationId) cancelAnimationFrame(this.animationId);
            this.animationId = null;
            this.lastAnimationDrawAt = 0;
        },
        getRoverCount() {
            if (Number.isFinite(this.roverCount) && this.roverCount >= 0) {
                return Math.trunc(this.roverCount);
            }
            return Math.max(0, Object.keys(this.points || {}).filter(name => name !== 'BASE').length);
        },
        addPoint(name, relX, relY, isBase = false) {
            if (!this.points[name]) {
                this.points[name] = { name, x: Number(relX) || 0, y: Number(relY) || 0, isBase, samples: 1 };
                if (isBase) this.basePoint = this.points[name];
            } else if (!isBase) {
                const point = this.points[name];
                point.samples = Number(point.samples || 1) + 1;
                point.x += ((Number(relX) || 0) - point.x) / point.samples;
                point.y += ((Number(relY) || 0) - point.y) / point.samples;
            }
        },
        addBaseline(from, to, data) {
            const orderedPair = from === 'BASE'
                ? ['BASE', to]
                : to === 'BASE'
                    ? ['BASE', from]
                    : [from, to].sort();
            const direction = from === orderedPair[0] && to === orderedPair[1] ? 1 : -1;
            from = orderedPair[0];
            to = orderedPair[1];
            data = {
                ...data,
                dn: direction * Number(data.dn || 0),
                de: direction * Number(data.de || 0),
                dh: direction * Number(data.dh || 0),
            };
            const key = `${from}\u0000${to}`;
            let edge = this.baselines.find(item => item.key === key);
            if (edge) {
                edge.samples += 1;
                edge.data.dn += (Number(data.dn) - edge.data.dn) / edge.samples;
                edge.data.de += (Number(data.de) - edge.data.de) / edge.samples;
                edge.data.dh += (Number(data.dh) - edge.data.dh) / edge.samples;
                edge.data.full_data = data.full_data;
            } else {
                edge = {
                    key,
                    from,
                    to,
                    samples: 1,
                    data: {
                        ...data,
                        dn: Number(data.dn) || 0,
                        de: Number(data.de) || 0,
                        dh: Number(data.dh) || 0,
                    },
                };
                this.baselines.push(edge);
            }

            const tbody = document.getElementById('gnss-baseline-table-body');
            if (!tbody) return;
            let row = Array.from(tbody.rows).find(item => item.dataset.edgeKey === key);
            if (!row) {
                row = document.createElement('tr');
                row.dataset.edgeKey = key;
                tbody.appendChild(row);
            }
            row.innerHTML = `
                <td class="ps-3 text-muted">${this.baselines.indexOf(edge) + 1} <span class="badge bg-secondary ms-1" style="font-size: 0.6rem;">n=${edge.samples}</span></td>
                <td class="text-info fw-bold">${from}</td>
                <td class="text-warning fw-bold">${to}</td>
                <td class="text-end font-monospace" style="color: #a7f3d0;">${edge.data.dn.toFixed(4)}</td>
                <td class="text-end font-monospace" style="color: #a7f3d0;">${edge.data.de.toFixed(4)}</td>
                <td class="text-end font-monospace" style="color: #a7f3d0;">${edge.data.dh.toFixed(4)}</td>
                <td class="pe-3 text-end"><button class="btn btn-sm btn-outline-info py-0 px-2 view-adv-btn" style="font-size: 0.7rem; border-radius: 4px;">Chi tiết</button></td>
            `;
            row.querySelector('.view-adv-btn').onclick = () => {
                const output = document.getElementById('gnss-advanced-data-json');
                if (output) output.textContent = JSON.stringify(edge.data.full_data || {}, null, 2);
                bootstrap.Modal.getOrCreateInstance(document.getElementById('gnssAdvancedDataModal')).show();
            };
        },
        getProjection() {
            const values = Object.values(this.points);
            const minX = Math.min(...values.map(item => item.x), 0);
            const maxX = Math.max(...values.map(item => item.x), 0);
            const minY = Math.min(...values.map(item => item.y), 0);
            const maxY = Math.max(...values.map(item => item.y), 0);
            const padding = 90;
            const rangeX = Math.max(maxX - minX, 1);
            const rangeY = Math.max(maxY - minY, 1);
            const scale = Math.max(0.01, Math.min(
                (this.viewWidth - padding * 2) / rangeX,
                (this.viewHeight - padding * 2) / rangeY,
            ));
            const centerX = this.viewWidth / 2 - ((minX + maxX) / 2) * scale;
            const centerY = this.viewHeight / 2 + ((minY + maxY) / 2) * scale;
            return { scale, centerX, centerY };
        },
        getScreenCoords(pt, projection = this.getProjection()) {
            return {
                x: projection.centerX + (pt.x * projection.scale),
                y: projection.centerY - (pt.y * projection.scale),
            };
        },
        fitToResult() {
            const fit = () => {
                this.requestResize();
                this.resize(true);
                this.draw();
            };
            requestAnimationFrame(() => {
                fit();
                requestAnimationFrame(fit);
            });
        },
        loadAdjustmentResult(result) {
            if (!result?.points) return;
            const downloadBtn = document.getElementById('gnss-download-results-btn');
            const auditJsonBtn = document.getElementById('gnss-download-audit-json-btn');
            const reportUrl = String(result.report_file_url || '');
            const excelUrl = result.excel_report_url
                || (reportUrl.toLowerCase().split('?', 1)[0].endsWith('.xlsx') ? reportUrl : '');
            const auditJsonUrl = String(result.audit_json_url || '');
            if (downloadBtn) {
                downloadBtn.disabled = !excelUrl;
                downloadBtn.classList.toggle('disabled', !excelUrl);
                downloadBtn.innerHTML = excelUrl
                    ? '<i class="bi bi-file-earmark-spreadsheet-fill me-2"></i>Tải kết quả Excel (.xlsx)'
                    : '<i class="bi bi-hourglass-split me-2"></i>Đang tạo file Excel...';
                downloadBtn.onclick = excelUrl ? () => {
                    const excelAnchor = document.createElement('a');
                    excelAnchor.href = excelUrl;
                    excelAnchor.download = excelUrl.split('/').pop() || 'gnss_binh_sai.xlsx';
                    document.body.appendChild(excelAnchor);
                    excelAnchor.click();
                    excelAnchor.remove();
                } : null;
            }
            if (auditJsonBtn) {
                auditJsonBtn.disabled = !auditJsonUrl;
                auditJsonBtn.classList.toggle('disabled', !auditJsonUrl);
                auditJsonBtn.onclick = auditJsonUrl ? () => {
                    const auditAnchor = document.createElement('a');
                    auditAnchor.href = auditJsonUrl;
                    auditAnchor.download = auditJsonUrl.split('/').pop() || 'gnss_adjustment_audit.json';
                    document.body.appendChild(auditAnchor);
                    auditAnchor.click();
                    auditAnchor.remove();
                } : null;
            }
            if (!this.ctx) return;
            this.points = {};
            this.baselines = [];
            this.basePoint = null;
            const tbody = document.getElementById('gnss-baseline-table-body');
            const tooltips = document.getElementById('gnss-board-tooltips');
            if (tbody) tbody.innerHTML = '';
            if (tooltips) tooltips.innerHTML = '';

            const resultBaselines = Array.isArray(result.baselines) ? result.baselines : [];
            let baseXYZ = result.base?.ecef_xyz;
            if (!Array.isArray(baseXYZ)) {
                const seed = resultBaselines.find(item => item.from === 'BASE' && result.points[item.to]);
                const target = seed ? getAdjustedPointCoordinates(result.points[seed.to]) : null;
                const vector = seed?.adjusted_xyz || seed?.adjusted_neu || seed?.observed_xyz || seed?.observed_neu;
                if (target?.length >= 3 && Array.isArray(vector)) {
                    baseXYZ = target.map((value, index) => Number(value) - Number(vector[index] || 0));
                }
            }
            if (!Array.isArray(baseXYZ)) {
                baseXYZ = getAdjustedPointCoordinates(Object.values(result.points)[0]);
            }
            baseXYZ = Array.isArray(baseXYZ) ? baseXYZ.map(Number) : [0, 0, 0];
            this.addPoint('BASE', 0, 0, true);
            this.roverCount = Array.isArray(result.points)
                ? result.points.length
                : Object.keys(result.points || {}).length;
            Object.entries(result.points).forEach(([name, point]) => {
                const coordinate = getAdjustedPointCoordinates(point).map(Number);
                if (coordinate.length >= 2 && coordinate.every(Number.isFinite)) {
                    this.addPoint(name, coordinate[1] - baseXYZ[1], coordinate[0] - baseXYZ[0], false);
                }
            });
            resultBaselines.forEach(item => {
                const vector = item.adjusted_xyz || item.adjusted_neu || item.observed_xyz || item.observed_neu;
                if (!Array.isArray(vector) || vector.length < 3) return;
                this.addBaseline(item.from, item.to, {
                    dn: Number(vector[0]) || 0,
                    de: Number(vector[1]) || 0,
                    dh: Number(vector[2]) || 0,
                    full_data: item,
                });
            });
            this.fitToResult();
        },
        draw(timestamp = performance.now()) {
            if (!this.ctx) return;
            const ctx = this.ctx;
            const width = this.viewWidth || this.canvas.width;
            const height = this.viewHeight || this.canvas.height;
            const time = Number(timestamp || 0) / 1000;
            ctx.clearRect(0, 0, width, height);
            if (!this.backgroundGradient) {
                this.backgroundGradient = ctx.createLinearGradient(0, 0, width, height);
                this.backgroundGradient.addColorStop(0, '#06141b');
                this.backgroundGradient.addColorStop(0.55, '#0a2229');
                this.backgroundGradient.addColorStop(1, '#071117');
            }
            ctx.fillStyle = this.backgroundGradient;
            ctx.fillRect(0, 0, width, height);

            ctx.strokeStyle = 'rgba(91,192,190,.12)';
            this.ctx.lineWidth = 1;
            const gridOffset = (time * 8) % 48;
            ctx.beginPath();
            for (let x = gridOffset; x < width; x += 48) {
                ctx.moveTo(x, 0); ctx.lineTo(x, height);
            }
            for (let y = gridOffset; y < height; y += 48) {
                ctx.moveTo(0, y); ctx.lineTo(width, y);
            }
            ctx.stroke();

            ctx.fillStyle = '#7dd3c7';
            ctx.font = "600 13px 'IBM Plex Mono', monospace";
            ctx.fillText('GNSS NETWORK SOLVER', 24, 30);
            ctx.fillStyle = 'rgba(203,255,248,.55)';
            ctx.font = "11px 'IBM Plex Mono', monospace";
            ctx.fillText(`${gnssAdjustmentDebugState.phase}  ·  ${this.baselines.length} cạnh  ·  ${gnssAdjustmentDebugState.baselineCount} trị đo`, 24, 49);
            ctx.fillText(`${this.getRoverCount()} rover + 1 BASE`, 24, 66);

            if (Object.keys(this.points).length === 0) {
                const centerX = width / 2;
                const centerY = height / 2 - 10;
                const maxRadius = Math.min(width, height) * 0.27;
                for (let ring = 1; ring <= 4; ring += 1) {
                    ctx.beginPath();
                    ctx.arc(centerX, centerY, maxRadius * ring / 4, 0, Math.PI * 2);
                    ctx.strokeStyle = `rgba(45,212,191,${0.08 + ring * 0.025})`;
                    ctx.stroke();
                }
                const angle = time * 1.15;
                const sweep = ctx.createLinearGradient(
                    centerX, centerY,
                    centerX + Math.cos(angle) * maxRadius,
                    centerY + Math.sin(angle) * maxRadius,
                );
                sweep.addColorStop(0, 'rgba(45,212,191,0)');
                sweep.addColorStop(1, 'rgba(45,212,191,.85)');
                ctx.strokeStyle = sweep;
                ctx.lineWidth = 3;
                ctx.beginPath();
                ctx.moveTo(centerX, centerY);
                ctx.lineTo(centerX + Math.cos(angle) * maxRadius, centerY + Math.sin(angle) * maxRadius);
                ctx.stroke();
                const expectedCount = Math.max(gnssAdjustmentDebugState.expectedStationIds.length, 5);
                for (let index = 0; index < expectedCount; index += 1) {
                    const dotAngle = (Math.PI * 2 * index / expectedCount) + 0.35;
                    const radius = maxRadius * (0.48 + (index % 3) * 0.17);
                    const pulse = 2.5 + 1.8 * (1 + Math.sin(time * 3 + index)) / 2;
                    ctx.beginPath();
                    ctx.arc(centerX + Math.cos(dotAngle) * radius, centerY + Math.sin(dotAngle) * radius, pulse, 0, Math.PI * 2);
                    ctx.fillStyle = index < gnssAdjustmentDebugState.baselineCount ? '#2dd4bf' : 'rgba(148,163,184,.55)';
                    ctx.fill();
                }
                ctx.textAlign = 'center';
                ctx.fillStyle = '#d5fffb';
                ctx.font = "600 16px 'IBM Plex Mono', monospace";
                ctx.fillText('ĐANG QUÉT BASELINE', centerX, centerY + maxRadius + 42);
                ctx.fillStyle = 'rgba(203,255,248,.55)';
                ctx.font = "12px 'IBM Plex Mono', monospace";
                ctx.fillText('Chờ các rover gửi nghiệm RTK Fixed', centerX, centerY + maxRadius + 64);
                ctx.textAlign = 'start';
                return;
            }

            const projection = this.getProjection();
            const screenCoords = {};
            Object.values(this.points).forEach(point => {
                screenCoords[point.name] = this.getScreenCoords(point, projection);
            });
            ctx.save();
            ctx.setLineDash([12, 8]);
            ctx.strokeStyle = 'rgba(45,212,191,.9)';
            ctx.lineWidth = 2.5;
            ctx.shadowColor = '#2dd4bf';
            ctx.shadowBlur = this.interactionActive ? 0 : 10;
            this.baselines.forEach((baseline, index) => {
                const p1 = this.points[baseline.from];
                const p2 = this.points[baseline.to];
                if (p1 && p2) {
                    const sp1 = screenCoords[p1.name];
                    const sp2 = screenCoords[p2.name];
                    ctx.lineDashOffset = -time * 28 - index * 5;
                    ctx.beginPath();
                    ctx.moveTo(sp1.x, sp1.y);
                    ctx.lineTo(sp2.x, sp2.y);
                    ctx.stroke();
                    const progress = (time * 0.35 + index * 0.15) % 1;
                    ctx.beginPath();
                    ctx.arc(sp1.x + (sp2.x - sp1.x) * progress, sp1.y + (sp2.y - sp1.y) * progress, 4, 0, Math.PI * 2);
                    ctx.fillStyle = '#fbbf24';
                    ctx.shadowColor = '#f59e0b';
                    ctx.shadowBlur = this.interactionActive ? 0 : 8;
                    ctx.fill();
                    ctx.shadowBlur = 0;
                    const midX = (sp1.x + sp2.x) / 2;
                    const midY = (sp1.y + sp2.y) / 2;
                    ctx.fillStyle = 'rgba(213,255,251,.82)';
                    ctx.font = "10px 'IBM Plex Mono', monospace";
                    ctx.fillText(`n=${baseline.samples}`, midX + 7, midY - 7);
                }
            });
            ctx.restore();

            Object.values(this.points).forEach((pt, index) => {
                const sp = screenCoords[pt.name];
                const pulse = 12 + 3 * Math.sin(time * 2.7 + index);
                ctx.beginPath();
                ctx.arc(sp.x, sp.y, pulse, 0, Math.PI * 2);
                ctx.fillStyle = pt.isBase ? 'rgba(251,113,133,.13)' : 'rgba(45,212,191,.12)';
                ctx.fill();
                ctx.beginPath();
                ctx.arc(sp.x, sp.y, pt.isBase ? 8 : 6, 0, Math.PI * 2);
                ctx.fillStyle = pt.isBase ? '#fb7185' : '#2dd4bf';
                ctx.shadowColor = ctx.fillStyle;
                ctx.shadowBlur = this.interactionActive ? 0 : 12;
                ctx.fill();
                ctx.shadowBlur = 0;
                ctx.strokeStyle = '#d5fffb';
                ctx.lineWidth = 1.5;
                ctx.stroke();
                ctx.fillStyle = '#e6fffb';
                ctx.font = "600 12px 'IBM Plex Mono', monospace";
                ctx.fillText(pt.name, sp.x + 12, sp.y - 11);
            });
        }
    };

    // Lệnh Bình sai - Trigger API start gnss adjustment
    function ensureGnssTerminalModal() {
        let modal = document.getElementById('gnssTerminalModal');
        if (modal && !modal.querySelector('#gnss-workflow-map')) {
            // The route template may have inserted the former Baseline Vectors
            // modal before this script loads. Replace it once so every entry
            // point gets the same live workflow UI.
            window.bootstrap?.Modal?.getInstance(modal)?.dispose();
            modal.remove();
            modal = null;
        }
        if (modal) return modal;

        const wrapper = document.createElement('div');
        wrapper.innerHTML = `
            <div class="modal fade" id="gnssTerminalModal" tabindex="-1">
                <div class="modal-dialog modal-xl modal-dialog-centered gnss-terminal-dialog">
                    <div class="modal-content bg-dark text-light border-primary gnss-terminal-content">
                        <div class="modal-header border-bottom border-secondary py-2">
                            <h5 class="modal-title text-primary font-monospace" style="font-size: 1.1rem;">
                                <i class="bi bi-cpu me-2"></i>GNSS Agent Calculation Board (Real-time)
                            </h5>
                            <div id="gnss-phase-indicator" class="ms-4 text-warning fw-bold font-monospace">Phase: WAITING</div>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" title="Thu nhỏ cửa sổ; tiến trình bình sai vẫn tiếp tục"></button>
                        </div>
                        <div class="modal-body p-0 d-flex flex-row gnss-terminal-body">
                            <div class="position-relative" id="gnss-board-container">
                                <canvas id="gnss-board-canvas" style="width: 100%; height: 100%; display: block; background: #06141b;"></canvas>
                                <div id="gnss-board-tooltips" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;"></div>
                            </div>
                            <div id="gnss-column-resizer" title="Kéo để đổi chiều rộng bảng dữ liệu" style="flex: 0 0 7px; cursor: col-resize; background: #374151; border-left: 1px solid #111827; border-right: 1px solid #64748b; touch-action: none;"></div>
                            <div id="gnss-data-column" class="d-flex flex-column">
                                <section class="gnss-workflow-panel flex-grow-1" id="gnss-data-panel" aria-label="Sơ đồ tiến trình bình sai">
                                    <header class="gnss-workflow-header">
                                        <div>
                                            <span class="gnss-workflow-kicker"><i class="bi bi-stars me-1"></i> LIVE WORKFLOW</span>
                                            <h6><i class="bi bi-diagram-3-fill"></i> Sơ đồ quy trình bình sai</h6>
                                            <p id="gnss-workflow-current">Chưa bắt đầu</p>
                                        </div>
                                        <span class="gnss-workflow-live"><i></i> REAL-TIME</span>
                                    </header>
                                    <div class="gnss-workflow-progress" aria-hidden="true">
                                        <span id="gnss-workflow-progress-bar"></span>
                                    </div>
                                    <div class="gnss-workflow-progress-meta">
                                        <span>Tiến trình đã vẽ</span>
                                        <strong id="gnss-workflow-progress-value">0/0 mốc</strong>
                                    </div>
                                    <div id="gnss-workflow-scroll" class="gnss-workflow-scroll">
                                        <div id="gnss-workflow-map" class="gnss-workflow-map"></div>
                                    </div>
                                </section>
                                <div id="gnss-debug-resizer" title="Kéo để đổi chiều cao Live Debug" style="height: 7px; flex: 0 0 7px; cursor: row-resize; background: #2c3440; border-top: 1px solid #4a5568; border-bottom: 1px solid #1a202c; touch-action: none; transition: background 0.2s;"></div>
                                <div id="gnss-debug-section" class="bg-darker d-flex flex-column live-debug-panel">
                                    <div class="d-flex justify-content-between align-items-center px-3 py-2 bg-gradient-debug border-bottom border-secondary gnss-debug-header">
                                        <h6 class="mb-0 text-warning font-monospace fw-bold" style="font-size: 0.8rem; letter-spacing: 0.5px;"><i class="bi bi-terminal-fill me-2"></i>Live Debug</h6>
                                        <div class="d-flex gap-1 gnss-debug-actions">
                                            <button id="gnss-debug-copy" type="button" class="btn btn-sm btn-outline-info py-0 px-1" style="font-size: 0.65rem;" title="Sao chép toàn bộ log">Sao chép</button>
                                            <button id="gnss-debug-follow" type="button" class="btn btn-sm btn-outline-secondary py-0 px-1" style="font-size: 0.65rem;" title="Xuống cuối và tiếp tục tự cuộn">↓ Cuối</button>
                                            <button id="gnss-debug-toggle" type="button" class="btn btn-sm btn-outline-secondary py-0 px-1" style="font-size: 0.65rem;" title="Thu gọn hoặc mở Live Debug"><i class="bi bi-chevron-down"></i></button>
                                            <button id="gnss-debug-clear" type="button" class="btn btn-sm btn-outline-secondary py-0 px-1" style="font-size: 0.65rem;">Xóa log</button>
                                        </div>
                                    </div>
                                    <div id="gnss-debug-summary" class="px-3 py-1 text-muted font-monospace border-bottom border-secondary" style="font-size: 0.72rem; white-space: nowrap; overflow-x: auto; overflow-y: hidden; flex: 0 0 auto; background: rgba(0,0,0,0.3);">WS: CONNECTING</div>
                                    <div id="gnss-debug-log" class="p-3 font-monospace flex-grow-1 text-light" tabindex="0" style="min-height: 0; overflow: auto; scrollbar-gutter: stable; user-select: text; cursor: text; white-space: pre-wrap; overflow-wrap: break-word; word-break: normal; font-size: 0.8rem; line-height: 1.6;"></div>
                                </div>
                                <div id="adj-results-section" class="p-3 border-top border-secondary bg-gradient-premium" style="display: none; position: relative; flex: 0 0 auto; max-height: min(34vh, 300px); overflow-y: auto;">
                                    <h6 id="adj-process-status" class="mb-2"></h6>
                                    <div class="text-light opacity-75 font-monospace mb-2" style="font-size: 0.75rem;"><i class="bi bi-clock me-1"></i>Time: <span id="adj-val-time"></span></div>
                                    <div class="d-flex gap-2 mb-2">
                                        <button id="gnss-download-results-btn" class="btn btn-sm btn-success w-100 px-3 py-2 shadow-sm fw-bold" style="border-radius: 7px; letter-spacing: 0.4px;">
                                            <i class="bi bi-hourglass-split me-2"></i>Đang tạo file Excel...
                                        </button>
                                        <button id="gnss-download-audit-json-btn" class="btn btn-sm btn-outline-info px-3 py-2 shadow-sm fw-bold" style="border-radius: 7px; white-space: nowrap;" disabled>
                                            <i class="bi bi-filetype-json me-1"></i>Audit JSON
                                        </button>
                                    </div>
                                    <div id="adj-points-list" class="mt-2" style="max-height: 120px; overflow-y: auto;"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `.trim();
        modal = wrapper.firstElementChild;
        document.body.appendChild(modal);
        modal.addEventListener('shown.bs.modal', () => {
            window.gnssBoardState?.init?.({ preserve: gnssAdjustmentDebugState.active });
            if (pendingGnssAdjustmentResult) {
                window.gnssBoardState?.loadAdjustmentResult?.(pendingGnssAdjustmentResult);
                window.gnssBoardState?.fitToResult?.();
            }
            refreshGnssAdjustmentRunningPill();
        });
        modal.addEventListener('hidden.bs.modal', () => {
            window.gnssBoardState?.stopAnimation?.();
            refreshGnssAdjustmentRunningPill();
        });
        window.addEventListener('resize', () => {
            window.gnssBoardState?.requestResize?.();
            window.gnssBoardState?.resize?.(true);
        }, { passive: true });
        const dataColumn = modal.querySelector('#gnss-data-column');
        const debugSection = modal.querySelector('#gnss-debug-section');
        const debugToggle = modal.querySelector('#gnss-debug-toggle');
        const savedColumnWidth = Number(localStorage.getItem('gnssDataColumnWidth'));
        const savedDebugHeight = Number(localStorage.getItem('gnssDebugHeight'));
        const maxInitialColumnWidth = Math.max(340, window.innerWidth * 0.68);
        if (savedColumnWidth >= 340) {
            const fittedWidth = Math.min(savedColumnWidth, maxInitialColumnWidth);
            dataColumn.style.width = `${fittedWidth}px`;
            dataColumn.style.flexBasis = `${fittedWidth}px`;
        }
        const maxInitialDebugHeight = Math.max(150, window.innerHeight * 0.48);
        if (savedDebugHeight >= 140) {
            const fittedHeight = Math.min(savedDebugHeight, maxInitialDebugHeight);
            debugSection.style.height = `${fittedHeight}px`;
            debugSection.style.flexBasis = `${fittedHeight}px`;
        }
        const setDebugCollapsed = collapsed => {
            dataColumn.classList.toggle('gnss-debug-collapsed', collapsed);
            debugToggle?.setAttribute('aria-expanded', String(!collapsed));
            const icon = debugToggle?.querySelector('i');
            if (icon) icon.className = collapsed ? 'bi bi-chevron-up' : 'bi bi-chevron-down';
            if (!collapsed) scheduleGnssAdjustmentDebugUiRefresh();
            requestAnimationFrame(redrawGnssBoard);
        };

        const redrawGnssBoard = () => {
            const board = window.gnssBoardState;
            if (!board?.canvas) return;
            board.requestResize?.();
            board.resize?.(true);
            board.draw?.();
        };
        setDebugCollapsed(localStorage.getItem('gnssDebugCollapsed') === '1');
        const installResizer = (handle, onMove, onEnd) => {
            handle?.addEventListener('pointerdown', event => {
                event.preventDefault();
                handle.setPointerCapture?.(event.pointerId);
                const previousUserSelect = document.body.style.userSelect;
                const previousCursor = document.body.style.cursor;
                document.body.style.userSelect = 'none';
                document.body.style.cursor = getComputedStyle(handle).cursor;
                modal.classList.add('gnss-is-resizing');
                gnssLayoutInteractionActive = true;
                if (window.gnssBoardState) window.gnssBoardState.interactionActive = true;
                let moveFrameId = null;
                let latestPosition = { clientX: event.clientX, clientY: event.clientY };
                const flushMove = () => {
                    moveFrameId = null;
                    onMove(latestPosition);
                };
                const move = moveEvent => {
                    latestPosition = {
                        clientX: moveEvent.clientX,
                        clientY: moveEvent.clientY,
                    };
                    if (moveFrameId === null) {
                        moveFrameId = requestAnimationFrame(flushMove);
                    }
                };
                const end = () => {
                    handle.removeEventListener('pointermove', move);
                    handle.removeEventListener('pointerup', end);
                    handle.removeEventListener('pointercancel', end);
                    if (moveFrameId !== null) {
                        cancelAnimationFrame(moveFrameId);
                        flushMove();
                    }
                    document.body.style.userSelect = previousUserSelect;
                    document.body.style.cursor = previousCursor;
                    modal.classList.remove('gnss-is-resizing');
                    gnssLayoutInteractionActive = false;
                    if (window.gnssBoardState) window.gnssBoardState.interactionActive = false;
                    onEnd?.();
                    redrawGnssBoard();
                    scheduleGnssAdjustmentDebugUiRefresh();
                    scheduleGnssAdjustmentWorkflowRender();
                };
                handle.addEventListener('pointermove', move);
                handle.addEventListener('pointerup', end);
                handle.addEventListener('pointercancel', end);
            });
        };
        installResizer(modal.querySelector('#gnss-column-resizer'), event => {
            const bodyRect = modal.querySelector('.modal-body').getBoundingClientRect();
            const width = Math.max(380, Math.min(bodyRect.right - event.clientX, bodyRect.width * 0.75));
            dataColumn.style.width = `${width}px`;
            dataColumn.style.flexBasis = `${width}px`;
            window.gnssBoardState?.requestResize?.();
        }, () => localStorage.setItem('gnssDataColumnWidth', String(Math.round(dataColumn.getBoundingClientRect().width))));
        installResizer(modal.querySelector('#gnss-debug-resizer'), event => {
            const columnRect = dataColumn.getBoundingClientRect();
            const resultsHeight = modal.querySelector('#adj-results-section')?.offsetHeight || 0;
            const height = Math.max(160, Math.min(columnRect.bottom - event.clientY - resultsHeight, columnRect.height - 150));
            debugSection.style.height = `${height}px`;
            debugSection.style.flexBasis = `${height}px`;
        }, () => localStorage.setItem('gnssDebugHeight', String(Math.round(debugSection.getBoundingClientRect().height))));
        const debugLog = modal.querySelector('#gnss-debug-log');
        debugLog?.addEventListener('scroll', () => {
            const distanceFromBottom = debugLog.scrollHeight - debugLog.scrollTop - debugLog.clientHeight;
            gnssAdjustmentDebugState.autoScroll = distanceFromBottom <= 24;
            const followButton = modal.querySelector('#gnss-debug-follow');
            followButton?.classList.toggle('btn-warning', !gnssAdjustmentDebugState.autoScroll);
            followButton?.classList.toggle('btn-outline-secondary', gnssAdjustmentDebugState.autoScroll);
        }, { passive: true });
        modal.querySelector('#gnss-debug-copy')?.addEventListener('click', event => {
            copyGnssAdjustmentDebugOutput(event.currentTarget);
        });
        modal.querySelector('#gnss-debug-follow')?.addEventListener('click', () => {
            scrollGnssAdjustmentDebugToBottom();
        });
        debugToggle?.addEventListener('click', () => {
            const collapsed = !dataColumn.classList.contains('gnss-debug-collapsed');
            setDebugCollapsed(collapsed);
            localStorage.setItem('gnssDebugCollapsed', collapsed ? '1' : '0');
        });
        modal.querySelector('#gnss-debug-clear')?.addEventListener('click', () => {
            gnssAdjustmentDebugState.entries = [];
            gnssAdjustmentDebugState.entriesRevision += 1;
            gnssAdjustmentDebugState.entriesGeneration += 1;
            gnssAdjustmentDebugState.autoScroll = true;
            addGnssAdjustmentDebug('UI', 'Đã xóa nhật ký debug.', 'info');
        });
        refreshGnssAdjustmentDebugUi();
        return modal;
    }
    window.ensureGnssTerminalModal = ensureGnssTerminalModal;

    function showAdjustmentError(title, message) {
        if (window.Swal?.fire) {
            window.Swal.fire({ icon: 'error', title, text: message });
            return;
        }
        window.toast?.error?.(message);
        alert(`${title}: ${message}`);
    }

    if (!window.Swal?.fire) {
        window.Swal = {
            fire(...args) {
                const config = typeof args[0] === 'object'
                    ? args[0]
                    : { title: args[0], text: args[1] };
                const title = config.title || 'Thong bao';
                const text = config.text || config.html || '';
                window.toast?.error?.(text || title);
                alert(text ? `${title}: ${text}` : title);
            }
        };
    }

    async function readApiError(response) {
        if (!response) return 'Khong nhan duoc phan hoi tu may chu';
        try {
            const data = await response.clone().json();
            return data.detail || data.message || data.error || `HTTP ${response.status}`;
        } catch (_) {
            try {
                const text = await response.text();
                return text || `HTTP ${response.status}`;
            } catch (__) {
                return `HTTP ${response.status}`;
            }
        }
        window.gnssBoardState?.fitToResult?.();
    }

        window.requestGnssAdjustment = async function(projectId, stationIds) {
        // The advanced-panel action operates on the currently selected station,
        // while the map-cluster action passes the project explicitly.
        projectId = projectId || currentStationData?.project_id;
        if (!projectId) {
            showAdjustmentError('Loi', 'Khong xac dinh duoc du an de binh sai');
            return;
        }

        if (isGnssAdjustmentRunning(projectId)) {
            const existingModal = ensureGnssTerminalModal();
            bootstrap.Modal.getOrCreateInstance(existingModal).show();
            addGnssAdjustmentDebug('UI', 'Đã mở lại phiên Bình sai đang chạy; tiến trình không bị khởi động lại.', 'success');
            return;
        }
        
        let terminalModal;
        try {
            // Mở modal tiến trình
            const terminalModalEl = ensureGnssTerminalModal();
            if (!window.bootstrap?.Modal) {
                throw new Error('Bootstrap Modal chua san sang');
            }
            terminalModal = bootstrap.Modal.getOrCreateInstance(terminalModalEl);
            terminalModal.show();
            resetGnssAdjustmentDebug({ projectId, stationIds });
            addGnssAdjustmentDebug('API', `Đang gọi API khởi động cho dự án #${projectId}.`, 'info');
            
            // Initialize before calling the API, otherwise a very fast WebSocket
            // baseline can arrive before the canvas has a rendering context.
            await new Promise(resolve => setTimeout(resolve, 300));
            window.gnssBoardState?.init?.();

            const payload = {
                project_id: projectId,
                base_mountpoint: '',
                selected_clusters: stationIds ? [stationIds] : null
            };
            
            let res;
            if (window.authManager && window.authManager.token) {
                res = await window.authManager.apiFetch('/api/admin/gnss/adjustment/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
            } else {
                res = await fetch('/api/admin/gnss/adjustment/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!res.ok) throw new Error('Bạn cần đăng nhập với quyền Quản trị viên để thực hiện tính năng này');
            }

            if (res && !res.ok) throw new Error(await readApiError(res));
            if (!res) throw new Error('Không nhận được phản hồi từ API khởi động Bình sai');

            let startResult = {};
            try {
                startResult = await res.json();
            } catch (_) {
                startResult = {};
            }
            if (Array.isArray(startResult.expected_station_ids)) {
                gnssAdjustmentDebugState.expectedStationIds = startResult.expected_station_ids;
            }
            if (Array.isArray(startResult.skipped_offline_station_ids) && startResult.skipped_offline_station_ids.length) {
                addGnssAdjustmentDebug(
                    'ONLINE',
                    `Đã loại các trạm GNSS offline: ${startResult.skipped_offline_station_ids.join(', ')}.`,
                    'warning',
                );
                upsertGnssWorkflowNode('online-filter', {
                    title: 'Lọc cụm GNSS đang hoạt động',
                    detail: `Bỏ ${startResult.skipped_offline_station_ids.length} trạm không có heartbeat GNSS gần đây (ID ${startResult.skipped_offline_station_ids.join(', ')}); còn ${gnssAdjustmentDebugState.expectedStationIds.length} rover ứng viên, đang chờ #AGRICA RTK Fixed để xác nhận.`,
                    status: 'warning',
                    icon: 'bi-funnel',
                });
            }
            setGnssAdjustmentPhase(startResult.phase || 'COLLECTING_BASELINE', startResult.message || 'API đã khởi động phiên Bình sai.');
            addGnssAdjustmentDebug(
                'API',
                startResult.existing
                    ? `HTTP ${res.status}: đã nối lại phiên đang chạy, không reset dữ liệu server.`
                    : `HTTP ${res.status}: đang chờ ${gnssAdjustmentDebugState.expectedStationIds.length || 'các'} trạm gửi #AGRICA hợp lệ.`,
                'success',
            );
            startGnssAdjustmentStatusPolling();
            syncGnssAdjustmentStatus();
            
        } catch (error) {
            console.error('Adjustment trigger error:', error);
            setGnssAdjustmentPhase('ERROR', error.message || 'Không thể khởi động Bình sai.');
            addGnssAdjustmentDebug('API', error.message || 'Không thể khởi động Bình sai.', 'error');
            Swal.fire({
                icon: 'error',
                title: 'Lỗi khởi chạy Bình sai',
                text: error.message
            });
        }
    };

    if (closeLongtermBtn && longtermOverlay) {
        closeLongtermBtn.addEventListener('click', () => {
            longtermOverlay.classList.remove('active');
            stopLongTerm3DAnimations();
            rainCorrelationAiRunning = false;
            closeSlideModelResultPopup();

            // Chỉ bỏ force-hidden, giữ hidden (sidebar vẫn đóng)
            if (stationSidebar && currentMapMode !== 'rescue') {
                stationSidebar.classList.remove('force-hidden');
            }

            console.log('📊 [LONGTERM] Analysis overlay closed');
        });
    }

    // Time range selector buttons for long-term analysis
    const rangeSelector = document.getElementById('longterm-range-selector');
    if (rangeSelector) {
        rangeSelector.querySelectorAll('.btn').forEach(btn => {
            btn.addEventListener('click', () => {
                rangeSelector.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                loadLongTermAnalysis({ includeCorrelation: isRainCorrelationAiEnabled });
            });
        });
    }

    const runRainCorrBtn = document.getElementById('btn-run-rain-correlation');
    if (runRainCorrBtn) {
        runRainCorrBtn.addEventListener('click', async () => {
            if (rainCorrelationAiRunning) return;
            isRainCorrelationAiEnabled = true;
            rainCorrelationAiRunning = true;
            updateRainCorrelationAiControls();
            const analysisData = await loadLongTermAnalysis({ includeCorrelation: true });
            showSlideModelResultPopup(analysisData?.rainfall_correlation || null);
        });
    }

    const smModelPopupOverlay = document.getElementById('sm-model-popup-overlay');
    const smModelPopupClose = document.getElementById('sm-model-popup-close');
    const smModelPopupCloseBtn = document.getElementById('sm-model-popup-close-btn');
    const smModelPopupOkBtn = document.getElementById('sm-model-popup-ok-btn');

    [smModelPopupClose, smModelPopupCloseBtn, smModelPopupOkBtn].forEach(btn => {
        if (btn) btn.addEventListener('click', closeSlideModelResultPopup);
    });

    if (smModelPopupOverlay) {
        smModelPopupOverlay.addEventListener('click', (event) => {
            if (event.target === smModelPopupOverlay) {
                closeSlideModelResultPopup();
            }
        });
    }

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeSlideModelResultPopup();
        }
    });

    // Nút tắt/bật còi trong sidebar
    const sirenToggleBtns = document.querySelectorAll('.btn-siren-toggle');
    sirenToggleBtns.forEach(sirenToggleBtn => {
        sirenToggleBtn.addEventListener('click', async () => {
            if (!currentAlertStationId) return;
            const state = sirenToggleBtn.getAttribute('data-siren-state');
            const target = sirenToggleBtn.getAttribute('data-target') || 'all';
            if (state === 'idle') return; // disabled, không làm gì

            try {
                const iconBase = target === 'pi_center' ? 'Center' : 'Point';
                sirenToggleBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>`;

                if (state === 'alerting') {
                    // Đang kêu → Tắt còi
                    const response = await window.authManager.apiFetch(`/api/field/stations/${currentAlertStationId}/stop-siren?target=${target}`, {
                        method: 'POST'
                    });
                    if (response && response.ok) {
                        window.toast?.success(`Mute command sent (${iconBase})`);
                        setSirenButtonState('muted', target);
                        // Tắt âm thanh trên trình duyệt web khi user nhấn Mute
                        AlertSoundManager.mute();
                    } else {
                        window.toast?.error(`Failed to mute (${iconBase})`);
                        setSirenButtonState('alerting', target);
                    }
                } else if (state === 'muted') {
                    // Đã tắt → Bật lại còi
                    const response = await window.authManager.apiFetch(`/api/field/stations/${currentAlertStationId}/enable-siren?target=${target}`, {
                        method: 'POST'
                    });
                    if (response && response.ok) {
                        window.toast?.success(`Alarm re-enabled (${iconBase})`);
                        setSirenButtonState('alerting', target);
                    } else {
                        window.toast?.error(`Failed to enable (${iconBase})`);
                        setSirenButtonState('muted', target);
                    }
                }
            } catch (error) {
                console.error('Error toggling siren:', error);
                window.toast?.error('Cannot connect to server');
                // Khôi phục trạng thái cũ
                const target = sirenToggleBtn.getAttribute('data-target') || 'all';
                setSirenButtonState(state, target);
            }
        });
    });

    console.log('✅ [MAP] All event listeners setup complete');
}
