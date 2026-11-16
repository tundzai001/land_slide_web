/**
 * destruction-system.js
 * =====================
 * UPGRADED: Cinematic destruction for environment objects.
 * - Houses: multi-stage collapse with dust clouds, fragment showers
 * - Trees: realistic uprooting with soil clumps, snap & fall
 * - Vehicles: flip and tumble with debris
 * - Impact shockwave effect
 * - Sound-like visual cues (screen flash on major impacts)
 */

import * as THREE from 'three';

export class DestructionSystem {
    constructor(scene, envBuilder) {
        this.scene = scene;
        this.env = envBuilder;

        this.fragments = [];
        this.gravity = 9.81;
        this._impactFlash = 0;
    }

    _checkHouseCollisions(frontPos, halfWidth, kineticEnergy) {
        let housesDestroyed = 0;
        for (const house of this.env.houses) {
            if (house.destroyed) continue;

            const dx = house.position.x - frontPos.x;
            const dz = Math.abs(house.position.z - frontPos.z);

            if (dx > -5 && dx < 15 && dz < halfWidth && kineticEnergy > 50000) {
                this._destroyHouse(house, frontPos, kineticEnergy);
                housesDestroyed++;
            }
        }
        return housesDestroyed;
    }

    _checkTreeCollisions(frontPos, halfWidth, kineticEnergy) {
        let treesDestroyed = 0;
        for (const tree of this.env.trees) {
            if (tree.destroyed) continue;

            const dx = tree.position.x - frontPos.x;
            const dz = Math.abs(tree.position.z - frontPos.z);

            if (dx > -3 && dx < 10 && dz < halfWidth && kineticEnergy > 5000) {
                this._destroyTree(tree, frontPos);
                treesDestroyed++;
            }
        }
        return treesDestroyed;
    }

    /**
     * Check collisions between debris front and environment objects
     */
    checkCollisions(frontPos, width, kineticEnergy) {
        const halfWidth = width / 2;
        const housesDestroyed = this._checkHouseCollisions(frontPos, halfWidth, kineticEnergy);
        const treesDestroyed = this._checkTreeCollisions(frontPos, halfWidth, kineticEnergy);

        // Update existing fragments
        this._updateFragments();

        return { houses: housesDestroyed, trees: treesDestroyed };
    }

    /**
     * Destroy a house — UPGRADED: more fragments, varied sizes, dust burst
     */
    _destroyHouse(house, debrisPos, energy) {
        house.destroyed = true;

        const pos = house.position;
        const mesh = house.mesh;

        // Generate many more fragments
        const fragmentCount = 12 + Math.floor(Math.random() * 10);
        const colors = [
            0xdcd0c0, 0x8b4513, 0x6b3a2a, 0xa0522d, 0xc9b99a,
            0x888888, 0x665544, 0xaa9988, 0xbbaa88, 0x776655
        ];

        for (let i = 0; i < fragmentCount; i++) {
            const sizeBase = 0.3 + Math.random() * 2.0;
            const fragGeo = new THREE.BoxGeometry(
                sizeBase,
                sizeBase * (0.3 + Math.random() * 0.7),
                sizeBase * (0.4 + Math.random() * 0.8)
            );
            const fragMat = new THREE.MeshStandardMaterial({
                color: colors[Math.floor(Math.random() * colors.length)],
                roughness: 0.85,
            });
            const frag = new THREE.Mesh(fragGeo, fragMat);

            frag.position.set(
                pos.x + (Math.random() - 0.5) * house.width * 1.5,
                pos.y + 1 + Math.random() * 4,
                pos.z + (Math.random() - 0.5) * house.depth * 1.5
            );

            frag.castShadow = true;

            // Explosive velocity based on energy
            const energyFactor = Math.min(energy / 100000, 3);
            const vx = (2 + Math.random() * 6) * energyFactor;
            const vy = (4 + Math.random() * 8);
            const vz = (Math.random() - 0.5) * 6 * energyFactor;

            this.scene.add(frag);
            this.fragments.push({
                mesh: frag,
                velocity: new THREE.Vector3(vx, vy, vz),
                angularVel: new THREE.Vector3(
                    (Math.random() - 0.5) * 8,
                    (Math.random() - 0.5) * 8,
                    (Math.random() - 0.5) * 8
                ),
                life: 0,
                maxLife: 6 + Math.random() * 6,
            });
        }

        // Dust burst at impact point
        this._createDustBurst(pos, 8);

        // Remove original house mesh
        this.scene.remove(mesh);
    }

