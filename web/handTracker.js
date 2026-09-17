import { FilesetResolver, HandLandmarker } from "@mediapipe/tasks-vision";

const WASM_CDN = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/wasm";
const MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

// Key landmark indices
const WRIST = 0;
const THUMB_CMC = 1, THUMB_MCP = 2, THUMB_IP = 3, THUMB_TIP = 4;
const INDEX_MCP = 5, INDEX_PIP = 6, INDEX_DIP = 7, INDEX_TIP = 8;
const MIDDLE_MCP = 9, MIDDLE_PIP = 10, MIDDLE_DIP = 11, MIDDLE_TIP = 12;
const RING_MCP = 13, RING_PIP = 14, RING_DIP = 15, RING_TIP = 16;
const PINKY_MCP = 17, PINKY_PIP = 18, PINKY_DIP = 19, PINKY_TIP = 20;

// Gesture tuning thresholds
const PINCH_ON = 0.32;
const PINCH_OFF = 0.45;
const ROTATE_SPEED = 5.0;
const SMOOTHING = 0.35; // Exponential Moving Average smoothing factor

// Swipe detection knobs
const SWIPE_MIN_SPEED = 1.15; // normalized units per second
const SWIPE_COOLDOWN_MS = 1200; // time before another swipe can fire
const SWIPE_HISTORY_SIZE = 6;

export class HandTracker {
  constructor(video, overlay, callbacks) {
    this.video = video;
    this.overlay = overlay;
    this.callbacks = callbacks || {};
    this.landmarker = null;
    this.stream = null;
    this.rafId = 0;
    this.running = false;
    this.lastVideoTime = -1;

    this.handStates = new Map();
    this.prevMode = "idle";
    this.prevSpinGrab = null;
    this.prevZoomDist = null;
    this.prevExpandDist = null;
    this.lastStatus = { hands: 0, mode: "idle" };

    // Velocity history for flick/swipe detection
    this.velocityHistory = [];
    this.lastSwipeTime = 0;

    // Laser pointer state
    this.activePointer = null; // { x, y, confidence }
    this.explodeLevel = 0.0; // 0.0 (assembled) to 2.0 (exploded)

    // Double pinch detection
    this.lastPinchTime = 0;
  }

