import { createOrbScene } from "./orbScene.js?v=3.0.0";
import { HandTracker } from "./handTracker.js?v=3.0.0";

// DOM references
const container = document.getElementById("canvas-container");
const videoEl = document.getElementById("webcam-video");
const overlayEl = document.getElementById("webcam-overlay");
const statusModeEl = document.getElementById("status-mode");
const statusHandsEl = document.getElementById("status-hands");
const wsStatusEl = document.getElementById("ws-status");
const audioMeterBar = document.getElementById("audio-meter-bar");
const gestureBtn = document.getElementById("btn-toggle-gesture");
const themeBtn = document.getElementById("btn-theme");
const voiceBtn = document.getElementById("btn-voice");
const resetBtn = document.getElementById("btn-reset");
const fullscreenBtn = document.getElementById("btn-fullscreen");
const soundscapeBtn = document.getElementById("btn-soundscape");
const toastEl = document.getElementById("hud-toast");
const pipContainer = document.getElementById("pip-container");
const voiceRingEl = document.getElementById("voice-ring");
const voiceRingLabel = voiceRingEl?.querySelector(".voice-ring-label");
const vitalsCpuEl = document.getElementById("vitals-cpu");
const vitalsRamEl = document.getElementById("vitals-ram");
const brainBadgeEl = document.getElementById("brain-badge");
const terminalFeedEl = document.getElementById("terminal-feed");
const terminalStatusEl = document.getElementById("terminal-status");
const terminalModelEl = document.getElementById("terminal-model");
const personaBadge = document.getElementById("persona-badge");
const personaStatusItem = document.getElementById("persona-status-item");
const personaModal = document.getElementById("persona-modal");
const personaBackdrop = document.getElementById("persona-backdrop");
const personaWitSlider = document.getElementById("persona-wit-slider");
const personaWitValue = document.getElementById("persona-wit-value");
const personaWitDesc = document.getElementById("persona-wit-desc");
const personaBtn = document.getElementById("btn-persona");
const personaBtnApply = document.getElementById("btn-persona-apply");
const personaBtnReset = document.getElementById("btn-persona-reset");
const personaCards = document.querySelectorAll(".persona-card");

// Barehands Board references
const barehandsModal = document.getElementById("barehands-modal");
const barehandsBackdrop = document.getElementById("barehands-backdrop");
const barehandsIframe = document.getElementById("barehands-iframe");
const barehandsCloseBtn = document.getElementById("barehands-close-btn");
const barehandsPopoutBtn = document.getElementById("barehands-popout-btn");

function openBarehandsStage(construct) {
  if (!barehandsModal || !barehandsIframe) return;
  const targetUrl = construct ? `/stage.html?construct=${encodeURIComponent(construct)}` : "/stage.html";
  barehandsIframe.src = targetUrl;
  barehandsModal.classList.remove("hidden");
  showToast("🖐️ BAREHANDS // HOLOGRAPHIC BOARD ACTIVE", 3500);
  try {
    window.open(targetUrl, "barehands_stage");
  } catch (e) {}
}

function closeBarehandsStage() {
  if (!barehandsModal || !barehandsIframe) return;
  barehandsModal.classList.add("hidden");
  barehandsIframe.src = "about:blank";
}

if (barehandsCloseBtn) barehandsCloseBtn.addEventListener("click", closeBarehandsStage);
if (barehandsBackdrop) barehandsBackdrop.addEventListener("click", closeBarehandsStage);
if (barehandsPopoutBtn) {
  barehandsPopoutBtn.addEventListener("click", () => {
    window.open("/stage.html", "_blank");
  });
}

// Mobile QR Modal references
const btnMobileQr = document.getElementById("btn-mobile-qr");
const qrModal = document.getElementById("qr-modal");
const qrBackdrop = document.getElementById("qr-backdrop");
if (btnMobileQr && qrModal) {
  btnMobileQr.addEventListener("click", () => qrModal.classList.remove("hidden"));
}
if (qrBackdrop && qrModal) {
  qrBackdrop.addEventListener("click", () => qrModal.classList.add("hidden"));
}

// Subordinate Fleet Dock references
const fleetDock = document.getElementById("fleet-dock");
const fleetDockHeader = document.getElementById("fleet-dock-header");
const fleetDockHeading = document.getElementById("fleet-dock-heading");
const btnFleetDeployAll = document.getElementById("btn-fleet-deploy-all");
const btnFleet = document.getElementById("btn-fleet");

let lastUserLineText = "";
let lastUserLineTime = 0;
let lastJarvisLineText = "";
let lastJarvisLineTime = 0;

function normalizeDialogue(t) {
  return (t || "")
    .toLowerCase()
    .replace(/^\[[a-z0-9_\s-]+\]\s*/i, "")
    .replace(/[^\w\s]/g, "")
    .trim();
}

function addTerminalLine(role, text, isTool = false) {
  if (!terminalFeedEl || !text) return;
  const now = Date.now();
  const norm = normalizeDialogue(text);
  const isUser = role.toLowerCase() === "user";

  if (isUser) {
    if (norm && norm === lastUserLineText && (now - lastUserLineTime) < 3500) {
      return; // Suppress duplicate user line within 3.5s
    }
    lastUserLineText = norm;
    lastUserLineTime = now;
  } else {
    // Suppress duplicate or nested jarvis line within 3.5s
    if (norm && (norm === lastJarvisLineText || (lastJarvisLineText.length > 5 && lastJarvisLineText.includes(norm)) || (norm.length > 5 && norm.includes(lastJarvisLineText))) && (now - lastJarvisLineTime) < 3500) {
      return;
    }
    lastJarvisLineText = norm;
    lastJarvisLineTime = now;
  }

  const line = document.createElement("div");
  line.className = `terminal-line terminal-${role.toLowerCase()}`;
  if (isTool) line.classList.add("terminal-tool");

  const speaker = document.createElement("span");
  speaker.className = "terminal-speaker";
  speaker.textContent = role.toUpperCase() === "USER" ? "YOU:" : "JARVIS:";

  const body = document.createElement("span");
  body.className = "terminal-text";
  body.textContent = text;

  line.appendChild(speaker);
  line.appendChild(body);
  terminalFeedEl.appendChild(line);

  while (terminalFeedEl.children.length > 25) {
    terminalFeedEl.removeChild(terminalFeedEl.firstChild);
  }
  terminalFeedEl.scrollTop = terminalFeedEl.scrollHeight;
}

// Initialize Three.js scene
const scene = createOrbScene(container);

// Gesture Tracker
let tracker = null;
let cameraActive = false;

function showToast(message, duration = 3000) {
  if (!toastEl) return;
  toastEl.textContent = message;
  toastEl.classList.add("visible");
  setTimeout(() => toastEl.classList.remove("visible"), duration);
}

// ——— VOICE STATE INDICATOR ———
function setVoiceState(state) {
  if (!voiceRingEl) return;
  voiceRingEl.setAttribute("data-state", state);
  if (voiceRingLabel) {
    const labels = { idle: "IDLE", listening: "LISTEN", thinking: "THINK", speaking: "SPEAK" };
    voiceRingLabel.textContent = labels[state] || state.toUpperCase();
  }
}

// ——— THEME CYCLING ———
function cycleTheme() {
  const label = scene.cycleTheme();
  if (label && themeBtn) {
    themeBtn.textContent = `THEME [T]: ${label.split("//")[0].trim()}`;
  }
  showToast(`Theme: ${label || "UNKNOWN"}`, 2000);
}

// ——— STARK SOUNDSCAPE & PROCEDURAL SFX ENGINE ———
class JarvisSoundscape {
  constructor() {
    this.ctx = null;
    this.ambientGain = null;
    this.masterGain = null;
    this.enabled = true;
    this.ambientRunning = false;
    this.droneOsc1 = null;
    this.droneOsc2 = null;
  }

