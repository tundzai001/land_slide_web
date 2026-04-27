/**
 * particle-system.js
 * ==================
 * UPGRADED: Massive landslide particle effects:
 * - Sliding mud mass (a visible body of moving earth)
 * - Debris particles (earth, rocks tumbling down)
 * - Dust clouds (rising mushroom clouds after impact)
 * - Mud splash on ground impact
 * - Trailing mud streaks
 *
 * Uses InstancedMesh for high performance.
 */

import * as THREE from 'three';

const MAX_DEBRIS = 5000;
const MAX_DUST = 2000;
const MAX_MUD_BLOBS = 1000;

export class ParticleSystem {
    constructor(scene) {
        this.scene = scene;

        this._initDebris();
        this._initDust();
        this._initMudBlobs();
        this._initSlidingMass();

        this.debrisCount = 0;
        this.dustCount = 0;
    }

    // ─── DEBRIS PARTICLES ────────────────────────────────────────────
    _initDebris() {
        const geo = new THREE.DodecahedronGeometry(1.0, 0);
        const mat = new THREE.MeshStandardMaterial({
            color: 0x8b7355,
            roughness: 0.9,
            metalness: 0.05,
        });

        this.debrisMesh = new THREE.InstancedMesh(geo, mat, MAX_DEBRIS);
        this.debrisMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        this.debrisMesh.count = 0;
        this.debrisMesh.castShadow = true;
        this.debrisMesh.frustumCulled = false;
        this.scene.add(this.debrisMesh);

        this.debrisData = [];
        this._dummyMatrix = new THREE.Matrix4();
        this._dummyPos = new THREE.Vector3();
        this._dummyQuat = new THREE.Quaternion();
        this._dummyScale = new THREE.Vector3();

        // Rich earth-tone color palette
        const colors = [
            new THREE.Color(0x8b7355),
            new THREE.Color(0x6b5b45),
            new THREE.Color(0x9c8b6b),
            new THREE.Color(0x5c4a3a),
            new THREE.Color(0x7a6a52),
            new THREE.Color(0xa09070),
            new THREE.Color(0x4a3a28),
            new THREE.Color(0x6d5d4d),
            new THREE.Color(0x8a7a5a),
            new THREE.Color(0x554535),
        ];

        const colorAttr = new THREE.InstancedBufferAttribute(
            new Float32Array(MAX_DEBRIS * 3), 3
        );
        for (let i = 0; i < MAX_DEBRIS; i++) {
            const c = colors[i % colors.length];
            colorAttr.setXYZ(i, c.r, c.g, c.b);
        }
        this.debrisMesh.instanceColor = colorAttr;
    }

    // ─── DUST PARTICLES ──────────────────────────────────────────────
    _initDust() {
        const geo = new THREE.SphereGeometry(1.0, 4, 4);
        const mat = new THREE.MeshBasicMaterial({
            color: 0xb0a090,
            transparent: true,
            opacity: 0.25,
            depthWrite: false,
        });

        this.dustMesh = new THREE.InstancedMesh(geo, mat, MAX_DUST);
        this.dustMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        this.dustMesh.count = 0;
        this.dustMesh.frustumCulled = false;
        this.scene.add(this.dustMesh);

        this.dustData = [];
    }

    // ─── MUD BLOBS (ground splatter) ─────────────────────────────────
    _initMudBlobs() {
        const geo = new THREE.SphereGeometry(0.5, 4, 3);
        const mat = new THREE.MeshStandardMaterial({
            color: 0x5c4a3a,
            roughness: 0.95,
            metalness: 0.0,
        });

        this.mudMesh = new THREE.InstancedMesh(geo, mat, MAX_MUD_BLOBS);
        this.mudMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        this.mudMesh.count = 0;
        this.mudMesh.frustumCulled = false;
        this.mudMesh.receiveShadow = true;
        this.scene.add(this.mudMesh);

        this.mudData = [];
    }

    // ─── SLIDING MASS (the main visible body of mud) ──────────────────
    _initSlidingMass() {
        // A deformable blob representing the main sliding body
        const geo = new THREE.SphereGeometry(8, 12, 8);
        const mat = new THREE.MeshStandardMaterial({
            color: 0x6b5545,
            roughness: 0.95,
            metalness: 0.02,
            transparent: true,
            opacity: 0,
        });

        this.slidingMass = new THREE.Mesh(geo, mat);
        this.slidingMass.scale.set(2.5, 0.4, 1.5);
        this.slidingMass.castShadow = true;
        this.slidingMass.receiveShadow = true;
        this.scene.add(this.slidingMass);

        // Secondary mass (trailing body)
        const geo2 = new THREE.SphereGeometry(6, 10, 6);
        const mat2 = mat.clone();
        mat2.color.set(0x7a6a52);
        this.slidingMassTrail = new THREE.Mesh(geo2, mat2);
        this.slidingMassTrail.scale.set(2, 0.3, 1.8);
        this.slidingMassTrail.castShadow = true;
        this.scene.add(this.slidingMassTrail);
    }

