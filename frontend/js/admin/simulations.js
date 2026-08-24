(() => {
class AdminSimulationFeature extends window.AdminManager {
    _simulationActive() {
        return document.documentElement.dataset.appView === 'admin'
            && this.currentTabId === 'tab-simulations'
            && this.hasPermission?.('MANAGE_SIMULATIONS');
    }

    async loadSimulationRuns(force = false) {
        if (!this.hasPermission?.('MANAGE_SIMULATIONS')) return;
        if (!this._simulationActive() && !force) return;
        const list = document.getElementById('simulation-audit-list');
        const meta = document.getElementById('simulation-audit-meta');
        if (!list) return;
        if (!force && this._simulationRows) {
            this.renderSimulationRuns(this._simulationRows);
            return;
        }
        list.replaceChildren(this._simulationNode('div', 'Đang tải nhật ký mô phỏng…', 'ops-loading'));
        try {
            const response = await window.authManager.apiFetch('/api/simulations/runs?limit=50', { cache: 'no-store' });
            if (!response?.ok) throw new Error(`HTTP ${response?.status || 0}`);
            this._simulationRows = await response.json();
            this.renderSimulationRuns(this._simulationRows);
        } catch (error) {
            meta && (meta.textContent = 'Không thể đồng bộ nhật ký');
            list.replaceChildren(this._simulationNode('div', `Không tải được nhật ký · ${error.message}`, 'ops-empty is-error'));
        }
    }

    _simulationNode(tag, text, className = '') {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text != null) element.textContent = text;
        return element;
    }

    renderSimulationRuns(rows) {
        const list = document.getElementById('simulation-audit-list');
        const meta = document.getElementById('simulation-audit-meta');
        if (!list) return;
        list.replaceChildren();
        const safeRows = Array.isArray(rows) ? rows : [];
        if (meta) meta.textContent = `${safeRows.length} lần chạy gần nhất · dữ liệu audit bất biến`;
        if (!safeRows.length) {
            list.appendChild(this._simulationNode('div', 'Chưa có lần mô phỏng nào.', 'ops-empty'));
            return;
        }
        safeRows.forEach(run => {
            const card = this._simulationNode('article', null, 'simulation-audit-card');
            const header = this._simulationNode('div', null, 'simulation-audit-card__header');
            const title = this._simulationNode('strong', run.display_name || `Mô phỏng #${run.id}`);
            const status = this._simulationNode('span', `${run.status || 'unknown'} · ${Number(run.progress || 0)}%`, `management-status is-${run.status === 'completed' ? 'success' : run.status === 'failed' || run.status === 'interrupted' ? 'offline' : 'warning'}`);
            header.append(title, status);
            const facts = this._simulationNode('div', null, 'simulation-audit-card__facts');
            facts.append(
                this._simulationNode('span', `${run.mode || 'manual'} · seed ${run.seed ?? '--'}`),
                this._simulationNode('span', run.station_name || run.project_name || 'Kịch bản thủ công'),
                this._simulationNode('span', run.created_at ? new Date(Number(run.created_at) * 1000).toLocaleString('vi-VN') : '--'),
            );
            const actions = this._simulationNode('div', null, 'simulation-audit-card__actions');
            if (['queued', 'running'].includes(run.status)) {
                const stop = this._simulationNode('button', 'Dừng', 'btn btn-sm btn-outline-danger');
                stop.type = 'button'; stop.addEventListener('click', () => this.stopSimulationRun(run.id, stop)); actions.appendChild(stop);
            }
            const rerun = this._simulationNode('button', 'Chạy lại', 'btn btn-sm btn-outline-primary');
            rerun.type = 'button'; rerun.addEventListener('click', () => this.rerunSimulation(run.id, rerun)); actions.appendChild(rerun);
            const exportButton = this._simulationNode('button', 'Xuất bundle', 'btn btn-sm btn-primary');
            exportButton.type = 'button'; exportButton.addEventListener('click', () => this.exportSimulation(run.id, exportButton)); actions.appendChild(exportButton);
            card.append(header, facts, actions);
            list.appendChild(card);
        });
    }

    async stopSimulationRun(id, button) {
        if (!this.hasPermission('MANAGE_SIMULATIONS')) return;
        button.disabled = true;
        try {
            const response = await window.authManager.apiFetch(`/api/simulations/runs/${id}/stop`, { method: 'POST' });
            if (!response?.ok) throw new Error(`HTTP ${response?.status || 0}`);
            await this.loadSimulationRuns(true);
        } catch (error) { window.toast?.error?.(`Không dừng được mô phỏng: ${error.message}`); button.disabled = false; }
    }

    async rerunSimulation(id, button) {
        if (!this.hasPermission('MANAGE_SIMULATIONS')) return;
        button.disabled = true;
        try {
            const response = await window.authManager.apiFetch(`/api/simulations/runs/${id}/rerun`, { method: 'POST' });
            if (!response?.ok) throw new Error(`HTTP ${response?.status || 0}`);
            await this.loadSimulationRuns(true);
        } catch (error) { window.toast?.error?.(`Không chạy lại được: ${error.message}`); button.disabled = false; }
    }

    async exportSimulation(id, button) {
        if (!this.hasPermission('MANAGE_SIMULATIONS')) return;
        button.disabled = true;
        try {
            const response = await window.authManager.apiFetch(`/api/simulations/runs/${id}/bundle`, { cache: 'no-store' });
            if (!response?.ok) throw new Error(`HTTP ${response?.status || 0}`);
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement('a');
            anchor.href = url;
            anchor.download = `simulation_${id}.zip`;
            anchor.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        }
        catch (error) { window.toast?.error?.(`Không xuất được bundle: ${error.message}`); }
        finally { button.disabled = false; }
    }
}
window.applyAdminFeature(AdminSimulationFeature);
})();