  init() {
    if (this.ctx) return;
    try {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) return;
      this.ctx = new AudioContextClass();

      this.masterGain = this.ctx.createGain();
      this.masterGain.gain.setValueAtTime(0.75, this.ctx.currentTime);
      this.masterGain.connect(this.ctx.destination);

      this._startAmbientDrone();
    } catch (e) {
      console.warn("WebAudio initialization notice:", e);
    }
  }

  unlock() {
    if (!this.ctx) {
      this.init();
    } else if (this.ctx.state === "suspended") {
      this.ctx.resume();
    }
  }

  _startAmbientDrone() {
    if (!this.ctx || this.ambientRunning) return;
    try {
      // 55Hz fundamental (A1) + 110Hz warm harmonic (A2)
      this.droneOsc1 = this.ctx.createOscillator();
      this.droneOsc1.type = "sine";
      this.droneOsc1.frequency.setValueAtTime(55.0, this.ctx.currentTime);

      this.droneOsc2 = this.ctx.createOscillator();
      this.droneOsc2.type = "triangle";
      this.droneOsc2.frequency.setValueAtTime(110.0, this.ctx.currentTime);

      const filter = this.ctx.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.setValueAtTime(160, this.ctx.currentTime);
      filter.Q.setValueAtTime(1.8, this.ctx.currentTime);

      this.ambientGain = this.ctx.createGain();
      this.ambientGain.gain.setValueAtTime(0.04, this.ctx.currentTime);

      const osc2Gain = this.ctx.createGain();
      osc2Gain.gain.setValueAtTime(0.35, this.ctx.currentTime);

      this.droneOsc1.connect(filter);
      this.droneOsc2.connect(osc2Gain);
      osc2Gain.connect(filter);

      filter.connect(this.ambientGain);
      this.ambientGain.connect(this.masterGain);

      this.droneOsc1.start();
      this.droneOsc2.start();
      this.ambientRunning = true;
    } catch (e) {
      console.warn("Ambient drone start notice:", e);
    }
  }

  duck(targetGain = 0.005, rampTime = 0.08) {
    if (!this.ambientGain || !this.ctx) return;
    try {
      this.ambientGain.gain.setTargetAtTime(targetGain, this.ctx.currentTime, rampTime);
    } catch (_) {}
  }

  unduck(targetGain = 0.04, rampTime = 0.6) {
    if (!this.ambientGain || !this.ctx || !this.enabled) return;
    try {
      this.ambientGain.gain.setTargetAtTime(targetGain, this.ctx.currentTime, rampTime);
    } catch (_) {}
  }

  setMuted(muted) {
    this.enabled = !muted;
    if (this.masterGain && this.ctx) {
      this.masterGain.gain.setTargetAtTime(this.enabled ? 0.75 : 0.0, this.ctx.currentTime, 0.05);
    }
  }

  playWake() {
    if (!this.enabled) return;
    this.unlock();
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    [880, 1760].forEach((freq, i) => {
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, now);
      const amp = i === 0 ? 0.35 : 0.18;
      gain.gain.setValueAtTime(0.001, now);
      gain.gain.linearRampToValueAtTime(amp, now + 0.008);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.42);
      osc.connect(gain);
      gain.connect(this.masterGain);
      osc.start(now);
      osc.stop(now + 0.45);
    });
  }

  playThinking() {
    if (!this.enabled) return;
    this.unlock();
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    const filter = this.ctx.createBiquadFilter();
    osc.type = "sine";
    osc.frequency.setValueAtTime(130.81, now);
    osc.frequency.exponentialRampToValueAtTime(220.0, now + 0.45);

    filter.type = "bandpass";
    filter.frequency.setValueAtTime(200, now);
    filter.Q.setValueAtTime(3.0, now);

    gain.gain.setValueAtTime(0.001, now);
    gain.gain.linearRampToValueAtTime(0.28, now + 0.15);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.48);

    osc.connect(filter);
    filter.connect(gain);
    gain.connect(this.masterGain);
    osc.start(now);
    osc.stop(now + 0.50);
  }

  playAuthConfirmed() {
    if (!this.enabled) return;
    this.unlock();
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    const notes = [
      { f: 1046.50, t: 0.00, d: 0.10 },
      { f: 1318.51, t: 0.07, d: 0.11 },
      { f: 1567.98, t: 0.14, d: 0.18 }
    ];
    notes.forEach(({ f, t, d }) => {
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(f, now + t);
      gain.gain.setValueAtTime(0.001, now + t);
      gain.gain.linearRampToValueAtTime(0.24, now + t + 0.006);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + t + d);
      osc.connect(gain);
      gain.connect(this.masterGain);
      osc.start(now + t);
      osc.stop(now + t + d);
    });
  }

  playBargeInCut() {
    if (!this.enabled) return;
    this.unlock();
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = "sawtooth";
    osc.frequency.setValueAtTime(1200, now);
    osc.frequency.exponentialRampToValueAtTime(240, now + 0.035);

    gain.gain.setValueAtTime(0.22, now);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.035);

    osc.connect(gain);
    gain.connect(this.masterGain);
    osc.start(now);
    osc.stop(now + 0.04);
  }

  playSecurityAlert() {
    if (!this.enabled) return;
    this.unlock();
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    [0, 0.12, 0.24].forEach((offset) => {
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = "square";
      osc.frequency.setValueAtTime(880, now + offset);
      osc.frequency.setValueAtTime(659.25, now + offset + 0.05);

      gain.gain.setValueAtTime(0.18, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.001, now + offset + 0.09);

      osc.connect(gain);
      gain.connect(this.masterGain);
      osc.start(now + offset);
      osc.stop(now + offset + 0.10);
    });
  }

  playBlueprintWhoosh() {
    if (!this.enabled) return;
    this.unlock();
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    const filter = this.ctx.createBiquadFilter();

    osc.type = "triangle";
    osc.frequency.setValueAtTime(220, now);
    osc.frequency.exponentialRampToValueAtTime(880, now + 0.22);
    osc.frequency.exponentialRampToValueAtTime(330, now + 0.48);

    filter.type = "bandpass";
    filter.frequency.setValueAtTime(600, now);
    filter.frequency.exponentialRampToValueAtTime(1800, now + 0.22);
    filter.frequency.exponentialRampToValueAtTime(500, now + 0.48);
    filter.Q.setValueAtTime(2.5, now);

    gain.gain.setValueAtTime(0.001, now);
    gain.gain.linearRampToValueAtTime(0.28, now + 0.20);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.50);

    osc.connect(filter);
    filter.connect(gain);
    gain.connect(this.masterGain);
    osc.start(now);
    osc.stop(now + 0.52);
  }

  play(sfxName) {
    switch (sfxName) {
      case "wake": this.playWake(); break;
      case "thinking": this.playThinking(); break;
      case "auth_confirmed": this.playAuthConfirmed(); break;
      case "barge_in_cut": this.playBargeInCut(); break;
      case "security_alert": this.playSecurityAlert(); break;
      case "blueprint_whoosh": this.playBlueprintWhoosh(); break;
    }
  }
}

const soundscape = new JarvisSoundscape();

function toggleSoundscape() {
  soundscape.unlock();
  soundscape.setMuted(!soundscape.enabled);
  if (soundscapeBtn) {
    soundscapeBtn.textContent = `SOUNDSCAPE [S]: ${soundscape.enabled ? "ON" : "MUTED"}`;
    soundscapeBtn.className = soundscape.enabled ? "hud-btn btn-active" : "hud-btn";
  }
  showToast(`Soundscape: ${soundscape.enabled ? "ACTIVE" : "MUTED"}`);
}

// Hand Gesture Callbacks
function initTracker() {
  tracker = new HandTracker(videoEl, overlayEl, {
    onRotate: (dt, dp) => scene.rotateBy(dt, dp),
    onZoom: (factor) => scene.zoomBy(factor),
    onTwoHandExpand: (explodeLevel, delta) => {
      scene.setExplodeLevel(explodeLevel);
      if (terminalStatusEl) {
        terminalStatusEl.textContent = `CAD EXPLODE // ${(explodeLevel * 100).toFixed(0)}%`;
      }
    },
    onTwoHandRotate: (deltaAngle) => {
      scene.rotateConstruct?.(deltaAngle);
    },
    onPoint: (screenX, screenY) => {
      scene.setLaserPointer(screenX, screenY, (targeted) => {
        soundscape.play("sub_bass_tick");
        showToast(`🎯 TARGET: ${targeted.name.toUpperCase()}`, 1600);
        if (terminalStatusEl) {
          terminalStatusEl.textContent = `POINTER // ${targeted.name.toUpperCase()} [${targeted.material}]`;
        }
        sendWsMessage({
          type: "GESTURE_ACTION",
          action: "inspect_component",
          component: targeted,
        });
      });
    },
    onPointEnd: () => {
      scene.clearLaserPointer();
    },
    onSwipe: (action) => {
      if (action === "FLICK_RIGHT") {
        soundscape.play("chime_positive");
        scene.triggerBurst();
        showToast("📦 GESTURE: FLICK RIGHT -> SAVING TO VAULT", 3500);
        sendWsMessage({ type: "GESTURE_ACTION", action: "flick_save" });
        scene.dismissConstruct(true);
      } else if (action === "FLICK_LEFT") {
        soundscape.play("whoosh");
        scene.triggerBurst();
        showToast("💥 GESTURE: FLICK LEFT -> DISMISSING CONSTRUCT", 3500);
        sendWsMessage({ type: "GESTURE_ACTION", action: "flick_dismiss" });
        scene.dismissConstruct(false);
      }
    },
    onStatus: (st) => {
      statusModeEl.textContent = st.mode.toUpperCase();
      statusHandsEl.textContent = `${st.hands} HAND${st.hands === 1 ? "" : "S"}`;
      if (st.mode === "spin") {
        statusModeEl.className = "badge badge-active";
      } else if (st.mode === "zoom") {
        statusModeEl.className = "badge badge-zoom";
      } else if (st.mode === "explode") {
        statusModeEl.className = "badge badge-active";
      } else if (st.mode === "pointing") {
        statusModeEl.className = "badge badge-active";
      } else {
        statusModeEl.className = "badge badge-standby";
      }
    },
    onAction: (action) => {
      if (action === "DOUBLE_PINCH") {
        showToast("GESTURE: DOUBLE PINCH -> ACTIVATING JARVIS");
        sendWsMessage({ type: "TRIGGER_ACTION", action: "double_pinch" });
        scene.triggerBurst();
      }
    },
  });
}

let frameRelayTimer = null;
const relayCanvas = document.createElement("canvas");
relayCanvas.width = 640;
relayCanvas.height = 480;

function startBiometricFrameRelay() {
  if (frameRelayTimer) clearInterval(frameRelayTimer);
  frameRelayTimer = setInterval(() => {
    if (!cameraActive || !tracker || !tracker.video || tracker.video.readyState < 2) return;
    try {
      const ctx = relayCanvas.getContext("2d");
      ctx.drawImage(tracker.video, 0, 0, 640, 480);
      const dataUrl = relayCanvas.toDataURL("image/jpeg", 0.65);
      sendWsMessage({ type: "OPTICAL_FRAME", frame: dataUrl });
    } catch (e) {
      console.debug("Optical frame relay error:", e);
    }
  }, 1500);
}

function stopBiometricFrameRelay() {
  if (frameRelayTimer) {
    clearInterval(frameRelayTimer);
    frameRelayTimer = null;
  }
}

async function toggleCamera() {
  if (!tracker) initTracker();

  if (cameraActive) {
    stopBiometricFrameRelay();
    tracker.stop();
    cameraActive = false;
    gestureBtn.textContent = "GESTURES [G]: OFF";
    gestureBtn.classList.remove("btn-active");
    pipContainer.classList.remove("active");
    statusModeEl.textContent = "STANDBY";
    statusHandsEl.textContent = "0 HANDS";
    showToast("Webcam gestures disabled");
    sendWsMessage({ type: "CAMERA_RELEASE" });
  } else {
    gestureBtn.textContent = "GESTURES [G]: ACQUIRING...";
    // 1. Request Python Biometric Sentinel to yield camera hardware
    sendWsMessage({ type: "CAMERA_ACQUIRE" });
    // Allow up to 400ms for OpenCV V4L2 device file descriptor release
    await new Promise((r) => setTimeout(r, 400));

    try {
      await tracker.start();
      cameraActive = true;
      gestureBtn.textContent = "GESTURES [G]: ON";
      gestureBtn.classList.add("btn-active");
      pipContainer.classList.add("active");
      showToast("Webcam gestures active. Pinch to spin, double-pinch to zoom.");
      startBiometricFrameRelay();
    } catch (err) {
      console.error("Camera access failed:", err);
      gestureBtn.textContent = "GESTURES [G]: FAILED";
      showToast("Camera error: " + (err.message || err.name || "Access Denied"));
      sendWsMessage({ type: "CAMERA_RELEASE" });
      setTimeout(() => {
        gestureBtn.textContent = "GESTURES [G]: OFF";
      }, 3000);
    }
  }
}

window.addEventListener("beforeunload", () => {
  if (cameraActive) {
    sendWsMessage({ type: "CAMERA_RELEASE" });
  }
});

// ——— WEB SPEECH API VOICE COMMANDS ———
let speechRecognition = null;
let speechActive = false;
let isJarvisSpeaking = false;
let lastJarvisSpeakEndTime = 0;
let lastJarvisSpokenText = "";

function toggleVoiceCommands() {
  if (speechActive) {
    stopVoiceCommands();
  } else {
    startVoiceCommands();
  }
}

