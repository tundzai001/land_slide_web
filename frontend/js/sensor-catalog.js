window.sensorTypes = () => (window.SensorCatalog || [
    {key: 'gnss'}, {key: 'rain'}, {key: 'water'}, {key: 'imu'}
]).map(sensor => sensor.key);
window.filterSensorCatalog = function(query = '') {
    const normalized = query.toLocaleLowerCase('vi');
    document.querySelectorAll('[data-sensor-choice]').forEach(row => {
        row.hidden = !row.textContent.toLocaleLowerCase('vi').includes(normalized);
    });
};
window.selectSensorGroup = function(group) {
    (window.SensorCatalog || []).forEach(sensor => {
        if (group !== 'all' && sensor.group !== group) return;
        const checkbox = document.getElementById(`edit-${sensor.key}`);
        if (checkbox) { checkbox.checked = true; checkbox.dispatchEvent(new Event('change', {bubbles: true})); }
    });
};

window.mountCustomSensorPreset = function(sensor) {
    if (!sensor || !/^custom_[0-9a-f]{12}$/.test(sensor.key) || typeof sensor.label !== 'string' || typeof sensor.note !== 'string') return;
    window.SensorCatalog ||= [];
    if (!window.SensorCatalog.some(item => item.key === sensor.key)) window.SensorCatalog.push(sensor);
    const grid = document.querySelector('.monitoring-picker-grid');
    if (!grid || document.getElementById(`edit-${sensor.key}`)) return;
    const choice = document.createElement('label');
    choice.className = 'monitoring-choice';
    choice.dataset.sensorChoice = '';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.id = `edit-${sensor.key}`;
    const copy = document.createElement('span');
    copy.className = 'monitoring-choice-copy';
    const title = document.createElement('strong');
    title.textContent = sensor.label;
    const description = document.createElement('small');
    description.textContent = sensor.note;
    copy.append(title, description);
    const check = document.createElement('span');
    check.className = 'monitoring-choice-check';
    check.setAttribute('aria-hidden', 'true');
    check.innerHTML = '<i class="bi bi-check2"></i>';
    choice.append(input, copy, check);
    grid.append(choice);
    const heading = document.querySelector('.station-connection-heading');
    if (heading && window.monitoringSensorSection) heading.insertAdjacentHTML('afterend', window.monitoringSensorSection(sensor));
    input.addEventListener('change', () => window.adminManager?.syncMqttSectionsForStep?.());
    window.adminManager?.bindMqttTopicValidation?.();
};

window.loadCustomSensorPresets = async function(token) {
    try {
        const response = await fetch('/api/admin/sensor-presets', {headers: {'Authorization': `Bearer ${token}`}});
        if (!response.ok) throw new Error('Không tải được danh sách cảm biến đã lưu.');
        const sensors = await response.json();
        sensors.forEach(window.mountCustomSensorPreset);
        const addButton = document.getElementById('btn-add-custom-sensor');
        if (addButton) addButton.hidden = window.adminManager?.currentUserRole !== 'admin';
        return true;
    } catch (error) {
        const feedback = document.getElementById('custom-sensor-feedback');
        if (feedback) feedback.textContent = error.message;
        return false;
    }
};

window.toggleCustomSensorForm = function() {
    const form = document.getElementById('custom-sensor-form');
    if (!form) return;
    form.hidden = !form.hidden;
    if (!form.hidden) document.getElementById('custom-sensor-name')?.focus();
};

function _validateCustomSensorInputs(name, description, feedback) {
    if (!name || !description) {
        if (feedback) feedback.textContent = 'Nhập tên và mô tả cảm biến.';
        document.getElementById(!name ? 'custom-sensor-name' : 'custom-sensor-description')?.focus();
        return false;
    }
    return true;
}

function _onCustomSensorCreated(sensor, feedback) {
    window.mountCustomSensorPreset(sensor);
    const checkbox = document.getElementById(`edit-${sensor.key}`);
    if (checkbox) {
        checkbox.checked = true;
        checkbox.dispatchEvent(new Event('change', { bubbles: true }));
    }
    for (const id of ['custom-sensor-name', 'custom-sensor-description', 'custom-sensor-unit']) {
        const input = document.getElementById(id);
        if (input) input.value = '';
    }
    const form = document.getElementById('custom-sensor-form');
    if (form) form.hidden = true;
    if (feedback) feedback.textContent = '';
}

window.createCustomSensorPreset = async function() {
    const name = document.getElementById('custom-sensor-name')?.value.trim() || '';
    const description = document.getElementById('custom-sensor-description')?.value.trim() || '';
    const unit = document.getElementById('custom-sensor-unit')?.value.trim() || '';
    const feedback = document.getElementById('custom-sensor-feedback');
    const button = document.getElementById('btn-save-custom-sensor');
    if (!_validateCustomSensorInputs(name, description, feedback)) return;

    if (button) button.disabled = true;
    if (feedback) feedback.textContent = 'Đang lưu cảm biến…';
    try {
        const response = await fetch('/api/admin/sensor-presets', {
            method: 'POST',
            headers: {'Authorization': `Bearer ${window.adminManager?.token}`, 'Content-Type': 'application/json'},
            body: JSON.stringify({name, description, unit})
        });
        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            throw new Error(typeof body.detail === 'string' ? body.detail : 'Không lưu được cảm biến.');
        }
        const sensor = await response.json();
        _onCustomSensorCreated(sensor, feedback);
    } catch (error) {
        if (feedback) feedback.textContent = error.message;
    } finally {
        if (button) button.disabled = false;
    }
};
