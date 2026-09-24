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
    } else if (this.mode === "system_interconnect" || constructName.includes("pi") || constructName.includes("camera") || constructName.includes("battery") || constructName.includes("connect")) {
      const v = (5.12 + Math.sin(this.time * 3) * 0.03).toFixed(2);
      const a = (1.42 + s * 0.35 + Math.sin(this.time * 5) * 0.04).toFixed(2);
      const w = (v * a).toFixed(2);
      const tempSoC = Math.round(44 + s * 12 + Math.sin(this.time * 2) * 2);
      this.telemetry = {
        primaryLabel: "SYSTEM BUS & CLOCK",
        primaryVal: "CSI-2 1.5 Gbps  |  I2C 400 kHz",
        secondaryLabel: "POWER CONSUMPTION",
        secondaryVal: `${v} V · ${a} A (${w} W)`,
        tertiaryLabel: "SoC THERMALS // THROUGHPUT",
        tertiaryVal: `${tempSoC}°C  ·  1080p @ 60 FPS`,
        formula: "P = V·I = 7.27 W  |  MIPI D-PHY v1.2  |  T_j < 85°C",
        nominal: tempSoC < 75
      };
      this.alert = tempSoC >= 75 ? `⚠️ ELEVATED SoC TEMPERATURE (${tempSoC}°C)` : null;
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
  // ── MOVIE-ACCURATE STARK MARK VII ARC REACTOR ──
  static buildArcReactor() {
    const group = new THREE.Group();
    group.name = "construct_root";
    const parts = [];

    // ── High-Tech Stark Alloy & Energy Materials ──
    const matTitaniumChassis = new THREE.MeshBasicMaterial({ color: 0x37474f, wireframe: false });
    const matChassisWire = new THREE.MeshBasicMaterial({ color: 0x00e5ff, wireframe: true, transparent: true, opacity: 0.45 });
    const matCopperCoil = new THREE.MeshBasicMaterial({ color: 0xc87533, wireframe: false });
    const matCopperWire = new THREE.MeshBasicMaterial({ color: 0xffa040, wireframe: true, transparent: true, opacity: 0.85 });
    const matAlloyClamp = new THREE.MeshBasicMaterial({ color: 0x90a4ae, wireframe: false });
    const matStatorPCB = new THREE.MeshBasicMaterial({ color: 0x0a1f22, side: THREE.DoubleSide });
    const matCyanNeon = new THREE.MeshBasicMaterial({ color: 0x00f0ff, transparent: true, opacity: 0.9 });
    const matCoreWhiteHot = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.98 });
    const matFrostedGlass = new THREE.MeshBasicMaterial({ color: 0x00f0ff, transparent: true, opacity: 0.45, side: THREE.DoubleSide });

    // ── Layer 1: Outer Machined Titanium Alloy Chassis Ring ──
    const outerTorusGeo = new THREE.TorusGeometry(3.15, 0.22, 24, 64);
    const outerTorus = new THREE.Mesh(outerTorusGeo, matTitaniumChassis);
    const outerTorusWire = new THREE.Mesh(outerTorusGeo, matChassisWire);
    outerTorus.add(outerTorusWire);

    const outerCasingGeo = new THREE.CylinderGeometry(3.35, 3.35, 0.35, 64, 1, true);
    const outerCasing = new THREE.Mesh(outerCasingGeo, new THREE.MeshBasicMaterial({ color: 0x00e5ff, wireframe: true, transparent: true, opacity: 0.4 }));
    outerTorus.add(outerCasing);

    // 3 Outer Chassis Mounting Lugs
    for (let l = 0; l < 3; l++) {
      const lugAng = (l / 3) * Math.PI * 2;
      const lugGeo = new THREE.BoxGeometry(0.32, 0.6, 0.4);
      const lugMesh = new THREE.Mesh(lugGeo, matAlloyClamp);
      lugMesh.position.set(Math.cos(lugAng) * 3.3, Math.sin(lugAng) * 3.3, 0);
      lugMesh.rotation.z = lugAng + Math.PI / 2;
      outerTorus.add(lugMesh);
    }

    outerTorus.userData = {
      home: new THREE.Vector3(0, 0, 0),
      explodeDir: new THREE.Vector3(0, 0, -3.2),
      label: "[AR-01] Machined Titanium Alloy Chassis & Retention Ring",
      intensity: 0.8
    };
    group.add(outerTorus);
    parts.push(outerTorus);

    // ── Layer 2: Segmented Stator PCB Baseplate with Backlit Apertures ──
    const statorGeo = new THREE.RingGeometry(1.65, 3.15, 64);
    const statorMesh = new THREE.Mesh(statorGeo, matStatorPCB);
    const statorTracesGeo = new THREE.RingGeometry(2.1, 2.75, 48, 2);
    const statorTraces = new THREE.Mesh(statorTracesGeo, new THREE.MeshBasicMaterial({ color: 0x00e5ff, wireframe: true, transparent: true, opacity: 0.5 }));
    statorMesh.add(statorTraces);

    statorMesh.userData = {
      home: new THREE.Vector3(0, 0, -0.15),
      explodeDir: new THREE.Vector3(0, 0, -1.8),
      label: "[AR-02] Segmented Stator PCB & Bus Conduit Sub-Assembly",
      intensity: 0.9
    };
    group.add(statorMesh);
    parts.push(statorMesh);

    // ── Layer 3: 10 Precision Toroidal Copper Induction Coils ──
    const numCoils = 10;
    const coilRadius = 2.45;

    for (let i = 0; i < numCoils; i++) {
      const angle = (i / numCoils) * Math.PI * 2;
      const coilGroup = new THREE.Group();

      // Main Copper Core
      const coreGeo = new THREE.BoxGeometry(0.48, 0.82, 0.58);
      const coilBody = new THREE.Mesh(coreGeo, matCopperCoil);
      coilGroup.add(coilBody);

      // Fine Wound Wire Ribs (representing copper winding magnet wire)
      const wireWrapGeo = new THREE.BoxGeometry(0.51, 0.84, 0.60);
      const wireWrap = new THREE.Mesh(wireWrapGeo, matCopperWire);
      coilGroup.add(wireWrap);

      // Triangular Alloy Retention Clamp with Micro-Bolt
      const clampGeo = new THREE.BoxGeometry(0.24, 0.92, 0.68);
      const clampMesh = new THREE.Mesh(clampGeo, matAlloyClamp);
      coilGroup.add(clampMesh);

      // Backlit LED Diffuser Channel
      const ledGeo = new THREE.BoxGeometry(0.38, 0.7, 0.1);
      const ledMesh = new THREE.Mesh(ledGeo, matCyanNeon);
      ledMesh.position.z = -0.32;
      coilGroup.add(ledMesh);

      // Position radially
      const cx = Math.cos(angle) * coilRadius;
      const cy = Math.sin(angle) * coilRadius;
      coilGroup.position.set(cx, cy, 0);
      coilGroup.rotation.z = angle + Math.PI / 2;

      // Radial explode vector
      const radialDir = new THREE.Vector3(Math.cos(angle) * 3.5, Math.sin(angle) * 3.5, 0.2);
      coilGroup.userData = {
        home: coilGroup.position.clone(),
        explodeDir: radialDir,
        label: `[AR-03] Toroidal Induction Coil #${i+1} · 12.8 T Copper Solenoid`,
        intensity: 1.2
      };
      group.add(coilGroup);
      parts.push(coilGroup);
    }

    // ── Layer 4: Laser-Cut Titanium Radial Heat Sink Fins ──
    const finsGroup = new THREE.Group();
    const numFins = 20;
    for (let f = 0; f < numFins; f++) {
      const fAng = (f / numFins) * Math.PI * 2;
      const finGeo = new THREE.BoxGeometry(0.06, 0.45, 0.35);
      const finMesh = new THREE.Mesh(finGeo, matAlloyClamp);
      finMesh.position.set(Math.cos(fAng) * 1.55, Math.sin(fAng) * 1.55, 0);
      finMesh.rotation.z = fAng + Math.PI / 2;
      finsGroup.add(finMesh);
    }
    finsGroup.userData = {
      home: new THREE.Vector3(0, 0, 0),
      explodeDir: new THREE.Vector3(0, 0, 1.2),
      label: "[AR-04] Laser-Cut Radial Thermal Heat Sink Array",
      intensity: 1.0
    };
    group.add(finsGroup);
    parts.push(finsGroup);

    // ── Layer 5: Counter-Rotating Poloidal Magnetic Flux Rings ──
    const ring1Geo = new THREE.RingGeometry(1.32, 1.48, 48);
    const ring1 = new THREE.Mesh(ring1Geo, new THREE.MeshBasicMaterial({ color: 0x00f0ff, wireframe: true, side: THREE.DoubleSide }));
    const ring2Geo = new THREE.RingGeometry(1.82, 1.96, 48);
    const ring2 = new THREE.Mesh(ring2Geo, new THREE.MeshBasicMaterial({ color: 0x00b0ff, wireframe: true, side: THREE.DoubleSide }));
    ring1.userData = { home: new THREE.Vector3(0, 0, 0.12), explodeDir: new THREE.Vector3(0, 0, 2.4), label: "[AR-05] Inner Poloidal Flux Guide Ring A", intensity: 1.1, rotSpeed: 1.8 };
    ring2.userData = { home: new THREE.Vector3(0, 0, -0.12), explodeDir: new THREE.Vector3(0, 0, -2.4), label: "[AR-06] Outer Poloidal Flux Guide Ring B", intensity: 1.1, rotSpeed: -1.4 };
    group.add(ring1);
    group.add(ring2);
    parts.push(ring1, ring2);

    // ── Layer 6: Central Vibranium-Palladium Fusion Core Capsule ──
    const coreAssembly = new THREE.Group();

    // Central Bezel Ring
    const coreBezelGeo = new THREE.TorusGeometry(1.22, 0.08, 16, 48);
    const coreBezel = new THREE.Mesh(coreBezelGeo, matAlloyClamp);
    coreAssembly.add(coreBezel);

    // Frosted Lens Disc
    const lensDiscGeo = new THREE.CircleGeometry(1.18, 48);
    const lensDisc = new THREE.Mesh(lensDiscGeo, matFrostedGlass);
    lensDisc.position.z = 0.05;
    coreAssembly.add(lensDisc);

    // Iconic Triangular Energy Prism Frame
    const triGroup = new THREE.Group();
    for (let t = 0; t < 3; t++) {
      const tAngle = (t / 3) * Math.PI * 2;
      const barGeo = new THREE.BoxGeometry(0.8, 0.08, 0.15);
      const bar = new THREE.Mesh(barGeo, matAlloyClamp);
      bar.position.set(Math.cos(tAngle) * 0.5, Math.sin(tAngle) * 0.5, 0.12);
      bar.rotation.z = tAngle + Math.PI / 6;
      triGroup.add(bar);
    }
    coreAssembly.add(triGroup);

    // Pure White-Hot Core Fusion Emitter
    const emitterGeo = new THREE.CylinderGeometry(0.55, 0.55, 0.22, 32);
    const emitter = new THREE.Mesh(emitterGeo, matCoreWhiteHot);
    emitter.rotation.x = Math.PI / 2;
    emitter.position.z = 0.08;
    coreAssembly.add(emitter);

    // Surrounding Electric Cyan Glow Shell
    const glowShellGeo = new THREE.SphereGeometry(0.72, 24, 24);
    const glowShell = new THREE.Mesh(glowShellGeo, new THREE.MeshBasicMaterial({ color: 0x00f0ff, transparent: true, opacity: 0.45, wireframe: true }));
    coreAssembly.add(glowShell);

    coreAssembly.userData = {
      home: new THREE.Vector3(0, 0, 0.15),
      explodeDir: new THREE.Vector3(0, 0, 4.4),
      label: "[AR-07] Vibranium-Palladium Core Lattice · 14.2 GW Fusion Emitter",
      intensity: 1.6,
      isCore: true
    };
    group.add(coreAssembly);
    parts.push(coreAssembly);

    // ── Layer 7: Swirling Plasma Magnetic Flux Particle Swarm ──
    const particleCount = 450;
    const pGeo = new THREE.BufferGeometry();
    const pPos = new Float32Array(particleCount * 3);
    for (let i = 0; i < particleCount; i++) {
      const theta = Math.random() * Math.PI * 2;
      const rad = 2.1 + Math.random() * 0.8;
      pPos[i * 3] = Math.cos(theta) * rad;
      pPos[i * 3 + 1] = Math.sin(theta) * rad;
      pPos[i * 3 + 2] = (Math.random() - 0.5) * 0.7;
    }
    pGeo.setAttribute("position", new THREE.BufferAttribute(pPos, 3));
    const pMat = new THREE.PointsMaterial({ color: 0x00f0ff, size: 0.08, transparent: true, opacity: 0.9 });
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

  // ── HIGH-DETAIL EMBEDDED COMPUTING CONSTRUCT: RASPBERRY PI 4 / 5 ──
  static buildRaspberryPi() {
    const group = new THREE.Group();
    group.name = "construct_root";
    const parts = [];

    const matPcb = new THREE.MeshBasicMaterial({ color: 0x0a3d24, wireframe: false, side: THREE.DoubleSide });
    const matPcbTrace = new THREE.MeshBasicMaterial({ color: 0x00e5ff, wireframe: true, transparent: true, opacity: 0.35 });
    const matSocAlloy = new THREE.MeshBasicMaterial({ color: 0xb0bec5, wireframe: false });
    const matChipBlack = new THREE.MeshBasicMaterial({ color: 0x1a1a1a, wireframe: false });
    const matGoldPins = new THREE.MeshBasicMaterial({ color: 0xffd700, wireframe: false });
    const matHeaderBlack = new THREE.MeshBasicMaterial({ color: 0x212121, wireframe: false });
    const matMetalShield = new THREE.MeshBasicMaterial({ color: 0x90a4ae, wireframe: false });
    const matUsbBlue = new THREE.MeshBasicMaterial({ color: 0x0055ff, wireframe: false });
    const matWhiteSocket = new THREE.MeshBasicMaterial({ color: 0xf5f5f5, wireframe: false });

    // 1. Primary FR-4 Multi-Layer Substrate PCB
    const pcbGeo = new THREE.BoxGeometry(3.6, 0.08, 2.4);
    const pcbMesh = new THREE.Mesh(pcbGeo, matPcb);
    pcbMesh.add(new THREE.Mesh(pcbGeo, matPcbTrace));
    pcbMesh.userData = { home: new THREE.Vector3(0, 0, 0), explodeDir: new THREE.Vector3(0, -1.2, 0), label: "[RPI-01] 6-Layer High-Speed FR-4 PCB Substrate", intensity: 1.0 };
    group.add(pcbMesh);
    parts.push(pcbMesh);

    // 2. Broadcom BCM2712 Quad-Core 2.4GHz SoC with Metal Heat Spreader
    const socGeo = new THREE.BoxGeometry(0.72, 0.14, 0.72);
    const socMesh = new THREE.Mesh(socGeo, matSocAlloy);
    socMesh.position.set(-0.25, 0.11, -0.15);
    socMesh.userData = { home: new THREE.Vector3(-0.25, 0.11, -0.15), explodeDir: new THREE.Vector3(0, 1.8, 0), label: "[RPI-02] Broadcom BCM2712 Quad-Core 2.4GHz SoC", intensity: 1.5, isCore: true };
    group.add(socMesh);
    parts.push(socMesh);

    // 3. 8GB LPDDR4X-4266 SDRAM IC
    const ramGeo = new THREE.BoxGeometry(0.55, 0.08, 0.55);
    const ramMesh = new THREE.Mesh(ramGeo, matChipBlack);
    ramMesh.position.set(-0.25, 0.08, 0.55);
    ramMesh.userData = { home: new THREE.Vector3(-0.25, 0.08, 0.55), explodeDir: new THREE.Vector3(0, 1.4, 0), label: "[RPI-03] 8GB LPDDR4X SDRAM", intensity: 1.2 };
    group.add(ramMesh);
    parts.push(ramMesh);

    // 4. 40-Pin Dual-Row GPIO Header
    const gpioGroup = new THREE.Group();
    const gpioBase = new THREE.Mesh(new THREE.BoxGeometry(2.1, 0.12, 0.22), matHeaderBlack);
    gpioGroup.add(gpioBase);
    for (let p = 0; p < 20; p++) {
      const px = -0.95 + p * 0.1;
      const pinA = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.32, 8), matGoldPins);
      pinA.position.set(px, 0.18, -0.05);
      const pinB = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.32, 8), matGoldPins);
      pinB.position.set(px, 0.18, 0.05);
      gpioGroup.add(pinA, pinB);
    }
    gpioGroup.position.set(0.4, 0.1, -1.02);
    gpioGroup.userData = { home: new THREE.Vector3(0.4, 0.1, -1.02), explodeDir: new THREE.Vector3(0, 2.2, -1.0), label: "[RPI-04] 40-Pin Multi-Function GPIO Bus", intensity: 1.1 };
    group.add(gpioGroup);
    parts.push(gpioGroup);

    // 5. Gigabit Ethernet Port
    const ethMesh = new THREE.Mesh(new THREE.BoxGeometry(0.75, 0.62, 0.68), matMetalShield);
    ethMesh.position.set(1.45, 0.35, -0.72);
    ethMesh.userData = { home: new THREE.Vector3(1.45, 0.35, -0.72), explodeDir: new THREE.Vector3(1.6, 0.8, -0.8), label: "[RPI-05] Shielded RJ45 Gigabit Ethernet Port", intensity: 1.0 };
    group.add(ethMesh);
    parts.push(ethMesh);

    // 6. Dual Stacked USB 3.0 & USB 2.0 Ports
    const usb3Mesh = new THREE.Mesh(new THREE.BoxGeometry(0.68, 0.65, 0.58), matMetalShield);
    const usb3Tongue = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.08, 0.4), matUsbBlue);
    usb3Tongue.position.set(0.28, 0.1, 0);
    usb3Mesh.add(usb3Tongue);
    usb3Mesh.position.set(1.45, 0.36, 0.05);
    usb3Mesh.userData = { home: new THREE.Vector3(1.45, 0.36, 0.05), explodeDir: new THREE.Vector3(1.8, 0.8, 0), label: "[RPI-06A] Dual USB 3.0 Host Ports", intensity: 1.1 };
    group.add(usb3Mesh);
    parts.push(usb3Mesh);

    const usb2Mesh = new THREE.Mesh(new THREE.BoxGeometry(0.68, 0.65, 0.58), matMetalShield);
    usb2Mesh.position.set(1.45, 0.36, 0.78);
    usb2Mesh.userData = { home: new THREE.Vector3(1.45, 0.36, 0.78), explodeDir: new THREE.Vector3(1.8, 0.8, 0.9), label: "[RPI-06B] Dual USB 2.0 Host Ports", intensity: 1.0 };
    group.add(usb2Mesh);
    parts.push(usb2Mesh);

    // 7. Dual Micro-HDMI Ports & USB-C Power In
    const hdmi1 = new THREE.Mesh(new THREE.BoxGeometry(0.32, 0.16, 0.26), matMetalShield);
    hdmi1.position.set(-0.55, 0.12, 1.1);
    hdmi1.userData = { home: new THREE.Vector3(-0.55, 0.12, 1.1), explodeDir: new THREE.Vector3(-0.4, 0.6, 1.6), label: "[RPI-07A] Micro-HDMI 0 Port · 4Kp60", intensity: 1.0 };
    const hdmi2 = new THREE.Mesh(new THREE.BoxGeometry(0.32, 0.16, 0.26), matMetalShield);
    hdmi2.position.set(0.05, 0.12, 1.1);
    hdmi2.userData = { home: new THREE.Vector3(0.05, 0.12, 1.1), explodeDir: new THREE.Vector3(0.2, 0.6, 1.6), label: "[RPI-07B] Micro-HDMI 1 Port · 4Kp60", intensity: 1.0 };
    const usbcPower = new THREE.Mesh(new THREE.BoxGeometry(0.38, 0.16, 0.28), matMetalShield);
    usbcPower.position.set(-1.25, 0.12, 1.1);
    usbcPower.userData = { home: new THREE.Vector3(-1.25, 0.12, 1.1), explodeDir: new THREE.Vector3(-1.2, 0.6, 1.6), label: "[RPI-08] USB-C 5V/5A Power Delivery Ingest", intensity: 1.3 };
    group.add(hdmi1, hdmi2, usbcPower);
    parts.push(hdmi1, hdmi2, usbcPower);

    // 8. CSI-2 MIPI Camera Ribbon FPC Socket
    const csiSocket = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.22, 0.88), matWhiteSocket);
    csiSocket.position.set(0.65, 0.15, 0.15);
    csiSocket.userData = { home: new THREE.Vector3(0.65, 0.15, 0.15), explodeDir: new THREE.Vector3(0, 1.6, 0), label: "[RPI-09] 22-Pin MIPI CSI-2 Camera Port", intensity: 1.3 };
    group.add(csiSocket);
    parts.push(csiSocket);

    // 9. DSI Display Ribbon Socket & Underside MicroSD Slot
    const dsiSocket = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.22, 0.88), matWhiteSocket);
    dsiSocket.position.set(-1.45, 0.15, -0.15);
    dsiSocket.userData = { home: new THREE.Vector3(-1.45, 0.15, -0.15), explodeDir: new THREE.Vector3(-1.2, 1.4, 0), label: "[RPI-10] 22-Pin MIPI DSI Display Port", intensity: 1.0 };
    const sdSlot = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.07, 0.55), matMetalShield);
    sdSlot.position.set(-1.65, -0.08, 0);
    sdSlot.userData = { home: new THREE.Vector3(-1.65, -0.08, 0), explodeDir: new THREE.Vector3(-2.2, -0.6, 0), label: "[RPI-11] MicroSD Card Interface", intensity: 1.0 };
    group.add(dsiSocket, sdSlot);
    parts.push(dsiSocket, sdSlot);

    group.userData = {
      ports: {
        csi: new THREE.Vector3(0.65, 0.26, 0.15),
        power: new THREE.Vector3(-1.25, 0.15, 1.1),
        gpio_vcc: new THREE.Vector3(0.3, 0.35, -1.07),
        gpio_gnd: new THREE.Vector3(0.4, 0.35, -0.97),
        gpio_sda: new THREE.Vector3(0.2, 0.35, -1.07),
        gpio_scl: new THREE.Vector3(0.2, 0.35, -0.97)
      }
    };

    return { group, parts, name: "raspberry_pi", type: "hardware" };
  }

  // ── HIGH-DETAIL EMBEDDED OPTICAL CONSTRUCT: CAMERA MODULE ──
  static buildCameraModule() {
    const group = new THREE.Group();
    group.name = "construct_root";
    const parts = [];

    const matPcb = new THREE.MeshBasicMaterial({ color: 0x0a3d24, wireframe: false });
    const matPcbWire = new THREE.MeshBasicMaterial({ color: 0x00e5ff, wireframe: true, transparent: true, opacity: 0.4 });
    const matBarrel = new THREE.MeshBasicMaterial({ color: 0x263238, wireframe: false });
    const matGlass = new THREE.MeshBasicMaterial({ color: 0x00e5ff, transparent: true, opacity: 0.75 });
    const matSocket = new THREE.MeshBasicMaterial({ color: 0xf5f5f5, wireframe: false });

    // 1. Camera PCB Substrate
    const pcbGeo = new THREE.BoxGeometry(1.2, 0.08, 1.2);
    const pcbMesh = new THREE.Mesh(pcbGeo, matPcb);
    pcbMesh.add(new THREE.Mesh(pcbGeo, matPcbWire));
    pcbMesh.userData = { home: new THREE.Vector3(0, 0, 0), explodeDir: new THREE.Vector3(0, -1.0, 0), label: "[CAM-01] Sony IMX Sensor PCB Substrate", intensity: 1.0 };
    group.add(pcbMesh);
    parts.push(pcbMesh);

    // 2. Optical Sensor Barrel
    const barrelGeo = new THREE.CylinderGeometry(0.38, 0.42, 0.52, 24);
    const barrelMesh = new THREE.Mesh(barrelGeo, matBarrel);
    barrelMesh.position.set(0, 0.3, 0);
    barrelMesh.userData = { home: new THREE.Vector3(0, 0.3, 0), explodeDir: new THREE.Vector3(0, 1.5, 0), label: "[CAM-02] Voice Coil Autofocus Mechanism", intensity: 1.4 };
    group.add(barrelMesh);
    parts.push(barrelMesh);

    // 3. Optical Glass Front Element
    const lensGeo = new THREE.CylinderGeometry(0.25, 0.25, 0.06, 24);
    const lensMesh = new THREE.Mesh(lensGeo, matGlass);
    lensMesh.position.set(0, 0.58, 0);
    lensMesh.userData = { home: new THREE.Vector3(0, 0.58, 0), explodeDir: new THREE.Vector3(0, 2.4, 0), label: "[CAM-03] 12MP f/1.8 Quad-Bayer Optical Lens", intensity: 1.6, isCore: true };
    group.add(lensMesh);
    parts.push(lensMesh);

    // 4. CSI FPC Flex Ribbon Connector Port
    const csiSocket = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.16, 0.72), matSocket);
    csiSocket.position.set(-0.45, 0.12, 0);
    csiSocket.userData = { home: new THREE.Vector3(-0.45, 0.12, 0), explodeDir: new THREE.Vector3(-1.4, 0.8, 0), label: "[CAM-04] MIPI CSI Flex Ribbon Receiver", intensity: 1.2 };
    group.add(csiSocket);
    parts.push(csiSocket);

    group.userData = {
      ports: {
        csi: new THREE.Vector3(-0.45, 0.2, 0)
      }
    };

    return { group, parts, name: "camera_module", type: "hardware" };
  }

  // ── HIGH-DETAIL POWER CONSTRUCT: RECHARGEABLE LIPO BATTERY MODULE ──
  static buildBatteryPack() {
    const group = new THREE.Group();
    group.name = "construct_root";
    const parts = [];

    const matPouch = new THREE.MeshBasicMaterial({ color: 0x37474f, wireframe: false });
    const matKapton = new THREE.MeshBasicMaterial({ color: 0xffa000, transparent: true, opacity: 0.85 });
    const matBms = new THREE.MeshBasicMaterial({ color: 0x1b5e20, wireframe: false });
    const matRedWire = new THREE.MeshBasicMaterial({ color: 0xff1744, wireframe: false });
    const matBlackWire = new THREE.MeshBasicMaterial({ color: 0x212121, wireframe: false });

    // 1. Lithium Polymer Cell Pouch
    const pouchMesh = new THREE.Mesh(new THREE.BoxGeometry(2.6, 0.45, 1.4), matPouch);
    pouchMesh.add(new THREE.Mesh(new THREE.BoxGeometry(2.62, 0.46, 1.42), matKapton));
    pouchMesh.userData = { home: new THREE.Vector3(0, 0, 0), explodeDir: new THREE.Vector3(0, -1.0, 0), label: "[BAT-01] 3.7V 5000mAh LiPo Cell", intensity: 1.2 };
    group.add(pouchMesh);
    parts.push(pouchMesh);

    // 2. Battery Protection Circuit Module (BMS)
    const bmsMesh = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.35, 1.3), matBms);
    bmsMesh.position.set(1.4, 0.05, 0);
    bmsMesh.userData = { home: new THREE.Vector3(1.4, 0.05, 0), explodeDir: new THREE.Vector3(1.4, 0.5, 0), label: "[BAT-02] BMS Safety Regulator", intensity: 1.4 };
    group.add(bmsMesh);
    parts.push(bmsMesh);

    // 3. Silicone Wire Leads
    const redWire = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.6, 8), matRedWire);
    redWire.rotation.z = Math.PI / 2;
    redWire.position.set(1.8, 0.1, 0.2);
    const blackWire = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.6, 8), matBlackWire);
    blackWire.rotation.z = Math.PI / 2;
    blackWire.position.set(1.8, 0.1, -0.2);
    group.add(redWire, blackWire);
    parts.push(redWire, blackWire);

    group.userData = {
      ports: {
        power: new THREE.Vector3(2.1, 0.1, 0),
        vcc: new THREE.Vector3(2.1, 0.1, 0.2),
        gnd: new THREE.Vector3(2.1, 0.1, -0.2)
      }
    };

    return { group, parts, name: "battery_pack", type: "hardware" };
  }

  // ── HIGH-DETAIL DISPLAY CONSTRUCT: 0.96" I2C OLED SCREEN ──
  static buildOLEDDisplay() {
    const group = new THREE.Group();
    group.name = "construct_root";
    const parts = [];

    const matPcb = new THREE.MeshBasicMaterial({ color: 0x01579b, wireframe: false });
    const matGlass = new THREE.MeshBasicMaterial({ color: 0x050515, wireframe: false });
    const matPixelGlow = new THREE.MeshBasicMaterial({ color: 0x00e5ff, transparent: true, opacity: 0.9 });
    const matGoldPins = new THREE.MeshBasicMaterial({ color: 0xffd700, wireframe: false });

    // 1. OLED PCB Substrate
    const pcb = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.06, 1.4), matPcb);
    pcb.userData = { home: new THREE.Vector3(0, 0, 0), explodeDir: new THREE.Vector3(0, -1.0, 0), label: "[OLED-01] SSD1306 Controller Board · I2C Mode", intensity: 1.0 };
    group.add(pcb);
    parts.push(pcb);

    // 2. Active Matrix OLED Glass Display
    const glass = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.08, 0.8), matGlass);
    const pixels = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.09, 0.7), matPixelGlow);
    glass.add(pixels);
    glass.position.set(0, 0.08, 0.15);
    glass.userData = { home: new THREE.Vector3(0, 0.08, 0.15), explodeDir: new THREE.Vector3(0, 1.5, 0), label: "[OLED-02] 128x64 Monochrome Pixel Matrix", intensity: 1.5, isCore: true };
    group.add(glass);
    parts.push(glass);

    // 3. 4-Pin I2C Header (VCC, GND, SCL, SDA)
    const headerGroup = new THREE.Group();
    for (let p = 0; p < 4; p++) {
      const pin = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.28, 8), matGoldPins);
      pin.position.set(-0.35 + p * 0.23, 0.12, -0.55);
      headerGroup.add(pin);
    }
    headerGroup.userData = { home: new THREE.Vector3(0, 0, 0), explodeDir: new THREE.Vector3(0, 1.2, -1.2), label: "[OLED-03] 4-Pin Header (GND, VCC, SCL, SDA)", intensity: 1.1 };
    group.add(headerGroup);
    parts.push(headerGroup);

    group.userData = {
      ports: {
        i2c: new THREE.Vector3(0, 0.2, -0.55)
      }
    };

    return { group, parts, name: "oled_display", type: "hardware" };
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// 3b. PHYSICAL 3D INTERCONNECT ROUTING ENGINE (Ribbon Cables, Wires, Conduits)
// ══════════════════════════════════════════════════════════════════════════════
export class InterconnectRouter {
  static createCsiRibbon(fromPos, toPos) {
    const mid1 = new THREE.Vector3(fromPos.x + (toPos.x - fromPos.x) * 0.25, fromPos.y + 0.9, fromPos.z + 0.3);
    const mid2 = new THREE.Vector3(fromPos.x + (toPos.x - fromPos.x) * 0.75, toPos.y + 0.9, toPos.z - 0.3);
    const curve = new THREE.CatmullRomCurve3([fromPos, mid1, mid2, toPos]);

    const tubeGeo = new THREE.TubeGeometry(curve, 36, 0.07, 8, false);
    const ribbonMat = new THREE.MeshBasicMaterial({ color: 0x8ff0e4, transparent: true, opacity: 0.8, wireframe: false });
    const ribbonMesh = new THREE.Mesh(tubeGeo, ribbonMat);

    const pulseCount = 35;
    const pulseGeo = new THREE.BufferGeometry();
    const pulsePos = new Float32Array(pulseCount * 3);
    for (let i = 0; i < pulseCount; i++) {
      const pt = curve.getPointAt(i / pulseCount);
      pulsePos[i * 3] = pt.x;
      pulsePos[i * 3 + 1] = pt.y;
      pulsePos[i * 3 + 2] = pt.z;
    }
    pulseGeo.setAttribute("position", new THREE.BufferAttribute(pulsePos, 3));
    const pulseMat = new THREE.PointsMaterial({ color: 0x00ffff, size: 0.14, transparent: true, opacity: 0.95 });
    const pulseSystem = new THREE.Points(pulseGeo, pulseMat);

    const group = new THREE.Group();
    group.add(ribbonMesh);
    group.add(pulseSystem);

    return { group, curve, pulseSystem, pulseCount, type: "csi_ribbon", label: "MIPI CSI-2 2-Lane Bus · 1.5 Gbps" };
  }

