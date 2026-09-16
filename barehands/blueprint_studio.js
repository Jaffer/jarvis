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
    } else if (constructName.includes("thrust")) {
      // Convergent-Divergent Rocket & Vector Thruster
      const chamberPSI = Math.round(1850 * s + Math.sin(this.time * 6) * 40);
      const thrustKN = (42.5 * s + Math.sin(this.time * 3) * 1.5).toFixed(1);
      const ispSec = Math.round(310 + 25 * (1.0 / s));
      const machNo = (2.4 * s).toFixed(2);

      this.telemetry = {
        primaryLabel: "VECTOR THRUST",
        primaryVal: `${thrustKN} kN`,
        secondaryLabel: "CHAMBER PRESSURE",
        secondaryVal: `${chamberPSI} PSI`,
        tertiaryLabel: "SPECIFIC IMPULSE (Isp)",
        tertiaryVal: `${ispSec} s (Mach ${machNo})`,
        formula: "F = ṁvₑ + (pₑ - p₀)Aₑ   |   Isp = F / (ṁ·g₀)",
        nominal: chamberPSI < 2800
      };

      if (chamberPSI > 2600) {
        this.alert = `⚠️ CHAMBER OVERPRESSURE: ${chamberPSI} PSI — GIMBAL THROTTLE REQUIRED`;
        if (this.time - this._lastAlarmTime > 1.8) {
          HolographicAudio.playAlarm();
          this._lastAlarmTime = this.time;
        }
      } else {
        this.alert = null;
      }
    } else if (constructName.includes("accelerator") || constructName.includes("collider")) {
      // Relativistic Beam Particle Dynamics
      const beamEnergyTeV = (7.0 * s).toFixed(2);
      const beamCurrentMA = (540 * s).toFixed(0);
      const vacuumTorr = "1.2 × 10⁻¹⁰";
      const lumi = (1.8 * s).toFixed(2) + " × 10³⁴";

      this.telemetry = {
        primaryLabel: "BEAM ENERGY",
        primaryVal: `${beamEnergyTeV} TeV`,
        secondaryLabel: "INSTANT LUMINOSITY",
        secondaryVal: `${lumi} cm⁻²s⁻¹`,
        tertiaryLabel: "UHV CHAMBER",
        tertiaryVal: `${vacuumTorr} Torr (${beamCurrentMA} mA)`,
        formula: "γ = 1 / √(1 - v²/c²)   |   Bρ = p / q",
        nominal: s <= 1.6
      };

      if (s > 1.6) {
        this.alert = `⚠️ BEAM LOSS DETECTED: QUADRUPOLE MAGNET RESYNCHRONIZATION IN PROGRESS`;
        if (this.time - this._lastAlarmTime > 1.8) {
          HolographicAudio.playAlarm();
          this._lastAlarmTime = this.time;
        }
      } else {
        this.alert = null;
      }
    } else if (constructName.includes("drone")) {
      // Aerodynamic Lift & Drag Solver
      const liftN = (120 * s).toFixed(1);
      const cd = (0.038 * (1 + 0.4 * s)).toFixed(3);
      const rpm = Math.round(8400 * s);
      const powerW = Math.round(1450 * s);

      this.telemetry = {
        primaryLabel: "AERODYNAMIC LIFT",
        primaryVal: `${liftN} N (RPM: ${rpm})`,
        secondaryLabel: "DRAG COEFFICIENT",
        secondaryVal: `Cd: ${cd}`,
        tertiaryLabel: "POWER DRAW",
        tertiaryVal: `${powerW} W (Efficiency: ${(92 - s * 4).toFixed(1)}%)`,
        formula: "Fd = ½ ρ v² Cd A   |   L = ½ ρ v² Cl A",
        nominal: s <= 1.7
      };
      this.alert = s > 1.7 ? `⚠️ ROTOR STALL WARNING: AERODYNAMIC SEPARATION DETECTED` : null;
    } else {
      // Cybernetic Neural Grid
      const nodes = Math.round(256 * s);
      const syncGhz = (4.8 * s).toFixed(2);
      const coherence = (99.2 - s * 2.1).toFixed(1);

      this.telemetry = {
        primaryLabel: "ACTIVE SYNAPSES",
        primaryVal: `${nodes} Nodes`,
        secondaryLabel: "CLOCK FREQUENCY",
        secondaryVal: `${syncGhz} GHz`,
        tertiaryLabel: "QUANTUM COHERENCE",
        tertiaryVal: `${coherence}%`,
        formula: "I_syn = ∑ w_ij · S_j(t)   |   τ_m (dV/dt) = -(V - V_rest) + R·I",
        nominal: coherence >= 88.0
      };
      this.alert = coherence < 88.0 ? `⚠️ DECOHERENCE WARNING: QUANTUM NODE INTERFERENCE DETECTED` : null;
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

  // ── FLIGHT STABILIZATION THRUSTER ──
  static buildThruster() {
    const group = new THREE.Group();
    group.name = "construct_root";
    const parts = [];

    // 1. Convergent-Divergent Bell Nozzle Shell
    const nozzleGeo = new THREE.CylinderGeometry(1.2, 2.5, 4.0, 24, 6, true);
    const nozzleMat = new THREE.MeshBasicMaterial({ color: 0x00e5ff, wireframe: true, transparent: true, opacity: 0.8 });
    const nozzleMesh = new THREE.Mesh(nozzleGeo, nozzleMat);
    nozzleMesh.userData = { home: new THREE.Vector3(0, -0.5, 0), explodeDir: new THREE.Vector3(0, -3.5, 0), label: "[TH-01] Convergent-Divergent Nozzle · Carbon-Carbon", intensity: 1.1 };
    group.add(nozzleMesh);
    parts.push(nozzleMesh);

    // 2. High-Pressure Turbine Rotor with 12 Blades
    const turbineGroup = new THREE.Group();
    const shaftGeo = new THREE.CylinderGeometry(0.35, 0.35, 3.2, 16);
    const shaft = new THREE.Mesh(shaftGeo, new THREE.MeshBasicMaterial({ color: 0xffb300, wireframe: true }));
    turbineGroup.add(shaft);
    for (let i = 0; i < 12; i++) {
      const angle = (i / 12) * Math.PI * 2;
      const bladeGeo = new THREE.BoxGeometry(0.1, 0.85, 0.03);
      const blade = new THREE.Mesh(bladeGeo, new THREE.MeshBasicMaterial({ color: 0x00e5ff }));
      blade.position.set(Math.cos(angle) * 0.55, 0, Math.sin(angle) * 0.55);
      blade.rotation.y = -angle + 0.35;
      turbineGroup.add(blade);
    }
    turbineGroup.userData = { home: new THREE.Vector3(0, 1.2, 0), explodeDir: new THREE.Vector3(0, 3.8, 0), label: "[TH-02] Cryogenic Turbine Rotor · 64,000 RPM · Inconel 718", intensity: 1.4, rotSpeed: 4.0 };
    group.add(turbineGroup);
    parts.push(turbineGroup);

    // 3. Fuel Injector Manifold & Gimbal Ring
    const manifoldGeo = new THREE.TorusGeometry(1.6, 0.16, 12, 24);
    const manifold = new THREE.Mesh(manifoldGeo, new THREE.MeshBasicMaterial({ color: 0xffb300, wireframe: true }));
    manifold.rotation.x = Math.PI / 2;
    manifold.position.y = 1.0;
    manifold.userData = { home: new THREE.Vector3(0, 1.0, 0), explodeDir: new THREE.Vector3(0, 2.0, 0), label: "[TH-03] Multi-Port Cryo Injector · 1850 PSI", intensity: 1.2 };
    group.add(manifold);
    parts.push(manifold);

    // 4. Vector Gimbal Actuator Ring
    const gimbalGeo = new THREE.TorusGeometry(2.7, 0.12, 12, 32);
    const gimbal = new THREE.Mesh(gimbalGeo, new THREE.MeshBasicMaterial({ color: 0x00e5ff, wireframe: true }));
    gimbal.rotation.x = Math.PI / 2;
    gimbal.position.y = 0.2;
    gimbal.userData = { home: new THREE.Vector3(0, 0.2, 0), explodeDir: new THREE.Vector3(2.5, 0, 0), label: "[TH-04] Gimbal Actuator · ±18° Vectoring", intensity: 0.8 };
    group.add(gimbal);
    parts.push(gimbal);

    // 5. Mach Shock Diamonds
    const shockGroup = new THREE.Group();
    for (let i = 0; i < 4; i++) {
      const diamondGeo = new THREE.OctahedronGeometry(0.4 - i * 0.06, 0);
      const diamond = new THREE.Mesh(diamondGeo, new THREE.MeshBasicMaterial({ color: 0xff2a55, wireframe: true }));
      diamond.position.y = -2.6 - i * 0.7;
      shockGroup.add(diamond);
    }
    group.add(shockGroup);

    return { group, parts, name: "thruster" };
  }

  // ── QUANTUM PARTICLE ACCELERATOR ──
  static buildAccelerator() {
    const group = new THREE.Group();
    group.name = "construct_root";
    const parts = [];

    // 1. Relativistic Beam Vacuum Pipe
    const pipeGeo = new THREE.TorusGeometry(3.6, 0.3, 20, 64);
    const pipeMesh = new THREE.Mesh(pipeGeo, new THREE.MeshBasicMaterial({ color: 0x00e5ff, wireframe: true, transparent: true, opacity: 0.8 }));
    pipeMesh.userData = { home: new THREE.Vector3(), explodeDir: new THREE.Vector3(0, 0, -2.5), label: "[PA-01] Ultra-High Vacuum Beam Pipe · 10⁻¹⁰ Torr", intensity: 0.9 };
    group.add(pipeMesh);
    parts.push(pipeMesh);

    // 2. 8 Quadrupole Steering Magnets
    for (let i = 0; i < 8; i++) {
      const angle = (i / 8) * Math.PI * 2;
      const magGeo = new THREE.TorusGeometry(0.7, 0.12, 12, 16);
      const mag = new THREE.Mesh(magGeo, new THREE.MeshBasicMaterial({ color: 0xffb300, wireframe: true }));
      mag.position.set(Math.cos(angle) * 3.6, Math.sin(angle) * 3.6, 0);
      mag.rotation.z = angle + Math.PI / 2;
      const expDir = new THREE.Vector3(Math.cos(angle) * 2.2, Math.sin(angle) * 2.2, 0);
      mag.userData = { home: mag.position.clone(), explodeDir: expDir, label: `[PA-02] Quadrupole Focus Station #${i+1} · 8.4 T`, intensity: 1.3 };
      group.add(mag);
      parts.push(mag);
    }

    // 3. Central Collision Detector Chamber
    const detGeo = new THREE.SphereGeometry(1.4, 16, 16);
    const det = new THREE.Mesh(detGeo, new THREE.MeshBasicMaterial({ color: 0xffffff, wireframe: true, transparent: true, opacity: 0.7 }));
    det.userData = { home: new THREE.Vector3(), explodeDir: new THREE.Vector3(0, 0, 3.8), label: "[PA-03] Particle Collision Calorimeter · Silicon Tracker", intensity: 1.5 };
    group.add(det);
    parts.push(det);

    // 4. Counter-rotating relativistic particle beams
    const pCount = 200;
    const b1Pos = new Float32Array(pCount * 3);
    const b2Pos = new Float32Array(pCount * 3);
    for (let i = 0; i < pCount; i++) {
      const a1 = (i / pCount) * Math.PI * 2;
      b1Pos[i*3] = Math.cos(a1) * 3.6;
      b1Pos[i*3+1] = Math.sin(a1) * 3.6;
      b1Pos[i*3+2] = (Math.random() - 0.5) * 0.15;

      const a2 = (i / pCount) * Math.PI * 2;
      b2Pos[i*3] = Math.cos(a2) * 3.6;
      b2Pos[i*3+1] = Math.sin(a2) * 3.6;
      b2Pos[i*3+2] = (Math.random() - 0.5) * 0.15;
    }
    const b1Geo = new THREE.BufferGeometry(); b1Geo.setAttribute("position", new THREE.BufferAttribute(b1Pos, 3));
    const b2Geo = new THREE.BufferGeometry(); b2Geo.setAttribute("position", new THREE.BufferAttribute(b2Pos, 3));
    const b1 = new THREE.Points(b1Geo, new THREE.PointsMaterial({ color: 0x00e5ff, size: 0.12 }));
    const b2 = new THREE.Points(b2Geo, new THREE.PointsMaterial({ color: 0xff2a55, size: 0.12 }));
    b1.userData = { rotSpeed: 3.5 };
    b2.userData = { rotSpeed: -3.5 };
    group.add(b1, b2);

    return { group, parts, name: "accelerator" };
  }

  // ── AERODYNAMIC DRONE AIRFRAME ──
  static buildDroneAirframe() {
    const group = new THREE.Group();
    group.name = "construct_root";
    const parts = [];

    // 1. Central Carbon Monocoque Core
    const bodyGeo = new THREE.CylinderGeometry(1.0, 0.8, 0.45, 8);
    const body = new THREE.Mesh(bodyGeo, new THREE.MeshBasicMaterial({ color: 0x00e5ff, wireframe: true }));
    body.userData = { home: new THREE.Vector3(), explodeDir: new THREE.Vector3(0, 2.2, 0), label: "[DR-01] Carbon Monocoque Chassis · Toray T800", intensity: 0.9 };
    group.add(body);
    parts.push(body);

    // 2. 4 Tubular Carbon Motor Arms & Propellers
    const armPositions = [
      { x: 2.2, z: 2.2, angle: Math.PI / 4 },
      { x: -2.2, z: 2.2, angle: -Math.PI / 4 },
      { x: -2.2, z: -2.2, angle: -3 * Math.PI / 4 },
      { x: 2.2, z: -2.2, angle: 3 * Math.PI / 4 },
    ];

    armPositions.forEach((pos, idx) => {
      const armGroup = new THREE.Group();
      // Arm tube
      const tubeGeo = new THREE.CylinderGeometry(0.08, 0.08, 2.8, 8);
      const tube = new THREE.Mesh(tubeGeo, new THREE.MeshBasicMaterial({ color: 0xffb300, wireframe: true }));
      tube.rotation.z = Math.PI / 2;
      tube.rotation.y = pos.angle;
      tube.position.set(pos.x / 2, 0, pos.z / 2);
      armGroup.add(tube);

      // Motor Nacelle
      const motorGeo = new THREE.CylinderGeometry(0.3, 0.3, 0.5, 12);
      const motor = new THREE.Mesh(motorGeo, new THREE.MeshBasicMaterial({ color: 0x00e5ff }));
      motor.position.set(pos.x, 0.2, pos.z);
      armGroup.add(motor);

      // Propeller Disc
      const propGeo = new THREE.RingGeometry(0.2, 1.2, 24);
      const prop = new THREE.Mesh(propGeo, new THREE.MeshBasicMaterial({ color: 0x00e5ff, transparent: true, opacity: 0.4, side: THREE.DoubleSide }));
      prop.rotation.x = Math.PI / 2;
      prop.position.set(pos.x, 0.48, pos.z);
      prop.userData = { rotSpeed: idx % 2 === 0 ? 12 : -12 };
      armGroup.add(prop);

      const expDir = new THREE.Vector3(pos.x * 1.4, 0, pos.z * 1.4);
      armGroup.userData = { home: new THREE.Vector3(), explodeDir: expDir, label: `[DR-02] Brushless Drive Unit #${idx+1} · 1800 KV`, intensity: 1.2 };
      group.add(armGroup);
      parts.push(armGroup);
    });

    // 3. Forward Multispectral Sensor Pod
    const podGeo = new THREE.SphereGeometry(0.42, 12, 12);
    const pod = new THREE.Mesh(podGeo, new THREE.MeshBasicMaterial({ color: 0xff2a55, wireframe: true }));
    pod.position.set(0, -0.2, 1.1);
    pod.userData = { home: new THREE.Vector3(0, -0.2, 1.1), explodeDir: new THREE.Vector3(0, 0, 2.8), label: "[DR-04] Multispectral LIDAR Pod · 360° Mapping", intensity: 1.4 };
    group.add(pod);
    parts.push(pod);

    return { group, parts, name: "drone" };
  }

  // ── CYBERNETIC NEURAL CIRCUIT GRID ──
  static buildNeuralGrid() {
    const group = new THREE.Group();
    group.name = "construct_root";
    const parts = [];

    const nodeCount = 48;
    const nodes = [];
    const nodePositions = [];

    for (let i = 0; i < nodeCount; i++) {
      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);
      const r = 1.6 + Math.random() * 1.8;
      const pos = new THREE.Vector3(
        r * Math.sin(phi) * Math.cos(theta),
        r * Math.sin(phi) * Math.sin(theta),
        r * Math.cos(phi)
      );
      nodePositions.push(pos);

      const nodeGeo = new THREE.SphereGeometry(0.12, 8, 8);
      const nodeMat = new THREE.MeshBasicMaterial({ color: i % 3 === 0 ? 0xffb300 : 0x00e5ff });
      const nodeMesh = new THREE.Mesh(nodeGeo, nodeMat);
      nodeMesh.position.copy(pos);
      nodeMesh.userData = { home: pos.clone(), explodeDir: pos.clone().multiplyScalar(1.6), label: `[NC-${i+1}] Neuromorphic Core #${i+1}`, intensity: 1.0 };
      group.add(nodeMesh);
      parts.push(nodeMesh);
      nodes.push(nodeMesh);
    }

    // Connect nodes with laser waveguides
    const linePositions = [];
    for (let i = 0; i < nodeCount; i++) {
      for (let j = i + 1; j < nodeCount; j++) {
        if (nodePositions[i].distanceTo(nodePositions[j]) < 1.6) {
          linePositions.push(nodePositions[i].x, nodePositions[i].y, nodePositions[i].z);
          linePositions.push(nodePositions[j].x, nodePositions[j].y, nodePositions[j].z);
        }
      }
    }
    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute("position", new THREE.Float32BufferAttribute(linePositions, 3));
    const lines = new THREE.LineSegments(lineGeo, new THREE.LineBasicMaterial({ color: 0x00e5ff, transparent: true, opacity: 0.35 }));
    group.add(lines);

    return { group, parts, name: "neural_grid" };
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
      <!-- TOP BAR: Construct Selector -->
      <div style="position: absolute; top: 18px; left: 24px; display: flex; gap: 8px; pointer-events: auto; background: rgba(5,25,30,0.7); padding: 8px 16px; border-radius: 12px; border: 1px solid rgba(0,229,255,0.4); backdrop-filter: blur(10px);">
        <span style="font-weight: 700; color: #00e5ff; letter-spacing: 0.12em; line-height: 32px; margin-right: 8px;">STARK LABS // 3D BLUEPRINT:</span>
        <button class="holo-btn active" data-construct="arc_reactor">ARC REACTOR</button>
        <button class="holo-btn" data-construct="thruster">THRUSTER</button>
        <button class="holo-btn" data-construct="accelerator">ACCELERATOR</button>
        <button class="holo-btn" data-construct="drone">DRONE FRAME</button>
        <button class="holo-btn" data-construct="neural_grid">NEURAL GRID</button>
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
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "RENDER_3D_BLUEPRINT") {
            this.show();
            this.loadConstruct(data.construct || "arc_reactor", data.simulation || "thermal", data.stress || 1.0, data.exploded || false);
          }
        } catch (e) {}
      };
    } catch (e) {}
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

  static loadConstruct(name = "arc_reactor", simMode = "thermal", stress = 1.0, exploded = false) {
    this.show();
    this.simulator.mode = simMode;
    this.simulator.stressLevel = stress;
    this.isExploded = exploded;

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

    // Build new 3D model
    if (name.includes("arc") || name.includes("reactor")) {
      this.currentConstruct = BlueprintBuilder.buildArcReactor();
    } else if (name.includes("thrust")) {
      this.currentConstruct = BlueprintBuilder.buildThruster();
    } else if (name.includes("accelerator") || name.includes("collider")) {
      this.currentConstruct = BlueprintBuilder.buildAccelerator();
    } else if (name.includes("drone")) {
      this.currentConstruct = BlueprintBuilder.buildDroneAirframe();
    } else {
      this.currentConstruct = BlueprintBuilder.buildNeuralGrid();
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

    if (pinchedHands.length === 1) {
      // Single hand pinched -> 3D Holographic Rotation
      const h = pinchedHands[0];
      if (this._prevGestureHand) {
        const dx = h.x - this._prevGestureHand.x;
        const dy = h.y - this._prevGestureHand.y;
        this.currentConstruct.group.rotation.y += dx * 0.008;
        this.currentConstruct.group.rotation.x += dy * 0.008;
      }
      this._prevGestureHand = { x: h.x, y: h.y };
      this._prevHandDist = null;
    } else if (pinchedHands.length >= 2) {
      // Two hands pinched -> Gesture Pull/Spread (Exploded View Scrub & Scaling)
      const [h1, h2] = pinchedHands;
      const dist = Math.hypot(h1.x - h2.x, h1.y - h2.y);
      if (this._prevHandDist != null) {
        const dDist = dist - this._prevHandDist;
        this.explodeAmount = Math.max(0, Math.min(1.5, this.explodeAmount + dDist * 0.004));
        this.isExploded = this.explodeAmount > 0.3;
        const explodeBtn = document.getElementById("holo_explode_btn");
        if (explodeBtn) {
          explodeBtn.innerText = `EXPLODED VIEW: ${this.isExploded ? "ON" : "OFF"}`;
          explodeBtn.style.color = this.isExploded ? "#ffb300" : "#00e5ff";
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

// Attach globally for Barehands Board integration
window.HolographicStudio = HolographicStudio;
