/**
 * terrain-generator.js
 * ====================
 * Generates a realistic 3D hillside terrain using Fractal Brownian Motion (fBM)
 * with Perlin-style noise. Multi-layer texturing based on elevation and slope.
 * Includes stress visualization (cracks) for pre-failure indication.
 */

import * as THREE from 'three';

// ─── Simplex-like noise (compact implementation) ───
class SimplexNoise {
    constructor(seed = 42) {
        this.grad3 = [
            [1,1,0],[-1,1,0],[1,-1,0],[-1,-1,0],
            [1,0,1],[-1,0,1],[1,0,-1],[-1,0,-1],
            [0,1,1],[0,-1,1],[0,1,-1],[0,-1,-1]
        ];
        this.p = new Uint8Array(256);
        for (let i = 0; i < 256; i++) this.p[i] = i;
        // Shuffle with seed
        let s = seed;
        for (let i = 255; i > 0; i--) {
            s = (s * 16807 + 0) % 2147483647;
            const j = s % (i + 1);
            [this.p[i], this.p[j]] = [this.p[j], this.p[i]];
        }
        this.perm = new Uint8Array(512);
        for (let i = 0; i < 512; i++) this.perm[i] = this.p[i & 255];
    }

    noise2D(x, y) {
        const F2 = 0.5 * (Math.sqrt(3.0) - 1.0);
        const G2 = (3.0 - Math.sqrt(3.0)) / 6.0;
        const s = (x + y) * F2;
        const i = Math.floor(x + s);
        const j = Math.floor(y + s);
        const t = (i + j) * G2;
        const X0 = i - t;
        const Y0 = j - t;
        const x0 = x - X0;
        const y0 = y - Y0;

        let i1, j1;
        if (x0 > y0) { i1 = 1; j1 = 0; }
        else { i1 = 0; j1 = 1; }

        const x1 = x0 - i1 + G2;
        const y1 = y0 - j1 + G2;
        const x2 = x0 - 1.0 + 2.0 * G2;
        const y2 = y0 - 1.0 + 2.0 * G2;

        const ii = i & 255;
        const jj = j & 255;

        const dot = (g, x, y) => g[0]*x + g[1]*y;
        const gi0 = this.perm[ii + this.perm[jj]] % 12;
        const gi1 = this.perm[ii + i1 + this.perm[jj + j1]] % 12;
        const gi2 = this.perm[ii + 1 + this.perm[jj + 1]] % 12;

        let n0 = 0, n1 = 0, n2 = 0;
        let t0 = 0.5 - x0*x0 - y0*y0;
        if (t0 > 0) { t0 *= t0; n0 = t0 * t0 * dot(this.grad3[gi0], x0, y0); }
        let t1 = 0.5 - x1*x1 - y1*y1;
        if (t1 > 0) { t1 *= t1; n1 = t1 * t1 * dot(this.grad3[gi1], x1, y1); }
        let t2 = 0.5 - x2*x2 - y2*y2;
        if (t2 > 0) { t2 *= t2; n2 = t2 * t2 * dot(this.grad3[gi2], x2, y2); }

        return 70.0 * (n0 + n1 + n2);
    }
}

export class TerrainGenerator {
    constructor(scene) {
        this.scene = scene;
        this.noise = new SimplexNoise(12345);
        this.mesh = null;
        this.geometry = null;

        // Terrain dimensions
        this.width = 200;
        this.depth = 200;
        this.segments = 128;
        this.maxHeight = 50;

        // Stress visualization
        this.stressLevel = 0; // 0-1
        
        // Save initial geometry for deformation
        this.initialPositions = null;
    }

    /**
     * Fractal Brownian Motion
     */
    fbm(x, z, octaves = 6, persistence = 0.5, lacunarity = 2.0) {
        let value = 0;
        let amplitude = 1;
        let frequency = 1;
        let maxValue = 0;

        for (let i = 0; i < octaves; i++) {
            value += amplitude * this.noise.noise2D(x * frequency, z * frequency);
            maxValue += amplitude;
            amplitude *= persistence;
            frequency *= lacunarity;
        }

        return value / maxValue;
    }

    /**
     * Get terrain height at world position (x, z)
     */
    getHeightAt(worldX, worldZ) {
        const nx = worldX / this.width;
        const nz = worldZ / this.depth;
        return this._heightFunction(nx, nz);
    }

