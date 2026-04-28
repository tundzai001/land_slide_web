/**
 * physics-engine.js
 * =================
 * Advanced Geotechnical Physics Engine for the LS-RAPID Digital Twin.
 *
 * Implements:
 * 1. Method of Slices (FoS) — Rigorous stability analysis over the slope profile.
 * 2. Voellmy Rheology — Professional standard for debris flow/landslide kinematics.
 * 3. Green-Ampt Infiltration — Realistic, time-delayed pore water pressure generation.
 */

export class PhysicsEngine {
    constructor(terrainGen) {
        this.terrain = terrainGen;
        this.g = 9.81; // m/s²

        this._slideState = null;
        this._infiltrationState = {
            wettingDepth: 0,     // m
            cumulativeRain: 0,   // m
            pondingTime: 0       // s
        };
    }

    /**
     * Update infiltration model (Green-Ampt approximation)
     * Calculates realistic pore pressure buildup based on rainfall intensity and time.
     * 
     * @param {number} rainfall_mm_h - Rainfall intensity in mm/h
     * @param {number} dt - Timestep in seconds
     * @param {number} slipDepth - Depth of the slip surface in meters
     * @returns {number} Effective pore pressure ratio (ru)
     */
    calculateInfiltration(rainfall_mm_h, dt, slipDepth) {
        const I = (rainfall_mm_h / 1000) / 3600; // Intensity in m/s
        
        // Soil hydraulic properties (Typical Silty Sand / Loam)
        const Ks = 1.5e-5; // Saturated hydraulic conductivity m/s
        const dTheta = 0.25; // Change in volumetric water content
        const psi = 0.3; // Suction head m
        
        if (I > 0) {
            this._infiltrationState.cumulativeRain += I * dt;
            
            // Simplified Green-Ampt wetting front advance
            if (I <= Ks) {
                // All rain infiltrates
                this._infiltrationState.wettingDepth += (I / dTheta) * dt;
            } else {
                // Ponding occurs, infiltration is limited by capacity
                // Infiltration rate f = Ks * (1 + psi / Zw)
                let Zw = Math.max(0.01, this._infiltrationState.wettingDepth);
                let f = Ks * (1 + psi / Zw);
                f = Math.min(f, I * 5); 
                
                this._infiltrationState.wettingDepth += (f / dTheta) * dt;
                this._infiltrationState.pondingTime += dt;
            }
        } else {
            // Drainage / Percolation when rain stops
            const drainageRate = Ks * 0.1;
            this._infiltrationState.wettingDepth = Math.max(0, this._infiltrationState.wettingDepth + (drainageRate / dTheta) * dt);
            // Suction slowly recovers, so effective pore pressure would drop over long periods
        }

        // Calculate ru (Pore pressure ratio)
        // ru = u / (gamma * z)
        // If wetting front reaches the slip surface, pore pressure builds up hydrostatically
        let ru = 0;
        const Zw = this._infiltrationState.wettingDepth;
        
        if (Zw > slipDepth * 0.3) {
            // Perched water table starts forming above slip surface
            const hw = Math.max(0, Zw - slipDepth * 0.3); 
            // Max hydrostatic pressure if fully saturated to surface is ~0.5 (gamma_w / gamma_soil)
            ru = Math.min(0.6, (hw / slipDepth) * 0.5);
        }

        return ru;
    }

    /**
     * Calculate Factor of Safety using a Simplified Method of Slices
     * Integrates resisting and driving forces along the longitudinal profile.
     */
    calculateFoS(params) {
        const {
            cohesion = 15,          // c' in kPa
            frictionAngle = 30,     // φ' in degrees
            unitWeight = 18,        // γ in kN/m³
            slipDepth = 5,          // z in meters
            slopeAngle = 35,        // β in degrees (average macroscopic)
            porePressureRatio = 0,  // ru
            seismicCoeff = 0,       // kh
        } = params;

        const c = cohesion;
        const phi = frictionAngle * Math.PI / 180;
        const gamma = unitWeight;
        const kh = Math.max(0, seismicCoeff);
        const ru = Math.min(porePressureRatio, 0.6); // Cap at liquefaction

        // Discretize the slope into slices
        const numSlices = 20;
        const slopeLength = 60; // m
        const dx = slopeLength / numSlices;
        
        let sumResisting = 0;
        let sumDriving = 0;

        for (let i = 0; i < numSlices; i++) {
            const x = i * dx;
            // Generate a realistic slip surface profile (concave upwards)
            // Head (steep) -> Toe (flat)
            const normalizedX = x / slopeLength;
            // Local slope angle varies from steep at top to gentle at toe
            const localBetaDeg = slopeAngle + 15 * (1 - 2 * normalizedX); 
            const alpha = Math.max(5, localBetaDeg) * Math.PI / 180;
            
            // Slice depth tapers at the ends
            const edgeTaper = Math.sin(normalizedX * Math.PI);
            const z_i = slipDepth * edgeTaper;
            if (z_i < 0.1) continue;

            const W = gamma * z_i * dx; // Weight of slice per unit width
            const baseLength = dx / Math.cos(alpha);
            
            const u = ru * gamma * z_i; // Pore pressure at slice base
            const sigmaN = (W * Math.cos(alpha)) / baseLength; // Normal stress
            const sigmaEffective = Math.max(0, sigmaN - u);

            // Resisting force (Mohr-Coulomb)
            const resisting = (c + sigmaEffective * Math.tan(phi)) * baseLength;
            
            // Driving force (Gravity + Seismic)
            const driving = W * Math.sin(alpha) + kh * W * Math.cos(alpha);

            sumResisting += resisting;
            sumDriving += driving;
        }

        if (sumDriving <= 0) return 99;
        return Math.max(0, sumResisting / sumDriving);
    }