function startVoiceCommands() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    showToast("Speech Recognition not supported in this browser", 4000);
    return;
  }

  if (speechRecognition) {
    try { speechRecognition.stop(); } catch (e) {}
  }

  speechRecognition = new SpeechRecognition();
  speechRecognition.continuous = true;
  speechRecognition.interimResults = true;
  speechRecognition.lang = "en-US";

  const speechBadge = document.getElementById("speech-status");

  speechRecognition.onresult = (event) => {
    const now = Date.now();
    // Acoustic Echo Gate: drop any speech captured while Jarvis is actively speaking or during 750ms reverb window
    if (isJarvisSpeaking || (now - lastJarvisSpeakEndTime < 750)) {
      return;
    }

    for (let i = event.resultIndex; i < event.results.length; i++) {
      const res = event.results[i];
      const rawText = res[0].transcript.trim();
      if (res.isFinal) {
        // Self-echo filter: check if recognized transcript mirrors Jarvis's recent words
        const cleanT = rawText.toLowerCase().replace(/[^\w\s]/g, " ").trim();
        if (lastJarvisSpokenText && (now - lastJarvisSpeakEndTime < 3500) && cleanT.length > 5) {
          if (lastJarvisSpokenText.includes(cleanT) || cleanT.includes(lastJarvisSpokenText)) {
            console.log("🎙️ [Acoustic Echo Gate] Dropped self-hearing transcript:", rawText);
            return;
          }
          const wordsT = new Set(cleanT.split(/\s+/).filter(w => w.length > 2));
          const wordsJ = new Set(lastJarvisSpokenText.split(/\s+/).filter(w => w.length > 2));
          if (wordsT.size >= 2 && wordsJ.size >= 2) {
            let intersect = 0;
            for (const w of wordsT) {
              if (wordsJ.has(w)) intersect++;
            }
            if (intersect / wordsT.size >= 0.6) {
              console.log("🎙️ [Acoustic Echo Gate] Dropped echo overlap:", rawText);
              return;
            }
          }
        }

        setVoiceState("thinking");
        if (speechBadge) {
          speechBadge.textContent = "VOICE: PROCESSING";
          speechBadge.className = "badge badge-active";
        }
        handleVoiceCommand(rawText.toLowerCase());
      } else {
        // Interim speech feedback
        setVoiceState("listening");
        if (speechBadge) {
          speechBadge.textContent = "VOICE: HEARING YOU";
          speechBadge.className = "badge badge-active";
        }
        showToast(`🎙 "${rawText}"...`, 1200);
      }
    }
  };

  speechRecognition.onerror = (event) => {
    if (event.error !== "no-speech" && event.error !== "aborted") {
      console.warn("Speech error:", event.error);
    }
  };

  speechRecognition.onend = () => {
    // Seamless auto-restart for continuous hands-free operation
    if (speechActive) {
      setTimeout(() => {
        if (speechActive) {
          try {
            speechRecognition.start();
            setVoiceState("idle");
            if (speechBadge) {
              speechBadge.textContent = "VOICE: HANDS-FREE";
              speechBadge.className = "badge badge-active";
            }
          } catch (e) { /* already started */ }
        }
      }, 200);
    }
  };

  try {
    speechRecognition.start();
    speechActive = true;
    if (voiceBtn) {
      voiceBtn.textContent = "HANDS-FREE [V]: ON";
      voiceBtn.classList.add("btn-active");
    }
    if (speechBadge) {
      speechBadge.textContent = "VOICE: HANDS-FREE";
      speechBadge.className = "badge badge-active";
    }
    showToast("⚡ Hands-free voice listening active — speak anytime", 3500);
  } catch (err) {
    console.warn("Speech start note:", err.message);
  }
}

function stopVoiceCommands() {
  speechActive = false;
  if (speechRecognition) {
    try { speechRecognition.stop(); } catch (e) {}
    speechRecognition = null;
  }
  const speechBadge = document.getElementById("speech-status");
  if (speechBadge) {
    speechBadge.textContent = "VOICE: MUTED";
    speechBadge.className = "badge badge-standby";
  }
  if (voiceBtn) {
    voiceBtn.textContent = "HANDS-FREE [V]: OFF";
    voiceBtn.classList.remove("btn-active");
  }
  setVoiceState("idle");
  showToast("Voice listening paused (press V to resume)");
}

function handleVoiceCommand(rawTranscript) {
  const now = Date.now();
  if (isJarvisSpeaking || (now - lastJarvisSpeakEndTime < 650)) {
    console.log("🎙️ [Acoustic Echo Gate] Suppressed command during TTS window:", rawTranscript);
    return;
  }
  let transcript = (rawTranscript || "").trim().toLowerCase();

  // Strip wake word prefixes if user said "Hey Jarvis", "Jarvis", "Please", etc.
  transcript = transcript
    .replace(/^(hey|ok|okay|hello|hi)?\s*jarvis[,.\s]*/i, "")
    .replace(/^please[,.\s]*/i, "")
    .trim();
  if (!transcript) transcript = (rawTranscript || "").toLowerCase();

  showToast(`🎙 "${transcript}"`, 3000);
  scene.triggerBurst();
  addTerminalLine("user", transcript);

  // Wake Up Jarvis voice trigger check (instant local HUD feedback)
  if (transcript.includes("wake up") || transcript.includes("wakeup")) {
    soundscape.play("wake");
    scene.triggerBurst();
    sendWsMessage({ type: "VOICE_COMMAND", transcript: "wake up jarvis" });
    showToast("J.A.R.V.I.S. Online", 2500);
    return;
  }

  // Local commands (handled in browser)
  if (transcript.includes("reset view") || transcript.includes("reset")) {
    scene.resetView();
    showToast("View Reset", 2000);
    return;
  }

  // Barehands Board Catch-All (handles phonetic variations like 'bear hands', 'bear hands more', etc.)
  if (transcript.includes("barehand") || transcript.includes("bare hand") || transcript.includes("bear hand") || transcript.includes("barehands") || transcript.includes("bear hands")) {
    sendWsMessage({ type: "VOICE_COMMAND", transcript: "open barehands board" });
    showToast("Opening Barehands Board...", 2500);
    return;
  }

  // Webcam Gestures Voice Routing (handles 'gesture mode', 'on the gestures mode', 'justice mode', etc.)
  if (transcript.includes("gesture") || transcript.includes("gestures") || transcript.includes("justice mode") || transcript.includes("hand track")) {
    const isDisable = transcript.includes("off") || transcript.includes("disable") || transcript.includes("stop") || transcript.includes("close");
    if (isDisable && cameraRunning) {
      toggleCamera();
      showToast("Webcam gestures disabled", 2000);
    } else if (!isDisable && !cameraRunning) {
      toggleCamera();
      showToast("Webcam gestures activated", 2500);
    } else {
      showToast(`Gestures are already ${cameraRunning ? 'active' : 'off'}`, 2000);
    }
    sendWsMessage({ type: "VOICE_COMMAND", transcript });
    return;
  }

  // Flexible HUD Theme Routing
  if (transcript.includes("theme") || transcript.includes("reactor theme") || transcript.includes("crimson protocol")) {
    if (transcript.includes("arc") || transcript.includes("cyan") || transcript.includes("blue") || transcript.includes("reactor")) {
      const label = scene.setColorTheme("arc");
      if (themeBtn) themeBtn.textContent = "THEME [T]: ARC";
      showToast(`Theme: ${label}`, 2000);
      sendWsMessage({ type: "THEME_CHANGE", theme: "arc" });
      sendWsMessage({ type: "VOICE_COMMAND", transcript: "arc theme" });
      return;
    }
    if (transcript.includes("crimson") || transcript.includes("red") || transcript.includes("mark")) {
      const label = scene.setColorTheme("crimson");
      if (themeBtn) themeBtn.textContent = "THEME [T]: CRIMSON";
      showToast(`Theme: ${label}`, 2000);
      sendWsMessage({ type: "THEME_CHANGE", theme: "crimson" });
      sendWsMessage({ type: "VOICE_COMMAND", transcript: "crimson theme" });
      return;
    }
    if (transcript.includes("ultron") || transcript.includes("gold") || transcript.includes("amber") || transcript.includes("yellow")) {
      const label = scene.setColorTheme("ultron");
      if (themeBtn) themeBtn.textContent = "THEME [T]: ULTRON";
      showToast(`Theme: ${label}`, 2000);
      sendWsMessage({ type: "THEME_CHANGE", theme: "ultron" });
      sendWsMessage({ type: "VOICE_COMMAND", transcript: "ultron theme" });
      return;
    }
    cycleTheme();
    return;
  }

  // Forward to Python backend via WebSocket (opens Barehands, Memory Vault, ChatGPT, etc.)
  sendWsMessage({ type: "VOICE_COMMAND", transcript });
}

// ——— WEBSOCKET TO PYTHON BACKEND ———
let ws = null;
let wsReconnectTimer = null;

let currentPlayingAudio = null;
let pulseAnimFrame = null;

if ('speechSynthesis' in window) {
  window.speechSynthesis.onvoiceschanged = () => {
    window.speechSynthesis.getVoices();
  };
}

function stopActiveSpeech() {
  if (currentPlayingAudio) {
    try {
      currentPlayingAudio.pause();
      currentPlayingAudio.currentTime = 0;
    } catch (e) {}
    currentPlayingAudio = null;
  }
  if ('speechSynthesis' in window) {
    try { window.speechSynthesis.cancel(); } catch (e) {}
  }
  if (pulseAnimFrame) {
    cancelAnimationFrame(pulseAnimFrame);
    pulseAnimFrame = null;
  }
  if (typeof scene !== "undefined" && scene) {
    scene.setSpeaking(false);
    scene.setAudioLevel(0);
  }
  setVoiceState("idle");
}

let globalAudioCtx = null;
function ensureAudioContext() {
  try {
    if (!globalAudioCtx) {
      const AudioCtxClass = window.AudioContext || window.webkitAudioContext;
      if (AudioCtxClass) globalAudioCtx = new AudioCtxClass();
    }
    if (globalAudioCtx && globalAudioCtx.state === "suspended") {
      globalAudioCtx.resume().catch(() => {});
    }
  } catch (e) {}
  return globalAudioCtx;
}
window.addEventListener("click", ensureAudioContext, { passive: true });
window.addEventListener("keydown", ensureAudioContext, { passive: true });
window.addEventListener("touchstart", ensureAudioContext, { passive: true });

let cachedBrowserVoices = [];
function updateBrowserVoices() {
  if ('speechSynthesis' in window) {
    cachedBrowserVoices = window.speechSynthesis.getVoices() || [];
  }
}
if ('speechSynthesis' in window) {
  updateBrowserVoices();
  window.speechSynthesis.onvoiceschanged = updateBrowserVoices;
}

function startOrbPulseAnimation(getAudioLevelFn) {
  if (pulseAnimFrame) cancelAnimationFrame(pulseAnimFrame);
  function loop() {
    const level = getAudioLevelFn ? getAudioLevelFn() : (0.35 + 0.25 * Math.sin(performance.now() * 0.009) * Math.cos(performance.now() * 0.013));
    if (typeof scene !== "undefined" && scene) {
      scene.setSpeaking(true);
      scene.setAudioLevel(level);
      if (!getAudioLevelFn) {
        // Feed synthetic holographic waveform oscillations so 3D rings visibly ripple & pulse
        const now = performance.now() * 0.015;
        const syntheticSamples = [];
        for (let i = 0; i < 64; i++) {
          syntheticSamples.push(Math.sin(now + i * 0.45) * level);
        }
        scene.feedWaveform(syntheticSamples);
      }
    }
    setVoiceState("speaking");
    pulseAnimFrame = requestAnimationFrame(loop);
  }
  pulseAnimFrame = requestAnimationFrame(loop);
}

