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

## Deltas vs upstream (re-apply these when syncing)

| File | Delta |
| ---- | ----- |
| `index.html` | `<title>` → `J.A.R.V.I.S. // God's Eye View`; added `#jarvis-hud-return` style + HUD-origin learning script (reads `#hud=` opener hash → `document.referrer` → `localStorage` → fallback `http://localhost:5050`). |
| `src/ui/templates/scene-chrome.html` | Title-bar subtitle → `J.A.R.V.I.S. UPLINK // NO PLACE LEFT BEHIND`; added the `⟨ ORB HUD ⟩` return link inside `#title-bar`. |
| `README.md` | Two-line banner pointing at this document. |
| *(new)* `JARVIS-INTEGRATION.md` | This file. |

Everything else is byte-identical to upstream at vendoring time.

## Running it standalone (without JARVIS)

```bash
cd godseye
npm ci
npm run dev        # http://localhost:4173
```

Upstream documentation applies unchanged (`../godseye/README.md`, `docs/`).
