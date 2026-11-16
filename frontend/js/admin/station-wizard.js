(() => {
class AdminStationWizardFeature extends window.AdminManager {
    // =========================================================================
    // STATION WIZARD
    // =========================================================================

    bindMqttTopicValidation() {
        (window.sensorTypes?.() || ['gnss', 'rain', 'water', 'imu']).forEach(type => {
            const input = document.getElementById(`topic-${type}`);
            if (!input || input.dataset.topicValidationBound === 'true') return;
            input.dataset.topicValidationBound = 'true';
            input.setAttribute('autocomplete', 'off');
            input.addEventListener('input', () => {
                this.validateMqttTopicsLocally();
                clearTimeout(input._topicValidationTimer);
                input._topicValidationTimer = setTimeout(() => this.validateMqttTopicInput(input), 250);
            });
            input.addEventListener('blur', () => this.validateMqttTopicInput(input));
        });
    }

    getActiveMqttTopicInputs() {
        return (window.sensorTypes?.() || ['gnss', 'rain', 'water', 'imu'])
            .filter(type => document.getElementById(`edit-${type}`)?.checked)
            .map(type => document.getElementById(`topic-${type}`))
            .filter(Boolean);
    }

    setMqttTopicState(input, state, message = '') {
        let feedback = input.parentElement?.querySelector('.mqtt-topic-feedback');
        if (!feedback) {
            feedback = document.createElement('div');
            feedback.className = 'mqtt-topic-feedback';
            input.after(feedback);
        }
        input.classList.toggle('is-invalid', state === 'invalid');
        input.classList.toggle('is-valid', state === 'valid');
        input.classList.toggle('is-validating', state === 'validating');
        let topicValid = '';
        if (state === 'valid') topicValid = 'true';
        else if (state === 'invalid') topicValid = 'false';
        input.dataset.topicValid = topicValid;
        feedback.className = `mqtt-topic-feedback ${state}`;
        feedback.setAttribute('role', state === 'invalid' ? 'alert' : 'status');
        feedback.setAttribute('aria-live', 'polite');
        feedback.textContent = message;
    }

    validateMqttTopicsLocally() {
        const inputs = this.getActiveMqttTopicInputs();
        const counts = new Map();
        inputs.forEach(input => {
            const topic = input.value.trim();
            if (topic) counts.set(topic, (counts.get(topic) || 0) + 1);
        });
        let valid = true;
        inputs.forEach(input => {
            const topic = input.value.trim();
            if (topic && counts.get(topic) > 1) {
                this.setMqttTopicState(input, 'invalid', 'Topic này đang bị trùng trong biểu mẫu.');
                valid = false;
            } else if (!topic) {
                this.setMqttTopicState(input, 'idle', '');
            } else if (input.classList.contains('is-invalid')) {
                this.setMqttTopicState(input, 'idle', '');
            }
        });
        return valid;
    }

    async validateMqttTopicInput(input) {
        if (!input || !this.getActiveMqttTopicInputs().includes(input)) return true;
        const topic = input.value.trim();
        if (!topic) {
            this.setMqttTopicState(input, 'invalid', 'Hãy nhập MQTT topic.');
            return false;
        }
        if (!this.validateMqttTopicsLocally() || input.classList.contains('is-invalid')) return false;

        input._topicValidationController?.abort();
        const controller = new AbortController();
        input._topicValidationController = controller;
        this.setMqttTopicState(input, 'validating', 'Đang kiểm tra topic...');
        const params = new URLSearchParams({ topic });
        if (this.currentStationId) params.set('exclude_station_id', this.currentStationId);
        try {
            const res = await fetch(`/api/admin/devices/topic-availability?${params}`, {
                headers: { 'Authorization': `Bearer ${this.token}` },
                signal: controller.signal
            });
            if (!res.ok) throw new Error('Không thể kiểm tra topic');
            const result = await res.json();
            if (input.value.trim() !== topic) return false;
            if (!result.available) {
                const owner = result.conflict?.device_code ? ` (${result.conflict.device_code})` : '';
                this.setMqttTopicState(input, 'invalid', `Topic đã được sử dụng${owner}.`);
                return false;
            }
            this.setMqttTopicState(input, 'valid', 'Topic khả dụng.');
            return true;
        } catch (error) {
            if (error.name === 'AbortError') return false;
            this.setMqttTopicState(input, 'invalid', error.message);
            return false;
        }
    }

    async validateAllMqttTopics() {
        if (!this.validateMqttTopicsLocally()) return false;
        const inputs = this.getActiveMqttTopicInputs();
        const results = await Promise.all(inputs.map(input => this.validateMqttTopicInput(input)));
        const invalidIndex = results.findIndex(result => !result);
        if (invalidIndex >= 0) inputs[invalidIndex]?.focus();
        return invalidIndex < 0;
    }

    _resetModalCustomMqtt() {
        ['host', 'port', 'user', 'pass'].forEach(f => {
            const el = document.getElementById(`station-mqtt-${f}`);
            if (el) el.value = '';
        });
        const tlsEl = document.getElementById('station-mqtt-tls');
        if (tlsEl) tlsEl.checked = false;
    }

    _applyModalOriginCoordinates(location) {
        const latStr = location?.lat != null ? Number(location.lat).toFixed(7) : '';
        const lonStr = location?.lon != null ? Number(location.lon).toFixed(7) : '';
        const hStr = location?.h != null ? Number(location.h).toFixed(2) : '';

        document.getElementById('origin-lat').value = latStr;
        document.getElementById('origin-lon').value = lonStr;
        document.getElementById('origin-h').value = hStr;

        const originStatus = document.getElementById('origin-status');
        if (originStatus) {
            originStatus.textContent = location
                ? `Tọa độ lấy từ mô hình DEM (${location.dem_name || 'DEM'} · ô ${Number(location.grid?.column) + 1}, ${Number(location.grid?.row) + 1})`
                : 'Chưa có tọa độ gốc';
            originStatus.className = location ? 'text-success small' : 'text-muted';
        }
        this.resetGnssCalibrationResult?.();
        this.updateOriginActionButtons(Boolean(latStr && lonStr));

        const nonGnssTypes = (window.sensorTypes?.() || ['rain', 'water', 'imu']).filter(type => type !== 'gnss');
        nonGnssTypes.forEach(s => {
            const lat = document.getElementById(`origin-${s}-lat`);
            const lon = document.getElementById(`origin-${s}-lon`);
            const h = document.getElementById(`origin-${s}-h`);
            if (lat) lat.value = latStr;
            if (lon) lon.value = lonStr;
            if (h) h.value = hStr;
        });

        (window.SensorCatalog || []).forEach(sensor => {
            const lat = document.getElementById(`origin-${sensor.key}-lat`);
            const lon = document.getElementById(`origin-${sensor.key}-lon`);
            const h = document.getElementById(`origin-${sensor.key}-h`);
            if (lat) lat.value = latStr;
            if (lon) lon.value = lonStr;
            if (h) h.value = hStr;
        });
    }

    openAddStationModal(options = {}) {
        this.isEditMode = false;
        this.currentStationId = null;
        this.pendingStationLocation = options.location || null;
        this.currentStationConfig = {};
        this.stationPresetConfirm = null;
        this.currentStep = 1;
        this.resetGnssOriginRelockProgress?.();
        if (this._originResetTimer) {
            clearInterval(this._originResetTimer);
            this._originResetTimer = null;
        }

        document.getElementById('stationConfigForm').reset();
        const demLocation = document.getElementById('station-dem-location');
        if (demLocation) {
            demLocation.hidden = !this.pendingStationLocation;
            demLocation.textContent = this.pendingStationLocation
                ? `Vị trí đã chọn · ${this.pendingStationLocation.dem_name || 'DEM'} · ô ${Number(this.pendingStationLocation.grid?.column) + 1}, ${Number(this.pendingStationLocation.grid?.row) + 1} · cao độ ${Number(this.pendingStationLocation.h).toFixed(1)} m`
                : '';
        }
        const step2Notice = document.getElementById('step2-dem-location-notice');
        if (step2Notice) {
            step2Notice.hidden = !this.pendingStationLocation;
            step2Notice.innerHTML = this.pendingStationLocation
                ? `<i class="bi bi-geo-alt-fill text-primary me-2"></i><strong>Đã điền tọa độ từ điểm chọn trên mô hình DEM</strong>: ${this.pendingStationLocation.dem_name || 'DEM'} · ô ${Number(this.pendingStationLocation.grid?.column) + 1}, ${Number(this.pendingStationLocation.grid?.row) + 1} (Lat: ${Number(this.pendingStationLocation.lat).toFixed(6)}, Lon: ${Number(this.pendingStationLocation.lon).toFixed(6)}, Cao độ: ${Number(this.pendingStationLocation.h).toFixed(1)} m). Bạn có thể kiểm tra hoặc điều chỉnh.`
                : '';
        }
        document.getElementById('edit-station-id').value = '';

        this._resetModalCustomMqtt();
        this._applyModalOriginCoordinates(this.pendingStationLocation);
        document.getElementById('edit-project-id').value = this.currentProjectId;
        const alertingDisabledEl = document.getElementById('station-alerting-disabled');
        if (alertingDisabledEl) alertingDisabledEl.checked = false;
        const offlineDisplayEl = document.getElementById('station-offline-display-enabled');
        if (offlineDisplayEl) offlineDisplayEl.checked = false;
        const processingStorageEl = document.getElementById('cfg-station-processing-storage-enabled');
        if (processingStorageEl) processingStorageEl.checked = true;
        document.getElementById('modal-title').textContent = 'Thêm Trạm Mới';

        (window.sensorTypes?.() || ['gnss', 'rain', 'water', 'imu']).forEach(sensor => {
            const checkbox = document.getElementById(`edit-${sensor}`);
            if (checkbox) checkbox.checked = false;
            const section = document.getElementById(`mqtt-${sensor}-section`);
            if (section) section.style.display = 'none';
        });

        // ✅ Reset offline thresholds về mặc định
        document.getElementById('offline-gnss').value = this.defaultOfflineThresholds.gnss;
        document.getElementById('offline-rain').value = this.defaultOfflineThresholds.rain;
        document.getElementById('offline-water').value = this.defaultOfflineThresholds.water;
        document.getElementById('offline-imu').value = this.defaultOfflineThresholds.imu;

        // ✅ Update displays
        document.getElementById('offline-gnss-display').textContent = this.formatOfflineTime(this.defaultOfflineThresholds.gnss);
        document.getElementById('offline-rain-display').textContent = this.formatOfflineTime(this.defaultOfflineThresholds.rain);
        document.getElementById('offline-water-display').textContent = this.formatOfflineTime(this.defaultOfflineThresholds.water);
        document.getElementById('offline-imu-display').textContent = this.formatOfflineTime(this.defaultOfflineThresholds.imu);

        // Reset confirm steps source indicators cho trạm mới
        const rainConfirmSrc = document.getElementById('cfg-rain-confirm-source');
        const waterConfirmSrc = document.getElementById('cfg-water-confirm-source');
        if (rainConfirmSrc) { rainConfirmSrc.textContent = '⚠ Sẽ dùng giá trị Hệ thống nếu không sửa'; rainConfirmSrc.className = 'text-warning small'; }
        if (waterConfirmSrc) { waterConfirmSrc.textContent = '⚠ Sẽ dùng giá trị Hệ thống nếu không sửa'; waterConfirmSrc.className = 'text-warning small'; }

        // Reset RTK forwarding fields to default (all enabled)
        const fwdToggleIds = ['fwd-toggle-x', 'fwd-toggle-y', 'fwd-toggle-h', 'fwd-toggle-dx', 'fwd-toggle-dy', 'fwd-toggle-dh', 'fwd-toggle-vdx', 'fwd-toggle-vdy', 'fwd-toggle-vdh'];
        fwdToggleIds.forEach(id => { const el = document.getElementById(id); if (el) el.checked = true; });
        const rtkTopicEl = document.getElementById('gnss-rtk-topic');
        if (rtkTopicEl) rtkTopicEl.value = '';
        const aicasterSelect = document.getElementById('cfg-gnss-aicaster-user');
        if (aicasterSelect) {
            aicasterSelect.innerHTML = '<option value="">-- Chọn user AICaster của rover --</option>';
            delete aicasterSelect.dataset.loaded;
        }
        const aicasterStatus = document.getElementById('aicaster-user-status');
        if (aicasterStatus) {
            aicasterStatus.textContent = 'Danh sách lấy trực tiếp bằng GET /usertable; mật khẩu không được đưa ra trình duyệt.';
            aicasterStatus.className = 'd-block text-muted mt-2';
        }
        this.syncForwardingWrapStates();

        document.getElementById('mqtt-empty-state').style.display = 'block';
        this.updateOriginActionButtons(false);

        this.highlightPreset(null);
        this.bindMqttTopicValidation();
        this.updateWizardStep();
        if (this.stationModal) this.stationModal.show();
        window.loadCustomSensorPresets?.(this.token);
    }

    _populateEditStationDevices(devices) {
        const sensorTypes = (window.sensorTypes?.() || ['gnss', 'rain', 'water', 'imu']);
        sensorTypes.forEach(type => {
            const checkbox = document.getElementById(`edit-${type}`);
            const section = document.getElementById(`mqtt-${type}-section`);
            const input = document.getElementById(`topic-${type}`);

            if (checkbox) checkbox.checked = false;
            if (section) section.style.display = 'none';
            if (input) input.value = '';
        });

        if (!Array.isArray(devices)) return;
        const gnssDevice = devices.find(dev => dev.device_type === 'gnss' && dev.is_active !== false)
            || devices.find(dev => dev.device_type === 'gnss');
        devices.forEach(dev => {
            const type = dev.device_type;
            const checkbox = document.getElementById(`edit-${type}`);
            const section = document.getElementById(`mqtt-${type}-section`);
            const input = document.getElementById(`topic-${type}`);

            console.log(`📋 [EDIT] Device ${type}: is_active=${dev.is_active}, topic=${dev.mqtt_topic}`);

            if (checkbox && dev.is_active !== false) {
                checkbox.checked = true;
                if (section) section.style.display = 'block';
                if (input) input.value = dev.mqtt_topic || '';
                
                const devConfig = dev.config || {};
                const mqttCfg = devConfig.mqtt || {};
                
                const hostEl = document.getElementById(`cfg-${type}-mqtt-host`);
                const portEl = document.getElementById(`cfg-${type}-mqtt-port`);
                const tlsEl = document.getElementById(`cfg-${type}-mqtt-tls`);
                const userEl = document.getElementById(`cfg-${type}-mqtt-user`);
                const passEl = document.getElementById(`cfg-${type}-mqtt-pass`);
                
                if (hostEl) hostEl.value = mqttCfg.host || '';
                if (portEl) portEl.value = mqttCfg.port || '';
                if (tlsEl) {
                    tlsEl.checked = !!mqttCfg.use_tls;
                    const wrap = document.getElementById(`wrap-${type}-mqtt-tls`);
                    if (wrap) {
                        wrap.classList.toggle('is-on', tlsEl.checked);
                        wrap.classList.toggle('is-off', !tlsEl.checked);
                    }
                }
                if (userEl) userEl.value = mqttCfg.username || '';
                if (passEl) passEl.value = mqttCfg.password || '';
            } else if (checkbox) {
                checkbox.checked = false;
                if (section) section.style.display = 'none';
            }
        });

        const anyChecked = sensorTypes.some(t => document.getElementById(`edit-${t}`)?.checked);
        const emptyState = document.getElementById('mqtt-empty-state');
        if (emptyState) emptyState.style.display = anyChecked ? 'none' : 'block';
        if (gnssDevice) {
            this.renderGnssTrackingOffset?.(gnssDevice.tracking_offset, {
                state: gnssDevice.tracking_offset == null ? 'Chưa lưu offset' : 'Đang áp dụng',
                source: gnssDevice.tracking_offset == null ? 'Chưa có dữ liệu runtime/DB' : 'Đọc từ runtime/DB',
            });
        }
    }

    _populateEditStationThresholds(cfg) {
        const alertingDisabledEl = document.getElementById('station-alerting-disabled');
        if (alertingDisabledEl) {
            alertingDisabledEl.checked = (cfg.alerting?.enabled === false) || cfg.alerting_enabled === false;
        }
        const offlineDisplayEl = document.getElementById('station-offline-display-enabled');
        if (offlineDisplayEl) {
            offlineDisplayEl.checked = (cfg.offline_display?.enabled === true) || cfg.offline_display_enabled === true;
        }
        const processingStorageEl = document.getElementById('cfg-station-processing-storage-enabled');
        if (processingStorageEl) {
            processingStorageEl.checked = cfg.data_logging?.enabled !== false;
        }
        this.currentStationConfig = cfg;
        const simulationProfile = cfg.simulation_profile || {};
        const simulationFields = {
            'sim-profile-cohesion': ['cohesion_kpa', 15], 'sim-profile-friction': ['friction_angle_deg', 30],
            'sim-profile-unit-weight': ['unit_weight_kn_m3', 18], 'sim-profile-slip-depth': ['slip_depth_m', 5],
            'sim-profile-slope': ['slope_angle_deg', 25], 'sim-profile-ks': ['saturated_conductivity_m_s', 0.000015],
            'sim-profile-porosity': ['porosity', 0.25], 'sim-profile-base-ru': ['base_pore_pressure_ratio', 0],
            'sim-profile-water-dry': ['water_level_dry_m', 0], 'sim-profile-water-saturated': ['water_level_saturated_m', 1],
            'sim-profile-houses': ['house_count', 40], 'sim-profile-trees': ['tree_count', 300],
        };
        Object.entries(simulationFields).forEach(([id, [key, fallback]]) => {
            const input = document.getElementById(id);
            if (input) input.value = simulationProfile[key] ?? fallback;
        });

        const mqttCfg = cfg.mqtt || {};
        const mqttHostEl = document.getElementById('station-mqtt-host');
        if (mqttHostEl) mqttHostEl.value = mqttCfg.host || '';
        const mqttPortEl = document.getElementById('station-mqtt-port');
        if (mqttPortEl) mqttPortEl.value = mqttCfg.port || '';
        const mqttTlsEl = document.getElementById('station-mqtt-tls');
        if (mqttTlsEl) mqttTlsEl.checked = !!mqttCfg.use_tls;
        const mqttUserEl = document.getElementById('station-mqtt-user');
        if (mqttUserEl) mqttUserEl.value = mqttCfg.username || '';
        const mqttPassEl = document.getElementById('station-mqtt-pass');
        if (mqttPassEl) mqttPassEl.value = mqttCfg.password || '';

        const offlineThresholds = cfg.offline_thresholds || {};
        const gnssThreshold = offlineThresholds.gnss ?? this.defaultOfflineThresholds.gnss;
        const rainThreshold = offlineThresholds.rain ?? this.defaultOfflineThresholds.rain;
        const waterThreshold = offlineThresholds.water ?? this.defaultOfflineThresholds.water;
        const imuThreshold = offlineThresholds.imu ?? this.defaultOfflineThresholds.imu;

        document.getElementById('offline-gnss').value = gnssThreshold;
        document.getElementById('offline-rain').value = rainThreshold;
        document.getElementById('offline-water').value = waterThreshold;
        document.getElementById('offline-imu').value = imuThreshold;

        document.getElementById('offline-gnss-display').textContent = this.formatOfflineTime(gnssThreshold);
        document.getElementById('offline-rain-display').textContent = this.formatOfflineTime(rainThreshold);
        document.getElementById('offline-water-display').textContent = this.formatOfflineTime(waterThreshold);
        document.getElementById('offline-imu-display').textContent = this.formatOfflineTime(imuThreshold);

        if (cfg.velocity_classification && Array.isArray(cfg.velocity_classification)) {
            this.velocityConfig = cfg.velocity_classification;
        } else {
            this.velocityConfig = [
                { name: 'Extremely slow', threshold: 0, unit: 'mm/year', description: '< 16 mm/year', editable: true },
                { name: 'Very slow', threshold: 16, unit: 'mm/year', description: '16 mm/year to 1.6 m/year', editable: true },
                { name: 'Slow', threshold: 1.6, unit: 'm/year', description: '1.6 m/year to 13 mm/month', editable: true },
                { name: 'Moderate', threshold: 13, unit: 'm/month', description: '13 mm/month to 1.8 m/hour', editable: true },
                { name: 'Rapid', threshold: 1.8, unit: 'm/hr', description: '1.8 m/hour to 3 m/min', editable: true },
                { name: 'Very rapid', threshold: 3, unit: 'm/min', description: '3 m/min to 5 m/s', editable: true },
                { name: 'Extremely rapid', threshold: 5, unit: 'm/s', description: '> 5 m/s', editable: true }
            ];
        }

        const waterCfg = cfg.Water || {};
        document.getElementById('cfg-water-warning').value = waterCfg.warning_threshold ?? 0.15;
        document.getElementById('cfg-water-critical').value = waterCfg.critical_threshold ?? 0.30;

        const waterWarningConfirmEl = document.getElementById('cfg-water-warning-confirm');
        const waterCriticalConfirmEl = document.getElementById('cfg-water-critical-confirm');
        const waterConfirmSrc = document.getElementById('cfg-water-confirm-source');
        if (waterWarningConfirmEl) {
            const wcs = waterCfg.water_warning_confirm_steps ?? waterCfg.water_confirm_steps;
            waterWarningConfirmEl.value = wcs ?? 3;
            if (waterConfirmSrc) {
                waterConfirmSrc.textContent = wcs != null ? '✅ Đã lưu riêng cho trạm' : '⚠ Sẽ dùng giá trị Hệ thống';
                waterConfirmSrc.className = wcs != null ? 'text-success small' : 'text-warning small';
            }
        }
        if (waterCriticalConfirmEl) {
            const wccs = waterCfg.water_critical_confirm_steps ?? waterCfg.water_confirm_steps;
            waterCriticalConfirmEl.value = wccs ?? 2;
        }
        const waterSafeConfirmEl = document.getElementById('cfg-water-safe-confirm');
        const waterSafeConfirmSrc = document.getElementById('cfg-water-safe-confirm-source');
        if (waterSafeConfirmEl) {
            const wscs = waterCfg.water_safe_confirm_steps;
            waterSafeConfirmEl.value = wscs ?? 3;
            if (waterSafeConfirmSrc) {
                waterSafeConfirmSrc.textContent = wscs != null ? '✅ Đã lưu riêng cho trạm' : '⚠ Sẽ dùng giá trị Hệ thống';
                waterSafeConfirmSrc.className = wscs != null ? 'text-success small' : 'text-warning small';
            }
        }

        const rainCfg = cfg.RainAlerting || {};
        document.getElementById('cfg-rain-watch').value = rainCfg.rain_intensity_watch_threshold ?? 10.0;
        document.getElementById('cfg-rain-warning').value = rainCfg.rain_intensity_warning_threshold ?? 25.0;
        document.getElementById('cfg-rain-critical').value = rainCfg.rain_intensity_critical_threshold ?? 50.0;

        const rainWarningConfirmEl = document.getElementById('cfg-rain-warning-confirm');
        const rainCriticalConfirmEl = document.getElementById('cfg-rain-critical-confirm');
        const rainConfirmSrc = document.getElementById('cfg-rain-confirm-source');
        if (rainWarningConfirmEl) {
            const rcs = rainCfg.rain_warning_confirm_steps ?? rainCfg.rain_confirm_steps;
            rainWarningConfirmEl.value = rcs ?? 2;
            if (rainConfirmSrc) {
                rainConfirmSrc.textContent = rcs != null ? '✅ Đã lưu riêng cho trạm' : '⚠ Sẽ dùng giá trị Hệ thống';
                rainConfirmSrc.className = rcs != null ? 'text-success small' : 'text-warning small';
            }
        }
        if (rainCriticalConfirmEl) {
            const rccs = rainCfg.rain_critical_confirm_steps ?? rainCfg.rain_confirm_steps;
            rainCriticalConfirmEl.value = rccs ?? 1;
        }
        const rainSafeConfirmEl = document.getElementById('cfg-rain-safe-confirm');
        const rainSafeConfirmSrc = document.getElementById('cfg-rain-safe-confirm-source');
        if (rainSafeConfirmEl) {
            const rscs = rainCfg.rain_safe_confirm_steps;
            rainSafeConfirmEl.value = rscs ?? 3;
            if (rainSafeConfirmSrc) {
                rainSafeConfirmSrc.textContent = rscs != null ? '✅ Đã lưu riêng cho trạm' : '⚠ Sẽ dùng giá trị Hệ thống';
                rainSafeConfirmSrc.className = rscs != null ? 'text-success small' : 'text-warning small';
            }
        }
        const gnssCfg = cfg.GnssAlerting || {};
        document.getElementById('cfg-gnss-timeout').value = gnssCfg.gnss_degraded_timeout ?? 300;
        document.getElementById('cfg-gnss-hdop').value = gnssCfg.gnss_max_hdop ?? 4.0;

        const imuCfg = cfg.ImuAlerting || {};
        document.getElementById('cfg-imu-shock').value = imuCfg.shock_threshold_ms2 ?? 5.0;
        const tiltCritEl = document.getElementById('cfg-imu-tilt-crit');
        if (tiltCritEl) tiltCritEl.value = imuCfg.tilt_critical_deg ?? 15.0;
        const imuCriticalConfirmEl = document.getElementById('cfg-imu-critical-confirm');
        if (imuCriticalConfirmEl) imuCriticalConfirmEl.value = imuCfg.imu_critical_confirm_steps ?? imuCfg.imu_confirm_steps ?? 1;
        const imuSafeConfirmEl = document.getElementById('cfg-imu-safe-confirm');
        if (imuSafeConfirmEl) imuSafeConfirmEl.value = imuCfg.imu_safe_confirm_steps ?? 3;
        const gnssWarningStepsEl = document.getElementById('cfg-gnss-warning-steps');
        if (gnssWarningStepsEl) gnssWarningStepsEl.value = gnssCfg.gnss_warning_confirm_steps ?? gnssCfg.gnss_confirm_steps ?? 3;
        const gnssCriticalStepsEl = document.getElementById('cfg-gnss-critical-steps');
        if (gnssCriticalStepsEl) gnssCriticalStepsEl.value = gnssCfg.gnss_critical_confirm_steps ?? gnssCfg.gnss_confirm_steps ?? 2;
        const gnssSafeStepsEl = document.getElementById('cfg-gnss-safe-steps');
        if (gnssSafeStepsEl) gnssSafeStepsEl.value = gnssCfg.gnss_safe_confirm_steps ?? 5;

        const imuBaseline = cfg.ImuBaseline || {};
        const baseRollEl = document.getElementById('cfg-imu-base-roll');
        if (baseRollEl) baseRollEl.value = imuBaseline.baseline_roll ?? 0;
        const basePitchEl = document.getElementById('cfg-imu-base-pitch');
        if (basePitchEl) basePitchEl.value = imuBaseline.baseline_pitch ?? 0;
        const baseYawEl = document.getElementById('cfg-imu-base-yaw');
        if (baseYawEl) baseYawEl.value = imuBaseline.baseline_yaw ?? 0;
    }

    _populateEditStationForwarding(cfg) {
        const fwdCfg = cfg.gnss_rtk_forwarding || {};
        const approvalEl = document.getElementById('gnss-forwarding-approval');
        if (approvalEl) approvalEl.value = fwdCfg.approval?.reference || '';
        const fwdFields = fwdCfg.fields || {};
        const setToggle = (id, val, defaultVal = true) => {
            const el = document.getElementById(id);
            if (el) el.checked = (val !== undefined) ? !!val : defaultVal;
        };

        const fwdEnabledEl = document.getElementById('cfg-fwd-enabled');
        if (fwdEnabledEl) {
            fwdEnabledEl.checked = !!fwdCfg.enabled;
            this.toggleRtkForwardingSlide(false);
        }

        const rtkTopicEl = document.getElementById('gnss-rtk-topic');
        if (rtkTopicEl) rtkTopicEl.value = fwdCfg.rtk_topic || '';
        const rtkHostEl = document.getElementById('gnss-rtk-host');
        if (rtkHostEl) rtkHostEl.value = fwdCfg.host || '';
        const rtkPortEl = document.getElementById('gnss-rtk-port');
        if (rtkPortEl) rtkPortEl.value = fwdCfg.port || 1883;
        const rtkUserEl = document.getElementById('gnss-rtk-user');
        if (rtkUserEl) rtkUserEl.value = fwdCfg.username || '';
        const rtkPassEl = document.getElementById('gnss-rtk-pass');
        if (rtkPassEl) rtkPassEl.value = fwdCfg.password || '';
        const rtkCodeEl = document.getElementById('gnss-rtk-code');
        if (rtkCodeEl) rtkCodeEl.value = fwdCfg.gnss_code || '';

        setToggle('fwd-toggle-x', fwdFields.X);
        setToggle('fwd-toggle-y', fwdFields.Y);
        setToggle('fwd-toggle-h', fwdFields.H);
        setToggle('fwd-toggle-dx', fwdFields.dX);
        setToggle('fwd-toggle-dy', fwdFields.dY);
        setToggle('fwd-toggle-dh', fwdFields.dH);
        setToggle('fwd-toggle-vdx', fwdFields.VdX);
        setToggle('fwd-toggle-vdy', fwdFields.VdY);
        setToggle('fwd-toggle-vdh', fwdFields.VdH);
        this.syncForwardingWrapStates();

        const vnCfg = cfg.vn2000 || cfg.vn2000_params || {};
        const vnEnabledEl = document.getElementById('vn2000-enabled');
        if (vnEnabledEl) {
            vnEnabledEl.checked = !!vnCfg.enabled;
            this.toggleVn2000AdvancedSlide(false);
        }
        if (document.getElementById('vn-dx')) document.getElementById('vn-dx').value = vnCfg.dx ?? 191.90441429;
        if (document.getElementById('vn-dy')) document.getElementById('vn-dy').value = vnCfg.dy ?? 39.30318279;
        if (document.getElementById('vn-dz')) document.getElementById('vn-dz').value = vnCfg.dz ?? 111.45032835;
        if (document.getElementById('vn-rx')) document.getElementById('vn-rx').value = vnCfg.rx ?? 0.00928836;
        if (document.getElementById('vn-ry')) document.getElementById('vn-ry').value = vnCfg.ry ?? -0.01975479;
        if (document.getElementById('vn-rz')) document.getElementById('vn-rz').value = vnCfg.rz ?? 0.00427372;
        if (document.getElementById('vn-k')) document.getElementById('vn-k').value = vnCfg.k ?? 0.999999747093722;
        if (document.getElementById('vn-l0')) document.getElementById('vn-l0').value = vnCfg.l0_deg ?? 105.0;
        if (document.getElementById('vn-k0')) document.getElementById('vn-k0').value = vnCfg.k0 ?? 0.9999;
        if (document.getElementById('vn-resb')) document.getElementById('vn-resb').value = vnCfg.res_b ?? 0.0;
        if (document.getElementById('vn-resl')) document.getElementById('vn-resl').value = vnCfg.res_l ?? 0.0;
        if (document.getElementById('vn-resh')) document.getElementById('vn-resh').value = vnCfg.res_h ?? 0.0;
        if (document.getElementById('vn-resn')) document.getElementById('vn-resn').value = vnCfg.res_n ?? 0.0;
        if (document.getElementById('vn-rese')) document.getElementById('vn-rese').value = vnCfg.res_e ?? 0.0;
    }

    _populateEditStationOrigins(cfg) {
        const gnssOrigin = cfg.gnss_origin || {};
        if (gnssOrigin.lat) {
            document.getElementById('origin-lat').value = gnssOrigin.lat;
            document.getElementById('origin-lon').value = gnssOrigin.lon;
            document.getElementById('origin-h').value = gnssOrigin.h || 0;
            document.getElementById('origin-status').innerHTML = '<span class="text-success">✅ Đã có tọa độ gốc</span>';
            this.updateOriginActionButtons(true);
        } else {
            document.getElementById('origin-lat').value = '';
            document.getElementById('origin-lon').value = '';
            document.getElementById('origin-h').value = '';
            document.getElementById('origin-status').textContent = 'Chưa thiết lập';
            this.updateOriginActionButtons(false);
        }

        (window.sensorTypes?.() || ['rain', 'water', 'imu']).filter(type => type !== 'gnss').forEach(s => {
            const sOrigin = cfg[`${s}_origin`] || {};
            const latEl = document.getElementById(`origin-${s}-lat`);
            const lonEl = document.getElementById(`origin-${s}-lon`);
            const hEl = document.getElementById(`origin-${s}-h`);
            if (latEl) latEl.value = sOrigin.lat !== undefined ? sOrigin.lat : '';
            if (lonEl) lonEl.value = sOrigin.lon !== undefined ? sOrigin.lon : '';
            if (hEl) hEl.value = sOrigin.h !== undefined ? sOrigin.h : '';
        });

        const stationSaveIntervals = cfg.save_intervals || {};
        const saveGnssEl = document.getElementById('cfg-station-save-gnss');
        const saveRainEl = document.getElementById('cfg-station-save-rain');
        const saveWaterEl = document.getElementById('cfg-station-save-water');
        const saveImuEl = document.getElementById('cfg-station-save-imu');
        if (saveGnssEl) saveGnssEl.value = stationSaveIntervals.gnss || '';
        if (saveRainEl) saveRainEl.value = stationSaveIntervals.rain || '';
        if (saveWaterEl) saveWaterEl.value = stationSaveIntervals.water || '';
        if (saveImuEl) saveImuEl.value = stationSaveIntervals.imu || '';
    }

    async editStation(stationId) {
        try {
            this.isEditMode = true;
            this.currentStationId = stationId;
            this.pendingStationLocation = null;
            const demLocation = document.getElementById('station-dem-location');
            if (demLocation) demLocation.hidden = true;
            this.currentStep = 1;
            this.resetGnssOriginRelockProgress?.();
            this.resetGnssCalibrationResult?.();
            if (this._originResetTimer) {
                clearInterval(this._originResetTimer);
                this._originResetTimer = null;
            }

            window.toast?.info('Đang tải dữ liệu trạm...');

            const [resConfig, resDevices] = await Promise.all([
                fetch(`/api/admin/stations/${stationId}/config`, {
                    headers: { 'Authorization': `Bearer ${this.token}` }
                }),
                fetch(`/api/admin/stations/${stationId}/devices`, {
                    headers: { 'Authorization': `Bearer ${this.token}` }
                })
            ]);

            if (!resConfig.ok || !resDevices.ok) throw new Error('Không thể tải dữ liệu');

            const stationData = await resConfig.json();
            const devices = await resDevices.json();
            if (await window.loadCustomSensorPresets?.(this.token) === false) {
                throw new Error('Không tải được danh sách cảm biến đã lưu.');
            }

            // STEP 1: Basic info
            document.getElementById('edit-station-id').value = stationId;
            document.getElementById('edit-project-id').value = this.currentProjectId;
            document.getElementById('edit-code').value = stationData.station_code || '';
            document.getElementById('edit-name').value = stationData.name || '';

            // STEP 2: Sensors & MQTT
            this._populateEditStationDevices(devices);

            // STEP 3: Thresholds
            const cfg = stationData.config || {};
            this._populateEditStationThresholds(cfg);
            await this.loadAICasterUsers(
                cfg.gnss_aicaster_user || cfg.gnss_aicaster_client || {}
            );

            // STEP 4: Forwarding & Origins
            this._populateEditStationForwarding(cfg);
            this._populateEditStationOrigins(cfg);

            document.getElementById('modal-title').textContent = `Chỉnh sửa: ${stationData.name}`;

            this.highlightPreset(cfg.active_preset);
            this.bindMqttTopicValidation();
            this.validateMqttTopicsLocally();
            this.updateWizardStep();
            if (this.stationModal) this.stationModal.show();

        } catch (e) {
            console.error('❌ Error in editStation:', e);
            window.toast?.error('Lỗi: ' + e.message);
        }
    }

    updateWizardStep() {
        const stationModalEl = document.getElementById('stationConfigModal');
        const scope = stationModalEl || document;

        scope.querySelectorAll('.wizard-step').forEach(step => {
            const stepNum = Number.parseInt(step.dataset.step);
            step.classList.toggle('active', stepNum === this.currentStep);
            step.classList.toggle('completed', stepNum < this.currentStep);
            if (stepNum === this.currentStep) step.setAttribute('aria-current', 'step');
            else step.removeAttribute('aria-current');
        });

        scope.querySelectorAll('.wizard-content').forEach(content => {
            const stepNum = Number.parseInt(content.dataset.step);
            const isActive = stepNum === this.currentStep;
            content.classList.toggle('active', isActive);
            content.style.display = isActive ? 'block' : 'none';
            content.setAttribute('aria-hidden', isActive ? 'false' : 'true');
        });

        const modalBody = stationModalEl?.querySelector('.modal-body');
        if (modalBody) {
            modalBody.scrollTop = 0;
        }

        const btnBack = document.getElementById('btn-wizard-back');
        const btnNext = document.getElementById('btn-wizard-next');
        const btnSave = document.getElementById('btn-wizard-save');

        if (btnBack) btnBack.style.display = this.currentStep > 1 ? 'inline-block' : 'none';
        if (btnNext) btnNext.style.display = this.currentStep < this.totalSteps ? 'inline-block' : 'none';
        if (btnSave) btnSave.style.display = this.currentStep === this.totalSteps ? 'inline-block' : 'none';
        if (btnNext) btnNext.disabled = false;
        if (btnSave) btnSave.disabled = false;
        this.ensureWizardButtonInteractivity();

        // When reaching step 3, load pending devices for provisioning (only if editing existing station)
        const pendingSection = document.getElementById('pending-devices-section');
        if (this.currentStep === 3 && this.currentStationId) {
            if (pendingSection) pendingSection.style.display = 'block';
            this.loadWizardPendingDevices().catch((e) => {
                console.error('Failed to load pending devices in step 3:', e);
            });
        } else if (pendingSection) {
            pendingSection.style.display = 'none';
        }

        this.syncMqttSectionsForStep();
        this.syncSaveIntervalsForStep();
    }

    goToWizardStep(nextStep) {
        const normalizedStep = Math.max(1, Math.min(this.totalSteps, Number(nextStep) || 1));
        if (normalizedStep === this.currentStep) return;

        this.currentStep = normalizedStep;

        try {
            this.updateWizardStep();
        } catch (e) {
            console.error('Wizard UI update failed, applying fallback render:', e);

            // Fallback render: force-show only the target step content.
            document.querySelectorAll('#stationConfigModal .wizard-content').forEach(content => {
                const stepNum = Number(content.dataset.step);
                const isActive = stepNum === this.currentStep;
                content.classList.toggle('active', isActive);
                content.style.display = isActive ? 'block' : 'none';
            });
        }
    }

    syncMqttSectionsForStep() {
        const sensorTypes = (window.sensorTypes?.() || ['gnss', 'rain', 'water', 'imu']);
        const sectionByType = Object.fromEntries(sensorTypes.map(type => [type, document.getElementById(`mqtt-${type}-section`)]));
        const emptyState = document.getElementById('mqtt-empty-state');

        // Never show MQTT blocks outside step 2.
        if (this.currentStep !== 2) {
            sensorTypes.forEach(type => {
                const section = sectionByType[type];
                if (section) section.style.display = 'none';
            });
            if (emptyState) emptyState.style.display = 'none';
            return;
        }

        let anyChecked = false;
        sensorTypes.forEach(type => {
            const checked = !!document.getElementById(`edit-${type}`)?.checked;
            const section = sectionByType[type];
            if (section) section.style.display = checked ? 'block' : 'none';
            if (checked) anyChecked = true;
        });

        if (emptyState) emptyState.style.display = anyChecked ? 'none' : 'block';
    }

    async loadAICasterUsers(selectedBinding = null) {
        const select = document.getElementById('cfg-gnss-aicaster-user');
        const statusEl = document.getElementById('aicaster-user-status');
        const refreshButton = document.getElementById('btn-refresh-aicaster-users');
        if (!select) return;

        let desired = selectedBinding && typeof selectedBinding === 'object'
            ? selectedBinding
            : null;
        if (!desired && select.value) {
            try { desired = JSON.parse(select.value); } catch (err) { console.debug('Cannot parse aicaster user JSON:', err); desired = null; }
        }
        if (!desired) {
            desired = this.currentStationConfig?.gnss_aicaster_user
                || this.currentStationConfig?.gnss_aicaster_client
                || {};
        }

        select.disabled = true;
        if (refreshButton) refreshButton.disabled = true;
        if (statusEl) {
            statusEl.textContent = 'Đang đọc danh sách user từ AICaster...';
            statusEl.className = 'd-block text-info mt-2';
        }

        try {
            const response = await fetch('/api/admin/gnss/aicaster-users', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.detail || 'Không đọc được user table');

            const users = Array.isArray(payload.users) ? payload.users : [];
            select.innerHTML = '<option value="">-- Chọn user AICaster của rover --</option>';
            let matched = false;
            users.forEach(user => {
                const binding = {
                    username: String(user.username || '').trim(),
                    caster_host: String(user.caster_host || '').trim()
                };
                if (!binding.username) return;
                const option = document.createElement('option');
                option.value = JSON.stringify(binding);
                const mountpoints = Array.isArray(user.mountpoints) && user.mountpoints.length
                    ? user.mountpoints.join(', ')
                    : 'không giới hạn MP';
                const active = user.active_client_count !== ''
                    ? ` · ${user.active_client_count} client`
                    : '';
                option.textContent = `${binding.username} · ${mountpoints} · ${binding.caster_host}${active}`;
                if (
                    String(desired?.username || '').toLowerCase() === binding.username.toLowerCase()
                    && (
                        !desired?.caster_host
                        || String(desired.caster_host).toLowerCase() === binding.caster_host.toLowerCase()
                    )
                ) {
                    option.selected = true;
                    matched = true;
                }
                select.appendChild(option);
            });

            if (desired?.username && !matched) {
                const offlineOption = document.createElement('option');
                offlineOption.value = JSON.stringify({
                    username: String(desired.username),
                    caster_host: String(desired.caster_host || '')
                });
                offlineOption.textContent = `${desired.username} · đã lưu, hiện không còn trong user table`;
                offlineOption.selected = true;
                select.appendChild(offlineOption);
            }
            select.dataset.loaded = '1';
            if (statusEl) {
                statusEl.textContent = users.length
                    ? `Đã đọc ${users.length} user AICaster. Chọn tài khoản mà rover vật lý đang sử dụng.`
                    : 'User table của AICaster hiện không có tài khoản.';
                statusEl.className = `d-block ${users.length ? 'text-success' : 'text-warning'} mt-2`;
            }
        } catch (error) {
            console.debug('Failed to load AICaster users:', error);
            select.innerHTML = '<option value="">-- Không tải được danh sách AICaster --</option>';
            if (desired?.username) {
                const savedOption = document.createElement('option');
                savedOption.value = JSON.stringify({
                    username: String(desired.username),
                    caster_host: String(desired.caster_host || '')
                });
                savedOption.textContent = `${desired.username} · cấu hình đã lưu`;
                savedOption.selected = true;
                select.appendChild(savedOption);
            }
            if (statusEl) {
                statusEl.textContent = `Không đọc được AICaster: ${error.message}`;
                statusEl.className = 'd-block text-danger mt-2';
            }
        } finally {
            select.disabled = false;
            if (refreshButton) refreshButton.disabled = false;
        }
    }

    syncSaveIntervalsForStep() {
        if (this.currentStep !== 4) return;

        const sensors = [
            { type: 'gnss', elId: 'cfg-station-save-gnss' },
            { type: 'rain', elId: 'cfg-station-save-rain' },
            { type: 'water', elId: 'cfg-station-save-water' },
            { type: 'imu', elId: 'cfg-station-save-imu' }
        ];

        let visibleCount = 0;
        sensors.forEach(({ type, elId }) => {
            const inputEl = document.getElementById(elId);
            const col = inputEl?.closest('.col-md-6');
            if (col) {
                const checkboxEl = document.getElementById(`edit-${type}`);
                const isEnabled = Boolean(checkboxEl?.checked);
                col.style.display = isEnabled ? 'block' : 'none';
                if (isEnabled) visibleCount++;
            }
        });
        
        // Cập nhật thông báo nếu không có cảm biến nào
        let emptyState = document.getElementById('save-interval-empty-state');
        const container = document.querySelector('.sensor-config-body .row.g-3');
        if (visibleCount === 0 && container) {
            if (!emptyState) {
                emptyState = document.createElement('div');
                emptyState.id = 'save-interval-empty-state';
                emptyState.className = 'col-12 text-center text-muted small py-3';
                emptyState.innerHTML = '<i class="bi bi-x-circle me-1"></i> Không có cảm biến nào được bật cho trạm này.';
                container.appendChild(emptyState);
            }
            emptyState.style.display = 'block';
        } else if (emptyState) {
            emptyState.style.display = 'none';
        }
    }

    bindWizardButtons() {
        const btnBack = document.getElementById('btn-wizard-back');
        const btnNext = document.getElementById('btn-wizard-next');
        const btnSave = document.getElementById('btn-wizard-save');

        // Use direct handler assignment so buttons always follow latest instance state.
        if (btnBack) {
            btnBack.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.wizardPrev();
            };
        }

        if (btnNext) {
            btnNext.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.wizardNext();
            };
        }

        if (btnSave) {
            btnSave.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.saveStation();
            };
        }
    }

    bindWizardButtonFallback() {
        if (this._wizardFallbackBound) return;

        document.addEventListener('click', (e) => {
            const btn = e.target?.closest?.('#btn-wizard-next, #btn-wizard-back, #btn-wizard-save');
            if (!btn) return;

            const modalEl = document.getElementById('stationConfigModal');
            if (!modalEl?.classList.contains('show')) return;

            e.preventDefault();
            e.stopPropagation();

            if (btn.id === 'btn-wizard-next') {
                this.wizardNext();
            } else if (btn.id === 'btn-wizard-back') {
                this.wizardPrev();
            } else if (btn.id === 'btn-wizard-save') {
                this.saveStation();
            }
        }, true);

        // Extra fallback: bind directly on modal root so clicks still work even if another
        // layer/listener interferes at document level.
        const modalEl = document.getElementById('stationConfigModal');
        if (modalEl) {
            modalEl.addEventListener('click', (e) => {
                const btn = e.target?.closest?.('#btn-wizard-next, #btn-wizard-back, #btn-wizard-save');
                if (!btn) return;
                if (!modalEl.classList.contains('show')) return;

                e.preventDefault();
                e.stopPropagation();

                if (btn.id === 'btn-wizard-next') {
                    this.wizardNext();
                } else if (btn.id === 'btn-wizard-back') {
                    this.wizardPrev();
                } else if (btn.id === 'btn-wizard-save') {
                    this.saveStation();
                }
            }, true);
        }

        this._wizardFallbackBound = true;
    }

    ensureWizardButtonInteractivity() {
        const footer = document.querySelector('#stationConfigModal .modal-footer');
        const btnIds = ['btn-wizard-next', 'btn-wizard-back', 'btn-wizard-save'];

        if (footer) {
            footer.style.pointerEvents = 'auto';
            footer.style.position = 'relative';
            footer.style.zIndex = '1061';
        }

        btnIds.forEach((id) => {
            const btn = document.getElementById(id);
            if (!btn) return;
            btn.disabled = false;
            btn.style.pointerEvents = 'auto';
            btn.style.position = 'relative';
            btn.style.zIndex = '1062';
        });
    }

    wizardNext() {
        if (this.currentStep < this.totalSteps) {
            this.goToWizardStep(this.currentStep + 1);
        }
    }

    wizardPrev() {
        if (this.currentStep > 1) {
            this.goToWizardStep(this.currentStep - 1);
        }
    }

}
window.applyAdminFeature(AdminStationWizardFeature);
})();
