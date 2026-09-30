# JARVIS ↔ God's Eye View integration notes

This directory is a **vendored copy** of [bilawalsidhu/gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view)
(MIT license, © Bilawal Sidhu), pruned of `.git/`, `.github/`, `.agents/`,
`docs/media/`, and `pinokio/` to keep the JARVIS repository lean.

It exists so JARVIS can present the globe as a first-class subsystem: a HUD
button, hotkey `O`, voice phrases ("open God's Eye View", "eye in the sky",
"open the globe"), and the `open_board` LLM tool (target `godseye`) all bring
it up and open it.

## How JARVIS runs it

- **Lazy sidecar:** `GodsEyeViewService` in `../jarvis.py` does nothing at
  boot. The first open request verifies Node (24.x/26.x) + npm, runs
  `npm ci` once if `node_modules/` is missing, then starts the Vite dev server
  on `127.0.0.1:<port>` (default **4174**, see `godseye.port` in
  `../jarvis.json` or `JARVIS_GODSEYE_PORT`).
- **Own origin on purpose:** GEV's data providers are same-origin `/api/*`
  middleware inside Vite; JARVIS already owns `/api/*` on its HUD port. Serving
  GEV from its own port keeps both API namespaces collision-free.
- **Adoption:** if a globe is already listening on the port (manual
  `npm run dev`), JARVIS adopts it instead of spawning a second one.
- **Telemetry:** state is exposed via `GET /api/godseye/status`, kicked via
  `GET /api/godseye/start` (token-gated like `/api/system_info`), and mirrored
  into the subsystem health registry (`godseye_server`).
- **Cloud gating:** disabled when `JARVIS_PUBLIC_DEPLOYMENT` (Render) unless
  `JARVIS_GODSEYE=1`; `JARVIS_GODSEYE=0` disables everywhere.
- **Logs:** `godseye/.logs/install.log`, `godseye/.logs/vite.log`.
- **Shutdown:** the Vite process group is terminated via `atexit` when JARVIS
  exits.
- **Command bridge:** JARVIS keeps the single brain and the single voice. The
  globe is a dumb executor with no AI of its own — see below.

## Command bridge (one brain, one voice)

The globe owns **no AI**. Its own OpenAI-Realtime voice dock is hidden on load,
and every globe action comes from JARVIS:

```
you speak
  → JARVIS mic + STT (faster-whisper local, or Groq whisper-large-v3-turbo)
  → JARVIS brain (one decision-maker)
  → POST/GET /api/godseye/command        (queue on the HUD origin)
  → godseye/src/jarvis/bridge.js         (poll loop inside the globe page)
  → window.__godsEyeView.runAction(...)  (the globe's own action runner)
  → JARVIS's own voice answers
```

| Endpoint | Auth | Purpose |
| -------- | ---- | ------- |
| `GET /api/godseye/command` | token, or loopback | Drains queued actions and returns the current view. Every poll marks the page "live". |
| `POST /api/godseye/command` | token, or loopback | Explicit enqueue for HTTP/API callers. Unknown actions are refused (400), never silently dropped. |
| `POST /api/godseye/telemetry` | token, or loopback | The globe reports its camera centre so `nearest X` has an origin. |

**Voice grammar** (routed in section 2a, *before* the bare "open the globe"
handler so a destination is never swallowed):

- `show me the london bridge in god's eye view` → opens the globe + `fly_to_location`
- `god's eye, fly to tokyo tower` / `bring up the golden gate bridge in god's eye` → same
- `now move to the pyramids` / `take me to the colosseum` → bare nav verbs, which
  are gated on the globe actually being live
- `find the nearest coffee shop` / `nearest atm` / `closest pharmacy` → keyless
  Overpass lookup around the current view, then a flight to the result
- `zoom in` / `orbit left` / `pan right` / `stop tracking` / `pull out to the globe`
- `turn on the flights` / `hide cctv` / `disable the radio` (layer names are
  validated against a mirror of upstream's `LAYER_ALIASES`)

**Deliberate gates:** bare globe commands (no "god's eye" in them) only route
while the bridge or sidecar is live, so they never hijack unrelated handlers.
`pull up` / `bring up` remain owned by the 3D-construct sections unless the globe
is named; directional phrasing ("move the view to the left") is a camera pan,
never a destination. A POI lookup that cannot resolve an origin or a category
returns an honest miss rather than inventing a location.

**No OpenAI key is required.** Geocoding falls back to keyless Nominatim and POI
search to keyless Overpass. `GOOGLE_MAPS_API_KEY` only upgrades imagery
(photoreal 3D tiles, Street View) and place search quality.

## Deltas vs upstream (re-apply these when syncing)

| File | Delta |
| ---- | ----- |
| `index.html` | `<title>` → `J.A.R.V.I.S. // God's Eye View`; added `#jarvis-hud-return` style + HUD-origin learning script (reads `#hud=` opener hash → `document.referrer` → `localStorage` → fallback `http://localhost:5050`). |
| `src/ui/templates/scene-chrome.html` | Title-bar subtitle → `J.A.R.V.I.S. UPLINK // NO PLACE LEFT BEHIND`; added the `⟨ ORB HUD ⟩` return link inside `#title-bar`. |
| *(new)* `src/jarvis/bridge.js` | The whole inbound/outbound bridge: polls `/api/godseye/command`, dispatches to the action runner, posts camera telemetry, hides the globe's own voice dock. AI-free by design. |
| `src/app/tools.js` | Imports and installs `installJarvisBridge({ viewer })` after the debug handle exists; disposes it in the existing `defer(() => …)` teardown. |
| `src/voice/gevRealtime.js` | Captures the runner once and publishes it as `window.__godsEyeView.runAction` so the bridge can drive the globe programmatically. |
| `README.md` | Two-line banner pointing at this document. |
| *(new)* `JARVIS-INTEGRATION.md` | This file. |

Everything else is byte-identical to upstream at vendoring time.

## Running it standalone (without JARVIS)

```bash
cd godseye
npm ci
npm run dev        # http://localhost:4173
```

Standalone, the bridge finds no HUD, backs off to a 2.5 s poll, and stays quiet —
the globe still works on its own, just without voice. Upstream documentation
applies unchanged (`../godseye/README.md`, `docs/`).
