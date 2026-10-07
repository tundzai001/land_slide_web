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