function playAudioWithOrbPulsing(audioBase64, fallbackText) {
  stopActiveSpeech();
  try {
    ensureAudioContext();
    const audio = new Audio("data:audio/mp3;base64," + audioBase64);
    currentPlayingAudio = audio;

    let analyser = null;
    let dataArray = null;
    try {
      const actx = ensureAudioContext();
      if (actx) {
        const src = actx.createMediaElementSource(audio);
        analyser = actx.createAnalyser();
        analyser.fftSize = 64;
        dataArray = new Uint8Array(analyser.frequencyBinCount);
        src.connect(analyser);
        analyser.connect(actx.destination);
      }
    } catch (e) {
      console.debug("Web Audio Analyser setup notice:", e);
    }

    audio.onplay = () => {
      startOrbPulseAnimation(() => {
        if (analyser && dataArray) {
          analyser.getByteTimeDomainData(dataArray);
          let sum = 0;
          const samples = [];
          for (let i = 0; i < dataArray.length; i++) {
            const v = (dataArray[i] - 128) / 128.0;
            samples.push(v);
            sum += Math.abs(v);
          }
          const rms = sum / dataArray.length;
          if (typeof scene !== "undefined" && scene) {
            scene.feedWaveform(samples);
            scene.setAudioLevel(Math.min(1.0, rms * 4.0));
          }
          return Math.min(1.0, rms * 3.8);
        }
        return 0.38 + 0.28 * Math.sin(performance.now() * 0.009);
      });
      if (soundscape) soundscape.duck();
      const spBadge = document.getElementById("speech-status");
      if (spBadge) {
        spBadge.textContent = "VOICE: TRANSMITTING";
        spBadge.className = "badge badge-active";
      }
    };

    audio.onended = () => {
      stopActiveSpeech();
      if (soundscape) soundscape.unduck();
      const spBadge = document.getElementById("speech-status");
      if (spBadge) {
        spBadge.textContent = "VOICE: READY";
        spBadge.className = "badge badge-standby";
      }
    };

    audio.onerror = (err) => {
      console.warn("Neural audio play error; falling back to British male browser TTS:", err);
      stopActiveSpeech();
      if (fallbackText) speakTextBrowser(fallbackText);
    };

    const playPromise = audio.play();
    if (playPromise !== undefined) {
      playPromise.catch(err => {
        console.warn("Audio autoplay blocked by browser policy:", err);
        stopActiveSpeech();
        if (fallbackText) speakTextBrowser(fallbackText);
      });
    }
  } catch (err) {
    console.warn("Could not initialize audio element:", err);
    if (fallbackText) speakTextBrowser(fallbackText);
  }
}

function speakTextBrowser(text) {
  if (!text || !('speechSynthesis' in window)) return;
  stopActiveSpeech();
  try {
    const utterance = new SpeechSynthesisUtterance(text);
    const voices = cachedBrowserVoices.length > 0 ? cachedBrowserVoices : (window.speechSynthesis.getVoices() || []);
    
    // Strictly filter for male voices — exclude any female/woman voice
    const isMale = (v) => {
      const n = (v.name || "").toLowerCase();
      return (n.includes("male") || n.includes("george") || n.includes("daniel") || n.includes("oliver") || n.includes("rishi") || n.includes("guy") || n.includes("james") || n.includes("brian") || n.includes("arthur") || n.includes("david") || n.includes("ryan") || n.includes("thomas"))
             && !n.includes("female") && !n.includes("woman") && !n.includes("girl") && !n.includes("samantha") && !n.includes("victoria") && !n.includes("zira");
    };

    let selectedVoice = voices.find(v => (v.lang.includes("en-GB") || v.lang.includes("en_GB")) && isMale(v))
                     || voices.find(v => (v.lang.includes("en-GB") || v.lang.includes("en_GB")) && !v.name.toLowerCase().includes("female"))
                     || voices.find(v => (v.lang.includes("en-US") || v.lang.includes("en_US")) && isMale(v))
                     || voices.find(v => v.lang.startsWith("en") && isMale(v));

    if (selectedVoice) {
      utterance.voice = selectedVoice;
    }
    utterance.lang = "en-GB";

    // Set pitch to 0.75 for deep, refined British masculine Tony Stark presence
    utterance.pitch = 0.75;
    utterance.rate = 1.02;

    utterance.onstart = () => {
      startOrbPulseAnimation();
      if (soundscape) soundscape.duck();
      const spBadge = document.getElementById("speech-status");
      if (spBadge) {
        spBadge.textContent = "VOICE: TRANSMITTING";
        spBadge.className = "badge badge-active";
      }
    };

    utterance.onend = () => {
      stopActiveSpeech();
      if (soundscape) soundscape.unduck();
      const spBadge = document.getElementById("speech-status");
      if (spBadge) {
        spBadge.textContent = "VOICE: READY";
        spBadge.className = "badge badge-standby";
      }
    };

    utterance.onerror = () => {
      stopActiveSpeech();
    };

    window.speechSynthesis.speak(utterance);
  } catch (e) {
    console.debug("Browser speech error:", e);
  }
}

function sendWsMessage(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  } else {
    // Resilient Cloud HTTP fallback (e.g. Render deployments)
    const textCmd = msg.text || msg.transcript || "";
    if (textCmd && (msg.type === "VOICE_COMMAND" || msg.type === "TEXT_COMMAND")) {
      const termStatus = document.getElementById("terminal-status");
      if (termStatus) termStatus.textContent = "NEURAL // REASONING";
      fetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(msg)
      })
      .then(r => r.json())
      .then(data => {
        if (data.events && Array.isArray(data.events)) {
          data.events.forEach(handleServerEvent);
        } else if (data.response) {
          handleServerEvent({ type: "SUBTITLE", role: "jarvis", text: data.response });
        }
        if (data.audio_base64) {
          playAudioWithOrbPulsing(data.audio_base64, data.response);
        } else if (data.response && !currentPlayingAudio) {
          speakTextBrowser(data.response);
        }
      })
      .catch(err => {
        console.warn("API Command fallback notice:", err);
        const termStatus = document.getElementById("terminal-status");
        if (termStatus) termStatus.textContent = "STANDBY";
      });
    }
  }
}

function connectWebSocket() {
  const isHttps = window.location.protocol === "https:";
  const wsProto = isHttps ? "wss:" : "ws:";
  const host = window.location.hostname || "localhost";
  const isLocal = host === "localhost" || host === "127.0.0.1";
  const wsUrl = isLocal ? `ws://${host}:8765` : `${wsProto}//${window.location.host}/ws`;

  try {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      wsStatusEl.textContent = "CONNECTED";
      wsStatusEl.className = "badge badge-connected";
      showToast("Jarvis Core Connected", 2000);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleServerEvent(data);
      } catch (e) {
        console.error("Invalid WS message:", e);
      }
    };

    ws.onclose = () => {
      wsStatusEl.textContent = "STANDALONE";
      wsStatusEl.className = "badge badge-standby";
      clearTimeout(wsReconnectTimer);
      wsReconnectTimer = setTimeout(connectWebSocket, 5000);
    };

    ws.onerror = () => {
      ws.close();
    };
  } catch (err) {
    wsStatusEl.textContent = "STANDALONE";
    wsStatusEl.className = "badge badge-standby";
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(connectWebSocket, 5000);
  }
}

