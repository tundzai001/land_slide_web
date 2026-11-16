/**
 * environment-builder.js
 * ======================
 * UPGRADED: Rich village environment with varied architecture,
 * multiple tree species, detailed roads with lane markings,
 * power poles with wires, fences, rocks, vehicles, bridges.
 */

import * as THREE from 'three';

export class EnvironmentBuilder {
    constructor(scene, terrainGen, houseCount = 40, treeCount = 300) {
        this.scene = scene;
        this.terrain = terrainGen;
        this.houseCount = houseCount;
        this.treeCount = treeCount;

        this.houses = [];
        this.trees = [];
        this.roads = [];
        this.allObjects = [];
    }

    build() {
        this._buildHouses();
        this._buildTrees();
        this._buildRoad();
        this._buildPowerPoles();
        this._buildRocks();
        this._buildVehicles();
        this._buildFences();
        this._buildBushes();
    }

    clear() {
        for (const obj of this.allObjects) {
            this.scene.remove(obj);
            if (obj.geometry) obj.geometry.dispose();
            if (obj.material) {
                if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
                else obj.material.dispose();
            }
        }
        this.allObjects = [];
        this.houses = [];
        this.trees = [];
        this.roads = [];
    }

    // ─── HOUSES ──────────────────────────────────────────────────────
    _buildHouses() {
        const wallColors = [
            0xdcd0c0, 0xc9b99a, 0xe8d8c4, 0xb8a088, 0xf5ebe0,
            0xd4c4a8, 0xc8b494, 0xe0d2be, 0xbfae94, 0xd8cbb8,
            0xf0e6d2, 0xe5dcc8, 0xd0c8b0, 0xc5b898, 0xeae0cc
        ];
        const roofColors = [
            0x8b4513, 0xa0522d, 0x6b3a2a, 0x954535, 0x7c3a1e,
            0xb85c3c, 0x9c4828, 0x804020, 0xc4633a, 0x703020
        ];

        let placed = 0;
        let attempts = 0;
        const maxAttempts = this.houseCount * 10;

        while (placed < this.houseCount && attempts < maxAttempts) {
            attempts++;
            const x = (Math.random() - 0.3) * this.terrain.width * 0.5;
            const z = (Math.random() - 0.5) * this.terrain.depth * 0.7;

            const h = this.terrain.getHeightAt(x, z);
            const slope = this.terrain.getSlopeAt(x, z);

            if (slope > 25 || h > 25 || h < -1) continue;

            placed++;

            const houseW = 3 + Math.random() * 4;
            const houseH = 3 + Math.random() * 2.5;
            const houseD = 3 + Math.random() * 4;

            const group = new THREE.Group();
            group.position.set(x, h, z);

            // Wall
            const wallGeo = new THREE.BoxGeometry(houseW, houseH, houseD);
            const wallMat = new THREE.MeshStandardMaterial({
                color: wallColors[placed % wallColors.length],
                roughness: 0.75,
                metalness: 0.05,
            });
            const wall = new THREE.Mesh(wallGeo, wallMat);
            wall.position.y = houseH / 2;
            wall.castShadow = true;
            wall.receiveShadow = true;
            group.add(wall);

            // Roof (pitched)
            const roofGeo = new THREE.ConeGeometry(
                Math.max(houseW, houseD) * 0.78,
                2 + Math.random() * 1.5,
                4
            );
            const roofMat = new THREE.MeshStandardMaterial({
                color: roofColors[placed % roofColors.length],
                roughness: 0.65,
                metalness: 0.1,
            });
            const roof = new THREE.Mesh(roofGeo, roofMat);
            roof.position.y = houseH + 1.2;
            roof.rotation.y = Math.PI / 4;
            roof.castShadow = true;
            group.add(roof);

            // Door (small dark rectangle on front face)
            const doorGeo = new THREE.PlaneGeometry(1, 2);
            const doorMat = new THREE.MeshStandardMaterial({
                color: 0x3a2a1a,
                roughness: 0.9,
            });
            const door = new THREE.Mesh(doorGeo, doorMat);
            door.position.set(0, 1, houseD / 2 + 0.01);
            group.add(door);

            // Windows (2 small blue squares)
            const winGeo = new THREE.PlaneGeometry(0.7, 0.7);
            const winMat = new THREE.MeshStandardMaterial({
                color: 0x88bbdd,
                roughness: 0.3,
                metalness: 0.4,
                emissive: 0x223344,
                emissiveIntensity: 0.3,
            });
            const win1 = new THREE.Mesh(winGeo, winMat);
            win1.position.set(-houseW * 0.3, houseH * 0.6, houseD / 2 + 0.01);
            group.add(win1);
            const win2 = new THREE.Mesh(winGeo, winMat);
            win2.position.set(houseW * 0.3, houseH * 0.6, houseD / 2 + 0.01);
            group.add(win2);

            // Small chimney on some houses
            if (Math.random() > 0.6) {
                const chimGeo = new THREE.BoxGeometry(0.5, 1.5, 0.5);
                const chimMat = new THREE.MeshStandardMaterial({
                    color: 0x665544,
                    roughness: 0.9,
                });
                const chimney = new THREE.Mesh(chimGeo, chimMat);
                chimney.position.set(houseW * 0.3, houseH + 2.5, 0);
                chimney.castShadow = true;
                group.add(chimney);
            }

            group.rotation.y = Math.random() * Math.PI * 2;

            this.scene.add(group);
            this.allObjects.push(group);

            this.houses.push({
                mesh: group,
                position: new THREE.Vector3(x, h, z),
                destroyed: false,
                width: houseW,
                depth: houseD,
                fragments: []
            });
        }
    }

