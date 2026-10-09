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
        const x = chart._monitoringTimestamps ? (Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : '') : (typeof first === 'object' && first ? first.x : chart.data.labels?.[index]);
        rows.push([x, ...datasets.map(dataset => {
            const point = dataset.data[index];
            return point && typeof point === 'object' ? point.y : point;
        })]);
    }
    downloadChartArtifact(new Blob(['\uFEFF' + rows.map(row => row.map(cell).join(',')).join('\r\n')], { type:'text/csv;charset=utf-8' }), `${filename}.csv`);
}

function enhanceChartWorkspace(data) {
    const context = document.getElementById('charts-station-context');
    if (context && data) context.textContent = [data.name, data.station_code].filter(Boolean).join(' · ');
    const select = document.getElementById('chart-sensor-filter');
    const previous = select?.value;
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
            line.append(name, document.createTextNode(values.length
                ? ` · ${values.length.toLocaleString('vi-VN')} điểm · Thấp ${Math.min(...values).toLocaleString('vi-VN', {maximumFractionDigits:4})} · Cao ${Math.max(...values).toLocaleString('vi-VN', {maximumFractionDigits:4})} · TB ${(values.reduce((total,value)=>total+value,0)/values.length).toLocaleString('vi-VN', {maximumFractionDigits:4})}`
                : ' · Chưa có dữ liệu trong khoảng này'));
            summary.append(line);
        }
        canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', `${title}. ${summary.textContent}`);
        tools.querySelectorAll('button').forEach(button => { button.disabled = chart.data.datasets.every(dataset => !dataset.data.length); });
    });
    if (select && [...select.options].some(option => option.value === previous)) select.value = previous;
    filterWorkspaceCharts();
    setChartWorkspaceStatus(measurementCount ? `Đã tải dữ liệu · ${getChartRange().label}. CSV chứa các điểm đã tải; thời gian xuất theo UTC.` : 'Chưa có dữ liệu trong khoảng này. Thử khoảng thời gian khác hoặc tải lại.', measurementCount ? 'ready' : 'empty');
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