function handleServerEvent(data) {
  switch (data.type) {
    case "ACTIVATED":
      scene.triggerBurst();
      soundscape.play("wake");
      showToast(`⚡ ${data.reason.toUpperCase()} — JARVIS ONLINE`, 4000);
      const orbBadge = document.getElementById("system-status");
      if (orbBadge) {
        orbBadge.textContent = "ONLINE // ACTIVE";
        orbBadge.className = "badge badge-active";
      }
      break;

    case "SFX_PLAY":
      if (data.sfx) {
        soundscape.play(data.sfx);
      }
      break;

    case "SFX_MUTE":
      soundscape.setMuted(data.muted);
      if (soundscapeBtn) {
        soundscapeBtn.textContent = `SOUNDSCAPE [S]: ${soundscape.enabled ? "ON" : "MUTED"}`;
        soundscapeBtn.className = soundscape.enabled ? "hud-btn btn-active" : "hud-btn";
      }
      break;

    case "SPEAKING":
      isJarvisSpeaking = !!data.active;
      if (!data.active) {
        lastJarvisSpeakEndTime = Date.now();
      }
      scene.setSpeaking(data.active);
      setVoiceState(data.active ? "speaking" : "idle");
      if (data.active) {
        soundscape.duck();
      } else {
        soundscape.unduck();
      }
      const speechBadge = document.getElementById("speech-status");
      if (speechBadge) {
        speechBadge.textContent = data.active ? "VOICE: TRANSMITTING" : "VOICE: READY";
        speechBadge.className = data.active ? "badge badge-active" : "badge badge-standby";
      }
      break;

    case "AUDIO_LEVEL":
      scene.setAudioLevel(data.rms);
      if (data.waveform) {
        scene.feedWaveform(data.waveform);
      }
      if (audioMeterBar) {
        const pct = Math.min(100, Math.round(data.rms * 300));
        audioMeterBar.style.width = `${pct}%`;
      }
      break;

    case "VOICE_STATE":
      setVoiceState(data.state || "idle");
      if (data.state === "listening" || data.state === "speaking" || data.state === "thinking") {
        soundscape.duck();
      } else {
        soundscape.unduck();
      }
      break;

    case "VOICE_WAVEFORM":
      if (data.samples) {
        scene.feedWaveform(data.samples);
      }
      break;

    case "TOGGLE_GESTURES":
      if (data.action === "enable" && !cameraRunning) {
        toggleCamera();
      } else if (data.action === "disable" && cameraRunning) {
        toggleCamera();
      } else if (!data.action) {
        toggleCamera();
      }
      break;

    case "EXTERNAL_CAMERA_ACQUIRED":
      if (cameraActive) {
        stopBiometricFrameRelay();
        tracker.stop();
        cameraActive = false;
        gestureBtn.textContent = "GESTURES [G]: OFF";
        gestureBtn.classList.remove("btn-active");
        pipContainer.classList.remove("active");
        statusModeEl.textContent = "STANDBY";
        showToast("Webcam yielded to Barehands engineering board", 3000);
      }
      break;

    case "THEME_CHANGE":
      if (data.theme) {
        const label = scene.setColorTheme(data.theme);
        if (label && themeBtn) {
          themeBtn.textContent = `THEME [T]: ${label.split("//")[0].trim()}`;
        }
        showToast(`Theme: ${label}`, 2000);
      }
      break;

    case "STATUS":
      if (data.status && terminalStatusEl) {
        terminalStatusEl.textContent = data.status;
      }
      if (data.phrase) {
        const phraseEl = document.getElementById("welcome-phrase-display");
        if (phraseEl) phraseEl.textContent = `"${data.phrase}"`;
      }
      break;

    case "SYSTEM_TELEMETRY":
      if (vitalsCpuEl) vitalsCpuEl.textContent = `CPU: ${data.cpu_load || 0}`;
      if (vitalsRamEl) vitalsRamEl.textContent = `RAM: ${data.ram_pct || 0}%`;
      if (brainBadgeEl && data.model) brainBadgeEl.textContent = data.model.toUpperCase();
      break;

    case "PERSONA_UPDATED":
      updatePersonaUI(data);
      break;

    case "ROAST_DELIVERED":
      showToast(`🔥 STARK ROAST EXECUTED (${data.wit || 95}% Wit)`, 3500);
      if (personaBadge) {
        personaBadge.textContent = `🍸 WIT: ${data.wit || 95}% | UNFILTERED ROAST`;
        personaBadge.className = "badge badge-persona-unfiltered";
      }
      if (soundscape) soundscape.play("whoosh");
      break;

    case "SPEAKER_MATCH":
      const spkBadge = document.getElementById("speaker-badge");
      if (spkBadge) {
        const spkName = (data.speaker || "Vasim").toUpperCase();
        spkBadge.textContent = `👤 ${spkName} (${data.confidence_pct || 97}%)`;
        spkBadge.className = data.is_admin ? "badge badge-persona-stark" : "badge badge-standby";
      }
      break;

    case "ACOUSTIC_SCENE":
      const acBadge = document.getElementById("acoustic-badge");
      if (acBadge) {
        const shortScene = (data.scene || "QUIET").replace("_", " ").split(" ")[0];
        acBadge.textContent = `🎙️ ${data.decibels || 34}dB | ${shortScene}`;
      }
      break;

    case "FLEET_UPDATE":
      updateFleetStatusUI(data);
      break;

    case "FLEET_TASK_UPDATE":
      updateFleetBotTaskUI(data);
      break;

    case "SUBTITLE":
      if (data.role === "jarvis" && data.text) {
        lastJarvisSpokenText = (data.text || "").toLowerCase().replace(/[^\w\s]/g, " ").trim();
        if (!currentPlayingAudio && (ws && ws.readyState === WebSocket.OPEN) && (window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1")) {
          speakTextBrowser(data.text);
        }
      }
      addTerminalLine(data.role || "jarvis", data.text || "");
      if (terminalStatusEl) {
        if (data.role === "user") {
          terminalStatusEl.textContent = "USER // SPEAKING";
        } else if (data.latency_ms) {
          terminalStatusEl.textContent = `JARVIS // ${data.latency_ms}ms TTFT // ${data.total_ms || "?"}ms TOTAL`;
        } else {
          terminalStatusEl.textContent = "JARVIS // TRANSMITTING";
        }
      }
      break;

    case "MEMORY_UPDATE":
      showToast(`📝 Memory: ${data.note || "Updated"}`, 2500);
      scene.triggerBurst();
      addTerminalLine("jarvis", `Memory Vault updated: ${data.note}`, true);
      break;

    case "HUMAN_EXPERIENCE_UPDATED":
      showToast(`🧠 Human Insight: ${data.topic || "Cognitive Pattern Acquired"}`, 3500);
      scene.triggerBurst();
      soundscape.play("sub_bass_tick");
      addTerminalLine("jarvis", `🧠 [HUMAN COGNITION] ${data.topic || "Research"}: ${data.summary || ""}`, true);
      break;

    case "NAVIGATE":
      if (data.url) {
        showToast(`Navigating to ${data.label || "board"}...`, 2000);
        if (data.url.includes("stage.html")) {
          openBarehandsStage(data.construct || null);
        } else {
          window.open(data.url, data.target || "_blank");
        }
      }
      break;

    case "OPEN_BAREHANDS":
      openBarehandsStage(data.construct || null);
      break;

    case "PROACTIVE_INTERJECTION":
      scene.triggerBurst();
      showToast(`⚠️ [WATCHDOG ${data.category ? data.category.toUpperCase() : 'ALERT'}]: ${data.phrase || ''}`, 5000);
      addTerminalLine("jarvis", `[DIAGNOSTIC] ${data.phrase || ''}`, true);
      if (terminalStatusEl) {
        terminalStatusEl.textContent = `WATCHDOG // ${data.category ? data.category.toUpperCase() : 'ALERT'}`;
      }
      break;

    case "VISION_SCAN_START":
      scene.triggerBurst();
      soundscape.play("thinking");
      showToast("🔍 OPTICAL SCAN // ACQUIRING TARGET", 4000);
      if (terminalStatusEl) {
        terminalStatusEl.textContent = "SCANNING // OBJECT ANALYSIS";
      }
      container?.classList.add("vision-scanning");
      setTimeout(() => container?.classList.remove("vision-scanning"), 8000);
      break;

    case "VISION_SCAN_RESULT":
      container?.classList.remove("vision-scanning");
      scene.triggerBurst();
      showToast(`✅ SCAN COMPLETE: ${(data.analysis || '').slice(0, 75)}...`, 5000);
      addTerminalLine("jarvis", `[OPTICAL SCAN] ${data.analysis || ''}`, true);
      if (terminalStatusEl) {
        terminalStatusEl.textContent = `VISION // ${(data.backend || 'ANALYZED').toUpperCase()}`;
      }
      break;

    case "RENDER_3D_BLUEPRINT":
    case "DYNAMIC_CONSTRUCT":
      scene.loadConstruct(data.manifest || null);
      if (data.exploded) {
        scene.setExplodeLevel(1.5);
      } else {
        scene.setExplodeLevel(0.0);
      }
      soundscape.play("blueprint_whoosh");
      scene.triggerBurst();
      showToast(`📐 3D HOLOGRAM: ${data.construct ? data.construct.toUpperCase() : "BLUEPRINT ACTIVE"}`, 4000);
      if (terminalStatusEl) {
        terminalStatusEl.textContent = `HOLOGRAM // ${data.construct ? data.construct.toUpperCase() : "3D CAD ACTIVE"}`;
      }
      break;

    case "DISMISS_CONSTRUCT":
      scene.dismissConstruct(false);
      soundscape.play("whoosh");
      showToast("💥 HOLOGRAM DISMISSED", 2500);
      break;

    case "FACE_ENROLLMENT_START":
      showEnrollmentModalUI(data.admin_name || "Admin");
      soundscape.play("blueprint_whoosh");
      showToast("📷 BIOMETRIC PROTOCOL // ENROLLMENT ACTIVE", 3500);
      break;

    case "FACE_ENROLLMENT_PROGRESS":
      updateEnrollmentProgressUI(data.percentage || 0, data.stage || "CALIBRATING", data.frames || 0);
      soundscape.play("sub_bass_tick");
      break;

    case "FACE_ENROLLMENT_COMPLETE":
      finishEnrollmentModalUI(data.admin_name || "Admin");
      break;

    case "FACE_ENROLLMENT_CANCELLED":
      closeEnrollmentModal(false);
      showToast("Biometric enrollment cancelled", 2000);
      break;

    case "UI_MUTATION":
      handleUIMutation(data);
      break;
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// INSTANT VOICE-DRIVEN DYNAMIC UI MUTATION ENGINE
// ═══════════════════════════════════════════════════════════════════════════
function getUIMutationTargetElement(target) {
  if (!target) return null;
  const t = target.toLowerCase().trim();
  const targetMap = {
    "subtitles": "#cyber-terminal",
    "subtitle": "#cyber-terminal",
    "terminal": "#cyber-terminal",
    "chat": "#cyber-terminal",
    "history": "#cyber-terminal",
    "fleet": "#fleet-dock",
    "fleet_dock": "#fleet-dock",
    "bots": "#fleet-dock",
    "header": ".hud-header",
    "top_bar": ".hud-header",
    "topbar": ".hud-header",
    "status_panel": ".status-panel",
    "voice_ring": "#voice-ring",
    "ring": "#voice-ring",
    "audio_meter": ".audio-meter-container",
    "meter": ".audio-meter-container",
    "scanlines": ".overlay-scanlines",
    "vignette": ".vignette-overlay",
    "grain": ".overlay-grain",
    "reticle": ".reticle-container",
    "orb": "#canvas-container",
  };
  return targetMap[t] ? document.querySelector(targetMap[t]) : document.querySelector(target);
}

function setUIColorPalette(color) {
  if (!color) return;
  const c = color.toLowerCase().trim();
  const root = document.documentElement;

  const palettes = {
    "emerald": { primary: "#00e676", glow: "rgba(0, 230, 118, 0.45)", border: "rgba(0, 230, 118, 0.35)", cyan: "#00e676", cyanGlow: "rgba(0, 230, 118, 0.4)", theme: "emerald" },
    "green": { primary: "#00e676", glow: "rgba(0, 230, 118, 0.45)", border: "rgba(0, 230, 118, 0.35)", cyan: "#00e676", cyanGlow: "rgba(0, 230, 118, 0.4)", theme: "emerald" },
    "purple": { primary: "#d500f9", glow: "rgba(213, 0, 249, 0.45)", border: "rgba(213, 0, 249, 0.35)", cyan: "#e040fb", cyanGlow: "rgba(224, 64, 251, 0.4)", theme: "neon_purple" },
    "violet": { primary: "#d500f9", glow: "rgba(213, 0, 249, 0.45)", border: "rgba(213, 0, 249, 0.35)", cyan: "#e040fb", cyanGlow: "rgba(224, 64, 251, 0.4)", theme: "neon_purple" },
    "magenta": { primary: "#e040fb", glow: "rgba(224, 64, 251, 0.45)", border: "rgba(224, 64, 251, 0.35)", cyan: "#ff4081", cyanGlow: "rgba(255, 64, 129, 0.4)", theme: "neon_purple" },
    "red": { primary: "#ff1744", glow: "rgba(255, 23, 68, 0.45)", border: "rgba(255, 23, 68, 0.35)", cyan: "#ff5252", cyanGlow: "rgba(255, 82, 82, 0.4)", theme: "crimson" },
    "crimson": { primary: "#ff1744", glow: "rgba(255, 23, 68, 0.45)", border: "rgba(255, 23, 68, 0.35)", cyan: "#ff5252", cyanGlow: "rgba(255, 82, 82, 0.4)", theme: "crimson" },
    "cyan": { primary: "#00e5ff", glow: "rgba(0, 229, 255, 0.45)", border: "rgba(0, 229, 255, 0.35)", cyan: "#00b0ff", cyanGlow: "rgba(0, 176, 255, 0.4)", theme: "arc" },
    "blue": { primary: "#00b0ff", glow: "rgba(0, 176, 255, 0.45)", border: "rgba(0, 176, 255, 0.35)", cyan: "#00e5ff", cyanGlow: "rgba(0, 229, 255, 0.4)", theme: "arc" },
    "amber": { primary: "#ffaa30", glow: "rgba(255, 170, 48, 0.45)", border: "rgba(255, 170, 48, 0.35)", cyan: "#00e5ff", cyanGlow: "rgba(0, 229, 255, 0.4)", theme: "ultron" },
    "gold": { primary: "#ffd700", glow: "rgba(255, 215, 0, 0.45)", border: "rgba(255, 215, 0, 0.35)", cyan: "#ffaa30", cyanGlow: "rgba(255, 170, 48, 0.4)", theme: "ultron" },
    "orange": { primary: "#ff9100", glow: "rgba(255, 145, 0, 0.45)", border: "rgba(255, 145, 0, 0.35)", cyan: "#ffab40", cyanGlow: "rgba(255, 171, 64, 0.4)", theme: "ultron" },
    "white": { primary: "#f5f5f5", glow: "rgba(245, 245, 245, 0.45)", border: "rgba(245, 245, 245, 0.35)", cyan: "#80d8ff", cyanGlow: "rgba(128, 216, 255, 0.4)", theme: "arc" }
  };

  const p = palettes[c] || {
    primary: c.startsWith("#") ? c : "#00e5ff",
    glow: c.startsWith("#") ? `${c}77` : "rgba(0, 229, 255, 0.45)",
    border: c.startsWith("#") ? `${c}55` : "rgba(0, 229, 255, 0.35)",
    cyan: c.startsWith("#") ? c : "#00e5ff",
    cyanGlow: "rgba(0, 229, 255, 0.4)",
    theme: "arc"
  };

  root.style.setProperty("--color-primary", p.primary);
  root.style.setProperty("--color-primary-glow", p.glow);
  root.style.setProperty("--color-border", p.border);
  root.style.setProperty("--color-cyan", p.cyan);
  root.style.setProperty("--color-cyan-glow", p.cyanGlow);

  if (scene && scene.setColorTheme) {
    scene.setColorTheme(p.theme);
  }
  showToast(`UI Color Palette: ${c.toUpperCase()}`, 2500);
}

function repositionElement(el, pos) {
  if (!el) return;
  const p = (pos || "right").toLowerCase().trim();
  el.style.transition = "all 0.4s cubic-bezier(0.16, 1, 0.3, 1)";

  if (p === "right" || p === "bottom-right") {
    el.style.left = "auto";
    el.style.right = "28px";
    el.style.bottom = "100px";
    el.style.top = "auto";
    el.style.transform = "none";
  } else if (p === "left" || p === "bottom-left") {
    el.style.left = "28px";
    el.style.right = "auto";
    el.style.bottom = "100px";
    el.style.top = "auto";
    el.style.transform = "none";
  } else if (p === "top-right") {
    el.style.left = "auto";
    el.style.right = "28px";
    el.style.top = "84px";
    el.style.bottom = "auto";
    el.style.transform = "none";
  } else if (p === "top-left") {
    el.style.left = "28px";
    el.style.right = "auto";
    el.style.top = "84px";
    el.style.bottom = "auto";
    el.style.transform = "none";
  } else if (p === "top" || p === "center-top") {
    el.style.left = "50%";
    el.style.transform = "translateX(-50%)";
    el.style.top = "84px";
    el.style.bottom = "auto";
    el.style.right = "auto";
  } else if (p === "center" || p === "middle") {
    el.style.left = "50%";
    el.style.top = "50%";
    el.style.transform = "translate(-50%, -50%)";
    el.style.bottom = "auto";
    el.style.right = "auto";
  } else if (p === "bottom" || p === "center-bottom") {
    el.style.left = "50%";
    el.style.transform = "translateX(-50%)";
    el.style.bottom = "100px";
    el.style.top = "auto";
    el.style.right = "auto";
  }
}

function addModularWidget(widgetType, data = {}) {
  const w = (widgetType || "").toLowerCase().trim();
  const id = `widget-${w.replace(/[^a-z0-9_]/g, "_")}`;
  const existing = document.getElementById(id);
  if (existing) {
    existing.style.display = "";
    showToast(`Widget ${w.toUpperCase()} active`, 2000);
    return;
  }

  const container = document.createElement("div");
  container.id = id;
  container.className = "hud-modular-widget";

  if (w === "digital_clock" || w === "clock" || w === "time") {
    container.style.cssText = "position:fixed; top:84px; left:32px; z-index:45; background:rgba(10,14,24,0.78); border:1px solid var(--color-primary); border-radius:8px; padding:10px 18px; font-family:var(--font-mono); box-shadow:0 0 20px var(--color-primary-glow); backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px);";
    container.innerHTML = `
      <div style="font-size:9px; letter-spacing:2px; color:var(--color-primary); font-weight:700;">CHRONO // SYSTEM CLOCK</div>
      <div id="${id}-time" style="font-size:22px; font-weight:800; color:#fff; letter-spacing:1px; margin-top:2px;">--:--:--</div>
      <div id="${id}-date" style="font-size:10px; color:rgba(255,255,255,0.6); letter-spacing:1px; margin-top:2px;">---- -- ----</div>
    `;
    document.body.appendChild(container);

    function updateClock() {
      const timeEl = document.getElementById(`${id}-time`);
      const dateEl = document.getElementById(`${id}-date`);
      if (!timeEl) return;
      const now = new Date();
      timeEl.textContent = now.toLocaleTimeString();
      dateEl.textContent = now.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }).toUpperCase();
    }
    updateClock();
    setInterval(updateClock, 1000);
    showToast("Digital Chrono Widget Added", 2500);

  } else if (w === "cpu_gauge" || w === "vitals" || w === "gauge") {
    container.style.cssText = "position:fixed; bottom:290px; left:28px; z-index:45; width:220px; background:rgba(10,14,24,0.78); border:1px solid var(--color-primary); border-radius:8px; padding:10px 14px; font-family:var(--font-mono); box-shadow:0 0 20px var(--color-primary-glow); backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px);";
    container.innerHTML = `
      <div style="font-size:9px; letter-spacing:1.5px; color:var(--color-primary); font-weight:700;">TELEMETRY SPEEDOMETER</div>
      <div style="display:flex; justify-content:space-between; margin-top:8px; font-size:10.5px;"><span>CPU THREADS</span><span id="${id}-cpu" style="color:var(--color-cyan); font-weight:700;">NOMINAL</span></div>
      <div style="height:5px; background:rgba(255,255,255,0.1); border-radius:3px; overflow:hidden; margin-top:4px;"><div id="${id}-cpu-bar" style="height:100%; width:35%; background:linear-gradient(90deg, var(--color-cyan), var(--color-primary)); transition:width 0.3s ease;"></div></div>
      <div style="display:flex; justify-content:space-between; margin-top:8px; font-size:10.5px;"><span>MEMORY CORE</span><span id="${id}-ram" style="color:var(--color-cyan); font-weight:700;">STABLE</span></div>
      <div style="height:5px; background:rgba(255,255,255,0.1); border-radius:3px; overflow:hidden; margin-top:4px;"><div id="${id}-ram-bar" style="height:100%; width:48%; background:linear-gradient(90deg, var(--color-cyan), var(--color-primary)); transition:width 0.3s ease;"></div></div>
    `;
    document.body.appendChild(container);
    showToast("Telemetry Gauge Widget Added", 2500);

  } else {
    const title = data.title || "HOLOGRAPHIC CARD";
    const text = data.text || data.value || "Telemetry link active.";
    container.style.cssText = "position:fixed; top:120px; left:32px; z-index:45; max-width:260px; background:rgba(10,14,24,0.78); border:1px solid var(--color-primary); border-radius:8px; padding:10px 16px; font-family:var(--font-mono); box-shadow:0 0 20px var(--color-primary-glow); backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px);";
    container.innerHTML = `
      <div style="font-size:9px; letter-spacing:1.5px; color:var(--color-primary); font-weight:700;">${title.toUpperCase()}</div>
      <div style="font-size:12px; color:#fff; margin-top:4px; line-height:1.4;">${text}</div>
    `;
    document.body.appendChild(container);
    showToast(`Widget ${title} Added`, 2500);
  }

  if (soundscape) soundscape.play("click");
}

function handleUIMutation(data) {
  const action = (data.action || "style").toLowerCase().trim();
  const target = (data.target || "").toLowerCase().trim();
  const el = getUIMutationTargetElement(target);

  if (action === "hide" || action === "remove") {
    if (target === "clock" || target === "digital_clock" || target === "cpu_gauge" || target === "vitals") {
      const wEl = document.getElementById(`widget-${target}`);
      if (wEl) wEl.remove();
      showToast(`Removed widget: ${target}`, 2000);
      return;
    }
    if (el) {
      el.style.display = "none";
      if (soundscape) soundscape.play("whoosh");
      showToast(`UI Element Hidden: ${target.toUpperCase()}`, 2000);
      saveMutation({ action: "hide", target });
    }
  } else if (action === "show") {
    if (el) {
      el.style.display = "";
      if (soundscape) soundscape.play("wake");
      showToast(`UI Element Restored: ${target.toUpperCase()}`, 2000);
      saveMutation({ action: "show", target });
    }
  } else if (action === "add") {
    const widget = data.widget || target || "digital_clock";
    addModularWidget(widget, data);
    saveMutation({ action: "add", widget, data });
  } else if (action === "color" || action === "theme_color") {
    setUIColorPalette(data.color || data.value);
    saveMutation({ action: "color", color: data.color || data.value });
  } else if (action === "style") {
    if (data.color) {
      setUIColorPalette(data.color);
      saveMutation({ action: "color", color: data.color });
    } else if (el && data.property && data.value) {
      el.style[data.property] = data.value;
      saveMutation({ action: "style", target, property: data.property, value: data.value });
      showToast(`Modified ${target} ${data.property}`, 2000);
    }
  } else if (action === "reposition" || action === "move") {
    if (el) {
      repositionElement(el, data.position || "right");
      if (soundscape) soundscape.play("whoosh");
      showToast(`Moved ${target.toUpperCase()} to ${data.position || "new position"}`, 2000);
      saveMutation({ action: "reposition", target, position: data.position });
    }
  } else if (action === "orb_scale") {
    const scale = parseFloat(data.scale || 1.0);
    if (scene && scene.setScale) {
      scene.setScale(scale);
      showToast(`Orb Scale: ${scale}x`, 2000);
      if (soundscape) soundscape.play("whoosh");
      saveMutation({ action: "orb_scale", scale });
    }
  } else if (action === "reset") {
    resetAllUIMutations();
  }
}

function saveMutation(mut) {
  try {
    const saved = JSON.parse(localStorage.getItem("jarvis_ui_mutations") || "[]");
    saved.push(mut);
    localStorage.setItem("jarvis_ui_mutations", JSON.stringify(saved));
  } catch (e) {}
}

function loadSavedUIMutations() {
  try {
    const saved = JSON.parse(localStorage.getItem("jarvis_ui_mutations") || "[]");
    saved.forEach(mut => {
      try {
        handleUIMutation(mut);
      } catch (err) {}
    });
  } catch (e) {}
}

function resetAllUIMutations() {
  try {
    localStorage.removeItem("jarvis_ui_mutations");
  } catch (e) {}

  document.querySelectorAll(".hud-modular-widget").forEach(w => w.remove());
  ["#cyber-terminal", "#fleet-dock", ".hud-header", "#voice-ring", ".audio-meter-container", ".overlay-scanlines", ".vignette-overlay"].forEach(sel => {
    const el = document.querySelector(sel);
    if (el) {
      el.style.display = "";
      el.style.left = "";
      el.style.right = "";
      el.style.top = "";
      el.style.bottom = "";
      el.style.transform = "";
    }
  });

  const root = document.documentElement;
  root.style.removeProperty("--color-primary");
  root.style.removeProperty("--color-primary-glow");
  root.style.removeProperty("--color-border");
  root.style.removeProperty("--color-cyan");
  root.style.removeProperty("--color-cyan-glow");

  if (scene && scene.setScale) scene.setScale(1.0);
  if (scene && scene.setColorTheme) scene.setColorTheme("ultron");

  showToast("Restored Default Stark HUD Layout", 3000);
  if (soundscape) soundscape.play("wake");
}

// ——— LOCAL WEB AUDIO API FALLBACK ———
let localMicContext = null;

async function initLocalMic() {
  if (localMicContext) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    localMicContext = new (window.AudioContext || window.webkitAudioContext)();
    const source = localMicContext.createMediaStreamSource(stream);
    const analyser = localMicContext.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);

    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    function checkAudio() {
      requestAnimationFrame(checkAudio);
      analyser.getByteFrequencyData(dataArray);
      let sum = 0;
      for (let i = 0; i < bufferLength; i++) {
        sum += dataArray[i];
      }
      const avg = sum / bufferLength / 255;
      scene.setAudioLevel(avg);
      if (audioMeterBar) {
        audioMeterBar.style.width = `${Math.min(100, Math.round(avg * 140))}%`;
      }
    }
    checkAudio();
    showToast("Microphone audio visualizer linked", 2500);
  } catch (err) {
    console.log("Local mic visualizer optional (using backend audio):", err.message);
  }
}