    // ─── TREES ───────────────────────────────────────────────────────
    _buildTrees() {
        const trunkGeo = new THREE.CylinderGeometry(0.2, 0.4, 4, 6);
        const trunkMat = new THREE.MeshStandardMaterial({
            color: 0x5c3a1e,
            roughness: 0.9,
        });

        let placed = 0;
        let attempts = 0;
        const maxAttempts = this.treeCount * 10;

        while (placed < this.treeCount && attempts < maxAttempts) {
            attempts++;
            const x = (Math.random() - 0.5) * this.terrain.width * 0.88;
            const z = (Math.random() - 0.5) * this.terrain.depth * 0.88;

            const h = this.terrain.getHeightAt(x, z);
            const slope = this.terrain.getSlopeAt(x, z);

            if (slope > 40 || h < -1) continue;
            if (h > 30 && Math.random() > 0.3) continue;

            placed++;

            const scale = 0.5 + Math.random() * 1.0;
            const group = new THREE.Group();
            group.position.set(x, h, z);
            group.scale.set(scale, scale, scale);

            // Trunk
            const trunk = new THREE.Mesh(trunkGeo, trunkMat);
            trunk.position.y = 2;
            trunk.castShadow = true;
            group.add(trunk);

            // Pick tree type: pine (70%), deciduous (20%), palm (10%)
            const treeType = Math.random();
            
            if (treeType < 0.7) {
                // Pine tree — layered cones
                const layers = 2 + Math.floor(Math.random() * 2);
                for (let l = 0; l < layers; l++) {
                    const coneSize = 3.0 - l * 0.6;
                    const coneH = 4.0 - l * 0.8;
                    const canopyGeo = new THREE.ConeGeometry(coneSize, coneH, 7);
                    const canopyMat = new THREE.MeshStandardMaterial({
                        roughness: 0.8,
                    });
                    canopyMat.color.setHSL(
                        0.28 + Math.random() * 0.08,
                        0.45 + Math.random() * 0.25,
                        0.2 + Math.random() * 0.12
                    );
                    const canopy = new THREE.Mesh(canopyGeo, canopyMat);
                    canopy.position.y = 4.5 + l * 2.2;
                    canopy.castShadow = true;
                    group.add(canopy);
                }
            } else if (treeType < 0.9) {
                // Deciduous — sphere canopy
                const canopyGeo = new THREE.SphereGeometry(3, 8, 6);
                const canopyMat = new THREE.MeshStandardMaterial({ roughness: 0.8 });
                canopyMat.color.setHSL(
                    0.25 + Math.random() * 0.1,
                    0.5 + Math.random() * 0.3,
                    0.22 + Math.random() * 0.1
                );
                const canopy = new THREE.Mesh(canopyGeo, canopyMat);
                canopy.position.y = 6;
                canopy.castShadow = true;
                group.add(canopy);
            } else {
                // Palm tree — tall thin trunk + fan
                trunk.scale.y = 2;
                trunk.position.y = 4;
                const fanGeo = new THREE.SphereGeometry(2.5, 6, 4);
                const fanMat = new THREE.MeshStandardMaterial({
                    color: 0x2a7a3a,
                    roughness: 0.7,
                });
                const fan = new THREE.Mesh(fanGeo, fanMat);
                fan.scale.set(1, 0.4, 1);
                fan.position.y = 9;
                fan.castShadow = true;
                group.add(fan);
            }

            // Slight random lean
            group.rotation.z = (Math.random() - 0.5) * 0.1;
            group.rotation.x = (Math.random() - 0.5) * 0.1;

            this.scene.add(group);
            this.allObjects.push(group);

            this.trees.push({
                mesh: group,
                position: new THREE.Vector3(x, h, z),
                destroyed: false,
                originalRotation: group.rotation.clone()
            });
        }
    }

