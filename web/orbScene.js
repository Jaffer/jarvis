import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";

// ——— COLOR THEME PALETTES ———
const THEMES = {
  ultron: {
    bright: 0xffaa30, mid: 0xdd7700, dim: 0x884400, faint: 0x553300, hot: 0xffcc66,
    tint: [1.15, 0.85, 0.55], label: "ULTRON // AMBER",
  },
  jarvis: {
    bright: 0x00e5ff, mid: 0x0099cc, dim: 0x005577, faint: 0x003344, hot: 0x66ffff,
    tint: [0.55, 0.95, 1.15], label: "JARVIS // ARC REACTOR",
  },
  mark42: {
    bright: 0xff3333, mid: 0xcc1111, dim: 0x771111, faint: 0x441111, hot: 0xff6666,
    tint: [1.15, 0.55, 0.55], label: "MARK 42 // CRIMSON",
  },
};
const THEME_KEYS = Object.keys(THEMES);

const HOME_POSITION = new THREE.Vector3(0, 0.5, 5.5);
const MIN_DISTANCE = 0.6;
const MAX_DISTANCE = 40;

export function createOrbScene(container) {
  const width = container.clientWidth || window.innerWidth;
  const height = container.clientHeight || window.innerHeight;

  // ——— SCENE & CAMERA ———
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(55, width / height, 0.1, 500);
  camera.position.copy(HOME_POSITION);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.85;
  container.appendChild(renderer.domElement);

  // ——— POST PROCESSING ———
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));

  const bloom = new UnrealBloomPass(
    new THREE.Vector2(width, height),
    1.0, // strength baseline
    0.4, // radius
    0.35 // threshold (prevents white glare overexposure)
  );
  composer.addPass(bloom);

  // Chromatic aberration + subtle flicker
  const chromaticShader = {
    uniforms: {
      tDiffuse: { value: null },
      uTime: { value: 0 },
      uIntensity: { value: 0.003 },
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
      uniform float uTime;
      uniform float uIntensity;
      varying vec2 vUv;
      void main() {
        vec2 dir = vUv - vec2(0.5);
        float d = length(dir);
        float offset = uIntensity * d;
        float flicker = 1.0 + 0.02 * sin(uTime * 30.0) * sin(uTime * 7.3);
        vec4 cr = texture2D(tDiffuse, vUv + dir * offset);
        vec4 cg = texture2D(tDiffuse, vUv);
        vec4 cb = texture2D(tDiffuse, vUv - dir * offset * 0.5);
        gl_FragColor = vec4(cr.r, cg.g * 1.05, cb.b * 0.6, 1.0) * flicker;
        gl_FragColor.rgb = mix(gl_FragColor.rgb, gl_FragColor.rgb * vec3(1.15, 0.85, 0.55), 0.28);
      }
    `,
  };
  const chromaticPass = new ShaderPass(chromaticShader);
  composer.addPass(chromaticPass);

  // Orbit controls
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.04;
  controls.minDistance = MIN_DISTANCE;
  controls.maxDistance = MAX_DISTANCE;
  controls.zoomSpeed = 1.4;
  controls.enablePan = false;

  // Colors — mutable for theme switching
  let currentThemeIndex = 0;
  let C_BRIGHT = 0xffaa30;
  let C_MID = 0xdd7700;
  let C_DIM = 0x884400;
  let C_FAINT = 0x553300;
  let C_HOT = 0xffcc66;
  let currentTint = [1.15, 0.85, 0.55];

  // Track all materials for theme recoloring
  const allLineMats = [];
  const allMeshMats = [];
  const _origLineMat = lineMat;

  const orbGroup = new THREE.Group();
  scene.add(orbGroup);

  function lineMat(color, opacity = 1) {
    const mat = new THREE.LineBasicMaterial({
      color,
      transparent: true,
      opacity,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    mat.userData = { colorRole: _mapColorRole(color), baseOpacity: opacity };
    allLineMats.push(mat);
    return mat;
  }

  function _mapColorRole(color) {
    if (color === C_BRIGHT) return 'bright';
    if (color === C_MID) return 'mid';
    if (color === C_DIM) return 'dim';
    if (color === C_FAINT) return 'faint';
    if (color === C_HOT) return 'hot';
    return 'mid';
  }

  function latRing(radius, lat, segs = 120) {
    const r = radius * Math.cos(lat);
    const y = radius * Math.sin(lat);
    const pts = [];
    for (let i = 0; i <= segs; i++) {
      const a = (i / segs) * Math.PI * 2;
      pts.push(new THREE.Vector3(r * Math.cos(a), y, r * Math.sin(a)));
    }
    return new THREE.BufferGeometry().setFromPoints(pts);
  }

  function meridian(radius, lon, segs = 120) {
    const pts = [];
    for (let i = 0; i <= segs; i++) {
      const lat = (i / segs) * Math.PI - Math.PI / 2;
      pts.push(
        new THREE.Vector3(
          radius * Math.cos(lat) * Math.cos(lon),
          radius * Math.sin(lat),
          radius * Math.cos(lat) * Math.sin(lon)
        )
      );
    }
    return new THREE.BufferGeometry().setFromPoints(pts);
  }

  // ═══════════════════════════════════════════════
  // LAYER 1: OUTER SHELL
  // ═══════════════════════════════════════════════
  const outerShell = new THREE.Group();
  const R1 = 2.0;

  for (let i = -15; i <= 15; i++) {
    const lat = (i / 15) * (Math.PI / 2) * 0.95;
    const opacity = i % 3 === 0 ? 0.5 : 0.12;
    const color = i % 3 === 0 ? C_MID : C_FAINT;
    outerShell.add(new THREE.Line(latRing(R1, lat), lineMat(color, opacity)));
  }

  for (let i = 0; i < 24; i++) {
    const lon = (i / 24) * Math.PI * 2;
    const isMajor = i % 6 === 0;
    outerShell.add(
      new THREE.Line(meridian(R1, lon), lineMat(isMajor ? C_MID : C_FAINT, isMajor ? 0.6 : 0.1))
    );
  }

  const CROSS_LINES = 18;
  const CROSS_SPREAD = 0.25;
  for (let i = 0; i < 4; i++) {
    const lon = (i / 4) * Math.PI * 2;
    for (let j = 0; j < CROSS_LINES; j++) {
      const t = (j / (CROSS_LINES - 1)) * 2 - 1;
      const offset = (t * CROSS_SPREAD) / 2;
      const falloff = 1 - Math.abs(t) * 0.7;
      const opacity = 0.85 * falloff;
      const color = Math.abs(t) < 0.3 ? C_BRIGHT : C_MID;
      outerShell.add(new THREE.Line(meridian(R1, lon + offset, 200), lineMat(color, opacity)));
    }
  }

  const EQ_LINES = 20;
  const EQ_SPREAD = 0.35;
  for (let j = 0; j < EQ_LINES; j++) {
    const t = (j / (EQ_LINES - 1)) * 2 - 1;
    const offset = (t * EQ_SPREAD) / 2;
    const falloff = 1 - Math.abs(t) * 0.65;
    const opacity = 0.8 * falloff;
    const color = Math.abs(t) < 0.3 ? C_BRIGHT : C_MID;
    outerShell.add(new THREE.Line(latRing(R1, offset, 200), lineMat(color, opacity)));
  }
  orbGroup.add(outerShell);

  // ═══════════════════════════════════════════════
  // LAYER 2: GRID PANELS
  // ═══════════════════════════════════════════════
  const panelGroup = new THREE.Group();

  function createSpherePanel(latCenter, lonCenter, latSpan, lonSpan, radius, divisions = 4) {
    const group = new THREE.Group();
    const mat = lineMat(C_DIM, 0.25);

    for (let i = 0; i <= divisions; i++) {
      const lat = latCenter - latSpan / 2 + (i / divisions) * latSpan;
      const pts = [];
      for (let j = 0; j <= divisions * 4; j++) {
        const lon = lonCenter - lonSpan / 2 + (j / (divisions * 4)) * lonSpan;
        pts.push(
          new THREE.Vector3(
            radius * Math.cos(lat) * Math.cos(lon),
            radius * Math.sin(lat),
            radius * Math.cos(lat) * Math.sin(lon)
          )
        );
      }
      group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), mat));
    }

    for (let j = 0; j <= divisions; j++) {
      const lon = lonCenter - lonSpan / 2 + (j / divisions) * lonSpan;
      const pts = [];
      for (let i = 0; i <= divisions * 4; i++) {
        const lat = latCenter - latSpan / 2 + (i / (divisions * 4)) * latSpan;
        pts.push(
          new THREE.Vector3(
            radius * Math.cos(lat) * Math.cos(lon),
            radius * Math.sin(lat),
            radius * Math.cos(lat) * Math.sin(lon)
          )
        );
      }
      group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), mat));
    }
    return group;
  }

  for (let i = 0; i < 30; i++) {
    const lat = (Math.random() - 0.5) * Math.PI * 0.8;
    const lon = Math.random() * Math.PI * 2;
    const size = 0.15 + Math.random() * 0.25;
    const panel = createSpherePanel(lat, lon, size, size, R1 + 0.01, 3 + Math.floor(Math.random() * 3));
    panelGroup.add(panel);
  }
  orbGroup.add(panelGroup);

  // ═══════════════════════════════════════════════
  // LAYER 3: SECONDARY SHELL
  // ═══════════════════════════════════════════════
  const shell2 = new THREE.Group();
  const R2 = 2.12;

  for (let i = 0; i < 16; i++) {
    const lat = (Math.random() - 0.5) * Math.PI * 0.85;
    const startLon = Math.random() * Math.PI * 2;
    const arcLen = 0.3 + Math.random() * 1.2;
    const pts = [];
    const segs = 60;
    const r = R2 * Math.cos(lat);
    const y = R2 * Math.sin(lat);
    for (let j = 0; j <= segs; j++) {
      const a = startLon + (j / segs) * arcLen;
      pts.push(new THREE.Vector3(r * Math.cos(a), y, r * Math.sin(a)));
    }
    shell2.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), lineMat(C_MID, 0.2 + Math.random() * 0.3)));
  }

  for (let i = 0; i < 12; i++) {
    const lon = Math.random() * Math.PI * 2;
    const startLat = (Math.random() - 0.5) * Math.PI * 0.8;
    const arcLen = 0.3 + Math.random() * 0.8;
    const pts = [];
    const segs = 40;
    for (let j = 0; j <= segs; j++) {
      const lat = startLat + (j / segs) * arcLen;
      pts.push(
        new THREE.Vector3(
          R2 * Math.cos(lat) * Math.cos(lon),
          R2 * Math.sin(lat),
          R2 * Math.cos(lat) * Math.sin(lon)
        )
      );
    }
    shell2.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), lineMat(C_DIM, 0.15 + Math.random() * 0.2)));
  }
  orbGroup.add(shell2);

  // ═══════════════════════════════════════════════
  // LAYER 4: INNER CORE SPIRAL
  // ═══════════════════════════════════════════════
  const innerCore = new THREE.Group();
  const R3 = 0.9;

  for (let s = 0; s < 8; s++) {
    const pts = [];
    const turns = 3 + Math.random() * 2;
    const segs = 300;
    const phase = (s / 8) * Math.PI * 2;
    for (let i = 0; i <= segs; i++) {
      const t = i / segs;
      const lat = t * Math.PI - Math.PI / 2;
      const lon = t * turns * Math.PI * 2 + phase;
      pts.push(
        new THREE.Vector3(
          R3 * Math.cos(lat) * Math.cos(lon),
          R3 * Math.sin(lat),
          R3 * Math.cos(lat) * Math.sin(lon)
        )
      );
    }
    innerCore.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), lineMat(C_BRIGHT, 0.3 + Math.random() * 0.2)));
  }

  for (let i = -6; i <= 6; i++) {
    const lat = (i / 6) * (Math.PI / 2) * 0.9;
    innerCore.add(new THREE.Line(latRing(R3, lat, 80), lineMat(C_DIM, 0.2)));
  }

  for (let i = 0; i < 12; i++) {
    const lon = (i / 12) * Math.PI * 2;
    innerCore.add(new THREE.Line(meridian(R3, lon, 80), lineMat(C_DIM, 0.15)));
  }
  orbGroup.add(innerCore);

  // ═══════════════════════════════════════════════
  // LAYER 5: INNERMOST CORE
  // ═══════════════════════════════════════════════
  const coreR = 0.25;
  const icoGeo = new THREE.IcosahedronGeometry(coreR, 1);
  const icoEdges = new THREE.EdgesGeometry(icoGeo);
  const icoWireMat = lineMat(C_HOT, 0.9);
  const icoWire = new THREE.LineSegments(icoEdges, icoWireMat);
  orbGroup.add(icoWire);

  const coreSphereMat = new THREE.MeshBasicMaterial({
    color: C_HOT,
    transparent: true,
    opacity: 0.15,
    blending: THREE.AdditiveBlending,
  });
  const coreSphere = new THREE.Mesh(new THREE.SphereGeometry(0.15, 16, 16), coreSphereMat);
  orbGroup.add(coreSphere);

  const glowSphereMat = new THREE.MeshBasicMaterial({
    color: C_MID,
    transparent: true,
    opacity: 0.04,
    blending: THREE.AdditiveBlending,
  });
  const glowSphere = new THREE.Mesh(new THREE.SphereGeometry(0.5, 16, 16), glowSphereMat);
  orbGroup.add(glowSphere);

  // ═══════════════════════════════════════════════
  // CODE TEXT SPRITES
  // ═══════════════════════════════════════════════
  const codeSnippets = [
    "JARVIS // 2.0", "SYS_ACTIVE", "AUDIO.SYNC", "0xFF3A", "malloc()", ">> SCAN", "VOID*", "ACK_OK",
    "CORE.ONLINE", "ptr_ref", "exec()", "hash256", "::bind", "NODE.7",
    "01101001", "10110100", ">>> READY", "HEAP 4K", "WS:CONNECTED",
    "AI.VOICE", "IRQ 0x7", "DMA xfer", "REG EAX", "ANTIGRAVITY",
    "kernel.d", "pipe |>", "chmod +x", "fork()", "SIG_OK",
    "PORTAUDIO: UP", "AES-256", "ELEVENLABS", "TLS 1.3", "STREAM",
    "latency < 2ms", "200 OK", "AI_ORB", "fn main", "use std",
    "impl Jarvis", "async {}", "spawn()", "arc::new", ".unwrap",
  ];

  function makeTextSprite(text, size = 0.08) {
    const c = document.createElement("canvas");
    c.width = 256;
    c.height = 32;
    const ctx = c.getContext("2d");
    ctx.font = "bold 14px Courier New";
    const alpha = 0.35 + Math.random() * 0.55;
    ctx.fillStyle = `rgba(255, ${(130 + Math.random() * 80) | 0}, ${(20 + Math.random() * 30) | 0}, ${alpha})`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 128, 16);
    const tex = new THREE.CanvasTexture(c);
    tex.minFilter = THREE.LinearFilter;
    const s = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: tex,
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    s.scale.set(size * 5, size * 0.7, 1);
    return s;
  }

  function scatterText(count, sizeFn, rFn, speedScale) {
    const group = new THREE.Group();
    for (let i = 0; i < count; i++) {
      const sp = makeTextSprite(codeSnippets[Math.floor(Math.random() * codeSnippets.length)], sizeFn());
      const phi = Math.acos(2 * Math.random() - 1);
      const theta = Math.random() * Math.PI * 2;
      const r = rFn();
      sp.position.set(
        r * Math.sin(phi) * Math.cos(theta),
        r * Math.cos(phi),
        r * Math.sin(phi) * Math.sin(theta)
      );
      sp.userData = {
        phi,
        theta,
        r,
        speed: (speedScale[0] + Math.random() * speedScale[1]) * (Math.random() > 0.5 ? 1 : -1),
      };
      group.add(sp);
    }
    return group;
  }

  const textOuter = scatterText(800, () => 0.04 + Math.random() * 0.04, () => R1 + 0.03 + Math.random() * 0.08, [0.0002, 0.0008]);
  orbGroup.add(textOuter);

  const textInner = scatterText(80, () => 0.03 + Math.random() * 0.03, () => R3 + 0.02, [0.0005, 0.001]);
  orbGroup.add(textInner);

  const textAmbient = scatterText(300, () => 0.03, () => R3 + 0.2 + Math.random() * (R1 - R3 - 0.3), [0.0003, 0.0006]);
  orbGroup.add(textAmbient);

  // ═══════════════════════════════════════════════
  // ORBITING DEBRIS
  // ═══════════════════════════════════════════════
  const debrisGeos = [
    new THREE.IcosahedronGeometry(0.012, 0),
    new THREE.IcosahedronGeometry(0.02, 0),
    new THREE.IcosahedronGeometry(0.03, 1),
    new THREE.IcosahedronGeometry(0.008, 0),
    new THREE.TetrahedronGeometry(0.015, 0),
    new THREE.OctahedronGeometry(0.018, 0),
  ];
  const debris = [];
  for (let i = 0; i < 200; i++) {
    const geo = debrisGeos[Math.floor(Math.random() * debrisGeos.length)];
    const mat = new THREE.MeshBasicMaterial({
      color: Math.random() > 0.7 ? C_BRIGHT : C_MID,
      transparent: true,
      opacity: 0.3 + Math.random() * 0.6,
      blending: THREE.AdditiveBlending,
    });
    const mesh = new THREE.Mesh(geo, mat);
    const orbitR = 1.2 + Math.random() * 4.0;
    const speed = (0.08 + Math.random() * 0.6) * (Math.random() > 0.5 ? 1 : -1);
    const tiltX = (Math.random() - 0.5) * Math.PI * 0.9;
    const tiltZ = (Math.random() - 0.5) * Math.PI * 0.5;
    const phase = Math.random() * Math.PI * 2;
    mesh.userData = { orbitR, speed, tiltX, tiltZ, phase };
    debris.push(mesh);
    orbGroup.add(mesh);
  }

  // ═══════════════════════════════════════════════
  // DUST PARTICLES
  // ═══════════════════════════════════════════════
  const dustCount = 1800;
  const dustPos = new Float32Array(dustCount * 3);
  for (let i = 0; i < dustCount; i++) {
    const rr = 0.5 + Math.pow(Math.random(), 0.6) * 7;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    dustPos[i * 3] = rr * Math.sin(phi) * Math.cos(theta);
    dustPos[i * 3 + 1] = rr * Math.cos(phi);
    dustPos[i * 3 + 2] = rr * Math.sin(phi) * Math.sin(theta);
  }
  const dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute("position", new THREE.Float32BufferAttribute(dustPos, 3));

  const dotC = document.createElement("canvas");
  dotC.width = dotC.height = 64;
  const dCtx = dotC.getContext("2d");
  const g = dCtx.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, "rgba(255,170,48,1)");
  g.addColorStop(0.2, "rgba(255,120,20,0.6)");
  g.addColorStop(0.5, "rgba(200,80,0,0.15)");
  g.addColorStop(1, "rgba(100,40,0,0)");
  dCtx.fillStyle = g;
  dCtx.fillRect(0, 0, 64, 64);

  const dustMat = new THREE.PointsMaterial({
    map: new THREE.CanvasTexture(dotC),
    size: 0.04,
    transparent: true,
    opacity: 0.5,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    sizeAttenuation: true,
    color: C_BRIGHT,
  });
  const dustPoints = new THREE.Points(dustGeo, dustMat);
  orbGroup.add(dustPoints);

  // ═══════════════════════════════════════════════
  // SCANNING RINGS
  // ═══════════════════════════════════════════════
  function makeScanRing(radius, thickness = 0.015) {
    const geo = new THREE.RingGeometry(radius - thickness, radius + thickness, 120);
    const mat = new THREE.MeshBasicMaterial({
      color: C_BRIGHT,
      transparent: true,
      opacity: 0,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.rotation.x = Math.PI / 2;
    return mesh;
  }
  const scanRing1 = makeScanRing(R1, 0.01);
  const scanRing2 = makeScanRing(R1 * 0.7, 0.008);
  orbGroup.add(scanRing1, scanRing2);

  // Hexagonal Nodes
  for (let i = 0; i < 15; i++) {
    const phi = Math.acos(2 * Math.random() - 1);
    const theta = Math.random() * Math.PI * 2;
    const r = R1 + 0.02;
    const hexGeo = new THREE.CircleGeometry(0.03 + Math.random() * 0.02, 6);
    const hexEdges = new THREE.EdgesGeometry(hexGeo);
    const hex = new THREE.LineSegments(hexEdges, lineMat(C_MID, 0.5));
    hex.position.set(r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta));
    hex.lookAt(0, 0, 0);
    outerShell.add(hex);
  }

  // Camera gesture helpers
  const sphericalScratch = new THREE.Spherical();
  const offsetScratch = new THREE.Vector3();

  function rotateBy(deltaTheta, deltaPhi) {
    offsetScratch.copy(camera.position).sub(controls.target);
    sphericalScratch.setFromVector3(offsetScratch);
    sphericalScratch.theta -= deltaTheta;
    sphericalScratch.phi = THREE.MathUtils.clamp(sphericalScratch.phi - deltaPhi, 0.05, Math.PI - 0.05);
    sphericalScratch.makeSafe();
    offsetScratch.setFromSpherical(sphericalScratch);
    camera.position.copy(controls.target).add(offsetScratch);
    camera.lookAt(controls.target);
  }

  function zoomBy(factor) {
    offsetScratch.copy(camera.position).sub(controls.target);
    const dist = THREE.MathUtils.clamp(offsetScratch.length() * factor, MIN_DISTANCE, MAX_DISTANCE);
    offsetScratch.setLength(dist);
    camera.position.copy(controls.target).add(offsetScratch);
  }

  function resetView() {
    camera.position.copy(HOME_POSITION);
    controls.target.set(0, 0, 0);
    camera.lookAt(controls.target);
    controls.update();
  }

  // ——— AUDIO & REACTIVITY STATE ———
  let smoothedAudio = 0.0;
  let isSpeaking = false;
  let activationBurst = 0.0;
  let waveformSamples = new Float32Array(64);
  let waveformEnergy = 0.0;

  function setAudioLevel(val) {
    smoothedAudio = smoothedAudio * 0.7 + Math.min(val, 1.0) * 0.3;
  }

  function setSpeaking(speaking) {
    isSpeaking = speaking;
  }

  function triggerBurst() {
    activationBurst = 1.0;
  }

  function feedWaveform(samples) {
    if (!samples || samples.length === 0) return;
    for (let i = 0; i < 64 && i < samples.length; i++) {
      waveformSamples[i] = Math.abs(samples[i]);
    }
    let sum = 0;
    for (let i = 0; i < waveformSamples.length; i++) sum += waveformSamples[i];
    waveformEnergy = waveformEnergy * 0.6 + (sum / 64) * 0.4;
  }

  function setColorTheme(themeName) {
    let key = (themeName || "").toLowerCase();
    if (key === "arc" || key === "cyan") key = "jarvis";
    if (key === "crimson" || key === "red") key = "mark42";
    if (key === "amber") key = "ultron";

    const theme = THEMES[key] || THEMES.ultron;
    currentThemeIndex = THEME_KEYS.indexOf(key);
    if (currentThemeIndex < 0) currentThemeIndex = 0;
    C_BRIGHT = theme.bright;
    C_MID = theme.mid;
    C_DIM = theme.dim;
    C_FAINT = theme.faint;
    C_HOT = theme.hot;
    currentTint = theme.tint;
    // Recolor all tracked materials
    const roleMap = { bright: C_BRIGHT, mid: C_MID, dim: C_DIM, faint: C_FAINT, hot: C_HOT };
    for (const mat of allLineMats) {
      const role = mat.userData?.colorRole || 'mid';
      mat.color.setHex(roleMap[role] || C_MID);
    }
    // Recolor core materials
    coreSphereMat.color.setHex(C_HOT);
    glowSphereMat.color.setHex(C_MID);
    icoWireMat.color.setHex(C_HOT);
    dustMat.color.setHex(C_BRIGHT);
    scanRing1.material.color.setHex(C_BRIGHT);
    scanRing2.material.color.setHex(C_BRIGHT);
    return theme.label;
  }

  function cycleTheme() {
    const next = THEME_KEYS[(currentThemeIndex + 1) % THEME_KEYS.length];
    return setColorTheme(next);
  }

  function getThemeName() {
    return THEME_KEYS[currentThemeIndex];
  }

  // ═══════════════════════════════════════════════
  // ANIMATION LOOP
  // ═══════════════════════════════════════════════
  const clock = new THREE.Clock();
  let flickerTimer = 0;
  let rafId = 0;
  let disposed = false;

  function animate() {
    if (disposed) return;
    rafId = requestAnimationFrame(animate);
    const t = clock.getElapsedTime();

    // Decay activation burst
    if (activationBurst > 0) {
      activationBurst = Math.max(0, activationBurst - 0.02);
    }

    const audioBoost = Math.min(1.0, smoothedAudio * 1.5 + (isSpeaking ? 0.2 : 0.0) + activationBurst * 0.3);

    // Outer shell rotation accelerates slightly with audio
    const speedMult = 1.0 + audioBoost * 0.8;
    outerShell.rotation.y += 0.0015 * speedMult;
    outerShell.rotation.x = Math.sin(t * 0.08) * 0.05;

    panelGroup.rotation.y += 0.0018 * speedMult;
    panelGroup.rotation.x = Math.sin(t * 0.08 + 0.5) * 0.04;

    shell2.rotation.y -= 0.001 * speedMult;
    shell2.rotation.z = Math.sin(t * 0.12) * 0.03;

    innerCore.rotation.y -= 0.005 * speedMult;
    innerCore.rotation.z += 0.002;
    innerCore.rotation.x = Math.cos(t * 0.1) * 0.08;

    icoWire.rotation.x += 0.008 * speedMult;
    icoWire.rotation.y += 0.012 * speedMult;

    // Core pulse + Sound Reactivity + Voice Waveform
    const wave1 = Math.sin(t * 1.2);
    const wave3 = Math.pow(Math.max(0, Math.sin(t * 0.4)), 5);
    const wave4 = Math.pow(Math.max(0, Math.sin(t * 0.7 + 2)), 8);
    const fadeOut = Math.pow(Math.max(0, Math.sin(t * 0.25)), 3); // periodic subtle breathing
    const surge = wave3 * 0.3 + wave4 * 0.4;
    const voiceBoost = Math.min(1.0, waveformEnergy * 1.5); // voice waveform drives core intensity

    const coreScale = Math.min(1.35, 1 + surge * 0.2 + Math.sin(t * 5) * 0.03 + audioBoost * 0.3 + voiceBoost * 0.2);
    coreSphere.scale.setScalar(coreScale);

    const coreOpacity = Math.max(0, 
      (0.08 + wave1 * 0.03 + surge * 0.1 + audioBoost * 0.2 + voiceBoost * 0.25) * (1 - fadeOut * 0.5)
    );
    coreSphereMat.opacity = Math.min(0.45, coreOpacity);

    glowSphere.scale.setScalar(Math.min(1.4, 1 + surge * 0.2 + audioBoost * 0.4 + voiceBoost * 0.25));
    glowSphereMat.opacity = Math.max(0, (0.03 + surge * 0.04 + audioBoost * 0.1 + voiceBoost * 0.12) * (1 - fadeOut * 0.5));

    icoWire.scale.setScalar(Math.min(1.35, 1 + surge * 0.2 + audioBoost * 0.3 + voiceBoost * 0.25));
    icoWireMat.opacity = Math.min(0.9, 0.5 + surge * 0.2 + audioBoost * 0.2 + voiceBoost * 0.2);

    // Debris orbits
    debris.forEach((d) => {
      const u = d.userData;
      const a = t * u.speed * speedMult + u.phase;
      d.position.set(
        u.orbitR * Math.cos(a) * Math.cos(u.tiltX),
        u.orbitR * Math.sin(u.tiltX) * Math.sin(a * 0.8) + Math.sin(a * 0.3 + u.tiltZ) * 0.2,
        u.orbitR * Math.sin(a) * Math.cos(u.tiltZ)
      );
      d.rotation.x += 0.015;
      d.rotation.z += 0.01;
    });

    // Text drift
    const driftGroups = [
      [textOuter, 1],
      [textInner, 2],
      [textAmbient, 1.2],
    ];
    for (const [group, mult] of driftGroups) {
      group.children.forEach((sp) => {
        const u = sp.userData;
        u.theta += u.speed * mult * speedMult;
        sp.position.set(
          u.r * Math.sin(u.phi) * Math.cos(u.theta),
          u.r * Math.cos(u.phi),
          u.r * Math.sin(u.phi) * Math.sin(u.theta)
        );
      });
    }

    // Scan rings sweeping
    const scanY1 = Math.sin(t * 0.4 * speedMult) * R1;
    scanRing1.position.y = scanY1;
    const scanS1 = Math.sqrt(Math.max(0, R1 * R1 - scanY1 * scanY1)) / R1;
    scanRing1.scale.set(scanS1, scanS1, 1);
    scanRing1.material.opacity = (0.2 + audioBoost * 0.3) * scanS1;

    const scanY2 = Math.sin((t * 0.6 + 2) * speedMult) * R3;
    scanRing2.position.y = scanY2;
    const scanS2 = Math.sqrt(Math.max(0, R3 * R3 - scanY2 * scanY2)) / R3;
    scanRing2.scale.set(scanS2, scanS2, 1);
    scanRing2.material.opacity = (0.15 + audioBoost * 0.25) * scanS2;

    dustPoints.rotation.y += 0.0002 * speedMult;

    // Panel flicker
    flickerTimer += 0.016;
    if (flickerTimer > 0.1) {
      flickerTimer = 0;
      panelGroup.children.forEach((p) => {
        if (Math.random() > 0.95) p.visible = !p.visible;
      });
    }

    // Bloom pulse: capped baseline 1.1, max 1.6 so orb geometry is always crisp & visible
    bloom.strength = Math.min(1.6, 1.0 + Math.sin(t * 0.8) * 0.15 + audioBoost * 0.35 + voiceBoost * 0.25);

    // Update chromatic aberration tint per theme
    chromaticPass.uniforms.uTime.value = t;

    controls.update();
    composer.render();
  }

  animate();

  function onResize() {
    const w = container.clientWidth || window.innerWidth;
    const h = container.clientHeight || window.innerHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
    composer.setSize(w, h);
  }
  window.addEventListener("resize", onResize);

  function dispose() {
    disposed = true;
    cancelAnimationFrame(rafId);
    window.removeEventListener("resize", onResize);
    controls.dispose();
    composer.dispose();
    renderer.dispose();
    renderer.domElement.remove();
  }

  return {
    rotateBy,
    zoomBy,
    zoomIn: () => zoomBy(0.65),
    zoomOut: () => zoomBy(1.55),
    resetView,
    setAudioLevel,
    setSpeaking,
    triggerBurst,
    feedWaveform,
    setColorTheme,
    cycleTheme,
    getThemeName,
    dispose,
  };
}
