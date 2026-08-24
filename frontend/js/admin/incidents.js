/* Management incident inbox, kept additive so Rescue tab/API remain compatible. */
(() => {
    let busy = false;
    let pollTimer = null;
    const active = () => document.documentElement.dataset.appView === 'admin' && window.authManager?.isAuthenticated?.() && ['admin', 'operator', 'viewer'].includes(window.authManager.getUserInfo?.()?.role);
    const node = (tag, value, cls = '') => { const el = document.createElement(tag); if (cls) el.className = cls; el.textContent = value; return el; };
    function mount() {
        let root = document.getElementById('admin-incident-inbox'); if (root) return root;
        root = document.createElement('section'); root.id = 'admin-incident-inbox'; root.className = 'admin-incident-inbox'; root.setAttribute('data-private-content', 'true'); root.setAttribute('aria-labelledby', 'admin-incident-title');
        const head = document.createElement('div'); head.className = 'admin-incident-inbox__head'; const title = node('h2', 'Sự cố cần xử lý'); title.id = 'admin-incident-title'; head.append(node('div', 'Operations', 'eyebrow'), title); const reload = node('button', 'Tải lại', 'btn btn-sm btn-outline-secondary'); reload.type = 'button'; reload.addEventListener('click', () => window.loadAdminIncidents?.(true)); head.appendChild(reload);
        const meta = node('p', 'Đang đồng bộ…', 'admin-incident-inbox__meta'); meta.id = 'admin-incident-meta'; const list = document.createElement('div'); list.id = 'admin-incident-list'; list.className = 'admin-incident-inbox__list'; root.append(head, meta, list);
        const host = document.getElementById('tab-projects') || document.getElementById('admin-tab-content') || document.body; host.prepend(root); return root;
    }
    function render() {
        const root = mount(); root.hidden = !active(); if (root.hidden) return;
        const list = root.querySelector('#admin-incident-list'); list.replaceChildren();
        const rows = (window.incidentStore?.list?.() || []).filter(row => !['resolved', 'dismissed'].includes(row.status)).slice(0, 12);
        root.querySelector('#admin-incident-meta').textContent = rows.length ? `${rows.length} sự cố đang mở · realtime ${document.documentElement.dataset.incidentsRealtime || 'đang chờ'}` : 'Không có sự cố đang mở';
        rows.forEach(row => {
            const item = document.createElement('article'); item.className = 'admin-incident-item'; item.dataset.incidentId = row.id;
            const title = node('strong', `${row.reference || `INC-${row.id}`} · ${row.title}`); const detail = node('p', `${row.status} · ${row.priority} · ${row.summary || 'Không có mô tả'}`); item.append(title, detail);
            if (row.status === 'new' && ['admin', 'operator'].includes(window.authManager.getUserInfo()?.role)) { const button = node('button', 'Tiếp nhận', 'btn btn-sm btn-primary'); button.type = 'button'; button.addEventListener('click', () => acknowledge(row, button)); item.appendChild(button); }
            list.appendChild(item);
        });
    }
    async function acknowledge(row, button) {
        button.disabled = true;
        try { const response = await window.authManager.apiFetch(`/api/incidents/${row.id}/acknowledge`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': `admin-${row.id}-${crypto.randomUUID?.() || Date.now()}` }, body: JSON.stringify({ expected_version: row.version, assign_to_self: true }) }); if (!response?.ok) throw new Error(response.status); window.incidentStore?.upsert((await response.json()).case); render(); }
        catch (_) { button.disabled = false; button.textContent = 'Thử lại'; }
    }
    window.loadAdminIncidents = async function loadAdminIncidents(force = false) {
        if (!active() || busy) return; const root = mount(); root.hidden = false; if (!force && window.incidentStore?.revision > 0) return render(); busy = true;
        try { const response = await window.authManager.apiFetch('/api/incidents?limit=50&sort=-updated_at', { cache: 'no-store' }); if (!response?.ok) throw new Error(response.status); window.incidentStore?.hydrate(await response.json()); }
        catch (_) { root.querySelector('#admin-incident-meta').textContent = 'Không thể đồng bộ · thử lại'; }
        finally { busy = false; render(); }
    };
    function ensurePolling() {
        if (pollTimer || !active()) return;
        pollTimer = setInterval(() => {
            if (active() && document.documentElement.dataset.incidentsRealtime !== 'connected') window.loadAdminIncidents?.(true);
        }, 15000);
    }
    window.addEventListener('incidentStoreChanged', render); window.addEventListener('incidentChanged', render); window.addEventListener('auth:ready', () => { ensurePolling(); window.loadAdminIncidents?.(); });
    window.addEventListener('authzExpired', () => { if (pollTimer) clearInterval(pollTimer); pollTimer = null; });
    setTimeout(() => { ensurePolling(); window.loadAdminIncidents?.(); }, 0);
})();