    // ─── ROAD ────────────────────────────────────────────────────────
    _buildRoad() {
        const points = [];
        const roadWidth = 5;

        for (let i = -85; i <= 85; i += 2) {
            const z = i;
            const x = 20 + Math.sin(z * 0.025) * 12;
            const y = this.terrain.getHeightAt(x, z) + 0.18;
            points.push(new THREE.Vector3(x, y, z));
        }

        if (points.length < 2) return;

        const roadGeo = new THREE.BufferGeometry();
        const vertices = [];
        const indices = [];

        for (let i = 0; i < points.length; i++) {
            const p = points[i];
            const next = points[Math.min(i + 1, points.length - 1)];
            const prev = points[Math.max(i - 1, 0)];
            const dir = new THREE.Vector3().subVectors(next, prev).normalize();
            const perp = new THREE.Vector3(-dir.z, 0, dir.x).multiplyScalar(roadWidth / 2);

            const left = new THREE.Vector3().addVectors(p, perp);
            const right = new THREE.Vector3().subVectors(p, perp);

            vertices.push(left.x, left.y, left.z, right.x, right.y, right.z);

            if (i < points.length - 1) {
                const idx = i * 2;
                indices.push(idx, idx + 1, idx + 2, idx + 1, idx + 3, idx + 2);
            }
        }

        roadGeo.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
        roadGeo.setIndex(indices);
        roadGeo.computeVertexNormals();

        const roadMat = new THREE.MeshStandardMaterial({
            color: 0x3a3a3a,
            roughness: 0.92,
            metalness: 0.0,
        });

        const roadMesh = new THREE.Mesh(roadGeo, roadMat);
        roadMesh.receiveShadow = true;
        this.scene.add(roadMesh);
        this.allObjects.push(roadMesh);
        this.roads.push(roadMesh);

        // Center line markings
        this._buildRoadMarkings(points);
    }

    _buildRoadMarkings(points) {
        const dashLength = 3;
        const gapLength = 3;
        const markMat = new THREE.MeshBasicMaterial({ color: 0xdddd88 });

        let accum = 0;
        let drawing = true;

        for (let i = 0; i < points.length - 1; i++) {
            const p = points[i];
            const n = points[i + 1];
            const segLen = p.distanceTo(n);
            accum += segLen;

            if (drawing) {
                const markGeo = new THREE.PlaneGeometry(segLen, 0.15);
                const mark = new THREE.Mesh(markGeo, markMat);
                const mid = new THREE.Vector3().lerpVectors(p, n, 0.5);
                mark.position.copy(mid);
                mark.position.y += 0.02;
                mark.rotation.x = -Math.PI / 2;
                const dir = new THREE.Vector3().subVectors(n, p);
                mark.rotation.z = -Math.atan2(dir.z, dir.x);
                this.scene.add(mark);
                this.allObjects.push(mark);
            }

            if (accum > (drawing ? dashLength : gapLength)) {
                accum = 0;
                drawing = !drawing;
            }
        }
    }