    /**
     * Emit debris particles at the front of the landslide
     */
    emitDebris(frontPos, velocity, dt) {
        const emitCount = Math.min(
            Math.floor(velocity * 25 * dt),
            250
        );

        for (let i = 0; i < emitCount; i++) {
            if (this.debrisData.length >= MAX_DEBRIS) break;

            const particle = {
                position: new THREE.Vector3(
                    frontPos.x + (Math.random() - 0.5) * 20,
                    frontPos.y + Math.random() * 4,
                    frontPos.z + (Math.random() - 0.5) * 25
                ),
                velocity: new THREE.Vector3(
                    velocity * 0.6 + (Math.random() - 0.3) * velocity * 0.4,
                    Math.random() * 4 - 1,
                    (Math.random() - 0.5) * velocity * 0.3
                ),
                rotation: new THREE.Euler(
                    Math.random() * Math.PI * 2,
                    Math.random() * Math.PI * 2,
                    Math.random() * Math.PI * 2
                ),
                angularVel: new THREE.Vector3(
                    (Math.random() - 0.5) * 8,
                    (Math.random() - 0.5) * 8,
                    (Math.random() - 0.5) * 8
                ),
                scale: 0.8 + Math.random() * 3.5,
                life: 0,
                maxLife: 5 + Math.random() * 6,
            };

            this.debrisData.push(particle);
        }

        // Also emit mud blobs that stick to ground
        this._emitMudSplatter(frontPos, velocity, dt);

        // Update the visible sliding mass position
        this._updateSlidingMass(frontPos, velocity);
    }

    /**
     * Emit mud splatter that stays on the ground
     */
    _emitMudSplatter(frontPos, velocity, dt) {
        const emitCount = Math.min(Math.floor(velocity * 5 * dt), 30);

        for (let i = 0; i < emitCount; i++) {
            if (this.mudData.length >= MAX_MUD_BLOBS) break;

            this.mudData.push({
                position: new THREE.Vector3(
                    frontPos.x + (Math.random() - 0.5) * 15 + Math.random() * 5,
                    frontPos.y - 0.3,
                    frontPos.z + (Math.random() - 0.5) * 20
                ),
                scale: 1.0 + Math.random() * 3.0,
                flatScale: 0.15 + Math.random() * 0.15,
                life: 0,
                maxLife: 20 + Math.random() * 10, // Stay a long time
            });
        }
    }

    /**
     * Update the main visible sliding mass
     */
    _updateSlidingMass(frontPos, velocity) {
        // Main mass follows the front
        const mat = this.slidingMass.material;
        const targetOpacity = Math.min(velocity / 5, 0.9);
        mat.opacity += (targetOpacity - mat.opacity) * 0.1;

        this.slidingMass.position.set(
            frontPos.x - 5,
            frontPos.y + 1,
            frontPos.z
        );
        // Scale grows with velocity
        const growFactor = Math.min(velocity / 10, 2);
        this.slidingMass.scale.set(
            2.5 + growFactor,
            0.4 + growFactor * 0.2,
            1.5 + growFactor * 0.5
        );

        // Trail
        const mat2 = this.slidingMassTrail.material;
        mat2.opacity = mat.opacity * 0.7;
        this.slidingMassTrail.position.set(
            frontPos.x - 15,
            frontPos.y + 0.5,
            frontPos.z
        );
        this.slidingMassTrail.scale.set(
            2 + growFactor * 0.5,
            0.3 + growFactor * 0.1,
            1.8 + growFactor * 0.3
        );
    }

    /**
     * Emit dust cloud at impact point
     */
    emitDust(frontPos, velocity) {
        const emitCount = Math.min(Math.floor(velocity * 2.5), 40);

        for (let i = 0; i < emitCount; i++) {
            if (this.dustData.length >= MAX_DUST) break;

            this.dustData.push({
                position: new THREE.Vector3(
                    frontPos.x + (Math.random() - 0.5) * 15,
                    frontPos.y + Math.random() * 3,
                    frontPos.z + (Math.random() - 0.5) * 20
                ),
                velocity: new THREE.Vector3(
                    (Math.random() - 0.5) * 5,
                    2 + Math.random() * 6,
                    (Math.random() - 0.5) * 5
                ),
                scale: 3 + Math.random() * 7,
                life: 0,
                maxLife: 3 + Math.random() * 4,
                opacity: 0.3 + Math.random() * 0.3,
            });
        }
    }