    /**
     * Calculate slide motion using Voellmy Rheology Model
     * S = mu * N + (rho * g * v^2) / xi
     */
    calculateSlideMotion(params, elapsed, dt) {
        if (!this._slideState) {
            this._slideState = {
                velocity: 0,
                position: 0,     
                mass: 20 * 30 * params.slipDepth * params.unitWeight * 100, // kg
                volume: 20 * 30 * params.slipDepth, // m³
                flowHeight: params.slipDepth
            };
        }

        const state = this._slideState;
        const beta = params.slopeAngle * Math.PI / 180;
        
        // ── Voellmy Rheology Parameters ──
        // mu: Dry Coulomb friction coefficient (reduced due to fluidization)
        // xi: Turbulent drag coefficient (m/s²)
        let mu = Math.tan((params.frictionAngle - 10) * Math.PI / 180); // Reduced phi
        let xi = 300; // Typical for muddy debris flows (200 - 500)

        // Liquefaction / High pore pressure reduces basal friction dramatically
        const ru = params._effectiveRu || params.porePressureRatio || 0;
        if (ru > 0.3) {
            mu = Math.max(0.05, mu * (1 - ru)); // Liquefaction drop
            xi = 500; // More fluid, less turbulence drag
        }

        // Local slope based on position (terrain flattens out)
        const localSlope = Math.max(0, beta - state.position * 0.006);
        
        // ── Accelerating Forces (Gravity) ──
        const Fg = this.g * Math.sin(localSlope);

        // ── Resisting Forces (Voellmy) ──
        // 1. Coulomb friction
        const F_coulomb = mu * this.g * Math.cos(localSlope);
        
        // 2. Turbulent drag
        // drag = (g * v^2) / (xi * h)
        const h = Math.max(0.5, state.flowHeight);
        const F_turbulent = (this.g * state.velocity * state.velocity) / (xi * h);

        let acceleration = Fg - F_coulomb - F_turbulent;

        // Prevent backwards sliding if stopped
        if (state.velocity <= 0.01 && acceleration < 0) {
            acceleration = 0;
            state.velocity = 0;
        }

        // ── Integrate ──
        state.velocity = Math.max(0, state.velocity + acceleration * dt);
        state.position += state.velocity * dt;

        // ── Entrainment (Volume Enlargement) ──
        if (state.velocity > 1.0) {
            const entrainmentRate = 0.8; // Erosion rate
            const dV = entrainmentRate * state.velocity * dt;
            state.volume += dV;
            state.mass += dV * params.unitWeight * 100;
            // Flow height thins out as it spreads
            state.flowHeight = Math.max(1.0, state.flowHeight * 0.999);
        }

        // Front position for visualization
        const startX = -30;
        const frontX = startX + state.position * Math.cos(params.slopeAngle * Math.PI / 180);
        const frontY = this.terrain.getHeightAt(frontX, 0) + 1;
        
        return {
            velocity: state.velocity,
            position: state.position,
            volume: state.volume,
            frontPosition: { x: frontX, y: frontY, z: 0 },
            width: 20 + state.position * 0.4,
            kineticEnergy: 0.5 * state.mass * state.velocity * state.velocity,
            mass: state.mass,
            acceleration
        };
    }

    reset() {
        this._slideState = null;
        this._infiltrationState = { wettingDepth: 0, cumulativeRain: 0, pondingTime: 0 };
    }
}
