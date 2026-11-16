// --- GUEST RESCUE PICK ON MAP LOGIC ---
let isPickingRescueLocation = false;
let rescueMapClickListener = null;

window.enablePickOnMap = function () {
    if (!window.map || !window.rescueFormModal) return;

    // Tạm ẩn modal
    window.rescueFormModal.hide();

    // Đổi con trỏ chuột
    isPickingRescueLocation = true;
    document.getElementById('map').style.cursor = 'crosshair';
    window.toast?.info('Click vào Bản đồ để chốt Vị trí Cứu hộ', 5000);

    // Huỷ listener cũ nếu có
    if (rescueMapClickListener) {
        window.map.off('click', rescueMapClickListener);
    }

    // Lắng nghe sự kiện click
    rescueMapClickListener = function (e) {
        if (!isPickingRescueLocation) return;

        const lat = e.latlng.lat;
        const lon = e.latlng.lng;

        // Cập nhật input
        const latEl = document.getElementById('guest-rescue-lat');
        const lonEl = document.getElementById('guest-rescue-lon');
        if (latEl) latEl.value = Number(lat).toFixed(6);
        if (lonEl) lonEl.value = Number(lon).toFixed(6);

        // Trả về trạng thái bình thường
        isPickingRescueLocation = false;
        document.getElementById('map').style.cursor = '';
        window.map.off('click', rescueMapClickListener);

        // Vẽ marker tạm cho vị trí vừa click
        if (window.userLocationMarker && window.map.hasLayer(window.userLocationMarker)) {
            window.map.removeLayer(window.userLocationMarker);
        }
        if (window.userLocationCircle && window.map.hasLayer(window.userLocationCircle)) {
            window.map.removeLayer(window.userLocationCircle);
        }

        window.userLocationMarker = L.marker([lat, lon], {
            icon: L.divIcon({
                className: 'user-location-marker',
                html: '<div style="width: 18px; height: 18px; background: #0d6efd; border-radius: 50%; border: 3px solid white; box-shadow: 0 0 15px rgba(13,110,253,0.8); animation: guestRescuePulse 1.5s infinite;"></div>',
                iconSize: [18, 18],
                iconAnchor: [9, 9]
            })
        }).addTo(window.map).bindPopup('Vị trí được chọn trên bản đồ');

        window.map.setView([lat, lon], 15, { animate: true });

        // Mở lại modal sau thời gian ngắn
        setTimeout(() => {
            window.toast?.success('Đã ghim toạ độ thành công!');
            if (window.rescueFormModal) window.rescueFormModal.show();
        }, 150);
    };

    // Đợi 1 chút để không bắt nhầm sự kiện click vào nút
    setTimeout(() => {
        window.map.on('click', rescueMapClickListener);
    }, 150);
};

// --- ADMIN DRAGGABLE MARKER UTILITY ---
/**
 * Dành cho Admin: Kéo thả một marker để lấy toạ độ mới
 * Cách dùng: window.makeMarkerDraggable(markerObj)
 */
window.makeMarkerDraggable = function (marker, latInputId = 'input-lat', lngInputId = 'input-lng') {
    if (!marker) return;

    // Kích hoạt tính năng kéo thả của marker
    if (marker.dragging) {
        marker.dragging.enable();
    }

    // Lắng nghe sự kiện kết thúc thả chuột
    marker.on('dragend', function (e) {
        const position = marker.getLatLng();
        const lat = position.lat.toFixed(6);
        const lng = position.lng.toFixed(6);

        // Cập nhật DOM
        const latInput = document.getElementById(latInputId);
        const lngInput = document.getElementById(lngInputId);

        if (latInput) latInput.value = lat;
        if (lngInput) lngInput.value = lng;

        // Thông báo cho Admin (Sử dụng SweetAlert2 nếu có)
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: 'Đã cập nhật vị trí!',
                html: `Vị trí mới:<br><b>Lat:</b> ${lat}<br><b>Lng:</b> ${lng}`,
                icon: 'success',
                timer: 2500,
                showConfirmButton: false,
                toast: true,
                position: 'bottom-end'
            });
        } else if (window.toast?.success) {
            window.toast.success(`Đã lấy vị trí: ${lat}, ${lng}`);
        } else {
            alert(`Đã cập nhật vị trí mới!\nLat: ${lat}\nLng: ${lng}`);
        }
    });
};

// --- FEATURE 2: VOICE ALERT (Web Speech API) ---
function playWarningVoice(stationName, level) {
    if (!('speechSynthesis' in window)) {
        console.warn('[VOICE] Web Speech API not supported');
        return;
    }
    const text = `Cảnh báo! Trạm ${stationName} đang ở mức ${level}. Yêu cầu chú ý.`;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'vi-VN';
    utterance.rate = 0.9;
    utterance.pitch = 1.1;
    utterance.volume = 1;

    // Ưu tiên giọng nữ tiếng Việt
    const voices = speechSynthesis.getVoices();
    const viVoice = voices.find(v => v.lang.startsWith('vi') && v.name.toLowerCase().includes('female'))
        || voices.find(v => v.lang.startsWith('vi'))
        || null;
    if (viVoice) utterance.voice = viVoice;

    speechSynthesis.cancel(); // Hủy giọng cũ nếu đang phát
    speechSynthesis.speak(utterance);
}
window.playWarningVoice = playWarningVoice;

