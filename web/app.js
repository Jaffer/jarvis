import { createOrbScene } from "./orbScene.js";
import { HandTracker } from "./handTracker.js";

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

function addTerminalLine(role, text, isTool = false) {
  if (!terminalFeedEl || !text) return;
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

// Hand Gesture Callbacks
function initTracker() {
  tracker = new HandTracker(videoEl, overlayEl, {
    onRotate: (dt, dp) => scene.rotateBy(dt, dp),
    onZoom: (factor) => scene.zoomBy(factor),
    onStatus: (st) => {
      statusModeEl.textContent = st.mode.toUpperCase();
      statusHandsEl.textContent = `${st.hands} HAND${st.hands === 1 ? "" : "S"}`;
      if (st.mode === "spin") {
        statusModeEl.className = "badge badge-active";
      } else if (st.mode === "zoom") {
        statusModeEl.className = "badge badge-zoom";
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

async function toggleCamera() {
  if (!tracker) initTracker();

  if (cameraActive) {
    tracker.stop();
    cameraActive = false;
    gestureBtn.textContent = "GESTURES [G]: OFF";
    gestureBtn.classList.remove("btn-active");
    pipContainer.classList.remove("active");
    statusModeEl.textContent = "STANDBY";
    statusHandsEl.textContent = "0 HANDS";
    showToast("Webcam gestures disabled");
  } else {
    gestureBtn.textContent = "GESTURES [G]: STARTING...";
    try {
      await tracker.start();
      cameraActive = true;
      gestureBtn.textContent = "GESTURES [G]: ON";
      gestureBtn.classList.add("btn-active");
      pipContainer.classList.add("active");
      showToast("Webcam gestures active. Pinch to spin, double-pinch to zoom.");
    } catch (err) {
      console.error("Camera access failed:", err);
      gestureBtn.textContent = "GESTURES [G]: FAILED";
      showToast("Camera error: " + err.message);
      setTimeout(() => {
        gestureBtn.textContent = "GESTURES [G]: OFF";
      }, 3000);
    }
  }
}

// ——— WEB SPEECH API VOICE COMMANDS ———
let speechRecognition = null;
let speechActive = false;

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
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const res = event.results[i];
      const rawText = res[0].transcript.trim();
      if (res.isFinal) {
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

  // Local commands (handled in browser)
  if (transcript.includes("reset view") || transcript.includes("reset")) {
    scene.resetView();
    showToast("View Reset", 2000);
    return;
  }
  if (transcript.includes("switch theme") || transcript.includes("change theme") || transcript.includes("next theme") || transcript.includes("cycle theme")) {
    cycleTheme();
    return;
  }
  if (transcript.includes("ultron theme") || transcript.includes("gold theme")) {
    const label = scene.setColorTheme("ultron");
    if (themeBtn) themeBtn.textContent = "THEME [T]: ULTRON";
    showToast(`Theme: ${label}`, 2000);
    return;
  }
  if (transcript.includes("arc theme") || transcript.includes("cyan theme")) {
    const label = scene.setColorTheme("arc");
    if (themeBtn) themeBtn.textContent = "THEME [T]: ARC";
    showToast(`Theme: ${label}`, 2000);
    return;
  }
  if (transcript.includes("crimson theme") || transcript.includes("red theme")) {
    const label = scene.setColorTheme("crimson");
    if (themeBtn) themeBtn.textContent = "THEME [T]: CRIMSON";
    showToast(`Theme: ${label}`, 2000);
    return;
  }

  // Forward to Python backend via WebSocket (opens Barehands, Memory Vault, ChatGPT, etc.)
  sendWsMessage({ type: "VOICE_COMMAND", transcript });
}

// ——— WEBSOCKET TO PYTHON BACKEND ———
let ws = null;
let wsReconnectTimer = null;

function sendWsMessage(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  }
}

function connectWebSocket() {
  const host = window.location.hostname || "localhost";
  const port = 8765;
  const wsUrl = `ws://${host}:${port}`;

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
      wsReconnectTimer = setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  } catch (err) {
    wsStatusEl.textContent = "STANDALONE";
    wsStatusEl.className = "badge badge-standby";
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(connectWebSocket, 4000);
  }
}

function handleServerEvent(data) {
  switch (data.type) {
    case "ACTIVATED":
      scene.triggerBurst();
      showToast(`⚡ ${data.reason.toUpperCase()} — JARVIS ONLINE`, 4000);
      const orbBadge = document.getElementById("system-status");
      if (orbBadge) {
        orbBadge.textContent = "ONLINE // ACTIVE";
        orbBadge.className = "badge badge-active";
      }
      break;

    case "SPEAKING":
      scene.setSpeaking(data.active);
      setVoiceState(data.active ? "speaking" : "idle");
      const speechBadge = document.getElementById("speech-status");
      if (speechBadge) {
        speechBadge.textContent = data.active ? "VOICE: TRANSMITTING" : "VOICE: READY";
        speechBadge.className = data.active ? "badge badge-active" : "badge badge-standby";
      }
      break;

    case "AUDIO_LEVEL":
      scene.setAudioLevel(data.rms);
      if (audioMeterBar) {
        const pct = Math.min(100, Math.round(data.rms * 300));
        audioMeterBar.style.width = `${pct}%`;
      }
      break;

    case "VOICE_STATE":
      setVoiceState(data.state || "idle");
      break;

    case "VOICE_WAVEFORM":
      if (data.samples) {
        scene.feedWaveform(data.samples);
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

    case "SUBTITLE":
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

    case "NAVIGATE":
      if (data.url) {
        showToast(`Navigating to ${data.label || "board"}...`, 2000);
        window.open(data.url, "_blank");
      }
      break;
  }
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

// Button Events
gestureBtn?.addEventListener("click", toggleCamera);
themeBtn?.addEventListener("click", cycleTheme);
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
    if (sc === "g") toggleCamera();
    else if (sc === "t") cycleTheme();
    else if (sc === "v") toggleVoiceCommands();
    else if (sc === "r") {
      scene.resetView();
      showToast("View Reset");
    } else if (sc === "zoom-in") scene.zoomIn();
    else if (sc === "zoom-out") scene.zoomOut();
    else if (sc === "f") {
      if (!document.fullscreenElement) document.documentElement.requestFullscreen();
      else document.exitFullscreen();
    } else if (sc === "m") initLocalMic();
  });
});

// Keyboard controls
window.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  const key = e.key.toLowerCase();

  if (key === "g") {
    toggleCamera();
  } else if (key === "t") {
    cycleTheme();
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
  }
});

// Start
connectWebSocket();
showToast("JARVIS Holographic HUD Initialized", 3000);

// Auto-start hands-free voice listening
setTimeout(() => {
  startVoiceCommands();
}, 400);

// If browser security policy requires user gesture for microphone, auto-start on first interaction
window.addEventListener("pointerdown", () => {
  if (!speechActive) startVoiceCommands();
}, { once: true });
window.addEventListener("keydown", () => {
  if (!speechActive) startVoiceCommands();
}, { once: true });