    // ─── POWER POLES ──────────────────────────────────────────────────
    _buildPowerPoles() {
        const poleMat = new THREE.MeshStandardMaterial({
            color: 0x6b5b45,
            roughness: 0.9,
        });
        const poleGeo = new THREE.CylinderGeometry(0.15, 0.22, 9, 6);
        const armGeo = new THREE.BoxGeometry(4, 0.12, 0.12);
        const wireMat = new THREE.LineBasicMaterial({ color: 0x333333 });

        const poles = [];

        for (let z = -60; z <= 60; z += 22) {
            const x = 27 + Math.sin(z * 0.025) * 12;
            const y = this.terrain.getHeightAt(x, z);

            const group = new THREE.Group();
            group.position.set(x, y, z);

            const pole = new THREE.Mesh(poleGeo, poleMat);
            pole.position.y = 4.5;
            pole.castShadow = true;
            group.add(pole);

            const arm = new THREE.Mesh(armGeo, poleMat);
            arm.position.y = 8.5;
            group.add(arm);

            // Insulators
            const insGeo = new THREE.CylinderGeometry(0.08, 0.08, 0.3, 4);
            const insMat = new THREE.MeshStandardMaterial({ color: 0x445566, metalness: 0.5 });
            for (const xOff of [-1.5, 0, 1.5]) {
                const ins = new THREE.Mesh(insGeo, insMat);
                ins.position.set(xOff, 8.7, 0);
                group.add(ins);
            }

            this.scene.add(group);
            this.allObjects.push(group);
            poles.push(new THREE.Vector3(x, y + 8.7, z));
        }

        // Draw wires between poles
        for (let i = 0; i < poles.length - 1; i++) {
            for (const xOff of [-1.5, 0, 1.5]) {
                const wirePoints = [];
                const p1 = poles[i].clone();
                const p2 = poles[i + 1].clone();
                p1.x += xOff;
                p2.x += xOff;
                const steps = 10;
                for (let s = 0; s <= steps; s++) {
                    const t = s / steps;
                    const pt = new THREE.Vector3().lerpVectors(p1, p2, t);
                    // Parabolic sag
                    pt.y += (t * (1 - t)) * -3;
                    wirePoints.push(pt);
                }
                const wireGeo = new THREE.BufferGeometry().setFromPoints(wirePoints);
                const wire = new THREE.Line(wireGeo, wireMat);
                this.scene.add(wire);
                this.allObjects.push(wire);
            }
        }
    }

    // ─── ROCKS ──────────────────────────────────────────────────────
    _buildRocks() {
        const rockMat = new THREE.MeshStandardMaterial({
            color: 0x6a6a6a,
            roughness: 0.95,
            metalness: 0.05,
        });

        for (let i = 0; i < 80; i++) {
            const x = (Math.random() - 0.5) * this.terrain.width * 0.9;
            const z = (Math.random() - 0.5) * this.terrain.depth * 0.9;
            const h = this.terrain.getHeightAt(x, z);
            const slope = this.terrain.getSlopeAt(x, z);

            // More rocks on steep slopes
            if (slope < 15 && Math.random() > 0.3) continue;

            const size = 0.3 + Math.random() * 2.0;
            const geo = new THREE.DodecahedronGeometry(size, 0);
            const mat = rockMat.clone();
            mat.color.setHSL(0.08, 0.1, 0.3 + Math.random() * 0.15);

            const rock = new THREE.Mesh(geo, mat);
            rock.position.set(x, h + size * 0.3, z);
            rock.rotation.set(
                Math.random() * Math.PI,
                Math.random() * Math.PI,
                Math.random() * Math.PI
            );
            rock.scale.set(1, 0.6 + Math.random() * 0.4, 1);
            rock.castShadow = true;
            rock.receiveShadow = true;

            this.scene.add(rock);
            this.allObjects.push(rock);
        }
    }