// ——— HOLOGRAPHIC SILENT TYPING COMMAND MODAL ———
const cmdModal = document.getElementById("cmd-modal");
const cmdInput = document.getElementById("cmd-input");
const cmdBackdrop = document.getElementById("cmd-backdrop");
const cmdSubmitBtn = document.getElementById("btn-cmd-submit");
const cmdTriggerBtn = document.getElementById("btn-cmd");

function openCmdModal() {
  if (!cmdModal || !cmdInput) return;
  cmdModal.classList.remove("hidden");
  cmdModal.style.display = "flex";
  cmdModal.style.opacity = "1";
  cmdModal.style.visibility = "visible";
  cmdModal.style.pointerEvents = "auto";
  setTimeout(() => {
    cmdInput.focus();
    cmdInput.select();
  }, 50);
}

function closeCmdModal() {
  if (!cmdModal) return;
  cmdModal.classList.add("hidden");
  cmdModal.style.display = "none";
  cmdModal.style.opacity = "0";
  cmdModal.style.visibility = "hidden";
  cmdModal.style.pointerEvents = "none";
  if (cmdInput) cmdInput.blur();
}

function submitCmd() {
  if (!cmdInput) return;
  const text = cmdInput.value.trim();
  if (!text) {
    closeCmdModal();
    return;
  }
  closeCmdModal();
  cmdInput.value = "";
  addTerminalLine("user", text);
  showToast(`⌨ "${text}"`, 3000);
  soundscape.play("thinking");
  scene.triggerBurst();
  sendWsMessage({ type: "TEXT_COMMAND", text });
}