    /**
     * Height function — creates a natural hillside slope
     * Higher on one side (mountain), lower on the other (valley)
     */
    _heightFunction(nx, nz) {
        // Base slope: high on -x side, low on +x side
        // tan(angle) = (slopeGradient * maxHeight) / width
        const tanAngle = Math.tan((this.slopeAngle || 25) * Math.PI / 180);
        const slopeGradient = (0.5 - nx) * ((tanAngle * this.width) / this.maxHeight);

        // Add noise for natural variation
        const noiseVal = this.fbm(nx * 3, nz * 3, 6, 0.5, 2.1);

        // Ridge line (a mountain ridge along z-axis on the left side)
        const ridgeDist = Math.abs(nx + 0.3);
        const ridge = Math.max(0, 1 - ridgeDist * 4) * 0.5;

        // Valley (gentle depression on the right side)
        const valleyCenter = 0.3;
        const valleyDist = Math.abs(nx - valleyCenter);
        const valley = Math.max(0, 1 - valleyDist * 3) * 0.15;

        // Combine
        let h = (slopeGradient + noiseVal * 0.4 + ridge - valley) * this.maxHeight;

        // Ensure minimum height at edges
        h = Math.max(h, -2);

        return h;
    }

    /**
     * Get slope angle at a point (degrees)
     */
    getSlopeAt(worldX, worldZ) {
        const eps = 1.0;
        const hL = this.getHeightAt(worldX - eps, worldZ);
        const hR = this.getHeightAt(worldX + eps, worldZ);
        const hU = this.getHeightAt(worldX, worldZ - eps);
        const hD = this.getHeightAt(worldX, worldZ + eps);

        const dx = (hR - hL) / (2 * eps);
        const dz = (hD - hU) / (2 * eps);
        const slopeMag = Math.sqrt(dx * dx + dz * dz);

        return Math.atan(slopeMag) * (180 / Math.PI);
    }

    generate() {
        // Create geometry
        this.geometry = new THREE.PlaneGeometry(
            this.width, this.depth,
            this.segments, this.segments
        );
        this.geometry.rotateX(-Math.PI / 2);

        // Deform vertices
        const pos = this.geometry.attributes.position;
        const colors = new Float32Array(pos.count * 3);
        this.initialPositions = new Float32Array(pos.count * 3);

        for (let i = 0; i < pos.count; i++) {
            const x = pos.getX(i);
            const z = pos.getZ(i);

            // Normalized coords
            const nx = x / this.width;
            const nz = z / this.depth;

            const h = this._heightFunction(nx, nz);
            pos.setY(i, h);
            
            // Store original positions for sliding
            this.initialPositions[i * 3] = x;
            this.initialPositions[i * 3 + 1] = h;
            this.initialPositions[i * 3 + 2] = z;

            // Color based on height and slope
            const slope = this._getLocalSlope(nx, nz);
            this._setVertexColor(colors, i, h, slope);
        }

        this.geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
        this.geometry.computeVertexNormals();

        // Material with vertex colors
        const material = new THREE.MeshStandardMaterial({
            vertexColors: true,
            roughness: 0.85,
            metalness: 0.05,
            flatShading: false,
            side: THREE.DoubleSide,
        });

        this.mesh = new THREE.Mesh(this.geometry, material);
        this.mesh.castShadow = true;
        this.mesh.receiveShadow = true;
        this.scene.add(this.mesh);

        return this.mesh;
    }

    _getLocalSlope(nx, nz) {
        const eps = 0.01;
        const hL = this._heightFunction(nx - eps, nz);
        const hR = this._heightFunction(nx + eps, nz);
        const hU = this._heightFunction(nx, nz - eps);
        const hD = this._heightFunction(nx, nz + eps);

        const dx = (hR - hL) / (2 * eps * this.width);
        const dz = (hD - hU) / (2 * eps * this.depth);

        return Math.sqrt(dx * dx + dz * dz);
    }

    _setVertexColor(colors, i, height, slope) {
        let r, g, b;

        // Normalize height
        const nh = (height + 5) / (this.maxHeight + 5);

        if (nh > 0.75) {
            // Rock (high altitude) — grey/brown
            r = 0.45 + slope * 0.1;
            g = 0.40 + slope * 0.05;
            b = 0.35;
        } else if (nh > 0.4) {
            // Mid slope — brown earth with sparse green
            const mix = (nh - 0.4) / 0.35;
            r = 0.35 * mix + 0.25 * (1 - mix);
            g = 0.30 * mix + 0.40 * (1 - mix);
            b = 0.20 * mix + 0.15 * (1 - mix);

            // Steeper = more brown/bare
            if (slope > 0.8) {
                r += 0.1; g -= 0.05;
            }
        } else if (nh > 0.15) {
            // Gentle slope — green grass
            r = 0.20 + this.noise.noise2D(i * 0.1, i * 0.07) * 0.05;
            g = 0.40 + this.noise.noise2D(i * 0.13, i * 0.11) * 0.08;
            b = 0.12;
        } else {
            // Valley/flat — dark green / mud
            r = 0.18;
            g = 0.30;
            b = 0.12;
        }

        // Add slight noise variation
        const nv = this.noise.noise2D(i * 0.23, i * 0.17) * 0.04;
        r = Math.max(0, Math.min(1, r + nv));
        g = Math.max(0, Math.min(1, g + nv));
        b = Math.max(0, Math.min(1, b + nv));

        colors[i * 3] = r;
        colors[i * 3 + 1] = g;
        colors[i * 3 + 2] = b;
    }

