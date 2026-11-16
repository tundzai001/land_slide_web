/**
 * simulation-controller.js
 * ========================
 * Main entry point & orchestrator for the Slide model Digital Twin.
 * Bootstraps Three.js scene, terrain, environment, physics, particles, weather.
 * Manages simulation states: STABLE → WARNING → CRITICAL → SLIDING → DEPOSITED.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { SceneManager } from './scene-manager.js?v=20260428v3';
import { TerrainGenerator } from './terrain-generator.js?v=20260428v3';
import { EnvironmentBuilder } from './environment-builder.js?v=20260428v3';
import { PhysicsEngine } from './physics-engine.js?v=20260428v3';
import { DestructionSystem } from './destruction-system.js?v=20260428v3';
import { ParticleSystem } from './particle-system.js?v=20260428v3';
import { WeatherSystem } from './weather-system.js?v=20260428v3';

// ─── Simulation States ───
const SimState = {
    STABLE: 'STABLE',
    WARNING: 'WARNING',
    CRITICAL: 'CRITICAL',
    SLIDING: 'SLIDING',
    DEPOSITED: 'DEPOSITED'
};

class SimulationController {
    constructor() {
        // DOM refs
        this.canvas = document.getElementById('dt-canvas');
        this.viewport = document.getElementById('dt-viewport');
        this.loadingEl = document.getElementById('dt-loading');

        // State
        this.state = SimState.STABLE;
        this.isRunning = false;
        this.isPaused = false;
        this.simTime = 0;          // seconds of sim elapsed
        this.simSpeed = 5;
        this.maxSimTime = 86400;   // 24 hours of real-world time (seconds)
        this.inputMode = 'manual';
        this.stationData = null;
        this.currentRun = null;
        this.resultSeries = null;
        this._backendPending = false;
        // Time scale: how many real-world seconds pass per 1 wall-clock second
        // At 1x: 1 wall-second = 60 real-seconds (1 minute)
        // At 10x: 1 wall-second = 600 real-seconds (10 minutes) 
        this.timeScaleBase = 60; // Base: 1x = 60 real-seconds per wall-second

        // Physics params (from UI)
        this.params = {
            cohesion: 15,         // kPa
            frictionAngle: 30,    // degrees
            unitWeight: 18,       // kN/m³
            slipDepth: 5,         // m
            slopeAngle: 25,       // degrees
            rainfall: 0,          // mm/h
            porePressureRatio: 0, // ru (0-0.6)
            seismicCoeff: 0,      // kh
            houseCount: 40,
            treeCount: 300,
            ks: 1.5e-5,           // Saturated conductivity
            porosity: 0.25        // n
        };

        // Stats
        this.damageStats = {
            housesDestroyed: 0,
            treesDestroyed: 0,
            velocity: 0,
            volume: 0
        };

        // Custom thresholds
        this.fosThresholds = {
            warning: 1.5,
            critical: 1.0
        };

        // Sub-systems (initialized in init())
        this.sceneManager = null;
        this.terrainGen = null;
        this.envBuilder = null;
        this.physics = null;
        this.destruction = null;
        this.particles = null;
        this.weather = null;

        this.clock = new THREE.Clock();
    }

    async init() {
        try {
            // 1) Scene, Camera, Renderer, Post-processing
            this.sceneManager = new SceneManager(this.canvas, this.viewport);

            // 2) Terrain
            this.terrainGen = new TerrainGenerator(this.sceneManager.scene);
            this.terrainGen.generate();

            // 3) Environment (houses, trees, roads)
            this.envBuilder = new EnvironmentBuilder(
                this.sceneManager.scene,
                this.terrainGen,
                this.params.houseCount,
                this.params.treeCount
            );
            this.envBuilder.build();

            // 4) Physics Engine
            this.physics = new PhysicsEngine(this.terrainGen);

            // 5) Destruction System
            this.destruction = new DestructionSystem(
                this.sceneManager.scene,
                this.envBuilder
            );

            // 6) Particle System (debris, dust)
            this.particles = new ParticleSystem(this.sceneManager.scene);

            // 7) Weather System (rain, fog, skybox)
            this.weather = new WeatherSystem(this.sceneManager.scene, this.sceneManager.renderer);

            // Bind UI
            this._bindUI();

            this._isInitialized = true;
            
            // Hide loading
            setTimeout(() => {
                if (this.loadingEl) this.loadingEl.classList.add('hidden');
            }, 800);

        } catch (err) {
            console.error('Digital Twin init error:', err);
            document.querySelector('.dt-loading-text').textContent = 'Lỗi: ' + err.message;
        }
    }

    // ─── UI BINDING ─────────────────────────────────────────────────
    _bindUI() {
        // Sliders → params
        const sliderMap = {
            'param-cohesion':      { key: 'cohesion',           output: 'val-cohesion' },
            'param-friction':      { key: 'frictionAngle',      output: 'val-friction' },
            'param-unit-weight':   { key: 'unitWeight',         output: 'val-unit-weight' },
            'param-slip-depth':    { key: 'slipDepth',          output: 'val-slip-depth' },
            'param-slope-angle':   { key: 'slopeAngle',         output: 'val-slope-angle' },
            'param-rainfall':      { key: 'rainfall',           output: 'val-rainfall' },
            'param-pore-pressure': { key: 'porePressureRatio',  output: 'val-pore-pressure' },
            'param-seismic':       { key: 'seismicCoeff',       output: 'val-seismic' },
            'param-houses':        { key: 'houseCount',         output: 'val-houses' },
            'param-trees':         { key: 'treeCount',          output: 'val-trees' },
            'param-ks':            { key: 'ks',                 output: 'val-ks', scale: 1e-5 },
            'param-porosity':      { key: 'porosity',           output: 'val-porosity' },
        };

        const thresholdMap = {
            'param-fos-warning':  { key: 'warning', output: 'val-fos-warning' },
            'param-fos-critical': { key: 'critical', output: 'val-fos-critical' }
        };

        for (const [sliderId, cfg] of Object.entries(sliderMap)) {
            const el = document.getElementById(sliderId);
            const out = document.getElementById(cfg.output);
            if (!el) continue;

            el.addEventListener('input', () => {
                const val = Number.parseFloat(el.value);
                this.params[cfg.key] = cfg.scale ? val * cfg.scale : val;
                if (out) out.textContent = val;

                // Live update FoS when not sliding
                if (!this.isRunning || this.state === SimState.STABLE) {
                    this._updateFoS();
                }

                // Live update weather
                if (cfg.key === 'rainfall') {
                    this.weather.setRainIntensity(val / 200); // 0–1
                }

                // Live update environment and terrain
                if (cfg.key === 'houseCount' || cfg.key === 'treeCount' || cfg.key === 'slopeAngle') {
                    if (cfg.key === 'houseCount') this.envBuilder.houseCount = val;
                    if (cfg.key === 'treeCount') this.envBuilder.treeCount = val;

                    if (!this.isRunning || this.state === SimState.STABLE) {
                        
                        if (cfg.key === 'slopeAngle') {
                            this.terrainGen.slopeAngle = val;
                            // Remove old terrain mesh
                            if (this.terrainGen.mesh) {
                                this.sceneManager.scene.remove(this.terrainGen.mesh);
                                this.terrainGen.geometry.dispose();
                                this.terrainGen.mesh.material.dispose();
                            }
                            this.terrainGen.generate(); // Assuming generate() recreates it
                            // Need to update physics engine references if any, but physics reads from terrainGen dynamically
                        }

                        this.envBuilder.clear();
                        this.envBuilder.build();
                        
                        // Clean up old destruction fragments
                        this.destruction.fragments.forEach(f => {
                            if (f.mesh) this.sceneManager.scene.remove(f.mesh);
                        });
                        this.destruction.fragments = [];
                    }
                }
            });
        }

        // Threshold Sliders
        for (const [sliderId, cfg] of Object.entries(thresholdMap)) {
            const el = document.getElementById(sliderId);
            const out = document.getElementById(cfg.output);
            if (!el) continue;

            el.addEventListener('input', () => {
                const val = Number.parseFloat(el.value);
                this.fosThresholds[cfg.key] = val;
                if (out) out.textContent = val.toFixed(1);

                if (!this.isRunning || this.state === SimState.STABLE) {
                    this._updateFoS();
                }
            });
        }

        // Duration selector
        const durationEl = document.getElementById('param-sim-duration');
        if (durationEl) {
            durationEl.addEventListener('change', () => {
                this.maxSimTime = Number.parseInt(durationEl.value);
                const durationOut = document.getElementById('val-sim-duration');
                if (durationOut) {
                    const h = Math.round(this.maxSimTime / 3600);
                    durationOut.textContent = h + 'h';
                }
            });
        }

        // Run / Stop button
        const btnRun = document.getElementById('btn-run-simulation');
        btnRun.addEventListener('click', () => {
            if (this.isRunning || this._backendPending) {
                this.stop();
            } else {
                void this.start();
            }
        });

        // Reset button
        document.getElementById('btn-reset-simulation').addEventListener('click', () => {
            this.reset();
        });

        // Play/Pause timeline
        document.getElementById('btn-tl-play').addEventListener('click', () => {
            if (!this.isRunning) return;
            this.isPaused = !this.isPaused;
            const icon = document.querySelector('#btn-tl-play i');
            icon.className = this.isPaused ? 'bi bi-play-fill' : 'bi bi-pause-fill';
        });

        // Speed selector
        document.getElementById('tl-speed').addEventListener('change', (e) => {
            this.simSpeed = Number.parseInt(e.target.value);
        });

        // Toggle panel
        document.getElementById('btn-toggle-panel').addEventListener('click', () => {
            const panel = document.getElementById('dt-panel');
            panel.classList.toggle('dt-panel-open');
            panel.classList.toggle('dt-panel-closed');
            // Resize renderer
            setTimeout(() => this.sceneManager.onResize(), 350);
        });

        // Close overlay
        const btnClose = document.getElementById('btn-close-dt');
        if (btnClose) {
            btnClose.addEventListener('click', () => {
                window.closeDigitalTwin();
            });
        }

        // Fullscreen
        const btnFullscreen = document.getElementById('btn-fullscreen-dt');
        if (btnFullscreen) {
            btnFullscreen.addEventListener('click', () => {
                const container = document.getElementById('dt-overlay-container');
                if (!document.fullscreenElement) {
                    container.requestFullscreen().catch(err => console.log(err));
                } else {
                    void document.exitFullscreen();
                }
            });
        }

        // Close report modal
        const btnCloseReport = document.getElementById('btn-close-report');
        if (btnCloseReport) {
            btnCloseReport.addEventListener('click', () => {
                document.getElementById('dt-report-overlay').style.display = 'none';
            });
        }

        document.querySelectorAll('[data-simulation-mode]').forEach(button => {
            button.addEventListener('click', () => this._setInputMode(button.dataset.simulationMode));
        });
        document.getElementById('btn-dt-live-evaluate')?.addEventListener('click', () => this._evaluateLive());
        document.getElementById('btn-dt-history')?.addEventListener('click', () => this._showHistory());
        document.getElementById('btn-close-dt-results')?.addEventListener('click', () => this._toggleResults(false));

        // Initial FoS
        this._updateFoS();
        this._setRunUi('ready', 'Sẵn sàng chạy mô phỏng');
    }

    _setRunUi(state, message) {
        const card = document.getElementById('dt-run-card');
        const status = document.getElementById('dt-run-status-text');
        const statusIcon = card?.querySelector('.dt-run-status-line i');

        if (card) card.dataset.state = state;
        if (status) status.textContent = message;
        if (statusIcon) {
            statusIcon.className = state === 'running'
                ? 'bi bi-arrow-repeat'
                : state === 'complete'
                    ? 'bi bi-check-circle-fill'
                    : 'bi bi-circle-fill';
        }
    }

    _setRunButton(running) {
        const btnRun = document.getElementById('btn-run-simulation');
        if (!btnRun) return;
        btnRun.innerHTML = running
            ? '<i class="bi bi-stop-fill"></i> Dừng mô phỏng'
            : '<i class="bi bi-play-fill"></i> Chạy mô phỏng';
        btnRun.classList.toggle('running', running);
    }

    // ─── FoS CALCULATION ────────────────────────────────────────────
    _updateFoS() {
        const fos = this.physics.calculateFoS(this.params);
        this._displayFoS(fos);
        return fos;
    }

    _displayFoS(fos) {
        const clampedFos = Math.max(0, Math.min(fos, 3));
        const displayVal = fos.toFixed(2);

        // Gauge arc (326.73 = circumference for r=52)
        const circumference = 326.73;
        const ratio = Math.min(clampedFos / 3, 1);
        const offset = circumference * (1 - ratio);

        const gaugeArc = document.getElementById('fos-gauge-arc');
        const gaugeVal = document.getElementById('fos-gauge-value');
        const gaugeStatus = document.getElementById('fos-gauge-status');
        const fosHeader = document.getElementById('fos-value-header');
        const badge = document.getElementById('sim-status-badge');

        if (gaugeArc) gaugeArc.style.strokeDashoffset = offset;
        if (gaugeVal) gaugeVal.textContent = displayVal;
        if (fosHeader) fosHeader.textContent = displayVal;

        // Color based on FoS
        let color, statusText, statusClass;
        if (fos >= this.fosThresholds.warning) {
            color = '#10b981'; statusText = 'ỔN ĐỊNH'; statusClass = '';
        } else if (fos >= this.fosThresholds.critical) {
            color = '#f59e0b'; statusText = 'CẢNH BÁO'; statusClass = 'warning';
        } else {
            color = '#f43f5e'; statusText = 'NGUY HIỂM'; statusClass = 'critical';
        }

        if (gaugeArc) gaugeArc.style.stroke = color;
        if (gaugeArc) gaugeArc.style.filter = `drop-shadow(0 0 8px ${color}80)`;
        if (gaugeVal) { gaugeVal.style.color = color; gaugeVal.style.textShadow = `0 0 12px ${color}60`; }
        if (fosHeader) { fosHeader.style.color = color; fosHeader.style.textShadow = `0 0 10px ${color}60`; }
        if (gaugeStatus) {
            gaugeStatus.textContent = statusText;
            gaugeStatus.style.color = color;
            gaugeStatus.style.borderColor = `${color}50`;
            gaugeStatus.style.background = `${color}15`;
        }
        if (badge) {
            badge.className = 'dt-status-badge ' + statusClass;
            badge.querySelector('.dt-status-text').textContent = statusText;
        }
    }

    // ─── SIMULATION CONTROL ─────────────────────────────────────────
    async start() {
        if (this._backendPending) return;
        if (this.inputMode === 'station_snapshot' && !this.stationData?.id) {
            this._setRunUi('stopped', 'Hãy chọn một trạm trên bản đồ trước khi chạy');
            return;
        }
        this.isRunning = false;
        this.isPaused = false;
        this.resultSeries = null;
        this._backendPending = true;
        this._setRunButton(true);
        this._setRunUi('running', 'Backend đang tính chuỗi diễn biến…');
        try {
            const duration = Number(document.getElementById('param-sim-duration')?.value || 86400);
            const payload = {
                mode: this.inputMode,
                station_id: this.inputMode === 'station_snapshot' ? this.stationData.id : null,
                duration_hours: Math.round(duration / 3600),
                parameters: this._backendParameters(),
            };
            const response = await this._api('/api/simulations/runs', { method: 'POST', body: JSON.stringify(payload) });
            this.currentRun = response;
            await this._pollRun(response.id);
        } catch (error) {
            console.error('[SIMULATION] backend run failed:', error);
            this._setRunUi('stopped', `Không chạy được: ${error.message}`);
            this._setRunButton(false);
        } finally {
            this._backendPending = false;
        }
    }

    stop() {
        if (this._backendPending && this.currentRun?.id) {
            void this._api(`/api/simulations/runs/${this.currentRun.id}/stop`, { method: 'POST' }).catch(() => {});
        }
        this._backendPending = false;
        this.isRunning = false;
        this.isPaused = false;
        this.state = SimState.STABLE;

        this._setRunButton(false);
        this._setRunUi('stopped', 'Đã dừng — có thể chỉnh tham số và chạy lại');

        document.getElementById('dt-warning-overlay').style.display = 'none';
        document.getElementById('dt-damage-stats').style.display = 'none';
        const reportOverlay = document.getElementById('dt-report-overlay');
        if (reportOverlay) reportOverlay.style.display = 'none';
        this.viewport.classList.remove('camera-shake');
    }

    reset() {
        this.stop();
        this.simTime = 0;
        this.physics.reset();

        // Reset sliders to defaults
        const defaults = {
            'param-cohesion': 15, 'param-friction': 30, 'param-unit-weight': 18,
            'param-slip-depth': 5, 'param-slope-angle': 25, 'param-rainfall': 0,
            'param-pore-pressure': 0, 'param-seismic': 0,
            'param-houses': 40, 'param-trees': 300,
            'param-fos-warning': 1.5, 'param-fos-critical': 1.0,
            'param-ks': 1.5, 'param-porosity': 0.25
        };
        for (const [id, val] of Object.entries(defaults)) {
            const el = document.getElementById(id);
            if (el) { el.value = val; el.dispatchEvent(new Event('input')); }
        }

        // Rebuild environment
        this.envBuilder.clear();
        this.envBuilder.build();
        this.particles.reset();
        this.destruction.reset();
        this.weather.setRainIntensity(0);
        this._totalDisplacement = 0;
        this.resultSeries = null;
        this.currentRun = null;
        this._toggleResults(false);
        this.terrainGen.deformTerrain(0); // Reset terrain shape

        // Reset timeline
        document.getElementById('tl-progress').style.width = '0%';
        document.getElementById('tl-time').textContent = '00h00m';

        this._updateFoS();
        this._setRunUi('ready', 'Đã đặt lại — sẵn sàng chạy mô phỏng');
    }

    // ─── MAIN ANIMATION LOOP ────────────────────────────────────────
    _animate() {
        if (!this._isInitialized) return;
        this._animationFrameId = requestAnimationFrame(() => this._animate());

        const delta = this.clock.getDelta();
        const elapsed = this.clock.getElapsedTime();

        // Update sub-systems
        this.sceneManager.update(delta, elapsed);
        this.weather.update(delta);
        this.particles.update(delta);

        // Simulation logic
        if (this.isRunning && !this.isPaused) {
            this._simulationStep(delta);
        }

        // Render
        this.sceneManager.render();
    }

    // ─── SIMULATION STEP ────────────────────────────────────────────
    _simulationStep(delta) {
        if (this.resultSeries?.length) {
            this._playbackStep(delta);
            return;
        }
        // Real-world dt: timeScaleBase * simSpeed * wall-clock delta
        // e.g. at 5x speed: 60 * 5 = 300 real-seconds per wall-second
        const realDt = delta * this.timeScaleBase * this.simSpeed;
        
        // Sub-stepping for numerical stability (max 30s per sub-step)
        const maxSubDt = 30;
        const numSteps = Math.max(1, Math.ceil(realDt / maxSubDt));
        const subDt = realDt / numSteps;
        
        for (let step = 0; step < numSteps; step++) {
            this.simTime += subDt;
            this._simulationSubStep(subDt);
        }

        // Update timeline UI
        const progress = Math.min(this.simTime / this.maxSimTime * 100, 100);
        document.getElementById('tl-progress').style.width = progress + '%';
        
        // Display as HH:MM (real-world hours)
        const totalHours = this.simTime / 3600;
        const hrs = Math.floor(totalHours);
        const mins = Math.floor((totalHours - hrs) * 60);
        document.getElementById('tl-time').textContent =
            String(hrs).padStart(2, '0') + 'h' + String(mins).padStart(2, '0') + 'm';

        // Auto-stop when reaching the time limit
        if (this.simTime >= this.maxSimTime) {
            this.isRunning = false;
            this.isPaused = false;
            const playIcon = document.querySelector('#btn-tl-play i');
            if (playIcon) playIcon.className = 'bi bi-play-fill';
            this._setRunButton(false);
            this._setRunUi('complete', 'Mô phỏng đã hoàn tất theo thời lượng đã chọn');
        }
    }

    _simulationSubStep(dt) {

        // ── Phase 1: Build up pore pressure from rainfall (Green-Ampt Infiltration) ──
        if (this.params.rainfall > 0) {
            const infiltrationRu = this.physics.calculateInfiltration(
                this.params.rainfall, 
                dt, 
                this.params.slipDepth,
                this.params.ks,
                this.params.porosity
            );
            
            const totalRu = Math.min(
                (this.params.porePressureRatio || 0) + infiltrationRu,
                0.6
            );

            // Update the pore pressure display
            const poreOutput = document.getElementById('val-pore-pressure');
            if (poreOutput) poreOutput.textContent = totalRu.toFixed(2);
            
            // Use combined ru for FoS
            this.params._effectiveRu = totalRu;
        } else {
            this.params._effectiveRu = this.params.porePressureRatio || 0;
        }

        // ── Calculate FoS ──
        const fos = this.physics.calculateFoS({
            ...this.params,
            porePressureRatio: this.params._effectiveRu || this.params.porePressureRatio
        });
        this._displayFoS(fos);

        // ── State transitions ──
        if (this.state === SimState.STABLE || this.state === SimState.WARNING || this.state === SimState.CRITICAL) {
            if (fos >= this.fosThresholds.warning) {
                this.state = SimState.STABLE;
            } else if (fos >= this.fosThresholds.critical) {
                this.state = SimState.WARNING;
            } else {
                this.state = SimState.CRITICAL;
                // After ~2 seconds in critical → trigger sliding
                if (!this._criticalTimer) this._criticalTimer = 0;
                this._criticalTimer += dt;
                if (this._criticalTimer > 2) {
                    this.state = SimState.SLIDING;
                    this._slideStartTime = this.simTime;
                    this._criticalTimer = 0;
                }
            }
        }

        // ── Visual effects per state ──
        const warningOverlay = document.getElementById('dt-warning-overlay');
        const damageStats = document.getElementById('dt-damage-stats');

        if (this.state === SimState.WARNING) {
            warningOverlay.style.display = 'none';
            this.viewport.classList.remove('camera-shake');
            // Terrain cracks (visual hint)
            this.terrainGen.setStressLevel(0.3);
        }

        if (this.state === SimState.CRITICAL) {
            warningOverlay.style.display = 'flex';
            document.getElementById('dt-warning-fos').textContent = `FoS = ${fos.toFixed(2)}`;
            this.viewport.classList.add('camera-shake');
            this.terrainGen.setStressLevel(0.7);
        }

        if (this.state === SimState.SLIDING) {
            warningOverlay.style.display = 'none';
            damageStats.style.display = 'block';
            this.viewport.classList.add('camera-shake');
            this.terrainGen.setStressLevel(1.0);

            // Run landslide physics
            const slideElapsed = this.simTime - this._slideStartTime;
            const motion = this.physics.calculateSlideMotion(this.params, slideElapsed, dt);

            this.damageStats.velocity = motion.velocity;
            this.damageStats.volume = motion.volume;
            
            if (!this._maxVelocity || motion.velocity > this._maxVelocity) {
                this._maxVelocity = motion.velocity;
            }
            
            // Accumulate displacement for terrain deformation
            if (!this._totalDisplacement) this._totalDisplacement = 0;
            this._totalDisplacement += motion.velocity * dt;
            this.terrainGen.deformTerrain(this._totalDisplacement);

            // Move debris
            this.particles.emitDebris(motion.frontPosition, motion.velocity, dt);

            // Check destruction
            const destroyed = this.destruction.checkCollisions(
                motion.frontPosition,
                motion.width,
                motion.kineticEnergy
            );
            this.damageStats.housesDestroyed += destroyed.houses;
            this.damageStats.treesDestroyed += destroyed.trees;

            // Dust clouds
            if (motion.velocity > 2) {
                this.particles.emitDust(motion.frontPosition, motion.velocity);
            }

            // Update damage display
            document.getElementById('dmg-houses').textContent = this.damageStats.housesDestroyed;
            document.getElementById('dmg-trees').textContent = this.damageStats.treesDestroyed;
            document.getElementById('dmg-velocity').textContent = motion.velocity.toFixed(1);
            document.getElementById('dmg-volume').textContent = Math.round(motion.volume);

            // After debris stops or max slide time (5 min real-world)
            if (motion.velocity < 0.1 || slideElapsed > 300) {
                this.state = SimState.DEPOSITED;
                this.viewport.classList.remove('camera-shake');
            }
        }

        if (this.state === SimState.DEPOSITED) {
            // Final state — keep damage stats visible
            const badge = document.getElementById('sim-status-badge');
            badge.className = 'dt-status-badge';
            badge.querySelector('.dt-status-text').textContent = 'KẾT THÚC';

            // Show report modal once
            if (!this._reportShown) {
                this._reportShown = true;
                const reportOverlay = document.getElementById('dt-report-overlay');
                if (reportOverlay) {
                    reportOverlay.style.display = 'flex';
                    const slideElapsed = this.simTime - (this._slideStartTime || 0);
                    document.getElementById('rep-time').textContent = slideElapsed.toFixed(1);
                    document.getElementById('rep-vel').textContent = (this._maxVelocity || this.damageStats.velocity).toFixed(1);
                    document.getElementById('rep-vol').textContent = Math.round(this.damageStats.volume);
                    document.getElementById('rep-house').textContent = this.damageStats.housesDestroyed;
                    document.getElementById('rep-tree').textContent = this.damageStats.treesDestroyed;
                }
            }
        }

        // Reset critical timer if we're no longer critical
        if (this.state !== SimState.CRITICAL) {
            this._criticalTimer = 0;
        }
    }

    _backendParameters() {
        if (this.inputMode === 'station_snapshot') return {};
        return {
            cohesion: this.params.cohesion, friction_angle: this.params.frictionAngle,
            unit_weight: this.params.unitWeight, slip_depth: this.params.slipDepth,
            slope_angle: this.params.slopeAngle, rainfall: this.params.rainfall,
            pore_pressure_ratio: this.params.porePressureRatio, seismic_coeff: this.params.seismicCoeff,
            house_count: this.params.houseCount, tree_count: this.params.treeCount,
            ks: this.params.ks, porosity: this.params.porosity,
            fos_warning: this.fosThresholds.warning, fos_critical: this.fosThresholds.critical,
        };
    }

    async _api(url, options = {}) {
        const headers = new Headers(options.headers || {});
        if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
        const response = window.apiClient
            ? await window.apiClient(url, { ...options, headers, timeout: 30000 })
            : await fetch(url, { ...options, headers });
        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            throw new Error(body.detail || `HTTP ${response.status}`);
        }
        return response.json();
    }

    async _pollRun(runId) {
        while (this._backendPending) {
            const run = await this._api(`/api/simulations/runs/${runId}`, { requestKey: `simulation-${runId}` });
            this.currentRun = run;
            this._setRunUi('running', run.status === 'queued' ? 'Đang chờ bộ tính toán…' : `Đang tính toán · ${run.progress || 0}%`);
            if (!['queued', 'running'].includes(run.status)) {
                if (run.status === 'completed') this._loadResult(run);
                else {
                    this._setRunButton(false);
                    this._setRunUi('stopped', run.error || `Lần chạy kết thúc với trạng thái ${run.status}`);
                    this._renderResults(run);
                    this._toggleResults(true);
                }
                return;
            }
            await new Promise(resolve => setTimeout(resolve, 500));
        }
    }

    _setInputMode(mode) {
        this.inputMode = mode === 'station_snapshot' ? 'station_snapshot' : 'manual';
        document.querySelectorAll('[data-simulation-mode]').forEach(button => button.classList.toggle('active', button.dataset.simulationMode === this.inputMode));
        const stationSource = document.getElementById('dt-station-source');
        if (stationSource) stationSource.hidden = this.inputMode !== 'station_snapshot';
        document.querySelectorAll('#dt-panel input, #dt-panel select').forEach(field => {
            if (field.id === 'param-sim-duration') return;
            field.disabled = this.inputMode === 'station_snapshot';
        });
        this._updateStationContext();
    }

    _updateStationContext() {
        const name = this.stationData ? `${this.stationData.name || 'Trạm'} · ${this.stationData.code || ''}` : 'Chưa chọn trạm';
        const sourceName = document.getElementById('dt-source-name');
        const sourceFreshness = document.getElementById('dt-source-freshness');
        if (sourceName) sourceName.textContent = name;
        if (sourceFreshness) sourceFreshness.textContent = this.stationData ? 'Backend sẽ chụp dữ liệu mới nhất khi bấm chạy' : 'Chọn một trạm trên bản đồ trước khi chạy';
        const context = document.getElementById('dt-station-context');
        const detail = document.getElementById('dt-station-context-detail');
        if (context) context.textContent = this.inputMode === 'station_snapshot' ? name : 'Kịch bản độc lập';
        if (detail) detail.textContent = this.inputMode === 'station_snapshot' ? 'Thông số cảm biến được xác thực tại backend' : 'Các giá trị đang được nhập thủ công';
    }

    async _evaluateLive() {
        const target = document.getElementById('dt-live-result');
        if (!this.stationData?.id) {
            if (target) target.textContent = 'Chưa chọn trạm.';
            return;
        }
        if (target) target.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Đang đọc cảm biến…';
        try {
            const result = await this._api(`/api/simulations/stations/${this.stationData.id}/evaluation`, { requestKey: 'simulation-live' });
            if (target) {
                const warnText = result.warnings.length ? `${result.warnings.length} cảnh báo dữ liệu` : 'Dữ liệu đủ để đánh giá';
                target.innerHTML = `<strong>FoS ${Number(result.fos).toFixed(2)} · ${this._escape(result.classification)}</strong><small>${this._escape(warnText)}</small>`;
            }
            this._displayFoS(Number(result.fos));
        } catch (error) {
            if (target) target.textContent = error.message;
        }
    }

    _loadResult(run) {
        this.currentRun = run;
        this.resultSeries = run.time_series || [];
        this.maxSimTime = Number(run.duration_seconds || run.time_series?.at(-1)?.time_s || 86400);
        this.simTime = 0;
        this.state = SimState.STABLE;
        this.isRunning = this.resultSeries.length > 0;
        this.isPaused = false;
        this._setRunButton(this.isRunning);
        this._setRunUi('complete', 'Backend đã tính xong · đang phát lại kết quả');
        this._renderResults(run);
        this._toggleResults(true);
        const icon = document.querySelector('#btn-tl-play i');
        if (icon) icon.className = 'bi bi-pause-fill';
    }

    _playbackStep(delta) {
        this.simTime = Math.min(this.maxSimTime, this.simTime + delta * this.timeScaleBase * this.simSpeed);
        let index = Math.floor(this.simTime / this.maxSimTime * Math.max(0, this.resultSeries.length - 1));
        while (index + 1 < this.resultSeries.length && this.resultSeries[index + 1].time_s <= this.simTime) index += 1;
        const row = this.resultSeries[Math.min(index, this.resultSeries.length - 1)];
        if (!row) return;
        this._displayFoS(Number(row.fos));
        this.state = SimState[row.state] || SimState.STABLE;
        document.getElementById('tl-progress').style.width = `${Math.min(100, this.simTime / this.maxSimTime * 100)}%`;
        const hours = Math.floor(this.simTime / 3600);
        const minutes = Math.floor((this.simTime % 3600) / 60);
        document.getElementById('tl-time').textContent = `${String(hours).padStart(2, '0')}h${String(minutes).padStart(2, '0')}m`;
        const damage = document.getElementById('dt-damage-stats');
        if (damage) damage.style.display = ['SLIDING', 'DEPOSITED'].includes(row.state) ? 'block' : 'none';
        const values = { 'dmg-houses': row.houses_affected, 'dmg-trees': row.trees_affected, 'dmg-velocity': Number(row.velocity_m_s).toFixed(1), 'dmg-volume': Math.round(row.volume_m3) };
        Object.entries(values).forEach(([id, value]) => { const element = document.getElementById(id); if (element) element.textContent = value; });
        if (row.state === 'SLIDING') {
            const angle = (this.currentRun.parameters?.slope_angle || 25) * Math.PI / 180;
            const x = -30 + Number(row.runout_m) * Math.cos(angle);
            const front = new THREE.Vector3(x, this.terrainGen.getHeightAt(x, 0) + 1, 0);
            this.particles.emitDebris(front, Number(row.velocity_m_s), Math.min(delta, 0.05));
            this.terrainGen.deformTerrain(Number(row.runout_m));
        }
        if (this.simTime >= this.maxSimTime) {
            this.isRunning = false;
            this._setRunButton(false);
            this._setRunUi('complete', 'Đã phát hết kết quả mô phỏng');
            const icon = document.querySelector('#btn-tl-play i');
            if (icon) icon.className = 'bi bi-play-fill';
        }
    }

    _toggleResults(open) {
        const panel = document.getElementById('dt-results');
        panel?.classList.toggle('open', open);
        panel?.setAttribute('aria-hidden', String(!open));
        setTimeout(() => this.sceneManager?.onResize(), 260);
    }

    _escape(value) {
        const element = document.createElement('div');
        element.textContent = value == null ? '' : String(value);
        return element.innerHTML;
    }

    _chartSvg(series, key, label, thresholdLines = []) {
        if (!series?.length) return '<div class="dt-empty-result">Không có dữ liệu.</div>';
        const sampled = series.filter((_row, index) => index % Math.max(1, Math.ceil(series.length / 240)) === 0 || index === series.length - 1);
        const values = sampled.map(row => Number(row[key]) || 0);
        const minimum = Math.min(...values, ...thresholdLines);
        const maximum = Math.max(...values, ...thresholdLines, minimum + 0.001);
        const points = values.map((value, index) => `${(index / Math.max(1, values.length - 1) * 100).toFixed(2)},${(42 - (value - minimum) / (maximum - minimum) * 36).toFixed(2)}`).join(' ');
        const thresholds = thresholdLines.map(value => { const y = 42 - (value - minimum) / (maximum - minimum) * 36; return `<line x1="0" y1="${y}" x2="100" y2="${y}" class="threshold"/><text x="98" y="${y - 1}">${value}</text>`; }).join('');
        return `<figure class="dt-chart-card"><figcaption><strong>${this._escape(label)}</strong><span>${minimum.toFixed(2)} – ${maximum.toFixed(2)}</span></figcaption><svg viewBox="0 0 100 46" role="img" aria-label="${this._escape(label)} theo thời gian">${thresholds}<polyline points="${points}"/></svg></figure>`;
    }

    _profileSvg(profile, summary) {
        if (!profile?.length) return '<div class="dt-empty-result">Không có mặt cắt địa hình.</div>';
        const maxElevation = Math.max(...profile.map(point => Number(point.elevation_m) || 0), 1);
        const line = key => profile.map(point => `${(Number(point.x_m) / 120 * 100).toFixed(2)},${(44 - Number(point[key]) / maxElevation * 38).toFixed(2)}`).join(' ');
        const stopX = Math.min(100, Number(summary?.runout_m || 0) / 120 * 100);
        return `<figure class="dt-chart-card dt-profile-chart"><figcaption><strong>Mặt cắt và đường trượt 2D</strong><span>Điểm dừng ${this._escape(summary?.runout_m || 0)} m</span></figcaption><svg viewBox="0 0 100 48" role="img" aria-label="Mặt cắt sườn dốc và mặt trượt"><polyline class="terrain" points="${line('elevation_m')}"/><polyline class="slip" points="${line('slip_elevation_m')}"/><line class="stop" x1="${stopX}" y1="4" x2="${stopX}" y2="45"/></svg></figure>`;
    }

    _renderResults(run) {
        const content = document.getElementById('dt-results-content');
        if (!content) return;
        document.getElementById('dt-result-title').textContent = run.display_name || 'Kết quả mô phỏng';
        const summary = run.summary || {};
        const incomplete = run.status !== 'completed' ? '<div class="dt-incomplete"><i class="bi bi-exclamation-triangle"></i> Kết quả không hoàn tất</div>' : '';
        const stats = [
            ['FoS nhỏ nhất', summary.minimum_fos ?? '--'], ['Vận tốc cực đại', `${summary.max_velocity_m_s ?? 0} m/s`],
            ['Quãng trượt', `${summary.runout_m ?? 0} m`], ['Thể tích cuối', `${Math.round(summary.final_volume_m3 || 0)} m³`],
            ['Nhà ảnh hưởng', summary.houses_affected ?? 0], ['Cây ảnh hưởng', summary.trees_affected ?? 0],
        ];
        const charts = [
            this._chartSvg(run.time_series, 'fos', 'Hệ số an toàn FoS', [1, 1.5]),
            this._chartSvg(run.time_series, 'cumulative_rain_mm', 'Lượng mưa tích lũy'),
            this._chartSvg(run.time_series, 'pore_pressure_ratio', 'Áp lực nước lỗ rỗng ru'),
            this._chartSvg(run.time_series, 'velocity_m_s', 'Vận tốc khối trượt'),
            this._chartSvg(run.time_series, 'runout_m', 'Quãng đường trượt'),
            this._chartSvg(run.time_series, 'houses_affected', 'Nhà trong vùng ảnh hưởng'),
        ].join('');
        const events = (run.events || []).map(event => `<li><time>${(Number(event.time_s) / 3600).toFixed(2)}h</time><div><strong>${this._escape(event.state)}</strong><span>${this._escape(event.label)}</span></div></li>`).join('') || '<li>Không có sự kiện chuyển trạng thái.</li>';
        const warningsList = (run.warnings || []).map(item => `<li>${this._escape(item)}</li>`).join('');
        const warnings = warningsList ? `<section class="dt-data-warnings"><strong><i class="bi bi-database-exclamation"></i> Cảnh báo dữ liệu</strong><ul>${warningsList}</ul></section>` : '';
        const sourceRows = Object.entries(run.parameters || {}).map(([key, value]) => `<tr><th>${this._escape(key.replaceAll('_', ' '))}</th><td>${this._escape(value)}</td><td>${this._escape(run.parameter_sources?.[key] || 'Mặc định hệ thống')}</td></tr>`).join('');
        const sensors = Object.entries(run.sensor_snapshot || {});
        const sensorRows = sensors.map(([type, snapshot]) => `<tr><th>${this._escape(type)}</th><td>${snapshot.is_online && !snapshot.is_fallback ? 'Hợp lệ' : 'Không sử dụng'}</td><td>${snapshot.timestamp ? new Date(snapshot.timestamp * 1000).toLocaleString('vi-VN') : '--'}</td></tr>`).join('');
        let sensorTableHtml = '';
        if (sensors.length) {
            sensorTableHtml = `<div class="dt-table-wrap"><table class="dt-provenance-table"><caption>Tình trạng dữ liệu cảm biến tại thời điểm chạy</caption><thead><tr><th>Cảm biến</th><th>Sử dụng</th><th>Thời điểm</th></tr></thead><tbody>${sensorRows}</tbody></table></div>`;
        }
        const provenance = `<section class="dt-result-section"><div class="dt-result-section-title"><h4>Dữ liệu và phương pháp</h4><span>Engine ${this._escape(run.engine_version || '--')}</span></div><div class="dt-run-meta"><span>Chế độ</span><strong>${run.mode === 'station_snapshot' ? 'Ảnh chụp dữ liệu trạm' : 'Nhập thông số'}</strong><span>Trạm</span><strong>${this._escape(run.station_name || run.station_code || 'Không gắn trạm')}</strong><span>Seed tái lập</span><strong>${this._escape(run.seed ?? '--')}</strong></div><div class="dt-table-wrap"><table class="dt-provenance-table"><caption>Nguồn của từng tham số đầu vào</caption><thead><tr><th>Tham số</th><th>Giá trị</th><th>Nguồn</th></tr></thead><tbody>${sourceRows}</tbody></table></div>${sensorTableHtml}</section>`;
        const statsHtml = stats.map(([label, value]) => `<div><span>${this._escape(label)}</span><strong>${this._escape(value)}</strong></div>`).join('');
        content.innerHTML = `${incomplete}<section class="dt-result-hero"><span>KẾT LUẬN MÔ PHỎNG</span><h4>${this._escape(summary.classification || run.status)}</h4><p>Kết quả kịch bản, không phải chứng thư địa kỹ thuật.</p></section><div class="dt-result-stats">${statsHtml}</div><section class="dt-result-section"><div class="dt-result-section-title"><h4>Biến thiên theo thời gian</h4><span>${run.time_series?.length || 0} mẫu</span></div>${charts}</section><section class="dt-result-section"><div class="dt-result-section-title"><h4>Mặt cắt sườn dốc</h4></div>${this._profileSvg(run.terrain_profile, summary)}</section><section class="dt-result-section"><div class="dt-result-section-title"><h4>Sự kiện</h4></div><ol class="dt-event-list">${events}</ol></section>${provenance}${warnings}<div class="dt-export-bar"><button data-export="pdf"><i class="bi bi-file-earmark-pdf"></i> PDF</button><button data-export="xlsx"><i class="bi bi-file-earmark-excel"></i> XLSX</button><button data-export="json"><i class="bi bi-braces"></i> JSON</button><button class="primary" data-export="bundle"><i class="bi bi-file-zip"></i> Tải trọn bộ</button></div>`;
        content.querySelectorAll('[data-export]').forEach(button => button.addEventListener('click', () => this._download(button.dataset.export)));
    }

    async _download(format) {
        if (!this.currentRun?.id) return;
        const url = format === 'bundle' ? `/api/simulations/runs/${this.currentRun.id}/bundle` : `/api/simulations/runs/${this.currentRun.id}/export?format=${format}`;
        const response = window.apiClient ? await window.apiClient(url, { timeout: 60000 }) : await fetch(url);
        if (!response.ok) return window.toast?.error?.('Không thể tạo file báo cáo.');
        const blob = await response.blob();
        const href = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = href;
        const readableName = String(this.currentRun.display_name || `Mô phỏng ${this.currentRun.id}`)
            .replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_')
            .replace(/\s+/g, ' ')
            .trim();
        anchor.download = `${readableName}.${format === 'bundle' ? 'zip' : format}`;
        anchor.click();
        setTimeout(() => URL.revokeObjectURL(href), 1000);
    }

    async _showHistory() {
        this._toggleResults(true);
        const content = document.getElementById('dt-results-content');
        document.getElementById('dt-result-title').textContent = 'Lịch sử mô phỏng';
        content.innerHTML = '<div class="dt-history-loading"><span class="spinner-border"></span> Đang tải lịch sử…</div>';
        try {
            const runs = await this._api('/api/simulations/runs?limit=50', { requestKey: 'simulation-history' });
            const historyRunsHtml = runs.map(run => `<button type="button" data-run-id="${run.id}"><span class="dt-history-state ${this._escape(run.status)}"></span><div><strong>${this._escape(run.display_name)}</strong><small>${this._escape(run.summary?.classification || run.status)} · ${new Date(run.created_at * 1000).toLocaleString('vi-VN')}</small></div><i class="bi bi-chevron-right"></i></button>`).join('');
            content.innerHTML = `<div class="dt-history-list">${historyRunsHtml || '<div class="dt-empty-result">Chưa có lần mô phỏng nào.</div>'}</div>`;
            content.querySelectorAll('[data-run-id]').forEach(button => button.addEventListener('click', async () => {
                const run = await this._api(`/api/simulations/runs/${button.dataset.runId}`);
                this.currentRun = run;
                this._renderResults(run);
            }));
        } catch (error) {
            content.innerHTML = `<div class="dt-empty-result">${this._escape(error.message)}</div>`;
        }
    }

    dispose() {
        this.stop();
        this._isInitialized = false;
        if (this._animationFrameId) {
            cancelAnimationFrame(this._animationFrameId);
        }
        
        // Clean up UI events if necessary (for now we just hide it to reuse)
        this.envBuilder.clear();
        
        if (this.sceneManager?.renderer) {
            this.sceneManager.renderer.dispose();
            this.sceneManager.renderer.forceContextLoss();
        }
    }
}

// ─── OVERLAY INTEGRATION (Global) ──────────────────────────────────
window.openDigitalTwin = async function(stationData) {
    const container = document.getElementById('dt-overlay-container');
    if (!container) return;
    
    // Show overlay
    container.classList.add('dt-active');
    
    // Lazy init
    if (!window.digitalTwin) {
        window.digitalTwin = new SimulationController();
        await window.digitalTwin.init();
        // Wait a frame for layout to compute sizes
        await new Promise(r => setTimeout(r, 100));
        window.digitalTwin.sceneManager.onResize();
        window.digitalTwin._animate();
    } else {
        // Resume
        window.digitalTwin._isInitialized = true;
        window.digitalTwin.clock.start();
        window.digitalTwin.sceneManager.onResize();
        if (window.digitalTwin._animationFrameId) cancelAnimationFrame(window.digitalTwin._animationFrameId);
        window.digitalTwin._animate();
    }

    window.digitalTwin.stationData = stationData || null;
    window.digitalTwin._setInputMode(stationData ? 'station_snapshot' : 'manual');
};

window.closeDigitalTwin = function() {
    const container = document.getElementById('dt-overlay-container');
    if (container) {
        container.classList.remove('dt-active');
        if (document.fullscreenElement) {
            void document.exitFullscreen();
        }
    }
    
    // Pause rendering to save GPU
    if (window.digitalTwin) {
        window.digitalTwin.stop();
        window.digitalTwin._isInitialized = false;
        if (window.digitalTwin._animationFrameId) {
            cancelAnimationFrame(window.digitalTwin._animationFrameId);
        }
    }
};