  async start() {
    try {
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({
          video: { width: 640, height: 480, facingMode: "user" },
          audio: false,
        });
      } catch (mediaErr) {
        if (mediaErr.name === "NotReadableError" || mediaErr.name === "TrackStartError") {
          console.warn("Camera device busy (V4L2 releasing), retrying in 400ms...");
          await new Promise((r) => setTimeout(r, 400));
          this.stream = await navigator.mediaDevices.getUserMedia({
            video: { width: 640, height: 480, facingMode: "user" },
            audio: false,
          });
        } else {
          throw mediaErr;
        }
      }
      this.video.srcObject = this.stream;
      await this.video.play();

      const fileset = await FilesetResolver.forVisionTasks(WASM_CDN);
      const options = {
        baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
        runningMode: "VIDEO",
        numHands: 2,
        minHandDetectionConfidence: 0.6,
        minHandPresenceConfidence: 0.6,
        minTrackingConfidence: 0.6,
      };
      try {
        this.landmarker = await HandLandmarker.createFromOptions(fileset, options);
      } catch {
        this.landmarker = await HandLandmarker.createFromOptions(fileset, {
          ...options,
          baseOptions: { ...options.baseOptions, delegate: "CPU" },
        });
      }

      this.running = true;
      this.loop();
    } catch (err) {
      console.warn("HandTracker initialization failure:", err);
      this.callbacks.onError?.(err.message || "Failed to initialize webcam hand tracking");
      throw err;
    }
  }

  stop() {
    this.running = false;
    cancelAnimationFrame(this.rafId);
    this.landmarker?.close();
    this.landmarker = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
    this.handStates.clear();
    this.prevMode = "idle";
    this.prevSpinGrab = null;
    this.prevZoomDist = null;
    this.prevExpandDist = null;
    this.activePointer = null;
    const ctx = this.overlay.getContext("2d");
    ctx?.clearRect(0, 0, this.overlay.width, this.overlay.height);
    this.emitStatus({ hands: 0, mode: "idle" });
  }

  loop = () => {
    if (!this.running) return;
    this.rafId = requestAnimationFrame(this.loop);

    if (!this.landmarker || this.video.readyState < 2) return;
    if (this.video.currentTime === this.lastVideoTime) return;
    this.lastVideoTime = this.video.currentTime;

    const result = this.landmarker.detectForVideo(this.video, performance.now());
    const labels = result.handedness ? result.handedness.map((h) => h[0]?.categoryName ?? "?") : [];
    this.processHands(result.landmarks || [], labels);
    this.drawOverlay(result.landmarks || []);
  };

  /**
   * Classify hand configuration into primary poses:
   * - "pointing": index finger extended, other 3 fingers curled
   * - "open_palm": all fingers extended
   * - "pinching": thumb and index tips together
   * - "fist": all fingers curled
   */
  classifyPose(lm, handScale) {
    const thumbDist = dist2d(lm[THUMB_TIP], lm[INDEX_TIP]) / handScale;
    const isPinching = thumbDist < PINCH_ON;

    const wrist = lm[WRIST];
    const indexExt = dist2d(lm[INDEX_TIP], wrist) > 1.35 * dist2d(lm[INDEX_MCP], wrist);
    const middleCurl = dist2d(lm[MIDDLE_TIP], wrist) < 1.15 * dist2d(lm[MIDDLE_PIP], wrist);
    const ringCurl = dist2d(lm[RING_TIP], wrist) < 1.15 * dist2d(lm[RING_PIP], wrist);
    const pinkyCurl = dist2d(lm[PINKY_TIP], wrist) < 1.15 * dist2d(lm[PINKY_PIP], wrist);

    // Laser pointing: index extended, other 3 fingers curled
    if (indexExt && middleCurl && ringCurl && pinkyCurl && !isPinching) {
      return "pointing";
    }

    // Open palm: all fingers extended
    const middleExt = dist2d(lm[MIDDLE_TIP], wrist) > 1.3 * dist2d(lm[MIDDLE_MCP], wrist);
    const ringExt = dist2d(lm[RING_TIP], wrist) > 1.25 * dist2d(lm[RING_MCP], wrist);
    const pinkyExt = dist2d(lm[PINKY_TIP], wrist) > 1.2 * dist2d(lm[PINKY_MCP], wrist);
    if (indexExt && middleExt && ringExt && pinkyExt && !isPinching) {
      return "open_palm";
    }

    if (isPinching) return "pinching";
    if (middleCurl && ringCurl && pinkyCurl && !indexExt) return "fist";

    return "relaxed";
  }

  processHands(landmarks, labels) {
    const now = performance.now();
    const seen = new Set();
    const currentHands = [];

    landmarks.forEach((lm, i) => {
      const label = labels[i] || `hand_${i}`;
      seen.add(label);

      const handScale = dist2d(lm[WRIST], lm[MIDDLE_MCP]);
      if (handScale < 1e-6) return;

      const pose = this.classifyPose(lm, handScale);

      // Centroid (normalized screen coordinates: mirrored X)
      const rawX = 1 - lm[MIDDLE_MCP].x;
      const rawY = lm[MIDDLE_MCP].y;

      let state = this.handStates.get(label);
      if (!state) {
        state = {
          x: rawX,
          y: rawY,
          pose,
          pinching: false,
          history: [],
          pointer: { x: rawX, y: rawY },
        };
        this.handStates.set(label, state);
      }

      // Smooth coordinates with EMA
      state.x += (rawX - state.x) * SMOOTHING;
      state.y += (rawY - state.y) * SMOOTHING;
      state.pose = pose;

      // Laser Pointer coordinate (index fingertip, mirrored)
      const rawPtrX = 1 - lm[INDEX_TIP].x;
      const rawPtrY = lm[INDEX_TIP].y;
      state.pointer.x += (rawPtrX - state.pointer.x) * (SMOOTHING * 1.2);
      state.pointer.y += (rawPtrY - state.pointer.y) * (SMOOTHING * 1.2);

      // Track velocity history for flick gestures
      state.history.push({ x: state.x, y: state.y, t: now });
      if (state.history.length > SWIPE_HISTORY_SIZE) state.history.shift();

      // Check pinch state transitions
      const pinchRatio = dist2d(lm[THUMB_TIP], lm[INDEX_TIP]) / handScale;
      const wasPinching = state.pinching;
      if (state.pinching && pinchRatio > PINCH_OFF) state.pinching = false;
      else if (!state.pinching && pinchRatio < PINCH_ON) state.pinching = true;

      // Double-pinch trigger
      if (!wasPinching && state.pinching) {
        if (now - this.lastPinchTime < 450) {
          this.callbacks.onAction?.("DOUBLE_PINCH");
          this.lastPinchTime = 0;
        } else {
          this.lastPinchTime = now;
        }
      }

      currentHands.push({ label, state, lm });
    });

    // Purge absent hands
    for (const key of this.handStates.keys()) {
      if (!seen.has(key)) this.handStates.delete(key);
    }

    // ── GESTURE DETECTION PIPELINE ──

    // 1. Check Flick / Swipe Gesture
    this.detectSwipes(currentHands, now);

    // 2. Mode Determination
    let mode = "idle";
    const pinchingHands = currentHands.filter((h) => h.state.pinching);
    const openHands = currentHands.filter((h) => h.state.pose === "open_palm");
    const pointingHands = currentHands.filter((h) => h.state.pose === "pointing");

    // 3. Priority: Pointing Raycaster
    if (pointingHands.length >= 1) {
      mode = "pointing";
      const ptr = pointingHands[0].state.pointer;
      this.activePointer = { x: ptr.x, y: ptr.y };
      this.callbacks.onPoint?.(ptr.x, ptr.y);
    } else {
      if (this.activePointer) {
        this.activePointer = null;
        this.callbacks.onPointEnd?.();
      }
    }

    // 4. Two-Hand Explode / Expand (Open Palms or 2 Hands Apart)
    if (currentHands.length >= 2 && mode !== "pointing") {
      const h1 = currentHands[0].state;
      const h2 = currentHands[1].state;
      const dist = Math.hypot(h1.x - h2.x, h1.y - h2.y);

      if (pinchingHands.length >= 2) {
        // Micro-pinch mode: Camera Zoom
        mode = "zoom";
        if (this.prevZoomDist && dist > 1e-4) {
          const factor = Math.min(1.18, Math.max(0.85, this.prevZoomDist / dist));
          this.callbacks.onZoom?.(factor);
        }
        this.prevZoomDist = dist;
      } else {
        // Macro open-hand mode: CAD Explode / Expand View
        mode = "explode";
        if (this.prevExpandDist !== null) {
          const delta = dist - this.prevExpandDist;
          if (Math.abs(delta) > 0.003) {
            // Expand explodes outward; contracting brings it back
            this.explodeLevel = Math.max(0.0, Math.min(2.2, this.explodeLevel + delta * 4.0));
            this.callbacks.onTwoHandExpand?.(this.explodeLevel, delta);
          }
        }
        this.prevExpandDist = dist;

        // Two-hand spatial roll
        const dY = h1.y - h2.y;
        const dX = h1.x - h2.x;
        const angle = Math.atan2(dY, dX);
        if (this.prevTwoHandAngle !== undefined) {
          let deltaAngle = angle - this.prevTwoHandAngle;
          if (deltaAngle > Math.PI) deltaAngle -= Math.PI * 2;
          if (deltaAngle < -Math.PI) deltaAngle += Math.PI * 2;
          if (Math.abs(deltaAngle) > 0.02) {
            this.callbacks.onTwoHandRotate?.(deltaAngle);
          }
        }
        this.prevTwoHandAngle = angle;
      }
    } else {
      this.prevZoomDist = null;
      this.prevExpandDist = null;
      this.prevTwoHandAngle = undefined;
    }

    // 5. Single Hand Pinched Spin
    if (currentHands.length === 1 && pinchingHands.length === 1 && mode === "idle") {
      mode = "spin";
      const grab = { x: pinchingHands[0].state.x, y: pinchingHands[0].state.y };
      if (this.prevSpinGrab) {
        const dx = grab.x - this.prevSpinGrab.x;
        const dy = grab.y - this.prevSpinGrab.y;
        if (Math.abs(dx) > 1e-4 || Math.abs(dy) > 1e-4) {
          this.callbacks.onRotate?.(dx * ROTATE_SPEED, dy * ROTATE_SPEED);
        }
      }
      this.prevSpinGrab = grab;
    } else {
      this.prevSpinGrab = null;
    }

    this.prevMode = mode;
    this.emitStatus({ hands: landmarks.length, mode, explode: this.explodeLevel.toFixed(2) });
  }

  /**
   * Detect intentional rapid flick/swipe motions across consecutive frames.
   */
  detectSwipes(currentHands, now) {
    if (now - this.lastSwipeTime < SWIPE_COOLDOWN_MS) return;

    for (const h of currentHands) {
      const hist = h.state.history;
      if (hist.length < 4) continue;

      const oldest = hist[0];
      const newest = hist[hist.length - 1];
      const dt = (newest.t - oldest.t) / 1000.0;
      if (dt < 0.06 || dt > 0.4) continue;

      const dx = newest.x - oldest.x;
      const dy = newest.y - oldest.y;
      const dist = Math.hypot(dx, dy);
      const speed = dist / dt;

      if (speed >= SWIPE_MIN_SPEED) {
        let action = null;
        if (Math.abs(dx) > Math.abs(dy) * 1.4) {
          action = dx > 0 ? "FLICK_RIGHT" : "FLICK_LEFT";
        } else if (Math.abs(dy) > Math.abs(dx) * 1.4) {
          action = dy > 0 ? "FLICK_DOWN" : "FLICK_UP";
        }

        if (action) {
          this.lastSwipeTime = now;
          hist.length = 0; // Clear history to prevent duplicate trigger
          this.callbacks.onSwipe?.(action);
          this.callbacks.onAction?.(action);
          break;
        }
      }
    }
  }

  emitStatus(status) {
    if (
      status.hands !== this.lastStatus.hands ||
      status.mode !== this.lastStatus.mode ||
      status.explode !== this.lastStatus.explode
    ) {
      this.lastStatus = status;
      this.callbacks.onStatus?.(status);
    }
  }

  drawOverlay(landmarks) {
    const ctx = this.overlay.getContext("2d");
    if (!ctx) return;
    const { width, height } = this.overlay;
    ctx.clearRect(0, 0, width, height);

    // Render Laser Raycaster from index finger if active
    if (this.activePointer) {
      const px = this.activePointer.x * width;
      const py = this.activePointer.y * height;

      // Laser crosshairs
      ctx.strokeStyle = "rgba(0, 255, 255, 0.9)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(px, py, 14, 0, Math.PI * 2);
      ctx.stroke();

      ctx.beginPath();
      ctx.arc(px, py, 4, 0, Math.PI * 2);
      ctx.fillStyle = "#00ffff";
      ctx.fill();

      // Crosshair tick marks
      ctx.beginPath();
      ctx.moveTo(px - 22, py); ctx.lineTo(px - 14, py);
      ctx.moveTo(px + 14, py); ctx.lineTo(px + 22, py);
      ctx.moveTo(px, py - 22); ctx.lineTo(px, py - 14);
      ctx.moveTo(px, py + 14); ctx.lineTo(px, py + 22);
      ctx.stroke();

      // Holographic HUD text tag
      ctx.font = "10px monospace";
      ctx.fillStyle = "#00ffff";
      ctx.fillText("TARGET RAY // LOCKED", px + 18, py - 6);
    }

    // Render hand bones and joints
    for (const lm of landmarks) {
      const wrist = lm[WRIST];
      const thumb = lm[THUMB_TIP];
      const index = lm[INDEX_TIP];
      const handScale = dist2d(wrist, lm[MIDDLE_MCP]);
      const pinched = handScale > 1e-6 && dist2d(thumb, index) / handScale < PINCH_ON;

      // Draw skeleton lines
      const fingerBones = [
        [0, 1, 2, 3, 4],
        [0, 5, 6, 7, 8],
        [0, 9, 10, 11, 12],
        [0, 13, 14, 15, 16],
        [0, 17, 18, 19, 20],
      ];

      ctx.strokeStyle = pinched ? "rgba(255, 204, 102, 0.8)" : "rgba(0, 229, 255, 0.45)";
      ctx.lineWidth = pinched ? 2.2 : 1.2;

      for (const bone of fingerBones) {
        ctx.beginPath();
        for (let j = 0; j < bone.length; j++) {
          const pt = lm[bone[j]];
          const sx = (1 - pt.x) * width;
          const sy = pt.y * height;
          if (j === 0) ctx.moveTo(sx, sy);
          else ctx.lineTo(sx, sy);
        }
        ctx.stroke();
      }

      // Draw joint nodes
      for (let j = 0; j < 21; j++) {
        const pt = lm[j];
        const sx = (1 - pt.x) * width;
        const sy = pt.y * height;
        const isTip = [4, 8, 12, 16, 20].includes(j);

        ctx.fillStyle = isTip
          ? pinched
            ? "#ffcc66"
            : "#00e5ff"
          : "rgba(0, 180, 220, 0.6)";

        ctx.beginPath();
        ctx.arc(sx, sy, isTip ? 4 : 2, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }
}

function dist2d(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}
