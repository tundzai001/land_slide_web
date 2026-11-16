(() => {
class AdminVelocityFeature extends window.AdminManager {
    // VELOCITY CONFIG MODAL
    // =========================================================================

    openVelocityModal() {
        console.log('📊 [VELOCITY] Opening modal...');
        this.renderVelocityTable();
        if (this.velocityModal) this.velocityModal.show();
    }

    closeVelocityModal() {
        if (this.velocityModal) this.velocityModal.hide();
    }

    renderVelocityTable() {
        const tbody = document.getElementById('velocity-table-body');
        if (!tbody) return;

        this.refreshVelocityDescriptions();

        const unitOptions = [
            'mm/s', 'mm/day', 'mm/month', 'mm/year',
            'cm/day', 'cm/year',
            'm/s', 'm/min', 'm/hr', 'm/day', 'm/month', 'm/year'
        ];

        tbody.innerHTML = this.velocityConfig.map((vel, index) => {
            const unitSelectHtml = unitOptions.map(u =>
                `<option value="${u}"${u === vel.unit ? ' selected' : ''}>${u}</option>`
            ).join('');

            const thresholdHtml = vel.editable
                ? `<div class="input-group input-group-sm">
                            <input type="number"
                                   class="form-control"
                                   value="${vel.threshold}"
                                   step="0.00001"
                                   data-index="${index}"
                                   onchange="window.adminManager.updateVelocityThreshold(${index}, this.value)">
                            <select class="form-select form-select-sm" style="max-width:110px;"
                                    onchange="window.adminManager.updateVelocityUnit(${index}, this.value)">
                                ${unitSelectHtml}
                            </select>
                        </div>`
                : `<code>${vel.threshold} ${vel.unit}</code>`;

            return `
            <tr>
                <td><strong>${vel.name}</strong></td>
                <td>${thresholdHtml}</td>
                <td class="text-muted small">${vel.description}</td>
            </tr>`;
        }).join('');
    }

    updateVelocityThreshold(index, newValue) {
        const value = Number.parseFloat(String(newValue).replace(',', '.'));
        if (!Number.isNaN(value)) {
            this.velocityConfig[index].threshold = value;
            this.renderVelocityTable();
        }
    }

    updateVelocityUnit(index, newUnit) {
        if (newUnit && this.velocityConfig[index]) {
            this.velocityConfig[index].unit = newUnit;
            this.renderVelocityTable();
        }
    }

    formatVelocityThreshold(value) {
        const num = Number(value);
        if (!Number.isFinite(num)) return '--';
        if (Math.abs(num) >= 1000) return num.toFixed(0);
        if (Math.abs(num) >= 10) return String(Number(num.toFixed(2)));
        if (Math.abs(num) >= 1) return String(Number(num.toFixed(3)));
        return String(Number(num.toFixed(6)));
    }

    refreshVelocityDescriptions() {
        if (!Array.isArray(this.velocityConfig) || this.velocityConfig.length === 0) return;

        const n = this.velocityConfig.length;
        for (let i = 0; i < n; i++) {
            const curr = this.velocityConfig[i] || {};
            const next = this.velocityConfig[i + 1] || null;

            const currVal = this.formatVelocityThreshold(curr.threshold);
            const currUnit = curr.unit || 'mm/s';

            if (i === 0 && next) {
                const nextVal = this.formatVelocityThreshold(next.threshold);
                const nextUnit = next.unit || currUnit;
                curr.description = `< ${nextVal} ${nextUnit}`;
            } else if (i === n - 1) {
                curr.description = `> ${currVal} ${currUnit}`;
            } else if (next) {
                const nextVal = this.formatVelocityThreshold(next.threshold);
                const nextUnit = next.unit || currUnit;
                curr.description = `${currVal} ${currUnit} to ${nextVal} ${nextUnit}`;
            }
        }
    }

    applyVelocityConfig() {

        console.log('✅ [VELOCITY] Applied config:', this.velocityConfig);

        // Thông báo cho người dùng biết
        window.toast?.success('✅ Đã áp dụng bảng vận tốc. Hãy bấm "Lưu cấu hình" để lưu trạm.');

        // Đóng modal
        this.closeVelocityModal();
    }

    resetVelocityConfig() {
        // Khôi phục về mặc định Cruden & Varnes nếu cần
        this.velocityConfig = [
            { name: 'Extremely slow', threshold: 0, unit: 'mm/year', description: '< 16 mm/year', editable: true },
            { name: 'Very slow', threshold: 16, unit: 'mm/year', description: '16 mm/year to 1.6 m/year', editable: true },
            { name: 'Slow', threshold: 1.6, unit: 'm/year', description: '1.6 m/year to 13 mm/month', editable: true },
            { name: 'Moderate', threshold: 13, unit: 'm/month', description: '13 mm/month to 1.8 m/hour', editable: true },
            { name: 'Rapid', threshold: 1.8, unit: 'm/hr', description: '1.8 m/hour to 3 m/min', editable: true },
            { name: 'Very rapid', threshold: 3, unit: 'm/min', description: '3 m/min to 5 m/s', editable: true },
            { name: 'Extremely rapid', threshold: 5, unit: 'm/s', description: '> 5 m/s', editable: true }
        ];
        this.renderVelocityTable();
        window.toast?.info('Đã khôi phục cấu hình vận tốc mặc định');
    }


}
window.applyAdminFeature(AdminVelocityFeature);
})();