    /**
     * Update all particles
     */
    update(dt) {
        this._updateDebris(dt);
        this._updateDust(dt);
        this._updateMud(dt);
    }

    _updateDebris(dt) {
        const gravity = 9.81;
        const toRemove = [];

        for (let i = 0; i < this.debrisData.length; i++) {
            const p = this.debrisData[i];
            p.life += dt;

            if (p.life > p.maxLife) {
                toRemove.push(i);
                continue;
            }

            // Gravity
            p.velocity.y -= gravity * dt;

            // Position
            p.position.x += p.velocity.x * dt;
            p.position.y += p.velocity.y * dt;
            p.position.z += p.velocity.z * dt;

            // Rotation
            p.rotation.x += p.angularVel.x * dt;
            p.rotation.y += p.angularVel.y * dt;
            p.rotation.z += p.angularVel.z * dt;

            // Ground bounce
            if (p.position.y < 0) {
                p.position.y = 0;
                p.velocity.y *= -0.2;
                p.velocity.x *= 0.75;
                p.velocity.z *= 0.75;
                p.angularVel.multiplyScalar(0.5);
            }

            // Update instance matrix
            this._dummyPos.copy(p.position);
            this._dummyQuat.setFromEuler(p.rotation);
            this._dummyScale.setScalar(p.scale);
            this._dummyMatrix.compose(this._dummyPos, this._dummyQuat, this._dummyScale);
            this.debrisMesh.setMatrixAt(i, this._dummyMatrix);
        }

        for (let i = toRemove.length - 1; i >= 0; i--) {
            this.debrisData.splice(toRemove[i], 1);
        }

        this.debrisMesh.count = this.debrisData.length;
        if (this.debrisData.length > 0) {
            this.debrisMesh.instanceMatrix.needsUpdate = true;
        }
    }

    _updateDust(dt) {
        const toRemove = [];

        for (let i = 0; i < this.dustData.length; i++) {
            const p = this.dustData[i];
            p.life += dt;

            if (p.life > p.maxLife) {
                toRemove.push(i);
                continue;
            }

            // Rise and spread
            p.velocity.y *= (1 - 0.4 * dt);
            p.position.x += p.velocity.x * dt;
            p.position.y += p.velocity.y * dt;
            p.position.z += p.velocity.z * dt;

            // Grow and fade
            p.scale += dt * 0.8;

            this._dummyPos.copy(p.position);
            this._dummyQuat.set(0, 0, 0, 1);
            this._dummyScale.setScalar(p.scale);
            this._dummyMatrix.compose(this._dummyPos, this._dummyQuat, this._dummyScale);
            this.dustMesh.setMatrixAt(i, this._dummyMatrix);
        }

        for (let i = toRemove.length - 1; i >= 0; i--) {
            this.dustData.splice(toRemove[i], 1);
        }

        this.dustMesh.count = this.dustData.length;
        if (this.dustData.length > 0) {
            this.dustMesh.instanceMatrix.needsUpdate = true;
        }
    }

    _updateMud(dt) {
        const toRemove = [];

        for (let i = 0; i < this.mudData.length; i++) {
            const p = this.mudData[i];
            p.life += dt;

            if (p.life > p.maxLife) {
                toRemove.push(i);
                continue;
            }

            this._dummyPos.copy(p.position);
            this._dummyQuat.set(0, 0, 0, 1);
            this._dummyScale.set(p.scale, p.scale * p.flatScale, p.scale);
            this._dummyMatrix.compose(this._dummyPos, this._dummyQuat, this._dummyScale);
            this.mudMesh.setMatrixAt(i, this._dummyMatrix);
        }

        for (let i = toRemove.length - 1; i >= 0; i--) {
            this.mudData.splice(toRemove[i], 1);
        }

        this.mudMesh.count = this.mudData.length;
        if (this.mudData.length > 0) {
            this.mudMesh.instanceMatrix.needsUpdate = true;
        }
    }

    /**
     * Reset all particles
     */
    reset() {
        this.debrisData = [];
        this.dustData = [];
        this.mudData = [];
        this.debrisMesh.count = 0;
        this.dustMesh.count = 0;
        this.mudMesh.count = 0;

        // Hide sliding mass
        this.slidingMass.material.opacity = 0;
        this.slidingMassTrail.material.opacity = 0;
    }
}
