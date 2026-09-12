/* Map operations inbox: a small progressive-enhancement client for durable Incidents. */
(() => {
    const statusLabel = { new: 'Mới', acknowledged: 'Đã tiếp nhận', in_progress: 'Đang xử lý', monitoring: 'Theo dõi', resolved: 'Đã giải quyết', dismissed: 'Đã loại' };
    const priorityLabel = { URGENT: 'Khẩn', HIGH: 'Cao', NORMAL: 'Bình thường', LOW: 'Thấp', UNTRIAGED: 'Chưa phân loại' };
    let loading = false;
    let renderedRevision = -1;
    let pollTimer = null;
    const allowed = () => document.documentElement.dataset.appView === 'map' && window.authManager?.isAuthenticated?.() && ['admin', 'operator', 'viewer'].includes(window.authManager.getUserInfo?.()?.role);
    function text(tag, value, className = '') { const node = document.createElement(tag); if (className) node.className = className; node.textContent = value; return node; }
    function ensureIncidentInbox() {
        let root = document.getElementById('incident-inbox');
        if (root) return root;
        root = document.createElement('aside'); root.id = 'incident-inbox'; root.className = 'incident-inbox'; root.setAttribute('aria-label', 'Hộp sự cố vận hành'); root.setAttribute('data-private-content', 'true');
        root.innerHTML = '<div class="incident-inbox__head"><div><span class="eyebrow">Operations</span><h2>Sự cố</h2></div><button type="button" class="icon-btn" data-incident-close aria-label="Đóng hộp sự cố">×</button></div><div class="incident-inbox__meta"><span data-incident-connection>Đang tải…</span><button type="button" class="text-btn" data-incident-reload>Tải lại</button></div><div class="incident-inbox__list" data-incident-list></div>';
        const host = document.getElementById('app-root') || document.body;
        host.appendChild(root);
        let toggle = document.getElementById('incident-toggle');
        if (!toggle) { toggle = text('button', 'Sự cố', 'incident-toggle'); toggle.id = 'incident-toggle'; toggle.type = 'button'; toggle.setAttribute('aria-controls', 'incident-inbox'); host.appendChild(toggle); }
        toggle.setAttribute('aria-expanded', 'false');
        toggle.addEventListener('click', () => {
            root.classList.toggle('is-open');
            const isOpen = root.classList.contains('is-open');
            toggle.setAttribute('aria-expanded', String(isOpen));
            if (isOpen) { ensureIncidentPolling(); window.loadIncidentInbox?.(); }
            else if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        });
        root.querySelector('[data-incident-close]').addEventListener('click', () => { root.classList.remove('is-open'); toggle.setAttribute('aria-expanded', 'false'); if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } });
        root.querySelector('[data-incident-reload]').addEventListener('click', () => window.loadIncidentInbox?.(true));
        root.addEventListener('click', handleAction);
        return root;
    }
    function renderIncidentInbox() {
        const root = ensureIncidentInbox(); if (!allowed()) { root.hidden = true; return; } root.hidden = false;
        if (renderedRevision === window.incidentStore?.revision) return;
        renderedRevision = window.incidentStore?.revision ?? renderedRevision;
        const list = root.querySelector('[data-incident-list]'); list.replaceChildren();
        const rows = (window.incidentStore?.list?.() || []).filter(row => !['resolved', 'dismissed'].includes(row.status)).slice(0, 8);
        if (!rows.length) { list.appendChild(text('p', 'Chưa có sự cố cần xử lý.', 'incident-inbox__empty')); return; }
        rows.forEach(row => {
            const item = document.createElement('article'); item.className = `incident-item incident-item--${row.priority.toLowerCase()}`; item.dataset.incidentId = String(row.id);
            const head = document.createElement('div'); head.className = 'incident-item__head'; head.append(text('strong', row.reference || `INC-${row.id}`), text('span', priorityLabel[row.priority] || row.priority, 'incident-priority'), text('span', statusLabel[row.status] || row.status, 'incident-status'));
            const title = text('h3', row.title); const summary = text('p', row.summary || 'Không có mô tả chi tiết.');
            const meta = text('div', `${row.source_severity} · cập nhật ${new Date(row.updated_at * 1000).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}`, 'incident-item__meta');
            const actions = document.createElement('div'); actions.className = 'incident-item__actions';
            if (row.status === 'new' && ['admin', 'operator'].includes(window.authManager.getUserInfo()?.role)) { const button = text('button', 'Tiếp nhận', 'btn btn-sm btn-primary'); button.type = 'button'; button.dataset.incidentAction = 'acknowledge'; actions.appendChild(button); }
            item.append(head, title, summary, meta, actions); list.appendChild(item);
        });
    }
    async function handleAction(event) {
        const button = event.target.closest('[data-incident-action]'); if (!button || !allowed()) return;
        const item = button.closest('[data-incident-id]'); const incident = window.incidentStore?.get(item?.dataset.incidentId); if (!incident) return; button.disabled = true;
        try {
            const response = await window.authManager.apiFetch(`/api/incidents/${incident.id}/acknowledge`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': `map-${incident.id}-${crypto.randomUUID?.() || Date.now()}` }, body: JSON.stringify({ expected_version: incident.version, assign_to_self: true }) });
            if (!response?.ok) throw new Error(`HTTP ${response?.status || 0}`); const payload = await response.json(); window.incidentStore?.upsert(payload.case); renderIncidentInbox();
        } catch (error) { button.disabled = false; button.textContent = 'Thử lại'; console.warn('[INCIDENT] Mutation failed:', error); }
    }
    window.loadIncidentInbox = async function loadIncidentInbox(force = false) {
        if (!allowed() || loading) return; const root = ensureIncidentInbox(); root.hidden = false;
        if (!force && window.incidentStore?.revision > 0) { renderIncidentInbox(); return; }
        loading = true; root.querySelector('[data-incident-connection]').textContent = 'Đang đồng bộ…';
        try { const response = await window.authManager.apiFetch('/api/incidents?limit=50&sort=-updated_at', { cache: 'no-store' }); if (!response?.ok) throw new Error(`HTTP ${response?.status || 0}`); window.incidentStore?.hydrate(await response.json()); root.querySelector('[data-incident-connection]').textContent = 'Đã đồng bộ'; }
        catch (error) { root.querySelector('[data-incident-connection]').textContent = 'Mất kết nối · thử lại'; }
        finally { loading = false; renderIncidentInbox(); }
    };
    function ensureIncidentPolling() {
        if (pollTimer || !allowed()) return;
        pollTimer = setInterval(() => {
            if (allowed() && document.documentElement.dataset.incidentsRealtime !== 'connected') window.loadIncidentInbox?.(true);
        }, 15000);
    }
    window.addEventListener('incidentStoreChanged', renderIncidentInbox); window.addEventListener('incidentChanged', renderIncidentInbox);
    window.addEventListener('auth:ready', () => { if (allowed()) ensureIncidentInbox(); });
    window.addEventListener('authzExpired', () => { if (pollTimer) clearInterval(pollTimer); pollTimer = null; const root = document.getElementById('incident-inbox'); if (root) root.hidden = true; });
    setTimeout(() => { if (allowed()) ensureIncidentInbox(); }, 0);
})();
