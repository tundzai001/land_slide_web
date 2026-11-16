(() => {
class AdminStationPresetsFeature extends window.AdminManager {
    // =========================================================================
    // STATION PRESET SYSTEM
    // =========================================================================

    highlightPreset(presetName) {
        this.activePreset = presetName || null;

        if (!this.activePreset || this.activePreset === 'custom') {
            this.stationPresetConfirm = null;
        }

        // Reset all buttons visual styling to transparent/outlined
        const buttons = document.querySelectorAll('.preset-btn');
        buttons.forEach(btn => {
            btn.classList.remove('active');
        });

        if (!this.activePreset || this.activePreset === 'custom') return;

        // Add visual flair to the active one
        const activeBtn = document.getElementById(`btn-preset-${this.activePreset}`);
        if (activeBtn) {
            activeBtn.classList.add('active');
        }
    }

    applyStationPreset(presetName) {
        this.highlightPreset(presetName);

        const presets = {
            conservative: {
                gnss_warning_steps: 5,
                gnss_critical_steps: 3,
                water_warning_confirm: 5,
                water_critical_confirm: 3,
                rain_warning_confirm: 3,
                rain_critical_confirm: 2,
                gnss_hdop: 3.0,
                gnss_timeout: 600,
                water_warning: 0.20,
                water_critical: 0.40,
                rain_watch: 15.0,
                rain_warning: 35.0,
                rain_critical: 60.0,
                imu_tilt_crit: 25.0,
                imu_shock: 8.0,
                imu_critical_confirm: 1
            },
            balanced: {
                gnss_warning_steps: 3,
                gnss_critical_steps: 2,
                water_warning_confirm: 3,
                water_critical_confirm: 2,
                rain_warning_confirm: 2,
                rain_critical_confirm: 1,
                gnss_hdop: 4.0,
                gnss_timeout: 300,
                water_warning: 0.15,
                water_critical: 0.30,
                rain_watch: 10.0,
                rain_warning: 25.0,
                rain_critical: 50.0,
                imu_tilt_crit: 15.0,
                imu_shock: 5.0,
                imu_critical_confirm: 1
            },
            sensitive: {
                gnss_warning_steps: 1,
                gnss_critical_steps: 1,
                water_warning_confirm: 1,
                water_critical_confirm: 1,
                rain_warning_confirm: 1,
                rain_critical_confirm: 1,
                gnss_hdop: 5.0,
                gnss_timeout: 180,
                water_warning: 0.10,
                water_critical: 0.20,
                rain_watch: 5.0,
                rain_warning: 15.0,
                rain_critical: 30.0,
                imu_tilt_crit: 8.0,
                imu_shock: 3.0,
                imu_critical_confirm: 1
            }
        };

        const preset = presets[presetName];
        if (!preset) return;

        // ✅ ĐIỀN TỰ ĐỘNG CÁC GIÁ TRỊ VÀO FORM

        // Rain/Water confirm steps - warning/critical tách riêng
        const rainWarningConfirmEl = document.getElementById('cfg-rain-warning-confirm');
        const rainCriticalConfirmEl = document.getElementById('cfg-rain-critical-confirm');
        const waterWarningConfirmEl = document.getElementById('cfg-water-warning-confirm');
        const waterCriticalConfirmEl = document.getElementById('cfg-water-critical-confirm');
        if (rainWarningConfirmEl) rainWarningConfirmEl.value = preset.rain_warning_confirm;
        if (rainCriticalConfirmEl) rainCriticalConfirmEl.value = preset.rain_critical_confirm;
        if (waterWarningConfirmEl) waterWarningConfirmEl.value = preset.water_warning_confirm;
        if (waterCriticalConfirmEl) waterCriticalConfirmEl.value = preset.water_critical_confirm;

        // Cập nhật source indicator
        const rainSrc = document.getElementById('cfg-rain-confirm-source');
        const waterSrc = document.getElementById('cfg-water-confirm-source');
        if (rainSrc) { rainSrc.textContent = '🔧 Từ preset: ' + presetName; rainSrc.className = 'text-info small'; }
        if (waterSrc) { waterSrc.textContent = '🔧 Từ preset: ' + presetName; waterSrc.className = 'text-info small'; }

        // GNSS Quality
        const gnssHdopEl = document.getElementById('cfg-gnss-hdop');
        const gnssWarningStepsEl = document.getElementById('cfg-gnss-warning-steps');
        const gnssCriticalStepsEl = document.getElementById('cfg-gnss-critical-steps');
        const gnssTimeoutEl = document.getElementById('cfg-gnss-timeout');

        if (gnssHdopEl) gnssHdopEl.value = preset.gnss_hdop;
        if (gnssWarningStepsEl) gnssWarningStepsEl.value = preset.gnss_warning_steps;
        if (gnssCriticalStepsEl) gnssCriticalStepsEl.value = preset.gnss_critical_steps;
        if (gnssTimeoutEl) gnssTimeoutEl.value = preset.gnss_timeout;

        // Water
        const waterWarningEl = document.getElementById('cfg-water-warning');
        const waterCriticalEl = document.getElementById('cfg-water-critical');

        if (waterWarningEl) waterWarningEl.value = preset.water_warning;
        if (waterCriticalEl) waterCriticalEl.value = preset.water_critical;

        // Rain
        const rainWatchEl = document.getElementById('cfg-rain-watch');
        const rainWarningEl = document.getElementById('cfg-rain-warning');
        const rainCriticalEl = document.getElementById('cfg-rain-critical');

        if (rainWatchEl) rainWatchEl.value = preset.rain_watch;
        if (rainWarningEl) rainWarningEl.value = preset.rain_warning;
        if (rainCriticalEl) rainCriticalEl.value = preset.rain_critical;

        // IMU
        const imuTiltCritEl = document.getElementById('cfg-imu-tilt-crit');
        const imuShockEl = document.getElementById('cfg-imu-shock');
        const imuCriticalConfirmEl = document.getElementById('cfg-imu-critical-confirm');

        if (imuTiltCritEl) imuTiltCritEl.value = preset.imu_tilt_crit;
        if (imuShockEl) imuShockEl.value = preset.imu_shock;
        if (imuCriticalConfirmEl) imuCriticalConfirmEl.value = preset.imu_critical_confirm;

        // ✅ HIỆU ỨNG FLASH (để user biết đã áp dụng)
        const inputs = document.querySelectorAll('#stationConfigForm input[type="number"]');
        inputs.forEach(input => {
            input.style.transition = 'background 0.5s';
            input.style.background = 'rgba(14, 165, 233, 0.2)';
            setTimeout(() => {
                input.style.background = '';
            }, 500);
        });

        // ✅ THÔNG BÁO
        const presetLabels = {
            'conservative': 'Conservative - Ít cảnh báo sai',
            'balanced': 'Balanced - Cân bằng',
            'sensitive': 'Sensitive - Phát hiện nhanh'
        };

        window.toast?.success(`✅ Đã áp dụng preset: ${presetLabels[presetName]}`, 3000);
    }

    getConfirmStepWarnings() {
        const readInt = (id, fallback) => {
            const val = Number.parseInt(document.getElementById(id)?.value, 10);
            return Number.isFinite(val) ? val : fallback;
        };

        const checks = [
            {
                name: 'GNSS',
                warning: readInt('cfg-gnss-warning-steps', 3),
                critical: readInt('cfg-gnss-critical-steps', 2),
                safe: readInt('cfg-gnss-safe-steps', 5)
            },
            {
                name: 'Rain',
                warning: readInt('cfg-rain-warning-confirm', 2),
                critical: readInt('cfg-rain-critical-confirm', 1),
                safe: readInt('cfg-rain-safe-confirm', 3)
            },
            {
                name: 'Water',
                warning: readInt('cfg-water-warning-confirm', 3),
                critical: readInt('cfg-water-critical-confirm', 2),
                safe: readInt('cfg-water-safe-confirm', 3)
            },
            {
                name: 'IMU',
                critical: readInt('cfg-imu-critical-confirm', 1),
                safe: readInt('cfg-imu-safe-confirm', 3)
            }
        ];

        const warnings = [];
        checks.forEach((item) => {
            if (item.critical <= 0) {
                warnings.push(`${item.name}: Critical Confirm Steps phải >= 1`);
            }
            if (item.name !== 'IMU' && item.critical > item.warning) {
                warnings.push(`${item.name}: Critical Confirm Steps (${item.critical}) nên <= Warning (${item.warning}) để cảnh báo nặng phản ứng nhanh hơn`);
            }
            const compareBase = item.name === 'IMU' ? item.critical : Math.max(item.warning, item.critical);
            if (item.safe <= compareBase) {
                const targetLabel = item.name === 'IMU' ? 'Critical' : 'Warning/Critical';
                const stepsSummary = item.name === 'IMU' ? item.critical : `${item.warning}/${item.critical}`;
                warnings.push(`${item.name}: Safe Confirm Steps (${item.safe}) nên lớn hơn ${targetLabel} (${stepsSummary})`);
            }
        });

        return warnings;
    }

    confirmConfirmStepWarnings() {
        const warnings = this.getConfirmStepWarnings();
        if (warnings.length === 0) return true;

        const message = [
            '⚠ Cảnh báo cấu hình Confirm Steps:',
            ...warnings.map(w => `- ${w}`),
            '',
            'Bạn vẫn muốn lưu cấu hình trạm?'
        ].join('\n');

        return confirm(message);
    }

    confirmDeviceProvisionWarnings(deviceCode) {
        const warnings = this.getConfirmStepWarnings();

        const message = warnings.length > 0
            ? [
                `⚠ Cảnh báo trước khi gán thiết bị ${deviceCode}:`,
                ...warnings.map(w => `- ${w}`),
                '',
                'Nếu vẫn tiếp tục, thiết bị sẽ dùng cấu hình confirm steps hiện tại của trạm.',
                'Bạn có muốn tiếp tục?'
            ].join('\n')
            : [
                `Xác nhận gán thiết bị ${deviceCode} vào trạm hiện tại?`,
                'Bạn có muốn tiếp tục?'
            ].join('\n');

        return confirm(message);
    }

    _collectSensorConfig(type) {
        const checkbox = document.getElementById(`edit-${type}`);
        if (!checkbox?.checked) return null;

        const topicInput = document.getElementById(`topic-${type}`);
        const topic = topicInput?.value?.trim();
        if (!topic) {
            window.toast?.error(`Vui lòng nhập MQTT Topic cho ${type.toUpperCase()}`);
            topicInput?.focus();
            return { error: true };
        }

        const mqttHost = document.getElementById(`cfg-${type}-mqtt-host`)?.value?.trim() || null;
        const mqttPortEl = document.getElementById(`cfg-${type}-mqtt-port`);
        const mqttPort = mqttPortEl?.value ? Number.parseInt(mqttPortEl.value) : null;
        const mqttTls = !!document.getElementById(`cfg-${type}-mqtt-tls`)?.checked;
        const mqttUser = document.getElementById(`cfg-${type}-mqtt-user`)?.value?.trim() || null;
        const mqttPass = document.getElementById(`cfg-${type}-mqtt-pass`)?.value?.trim() || null;

        const cfg = { 
            topic: topic,
            mqtt: {
                host: mqttHost,
                port: mqttPort,
                use_tls: mqttTls,
                username: mqttUser,
                password: mqttPass
            }
        };

        const prefix = type === 'gnss' ? 'origin' : `origin-${type}`;
        const lat = document.getElementById(`${prefix}-lat`)?.value;
        const lon = document.getElementById(`${prefix}-lon`)?.value;
        const h = document.getElementById(`${prefix}-h`)?.value;

        if (lat && lon) {
            cfg.lat = Number.parseFloat(lat);
            cfg.lon = Number.parseFloat(lon);
            cfg.h = Number.parseFloat(h) || 0;
        }
        return { config: cfg };
    }

    _collectStationSensors() {
        const sensors = {};
        const sensorTypes = (window.sensorTypes?.() || ['gnss', 'rain', 'water', 'imu']);
        for (const type of sensorTypes) {
            const res = this._collectSensorConfig(type);
            if (res) {
                if (res.error) return null;
                sensors[type] = res.config;
            }
        }
        return sensors;
    }

    _collectOfflineThresholds() {
        return {
            gnss: Number.parseInt(document.getElementById('offline-gnss')?.value) || this.defaultOfflineThresholds.gnss,
            rain: Number.parseInt(document.getElementById('offline-rain')?.value) || this.defaultOfflineThresholds.rain,
            water: Number.parseInt(document.getElementById('offline-water')?.value) || this.defaultOfflineThresholds.water,
            imu: Number.parseInt(document.getElementById('offline-imu')?.value) || this.defaultOfflineThresholds.imu
        };
    }

    _collectRtkForwarding() {
        return {
            enabled: !!document.getElementById('cfg-fwd-enabled')?.checked,
            host: document.getElementById('gnss-rtk-host')?.value?.trim() || '',
            port: Number.parseInt(document.getElementById('gnss-rtk-port')?.value) || 1883,
            username: document.getElementById('gnss-rtk-user')?.value?.trim() || '',
            password: document.getElementById('gnss-rtk-pass')?.value?.trim() || '',
            rtk_topic: document.getElementById('gnss-rtk-topic')?.value?.trim() || '',
            gnss_code: document.getElementById('gnss-rtk-code')?.value?.trim() || 'gnss_processed',
            fields: {
                X: !!document.getElementById('fwd-toggle-x')?.checked,
                Y: !!document.getElementById('fwd-toggle-y')?.checked,
                H: !!document.getElementById('fwd-toggle-h')?.checked,
                dX: !!document.getElementById('fwd-toggle-dx')?.checked,
                dY: !!document.getElementById('fwd-toggle-dy')?.checked,
                dH: !!document.getElementById('fwd-toggle-dh')?.checked,
                VdX: !!document.getElementById('fwd-toggle-vdx')?.checked,
                VdY: !!document.getElementById('fwd-toggle-vdy')?.checked,
                VdH: !!document.getElementById('fwd-toggle-vdh')?.checked
            }
        };
    }

    _collectVn2000() {
        const l0Raw = document.getElementById('vn-l0')?.value;
        const l0Parsed = this.parseVn2000CentralMeridian(l0Raw);
        const l0Input = document.getElementById('vn-l0');
        if (l0Input) l0Input.value = Number(l0Parsed.value.toFixed(10));

        return {
            enabled: !!document.getElementById('vn2000-enabled')?.checked,
            dx: Number.parseFloat(document.getElementById('vn-dx')?.value) || 191.90441429,
            dy: Number.parseFloat(document.getElementById('vn-dy')?.value) || 39.30318279,
            dz: Number.parseFloat(document.getElementById('vn-dz')?.value) || 111.45032835,
            rx: Number.parseFloat(document.getElementById('vn-rx')?.value) || 0.00928836,
            ry: Number.parseFloat(document.getElementById('vn-ry')?.value) || -0.01975479,
            rz: Number.parseFloat(document.getElementById('vn-rz')?.value) || 0.00427372,
            k: Number.parseFloat(document.getElementById('vn-k')?.value) || 0.999999747093722,
            l0_deg: l0Parsed.value,
            l0_raw: String(l0Raw ?? '').trim(),
            l0_input_format: l0Parsed.format,
            k0: Number.parseFloat(document.getElementById('vn-k0')?.value) || 0.9999,
            res_b: Number.parseFloat(document.getElementById('vn-resb')?.value) || 0.0,
            res_l: Number.parseFloat(document.getElementById('vn-resl')?.value) || 0.0,
            res_h: Number.parseFloat(document.getElementById('vn-resh')?.value) || 0.0,
            res_n: Number.parseFloat(document.getElementById('vn-resn')?.value) || 0.0,
            res_e: Number.parseFloat(document.getElementById('vn-rese')?.value) || 0.0
        };
    }

    _collectStationMqtt() {
        return {
            host: document.getElementById('station-mqtt-host')?.value?.trim() || '',
            port: document.getElementById('station-mqtt-port')?.value ? Number.parseInt(document.getElementById('station-mqtt-port').value) : null,
            use_tls: !!document.getElementById('station-mqtt-tls')?.checked,
            username: document.getElementById('station-mqtt-user')?.value?.trim() || '',
            password: document.getElementById('station-mqtt-pass')?.value?.trim() || ''
        };
    }

    _collectGnssAicasterUser() {
        const aicasterValue = document.getElementById('cfg-gnss-aicaster-user')?.value;
        if (!aicasterValue) return { username: '', caster_host: '' };
        try {
            const selectedClient = JSON.parse(aicasterValue);
            return {
                username: String(selectedClient.username || '').trim(),
                caster_host: String(selectedClient.caster_host || '').trim()
            };
        } catch (error) {
            console.error('Invalid AICaster client selection:', error);
            return { username: '', caster_host: '' };
        }
    }

    _collectStationLocation() {
        if (this.isEditMode || !this.pendingStationLocation) return null;
        const stationLocation = { ...this.pendingStationLocation };
        const editedLat = Number.parseFloat(document.getElementById('origin-lat')?.value || document.getElementById('origin-rain-lat')?.value || document.getElementById('origin-water-lat')?.value);
        const editedLon = Number.parseFloat(document.getElementById('origin-lon')?.value || document.getElementById('origin-rain-lon')?.value || document.getElementById('origin-water-lon')?.value);
        const editedH = Number.parseFloat(document.getElementById('origin-h')?.value || document.getElementById('origin-rain-h')?.value || document.getElementById('origin-water-h')?.value);
        if (Number.isFinite(editedLat)) stationLocation.lat = editedLat;
        if (Number.isFinite(editedLon)) stationLocation.lon = editedLon;
        if (Number.isFinite(editedH)) stationLocation.h = editedH;
        return stationLocation;
    }

    _collectSimulationProfile() {
        return {
            version: 1,
            cohesion_kpa: Number.parseFloat(document.getElementById('sim-profile-cohesion')?.value || 15),
            friction_angle_deg: Number.parseFloat(document.getElementById('sim-profile-friction')?.value || 30),
            unit_weight_kn_m3: Number.parseFloat(document.getElementById('sim-profile-unit-weight')?.value || 18),
            slip_depth_m: Number.parseFloat(document.getElementById('sim-profile-slip-depth')?.value || 5),
            slope_angle_deg: Number.parseFloat(document.getElementById('sim-profile-slope')?.value || 25),
            saturated_conductivity_m_s: Number.parseFloat(document.getElementById('sim-profile-ks')?.value || 0.000015),
            porosity: Number.parseFloat(document.getElementById('sim-profile-porosity')?.value || 0.25),
            base_pore_pressure_ratio: Number.parseFloat(document.getElementById('sim-profile-base-ru')?.value || 0),
            water_level_dry_m: Number.parseFloat(document.getElementById('sim-profile-water-dry')?.value || 0),
            water_level_saturated_m: Number.parseFloat(document.getElementById('sim-profile-water-saturated')?.value || 1),
            base_seismic_coeff: 0,
            house_count: Number.parseInt(document.getElementById('sim-profile-houses')?.value || 40),
            tree_count: Number.parseInt(document.getElementById('sim-profile-trees')?.value || 300),
        };
    }

    _collectOrigins() {
        const parseOrigin = (prefix) => {
            const latVal = document.getElementById(`origin-${prefix}-lat`)?.value;
            const lonVal = document.getElementById(`origin-${prefix}-lon`)?.value;
            const hVal = document.getElementById(`origin-${prefix}-h`)?.value;
            return {
                lat: latVal !== '' ? latVal : undefined,
                lon: lonVal !== '' ? lonVal : undefined,
                h: hVal !== '' ? hVal : undefined,
            };
        };
        return {
            gnss_origin: {
                lat: document.getElementById('origin-lat')?.value || null,
                lon: document.getElementById('origin-lon')?.value || null,
                h: document.getElementById('origin-h')?.value || 0
            },
            rain_origin: parseOrigin('rain'),
            water_origin: parseOrigin('water'),
            imu_origin: parseOrigin('imu'),
        };
    }

    _buildStationConfig(finalConfirmSteps) {
        const offlineThresholds = this._collectOfflineThresholds();
        const rtkForwarding = this._collectRtkForwarding();
        const vn2000 = this._collectVn2000();
        const stationMqtt = this._collectStationMqtt();
        const gnssAicasterUser = this._collectGnssAicasterUser();
        const origins = this._collectOrigins();

        const config = {
            active_preset: this.activePreset || '',
            simulation_profile: this._collectSimulationProfile(),
            alerting: {
                enabled: !document.getElementById('station-alerting-disabled')?.checked
            },
            offline_display: {
                enabled: !!document.getElementById('station-offline-display-enabled')?.checked
            },
            data_logging: {
                enabled: !!document.getElementById('cfg-station-processing-storage-enabled')?.checked
            },
            Water: {
                warning_threshold: Number.parseFloat(document.getElementById('cfg-water-warning')?.value || 0),
                critical_threshold: Number.parseFloat(document.getElementById('cfg-water-critical')?.value || 0),
                water_warning_confirm_steps: finalConfirmSteps.waterWarning,
                water_critical_confirm_steps: finalConfirmSteps.waterCritical,
                water_confirm_steps: finalConfirmSteps.waterWarning,
                water_safe_confirm_steps: Number.parseInt(document.getElementById('cfg-water-safe-confirm')?.value) || 3
            },
            RainAlerting: {
                rain_intensity_watch_threshold: Number.parseFloat(document.getElementById('cfg-rain-watch')?.value || 0),
                rain_intensity_warning_threshold: Number.parseFloat(document.getElementById('cfg-rain-warning')?.value || 0),
                rain_intensity_critical_threshold: Number.parseFloat(document.getElementById('cfg-rain-critical')?.value || 0),
                rain_warning_confirm_steps: finalConfirmSteps.rainWarning,
                rain_critical_confirm_steps: finalConfirmSteps.rainCritical,
                rain_confirm_steps: finalConfirmSteps.rainWarning,
                rain_safe_confirm_steps: Number.parseInt(document.getElementById('cfg-rain-safe-confirm')?.value) || 3
            },
            GnssAlerting: {
                gnss_max_hdop: Number.parseFloat(document.getElementById('cfg-gnss-hdop')?.value || 4.0),
                gnss_warning_confirm_steps: finalConfirmSteps.gnssWarning,
                gnss_critical_confirm_steps: finalConfirmSteps.gnssCritical,
                gnss_confirm_steps: finalConfirmSteps.gnssWarning,
                gnss_safe_confirm_steps: Number.parseInt(document.getElementById('cfg-gnss-safe-steps')?.value) || 5,
                gnss_degraded_timeout: Number.parseInt(document.getElementById('cfg-gnss-timeout')?.value || 300)
            },
            ImuAlerting: {
                tilt_critical_deg: Number.parseFloat(document.getElementById('cfg-imu-tilt-crit')?.value || 15.0),
                tilt_warning_deg: Number.parseFloat(document.getElementById('cfg-imu-tilt-crit')?.value || 15.0),
                imu_warning_confirm_steps: finalConfirmSteps.imuCritical,
                imu_critical_confirm_steps: finalConfirmSteps.imuCritical,
                imu_confirm_steps: finalConfirmSteps.imuCritical,
                imu_safe_confirm_steps: Number.parseInt(document.getElementById('cfg-imu-safe-confirm')?.value) || 3,
                shock_threshold_ms2: Number.parseFloat(document.getElementById('cfg-imu-shock')?.value || 5.0)
            },
            ImuBaseline: {
                baseline_roll: Number.parseFloat(document.getElementById('cfg-imu-base-roll')?.value) || 0.0,
                baseline_pitch: Number.parseFloat(document.getElementById('cfg-imu-base-pitch')?.value) || 0.0,
                baseline_yaw: Number.parseFloat(document.getElementById('cfg-imu-base-yaw')?.value) || 0.0
            },
            ...origins,
            velocity_classification: this.velocityConfig,
            offline_thresholds: offlineThresholds,
            gnss_aicaster_user: gnssAicasterUser,
            gnss_rtk_forwarding: rtkForwarding,
            vn2000: vn2000,
            vn2000_params: vn2000,
            mqtt: stationMqtt,
            save_intervals: {
                gnss: (document.getElementById('edit-gnss')?.checked && document.getElementById('cfg-station-save-gnss')?.value) ? Number.parseInt(document.getElementById('cfg-station-save-gnss').value) : null,
                rain: (document.getElementById('edit-rain')?.checked && document.getElementById('cfg-station-save-rain')?.value) ? Number.parseInt(document.getElementById('cfg-station-save-rain').value) : null,
                water: (document.getElementById('edit-water')?.checked && document.getElementById('cfg-station-save-water')?.value) ? Number.parseInt(document.getElementById('cfg-station-save-water').value) : null,
                imu: (document.getElementById('edit-imu')?.checked && document.getElementById('cfg-station-save-imu')?.value) ? Number.parseInt(document.getElementById('cfg-station-save-imu').value) : null
            }
        };

        config.custom_sensors = Object.fromEntries((window.SensorCatalog || [])
            .filter(sensor => sensor.key.startsWith('custom_') && document.getElementById(`edit-${sensor.key}`)?.checked)
            .map(sensor => [sensor.key, sensor]));
        for (const sensor of (window.SensorCatalog || []).filter(sensor => !sensor.legacy)) {
            config[`${sensor.key}_origin`] = Object.fromEntries(['lat', 'lon', 'h'].map(axis => {
                const value = document.getElementById(`origin-${sensor.key}-${axis}`)?.value;
                return [axis, value === '' || value == null ? null : Number(value)];
            }));
        }
        return config;
    }

    async saveStation() {
        const code = document.getElementById('edit-code').value.trim();
        const name = document.getElementById('edit-name').value.trim();
        const projectId = document.getElementById('edit-project-id').value;

        if (!code || !name) {
            window.toast?.warning('Vui lòng nhập mã trạm và tên trạm');
            return;
        }

        const sensors = this._collectStationSensors();
        if (!sensors) return;

        if (typeof this.validateAllMqttTopics === 'function' && !(await this.validateAllMqttTopics())) {
            window.toast?.error('MQTT topic đang bị trùng hoặc chưa hợp lệ');
            return;
        }
        if (!this.confirmConfirmStepWarnings()) return;

        const finalConfirmSteps = {
            rainWarning: Number.parseInt(document.getElementById('cfg-rain-warning-confirm')?.value) || 2,
            rainCritical: Number.parseInt(document.getElementById('cfg-rain-critical-confirm')?.value) || 1,
            waterWarning: Number.parseInt(document.getElementById('cfg-water-warning-confirm')?.value) || 3,
            waterCritical: Number.parseInt(document.getElementById('cfg-water-critical-confirm')?.value) || 2,
            gnssWarning: Number.parseInt(document.getElementById('cfg-gnss-warning-steps')?.value) || 3,
            gnssCritical: Number.parseInt(document.getElementById('cfg-gnss-critical-steps')?.value) || 2,
            imuCritical: Number.parseInt(document.getElementById('cfg-imu-critical-confirm')?.value) || 1,
        };

        const config = this._buildStationConfig(finalConfirmSteps);
        const stationLocation = this._collectStationLocation();

        const payload = {
            station_code: code,
            name: name,
            sensors: sensors,
            config: config,
            owner_authorization: document.getElementById('gnss-forwarding-approval')?.value?.trim() || '',
            location: stationLocation
        };

        console.log('💾 [SAVE] isEditMode:', this.isEditMode, 'stationId:', this.currentStationId);

        try {
            let url = this.isEditMode
                ? `/api/admin/stations/${this.currentStationId}/config`
                : `/api/admin/projects/${projectId}/stations`;

            let method = this.isEditMode ? 'PUT' : 'POST';

            const res = await fetch(url, {
                method: method,
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const error = await res.json().catch(() => ({}));
                throw new Error(error.detail || 'Lỗi lưu trạm');
            }

            window.toast?.success('✅ Lưu thành công!');
            this._projectConfigCache?.delete(Number(projectId));
            this.stationModal.hide();
            this.pendingStationLocation = null;
            this.loadStations(projectId);
        } catch (e) {
            window.toast?.error('❌ ' + e.message);
        }
    }

    async deleteStation(stationId) {
        if (!confirm('Bạn có chắc muốn xóa trạm này?')) return;

        try {
            const res = await fetch(`/api/admin/stations/${stationId}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });

            if (!res.ok) throw new Error('Failed');

            window.toast?.success('✅ Xóa trạm thành công!');
            this._projectConfigCache?.delete(Number(this.currentProjectId));

            if (this.stationModal) this.stationModal.hide();
            this.loadStations(this.currentProjectId);

        } catch (e) {
            console.error('Lỗi xóa trạm:', e);
            window.toast?.error('❌ Lỗi xóa trạm');
        }
    }

    async _handleGnssHttpError(res, data, caller) {
        if (res.status === 401) {
            await window.authManager?.handleUnauthorizedResponse?.(caller);
            throw new Error('Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại');
        }
        if (res.status === 403) {
            throw new Error('Tài khoản không có quyền thực hiện thao tác này');
        }
        throw new Error(data.detail || `Backend trả về HTTP ${res.status}`);
    }

    _handleResetOriginTimeout(resetBtn, statusEl) {
        if (statusEl) {
            statusEl.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Gateway đã hết thời gian chờ; backend vẫn đang hoàn tất hiệu chuẩn…';
            statusEl.className = 'text-warning small';
        }
        window.toast?.info('HTTP hết thời gian chờ, không phải lỗi hiệu chuẩn. Đang chờ kết quả realtime.');
        setTimeout(() => {
            if (!this._gnssCalibrationInProgress) return;
            this._gnssCalibrationInProgress = false;
            if (resetBtn) resetBtn.disabled = false;
            if (statusEl) {
                statusEl.textContent = 'Không nhận được phản hồi realtime; tải lại cấu hình trạm để kiểm tra offset đã lưu.';
                statusEl.className = 'text-warning small';
            }
        }, 20_000);
    }

    _validateCanResetOrigin(stationId) {
        if (this._gnssOriginRelockInProgress) {
            window.toast?.warning('Đang khóa lại tọa độ gốc; hãy chờ hoàn tất');
            return false;
        }
        if (!stationId || Number.isNaN(Number(stationId))) {
            window.toast?.warning('Hãy lưu trạm trước khi hiệu chuẩn offset GNSS');
            return false;
        }
        return confirm('Thu mẫu RTK FIXED ổn định trong 60 giây để hiệu chuẩn offset? Tọa độ gốc sẽ được giữ nguyên.');
    }

    _applyCalibrationSuccess(data, statusEl) {
        const calibration = data.calibrations?.[0];
        const horizontalShiftMm = calibration
            ? Math.hypot(calibration.shift_e_m, calibration.shift_n_m) * 1000
            : 0;
        const totalOffsetMm = calibration?.new_tracking_offset_2d_mm || 0;
        this.renderGnssCalibrationResult(calibration);
        window.toast?.success(`Calibrated ${data.calibrated_count} GNSS offset(s); origin unchanged`);
        if (statusEl) {
            statusEl.innerHTML = `<i class="bi bi-check-circle me-1"></i> Applied ${horizontalShiftMm.toFixed(1)} mm; total tracking offset ${totalOffsetMm.toFixed(1)} mm. Origin unchanged.`;
            statusEl.className = 'text-success small';
        }
    }

    async resetGnssOrigin(stationId) {
        if (!this._validateCanResetOrigin(stationId)) return;

        const resetBtn = document.getElementById('btn-reset-origin');
        const statusEl = document.getElementById('origin-status');
        let awaitingRealtimeCompletion = false;
        try {
            if (resetBtn) resetBtn.disabled = true;
            this._gnssCalibrationInProgress = true;
            this._gnssCalibrationCompleted = false;
            if (statusEl) {
                statusEl.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Backend đang chuẩn bị thu mẫu RTK FIXED…';
                statusEl.className = 'text-info small';
            }

            const res = await fetch(`/api/admin/gnss/reset-origin/${stationId}`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${this.token}` },
                cache: 'no-store',
            });

            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                if (res.status === 504) {
                    if (this._gnssCalibrationCompleted) return;
                    awaitingRealtimeCompletion = true;
                    this._handleResetOriginTimeout(resetBtn, statusEl);
                    return;
                }
                await this._handleGnssHttpError(res, data, 'gnss-calibration');
            }

            this._applyCalibrationSuccess(data, statusEl);
        } catch (e) {
            window.toast?.error('Offset calibration failed: ' + e.message);
        } finally {
            if (!awaitingRealtimeCompletion) {
                this._gnssCalibrationInProgress = false;
                if (resetBtn) resetBtn.disabled = false;
            }
        }
    }

    _handleRelockOriginTimeout(stationId, statusEl, setActionButtonsDisabled) {
        if (statusEl && Number(this.currentStationId) === Number(stationId)) {
            statusEl.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Gateway hết thời gian chờ; backend vẫn đang khóa lại gốc…';
            statusEl.className = 'text-warning small';
        }
        window.toast?.info('Đang chờ kết quả khóa lại tọa độ gốc qua realtime.');
        setTimeout(() => {
            if (!this._gnssOriginRelockInProgress || this._gnssOriginRelockCompleted) return;
            this._gnssOriginRelockInProgress = false;
            this._gnssOriginRelockStationId = null;
            if (this.currentStationId) setActionButtonsDisabled(false);
            if (Number(this.currentStationId) === Number(stationId)) {
                this.updateGnssOriginRelockProgress?.({
                    ...this._gnssOriginRelockLastProgress,
                    phase: 'failed',
                    message: 'Không nhận được kết quả realtime; hãy tải lại cấu hình trạm để kiểm tra tọa độ gốc.',
                });
            }
            if (statusEl && Number(this.currentStationId) === Number(stationId)) {
                statusEl.textContent = 'Chưa nhận được kết quả realtime; tải lại cấu hình trạm để kiểm tra tọa độ gốc.';
                statusEl.className = 'text-warning small';
            }
        }, 130_000);
    }

    _applyRelockSuccessResult(result, stationId, statusEl) {
        const isActiveStation = Number(this.currentStationId) === Number(stationId);
        if (isActiveStation) {
            this.updateGnssOriginRelockProgress?.({
                phase: 'complete',
                sample_count: result?.sample_count || 61,
                minimum_samples: 61,
                duration_s: result?.duration_s || 60,
                minimum_duration_s: 60,
                remaining_s: 0,
            });
        }
        if (result?.origin && isActiveStation) {
            document.getElementById('origin-lat').value = result.origin.lat;
            document.getElementById('origin-lon').value = result.origin.lon;
            document.getElementById('origin-h').value = result.origin.h;
            this.renderGnssTrackingOffset([0, 0, 0], {
                state: 'Gốc mới đã khóa',
                source: `${result.sample_count} mẫu RTK FIXED`,
                duration: `${Number(result.duration_s || 0).toFixed(1)} giây`,
            });
        }
        this._gnssOriginRelockCompleted = true;
        this._gnssOriginRelockInProgress = false;
        this._gnssOriginRelockStationId = null;
        if (statusEl && isActiveStation) {
            statusEl.innerHTML = '<i class="bi bi-check-circle me-1" aria-hidden="true"></i>Đã khóa lại tọa độ gốc; chuyển vị tracking tính từ mốc mới.';
            statusEl.className = 'text-success small';
        }
        window.toast?.success('Đã khóa lại tọa độ gốc GNSS.');
    }

    _validateCanRelockOrigin(stationId) {
        if (this._gnssOriginRelockInProgress) {
            window.toast?.warning('Đang có thao tác khóa lại tọa độ gốc; hãy chờ hoàn tất');
            return null;
        }
        if (this._gnssCalibrationInProgress) {
            window.toast?.warning('Đang hiệu chuẩn offset GNSS; hãy chờ hoàn tất');
            return null;
        }
        if (!stationId || Number.isNaN(Number(stationId))) {
            window.toast?.warning('Hãy lưu trạm trước khi khóa lại tọa độ gốc');
            return null;
        }
        const topic = document.getElementById('topic-gnss')?.value.trim();
        if (!topic) {
            window.toast?.warning('Vui lòng nhập MQTT Topic của GNSS trước');
            return null;
        }
        return topic;
    }

    _handleRelockOriginCatch(e, stationId, statusEl) {
        this._gnssOriginRelockInProgress = false;
        this._gnssOriginRelockStationId = null;
        if (Number(this.currentStationId) === Number(stationId)) {
            this.updateGnssOriginRelockProgress?.({
                ...this._gnssOriginRelockLastProgress,
                phase: 'failed',
                message: e.message,
            });
            if (statusEl) {
                statusEl.textContent = e.message;
                statusEl.className = 'text-danger small';
            }
        }
        window.toast?.error('Không khóa lại được tọa độ gốc: ' + e.message);
    }

    async relockGnssOrigin(stationId) {
        const topic = this._validateCanRelockOrigin(stationId);
        if (!topic) return;

        if (!confirm('Khóa lại gốc theo vị trí GNSS hiện tại? Hệ thống sẽ thu 61 mẫu RTK FIXED ổn định trong ít nhất 60 giây. Gốc cũ được lưu lịch sử và chuyển vị tracking sẽ bắt đầu lại từ gốc mới.')) return;

        const setActionButtonsDisabled = (disabled) => {
            ['btn-relock-origin', 'btn-reset-origin', 'btn-fetch-origin'].forEach(id => {
                const actionButton = document.getElementById(id);
                if (actionButton) actionButton.disabled = disabled;
            });
        };
        const statusEl = document.getElementById('origin-status');
        let awaitingRealtimeCompletion = false;
        try {
            setActionButtonsDisabled(true);
            this._gnssOriginRelockInProgress = true;
            this._gnssOriginRelockStationId = Number(stationId);
            this._gnssOriginRelockCompleted = false;
            this.updateGnssOriginRelockProgress?.({
                phase: 'collecting', sample_count: 0, minimum_samples: 61,
                duration_s: 0, minimum_duration_s: 60, remaining_s: 60,
            });
            if (statusEl) {
                statusEl.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Đang chờ mẫu RTK FIXED ổn định…';
                statusEl.className = 'text-info small';
            }

            const res = await fetch(`/api/admin/gnss/relock-origin/${stationId}`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ topic }),
                cache: 'no-store',
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                if (res.status === 504) {
                    if (this._gnssOriginRelockCompleted) return;
                    awaitingRealtimeCompletion = true;
                    this._handleRelockOriginTimeout(stationId, statusEl, setActionButtonsDisabled);
                    return;
                }
                await this._handleGnssHttpError(res, data, 'gnss-origin-relock');
            }

            this._applyRelockSuccessResult(data.relock, stationId, statusEl);
        } catch (e) {
            this._handleRelockOriginCatch(e, stationId, statusEl);
        } finally {
            if (!awaitingRealtimeCompletion && !this._gnssOriginRelockInProgress) {
                setActionButtonsDisabled(false);
            }
        }
    }

    _renderRelockComplete(bar, label, detail, remainingEl) {
        bar.classList.add('bg-success');
        bar.classList.remove('progress-bar-animated');
        if (label) label.textContent = 'Đã khóa lại tọa độ gốc';
        if (detail) detail.textContent = 'Chuyển vị tracking đang tính từ mốc mới.';
        if (remainingEl) remainingEl.textContent = 'Hoàn tất';
    }

    _renderRelockFailed(bar, label, detail, remainingEl, message) {
        bar.classList.add('bg-danger');
        bar.classList.remove('progress-bar-animated');
        if (label) label.textContent = 'Chưa thể khóa lại tọa độ gốc';
        if (detail) detail.textContent = message || 'Thu mẫu RTK FIXED chưa đạt yêu cầu.';
        if (remainingEl) remainingEl.textContent = 'Đã dừng';
    }

    _renderRelockCollecting(bar, label, detail, remainingEl, remaining) {
        bar.classList.add('bg-info', 'progress-bar-animated');
        if (label) label.textContent = 'Đang thu mẫu RTK FIXED';
        if (detail) detail.textContent = 'Giữ RTK FIXED ổn định trong lúc thu mẫu.';
        if (remainingEl) remainingEl.textContent = `Còn khoảng ${remaining} giây`;
    }

    _updateRelockPhaseUI(phase, progress, remaining, bar) {
        const label = document.getElementById('gnss-origin-relock-label');
        const detail = document.getElementById('gnss-origin-relock-detail');
        const remainingEl = document.getElementById('gnss-origin-relock-remaining');

        bar.classList.remove('bg-info', 'bg-success', 'bg-danger');
        if (phase === 'complete') {
            this._renderRelockComplete(bar, label, detail, remainingEl);
        } else if (phase === 'failed') {
            this._renderRelockFailed(bar, label, detail, remainingEl, progress.message);
        } else {
            this._renderRelockCollecting(bar, label, detail, remainingEl, remaining);
        }
    }

    updateGnssOriginRelockProgress(progress = {}) {
        const box = document.getElementById('gnss-origin-relock-progress');
        const bar = document.getElementById('gnss-origin-relock-bar');
        const track = bar?.parentElement;
        if (!box || !bar || !track) return;

        const phase = progress.phase || 'collecting';
        const count = Number(progress.sample_count || 0);
        const target = Number(progress.minimum_samples || 61);
        const duration = Number(progress.duration_s || 0);
        const minimum = Number(progress.minimum_duration_s || 60);
        const remaining = Math.max(0, Math.ceil(Number(progress.remaining_s || 0)));
        const countPercent = target > 0 ? (count / target) * 100 : 0;
        const durationPercent = minimum > 0 ? (duration / minimum) * 100 : 100;
        const percent = phase === 'complete' ? 100 : Math.max(0, Math.min(100, countPercent, durationPercent));
        const counts = document.getElementById('gnss-origin-relock-counts');

        box.hidden = false;
        bar.style.width = `${percent.toFixed(1)}%`;
        track.setAttribute('aria-valuenow', String(Math.round(percent)));
        track.setAttribute('aria-valuetext', `${count} trên ${target} mẫu, ${duration.toFixed(1)} trên ${minimum} giây`);

        this._updateRelockPhaseUI(phase, progress, remaining, bar);

        if (counts) counts.textContent = `${count}/${target} mẫu · ${duration.toFixed(1)}/${minimum.toFixed(0)} giây`;
        this._gnssOriginRelockLastProgress = { ...progress };
    }

    resetGnssOriginRelockProgress() {
        this._gnssOriginRelockLastProgress = null;
        const box = document.getElementById('gnss-origin-relock-progress');
        if (box) box.hidden = true;
    }

    async refreshGnssTrackingOffset(stationId) {
        if (!stationId) return;
        const res = await fetch(`/api/admin/stations/${stationId}/devices`, {
            headers: { 'Authorization': `Bearer ${this.token}` },
            cache: 'no-store',
        });
        if (!res.ok) return;
        const devices = await res.json();
        const gnss = devices.find(device => device.device_type === 'gnss' && device.is_active !== false)
            || devices.find(device => device.device_type === 'gnss');
        if (gnss) this.renderGnssTrackingOffset(gnss.tracking_offset);
    }

    renderGnssCalibrationResult(calibration) {
        if (!calibration) return;
        this.renderGnssTrackingOffset(calibration.new_tracking_offset, {
            state: 'Vừa hiệu chuẩn & lưu',
            source: `${calibration.sample_count || 0} mẫu`,
            duration: `${Number(calibration.duration_s || 0).toFixed(1)} giây`,
        });
    }

    renderGnssTrackingOffset(offset, { state = 'Đang áp dụng', source = 'Dữ liệu runtime/DB', duration = '—' } = {}) {
        const box = document.getElementById('gnss-offset-result');
        if (!box) return;
        const set = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.textContent = value;
        };
        const values = Array.isArray(offset) ? offset.slice(0, 3).map(Number) : [];
        const valid = values.length === 3 && values.every(Number.isFinite);
        const formatMm = value => (value * 1000).toFixed(3);
        set('gnss-offset-e', valid ? formatMm(values[0]) : '—');
        set('gnss-offset-n', valid ? formatMm(values[1]) : '—');
        set('gnss-offset-u', valid ? formatMm(values[2]) : '—');
        set('gnss-offset-2d', valid ? (Math.hypot(values[0], values[1]) * 1000).toFixed(3) : '—');
        set('gnss-offset-state', valid ? state : 'Chưa có offset hợp lệ');
        set('gnss-offset-samples', source);
        set('gnss-offset-duration', duration);
        box.classList.toggle('is-missing', !valid);
        box.hidden = false;
    }

    resetGnssCalibrationResult() {
        const box = document.getElementById('gnss-offset-result');
        if (box) box.hidden = true;
    }

    updateOriginActionButtons(hasOrigin) {
        const resetBtn = document.getElementById('btn-reset-origin');
        const relockBtn = document.getElementById('btn-relock-origin');
        const fetchBtn = document.getElementById('btn-fetch-origin');
        const relockBusy = !!this._gnssOriginRelockInProgress;
        if (resetBtn) resetBtn.style.display = hasOrigin ? 'inline-block' : 'none';
        if (resetBtn) resetBtn.disabled = relockBusy;
        if (relockBtn) {
            relockBtn.style.display = hasOrigin && this.currentStationId ? 'inline-block' : 'none';
            relockBtn.disabled = relockBusy;
        }
        if (fetchBtn) fetchBtn.style.display = 'inline-block';
        if (fetchBtn) fetchBtn.disabled = relockBusy;
    }

}
window.applyAdminFeature(AdminStationPresetsFeature);
})();
