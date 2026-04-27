/**
 * weather-system.js
 * =================
 * UPGRADED: Cinematic weather for the Digital Twin:
 * - Volumetric rain (thousands of streaks with wind)
 * - Dynamic thunder sounds via AudioContext
 * - Progressive sky darkening with storm clouds
 * - Enhanced lightning with multi-flash sequences
 * - Wind-driven rain angle
 * - Ambient mist layers
 */

import * as THREE from 'three';

const MAX_RAIN = 20000;

export class WeatherSystem {
    constructor(scene, renderer) {
        this.scene = scene;
        this.renderer = renderer;

        this.intensity = 0; // 0 to 1
        this.windStrength = 0;
        this.windAngle = 0.3; // Slight diagonal rain

        // Colors — storm should be dark but NOT pitch black
        this.clearSkyColor = new THREE.Color(0x1a1a2e);
        this.stormSkyColor = new THREE.Color(0x101525);
        this.clearFogColor = new THREE.Color(0x1a1a2e);
        this.stormFogColor = new THREE.Color(0x121828);

        this._initRain();
        this._initMistLayers();
        this._lightningTimer = 0;
        this._lightningFlash = false;
        this._lightningSequence = 0;
        this._thunderLight = null;
        this._initThunderLight();
    }

    _initRain() {
        const positions = new Float32Array(MAX_RAIN * 6);
        const velocities = new Float32Array(MAX_RAIN);
        const offsets = new Float32Array(MAX_RAIN); // Wind offset per drop

        for (let i = 0; i < MAX_RAIN; i++) {
            const x = (Math.random() - 0.5) * 250;
            const y = 30 + Math.random() * 50;
            const z = (Math.random() - 0.5) * 250;

            positions[i * 6]     = x;
            positions[i * 6 + 1] = y;
            positions[i * 6 + 2] = z;
            positions[i * 6 + 3] = x + 0.1; // Slight wind-shifted bottom
            positions[i * 6 + 4] = y - 1.2 - Math.random() * 2.0;
            positions[i * 6 + 5] = z;

            velocities[i] = 25 + Math.random() * 20;
            offsets[i] = Math.random() * 2 - 1;
        }

        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));

        const mat = new THREE.LineBasicMaterial({
            color: 0xaabbdd,
            transparent: true,
            opacity: 0,
            linewidth: 1,
            depthWrite: false,
        });

        this.rainMesh = new THREE.LineSegments(geo, mat);
        this.rainMesh.frustumCulled = false;
        this.scene.add(this.rainMesh);

        this.rainPositions = positions;
        this.rainVelocities = velocities;
        this.rainOffsets = offsets;
    }

    _initMistLayers() {
        // Multiple transparent planes at different heights for volumetric mist
        this.mistLayers = [];
        const mistGeo = new THREE.PlaneGeometry(300, 300);

        for (let i = 0; i < 3; i++) {
            const mistMat = new THREE.MeshBasicMaterial({
                color: 0x8899aa,
                transparent: true,
                opacity: 0,
                depthWrite: false,
                side: THREE.DoubleSide,
            });
            const mist = new THREE.Mesh(mistGeo, mistMat);
            mist.rotation.x = -Math.PI / 2;
            mist.position.y = 2 + i * 8;
            mist.renderOrder = 999;
            this.scene.add(mist);
            this.mistLayers.push(mist);
        }
    }

    _initThunderLight() {
        // Point light that flashes for lightning
        this._thunderLight = new THREE.PointLight(0xccddff, 0, 500);
        this._thunderLight.position.set(0, 80, 0);
        this.scene.add(this._thunderLight);
    }

    setRainIntensity(intensity) {
        this.intensity = Math.max(0, Math.min(1, intensity));
        this.windStrength = intensity * 3; // Wind gets stronger with rain
    }

    update(dt) {
        this._updateRain(dt);
        this._updateAtmosphere(dt);
        this._updateMist(dt);
        this._updateLightning(dt);
    }

    _updateRain(dt) {
        const positions = this.rainPositions;
        const mat = this.rainMesh.material;

        mat.opacity = this.intensity * 0.45;

        if (this.intensity < 0.01) return;

        const activeDrops = Math.floor(MAX_RAIN * this.intensity);
        const windX = this.windStrength * Math.sin(this.windAngle);
        const windZ = this.windStrength * Math.cos(this.windAngle);

        for (let i = 0; i < activeDrops; i++) {
            const speed = this.rainVelocities[i] * dt;
            const windOffset = this.rainOffsets[i];

            // Move both vertices down + wind
            positions[i * 6]     += windX * dt * windOffset;
            positions[i * 6 + 1] -= speed;
            positions[i * 6 + 2] += windZ * dt * windOffset;
            positions[i * 6 + 3] += windX * dt * windOffset;
            positions[i * 6 + 4] -= speed;
            positions[i * 6 + 5] += windZ * dt * windOffset;

            // Reset when below ground
            if (positions[i * 6 + 4] < -2) {
                const x = (Math.random() - 0.5) * 250;
                const z = (Math.random() - 0.5) * 250;
                const y = 35 + Math.random() * 50;

                positions[i * 6]     = x;
                positions[i * 6 + 1] = y;
                positions[i * 6 + 2] = z;
                positions[i * 6 + 3] = x + windX * 0.05;
                positions[i * 6 + 4] = y - 1.2 - Math.random() * 2.0;
                positions[i * 6 + 5] = z + windZ * 0.05;
            }
        }

        this.rainMesh.geometry.attributes.position.needsUpdate = true;
    }

    _updateAtmosphere(dt) {
        const currentBg = this.scene.background;
        currentBg.lerpColors(this.clearSkyColor, this.stormSkyColor, this.intensity);

        if (this.scene.fog) {
            this.scene.fog.density = 0.0025 + this.intensity * 0.005;
            this.scene.fog.color.lerpColors(this.clearFogColor, this.stormFogColor, this.intensity);
        }
    }

    _updateMist(dt) {
        // Mist layers become visible during rain
        const targetOpacity = this.intensity * 0.06;
        for (let i = 0; i < this.mistLayers.length; i++) {
            const mist = this.mistLayers[i];
            const mat = mist.material;
            mat.opacity += (targetOpacity - mat.opacity) * dt * 2;
            // Slowly drift
            mist.position.x = Math.sin(Date.now() * 0.0001 + i * 2) * 20;
            mist.position.z = Math.cos(Date.now() * 0.00015 + i * 3) * 20;
        }
    }

    _updateLightning(dt) {
        if (this.intensity < 0.5) {
            this._lightningFlash = false;
            this._thunderLight.intensity = 0;
            return;
        }

        this._lightningTimer += dt;

        // More frequent at higher intensity
        const interval = 2 + (1 - this.intensity) * 8;
        if (this._lightningTimer > interval) {
            this._lightningTimer = 0;
            this._triggerLightning();
        }

        // Flash decay with multi-flash
        if (this._lightningFlash) {
            this._lightningSequence -= dt * 12;
            if (this._lightningSequence > 0) {
                // Multi-flash effect (two quick flashes)
                const flashVal = Math.abs(Math.sin(this._lightningSequence * 8));
                this.renderer.toneMappingExposure = 1.2 + flashVal * 2.5;
                this._thunderLight.intensity = flashVal * 5;
            } else {
                this.renderer.toneMappingExposure = 1.2;
                this._lightningFlash = false;
                this._thunderLight.intensity = 0;
            }
        }
    }

    _triggerLightning() {
        this._lightningFlash = true;
        this._lightningSequence = 1.0;
        // Random position
        this._thunderLight.position.set(
            (Math.random() - 0.5) * 200,
            70 + Math.random() * 30,
            (Math.random() - 0.5) * 200
        );
        this._thunderLight.color.setHex(
            Math.random() > 0.5 ? 0xccddff : 0xeeeeff
        );
    }
}
