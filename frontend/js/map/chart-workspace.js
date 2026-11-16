// Inspect and export the rendered measurements without additional API requests.
function formatChartTimestamp(value) {
    return Number.isFinite(value) ? new Date(value).toLocaleString('vi-VN', { hour12: false }) : 'Không có thời gian';
}

function setChartWorkspaceStatus(message, state = 'ready') {
    const status = document.getElementById('chart-workspace-status');
    if (status) { status.textContent = message; status.dataset.state = state; }
    const refresh = document.getElementById('charts-refresh');
    if (refresh) { refresh.disabled = state === 'loading'; refresh.setAttribute('aria-busy', String(state === 'loading')); }
}

function filterWorkspaceCharts() {
    const selected = document.getElementById('chart-sensor-filter')?.value || 'all';
    document.querySelectorAll('#charts-panel .chart-box').forEach(box => {
        box.classList.toggle('chart-filter-hidden', selected !== 'all' && box.querySelector('canvas')?.id !== selected);
    });
}

function downloadChartArtifact(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportWorkspaceChart(id, format) {
    const chart = charts[id];
    if (!chart) return;
    const filename = `${String(currentStationData?.station_code || 'tram').replace(/[^a-zA-Z0-9_-]/g, '_')}-${id}`;
    if (format === 'png') {
        const output = document.createElement('canvas');
        output.width = chart.canvas.width; output.height = chart.canvas.height;
        const context = output.getContext('2d');
        // Resolve semantic colors through an actual element, as tokens may reference tokens.
        context.fillStyle = getComputedStyle(chart.canvas.closest('.chart-box')).backgroundColor;
        context.fillRect(0, 0, output.width, output.height);
        context.drawImage(chart.canvas, 0, 0);
        output.toBlob(blob => { if (blob) downloadChartArtifact(blob, `${filename}.png`); }, 'image/png');
        return;
    }
    const datasets = chart.data.datasets;
    const count = Math.max(0, ...datasets.map(dataset => dataset.data.length));
    const cell = value => {
        const text = String(value ?? '');
        // Prevent spreadsheet formulas in station-defined labels.
        return `"${(/^[=+\-@]/.test(text) && typeof value !== 'number' ? "'" : '')}${text.replaceAll('"', '""')}"`;
    };
    const rows = [[chart._monitoringTimestamps ? 'Thời gian (ISO 8601)' : 'Trục X', ...datasets.map(dataset => dataset.label)]];
    for (let index = 0; index < count; index++) {
        const timestamp = chart._monitoringTimestamps?.[index];
        const first = datasets[0]?.data[index];
        let x = typeof first === 'object' ? first?.x : chart.data.labels?.[index];
        if (chart._monitoringTimestamps) {
            x = Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : '';
        }
        rows.push([x, ...datasets.map(dataset => {
            const point = dataset.data[index];
            return typeof point === 'object' ? (point?.y ?? point) : point;
        })]);
    }
    downloadChartArtifact(new Blob(['\uFEFF' + rows.map(row => row.map(cell).join(',')).join('\r\n')], { type:'text/csv;charset=utf-8' }), `${filename}.csv`);
}

function _ensureWorkspaceDetails(box, title, onToggle) {
    let details = box.querySelector('.chart-data-details');
    if (!details) {
        details = document.createElement('details');
        details.className = 'chart-data-details';
        const toggle = document.createElement('summary');
        toggle.textContent = 'Xem bảng số liệu';
        const scroll = document.createElement('div');
        scroll.className = 'chart-data-scroll';
        scroll.tabIndex = 0;
        scroll.setAttribute('role', 'region');
        scroll.setAttribute('aria-label', `Bảng số liệu: ${title}`);
        details.append(toggle, scroll);
        box.append(details);
        details.addEventListener('toggle', onToggle);
    }
    return details;
}

function _buildWorkspaceTable(chart, datasets, title) {
    const count = Math.max(0, ...datasets.map(dataset => dataset.data.length));
    const table = document.createElement('table');
    const caption = table.createCaption();
    caption.textContent = `${title} · ${Math.min(100, count)} / ${count} điểm gần nhất. Ô “—” là dữ liệu thiếu. Tải CSV để xem toàn bộ.`;
    const heading = table.createTHead().insertRow();
    const headers = [chart._monitoringTimestamps ? 'Thời gian (giờ địa phương)' : 'Trục X', ...datasets.map(d => d.label)];
    for (const label of headers) {
        const cell = document.createElement('th');
        cell.scope = 'col';
        cell.textContent = label;
        heading.append(cell);
    }
    const body = table.createTBody();
    for (let index = count - 1; index >= Math.max(0, count - 100); index--) {
        const row = body.insertRow();
        const first = datasets[0]?.data[index];
        let x = chart.data.labels?.[index];
        if (first && typeof first === 'object') x = first.x;
        if (chart._monitoringTimestamps) x = formatChartTimestamp(chart._monitoringTimestamps[index]);
        row.insertCell().textContent = x ?? '—';
        for (const dataset of datasets) {
            const point = dataset.data[index];
            const value = point && typeof point === 'object' ? point.y : point;
            row.insertCell().textContent = typeof value === 'number' && Number.isFinite(value)
                ? value.toLocaleString('vi-VN', { maximumFractionDigits: 6 })
                : '—';
        }
    }
    return table;
}

function renderWorkspaceDataTable(chart, box, title) {
    if (!chart) return;
    const chartId = chart.canvas.id;
    const details = _ensureWorkspaceDetails(box, title, () => {
        if (details.open) renderWorkspaceDataTable(charts[chartId], box, title);
    });
    // Render only the most recent 100 rows when expanded; CSV retains all loaded points.
    if (!details.open) return;
    const table = _buildWorkspaceTable(chart, chart.data.datasets, title);
    details.querySelector('.chart-data-scroll').replaceChildren(table);
}

function enhanceChartWorkspace(data) {
    const context = document.getElementById('charts-station-context');
    if (context && data) context.textContent = [data.name, data.station_code].filter(Boolean).join(' · ');
    const select = document.getElementById('chart-sensor-filter');
    const previous = select?.value;
    const panel = document.getElementById('charts-panel');
    if (panel) panel.dataset.rangeLabel = data?._chartRangeLabel || getChartRange().label;
    if (select) select.replaceChildren(new Option('Tất cả cảm biến', 'all'));
    let measurementCount = 0;
    document.querySelectorAll('#charts-panel .chart-box').forEach(box => {
        const canvas = box.querySelector('canvas');
        const chart = charts[canvas?.id];
        if (!chart || box.style.display === 'none') return;
        const title = box.querySelector('.chart-title')?.textContent.trim() || canvas.id;
        select?.add(new Option(title, canvas.id));
        let tools = box.querySelector('.chart-export-tools');
        if (!tools) {
            tools = document.createElement('div'); tools.className = 'chart-export-tools';
            for (const [format, label] of [['csv','CSV'], ['png','PNG']]) {
                const button = document.createElement('button');
                button.type = 'button'; button.className = 'chart-tool-button'; button.textContent = label;
                button.setAttribute('aria-label', `Xuất ${label}: ${title}`);
                button.onclick = () => exportWorkspaceChart(canvas.id, format);
                tools.append(button);
            }
            box.querySelector('.chart-title')?.after(tools);
        }
        let summary = box.querySelector('.chart-series-summary');
        if (!summary) { summary = document.createElement('div'); summary.className = 'chart-series-summary'; box.querySelector('.chart-canvas-wrap')?.after(summary); }
        summary.replaceChildren();
        for (const dataset of chart.data.datasets) {
            const values = dataset.data.map(point => point && typeof point === 'object' ? point.y : point).filter(value => typeof value === 'number' && Number.isFinite(value));
            measurementCount += values.length;
            const line = document.createElement('p');
            const name = document.createElement('strong'); name.textContent = dataset.label;
            let seriesText = ' · Chưa có dữ liệu trong khoảng này';
            if (values.length) {
                const missingText = dataset.data.length > values.length ? ` · Thiếu ${dataset.data.length - values.length} mẫu` : '';
                const minVal = Math.min(...values).toLocaleString('vi-VN', {maximumFractionDigits:4});
                const maxVal = Math.max(...values).toLocaleString('vi-VN', {maximumFractionDigits:4});
                const avgVal = (values.reduce((total,value)=>total+value,0)/values.length).toLocaleString('vi-VN', {maximumFractionDigits:4});
                seriesText = ` · ${values.length.toLocaleString('vi-VN')} điểm${missingText} · Thấp ${minVal} · Cao ${maxVal} · TB ${avgVal}`;
            }
            line.append(name, document.createTextNode(seriesText));
            summary.append(line);
        }
        renderWorkspaceDataTable(chart, box, title);
        canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', `${title}. ${summary.textContent}`);
        tools.querySelectorAll('button').forEach(button => { button.disabled = chart.data.datasets.every(dataset => !dataset.data.length); });
    });
    if (select && [...select.options].some(option => option.value === previous)) select.value = previous;
    filterWorkspaceCharts();
    const latest = Object.values(charts).flatMap(chart => chart._monitoringTimestamps || []).filter(Number.isFinite).reduce((max, timestamp) => Math.max(max, timestamp), 0);
    let statusText = 'Chưa có dữ liệu trong khoảng này. Thử khoảng thời gian khác hoặc tải lại.';
    if (measurementCount) {
        const rangeLabel = data?._chartRangeLabel || getChartRange().label;
        const latestText = latest ? ` Mẫu mới nhất: ${formatChartTimestamp(latest)}.` : '';
        statusText = `Đã tải dữ liệu · ${rangeLabel}.${latestText} CSV chứa các điểm đã tải; thời gian xuất theo UTC.`;
    }
    setChartWorkspaceStatus(statusText, measurementCount ? 'ready' : 'empty');
}

function setupChartWorkspaceControls() {
    window.addEventListener('themeChanged', () => {
        const styles = getComputedStyle(document.documentElement);
        const text = styles.getPropertyValue('--text-secondary').trim();
        const border = styles.getPropertyValue('--border-color').trim();
        for (const chart of Object.values(charts)) {
            for (const scale of Object.values(chart.options.scales || {})) {
                if (scale.ticks) scale.ticks.color = text;
                if (scale.grid?.display !== false) scale.grid.color = border;
            }
            if (chart.options.plugins.legend?.labels) chart.options.plugins.legend.labels.color = text;
            if (chart.options.plugins.tooltip) {
                Object.assign(chart.options.plugins.tooltip, {
                    backgroundColor: styles.getPropertyValue('--bg-secondary').trim(),
                    titleColor: styles.getPropertyValue('--text-primary').trim(),
                    bodyColor: text, borderColor: border,
                });
            }
            chart.update('none');
        }
    });
    document.getElementById('chart-sensor-filter')?.addEventListener('change', filterWorkspaceCharts);
    document.getElementById('charts-refresh')?.addEventListener('click', () => loadStationHistoryAndRenderCharts({ force:true }));
    const expand = document.getElementById('charts-expand');
    expand?.addEventListener('click', () => {
        const wide = document.getElementById('charts-panel')?.classList.toggle('charts-expanded');
        expand.setAttribute('aria-pressed', String(Boolean(wide)));
        expand.setAttribute('aria-label', wide ? 'Thu gọn biểu đồ' : 'Mở rộng biểu đồ');
        Object.values(charts).forEach(chart => chart.resize());
    });
    document.getElementById('charts-panel')?.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        event.preventDefault(); event.stopPropagation();
        const panel = event.currentTarget;
        if (panel.classList.contains('charts-expanded')) {
            expand?.click(); expand?.focus();
        } else {
            setChartsPanelOpen(panel, false);
            document.getElementById('btn-show-charts')?.focus();
        }
    });
}
