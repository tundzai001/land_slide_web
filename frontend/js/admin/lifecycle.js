(() => {
class AdminLifecycleFeature extends window.AdminManager {
    logout() {
        console.log('[SPA-NAV] admin logout redirect landing', {
            path: window.location.pathname,
            search: window.location.search,
        });
        window.SPA_SUPPRESS_AUTO_MAP_ON_LANDING = true;
        if (window.authManager?.logout) {
            window.authManager.logout(true);
            return;
        }
        window.authSession?.clearToken();
        window.location.href = '/';
    }

    dispose() {
        if (this._disposed) return;
        this.closeOperationInspector?.();
        this._disposed = true;
        this._refreshIntervals.forEach(clearInterval);
        this._refreshIntervals = [];
        if (this._wsReconnectTimer) clearTimeout(this._wsReconnectTimer);
        this._wsReconnectTimer = null;
        if (this._operationsWsReconnectTimer) clearTimeout(this._operationsWsReconnectTimer);
        this._operationsWsReconnectTimer = null;
        if (this.ws) {
            const socket = this.ws;
            this.ws = null;
            socket.onclose = null;
            socket.close();
        }
        if (this.operationsWs) {
            const socket = this.operationsWs;
            this.operationsWs = null;
            socket.onclose = null;
            socket.close();
        }
        window.removeEventListener('authzChanged', this._authzChangeHandler);
        window.removeEventListener('authzExpired', this._authzExpiredHandler);
        window.removeEventListener('popstate', this._popstateHandler);
        this._tabRequestControllers?.forEach?.(controller => controller.abort());
        this._tabRequestControllers?.clear?.();
        window.dbManager?.datasetRequestController?.abort?.();
        window.removeEventListener('spa:navigate', this._spaNavigateHandler);
    }

    toggleVn2000AdvancedSlide(animate = true) {
        const checkbox = document.getElementById('vn2000-enabled');
        const content = document.getElementById('vn2000-advanced-content');
        if (!checkbox || !content) return;

        if (checkbox.checked) {
            content.style.display = 'block';
            content.style.maxHeight = animate ? '0px' : 'none';
            if (animate) {
                setTimeout(() => {
                    content.style.maxHeight = '1000px';
                }, 10);
            }
        } else {
            if (animate) {
                content.style.maxHeight = '0px';
                setTimeout(() => {
                    content.style.display = 'none';
                }, 300);
            } else {
                content.style.display = 'none';
            }
        }
    }

    toggleRtkForwardingSlide(animate = true) {
        const checkbox = document.getElementById('cfg-fwd-enabled');
        const content = document.getElementById('rtk-forwarding-content');
        if (!checkbox || !content) return;

        if (checkbox.checked) {
            content.style.display = 'block';
            content.style.maxHeight = animate ? '0px' : 'none';
            if (animate) {
                setTimeout(() => {
                    content.style.maxHeight = '2000px';
                }, 10);
            }
        } else {
            if (animate) {
                content.style.maxHeight = '0px';
                setTimeout(() => {
                    content.style.display = 'none';
                }, 300);
            } else {
                content.style.display = 'none';
            }
        }
    }
}
window.applyAdminFeature(AdminLifecycleFeature);
})();
