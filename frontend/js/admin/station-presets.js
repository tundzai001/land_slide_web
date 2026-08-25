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
            const val = parseInt(document.getElementById(id)?.value, 10);
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
                warnings.push(`${item.name}: Safe Confirm Steps (${item.safe}) nên lớn hơn ${item.name === 'IMU' ? 'Critical' : 'Warning/Critical'} (${item.name === 'IMU' ? item.critical : `${item.warning}/${item.critical}`})`);
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

    async saveStation() {
        const code = document.getElementById('edit-code').value.trim();
        const name = document.getElementById('edit-name').value.trim();
        const projectId = document.getElementById('edit-project-id').value;

        if (!code || !name) {
            window.toast?.warning('Vui lòng nhập mã trạm và tên trạm');
            return;
        }

        const sensors = {};
        const sensorTypes = ['gnss', 'rain', 'water', 'imu'];
        let hasError = false;

        sensorTypes.forEach(type => {
            const checkbox = document.getElementById(`edit-${type}`);
            if (checkbox && checkbox.checked) {
                const topicInput = document.getElementById(`topic-${type}`);
                const topic = topicInput?.value?.trim();

                if (!topic) {
                    window.toast?.error(`Vui lòng nhập MQTT Topic cho ${type.toUpperCase()}`);
                    topicInput?.focus();
                    hasError = true;
                    return;
                }

                const mqttHost = document.getElementById(`cfg-${type}-mqtt-host`)?.value?.trim() || null;
                const mqttPort = document.getElementById(`cfg-${type}-mqtt-port`)?.value ? parseInt(document.getElementById(`cfg-${type}-mqtt-port`).value) : null;
                const mqttTls = !!document.getElementById(`cfg-${type}-mqtt-tls`)?.checked;
                const mqttUser = document.getElementById(`cfg-${type}-mqtt-user`)?.value?.trim() || null;
                const mqttPass = document.getElementById(`cfg-${type}-mqtt-pass`)?.value?.trim() || null;

                sensors[type] = { 
                    topic: topic,
                    mqtt: {
                        host: mqttHost,
                        port: mqttPort,
                        use_tls: mqttTls,
                        username: mqttUser,
                        password: mqttPass
                    }
                };

                if (type === 'gnss') {
                    const lat = document.getElementById('origin-lat').value;
                    const lon = document.getElementById('origin-lon').value;
                    const h = document.getElementById('origin-h').value;

                    if (lat && lon) {
                        sensors[type].lat = parseFloat(lat);
                        sensors[type].lon = parseFloat(lon);
                        sensors[type].h = parseFloat(h) || 0;
                    }
                } else if (['rain', 'water', 'imu'].includes(type)) {
                    const lat = document.getElementById(`origin-${type}-lat`)?.value;
                    const lon = document.getElementById(`origin-${type}-lon`)?.value;
                    const h = document.getElementById(`origin-${type}-h`)?.value;

                    if (lat && lon) {
                        sensors[type].lat = parseFloat(lat);
                        sensors[type].lon = parseFloat(lon);
                        sensors[type].h = parseFloat(h) || 0;
                    }
                }
            }
        });

        if (hasError) return;
        if (typeof this.validateAllMqttTopics === 'function' && !(await this.validateAllMqttTopics())) {
            window.toast?.error('MQTT topic đang bị trùng hoặc chưa hợp lệ');
            return;
        }
        if (!this.confirmConfirmStepWarnings()) return;

        const finalRainWarningConfirm = parseInt(document.getElementById('cfg-rain-warning-confirm')?.value) || 2;
        const finalRainCriticalConfirm = parseInt(document.getElementById('cfg-rain-critical-confirm')?.value) || 1;
        const finalWaterWarningConfirm = parseInt(document.getElementById('cfg-water-warning-confirm')?.value) || 3;
        const finalWaterCriticalConfirm = parseInt(document.getElementById('cfg-water-critical-confirm')?.value) || 2;
        const finalGnssWarningConfirm = parseInt(document.getElementById('cfg-gnss-warning-steps')?.value) || 3;
        const finalGnssCriticalConfirm = parseInt(document.getElementById('cfg-gnss-critical-steps')?.value) || 2;
        const finalImuCriticalConfirm = parseInt(document.getElementById('cfg-imu-critical-confirm')?.value) || 1;

        // ✅ THÊM OFFLINE THRESHOLDS VÀO CONFIG
        const offlineThresholds = {
            gnss: parseInt(document.getElementById('offline-gnss')?.value) || this.defaultOfflineThresholds.gnss,
            rain: parseInt(document.getElementById('offline-rain')?.value) || this.defaultOfflineThresholds.rain,
            water: parseInt(document.getElementById('offline-water')?.value) || this.defaultOfflineThresholds.water,
            imu: parseInt(document.getElementById('offline-imu')?.value) || this.defaultOfflineThresholds.imu
        };

        // ✅ ĐỌC GNSS RTK FORWARDING CONFIG
        const rtkForwarding = {
            enabled: !!document.getElementById('cfg-fwd-enabled')?.checked,
            host: document.getElementById('gnss-rtk-host')?.value?.trim() || '',
            port: parseInt(document.getElementById('gnss-rtk-port')?.value) || 1883,
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

        const l0Raw = document.getElementById('vn-l0')?.value;
        const l0Parsed = this.parseVn2000CentralMeridian(l0Raw);
        const l0Input = document.getElementById('vn-l0');
        if (l0Input) l0Input.value = Number(l0Parsed.value.toFixed(10));

        const vn2000 = {
            enabled: !!document.getElementById('vn2000-enabled')?.checked,
            dx: parseFloat(document.getElementById('vn-dx')?.value) || 191.90441429,
            dy: parseFloat(document.getElementById('vn-dy')?.value) || 39.30318279,
            dz: parseFloat(document.getElementById('vn-dz')?.value) || 111.45032835,
            rx: parseFloat(document.getElementById('vn-rx')?.value) || 0.00928836,
            ry: parseFloat(document.getElementById('vn-ry')?.value) || -0.01975479,
            rz: parseFloat(document.getElementById('vn-rz')?.value) || 0.00427372,
            k: parseFloat(document.getElementById('vn-k')?.value) || 0.999999747093722,
            l0_deg: l0Parsed.value,
            l0_raw: String(l0Raw ?? '').trim(),
            l0_input_format: l0Parsed.format,
            k0: parseFloat(document.getElementById('vn-k0')?.value) || 0.9999,
            res_b: parseFloat(document.getElementById('vn-resb')?.value) || 0.0,
            res_l: parseFloat(document.getElementById('vn-resl')?.value) || 0.0,
            res_h: parseFloat(document.getElementById('vn-resh')?.value) || 0.0,
            res_n: parseFloat(document.getElementById('vn-resn')?.value) || 0.0,
            res_e: parseFloat(document.getElementById('vn-rese')?.value) || 0.0
        };

        const stationMqtt = {
            host: document.getElementById('station-mqtt-host')?.value?.trim() || '',
            port: document.getElementById('station-mqtt-port')?.value ? parseInt(document.getElementById('station-mqtt-port').value) : null,
            use_tls: !!document.getElementById('station-mqtt-tls')?.checked,
            username: document.getElementById('station-mqtt-user')?.value?.trim() || '',
            password: document.getElementById('station-mqtt-pass')?.value?.trim() || ''
        };

        let gnssAicasterUser = { username: '', caster_host: '' };
        const aicasterValue = document.getElementById('cfg-gnss-aicaster-user')?.value;
        if (aicasterValue) {
            try {
                const selectedClient = JSON.parse(aicasterValue);
                gnssAicasterUser = {
                    username: String(selectedClient.username || '').trim(),
                    caster_host: String(selectedClient.caster_host || '').trim()
                };
            } catch (error) {
                console.error('Invalid AICaster client selection:', error);
            }
        }

        const config = {
            active_preset: this.activePreset || '',
            simulation_profile: {
                version: 1,
                cohesion_kpa: parseFloat(document.getElementById('sim-profile-cohesion')?.value || 15),
                friction_angle_deg: parseFloat(document.getElementById('sim-profile-friction')?.value || 30),
                unit_weight_kn_m3: parseFloat(document.getElementById('sim-profile-unit-weight')?.value || 18),
                slip_depth_m: parseFloat(document.getElementById('sim-profile-slip-depth')?.value || 5),
                slope_angle_deg: parseFloat(document.getElementById('sim-profile-slope')?.value || 25),
                saturated_conductivity_m_s: parseFloat(document.getElementById('sim-profile-ks')?.value || 0.000015),
                porosity: parseFloat(document.getElementById('sim-profile-porosity')?.value || 0.25),
                base_pore_pressure_ratio: parseFloat(document.getElementById('sim-profile-base-ru')?.value || 0),
                water_level_dry_m: parseFloat(document.getElementById('sim-profile-water-dry')?.value || 0),
                water_level_saturated_m: parseFloat(document.getElementById('sim-profile-water-saturated')?.value || 1),
                base_seismic_coeff: 0,
                house_count: parseInt(document.getElementById('sim-profile-houses')?.value || 40),
                tree_count: parseInt(document.getElementById('sim-profile-trees')?.value || 300),
            },
            alerting: {
                enabled: !document.getElementById('station-alerting-disabled')?.checked
            },
            offline_display: {
                enabled: !!document.getElementById('station-offline-display-enabled')?.checked
            },
            Water: {
                warning_threshold: parseFloat(document.getElementById('cfg-water-warning')?.value || 0),
                critical_threshold: parseFloat(document.getElementById('cfg-water-critical')?.value || 0),
                water_warning_confirm_steps: finalWaterWarningConfirm,
                water_critical_confirm_steps: finalWaterCriticalConfirm,
                water_confirm_steps: finalWaterWarningConfirm,
                water_safe_confirm_steps: parseInt(document.getElementById('cfg-water-safe-confirm')?.value) || 3
            },
            RainAlerting: {
                rain_intensity_watch_threshold: parseFloat(document.getElementById('cfg-rain-watch')?.value || 0),
                rain_intensity_warning_threshold: parseFloat(document.getElementById('cfg-rain-warning')?.value || 0),
                rain_intensity_critical_threshold: parseFloat(document.getElementById('cfg-rain-critical')?.value || 0),
                rain_warning_confirm_steps: finalRainWarningConfirm,
                rain_critical_confirm_steps: finalRainCriticalConfirm,
                rain_confirm_steps: finalRainWarningConfirm,
                rain_safe_confirm_steps: parseInt(document.getElementById('cfg-rain-safe-confirm')?.value) || 3
            },
            GnssAlerting: {
                gnss_max_hdop: parseFloat(document.getElementById('cfg-gnss-hdop')?.value || 4.0),
                gnss_warning_confirm_steps: finalGnssWarningConfirm,
                gnss_critical_confirm_steps: finalGnssCriticalConfirm,
                gnss_confirm_steps: finalGnssWarningConfirm,
                gnss_safe_confirm_steps: parseInt(document.getElementById('cfg-gnss-safe-steps')?.value) || 5,
                gnss_degraded_timeout: parseInt(document.getElementById('cfg-gnss-timeout')?.value || 300)
            },
            ImuAlerting: {
                tilt_critical_deg: parseFloat(document.getElementById('cfg-imu-tilt-crit')?.value || 15.0),
                tilt_warning_deg: parseFloat(document.getElementById('cfg-imu-tilt-crit')?.value || 15.0),
                imu_warning_confirm_steps: finalImuCriticalConfirm,
                imu_critical_confirm_steps: finalImuCriticalConfirm,
                imu_confirm_steps: finalImuCriticalConfirm,
                imu_safe_confirm_steps: parseInt(document.getElementById('cfg-imu-safe-confirm')?.value) || 3,
                shock_threshold_ms2: parseFloat(document.getElementById('cfg-imu-shock')?.value || 5.0)
            },
            ImuBaseline: {
                baseline_roll: parseFloat(document.getElementById('cfg-imu-base-roll')?.value) || 0.0,
                baseline_pitch: parseFloat(document.getElementById('cfg-imu-base-pitch')?.value) || 0.0,
                baseline_yaw: parseFloat(document.getElementById('cfg-imu-base-yaw')?.value) || 0.0
            },
            gnss_origin: {
                lat: document.getElementById('origin-lat')?.value || null,
                lon: document.getElementById('origin-lon')?.value || null,
                h: document.getElementById('origin-h')?.value || 0
            },
            rain_origin: {
                lat: document.getElementById('origin-rain-lat')?.value !== '' ? document.getElementById('origin-rain-lat').value : undefined,
                lon: document.getElementById('origin-rain-lon')?.value !== '' ? document.getElementById('origin-rain-lon').value : undefined,
                h: document.getElementById('origin-rain-h')?.value !== '' ? document.getElementById('origin-rain-h').value : undefined
            },
            water_origin: {
                lat: document.getElementById('origin-water-lat')?.value !== '' ? document.getElementById('origin-water-lat').value : undefined,
                lon: document.getElementById('origin-water-lon')?.value !== '' ? document.getElementById('origin-water-lon').value : undefined,
                h: document.getElementById('origin-water-h')?.value !== '' ? document.getElementById('origin-water-h').value : undefined
            },
            imu_origin: {
                lat: document.getElementById('origin-imu-lat')?.value !== '' ? document.getElementById('origin-imu-lat').value : undefined,
                lon: document.getElementById('origin-imu-lon')?.value !== '' ? document.getElementById('origin-imu-lon').value : undefined,
                h: document.getElementById('origin-imu-h')?.value !== '' ? document.getElementById('origin-imu-h').value : undefined
            },
            velocity_classification: this.velocityConfig,
            offline_thresholds: offlineThresholds,
            gnss_aicaster_user: gnssAicasterUser,
            gnss_rtk_forwarding: rtkForwarding,
            vn2000: vn2000,
            vn2000_params: vn2000,
            mqtt: stationMqtt,
            save_intervals: {
                gnss: (document.getElementById('edit-gnss')?.checked && document.getElementById('cfg-station-save-gnss')?.value) ? parseInt(document.getElementById('cfg-station-save-gnss').value) : null,
                rain: (document.getElementById('edit-rain')?.checked && document.getElementById('cfg-station-save-rain')?.value) ? parseInt(document.getElementById('cfg-station-save-rain').value) : null,
                water: (document.getElementById('edit-water')?.checked && document.getElementById('cfg-station-save-water')?.value) ? parseInt(document.getElementById('cfg-station-save-water').value) : null,
                imu: (document.getElementById('edit-imu')?.checked && document.getElementById('cfg-station-save-imu')?.value) ? parseInt(document.getElementById('cfg-station-save-imu').value) : null
            }
        };


        const payload = {
            station_code: code,
            name: name,
            sensors: sensors,
            config: config,
            location: null
        };

        console.log('💾 [SAVE] isEditMode:', this.isEditMode, 'stationId:', this.currentStationId);
        console.log('💾 [SAVE] Payload:', JSON.stringify(payload, null, 2));

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
            window.toast?.error('❌ Lỗi xóa trạm');
        }
    }

    async resetGnssOrigin(stationId) {
        if (!stationId || Number.isNaN(Number(stationId))) {
            window.toast?.warning('Hãy lưu trạm trước khi hiệu chuẩn offset GNSS');
            return;
        }
        if (!confirm('Thu mẫu RTK FIXED ổn định trong 60 giây để hiệu chuẩn offset? Tọa độ gốc sẽ được giữ nguyên.')) return;

        const resetBtn = document.getElementById('btn-reset-origin');
        const statusEl = document.getElementById('origin-status');
        try {
            if (resetBtn) resetBtn.disabled = true;
            this._gnssCalibrationInProgress = true;
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
                if (res.status === 401) {
                    await window.authManager?.handleUnauthorizedResponse?.('gnss-calibration');
                    throw new Error('Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại');
                }
                if (res.status === 403) {
                    throw new Error('Tài khoản không có quyền hiệu chuẩn trạm này');
                }
                throw new Error(data.detail || `Backend trả về HTTP ${res.status}`);
            }

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
        } catch (e) {
            window.toast?.error('Offset calibration failed: ' + e.message);
        } finally {
            this._gnssCalibrationInProgress = false;
            if (resetBtn) resetBtn.disabled = false;
        }
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
        const fetchBtn = document.getElementById('btn-fetch-origin');
        if (resetBtn) resetBtn.style.display = hasOrigin ? 'inline-block' : 'none';
        if (fetchBtn) fetchBtn.style.display = 'inline-block';
    }

}
window.applyAdminFeature(AdminStationPresetsFeature);
})();
