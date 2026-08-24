/* Shared in-memory Incident store. Deliberately excludes PII and localStorage. */
(() => {
    const items = new Map();
    let revision = 0;
    let selectedId = null;

    const safeCase = (raw) => {
        if (!raw || raw.id == null) return null;
        return {
            id: Number(raw.id),
            reference: String(raw.reference || ''),
            source_kind: String(raw.source_kind || 'UNKNOWN'),
            source_id: Number(raw.source_id || 0) || null,
            project_id: Number.isFinite(Number(raw.project_id)) ? Number(raw.project_id) : null,
            station_id: Number.isFinite(Number(raw.station_id)) ? Number(raw.station_id) : null,
            title: String(raw.title || 'Sự cố'),
            summary: String(raw.summary || ''),
            source_severity: String(raw.source_severity || 'UNKNOWN'),
            signal_state: String(raw.signal_state || 'UNKNOWN'),
            priority: String(raw.priority || 'UNTRIAGED'),
            status: String(raw.status || 'new'),
            assigned_to_user_id: Number.isFinite(Number(raw.assigned_to_user_id)) ? Number(raw.assigned_to_user_id) : null,
            assigned_to_username: raw.assigned_to_username ? String(raw.assigned_to_username) : null,
            opened_at: Number(raw.opened_at || 0),
            last_signal_at: Number(raw.last_signal_at || 0),
            acknowledged_at: Number(raw.acknowledged_at || 0) || null,
            resolved_at: Number(raw.resolved_at || 0) || null,
            updated_at: Number(raw.updated_at || 0),
            version: Number(raw.version || 1),
            revision: Number(raw.revision || 1),
            last_event_sequence: Number(raw.last_event_sequence || 0),
        };
    };

    const notify = (type, detail = {}) => {
        revision += 1;
        window.dispatchEvent(new CustomEvent(type, { detail: { ...detail, revision } }));
        window.dispatchEvent(new CustomEvent('incidentStoreChanged', { detail: { ...detail, revision } }));
    };

    const store = {
        hydrate(payload) {
            const rows = Array.isArray(payload?.items) ? payload.items : [];
            rows.map(safeCase).filter(Boolean).forEach(row => items.set(row.id, row));
            notify('incidentStoreHydrated', { total: Number(payload?.total || rows.length), snapshot_event_id: payload?.snapshot_event_id || 0 });
            return this.list();
        },
        applyEnvelope(message) {
            const next = safeCase(message?.summary || message?.case);
            if (!next) return null;
            items.set(next.id, next);
            notify('incidentChanged', { incident: next, envelope: { ...message, summary: undefined } });
            return next;
        },
        upsert(raw) {
            const next = safeCase(raw);
            if (!next) return null;
            items.set(next.id, next);
            notify('incidentChanged', { incident: next });
            return next;
        },
        get(id) { return items.get(Number(id)) || null; },
        list() { return Array.from(items.values()).sort((a, b) => (b.updated_at - a.updated_at) || (b.id - a.id)); },
        clear() { items.clear(); selectedId = null; notify('incidentStoreCleared'); },
        select(id) { selectedId = id == null ? null : Number(id); notify('incidentSelectionChanged', { incident: this.get(selectedId) }); },
        get selectedId() { return selectedId; },
        get revision() { return revision; },
    };
    window.incidentStore = store;
})();
