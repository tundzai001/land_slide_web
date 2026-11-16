(() => {
class AdminAutoAdjustmentFeature extends window.AdminManager {

    escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[char]);
    }

    // Called when the auto-adjustment toggle switch changes
    onAutoAdjToggle(enabled) {
        const body = document.getElementById('auto-adj-body');
        if (body) {
            body.style.display = enabled ? 'block' : 'none';
        }
        if (enabled) {
            this.populateAutoAdjClusterCheckboxes();
            this.generateSchedulePreview();
        }
    }

    // Populate cluster checkboxes from current modal clusters
    populateAutoAdjClusterCheckboxes() {
        const container = document.getElementById('auto-adj-cluster-checkboxes');
        if (!container) return;

        const clusterRows = document.querySelectorAll('#project-gnss-clusters-container .cluster-row');
        if (clusterRows.length === 0) {
            container.innerHTML = '<span class="text-muted small">Chưa có cụm nào được cấu hình</span>';
            return;
        }

        // Get current config to restore selections
        const project = (this.projectsData || []).find(p => p.id === this.currentProjectId);
        const savedConfig = project?.auto_adjustment_config || {};
        const savedClusters = Array.isArray(savedConfig.selected_clusters)
            ? savedConfig.selected_clusters.map(Number)
            : [];

        let html = '';
        clusterRows.forEach((row, idx) => {
            const nameInput = row.querySelector('.cluster-name');
            const clusterName = nameInput ? nameInput.value.trim() : `Cụm ${idx + 1}`;
            if (!clusterName) return;

            const isChecked = savedClusters.includes(idx) ? 'checked' : '';
            const inputId = `auto-adj-cluster-${idx}`;
            html += `
                <div class="form-check auto-adjustment-cluster-option">
                    <input class="form-check-input auto-adj-cluster-cb" type="checkbox" value="${idx}" id="${inputId}" ${isChecked}>
                    <label class="form-check-label" for="${inputId}">
                        <span class="auto-adjustment-cluster-icon"><i class="bi bi-bounding-box-circles"></i></span>
                        <span>${this.escapeHtml(clusterName)}</span>
                    </label>
                </div>
            `;
        });

        container.innerHTML = html || '<span class="text-muted small">Chưa có cụm nào</span>';
    }

    // Generate the schedule preview based on interval and start hour
    calculateDailySchedule(interval, startHour) {
        const safeInterval = Number.isInteger(interval) && interval > 0 ? interval : 4;
        const safeStart = Number.isInteger(startHour) && startHour >= 0 && startHour <= 23
            ? startHour
            : 0;
        const hours = [];
        let hour = safeStart;
        while (hours.length < Math.floor(24 / safeInterval)) {
            hours.push(`${String(hour).padStart(2, '0')}:00`);
            hour = (hour + safeInterval) % 24;
        }
        return { hours, nextCycle: `${String(safeStart).padStart(2, '0')}:00` };
    }

    generateSchedulePreview() {
        const intervalSelect = document.getElementById('auto-adj-interval');
        const startHourInput = document.getElementById('auto-adj-start-hour');
        const previewContainer = document.getElementById('auto-adj-schedule-preview');
        if (!intervalSelect || !startHourInput || !previewContainer) return;

        const interval = Number.parseInt(intervalSelect.value) || 4;
        let startHour = Number.parseInt(startHourInput.value);
        if (Number.isNaN(startHour) || startHour < 0 || startHour > 23) startHour = 0;

        const { hours, nextCycle } = this.calculateDailySchedule(interval, startHour);

        if (hours.length === 0) {
            previewContainer.innerHTML = '<span class="text-muted small">Không có mốc giờ nào</span>';
            return;
        }

        previewContainer.innerHTML = hours.map(h =>
            `<span class="auto-adjustment-time-chip"><i class="bi bi-clock"></i>${h}</span>`
        ).join('') + `<span class="auto-adjustment-next-day"><i class="bi bi-arrow-right"></i>Ngày kế tiếp&nbsp; ${nextCycle}</span>`;
    }

    // Load auto-adjustment config into the modal when it opens
    loadAutoAdjustmentConfig(project) {
        const config = project?.auto_adjustment_config || {};
        const enabledCheckbox = document.getElementById('auto-adj-enabled');
        const body = document.getElementById('auto-adj-body');
        const intervalSelect = document.getElementById('auto-adj-interval');
        const startHourInput = document.getElementById('auto-adj-start-hour');

        if (!enabledCheckbox || !body) return;

        const isEnabled = !!config.enabled;
        enabledCheckbox.checked = isEnabled;
        body.style.display = isEnabled ? 'block' : 'none';

        // Restore interval from saved scheduled_hours
        if (config.scheduled_hours && config.scheduled_hours.length >= 2) {
            // Infer interval from first two hours
            const h1 = Number.parseInt(config.scheduled_hours[0].split(':')[0]);
            const h2 = Number.parseInt(config.scheduled_hours[1].split(':')[0]);
            const inferredInterval = (h2 - h1 + 24) % 24;
            if (intervalSelect) intervalSelect.value = String(inferredInterval);
            // Infer start hour
            if (startHourInput) startHourInput.value = String(h1);
        } else if (config.interval_hours) {
            if (intervalSelect) intervalSelect.value = String(config.interval_hours);
            if (startHourInput) startHourInput.value = String(config.start_hour ?? 0);
        }

        if (isEnabled) {
            this.populateAutoAdjClusterCheckboxes();
            this.generateSchedulePreview();
        }
    }

    // Collect auto-adjustment config from the modal
    collectAutoAdjustmentConfig() {
        const enabledCheckbox = document.getElementById('auto-adj-enabled');
        if (!enabledCheckbox || !enabledCheckbox.checked) {
            return { enabled: false };
        }

        const intervalSelect = document.getElementById('auto-adj-interval');
        const startHourInput = document.getElementById('auto-adj-start-hour');

        const interval = Number.parseInt(intervalSelect?.value) || 4;
        let startHour = Number.parseInt(startHourInput?.value);
        if (Number.isNaN(startHour) || startHour < 0 || startHour > 23) startHour = 0;

        const { hours: scheduledHours } = this.calculateDailySchedule(interval, startHour);

        // Collect selected cluster indices
        const selectedClusters = [];
        document.querySelectorAll('.auto-adj-cluster-cb:checked').forEach(cb => {
            selectedClusters.push(Number.parseInt(cb.value));
        });

        const stationOwner = new Map();
        const clusterRows = [...document.querySelectorAll('#project-gnss-clusters-container .cluster-row')];
        for (const clusterIndex of selectedClusters) {
            const row = clusterRows[clusterIndex];
            if (!row) continue;
            const clusterName = row.querySelector('.cluster-name')?.value.trim() || `Cụm ${clusterIndex + 1}`;
            const stationCodes = [...row.querySelectorAll('.station-checkbox:checked')].map(item => item.value);
            for (const stationCode of stationCodes) {
                if (stationOwner.has(stationCode)) {
                    throw new Error(
                        `Không thể chạy song song “${stationOwner.get(stationCode)}” và “${clusterName}”: trùng trạm ${stationCode}.`
                    );
                }
                stationOwner.set(stationCode, clusterName);
            }
        }

        return {
            enabled: true,
            interval_hours: interval,
            start_hour: startHour,
            scheduled_hours: scheduledHours,
            selected_clusters: selectedClusters
        };
    }
}
window.applyAdminFeature(AdminAutoAdjustmentFeature);
})();