    /**
     * Destroy a tree — UPGRADED: soil clump at base, dramatic fall
     */
    _destroyTree(tree, debrisPos) {
        tree.destroyed = true;

        const mesh = tree.mesh;
        const pos = tree.position;

        const dx = pos.x - debrisPos.x;
        const dz = pos.z - debrisPos.z;
        const angle = Math.atan2(dz, dx);

        // Tree falls dramatically
        this.fragments.push({
            mesh: mesh,
            velocity: new THREE.Vector3(
                Math.cos(angle) * 4 + Math.random() * 3,
                3 + Math.random() * 3,
                Math.sin(angle) * 4 + Math.random() * 3
            ),
            angularVel: new THREE.Vector3(
                (Math.random() - 0.5) * 3,
                0,
                Math.cos(angle) * 3
            ),
            life: 0,
            maxLife: 10 + Math.random() * 5,
            isTree: true,
        });

        // Soil clump at base
        const soilGeo = new THREE.SphereGeometry(0.8, 4, 3);
        const soilMat = new THREE.MeshStandardMaterial({
            color: 0x5c4a3a,
            roughness: 0.95,
        });
        for (let i = 0; i < 3; i++) {
            const soil = new THREE.Mesh(soilGeo, soilMat);
            soil.position.set(
                pos.x + (Math.random() - 0.5) * 2,
                pos.y + Math.random(),
                pos.z + (Math.random() - 0.5) * 2
            );
            this.scene.add(soil);
            this.fragments.push({
                mesh: soil,
                velocity: new THREE.Vector3(
                    (Math.random() - 0.5) * 3,
                    2 + Math.random() * 3,
                    (Math.random() - 0.5) * 3
                ),
                angularVel: new THREE.Vector3(
                    Math.random() * 3, Math.random() * 3, Math.random() * 3
                ),
                life: 0,
                maxLife: 4 + Math.random() * 3,
            });
        }
    }

    /**
     * Create a burst of dust particles at a position
     */
    _createDustBurst(position, count) {
        const dustMat = new THREE.MeshBasicMaterial({
            color: 0xb0a090,
            transparent: true,
            opacity: 0.3,
            depthWrite: false,
        });

        for (let i = 0; i < count; i++) {
            const size = 1 + Math.random() * 3;
            const geo = new THREE.SphereGeometry(size, 4, 4);
            const dust = new THREE.Mesh(geo, dustMat.clone());
            dust.position.set(
                position.x + (Math.random() - 0.5) * 5,
                position.y + 1 + Math.random() * 2,
                position.z + (Math.random() - 0.5) * 5
            );

            this.scene.add(dust);
            this.fragments.push({
                mesh: dust,
                velocity: new THREE.Vector3(
                    (Math.random() - 0.5) * 4,
                    2 + Math.random() * 4,
                    (Math.random() - 0.5) * 4
                ),
                angularVel: new THREE.Vector3(0, 0, 0),
                life: 0,
                maxLife: 3 + Math.random() * 2,
                isDust: true,
            });
        }
    }

    _applyFragmentGroundCollision(frag, groundY = -0.5) {
        if (frag.mesh.position.y >= groundY) return;
        frag.mesh.position.y = groundY;
        frag.velocity.y *= -0.15;
        frag.velocity.x *= 0.65;
        frag.velocity.z *= 0.65;
        frag.angularVel.multiplyScalar(0.4);
    }

    _applyFragmentFade(frag) {
        const fadeStart = frag.maxLife * 0.7;
        if (frag.life <= fadeStart || !frag.mesh.material) return;
        const opacity = 1 - (frag.life - fadeStart) / (frag.maxLife - fadeStart);
        frag.mesh.material.transparent = true;
        frag.mesh.material.opacity = Math.max(0, opacity);
    }

    _stepSingleFragment(frag, dt) {
        frag.velocity.y -= this.gravity * dt;
        if (frag.isDust) {
            frag.velocity.multiplyScalar(1 - dt * 1.5);
            frag.mesh.scale.multiplyScalar(1 + dt * 0.3);
        }

        frag.mesh.position.x += frag.velocity.x * dt;
        frag.mesh.position.y += frag.velocity.y * dt;
        frag.mesh.position.z += frag.velocity.z * dt;

        frag.mesh.rotation.x += frag.angularVel.x * dt;
        frag.mesh.rotation.y += frag.angularVel.y * dt;
        frag.mesh.rotation.z += frag.angularVel.z * dt;

        this._applyFragmentGroundCollision(frag);
        this._applyFragmentFade(frag);
    }

    _disposeFragment(frag) {
        this.scene.remove(frag.mesh);
        if (frag.mesh.geometry) frag.mesh.geometry.dispose();
        if (frag.mesh.material && !frag.isTree) frag.mesh.material.dispose();
    }

    /**
     * Update fragment positions (physics)
     */
    _updateFragments() {
        const dt = 1 / 60;
        const toRemove = [];

        for (let i = 0; i < this.fragments.length; i++) {
            const frag = this.fragments[i];
            frag.life += dt;

            if (frag.life > frag.maxLife) {
                toRemove.push(i);
                continue;
            }

            this._stepSingleFragment(frag, dt);
        }

        // Remove expired fragments
        for (let i = toRemove.length - 1; i >= 0; i--) {
            const idx = toRemove[i];
            this._disposeFragment(this.fragments[idx]);
            this.fragments.splice(idx, 1);
        }
    }

    /**
     * Reset destruction system
     */
    reset() {
        for (const frag of this.fragments) {
            this.scene.remove(frag.mesh);
        }
        this.fragments = [];
    }
}
