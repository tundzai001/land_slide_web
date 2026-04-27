/**
 * physics-engine.js
 * =================
 * Core geotechnical physics for the LS-RAPID Digital Twin.
 *
 * Implements:
 * 1. Factor of Safety (FoS) — Mohr-Coulomb + Terzaghi Effective Stress
 *    FoS = [c' + (γ·z·cos²β - u) · tan(φ')] / [γ·z·sinβ·cosβ + kh·γ·z·cosβ]
 *
 * 2. Slide Motion — Newton's 2nd law on the slip mass
 *    a = g·sinβ - (τ_base / (ρ·z)) - drag
 *
 * 3. Volume Enlargement — entrainment of loose material
 *    m(t+dt) = m(t) + ρ·h_entrain·A_front·v·dt
 */

export class PhysicsEngine {
    constructor(terrainGen) {
        this.terrain = terrainGen;

        // Constants
        this.g = 9.81; // m/s²

        // Slide state
        this._slideState = null;
    }

    /**
     * Calculate Factor of Safety (Infinite Slope Model with seismic loading)
     *
     * FoS = [c' + (γ·z·cos²β - ru·γ·z) · tan(φ')]
     *        / [γ·z·sinβ·cosβ + kh·γ·z·cosβ]
     *
     * @param {Object} params
     * @returns {number} Factor of Safety
     */
    calculateFoS(params) {
        const {
            cohesion = 15,          // c' in kPa
            frictionAngle = 30,     // φ' in degrees
            unitWeight = 18,        // γ in kN/m³
            slipDepth = 5,          // z in meters
            slopeAngle = 35,        // β in degrees
            porePressureRatio = 0,  // ru (0-0.6)
            seismicCoeff = 0,       // kh (horizontal seismic coefficient)
        } = params;

        const c = cohesion;                                      // kPa
        const phi = frictionAngle * Math.PI / 180;               // radians
        const gamma = unitWeight;                                 // kN/m³
        const z = slipDepth;                                      // m
        const beta = slopeAngle * Math.PI / 180;                  // radians
        const ru = Math.max(0, Math.min(porePressureRatio, 0.6)); // clamped
        const kh = Math.max(0, seismicCoeff);

        // Pore water pressure: u = ru * γ * z
        const u = ru * gamma * z;

        // Normal stress on slip plane: σn = γ·z·cos²β
        const sigmaN = gamma * z * Math.cos(beta) * Math.cos(beta);

        // Effective normal stress: σ'n = σn - u
        const sigmaEffective = sigmaN - u;

        // Resisting force (numerator): τ_f = c' + σ'n · tan(φ')
        const resistingForce = c + Math.max(0, sigmaEffective) * Math.tan(phi);

        // Driving force (denominator): τ_d = γ·z·sinβ·cosβ + kh·γ·z·cosβ
        const gravityComponent = gamma * z * Math.sin(beta) * Math.cos(beta);
        const seismicComponent = kh * gamma * z * Math.cos(beta);
        const drivingForce = gravityComponent + seismicComponent;

        // FoS
        if (drivingForce <= 0) return 99; // Flat ground = infinitely stable
        const fos = resistingForce / drivingForce;

        return Math.max(0, fos);
    }

    /**
     * Calculate slide motion after failure (FoS < 1)
     *
     * Uses simplified Newtonian mechanics:
     * - Acceleration: a = g·sinβ - τ_residual/(ρ·z) - C_drag·v²
     * - Velocity: v(t+dt) = v(t) + a·dt
     * - Position: x(t+dt) = x(t) + v·dt
     *
     * @param {Object} params - Soil parameters
     * @param {number} elapsed - Time since slide start (s)
     * @param {number} dt - Timestep (s)
     * @returns {Object} { velocity, position, volume, frontPosition, width, kineticEnergy }
     */
    calculateSlideMotion(params, elapsed, dt) {
        if (!this._slideState) {
            // Initialize slide
            this._slideState = {
                velocity: 0,
                position: 0,     // distance traveled along slope
                mass: this._calculateInitialMass(params),
                volume: this._calculateInitialVolume(params),
            };
        }

        const state = this._slideState;
        const beta = params.slopeAngle * Math.PI / 180;
        const phi = params.frictionAngle * Math.PI / 180;
        const gamma = params.unitWeight;
        const z = params.slipDepth;
        const ru = params._effectiveRu || params.porePressureRatio;

        // ── Forces ──

        // Gravity component along slope
        const Fg = this.g * Math.sin(beta);

        // Residual shear resistance (post-failure, reduced — LS-RAPID "steady state")
        // After liquefaction, the friction drops significantly
        // τ_ss = (1 - Bss) · σ'n · tan(φ_a)
        const Bss = Math.min(ru * 1.5, 0.95); // Excess pore pressure ratio at steady state
        const sigmaEffN = gamma * z * Math.cos(beta) * Math.cos(beta) * (1 - Bss);
        const tauResidual = Math.max(0, sigmaEffN * Math.tan(phi * 0.3)); // Reduced friction angle at steady state
        const Fr = tauResidual / (gamma * z / this.g); // deceleration from residual resistance

        // Drag (air resistance + collision energy loss)
        const Cd = 0.005; // drag coefficient
        const Fdrag = Cd * state.velocity * state.velocity;

        // ── Acceleration ──
        const acceleration = Fg - Fr - Fdrag;

        // ── Integrate ──
        state.velocity = Math.max(0, state.velocity + acceleration * dt);
        state.position += state.velocity * dt;

        // ── Volume Enlargement (entrainment) ──
        // When debris flows over loose ground, it picks up more material
        if (state.velocity > 1) {
            const entrainmentRate = 0.5; // m³/s per m/s velocity (simplified)
            const dV = entrainmentRate * state.velocity * dt * 0.1;
            state.volume += dV;
            state.mass += dV * gamma * 100; // kg
        }

        // ── Deceleration on flat ground ──
        // As debris reaches flat area, slope decreases
        const effectiveSlope = Math.max(0, beta - state.position * 0.005);
        if (effectiveSlope < 0.05 && state.velocity > 0) {
            state.velocity *= (1 - 0.5 * dt); // friction stops it
        }

        // ── Front position in world coordinates ──
        // Debris starts from upper slope and moves downhill (+x direction)
        const startX = -30; // upper slope
        const frontX = startX + state.position * Math.cos(beta);
        const frontY = this.terrain.getHeightAt(frontX, 0) + 1;
        const frontPosition = { x: frontX, y: frontY, z: 0 };

        // Width of debris front (spreads as it moves)
        const width = 20 + state.position * 0.3;

        // Kinetic energy
        const kineticEnergy = 0.5 * state.mass * state.velocity * state.velocity;

        return {
            velocity: state.velocity,
            position: state.position,
            volume: state.volume,
            frontPosition,
            width,
            kineticEnergy,
            mass: state.mass,
            acceleration
        };
    }

    _calculateInitialMass(params) {
        // Approximate mass of the sliding block
        const width = 20; // m (across slope)
        const length = 30; // m (along slope)
        const depth = params.slipDepth;
        const density = params.unitWeight * 100; // kg/m³ (approx from kN/m³)
        return width * length * depth * density;
    }

    _calculateInitialVolume(params) {
        return 20 * 30 * params.slipDepth; // m³
    }

    /**
     * Reset physics state
     */
    reset() {
        this._slideState = null;
    }
}