cmdTriggerBtn?.addEventListener("click", openCmdModal);
cmdBackdrop?.addEventListener("click", closeCmdModal);
cmdSubmitBtn?.addEventListener("click", submitCmd);

cmdInput?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    submitCmd();
  } else if (e.key === "Escape") {
    e.preventDefault();
    closeCmdModal();
  }
});

// ——— BIOMETRIC ADMIN FACE ENROLLMENT MODAL ———
const enrollModal = document.getElementById("face-enrollment-modal");
const enrollBackdrop = document.getElementById("enroll-backdrop");
const enrollCloseBtn = document.getElementById("btn-enroll-cancel");
const enrollTriggerBtn = document.getElementById("btn-enroll");
const enrollProgressBar = document.getElementById("enroll-progress-bar");
const enrollPctText = document.getElementById("enroll-pct-text");
const enrollStageLabel = document.getElementById("enroll-stage-label");
const enrollStatusBadge = document.getElementById("enroll-status-badge");
const enrollGuidanceText = document.getElementById("enroll-guidance-text");
let fastEnrollTimer = null;

function showEnrollmentModalUI(adminName = "Admin") {
  if (!enrollModal) return;
  enrollModal.classList.remove("hidden");
  enrollModal.style.display = "flex";
  enrollModal.style.opacity = "1";
  enrollModal.style.visibility = "visible";
  enrollModal.style.pointerEvents = "auto";

  if (enrollProgressBar) enrollProgressBar.style.width = "0%";
  if (enrollPctText) enrollPctText.textContent = "0%";
  if (enrollStageLabel) enrollStageLabel.textContent = "OPTICAL CALIBRATION INITIATED";
  if (enrollStatusBadge) {
    enrollStatusBadge.textContent = "CALIBRATING...";
    enrollStatusBadge.style.color = "#00e5ff";
    enrollStatusBadge.style.borderColor = "var(--color-cyan)";
  }
  if (enrollGuidanceText) {
    enrollGuidanceText.textContent = `Center face within the oval reticle. Maintain eye contact while J.A.R.V.I.S. registers 3D neural topography for ${adminName}.`;
  }
  startFastEnrollmentRelay();
}

function updateEnrollmentProgressUI(pct, stage, frames) {
  if (!enrollModal || enrollModal.classList.contains("hidden")) {
    showEnrollmentModalUI();
  }
  if (enrollProgressBar) enrollProgressBar.style.width = `${pct}%`;
  if (enrollPctText) enrollPctText.textContent = `${pct}%`;
  if (enrollStageLabel) enrollStageLabel.textContent = (stage || "CALIBRATING").toUpperCase();
  if (enrollStatusBadge) enrollStatusBadge.textContent = `CAPTURING // ${pct}% [${frames || 0}/30]`;
}

function finishEnrollmentModalUI(adminName = "Admin") {
  if (enrollProgressBar) enrollProgressBar.style.width = "100%";
  if (enrollPctText) enrollPctText.textContent = "100%";
  if (enrollStageLabel) enrollStageLabel.textContent = "ADMIN PROFILE CANONICALIZED & COMMITTED";
  if (enrollStatusBadge) {
    enrollStatusBadge.textContent = "AUTHENTICATED // REGISTERED";
    enrollStatusBadge.style.color = "#00e676";
    enrollStatusBadge.style.borderColor = "#00e676";
  }
  if (enrollGuidanceText) {
    enrollGuidanceText.textContent = `Success. Biometric profile for ${adminName} is permanently enrolled. All security clearances granted.`;
  }
  soundscape.play("chime_positive");
  scene.triggerBurst();
  showToast(`✅ ADMIN BIOMETRIC ENROLLED: ${adminName.toUpperCase()}`, 5000);
  stopFastEnrollmentRelay();
  setTimeout(() => {
    closeEnrollmentModal(false);
  }, 2500);
}

function startFaceEnrollment() {
  showEnrollmentModalUI();
  sendWsMessage({ type: "START_FACE_ENROLLMENT", admin_name: "Admin" });
  soundscape.play("blueprint_whoosh");
}

function closeEnrollmentModal(notifyBackend = true) {
  if (!enrollModal) return;
  enrollModal.classList.add("hidden");
  enrollModal.style.display = "none";
  enrollModal.style.opacity = "0";
  enrollModal.style.visibility = "hidden";
  enrollModal.style.pointerEvents = "none";
  stopFastEnrollmentRelay();
  if (notifyBackend) {
    sendWsMessage({ type: "CANCEL_FACE_ENROLLMENT" });
  }
}

function startFastEnrollmentRelay() {
  if (fastEnrollTimer) clearInterval(fastEnrollTimer);
  if (!cameraActive) return;
  fastEnrollTimer = setInterval(() => {
    if (!cameraActive || !tracker || !tracker.video || tracker.video.readyState < 2) return;
    try {
      const ctx = relayCanvas.getContext("2d");
      ctx.drawImage(tracker.video, 0, 0, 640, 480);
      const dataUrl = relayCanvas.toDataURL("image/jpeg", 0.65);
      sendWsMessage({ type: "OPTICAL_FRAME", frame: dataUrl });
    } catch (e) {
      console.debug("Fast optical frame relay error:", e);
    }
  }, 120);
}

function stopFastEnrollmentRelay() {
  if (fastEnrollTimer) {
    clearInterval(fastEnrollTimer);
    fastEnrollTimer = null;
  }
}

enrollTriggerBtn?.addEventListener("click", startFaceEnrollment);
enrollCloseBtn?.addEventListener("click", () => closeEnrollmentModal(true));
enrollBackdrop?.addEventListener("click", () => closeEnrollmentModal(true));

// ——— DYNAMIC PERSONA & WIT CALIBRATION SYSTEM ———
let currentPersonaMode = "stark_lab";
let currentWitLevel = 75;

function openPersonaModal() {
  if (!personaModal) return;
  personaModal.classList.remove("hidden");
  personaModal.style.display = "flex";
  personaModal.style.opacity = "1";
  personaModal.style.visibility = "visible";
  personaModal.style.pointerEvents = "auto";
  soundscape?.play("whoosh");
}

function closePersonaModal() {
  if (!personaModal) return;
  personaModal.classList.add("hidden");
  personaModal.style.display = "none";
  personaModal.style.opacity = "0";
  personaModal.style.visibility = "hidden";
  personaModal.style.pointerEvents = "none";
}

function togglePersonaModal() {
  if (!personaModal) return;
  if (personaModal.classList.contains("hidden") || personaModal.style.display === "none") {
    openPersonaModal();
  } else {
    closePersonaModal();
  }
}

function getWitDescription(wit) {
  if (wit < 20) return "Zero small talk. Combat brevity & military-grade situational awareness.";
  if (wit < 50) return "First-principles physics, mathematical precision, and analytical rigor.";
  if (wit < 85) return "Sophisticated British poise, intellectual peer to Tony Stark, subtle dry irony.";
  return "Full theatrical British sarcasm, sharp tongue, playful skepticism, and humorous roasts.";
}

function updatePersonaUI(data) {
  if (!data) return;
  const mode = data.mode || "stark_lab";
  const wit = typeof data.wit_level === "number" ? data.wit_level : 75;
  const name = data.name || "Stark Lab";
  const icon = data.icon || "🔬";
  const color = data.color || "#00e5ff";
  const badgeClass = data.badge_class || `badge-persona-${mode}`;

  currentPersonaMode = mode;
  currentWitLevel = wit;

  // Update header badge
  if (personaBadge) {
    personaBadge.textContent = `${icon} WIT: ${wit}% | ${name.toUpperCase()}`;
    personaBadge.className = `badge ${badgeClass}`;
  }

  // Update footer button
  if (personaBtn) {
    personaBtn.textContent = `PERSONA [P]: ${name.toUpperCase()} (${wit}%)`;
    personaBtn.style.borderColor = color;
    personaBtn.style.color = color;
  }

  // Update modal preset card active state
  personaCards?.forEach(card => {
    if (card.getAttribute("data-mode") === mode) {
      card.classList.add("active");
    } else {
      card.classList.remove("active");
    }
  });

  // Update modal slider & readouts
  if (personaWitSlider) {
    personaWitSlider.value = wit;
  }
  if (personaWitValue) {
    personaWitValue.textContent = `${wit}%`;
    personaWitValue.style.color = color;
    personaWitValue.style.textShadow = `0 0 10px ${color}`;
  }
  if (personaWitDesc) {
    personaWitDesc.textContent = getWitDescription(wit);
  }

  showToast(`🎭 Persona: ${name.toUpperCase()} (${wit}% Wit)`, 2500);
}