    // ─── VEHICLES ──────────────────────────────────────────────────
    _buildVehicles() {
        const vehicleColors = [0xcc3333, 0x3366cc, 0x33aa33, 0xdddd33, 0xeeeeee, 0x333333];

        for (let i = 0; i < 6; i++) {
            const z = -50 + i * 20 + (Math.random() - 0.5) * 10;
            const x = 20 + Math.sin(z * 0.025) * 12 + (Math.random() - 0.5) * 3;
            const y = this.terrain.getHeightAt(x, z) + 0.3;

            const group = new THREE.Group();
            group.position.set(x, y, z);

            // Body
            const bodyGeo = new THREE.BoxGeometry(2.2, 1, 4);
            const bodyMat = new THREE.MeshStandardMaterial({
                color: vehicleColors[i % vehicleColors.length],
                roughness: 0.4,
                metalness: 0.5,
            });
            const body = new THREE.Mesh(bodyGeo, bodyMat);
            body.position.y = 0.5;
            body.castShadow = true;
            group.add(body);

            // Cabin (smaller box on top)
            const cabGeo = new THREE.BoxGeometry(1.8, 0.8, 2);
            const cabMat = new THREE.MeshStandardMaterial({
                color: 0x88bbcc,
                roughness: 0.2,
                metalness: 0.6,
                transparent: true,
                opacity: 0.7,
            });
            const cab = new THREE.Mesh(cabGeo, cabMat);
            cab.position.set(0, 1.2, -0.3);
            group.add(cab);

            // Wheels
            const wheelGeo = new THREE.CylinderGeometry(0.3, 0.3, 0.2, 8);
            const wheelMat = new THREE.MeshStandardMaterial({ color: 0x222222, roughness: 0.9 });
            for (const [wx, wz] of [[-1.1, -1.3], [1.1, -1.3], [-1.1, 1.3], [1.1, 1.3]]) {
                const wheel = new THREE.Mesh(wheelGeo, wheelMat);
                wheel.rotation.z = Math.PI / 2;
                wheel.position.set(wx, 0, wz);
                group.add(wheel);
            }

            group.rotation.y = Math.atan2(
                Math.cos((z + 2) * 0.025) * 12 - Math.cos(z * 0.025) * 12,
                2
            );

            this.scene.add(group);
            this.allObjects.push(group);
        }
    }

    // ─── FENCES ──────────────────────────────────────────────────
    _buildFences() {
        const fenceMat = new THREE.MeshStandardMaterial({
            color: 0x8b7355,
            roughness: 0.9,
        });

        // Fence along road edge
        for (let z = -60; z <= 60; z += 4) {
            const x = 14 + Math.sin(z * 0.025) * 12;
            const y = this.terrain.getHeightAt(x, z);

            // Post
            const postGeo = new THREE.CylinderGeometry(0.06, 0.06, 1.2, 4);
            const post = new THREE.Mesh(postGeo, fenceMat);
            post.position.set(x, y + 0.6, z);
            post.castShadow = true;
            this.scene.add(post);
            this.allObjects.push(post);

            // Rail
            if (z < 60) {
                const nextX = 14 + Math.sin((z + 4) * 0.025) * 12;
                const nextY = this.terrain.getHeightAt(nextX, z + 4);
                const railLen = Math.sqrt((nextX - x) ** 2 + 16);
                const railGeo = new THREE.BoxGeometry(0.06, 0.06, railLen);
                const rail = new THREE.Mesh(railGeo, fenceMat);
                const midX = (x + nextX) / 2;
                const midY = (y + nextY) / 2 + 0.9;
                rail.position.set(midX, midY, z + 2);
                rail.lookAt(nextX, nextY + 0.9, z + 4);
                this.scene.add(rail);
                this.allObjects.push(rail);
            }
        }
    }

    // ─── BUSHES ──────────────────────────────────────────────────
    _buildBushes() {
        for (let i = 0; i < 120; i++) {
            const x = (Math.random() - 0.5) * this.terrain.width * 0.85;
            const z = (Math.random() - 0.5) * this.terrain.depth * 0.85;
            const h = this.terrain.getHeightAt(x, z);
            const slope = this.terrain.getSlopeAt(x, z);

            if (slope > 35 || h < -1 || h > 35) continue;

            const size = 0.4 + Math.random() * 1.2;
            const geo = new THREE.SphereGeometry(size, 5, 4);
            const mat = new THREE.MeshStandardMaterial({ roughness: 0.85 });
            mat.color.setHSL(
                0.25 + Math.random() * 0.1,
                0.5 + Math.random() * 0.3,
                0.15 + Math.random() * 0.1
            );
            const bush = new THREE.Mesh(geo, mat);
            bush.position.set(x, h + size * 0.5, z);
            bush.scale.y = 0.6 + Math.random() * 0.3;
            bush.castShadow = true;

            this.scene.add(bush);
            this.allObjects.push(bush);
        }
    }
}
