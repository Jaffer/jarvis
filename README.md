# Desktop clap → Jarvis-style welcome

Python script that listens to your default microphone and runs a **double-clap** welcome flow (Spotify, Chrome windows, ElevenLabs voice, Cursor). See constants at the top of `jarvis.py` for behavior and tuning.

## Setup

From this project directory:

```bash
python -m pip install -r requirements.txt
```

## Environment variables

The script loads a **`.env` file** in the same folder as `jarvis.py` (via `python-dotenv`). You can also set variables in the shell.

### Required (ElevenLabs welcome line)

| Variable | Purpose |
| -------- | ------- |
| `ELEVENLABS_API_KEY` | API key from [ElevenLabs](https://elevenlabs.io). |
| `ELEVENLABS_VOICE_ID` | Voice ID from the ElevenLabs app (My Voices / library). |

Without these, the welcome speech is skipped (other actions may still run).

### Optional

| Variable | Purpose |
| -------- | ------- |
| `ELEVENLABS_MODEL_ID` | TTS model (default in code: `eleven_multilingual_v2`). |
| `ELEVENLABS_OUTPUT_FORMAT` | e.g. `pcm_24000` (must match playback expectations). |
| `ELEVENLABS_PCM_SAMPLE_RATE` | Override PCM sample rate if it differs from the format name. |
| `JARVIS_WELCOME_CACHE_DIR` | Custom folder for cached welcome WAV (default: `.cache/jarvis_welcome/` under the project). |
| `JARVIS_INPUT_DEVICE` | Optional mic override: **integer** index or **substring** of the device name. If unset, the script uses the Windows default; when that mic is silent, it auto-picks the loudest working input. List devices: `python -c "import sounddevice as sd; print(sd.query_devices())"`. |
| `CLAUDE_CODE_URL` | URL opened for Claude in Chrome (default: new chat). |
| `TASARADAR_URL` | URL opened for Tasaradar in Chrome (default: `https://tasaradar.com`). `BINANCE_BTC_URL` is still read as a fallback if set. |
| `CHROME_NEW_WINDOW_WAIT_S` | Seconds to wait for a new Chrome window on Windows (default `25`). |
| `CHROME_WINDOW_WIDTH` / `CHROME_WINDOW_HEIGHT` | Windowed Chrome size when not fullscreen. |

Example `.env`:

```env
ELEVENLABS_API_KEY=your_key_here
ELEVENLABS_VOICE_ID=your_voice_id_here
```

## Run

```bash
python jarvis.py
```

Allow the microphone if Windows prompts you. Stop with **Ctrl+C**.

## Tuning

Edit the constants at the top of `jarvis.py`:

| Constant      | Effect                                                            |
| ------------- | ----------------------------------------------------------------- |
| `SPIKE_RATIO` | Increase if you get false triggers; decrease if claps are missed. |
| `COOLDOWN_S`  | Minimum time between two logged claps.                            |
| `BLOCK_MS`    | Larger = slightly less CPU, a bit less precise timing.            |
| `MIN_RMS`     | Floor on how loud a block must be (helps in very quiet rooms).  |
| `SAMPLE_RATE` | Try `48000` if your device does not like `44100`.                 |

## Troubleshooting

- **Wrong or quiet mic:** On startup the script probes your default Windows input. If it is silent, it **auto-selects** the loudest working mic. To force a specific device, set `JARVIS_INPUT_DEVICE` in `.env` (index or name substring from `sounddevice.query_devices()`).
- **PortAudio / audio errors:** Update audio drivers or try another `SAMPLE_RATE`.
- **No reaction to claps:** Lower `SPIKE_RATIO` slightly or speak/clap closer to the mic.
- **Spam logs:** Raise `SPIKE_RATIO` or `COOLDOWN_S`.
- **No welcome speech:** Set `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` in `.env` and restart the terminal so variables load.

## 🛰️ God's Eye View (bundled live OSINT globe)

JARVIS ships with a vendored copy of [God's Eye View](https://github.com/bilawalsidhu/gods-eye-view) (MIT license, © Bilawal Sidhu) in `godseye/` — a photorealistic 3D globe with live aircraft, ships, satellites, earthquakes, traffic, and public cameras.

- **Open it:** HUD `GOD'S EYE [O]` button, hotkey `O`, say *"open God's Eye View"*, or ask JARVIS to open the globe (`open_board` tool with target `godseye`).
- **Lazy sidecar:** nothing runs until first use. JARVIS verifies Node 24+/npm, runs `npm ci` on first use, then starts Vite on `127.0.0.1:4174` — its own origin, so GEV's `/api` data providers never collide with JARVIS's `/api` routes.
- **Config:** `godseye.port` in `jarvis.json` (default `4174`); `JARVIS_GODSEYE=1/0` force-enables/disables (off on Render/cloud by default — see `.env.example`).
- **Keys optional:** the globe starts keyless (Esri imagery); add Cesium ion / Google / OpenAI keys later via GEV's in-app POWER UP panel (`godseye/.env`, git-ignored).
- **Logs:** `godseye/.logs/install.log`, `godseye/.logs/vite.log`. Deltas vs upstream are documented in `godseye/JARVIS-INTEGRATION.md`.

## 📅 Google Workspace (Calendar + Gmail voice bridge)

JARVIS can read your Google Calendar and Gmail over one OAuth identity and speak them proactively.

- **One-time OAuth setup (local):** place your OAuth Desktop `credentials.json` (Google Cloud project `jarvis-assistant-508807`, Calendar + Gmail APIs enabled) next to `jarvis.py`, then start JARVIS — the first Calendar/Gmail call opens the browser consent once and caches the token as `.google-workspace-token.json` (separate from any Drive MCP creds). Headless machines can paste the token JSON into `GOOGLE_WORKSPACE_TOKEN_JSON` instead. Requires `pip install -r requirements.txt` (adds `google-api-python-client`, `google-auth`, `google-auth-oauthlib`).
- **One-time OAuth setup (online / Render):** a cloud instance has no browser and no way to place a file, so paste the **Desktop** `credentials.json` contents into `GOOGLE_WORKSPACE_CLIENT_JSON`, then say **"connect google"**. JARVIS puts a clickable Google consent link on the HUD, you approve on your phone/laptop, Google lands on an unreachable `http://127.0.0.1:<port>/?code=...&state=...` page (that is expected — nothing is listening on the cloud host), and you **read that address back to JARVIS**, which finishes the exchange and caches the token. The `state` is verified first, so a stale or foreign redirect is refused before the single-use code is ever spent at Google. Because Render wipes its disk on redeploy, copy the resulting `.google-workspace-token.json` into `GOOGLE_WORKSPACE_TOKEN_JSON` afterwards so the connection survives. A `web`-type client is refused on purpose — only a Desktop client can receive the loopback redirect this flow depends on.
- **Scopes:** reads use `calendar.readonly` + `gmail.readonly`. Event creation requests `calendar.events` (default on — set `JARVIS_GOOGLE_ALLOW_WRITE=0` to keep every write off the consent screen). `JARVIS_GOOGLE_ALLOW_MARK_READ=1` additionally requests `gmail.modify` so the mail watcher can mark notified messages as read. `JARVIS_GOOGLE_BRIDGE_ENABLED=0` hard-disables the whole bridge. A cached token that lacks a newly-enabled scope triggers one more browser consent automatically on the next start.
- **Voice phrases:** *"connect google"* / *"set up gmail"* (one-time OAuth consent — see above), *"morning briefing"*, *"what's my next meeting"*, *"what's on my schedule tomorrow"*, *"check my unread email"*, *"digest emails about bank statements"*, *"find emails from Amazon"*, *"add event dentist tomorrow at 3 pm"*, *"schedule meeting with Sam at 9:30"*, *"put dentist on my calendar at 10 am"*, *"remind me about my standup 10 minutes before"*, *"quiet hours 21 to 7"*, *"snooze notifications for 30 minutes"*, *"what did I miss"*. A create phrase without a time makes JARVIS ask for one instead of guessing; a time already past today rolls to tomorrow (always stated in the spoken confirmation).
- **Proactive alerts:** a daemon thread polls Calendar (default 300 s) and Gmail (600 s), dedupes by id, and speaks anything due through the normal TTS queue — suppressed during calls. A scheduled morning briefing fires at `JARVIS_BRIEFING_HOUR:JARVIS_BRIEFING_MINUTE` (default 08:00) once per day.
- **Quiet hours:** 22:00–08:00 by default (`JARVIS_GOOGLE_QUIET_START_H/END_H`). During quiet hours, alerts queue instead of speaking; the queue drains as one "while you were away" block on your next Google-related question, so nothing is lost. *"quiet hours 21 to 7"* persists into `memory/Profile.md` and wins over the env defaults.
- **LLM tools:** `google_next_event`, `google_agenda` (day), `google_mail_digest` (keywords/labels), and `google_create_event` (title + ISO 8601 start) are exposed to the brain alongside the voice router; all paths report empty results, denied writes, and bad inputs honestly and never invent subjects or times.
- **Env vars:** see the *Google Workspace* block in `.env.example` (poll intervals, briefing time, quiet hours, urgent-event/mail keyword filters).
- **Offline tests:** `python3 scratch/test_google_workspace_bridge.py` (49 network-free checks against a stub API surface).

## 🎓 Autonomous Topic Learning (background research + a self-written progress bar)

Say *"learn hacking"* and JARVIS researches the topic in the background while you keep talking to it — one thread, no blocking, no invented facts.

- **What it does:** the `TopicLearner` daemon walks Wikipedia (search + full intro extract) and DuckDuckGo (instant answer + related subjects), then writes dated notes to `memory/02 - Knowledge/Learned/<topic>.md` with a Summary, Key points, the real source URLs and a *"Gaps (honest)"* list naming any source that failed. If nothing answers, the run reports `failed` with the reason — it never fabricates content to look finished.
- **Live progress:** `state/learning_state.json` carries `topic / percent / phase / detail / sources`, and every step broadcasts a `LEARNING_PROGRESS` event to the HUD. Ask *"learning status"* any time (or *"what are you learning"*), and *"what did you learn about hacking"* reads the saved summary back.
- **The progress bar writes its own code:** *"learn hacking and put the progress bar on the orb screen"* makes JARVIS generate the widget's HTML/CSS **itself** (`build_learning_progress_widget`) — themed with the HUD's own CSS variables so it always matches your active palette — and inject it through the existing dynamic-HUD architect. It mounts on `<body>` (outside the transformed HUD stage) so `position: fixed` anchors are truly screen-fixed, and it persists in `web/index.html` + `web/app.js`, surviving a refresh.
- **Voice control over its own UI** — every phrase rewrites both the live widget *and* its persisted code through `AutonomousCodeArchitect.update_hud_feature`, so what you hear is what stays:
  - *"move the progress bar to the top right corner"* / *"…to the bottom left"* / *"…to a corner"*
  - *"move it down a bit"* / *"move the progress bar slightly left"* — pixel nudges (20 px for *slightly / a bit*, 40 px otherwise) that accumulate and clamp, stored in `state/learning_progress_ui.json`
  - *"show the topic you are learning in the progress too"* / *"hide the topic from the progress bar"*
  - *"hide the progress bar"* / *"show the progress bar"*
- **Honest states:** a second topic while one runs is refused (*"I am already learning X, sir — N percent in"*); *"stop learning"* ends the run and says where it stopped; a crash mid-research is reported as `interrupted` on the next start instead of pretending to continue.
- **Permanent deletion stays separate:** *"remove the progress bar widget"* (the words *widget / component / feature / panel*) routes to the existing permanent-removal path, which also cleans the persisted manifest from `web/app.js` and `web/index.html`.
- **Offline tests:** `python3 scratch/test_learning_feature.py` (36 network-free checks — grammar claims and fall-throughs, widget builder + HUD validator, learner against a fake fetch, persisted-manifest replacement, handler replies).

## 🧠 Listener Intelligence (voice misrouting defence)

Bystander speech in another language was being transcribed and routed as your command. The fix is three cheap gates before the router ever sees a transcript:

- **1 · Language gate** — Whisper runs multilingual now (`"stt_model": "small"`, was `small.en`, so real `language` + `language_probability` come back) and only transcripts in `JARVIS_STT_LANGUAGES` (default `en`) get through. Confident foreign speech is dropped as `foreign_language`; borderline detections as `uncertain_language`; and when there is no language signal at all, the worst segment `avg_logprob` under `JARVIS_STT_MIN_LOGPROB` (default −1.0) drops it as `low_confidence_speech`. Native-script text (Telugu/Hindi/…) is detected by script even on English-only models; romanised text is never guessed at.
- **2 · Speaker gate** — once `python3 enroll_admin.py` has enrolled your voice, only the admin's voice issues commands; guests are ignored with a HUD note, not spoken back to. Before enrolment the gate stays permissive (it cannot lock you out), wake phrases and typed/websocket input always pass, and replay attacks are refused as `replay_spoof`. `JARVIS_SPEAKER_GATE=0` disables it.
- **3 · Fuzzy command normalisation** — at the top of the command router, *every* input path (mic, browser, HUD typing, HTTP, mobile) gets mishearings repaired: curated aliases (`utoobe → youtube`, `bear hands → barehands`, `god's eye → gods eye`, extendable in `jarvis.json` → `"speech_aliases"`) plus algorithmic phonetic/typo repair (`chorme → chrome`, `oepn → open`). Destructive instructions are never rewritten, ambiguous readings are left alone, every correction is logged and shown on the HUD (`TRANSCRIPT_CORRECTION`), and `JARVIS_FUZZY_COMMANDS=0` turns it off.
- **Offline tests:** `python3 scratch/test_listener_intelligence.py` (27 checks — all three layers against synthetic Whisper info/segments and dict speaker identities, no network).

## 🌐 OpenRouter free-model pool (self-switching cloud brain)

JARVIS can now think on **free** cloud models via OpenRouter — no per-token billing — with a pool that picks the right model itself and switches the instant the acting one dies, runs dry, or hits a limit.

- **The pool (`openrouter.py`):** 11 free models (verified live against OpenRouter's model list), ordered by purpose — big/fast long-context models first for conversation (`nemotron-3.5-lightning`, `nemotron-3-super-120b`, `qwen3.8-27b`, `gemma-4-31b`, `inkling`…), small ones first for the `fast` purpose, coding models first for `code`. It *sticks* to the last model that answered well until that one fails.
- **Automatic switching:** rate limit (429) → 60 s cooldown, next model in; **out of tokens/quota** (402, daily limits) → 6 h cooldown; dead/retired models → 24 h; context-overflow → skip the small model for *that request only* so a 1 M-context free model can still answer it; empty/failed output → next model. Every switch is logged and shown on the HUD (`MODEL_SWITCH` toast: *"nemotron lightning rate limit → qwen"*). Tool schemas a model rejects are retried tool-less and remembered.
- **Engine order (`jarvis.json` → `brain.engine`):** `auto` = OpenRouter pool → Groq → local Ollama (current default). `openrouter` = pool then local only. `groq`/`ollama` keep the legacy Groq-if-key-then-Ollama behaviour. Optional `brain.openrouter_models` array overrides the model order.
- **Setup:** one line in `.env` (never in the repo): `OPENROUTER_API_KEY=sk-or-v1-…` — get yours at https://openrouter.ai/keys. Without it the pool idles silently and everything works as before; `openrouter.py` exposes `status()` (ready / cooling / reason per model) if you want to inspect the pool live.
- **Offline tests:** `python3 scratch/test_openrouter_pool.py` (19 network-free checks — error classification, failover, cooldowns, tool retry, stickiness, brain glue, all with a fake transport). Live check used during integration: `scratch/smoke_openrouter.py` (real key + real free models; it already proved failover — lightning timed out and super-120b took over mid-request).

## 🔐 Guided Enrollment (code-locked face + Google-style voice test)

Say the full sentence ***"start face and voice enrollment. code: Even dead I am the hero"*** into the microphone and JARVIS walks whoever is standing there through four stages: **who's enrolling** (spoken name → its own profile, never piled onto "Admin") → **face capture** → a spoken **voice test** — five real commands JARVIS will actually use (*"Hey Jarvis, open YouTube"*, *"Hey Jarvis, what is the weather today"*, …). Each prompt must be read back word-correctly **and** captured as live voice; the averaged voiceprint and the face are then saved under that display name, so your friends can enroll the same way while visiting.

- **The code is the key, and it is strict:** the check runs on the RAW transcript before typo repair (so a *"event"*-for-*"even"* mishearing can never launder a wrong code into a right one), uses constant-time word comparison, refuses typed/websocket/HUD origins (**mic only — you must be physically present**), and locks out for 5 minutes after 5 wrong attempts. The terminal wizard `enroll_admin.py` asks for the same sentence first — it starts nothing without it. Bare phrases like *"enroll my face"* no longer start anything; they just tell you the code is required.
- **Nothing writes without a live body:** the face stage runs the anti-spoof liveness check (photos/screens held to the camera are refused), each voice read-back must be long, loud and live (silence and replay refused), 2 retries per stage before the session aborts, and the whole session expires after 10 minutes. The HUD narrates every step (code accepted → name captured → face progress → each prompt → complete).
- **Multi-user by design:** profiles live per-name (`users` / `face_users` in `memory/00 - Biometrics/admin_profile.json`) next to the untouched legacy admin profile; every enrolled voice commands, strangers are still ignored. The LLM tool and the HUD button can only *explain/open* enrollment — neither can start it or write a profile.
- **Offline tests:** `.venv/bin/python scratch/test_guided_enrollment.py` (32 network-free checks — trigger, strict code gate + lockout, prompt matching, name stage, speaker-gate passthrough, multi-user stores, full router state machine with stubs).

## 🧪 Running the test suites

- **Network-free suites** run on any interpreter:
  - `python3 scratch/test_learning_feature.py` (36) · `python3 scratch/test_google_workspace_bridge.py` (49) · `python3 scratch/test_godseye_bridge.py` (44) · `python3 scratch/test_listener_intelligence.py` (27) · `python3 test_self_coding_and_gps.py` (3) · `python3 scratch/test_watchdog.py`
  - `.venv/bin/python scratch/test_guided_enrollment.py` (32 — needs the venv for `cv2`/`scipy` imports, still fully offline with stubs)
- **Vision / biometric / camera suites need the project environment** — they import `cv2`, `mediapipe`, `sounddevice` or `edge_tts`, which live in the venv built from `requirements.txt`. Running them with a bare system `python3` aborts with `No module named 'cv2'`: that is an interpreter problem, not a code failure. Use:
  ```bash
  .venv/bin/python scratch/test_fixes.py
  .venv/bin/python scratch/test_camera_arbitration.py
  .venv/bin/python scratch/test_vision_scanner.py
  .venv/bin/python scratch/test_face_pipeline.py
  .venv/bin/python scratch/test_anti_spoofing.py
  ```
- **`scratch/test_voice_pipeline.py`** is a live check (microphone → Whisper → speaker sentinel): 9/10 here, and the remaining step is your own one-time `python enroll_admin.py` (Stage 2 — it now asks for the enrollment code sentence first, same secret as the voice flow); with no voice profile JARVIS correctly stays in guest protocol.
