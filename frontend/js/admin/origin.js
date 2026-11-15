(() => {
class AdminOriginFeature extends window.AdminManager {
    // =========================================================================
    // FETCH ORIGIN COORDINATES (LIVE FROM DEVICE)
    // =========================================================================

    _applyLiveOriginResult(result, statusEl) {
        const latEl = document.getElementById('origin-lat');
        const lonEl = document.getElementById('origin-lon');
        const hEl = document.getElementById('origin-h');
        const currentLat = parseFloat(latEl?.value);
        const currentLon = parseFloat(lonEl?.value);
        const currentH = parseFloat(hEl?.value);
        const hasOrigin = Number.isFinite(currentLat) && Number.isFinite(currentLon);

        if (!hasOrigin) {
            // No existing origin -> allow filling
            if (latEl) latEl.value = result.lat;
            if (lonEl) lonEl.value = result.lon;
            if (hEl) hEl.value = result.h;
            this.updateOriginActionButtons(true);

            statusEl.innerHTML = `<span class="text-success">✅ Đã nhận: Sats ${result.num_sats}, Fix ${result.fix_quality}</span>`;
            window.toast?.success('Đã lấy tọa độ thực từ thiết bị!');
        } else {
            // Existing origin -> verification only, do NOT overwrite locked origin fields
            const deltaM = this.computeGeoDistanceMeters(currentLat, currentLon, result.lat, result.lon);
            const deltaH = Number.isFinite(currentH) ? (result.h - currentH) : 0;
            statusEl.innerHTML = `<span class="text-info"><i class="bi bi-info-circle me-1" aria-hidden="true"></i>Kiểm tra trực tiếp: Δxy=${deltaM.toFixed(3)}m, Δh=${deltaH.toFixed(3)}m (Sats ${result.num_sats}, Fix ${result.fix_quality})</span>`;
            window.toast?.info('Đã kiểm tra live GNSS. Origin hiện tại không bị ghi đè.');
        }
    }

    async fetchLatestOrigin() {
        const topic = document.getElementById('topic-gnss')?.value.trim();
        if (!topic) {
            window.toast?.warning('Vui lòng nhập MQTT Topic của GNSS trước');
            return;
        }

        const statusEl = document.getElementById('origin-status');
        const btnEl = document.getElementById('btn-fetch-origin');

        statusEl.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Đang kết nối thiết bị...';
        if (btnEl) btnEl.disabled = true;

        try {
            // Gọi API backend để subscribe tạm thời vào topic và lấy message mới nhất
            const res = await fetch('/api/admin/gnss/fetch-live-origin', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ 
                    topic: topic,
                    mqtt: {
                        host: document.getElementById('cfg-gnss-mqtt-host')?.value?.trim() || '',
                        port: document.getElementById('cfg-gnss-mqtt-port')?.value ? parseInt(document.getElementById('cfg-gnss-mqtt-port').value) : null,
                        username: document.getElementById('cfg-gnss-mqtt-user')?.value?.trim() || '',
                        password: document.getElementById('cfg-gnss-mqtt-pass')?.value?.trim() || '',
                        use_tls: !!document.getElementById('cfg-gnss-mqtt-tls')?.checked
                    }
                })
            });

            const result = await res.json();

            if (!res.ok) {
                throw new Error(result.detail || 'Timeout hoặc thiết bị offline');
            }
            this._applyLiveOriginResult(result, statusEl);
        } catch (e) {
            console.error(e);
            statusEl.innerHTML = `<span class="text-danger">❌ Lỗi: ${e.message}</span>`;
            window.toast?.error('Không lấy được tọa độ. Kiểm tra lại Topic hoặc thiết bị.');
        } finally {
            if (btnEl) btnEl.disabled = false;
        }
    }

    computeGeoDistanceMeters(lat1, lon1, lat2, lon2) {
        const toRad = (v) => (Number(v) * Math.PI) / 180;
        const R = 6371000;
        const p1 = toRad(lat1);
        const p2 = toRad(lat2);
        const dLat = toRad(lat2 - lat1);
        const dLon = toRad(lon2 - lon1);
        const a = Math.sin(dLat / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * (Math.sin(dLon / 2) ** 2);
        return 2 * R * Math.asin(Math.sqrt(a));
    }

}
window.applyAdminFeature(AdminOriginFeature);
})();