// --- FEATURE 3: QR CODE SHARING ---
window.showStationQR = async function (lat, lng, stationName) {
    // Xoá popup cũ nếu có
    let existing = document.getElementById('qr-popup-overlay');
    if (existing) existing.remove();

    const url = `${window.location.origin}/map?lat=${lat}&lng=${lng}`;

    const overlay = document.createElement('div');
    overlay.id = 'qr-popup-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:var(--z-critical);display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.5);';
    overlay.innerHTML = `
        <div class="qr-popup-glass">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h6 class="mb-0 fw-bold"><i class="bi bi-qr-code me-2"></i>${stationName || 'Trạm'}</h6>
                <button class="btn btn-sm btn-close" id="qr-popup-close"></button>
            </div>
            <div id="qr-canvas-wrap" class="text-center mb-2"></div>
            <div class="text-center small opacity-75 text-break" style="font-size:0.7rem;">${url}</div>
        </div>
    `;
    document.body.appendChild(overlay);

    // Load the optional QR bundle only when this feature is opened.
    if (typeof QRCode === 'undefined') {
        await window.loadFeatureLibrary?.('qr');
    }
    if (typeof QRCode !== 'undefined') {
        new QRCode(document.getElementById('qr-canvas-wrap'), {
            text: url, width: 180, height: 180, colorDark: '#0f172a', colorLight: '#ffffff'
        });
    } else {
        document.getElementById('qr-canvas-wrap').innerHTML = '<p class="text-muted">Thư viện QR chưa được tải.</p>';
    }

    document.getElementById('qr-popup-close').addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
};

// --- FEATURE 4: PDF EXPORT (Server-side) ---
window.exportStationPDF = async function () {
    if (!currentStationData?.id) {
        // Fallback client-side
        const sidebar = document.getElementById('detail-sidebar');
        if (typeof html2pdf === 'undefined') {
            await window.loadFeatureLibrary?.('pdf');
        }
        if (!sidebar || typeof html2pdf === 'undefined') {
            window.toast?.error('Không thể xuất PDF.');
            return;
        }
        const stName = document.getElementById('st-name')?.textContent || 'Tram';
        const fileName = `BaoCao_${stName.replace(/\s+/g, '_')}_${new Date().toISOString().slice(0, 10)}.pdf`;
        const clone = sidebar.cloneNode(true);
        clone.style.cssText = 'position:absolute;left:-9999px;top:0;width:700px;background:#fff;color:#1e293b;padding:24px;';
        clone.querySelectorAll('.sidebar-close-btn, .btn-export-pdf, .btn-qr-share').forEach(el => el.remove());
        document.body.appendChild(clone);
        html2pdf().set({
            margin: [10, 10, 10, 10], filename: fileName, image: { type: 'jpeg', quality: 0.95 },
            html2canvas: { scale: 2, useCORS: true, backgroundColor: '#ffffff' },
            jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
        }).from(clone).save().then(() => { clone.remove(); window.toast?.success(`Đã tải ${fileName}`); })
            .catch(() => { clone.remove(); window.toast?.error('Lỗi xuất PDF.'); });
        return;
    }

    // Server-side professional PDF
    const stationId = currentStationData.id;
    window.toast?.info('Đang tạo báo cáo PDF trên server...');
    const url = `/api/admin/export/station/${stationId}/pdf`;
    fetch(url).then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
    }).then(blob => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `BaoCao_${(currentStationData.name || 'Tram').replace(/\s+/g, '_')}_${new Date().toISOString().slice(0, 10)}.pdf`;
        a.click();
        URL.revokeObjectURL(a.href);
        window.toast?.success('Đã tải xuống báo cáo PDF!');
    }).catch(err => {
        console.error('[PDF Server]', err);
        window.toast?.error('Lỗi khi xuất PDF từ server. Thử phương án client-side...');
    });
};
// --- FEATURE 5: STATION RISK HEATMAP LAYER ---
let stationHeatLayer = null;
let heatmapVisible = false;
let heatmapLoading = false;

function buildHeatmapData() {
    return allStations
        .filter(station => hasValidLatLon(station.location))
        .filter(station => ['MEDIUM', 'CRITICAL'].includes(normalizeRiskLevel(station.risk_level, station.status)))
        .map(station => {
            const risk = normalizeRiskLevel(station.risk_level, station.status);
            return [Number(station.location.lat), Number(station.location.lon), risk === 'CRITICAL' ? 1 : 0.65];
        });
}

function refreshHeatmapData() {
    if (!heatmapVisible || !stationHeatLayer) return;
    const data = buildHeatmapData();
    stationHeatLayer.setLatLngs(data);
    updateHeatmapLegend(data);
}

