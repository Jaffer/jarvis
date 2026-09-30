/**
 * JARVIS vendored delta — one brain, one voice.
 *
 * The globe is a DUMB EXECUTOR: it owns no AI. This module is the only inbound
 * control surface, and it carries two flows over the same loopback origin that
 * the ORB HUD handed us when it opened this tab:
 *
 *   inbound  — poll `<hud>/api/godseye/command` and run each queued action
 *              through the same action runner the (disabled) voice dock used.
 *   outbound — post the camera centre so JARVIS can answer "nearest X".
 *
 * The ORB HUD origin is recovered exactly as the return-link script does
 * (`#hud=`, then `document.referrer`, then localStorage), so it works from LAN
 * IPs and non-default ports without any build-time configuration.
 *
 * See JARVIS-INTEGRATION.md for the delta log.
 */

const POLL_MS = 700;
const POLL_BACKOFF_MS = 2500;
const TELEMETRY_MS = 5000;
const DEFAULT_HUD_ORIGIN = 'http://localhost:5050';

/** Recover the ORB HUD origin (mirrors the index.html return-link script). */
export function resolveHudOrigin() {
  let hud = null;
  const m = location.hash.match(/hud=([^&]+)/);
  if (m) {
    try {
      hud = decodeURIComponent(m[1]);
    } catch {
      hud = null;
    }
  }
  if (!hud && document.referrer) {
    try {
      const u = new URL(document.referrer);
      if (u.origin !== location.origin) hud = u.origin;
    } catch {
      hud = null;
    }
  }
  if (hud) {
    try {
      localStorage.setItem('jarvis_hud_origin', hud);
    } catch {
      /* private mode — the hash/referrer still work for this load */
    }
  }
  if (!hud) {
    try {
      hud = localStorage.getItem('jarvis_hud_origin');
    } catch {
      hud = null;
    }
  }
  return (hud || DEFAULT_HUD_ORIGIN).replace(/\/+$/, '');
}

/** Camera centre in degrees (no Cesium import needed — the getter is enough). */
function readViewCentre(viewer) {
  const carto = viewer?.camera?.positionCartographic;
  if (!carto) return null;
  const toDeg = 180 / Math.PI;
  const lat = carto.latitude * toDeg;
  const lng = carto.longitude * toDeg;
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return { lat, lng, heightM: Number.isFinite(carto.height) ? carto.height : null };
}

/** Hide the globe's own voice dock — JARVIS owns the microphone. */
function suppressVoiceDock() {
  const dock = document.getElementById('gev-voice-control');
  if (!dock) return;
  dock.dataset.jarvisManaged = 'true';
  dock.style.display = 'none';
  dock.setAttribute('aria-hidden', 'true');
}

/**
 * Install the JARVIS bridge.
 *
 * @param {{viewer?: object}} [options]
 * @returns {{stop: () => void, hudOrigin: string}}
 */
export function installJarvisBridge({ viewer = null } = {}) {
  const hudOrigin = resolveHudOrigin();
  const commandUrl = `${hudOrigin}/api/godseye/command`;
  const telemetryUrl = `${hudOrigin}/api/godseye/telemetry`;
  let cancelled = false;
  let pollTimer = null;
  let telemetryTimer = null;
  const seen = new Set();

  suppressVoiceDock();

  const dispatch = async (cmd) => {
    const action = String(cmd?.action || '');
    const args = cmd?.args && typeof cmd.args === 'object' ? cmd.args : {};
    if (!action) return;
    const key = `${action}:${JSON.stringify(args)}`;
    if (seen.has(key)) return;
    seen.add(key);
    if (seen.size > 64) seen.clear();
    const run = window.__godsEyeView?.runAction;
    if (typeof run !== 'function') {
      console.warn('[JARVIS bridge] action runner unavailable — dropping', action);
      return;
    }
    try {
      const result = await run(action, args);
      console.log('[JARVIS bridge]', action, args, result?.ok === false ? result : 'ok');
    } catch (err) {
      console.warn('[JARVIS bridge]', action, 'failed:', err?.message || err);
    }
  };

  const poll = async () => {
    if (cancelled) return;
    let delay = POLL_MS;
    try {
      const res = await fetch(commandUrl, {
        method: 'GET',
        cache: 'no-store',
        credentials: 'omit',
        mode: 'cors',
      });
      if (res.ok) {
        const data = await res.json();
        for (const cmd of data?.commands || []) void dispatch(cmd);
      } else {
        delay = POLL_BACKOFF_MS;
      }
    } catch {
      // HUD closed or restarting — keep trying, quietly.
      delay = POLL_BACKOFF_MS;
    }
    if (!cancelled) pollTimer = setTimeout(poll, delay);
  };

  const postTelemetry = async () => {
    if (cancelled) return;
    const centre = readViewCentre(viewer || window.__godsEyeView?.viewer);
    try {
      if (centre) {
        await fetch(telemetryUrl, {
          method: 'POST',
          cache: 'no-store',
          credentials: 'omit',
          mode: 'cors',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(centre),
        });
      }
    } catch {
      /* telemetry is best-effort; the next tick retries */
    }
    if (!cancelled) telemetryTimer = setTimeout(postTelemetry, TELEMETRY_MS);
  };

  // Kick both loops a beat after install so the viewer is fully built.
  setTimeout(() => {
    if (cancelled) return;
    void poll();
    void postTelemetry();
  }, 400);

  const bridge = {
    hudOrigin,
    stop() {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
      if (telemetryTimer) clearTimeout(telemetryTimer);
      pollTimer = null;
      telemetryTimer = null;
    },
  };
  window.__jarvisGevBridge = bridge;
  console.log('[JARVIS bridge] attached — HUD origin', hudOrigin);
  return bridge;
}
