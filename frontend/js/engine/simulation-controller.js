/**
 * simulation-controller.js
 * ========================
 * Main entry point & orchestrator for the LS-RAPID Digital Twin.
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
            treeCount: 300
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

        this.init();
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
                const val = parseFloat(el.value);
                this.params[cfg.key] = val;
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
                const val = parseFloat(el.value);
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
                this.maxSimTime = parseInt(durationEl.value);
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
            if (this.isRunning) {
                this.stop();
            } else {
                this.start();
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
            this.simSpeed = parseInt(e.target.value);
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
                    document.exitFullscreen();
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

        // Initial FoS
        this._updateFoS();
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
    start() {
        this.isRunning = true;
        this.isPaused = false;
        this.simTime = 0;
        this.state = SimState.STABLE;

        // Update UI
        const btnRun = document.getElementById('btn-run-simulation');
        btnRun.innerHTML = '<i class="bi bi-stop-fill"></i> Dừng Mô phỏng';
        btnRun.classList.add('running');

        const playIcon = document.querySelector('#btn-tl-play i');
        playIcon.className = 'bi bi-pause-fill';
        
        // Auto-collapse left panel to make room for simulation
        const panel = document.getElementById('dt-panel');
        if (panel && panel.classList.contains('dt-panel-open')) {
            panel.classList.remove('dt-panel-open');
            panel.classList.add('dt-panel-closed');
            setTimeout(() => this.sceneManager.onResize(), 350);
        }

        // Reset damage stats
        this.damageStats = { housesDestroyed: 0, treesDestroyed: 0, velocity: 0, volume: 0 };
        this._maxVelocity = 0;
        this._reportShown = false;

        // Reset physics engine state
        this.physics.reset();
    }

    stop() {
        this.isRunning = false;
        this.isPaused = false;
        this.state = SimState.STABLE;

        const btnRun = document.getElementById('btn-run-simulation');
        btnRun.innerHTML = '<i class="bi bi-play-fill"></i> Chạy Mô phỏng';
        btnRun.classList.remove('running');

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
            'param-fos-warning': 1.5, 'param-fos-critical': 1.0
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
        this.terrainGen.deformTerrain(0); // Reset terrain shape

        // Reset timeline
        document.getElementById('tl-progress').style.width = '0%';
        document.getElementById('tl-time').textContent = '00h00m';

        this._updateFoS();
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
            this.isPaused = true;
            const playIcon = document.querySelector('#btn-tl-play i');
            if (playIcon) playIcon.className = 'bi bi-play-fill';
        }
    }

    _simulationSubStep(dt) {

        // ── Phase 1: Build up pore pressure from rainfall (Green-Ampt Infiltration) ──
        if (this.params.rainfall > 0) {
            const infiltrationRu = this.physics.calculateInfiltration(this.params.rainfall, dt, this.params.slipDepth);
            
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
        const prevState = this.state;

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

    dispose() {
        this.stop();
        this._isInitialized = false;
        if (this._animationFrameId) {
            cancelAnimationFrame(this._animationFrameId);
        }
        
        // Clean up UI events if necessary (for now we just hide it to reuse)
        this.envBuilder.clear();
        
        if (this.sceneManager && this.sceneManager.renderer) {
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
        // Wait a frame for layout to compute sizes
        await new Promise(r => setTimeout(r, 100));
        window.digitalTwin.sceneManager.onResize();
        window.digitalTwin._animate();
    } else {
        // Resume
        window.digitalTwin._isInitialized = true;
        window.digitalTwin.clock.start();
        window.digitalTwin.sceneManager.onResize();
        window.digitalTwin._animate();
    }

    // Map station data to simulation params if provided
    if (stationData) {
        if (stationData.rain) {
            const rainInput = document.getElementById('param-rainfall');
            if (rainInput) {
                // Approximate 24h rain to mm/h intensity
                rainInput.value = Math.min(stationData.rain.h24 / 24, 200);
                rainInput.dispatchEvent(new Event('input'));
            }
        }
    }
};

window.closeDigitalTwin = function() {
    const container = document.getElementById('dt-overlay-container');
    if (container) {
        container.classList.remove('dt-active');
        if (document.fullscreenElement) {
            document.exitFullscreen();
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