function updateHeatmapLegend(data) {
    const legend = document.getElementById('heatmap-legend');
    const count = document.getElementById('heatmap-count');
    if (count) count.textContent = `${data.length} trạm cảnh báo · ${data.filter(point => point[2] === 1).length} nguy cấp`;
    if (legend) legend.hidden = !heatmapVisible;
}

async function toggleHeatmap() {
    const btn = document.getElementById('heatmap-toggle');
    const checkbox = document.getElementById('layer-heatmap');
    if (!map || heatmapLoading) return;
    if (!heatmapVisible && !buildHeatmapData().length) {
        if (checkbox) checkbox.checked = false;
        window.toast?.info('Hiện không có trạm cảnh báo có tọa độ để hiển thị.');
        return;
    }
    if (!heatmapVisible && L.heatLayer === undefined) {
        heatmapLoading = true;
        if (btn) btn.disabled = true;
        btn?.setAttribute('aria-busy', 'true');
        btn?.classList.add('is-loading');
        try { await window.loadFeatureLibrary?.('heat'); }
        catch (err) {
            console.debug('Failed to load heat library:', err);
            if (checkbox) checkbox.checked = false;
            window.toast?.error('Không thể tải lớp heatmap.');
            return;
        } finally {
            heatmapLoading = false;
            if (btn) btn.disabled = false;
            btn?.removeAttribute('aria-busy');
            btn?.classList.remove('is-loading');
        }
    }
    if (L.heatLayer === undefined) {
        if (checkbox) checkbox.checked = heatmapVisible;
        window.toast?.error('Plugin heatmap chưa sẵn sàng.');
        return;
    }

    heatmapVisible = !heatmapVisible;

    if (heatmapVisible) {
        const data = buildHeatmapData();
        if (!data.length) {
            heatmapVisible = false;
            if (checkbox) checkbox.checked = false;
            setMapState({ layers: { heatmap: false } });
            window.toast?.info('Hiện không có trạm cảnh báo có tọa độ để hiển thị.');
            return;
        }
        stationHeatLayer = L.heatLayer(data, {
            radius: 35, blur: 18, maxZoom: 7, minOpacity: 0.25,
            gradient: { 0.2: '#2196f3', 0.4: '#4caf50', 0.6: '#ffeb3b', 0.8: '#ff9800', 1: '#f44336' }
        }).addTo(map);
        btn?.classList.add('active');
        btn?.setAttribute('aria-pressed', 'true');
        if (checkbox) checkbox.checked = true;
        setMapState({ layers: { heatmap: true } });
        updateHeatmapLegend(data);
    } else {
        if (stationHeatLayer) {
            map.removeLayer(stationHeatLayer);
            stationHeatLayer = null;
        }
        btn?.classList.remove('active');
        btn?.setAttribute('aria-pressed', 'false');
        if (checkbox) checkbox.checked = false;
        setMapState({ layers: { heatmap: false } });
        updateHeatmapLegend([]);
    }
}

runWhenDomReady(() => {
    const heatBtn = document.getElementById('heatmap-toggle');
    if (heatBtn) heatBtn.addEventListener('click', toggleHeatmap);
});

// --- FEATURE 6: TIMELINE SLIDER ---
let timelineMarkers = []; // Sẽ được tạo từ rescueRequestsData

function setupTimelineSlider() {
    const slider = document.getElementById('timeline-slider');
    const label = document.getElementById('timeline-label');
    const wrap = document.getElementById('timeline-slider-wrap');
    if (!slider || !label || !wrap) return;

    slider.addEventListener('input', () => {
        const dayValue = Number.parseInt(slider.value, 10);
        const targetDate = new Date();
        targetDate.setDate(targetDate.getDate() - (30 - dayValue));
        const dateStr = targetDate.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' });
        label.textContent = `Ngày ${dateStr}`;

        // Filter rescue markers: hiển thị marker thuộc ngày đó
        Object.entries(rescueMarkers).forEach(([id, marker]) => {
            const req = rescueRequestsData.find(r => String(r.id) === String(id));
            if (!req?.created_at) return;

            const reqDate = new Date(normalizeEpochMs(req.created_at));
            const daysDiff = Math.floor((Date.now() - reqDate.getTime()) / (1000 * 60 * 60 * 24));
            const reqDaySlot = 30 - daysDiff; // 1 = cũ nhất, 30 = mới nhất

            if (window.map) {
                if (reqDaySlot <= dayValue) {
                    if (!window.map.hasLayer(marker)) marker.addTo(window.map);
                } else if (window.map.hasLayer(marker)) {
                    window.map.removeLayer(marker);
                }
            }
        });
    });
}

// Hiển thị timeline khi có đủ dữ liệu
window.showTimelineSlider = function () {
    const wrap = document.getElementById('timeline-slider-wrap');
    if (wrap) {
        wrap.style.display = wrap.style.display === 'none' ? 'flex' : 'none';
        if (wrap.style.display === 'flex') setupTimelineSlider();
    }
};

console.log('[MAP] Script fully loaded');