function sendPersonaCalibration(mode, witLevel) {
  sendWsMessage({
    type: "CALIBRATE_PERSONA",
    mode: mode || currentPersonaMode,
    wit_level: typeof witLevel === "number" ? witLevel : currentWitLevel
  });
  soundscape?.play("sub_bass_tick");
}

personaStatusItem?.addEventListener("click", togglePersonaModal);
personaBtn?.addEventListener("click", togglePersonaModal);
personaBackdrop?.addEventListener("click", closePersonaModal);
personaBtnApply?.addEventListener("click", () => {
  sendPersonaCalibration(currentPersonaMode, currentWitLevel);
  closePersonaModal();
});
personaBtnReset?.addEventListener("click", () => {
  sendPersonaCalibration("stark_lab", 75);
});

personaCards?.forEach(card => {
  card.addEventListener("click", () => {
    const mode = card.getAttribute("data-mode");
    const defaultWit = parseInt(card.getAttribute("data-wit") || "75", 10);
    currentPersonaMode = mode;
    currentWitLevel = defaultWit;
    sendPersonaCalibration(mode, defaultWit);
  });
});

personaWitSlider?.addEventListener("input", (e) => {
  const val = parseInt(e.target.value, 10);
  currentWitLevel = val;
  if (personaWitValue) personaWitValue.textContent = `${val}%`;
  if (personaWitDesc) personaWitDesc.textContent = getWitDescription(val);
  
  personaCards?.forEach(card => {
    const cMode = card.getAttribute("data-mode");
    if ((val < 20 && cMode === "tactical") ||
        (val >= 20 && val < 50 && cMode === "engineering") ||
        (val >= 50 && val < 85 && cMode === "stark_lab") ||
        (val >= 85 && cMode === "unfiltered")) {
      card.classList.add("active");
      currentPersonaMode = cMode;
    } else {
      card.classList.remove("active");
    }
  });
});

personaWitSlider?.addEventListener("change", (e) => {
  const val = parseInt(e.target.value, 10);
  sendPersonaCalibration(currentPersonaMode, val);
});

// ── Subordinate Fleet UI Functions ──
function toggleFleetDock() {
  if (!fleetDock) return;
  fleetDock.classList.toggle("minimized");
  const isMin = fleetDock.classList.contains("minimized");
  showToast(isMin ? "Subordinate Fleet Bay Minimized" : "Subordinate Fleet Bay Expanded", 2000);
}

function deployAllFleetBots() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "DISPATCH_PARALLEL_FLEET", assignments: [] }));
    scene.triggerBurst();
    soundscape.play("whoosh");
    showToast("⚡ Subordinate Fleet Deployed in Parallel", 3000);
    ["dum_e", "friday", "edith", "veronica"].forEach((id) => {
      const pod = document.getElementById(`pod-${id}`);
      const badge = document.getElementById(`badge-${id}`);
      if (pod) pod.classList.add("working");
      if (badge) badge.textContent = "WORKING";
    });
  } else {
    showToast("WebSocket link offline", 2000);
  }
}

function dispatchSingleBot(botId, task) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "DISPATCH_FLEET_TASK", bot_id: botId, task: task }));
    scene.triggerBurst();
    soundscape.play("sub_bass_tick");
    const pod = document.getElementById(`pod-${botId}`);
    const badge = document.getElementById(`badge-${botId}`);
    const ticker = document.getElementById(`ticker-${botId}`);
    if (pod) pod.classList.add("working");
    if (badge) badge.textContent = "WORKING";
    if (ticker) ticker.textContent = `Executing: ${task}...`;
    showToast(`🤖 Deploying ${botId.toUpperCase()}...`, 2000);
  }
}

function updateFleetStatusUI(data) {
  const fleet = data.fleet;
  if (!fleet || !fleet.bots) return;

  let workingCount = 0;
  Object.entries(fleet.bots).forEach(([bId, bot]) => {
    const pod = document.getElementById(`pod-${bId}`);
    const badge = document.getElementById(`badge-${bId}`);
    const ticker = document.getElementById(`ticker-${bId}`);

    const isWorking = bot.status === "WORKING";
    if (isWorking) workingCount++;

    if (pod) {
      if (isWorking) pod.classList.add("working");
      else pod.classList.remove("working");
    }

    if (badge) {
      badge.textContent = bot.status || "STANDBY";
    }

    if (ticker) {
      if (isWorking && bot.active_task) {
        ticker.textContent = `Active: ${bot.active_task}`;
      } else if (bot.last_result && bot.last_result.summary) {
        ticker.textContent = bot.last_result.summary;
      } else if (bot.last_task) {
        ticker.textContent = bot.last_task;
      }
    }
  });

  if (fleetDockHeading) {
    fleetDockHeading.textContent = workingCount > 0 ? `SUBORDINATE FLEET // ${workingCount} ACTIVE` : `SUBORDINATE FLEET // 4 READY`;
  }
  if (btnFleet) {
    btnFleet.textContent = workingCount > 0 ? `FLEET [B]: ${workingCount} ACTIVE` : `FLEET [B]: 4 READY`;
  }
}

function updateFleetBotTaskUI(data) {
  const bId = data.bot_id;
  const pod = document.getElementById(`pod-${bId}`);
  const badge = document.getElementById(`badge-${bId}`);
  const ticker = document.getElementById(`ticker-${bId}`);

  const isWorking = data.status === "WORKING";
  if (pod) {
    if (isWorking) pod.classList.add("working");
    else pod.classList.remove("working");
  }
  if (badge) {
    badge.textContent = data.status || "STANDBY";
  }
  if (ticker) {
    if (isWorking) {
      ticker.textContent = `Executing: ${data.task}...`;
    } else if (data.result && data.result.summary) {
      ticker.textContent = data.result.summary;
    }
  }

  if (data.status === "SUCCESS") {
    scene.triggerBurst();
    soundscape.play("sub_bass_tick");
    const botName = data.result?.name || bId.toUpperCase();
    showToast(`✅ ${botName} completed assignment (${data.duration_s}s)`, 3000);
    addTerminalLine("jarvis", `[${botName}] ${data.result?.summary || 'Task completed.'}`, true);
  }
}

// Subordinate Fleet Click Listeners
fleetDockHeader?.addEventListener("click", toggleFleetDock);
btnFleetDeployAll?.addEventListener("click", (e) => {
  e.stopPropagation();
  deployAllFleetBots();
});
btnFleet?.addEventListener("click", () => {
  deployAllFleetBots();
});

document.querySelectorAll(".pod-run-btn").forEach((btn) => {
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const botId = btn.getAttribute("data-bot");
    const task = btn.getAttribute("data-task") || "Diagnostic sweep";
    if (botId) dispatchSingleBot(botId, task);
  });
});

// Button Events
gestureBtn?.addEventListener("click", toggleCamera);
themeBtn?.addEventListener("click", cycleTheme);
soundscapeBtn?.addEventListener("click", toggleSoundscape);
voiceBtn?.addEventListener("click", toggleVoiceCommands);
resetBtn?.addEventListener("click", () => {
  scene.resetView();
  showToast("View Reset");
});
fullscreenBtn?.addEventListener("click", () => {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen();
  } else {
    document.exitFullscreen();
  }
});

// Interactive bottom-left shortcut legend items
document.querySelectorAll(".shortcut-item").forEach((item) => {
  item.addEventListener("click", () => {
    const sc = item.getAttribute("data-shortcut");
    if (sc === "cmd") openCmdModal();
    else if (sc === "p") togglePersonaModal();
    else if (sc === "g") toggleCamera();
    else if (sc === "e") startFaceEnrollment();
    else if (sc === "t") cycleTheme();
    else if (sc === "s") toggleSoundscape();
    else if (sc === "v") toggleVoiceCommands();
    else if (sc === "r") {
      scene.resetView();
      showToast("View Reset");
    } else if (sc === "zoom-in") scene.zoomIn();
    else if (sc === "zoom-out") scene.zoomOut();
    else if (sc === "f") {
      if (!document.fullscreenElement) document.documentElement.requestFullscreen();
      else document.exitFullscreen();
    } else if (sc === "b") toggleFleetDock();
    else if (sc === "m") initLocalMic();
  });
});

// Keyboard controls
window.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") {
    if (e.key === "Escape") {
      closeCmdModal();
      closeEnrollmentModal(true);
      closePersonaModal();
    }
    return;
  }
  const key = e.key.toLowerCase();

  if (e.key === "Escape") {
    closeCmdModal();
    closeEnrollmentModal(true);
    closePersonaModal();
    return;
  }

  if (key === "p") {
    togglePersonaModal();
    return;
  }

  if (e.key === "Enter" || e.key === "/" || key === "c") {
    e.preventDefault();
    openCmdModal();
    return;
  }

  if (key === "e") {
    startFaceEnrollment();
    return;
  }

  if (key === "x") {
    scene.toggleExplode();
    soundscape.play("sub_bass_tick");
    showToast(`CAD Explode: ${(scene.getExplodeLevel() * 100).toFixed(0)}%`);
    return;
  }

  if (key === "g") {
    toggleCamera();
  } else if (key === "t") {
    cycleTheme();
  } else if (key === "s") {
    toggleSoundscape();
  } else if (key === "v") {
    toggleVoiceCommands();
  } else if (key === "r") {
    scene.resetView();
    showToast("View Reset");
  } else if (key === "+" || key === "=") {
    scene.zoomIn();
  } else if (key === "-" || key === "_") {
    scene.zoomOut();
  } else if (key === "f") {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen();
    } else {
      document.exitFullscreen();
    }
  } else if (key === "m") {
    initLocalMic();
  } else if (key === "b") {
    toggleFleetDock();
  } else if (key === "delete" || key === "backspace") {
    scene.dismissConstruct(false);
    soundscape.play("whoosh");
    showToast("💥 Hologram Dismissed");
  }
});

// Start
loadSavedUIMutations();
connectWebSocket();
showToast("JARVIS Holographic HUD Initialized", 3000);

// Auto-start hands-free voice listening
setTimeout(() => {
  startVoiceCommands();
}, 400);

// If browser security policy requires user gesture for audio & microphone, auto-unlock on first interaction
window.addEventListener("pointerdown", () => {
  soundscape.unlock();
  if (!speechActive) startVoiceCommands();
}, { once: true });
window.addEventListener("keydown", () => {
  soundscape.unlock();
  if (!speechActive) startVoiceCommands();
}, { once: true });

