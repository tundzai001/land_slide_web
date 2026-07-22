// =====================================================
// MARKER ALERT STATE — Đỏ + nhấp nháy khi có cảnh báo
// =====================================================
let markerAlertState = {};

function setMarkerAlert(stationId, active) {
    const marker = markers[stationId];
    if (!marker) return;

    if (active) {
        markerAlertState[stationId] = true;

        const iconHtml = `<div class="marker-circle marker-device-alert" style="
                    width: 22px; height: 22px; box-sizing: border-box; background: #fa5252;
                    border-radius: 50%; border: 3px solid white;
                    box-shadow: 0 0 12px rgba(250, 82, 82, 0.8);
                "></div>`;

        const alertIcon = L.divIcon({
            className: 'custom-map-marker',
            html: iconHtml,
            iconSize: [22, 22],
            iconAnchor: [11, 11]
        });
        marker.setIcon(alertIcon);

        console.log(`🔴 [MARKER] Station ${stationId} → ĐỎ + nhấp nháy`);
    } else {
        clearMarkerAlert(stationId);
    }
}

function clearMarkerAlert(stationId) {
    delete markerAlertState[stationId];

    // Tìm station data để khôi phục màu gốc theo risk_level
    const station = allStations.find(s => s.id === stationId);
    if (station) {
        // Xóa cache để bắt buộc vẽ lại marker
        delete stationStateCache[stationId];
        updateMarker(station);
    }

    console.log(`🟢 [MARKER] Station ${stationId} → Khôi phục màu gốc`);
}

// (updateSidebarUI đã được chuyển xuống dưới — duy nhất 1 bản)

