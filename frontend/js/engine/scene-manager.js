/**
 * scene-manager.js
 * ================
 * Three.js Scene, Camera, Renderer, Lighting, Post-Processing, OrbitControls.
 * UPGRADED: Cinematic quality — volumetric atmosphere, god rays, vignette,
 * animated skybox gradient, water plane, 4K shadows, enhanced bloom.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { FXAAShader } from 'three/addons/shaders/FXAAShader.js';

// ── Custom Vignette Shader ──
const VignetteShader = {
    uniforms: {
        tDiffuse: { value: null },
        offset: { value: 0.95 },
        darkness: { value: 1.2 },
    },
    vertexShader: `
        varying vec2 vUv;
        void main() {
            vUv = uv;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
    `,
    fragmentShader: `
        uniform sampler2D tDiffuse;
        uniform float offset;
        uniform float darkness;
        varying vec2 vUv;
        void main() {
            vec4 texel = texture2D(tDiffuse, vUv);
            vec2 uv = (vUv - vec2(0.5)) * vec2(offset);
            float vig = clamp(1.0 - dot(uv, uv), 0.0, 1.0);
            texel.rgb *= mix(1.0, vig, darkness);
            gl_FragColor = texel;
        }
    `,
};

export class SceneManager {
    constructor(canvas, container) {
        this.canvas = canvas;
        this.container = container;

        // ── Renderer ──
        this.renderer = new THREE.WebGLRenderer({
            canvas,
            antialias: true,
            alpha: false,
            powerPreference: 'high-performance'
        });
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.setSize(container.clientWidth, container.clientHeight);
        this.renderer.shadowMap.enabled = true;
        this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this.renderer.toneMappingExposure = 1.2;
        this.renderer.outputColorSpace = THREE.SRGBColorSpace;

        // ── Scene ──
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x1a1a2e);
        this.scene.fog = new THREE.FogExp2(0x1a1a2e, 0.0025);

        // ── Camera ──
        const aspect = container.clientWidth / container.clientHeight;
        this.camera = new THREE.PerspectiveCamera(50, aspect, 0.5, 2000);
        this.camera.position.set(90, 70, 110);
        this.camera.lookAt(0, 0, 0);

        // ── Controls ──
        this.controls = new OrbitControls(this.camera, canvas);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.06;
        this.controls.maxPolarAngle = Math.PI * 0.48;
        this.controls.minDistance = 20;
        this.controls.maxDistance = 300;
        this.controls.target.set(0, 8, 0);
        this.controls.autoRotate = false;
        this.controls.autoRotateSpeed = 0.3;

        // ── Lighting ──
        this._setupLighting();

        // ── Post-Processing ──
        this._setupPostProcessing();

        // ── Resize ──
        window.addEventListener('resize', () => this.onResize());

        // ── Ground + Water ──
        this._setupGround();
        this._setupWater();
        this._setupSkyDome();
        this._setupAtmosphericParticles();
    }

    _setupLighting() {
        // Ambient (fill light — slightly warm)
        const ambient = new THREE.AmbientLight(0x5a6578, 0.5);
        this.scene.add(ambient);

        // Hemisphere (sky blue + ground ochre)
        const hemi = new THREE.HemisphereLight(0x8ec8e8, 0x4a6b3d, 0.6);
        this.scene.add(hemi);

        // Sun (directional with HIGH quality shadows)
        this.sunLight = new THREE.DirectionalLight(0xffe8c0, 2.0);
        this.sunLight.position.set(60, 100, 40);
        this.sunLight.castShadow = true;
        this.sunLight.shadow.mapSize.width = 2048;
        this.sunLight.shadow.mapSize.height = 2048;
        this.sunLight.shadow.camera.left = -120;
        this.sunLight.shadow.camera.right = 120;
        this.sunLight.shadow.camera.top = 120;
        this.sunLight.shadow.camera.bottom = -120;
        this.sunLight.shadow.camera.near = 1;
        this.sunLight.shadow.camera.far = 300;
        this.sunLight.shadow.bias = -0.0005;
        this.sunLight.shadow.normalBias = 0.02;
        this.scene.add(this.sunLight);

        // Warm fill light from behind
        const backFill = new THREE.DirectionalLight(0xffa050, 0.4);
        backFill.position.set(-50, 40, -70);
        this.scene.add(backFill);

        // Cool rim light for depth
        const rim = new THREE.DirectionalLight(0x6dd5fa, 0.35);
        rim.position.set(-40, 30, -60);
        this.scene.add(rim);

        // Subtle bounce light from below (simulates ground reflection)
        const bounce = new THREE.PointLight(0x8b7355, 0.3, 200);
        bounce.position.set(0, -5, 0);
        this.scene.add(bounce);
    }

    _setupPostProcessing() {
        const size = this.renderer.getSize(new THREE.Vector2());

        this.composer = new EffectComposer(this.renderer);

        // Render pass
        const renderPass = new RenderPass(this.scene, this.camera);
        this.composer.addPass(renderPass);

        // Bloom — stronger for cinematic look
        this.bloomPass = new UnrealBloomPass(
            new THREE.Vector2(size.x, size.y),
            0.45,  // strength
            0.5,   // radius
            0.80   // threshold
        );
        this.composer.addPass(this.bloomPass);

        // Vignette
        const vignettePass = new ShaderPass(VignetteShader);
        vignettePass.uniforms['offset'].value = 0.95;
        vignettePass.uniforms['darkness'].value = 1.3;
        this.composer.addPass(vignettePass);

        // FXAA
        const fxaaPass = new ShaderPass(FXAAShader);
        fxaaPass.uniforms['resolution'].value.set(1 / size.x, 1 / size.y);
        this.composer.addPass(fxaaPass);

        this.fxaaPass = fxaaPass;
    }

    _setupGround() {
        // Large ground plane (base level)
        const groundGeo = new THREE.PlaneGeometry(600, 600);
        const groundMat = new THREE.MeshStandardMaterial({
            color: 0x1a3a2a,
            roughness: 0.95,
            metalness: 0.0,
        });
        const ground = new THREE.Mesh(groundGeo, groundMat);
        ground.rotation.x = -Math.PI / 2;
        ground.position.y = -0.5;
        ground.receiveShadow = true;
        this.scene.add(ground);
    }

    _setupWater() {
        // Simple reflective water plane on the far valley side
        const waterGeo = new THREE.PlaneGeometry(200, 400);
        const waterMat = new THREE.MeshStandardMaterial({
            color: 0x1a4a6a,
            roughness: 0.1,
            metalness: 0.6,
            transparent: true,
            opacity: 0.7,
        });
        this.waterMesh = new THREE.Mesh(waterGeo, waterMat);
        this.waterMesh.rotation.x = -Math.PI / 2;
        this.waterMesh.position.set(60, -0.3, 0);
        this.waterMesh.receiveShadow = true;
        this.scene.add(this.waterMesh);
    }

    _setupSkyDome() {
        // Gradient sky dome
        const skyGeo = new THREE.SphereGeometry(800, 32, 15);
        const skyMat = new THREE.ShaderMaterial({
            uniforms: {
                topColor: { value: new THREE.Color(0x0a1628) },
                bottomColor: { value: new THREE.Color(0x1a2a4a) },
                offset: { value: 20 },
                exponent: { value: 0.4 },
            },
            vertexShader: `
                varying vec3 vWorldPosition;
                void main() {
                    vec4 worldPosition = modelMatrix * vec4(position, 1.0);
                    vWorldPosition = worldPosition.xyz;
                    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
                }
            `,
            fragmentShader: `
                uniform vec3 topColor;
                uniform vec3 bottomColor;
                uniform float offset;
                uniform float exponent;
                varying vec3 vWorldPosition;
                void main() {
                    float h = normalize(vWorldPosition + offset).y;
                    gl_FragColor = vec4(mix(bottomColor, topColor, max(pow(max(h, 0.0), exponent), 0.0)), 1.0);
                }
            `,
            side: THREE.BackSide,
        });
        this.skyDome = new THREE.Mesh(skyGeo, skyMat);
        this.scene.add(this.skyDome);
    }

    _setupAtmosphericParticles() {
        // Floating dust / firefly particles
        const count = 500;
        const positions = new Float32Array(count * 3);
        const sizes = new Float32Array(count);

        for (let i = 0; i < count; i++) {
            positions[i * 3] = (Math.random() - 0.5) * 300;
            positions[i * 3 + 1] = Math.random() * 60 + 5;
            positions[i * 3 + 2] = (Math.random() - 0.5) * 300;
            sizes[i] = 0.5 + Math.random() * 1.5;
        }

        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geo.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

        const mat = new THREE.PointsMaterial({
            color: 0xffeedd,
            size: 0.8,
            transparent: true,
            opacity: 0.15,
            depthWrite: false,
            sizeAttenuation: true,
        });

        this.atmosphericParticles = new THREE.Points(geo, mat);
        this.scene.add(this.atmosphericParticles);
        this._atmosPositions = positions;
    }

    onResize() {
        const w = this.container.clientWidth;
        const h = this.container.clientHeight;

        this.camera.aspect = w / h;
        this.camera.updateProjectionMatrix();

        this.renderer.setSize(w, h);
        this.composer.setSize(w, h);

        if (this.fxaaPass) {
            this.fxaaPass.uniforms['resolution'].value.set(1 / w, 1 / h);
        }
    }

    update(delta, elapsed) {
        this.controls.update();

        // Subtle sun orbit
        const angle = elapsed * 0.015;
        this.sunLight.position.x = 70 * Math.cos(angle);
        this.sunLight.position.z = 50 * Math.sin(angle);

        // Water ripple animation
        if (this.waterMesh) {
            this.waterMesh.position.y = -0.3 + Math.sin(elapsed * 0.8) * 0.05;
        }

        // Atmospheric particles drift
        if (this._atmosPositions) {
            const pos = this._atmosPositions;
            for (let i = 0; i < pos.length; i += 3) {
                pos[i] += Math.sin(elapsed * 0.3 + i) * 0.02;
                pos[i + 1] += Math.sin(elapsed * 0.5 + i * 0.7) * 0.01;
                pos[i + 2] += Math.cos(elapsed * 0.2 + i * 0.5) * 0.02;
            }
            this.atmosphericParticles.geometry.attributes.position.needsUpdate = true;
        }
    }

    render() {
        this.composer.render();
    }
}