    /**
     * Set stress level (0-1) to visualize pre-failure cracks
     * Darkens the slip zone area of the terrain
     */
    setStressLevel(level) {
        this.stressLevel = level;
        if (!this.mesh || !this.geometry) return;

        const colors = this.geometry.attributes.color;
        const pos = this.geometry.attributes.position;

        for (let i = 0; i < pos.count; i++) {
            const x = pos.getX(i);
            const y = pos.getY(i);
            const z = pos.getZ(i);

            const nx = x / this.width;
            const nz = z / this.depth;

            // Slip zone: upper-middle portion of the slope, localized in Z
            const distZ = Math.abs(nz);
            const zFactor = 1.0 - (distZ / 0.15); // Slip width in Z (~30% of total depth)
            
            const inSlipZone = nx < -0.05 && nx > -0.35 && y > 10 && zFactor > 0;

            if (inSlipZone && level > 0) {
                // Darken and redden
                const factor = level * 0.4 * zFactor;
                const origR = colors.getX(i);
                const origG = colors.getY(i);
                const origB = colors.getZ(i);

                colors.setXYZ(i,
                    origR + factor * 0.4,
                    origG - factor * 0.2,
                    origB - factor * 0.15
                );
            }
        }

        colors.needsUpdate = true;
    }

    /**
     * Physically deform the terrain to simulate the sliding mass
     * displacement: how far the mass has moved
     */
    deformTerrain(displacement) {
        if (!this.mesh || !this.geometry || !this.initialPositions) return;

        const pos = this.geometry.attributes.position;
        const colors = this.geometry.attributes.color;
        let deformed = false;

        for (let i = 0; i < pos.count; i++) {
            const x = this.initialPositions[i * 3];
            const origY = this.initialPositions[i * 3 + 1];
            const z = this.initialPositions[i * 3 + 2];
            
            const nx = x / this.width;
            const nz = z / this.depth;

            // Localize in Z
            const distZ = Math.abs(nz);
            const zFactorSource = 1.0 - (distZ / 0.15); 
            const zFactorToe = 1.0 - (distZ / 0.2); // Spreads wider at toe

            // Define the slip zone
            const inSlipZone = nx < -0.05 && nx > -0.35 && origY > 10 && zFactorSource > 0;
            const isToe = nx >= -0.05 && nx < 0.15 && origY <= 15 && zFactorToe > 0;

            if (inSlipZone) {
                // The source area sinks (scar)
                const depth = Math.min(displacement * 0.15, 3.5); // max 3.5m deep scar
                // Taper the depth at edges (X and Z)
                const edgeFactorX = 1.0 - Math.abs((nx + 0.2) / 0.15); // max depth at center (-0.2)
                const sink = depth * Math.max(0, edgeFactorX) * Math.max(0, zFactorSource);
                
                pos.setY(i, origY - sink);
                deformed = true;

                // Color the exposed slip surface darker brown
                if (sink > 0.5) {
                    colors.setXYZ(i, 0.35, 0.2, 0.15); // dark reddish brown (exposed soil)
                }
            } else if (isToe) {
                // The toe area rises (deposit)
                const bulge = Math.min(displacement * 0.12, 2.5); // max 2.5m bulge
                const edgeFactorX = 1.0 - Math.abs((nx - 0.05) / 0.1);
                const rise = bulge * Math.max(0, edgeFactorX) * Math.max(0, zFactorToe);
                
                // Only rise if we haven't already
                pos.setY(i, Math.max(pos.getY(i), origY + rise));
                deformed = true;

                // Color the deposited soil
                if (rise > 0.5) {
                    colors.setXYZ(i, 0.42, 0.28, 0.18); // muddy brown deposit
                }
            }
        }

        if (deformed) {
            pos.needsUpdate = true;
            colors.needsUpdate = true;
            this.geometry.computeVertexNormals();
        }
    }
}