  static createJumperWire(fromPos, toPos, color = 0xff1744, label = "+5V VCC Rail") {
    const dist = fromPos.distanceTo(toPos);
    const mid = new THREE.Vector3(
      (fromPos.x + toPos.x) / 2,
      Math.max(fromPos.y, toPos.y) + Math.min(1.8, dist * 0.35 + 0.4),
      (fromPos.z + toPos.z) / 2
    );
    const curve = new THREE.CatmullRomCurve3([fromPos, mid, toPos]);
    const tubeGeo = new THREE.TubeGeometry(curve, 28, 0.035, 8, false);
    const wireMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.88 });
    const wireMesh = new THREE.Mesh(tubeGeo, wireMat);

    const pulseCount = 20;
    const pulseGeo = new THREE.BufferGeometry();
    const pulsePos = new Float32Array(pulseCount * 3);
    for (let i = 0; i < pulseCount; i++) {
      const pt = curve.getPointAt(i / pulseCount);
      pulsePos[i * 3] = pt.x;
      pulsePos[i * 3 + 1] = pt.y;
      pulsePos[i * 3 + 2] = pt.z;
    }
    pulseGeo.setAttribute("position", new THREE.BufferAttribute(pulsePos, 3));
    const pulseMat = new THREE.PointsMaterial({ color, size: 0.10, transparent: true, opacity: 0.95 });
    const pulseSystem = new THREE.Points(pulseGeo, pulseMat);

    const group = new THREE.Group();
    group.add(wireMesh);
    group.add(pulseSystem);

    return { group, curve, pulseSystem, pulseCount, type: "wire", label };
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
  static targetPosition = new THREE.Vector3(0, 0, 0);
  static targetScale = 1.0;
  static _dockPosition = "center";
  static _gestureState = "IDLE";
  static _pinchDecayFrames = 0;
  static _prevCursorPos = null;
  static _prevTwoHandDist = null;
  static _isDragging = false;
  static _dragAnchor = null;

  static components = [];
  static interconnects = [];

  static setControlPosition(pos = "bottom") {
    const bar = document.getElementById("holo_bottom_bar");
    if (!bar) return;
    HolographicAudio.playServo(1);
    if (pos === "top") {
      bar.style.top = "76px";
      bar.style.bottom = "auto";
      bar.style.left = "50%";
      bar.style.right = "auto";
      bar.style.transform = "translateX(-50%)";
      bar.style.flexDirection = "row";
    } else if (pos === "left") {
      bar.style.top = "50%";
      bar.style.bottom = "auto";
      bar.style.left = "24px";
      bar.style.right = "auto";
      bar.style.transform = "translateY(-50%)";
      bar.style.flexDirection = "column";
    } else if (pos === "right") {
      bar.style.top = "50%";
      bar.style.bottom = "auto";
      bar.style.right = "24px";
      bar.style.left = "auto";
      bar.style.transform = "translateY(-50%)";
      bar.style.flexDirection = "column";
    } else {
      bar.style.top = "auto";
      bar.style.bottom = "24px";
      bar.style.left = "50%";
      bar.style.right = "auto";
      bar.style.transform = "translateX(-50%)";
      bar.style.flexDirection = "row";
    }
  }

  static setSimulationMode(mode) {
    if (!mode) return;
    this.simulator.mode = mode;
    HolographicAudio.playClick();
    if (this.hudEl) {
      this.hudEl.querySelectorAll(".sim-btn").forEach(b => {
        b.classList.toggle("active", b.getAttribute("data-sim") === mode);
      });
    }
  }

  static setExploded(exploded) {
    this.isExploded = !!exploded;
    const explodeBtn = document.getElementById("holo_explode_btn");
    if (explodeBtn) {
      explodeBtn.innerText = `EXPLODED: ${this.isExploded ? "ON" : "OFF"}`;
      explodeBtn.style.color = this.isExploded ? "#ffb300" : "#00e5ff";
    }
    HolographicAudio.playServo(this.isExploded ? 1 : -1);
  }

  static dock(mode = "center") {
    if (!this.currentConstruct || !this.camera) return;
    this._isDragging = false;
    this._dragAnchor = null;
    this._dockPosition = mode;
    const vFOV = (this.camera.fov * Math.PI) / 180;
    const dist = Math.abs(this.camera.position.z - (this.currentConstruct.group ? this.currentConstruct.group.position.z : 0));
    const visibleHeight = 2 * Math.tan(vFOV / 2) * dist;
    const visibleWidth = visibleHeight * (window.innerWidth / window.innerHeight);

    if (mode === "left") {
      this.targetPosition.set(-visibleWidth * 0.30, 0, 0);
      HolographicAudio.playServo(-1);
    } else if (mode === "right") {
      this.targetPosition.set(visibleWidth * 0.30, 0, 0);
      HolographicAudio.playServo(1);
    } else {
      this.targetPosition.set(0, 0, 0);
      HolographicAudio.playClick();
    }
  }

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
          <button class="holo-btn" data-construct="dynamic" id="holo_dynamic_btn">🛠 DYNAMIC</button>
        </div>

        <div style="flex: 1; display: flex; gap: 8px; background: rgba(5,25,30,0.75); padding: 6px 14px; border-radius: 12px; border: 1px solid rgba(0,229,255,0.4); backdrop-filter: blur(10px);">
          <input id="holo_prompt_input" type="text" placeholder="Ask JARVIS for ANY construct (e.g. '3D model of a Toyota Supra', 'iPhone 15 Pro', 'jet engine')..." style="flex: 1; background: rgba(0,0,0,0.5); border: 1px solid rgba(0,229,255,0.3); border-radius: 6px; padding: 6px 12px; color: #ffffff; font-family: monospace; font-size: 11px; outline: none;">
          <button id="holo_submit_btn" style="background: rgba(0,229,255,0.2); border: 1px solid #00e5ff; color: #00e5ff; padding: 6px 14px; border-radius: 6px; font-family: monospace; font-size: 11px; font-weight: 700; cursor: pointer;">⚡ CONSTRUCT / MODIFY</button>
        </div>
      </div>

      <!-- TOP RIGHT: Close Studio Button -->
      <div style="position: absolute; top: 18px; right: 24px; pointer-events: auto;">
        <button id="holo_close_btn" style="background: rgba(255,23,68,0.2); border: 1px solid #ff1744; color: #ff80ab; padding: 8px 18px; border-radius: 8px; font-family: monospace; font-weight: 700; cursor: pointer;">✕ CLOSE BLUEPRINT</button>
      </div>

      <!-- LEFT PANEL: Real-World Science Telemetry & Formulas -->
      <div id="holo_telemetry_panel" style="position: absolute; top: 80px; left: 24px; width: 340px; background: rgba(5,25,30,0.75); border: 1px solid rgba(0,229,255,0.35); border-radius: 12px; padding: 18px; backdrop-filter: blur(12px); transition: all 0.3s;">
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
      <div id="holo_bottom_bar" style="position: absolute; bottom: 24px; left: 50%; transform: translateX(-50%); display: flex; align-items: center; gap: 16px; pointer-events: auto; background: rgba(5,25,30,0.8); padding: 12px 24px; border-radius: 14px; border: 1px solid rgba(0,229,255,0.4); backdrop-filter: blur(14px); transition: all 0.3s;">
        <div style="display: flex; gap: 6px;">
          <button class="sim-btn active" data-sim="thermal">THERMAL</button>
          <button class="sim-btn" data-sim="stress">VON MISES</button>
          <button class="sim-btn" data-sim="em_field">EM CONFINEMENT</button>
          <button class="sim-btn" data-sim="aerodynamics">AERO</button>
        </div>

        <div style="width: 1px; height: 32px; background: rgba(0,229,255,0.3);"></div>

        <button id="holo_connect_btn" style="background: rgba(0,255,180,0.2); border: 1px solid #00ffb4; color: #00ffb4; padding: 7px 14px; border-radius: 8px; font-size: 11px; font-weight: 700; cursor: pointer; transition: all 0.2s;">🔗 CONNECT & SIMULATE</button>

        <div style="width: 1px; height: 32px; background: rgba(0,229,255,0.3);"></div>

        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 11px; color: #00e5ff;">STRESS:</span>
          <input type="range" id="holo_stress_slider" min="0.5" max="2.0" step="0.05" value="1.0" style="width: 100px; cursor: pointer;">
          <span id="holo_stress_val" style="font-size: 12px; font-weight: 700; width: 38px;">100%</span>
        </div>

        <div style="width: 1px; height: 32px; background: rgba(0,229,255,0.3);"></div>

        <button id="holo_explode_btn" style="background: rgba(0,229,255,0.15); border: 1px solid #00e5ff; color: #00e5ff; padding: 7px 14px; border-radius: 8px; font-size: 11px; font-weight: 700; cursor: pointer;">EXPLODED: OFF</button>

        <div style="width: 1px; height: 32px; background: rgba(0,229,255,0.3);"></div>

        <div style="display: flex; gap: 6px;">
          <button id="holo_dock_left" class="holo-dock-btn" title="Dock construct to Left">⇇ LEFT</button>
          <button id="holo_center_btn" class="holo-dock-btn" title="Center construct">🎯 CENTER</button>
          <button id="holo_dock_right" class="holo-dock-btn" title="Dock construct to Right">⇉ RIGHT</button>
        </div>
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
      .holo-dock-btn {
        background: rgba(0,229,255,0.12); border: 1px solid rgba(0,229,255,0.4); color: #8ff0e4;
        padding: 6px 12px; border-radius: 6px; font-family: inherit; font-size: 11px; font-weight: 700;
        letter-spacing: 0.08em; cursor: pointer; transition: all 0.2s;
      }
      .holo-dock-btn:hover { background: rgba(0,229,255,0.28); color: #ffffff; box-shadow: 0 0 10px rgba(0,229,255,0.4); }
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

    document.getElementById("holo_connect_btn")?.addEventListener("click", () => this.connectAndSimulate());
    document.getElementById("holo_dock_left")?.addEventListener("click", () => this.dock("left"));
    document.getElementById("holo_center_btn")?.addEventListener("click", () => this.dock("center"));
    document.getElementById("holo_dock_right")?.addEventListener("click", () => this.dock("right"));

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
    let dragMode = "rotate"; // "rotate" | "pan"
    let prevX = 0, prevY = 0;

    canvas.addEventListener("contextmenu", (e) => e.preventDefault());

    canvas.addEventListener("mousedown", (e) => {
      isDragging = true;
      dragMode = (e.button === 2 || e.shiftKey) ? "pan" : "rotate";
      prevX = e.clientX;
      prevY = e.clientY;
    });

    window.addEventListener("mouseup", () => { isDragging = false; });

    window.addEventListener("mousemove", (e) => {
      if (!isDragging || !this.currentConstruct) return;
      const dx = e.clientX - prevX;
      const dy = e.clientY - prevY;
      prevX = e.clientX;
      prevY = e.clientY;

      if (dragMode === "pan") {
        const vFOV = (this.camera.fov * Math.PI) / 180;
        const dist = Math.abs(this.camera.position.z - (this.currentConstruct.group ? this.currentConstruct.group.position.z : 0));
        const visibleHeight = 2 * Math.tan(vFOV / 2) * dist;
        const visibleWidth = visibleHeight * (window.innerWidth / window.innerHeight);
        this.targetPosition.x += (dx / window.innerWidth) * visibleWidth;
        this.targetPosition.y -= (dy / window.innerHeight) * visibleHeight;
      } else {
        this.currentConstruct.group.rotation.y += dx * 0.008;
        this.currentConstruct.group.rotation.x += dy * 0.008;
      }
    });

    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.camera.position.z = Math.max(4.5, Math.min(16.0, this.camera.position.z + e.deltaY * 0.006));
    });

    canvas.addEventListener("dblclick", () => {
      this.dock("center");
      this.targetScale = 1.0;
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
          } else if (data.type === "MULTI_CONSTRUCT") {
            this.show();
            this.loadMulti(data.items || [], data.connect || false, data.simulate || false);
          } else if (data.type === "CONNECT_AND_SIMULATE") {
            this.connectAndSimulate();
          } else if (data.type === "UI_CONTROL") {
            if (data.pos) this.setControlPosition(data.pos);
            if (data.dock) this.dock(data.dock);
            if (data.sim) this.setSimulationMode(data.sim);
            if (data.exploded != null) this.setExploded(data.exploded);
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

  static loadConstruct(name = "arc_reactor", simMode = "thermal", stress = 1.0, exploded = false, manifest = null, options = {}) {
    this.show();
    this.simulator.mode = simMode;
    this.simulator.stressLevel = stress;
    this.isExploded = exploded;
    HolographicAudio.playServo(1);

    if (!options.add) {
      if (this.components && this.components.length > 0) {
        this.components.forEach(c => {
          if (c && c.group) this.scene.remove(c.group);
        });
      }
      if (this.interconnects && this.interconnects.length > 0) {
        this.interconnects.forEach(conn => {
          if (conn && conn.group) this.scene.remove(conn.group);
        });
      }
      this.components = [];
      this.interconnects = [];
      this.currentConstruct = null;
      this._clearCallouts();
    }

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
        explodeBtn.innerText = `EXPLODED: ${this.isExploded ? "ON" : "OFF"}`;
        explodeBtn.style.color = this.isExploded ? "#ffb300" : "#00e5ff";
      }
    }

    let construct = null;
    const n = (name || "").toLowerCase();

    if (manifest) {
      construct = BlueprintBuilder.buildFromManifest(manifest);
      this.activeManifest = manifest;
      this.simulator.activeManifest = manifest;
      const dynBtn = document.getElementById("holo_dynamic_btn");
      if (dynBtn) {
        dynBtn.innerText = `🛠 ${manifest.name ? manifest.name.toUpperCase() : "DYNAMIC"}`;
        dynBtn.classList.add("active");
      }
    } else if (n.includes("pi") || n.includes("raspberry")) {
      construct = BlueprintBuilder.buildRaspberryPi();
      this.activeManifest = null;
    } else if (n.includes("camera") || n.includes("lens") || n.includes("optic")) {
      construct = BlueprintBuilder.buildCameraModule();
      this.activeManifest = null;
    } else if (n.includes("battery") || n.includes("cell") || n.includes("power_pack")) {
      construct = BlueprintBuilder.buildBatteryPack();
      this.activeManifest = null;
    } else if (n.includes("oled") || n.includes("display") || n.includes("screen")) {
      construct = BlueprintBuilder.buildOLEDDisplay();
      this.activeManifest = null;
    } else if (n === "dynamic" && this.activeManifest) {
      construct = BlueprintBuilder.buildFromManifest(this.activeManifest);
    } else {
      construct = BlueprintBuilder.buildArcReactor();
      this.activeManifest = null;
    }

    this.scene.add(construct.group);
    this.components.push(construct);
    this.currentConstruct = construct;

    this._rearrangeComponents();
    this._createCallouts();

    if (options.connect) {
      setTimeout(() => this.connectAndSimulate(), 250);
    }
  }

  static _rearrangeComponents() {
    const len = this.components.length;
    if (len <= 1) {
      if (this.components[0]) this.components[0].group.position.set(0, 0, 0);
    } else if (len === 2) {
      this.components[0].group.position.set(-2.0, 0, 0);
      this.components[1].group.position.set(2.0, 0.4, 0);
    } else if (len === 3) {
      this.components[0].group.position.set(-2.2, 0.2, 0);
      this.components[1].group.position.set(1.8, 0.6, 0);
      this.components[2].group.position.set(0, -2.2, 0);
    } else if (len >= 4) {
      this.components.forEach((c, idx) => {
        const angle = (idx / len) * Math.PI * 2;
        c.group.position.set(Math.cos(angle) * 2.8, Math.sin(angle) * 2.0, 0);
      });
    }
  }

  static loadMulti(items = [], shouldConnect = false, shouldSimulate = false) {
    this.show();
    HolographicAudio.playBoot();
    // No preloaded hardware catalog: the user names what they want and JARVIS
    // synthesizes it. Default to the Arc Reactor when nothing is specified.
    if (!items || items.length === 0) items = ["arc_reactor"];

    if (this.components) {
      this.components.forEach(c => { if (c && c.group) this.scene.remove(c.group); });
    }
    if (this.interconnects) {
      this.interconnects.forEach(conn => { if (conn && conn.group) this.scene.remove(conn.group); });
    }
    this.components = [];
    this.interconnects = [];
    this.currentConstruct = null;
    this._clearCallouts();

    items.forEach(it => {
      if (typeof it === "string") {
        this.loadConstruct(it, "fluid_dynamics", 1.0, false, null, { add: true });
      } else if (it && typeof it === "object") {
        this.loadConstruct(it.name || it.id || "dynamic", "fluid_dynamics", 1.0, false, it, { add: true });
      }
    });

    if (shouldConnect || shouldSimulate) {
      setTimeout(() => this.connectAndSimulate(), 350);
    }
  }

  static connectAndSimulate() {
    this.show();
    HolographicAudio.playBoot();
    HolographicAudio.playServo(1);

    if (this.interconnects) {
      this.interconnects.forEach(conn => {
        if (conn && conn.group) this.scene.remove(conn.group);
      });
    }
    this.interconnects = [];

    if (this.components.length < 2) {
      if (this.components.length === 1) {
        // Interconnect the existing part with a power/distribution module
        // synthesized generically (no preloaded hardware catalog).
        this.loadConstruct("power_distribution_module", "system_interconnect", 1.0, false, null, { add: true });
      } else {
        this.loadMulti(["arc_reactor"], false, false);
      }
    }

    const pi = this.components.find(c => c.name.includes("pi"));
    const cam = this.components.find(c => c.name.includes("camera"));
    const bat = this.components.find(c => c.name.includes("battery"));
    const oled = this.components.find(c => c.name.includes("oled") || c.name.includes("display"));

    if (pi && cam) {
      const piPos = pi.group.position.clone().add(new THREE.Vector3(0.65, 0.26, 0.15));
      const camPos = cam.group.position.clone().add(new THREE.Vector3(-0.45, 0.2, 0));
      const csiRibbon = InterconnectRouter.createCsiRibbon(piPos, camPos);
      this.scene.add(csiRibbon.group);
      this.interconnects.push(csiRibbon);
    }

    if (pi && bat) {
      const batVcc = bat.group.position.clone().add(new THREE.Vector3(2.1, 0.1, 0.2));
      const batGnd = bat.group.position.clone().add(new THREE.Vector3(2.1, 0.1, -0.2));
      const piPower = pi.group.position.clone().add(new THREE.Vector3(-1.25, 0.15, 1.1));
      const piGnd = pi.group.position.clone().add(new THREE.Vector3(0.4, 0.35, -0.97));

      const vccWire = InterconnectRouter.createJumperWire(batVcc, piPower, 0xff1744, "+5V VCC Power Rail");
      const gndWire = InterconnectRouter.createJumperWire(batGnd, piGnd, 0x212121, "GND Power Return");
      this.scene.add(vccWire.group, gndWire.group);
      this.interconnects.push(vccWire, gndWire);
    }

    if (pi && oled) {
      const piSda = pi.group.position.clone().add(new THREE.Vector3(0.2, 0.35, -1.07));
      const piScl = pi.group.position.clone().add(new THREE.Vector3(0.2, 0.35, -0.97));
      const oledPort = oled.group.position.clone().add(new THREE.Vector3(0, 0.2, -0.55));

      const sdaWire = InterconnectRouter.createJumperWire(piSda, oledPort, 0xffeb3b, "I2C SDA Serial Data");
      const sclWire = InterconnectRouter.createJumperWire(piScl, oledPort, 0x4caf50, "I2C SCL Serial Clock");
      this.scene.add(sdaWire.group, sclWire.group);
      this.interconnects.push(sdaWire, sclWire);
    }

    if (this.interconnects.length === 0 && this.components.length >= 2) {
      const c1Pos = this.components[0].group.position.clone();
      const c2Pos = this.components[1].group.position.clone();
      const conduit = InterconnectRouter.createCsiRibbon(c1Pos, c2Pos);
      this.scene.add(conduit.group);
      this.interconnects.push(conduit);
    }

    this.simulator.mode = "system_interconnect";
    if (this.hudEl) {
      this.hudEl.querySelectorAll(".sim-btn").forEach(b => b.classList.remove("active"));
    }
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
    // 0. Smooth translation spring easing towards targetPosition and scale
    if (this.currentConstruct && this.currentConstruct.group) {
      this.currentConstruct.group.position.lerp(this.targetPosition, Math.min(1.0, dt * 9.0));
      const curSc = this.currentConstruct.group.scale.x;
      const nxtSc = curSc + (this.targetScale - curSc) * Math.min(1.0, dt * 9.0);
      this.currentConstruct.group.scale.setScalar(nxtSc);
    }

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

    const allConstructs = (this.components && this.components.length > 0) ? this.components : (this.currentConstruct ? [this.currentConstruct] : []);
    allConstructs.forEach(c => {
      if (c && c.parts) {
        c.parts.forEach(p => {
          if (p.userData && p.userData.home && p.userData.explodeDir) {
            p.position.copy(p.userData.home).addScaledVector(p.userData.explodeDir, this.explodeAmount);
          }
          if (p.userData && p.userData.rotSpeed && p.rotation) {
            p.rotation.z += p.userData.rotSpeed * dt;
          }
          if (p.material && p.userData && p.userData.intensity && p.userData.shiftColor) {
            const col = this.simulator.getColor(0x00e5ff, p.userData.intensity);
            if (p.material.color) p.material.color.copy(col);
          }
          if (p.userData && p.userData.isCore) {
            const pulse = 1.0 + Math.sin(performance.now() * 0.005) * 0.04;
            p.scale.set(pulse, pulse, 1.0);
          }
        });

        // Ambient idle rotation
        if (!this._isDragging && this._gestureState !== "INSPECT" && c.group) {
          c.group.rotation.y += dt * 0.20;
        }

        if (c.pSystem) {
          c.pSystem.rotation.z += dt * 0.8;
        }
      }
    });

    // 3b. Animate Physical Interconnect Signal & Electron Pulse Streams
    if (this.interconnects && this.interconnects.length > 0) {
      const nowSec = performance.now() * 0.001;
      this.interconnects.forEach(conn => {
        if (conn && conn.pulseSystem && conn.curve) {
          const posAttr = conn.pulseSystem.geometry.attributes.position;
          const arr = posAttr.array;
          const count = conn.pulseCount;
          for (let i = 0; i < count; i++) {
            const tVal = ((nowSec * 0.85) + (i / count)) % 1.0;
            const pt = conn.curve.getPointAt(tVal);
            arr[i * 3] = pt.x;
            arr[i * 3 + 1] = pt.y;
            arr[i * 3 + 2] = pt.z;
          }
          posAttr.needsUpdate = true;
        }
      });
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
    if (!this.active || !this.currentConstruct || !this.camera) return;
    if (!cursors) return;

    const cursorList = Object.values(cursors).filter(c => c && !c.ghost);
    if (cursorList.length === 0) {
      this._gestureState = "IDLE";
      this._pinchDecayFrames = 0;
      this._prevCursorPos = null;
      this._prevTwoHandDist = null;
      this._isDragging = false;
      this._dragAnchor = null;
      return;
    }

    const vFOV = (this.camera.fov * Math.PI) / 180;
    const distToConstruct = Math.abs(this.camera.position.z - (this.currentConstruct.group ? this.currentConstruct.group.position.z : 0));
    const visibleHeight = 2 * Math.tan(vFOV / 2) * distToConstruct;
    const visibleWidth = visibleHeight * (window.innerWidth / window.innerHeight);

    const pinchedHands = cursorList.filter(c => c.pinched);

    if (cursorList.length === 1) {
      const h = cursorList[0];
      const isPinched = h.pinched;

      if (isPinched) {
        this._pinchDecayFrames = 8; // Grace hold for fast movement
      } else if (this._pinchDecayFrames > 0) {
        this._pinchDecayFrames--;
      }

      const activeDrag = isPinched || this._pinchDecayFrames > 0;

      // Unproject screen coordinates directly to 3D world space at construct depth Z
      const handWorldX = (h.x / window.innerWidth - 0.5) * visibleWidth;
      const handWorldY = -(h.y / window.innerHeight - 0.5) * visibleHeight;

      if (activeDrag) {
        if (!this._isDragging || !this._dragAnchor) {
          this._isDragging = true;
          this._dragAnchor = {
            startHandX: handWorldX,
            startHandY: handWorldY,
            startObjX: this.currentConstruct.group.position.x,
            startObjY: this.currentConstruct.group.position.y
          };
          HolographicAudio.playConfirm();
        }

        // Direct 1:1 World-Space Grab Translation
        const targetX = this._dragAnchor.startObjX + (handWorldX - this._dragAnchor.startHandX);
        const targetY = this._dragAnchor.startObjY + (handWorldY - this._dragAnchor.startHandY);

        // Soft-clamp within visible viewport
        const maxX = visibleWidth * 0.46;
        const maxY = visibleHeight * 0.44;
        this.targetPosition.x = Math.max(-maxX, Math.min(maxX, targetX));
        this.targetPosition.y = Math.max(-maxY, Math.min(maxY, targetY));

        // Direct follow during pinch-drag (instant, responsive 1:1 movement)
        this.currentConstruct.group.position.lerp(this.targetPosition, 0.75);
        this._gestureState = "DRAG";
      } else {
        // Pinch released
        if (this._isDragging) {
          this._isDragging = false;
          this._dragAnchor = null;
        }

        // ── OPEN-PALM HOVER: 3D Holographic Angular Inspection ──
        if (this._prevCursorPos) {
          const dx = h.x - this._prevCursorPos.x;
          const dy = h.y - this._prevCursorPos.y;
          if (Math.hypot(dx, dy) < 180) {
            this.currentConstruct.group.rotation.y += dx * 0.007;
            this.currentConstruct.group.rotation.x += dy * 0.007;
            this._gestureState = "INSPECT";
          }
        }
      }

      this._prevCursorPos = { x: h.x, y: h.y };
      this._prevTwoHandDist = null;

    } else if (cursorList.length >= 2) {
      // ── TWO HANDS: Scale/Depth or Explode Scrub ──
      this._isDragging = false;
      this._dragAnchor = null;
      const [h1, h2] = cursorList;
      const currentDist = Math.hypot(h1.x - h2.x, h1.y - h2.y);

      if (this._prevTwoHandDist != null) {
        const dDist = currentDist - this._prevTwoHandDist;
        if (Math.abs(dDist) < 150) {
          if (pinchedHands.length >= 2) {
            // Two pinched hands: Scale / Camera Depth Zoom
            this.targetScale = Math.max(0.4, Math.min(2.8, this.targetScale + dDist * 0.004));
            this.camera.position.z = Math.max(4.5, Math.min(16.0, this.camera.position.z - dDist * 0.01));
            this._gestureState = "PINCH_SCALE";
          } else {
            // Two open hands: Exploded View Scrub
            this.explodeAmount = Math.max(0, Math.min(1.5, this.explodeAmount + dDist * 0.005));
            this.isExploded = this.explodeAmount > 0.25;
            const explodeBtn = document.getElementById("holo_explode_btn");
            if (explodeBtn) {
              explodeBtn.innerText = `EXPLODED VIEW: ${this.isExploded ? "ON" : "OFF"}`;
              explodeBtn.style.color = this.isExploded ? "#ffb300" : "#00e5ff";
            }
            this._gestureState = "EXPLODE_SCRUB";
          }
        }
      }
      this._prevTwoHandDist = currentDist;
      this._prevCursorPos = null;
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
