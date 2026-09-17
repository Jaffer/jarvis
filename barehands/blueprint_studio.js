/**
 * J.A.R.V.I.S. Cinematic 3D Holographic Engineering & Science Simulation Suite
 * Movie-accurate 3D Blueprints, Real-World Physics Solvers, Exploded View, & Web Audio
 * Integrated with Barehands Board (stage.html)
 */

import * as THREE from "three";

// ══════════════════════════════════════════════════════════════════════════════
// 1. PROCEDURAL SCI-FI AUDIO SYNTHESIZER (Web Audio API)
// ══════════════════════════════════════════════════════════════════════════════
export class HolographicAudio {
  static ctx = null;
  static init() {
    if (!this.ctx) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) this.ctx = new AudioContext();
    }
    if (this.ctx && this.ctx.state === "suspended") {
      this.ctx.resume().catch(() => {});
    }
  }

  static playBoot() {
    this.init();
    if (!this.ctx) return;
    const notes = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6
    notes.forEach((freq, idx) => {
      setTimeout(() => {
        try {
          const osc = this.ctx.createOscillator();
          const gain = this.ctx.createGain();
          osc.type = "sine";
          osc.frequency.setValueAtTime(freq, this.ctx.currentTime);
          gain.gain.setValueAtTime(0.08, this.ctx.currentTime);
          gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.35);
          osc.connect(gain);
          gain.connect(this.ctx.destination);
          osc.start();
          osc.stop(this.ctx.currentTime + 0.36);
        } catch (e) {}
      }, idx * 60);
    });
  }

  static playServo(direction = 1) {
    this.init();
    if (!this.ctx) return;
    try {
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = "triangle";
      const startF = direction > 0 ? 160 : 480;
      const endF = direction > 0 ? 480 : 160;
      osc.frequency.setValueAtTime(startF, this.ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(endF, this.ctx.currentTime + 0.25);
      gain.gain.setValueAtTime(0.06, this.ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.26);
      osc.connect(gain);
      gain.connect(this.ctx.destination);
      osc.start();
      osc.stop(this.ctx.currentTime + 0.27);
    } catch (e) {}
  }

  static playAlarm() {
    this.init();
    if (!this.ctx) return;
    try {
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = "sawtooth";
      osc.frequency.setValueAtTime(880, this.ctx.currentTime);
      osc.frequency.setValueAtTime(440, this.ctx.currentTime + 0.12);
      gain.gain.setValueAtTime(0.07, this.ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.24);
      osc.connect(gain);
      gain.connect(this.ctx.destination);
      osc.start();
      osc.stop(this.ctx.currentTime + 0.25);
    } catch (e) {}
  }

  static playClick() {
    this.init();
    if (!this.ctx) return;
    try {
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(1400, this.ctx.currentTime);
      gain.gain.setValueAtTime(0.05, this.ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.08);
      osc.connect(gain);
      gain.connect(this.ctx.destination);
      osc.start();
      osc.stop(this.ctx.currentTime + 0.09);
    } catch (e) {}
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// 2. REAL-WORLD SCIENCE PHYSICS SOLVER ENGINE
// ══════════════════════════════════════════════════════════════════════════════
export class PhysicsSimulator {
  constructor() {
    this.mode = "thermal"; // "thermal" | "stress" | "em_field" | "aerodynamics"
    this.stressLevel = 1.0; // 0.5 to 2.0
    this.time = 0;
    this.telemetry = {};
    this.alert = null;
    this._lastAlarmTime = 0;
  }

  update(dt, constructName) {
    this.time += dt;
    const s = this.stressLevel;

    if (constructName.includes("arc") || constructName.includes("reactor")) {
      // Tokamak Plasma Fusion & Thermal Dissipation
      // Fourier heat flux: Q = -k * dT/dx + epsilon * sigma * (T^4 - T0^4)
      const baseTemp = 950;
      const currentTempK = Math.round(baseTemp + s * 380 + Math.sin(this.time * 4) * 15);
      const meltLimitK = 1668; // Titanium melting point
      const thermalFluxMW = (s * 4.8 + Math.cos(this.time * 2) * 0.2).toFixed(2);
      // Beta confinement ratio: beta = (2*mu0*p) / B^2
      const bFieldTesla = (12.4 + s * 1.8).toFixed(1);
      const betaRatio = Math.max(70, Math.min(99.4, (98.5 - s * 4.2 + Math.sin(this.time * 3) * 1.2))).toFixed(1);
      // von Mises stress: sigma_v
      const vonMisesMPa = Math.round(380 * s + Math.sin(this.time * 5) * 20);
      const yieldMPa = 550;
      const safetyFactor = (yieldMPa / Math.max(1, vonMisesMPa)).toFixed(2);

      this.telemetry = {
        primaryLabel: "CORE TEMPERATURE",
        primaryVal: `${currentTempK} K (${currentTempK - 273}°C)`,
        secondaryLabel: "B-FIELD CONFINEMENT",
        secondaryVal: `${bFieldTesla} T (${betaRatio}% stability)`,
        tertiaryLabel: "VON MISES STRESS",
        tertiaryVal: `${vonMisesMPa} MPa (SF: ${safetyFactor})`,
        formula: "Q = -k∇T + εσ(T⁴ - T₀⁴)   |   β = 2μ₀p / B²",
        nominal: safetyFactor >= 1.0 && currentTempK < 1400
      };

      if (currentTempK >= 1380 || safetyFactor < 1.0) {
        this.alert = `⚠️ CRITICAL: CORE TEMP ${currentTempK}K EXCEEDS SAFE LIMIT (SF: ${safetyFactor})`;
        if (this.time - this._lastAlarmTime > 1.8) {
          HolographicAudio.playAlarm();
          this._lastAlarmTime = this.time;
        }
      } else {
        this.alert = null;
      }
    } else {
      // Universal Dynamic Generative Construct & Physics Engine Solver
      const phys = (this.activeManifest && this.activeManifest.physics) ? this.activeManifest.physics : null;
      const baseNum = phys && phys.primaryVal ? (parseFloat(phys.primaryVal.replace(/[^0-9.]/g, '')) || 100) : 100;
      const primaryOsc = Math.round(baseNum * s + Math.sin(this.time * 5) * (baseNum * 0.02));
      const primaryUnits = phys && phys.primaryVal ? phys.primaryVal.replace(/[0-9., ]/g, '') : '%';

      this.telemetry = {
        primaryLabel: (phys && phys.primaryLabel) || "SYSTEM LOAD",
        primaryVal: phys && phys.primaryVal ? `${primaryOsc} ${primaryUnits}`.trim() : `${Math.round(s * 100)}%`,
        secondaryLabel: (phys && phys.secondaryLabel) || "FIELD FLUX / OUTPUT",
        secondaryVal: (phys && phys.secondaryVal) || `${(98.4 * Math.min(1.0, 1.2 / s)).toFixed(1)}% (STABLE)`,
        tertiaryLabel: (phys && phys.tertiaryLabel) || "SAFETY FACTOR",
        tertiaryVal: (phys && phys.tertiaryVal) || `${(1.55 / Math.max(0.5, s)).toFixed(2)} (NOMINAL)`,
        formula: (phys && phys.formula) || "∇·E = ρ/ε₀  |  σ_v = √[½((σ₁-σ₂)² + (σ₂-σ₃)² + (σ₃-σ₁)²)]",
        nominal: s <= 1.25
      };

      if (s > 1.35) {
        this.alert = `⚠️ ELEVATED STRESS LOAD DETECTED (${Math.round(s * 100)}% NOMINAL CAPACITY)`;
        if (this.time - this._lastAlarmTime > 1.8) {
          HolographicAudio.playAlarm();
          this._lastAlarmTime = this.time;
        }
      } else {
        this.alert = null;
      }
    }
  }

  // Returns dynamic color based on simulation mode and local component intensity
  getColor(baseColor, intensity = 1.0) {
    const s = this.stressLevel;
    if (this.mode === "thermal") {
      // Cyan (25C) -> Gold (450C) -> Crimson (1400C)
      const t = Math.min(1.0, (s * intensity) / 1.6);
      if (t < 0.5) {
        const f = t / 0.5;
        return new THREE.Color().lerpColors(new THREE.Color(0x00e5ff), new THREE.Color(0xffb300), f);
      } else {
        const f = (t - 0.5) / 0.5;
        return new THREE.Color().lerpColors(new THREE.Color(0xffb300), new THREE.Color(0xff1744), f);
      }
    } else if (this.mode === "stress") {
      // Green/Cyan -> Amber -> Bright Red
      const t = Math.min(1.0, (s * intensity) / 1.5);
      return new THREE.Color().lerpColors(new THREE.Color(0x00e5ff), new THREE.Color(0xff2a55), t);
    } else if (this.mode === "em_field") {
      // Electric Blue / Violet Plasma
      const pulse = 0.5 + 0.5 * Math.sin(this.time * 6 + intensity * 4);
      return new THREE.Color().lerpColors(new THREE.Color(0x00b0ff), new THREE.Color(0xd500f9), pulse);
    } else {
      // Aerodynamics: Airflow streamline cyan
      return new THREE.Color(0x00e5ff);
    }
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// 3. PROCEDURAL 3D CONSTRUCT BUILDERS
// ══════════════════════════════════════════════════════════════════════════════
export class BlueprintBuilder {
  // ── ARC REACTOR (MARK 42) ──
  static buildArcReactor() {
    const group = new THREE.Group();
    group.name = "construct_root";
    const parts = [];

    // Materials
    const matCyanWire = new THREE.MeshBasicMaterial({ color: 0x00e5ff, wireframe: true, transparent: true, opacity: 0.85 });
    const matCyanSolid = new THREE.MeshBasicMaterial({ color: 0x00e5ff, transparent: true, opacity: 0.35 });
    const matGoldWire = new THREE.MeshBasicMaterial({ color: 0xffb300, wireframe: true, transparent: true, opacity: 0.9 });
    const matCoreGlow = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.95 });

    // 1. Tokamak Confinement Torus (Outer Shell)
    const torusGeo = new THREE.TorusGeometry(3.0, 0.45, 20, 48);
    const torusMesh = new THREE.Mesh(torusGeo, matCyanWire);
    torusMesh.userData = { home: new THREE.Vector3(), explodeDir: new THREE.Vector3(0, 0, -3.0), label: "[AR-01] Tokamak Plasma Torus · Niobium-Titanium", intensity: 0.8 };
    group.add(torusMesh);
    parts.push(torusMesh);

    // 2. 10 Superconducting Magnetic Solenoids (Arrayed radially)
    const numCoils = 10;
    for (let i = 0; i < numCoils; i++) {
      const angle = (i / numCoils) * Math.PI * 2;
      const coilGeo = new THREE.CylinderGeometry(0.5, 0.5, 0.4, 16);
      const coilMesh = new THREE.Mesh(coilGeo, matGoldWire);
      const cx = Math.cos(angle) * 3.0;
      const cy = Math.sin(angle) * 3.0;
      coilMesh.position.set(cx, cy, 0);
      coilMesh.rotation.z = angle + Math.PI / 2;
      const radialDir = new THREE.Vector3(Math.cos(angle) * 2.5, Math.sin(angle) * 2.5, 0);
      coilMesh.userData = { home: coilMesh.position.clone(), explodeDir: radialDir, label: `[AR-03] Solenoid #${i+1} · 12.8 T Confinement`, intensity: 1.2 };
      group.add(coilMesh);
      parts.push(coilMesh);
    }

    // 3. Central Vibranium-Palladium Core Lattice
    const coreGeo = new THREE.IcosahedronGeometry(1.0, 1);
    const coreMesh = new THREE.Mesh(coreGeo, matCoreGlow);
    const coreInnerGeo = new THREE.OctahedronGeometry(0.65, 0);
    const coreInner = new THREE.Mesh(coreInnerGeo, new THREE.MeshBasicMaterial({ color: 0x00e5ff, wireframe: true }));
    coreMesh.add(coreInner);
    coreMesh.userData = { home: new THREE.Vector3(), explodeDir: new THREE.Vector3(0, 0, 4.2), label: "[AR-02] Vibranium-Palladium Core Lattice · 14.2 GW Clean Fusion", intensity: 1.5 };
    group.add(coreMesh);
    parts.push(coreMesh);

    // 4. Counter-rotating Plasma Energy Rings
    const ring1Geo = new THREE.RingGeometry(1.6, 1.75, 32);
    const ring1 = new THREE.Mesh(ring1Geo, new THREE.MeshBasicMaterial({ color: 0x00e5ff, wireframe: true, side: THREE.DoubleSide }));
    const ring2Geo = new THREE.RingGeometry(2.1, 2.22, 32);
    const ring2 = new THREE.Mesh(ring2Geo, new THREE.MeshBasicMaterial({ color: 0xffb300, wireframe: true, side: THREE.DoubleSide }));
    ring1.userData = { home: new THREE.Vector3(0, 0, 0.1), explodeDir: new THREE.Vector3(0, 0, 2.0), label: "[AR-04] Poloidal Energy Ring A", intensity: 1.0, rotSpeed: 1.5 };
    ring2.userData = { home: new THREE.Vector3(0, 0, -0.1), explodeDir: new THREE.Vector3(0, 0, -2.0), label: "[AR-05] Poloidal Energy Ring B", intensity: 1.0, rotSpeed: -1.8 };
    group.add(ring1);
    group.add(ring2);
    parts.push(ring1, ring2);

    // 5. Ambient Plasma Particle Cloud
    const particleCount = 350;
    const pGeo = new THREE.BufferGeometry();
    const pPos = new Float32Array(particleCount * 3);
    for (let i = 0; i < particleCount; i++) {
      const theta = Math.random() * Math.PI * 2;
      const rad = 2.4 + Math.random() * 1.2;
      pPos[i * 3] = Math.cos(theta) * rad;
      pPos[i * 3 + 1] = Math.sin(theta) * rad;
      pPos[i * 3 + 2] = (Math.random() - 0.5) * 0.8;
    }
    pGeo.setAttribute("position", new THREE.BufferAttribute(pPos, 3));
    const pMat = new THREE.PointsMaterial({ color: 0x00e5ff, size: 0.09, transparent: true, opacity: 0.85 });
    const pSystem = new THREE.Points(pGeo, pMat);
    group.add(pSystem);

    return { group, parts, pSystem, name: "arc_reactor" };
  }

  // ── DYNAMIC GENERATIVE BLUEPRINT COMPILER ──
  static buildFromManifest(manifest) {
    const group = new THREE.Group();
    group.name = "construct_root";
    const parts = [];

    const partsList = (manifest && manifest.parts) ? manifest.parts : [];
    partsList.forEach((pDef, idx) => {
      let geo;
      const gType = (pDef.geo || "box").toLowerCase();
      const args = Array.isArray(pDef.args) ? pDef.args : [1, 1, 1];

      try {
        if (gType === "box") {
          geo = new THREE.BoxGeometry(...args);
        } else if (gType === "cylinder") {
          geo = new THREE.CylinderGeometry(...args);
        } else if (gType === "torus") {
          geo = new THREE.TorusGeometry(...args);
        } else if (gType === "cone") {
          geo = new THREE.ConeGeometry(...args);
        } else if (gType === "capsule") {
          geo = new THREE.CapsuleGeometry(...args);
        } else if (gType === "sphere") {
          geo = new THREE.SphereGeometry(...args);
        } else if (gType === "ring") {
          geo = new THREE.RingGeometry(...args);
        } else {
          geo = new THREE.BoxGeometry(1, 1, 1);
        }
      } catch (e) {
        geo = new THREE.BoxGeometry(1, 1, 1);
      }

      const matDef = pDef.mat || {};
      let colorVal = 0x00e5ff;
      if (matDef.color) {
        if (typeof matDef.color === "string") {
          colorVal = parseInt(matDef.color.replace("#", ""), 16);
        } else if (typeof matDef.color === "number") {
          colorVal = matDef.color;
        }
      }

      const mat = new THREE.MeshBasicMaterial({
        color: isNaN(colorVal) ? 0x00e5ff : colorVal,
        wireframe: matDef.wireframe !== false,
        transparent: true,
        opacity: matDef.opacity != null ? matDef.opacity : 0.85,
        side: THREE.DoubleSide
      });

      const mesh = new THREE.Mesh(geo, mat);
      if (Array.isArray(pDef.pos)) mesh.position.set(...pDef.pos);
      if (Array.isArray(pDef.rot)) mesh.rotation.set(...pDef.rot);
      if (Array.isArray(pDef.scale)) mesh.scale.set(...pDef.scale);

      const homePos = mesh.position.clone();
      const expDir = Array.isArray(pDef.explodeDir) ? new THREE.Vector3(...pDef.explodeDir) : new THREE.Vector3(0, 1.5, 0);

      mesh.userData = {
        id: pDef.id || `part_${idx}`,
        home: homePos,
        explodeDir: expDir,
        label: pDef.callout || pDef.name || `Sub-Assembly #${idx+1}`,
        intensity: pDef.intensity || 1.0,
        rotSpeed: pDef.rotSpeed || 0
      };

      group.add(mesh);
      parts.push(mesh);
    });

    return { group, parts, name: (manifest && manifest.id) || "custom_construct", manifest };
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// 4. MAIN HOLOGRAPHIC STUDIO CONTROLLER
// ══════════════════════════════════════════════════════════════════════════════
export class HolographicStudio {
  static scene = null;
  static camera = null;
  static renderer = null;
  static currentConstruct = null;
  static simulator = new PhysicsSimulator();
  static isExploded = false;
  static explodeAmount = 0.0;
  static container = null;
  static hudEl = null;
  static calloutsContainer = null;
  static calloutEls = [];
  static active = false;

  static init() {
    if (this.scene) return;

    // Create HUD & WebGL overlay container
    this.container = document.createElement("div");
    this.container.id = "holographic_studio_overlay";
    this.container.style.cssText = `
      position: absolute; inset: 0; width: 100vw; height: 100vh;
      pointer-events: none; z-index: 950; display: none; overflow: hidden;
    `;
    document.body.appendChild(this.container);

    // WebGL Canvas
    const canvas = document.createElement("canvas");
    canvas.id = "holographic_webgl_canvas";
    canvas.style.cssText = "position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: auto;";
    this.container.appendChild(canvas);

    // Callouts overlay
    this.calloutsContainer = document.createElement("div");
    this.calloutsContainer.style.cssText = "position: absolute; inset: 0; pointer-events: none;";
    this.container.appendChild(this.calloutsContainer);

    // Three.js Scene Setup
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 100);
    this.camera.position.set(0, 0, 9.5);

    this.renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    this.renderer.setSize(window.innerWidth, window.innerHeight);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

    // Ambient Grid Floor
    const grid = new THREE.GridHelper(18, 24, 0x00e5ff, 0x003344);
    grid.position.y = -4.2;
    grid.material.transparent = true;
    grid.material.opacity = 0.45;
    this.scene.add(grid);

    // Build Glass Engineering HUD
    this._buildHUD();

    // Mouse Controls
    this._initMouseControls(canvas);

    // Connect WebSocket to jarvis.py
    this._connectWebSocket();

    // Animation Loop
    let lastT = performance.now();
    const animate = (now) => {
      requestAnimationFrame(animate);
      const dt = Math.min((now - lastT) / 1000, 0.05);
      lastT = now;
      if (this.active) {
        this._renderFrame(dt);
      }
    };
    requestAnimationFrame(animate);
  }

  static _buildHUD() {
    this.hudEl = document.createElement("div");
    this.hudEl.id = "holographic_glass_hud";
    this.hudEl.style.cssText = `
      position: absolute; inset: 0; pointer-events: none; font-family: -apple-system, "SF Mono", Menlo, monospace;
      color: #8ff0e4; text-shadow: 0 0 10px rgba(0,229,255,0.6); user-select: none;
    `;

    this.hudEl.innerHTML = `
      <!-- TOP BAR: Construct Selector & Dynamic Voice/Prompt Bar -->
      <div style="position: absolute; top: 18px; left: 24px; right: 190px; display: flex; align-items: center; gap: 12px; pointer-events: auto;">
        <div style="display: flex; gap: 8px; background: rgba(5,25,30,0.75); padding: 6px 14px; border-radius: 12px; border: 1px solid rgba(0,229,255,0.4); backdrop-filter: blur(10px);">
          <button class="holo-btn active" data-construct="arc_reactor">⚛ ARC REACTOR</button>
          <button class="holo-btn" data-construct="dynamic" id="holo_dynamic_btn">🛠 DYNAMIC BLUEPRINT</button>
        </div>

        <div style="flex: 1; display: flex; gap: 8px; background: rgba(5,25,30,0.75); padding: 6px 14px; border-radius: 12px; border: 1px solid rgba(0,229,255,0.4); backdrop-filter: blur(10px);">
          <input id="holo_prompt_input" type="text" placeholder="Instruct JARVIS to construct or modify (e.g. 'Build plasma cutter', 'Construct railgun', 'Add pressure gauge')..." style="flex: 1; background: rgba(0,0,0,0.5); border: 1px solid rgba(0,229,255,0.3); border-radius: 6px; padding: 6px 12px; color: #ffffff; font-family: monospace; font-size: 11px; outline: none;">
          <button id="holo_submit_btn" style="background: rgba(0,229,255,0.2); border: 1px solid #00e5ff; color: #00e5ff; padding: 6px 14px; border-radius: 6px; font-family: monospace; font-size: 11px; font-weight: 700; cursor: pointer;">⚡ CONSTRUCT / MODIFY</button>
        </div>
      </div>

      <!-- TOP RIGHT: Close Studio Button -->
      <div style="position: absolute; top: 18px; right: 24px; pointer-events: auto;">
        <button id="holo_close_btn" style="background: rgba(255,23,68,0.2); border: 1px solid #ff1744; color: #ff80ab; padding: 8px 18px; border-radius: 8px; font-family: monospace; font-weight: 700; cursor: pointer;">✕ CLOSE BLUEPRINT</button>
      </div>

      <!-- LEFT PANEL: Real-World Science Telemetry & Formulas -->
      <div style="position: absolute; top: 80px; left: 24px; width: 340px; background: rgba(5,25,30,0.75); border: 1px solid rgba(0,229,255,0.35); border-radius: 12px; padding: 18px; backdrop-filter: blur(12px);">
        <div style="font-size: 11px; letter-spacing: 0.16em; color: #00e5ff; margin-bottom: 6px;">PHYSICS SIMULATION TELEMETRY</div>
        <div id="holo_sim_formula" style="font-size: 12px; color: #ffb300; background: rgba(0,0,0,0.5); padding: 6px 10px; border-radius: 6px; margin-bottom: 14px; border: 1px solid rgba(255,179,0,0.3);">Q = -k∇T + εσ(T⁴ - T₀⁴)</div>
        
        <div style="display: flex; flex-direction: column; gap: 10px;">
          <div>
            <div id="holo_lbl_1" style="font-size: 10px; color: #7fb3ab;">CORE TEMPERATURE</div>
            <div id="holo_val_1" style="font-size: 18px; font-weight: 700; color: #ffffff;">980 K (707°C)</div>
          </div>
          <div>
            <div id="holo_lbl_2" style="font-size: 10px; color: #7fb3ab;">B-FIELD CONFINEMENT</div>
            <div id="holo_val_2" style="font-size: 16px; font-weight: 700; color: #00e5ff;">12.8 T (98.2%)</div>
          </div>
          <div>
            <div id="holo_lbl_3" style="font-size: 10px; color: #7fb3ab;">VON MISES STRESS</div>
            <div id="holo_val_3" style="font-size: 16px; font-weight: 700; color: #ffb300;">410 MPa (SF: 1.34)</div>
          </div>
        </div>

        <div id="holo_alert_box" style="display: none; margin-top: 14px; padding: 8px 12px; background: rgba(255,23,68,0.25); border: 1px solid #ff1744; border-radius: 6px; font-size: 12px; font-weight: 700; color: #ff80ab;"></div>
      </div>

      <!-- BOTTOM CONTROL BAR: Simulation Modes & Controls -->
      <div style="position: absolute; bottom: 24px; left: 50%; transform: translateX(-50%); display: flex; align-items: center; gap: 16px; pointer-events: auto; background: rgba(5,25,30,0.8); padding: 12px 24px; border-radius: 14px; border: 1px solid rgba(0,229,255,0.4); backdrop-filter: blur(14px);">
        <div style="display: flex; gap: 6px;">
          <button class="sim-btn active" data-sim="thermal">THERMAL DISSIPATION</button>
          <button class="sim-btn" data-sim="stress">VON MISES STRESS</button>
          <button class="sim-btn" data-sim="em_field">EM CONFINEMENT</button>
          <button class="sim-btn" data-sim="aerodynamics">AERODYNAMICS</button>
        </div>

        <div style="width: 1px; height: 32px; background: rgba(0,229,255,0.3);"></div>

        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 11px; color: #00e5ff;">STRESS:</span>
          <input type="range" id="holo_stress_slider" min="0.5" max="2.0" step="0.05" value="1.0" style="width: 120px; cursor: pointer;">
          <span id="holo_stress_val" style="font-size: 12px; font-weight: 700; width: 42px;">100%</span>
        </div>

        <div style="width: 1px; height: 32px; background: rgba(0,229,255,0.3);"></div>

        <button id="holo_explode_btn" style="background: rgba(0,229,255,0.15); border: 1px solid #00e5ff; color: #00e5ff; padding: 8px 16px; border-radius: 8px; font-weight: 700; cursor: pointer;">EXPLODED VIEW: OFF</button>
      </div>
    `;

    // Inject CSS styles for buttons
    const style = document.createElement("style");
    style.innerHTML = `
      .holo-btn, .sim-btn {
        background: rgba(0,229,255,0.08); border: 1px solid rgba(0,229,255,0.35); color: #8ff0e4;
        padding: 6px 14px; border-radius: 6px; font-family: inherit; font-size: 11px; font-weight: 700;
        letter-spacing: 0.08em; cursor: pointer; transition: all 0.2s;
      }
      .holo-btn:hover, .sim-btn:hover { background: rgba(0,229,255,0.22); color: #ffffff; }
      .holo-btn.active, .sim-btn.active {
        background: rgba(0,229,255,0.35); border-color: #00e5ff; color: #ffffff;
        box-shadow: 0 0 12px rgba(0,229,255,0.5);
      }
    `;
    document.head.appendChild(style);
    this.container.appendChild(this.hudEl);

    // Bind Button Click Events
    this.hudEl.querySelectorAll(".holo-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        this.hudEl.querySelectorAll(".holo-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        HolographicAudio.playClick();
        this.loadConstruct(btn.getAttribute("data-construct"), this.simulator.mode, this.simulator.stressLevel, this.isExploded);
      });
    });

    this.hudEl.querySelectorAll(".sim-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        this.hudEl.querySelectorAll(".sim-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        HolographicAudio.playClick();
        this.simulator.mode = btn.getAttribute("data-sim");
      });
    });

    const slider = document.getElementById("holo_stress_slider");
    slider.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value);
      this.simulator.stressLevel = val;
      document.getElementById("holo_stress_val").innerText = `${Math.round(val * 100)}%`;
    });

    const explodeBtn = document.getElementById("holo_explode_btn");
    explodeBtn.addEventListener("click", () => {
      this.isExploded = !this.isExploded;
      explodeBtn.innerText = `EXPLODED VIEW: ${this.isExploded ? "ON" : "OFF"}`;
      explodeBtn.style.background = this.isExploded ? "rgba(255,179,0,0.3)" : "rgba(0,229,255,0.15)";
      explodeBtn.style.borderColor = this.isExploded ? "#ffb300" : "#00e5ff";
      explodeBtn.style.color = this.isExploded ? "#ffb300" : "#00e5ff";
      HolographicAudio.playServo(this.isExploded ? 1 : -1);
    });

    // Bind Prompt Input Submit
    const submitPrompt = () => {
      const input = document.getElementById("holo_prompt_input");
      const text = input ? input.value.trim() : "";
      if (!text) return;
      HolographicAudio.playClick();
      fetch("/construct_prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text })
      }).catch(() => {});
      input.value = "";
    };

    const submitBtn = document.getElementById("holo_submit_btn");
    if (submitBtn) submitBtn.addEventListener("click", submitPrompt);
    const promptInput = document.getElementById("holo_prompt_input");
    if (promptInput) {
      promptInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") submitPrompt();
      });
    }

    document.getElementById("holo_close_btn").addEventListener("click", () => {
      this.hide();
    });
  }

  static _initMouseControls(canvas) {
    let isDragging = false;
    let prevX = 0, prevY = 0;

    canvas.addEventListener("mousedown", (e) => {
      isDragging = true;
      prevX = e.clientX;
      prevY = e.clientY;
    });

    window.addEventListener("mouseup", () => { isDragging = false; });

    window.addEventListener("mousemove", (e) => {
      if (!isDragging || !this.currentConstruct) return;
      const dx = e.clientX - prevX;
      const dy = e.clientY - prevY;
      this.currentConstruct.group.rotation.y += dx * 0.008;
      this.currentConstruct.group.rotation.x += dy * 0.008;
      prevX = e.clientX;
      prevY = e.clientY;
    });

    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.camera.position.z = Math.max(4.5, Math.min(16.0, this.camera.position.z + e.deltaY * 0.006));
    });
  }

  static _connectWebSocket() {
    try {
      const wsUrl = `ws://${window.location.hostname || "localhost"}:8765`;
      const ws = new WebSocket(wsUrl);
      this._ws = ws;

      ws.onopen = () => {
        try {
          ws.send(JSON.stringify({ type: "GET_ACTIVE_CONSTRUCT" }));
        } catch (e) {}
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "RENDER_3D_BLUEPRINT" || data.type === "DYNAMIC_CONSTRUCT" || data.type === "MODIFY_CONSTRUCT") {
            this.show();
            this.loadConstruct(data.construct || (data.manifest ? data.manifest.id : "dynamic"), data.simulation || "fluid_dynamics", data.stress || 1.0, data.exploded || false, data.manifest);
          } else if (data.type === "ACTIVE_CONSTRUCT_STATE" && data.construct) {
            this.show();
            this.loadConstruct(data.construct, data.simulation || "thermal", data.stress || 1.0, data.exploded || false, data.manifest || null);
          } else if (data.type === "DISMISS_CONSTRUCT") {
            this.hide();
          }
        } catch (e) {}
      };

      ws.onclose = () => {
        setTimeout(() => this._connectWebSocket(), 3000);
      };

      ws.onerror = () => {
        try { ws.close(); } catch (e) {}
      };
    } catch (e) {
      setTimeout(() => this._connectWebSocket(), 4000);
    }
  }

  static show() {
    this.init();
    this.active = true;
    this.container.style.display = "block";
    HolographicAudio.playBoot();
  }

  static hide() {
    this.active = false;
    if (this.container) this.container.style.display = "none";
  }

  static loadConstruct(name = "arc_reactor", simMode = "thermal", stress = 1.0, exploded = false, manifest = null) {
    this.show();
    this.simulator.mode = simMode;
    this.simulator.stressLevel = stress;
    this.isExploded = exploded;
    HolographicAudio.playServo(1);

    // Remove old construct
    if (this.currentConstruct) {
      this.scene.remove(this.currentConstruct.group);
      this.currentConstruct = null;
    }
    this._clearCallouts();

    // Update active HUD buttons
    if (this.hudEl) {
      this.hudEl.querySelectorAll(".holo-btn").forEach(b => {
        b.classList.toggle("active", b.getAttribute("data-construct") === name);
      });
      this.hudEl.querySelectorAll(".sim-btn").forEach(b => {
        b.classList.toggle("active", b.getAttribute("data-sim") === simMode);
      });
      const slider = document.getElementById("holo_stress_slider");
      if (slider) slider.value = stress;
      const stressVal = document.getElementById("holo_stress_val");
      if (stressVal) stressVal.innerText = `${Math.round(stress * 100)}%`;
      const explodeBtn = document.getElementById("holo_explode_btn");
      if (explodeBtn) {
        explodeBtn.innerText = `EXPLODED VIEW: ${this.isExploded ? "ON" : "OFF"}`;
        explodeBtn.style.color = this.isExploded ? "#ffb300" : "#00e5ff";
      }
    }

    // Build model: manifest, Arc Reactor, or dynamic construct
    if (manifest) {
      this.currentConstruct = BlueprintBuilder.buildFromManifest(manifest);
      this.activeManifest = manifest;
      this.simulator.activeManifest = manifest;
      const dynBtn = document.getElementById("holo_dynamic_btn");
      if (dynBtn) {
        dynBtn.innerText = `🛠 DYNAMIC: ${manifest.name ? manifest.name.toUpperCase() : "CONSTRUCT"}`;
        dynBtn.setAttribute("data-construct", "dynamic");
        dynBtn.classList.add("active");
        this.hudEl.querySelectorAll(".holo-btn").forEach(b => {
          if (b !== dynBtn) b.classList.remove("active");
        });
      }
    } else if (name === "dynamic" && this.activeManifest) {
      this.currentConstruct = BlueprintBuilder.buildFromManifest(this.activeManifest);
      this.simulator.activeManifest = this.activeManifest;
      const dynBtn = document.getElementById("holo_dynamic_btn");
      if (dynBtn) {
        dynBtn.innerText = `🛠 DYNAMIC: ${this.activeManifest.name ? this.activeManifest.name.toUpperCase() : "CONSTRUCT"}`;
        dynBtn.classList.add("active");
        this.hudEl.querySelectorAll(".holo-btn").forEach(b => {
          if (b !== dynBtn) b.classList.remove("active");
        });
      }
    } else if (name === "dynamic" && !this.activeManifest) {
      const input = document.getElementById("holo_prompt_input");
      if (input) {
        input.focus();
        input.placeholder = "Enter machine to construct (e.g. 'Build plasma cutter', 'Construct railgun')...";
      }
      this.currentConstruct = BlueprintBuilder.buildArcReactor();
      this.activeManifest = null;
      this.simulator.activeManifest = null;
      const arcBtn = this.hudEl ? this.hudEl.querySelector('[data-construct="arc_reactor"]') : null;
      if (arcBtn) {
        this.hudEl.querySelectorAll(".holo-btn").forEach(b => b.classList.remove("active"));
        arcBtn.classList.add("active");
      }
    } else {
      // Default: Flagship Arc Reactor Core
      this.currentConstruct = BlueprintBuilder.buildArcReactor();
      this.activeManifest = null;
      this.simulator.activeManifest = null;
      const arcBtn = this.hudEl ? this.hudEl.querySelector('[data-construct="arc_reactor"]') : null;
      if (arcBtn) {
        this.hudEl.querySelectorAll(".holo-btn").forEach(b => b.classList.remove("active"));
        arcBtn.classList.add("active");
      }
    }

    this.scene.add(this.currentConstruct.group);
    this.currentConstruct.group.position.set(0, 0, 0);

    // Create callout tags for exploded view
    this._createCallouts();
  }

  static _createCallouts() {
    this._clearCallouts();
    if (!this.currentConstruct || !this.currentConstruct.parts) return;

    this.currentConstruct.parts.forEach(p => {
      if (!p.userData || !p.userData.label) return;
      const tag = document.createElement("div");
      tag.className = "holo-callout";
      tag.style.cssText = `
        position: absolute; transform: translate(-50%, -50%); pointer-events: none;
        background: rgba(5,25,30,0.85); border: 1px solid #00e5ff; border-radius: 6px;
        padding: 4px 10px; font-size: 11px; font-family: monospace; font-weight: 700;
        color: #8ff0e4; box-shadow: 0 0 10px rgba(0,229,255,0.4); opacity: 0;
        transition: opacity 0.3s; white-space: nowrap;
      `;
      tag.innerText = p.userData.label;
      this.calloutsContainer.appendChild(tag);
      this.calloutEls.push({ el: tag, part: p });
    });
  }

  static _clearCallouts() {
    this.calloutEls.forEach(c => c.el.remove());
    this.calloutEls = [];
  }

  static _renderFrame(dt) {
    // 1. Update Physics Solver
    const cName = this.currentConstruct ? this.currentConstruct.name : "arc_reactor";
    this.simulator.update(dt, cName);

    // 2. Update HUD Telemetry Readouts
    const tel = this.simulator.telemetry;
    if (tel && this.hudEl) {
      document.getElementById("holo_sim_formula").innerText = tel.formula || "";
      document.getElementById("holo_lbl_1").innerText = tel.primaryLabel || "";
      document.getElementById("holo_val_1").innerText = tel.primaryVal || "";
      document.getElementById("holo_lbl_2").innerText = tel.secondaryLabel || "";
      document.getElementById("holo_val_2").innerText = tel.secondaryVal || "";
      document.getElementById("holo_lbl_3").innerText = tel.tertiaryLabel || "";
      document.getElementById("holo_val_3").innerText = tel.tertiaryVal || "";

      const alertBox = document.getElementById("holo_alert_box");
      if (this.simulator.alert) {
        alertBox.style.display = "block";
        alertBox.innerText = this.simulator.alert;
      } else {
        alertBox.style.display = "none";
      }
    }

    // 3. Exploded View Easing
    const targetExp = this.isExploded ? 1.0 : 0.0;
    this.explodeAmount += (targetExp - this.explodeAmount) * 0.06;

    if (this.currentConstruct && this.currentConstruct.parts) {
      this.currentConstruct.parts.forEach(p => {
        if (p.userData && p.userData.home && p.userData.explodeDir) {
          p.position.copy(p.userData.home).addScaledVector(p.userData.explodeDir, this.explodeAmount);
        }

        // Sub-component continuous rotations
        if (p.userData && p.userData.rotSpeed) {
          if (p.rotation) p.rotation.z += p.userData.rotSpeed * dt;
        }

        // Color shifting from Physics Simulator
        if (p.material && p.userData && p.userData.intensity) {
          const col = this.simulator.getColor(0x00e5ff, p.userData.intensity);
          if (p.material.color) p.material.color.copy(col);
        }
      });

      // Ambient idle rotation
      this.currentConstruct.group.rotation.y += dt * 0.25;

      // Particle rotations
      if (this.currentConstruct.pSystem) {
        this.currentConstruct.pSystem.rotation.z += dt * 0.8;
      }
    }

    // 4. Update 3D Screen Space Callout Tags
    const tempV = new THREE.Vector3();
    this.calloutEls.forEach(c => {
      if (this.explodeAmount > 0.45) {
        c.part.getWorldPosition(tempV);
        tempV.project(this.camera);
        const x = (tempV.x * 0.5 + 0.5) * window.innerWidth;
        const y = (-tempV.y * 0.5 + 0.5) * window.innerHeight;
        c.el.style.left = `${x}px`;
        c.el.style.top = `${y - 20}px`;
        c.el.style.opacity = Math.min(1.0, (this.explodeAmount - 0.45) / 0.5);
      } else {
        c.el.style.opacity = "0";
      }
    });

    // 5. Render Three.js Scene
    this.renderer.render(this.scene, this.camera);
  }

  // Multi-Modal Barehands Hand Gesture Tracker Integration
  static updateGestures(cursors) {
    if (!this.active || !this.currentConstruct) return;
    if (!cursors) return;

    const cursorList = Object.values(cursors).filter(c => c && !c.ghost);
    if (cursorList.length === 0) {
      this._prevGestureHand = null;
      this._prevHandDist = null;
      return;
    }

    const pinchedHands = cursorList.filter(c => c.pinched);

    if (pinchedHands.length === 1 || cursorList.length === 1) {
      // 1 Hand (pinched or single tracked cursor) -> Smooth 3D Rotation
      const h = pinchedHands.length === 1 ? pinchedHands[0] : cursorList[0];
      if (this._prevGestureHand) {
        const dx = h.x - this._prevGestureHand.x;
        const dy = h.y - this._prevGestureHand.y;
        if (Math.hypot(dx, dy) < 140) {
          this.currentConstruct.group.rotation.y += dx * 0.007;
          this.currentConstruct.group.rotation.x += dy * 0.007;
        }
      }
      this._prevGestureHand = { x: h.x, y: h.y };
      this._prevHandDist = null;
    } else if (cursorList.length >= 2) {
      // 2 Hands -> Pull / Spread scrubbing (CAD explode & camera zoom)
      const [h1, h2] = cursorList;
      const dist = Math.hypot(h1.x - h2.x, h1.y - h2.y);
      if (this._prevHandDist != null) {
        const dDist = dist - this._prevHandDist;
        if (Math.abs(dDist) < 120) {
          if (pinchedHands.length >= 2) {
            // Dual pinch -> Depth Zoom
            this.camera.position.z = Math.max(4.5, Math.min(16.0, this.camera.position.z - dDist * 0.012));
          } else {
            // Dual open hands expand/contract -> Exploded View scrub
            this.explodeAmount = Math.max(0, Math.min(1.5, this.explodeAmount + dDist * 0.005));
            this.isExploded = this.explodeAmount > 0.25;
            const explodeBtn = document.getElementById("holo_explode_btn");
            if (explodeBtn) {
              explodeBtn.innerText = `EXPLODED VIEW: ${this.isExploded ? "ON" : "OFF"}`;
              explodeBtn.style.color = this.isExploded ? "#ffb300" : "#00e5ff";
            }
          }
        }
      }
      this._prevHandDist = dist;
      this._prevGestureHand = null;
    } else {
      this._prevGestureHand = null;
      this._prevHandDist = null;
    }
  }
}

// Attach globally for Barehands Board integration & auto-init
window.HolographicStudio = HolographicStudio;
try {
  if (typeof window !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => {
        HolographicStudio.init();
      });
    } else {
      HolographicStudio.init();
    }
  }
} catch (e) {
  console.debug("HolographicStudio auto-init deferred:", e);
}
