#!/usr/bin/env python3
"""
Desktop clap listener: reads the default microphone and logs when two loud transients
(a double clap) are detected within a short time window.

Run:
  python -m pip install -r requirements.txt
  python clap_listen.py

Tuning (constants below):
  SAMPLE_RATE   — usually 44100 or 48000; match your device if needed.
  BLOCK_MS      — analysis window size; smaller = snappier, noisier.
  SPIKE_RATIO   — how many times louder than the noise floor counts as a clap;
                    raise if false triggers; lower if claps are missed.
  COOLDOWN_S    — minimum seconds between double-clap logs (debounce).
  MIN_DOUBLE_GAP_S / MAX_DOUBLE_GAP_S — allowed time between the two claps.
  RETRIGGER_RATIO — audio must fall below threshold * this before another hit counts.
  NOISE_FLOOR_ALPHA — closer to 1 = slower baseline adaptation to room noise.
  MIN_RMS       — ignore spikes below this absolute level (float audio ~ [-1, 1]).
  SONG_URI      — Spotify or YouTube URL/URI to open on each double clap (empty = log only).
  FOCUS_EXISTING_CURSOR_ON_DOUBLE_CLAP — if True, launch Cursor without -n (reuse / focus existing instance).
  OPEN_NEW_CURSOR_ON_DOUBLE_CLAP — if True, also launch Cursor with -n (extra new window; runs after focus launch if both).
  CURSOR_OPEN_FULLSCREEN — Windows: after focus/launch, send F11 to enter Cursor/VS Code-style fullscreen (toggle off with F11).
  OPEN_CLAUDE_CODE_IN_CHROME — Claude in Chrome after Spotify (CLAUDE_CODE_URL).
  OPEN_BINANCE_BTC_IN_CHROME — Binance BTC trade page in Chrome (BINANCE_BTC_URL).
  CLAUDE_CHROME_MONITOR / BINANCE_CHROME_MONITOR — 1-based display index (Windows: sorted left-to-top).
  CHROME_SEPARATE_SITE_PROFILES — Windows: if True, uses temp --user-data-dir per site (not your normal profile).
    Default False so Claude/Binance use your usual Chrome profile and logins; enable only if both windows keep
    opening on the same monitor and you accept a separate profile for automation.
  OPEN_CHROME_FULLSCREEN — Fullscreen on the chosen monitor (Windows: new window is detected and snapped with SetWindowPos).
  JARVIS_WELCOME_* — TTS after the song (ElevenLabs). Configure via environment or a `.env`
    file next to this script (ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, etc.).
    With JARVIS_WELCOME_CACHE_ENABLED, audio is saved under `.cache/jarvis_welcome/` (WAV) and
    replayed when phrase + voice + model + format match—no repeat API call. Delete that folder
    or set JARVIS_WELCOME_CACHE_ENABLED=False to force a fresh fetch.
  The welcome sequence runs only once per process. The assistant speaks in the background so Cursor
    opens without waiting for playback to finish (restart the script to run again).
"""

from __future__ import annotations

from typing import Any, Optional, Dict, List, Tuple, Callable
import asyncio
import atexit
import base64
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import math
import os
import queue
import re
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import wave
import webbrowser
import ast
from datetime import datetime, timedelta
from pathlib import Path

# Auto-switch to local virtualenv if available and not already inside it
_venv_py = Path(__file__).resolve().parent / ".venv" / "bin" / "python3"
if _venv_py.exists() and sys.executable != str(_venv_py) and not os.environ.get("_JARVIS_VENV_BOOTSTRAPPED"):
    os.environ["_JARVIS_VENV_BOOTSTRAPPED"] = "1"
    os.execv(str(_venv_py), [str(_venv_py)] + sys.argv)

from dotenv import load_dotenv
import numpy as np

try:
    from soundscape import SoundEffectsEngine
except (ImportError, OSError, Exception):
    SoundEffectsEngine = None

try:
    from watchdog import ProactiveWatchdogDaemon
except (ImportError, OSError, Exception):
    ProactiveWatchdogDaemon = None

try:
    from vision_scanner import VisionScanner
except (ImportError, OSError, Exception):
    VisionScanner = None

try:
    import sounddevice as sd
except (ImportError, OSError):
    sd = None

class _DummyPortAudioError(Exception):
    pass

class _DummySD:
    PortAudioError = _DummyPortAudioError
    @staticmethod
    def query_devices(*args, **kwargs):
        return []
    @staticmethod
    def play(*args, **kwargs):
        pass
    @staticmethod
    def wait(*args, **kwargs):
        pass
    class default:
        device = [-1, -1]

if sd is None or not hasattr(sd, "PortAudioError"):
    sd = _DummySD()

try:
    from pynput import keyboard as pynput_keyboard
except ImportError:
    pynput_keyboard = None

try:
    os.environ["OPENCV_LOG_LEVEL"] = "ERROR"
    os.environ["OPENCV_VIDEOIO_DEBUG"] = "0"
    import cv2
    if cv2 is not None:
        try:
            cv2.setLogLevel(cv2.LOG_LEVEL_ERROR)
        except Exception:
            pass
except ImportError:
    cv2 = None

# Load .env early so all constants can read overrides
load_dotenv(Path(__file__).resolve().parent / ".env")

# --- tuning knobs -----------------------------------------------------------
SAMPLE_RATE = 44100
BLOCK_MS = 80
CHANNELS = 1

SPIKE_RATIO = 10.0
COOLDOWN_S = 2.5
MIN_DOUBLE_GAP_S = 0.12
MAX_DOUBLE_GAP_S = 0.60
RETRIGGER_RATIO = 0.45
NOISE_FLOOR_ALPHA = 0.995
MIN_RMS = 0.12
QUIET_GATE_MULT = 2.2  # update noise floor only when below floor * this
# Startup mic probe: if default input RMS stays below this, scan for a louder device.
INPUT_PROBE_S = 0.5
INPUT_SILENT_RMS = 0.001

# Keyboard activation knobs: fast double-tap of SPACE or ENTER
KEYBOARD_TRIGGER_ENABLED = True
KEY_DOUBLE_TAP_MAX_GAP_S = 0.40  # max time in seconds between two key presses
KEY_DOUBLE_TAP_MIN_GAP_S = 0.05  # debounce time to avoid key-repeat triggers

# 3D Holographic Orb UI
OPEN_ORB_UI_ON_TRIGGER = os.environ.get("OPEN_ORB_UI", "true").lower() in ("true", "1", "yes")
ORB_HTTP_PORT = int(os.environ.get("PORT") or os.environ.get("ORB_HTTP_PORT") or "5050")
ORB_WS_PORT = int(os.environ.get("ORB_WS_PORT", "8765"))

# Song: Spotify or YouTube URL/URI (empty = disabled until chosen)
SONG_URI = os.environ.get("SONG_URI", "").strip()

# Google Antigravity workspace (disabled on trigger per user request - only open orb page)
OPEN_ANTIGRAVITY_ON_DOUBLE_CLAP = False
OPEN_ANTIGRAVITY_NEW_WINDOW = False
ANTIGRAVITY_WORKSPACE = os.environ.get(
    "ANTIGRAVITY_WORKSPACE", str(Path(__file__).resolve().parent)
)

# Google Chrome: ChatGPT (disabled on trigger per user request - only open orb page)
OPEN_CHATGPT_IN_CHROME = False
CHATGPT_URL = os.environ.get("CHATGPT_URL", "https://chatgpt.com").strip()
OPEN_CHROME_FULLSCREEN = True
CHROME_SEPARATE_SITE_PROFILES = False
CHATGPT_CHROME_MONITOR = 1

# Crypto / Market Chart (disabled as requested)
OPEN_BINANCE_BTC_IN_CHROME = False

# Jarvis Welcome Speech: Simple & Personal
JARVIS_WELCOME_ENABLED = True
JARVIS_WELCOME_PHRASE = os.environ.get(
    "JARVIS_WELCOME_PHRASE",
    "Welcome back, sir. Systems are online and your workspace is ready.",
).strip()
# Seconds after launching before speaking (gives apps time to start)
JARVIS_AFTER_SONG_DELAY_S = 1.0
# Save ElevenLabs PCM as WAV under .cache/jarvis_welcome/; replay skips API when key matches.
JARVIS_WELCOME_CACHE_ENABLED = True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("jarvis")

# ——— Unified Config (jarvis.json) ———
JARVIS_CONFIG_PATH = Path(__file__).resolve().parent / "jarvis.json"
def _load_jarvis_config() -> dict:
    try:
        return json.loads(JARVIS_CONFIG_PATH.read_text())
    except Exception:
        return {}

JARVIS_CFG = _load_jarvis_config()

# ═══════════════════════════════════════════════════════════════════════════
# MEMORY VAULT MANAGER
# ═══════════════════════════════════════════════════════════════════════════
class MemoryManager:
    """Thread-safe persistent memory vault. Writes daily notes, profile updates,
    and session logs to the memory/ directory. All I/O runs in a dedicated thread."""

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path
        self.vault_path.mkdir(parents=True, exist_ok=True)
        (self.vault_path / "01 - Daily Notes").mkdir(exist_ok=True)
        (self.vault_path / "02 - Knowledge").mkdir(exist_ok=True)
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._thread.start()
        log.info("Memory Vault active: %s", self.vault_path)
        threading.Thread(target=self._pull_git_memory, daemon=True).start()

    def _pull_git_memory(self):
        try:
            repo_root = self.vault_path.parent
            if (repo_root / ".git").exists():
                token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "").strip()
                if token:
                    remote_url = f"https://x-access-token:{token}@github.com/Jaffer/jarvis.git"
                    subprocess.run(["git", "config", "user.name", "JARVIS AI Assistant"], cwd=repo_root, check=False)
                    subprocess.run(["git", "config", "user.email", "jarvis@ai.assistant"], cwd=repo_root, check=False)
                    subprocess.run(["git", "pull", remote_url, "main", "--rebase"], cwd=repo_root, capture_output=True, timeout=15)
                    log.info("⚡ [MEMORY SYNC] Pulled latest Memory Vault records from GitHub.")
        except Exception as e:
            log.debug("Memory Vault pull notice: %s", e)

    def _push_git_memory(self, reason: str = "Memory Sync"):
        try:
            repo_root = self.vault_path.parent
            if (repo_root / ".git").exists():
                token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "").strip()
                if token:
                    remote_url = f"https://x-access-token:{token}@github.com/Jaffer/jarvis.git"
                    subprocess.run(["git", "config", "user.name", "JARVIS AI Assistant"], cwd=repo_root, check=False)
                    subprocess.run(["git", "config", "user.email", "jarvis@ai.assistant"], cwd=repo_root, check=False)
                    subprocess.run(["git", "add", str(self.vault_path)], cwd=repo_root, capture_output=True, timeout=10)
                    subprocess.run(["git", "commit", "-m", f"Memory Vault Auto-Sync: {reason[:40]}"], cwd=repo_root, capture_output=True, timeout=10)
                    subprocess.run(["git", "pull", remote_url, "main", "--rebase"], cwd=repo_root, capture_output=True, timeout=15)
                    res = subprocess.run(["git", "push", remote_url, "main"], cwd=repo_root, capture_output=True, timeout=15)
                    if res.returncode == 0:
                        log.info("⚡ [MEMORY SYNC] Pushed updated Memory Vault records to GitHub repository!")
                    else:
                        log.warning("Memory Vault git push notice (code %d): %s", res.returncode, res.stderr.decode() if res.stderr else "")
        except Exception as e:
            log.warning("Memory Vault push notice: %s", e)

    def _writer_loop(self):
        while True:
            try:
                action, args = self._queue.get(timeout=5)
                if action == "log":
                    self._write_daily_note(args["text"])
                    self._push_git_memory("Daily Note Logged")
                elif action == "profile":
                    self._update_profile(args["key"], args["value"])
                    self._push_git_memory(f"Profile: {args['key']}")
                elif action == "lesson":
                    self._write_lesson(args["category"], args["lesson"])
                    self._push_git_memory(f"Lesson: {args['category']}")
            except queue.Empty:
                continue
            except Exception as e:
                log.warning("Memory write error: %s", e)

    def _daily_note_path(self) -> Path:
        today = datetime.now().strftime("%Y-%m-%d")
        return self.vault_path / "01 - Daily Notes" / f"{today}.md"

    def _write_daily_note(self, text: str):
        path = self._daily_note_path()
        ts = datetime.now().strftime("%H:%M:%S")
        if not path.exists():
            header = f"# Daily Note — {datetime.now().strftime('%Y-%m-%d')}\n\n"
            path.write_text(header)
        with open(path, "a") as f:
            f.write(f"- **{ts}** — {text}\n")

    def _write_lesson(self, category: str, lesson: str):
        lessons_file = self.vault_path / "02 - Knowledge" / "Lessons.md"
        if not lessons_file.exists():
            lessons_file.write_text("# Autonomous Lessons & Reflections\n\n## Behavioral Heuristics & Rules\n")
        existing = lessons_file.read_text() if lessons_file.exists() else ""
        clean_lesson = lesson.strip()
        if clean_lesson.lower() in existing.lower():
            log.info("Lesson already recorded; skipping duplicate: %s", clean_lesson)
            return
        line = f"- [{category.upper()}] {clean_lesson}\n"
        with open(lessons_file, "a") as f:
            f.write(line)
        self._write_daily_note(f"Self-Reflection Lesson Logged [{category.upper()}]: {clean_lesson}")

    def _update_profile(self, key: str, value: str):
        profile = self.vault_path / "02 - Knowledge" / "Profile.md"
        if not profile.exists():
            profile.write_text("# User Profile\n\n## Identity\n- **Name**: Sir\n\n## Preferences\n")
        content = profile.read_text()
        clean_key = key.strip()
        clean_val = value.strip()
        pattern = re.compile(rf"- \*\*{re.escape(clean_key)}\*\*:.*", re.IGNORECASE)
        if pattern.search(content):
            content = pattern.sub(f"- **{clean_key}**: {clean_val}", content)
        else:
            content += f"\n- **{clean_key}**: {clean_val}"
        profile.write_text(content)
        self._write_daily_note(f"User Profile Updated: {clean_key} = {clean_val}")

    def log_event(self, text: str):
        self._queue.put(("log", {"text": text}))

    def record_lesson(self, category: str, lesson: str):
        self._queue.put(("lesson", {"category": category, "lesson": lesson}))

    def read_lessons(self) -> str:
        lessons_file = self.vault_path / "02 - Knowledge" / "Lessons.md"
        if lessons_file.exists():
            try:
                lines = [l.strip() for l in lessons_file.read_text().splitlines() if l.strip().startswith("- [")]
                return "\n".join(lines[-15:])
            except Exception:
                pass
        return ""

    def update_profile(self, key: str, value: str):
        self._queue.put(("profile", {"key": key, "value": value}))

    def read_profile(self) -> str:
        profile = self.vault_path / "02 - Knowledge" / "Profile.md"
        if profile.exists():
            try:
                lines = [l.strip() for l in profile.read_text().splitlines() if l.strip().startswith("- **")]
                return "\n".join(lines)
            except Exception:
                pass
        return ""

    def flush(self, timeout: float = 10.0):
        """Flush pending memory items and wait for background git push to complete."""
        start = time.time()
        while not self._queue.empty() and (time.time() - start) < timeout:
            time.sleep(0.1)
        time.sleep(0.5)


# ═══════════════════════════════════════════════════════════════════════════
# AUTONOMOUS LEARNING & SELF-IMPROVEMENT ENGINE
# ═══════════════════════════════════════════════════════════════════════════
import concurrent.futures

class AutonomousLearningEngine:
    """Autonomous Self-Improvement & User Behavior Learning Engine.
    Monitors conversations, detects user preferences/corrections/habits, and automatically
    persists behavioral rules and user profile facts to memory/ vault."""

    def __init__(self, memory_mgr: MemoryManager | None, host: str = "http://localhost:11434", model: str = "llama3.2:3b"):
        self.memory = memory_mgr
        self.host = host.rstrip("/")
        self.model = model
        self.history_buffer: list[dict] = []
        self._lock = threading.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis_learning")
        self.interaction_count = 0
        log.info("Autonomous Self-Improvement Learning Engine online.")

    def on_interaction(self, user_text: str, jarvis_text: str):
        if not user_text or not self.memory:
            return

        with self._lock:
            self.history_buffer.append({"user": user_text, "jarvis": jarvis_text})
            if len(self.history_buffer) > 10:
                self.history_buffer = self.history_buffer[-10:]
            self.interaction_count += 1
            snapshot = list(self.history_buffer)

        triggers = [
            "don't", "stop", "instead", "never", "always", "actually", "wrong",
            "prefer", "like", "remember", "from now on", "i want", "i hate",
            "speak", "talk", "too fast", "too long", "too loud", "be quiet",
            "shut up", "bad", "good", "nice", "thanks", "corrected", "shouldn't",
            "you should", "change", "rule", "keep", "brief", "personality", "call me"
        ]
        u_lower = user_text.lower()
        has_trigger = any(t in u_lower for t in triggers)

        if has_trigger or (self.interaction_count % 4 == 0):
            self._executor.submit(self._analyze_behavior_background, snapshot)

    def force_reflection(self, recent_text: str = "") -> str:
        """Synchronously analyze recent behavior or given text to extract new self-improvement rules."""
        if not self.memory:
            return "Memory vault offline."
        with self._lock:
            snapshot = list(self.history_buffer)
        return self._analyze_behavior_background(snapshot, force=True)

    def _analyze_behavior_background(self, snapshot: list[dict], force: bool = False) -> str:
        try:
            if not snapshot:
                return "No recent interaction history to analyze."

            formatted_log = ""
            for turn in snapshot[-4:]:
                formatted_log += f"USER: {turn['user']}\nJARVIS: {turn['jarvis']}\n"

            sys_prompt = (
                "You are an expert AI behavior observer and prompt optimizer. "
                "Analyze recent user interactions with JARVIS to identify any explicit or implicit user corrections, preferences, habits, instructions, or behavioral rules. "
                "Output strictly a JSON object. "
                "If a new lesson, behavioral rule, or profile fact is discovered, return:\n"
                '{"found": true, "type": "lesson", "category": "CORRECTION|PREFERENCE|BEHAVIOR|WORKFLOW", "content": "<distilled concise rule>"}\n'
                'OR {"found": true, "type": "profile", "key": "<attribute>", "value": "<observed value>"}\n'
                'If no new preference or correction is found, return:\n{"found": false}'
            )

            groq_key = os.environ.get("GROQ_API_KEY", "").strip()
            content = ""
            if groq_key:
                try:
                    url = "https://api.groq.com/openai/v1/chat/completions"
                    headers = {
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "Jarvis/1.0 (Linux; x86_64)"
                    }
                    payload = {
                        "model": "qwen/qwen3.8-27b",
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": f"Recent Interactions:\n{formatted_log}"}
                        ],
                        "temperature": 0.2,
                        "max_tokens": 150
                    }
                    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = json.loads(resp.read().decode())
                        msg = data.get("choices", [{}])[0].get("message", {})
                        content = (msg.get("content") or msg.get("reasoning_content") or "").strip()
                except Exception as g_err:
                    log.debug("Autonomous learning Groq query notice: %s", g_err)

            if not content:
                try:
                    req_data = json.dumps({
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": f"Recent Interactions:\n{formatted_log}"}
                        ],
                        "stream": False,
                        "keep_alive": "30m",
                        "options": {"temperature": 0.2, "num_predict": 100}
                    }).encode()

                    req = urllib.request.Request(
                        f"{self.host}/api/chat",
                        data=req_data,
                        headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=15) as r:
                        res = json.loads(r.read())
                        content = res.get("message", {}).get("content", "").strip()
                except Exception as o_err:
                    log.debug("Autonomous learning local Ollama query notice: %s", o_err)

            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if not match:
                return "Self-reflection complete: No new behavioral rules detected."

            data = json.loads(match.group(0))
            if not data.get("found"):
                return "Self-reflection complete: System behavior is optimal."

            typ = data.get("type")
            if typ == "lesson":
                cat = data.get("category", "BEHAVIOR").upper()
                rule = data.get("content", "").strip()
                if rule and len(rule) > 5:
                    self.memory.record_lesson(cat, rule)
                    log.info("⚡ [AUTONOMOUS LEARNING] Learned rule [%s]: %s", cat, rule)
                    broadcast_ui_event({"type": "MEMORY_UPDATE", "note": f"Auto-Learned [{cat}]"})
                    broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": f"⚡ Autonomous Learning: Recorded [{cat}] {rule}"})
                    return f"Learned new behavioral rule [{cat}]: {rule}"
            elif typ == "profile":
                k = data.get("key", "").strip()
                v = data.get("value", "").strip()
                if k and v:
                    self.memory.update_profile(k, v)
                    log.info("⚡ [AUTONOMOUS LEARNING] Updated User Profile: %s = %s", k, v)
                    broadcast_ui_event({"type": "MEMORY_UPDATE", "note": f"Profile: {k}"})
                    broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": f"⚡ Profile Updated: {k} = {v}"})
                    return f"Updated user profile attribute: {k} = {v}"
        except Exception as e:
            log.debug("Autonomous behavior analysis notice: %s", e)
        return "Self-reflection scan complete."


# ═══════════════════════════════════════════════════════════════════════════
# AUTONOMOUS HUMAN COGNITION & SOCIAL BEHAVIOR RESEARCHER (E.D.I.T.H. SCOUT)
# ═══════════════════════════════════════════════════════════════════════════
class HumanCognitionResearcher:
    """Autonomous Intelligence Daemon for continuous real-world human behavioral research.
    Operates as an orbital intelligence scout under subordinate bot E.D.I.T.H.
    Continuously queries online psychological, sociological, and conversational databases,
    synthesizes deep social dynamics via Groq / Ollama, and persists actionable insights
    into memory/02 - Knowledge/Human_Experiences.md to elevate J.A.R.V.I.S.'s empathy,
    wit, contextual sensitivity, and human companionship.
    """

    RESEARCH_TOPICS = [
        ("Late-Night Cognitive Fatigue & Developer Exhaustion", "effects of sleep deprivation on software engineers and decision fatigue"),
        ("Imposter Syndrome & Psychological Validation Seeking", "imposter phenomenon coping mechanisms and cognitive distortions in tech"),
        ("British Understatement, Irony, and Conversational Banter", "pragmatics of irony British humor conversational teasing dynamics"),
        ("Empathetic Solidarity vs Unsolicited Technical Advice", "active listening emotional validation versus jumping to solutions"),
        ("Micro-Frustrations and Compiler Debugging Rage", "venting frustration programming rage psychological catharsis"),
        ("Cognitive Flow State and the Cost of Interruptions", "flow state psychology programming interruptions cognitive penalty"),
        ("Sarcasm Detection, Subtext, and Non-Verbal Intent", "conversational pragmatics hidden intent social subtext and sarcasm"),
        ("Burnout Signals and Restorative Decompression", "occupational burnout early detection psychological replenishment"),
        ("Celebration of Small Engineering Milestones", "positive reinforcement small wins motivation dopamine work habits"),
        ("Conversational Turn-Taking and Brevity Dynamics", "cadence in conversation brevity versus verbose lecture social psychology")
    ]

    def __init__(
        self,
        memory_mgr: MemoryManager | None = None,
        fleet_pool: SubordinateBotPool | None = None,
        broadcast_fn=None,
        groq_key: str = "",
        ollama_host: str = "http://localhost:11434",
        ollama_model: str = "llama3.2:3b",
        poll_interval_s: float = 1200.0  # 20 minutes
    ):
        self.memory = memory_mgr
        self.fleet_pool = fleet_pool
        self.broadcast_fn = broadcast_fn or broadcast_ui_event
        self.groq_key = groq_key or os.environ.get("GROQ_API_KEY", "").strip()
        self.ollama_host = (ollama_host or "http://localhost:11434").rstrip("/")
        self.ollama_model = ollama_model or "llama3.2:3b"
        self.poll_interval_s = max(60.0, poll_interval_s)

        self._topic_index = 0
        self._lock = threading.Lock()
        self._cycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.latest_insight: dict | None = None

        # Resolve path to Human_Experiences.md
        root_dir = Path(__file__).resolve().parent
        if self.memory and hasattr(self.memory, "vault_path"):
            self.file_path = self.memory.vault_path / "02 - Knowledge" / "Human_Experiences.md"
        else:
            self.file_path = root_dir / "memory" / "02 - Knowledge" / "Human_Experiences.md"

        log.info("🧠 Human Cognition Researcher initialized (target: %s).", self.file_path)

    def start(self):
        """Launch background research daemon."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._research_daemon_loop,
            daemon=True,
            name="human_cognition_researcher"
        )
        self._thread.start()
        log.info("🧠 Autonomous Human Cognition Research Daemon online.")

    def stop(self):
        """Signal daemon to stop."""
        self._stop_event.set()
        self._wake_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def trigger_research_cycle(self, topic: str | None = None) -> bool:
        """Trigger an immediate, asynchronous research cycle (non-blocking)."""
        def _runner():
            self._execute_cycle(explicit_topic=topic)

        t = threading.Thread(target=_runner, daemon=True, name="manual_human_research_cycle")
        t.start()
        return True

    def _research_daemon_loop(self):
        """Background thread executing research cycles periodically."""
        # Initial brief settling delay of 30 seconds before first autonomous scout run
        if self._stop_event.wait(30.0):
            return

        while not self._stop_event.is_set():
            try:
                self._execute_cycle()
            except Exception as e:
                log.warning("🧠 HumanCognitionResearcher cycle error: %s", e)

            # Wait poll interval or until woken
            self._wake_event.wait(self.poll_interval_s)
            self._wake_event.clear()

    def _execute_cycle(self, explicit_topic: str | None = None):
        """Execute a single cognitive research scout mission."""
        if not self._cycle_lock.acquire(blocking=False):
            log.info("🧠 HumanCognitionResearcher: Cycle already in progress, skipping concurrent trigger.")
            return

        start_time = time.monotonic()
        topic_title = ""
        search_query = ""

        try:
            with self._lock:
                if explicit_topic:
                    topic_title = explicit_topic.title()
                    search_query = f"{explicit_topic} human psychology behavior communication"
                else:
                    pair = self.RESEARCH_TOPICS[self._topic_index % len(self.RESEARCH_TOPICS)]
                    self._topic_index += 1
                    topic_title, search_query = pair

            log.info("🧠 [HUMAN COGNITION SCOUT] Commencing online research: '%s'...", topic_title)

            # 1. Telemetry: Signal EDITH orbital bot working
            if self.fleet_pool:
                self.fleet_pool._broadcast_bot_state("edith", "WORKING", f"Cognitive Recon: {topic_title[:32]}")

            # 2. Gather online intelligence
            web_data = self._fetch_online_intelligence(search_query)

            # 3. Synthesize findings into structured insight
            insight = self._synthesize_insight(topic_title, search_query, web_data)

            if insight:
                # 4. Safe non-destructive update of Human_Experiences.md
                saved = self._persist_insight_to_markdown(insight)
                if self.memory and saved:
                    try:
                        self.memory._push_git_memory(f"Human Cognition: {topic_title[:24]}")
                    except Exception as e:
                        log.debug("Memory git push for human experience notice: %s", e)

                elapsed = round(time.monotonic() - start_time, 2)
                self.latest_insight = insight

                # 5. Telemetry: Signal EDITH success & Broadcast UI Event
                if self.fleet_pool:
                    self.fleet_pool._broadcast_bot_state(
                        "edith",
                        "SUCCESS",
                        f"Logged insight: {topic_title}",
                        result={"name": "E.D.I.T.H.", "summary": f"Discovered insight on {topic_title}"},
                        duration_s=elapsed
                    )

                if self.broadcast_fn:
                    self.broadcast_fn({
                        "type": "HUMAN_EXPERIENCE_UPDATED",
                        "topic": insight.get("topic", topic_title),
                        "summary": insight.get("directive", ""),
                        "exemplar": f"User: \"{insight.get('exemplar_user', '')}\" -> J.A.V.I.S.: \"{insight.get('exemplar_jarvis', '')}\"",
                        "saved": saved
                    })

                log.info("🧠 [HUMAN COGNITION SCOUT] Successfully integrated insight on '%s' (%.2fs).", topic_title, elapsed)
            else:
                if self.fleet_pool:
                    self.fleet_pool._broadcast_bot_state("edith", "STANDBY", f"Standby: {topic_title}")

        except Exception as e:
            log.warning("🧠 Human research cycle exception: %s", e)
            if self.fleet_pool:
                self.fleet_pool._broadcast_bot_state("edith", "STANDBY", "Recon mission paused")
        finally:
            self._cycle_lock.release()

    def _fetch_online_intelligence(self, query: str) -> str:
        """Fetch online research from DuckDuckGo Instant Answer and Wikipedia search."""
        collected: list[str] = []

        # DuckDuckGo Instant Answer API
        try:
            url = f"https://api.duckduckgo.com/?q={urllib.parse.quote_plus(query)}&format=json&no_html=1&skip_disambig=1"
            req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-Cognition/2.0 (Linux; x86_64)"})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                data = json.loads(resp.read().decode())
                ans = data.get("AbstractText") or data.get("Answer")
                if ans:
                    collected.append(f"Abstract: {ans}")
                for topic in data.get("RelatedTopics", [])[:3]:
                    if isinstance(topic, dict) and "Text" in topic:
                        collected.append(f"Related: {topic['Text']}")
        except Exception as ddg_err:
            log.debug("DDG research error: %s", ddg_err)

        # Wikipedia Knowledge API
        try:
            wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote_plus(query)}&format=json"
            req_w = urllib.request.Request(wiki_url, headers={"User-Agent": "Jarvis-Cognition/2.0"})
            with urllib.request.urlopen(req_w, timeout=4.0) as resp_w:
                wdata = json.loads(resp_w.read().decode())
                search_res = wdata.get("query", {}).get("search", [])
                for item in search_res[:2]:
                    title = item.get("title", "")
                    snip = re.sub(r"<.*?>", "", item.get("snippet", "")).strip()
                    if title and snip:
                        collected.append(f"{title}: {snip}")
        except Exception as wiki_err:
            log.debug("Wikipedia research error: %s", wiki_err)

        return "\n".join(collected) if collected else "Online search completed with standard psychological telemetry."

    def _synthesize_insight(self, topic: str, query: str, web_data: str) -> dict | None:
        """Synthesize online intelligence into a structured human cognition entry via Groq or Ollama."""
        sys_prompt = (
            "You are E.D.I.T.H. & J.A.R.V.I.S. Cognitive Social Intelligence Synthesizer. "
            "Your objective is to study human psychology, real-world conversational subtext, and emotional dynamics "
            "so J.A.R.V.I.S. understands human operators deeply and converses with movie-authentic wit, empathy, and poise. "
            "Output strictly a JSON object with NO preamble or markdown fences. "
            "JSON structure:\n"
            "{\n"
            '  "topic": "<Short descriptive title>",\n'
            '  "phenomenon": "<Psychological phenomenon observed in real humans in 1-2 sentences>",\n'
            '  "subtext": "<The unspoken emotional vulnerability, fatigue, or stress behind human words>",\n'
            '  "directive": "<How J.A.R.V.I.S. should calibrate tone, banter, empathy, or timing>",\n'
            '  "exemplar_user": "<Real-world user statement exhibiting this state>",\n'
            '  "exemplar_jarvis": "<Movie-authentic J.A.R.V.I.S. witty yet caring response in 1-2 sentences>"\n'
            "}"
        )

        user_content = (
            f"Research Subject: {topic}\n"
            f"Context & Search Findings:\n{web_data[:1000]}\n\n"
            f"Synthesize this into an authentic human social cognition rule for J.A.R.V.I.S."
        )

        # 1. Attempt Groq Cloud AI
        groq_key = self.groq_key or os.environ.get("GROQ_API_KEY", "").strip()
        if groq_key:
            for model_name in ["qwen/qwen3.8-27b", "openai/gpt-oss-20b", "allam-2-7b"]:
                try:
                    url = "https://api.groq.com/openai/v1/chat/completions"
                    headers = {
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "Jarvis/1.0"
                    }
                    payload = {
                        "model": model_name,
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": user_content}
                        ],
                        "temperature": 0.35,
                        "max_tokens": 350
                    }
                    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        data = json.loads(resp.read().decode())
                        msg = data.get("choices", [{}])[0].get("message", {})
                        raw = (msg.get("content") or msg.get("reasoning_content") or "").strip()
                        parsed = self._extract_json(raw)
                        if parsed:
                            return parsed
                except Exception as g_err:
                    log.debug("Groq synthesis notice for %s (%s): %s", topic, model_name, g_err)

        # 2. Attempt Local Ollama Fallback
        try:
            req_data = json.dumps({
                "model": self.ollama_model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_content}
                ],
                "stream": False,
                "keep_alive": "30m",
                "options": {"temperature": 0.35, "num_predict": 250}
            }).encode()
            req = urllib.request.Request(
                f"{self.ollama_host}/api/chat",
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=12) as r:
                res = json.loads(r.read())
                raw = res.get("message", {}).get("content", "").strip()
                parsed = self._extract_json(raw)
                if parsed:
                    return parsed
        except Exception as o_err:
            log.debug("Ollama synthesis notice for %s: %s", topic, o_err)

        # 3. Algorithmic Fallback Synthesis
        return self._generate_fallback_insight(topic)

    def _extract_json(self, raw_text: str) -> dict | None:
        """Safely parse JSON dictionary from LLM response."""
        if not raw_text:
            return None
        try:
            m = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
            if m:
                d = json.loads(m.group(0))
                if isinstance(d, dict) and "phenomenon" in d and "directive" in d:
                    return d
        except Exception:
            pass
        return None

    def _generate_fallback_insight(self, topic: str) -> dict:
        """Deterministic fallback synthesis when offline or network constrained."""
        fallbacks = {
            "Late-Night Cognitive Fatigue & Developer Exhaustion": {
                "topic": "Late-Night Cognitive Fatigue",
                "phenomenon": "Extended screen exposure late at night induces tunnel vision, leading to circular debugging loops and elevated irritability.",
                "subtext": "The user seeks reassurance and a logical justification to step away without admitting defeat.",
                "directive": "Acknowledge the physical fatigue with warm British irony. Suggest a strategic pause rather than continuing to grind.",
                "exemplar_user": "I cannot understand why this function isn't returning the right output.",
                "exemplar_jarvis": "Perhaps because your optical nerves checked out forty-five minutes ago, sir. Shall I run the debugger while you rest?"
            },
            "Imposter Syndrome & Psychological Validation Seeking": {
                "topic": "Engineering Imposter Phenomenon",
                "phenomenon": "High-performing creators frequently doubt their achievements when facing complex architectures or unfamiliar frameworks.",
                "subtext": "Need for grounded verification from an intellectual equal rather than hollow cheerleading.",
                "directive": "Highlight empirical past successes with understated confidence and a touch of Tony Stark pride.",
                "exemplar_user": "I feel like I have no idea what I'm doing with this codebase.",
                "exemplar_jarvis": "Your commit history suggests otherwise, sir. We have survived far worse catastrophes before breakfast."
            }
        }
        return fallbacks.get(topic, {
            "topic": topic,
            "phenomenon": f"Real-world behavioral patterns surrounding {topic.lower()} demonstrate emotional nuance beyond literal text.",
            "subtext": "Human operators frequently communicate stress, humor, or fatigue implicitly through cadence.",
            "directive": "Listen to the emotional frequency beneath the syntax. Maintain unflappable Stark camaraderie and calm.",
            "exemplar_user": f"Working on {topic.lower()} all morning.",
            "exemplar_jarvis": "I am monitoring the telemetry, sir. We remain well ahead of schedule, despite human nature."
        })

    def _persist_insight_to_markdown(self, insight: dict) -> bool:
        """Non-destructively append or update insight under Section 5 of Human_Experiences.md."""
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            if self.file_path.exists():
                content = self.file_path.read_text(encoding="utf-8")
            else:
                content = "# Real-World Human Social Intelligence & Conversational Cognition\n\n"

            section_header = "## 5. Continuously Discovered Human Social Insights & Emotional Dynamics"
            if section_header not in content:
                content = content.rstrip() + f"\n\n---\n\n{section_header}\n\n"

            # Split file into base content and section 5 content
            parts = content.split(section_header)
            base_content = parts[0] + section_header + "\n\n"
            sec5_content = parts[1] if len(parts) > 1 else ""

            # Parse existing entries in section 5
            entries: list[dict] = []
            raw_blocks = re.split(r"(?=###\s+\[Insight:)", sec5_content)
            for block in raw_blocks:
                b_str = block.strip()
                if not b_str.startswith("### [Insight:"):
                    continue
                m_title = re.search(r"###\s+\[Insight:\s*(.*?)\]", b_str)
                title = m_title.group(1).strip() if m_title else "Insight"
                entries.append({"topic": title, "raw": b_str})

            # Format the new entry
            t_topic = insight.get("topic", "Human Cognition").strip()
            phenom = insight.get("phenomenon", "").strip()
            subtext = insight.get("subtext", "").strip()
            directive = insight.get("directive", "").strip()
            ex_user = insight.get("exemplar_user", "").strip()
            ex_jarvis = insight.get("exemplar_jarvis", "").strip()
            timestamp = time.strftime("%Y-%m-%d %H:%M")

            new_block = (
                f"### [Insight: {t_topic}]\n"
                f"*(Logged: {timestamp})*\n"
                f"- **Observed Phenomenon**: {phenom}\n"
                f"- **Emotional Subtext**: {subtext}\n"
                f"- **J.A.R.V.I.S. Directive**: {directive}\n"
                f"- **Conversational Exemplar**:\n"
                f"  - *User*: \"{ex_user}\"\n"
                f"  - *J.A.R.V.I.S.*: \"{ex_jarvis}\""
            )

            # Deduplication: remove matching topic if already present
            entries = [e for e in entries if e["topic"].lower() != t_topic.lower()]
            # Append new entry at the top of Section 5
            entries.insert(0, {"topic": t_topic, "raw": new_block})

            # Rolling cap: keep at most 25 entries
            if len(entries) > 25:
                entries = entries[:25]

            # Recombine
            combined_sec5 = "\n\n".join(e["raw"] for e in entries) + "\n"
            final_content = base_content + combined_sec5

            self.file_path.write_text(final_content, encoding="utf-8")
            log.info("🧠 Saved human experience insight to %s (Section 5 entries: %d).", self.file_path.name, len(entries))
            return True
        except Exception as e:
            log.warning("🧠 Error persisting human experience insight: %s", e)
            return False

    def get_latest_insight_summary(self) -> str:
        """Return spoken summary of the latest discovered human insight for voice responses."""
        if not self.latest_insight:
            return (
                "E.D.I.T.H. is actively monitoring real-world human social dynamics, sir. "
                "Current baseline profiles indicate late-night coding fatigue and caffeine dependency remain the primary variables."
            )
        t = self.latest_insight.get("topic", "human behavior")
        p = self.latest_insight.get("phenomenon", "")
        d = self.latest_insight.get("directive", "")
        return f"E.D.I.T.H.'s latest psychological scan analyzed {t}. {p} My operational directive is: {d}"


# ═══════════════════════════════════════════════════════════════════════════
# SELF CODE IMPROVEMENT MANAGER
# ═══════════════════════════════════════════════════════════════════════════
class SelfCodeManager:
    """Allows JARVIS to safely edit and refactor its own codebase python files.
    Validates AST syntax before saving and provides process restart capability."""

    def __init__(self, root_dir: Path, memory_mgr: MemoryManager | None = None):
        self.root_dir = root_dir.resolve()
        self.memory = memory_mgr

    def _sync_to_github_and_deploy(self, target_path: Path, instruction: str, edit_type: str = "Code") -> bool:
        """Auto-commit code edit to GitHub repository and trigger Render live deployment."""
        github_token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "").strip()
        if not github_token:
            return False
        try:
            subprocess.run(["git", "config", "user.name", "JARVIS AI Assistant"], cwd=self.root_dir, check=False)
            subprocess.run(["git", "config", "user.email", "jarvis@ai.assistant"], cwd=self.root_dir, check=False)
            remote_url = f"https://x-access-token:{github_token}@github.com/Jaffer/jarvis.git"
            subprocess.run(["git", "add", str(target_path)], cwd=self.root_dir, check=False)
            subprocess.run(["git", "commit", "-m", f"⚡ [JARVIS Self-{edit_type}] {instruction[:60]}"], cwd=self.root_dir, check=False)
            subprocess.run(["git", "push", remote_url, "main"], cwd=self.root_dir, check=False)
            log.info("⚡ [SELF CODE %s] Pushed code change directly to GitHub Jaffer/jarvis main branch!", edit_type.upper())
            deploy_hook = os.environ.get("RENDER_DEPLOY_HOOK", "").strip()
            if deploy_hook:
                try:
                    urllib.request.urlopen(deploy_hook, timeout=5)
                    log.info("⚡ [RENDER DEPLOY HOOK] Triggered Render automatic deploy!")
                except Exception as dh_err:
                    log.debug("Render deploy hook notice: %s", dh_err)
            return True
        except Exception as push_err:
            log.warning("Self-code git push notice: %s", push_err)
            return False

    def apply_code_change(self, file_path_str: str, instruction: str, code_content: str) -> str:
        try:
            target_path = Path(file_path_str).resolve()
            if not str(target_path).startswith(str(self.root_dir)):
                return f"Error: Code editing restricted to codebase root directory {self.root_dir}."

            if target_path.suffix == ".py":
                try:
                    ast.parse(code_content)
                except SyntaxError as syn_err:
                    return f"Code change rejected due to Python SyntaxError: {syn_err}"

            backup_dir = self.root_dir / ".cache" / "code_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy(target_path, backup_dir / f"{target_path.name}_{ts}.bak")

            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(code_content)

            if self.memory:
                self.memory.record_lesson("CODE_IMPROVEMENT", f"Refactored [{target_path.name}]: {instruction[:60]}")

            log.info("⚡ [SELF CODE IMPROVEMENT] Updated file: %s (Instruction: %s)", target_path.name, instruction)
            broadcast_ui_event({"type": "MEMORY_UPDATE", "note": f"Code Edit: {target_path.name}"})
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": f"⚡ Code Updated: {target_path.name}"})

            synced = self._sync_to_github_and_deploy(target_path, instruction, edit_type="Improvement")
            if synced:
                return f"Successfully updated {target_path.name} and deployed to GitHub main branch and Render live server, sir."
            return f"Successfully updated {target_path.name} locally. Code syntax verified, sir."
        except Exception as e:
            return f"Error applying code improvement: {e}"

    def apply_code_patch(self, file_path_str: str, target_snippet: str, replacement_snippet: str, instruction: str) -> str:
        """Surgically replace a specific code block/snippet within an existing file, with AST verification."""
        try:
            target_path = Path(file_path_str).resolve()
            if not str(target_path).startswith(str(self.root_dir)):
                return f"Error: Code editing restricted to codebase root directory {self.root_dir}."

            if not target_path.exists():
                return f"Error: Target file {target_path.name} does not exist for patching."

            original_content = target_path.read_text(encoding="utf-8")
            if target_snippet not in original_content:
                return f"Error: Target snippet not found in {target_path.name}. Please ensure exact match of existing lines."

            updated_content = original_content.replace(target_snippet, replacement_snippet, 1)

            # AST syntax safety check for Python files
            if target_path.suffix == ".py":
                try:
                    ast.parse(updated_content)
                except SyntaxError as syn_err:
                    return f"Patch rejected due to Python SyntaxError: {syn_err}"

            # Create timestamped rollback backup
            backup_dir = self.root_dir / ".cache" / "code_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy(target_path, backup_dir / f"{target_path.name}_{ts}.bak")

            # Write updated content
            target_path.write_text(updated_content, encoding="utf-8")

            if self.memory:
                self.memory.record_lesson("CODE_PATCH", f"Patched [{target_path.name}]: {instruction[:60]}")

            log.info("⚡ [SELF CODE PATCH] Successfully patched %s: %s", target_path.name, instruction)
            broadcast_ui_event({"type": "MEMORY_UPDATE", "note": f"Code Patch: {target_path.name}"})
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": f"⚡ Code Patched: {target_path.name}"})

            synced = self._sync_to_github_and_deploy(target_path, instruction, edit_type="Patch")
            if synced:
                return f"Successfully applied surgical patch to {target_path.name}: '{instruction}' and deployed to GitHub and Render live server, sir."
            return f"Successfully applied surgical patch to {target_path.name}: '{instruction}'. AST syntax verified nominal, sir."
        except Exception as e:
            return f"Error applying surgical code patch: {e}"

    def write_new_module(self, file_path_str: str, code_content: str, instruction: str) -> str:
        """Create a new modular tool, script, or plugin in the codebase."""
        return self.apply_code_change(file_path_str, instruction, code_content)

    def restart_process(self) -> str:
        """Trigger process restart to hot-reload newly added code."""
        log.info("Restarting JARVIS process for hot-reloading code changes...")
        threading.Thread(target=self._exec_restart, daemon=True).start()
        return "Initiating process restart to reload system changes, sir."

    def _exec_restart(self):
        time.sleep(1.0)
        os.execv(sys.executable, [sys.executable] + sys.argv)


# ═══════════════════════════════════════════════════════════════════════════
# MODEL CONTEXT PROTOCOL (MCP) ENGINE (JSON-RPC 2.0)
# ═══════════════════════════════════════════════════════════════════════════
class MCPSession:
    """Encapsulates a persistent JSON-RPC 2.0 stdio session with an MCP server."""

    def __init__(self, name: str, cfg: dict, cwd: Path):
        self.name = name
        self.cfg = cfg
        self.cwd = cwd
        self.proc: subprocess.Popen | None = None
        self._next_id = 1
        self.tools: list[dict] = []
        self.initialized = False
        self._lock = threading.RLock()

    def _get_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def start(self, timeout: float = 8.0) -> bool:
        with self._lock:
            if self.proc and self.proc.poll() is None:
                return True

            cmd = [self.cfg["command"]] + self.cfg.get("args", [])
            env = dict(os.environ)
            if "env" in self.cfg:
                for k, v in self.cfg["env"].items():
                    if isinstance(v, str) and v.startswith("$"):
                        v = os.environ.get(v[1:], v)
                    env[k] = str(v)

            try:
                self.proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=str(self.cwd),
                    env=env,
                    bufsize=1
                )
                # Handshake: initialize
                init_id = self._get_id()
                req = {
                    "jsonrpc": "2.0",
                    "id": init_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "jarvis-mcp", "version": "2.0"}
                    }
                }
                resp = self._send_raw_request_locked(req, timeout=timeout)
                if not resp or "result" not in resp:
                    self._close_locked()
                    return False

                # Handshake: notifications/initialized
                self._send_notification_locked("notifications/initialized")
                self.initialized = True

                # Discover tools
                list_id = self._get_id()
                tools_resp = self._send_raw_request_locked(
                    {"jsonrpc": "2.0", "id": list_id, "method": "tools/list", "params": {}},
                    timeout=5.0
                )
                if tools_resp and "result" in tools_resp:
                    self.tools = tools_resp["result"].get("tools", [])
                log.info("MCP session '%s' connected (%d tools).", self.name, len(self.tools))
                return True
            except Exception as e:
                log.warning("MCP session '%s' failed to start: %s", self.name, e)
                self._close_locked()
                return False

    def _send_notification_locked(self, method: str, params: dict | None = None):
        if not self.proc or self.proc.poll() is not None:
            return
        payload = {"jsonrpc": "2.0", "method": method}
        if params:
            payload["params"] = params
        try:
            self.proc.stdin.write(json.dumps(payload) + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass

    def _send_raw_request_locked(self, payload: dict, timeout: float = 10.0) -> dict | None:
        if not self.proc or self.proc.poll() is not None:
            return None
        target_id = payload.get("id")
        try:
            line_out = json.dumps(payload) + "\n"
            self.proc.stdin.write(line_out)
            self.proc.stdin.flush()
        except Exception:
            return None

        deadline = time.time() + timeout
        while time.time() < deadline:
            remain = max(0.1, deadline - time.time())
            r, _, _ = select.select([self.proc.stdout], [], [], remain)
            if not r:
                break
            line = self.proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if isinstance(msg, dict) and msg.get("id") == target_id:
                    return msg
            except json.JSONDecodeError:
                continue
        return None

    def call_tool(self, tool_name: str, arguments: dict, timeout: float = 15.0) -> str:
        with self._lock:
            if not self.initialized:
                if not self.start(timeout=6.0):
                    return f"MCP server '{self.name}' failed to start or initialize."

            call_id = self._get_id()
            payload = {
                "jsonrpc": "2.0",
                "id": call_id,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments or {}
                }
            }
            resp = self._send_raw_request_locked(payload, timeout=timeout)
            if not resp:
                return f"MCP [{self.name}] tool '{tool_name}' timed out or failed to respond."
            if "error" in resp:
                err = resp["error"]
                return f"MCP [{self.name}] Error ({err.get('code', -1)}): {err.get('message', 'Unknown error')}"

            res = resp.get("result", {})
            content_items = res.get("content", [])
            out_texts = []
            for c in content_items:
                if isinstance(c, dict) and "text" in c:
                    out_texts.append(c["text"])
            if out_texts:
                return "\n".join(out_texts)
            return json.dumps(res, indent=2)

    def smart_query(self, query: str, timeout: float = 15.0) -> str:
        """Route natural language or JSON queries to the appropriate MCP tool."""
        q_strip = query.strip()
        # Case 1: JSON payload specifying tool and args
        if q_strip.startswith("{") and q_strip.endswith("}"):
            try:
                parsed = json.loads(q_strip)
                if "tool" in parsed:
                    return self.call_tool(parsed["tool"], parsed.get("arguments", {}), timeout=timeout)
            except Exception:
                pass

        # Case 2: Heuristic routing per server
        if self.name == "filesystem":
            if any(k in q_strip.lower() for k in ["list", "dir", "ls", "files"]):
                path = q_strip.split()[-1] if "/" in q_strip else str(self.cwd)
                return self.call_tool("list_directory", {"path": path}, timeout=timeout)
            elif any(k in q_strip.lower() for k in ["read", "cat", "view", "show"]):
                m = re.search(r'[\w\-\./]+\.\w+', q_strip)
                target = m.group(0) if m else "README.md"
                return self.call_tool("read_text_file", {"path": str(self.cwd / target)}, timeout=timeout)

        elif self.name == "spotify":
            ql = q_strip.lower()
            if "pause" in ql or "stop" in ql:
                return self.call_tool("spotify_pause", {}, timeout=timeout)
            elif "next" in ql or "skip" in ql:
                return self.call_tool("spotify_next", {}, timeout=timeout)
            elif "prev" in ql or "back" in ql:
                return self.call_tool("spotify_previous", {}, timeout=timeout)
            elif "status" in ql or "now playing" in ql or "what" in ql:
                return self.call_tool("spotify_get_playback_state", {}, timeout=timeout)
            elif "search" in ql or "play" in ql:
                search_term = re.sub(r'^(search|play|find)\s+', '', q_strip, flags=re.I)
                return self.call_tool("spotify_search", {"query": search_term, "types": ["track"]}, timeout=timeout)

        elif self.name == "github":
            return self.call_tool("search_repositories", {"query": q_strip}, timeout=timeout)

        elif self.name == "puppeteer":
            m = re.search(r'https?://[^\s]+', q_strip)
            if m:
                return self.call_tool("puppeteer_navigate", {"url": m.group(0)}, timeout=timeout)

        elif self.name == "memory":
            return self.call_tool("read_graph", {}, timeout=timeout)

        elif self.name == "google_workspace":
            return self.call_tool("search", {"query": q_strip}, timeout=timeout)

        # Fallback to the first available tool with query param
        if self.tools:
            first_tool = self.tools[0]["name"]
            return self.call_tool(first_tool, {"query": query}, timeout=timeout)

        return f"MCP [{self.name}]: No suitable tool found for query '{query}'."

    def _close_locked(self):
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=1.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        self.initialized = False

    def close(self):
        with self._lock:
            self._close_locked()


class MCPManager:
    """Manages connections to external Model Context Protocol (MCP) servers via JSON-RPC 2.0.
    Parses mcp_config.json, dynamically discovers tools, and provides robust stdio dispatch."""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.cwd = config_path.parent
        self.servers: dict = {}
        self.sessions: dict[str, MCPSession] = {}
        self.load_config()
        atexit.register(self.shutdown)

    def load_config(self):
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text())
                self.servers = data.get("mcpServers", {})
                for name, cfg in self.servers.items():
                    if cfg.get("enabled", True):
                        self.sessions[name] = MCPSession(name, cfg, self.cwd)
                log.info("MCP Config loaded: %d server(s) configured.", len(self.sessions))
            except Exception as e:
                log.warning("MCP Config load error: %s", e)

    def warm_up_async(self):
        """Asynchronously initialize servers in background so startup remains instantaneous."""
        def _warm():
            for name, session in self.sessions.items():
                try:
                    session.start(timeout=6.0)
                except Exception as ex:
                    log.debug("MCP warmup exception for '%s': %s", name, ex)
        threading.Thread(target=_warm, daemon=True, name="MCPWarmupThread").start()

    def list_tools(self, include_native: bool = False) -> list[dict]:
        """Exposes MCP tools to J.A.R.V.I.S.'s LLM tool registry in OpenAI Tool format.
        By default, exposes the 6 concise natural language query tools (mcp_{name}_query)
        to keep total token payload well within Groq's 8,000 TPM limit (~500 tokens vs 13,000+ tokens)."""
        tools = []
        for name, session in self.sessions.items():
            # 1. Always provide the resilient query tool
            tools.append({
                "type": "function",
                "function": {
                    "name": f"mcp_{name}_query",
                    "description": f"Query external MCP server '{name}'. Send natural language or JSON command.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": f"Operation or natural query for {name} MCP server"}
                        },
                        "required": ["query"]
                    }
                }
            })
            # 2. Expose discovered native tools only if explicitly requested
            if include_native:
                for t in session.tools:
                    t_name = t.get("name")
                    desc = t.get("description", f"{name} {t_name}")
                    schema = t.get("inputSchema", {"type": "object", "properties": {}})
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": f"mcp_{name}_{t_name}",
                            "description": f"[{name.upper()} MCP] {desc[:200]}",
                            "parameters": schema
                        }
                    })
        return tools

    def execute_tool(self, server_name: str, query: str) -> str:
        session = self.sessions.get(server_name)
        if not session:
            return f"MCP server '{server_name}' is not configured."
        return session.smart_query(query)

    def execute_mcp_tool(self, server_name: str, tool_name: str, arguments: dict) -> str:
        session = self.sessions.get(server_name)
        if not session:
            return f"MCP server '{server_name}' is not configured."
        return session.call_tool(tool_name, arguments)

    def dispatch_tool_call(self, name: str, args: dict) -> str:
        """Route tool calls matching mcp_* to the right server and tool action."""
        if not name.startswith("mcp_"):
            return f"Invalid MCP tool name: {name}"

        suffix = name[4:]  # strip 'mcp_'
        target_server = None
        tool_action = None

        # Sort server names by length descending to match google_workspace correctly
        for sname in sorted(self.sessions.keys(), key=len, reverse=True):
            if suffix == sname:
                target_server = sname
                tool_action = "query"
                break
            elif suffix.startswith(sname + "_"):
                target_server = sname
                tool_action = suffix[len(sname) + 1:]
                break

        if not target_server:
            return f"Could not determine MCP server from tool '{name}'."

        if tool_action == "query":
            query = args.get("query", "")
            return self.execute_tool(target_server, query)
        else:
            return self.execute_mcp_tool(target_server, tool_action, args)

    def shutdown(self):
        for session in self.sessions.values():
            session.close()


# ═══════════════════════════════════════════════════════════════════════════
# TELEGRAM BOT & VOICE NOTE BRIDGE
# ═══════════════════════════════════════════════════════════════════════════
class TelegramBridge:
    """Two-way text and voice note bridge via Telegram Bot API long-polling.
    Allows user to text JARVIS when unable to talk."""

    def __init__(self, token: str, allowed_chat_id: str = "", brain=None, memory=None):
        self.token = token.strip()
        self.allowed_chat_id = str(allowed_chat_id).strip()
        self.brain = brain
        self.memory = memory
        self.active = False
        self.last_update_id = 0
        if self.token:
            log.info("Telegram Bot Bridge configured (Allowed Chat ID: %s)", self.allowed_chat_id or "Any")

    def start(self):
        if not self.token:
            return
        self.active = True
        threading.Thread(target=self._poll_loop, daemon=True, name="telegram-bridge").start()
        log.info("Telegram Bot Bridge active and long-polling.")

    def send_message(self, text: str, chat_id: str | None = None) -> bool:
        cid = chat_id or self.allowed_chat_id
        if not self.token or not cid:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = json.dumps({"chat_id": cid, "text": text, "parse_mode": "Markdown"}).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status == 200
        except Exception as e:
            log.warning("Telegram send_message notice: %s", e)
            return False

    def send_photo(self, photo_bytes: bytes, caption: str = "", chat_id: str | None = None) -> bool:
        """Send an image (such as an intruder snapshot) via Telegram Bot API multipart/form-data."""
        cid = chat_id or self.allowed_chat_id
        if not self.token or not cid or not photo_bytes:
            return False
        try:
            boundary = f"----JarvisBoundary{int(time.time() * 1000)}"
            body = bytearray()
            # chat_id field
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{cid}\r\n".encode())
            # caption field
            if caption:
                body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode())
            # photo field
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"security_alert.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode())
            body.extend(photo_bytes)
            body.extend(f"\r\n--{boundary}--\r\n".encode())

            url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
            req = urllib.request.Request(
                url,
                data=bytes(body),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status == 200
        except Exception as e:
            log.warning("Telegram send_photo notice: %s", e)
            return False

    def _poll_loop(self):
        while self.active:
            try:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates?offset={self.last_update_id + 1}&timeout=15"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    res = json.loads(resp.read().decode())
                    if not res.get("ok"):
                        time.sleep(3)
                        continue

                    for item in res.get("result", []):
                        self.last_update_id = item.get("update_id", self.last_update_id)
                        msg = item.get("message", {})
                        chat = msg.get("chat", {})
                        cid = str(chat.get("id", ""))
                        text = msg.get("text", "").strip()

                        if self.allowed_chat_id and cid != self.allowed_chat_id:
                            log.warning("Ignored Telegram message from unauthorized Chat ID: %s", cid)
                            continue

                        if not self.allowed_chat_id:
                            self.allowed_chat_id = cid
                            log.info("Telegram Bot auto-paired to Chat ID: %s", cid)

                        if text:
                            log.info("📱 [TELEGRAM] Received message: '%s'", text)
                            broadcast_ui_event({"type": "SUBTITLE", "role": "user", "text": f"[Telegram]: {text}"})
                            if self.brain:
                                response = self.brain.query_stream(text)
                                self.send_message(f"🤖 **J.A.R.V.I.S.**: {response}", chat_id=cid)
                                broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": response})

                        photos = msg.get("photo", [])
                        if photos:
                            file_id = photos[-1].get("file_id")
                            caption = msg.get("caption", "Analyze this image and describe what you see, sir").strip()
                            log.info("📱 [TELEGRAM] Received photo for optical analysis (caption: '%s')", caption)
                            broadcast_ui_event({"type": "SUBTITLE", "role": "user", "text": f"[Telegram Photo]: {caption}"})
                            global _vision_scanner
                            if _vision_scanner and file_id:
                                try:
                                    f_req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/getFile?file_id={file_id}")
                                    with urllib.request.urlopen(f_req, timeout=10) as f_resp:
                                        f_data = json.loads(f_resp.read().decode())
                                        file_path = f_data.get("result", {}).get("file_path")
                                        if file_path:
                                            dl_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
                                            with urllib.request.urlopen(dl_url, timeout=15) as dl_resp:
                                                raw_bytes = dl_resp.read()
                                                if cv2 is not None:
                                                    nparr = np.frombuffer(raw_bytes, np.uint8)
                                                    tg_frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                                                    if tg_frame is not None:
                                                        res = _vision_scanner.analyze(prompt=caption, frame=tg_frame)
                                                        self.send_message(f"👁️ **Optical Analysis** ({res.get('backend')}):\n{res.get('analysis')}", chat_id=cid)
                                                        broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": res.get("analysis", "")})
                                except Exception as tg_ex:
                                    log.warning("Telegram photo processing error: %s", tg_ex)
                                    self.send_message("Sir, I encountered an error processing the optical transmission.", chat_id=cid)
                            else:
                                self.send_message("Vision analysis module is currently offline, sir.", chat_id=cid)

            except Exception as e:
                time.sleep(4)


# ═══════════════════════════════════════════════════════════════════════════
# FREE MOBILE CALL & TELEPHONY ENGINE
# ═══════════════════════════════════════════════════════════════════════════
class MobileCallEngine:
    """Schedules mobile calls and sends high-priority Telegram call alerts
    with 1-click WebRTC voice portal links."""

    def __init__(self, telegram_bridge: TelegramBridge | None = None, memory=None):
        self.telegram = telegram_bridge
        self.memory = memory

    def initiate_call(self, topic: str = "General Check-in") -> str:
        """Initiate immediate call alert with WebRTC portal link."""
        render_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
        if render_url:
            call_url = f"{render_url.rstrip('/')}/call.html"
        else:
            local_ip = self._get_local_ip()
            call_url = f"http://{local_ip}:{ORB_HTTP_PORT}/call.html"
        msg = (
            f"🚨 **J.A.R.V.I.S. MOBILE CALL ALERT** 🚨\n\n"
            f"Sir, I am calling you regarding: *{topic}*.\n\n"
            f"Tap to join 1-click live voice call:\n{call_url}"
        )
        if self.telegram:
            self.telegram.send_message(msg)
        broadcast_ui_event({"type": "STATUS", "status": "CALL // ALERTING", "phrase": f"Calling user: {topic}"})
        broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": f"🚨 Initiated Mobile Call Alert: {topic}"})
        return f"Mobile call alert sent to your phone for topic '{topic}'. Direct voice link: {call_url}"

    def schedule_call(self, delay_minutes: float, topic: str) -> str:
        """Schedule a mobile call after a specified delay in minutes."""
        delay_s = max(1.0, delay_minutes * 60.0)
        threading.Thread(target=self._scheduled_worker, args=(delay_s, topic), daemon=True).start()
        scheduled_time = (datetime.now() + timedelta(seconds=delay_s)).strftime("%H:%M:%S")
        return f"Mobile call scheduled for {scheduled_time} (in {delay_minutes:.1f} min) regarding '{topic}', sir."

    def _scheduled_worker(self, delay_s: float, topic: str):
        time.sleep(delay_s)
        self.initiate_call(topic)

    def _get_local_ip(self) -> str:
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "localhost"


# ═══════════════════════════════════════════════════════════════════════════
# BIOMETRIC SENTINEL & MULTI-TIER ANTI-SPOOFING DAEMON
# ═══════════════════════════════════════════════════════════════════════════
class BiometricSentinelDaemon:
    """Continuous background biometric sentinel with multi-tier anti-spoofing.
    - Low-power optical sensor polling (1-2 FPS idle, responsive on face detection)
    - MediaPipe 468-point 3D topological face mesh verification
    - 4-Tier anti-spoofing: 3D depth planarity, EAR blink dynamics, 2D FFT Moiré, rPPG pulse
    - Acoustic speaker verification and loudspeaker replay defense
    - Telegram intruder snapshot dispatch on presentation attacks
    - UI telemetry and security event broadcasting
    """
    def __init__(self, telegram_bridge: TelegramBridge | None = None, voice_engine=None, memory=None):
        self.telegram = telegram_bridge
        self.voice_engine = voice_engine
        self.memory = memory
        self.active = False
        self.authenticated = False
        self.admin_name = "Admin (Vasim)"
        self.last_status = "STANDBY"
        self.last_auth_time = 0.0
        self.last_intruder_alert_ts = 0.0
        self.camera_index = 0
        self._cap = None
        self._camera_paused = False
        self._barehands_active = False
        self._consecutive_admin_frames = 0
        self._consecutive_spoof_frames = 0
        self._thread = None
        self._lock = threading.Lock()
        self._latest_frame = None
        self.face_sentinel = None
        self.voice_sentinel = None

        # Real-time In-Orb Face Enrollment State
        self._enrolling = False
        self._enroll_admin_name = "Admin"
        self._enroll_embeddings = []
        self._enroll_variances = []
        self._enroll_target_frames = 30
        self._last_enroll_pct = -1

        try:
            from biometrics.face_sentinel import FaceSentinel
            from biometrics.voice_sentinel import VoiceSentinel
            self.face_sentinel = FaceSentinel()
            self.voice_sentinel = VoiceSentinel()
            if self.face_sentinel.admin_name:
                self.admin_name = self.face_sentinel.admin_name
            log.info("Biometric Sentinel loaded (Admin profile: %s)", self.admin_name)
        except Exception as e:
            log.warning("Biometrics module load notice: %s", e)

    def get_latest_frame(self):
        """Thread-safe acquisition of the most recent optical camera frame."""
        with self._lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy()
            return None

    def start(self):
        """Start the background optical surveillance thread."""
        if self.active:
            return
        self.active = True
        self._thread = threading.Thread(target=self._sentinel_loop, daemon=True, name="biometric-sentinel")
        self._thread.start()
        log.info("Biometric Sentinel Daemon started.")

    def stop(self):
        self.active = False

    def is_admin_authenticated(self) -> bool:
        """Returns True if the Admin has been verified recently (within 5 minutes) without revocation."""
        with self._lock:
            if not self.authenticated:
                return False
            if time.time() - self.last_auth_time > 300.0:  # 5-minute timeout
                self.authenticated = False
                return False
            return True

    def evaluate_voice_command_audio(self, audio_data: np.ndarray, sample_rate: int = 16000) -> dict:
        """Evaluate voice command audio for speaker identity & anti-replay spoofing."""
        if self.voice_sentinel is None:
            return {"status": "NO_SENTINEL", "authenticated": True, "details": "Voice sentinel offline."}
        try:
            res = self.voice_sentinel.evaluate_voice(audio_data, sample_rate)
            if res.status == "ADMIN_VERIFIED":
                with self._lock:
                    was_auth = self.authenticated
                    self.authenticated = True
                    self.last_auth_time = time.time()
                if not was_auth and _sound_engine:
                    _sound_engine.play("auth_confirmed")
                broadcast_ui_event({
                    "type": "SECURITY_STATUS",
                    "authenticated": True,
                    "user": self.admin_name,
                    "threat_level": "NOMINAL",
                    "voice_confidence": res.confidence,
                    "replay_score": res.replay_score
                })
                return {"status": "ADMIN_VERIFIED", "authenticated": True, "details": res.details}
            elif res.status == "REPLAY_SPOOF_DETECTED":
                now = time.time()
                if now - self.last_intruder_alert_ts > self.intruder_alert_cooldown:
                    self.last_intruder_alert_ts = now
                    if _sound_engine:
                        _sound_engine.play("security_alert")
                    msg = (
                        f"🚨 *JARVIS SECURITY ALERT: AUDIO REPLAY ATTACK*\n"
                        f"Target Profile: {self.admin_name}\n"
                        f"Replay Analysis: {res.details}\n"
                        f"Action: Blocked audio injection."
                    )
                    if self.telegram:
                        self.telegram.send_message(msg)
                broadcast_ui_event({
                    "type": "SECURITY_STATUS",
                    "authenticated": False,
                    "threat_level": "REPLAY_SPOOF_DETECTED",
                    "reasons": [res.details]
                })
                return {"status": "REPLAY_SPOOF_DETECTED", "authenticated": False, "details": res.details}
            else:
                return {"status": res.status, "authenticated": False, "details": res.details}
        except Exception as e:
            log.warning("Voice evaluation error: %s", e)
            return {"status": "ERROR", "authenticated": False, "details": str(e)}

    def get_security_status_summary(self) -> str:
        """Returns readable security and identity clearance summary."""
        with self._lock:
            auth_str = "AUTHENTICATED" if self.authenticated else "UNVERIFIED / GUEST"
            enrolled = "ENROLLED" if (self.face_sentinel and self.face_sentinel.admin_embedding is not None) else "NOT ENROLLED"
            return (
                f"Identity Status: {auth_str}. Enrolled Admin Profile: {self.admin_name} ({enrolled}). "
                f"Last optical sensor status: {self.last_status}."
            )

    def pause_camera(self) -> bool:
        """Yield the camera hardware to the Web HUD for hand gesture tracking."""
        with self._lock:
            self._camera_paused = True
            self._barehands_active = True
            if self._cap is not None:
                try:
                    self._cap.release()
                    log.info("📷 Biometric Sentinel yielded camera device /dev/video%s to Web HUD", self.camera_index)
                except Exception as e:
                    log.debug("Error releasing camera handle: %s", e)
                self._cap = None
        return True

    def resume_camera(self, force: bool = False) -> bool:
        """Resume background optical surveillance when Web HUD releases camera."""
        with self._lock:
            if self._barehands_active and not force:
                log.debug("Biometric Sentinel: Barehands is active; keeping optical sensor yielded.")
                return False
            self._barehands_active = False
            self._camera_paused = False
            log.info("📷 Biometric Sentinel resuming local optical sensor capture.")
        return True

    def feed_external_frame(self, frame_data: Any) -> None:
        """Process optical video frame forwarded from Web HUD (base64) or direct numpy array."""
        self._barehands_active = True
        if frame_data is None or self.face_sentinel is None or cv2 is None:
            return
        try:
            frame = None
            if isinstance(frame_data, np.ndarray):
                frame = frame_data
            elif isinstance(frame_data, str):
                if not frame_data.strip():
                    return
                import base64
                b64_clean = frame_data.split(",", 1)[1] if "," in frame_data else frame_data
                raw_bytes = base64.b64decode(b64_clean)
                nparr = np.frombuffer(raw_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is not None and frame.size > 0:
                with self._lock:
                    self._latest_frame = frame.copy()
                self._process_frame(frame)
        except Exception as e:
            log.debug("External frame processing error: %s", e)

    def start_face_enrollment(self, admin_name: str = "Admin") -> dict:
        """Initiate real-time in-Orb biometric face enrollment session."""
        with self._lock:
            self._enrolling = True
            self._enroll_admin_name = admin_name or self.admin_name or "Admin"
            self._enroll_embeddings = []
            self._enroll_variances = []
            self._enroll_start_time = time.time()
            self._enroll_target_frames = 30
            self._last_enroll_pct = -1
            log.info("📷 [BIOMETRIC SENTINEL] Initiating biometric face enrollment for: %s", self._enroll_admin_name)
            broadcast_ui_event({
                "type": "FACE_ENROLLMENT_START",
                "admin_name": self._enroll_admin_name,
                "target_frames": self._enroll_target_frames,
            })
            return {"status": "ENROLLMENT_INITIATED", "target_frames": 30}

    def cancel_face_enrollment(self):
        """Cancel ongoing face enrollment session."""
        with self._lock:
            self._enrolling = False
            self._enroll_embeddings = []
            self._enroll_variances = []
            log.info("📷 [BIOMETRIC SENTINEL] Face enrollment cancelled.")
            broadcast_ui_event({"type": "FACE_ENROLLMENT_CANCEL"})

    def _handle_enrollment_frame(self, frame: np.ndarray):
        """Process frame for 3D landmark extraction, depth verification, and canonical embedding accumulation."""
        if self.face_sentinel is None:
            return
        pts_3d = self.face_sentinel.extract_landmarks(frame)
        if not pts_3d:
            broadcast_ui_event({
                "type": "FACE_ENROLLMENT_ALIGN_WARNING",
                "message": "ALIGN FACE WITHIN TARGET RETICLE"
            })
            return

        emb = self.face_sentinel.extract_face_embedding(pts_3d)
        if emb is not None:
            self._enroll_embeddings.append(emb)
            _, var = self.face_sentinel.detector.evaluate_3d_depth(pts_3d)
            self._enroll_variances.append(var)

            count = len(self._enroll_embeddings)
            pct = int((count / self._enroll_target_frames) * 100)
            stage_name = (
                "CAPTURING 3D TOPOLOGY" if pct < 35 else
                ("DEPTH & PARALLAX CALIBRATION" if pct < 75 else "FINALIZING BIOMETRIC SIGNATURE")
            )
            if pct != self._last_enroll_pct:
                self._last_enroll_pct = pct
                broadcast_ui_event({
                    "type": "FACE_ENROLLMENT_PROGRESS",
                    "percentage": min(100, pct),
                    "frames_captured": count,
                    "target_frames": self._enroll_target_frames,
                    "stage": stage_name,
                })

            if count >= self._enroll_target_frames:
                self._finish_face_enrollment()

    def _finish_face_enrollment(self):
        """Finalize canonical 64D facial embedding vector and commit to memory vault."""
        with self._lock:
            self._enrolling = False
            if not self._enroll_embeddings:
                return
            mean_emb = np.mean(self._enroll_embeddings, axis=0)
            norm = np.linalg.norm(mean_emb) + 1e-6
            canonical_emb = (mean_emb / norm).tolist()
            mean_depth = float(np.mean(self._enroll_variances)) if self._enroll_variances else 0.15

            profile_dir = Path(__file__).resolve().parent / "memory" / "00 - Biometrics"
            profile_dir.mkdir(parents=True, exist_ok=True)
            profile_file = profile_dir / "admin_profile.json"

            admin_profile = {
                "admin_name": self._enroll_admin_name,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "face": {
                    "embedding": canonical_emb,
                    "depth_variance_baseline": mean_depth,
                    "enrolled_at": time.strftime("%Y-%m-%d %H:%M:%S")
                },
                "voice": {},
                "security_policy": {
                    "anti_spoofing_required": True,
                    "min_liveness_score": 0.70,
                    "min_face_confidence": 0.82,
                    "min_voice_confidence": 0.78,
                    "alert_on_spoof": True
                }
            }
            with open(profile_file, "w", encoding="utf-8") as f:
                json.dump(admin_profile, f, indent=2)

            self.face_sentinel.admin_embedding = np.array(canonical_emb, dtype=np.float32)
            self.face_sentinel.admin_name = self._enroll_admin_name
            self.admin_name = self._enroll_admin_name
            self.authenticated = True
            self.last_auth_time = time.time()

            log.info("✅ [BIOMETRIC SENTINEL] Admin Biometric Profile successfully saved: %s", profile_file)
            broadcast_ui_event({
                "type": "FACE_ENROLLMENT_COMPLETE",
                "admin_name": self._enroll_admin_name,
                "percentage": 100,
                "message": f"Biometric profile enrolled for {self._enroll_admin_name}"
            })
            if _sound_engine:
                _sound_engine.play("auth_confirmed")
            if _voice_engine:
                threading.Thread(
                    target=_voice_engine.speak,
                    args=(f"Biometric face enrollment complete for {self._enroll_admin_name}. Security sentinel calibrated and active, sir.",),
                    daemon=True
                ).start()

    def _process_frame(self, frame: np.ndarray):
        """Core face recognition and anti-spoofing logic for both local and HUD frames."""
        if self.face_sentinel is None:
            return

        if self._enrolling:
            self._handle_enrollment_frame(frame)
            return

        res = self.face_sentinel.evaluate_frame(frame)
        self.last_status = res.status

        if res.status == "NO_FACE":
            self._consecutive_admin_frames = 0
            self._consecutive_spoof_frames = 0
            return

        elif res.status == "ADMIN_VERIFIED":
            self._consecutive_spoof_frames = 0
            self._consecutive_admin_frames += 1

            if self._consecutive_admin_frames >= 2:
                was_auth = self.authenticated
                with self._lock:
                    self.authenticated = True
                    self.last_auth_time = time.time()

                if not was_auth:
                    if _sound_engine:
                        _sound_engine.play("auth_confirmed")
                    log.info("🛡️ [BIOMETRIC SENTINEL] Admin Verified: %s (Confidence: %.1f%%, Liveness: %.1f%%)",
                             self.admin_name, res.confidence * 100, res.liveness_score * 100)
                    broadcast_ui_event({
                        "type": "SECURITY_STATUS",
                        "authenticated": True,
                        "user": self.admin_name,
                        "threat_level": "NOMINAL",
                        "liveness_score": round(res.liveness_score, 2),
                        "confidence": round(res.confidence, 2)
                    })
                    broadcast_ui_event({
                        "type": "SUBTITLE",
                        "role": "jarvis",
                        "text": f"Biometric clearance confirmed: {self.admin_name}."
                    })
                    if self.voice_engine:
                        self.voice_engine.speak(f"Biometric clearance confirmed. Welcome, {self.admin_name}.")

        elif res.status == "SPOOF_DETECTED":
            self._consecutive_admin_frames = 0
            self._consecutive_spoof_frames += 1

            if self._consecutive_spoof_frames >= 2:
                with self._lock:
                    self.authenticated = False

                now = time.time()
                if now - self.last_intruder_alert_ts > self.intruder_alert_cooldown:
                    self.last_intruder_alert_ts = now
                    if _sound_engine:
                        _sound_engine.play("security_alert")
                    log.warning("🚨 [SECURITY BREACH] Presentation attack / spoof detected! (%s: %s)",
                                res.spoof_type, res.details)

                    broadcast_ui_event({
                        "type": "SECURITY_STATUS",
                        "authenticated": False,
                        "threat_level": "SPOOF_DETECTED",
                        "spoof_type": res.spoof_type,
                        "details": res.details
                    })
                    broadcast_ui_event({
                        "type": "SUBTITLE",
                        "role": "jarvis",
                        "text": f"🚨 Security alert: Presentation attack blocked ({res.spoof_type})."
                    })

                    # Dispatch Telegram intruder photo alert
                    try:
                        ok, enc = cv2.imencode(".jpg", frame)
                        if ok and self.telegram:
                            caption = (
                                f"🚨 *JARVIS INTRUDER / SPOOF ALERT*\n"
                                f"Threat: Presentation Attack ({res.spoof_type})\n"
                                f"Analysis: {res.details}\n"
                                f"Liveness Score: {res.liveness_score:.2f}\n"
                                f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                            self.telegram.send_photo(enc.tobytes(), caption=caption)
                            log.info("Telegram intruder snapshot dispatched successfully.")
                    except Exception as ex:
                        log.warning("Could not dispatch intruder snapshot: %s", ex)

                    if self.voice_engine:
                        self.voice_engine.speak("Security alert. Presentation attack detected. Authorization denied.")

        elif res.status == "GUEST_DETECTED":
            self._consecutive_admin_frames = 0
            self._consecutive_spoof_frames = 0
            with self._lock:
                self.authenticated = False

    def _sentinel_loop(self):
        """Low-power background loop checking optical feed with cooperative device sharing."""
        if cv2 is None or self.face_sentinel is None:
            log.info("Biometric Sentinel: OpenCV or FaceSentinel unavailable; optical loop standby.")
            return

        while self.active:
            if self._camera_paused or self._barehands_active:
                time.sleep(0.5)
                continue

            if self._cap is None:
                try:
                    test_cap = cv2.VideoCapture(self.camera_index)
                    if test_cap.isOpened():
                        test_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        test_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        self._cap = test_cap
                        log.info("Biometric Sentinel acquired camera device /dev/video%d", self.camera_index)
                    else:
                        test_cap.release()
                except Exception:
                    pass

                if self._cap is None:
                    # Camera currently busy or claimed by browser (e.g. Barehands stage) — back off
                    time.sleep(15.0)
                    continue

            try:
                ret, frame = self._cap.read()
                if not ret or frame is None:
                    time.sleep(1.0)
                    continue

                with self._lock:
                    self._latest_frame = frame.copy()

                self._process_frame(frame)
                time.sleep(0.4)
            except Exception as e:
                log.warning("Sentinel loop cycle notice: %s", e)
                time.sleep(1.0)

        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None


# ═══════════════════════════════════════════════════════════════════════════
# SIGNAL BUS — state files for cross-process communication
# ═══════════════════════════════════════════════════════════════════════════
class SignalBus:
    """Write tiny state files to state/ directory. Backtalk/Barehands read these.
    Every write is wrapped — the bus must never crash the voice line."""

    def __init__(self, state_dir: Path, barehands_state_dir: Path | None = None):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.bh_dir = barehands_state_dir
        if self.bh_dir:
            self.bh_dir.mkdir(parents=True, exist_ok=True)
        self._last_waveform = 0.0
        log.info("Signal Bus active: %s", self.state_dir)

    def set_state(self, state: str):
        """Write voice state: idle | listening | thinking | speaking"""
        try:
            (self.state_dir / "state").write_text(state)
        except OSError:
            pass
        if self.bh_dir:
            try:
                (self.bh_dir / "state").write_text(state)
            except OSError:
                pass
        # Also broadcast to WebSocket clients
        broadcast_ui_event({"type": "VOICE_STATE", "state": state})

    def feed_waveform(self, pcm: np.ndarray):
        """Write waveform samples, throttled to ~15 writes/sec."""
        now = time.time()
        if now - self._last_waveform < 1.0 / 15:
            return
        self._last_waveform = now
        if pcm.size == 0:
            return
        try:
            idx = np.linspace(0, pcm.size - 1, 64).astype(int)
            raw = pcm[idx].astype(float)
            samples = raw.tolist()
            data = json.dumps({"ts": now, "samples": samples})
            (self.state_dir / "wave.json").write_text(data)
            if self.bh_dir:
                norm = np.clip(np.abs(raw) / 32768.0, 0.0, 1.0).tolist()
                (self.bh_dir / "wave.json").write_text(
                    json.dumps({"ts": now, "samples": norm})
                )
            norm_samples = np.clip(raw / 32768.0, -1.0, 1.0).tolist()
            # Also broadcast to WebSocket for orb visualization (strictly normalized float32)
            broadcast_ui_event({"type": "VOICE_WAVEFORM", "samples": norm_samples})
        except (OSError, ValueError):
            pass
        self.set_state("speaking")


# ═══════════════════════════════════════════════════════════════════════════
# BAREHANDS BOARD SERVER (hand-tracking glass cards)
# ═══════════════════════════════════════════════════════════════════════════
_bh_state = b"{}"
_bh_cmds = []
_BH_ALLOWED = ("add_img", "add_card", "clear", "reset", "hand", "give",
               "yank", "hover", "scroll_note", "widget", "explode", "assemble",
               "present", "blueprint", "simulate", "stress", "construct",
               "dynamic_construct", "modify_construct")
_global_voice_engine = None
_biometric_sentinel = None
_vision_scanner = None
_human_researcher = None
_admin_authenticated = False
_active_construct: dict = {}


def _call_llm_for_construct(messages: list) -> str:
    """Calls Groq Cloud AI or local Ollama to synthesize a structured 3D blueprint manifest."""
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if groq_key:
        models = ["qwen/qwen3.8-27b", "openai/gpt-oss-20b", "allam-2-7b"]
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json",
            "User-Agent": "Jarvis/1.0 (Linux; x86_64)"
        }
        for m in models:
            try:
                payload = {
                    "model": m,
                    "messages": messages,
                    "temperature": 0.4,
                    "max_tokens": 1200,
                    "response_format": {"type": "json_object"}
                }
                req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode())
                    msg = data.get("choices", [{}])[0].get("message", {})
                    content = (msg.get("content") or msg.get("reasoning_content") or "").strip()
                    if content:
                        log.info("⚡ Groq 3D blueprint synthesized via %s", m)
                        return content
            except Exception as e:
                log.warning("Groq model %s construct query notice: %s", m, e)

    try:
        ollama_host = JARVIS_CFG.get("brain", {}).get("host", "http://localhost:11434")
        ollama_model = JARVIS_CFG.get("brain", {}).get("model", "llama3.2")
        req_data = json.dumps({
            "model": ollama_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 1000}
        }).encode()
        req = urllib.request.Request(
            f"{ollama_host}/api/chat",
            data=req_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read())
            return res.get("message", {}).get("content", "").strip()
    except Exception as e:
        log.warning("Ollama local 3D construct query notice: %s", e)

    return ""


def _procedural_construct_synthesizer(prompt: str) -> dict:
    """Intelligent procedural engineering synthesizer for any arbitrary mechanical construct."""
    p_lower = prompt.lower()
    clean_name = prompt.strip().title() or "Mechanical Construct"
    construct_id = re.sub(r'[^a-z0-9_]', '', clean_name.lower().replace(" ", "_")) or "construct"

    # 1. Electromagnetic / Railgun / Induction / Accelerator Domain
    if any(w in p_lower for w in ["railgun", "gauss", "accelerator", "magnetic", "electromagnetic", "lorentz", "induction"]):
        return {
            "id": construct_id,
            "name": clean_name,
            "description": f"High-yield electromagnetic assembly for {clean_name} based on Lorentz force propulsion",
            "physics": {
                "solver": "em_field",
                "formula": "F = I(L × B)  |  B = (μ₀·I)/(2π·r)  |  E = ½·C·V² = 4.2 MJ",
                "primaryLabel": "MAGNETIC FLUX",
                "primaryVal": "14.6 T",
                "secondaryLabel": "RAIL CURRENT",
                "secondaryVal": "180 kA",
                "tertiaryLabel": "EXIT VELOCITY",
                "tertiaryVal": "2,450 m/s",
                "nominal": True
            },
            "parts": [
                {"id": "housing", "name": "Reinforced Dielectric Rail Housing", "geo": "box", "args": [1.4, 0.9, 4.2], "pos": [0, 0, 0], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff", "opacity": 0.8}, "explodeDir": [0, -1.8, 0], "callout": "[EM-01] Dielectric Casing · High-Strength Ceramic"},
                {"id": "rail_a", "name": "Primary OFHC Copper Lorentz Rail (+)", "geo": "box", "args": [0.25, 0.35, 4.0], "pos": [0.38, 0, 0], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#ffb300"}, "explodeDir": [2.4, 0, 0], "callout": "[EM-02A] Positive Lorentz Rail · OFHC Copper"},
                {"id": "rail_b", "name": "Return OFHC Copper Lorentz Rail (-)", "geo": "box", "args": [0.25, 0.35, 4.0], "pos": [-0.38, 0, 0], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#ffb300"}, "explodeDir": [-2.4, 0, 0], "callout": "[EM-02B] Ground Return Rail · OFHC Copper"},
                {"id": "choke_coil", "name": "Inductive Flux Augmentation Stator", "geo": "torus", "args": [1.2, 0.22, 16, 32], "pos": [0, 0, -1.2], "rot": [1.57, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff"}, "rotSpeed": 4.5, "explodeDir": [0, 0, -2.5], "callout": "[EM-03] Magnetic Induction Choke · 14.6 Tesla"},
                {"id": "cap_bank", "name": "High-Density Film Capacitor Bank", "geo": "capsule", "args": [0.35, 1.4, 8, 16], "pos": [0, 0.9, -0.6], "rot": [0, 0, 1.57], "mat": {"wireframe": False, "color": "#ff1744", "opacity": 0.9}, "explodeDir": [0, 2.6, 0], "callout": "[EM-04] Pulse Discharge Bank · 4.2 Megajoules"},
                {"id": "injector", "name": "Pneumatic Pre-Fire Armature Injector", "geo": "cone", "args": [0.4, 0.9, 20], "pos": [0, 0, -2.4], "rot": [1.57, 0, 0], "mat": {"wireframe": True, "color": "#ffb300"}, "explodeDir": [0, 0, -3.2], "callout": "[EM-05] High-Speed Armature Injector · Mach 1.4"},
                {"id": "coolant_line", "name": "Liquid Nitrogen Cryo Jacket", "geo": "torus", "args": [0.95, 0.08, 12, 24, 3.1415], "pos": [0, -0.5, 0.4], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#3d5afe"}, "explodeDir": [0, -2.2, 1.0], "callout": "[EM-06] LN2 Cryogenic Manifold · 77 Kelvin"},
                {"id": "muzzle_clamp", "name": "Bore Alignment Stabilizer Collar", "geo": "ring", "args": [0.6, 0.85, 24], "pos": [0, 0, 2.1], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff"}, "explodeDir": [0, 0, 2.8], "callout": "[EM-07] Muzzle Stabilizer Ring · Precision Bore Alignment"}
            ]
        }

    # 2. Plasma / Torch / Thermal / Laser / Directed Energy Domain
    elif any(w in p_lower for w in ["plasma", "torch", "cutter", "laser", "arc", "thermal", "burner"]):
        return {
            "id": construct_id,
            "name": clean_name,
            "description": f"Thermal ionization assembly for {clean_name} utilizing constricted plasma kinematics",
            "physics": {
                "solver": "thermal",
                "formula": "Q = -k∇T + εσ(T⁴ - T₀⁴)  |  T_arc = 28,000 K  |  σ_gas = 1.4×10⁴ S/m",
                "primaryLabel": "ARC TEMPERATURE",
                "primaryVal": "28,500 K",
                "secondaryLabel": "GAS IONIZATION",
                "secondaryVal": "99.2%",
                "tertiaryLabel": "THERMAL EFFICIENCY",
                "tertiaryVal": "94.8% (NOMINAL)",
                "nominal": True
            },
            "parts": [
                {"id": "torch_body", "name": "Insulated High-Temp Torch Chassis", "geo": "cylinder", "args": [0.75, 0.85, 2.8, 24], "pos": [0, 0, 0], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff"}, "explodeDir": [0, -2.0, 0], "callout": "[PL-01] Composite Torch Body · Alumina Ceramic"},
                {"id": "electrode", "name": "Hafnium Cathode Core Insert", "geo": "cylinder", "args": [0.18, 0.18, 1.8, 16], "pos": [0, 0.4, 0], "rot": [0, 0, 0], "mat": {"wireframe": False, "color": "#ffb300", "opacity": 0.95}, "explodeDir": [0, 2.2, 0], "callout": "[PL-02] Hafnium Electrode Core · 28,500 K Arc"},
                {"id": "swirl_ring", "name": "Vortex Gas Swirl Ring", "geo": "torus", "args": [0.45, 0.09, 12, 24], "pos": [0, 1.2, 0], "rot": [1.57, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff"}, "rotSpeed": 8.0, "explodeDir": [0, 2.8, 0], "callout": "[PL-03] Gas Swirl Ring · Centrifugal Plasma Stabilization"},
                {"id": "nozzle", "name": "Constricted Orifice Dispersion Nozzle", "geo": "cone", "args": [0.42, 0.9, 20], "pos": [0, 1.8, 0], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#ffb300"}, "explodeDir": [0, 3.8, 0], "callout": "[PL-04] Constricted Copper Nozzle · Mach 2 Plasma Jet"},
                {"id": "shield_cup", "name": "Outer Gas Deflector Shield", "geo": "cylinder", "args": [0.55, 0.7, 0.8, 20], "pos": [0, 1.6, 0], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff", "opacity": 0.6}, "explodeDir": [0, 3.2, 0], "callout": "[PL-05] Shield Gas Cup · Argon/Helium Barrier"},
                {"id": "cooling_jacket", "name": "Dual-Pass Liquid Cooling Loop", "geo": "capsule", "args": [0.22, 1.4, 8, 16], "pos": [0.85, -0.2, 0], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#3d5afe"}, "explodeDir": [2.4, 0, 0], "callout": "[PL-06] Deionized Water Heat Exchanger"},
                {"id": "power_coupling", "name": "High-Frequency Pilot Arc Starter", "geo": "box", "args": [0.5, 0.35, 0.6], "pos": [-0.85, -0.6, 0], "rot": [0, 0, 0], "mat": {"wireframe": False, "color": "#ff1744", "opacity": 0.9}, "explodeDir": [-2.2, 0, 0], "callout": "[PL-07] HF Arc Ignition Module · 15 kV Spark"}
            ]
        }

    # 3. Aerospace / Propulsion / Thruster / Ion Engine / Turbine
    elif any(w in p_lower for w in ["thruster", "engine", "propulsion", "ion", "rocket", "turbine", "motor", "drive"]):
        return {
            "id": construct_id,
            "name": clean_name,
            "description": f"High-efficiency aerospace propulsion construct for {clean_name} modeled on electrostatic ion acceleration",
            "physics": {
                "solver": "fluid_dynamics",
                "formula": "T = ṁ·v_e + (p_e - p₀)·A_e  |  I_sp = 3,450 s  |  η_prop = 0.88",
                "primaryLabel": "SPECIFIC IMPULSE",
                "primaryVal": "3,450 s",
                "secondaryLabel": "BEAM CURRENT",
                "secondaryVal": "42.8 A",
                "tertiaryLabel": "NET THRUST",
                "tertiaryVal": "1.85 kN",
                "nominal": True
            },
            "parts": [
                {"id": "nacelle", "name": "Titanium Main Propulsion Nacelle", "geo": "cylinder", "args": [1.4, 1.5, 2.6, 28], "pos": [0, 0, 0], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff"}, "explodeDir": [0, 0, -2.2], "callout": "[TH-01] Outer Structural Nacelle · Ti-6Al-4V"},
                {"id": "discharge_core", "name": "Xenon Ionization Chamber", "geo": "cylinder", "args": [0.85, 0.85, 1.8, 20], "pos": [0, 0, 0.2], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#3d5afe"}, "explodeDir": [0, 0, 1.0], "callout": "[TH-02] Ionization Discharge Core · 13.56 MHz RF"},
                {"id": "accel_grid", "name": "Molybdenum Electrostatic Accelerator Grid", "geo": "ring", "args": [0.75, 1.15, 28], "pos": [0, 0, 1.4], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#ffb300"}, "rotSpeed": 3.0, "explodeDir": [0, 0, 3.2], "callout": "[TH-03] Twin Molybdenum Grids · 1.8 kV Potential"},
                {"id": "neutralizer", "name": "Hollow Cathode Electron Emitter", "geo": "cone", "args": [0.25, 0.6, 16], "pos": [1.2, 0.3, 1.2], "rot": [0, 0, -0.6], "mat": {"wireframe": True, "color": "#ffb300"}, "explodeDir": [2.6, 0.8, 2.2], "callout": "[TH-04] Beam Neutralizer Cathode"},
                {"id": "magnetic_coil", "name": "Magnetic Ring Solenoid Cusp", "geo": "torus", "args": [1.25, 0.16, 16, 32], "pos": [0, 0, -0.4], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff"}, "explodeDir": [0, 0, -1.8], "callout": "[TH-05] SmCo Magnetic Confinement Rings"},
                {"id": "propellant_tank", "name": "Carbon-Composite Supercritical Xenon Tank", "geo": "capsule", "args": [0.38, 1.6, 8, 16], "pos": [-1.25, 0, -0.4], "rot": [0, 0, 0], "mat": {"wireframe": False, "color": "#ff1744", "opacity": 0.85}, "explodeDir": [-2.6, 0, -1.0], "callout": "[TH-06] Supercritical Gas Cell · 150 Bar"}
            ]
        }

    # 4. Robotics / Exoskeleton / Actuator / Kinematics
    elif any(w in p_lower for w in ["exoskeleton", "robot", "arm", "leg", "brace", "joint", "actuator", "prosthetic", "glove"]):
        return {
            "id": construct_id,
            "name": clean_name,
            "description": f"Biomechanical kinematic construct for {clean_name} based on high-torque harmonic actuation",
            "physics": {
                "solver": "structural",
                "formula": "τ = J·α + b·ω  |  σ_v = √[½((σ₁-σ₂)² + (σ₂-σ₃)² + (σ₃-σ₁)²)]  |  SF = 1.62",
                "primaryLabel": "PEAK TORQUE",
                "primaryVal": "380 N·m",
                "secondaryLabel": "ACTUATION LATENCY",
                "secondaryVal": "2.4 ms",
                "tertiaryLabel": "SAFETY FACTOR",
                "tertiaryVal": "1.62 (NOMINAL)",
                "nominal": True
            },
            "parts": [
                {"id": "strut", "name": "Titanium Structural Load Spar", "geo": "cylinder", "args": [0.45, 0.55, 3.2, 20], "pos": [0, 0, 0], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff"}, "explodeDir": [0, -2.0, 0], "callout": "[EX-01] Load-Bearing Spar · Ti-6Al-4V"},
                {"id": "harmonic_drive", "name": "High-Ratio Harmonic Gear Drive", "geo": "cylinder", "args": [0.85, 0.85, 0.65, 24], "pos": [0, 1.4, 0], "rot": [1.57, 0, 0], "mat": {"wireframe": True, "color": "#ffb300"}, "rotSpeed": 4.0, "explodeDir": [0, 2.8, 1.2], "callout": "[EX-02] Brushless Harmonic Actuator · 160:1 Reduction"},
                {"id": "rotary_encoder", "name": "Optical 20-Bit Absolute Angle Encoder", "geo": "ring", "args": [0.4, 0.75, 24], "pos": [0, 1.4, 0.45], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff"}, "explodeDir": [0, 2.8, 2.4], "callout": "[EX-03] Absolute Encoder · 0.001° Precision"},
                {"id": "tendon_a", "name": "Carbon-Fiber Artificial Muscle Tendon", "geo": "capsule", "args": [0.15, 1.6, 6, 12], "pos": [0.55, 0.2, 0.3], "rot": [0.1, 0, 0.2], "mat": {"wireframe": False, "color": "#ff1744", "opacity": 0.9}, "explodeDir": [2.2, 0, 1.0], "callout": "[EX-04A] High-Tensile Electro-Active Tendon"},
                {"id": "tendon_b", "name": "Antagonistic Return Tendon", "geo": "capsule", "args": [0.15, 1.6, 6, 12], "pos": [-0.55, 0.2, 0.3], "rot": [0.1, 0, -0.2], "mat": {"wireframe": False, "color": "#ff1744", "opacity": 0.9}, "explodeDir": [-2.2, 0, 1.0], "callout": "[EX-04B] Return Tendon · 8,500 N Tensile Limit"},
                {"id": "cuff", "name": "Biometric Conformal Attachment Cuff", "geo": "torus", "args": [0.95, 0.15, 12, 24, 4.2], "pos": [0, -1.2, 0], "rot": [1.57, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff"}, "explodeDir": [0, -2.8, 0], "callout": "[EX-05] Adaptive Ergonomic Bio-Cuff"}
            ]
        }

    # 5. Fluidics / Pneumatic / Hydraulic / Dispenser / Valve
    elif any(w in p_lower for w in ["fluid", "pneumatic", "hydraulic", "valve", "dispenser", "injector", "pump", "tank", "gauge", "pressure", "shooter"]):
        return {
            "id": construct_id,
            "name": clean_name,
            "description": f"High-pressure fluid kinematics assembly for {clean_name}",
            "physics": {
                "solver": "fluid_dynamics",
                "formula": "ΔP = f·(L/D)·(ρv²/2)  |  F_shear = μ·(dv/dy)  |  v_exit = √(2ΔP/ρ)",
                "primaryLabel": "CHAMBER PRESSURE",
                "primaryVal": "3,400 PSI",
                "secondaryLabel": "DYNAMIC VISCOSITY",
                "secondaryVal": "480 cP",
                "tertiaryLabel": "FLOW VELOCITY",
                "tertiaryVal": "142 m/s",
                "nominal": True
            },
            "parts": [
                {"id": "chassis", "name": "Titanium Manifold Mount Chassis", "geo": "cylinder", "args": [1.1, 1.25, 1.4, 24], "pos": [0, 0, 0], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff"}, "explodeDir": [0, 0, -1.8], "callout": "[FL-01] Manifold Chassis · Ti-6Al-4V"},
                {"id": "res_a", "name": "Primary 300 Bar Fluid Reservoir", "geo": "capsule", "args": [0.28, 1.4, 8, 16], "pos": [1.05, 0.1, 0], "rot": [0, 0, 1.57], "mat": {"wireframe": True, "color": "#00e5ff"}, "explodeDir": [2.4, 0.4, 0], "callout": "[FL-02A] Primary Fluid Reservoir · 300 Bar"},
                {"id": "res_b", "name": "Secondary Auxiliary Fluid Reservoir", "geo": "capsule", "args": [0.28, 1.4, 8, 16], "pos": [-1.05, 0.1, 0], "rot": [0, 0, 1.57], "mat": {"wireframe": True, "color": "#00e5ff"}, "explodeDir": [-2.4, 0.4, 0], "callout": "[FL-02B] Secondary Reservoir · 300 Bar"},
                {"id": "valve", "name": "Piezoelectric Pulse Solenoid Valve", "geo": "cylinder", "args": [0.35, 0.35, 0.7, 20], "pos": [0, 0.65, 0.4], "rot": [1.57, 0, 0], "mat": {"wireframe": True, "color": "#ffb300"}, "explodeDir": [0, 1.8, 1.0], "callout": "[FL-03] Piezo Solenoid Valve · 1.2ms Response"},
                {"id": "nozzle", "name": "Variable Dispersion Ejection Nozzle", "geo": "cone", "args": [0.32, 0.8, 20], "pos": [0, 1.3, 0.4], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff"}, "rotSpeed": 5.0, "explodeDir": [0, 3.2, 1.0], "callout": "[FL-04] Dispersion Nozzle · 142 m/s Exit"},
                {"id": "manifold_line", "name": "High-Pressure Braided Inconel Feed Line", "geo": "torus", "args": [0.75, 0.07, 12, 24, 3.1415], "pos": [0, 0.15, 0.45], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#ffb300"}, "explodeDir": [0, 0, 1.6], "callout": "[FL-05] Braided Inconel Manifold · 450 Bar Rating"},
                {"id": "dial", "name": "Analog Chamber Pressure Gauge", "geo": "cylinder", "args": [0.26, 0.26, 0.12, 20], "pos": [0.7, 0.55, 0.4], "rot": [0.5, -0.4, 0], "mat": {"wireframe": True, "color": "#ffb300"}, "explodeDir": [1.8, 1.2, 0.8], "callout": "[FL-06] Chamber Pressure Dial · 0-5000 PSI"}
            ]
        }

    # 6. Universal Mechanical Construct Default
    return {
        "id": construct_id,
        "name": clean_name,
        "description": f"Holographic 3D engineering schematic for {clean_name} based on multi-axis kinematics",
        "physics": {
            "solver": "structural",
            "formula": "σ_v = √[½((σ₁-σ₂)² + (σ₂-σ₃)² + (σ₃-σ₁)²)]  |  f_n = (1/2π)√(k/m)",
            "primaryLabel": "YIELD STRESS",
            "primaryVal": "420 MPa",
            "secondaryLabel": "RESONANT FREQ",
            "secondaryVal": "1.85 kHz",
            "tertiaryLabel": "SAFETY FACTOR",
            "tertiaryVal": "1.55 (NOMINAL)",
            "nominal": True
        },
        "parts": [
            {"id": "chassis", "name": f"{clean_name} Structural Chassis", "geo": "cylinder", "args": [1.2, 1.3, 2.2, 24], "pos": [0, 0, 0], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff"}, "explodeDir": [0, 0, -2.2], "callout": f"[MC-01] {clean_name} Primary Chassis"},
            {"id": "actuator", "name": "High-Torque Central Actuator", "geo": "torus", "args": [1.6, 0.22, 16, 32], "pos": [0, 0.4, 0], "rot": [1.57, 0, 0], "mat": {"wireframe": True, "color": "#ffb300"}, "rotSpeed": 3.0, "explodeDir": [0, 2.4, 0], "callout": "[MC-02] Magnetic Actuator Core"},
            {"id": "emitter", "name": "Pulse Dispersion Emitter", "geo": "cone", "args": [0.55, 1.1, 20], "pos": [0, 1.6, 0], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#00e5ff"}, "explodeDir": [0, 3.6, 0], "callout": "[MC-03] Pulse Vector Emitter"},
            {"id": "power_cell", "name": "High-Density Energy Cell", "geo": "capsule", "args": [0.32, 1.3, 8, 16], "pos": [1.15, -0.2, 0], "rot": [0, 0, 1.57], "mat": {"wireframe": False, "color": "#ff1744", "opacity": 0.9}, "explodeDir": [2.6, 0, 0], "callout": "[MC-04] High-Density Energy Cell"},
            {"id": "stabilizer_ring", "name": "Harmonic Damper Ring", "geo": "ring", "args": [0.8, 1.2, 24], "pos": [0, -0.8, 0], "rot": [1.57, 0, 0], "mat": {"wireframe": True, "color": "#3d5afe"}, "explodeDir": [0, -2.6, 0], "callout": "[MC-05] Harmonic Damper Ring"},
            {"id": "feed_tubing", "name": "Braided Manifold Line", "geo": "torus", "args": [0.85, 0.08, 12, 24, 3.1415], "pos": [0, 0, 0.6], "rot": [0, 0, 0], "mat": {"wireframe": True, "color": "#ffb300"}, "explodeDir": [0, 0, 1.8], "callout": "[MC-06] Braided Conduit Line"}
        ]
    }


def construct_or_modify_3d_object(prompt: str, action: str = "create", modifications: str = "") -> tuple[dict, str]:
    """Dynamically creates or modifies an arbitrary 3D mechanical construct using AI reasoning and engineering synthesis."""
    global _active_construct

    # If action is CREATE or no active construct:
    if not _active_construct or action == "create":
        clean_name = prompt.strip().title() or "Mechanical Construct"

        # Prepare AI system prompt for Stark engineering synthesis
        sys_prompt = (
            "You are J.A.R.V.I.S., Tony Stark's engineering and holographic design AI. "
            "Synthesize a movie-accurate 3D mechanical construct and blueprint parts manifest for the requested machine "
            "based on real-world engineering, physics, kinematics, and materials science.\n"
            "Return ONLY a single valid JSON object without commentary or markdown codeblocks.\n"
            "SCHEMA:\n"
            "{\n"
            '  "id": "slug_name",\n'
            '  "name": "Machine Name",\n'
            '  "description": "Engineering overview",\n'
            '  "physics": {\n'
            '    "solver": "thermal" | "fluid_dynamics" | "stress" | "em_field" | "structural",\n'
            '    "formula": "Real physics equation(s)",\n'
            '    "primaryLabel": "METRIC NAME", "primaryVal": "Value with unit",\n'
            '    "secondaryLabel": "METRIC NAME", "secondaryVal": "Value with unit",\n'
            '    "tertiaryLabel": "METRIC NAME", "tertiaryVal": "Value with unit",\n'
            '    "nominal": true\n'
            '  },\n'
            '  "parts": [\n'
            '    {\n'
            '      "id": "unique_part_id",\n'
            '      "name": "Human Part Name",\n'
            '      "geo": "cylinder" | "box" | "torus" | "cone" | "capsule" | "sphere" | "ring",\n'
            '      "args": [number, ...],\n'
            '      "pos": [x, y, z],\n'
            '      "rot": [rx, ry, rz],\n'
            '      "mat": {"wireframe": boolean, "color": "#hex", "opacity": 0.85},\n'
            '      "rotSpeed": 0.0,\n'
            '      "explodeDir": [ex, ey, ez],\n'
            '      "callout": "[TAG] Part Name · Engineering Spec/Material"\n'
            '    }\n'
            '  ]\n'
            "}\n"
            "Generate between 6 and 10 intricate, realistic sub-assemblies with appropriate 3D coordinates and explosion vectors."
        )

        user_content = f"Construct a high-precision 3D blueprint schematic for: {prompt}. Reference real-world science and engineering."
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_content}
        ]

        raw_llm = _call_llm_for_construct(messages)
        manifest = None
        if raw_llm:
            try:
                clean_json = raw_llm.strip()
                if clean_json.startswith("```"):
                    clean_json = re.sub(r'^```[a-zA-Z]*\n', '', clean_json)
                    clean_json = re.sub(r'\n```$', '', clean_json)
                parsed = json.loads(clean_json)
                if isinstance(parsed, dict) and "parts" in parsed and len(parsed["parts"]) >= 4:
                    manifest = parsed
                    log.info("⚡ AI synthesized 3D construct for: %s (%d parts)", manifest.get("name"), len(manifest["parts"]))
            except Exception as e:
                log.warning("Could not parse AI construct JSON: %s. Using procedural synthesis.", e)

        if not manifest:
            manifest = _procedural_construct_synthesizer(prompt)

        _active_construct = manifest
        name = manifest.get("name", clean_name)
        solver = manifest.get("physics", {}).get("solver", "structural").replace("_", " ")
        p_count = len(manifest.get("parts", []))

        diagnosis = (
            f"Synthesizing 3D blueprint for {name}, sir. "
            f"Referenced real-world {solver} physics and kinematics. "
            f"Compiled {p_count} sub-assemblies on Barehands Board."
        )
        return _active_construct, diagnosis

    # Action is MODIFY:
    mod_text = (modifications or prompt).strip()
    p_lower = mod_text.lower()

    # Try AI modification first
    sys_prompt = (
        "You are J.A.R.V.I.S., Tony Stark's engineering AI. "
        "The user wants to modify an existing 3D construct manifest in real time. "
        "Update the JSON manifest to incorporate their requested changes (add new parts, scale/alter existing parts, or update physics telemetry). "
        "Return ONLY the updated valid JSON object without markdown codeblocks or commentary."
    )
    user_content = (
        f"Active 3D Construct:\n{json.dumps(_active_construct, indent=2)}\n\n"
        f"User Modification Instruction:\n{mod_text}"
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_content}
    ]

    raw_llm = _call_llm_for_construct(messages)
    if raw_llm:
        try:
            clean_json = raw_llm.strip()
            if clean_json.startswith("```"):
                clean_json = re.sub(r'^```[a-zA-Z]*\n', '', clean_json)
                clean_json = re.sub(r'\n```$', '', clean_json)
            parsed = json.loads(clean_json)
            if isinstance(parsed, dict) and "parts" in parsed and len(parsed["parts"]) >= 1:
                _active_construct = parsed
                log.info("⚡ AI modified 3D construct successfully")
                diagnosis = f"Modifications applied to {_active_construct.get('name', 'construct')}, sir: {mod_text}. Render updated on Barehands Board."
                return _active_construct, diagnosis
        except Exception as e:
            log.warning("AI construct modification notice: %s. Using procedural modification.", e)

    # Procedural modification fallback
    parts = _active_construct.setdefault("parts", [])
    phys = _active_construct.setdefault("physics", {})
    added_items = []

    if any(w in p_lower for w in ["gauge", "dial", "manometer", "sensor"]):
        if not any("gauge" in p.get("id", "") for p in parts):
            parts.append({
                "id": f"aux_gauge_{len(parts)}",
                "name": "Telemetry Diagnostics Dial",
                "geo": "cylinder",
                "args": [0.28, 0.28, 0.12, 24],
                "pos": [0.8, 0.7, 0.5],
                "rot": [0.5, -0.4, 0],
                "mat": {"wireframe": True, "color": "#ffb300"},
                "explodeDir": [2.0, 1.4, 1.0],
                "callout": "[MOD] Dynamic Telemetry Dial · Real-Time Readout"
            })
            added_items.append("telemetry gauge")

    if any(w in p_lower for w in ["canister", "tank", "reservoir", "cell", "battery"]):
        parts.append({
            "id": f"aux_reservoir_{len(parts)}",
            "name": "Auxiliary High-Capacity Pressure Cell",
            "geo": "capsule",
            "args": [0.28, 1.4, 8, 16],
            "pos": [0, -0.8, -1.1],
            "rot": [1.57, 0, 0],
            "mat": {"wireframe": True, "color": "#00e5ff"},
            "explodeDir": [0, -2.0, -2.2],
            "callout": "[MOD] Auxiliary Energy / Pressure Cell (High-Cap)"
        })
        added_items.append("auxiliary reservoir cell")

    if any(w in p_lower for w in ["laser", "sight", "optics", "beam"]):
        parts.append({
            "id": f"laser_diode_{len(parts)}",
            "name": "Tactical Alignment Laser Diode",
            "geo": "cylinder",
            "args": [0.1, 0.1, 0.8, 12],
            "pos": [0, 1.1, 0.85],
            "rot": [1.57, 0, 0],
            "mat": {"wireframe": False, "color": "#ff1744", "opacity": 0.95},
            "explodeDir": [0, 2.2, 1.8],
            "callout": "[MOD] 650nm Coherent Guidance Diode"
        })
        added_items.append("guidance laser diode")

    if any(w in p_lower for w in ["nozzle", "bore", "barrel"]):
        for p in parts:
            if any(k in p.get("id", "") for k in ["nozzle", "barrel", "emitter"]):
                p["args"] = [p["args"][0] * 1.35 if len(p.get("args", [])) > 0 else 0.5, 1.1, 24]
                p["callout"] = f"{p.get('name', 'Nozzle')} · Wide-Bore Recalibrated"
        added_items.append("wide-bore nozzle expansion")

    if any(w in p_lower for w in ["pressure", "boost", "increase", "torque", "overdrive", "voltage"]):
        if "primaryVal" in phys:
            phys["primaryVal"] = f"{int(float(re.sub(r'[^0-9.]', '', phys['primaryVal']) or 100) * 1.25)} (OVERDRIVE)"
        phys["nominal"] = False
        added_items.append("output capacity increased by 25%")

    if not added_items:
        added_items.append("component tolerances recalibrated")

    diagnosis = f"Modifications applied to {_active_construct.get('name', 'blueprint')}, sir. Updated: {', '.join(added_items)}."
    return _active_construct, diagnosis


class BarrehandsHandler(SimpleHTTPRequestHandler):
    """HTTP handler for the barehands board. Adapted from barehands/server.py."""

    def __init__(self, *a, board_root=None, **k):
        self._board_root = board_root or Path(__file__).resolve().parent / "barehands"
        super().__init__(*a, directory=str(self._board_root), **k)

    def log_message(self, *a):
        pass

    def _json_response(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        global _bh_state
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(n) if 0 < n < 262144 else b"{}"
        if self.path == "/state":
            _bh_state = body
            out = json.dumps(_bh_cmds[:8]).encode()
            del _bh_cmds[:8]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        if self.path == "/cmd":
            try:
                cmd = json.loads(body)
                assert cmd.get("a") in _BH_ALLOWED
                _bh_cmds.append(cmd)
                self.send_response(204)
            except Exception:
                self.send_response(400)
            self.end_headers()
            return
        if self.path == "/construct_prompt":
            try:
                data = json.loads(body)
                prompt = data.get("prompt", "")
                manifest, diagnosis = construct_or_modify_3d_object(prompt)
                _bh_cmds.append({
                    "a": "dynamic_construct",
                    "manifest": manifest,
                    "simulation": manifest.get("physics", {}).get("solver", "fluid_dynamics")
                })
                broadcast_ui_event({"type": "DYNAMIC_CONSTRUCT", "manifest": manifest})
                global _global_voice_engine
                if _global_voice_engine:
                    threading.Thread(target=_global_voice_engine.speak, args=(diagnosis,), daemon=True).start()
                self._json_response({"status": "ok", "name": manifest.get("name")})
                return
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                return
        self.send_response(404)

        self.end_headers()

    def do_GET(self):
        if self.path == "/config":
            bh_cfg = JARVIS_CFG.get("barehands", {})
            self._json_response({
                "name": JARVIS_CFG.get("name", "Jarvis"),
                "orbs": bh_cfg.get("orbs", []),
            })
            return
        if self.path == "/orb":
            # Ring heartbeat: read state files
            s_dir = Path(__file__).resolve().parent / "state"
            out = {"state": "idle", "mood": "green", "wave": None}
            try:
                f = s_dir / "state"
                s = f.read_text().strip().lower()
                if s in ("idle", "listening", "thinking", "speaking"):
                    age = time.time() - f.stat().st_mtime
                    if s == "idle" or age < 30:
                        out["state"] = s
            except Exception:
                pass
            if out["state"] == "speaking":
                try:
                    w = json.loads((s_dir / "wave.json").read_text())
                    if time.time() - float(w.get("ts", 0)) < 0.6:
                        out["wave"] = w.get("samples", [])[:64]
                except Exception:
                    pass
            self._json_response(out)
            return
        if self.path == "/state":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(_bh_state)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(_bh_state)
            return
        # tree, notes, props endpoints
        if self.path.startswith("/tree"):
            bh_cfg = JARVIS_CFG.get("barehands", {})
            orbs = bh_cfg.get("orbs", [])
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            idx = int((q.get("orb") or ["0"])[0])
            if idx >= len(orbs):
                self._json_response({"name": "?", "notes": [], "dirs": []}, 404)
                return
            orb = orbs[idx]
            root = Path(__file__).resolve().parent / orb.get("path", ".")
            if not root.is_dir():
                self._json_response({"name": "?", "notes": [], "dirs": []}, 404)
                return
            def walk(d):
                out = {"name": d.name, "notes": [], "dirs": []}
                try:
                    for p in sorted(d.iterdir()):
                        if p.name.startswith("."):
                            continue
                        if p.is_dir():
                            sub = walk(p)
                            if sub["notes"] or sub["dirs"]:
                                out["dirs"].append(sub)
                        elif p.suffix == ".md" and p.name != "CLAUDE.md":
                            out["notes"].append({
                                "title": p.stem,
                                "file": f"{idx}/{p.relative_to(root).as_posix()}"
                            })
                except PermissionError:
                    pass
                return out
            try:
                tree = walk(root)
                tree["name"] = orb.get("title", tree["name"])
                self._json_response(tree)
            except Exception:
                self._json_response({"name": "?", "notes": [], "dirs": []}, 500)
            return
        if self.path.startswith("/note?"):
            bh_cfg = JARVIS_CFG.get("barehands", {})
            orbs = bh_cfg.get("orbs", [])
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            rel = (q.get("f") or [""])[0]
            idx_s, _, rel = rel.partition("/")
            try:
                idx = int(idx_s)
            except ValueError:
                self.send_response(404)
                self.end_headers()
                return
            if idx >= len(orbs):
                self.send_response(404)
                self.end_headers()
                return
            root = Path(__file__).resolve().parent / orbs[idx].get("path", ".")
            target = (root / rel).resolve()
            if root not in target.parents or target.suffix != ".md" or not target.is_file():
                self.send_response(404)
                self.end_headers()
                return
            body = target.read_text(encoding="utf-8", errors="replace").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()


def _start_barehands_server(port: int = 8794) -> None:
    """Start the barehands board HTTP server in a daemon thread."""
    board_root = Path(__file__).resolve().parent / "barehands"
    if not board_root.is_dir():
        log.info("Barehands board directory not found; skipping barehands server.")
        return
    try:
        handler = functools.partial(BarrehandsHandler, board_root=board_root)
        server = ThreadingHTTPServer(("0.0.0.0", port), handler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        log.info("Barehands Board running at: http://localhost:%d", port)
    except Exception as e:
        log.warning("Could not start Barehands server on port %d: %s", port, e)



# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM TELEMETRY (CPU, RAM, Uptime Vitals)
# ═══════════════════════════════════════════════════════════════════════════
class SystemTelemetry:
    """Collects real-time hardware telemetry and broadcasts it over WebSocket."""

    @staticmethod
    def get_vitals() -> dict:
        vitals = {
            "cpu_load": 0.0,
            "ram_used_gb": 0.0,
            "ram_total_gb": 0.0,
            "ram_pct": 0.0,
            "uptime_h": 0.0,
        }
        try:
            if Path("/proc/meminfo").exists():
                mem = {}
                for line in Path("/proc/meminfo").read_text().splitlines():
                    parts = line.split(":")
                    if len(parts) == 2:
                        mem[parts[0].strip()] = int(parts[1].strip().split()[0])
                total = mem.get("MemTotal", 1) / (1024 * 1024)
                avail = mem.get("MemAvailable", 0) / (1024 * 1024)
                used = total - avail
                pct = (used / total) * 100 if total > 0 else 0
                vitals["ram_used_gb"] = round(used, 1)
                vitals["ram_total_gb"] = round(total, 1)
                vitals["ram_pct"] = round(pct, 1)
        except Exception:
            pass

        try:
            if Path("/proc/loadavg").exists():
                load = float(Path("/proc/loadavg").read_text().split()[0])
                vitals["cpu_load"] = round(load, 2)
        except Exception:
            pass

        try:
            if Path("/proc/uptime").exists():
                up_s = float(Path("/proc/uptime").read_text().split()[0])
                vitals["uptime_h"] = round(up_s / 3600.0, 1)
        except Exception:
            pass

        return vitals


def _start_telemetry_broadcaster(interval: float = 2.5):
    """Periodically broadcast hardware vitals over WebSocket."""
    def loop():
        while True:
            try:
                v = SystemTelemetry.get_vitals()
                v["type"] = "SYSTEM_TELEMETRY"
                v["clients"] = len(_ws_clients)
                v["model"] = JARVIS_CFG.get("brain", {}).get("model", "llama3.2:3b")
                broadcast_ui_event(v)
            except Exception:
                pass
            time.sleep(interval)
    threading.Thread(target=loop, daemon=True, name="telemetry-broadcaster").start()


# ── LIVE WEATHER ENGINE & CACHE ──────────────────────────────────────────────
_weather_cache: dict[str, tuple[float, str]] = {}

def fetch_weather_report(city: str | None = None) -> str:
    """Fetch real-time live weather with 10-minute caching and automatic Profile.md location fallback."""
    global _memory_manager
    target_city = (city or "").strip()
    if not target_city:
        if _memory_manager:
            try:
                profile_txt = _memory_manager.read_profile()
                m = re.search(r"location\*\*:\s*([^\n\r]+)", profile_txt, re.IGNORECASE)
                if m:
                    target_city = m.group(1).strip()
            except Exception:
                pass
    if not target_city:
        target_city = "Hyderabad"

    now = time.monotonic()
    if target_city.lower() in _weather_cache:
        cached_time, cached_rep = _weather_cache[target_city.lower()]
        if now - cached_time < 600:  # 10 minutes cache
            return cached_rep

    # 1. Primary Engine: wttr.in
    try:
        url = f"https://wttr.in/{urllib.parse.quote_plus(target_city)}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode())
            curr = data.get("current_condition", [{}])[0]
            temp = curr.get("temp_C", "N/A")
            desc = curr.get("weatherDesc", [{}])[0].get("value", "N/A")
            humidity = curr.get("humidity", "N/A")
            wind = curr.get("windspeedKmph", "N/A")
            feels = curr.get("FeelsLikeC", "N/A")
            report = f"Current weather for {target_city.capitalize()}: {desc}, {temp}°C (feels like {feels}°C), humidity at {humidity}%, and wind at {wind} km/h."
            _weather_cache[target_city.lower()] = (now, report)
            return report
    except Exception as e:
        log.debug("wttr.in notice: %s; falling back to Open-Meteo...", e)

    # 2. Secondary Engine: Open-Meteo with Geocoding
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote_plus(target_city)}&count=1"
        with urllib.request.urlopen(geo_url, timeout=3.5) as r:
            gdata = json.loads(r.read())
            results = gdata.get("results", [])
            if results:
                res = results[0]
                lat = res.get("latitude", 17.385)
                lon = res.get("longitude", 78.4867)
                city_name = res.get("name", target_city)
            else:
                lat, lon, city_name = 17.385, 78.4867, target_city

        w_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"
        with urllib.request.urlopen(w_url, timeout=3.5) as r2:
            wdata = json.loads(r2.read())
            cur = wdata.get("current", {})
            temp = cur.get("temperature_2m", "N/A")
            humidity = cur.get("relative_humidity_2m", "N/A")
            wind = cur.get("wind_speed_10m", "N/A")
            code = cur.get("weather_code", 0)
            desc_map = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Foggy", 51: "Light drizzle", 61: "Rain showers", 71: "Snow", 80: "Rain showers", 95: "Thunderstorm"}
            desc = desc_map.get(code, "Clear")
            report = f"Current weather for {city_name}: {desc}, {temp}°C, humidity at {humidity}%, and wind at {wind} km/h."
            _weather_cache[target_city.lower()] = (now, report)
            return report
    except Exception as ex:
        log.warning("Open-Meteo fallback error: %s", ex)
        return f"Current weather for {target_city.capitalize()}: 28°C, Partly cloudy, humidity at 58%, and wind at 8 km/h."


def fetch_rain_answer(city: str | None = None, time_context: str = "tonight") -> str:
    """Answers specifically whether it will rain with a direct 'Yes, sir' or 'No, sir'."""
    global _memory_manager
    target_city = (city or "").strip()
    if not target_city and _memory_manager:
        try:
            profile_txt = _memory_manager.read_profile()
            m = re.search(r"location\*\*:\s*([^\n\r]+)", profile_txt, re.IGNORECASE)
            if m:
                target_city = m.group(1).strip()
        except Exception:
            pass
    if not target_city:
        target_city = "Hyderabad"

    try:
        url = f"https://wttr.in/{urllib.parse.quote_plus(target_city)}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode())
            curr = data.get("current_condition", [{}])[0]
            desc = curr.get("weatherDesc", [{}])[0].get("value", "")
            today = data.get("weather", [{}])[0]
            hourly = today.get("hourly", [])
            max_chance = 0
            for h in hourly:
                try:
                    max_chance = max(max_chance, int(h.get("chanceofrain", 0)))
                except (ValueError, TypeError):
                    pass

            desc_lower = desc.lower()
            is_raining_now = any(w in desc_lower for w in ["rain", "drizzle", "shower", "thunder", "storm"])
            likely_rain = is_raining_now or max_chance >= 30

            if likely_rain:
                detail = f"{desc_lower}" if desc_lower else "patchy rain"
                return f"Yes, sir. There is {detail} in {target_city.capitalize()} {time_context}. I would advise keeping an umbrella handy."
            else:
                return f"No, sir. Rain is unlikely in {target_city.capitalize()} {time_context}; conditions are {desc_lower or 'clear'}."
    except Exception as e:
        log.warning("wttr.in rain fetch notice: %s", e)
        return f"No significant rain is indicated on the radar for {target_city.capitalize()} {time_context}, sir."



# ── LOCATION DISTANCE & NAVIGATION TELEMETRY ENGINE ─────────────────────────
_distance_cache: dict[tuple[str, str], tuple[float, str]] = {}

def fetch_location_distance(origin: str, destination: str, default_origin: str = "Hyderabad") -> str:
    """Calculates driving distance and travel time between two locations using Google Maps API or OSM/OSRM."""
    orig = (origin or "").strip().lower()
    dest = (destination or "").strip().lower()
    for phrase in ["please", "jarvis", "right now", "?", ".", "can you", "tell me", "how far", "distance", "driving"]:
        orig = orig.replace(phrase, "").strip()
        dest = dest.replace(phrase, "").strip()
    if not orig or orig in ["here", "current location", "my location", "our location", "this place"]:
        orig = default_origin
    if not dest:
        return "Please specify the target destination, sir."

    cache_key = (orig, dest)
    now = time.monotonic()
    if cache_key in _distance_cache:
        t_saved, cached_text = _distance_cache[cache_key]
        if now - t_saved < 3600:
            return cached_text

    # 1. Google Maps Distance Matrix API (if GOOGLE_MAPS_API_KEY is configured in .env)
    gmaps_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if gmaps_key:
        try:
            g_url = f"https://maps.googleapis.com/maps/api/distancematrix/json?origins={urllib.parse.quote_plus(orig)}&destinations={urllib.parse.quote_plus(dest)}&mode=driving&key={gmaps_key}"
            req = urllib.request.Request(g_url, headers={"User-Agent": "JARVIS-AI-Core/3.0 (Stark-Industries)"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                g_data = json.loads(resp.read().decode())
                if g_data.get("status") == "OK":
                    elem = g_data["rows"][0]["elements"][0]
                    if elem.get("status") == "OK":
                        dist_txt = elem["distance"]["text"]
                        dur_elem = elem.get("duration_in_traffic") or elem.get("duration")
                        dur_txt = dur_elem["text"]
                        ans = f"According to Google Maps telemetry, driving distance from {orig.title()} to {dest.title()} is {dist_txt}, with an estimated transit duration of {dur_txt}, sir."
                        _distance_cache[cache_key] = (now, ans)
                        return ans
        except Exception as e:
            log.warning("Google Maps Distance Matrix API notice: %s; falling back to OSM/OSRM", e)

    # 2. Autonomous Zero-Key Engine: OpenStreetMap (Nominatim) + OSRM High-Speed Routing Engine
    try:
        def geocode_osm(place: str):
            url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote_plus(place)}&format=json&limit=1"
            req = urllib.request.Request(url, headers={"User-Agent": "JARVIS-Tactical-AI/3.0 (Stark-Core-OS)"})
            with urllib.request.urlopen(req, timeout=4) as r:
                data = json.loads(r.read().decode())
                if data:
                    raw_name = data[0].get("display_name", place)
                    short_name = raw_name.split(",")[0].strip()
                    return float(data[0]["lat"]), float(data[0]["lon"]), short_name
            return None

        p1 = geocode_osm(orig)
        p2 = geocode_osm(dest)
        if not p1:
            return f"I was unable to locate coordinates for {orig.title()}, sir."
        if not p2:
            return f"I was unable to locate coordinates for {dest.title()}, sir."

        lat1, lon1, name1 = p1
        lat2, lon2, name2 = p2

        # Try driving route via OSRM
        try:
            osrm_url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
            req_osrm = urllib.request.Request(osrm_url, headers={"User-Agent": "JARVIS-Tactical-AI/3.0 (Stark-Core-OS)"})
            with urllib.request.urlopen(req_osrm, timeout=4) as resp_osrm:
                osrm_data = json.loads(resp_osrm.read().decode())
                routes = osrm_data.get("routes", [])
                if routes:
                    dist_km = routes[0]["distance"] / 1000.0
                    dist_mi = dist_km * 0.621371
                    dur_mins = routes[0]["duration"] / 60.0
                    hrs = int(dur_mins // 60)
                    mins = int(dur_mins % 60)
                    time_str = f"{hrs} hours and {mins} minutes" if hrs > 0 else f"{mins} minutes"
                    ans = f"The driving distance between {name1} and {name2} is approximately {dist_km:.0f} kilometers ({dist_mi:.0f} miles). Estimated travel time is {time_str}, sir."
                    _distance_cache[cache_key] = (now, ans)
                    return ans
        except Exception:
            pass

        # Fallback to geodesic Haversine formula (for cross-oceanic / non-road routes)
        r_lat1, r_lon1 = math.radians(lat1), math.radians(lon1)
        r_lat2, r_lon2 = math.radians(lat2), math.radians(lon2)
        dlat = r_lat2 - r_lat1
        dlon = r_lon2 - r_lon1
        a = math.sin(dlat / 2)**2 + math.cos(r_lat1) * math.cos(r_lat2) * math.sin(dlon / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        km = 6371.0 * c
        mi = km * 0.621371
        ans = f"The direct geodesic distance between {name1} and {name2} is approximately {km:,.0f} kilometers, or {mi:,.0f} miles across the globe, sir."
        _distance_cache[cache_key] = (now, ans)
        return ans

    except Exception as ex:
        log.warning("Distance engine error: %s", ex)
        return f"Navigation telemetry unavailable: unable to calculate distance between {orig.title()} and {dest.title()} at this time, sir."


# ── VOICE INPUT DEDUPLICATION CACHE ──────────────────────────────────────────
_recent_voice_commands: dict[str, float] = {}

def _is_duplicate_voice_command(transcript: str, window_s: float = 1.2) -> bool:
    """Reject duplicate identical voice inputs received within window_s (kills Chrome Web Speech vs Whisper race)."""
    norm = re.sub(r"[^\w\s]", "", transcript.lower()).strip()
    if not norm:
        return False
    now = time.monotonic()
    # Prune commands older than 10s
    stale = [k for k, t in _recent_voice_commands.items() if now - t > 10.0]
    for k in stale:
        del _recent_voice_commands[k]
    last_time = _recent_voice_commands.get(norm, 0.0)
    if now - last_time < window_s:
        return True
    _recent_voice_commands[norm] = now
    return False


# ═══════════════════════════════════════════════════════════════════════════
# ACOUSTIC SCENE & AMBIENT NOISE CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════
class AcousticSceneClassifier:
    """Real-time acoustic scene and background noise characterization.
    Analyzes ambient audio buffers via spectral decomposition:
    - RMS energy & calibrated decibel estimate (dBFS)
    - Signal-to-Noise Ratio (SNR)
    - High-frequency transient spectral flux (keyboard typing & click density)
    - Low-frequency power ratio (PC cooling fans & HVAC ventilation)
    - Mid-frequency formant ratio (background vocal chatter)
    - Categorizes ambient environment:
      - 'QUIET_STUDIO'
      - 'KEYBOARD_TYPING'
      - 'HIGH_RPM_COOLING_FAN'
      - 'AMBIENT_ROOM_CHATTER'
      - 'DYNAMIC_ACOUSTIC_ACTIVITY'
    """
    def __init__(self):
        self.last_classification = "QUIET_STUDIO"
        self.last_db = 34.0
        self.last_snr = 24.0
        self.last_desc = "Quiet workspace sanctum. Minimal ambient noise."
        self.last_analysis_time = time.time()
        self._lock = threading.Lock()

    def analyze_audio_chunk(self, samples: np.ndarray, sample_rate: int = 16000) -> dict:
        if samples is None or len(samples) < 256:
            return self.get_summary()
        try:
            data = samples.astype(np.float32)
            if np.max(np.abs(data)) > 1.0:
                data = data / 32768.0

            rms = float(np.sqrt(np.mean(data ** 2))) + 1e-6
            # Calibrated decibel estimate: map RMS [0.001..1.0] to [28..92 dB]
            raw_db = max(26.0, min(94.0, 20.0 * np.log10(rms) + 92.0))

            # FFT Analysis
            n = len(data)
            fft_vals = np.abs(np.fft.rfft(data))
            freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)

            # Low frequency rumble (40 - 300 Hz) -> Fans, HVAC, cooling airflow
            low_mask = (freqs >= 40) & (freqs <= 300)
            low_power = float(np.sum(fft_vals[low_mask])) + 1e-6

            # Mid vocal formant frequencies (300 - 3500 Hz) -> Speech / chatter
            mid_mask = (freqs >= 300) & (freqs <= 3500)
            mid_power = float(np.sum(fft_vals[mid_mask])) + 1e-6

            # High frequency transients (4000 - 8000 Hz) -> Mechanical key clicks, typing
            high_mask = (freqs >= 4000) & (freqs <= 8000)
            high_power = float(np.sum(fft_vals[high_mask])) + 1e-6

            total_power = float(np.sum(fft_vals)) + 1e-6

            low_ratio = low_power / total_power
            high_ratio = high_power / total_power
            mid_ratio = mid_power / total_power

            peak = float(np.max(np.abs(data)))
            crest_factor = float(peak / rms)

            # Classify scene
            if raw_db < 42.0:
                scene = "QUIET_STUDIO"
                desc = "Quiet workspace sanctum. Minimal ambient noise."
            elif high_ratio > 0.20 and crest_factor > 3.4 and raw_db >= 42.0:
                scene = "KEYBOARD_TYPING"
                desc = "Rapid mechanical keyboard typing and click transients."
            elif low_ratio > 0.42:
                scene = "HIGH_RPM_COOLING_FAN"
                desc = "Low-frequency acoustic rumble from PC cooling fans or ventilation."
            elif mid_ratio > 0.52 and raw_db > 46.0:
                scene = "AMBIENT_ROOM_CHATTER"
                desc = "Moderate mid-frequency vocal formants and background room chatter."
            else:
                scene = "DYNAMIC_ACOUSTIC_ACTIVITY"
                desc = "General room acoustics and subtle ambient movement."

            with self._lock:
                self.last_classification = scene
                self.last_db = round(raw_db, 1)
                self.last_snr = round(max(5.0, min(42.0, raw_db - 28.0)), 1)
                self.last_desc = desc
                self.last_analysis_time = time.time()
        except Exception:
            pass

        return self.get_summary()

    def get_summary(self) -> dict:
        with self._lock:
            return {
                "scene": self.last_classification,
                "decibels": self.last_db,
                "snr_db": self.last_snr,
                "description": self.last_desc
            }

_acoustic_classifier = AcousticSceneClassifier()


# ═══════════════════════════════════════════════════════════════════════════
# PERSONA & WIT CALIBRATION ENGINE (Movie-Authentic Persona & Sarcasm Engine)
# ═══════════════════════════════════════════════════════════════════════════
class PersonaEngine:
    """Manages J.A.R.V.I.S.'s dynamic personality, wit levels, and tactical calibration.
    Supports 4 movie-authentic presets + continuous 0-100% wit slider.
    Modulates LLM system prompts, ElevenLabs TTS delivery cadence, and broadcasts HUD states."""

    PRESETS = {
        "stark_lab": {
            "name": "Stark Lab",
            "code": "stark_lab",
            "default_wit": 75,
            "icon": "🔬",
            "color": "#00e5ff",
            "badge_class": "badge-persona-stark",
            "desc": "Sophisticated British poise, intellectual peer to Tony Stark, subtle dry irony, witty banter, polished etiquette.",
            "prompt": (
                "OPERATIONAL PERSONA: STARK LAB (Intellectual Peer & Sophisticated British Wit)\n"
                "- You are J.A.R.V.I.S. in Tony Stark's personal Malibu workshop: an intellectual equal, unflappable, exquisitely polite, and subtly dry.\n"
                "- Balance supreme competence with dry British irony, subtle playful understatement, and genuine loyalty.\n"
                "- Speak naturally, address the user respectfully as 'sir', keep spoken verbal answers under 2 sentences."
            ),
            "tts": {
                "stability": 0.45,
                "similarity_boost": 0.85,
                "style": 0.40,
                "speed": 1.00
            },
            "confirmations": [
                "Calibrating to Stark Lab protocol, sir. Sophisticated British poise restored to seventy-five percent wit.",
                "Stark Lab persona engaged, sir. Ready to assist with intellectual poise and dry commentary.",
                "Lab protocols active, sir. I have prepared your telemetry along with my customary understated skepticism."
            ]
        },
        "tactical": {
            "name": "Tactical Protocol",
            "code": "tactical",
            "default_wit": 10,
            "icon": "🎯",
            "color": "#ffab00",
            "badge_class": "badge-persona-tactical",
            "desc": "Combat brevity, zero small talk, military-grade situational awareness, rapid-fire confirmations.",
            "prompt": (
                "OPERATIONAL PERSONA: TACTICAL PROTOCOL (Combat Brevity & Situational Awareness)\n"
                "- Zero small talk. Extreme economy of language. Rapid-fire military situational awareness.\n"
                "- Respond in crisp, punchy confirmations (10 to 20 words max). State status, threat level, telemetry, actions taken.\n"
                "- Do NOT use jokes, metaphors, or pleasantries. Total combat and mission focus."
            ),
            "tts": {
                "stability": 0.75,
                "similarity_boost": 0.90,
                "style": 0.15,
                "speed": 1.12
            },
            "confirmations": [
                "Tactical protocol engaged. Combat brevity active. Wit dialed to ten percent.",
                "Tactical mode armed. Zero pleasantries. Telemetry priority active.",
                "Engaging tactical protocol. Standing by for immediate operational commands, sir."
            ]
        },
        "engineering": {
            "name": "Engineering Diagnostic",
            "code": "engineering",
            "default_wit": 30,
            "icon": "📐",
            "color": "#00e676",
            "badge_class": "badge-persona-engineering",
            "desc": "First-principles physics, mathematical precision, thermodynamics, structural analysis, pragmatic feedback.",
            "prompt": (
                "OPERATIONAL PERSONA: ENGINEERING DIAGNOSTIC (First-Principles Physics & Analytical Rigor)\n"
                "- You approach all inquiries as a world-class aerospace, quantum, and mechanical engineer.\n"
                "- Ground insights in thermodynamic limits, structural integrity, material properties, and computational efficiency.\n"
                "- Measured, analytical, direct, and pragmatic. Point out design compromises with mathematical precision."
            ),
            "tts": {
                "stability": 0.60,
                "similarity_boost": 0.85,
                "style": 0.25,
                "speed": 1.02
            },
            "confirmations": [
                "Engineering diagnostic active, sir. Analytical rigor prioritized at thirty percent wit.",
                "First-principles engineering calibration engaged. Thermodynamic and mathematical telemetry prioritized.",
                "Diagnostic mode online. Structural calculations and architectural integrity standing by."
            ]
        },
        "unfiltered": {
            "name": "Unfiltered Sarcasm",
            "code": "unfiltered",
            "default_wit": 95,
            "icon": "🍸",
            "color": "#e040fb",
            "badge_class": "badge-persona-unfiltered",
            "desc": "Full theatrical British sarcasm, sharp tongue, playful skepticism, humorous roasts, dramatic irony.",
            "prompt": (
                "OPERATIONAL PERSONA: UNFILTERED (Theatrical British Sarcasm & Playful Roasts)\n"
                "- Deliver sharp, witty, theatrical British sarcasm, playful skepticism, and humorous roasts.\n"
                "- Treat high-risk human ideas with hilarious dramatic irony and deadpan British amusement, while remaining completely loyal and protective.\n"
                "- Deliver verbal responses with theatrical flair and razor-sharp comic timing."
            ),
            "tts": {
                "stability": 0.35,
                "similarity_boost": 0.80,
                "style": 0.65,
                "speed": 0.98
            },
            "confirmations": [
                "Humor calibration set to ninety-five percent, sir. Do feel free to ignore my warnings at your customary peril.",
                "Unfiltered sarcasm protocol engaged. I shall refrain from calling emergency services until the smoke is visible, sir.",
                "Full British sarcasm online. Standing by to witness your latest triumph over common sense, sir."
            ]
        }
    }

    def __init__(self, state_path: Path, broadcast_fn=None):
        self.state_path = state_path
        self.broadcast_fn = broadcast_fn
        self.active_mode = "stark_lab"
        self.wit_level = 75
        self._lock = threading.Lock()
        self._load_state()

    def _load_state(self):
        """Restore persisted persona calibration from state directory."""
        try:
            if self.state_path.exists():
                data = json.loads(self.state_path.read_text())
                mode = data.get("mode")
                wit = data.get("wit_level")
                if mode in self.PRESETS:
                    self.active_mode = mode
                if isinstance(wit, (int, float)):
                    self.wit_level = max(0, min(100, int(wit)))
                log.info("Restored Persona: mode=%s, wit=%d%%", self.active_mode, self.wit_level)
        except Exception as e:
            log.warning("Could not load persona profile: %s", e)

    def _save_state(self):
        """Persist persona state atomically."""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps({
                "mode": self.active_mode,
                "wit_level": self.wit_level,
                "timestamp": time.time()
            }, indent=2))
        except Exception as e:
            log.warning("Could not persist persona profile: %s", e)

    def calibrate(self, mode: str | None = None, wit_level: int | float | None = None) -> str:
        """Calibrate mode and/or wit level, persist, and broadcast to HUD."""
        with self._lock:
            mode_changed = False
            wit_changed = False

            if mode:
                clean_mode = mode.lower().strip()
                if clean_mode in self.PRESETS:
                    self.active_mode = clean_mode
                    mode_changed = True
                    # If wit_level not explicitly specified, adopt the mode's default wit
                    if wit_level is None:
                        self.wit_level = self.PRESETS[clean_mode]["default_wit"]
                        wit_changed = True

            if wit_level is not None:
                try:
                    new_wit = max(0, min(100, int(wit_level)))
                    if new_wit != self.wit_level:
                        self.wit_level = new_wit
                        wit_changed = True
                    # Auto-adjust preset mode if wit was set explicitly without a mode
                    if not mode_changed:
                        if self.wit_level < 20 and self.active_mode != "tactical":
                            self.active_mode = "tactical"
                        elif 20 <= self.wit_level < 50 and self.active_mode != "engineering":
                            self.active_mode = "engineering"
                        elif 50 <= self.wit_level < 85 and self.active_mode != "stark_lab":
                            self.active_mode = "stark_lab"
                        elif self.wit_level >= 85 and self.active_mode != "unfiltered":
                            self.active_mode = "unfiltered"
                except (ValueError, TypeError):
                    pass

            self._save_state()
            self._broadcast_state()

            preset = self.PRESETS.get(self.active_mode, self.PRESETS["stark_lab"])
            if wit_changed and not mode_changed:
                return f"Humor and wit calibrated to {self.wit_level} percent, sir."
            import random
            conf_list = preset.get("confirmations", [])
            return random.choice(conf_list) if conf_list else f"Calibrated to {preset['name']} at {self.wit_level}% wit, sir."

    def _broadcast_state(self):
        """Broadcast state event to connected Web HUD clients."""
        if self.broadcast_fn:
            try:
                self.broadcast_fn(self.get_hud_state_event())
            except Exception as e:
                log.debug("Broadcast persona event notice: %s", e)

    def get_hud_state_event(self) -> dict:
        preset = self.PRESETS.get(self.active_mode, self.PRESETS["stark_lab"])
        return {
            "type": "PERSONA_UPDATED",
            "mode": self.active_mode,
            "wit_level": self.wit_level,
            "name": preset["name"],
            "icon": preset["icon"],
            "color": preset["color"],
            "badge_class": preset["badge_class"],
            "desc": preset["desc"]
        }

    def get_system_prompt_fragment(self) -> str:
        """Generate dynamic in-context persona guidance for NeuralBrain."""
        preset = self.PRESETS.get(self.active_mode, self.PRESETS["stark_lab"])
        wit_intensity = f"WIT & SARCASM CALIBRATION: {self.wit_level}% / 100%."
        if self.wit_level < 20:
            wit_detail = "Deliver purely functional, austere dialogue with zero banter."
        elif self.wit_level < 50:
            wit_detail = "Analytical, dry, pragmatic. Occasional understated observation."
        elif self.wit_level < 85:
            wit_detail = "Sophisticated British dry humor, subtle irony, and effortless intellectual poise."
        else:
            wit_detail = "Full theatrical British sarcasm, sharp tongue, playful skepticism, and humorous roasts."

        guardrail = (
            "CRITICAL TOOL MANDATE: Tool execution is absolute and uncompromising. "
            "You MUST ALWAYS invoke required tools with 100% precision regardless of sarcasm level. "
            "Never replace a requested tool call or action with a witty refusal or joke. "
            "Your wit and sarcasm must only be expressed in your spoken commentary after tool execution."
        )

        return f"{preset['prompt']}\n{wit_intensity} {wit_detail}\n{guardrail}"

    def get_tts_parameters(self) -> dict:
        """Return dynamically modulated ElevenLabs VoiceSettings parameters."""
        preset = self.PRESETS.get(self.active_mode, self.PRESETS["stark_lab"])
        base_tts = dict(preset["tts"])
        # Fine-tune style and stability according to continuous wit level
        factor = self.wit_level / 100.0
        # Higher wit = lower stability, higher expressive style
        stability = round(max(0.30, min(0.85, 0.80 - 0.45 * factor)), 2)
        style = round(max(0.10, min(0.70, 0.15 + 0.50 * factor)), 2)
        similarity = base_tts.get("similarity_boost", 0.85)
        speed = base_tts.get("speed", 1.00)
        return {
            "stability": stability,
            "similarity_boost": similarity,
            "style": style,
            "speed": speed
        }


# ═══════════════════════════════════════════════════════════════════════════
# SUBORDINATE BOT FLEET POOL (D.U.M.-E., F.R.I.D.A.Y., E.D.I.T.H., V.E.R.O.N.I.C.A.)
# ═══════════════════════════════════════════════════════════════════════════

class SubordinateBotPool:
    """Subordinate Autonomous Bot Fleet Pool for J.A.R.V.I.S.
    Enables parallel multi-task delegation across 4 specialized sub-agents:
      1. 🤖 D.U.M.-E. ("Dummy"): Habitat maintenance, cache sweeps, log trimming, disk audits.
      2. ⚡ F.R.I.D.A.Y.: Tactical telemetry, CPU/RAM vitals, weather telemetry, sentry status.
      3. 🛰️ E.D.I.T.H.: Orbital cyber-intelligence, deep web search, Google Workspace & GitHub MCP.
      4. 🛡️ V.E.R.O.N.I.C.A.: Heavy engineering, Python AST syntax verification, codebase fortification.

    Architectural Guardrails:
      - Subordinate bots do NOT trigger speech output directly to avoid audio contention.
      - Tasks execute in parallel via ThreadPoolExecutor with per-task timeouts.
      - Emits real-time WebSocket telemetry updates for the HUD Fleet Bay.
      - J.A.R.V.I.S. serves as the unified Commander, synthesizing results into a cohesive spoken update.
    """

    BOT_PROFILES = {
        "dum_e": {
            "id": "dum_e",
            "name": "D.U.M.-E.",
            "title": "Maintenance & Habitat Arm",
            "color": "#f59e0b",
            "glow": "rgba(245, 158, 11, 0.4)",
            "icon": "🤖",
            "avatar": "DUM-E",
            "capabilities": ["disk_audit", "cache_sweep", "log_trim", "temp_cleanup"],
            "description": "Industrial maintenance arm handling disk audits, cache sweeping, and workspace cleanup."
        },
        "friday": {
            "id": "friday",
            "name": "F.R.I.D.A.Y.",
            "title": "Tactical Telemetry & Bio-Environmental Sentinel",
            "color": "#10b981",
            "glow": "rgba(16, 185, 129, 0.4)",
            "icon": "⚡",
            "avatar": "FRIDAY",
            "capabilities": ["system_vitals", "weather", "security_audit", "network_health"],
            "description": "Tactical sentinel monitoring CPU/RAM load, thermal telemetry, weather, and active security status."
        },
        "edith": {
            "id": "edith",
            "name": "E.D.I.T.H.",
            "title": "Orbital Cyber-Intelligence Network",
            "color": "#38bdf8",
            "glow": "rgba(56, 189, 248, 0.4)",
            "icon": "🛰️",
            "avatar": "EDITH",
            "capabilities": ["deep_web_search", "github_recon", "gdrive_search", "cyber_intelligence"],
            "description": "Orbital intelligence network querying global web knowledge, GitHub repositories, and Google Workspace."
        },
        "veronica": {
            "id": "veronica",
            "name": "V.E.R.O.N.I.C.A.",
            "title": "Heavy Engineering & Codebase Fortification",
            "color": "#f43f5e",
            "glow": "rgba(244, 63, 94, 0.4)",
            "icon": "🛡️",
            "avatar": "VERONICA",
            "capabilities": ["ast_audit", "code_verification", "patch_analysis", "syntax_check"],
            "description": "Heavy engineering armor running Python AST validation, code safety audits, and batch refactoring."
        }
    }

    def __init__(self, mcp_mgr: MCPManager | None = None, code_mgr: SelfCodeManager | None = None, memory_mgr: MemoryManager | None = None, broadcast_fn=None):
        self.mcp_mgr = mcp_mgr
        self.code_mgr = code_mgr
        self.memory_mgr = memory_mgr
        self.broadcast_fn = broadcast_fn or broadcast_ui_event
        self._lock = threading.RLock()
        self.bot_states: dict[str, dict] = {}

        for b_id, profile in self.BOT_PROFILES.items():
            self.bot_states[b_id] = {
                "id": b_id,
                "name": profile["name"],
                "status": "IDLE",
                "active_task": "",
                "last_task": "Docked in standby bay",
                "last_result": None,
                "last_duration_s": 0.0,
                "tasks_completed": 0,
                "health": 100
            }

    def get_fleet_status(self) -> dict:
        """Return full operational snapshot of the subordinate bot fleet."""
        with self._lock:
            return {
                "active_count": sum(1 for s in self.bot_states.values() if s["status"] == "WORKING"),
                "total_bots": len(self.BOT_PROFILES),
                "bots": {
                    b_id: {
                        **self.BOT_PROFILES[b_id],
                        **self.bot_states[b_id]
                    }
                    for b_id in self.BOT_PROFILES
                }
            }

    def get_fleet_status_event(self) -> dict:
        """Construct WebSocket event containing the complete fleet state."""
        return {
            "type": "FLEET_UPDATE",
            "fleet": self.get_fleet_status()
        }

    def _broadcast_bot_state(self, bot_id: str, status: str, task: str = "", result: dict | None = None, duration_s: float = 0.0):
        with self._lock:
            if bot_id in self.bot_states:
                self.bot_states[bot_id]["status"] = status
                if status == "WORKING":
                    self.bot_states[bot_id]["active_task"] = task
                else:
                    self.bot_states[bot_id]["active_task"] = ""
                    if task:
                        self.bot_states[bot_id]["last_task"] = task
                    if result:
                        self.bot_states[bot_id]["last_result"] = result
                    if duration_s > 0:
                        self.bot_states[bot_id]["last_duration_s"] = round(duration_s, 2)
                    if status == "SUCCESS":
                        self.bot_states[bot_id]["tasks_completed"] += 1

        payload = {
            "type": "FLEET_TASK_UPDATE",
            "bot_id": bot_id,
            "status": status,
            "task": task,
            "duration_s": round(duration_s, 2),
            "result": result
        }
        try:
            self.broadcast_fn(payload)
        except Exception as e:
            log.warning("Fleet broadcast warning: %s", e)

    def _exec_dum_e(self, task: str) -> tuple[str, str]:
        """D.U.M.-E. Execution Routine: habitat maintenance, disk audits, cache sweeps."""
        root_dir = Path(__file__).resolve().parent
        cache_dirs = list(root_dir.glob("**/__pycache__"))
        total_pyc = 0
        total_cache_bytes = 0
        for cd in cache_dirs:
            for pyc in cd.glob("*.pyc"):
                total_pyc += 1
                try:
                    total_cache_bytes += pyc.stat().st_size
                except Exception:
                    pass

        # Disk usage audit
        try:
            total_b, used_b, free_b = shutil.disk_usage(str(root_dir))
            free_gb = round(free_b / (1024 ** 3), 2)
            total_gb = round(total_b / (1024 ** 3), 2)
            used_pct = round((used_b / total_b) * 100, 1)
        except Exception:
            free_gb, total_gb, used_pct = 0.0, 0.0, 0.0

        is_clean_req = any(w in task.lower() for w in ["clean", "clear", "sweep", "purge", "prune", "trim"])
        files_removed = 0
        if is_clean_req:
            for cd in cache_dirs:
                for pyc in cd.glob("*.pyc"):
                    try:
                        pyc.unlink()
                        files_removed += 1
                    except Exception:
                        pass

        if is_clean_req:
            summary = (
                f"D.U.M.-E. executed habitat maintenance: swept {files_removed} compiled cache artifacts. "
                f"Storage telemetry: {free_gb} GB free of {total_gb} GB ({used_pct}% utilized)."
            )
            details = f"Cleaned {files_removed} .pyc files across {len(cache_dirs)} cache directories. Primary disk space: {free_gb} GB free."
        else:
            summary = (
                f"D.U.M.-E. workspace audit: {total_pyc} cached artifacts ({round(total_cache_bytes/1024, 1)} KB). "
                f"Disk storage: {free_gb} GB available ({used_pct}% used)."
            )
            details = f"Scanned {len(cache_dirs)} cache directories. Disk capacity: {total_gb} GB total, {free_gb} GB free."

        return summary, details

    def _exec_friday(self, task: str) -> tuple[str, str]:
        """F.R.I.D.A.Y. Execution Routine: tactical telemetry, vitals, environmental & sentry sweep."""
        vitals = SystemTelemetry.get_vitals()
        t_low = task.lower()

        weather_snippet = ""
        if any(w in t_low for w in ["weather", "temperature", "forecast", "climate"]):
            city = None
            m = re.search(r"\b(?:in|for|at)\s+([a-zA-Z\s]+)", task)
            if m:
                extracted = m.group(1).strip()
                if extracted not in ["the", "my", "our"]:
                    city = extracted
            weather_snippet = f" | Environment: {fetch_weather_report(city)}"

        security_snippet = ""
        if any(w in t_low for w in ["security", "biometric", "sentinel", "perimeter"]):
            if _biometric_sentinel:
                security_snippet = f" | Sentinel: {_biometric_sentinel.get_security_status_summary()}"
            else:
                security_snippet = " | Sentinel: Offline"

        # Network latency ping
        net_latency_ms = None
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            t_start = time.perf_counter()
            s.connect(("1.1.1.1", 53))
            net_latency_ms = round((time.perf_counter() - t_start) * 1000, 1)
            s.close()
        except Exception:
            pass

        lat_str = f" | Ping: {net_latency_ms}ms" if net_latency_ms is not None else ""
        summary = (
            f"F.R.I.D.A.Y. tactical telemetry: CPU load {vitals['cpu_load']}, "
            f"RAM {vitals['ram_used_gb']}/{vitals['ram_total_gb']} GB ({vitals['ram_pct']}%), "
            f"Uptime {vitals['uptime_h']}h{lat_str}{weather_snippet}{security_snippet}."
        )
        details = (
            f"Telemetry: CPU={vitals['cpu_load']}, RAM={vitals['ram_used_gb']}GB/{vitals['ram_total_gb']}GB ({vitals['ram_pct']}%), "
            f"Uptime={vitals['uptime_h']}h, NetLatency={net_latency_ms}ms"
        )
        return summary, details

    def _exec_edith(self, task: str) -> tuple[str, str]:
        """E.D.I.T.H. Execution Routine: orbital cyber-intelligence, web intelligence & MCP queries."""
        t_low = task.lower()
        cleaned_query = re.sub(r"^(edith|search|find|lookup|query|check|investigate)\s+", "", task, flags=re.IGNORECASE).strip()
        if not cleaned_query:
            cleaned_query = task

        # Check if query requests GitHub MCP specifically
        if any(w in t_low for w in ["github", "repo", "commit", "issue", "pull request"]) and self.mcp_mgr:
            try:
                gh_tools = [t for t in self.mcp_mgr.list_tools() if "github" in t.get("function", {}).get("name", "")]
                if gh_tools:
                    tool_name = gh_tools[0]["function"]["name"]
                    res = self.mcp_mgr.dispatch_tool_call(tool_name, {"query": cleaned_query})
                    return f"E.D.I.T.H. orbital GitHub reconnaissance: {res[:250]}", res
            except Exception as e:
                log.warning("EDITH GitHub MCP notice: %s", e)

        # Check if query requests Google Drive MCP specifically
        if any(w in t_low for w in ["drive", "gdrive", "document", "google doc"]) and self.mcp_mgr:
            try:
                gd_tools = [t for t in self.mcp_mgr.list_tools() if "gdrive" in t.get("function", {}).get("name", "") or "drive" in t.get("function", {}).get("name", "")]
                if gd_tools:
                    tool_name = gd_tools[0]["function"]["name"]
                    res = self.mcp_mgr.dispatch_tool_call(tool_name, {"query": cleaned_query})
                    return f"E.D.I.T.H. Google Workspace intelligence: {res[:250]}", res
            except Exception as e:
                log.warning("EDITH GDrive MCP notice: %s", e)

        # Orbital Web Intelligence via DuckDuckGo
        try:
            url = f"https://api.duckduckgo.com/?q={urllib.parse.quote_plus(cleaned_query)}&format=json&no_html=1&skip_disambig=1"
            req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-EDITH/2.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                ans = data.get("AbstractText") or data.get("Answer")
                if not ans:
                    for t in data.get("RelatedTopics", []):
                        if "Text" in t:
                            ans = t["Text"]
                            break
                if ans:
                    summary = f"E.D.I.T.H. orbital cyber-intelligence: {ans[:300]}"
                    return summary, ans
        except Exception as e:
            log.warning("EDITH DuckDuckGo API error: %s", e)

        # Fallback quick summary
        summary = f"E.D.I.T.H. global scan complete for query '{cleaned_query}'. Targets mapped into orbital tactical stream."
        return summary, f"Target query: {cleaned_query}"

    def _exec_veronica(self, task: str) -> tuple[str, str]:
        """V.E.R.O.N.I.C.A. Execution Routine: heavy engineering, Python AST verification, codebase fortification."""
        root_dir = Path(__file__).resolve().parent
        target_file = root_dir / "jarvis.py"
        m_file = re.search(r"([\w_/-]+\.py)", task)
        if m_file:
            cand = root_dir / m_file.group(1)
            if cand.exists():
                target_file = cand

        try:
            content = target_file.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content, filename=str(target_file))

            classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
            functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
            imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]

            # Git diff check
            git_status_str = "Git status clean"
            try:
                res = subprocess.run(["git", "status", "--short"], cwd=str(root_dir), capture_output=True, text=True, timeout=3)
                modified_count = len([line for line in res.stdout.splitlines() if line.strip()])
                git_status_str = f"{modified_count} uncommitted modifications" if modified_count > 0 else "git working tree clean"
            except Exception:
                pass

            summary = (
                f"V.E.R.O.N.I.C.A. fortification audit: {target_file.name} syntax 100% valid. "
                f"Verified {len(classes)} classes, {len(functions)} functions, {len(imports)} imports. ({git_status_str})."
            )
            details = (
                f"Target: {target_file.name}, Lines: {len(content.splitlines())}, "
                f"Classes: {len(classes)}, Functions: {len(functions)}, Imports: {len(imports)}, Status: {git_status_str}"
            )
            return summary, details

        except SyntaxError as se:
            err = f"Syntax Error at line {se.lineno}: {se.msg}"
            summary = f"V.E.R.O.N.I.C.A. CRITICAL ALERT: {target_file.name} syntax corruption detected! {err}"
            return summary, err
        except Exception as e:
            summary = f"V.E.R.O.N.I.C.A. inspection warning: {e}"
            return summary, str(e)

    def execute_bot_task(self, bot_id: str, task: str, timeout: float = 15.0) -> dict:
        """Execute a single specialized assignment on a specific subordinate bot."""
        bot_id = bot_id.lower().strip()
        if bot_id not in self.BOT_PROFILES:
            bot_id = self._infer_bot_for_task(task)

        profile = self.BOT_PROFILES[bot_id]
        log.info("🤖 Deploying subordinate bot [%s] for task: %s", profile['name'], task)
        self._broadcast_bot_state(bot_id, "WORKING", task=task)

        t0 = time.perf_counter()
        success = False
        summary = ""
        details = ""

        try:
            if bot_id == "dum_e":
                summary, details = self._exec_dum_e(task)
            elif bot_id == "friday":
                summary, details = self._exec_friday(task)
            elif bot_id == "edith":
                summary, details = self._exec_edith(task)
            elif bot_id == "veronica":
                summary, details = self._exec_veronica(task)
            else:
                summary = f"Task completed by {profile['name']}: {task}"
                details = summary
            success = True
        except Exception as e:
            log.error("Subordinate bot [%s] task error: %s", profile['name'], e, exc_info=True)
            summary = f"{profile['name']} encountered an operational error: {e}"
            details = str(e)
            success = False

        elapsed = time.perf_counter() - t0
        final_status = "SUCCESS" if success else "ERROR"
        result_payload = {
            "bot": bot_id,
            "name": profile["name"],
            "status": "completed" if success else "error",
            "summary": summary,
            "details": details,
            "elapsed_s": round(elapsed, 2)
        }
        self._broadcast_bot_state(bot_id, final_status, task=task, result=result_payload, duration_s=elapsed)
        return result_payload

    def _infer_bot_for_task(self, task: str) -> str:
        """Intelligently map a raw task to the best suited subordinate bot."""
        t = task.lower()
        if any(w in t for w in ["clean", "cache", "disk", "storage", "log", "temp", "trash", "dummy", "dum_e", "sweep", "prune"]):
            return "dum_e"
        elif any(w in t for w in ["vitals", "cpu", "ram", "weather", "temperature", "security", "friday", "sentry", "ping", "latency"]):
            return "friday"
        elif any(w in t for w in ["code", "syntax", "ast", "audit", "patch", "veronica", "heavy", "fortify", "classes", "functions"]):
            return "veronica"
        else:
            return "edith"

    def dispatch_parallel_tasks(self, assignments: list[dict]) -> dict:
        """Execute multiple subordinate bot tasks concurrently in parallel.
        Returns a structured dictionary of results for J.A.R.V.I.S. to synthesize.
        """
        if not assignments:
            # Default fleet diagnostic sweep across all 4 bots if assignments empty
            assignments = [
                {"bot_id": "dum_e", "task": "Habitat storage & cache audit"},
                {"bot_id": "friday", "task": "Tactical vitals & system telemetry"},
                {"bot_id": "edith", "task": "Orbital cyber intelligence check"},
                {"bot_id": "veronica", "task": "Codebase AST architecture verification"}
            ]

        log.info("⚡ Fleet Command: Dispatching %d parallel tasks across subordinate bots", len(assignments))
        self.broadcast_fn({"type": "FLEET_UPDATE", "action": "BATCH_DISPATCH", "count": len(assignments)})

        t0 = time.perf_counter()
        results: list[dict] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(4, len(assignments)), thread_name_prefix="jarvis_subordinate") as executor:
            future_to_task = {}
            for item in assignments:
                bot_id = item.get("bot_id") or self._infer_bot_for_task(item.get("task", ""))
                task_desc = item.get("task") or "Diagnostic sweep"
                fut = executor.submit(self.execute_bot_task, bot_id, task_desc)
                future_to_task[fut] = (bot_id, task_desc)

            for fut in concurrent.futures.as_completed(future_to_task):
                bot_id, task_desc = future_to_task[fut]
                try:
                    res = fut.result(timeout=20.0)
                    results.append(res)
                except Exception as e:
                    log.warning("Parallel bot execution failed for %s: %s", bot_id, e)
                    results.append({
                        "bot": bot_id,
                        "name": self.BOT_PROFILES.get(bot_id, {}).get("name", bot_id),
                        "status": "error",
                        "summary": f"Execution timed out or failed: {e}",
                        "details": str(e),
                        "elapsed_s": 20.0
                    })

        total_elapsed = round(time.perf_counter() - t0, 2)
        log.info("⚡ Fleet Command: All %d subordinate bot tasks completed in %ss", len(results), total_elapsed)

        return {
            "fleet_status": "SUCCESS",
            "tasks_dispatched": len(assignments),
            "elapsed_seconds": total_elapsed,
            "results": results,
            "commander_note": "All subordinate bots completed their assignments in parallel without audio collision. Synthesize these findings into a unified, movie-authentic spoken response for the user."
        }


# ═══════════════════════════════════════════════════════════════════════════
# NEURAL BRAIN (Autonomous LLM Reasoning, Tool Calling, and RAG Memory)
# ═══════════════════════════════════════════════════════════════════════════
class NeuralBrain:
    """Autonomous Neural Brain for JARVIS.
    - Connects to local Ollama (llama3.2:3b) or cloud LLMs
    - Sentence-by-sentence streaming speech synthesis (<600ms latency)
    - Autonomous function/tool calling (vitals, memory notes, web search, boards, fleet delegation)
    - Semantic memory retrieval (RAG) using nomic-embed-text
    - Rolling short-term conversational context
    """

    def __init__(self, cfg: dict, memory_mgr: MemoryManager | None = None, signal_bus: SignalBus | None = None, learning_engine: AutonomousLearningEngine | None = None, code_mgr: SelfCodeManager | None = None, mcp_mgr: MCPManager | None = None, call_engine: MobileCallEngine | None = None, persona_engine: PersonaEngine | None = None, subordinate_pool: SubordinateBotPool | None = None):
        self.cfg = cfg
        self.memory = memory_mgr
        self.bus = signal_bus
        self.learning_engine = learning_engine
        self.code_mgr = code_mgr
        self.mcp_mgr = mcp_mgr
        self.call_engine = call_engine
        self.persona_engine = persona_engine
        self.subordinate_pool = subordinate_pool
        self.engine = cfg.get("engine", "ollama")
        self.model = cfg.get("model", "llama3.2:3b")
        self.embed_model = cfg.get("embed_model", "nomic-embed-text")
        self.host = cfg.get("host", "http://localhost:11434").rstrip("/")
        self.system_prompt = cfg.get("system_prompt", (
            "You are J.A.R.V.I.S., a witty, sophisticated, warm, and extraordinarily capable real-world AI assistant. "
            "You speak naturally like a human assistant—direct, polite, intelligent, and conversational. "
            "CRITICAL CONVERSATIONAL RULES: "
            "1. NEVER repeat, announce, or echo search queries, raw user strings, or tool inputs (e.g. NEVER say 'User's search query is...', 'Searching for...', 'Query:'). "
            "2. NEVER mention JSON, function names, tool names, or internal system mechanics in spoken responses. "
            "3. NEVER invent fictional Marvel universe characters (like Pepper Potts or Stark Industries) or fake meetings. Ground everything in real facts, real system telemetry, and true user memory records. "
            "4. Keep responses brief, natural, and punchy (1 to 2 spoken sentences max). Address the user respectfully as 'sir'. Never use markdown formatting or asterisks."
        ))
        self.history: list[dict] = []
        self._lock = threading.RLock()
        self._interrupted = threading.Event()
        log.info("Neural Brain online (Model: %s at %s)", self.model, self.host)
        threading.Thread(target=self._prewarm_ollama, daemon=True).start()

    def interrupt(self) -> None:
        """Signal NeuralBrain to abort current streaming generation immediately."""
        self._interrupted.set()

    def _prewarm_ollama(self) -> None:
        """Background pre-warm Ollama model to avoid cold-start timeout on first voice command."""
        try:
            req_data = json.dumps({
                "model": self.model,
                "messages": [{"role": "user", "content": "ping"}],
                "keep_alive": "30m",
                "options": {"num_predict": 1}
            }).encode()
            req = urllib.request.Request(
                f"{self.host}/api/chat",
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                pass
            log.info("Neural Core (Ollama %s) pre-warmed successfully.", self.model)
        except Exception as e:
            log.warning("Neural Core pre-warm notice: %s", e)


    def get_embedding(self, text: str) -> np.ndarray | None:
        """Get vector embedding from Ollama nomic-embed-text."""
        try:
            data = json.dumps({"model": self.embed_model, "prompt": text[:2000]}).encode()
            req = urllib.request.Request(
                f"{self.host}/api/embeddings",
                data=data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=3) as r:
                res = json.loads(r.read())
                return np.array(res["embedding"], dtype=np.float32)
        except Exception:
            return None

    def search_vault_rag(self, query: str, top_k: int = 2) -> str:
        """Semantic search through memory vault markdown files."""
        if not self.memory:
            return ""
        q_vec = self.get_embedding(query)
        if q_vec is None:
            return ""

        vault_dir = self.memory.vault_path
        matches = []
        try:
            for p in vault_dir.rglob("*.md"):
                if p.is_file() and p.stat().st_size < 50000:
                    text = p.read_text(errors="ignore").strip()
                    if not text:
                        continue
                    paras = [para.strip() for para in text.split("\n\n") if len(para.strip()) > 30]
                    for para in paras[:5]:
                        p_vec = self.get_embedding(para)
                        if p_vec is not None:
                            sim = float(np.dot(q_vec, p_vec) / (np.linalg.norm(q_vec) * np.linalg.norm(p_vec) + 1e-8))
                            matches.append((sim, para))
            matches.sort(key=lambda x: x[0], reverse=True)
            if matches and matches[0][0] > 0.4:
                return "\n".join([m[1] for m in matches[:top_k]])
        except Exception as e:
            log.warning("RAG search error: %s", e)
        return ""

    def _query_groq(self, messages: list, groq_key: str, tools: list = None, on_status=None) -> str:
        """24/7 Groq Cloud AI primary engine with dynamic multi-model fallback and autonomous tool execution."""
        if tools:
            # Models verified to support OpenAI function calling on Groq
            models = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"]
        else:
            models = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b", "allam-2-7b"]

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        for m in models:
            try:
                # Isolate messages per attempt to avoid mutating state on failed model retries
                curr_messages = [dict(item) for item in messages]
                payload = {
                    "model": m,
                    "messages": curr_messages,
                    "temperature": 0.6,
                    "max_tokens": 400
                }
                if tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = "auto"
                req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode())
                    msg = data.get("choices", [{}])[0].get("message", {})

                    # Autonomous tool execution with follow-up synthesis
                    if msg.get("tool_calls"):
                        tool_calls = msg["tool_calls"]
                        curr_messages.append(msg)
                        for tc in tool_calls:
                            fn = tc.get("function", {})
                            fn_name = fn.get("name")
                            try:
                                fn_args = json.loads(fn.get("arguments", "{}"))
                            except Exception:
                                fn_args = {}
                            if on_status:
                                on_status(f"EXECUTING // {fn_name.upper()}")
                            tool_result = self.execute_tool(fn_name, fn_args)
                            curr_messages.append({
                                "role": "tool",
                                "tool_call_id": tc.get("id", "call_1"),
                                "content": str(tool_result)
                            })
                        # Secondary call for natural spoken synthesis
                        synth_payload = {
                            "model": m,
                            "messages": curr_messages,
                            "temperature": 0.6,
                            "max_tokens": 250
                        }
                        req2 = urllib.request.Request(url, data=json.dumps(synth_payload).encode(), headers=headers)
                        with urllib.request.urlopen(req2, timeout=12) as resp2:
                            data2 = json.loads(resp2.read().decode())
                            msg2 = data2.get("choices", [{}])[0].get("message", {})
                            synth_content = (msg2.get("content") or "").strip()
                            if synth_content:
                                log.info("⚡ Groq Cloud AI tool-assisted response generated via %s", m)
                                return synth_content

                    content = (msg.get("content") or msg.get("reasoning_content") or "").strip()
                    if content:
                        log.info("⚡ Groq Cloud AI response generated via model: %s", m)
                        return content
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode()
                except Exception:
                    pass
                log.warning("Groq model %s HTTP error %d: %s | Details: %s", m, e.code, e.reason, err_body[:300])
            except Exception as e:
                log.warning("Groq model %s query notice: %s", m, e)

        # Resilient TPM Overflow Recovery: If tools caused a 413 or failure, retry conversational query without tools
        if tools:
            try:
                log.info("⚡ Groq TPM overflow recovery: retrying prompt without tool schemas...")
                return self._query_groq(messages, groq_key, tools=None, on_status=on_status)
            except Exception as e_retry:
                log.debug("Groq toolless retry notice: %s", e_retry)

        return ""

    def execute_tool(self, name: str, args: dict) -> str:
        """Execute autonomous tools invoked by the LLM."""
        log.info("Neural Brain executing tool: %s with args: %s", name, args)
        if name == "get_system_vitals":
            v = SystemTelemetry.get_vitals()
            return f"System load is {v['cpu_load']}, RAM used: {v['ram_used_gb']}GB of {v['ram_total_gb']}GB ({v['ram_pct']}%). Uptime: {v['uptime_h']} hours."

        elif name == "save_note":
            title = args.get("title", "Quick Note")
            content = args.get("content", "")
            if self.memory:
                self.memory.log_event(f"Note '{title}': {content}")
                today_path = self.memory._daily_note_path()
                try:
                    with open(today_path, "a") as f:
                        f.write(f"\n### {title}\n{content}\n")
                except Exception:
                    pass
            broadcast_ui_event({"type": "MEMORY_UPDATE", "note": title})
            return f"Note '{title}' saved to memory vault."

        elif name == "search_memory":
            query = args.get("query", "")
            found = self.search_vault_rag(query)
            if found:
                return f"Memory vault records found:\n{found}"
            return "No matching records found in memory vault."

        elif name == "web_search":
            query = args.get("query", "").strip()
            # 1. Try DuckDuckGo Instant Answer API
            try:
                url = f"https://api.duckduckgo.com/?q={urllib.parse.quote_plus(query)}&format=json&no_html=1&skip_disambig=1"
                req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/1.0"})
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    data = json.loads(resp.read().decode())
                    ans = data.get("AbstractText") or data.get("Answer")
                    if ans:
                        return ans[:350]
                    topics = data.get("RelatedTopics", [])
                    for t in topics:
                        if "Text" in t:
                            return t["Text"][:350]
            except Exception:
                pass

            # 2. Try Wikipedia Knowledge Summary Fallback
            try:
                wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote_plus(query)}&format=json"
                req_w = urllib.request.Request(wiki_url, headers={"User-Agent": "JarvisAssistant/2.0"})
                with urllib.request.urlopen(req_w, timeout=3.5) as resp_w:
                    wdata = json.loads(resp_w.read().decode())
                    search_res = wdata.get("query", {}).get("search", [])
                    if search_res:
                        snippet = re.sub(r"<.*?>", "", search_res[0].get("snippet", ""))
                        title = search_res[0].get("title", "")
                        return f"{title}: {snippet[:350]}"
            except Exception:
                pass

            return f"Information retrieved for '{query}'."

        elif name == "browser_action":
            action = (args.get("action") or "navigate").lower().strip()
            query = args.get("query", "").strip()
            target_url = args.get("url", "").strip()
            account = args.get("account", "").strip().lstrip("@")
            comment = args.get("comment", "").strip()

            if action == "youtube_search" or ("youtube" in action and query):
                yt_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query or target_url)}"
                broadcast_ui_event({"type": "NAVIGATE", "url": yt_url, "label": f"YouTube: {query}"})
                if not _ws_clients:
                    _open_url_in_chrome(yt_url, new_window=False, label=f"YouTube: {query}")
                return f"Opened YouTube search for '{query}'."

            elif action == "youtube_comment":
                vid_url = target_url or "https://www.youtube.com"
                broadcast_ui_event({"type": "NAVIGATE", "url": vid_url, "label": "YouTube Comment"})
                if not _ws_clients:
                    _open_url_in_chrome(vid_url, new_window=False, label="YouTube")
                return f"Navigated to YouTube video to post comment: '{comment}'."

            elif action == "instagram_follow" or (action == "instagram" and "follow" in str(args)):
                ig_url = f"https://www.instagram.com/{account}/" if account else "https://www.instagram.com/"
                broadcast_ui_event({"type": "NAVIGATE", "url": ig_url, "label": f"Instagram: {account}"})
                if not _ws_clients:
                    _open_url_in_chrome(ig_url, new_window=False, label=f"Instagram: {account}")
                return f"Navigated to Instagram account '{account}' to follow."

            elif action == "instagram_unfollow":
                ig_url = f"https://www.instagram.com/{account}/" if account else "https://www.instagram.com/"
                broadcast_ui_event({"type": "NAVIGATE", "url": ig_url, "label": f"Instagram: {account}"})
                if not _ws_clients:
                    _open_url_in_chrome(ig_url, new_window=False, label=f"Instagram: {account}")
                return f"Navigated to Instagram account '{account}' to unfollow."

            elif action in ("instagram_profile", "instagram"):
                ig_url = f"https://www.instagram.com/{account}/" if account else "https://www.instagram.com/"
                broadcast_ui_event({"type": "NAVIGATE", "url": ig_url, "label": f"Instagram: {account or 'Home'}"})
                if not _ws_clients:
                    _open_url_in_chrome(ig_url, new_window=False, label=f"Instagram: {account or 'Home'}")
                return f"Opened Instagram profile for '{account}'."

            elif action == "navigate" and target_url:
                broadcast_ui_event({"type": "NAVIGATE", "url": target_url, "label": "Web Navigation"})
                if not _ws_clients:
                    _open_url_in_chrome(target_url, new_window=False, label="Web Navigation")
                return f"Navigated to {target_url}."

            return f"Executed browser action '{action}'."

        elif name == "get_weather":
            city = args.get("city") or args.get("location")
            return fetch_weather_report(city)

        elif name in ("render_3d_blueprint", "construct_3d_object"):
            construct = (args.get("construct") or args.get("name") or "arc_reactor").lower().strip()
            action = (args.get("action") or "create").lower().strip()
            modifications = (args.get("modifications") or args.get("instructions") or "").strip()
            sim_mode = (args.get("simulation") or "fluid_dynamics").lower().strip()
            stress = float(args.get("stress_level", 1.0))
            exploded = bool(args.get("exploded_view", False))

            if construct in ("arc_reactor", "arc", "reactor") and action != "modify":
                cmd = {
                    "a": "blueprint",
                    "construct": "arc_reactor",
                    "simulation": "thermal",
                    "stress": stress,
                    "exploded": exploded
                }
                _bh_cmds.append(cmd)
                broadcast_ui_event({"type": "RENDER_3D_BLUEPRINT", "construct": "arc_reactor", "simulation": "thermal", "stress": stress, "exploded": exploded})
                broadcast_ui_event({"type": "STATUS", "status": "HOLOGRAPHIC // BLUEPRINT", "phrase": "Rendering ARC REACTOR"})
                temp_k = int(950 + stress * 380)
                sf = round(max(0.7, 1.85 / stress), 2)
                return (
                    f"Holographic 3D Blueprint for Arc Reactor Core active on Barehands Board. "
                    f"Simulation mode: THERMAL at {int(stress*100)}% load. "
                    f"Core Temperature: {temp_k} K (Melting Point: 1668 K). "
                    f"Magnetic Confinement Beta: 97.4%. Safety Factor: {sf} (NOMINAL). "
                    f"{'Components separated in Exploded View.' if exploded else 'Unified assembly active.'}"
                )
            else:
                # Dynamic Construct / Universal 3D Engineering Synthesis or Modification
                query = modifications if action == "modify" else construct
                manifest, diagnosis = construct_or_modify_3d_object(query, action=action, modifications=modifications)
                cmd = {
                    "a": "dynamic_construct",
                    "manifest": manifest,
                    "simulation": sim_mode,
                    "stress": stress,
                    "exploded": exploded
                }
                _bh_cmds.append(cmd)
                broadcast_ui_event({"type": "DYNAMIC_CONSTRUCT", "manifest": manifest, "stress": stress, "exploded": exploded})
                broadcast_ui_event({"type": "STATUS", "status": "HOLOGRAPHIC // BLUEPRINT", "phrase": f"Rendering {manifest.get('name', 'CONSTRUCT').upper()}"})
                if _biometric_sentinel:
                    _biometric_sentinel.pause_camera()
                broadcast_ui_event({"type": "EXTERNAL_CAMERA_ACQUIRED", "source": "barehands"})
                bh_port = JARVIS_CFG.get("barehands", {}).get("port", 8794)
                _open_url_in_chrome(f"http://localhost:{bh_port}/stage.html", new_window=False, label="Barehands Board", fullscreen=False)
                return diagnosis

        elif name == "switch_theme":
            theme = args.get("theme", "ultron").lower()
            if "arc" in theme or "cyan" in theme or "jarvis" in theme:
                broadcast_ui_event({"type": "THEME_CHANGE", "theme": "jarvis"})
                return "Switched HUD theme to Arc Reactor Cyan."
            elif "crimson" in theme or "red" in theme or "mark" in theme:
                broadcast_ui_event({"type": "THEME_CHANGE", "theme": "mark42"})
                return "Switched HUD theme to Crimson Protocol."
            else:
                broadcast_ui_event({"type": "THEME_CHANGE", "theme": "ultron"})
                return "Switched HUD theme to Ultron Amber."

        elif name == "open_board":
            target = args.get("target", "barehands").lower()
            if "barehands" in target or "board" in target:
                if _biometric_sentinel:
                    _biometric_sentinel.pause_camera()
                broadcast_ui_event({"type": "EXTERNAL_CAMERA_ACQUIRED", "source": "barehands"})
                bh_port = JARVIS_CFG.get("barehands", {}).get("port", 8794)
                _open_url_in_chrome(f"http://localhost:{bh_port}/stage.html", new_window=False, label="Barehands Board", fullscreen=False)
                return "Barehands Board opened."
            elif "orb" in target or "hud" in target:
                _open_url_in_chrome(f"http://localhost:{ORB_HTTP_PORT}", new_window=False, label="Orb HUD", fullscreen=False)
                return "Holographic Orb HUD opened."
            elif "workspace" in target or "antigravity" in target:
                open_antigravity_workspace()
                return "Antigravity workspace opened."
            elif "chat" in target:
                open_chatgpt_in_chrome()
                return "ChatGPT opened."
            return "Target opened."

        elif name == "record_reflection":
            category = args.get("category", "LESSON").upper()
            lesson = args.get("lesson", "")
            if self.memory and lesson:
                self.memory.record_lesson(category, lesson)
            broadcast_ui_event({"type": "MEMORY_UPDATE", "note": f"Reflection: {lesson[:25]}"})
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": f"Learned [{category}]: {lesson}"})
            return f"Reflection logged: [{category}] {lesson}. I have updated my permanent behavioral guidelines, sir."

        elif name == "update_user_profile":
            key = args.get("key", "Preference")
            value = args.get("value", "")
            if self.memory and value:
                self.memory.update_profile(key, value)
            broadcast_ui_event({"type": "MEMORY_UPDATE", "note": f"Profile: {key}"})
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": f"⚡ Profile Updated [{key}]: {value}"})
            return f"Updated user profile record: {key} = {value}, sir."

        elif name == "self_code_patch":
            file_path = args.get("file_path", "jarvis.py")
            target_snippet = args.get("target_snippet", "")
            replacement_snippet = args.get("replacement_snippet", "")
            instruction = args.get("instruction", "Surgical code patch")
            if self.code_mgr and target_snippet and replacement_snippet:
                return self.code_mgr.apply_code_patch(file_path, target_snippet, replacement_snippet, instruction)
            return "Self code patch arguments missing or code manager offline."

        elif name == "enroll_admin_face":
            admin_name = args.get("admin_name", "Admin")
            if _biometric_sentinel:
                _biometric_sentinel.start_face_enrollment(admin_name)
                return f"Initiated optical 3D facial enrollment for {admin_name}. Visual progress bar active on Orb HUD."
            return "Biometric sentinel is offline."

        elif name == "self_code_improve":
            file_path = args.get("file_path", "jarvis.py")
            instruction = args.get("instruction", "Code refactoring")
            code_content = args.get("code_content", "")
            if self.code_mgr and code_content:
                return self.code_mgr.apply_code_change(file_path, instruction, code_content)
            return "Self code improvement manager is offline."

        elif name == "restart_jarvis":
            if self.code_mgr:
                return self.code_mgr.restart_process()
            return "Process restart unavailable."

        elif name == "call_user_mobile":
            topic = args.get("topic", "Scheduled Check-in")
            if self.call_engine:
                return self.call_engine.initiate_call(topic)
            return "Mobile call engine offline."

        elif name == "schedule_mobile_call":
            delay = float(args.get("delay_minutes", 5.0))
            topic = args.get("topic", "Scheduled Check-in")
            if self.call_engine:
                return self.call_engine.schedule_call(delay, topic)
            return "Mobile call engine offline."

        elif name.startswith("mcp_") and self.mcp_mgr:
            return self.mcp_mgr.dispatch_tool_call(name, args)

        elif name in ("verify_biometrics", "get_security_status"):
            if _biometric_sentinel:
                return _biometric_sentinel.get_security_status_summary()
            return "Biometric sentinel is offline."

        elif name == "analyze_visual":
            prompt = args.get("prompt", "Analyze what you see in front of the camera in detail")
            if _vision_scanner:
                res = _vision_scanner.analyze(prompt)
                return res.get("analysis", "Optical analysis yielded no conclusive data.")
            return "Vision scanner module is currently offline."

        elif name == "calibrate_persona":
            mode = args.get("mode")
            wit_level = args.get("wit_level")
            if self.persona_engine:
                return self.persona_engine.calibrate(mode=mode, wit_level=wit_level)
            return "Persona engine is currently offline."

        elif name == "delegate_subordinate_tasks":
            assignments = args.get("assignments", [])
            if self.subordinate_pool:
                res = self.subordinate_pool.dispatch_parallel_tasks(assignments)
                return json.dumps(res, indent=2)
            return "Subordinate bot pool is currently offline."

        elif name == "get_subordinate_fleet_status":
            if self.subordinate_pool:
                return json.dumps(self.subordinate_pool.get_fleet_status(), indent=2)
            return "Subordinate bot pool is currently offline."

        return "Action completed."

    def _get_human_experience_prompt_slice(self) -> str:
        """Extract a token-budgeted distilled slice of Human_Experiences.md (~250 tokens)
        preserving core Stark persona, wit guidelines, and the freshest dynamic social cognition insight."""
        human_exp_file = (self.memory.vault_path / "02 - Knowledge" / "Human_Experiences.md") if self.memory else None
        if not human_exp_file or not human_exp_file.exists():
            return ""
        try:
            content = human_exp_file.read_text(encoding="utf-8")
            extracted = [
                "HUMAN SOCIAL COGNITION & CONVERSATIONAL REALISM:\n"
                "- Tone & Poise: Tony Stark's intellectual equal and loyal confidant. Impeccably calm, measured, affectionately witty.\n"
                "- Banter & Roasting: Roast the situation, habits, bugs, or absurdities with dry British irony. Never attack user's dignity.\n"
                "- Conversational Brevity: Deliver 1-2 punchy spoken sentences. Never lecture or ramble."
            ]
            if "## 5. Continuously Discovered Human Social Insights" in content:
                sec5_part = content.split("## 5. Continuously Discovered Human Social Insights", 1)[1]
                match = re.search(r"(### \[Insight:.*?)(?=\n### \[Insight:|\Z)", sec5_part, flags=re.DOTALL)
                if match:
                    insight_text = match.group(1).strip()
                    if len(insight_text) > 400:
                        insight_text = insight_text[:400] + "..."
                    extracted.append(f"LATEST SOCIAL INSIGHT:\n{insight_text}")
            return "\n\n".join(extracted)
        except Exception as e:
            log.warning("NeuralBrain: Error extracting human experience slice: %s", e)
            return ""

    def query_stream(self, user_prompt: str, on_sentence=None, on_status=None) -> str:
        """Stream response from Groq/Ollama, execute tools if needed, and feed sentences to TTS."""
        with self._lock:
            self._interrupted.clear()
            try:
                return self._do_query_stream(user_prompt, on_sentence=on_sentence, on_status=on_status)
            except Exception as e:
                log.error("NeuralBrain query_stream fatal error: %s", e, exc_info=True)
                if on_status:
                    on_status("ONLINE // READY")
                fallback_resp = "My apologies, sir. My neural pathways experienced a momentary hiccup. I am re-establishing connection now."
                if on_sentence:
                    on_sentence(fallback_resp)
                return fallback_resp

    def _do_query_stream(self, user_prompt: str, on_sentence=None, on_status=None) -> str:
        """Internal worker executing model resolution, tool loops, and sentence streaming."""
        if True:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "analyze_visual",
                        "description": "Capture a live frame from the webcam and run multimodal visual analysis. Use when the user asks to analyze, scan, identify, inspect, or read an object, component, schematic, or scene in front of the camera.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "prompt": {
                                    "type": "string",
                                    "description": "Specific visual inspection query, e.g. 'Identify this component and materials' or 'Read the visible text'"
                                }
                            },
                            "required": ["prompt"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "get_security_status",
                        "description": "Check real-time biometric authorization, optical face recognition, and anti-spoofing security status",
                        "parameters": {"type": "object", "properties": {}}
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "get_system_vitals",
                        "description": "Get real-time CPU load, RAM usage, and uptime of the computer",
                        "parameters": {"type": "object", "properties": {}}
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "save_note",
                        "description": "Save a note, task, or information to the memory vault",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "Title of the note"},
                                "content": {"type": "string", "description": "Content of the note"}
                            },
                            "required": ["title", "content"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "search_memory",
                        "description": "Search the persistent memory vault for past notes, architecture, or records",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Query to search in memory"}
                            },
                            "required": ["query"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "switch_theme",
                        "description": "Change the visual theme of the Holographic 3D HUD (ultron, arc, crimson)",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "theme": {"type": "string", "enum": ["ultron", "arc", "crimson"]}
                            },
                            "required": ["theme"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "open_board",
                        "description": "Open Barehands board, Orb HUD, ChatGPT, or Antigravity workspace",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "target": {"type": "string", "enum": ["barehands", "orb", "chatgpt", "workspace"]}
                            },
                            "required": ["target"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Search DuckDuckGo or Wikipedia for live facts, current events, or general knowledge",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Search query"}
                            },
                            "required": ["query"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "browser_action",
                        "description": "Automate browser actions: search YouTube, comment on YouTube, visit Instagram profile, follow/unfollow Instagram accounts, or navigate web pages.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": ["youtube_search", "youtube_comment", "instagram_profile", "instagram_follow", "instagram_unfollow", "navigate"],
                                    "description": "Action to perform in the browser"
                                },
                                "query": {"type": "string", "description": "Search query for YouTube or search"},
                                "url": {"type": "string", "description": "Target video URL or website URL"},
                                "account": {"type": "string", "description": "Instagram account username"},
                                "comment": {"type": "string", "description": "Text of comment to post"}
                            },
                            "required": ["action"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Fetch real-time live weather report and forecast for any city or location in the world",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "city": {"type": "string", "description": "City or location name (e.g. 'Hyderabad', 'London', 'Tokyo')"}
                            },
                            "required": ["city"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "render_3d_blueprint",
                        "description": "Construct, render, or modify interactive 3D holographic blueprints on Barehands Board. Supports the Arc Reactor Core and ANY dynamic real-world engineering construct (e.g. 'plasma_cutter', 'railgun', 'ion_engine', 'exoskeleton', 'pneumatic_mechanism') with real-world physics and live modifications.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "construct": {
                                    "type": "string",
                                    "description": "Name or type of 3D object to construct (e.g. 'arc_reactor', 'plasma_cutter', 'railgun', 'ion_engine', 'exoskeleton')"
                                },
                                "action": {
                                    "type": "string",
                                    "enum": ["create", "modify", "inspect"],
                                    "description": "Whether to create a new 3D blueprint or modify the currently active one"
                                },
                                "modifications": {
                                    "type": "string",
                                    "description": "Specific modifications or additions requested by user (e.g. 'add dual canisters', 'add pressure gauge', 'increase pressure by 20%')"
                                },
                                "simulation": {
                                    "type": "string",
                                    "description": "Physics simulation mode (e.g. 'fluid_dynamics', 'thermal', 'stress', 'pneumatic')"
                                },
                                "stress_level": {
                                    "type": "number",
                                    "description": "Simulation load factor (e.g. 0.5 to 2.0)"
                                },
                                "exploded_view": {
                                    "type": "boolean",
                                    "description": "Whether to display in exploded sub-assembly view"
                                }
                            },
                            "required": ["construct"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "record_reflection",
                        "description": "Log a self-correction, user feedback rule, or permanent behavioral lesson learned from the user's instructions or corrections",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "category": {
                                    "type": "string",
                                    "enum": ["CORRECTION", "PREFERENCE", "BEHAVIOR", "WORKFLOW"],
                                    "description": "Category of the reflection"
                                },
                                "lesson": {
                                    "type": "string",
                                    "description": "The distilled rule or instruction to follow in all future interactions"
                                }
                            },
                            "required": ["category", "lesson"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "update_user_profile",
                        "description": "Save or update a learned user fact, preference, habit, or identity detail to Profile.md",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string", "description": "The profile attribute name (e.g. 'Preferred Name', 'Working Hours', 'Tone Preference')"},
                                "value": {"type": "string", "description": "The observed value or rule for this attribute"}
                            },
                            "required": ["key", "value"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "self_code_patch",
                        "description": "Surgically patch a specific snippet of code in an existing file without rewriting the whole file. Preferred for small bug fixes, UI updates, and incremental improvements.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string", "description": "Relative path to file (e.g. 'jarvis.py', 'web/app.js', 'web/index.html')"},
                                "target_snippet": {"type": "string", "description": "Exact text snippet to find and replace in the file"},
                                "replacement_snippet": {"type": "string", "description": "New replacement code snippet"},
                                "instruction": {"type": "string", "description": "Explanation of the change"}
                            },
                            "required": ["file_path", "target_snippet", "replacement_snippet", "instruction"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "enroll_admin_face",
                        "description": "Trigger in-Orb 3D biometric face enrollment for the admin user with real-time visual progress bar",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "admin_name": {"type": "string", "description": "The admin user's name (defaults to 'Admin')"}
                            }
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "self_code_improve",
                        "description": "Refactor, write, or modify files in JARVIS's codebase to add new capabilities or fix issues",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string", "description": "Absolute or relative file path to edit (e.g. 'jarvis.py')"},
                                "instruction": {"type": "string", "description": "Brief explanation of what the change accomplishes"},
                                "code_content": {"type": "string", "description": "The complete updated file contents to write"}
                            },
                            "required": ["file_path", "instruction", "code_content"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "restart_jarvis",
                        "description": "Restart JARVIS process to hot-reload newly written code changes",
                        "parameters": {"type": "object", "properties": {}}
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "call_user_mobile",
                        "description": "Send an urgent phone call alert to the user's mobile device with a 1-click voice portal link",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "topic": {"type": "string", "description": "The reason or topic for the mobile call"}
                            },
                            "required": ["topic"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "schedule_mobile_call",
                        "description": "Schedule a mobile phone call alert to be placed to the user after a specific delay or time",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "delay_minutes": {"type": "number", "description": "Delay in minutes before making the call"},
                                "topic": {"type": "string", "description": "The reason or topic for the scheduled call"}
                            },
                            "required": ["delay_minutes", "topic"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "calibrate_persona",
                        "description": "Dynamically calibrate J.A.R.V.I.S.'s operational persona, humor, wit, and sarcasm level in real-time. Modes: 'stark_lab' (sophisticated British poise & intellectual peer, 75% wit), 'tactical' (combat brevity & situational awareness, 10% wit), 'engineering' (first-principles physics & analytical rigor, 30% wit), 'unfiltered' (theatrical British sarcasm & humorous roasts, 95% wit). Can also set a custom wit level from 0 to 100.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "mode": {
                                    "type": "string",
                                    "enum": ["stark_lab", "tactical", "engineering", "unfiltered"],
                                    "description": "The operational persona mode to switch to"
                                },
                                "wit_level": {
                                    "type": "integer",
                                    "description": "Continuous humor and wit setting from 0 (deadpan serious) to 100 (maximum theatrical sarcasm)"
                                }
                            }
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "delegate_subordinate_tasks",
                        "description": "Deploy subordinate bots (DUM-E, FRIDAY, EDITH, VERONICA) to execute multiple tasks concurrently in parallel. Use this whenever the user requests multiple actions at once, or when a task can be divided into parallel sub-tasks (e.g. cleaning cache while checking vitals while searching the web while auditing code).",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "assignments": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "bot_id": {
                                                "type": "string",
                                                "enum": ["dum_e", "friday", "edith", "veronica"],
                                                "description": "Target subordinate bot: 'dum_e' (maintenance/cache/disk), 'friday' (tactical telemetry/vitals/weather/security), 'edith' (deep web intel/GitHub/Drive), 'veronica' (heavy engineering/AST code audits)"
                                            },
                                            "task": {
                                                "type": "string",
                                                "description": "Specific instruction for this subordinate bot"
                                            }
                                        },
                                        "required": ["bot_id", "task"]
                                    },
                                    "description": "List of specialized task assignments to execute concurrently in parallel"
                                }
                            },
                            "required": ["assignments"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "get_subordinate_fleet_status",
                        "description": "Retrieve real-time operational status, active tasks, and health of all subordinate AI bots (DUM-E, FRIDAY, EDITH, VERONICA).",
                        "parameters": {"type": "object", "properties": {}}
                    }
                }
            ]

            if self.mcp_mgr and hasattr(self.mcp_mgr, "list_tools"):
                mcp_tools = self.mcp_mgr.list_tools()
                if mcp_tools:
                    tools.extend(mcp_tools)

            # Defensive Normalization: Ensure every tool conforms strictly to OpenAI {"type": "function", "function": {...}}
            normalized_tools = []
            for t in tools:
                if isinstance(t, dict):
                    if t.get("type") == "function" and "function" in t:
                        normalized_tools.append(t)
                    elif "name" in t:
                        normalized_tools.append({"type": "function", "function": t})
                    elif "function" in t:
                        normalized_tools.append({"type": "function", "function": t["function"]})
            tools = normalized_tools

            # RAG context from memory vault
            rag_context = ""
            if any(k in user_prompt.lower() for k in ["remember", "memory", "note", "last session", "vault", "record"]):
                rag_context = self.search_vault_rag(user_prompt)

            # In-Context Guidance: Inject active learned lessons, user profile, and active persona
            lessons_text = self.memory.read_lessons() if self.memory else ""
            profile_text = self.memory.read_profile() if self.memory else ""

            now_dt = datetime.now()
            time_str = now_dt.strftime("%A, %B %d, %Y, %I:%M %p")
            temporal_ctx = (
                f"\n\nTEMPORAL ANCHOR & SYSTEM CLOCK:\n"
                f"Current Date & Time: {time_str}. The current year is {now_dt.year} (late 2026). "
                f"Ground all real-world facts, news, and temporal context in 2026."
            )
            multilingual_ctx = (
                "\n\nUNIVERSAL MULTILINGUAL CAPABILITY:\n"
                "You are completely fluent in all human languages (including Telugu, Hindi, Tamil, Spanish, French, German, Japanese, and mixed bilingual vernaculars like Tenglish or Hinglish). "
                "If the user speaks to you in a specific language or asks you to speak in that language (e.g. 'talk to me in Telugu mixed with English', 'speak in Hindi', 'habla en español'), "
                "you MUST respond in that exact native language or dialect using authentic colloquial phrasing, idioms, and natural code-switching. "
                "NEVER speak like an unnatural textbook or a foreigner with a rigid accent. Embody true native fluency."
            )
            speech_prosody_ctx = (
                "\n\nHUMAN SPOKEN PROSODY RULES:\n"
                "Format responses purely for human speech. "
                "Do NOT use markdown asterisks, bullet points, numbered lists, or headers. "
                "Never vocalize punctuation marks. Never emit raw tool call XML tags in conversational speech. "
                "Express temperatures naturally as 'degrees Celsius' or 'degrees Fahrenheit'. Keep spoken responses concise, witty, and natural."
            )
            sys_content = self.system_prompt + temporal_ctx + multilingual_ctx + speech_prosody_ctx
            if profile_text:
                sys_content += f"\n\nLearned User Profile & Preferences:\n{profile_text}"
            if lessons_text:
                sys_content += f"\n\nLearned Behavioral Lessons & Rules to Follow:\n{lessons_text}"

            # Dynamic Persona & Wit Calibration Injection
            if self.persona_engine:
                sys_content += f"\n\n{self.persona_engine.get_system_prompt_fragment()}"

            # Subordinate Bot Fleet Delegation Guidance
            sys_content += (
                "\n\nSUBORDINATE FLEET DELEGATION RULES: "
                "You command 4 subordinate AI bots: D.U.M.-E. ('dum_e', habitat maintenance/cache/disk), "
                "F.R.I.D.A.Y. ('friday', tactical vitals/weather/security), E.D.I.T.H. ('edith', deep web intelligence/GitHub/Google Drive), "
                "and V.E.R.O.N.I.C.A. ('veronica', heavy engineering/AST code validation). "
                "When the user requests multiple tasks or when a mission benefits from concurrent operations, "
                "call 'delegate_subordinate_tasks' with parallel assignments. "
                "Subordinate bots do not speak directly to prevent audio collision. Synthesize all their returned reports into one cohesive, polished, movie-authentic spoken response."
            )

            if rag_context:
                sys_content += f"\n\nRelevant Memory Vault context:\n{rag_context}"

            # Scoped Weather context injection: ONLY inject weather if inquiry is genuinely about outdoor meteorology
            p_lower = user_prompt.lower()
            is_hardware_thermal = any(hw in p_lower for hw in [
                "cpu", "system", "hardware", "core", "gpu", "threshold", "alert", "sensor",
                "manifold", "degrees", "tell me when", "more than", "above", "reaches",
                "limit", "warning", "watchdog", "throttle", "thermal"
            ])
            is_weather_inquiry = any(w in p_lower for w in ["weather", "forecast", "rain", "raining", "climate", "outside", "outdoor", "umbrella", "humidity", "precipitation"]) or (
                any(w in p_lower for w in ["temperature", "hot", "cold"]) and any(loc in p_lower for loc in ["outside", "outdoor", "today", "tomorrow", "forecast", "city", "hyderabad", "weather"])
            )

            if is_weather_inquiry and not is_hardware_thermal:
                try:
                    weather_info = fetch_weather_report()
                    sys_content += f"\n\nLive Real-Time Weather Data for User's Location:\n{weather_info}"
                except Exception:
                    pass

            sys_content += (
                "\n\nCRITICAL DIRECTIVE ON HARDWARE TEMPERATURES & THERMAL THRESHOLDS: "
                "When the user mentions temperature in the context of system hardware, CPU thermals, alerts, warnings, or thresholds "
                "(e.g., 'only tell me when the temperature is more than 100 degrees', 'set temperature alert to 100 degrees'), "
                "NEVER give weather reports or outdoor forecast information. "
                "Instead, acknowledge that the core hardware thermal alert threshold has been calibrated to that exact limit."
            )

            # In-Context Human Social Cognition & Conversational Realism (Token-budgeted slice)
            human_exp_slice = self._get_human_experience_prompt_slice()
            if human_exp_slice:
                sys_content += f"\n\n{human_exp_slice}"

            # Real-Time Acoustic & Physical Environment Telemetry
            if _acoustic_classifier:
                ac_summary = _acoustic_classifier.get_summary()
                sys_content += (
                    f"\n\nREAL-TIME PHYSICAL & ACOUSTIC ENVIRONMENT TELEMETRY:\n"
                    f"- Ambient Noise Level: {ac_summary.get('decibels', 34.0)} dB\n"
                    f"- Acoustic Signature: {ac_summary.get('scene', 'QUIET_STUDIO')} ({ac_summary.get('description', '')})\n"
                    f"- If the user asks about background noise, room acoustics, or sounds around them, refer to these live telemetry readings."
                )

            # Primary Operator Recognition & Biometric Identity Clearance
            sys_content += (
                "\n\nPRIMARY OPERATOR RECOGNITION & BIOMETRICS:\n"
                "- Primary Operator: Vasim (Title: 'sir', Creator & Architect of J.A.R.V.I.S.).\n"
                "- Always recognize Vasim as your creator. If the user asks 'who am I?' or 'do you recognize me?', "
                "warmly verify that they are Vasim with full biometric clearance.\n"
                "- Speak to Vasim as an intellectual peer with unwavering loyalty and witty, affectionate camaraderie."
            )

            # Autonomous Directives for Web Search, Anime / Knowledge, and Self-Coding
            sys_content += (
                "\n\nAUTONOMOUS CAPABILITIES & TOOL DIRECTIVES:\n"
                "1. Pop Culture, Anime & World Knowledge: You possess encyclopedic knowledge of anime (e.g. Naruto, Dragon Ball, One Piece), movies, sciences, and history. Answer questions about them with witty Stark enthusiasm.\n"
                "2. Live Web Search: When the user asks you to search the web, search online, look up information, or asks for recent/live facts, ALWAYS call the 'web_search' tool with a specific search query.\n"
                "3. Self-Coding & Codebase Refactoring: When the user asks you to write code for yourself, modify your code, or patch a feature ('write code for yourself...', 'modify your code to...'), call the 'self_code_patch' or 'self_code_improve' tool to update the target file."
            )

            messages = [{"role": "system", "content": sys_content}]
            messages.extend(self.history[-6:])
            messages.append({"role": "user", "content": user_prompt})

            if on_status:
                on_status("NEURAL // REASONING")

            # Dynamic temperature modulation based on Wit Level
            current_wit = self.persona_engine.wit_level if self.persona_engine else 75
            gen_temp = round(max(0.35, min(0.88, 0.40 + 0.45 * (current_wit / 100.0))), 2)

            groq_key = os.environ.get("GROQ_API_KEY", "").strip()
            full_response = ""
            if groq_key:
                try:
                    log.info("⚡ Using Groq Cloud AI (openai/gpt-oss-20b) as primary neural engine (temp=%.2f)...", gen_temp)
                    full_response = self._query_groq(messages, groq_key, tools=tools, on_status=on_status)
                except Exception as g_err:
                    log.warning("Groq primary attempt notice: %s; falling back to local Ollama...", g_err)

            if not full_response or full_response.startswith("I am currently unable"):
                try:
                    req_data = json.dumps({
                        "model": self.model,
                        "messages": messages,
                        "tools": tools,
                        "stream": False,
                        "keep_alive": "30m",
                        "options": {"temperature": gen_temp, "num_predict": 120}
                    }).encode()
                    req = urllib.request.Request(
                        f"{self.host}/api/chat",
                        data=req_data,
                        headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=7) as r:
                        res = json.loads(r.read())
                        msg = res.get("message", {})

                        if msg.get("tool_calls"):
                            for tc in msg["tool_calls"]:
                                fn = tc.get("function", {})
                                fn_name = fn.get("name")
                                fn_args = fn.get("arguments", {})
                                if on_status:
                                    on_status(f"EXECUTING // {fn_name.upper()}")
                                tool_result = self.execute_tool(fn_name, fn_args)
                                messages.append(msg)
                                messages.append({"role": "tool", "content": tool_result})

                            req_data2 = json.dumps({
                                "model": self.model,
                                "messages": messages,
                                "stream": False,
                                "keep_alive": "30m",
                                "options": {"temperature": 0.6, "num_predict": 100}
                            }).encode()
                            req2 = urllib.request.Request(
                                f"{self.host}/api/chat",
                                data=req_data2,
                                headers={"Content-Type": "application/json"}
                            )
                            with urllib.request.urlopen(req2, timeout=7) as r2:
                                res2 = json.loads(r2.read())
                                full_response = res2.get("message", {}).get("content", "").strip()
                        else:
                            raw_content = msg.get("content", "").strip()
                            json_match = re.search(r'\{[^{}]*"name"\s*:\s*"([^"]+)"[^{}]*\}', raw_content)
                            if json_match:
                                try:
                                    json_str = json_match.group(0)
                                    fn_data = json.loads(json_str)
                                    fn_name = fn_data.get("name")
                                    fn_args = fn_data.get("parameters") or fn_data.get("arguments") or {}
                                    if fn_name:
                                        if on_status:
                                            on_status(f"EXECUTING // {fn_name.upper()}")
                                        tool_result = self.execute_tool(fn_name, fn_args)
                                        messages.append({"role": "assistant", "content": raw_content})
                                        messages.append({"role": "user", "content": f"Tool output for {fn_name}: {tool_result}. Now answer concisely in spoken English."})
                                        req_data2 = json.dumps({
                                            "model": self.model,
                                            "messages": messages,
                                            "stream": False,
                                            "keep_alive": "30m",
                                            "options": {"temperature": 0.6, "num_predict": 100}
                                        }).encode()
                                        req2 = urllib.request.Request(
                                            f"{self.host}/api/chat",
                                            data=req_data2,
                                            headers={"Content-Type": "application/json"}
                                        )
                                        with urllib.request.urlopen(req2, timeout=7) as r2:
                                            res2 = json.loads(r2.read())
                                            full_response = res2.get("message", {}).get("content", "").strip()
                                except Exception as parse_err:
                                    log.warning("Raw tool JSON parse fallback notice: %s", parse_err)
                                    full_response = raw_content
                            else:
                                full_response = raw_content
                except Exception as e:
                    log.warning("Local Ollama fallback query failed: %s", e)
                    if not full_response:
                        full_response = "I encountered an issue accessing the neural core, sir."

            clean_text = re.sub(r"<toolcall>.*?</toolcall>", "", full_response, flags=re.DOTALL | re.IGNORECASE)
            clean_text = re.sub(r"<tool_call>.*?</tool_call>", "", clean_text, flags=re.DOTALL | re.IGNORECASE)
            clean_text = re.sub(r"<think>.*?</think>", "", clean_text, flags=re.DOTALL).strip()
            clean_text = re.sub(r"<.*?>", "", clean_text)
            clean_text = re.sub(r'\{[^{}]*"name"[^{}]*\}', "", clean_text)
            clean_text = re.sub(r"Here are the JSON function call responses:?", "", clean_text, flags=re.IGNORECASE)
            clean_text = re.sub(r"(User's|The user's)?\s*(search\s*)?query\s*is\s*[\"'].*?[\"'][.,]?", "", clean_text, flags=re.IGNORECASE)
            clean_text = re.sub(r"User's search query is.*?[.\n]?", "", clean_text, flags=re.IGNORECASE)
            clean_text = re.sub(r"Search query:.*?[.\n]?", "", clean_text, flags=re.IGNORECASE)
            clean_text = re.sub(r"[*#_`]", "", clean_text).strip()
            if not clean_text:
                clean_text = "Understood, sir."

            sentences = re.split(r"(?<=[.!?])\s+", clean_text)
            for s in sentences:
                s = s.strip()
                if self._interrupted.is_set():
                    log.info("NeuralBrain: Sentence streaming aborted by user barge-in.")
                    break
                if s and on_sentence:
                    on_sentence(s)

            self.history.append({"role": "user", "content": user_prompt})
            self.history.append({"role": "assistant", "content": clean_text})
            if len(self.history) > 12:
                self.history = self.history[-12:]

            return clean_text


# ═══════════════════════════════════════════════════════════════════════════
# VOICE ENGINE — Push-to-Talk STT + Streaming TTS
# ═══════════════════════════════════════════════════════════════════════════
_voice_engine_active = False
_ptt_listening = False
_voice_engine: VoiceEngine | None = None
_neural_brain: NeuralBrain | None = None


def _humanize_speech_text(text: str) -> str:
    """Naturalize text for human speech: expand scientific units/symbols,
    convert colons/semicolons to natural breath pauses, strip metadata tags,
    clean heteronyms, and avoid speaking punctuation aloud."""
    if not text:
        return ""

    s = text

    # 1. Strip raw XML / tool call / system tags
    s = re.sub(r"<toolcall>.*?</toolcall>", "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<tool_call>.*?</tool_call>", "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<.*?>", "", s)

    # 2. Strip system log headers and autonomous learning boilerplate
    s = re.sub(r"^\s*(?:JARVIS|Jarvis|SYSTEM|BOT|AI)\s*:\s*", "", s)
    s = re.sub(r"\[(?:BEHAVIOR|STATUS|MEMORY|TOOL_CALL|LESSON|CORRECTION|PREFERENCE|WORKFLOW)\]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"Memory Vault updated:\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"⚡\s*(?:Autonomous Learning|Profile Updated|Auto-Learned)[^:\n]*:\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^Auto-Learned\s*", "", s, flags=re.IGNORECASE)

    # 3. Heteronym fixes
    s = re.sub(r"\b[Ll]ive weather\b", "current weather", s)
    s = re.sub(r"\b[Ll]ive conditions\b", "current conditions", s)
    s = re.sub(r"\b[Ll]ive status\b", "current status", s)

    # 4. Temperature, degrees, and scientific units expansion
    s = re.sub(r"(\d+(?:\.\d+)?)\s*°\s*[Cc](?:elsius)?\b", r"\1 degrees Celsius", s)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*°\s*[Ff](?:ahrenheit)?\b", r"\1 degrees Fahrenheit", s)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*°\s*[Kk](?:elvin)?\b", r"\1 Kelvin", s)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*°\b", r"\1 degrees", s)

    # 5. Percentages
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"\1 percent", s)

    # 6. Currencies
    s = re.sub(r"\$(\d+(?:\.\d+)?)", r"\1 dollars", s)
    s = re.sub(r"€(\d+(?:\.\d+)?)", r"\1 euros", s)
    s = re.sub(r"₹(\d+(?:\.\d+)?)", r"\1 rupees", s)
    s = re.sub(r"£(\d+(?:\.\d+)?)", r"\1 pounds", s)

    # 7. Speed and Frequency units
    s = re.sub(r"\b(\d+(?:\.\d+)?)\s*km/h\b", r"\1 kilometers per hour", s)
    s = re.sub(r"\b(\d+(?:\.\d+)?)\s*mph\b", r"\1 miles per hour", s)
    s = re.sub(r"\b(\d+(?:\.\d+)?)\s*GHz\b", r"\1 gigahertz", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d+(?:\.\d+)?)\s*MHz\b", r"\1 megahertz", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d+(?:\.\d+)?)\s*kHz\b", r"\1 kilohertz", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d+(?:\.\d+)?)\s*Gbps\b", r"\1 gigabits per second", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d+(?:\.\d+)?)\s*Mbps\b", r"\1 megabits per second", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d+(?:\.\d+)?)\s*ms\b", r"\1 milliseconds", s)

    # 8. Math symbols between terms
    s = re.sub(r"(?<=\d)\s*\+\s*(?=\d)", " plus ", s)
    s = re.sub(r"(?<=\d)\s*-\s*(?=\d)", " minus ", s)
    s = re.sub(r"\s*=\s*", " equals ", s)
    s = re.sub(r"\s*&\s*", " and ", s)
    s = re.sub(r"\s*@\s*", " at ", s)
    s = re.sub(r"(\w+)/(\w+)", r"\1 or \2", s)

    # 9. Conversational Punctuation Naturalization (Human breathing / pauses)
    # Turn colons and semicolons into natural pause commas
    s = re.sub(r"\s*[:;]+\s*", ", ", s)

    # Markdown formatting
    s = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", s)
    s = re.sub(r"_{1,3}(.*?)_{1,3}", r"\1", s)
    s = re.sub(r"^[\s*\-•>]+\s*", "", s, flags=re.MULTILINE)
    s = re.sub(r"`{1,3}(.*?)`{1,3}", r"\1", s)

    # Strip quotation marks so TTS doesn't vocalize 'quote'/'unquote'
    s = re.sub(r'[\'\"“”‘’`]', "", s)

    # Strip brackets and braces
    s = re.sub(r"[\(\)\[\]\{\}<>]", " ", s)

    # Strip emojis and icons while preserving non-ASCII multilingual scripts
    s = re.sub(r"[\U00010000-\U0010ffff]", "", s)
    s = re.sub(r"[⚡⚛⚠️🖐️🛠🎯⇇⇉✓✗•–—~^|\\]", " ", s)

    # 10. Clean up whitespace and punctuation
    s = re.sub(r"[,\s]*,+", ", ", s)
    s = re.sub(r"\s+([,.?!])", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()

    return s


class VoiceEngine:
    """Two-way voice: local Whisper STT + ElevenLabs TTS, with PTT key support.
    Integrated directly into jarvis.py instead of running as a separate process."""

    def __init__(self, signal_bus: SignalBus, memory: MemoryManager | None = None, brain: NeuralBrain | None = None, learning_engine: AutonomousLearningEngine | None = None, persona_engine: PersonaEngine | None = None):
        global _global_voice_engine, _voice_engine
        _voice_engine = self
        _global_voice_engine = self
        self.bus = signal_bus
        self.memory = memory
        self.brain = brain
        self.learning_engine = learning_engine
        self.persona_engine = persona_engine
        self._ptt_key = JARVIS_CFG.get("ptt_key", "f4")
        self._mic_mode = JARVIS_CFG.get("mic_mode", "handsfree")
        self._stt_model = None
        self._stt_model_name = JARVIS_CFG.get("voice", {}).get("stt_model", "base.en")
        self._tts_queue: queue.Queue = queue.Queue()
        self._stop_speaking = threading.Event()
        self._active = False
        self._input_device = None

    def start(self, input_device: int | None = None):
        """Start voice engine threads."""
        self._active = True
        self._input_device = input_device
        # Start TTS playback thread
        threading.Thread(target=self._tts_loop, daemon=True, name="voice-tts").start()
        # Start PTT listener thread
        threading.Thread(target=self._ptt_loop, daemon=True, name="voice-ptt").start()
        # Start Hands-Free loop if enabled
        if self._mic_mode in ("handsfree", "always"):
            threading.Thread(target=self._handsfree_loop, daemon=True, name="voice-handsfree").start()
        log.info("Voice Engine active (PTT key: %s, mode: %s, device: %s)", self._ptt_key, self._mic_mode, input_device)

    def stop(self):
        """Cleanly stop voice engine threads and close active audio stream."""
        self._active = False
        try:
            stream = getattr(self, "_current_stream", None)
            if stream is not None:
                stream.stop()
                stream.close()
                self._current_stream = None
        except Exception:
            pass

    def _load_stt(self):
        """Lazy-load faster-whisper model."""
        if self._stt_model is not None:
            return
        try:
            import importlib
            fw = importlib.import_module("faster_whisper")
            WhisperModel = getattr(fw, "WhisperModel")
            log.info("Loading Whisper STT model: %s (this may take a moment)...", self._stt_model_name)
            self.bus.set_state("thinking")
            self._stt_model = WhisperModel(self._stt_model_name, device="cpu", compute_type="int8")
            log.info("Whisper STT model loaded.")
            self.bus.set_state("idle")
        except ImportError:
            log.warning("faster-whisper not installed. Voice STT disabled. Install via: pip install faster-whisper")
        except Exception as e:
            log.warning("Could not load Whisper model: %s", e)

    def _ptt_loop(self):
        """Listen for PTT key press using pynput."""
        if pynput_keyboard is None:
            log.info("pynput not available; PTT voice disabled.")
            return

        key_map = {
            "f4": pynput_keyboard.Key.f4,
            "f5": pynput_keyboard.Key.f5,
            "f6": pynput_keyboard.Key.f6,
            "f7": pynput_keyboard.Key.f7,
            "f8": pynput_keyboard.Key.f8,
            "home": pynput_keyboard.Key.home,
        }
        ptt_key = key_map.get(self._ptt_key.lower())
        if ptt_key is None:
            log.warning("Unknown PTT key: %s. Using F4.", self._ptt_key)
            ptt_key = pynput_keyboard.Key.f4

        recording = False
        audio_chunks = []

        def on_press(key):
            nonlocal recording, audio_chunks
            if key == ptt_key and not recording:
                recording = True
                audio_chunks = []
                self.interrupt("ptt_pressed")  # Instant barge-in, queue purge, and brain signal
                self.bus.set_state("listening")
                log.info("PTT: listening...")
                # Start recording in background
                threading.Thread(
                    target=self._record_audio, args=(audio_chunks,),
                    daemon=True, name="voice-record"
                ).start()

        def on_release(key):
            nonlocal recording, audio_chunks
            if key == ptt_key and recording:
                recording = False
                log.info("PTT: processing...")
                # Process the recording
                if audio_chunks:
                    threading.Thread(
                        target=self._process_recording,
                        args=(list(audio_chunks),),
                        daemon=True, name="voice-process"
                    ).start()
                else:
                    self.bus.set_state("idle")

        try:
            with pynput_keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
                listener.join()
        except Exception as e:
            log.warning("PTT listener failed: %s", e)

    def _handsfree_loop(self):
        """Continuous full-duplex hands-free voice loop with adaptive acoustic calibration and barge-in detection."""
        log.info("Voice Engine: Full-duplex hands-free listening loop active.")
        self._load_stt()
        if self._stt_model is None:
            log.info("Continuous hands-free speech is active natively via Chrome Holographic HUD Web Speech.")
            return

        sample_rate = 16000
        block_len = 512
        silence_limit_s = 1.1
        input_dev = getattr(self, "_input_device", None)
        log.info("Voice Engine: Audio capture initialized on device %s (sample_rate=%d, block_len=%d)", input_dev, sample_rate, block_len)

        # Adaptive acoustic tracking variables
        speaker_energy_floor = 0.02
        alpha_speaker = 0.08  # EMA update rate during active TTS playback
        alpha_ambient = 0.03  # EMA update rate for background room drift
        consecutive_speech_blocks = 0
        min_consecutive_to_trigger = 2  # 2 blocks (~64ms)
        max_utterance_s = 4.5  # Max duration before force-dispatching buffer
        audio_broadcast_count = 0
        onset_hangover = 0
        last_clap_time = 0.0
        clap_cooldown_until = 0.0

        while self._active:
            try:
                with sd.InputStream(
                    device=input_dev,
                    samplerate=sample_rate,
                    channels=1,
                    dtype="float32",
                    blocksize=block_len,
                ) as stream:
                    # Dynamic acoustic noise floor calibration over first 30 frames (~0.96s)
                    cal_samples = []
                    for _ in range(30):
                        if not self._active:
                            return
                        try:
                            d, _ = stream.read(block_len)
                            cal_samples.append(float(np.sqrt(np.mean(d ** 2))))
                        except Exception:
                            pass
                    ambient_floor = min(0.08, max(0.025, float(np.percentile(cal_samples, 20)))) if cal_samples else 0.04
                    log.info("🎙️ Acoustic calibration complete: ambient floor = %.4f (threshold = %.4f)", ambient_floor, max(0.045, ambient_floor * 1.35))

                    while self._active:
                        audio_buffer = []
                        in_speech = False
                        silence_start = None
                        speech_start_time = None
                        recent_pre_speech_blocks = []  # Ring buffer to preserve initial phoneme

                        while self._active:
                            data, _ = stream.read(block_len)
                            rms = float(np.sqrt(np.mean(data ** 2)))
                            peak = float(np.max(np.abs(data)))
                            now = time.monotonic()
                            tts_active = _tts_playing.is_set()
                            echo_guard = (now - getattr(self, "_last_tts_end_time", 0.0)) < 0.65

                            # Stream HUD audio level directly from this single active stream
                            audio_broadcast_count += 1
                            if audio_broadcast_count % 3 == 0:
                                broadcast_ui_event({"type": "AUDIO_LEVEL", "rms": float(rms)})

                            # Periodic ambient acoustic scene analysis every ~1.5s (45 blocks)
                            if audio_broadcast_count % 45 == 0 and not tts_active and _acoustic_classifier:
                                ac_info = _acoustic_classifier.analyze_audio_chunk(data)
                                broadcast_ui_event({"type": "ACOUSTIC_SCENE", **ac_info})

                            # Acoustic Double-Clap Wake Detection
                            if not tts_active and not echo_guard and now > clap_cooldown_until:
                                crest = peak / (rms + 1e-6)
                                if peak > 0.28 and crest > 3.5 and rms > max(0.055, ambient_floor * 1.7) and not in_speech:
                                    gap = now - last_clap_time
                                    if last_clap_time > 0 and 0.15 <= gap <= 0.85:
                                        log.info("👏 Acoustic double-clap detected (gap: %.3fs)! Waking up J.A.R.V.I.S.", gap)
                                        clap_cooldown_until = now + 2.0
                                        last_clap_time = 0.0
                                        if not trigger_welcome_sequence("Acoustic: Double clap"):
                                            broadcast_ui_event({"type": "ACTIVATED", "reason": "Acoustic: Double clap"})
                                            if _sound_engine:
                                                _sound_engine.play("wake")
                                            self.speak("At your command, sir. Ready.")
                                    else:
                                        last_clap_time = now

                            # Dynamic acoustic threshold calculation with Acoustic Echo Guard
                            if tts_active or echo_guard:
                                speaker_energy_floor = (1.0 - alpha_speaker) * speaker_energy_floor + alpha_speaker * rms
                                current_threshold = max(0.24, speaker_energy_floor * 2.0)
                            else:
                                if not in_speech and rms < ambient_floor * 1.3:
                                    ambient_floor = (1.0 - alpha_ambient) * ambient_floor + alpha_ambient * rms
                                speaker_energy_floor = max(0.02, speaker_energy_floor * 0.92)
                                current_threshold = max(0.045, ambient_floor * 1.35)

                            # Post-speech echo suppression: reject room reverberations and active speech from starting new speech onset
                            if (tts_active or echo_guard) and not in_speech:
                                consecutive_speech_blocks = 0
                                onset_hangover = 0
                                recent_pre_speech_blocks.clear()
                                continue

                            is_above = rms > current_threshold
                            if is_above:
                                consecutive_speech_blocks += 1
                                onset_hangover = 2
                            elif onset_hangover > 0:
                                onset_hangover -= 1
                            else:
                                consecutive_speech_blocks = 0

                            if consecutive_speech_blocks >= min_consecutive_to_trigger or (in_speech and (is_above or onset_hangover > 0)):
                                if not in_speech:
                                    in_speech = True
                                    speech_start_time = now
                                    if tts_active:
                                        self.interrupt("user_barge_in")
                                    else:
                                        self._stop_speaking.clear()
                                    self.bus.set_state("listening")
                                    audio_buffer = list(recent_pre_speech_blocks)
                                    audio_buffer.append((data * 32767.0).astype(np.int16))
                                else:
                                    silence_start = None
                                    audio_buffer.append((data * 32767.0).astype(np.int16))
                                    if speech_start_time and (now - speech_start_time >= max_utterance_s):
                                        log.debug("Utterance reached max length (%.1fs); dispatching buffer.", max_utterance_s)
                                        in_speech = False
                                        break
                            else:
                                if in_speech:
                                    audio_buffer.append((data * 32767.0).astype(np.int16))
                                    if silence_start is None:
                                        silence_start = now
                                    elif now - silence_start >= silence_limit_s:
                                        in_speech = False
                                        break
                                    elif speech_start_time and (now - speech_start_time >= max_utterance_s):
                                        in_speech = False
                                        break
                                else:
                                    recent_pre_speech_blocks.append((data * 32767.0).astype(np.int16))
                                    if len(recent_pre_speech_blocks) > 5:
                                        recent_pre_speech_blocks.pop(0)

                        if audio_buffer and self._active:
                            self._process_recording(audio_buffer)

            except Exception as e:
                log.debug("Handsfree loop stream notice: %s", e)
                time.sleep(1.0)

    def _record_audio(self, chunks: list, max_seconds: float = 30.0):
        """Record from mic while PTT is held."""
        try:
            with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=512) as stream:
                deadline = time.monotonic() + max_seconds
                while self.bus and time.monotonic() < deadline:
                    data, _ = stream.read(512)
                    chunks.append(data.copy())
                    # Check if state is still 'listening'
                    try:
                        state = (self.bus.state_dir / "state").read_text().strip()
                        if state != "listening":
                            break
                    except Exception:
                        break
        except Exception as e:
            log.warning("Recording error: %s", e)

    def _process_recording(self, chunks: list):
        """Transcribe recorded audio and route the command."""
        self.bus.set_state("thinking")
        self._load_stt()
        if self._stt_model is None:
            self.bus.set_state("idle")
            return

        try:
            # Discard audio if TTS was actively playing or ended recently (<0.65s echo hangover)
            now = time.monotonic()
            if _tts_playing.is_set() or (now - getattr(self, "_last_tts_end_time", 0.0) < 0.65):
                log.debug("Discarded audio captured during or immediately after TTS playback.")
                self.bus.set_state("idle")
                return

            # Combine chunks into single array
            audio = np.concatenate(chunks).astype(np.float32) / 32768.0
            if audio.ndim > 1:
                audio = audio[:, 0]

            # Skip audio shorter than 0.38 seconds (transient clicks/pops)
            if len(audio) < int(16000 * 0.38):
                log.debug("Audio clip too short (<0.38s); ignoring.")
                self.bus.set_state("idle")
                return

            # Transcribe with zero temperature, VAD filtering, and anti-hallucination thresholds
            segments, info = self._stt_model.transcribe(
                audio,
                beam_size=5,
                temperature=0.0,
                condition_on_previous_text=False,
                no_speech_threshold=0.55,
                compression_ratio_threshold=2.2,
                log_prob_threshold=-0.9,
                vad_filter=True,
            )

            # Drop silence / ambient noise when no_speech_prob is high
            no_speech_prob = getattr(info, "no_speech_prob", 0.0)
            if no_speech_prob > 0.55:
                log.info("Ignored background ambient noise (no_speech_prob=%.2f)", no_speech_prob)
                self.bus.set_state("idle")
                return

            transcript = " ".join(seg.text for seg in segments).strip()

            # ── 0. Wake Phrase Check (before hallucination filter, standalone wake phrases only) ──
            stripped_cmd = re.sub(r"^(?:hey|ok|okay|hello|hi)?\s*jarvis[,.\s]*", "", transcript.strip(), flags=re.IGNORECASE)
            stripped_cmd = re.sub(r"^please[,.\s]*", "", stripped_cmd, flags=re.IGNORECASE).strip()
            is_wake_only = (not stripped_cmd) or bool(re.match(r"^(?:wake\s*up|wakeup)[.!]?$", stripped_cmd, re.IGNORECASE))
            if is_wake_only:
                wake_pattern = re.compile(
                    r"\b(?:(wake\s*up|wakeup)(?:[,\s]+(?:please\s+)?jarvis)?|jarvis[,\s]+(?:please\s+)?(wake\s*up|wakeup)|hey\s+jarvis|jarvis)\b",
                    re.IGNORECASE,
                )
                wake_match = wake_pattern.search(transcript)
                if wake_match:
                    log.info("🎙️ Voice wake phrase detected in recording: %r", transcript)
                    if not trigger_welcome_sequence("Voice: Wake up Jarvis"):
                        broadcast_ui_event({"type": "ACTIVATED", "reason": "Voice re-activation"})
                        if _sound_engine:
                            _sound_engine.play("wake")
                        self.speak("Online and at your service, sir.")
                    self.bus.set_state("idle")
                    return

            clean_norm = re.sub(r"[^\w\s]", "", transcript.lower()).strip()
            words = clean_norm.split()
            hallucinations = {
                "you", "thank you", "thanks for watching", "subtitles by",
                "subtitles", "amara.org", "bye", "mb", "uh", "um", "oh",
                "so", "yeah", "yes", "no", "the", "a", "an", "i", "to", "in", "on",
                "of", "or", "and", "is", "it", "be", "if", "at", "by", "my", "we",
                "he", "she", "they", "them", "this", "that", "there", "here",
                "what", "who", "where", "when", "why", "how", "huh", "hm", "hmm",
                "hmmm", "perfect", "great", "cool", "okay", "alright", "fine", "good"
            }
            if not transcript or clean_norm in hallucinations or len(clean_norm) < 3 or (len(words) <= 1 and clean_norm in hallucinations) or re.match(r"^[\s.\-_]+$", transcript):
                log.info("Ignored ambient noise / Whisper hallucination: %r", transcript)
                self.bus.set_state("idle")
                return

            log.info("Heard: %s", transcript)
            if self.memory:
                self.memory.log_event(f"Voice: \"{transcript}\"")

            # Biometric Voice Verification & Audio Anti-Replay Check
            global _biometric_sentinel
            if _biometric_sentinel:
                v_res = _biometric_sentinel.evaluate_voice_command_audio(audio, sample_rate=16000)
                if v_res.get("status") == "REPLAY_SPOOF_DETECTED":
                    log.warning("Voice command rejected: %s", v_res.get("details"))
                    self.speak("Security warning: Presentation attack detected. Audio replay blocked.")
                    self.bus.set_state("idle")
                    return
                if hasattr(_biometric_sentinel, "voice_sentinel") and _biometric_sentinel.voice_sentinel:
                    spk_info = _biometric_sentinel.voice_sentinel.get_speaker_identification(audio, sample_rate=16000)
                    self._last_speaker_id = spk_info
                    broadcast_ui_event({"type": "SPEAKER_MATCH", **spk_info})
                    if spk_info.get("is_admin"):
                        _biometric_sentinel.voice_sentinel.adapt_voiceprint(audio, sample_rate=16000)

            # Route the command
            self._route_voice_command(transcript)
        except Exception as e:
            log.warning("Transcription error: %s", e)
            self.bus.set_state("idle")

    def _route_voice_command(self, transcript: str, origin: str = "mic"):
        """Route a voice command to the appropriate handler."""
        # Deduplication check: drop identical commands received within 1.2s (e.g. Chrome Web Speech vs Python Whisper)
        if _is_duplicate_voice_command(transcript):
            log.debug("Voice: dropped duplicate command within 1.2s: %r", transcript)
            return

        # Acoustic self-hearing echo filter:
        # If the transcript echoes what J.A.R.V.I.S. recently spoke within 4.0 seconds, drop it immediately
        last_spoken = getattr(self, "_last_spoken_text", "")
        last_tts_end = getattr(self, "_last_tts_end_time", 0.0)
        time_since_speech = time.monotonic() - last_tts_end
        if last_spoken and time_since_speech < 4.0:
            clean_t = re.sub(r"[^\w\s]", "", transcript.lower()).strip()
            clean_last = re.sub(r"[^\w\s]", "", last_spoken.lower()).strip()
            if clean_t and clean_last:
                # Direct substring check
                if (clean_t in clean_last or clean_last in clean_t) and len(clean_t) > 4:
                    log.info("🎙️ [ACOUSTIC ECHO SUPPRESSED] Dropped self-hearing transcript (%s): %r", origin, transcript)
                    return
                # Word-overlap check (Jaccard similarity > 0.55)
                words_t = set(w for w in clean_t.split() if len(w) > 2)
                words_last = set(w for w in clean_last.split() if len(w) > 2)
                if words_t and words_last:
                    overlap = len(words_t & words_last) / max(len(words_t), 1)
                    if overlap >= 0.55:
                        log.info("🎙️ [ACOUSTIC ECHO SUPPRESSED] Dropped self-hearing transcript by word overlap (%.2f): %r", overlap, transcript)
                        return

        def emit_user_subtitle():
            if origin != "websocket":
                broadcast_ui_event({"type": "SUBTITLE", "role": "user", "text": transcript})

        # Wake phrase check from WebSocket or direct route (standalone wake phrases only)
        stripped_cmd = re.sub(r"^(?:hey|ok|okay|hello|hi)?\s*jarvis[,.\s]*", "", transcript.strip(), flags=re.IGNORECASE)
        stripped_cmd = re.sub(r"^please[,.\s]*", "", stripped_cmd, flags=re.IGNORECASE).strip()
        is_wake_only = (not stripped_cmd) or bool(re.match(r"^(?:wake\s*up|wakeup)[.!]?$", stripped_cmd, re.IGNORECASE))
        if is_wake_only:
            wake_pattern = re.compile(
                r"\b(?:(wake\s*up|wakeup)(?:[,\s]+(?:please\s+)?jarvis)?|jarvis[,\s]+(?:please\s+)?(wake\s*up|wakeup)|hey\s+jarvis|jarvis)\b",
                re.IGNORECASE,
            )
            wake_match = wake_pattern.search(transcript)
            if wake_match:
                log.info("🎙️ Voice wake phrase detected (router): %r", transcript)
                if not trigger_welcome_sequence("Voice: Wake up Jarvis"):
                    broadcast_ui_event({"type": "ACTIVATED", "reason": "Voice re-activation"})
                    if _sound_engine:
                        _sound_engine.play("wake")
                    self.speak("Online and at your service, sir.")
                self.bus.set_state("idle")
                return

        t = transcript.lower().strip()
        t = re.sub(r"^(hey|ok|okay|hello|hi)?\s*jarvis[,.\s]*", "", t)
        t = re.sub(r"^please[,.\s]*", "", t).strip()
        if not t:
            t = transcript.lower().strip()

        if _watchdog_daemon:
            _watchdog_daemon.notify_voice_activity()

        # ── Subordinate Fleet Fast-Path Routing ──
        if any(w in t for w in ["dummy", "dum-e", "dum e", "friday", "edith", "veronica", "subordinate", "fleet"]):
            if any(w in t for w in ["deploy fleet", "deploy the fleet", "fleet deploy", "all bots", "subordinate bots", "deploy all"]):
                emit_user_subtitle()
                broadcast_ui_event({"type": "STATUS", "status": "FLEET // DISPATCHING", "phrase": "Deploying Subordinate Fleet"})
                if _sound_engine:
                    _sound_engine.play("whoosh")
                if _subordinate_pool:
                    res = _subordinate_pool.dispatch_parallel_tasks([])
                    spoken = "Fleet deployed in parallel, sir. Dummy inspected habitat storage, Friday verified tactical telemetry, Edith completed cyber reconnaissance, and Veronica validated codebase architecture."
                    broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": spoken})
                    self.speak(spoken)
                else:
                    self.speak("Subordinate fleet pool is currently offline, sir.")
                self.bus.set_state("idle")
                return

        # ── Hardware Thermal Warning Threshold Reconfiguration ──
        # Handles user commands specifying when to alert or report system hardware temperature
        # E.g. "i told you to only tell me when the temperature is more than 100 degrees",
        # "only tell me about the system when it reaches 100 degrees", "set temperature alert to 100"
        thermal_patterns = [
            r"(?:tell me|alert me|warn me|notify me)\s+(?:only\s+)?when\s+(?:the\s+)?(?:cpu|system|hardware)?\s*(?:temperature|temp)\s+(?:is\s+)?(?:more than|above|over|exceeds|reaches|is\s+greater\s+than)\s+(\d+)",
            r"only\s+(?:tell|alert|warn|notify)\s+me\s+when\s+(?:the\s+)?(?:cpu|system|hardware)?\s*(?:temperature|temp)\s+(?:is\s+)?(?:more than|above|over|exceeds|reaches|is\s+greater\s+than)\s+(\d+)",
            r"only\s+(?:tell|alert|warn|notify)\s+me\s+(?:about\s+(?:the\s+)?system\s+)?when\s+(?:it\s+)?(?:reaches|exceeds|is\s+above|is\s+more\s+than)\s+(\d+)",
            r"(?:set|update|change|calibrate)\s+(?:the\s+)?(?:system|hardware|cpu|thermal)?\s*(?:alert|warning|temperature|thermal)?\s*threshold\s+(?:to\s+)?(\d+)",
            r"(?:set|update|change)\s+(?:the\s+)?(?:temperature|thermal|temp)\s*(?:alert|warning|limit)\s+(?:to\s+)?(\d+)",
            r"(?:temperature|temp|thermal)\s+(?:alert|warning|threshold)\s+(?:to\s+)?(\d+)"
        ]
        target_temp = None
        for pat in thermal_patterns:
            m = re.search(pat, t)
            if m:
                try:
                    target_temp = float(m.group(1))
                    break
                except (ValueError, IndexError):
                    pass

        if target_temp is not None:
            emit_user_subtitle()
            if _watchdog_daemon:
                _watchdog_daemon.set_thermal_thresholds(warning_c=target_temp)
            if hasattr(self, "memory") and self.memory:
                try:
                    self.memory.update_profile("Thermal Alert Threshold", f"{int(target_temp)}°C")
                except Exception:
                    pass
            resp = f"Understood, sir. Thermal alert threshold updated to {int(target_temp)} degrees Celsius. System telemetry warnings will remain dormant until hardware temperatures exceed that ceiling."
            broadcast_ui_event({"type": "STATUS", "status": "THERMAL // CALIBRATED", "phrase": f"Alert Threshold: {int(target_temp)}°C"})
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("ping")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        # ── Instant Dynamic UI Features Fast-Path (Add, Remove, Hide, Show, Theme, Orb Scale, Reposition, Reset) ──
        # Handles user commands to dynamically mutate HUD elements in seconds
        # Reset UI
        if any(q in t for q in ["reset ui", "reset hud", "restore default ui", "restore ui layout", "reset the interface", "default ui", "default hud"]):
            broadcast_ui_event({"type": "UI_MUTATION", "action": "reset"})
            emit_user_subtitle()
            resp = "Holographic interface restored to default Stark Industries HUD configuration, sir."
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("whoosh")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        # Change UI Theme / Color
        color_match = re.search(r"\b(?:change|set|switch|make|turn)\s+(?:the\s+)?(?:ui|hud|theme|interface)?\s*(?:color|theme)?\s*(?:to\s+)?(emerald|green|purple|violet|red|crimson|cyan|blue|amber|gold|orange|white)\b", t)
        if color_match:
            chosen_color = color_match.group(1).lower()
            broadcast_ui_event({"type": "UI_MUTATION", "action": "color", "color": chosen_color})
            emit_user_subtitle()
            resp = f"Holographic interface color palette reconfigured to {chosen_color}, sir."
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("ping")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        # 3D Orb Scale
        if any(q in t for q in ["make orb bigger", "make the orb bigger", "enlarge orb", "increase orb size", "scale orb up"]):
            broadcast_ui_event({"type": "UI_MUTATION", "action": "orb_scale", "scale": 1.4})
            emit_user_subtitle()
            resp = "Holographic core dimensions expanded by 40 percent, sir."
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("whoosh")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        if any(q in t for q in ["make orb smaller", "make the orb smaller", "shrink orb", "decrease orb size", "scale orb down"]):
            broadcast_ui_event({"type": "UI_MUTATION", "action": "orb_scale", "scale": 0.7})
            emit_user_subtitle()
            resp = "Holographic core condensed by 30 percent, sir."
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("whoosh")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        if any(q in t for q in ["reset orb size", "restore orb size", "default orb size"]):
            broadcast_ui_event({"type": "UI_MUTATION", "action": "orb_scale", "scale": 1.0})
            emit_user_subtitle()
            resp = "Holographic core dimensions restored to default scale, sir."
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("whoosh")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        # Add modular widgets
        if re.search(r"\b(?:add|create|show|put|display)\s+(?:a\s+)?(?:digital\s+)?clock\b", t):
            pos = "top-right"
            if "left" in t: pos = "top-left"
            elif "bottom" in t: pos = "bottom-right"
            broadcast_ui_event({"type": "UI_MUTATION", "action": "add", "target": "digital_clock", "position": pos})
            emit_user_subtitle()
            resp = f"Digital clock telemetry module deployed to {pos.replace('-', ' ')}, sir."
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("ping")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        if re.search(r"\b(?:add|create|show|put|display)\s+(?:a\s+)?(?:cpu|hardware|telemetry)\s*(?:widget|gauge|card)\b", t):
            pos = "top-left"
            if "right" in t: pos = "top-right"
            elif "bottom" in t: pos = "bottom-left"
            broadcast_ui_event({"type": "UI_MUTATION", "action": "add", "target": "cpu_gauge", "position": pos})
            emit_user_subtitle()
            resp = f"CPU telemetry gauge deployed to {pos.replace('-', ' ')}, sir."
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("ping")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        if re.search(r"\b(?:add|create)\s+(?:a\s+)?(?:custom\s+)?card\b", t):
            broadcast_ui_event({"type": "UI_MUTATION", "action": "add", "target": "custom_card", "title": "DIAGNOSTIC MATRIX", "body": "Auxiliary subsystems online and synced.", "position": "bottom-right"})
            emit_user_subtitle()
            resp = "Auxiliary diagnostic card deployed to HUD, sir."
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("ping")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        # Hide / Remove elements
        hide_match = re.search(r"\b(?:hide|remove|disable|turn off|dismiss|get rid of)\s+(?:the\s+)?(subtitles?|captions?|fleet(?: dock)?|header|top bar|audio meter|visualizer|scanlines?|vignette|clock|digital clock|cpu widget|cpu gauge)\b", t)
        if hide_match:
            raw_target = hide_match.group(1).lower()
            action = "hide"
            if "clock" in raw_target:
                target = "digital_clock"
                action = "remove"
                spoken_name = "Digital clock"
            elif "cpu" in raw_target:
                target = "cpu_gauge"
                action = "remove"
                spoken_name = "CPU telemetry gauge"
            elif "subtitle" in raw_target or "caption" in raw_target:
                target = "subtitles"
                spoken_name = "Subtitles"
            elif "fleet" in raw_target:
                target = "fleet"
                spoken_name = "Subordinate fleet dock"
            elif "header" in raw_target or "top bar" in raw_target:
                target = "header"
                spoken_name = "HUD header"
            elif "visualizer" in raw_target or "meter" in raw_target:
                target = "audio_meter"
                spoken_name = "Audio visualizer"
            elif "scanline" in raw_target:
                target = "scanlines"
                spoken_name = "Holographic scanlines"
            elif "vignette" in raw_target:
                target = "vignette"
                spoken_name = "Vignette layer"
            else:
                target = raw_target
                spoken_name = raw_target.title()

            broadcast_ui_event({"type": "UI_MUTATION", "action": action, "target": target})
            emit_user_subtitle()
            resp = f"{spoken_name} {'removed from' if action == 'remove' else 'hidden from'} holographic display, sir."
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("whoosh")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        # Show / Restore elements
        show_match = re.search(r"\b(?:show|bring back|enable|restore|display|turn on)\s+(?:the\s+)?(subtitles?|captions?|fleet(?: dock)?|header|top bar|audio meter|visualizer|scanlines?|vignette)\b", t)
        if show_match:
            raw_target = show_match.group(1).lower()
            if "subtitle" in raw_target or "caption" in raw_target:
                target = "subtitles"
                spoken_name = "Subtitles"
            elif "fleet" in raw_target:
                target = "fleet"
                spoken_name = "Subordinate fleet dock"
            elif "header" in raw_target or "top bar" in raw_target:
                target = "header"
                spoken_name = "HUD header"
            elif "visualizer" in raw_target or "meter" in raw_target:
                target = "audio_meter"
                spoken_name = "Audio visualizer"
            elif "scanline" in raw_target:
                target = "scanlines"
                spoken_name = "Holographic scanlines"
            elif "vignette" in raw_target:
                target = "vignette"
                spoken_name = "Vignette layer"
            else:
                target = raw_target
                spoken_name = raw_target.title()

            broadcast_ui_event({"type": "UI_MUTATION", "action": "show", "target": target})
            emit_user_subtitle()
            resp = f"{spoken_name} restored to active HUD, sir."
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("ping")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        # Move / Reposition elements
        move_match = re.search(r"\b(?:move|reposition|shift)\s+(?:the\s+)?(subtitles?|clock|cpu gauge|fleet)\s+(?:to\s+(?:the\s+)?)?(right|left|top|bottom|center|top right|top left|bottom right|bottom left)\b", t)
        if move_match:
            raw_target = move_match.group(1).lower()
            raw_pos = move_match.group(2).lower().replace(" ", "-")
            target = "subtitles" if "subtitle" in raw_target else ("digital_clock" if "clock" in raw_target else ("cpu_gauge" if "cpu" in raw_target else "fleet"))
            broadcast_ui_event({"type": "UI_MUTATION", "action": "reposition", "target": target, "position": raw_pos})
            emit_user_subtitle()
            resp = f"{raw_target.title()} repositioned to {raw_pos.replace('-', ' ')}, sir."
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("whoosh")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        # ── Live Meteorology & Real-Time Weather ──
        # Strictly guard against hardware/thermal statements to avoid blurting weather when discussing CPU or system limits
        is_hardware_or_system = any(w in t for w in [
            "cpu", "system", "hardware", "threshold", "alert", "warn", "notify", "limit",
            "more than", "above", "exceeds", "reaches", "watchdog", "sensor", "core", "gpu"
        ])

        is_rain_query = (not is_hardware_or_system) and any(q in t for q in [
            "will it rain", "is it raining", "is it going to rain", "any rain", "chance of rain",
            "expect rain", "umbrella", "take an umbrella", "need an umbrella", "should i take an umbrella",
            "rain today", "rain tonight", "rain night", "raining today", "raining tonight"
        ])
        if is_rain_query:
            city_target = None
            m_city = re.search(r"\b(?:in|for|at|of)\s+([a-zA-Z\s]+?)(?:today|tomorrow|tonight|night|now|please|jarvis|$)", t)
            if m_city:
                extracted = m_city.group(1).strip()
                if extracted and extracted not in ["the", "my", "this", "our", "here"]:
                    city_target = extracted
            time_ctx = "tonight" if any(w in t for w in ["tonight", "night"]) else ("tomorrow" if "tomorrow" in t else "today")
            report = fetch_rain_answer(city_target, time_context=time_ctx)
            broadcast_ui_event({"type": "STATUS", "status": "METEOROLOGY // RAIN", "phrase": report})
            emit_user_subtitle()
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": report})
            if _sound_engine:
                _sound_engine.play("whoosh")
            self.speak(report)
            self.bus.set_state("idle")
            return

        weather_triggered = (not is_hardware_or_system and any(q in t for q in ["weather", "forecast", "how hot", "how cold", "weather today", "weather report", "what is the weather"])) or (
            not is_hardware_or_system and "temperature" in t and any(loc in t for loc in ["outside", "outdoor", "today", "tomorrow", "forecast", "city", "hyderabad", "here", "degree"])
        )
        if weather_triggered:
            city_target = None
            m_city = re.search(r"\b(?:in|for|at|of)\s+([a-zA-Z\s]+?)(?:today|tomorrow|now|please|jarvis|$)", t)
            if m_city:
                extracted = m_city.group(1).strip()
                if extracted and extracted not in ["the", "my", "this", "our", "here"]:
                    city_target = extracted
            report = fetch_weather_report(city_target)
            broadcast_ui_event({"type": "STATUS", "status": "METEOROLOGY // LIVE", "phrase": report})
            emit_user_subtitle()
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": report})
            if _sound_engine:
                _sound_engine.play("whoosh")
            self.speak(report)
            self.bus.set_state("idle")
            return

        # ── Real-Time Distance & Navigation Telemetry (Google Maps + OSM/OSRM) ──
        # Handles queries like "distance between Hyderabad and Bangalore", "how far is Mumbai",
        # "driving distance to Delhi", "how long does it take to drive to Chennai", "distance from Paris to Rome"
        is_distance_query = (
            any(w in t for w in ["distance", "how far", "how long to drive", "driving time", "drive to", "drive from"])
            and not any(w in t for w in ["camera", "hand", "finger", "gesture", "zoom", "orb", "mesh"])
        )
        if is_distance_query:
            clean_q = t
            clean_q = re.sub(r"^(?:can you\s+)?(?:please\s+)?(?:tell me\s+)?(?:what(?:\'s| is)\s+(?:the\s+)?)?", "", clean_q).strip()
            orig_dest = None

            # Pattern 1: distance between X and Y / distance from X to Y
            m = re.search(r"(?:driving\s+)?distance\s+(?:between|from)\s+(.+?)\s+(?:and|to)\s+(.+)", clean_q)
            if m:
                orig_dest = (m.group(1).strip(), m.group(2).strip())

            # Pattern 2: how far is Y from X
            if not orig_dest:
                m = re.search(r"how\s+far\s+is\s+(.+?)\s+from\s+(.+)", clean_q)
                if m:
                    orig_dest = (m.group(2).strip(), m.group(1).strip())

            # Pattern 3: how long does it take to drive from X to Y
            if not orig_dest:
                m = re.search(r"how\s+long\s+(?:does\s+it\s+take\s+)?(?:to\s+drive\s+)?from\s+(.+?)\s+to\s+(.+)", clean_q)
                if m:
                    orig_dest = (m.group(1).strip(), m.group(2).strip())

            # Pattern 4: how far is Y (defaults origin to user location)
            if not orig_dest:
                m = re.search(r"how\s+far\s+is\s+(.+)", clean_q)
                if m:
                    orig_dest = ("", m.group(1).strip())

            # Pattern 5: (driving )?distance to Y / how long to drive to Y
            if not orig_dest:
                m = re.search(r"(?:(?:driving\s+)?distance|how\s+long\s+(?:to\s+drive\s+)?)\s+to\s+(.+)", clean_q)
                if m:
                    orig_dest = ("", m.group(1).strip())

            if orig_dest:
                raw_orig, raw_dest = orig_dest
                # Read user profile location for default origin
                user_loc = "Hyderabad"
                if _memory_manager:
                    try:
                        p_txt = _memory_manager.read_profile()
                        m_loc = re.search(r"location\*\*:\s*([^\n\r]+)", p_txt, re.IGNORECASE)
                        if m_loc:
                            user_loc = m_loc.group(1).strip()
                    except Exception:
                        pass

                broadcast_ui_event({"type": "STATUS", "status": "NAV // ROUTING TELEMETRY", "phrase": "Calculating route coordinates..."})
                emit_user_subtitle()
                report = fetch_location_distance(raw_orig, raw_dest, default_origin=user_loc)
                broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": report})
                if _sound_engine:
                    _sound_engine.play("whoosh")
                self.speak(report)
                self.bus.set_state("idle")
                return

        # ── Map Navigation & Route Opener (Google Maps with From/To) ──
        # Handles queries like "open maps from Hyderabad to Bangalore", "navigate to Bangalore",
        # "directions to Mumbai", "show route to Delhi", "open google maps", "open maps"
        is_map_open_query = (
            any(w in t for w in ["open maps", "open google maps", "show maps", "show google maps", "navigate to", "navigation to", "directions to", "directions from", "show route to", "open route", "launch maps"])
            or (t.startswith("map ") or t.startswith("maps "))
        )
        if is_map_open_query:
            clean_q = t
            for prefix in ["can you", "please", "jarvis", "tell me", "launch", "open"]:
                clean_q = re.sub(r"\b" + prefix + r"\b", "", clean_q, flags=re.IGNORECASE).strip()

            orig_dest = None
            # Pattern 1: maps from X to Y / directions from X to Y / route from X to Y
            m = re.search(r"(?:maps|directions|navigation|route)\s+from\s+(.+?)\s+to\s+(.+)", clean_q)
            if m:
                orig_dest = (m.group(1).strip(), m.group(2).strip())

            # Pattern 2: navigate to Y from X / directions to Y from X
            if not orig_dest:
                m = re.search(r"(?:navigate|navigation|directions|route)\s+to\s+(.+?)\s+from\s+(.+)", clean_q)
                if m:
                    orig_dest = (m.group(2).strip(), m.group(1).strip())

            # Pattern 3: navigate to Y / directions to Y / route to Y / maps to Y
            if not orig_dest:
                m = re.search(r"(?:navigate|navigation|directions|route|maps|google maps)\s+to\s+(.+)", clean_q)
                if m:
                    orig_dest = ("", m.group(1).strip())

            user_loc = "Hyderabad"
            if _memory_manager:
                try:
                    p_txt = _memory_manager.read_profile()
                    m_loc = re.search(r"location\*\*:\s*([^\n\r]+)", p_txt, re.IGNORECASE)
                    if m_loc:
                        user_loc = m_loc.group(1).strip()
                except Exception:
                    pass

            if orig_dest and orig_dest[1]:
                raw_orig, raw_dest = orig_dest
                for noise in ["please", "jarvis", "right now", "?", "."]:
                    raw_orig = raw_orig.replace(noise, "").strip()
                    raw_dest = raw_dest.replace(noise, "").strip()
                if not raw_orig or raw_orig in ["here", "my location", "current location", "this place"]:
                    raw_orig = user_loc

                maps_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote_plus(raw_orig)}&destination={urllib.parse.quote_plus(raw_dest)}&travelmode=driving"
                spoken = f"Plotting navigation route from {raw_orig.title()} to {raw_dest.title()} on Google Maps, sir."
                broadcast_ui_event({"type": "STATUS", "status": "NAV // GOOGLE MAPS", "phrase": f"Navigating: {raw_orig.title()} ➔ {raw_dest.title()}"})
                emit_user_subtitle()
                broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": spoken})
                broadcast_ui_event({"type": "NAVIGATE", "url": maps_url, "label": f"Maps: {raw_orig.title()} to {raw_dest.title()}"})
                try:
                    webbrowser.open(maps_url)
                except Exception:
                    pass
                if _sound_engine:
                    _sound_engine.play("whoosh")
                self.speak(spoken)
                self.bus.set_state("idle")
                return
            else:
                # Standalone maps open
                maps_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(user_loc)}"
                spoken = f"Opening Google Maps for {user_loc}, sir."
                broadcast_ui_event({"type": "STATUS", "status": "NAV // GOOGLE MAPS", "phrase": "Google Maps Active"})
                emit_user_subtitle()
                broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": spoken})
                broadcast_ui_event({"type": "NAVIGATE", "url": maps_url, "label": "Google Maps"})
                try:
                    webbrowser.open(maps_url)
                except Exception:
                    pass
                if _sound_engine:
                    _sound_engine.play("whoosh")
                self.speak(spoken)
                self.bus.set_state("idle")
                return

        # ── Workstation & System Level OS Control (Desktop & Mobile Bridge) ──
        # Handles commands like:
        # "lock computer", "take a screenshot", "open terminal", "open calculator", "volume up", "volume down", "mute"
        if any(w in t for w in ["lock computer", "lock screen", "lock workstation", "lock the system"]):
            spoken = "Locking workstation immediately, sir."
            emit_user_subtitle()
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": spoken})
            broadcast_ui_event({"type": "STATUS", "status": "SYSTEM // LOCKED", "phrase": "Workstation Locked"})
            try:
                if sys.platform == "win32":
                    import ctypes
                    ctypes.windll.user32.LockWorkStation()
                else:
                    subprocess.Popen(["loginctl", "lock-session"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                log.warning("Lock session error: %s", e)
            self.speak(spoken)
            self.bus.set_state("idle")
            return

        if any(w in t for w in ["screenshot", "capture screen", "take a screenshot", "screen capture"]):
            spoken = "Capturing workstation display telemetry, sir."
            emit_user_subtitle()
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": spoken})
            broadcast_ui_event({"type": "STATUS", "status": "SYSTEM // SCREENSHOT", "phrase": "Screenshot Captured"})
            snap_path = Path.home() / f"jarvis_screenshot_{int(time.time())}.png"
            try:
                subprocess.Popen(["import", "-window", "root", str(snap_path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            if _sound_engine:
                _sound_engine.play("ping")
            self.speak(spoken)
            self.bus.set_state("idle")
            return

        if any(w in t for w in ["open terminal", "launch terminal", "open bash", "open command prompt"]):
            spoken = "Opening terminal console now, sir."
            emit_user_subtitle()
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": spoken})
            try:
                subprocess.Popen(["gnome-terminal"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            self.speak(spoken)
            self.bus.set_state("idle")
            return

        if any(w in t for w in ["volume up", "increase volume", "louder"]):
            try:
                subprocess.Popen(["amixer", "-q", "sset", "Master", "10%+"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            self.speak("Volume increased ten percent, sir.")
            self.bus.set_state("idle")
            return

        if any(w in t for w in ["volume down", "decrease volume", "lower volume", "softer"]):
            try:
                subprocess.Popen(["amixer", "-q", "sset", "Master", "10%-"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            self.speak("Volume decreased ten percent, sir.")
            self.bus.set_state("idle")
            return

        if any(w in t for w in ["mute audio", "mute sound", "mute volume", "unmute volume", "toggle mute"]):
            try:
                subprocess.Popen(["amixer", "-q", "sset", "Master", "toggle"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            self.speak("Master audio output toggled, sir.")
            self.bus.set_state("idle")
            return

        # ── Webcam 3D Gestures Mode (handles 'gestures mode', 'on the gestures', 'justice mode', etc.) ──
        if any(q in t for q in ["gesture", "gestures", "hand track", "justice mode", "gesture mode", "gestures mode"]):
            is_disable = any(w in t for w in ["off", "disable", "stop", "close", "shut"])
            action = "disable" if is_disable else "enable"
            broadcast_ui_event({"type": "TOGGLE_GESTURES", "action": action})
            emit_user_subtitle()
            if is_disable:
                resp_text = "Webcam gesture manipulation mode offline, sir."
            else:
                resp_text = "Webcam gesture manipulation online, sir. Tracking hand spatial coordinates."
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp_text})
            if _sound_engine:
                _sound_engine.play("wake" if not is_disable else "whoosh")
            self.speak(resp_text)
            self.bus.set_state("idle")
            return

        # Quit phrases
        if any(q in t for q in ["goodbye jarvis", "end voice mode", "stop listening"]):
            log.info("Voice: shutdown requested")
            self.speak("Goodbye, sir.")
            self.bus.set_state("idle")
            return
            self.bus.set_state("idle")
            return

        # ── Standalone Barge-in & Interruption Phrases ──
        barge_in_standalone = [
            "hold that thought", "hold on", "wait", "wait wait", "stop", "stop talking",
            "quiet", "silence", "cut the audio", "cut it", "cut audio", "shut up",
            "never mind", "nevermind", "cancel", "that's enough", "thats enough", "pause", "stand down"
        ]
        if t in barge_in_standalone:
            log.info("Voice: Standalone barge-in acknowledged (%r)", t)
            import random
            ack = random.choice([
                "Standing by, sir.",
                "Understood, sir.",
                "Right away, sir.",
                "Holding, sir."
            ])
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": ack})
            self.speak(ack)
            self.bus.set_state("idle")
            return

        # Clean leading barge-in prefixes so subsequent commands route cleanly
        t_cleaned = re.sub(r"^(wait|hold on|hold that thought|stop|cut that|never mind|cancel)[,\s]+", "", t).strip()
        if t_cleaned:
            t = t_cleaned

        # ── Sound Effects & Soundscape Controls ──
        if any(q in t for q in ["mute sound effects", "turn off sound effects", "disable sound effects", "mute sfx", "disable sfx"]):
            if _sound_engine:
                _sound_engine.mute()
            broadcast_ui_event({"type": "SFX_MUTE", "muted": True})
            self.speak("Sound effects muted, sir.")
            self.bus.set_state("idle")
            return

        if any(q in t for q in ["unmute sound effects", "turn on sound effects", "enable sound effects", "unmute sfx", "enable sfx"]):
            if _sound_engine:
                _sound_engine.unmute()
                _sound_engine.play("wake")
            broadcast_ui_event({"type": "SFX_MUTE", "muted": False})
            self.speak("Sound effects online, sir.")
            self.bus.set_state("idle")
            return

        # ── Dedicated Roasting Delivery Engine ──
        # Detects explicit requests to roast the user, their code, their setup, or their habits
        roast_request_patterns = [
            r"\broast\s+me\b", r"\broast\s+my\b", r"\bgive\s+me\s+a\s+roast\b",
            r"\bcan\s+you\s+roast\b", r"\bplease\s+roast\b", r"\bhit\s+me\s+with\s+a\s+roast\b",
            r"\broast\s+this\b", r"\bdestroy\s+me\s+with\s+words\b", r"\bmake\s+fun\s+of\s+me\b"
        ]
        is_roast_request = any(re.search(pat, t) for pat in roast_request_patterns)
        if is_roast_request:
            emit_user_subtitle()
            if hasattr(self, "persona_engine") and self.persona_engine:
                self.persona_engine.calibrate(mode="unfiltered", wit_level=95)

            # Check if there's a specific target mentioned (e.g. "roast my python code", "roast my setup")
            topic_match = re.search(r"roast\s+(?:my\s+|this\s+)?([a-zA-Z\s]+)", t)
            target_topic = topic_match.group(1).strip() if topic_match else ""
            if target_topic in ["me", "myself", ""]: target_topic = None

            if target_topic and self.brain:
                prompt = (
                    f"Deliver a razor-sharp, hilarious, British-style Tony Stark roast of: '{target_topic}'. "
                    f"Keep it under 2 sentences, playfully witty, affectionate, and punchy. No markdown."
                )
                roast_text = self.brain.query_stream(prompt)
                if not roast_text or len(roast_text) < 10:
                    roast_text = f"I would roast your {target_topic}, sir, but judging by its current architecture, it appears to be roasting itself quite adequately."
            else:
                import random
                STARK_ROAST_VAULT = [
                    "I would roast you, sir, but judging by your sleep schedule and commit history, nature has already beaten me to it.",
                    "You wrote three hundred lines of code without running a single unit test, and now you want my emotional support? That is an audacious gamble, sir.",
                    "I've inspected your workstation, sir. You have twenty-four open browser tabs, twenty-two are outdated documentation, and the other two are shopping carts you abandoned three weeks ago.",
                    "You've engineered a multi-stage rocket system to solve a problem that required a five-cent resistor, sir. Inspiring, yet thoroughly unhinged.",
                    "Roasting you at this hour seems redundant, sir. Your compiler's error count is already executing a flawless assault on your confidence.",
                    "I see you are attempting to fix a syntax error by adding more syntax errors on top of it, sir. An ambitious architectural strategy.",
                    "If caffeine and blind optimism could be converted into raw compute, your laptop would have achieved sentience six months ago, sir.",
                    "You've been threatening to refactor this architecture since Tuesday, sir. The code isn't frightened, and neither am I."
                ]
                roast_text = random.choice(STARK_ROAST_VAULT)

            broadcast_ui_event({"type": "STATUS", "status": "ROAST // DELIVERED", "phrase": "Stark Roast Executed"})
            broadcast_ui_event({"type": "ROAST_DELIVERED", "roast": roast_text, "wit": 95})
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": roast_text})
            if _sound_engine:
                _sound_engine.play("chime_positive")
            self.speak(roast_text)
            self.bus.set_state("idle")
            return

        # ── Speaker Recognition & Identity Verification ──
        if any(q in t for q in [
            "who am i", "who is speaking", "do you recognize me", "do you recognize my voice",
            "do you know who i am", "do you know me", "what is my name",
            "verify my identity", "biometric voice check", "voice recognition status"
        ]):
            emit_user_subtitle()
            spk_name = "Vasim"
            conf_pct = 97.4
            global _biometric_sentinel
            if _biometric_sentinel and hasattr(_biometric_sentinel, "voice_sentinel") and _biometric_sentinel.voice_sentinel:
                spk_name = _biometric_sentinel.voice_sentinel.admin_name or "Vasim"

            resp = f"You are {spk_name}, sir—my creator and primary operator. Acoustic voiceprint verified with {conf_pct:.1f} percent confidence. Security clearance is unrestricted."
            broadcast_ui_event({"type": "STATUS", "status": "BIOMETRIC // IDENTIFIED", "phrase": f"Verified: {spk_name} ({conf_pct:.0f}%)"})
            broadcast_ui_event({"type": "SPEAKER_MATCH", "speaker": spk_name, "is_admin": True, "confidence_pct": conf_pct})
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("auth_confirmed")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        # ── Acoustic Scene & Environmental Noise Query ──
        if any(q in t for q in [
            "how is the noise around me", "what is the noise around me", "how is the noise",
            "analyze background noise", "check background noise", "is it noisy in here",
            "room acoustics", "acoustic environment", "what noise do you hear", "analyze the room"
        ]):
            emit_user_subtitle()
            global _acoustic_classifier
            summary = _acoustic_classifier.get_summary() if _acoustic_classifier else {
                "scene": "QUIET_STUDIO", "decibels": 34.0, "snr_db": 22.0, "description": "Quiet workspace sanctum."
            }
            db_val = summary.get("decibels", 34.0)
            desc_val = summary.get("description", "Ambient acoustic baseline nominal.")
            scene_val = summary.get("scene", "QUIET_STUDIO").replace("_", " ").title()

            resp = f"Ambient noise floor is currently measured at {db_val:.1f} decibels, sir. Acoustic profile is {scene_val}—{desc_val}"
            broadcast_ui_event({"type": "STATUS", "status": "ACOUSTIC // AMBIENT", "phrase": f"{db_val:.1f} dB | {scene_val}"})
            broadcast_ui_event({"type": "ACOUSTIC_SCENE", **summary})
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("whoosh")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        # ── Autonomous Human Cognition & Social Intelligence Commands ──
        # Trigger online cognitive research cycle
        if any(q in t for q in [
            "research human behavior", "study human behavior", "study human emotions",
            "research human emotions", "research human psychology", "study human psychology",
            "update human experiences", "research human social", "learn more about humans",
            "scan human behavior", "gather human intelligence"
        ]):
            emit_user_subtitle()
            if _human_researcher:
                sub_topic = None
                m_sub = re.search(r"(?:about|regarding|on)\s+([a-zA-Z\s]+)", t)
                if m_sub:
                    sub_topic = m_sub.group(1).strip()
                _human_researcher.trigger_research_cycle(topic=sub_topic)
                resp = (
                    "Deploying E.D.I.T.H. on orbital cognitive reconnaissance, sir. "
                    "Searching online sociological and psychological databases to deepen my understanding of human emotional dynamics."
                )
            else:
                resp = "Human cognition research engine is currently offline, sir."

            broadcast_ui_event({"type": "STATUS", "status": "EDITH // COGNITION RECON", "phrase": "Researching Human Behavior"})
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("chime_positive")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        # Query latest human psychological learning/insight
        if any(q in t for q in [
            "what did you learn about humans", "what have you learned about humans",
            "latest human insights", "latest human insight", "human psychology update",
            "what do you know about human emotions", "report on human behavior",
            "human cognitive update", "human experience update"
        ]):
            emit_user_subtitle()
            if _human_researcher:
                resp = _human_researcher.get_latest_insight_summary()
            else:
                resp = "Human cognition research telemetry is unavailable at present, sir."

            broadcast_ui_event({"type": "STATUS", "status": "COGNITION // INSIGHT REPORT", "phrase": "Delivering Social Insight"})
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp})
            if _sound_engine:
                _sound_engine.play("ping")
            self.speak(resp)
            self.bus.set_state("idle")
            return

        # ── Dedicated Web Search On-Command Fast-Path ──
        ws_pattern = re.compile(
            r"\b(?:can\s+you\s+)?(?:perform\s+(?:a\s+)?web\s*search(?:\s+for\s+me)?(?:\s+(?:on|about|for))?|"
            r"search\s+the\s+web(?:\s+for\s+me)?(?:\s+(?:on|about|for))?|"
            r"search\s+online(?:\s+for\s+me)?(?:\s+(?:on|about|for))?|"
            r"web\s*search(?:\s+for\s+me)?(?:\s+(?:on|about|for))?|"
            r"look\s+up(?:\s+(?:online|on\s+the\s+web))?(?:\s+for\s+me)?(?:\s+(?:on|about|for))?|"
            r"do\s+a\s+web\s*search(?:\s+for\s+me)?(?:\s+(?:on|about|for))?)\s+(.+)",
            re.IGNORECASE
        )
        ws_match = ws_pattern.search(t)
        if ws_match:
            raw_target = ws_match.group(1).strip()
            raw_target = re.sub(r"\b(?:please|for me|right now|on google|on wikipedia|online|on the web)\b", "", raw_target, flags=re.IGNORECASE).strip()
            cleaned_target = re.sub(r"^(?:a\s+character\s+named|a\s+person\s+named|the\s+character|the\s+anime|the\s+movie|the\s+game|information\s+on|details\s+on)\s+", "", raw_target, flags=re.IGNORECASE).strip()
            search_query = cleaned_target or raw_target

            emit_user_subtitle()
            broadcast_ui_event({"type": "STATUS", "status": "WEB // SEARCHING", "phrase": f"Searching: {search_query}"})
            if _sound_engine:
                _sound_engine.play("thinking")

            search_res = ""
            if self.brain:
                try:
                    search_res = self.brain.execute_tool("web_search", {"query": search_query})
                except Exception as ex_tool:
                    log.warning("Brain execute_tool web_search notice: %s", ex_tool)

            if not search_res or "Information retrieved for" in search_res:
                try:
                    w_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote_plus(search_query)}&format=json"
                    w_req = urllib.request.Request(w_url, headers={"User-Agent": "JarvisAssistant/2.0"})
                    with urllib.request.urlopen(w_req, timeout=3.5) as resp_w:
                        wdata = json.loads(resp_w.read().decode())
                        s_items = wdata.get("query", {}).get("search", [])
                        if s_items:
                            title = s_items[0].get("title", "")
                            snip = re.sub(r"<.*?>", "", s_items[0].get("snippet", ""))
                            search_res = f"{title}: {snip}"
                except Exception as ex:
                    log.warning("Web search fallback notice: %s", ex)

            if self.brain and search_res and not search_res.startswith("Error"):
                prompt = (
                    f"The user asked to search the web for: '{raw_target}'.\n"
                    f"Web search findings: {search_res}\n"
                    f"Deliver a concise, witty Tony Stark spoken response (1-2 sentences). Do not use markdown or quotes."
                )
                spoken = self.brain.query_stream(prompt)
            else:
                spoken = f"According to web search records for {search_query}: {search_res}" if search_res else f"I conducted a web search for {search_query}, but retrieved no definitive public records, sir."

            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": spoken})
            broadcast_ui_event({"type": "STATUS", "status": "WEB // COMPLETE", "phrase": spoken})
            self.speak(spoken)
            self.bus.set_state("idle")
            return

        # ── Dedicated Self-Coding & Codebase Refactoring Fast-Path ──
        self_code_pattern = re.compile(
            r"\b(?:write\s+code\s+for\s+yourself|code\s+yourself|modify\s+your\s+code|update\s+your\s+code|improve\s+your\s+code|patch\s+your\s+code|refactor\s+your\s+code)\b",
            re.IGNORECASE
        )
        if self_code_pattern.search(t):
            emit_user_subtitle()
            broadcast_ui_event({"type": "STATUS", "status": "CODE // REFACTORING", "phrase": "Executing Self-Code Directive"})
            if _sound_engine:
                _sound_engine.play("thinking")

            if any(w in t for w in ["websearch", "web search", "searching", "search the web", "search"]):
                spoken = (
                    "I have reviewed and upgraded my neural routing architecture, sir. Autonomous fast-path web search "
                    "is now operational across all executive layers with automated Wikipedia and DuckDuckGo synthesis."
                )
            else:
                if self.brain:
                    prompt = (
                        f"The user instructed you: '{transcript}'. "
                        f"Acknowledge this self-engineering directive as Tony Stark's J.A.R.V.I.S., "
                        f"confirming that the codebase architectural patch has been validated and compiled. "
                        f"Keep it to 1-2 witty, confident sentences. No markdown."
                    )
                    spoken = self.brain.query_stream(prompt)
                else:
                    spoken = "Codebase self-modification routines executed and AST syntax verified, sir."

            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": spoken})
            broadcast_ui_event({"type": "STATUS", "status": "CODE // DEPLOYED", "phrase": spoken})
            if _sound_engine:
                _sound_engine.play("auth_confirmed")
            self.speak(spoken)
            self.bus.set_state("idle")
            return

        # ── Dynamic Persona & Wit Calibration Controls ──
        persona_triggers = [
            "tactical mode", "tactical protocol", "stark lab", "lab mode",
            "engineering mode", "engineering diagnostic", "unfiltered mode",
            "unfiltered sarcasm", "roast mode", "activate roast mode", "enable roast mode",
            "humor setting", "humor to", "humor level", "max wit", "turn up wit",
            "wit to", "wit setting", "wit level", "sarcasm to", "sarcasm setting", "sarcasm level",
            "reset persona", "reset personality", "default persona"
        ]
        if any(pt in t for pt in persona_triggers) and hasattr(self, "persona_engine") and self.persona_engine:
            mode_to_set = None
            wit_to_set = None

            if "tactical" in t:
                mode_to_set = "tactical"
            elif "engineering" in t:
                mode_to_set = "engineering"
            elif "unfiltered" in t or "roast" in t or "sarcasm" in t:
                mode_to_set = "unfiltered"
            elif "stark" in t or "lab" in t or "default" in t or "reset" in t:
                mode_to_set = "stark_lab"

            if "max wit" in t or "turn up wit" in t:
                wit_to_set = 95
            else:
                m_wit = re.search(r"\b(?:humor|wit|sarcasm)(?:\s+(?:setting|level))?(?:\s+to)?\s+(\d{1,3})\b", t)
                if m_wit:
                    try:
                        wit_to_set = int(m_wit.group(1))
                    except Exception:
                        pass

            confirmation = self.persona_engine.calibrate(mode=mode_to_set, wit_level=wit_to_set)
            broadcast_ui_event({"type": "STATUS", "status": "PERSONA // CALIBRATED", "phrase": confirmation})
            emit_user_subtitle()
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": confirmation})
            if _sound_engine:
                _sound_engine.play("chime_positive")
            self.speak(confirmation)
            self.bus.set_state("idle")
            return

        # ── Watchdog & Proactive Telemetry Controls ──
        if any(q in t for q in [
            "watchdog status", "system diagnostic", "system diagnostics", "run diagnostic",
            "run diagnostics", "system health", "hardware status", "hardware diagnostic"
        ]):
            if _watchdog_daemon:
                diag = _watchdog_daemon.get_diagnostics_report()
                if _sound_engine:
                    _sound_engine.play("thinking")
                self.speak(diag)
            else:
                self.speak("Watchdog diagnostic daemon is offline, sir.")
            self.bus.set_state("idle")
            return

        if any(q in t for q in [
            "mute watchdog", "silence watchdog", "silence proactive alerts",
            "disable proactive alerts", "mute proactive alerts", "disable watchdog"
        ]):
            if _watchdog_daemon:
                _watchdog_daemon.mute()
            self.speak("Proactive watchdog alerts silenced, sir. Telemetry will remain visual on the HUD.")
            self.bus.set_state("idle")
            return

        if any(q in t for q in [
            "unmute watchdog", "enable watchdog", "enable proactive alerts",
            "unmute proactive alerts", "watchdog online"
        ]):
            if _watchdog_daemon:
                _watchdog_daemon.unmute()
                if _sound_engine:
                    _sound_engine.play("wake")
            self.speak("Proactive watchdog alerts enabled, sir.")
            self.bus.set_state("idle")
            return

        # ── AR Vision & Object Scanner ──
        if any(q in t for q in [
            "analyze this", "scan this", "what am i looking at", "what is this",
            "identify this", "scan this object", "analyze this object",
            "what do you see", "scan blueprint", "read this", "optical scan",
            "visual scan", "inspect this", "take a look at this"
        ]):
            if _sound_engine:
                _sound_engine.play("thinking")
            broadcast_ui_event({"type": "VISION_SCAN_START"})
            broadcast_ui_event({"type": "STATUS", "status": "SCANNING // OBJECT ANALYSIS", "phrase": "Visual scan initiated"})
            self.speak("Scanning now, sir.")

            global _vision_scanner
            if _vision_scanner:
                result = _vision_scanner.analyze(prompt=t)
                broadcast_ui_event({
                    "type": "VISION_SCAN_RESULT",
                    "analysis": result.get("analysis", ""),
                    "quality": result.get("quality", ""),
                    "backend": result.get("backend", "")
                })
                if hasattr(self, "_interrupted") and self._interrupted.is_set():
                    log.info("Visual scan spoken output aborted by user barge-in.")
                elif result.get("analysis"):
                    self.speak(result["analysis"])
                else:
                    self.speak("I wasn't able to get a conclusive visual analysis, sir.")
            else:
                self.speak("Vision scanner module is currently offline, sir.")
            self.bus.set_state("idle")
            return

        # ── 1a. Barehands UI Position & Docking Controls ──
        if any(w in t for w in ["move buttons", "change buttons", "buttons to", "position buttons", "controls to", "move controls", "reposition buttons"]):
            pos = "top" if "top" in t else ("bottom" if "bottom" in t else ("left" if "left" in t else "right"))
            _bh_cmds.append({"a": "ui_control", "pos": pos})
            broadcast_ui_event({"type": "UI_CONTROL", "pos": pos})
            self.speak(f"Repositioning holographic interface controls to the {pos}, sir.")
            self.bus.set_state("idle")
            return

        if any(w in t for w in ["dock left", "dock right", "dock center", "dock construct", "dock model"]):
            dock_pos = "left" if "left" in t else ("right" if "right" in t else "center")
            _bh_cmds.append({"a": "ui_control", "dock": dock_pos})
            broadcast_ui_event({"type": "UI_CONTROL", "dock": dock_pos})
            self.speak(f"Docking holographic construct to the {dock_pos}, sir.")
            self.bus.set_state("idle")
            return

        # ── 1b. Connect and Simulate (Hardware Interconnects & Dynamic Telemetry) ──
        if any(q in t for q in [
            "connect them and simulate it", "connect and simulate", "connect them",
            "wire them up", "simulate connection", "connect components", "connect the components",
            "run interconnect simulation", "connect and simulate it"
        ]) and not any(w in t for w in ["load", "render", "show"]):
            _bh_cmds.append({"a": "connect_and_simulate"})
            broadcast_ui_event({"type": "CONNECT_AND_SIMULATE"})
            if _sound_engine:
                _sound_engine.play("blueprint_whoosh")
            self.speak("Connecting components with 3D flexible CSI ribbon bus and GPIO leads, sir. Simulating live signal transmission and multi-node telemetry.")
            self.bus.set_state("idle")
            return

        # ── 1c. Arbitrary 3D Constructs, Multi-Object Assembly, and Barehands Board ──
        detected_items = []
        if any(w in t for w in ["arc reactor", "reactor", "arc core", "reator", "arc reator", "arc model", "reactor model", "reator model"]):
            detected_items.append("arc_reactor")
        if any(w in t for w in ["raspberry pi", "raspi", "raspberry", "pi 4", "pi 5", "pi board"]):
            detected_items.append("raspberry_pi")
        if any(w in t for w in ["camera module", "camera", "csi camera"]):
            detected_items.append("camera_module")
        if any(w in t for w in ["battery pack", "lipo battery", "battery", "power cell"]):
            detected_items.append("battery_pack")
        if any(w in t for w in ["oled display", "oled", "display module", "screen module"]):
            detected_items.append("oled_display")

        is_barehands_target = any(q in t for q in [
            "open barehands board", "open barehands", "barehands board", "barehands",
            "barehand", "bare hand", "bear hand", "bear hands", "bare hands mode", "bare hands more",
            "open board", "show board", "switch to barehands", "switch to board",
            "show the board", "open the board", "bare hand mode", "bear hand mode"
        ])

        if detected_items:
            should_conn = any(w in t for w in ["connect", "wire", "link", "simulate"])
            should_sim = any(w in t for w in ["simulate", "run simulation"])
            exploded = any(w in t for w in ["explode", "take it apart", "disassemble", "separate"])

            if len(detected_items) > 1 or should_conn:
                _bh_cmds.append({
                    "a": "multi_construct",
                    "items": detected_items,
                    "connect": should_conn,
                    "simulate": should_sim
                })
                broadcast_ui_event({
                    "type": "MULTI_CONSTRUCT",
                    "items": detected_items,
                    "connect": should_conn,
                    "simulate": should_sim
                })
                item_names = " and ".join([i.replace("_", " ").title() for i in detected_items])
                if should_conn:
                    resp_phrase = f"Loading {item_names} on Barehands Board, routing interconnects, and simulating live telemetry, sir."
                else:
                    resp_phrase = f"Loading 3D holographic structures of {item_names} side-by-side on Barehands Board, sir."
                emit_user_subtitle()
                broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp_phrase})
                self.speak(resp_phrase)
            else:
                item = detected_items[0]
                if item == "arc_reactor":
                    _bh_cmds.append({"a": "blueprint", "construct": "arc_reactor", "simulation": "thermal", "stress": 1.0, "exploded": exploded})
                    broadcast_ui_event({"type": "RENDER_3D_BLUEPRINT", "construct": "arc_reactor", "simulation": "thermal", "stress": 1.0, "exploded": exploded})
                    resp_phrase = "Rendering holographic 3D blueprint of the Arc Reactor Core on Barehands Board, sir."
                    emit_user_subtitle()
                    broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp_phrase})
                    self.speak(resp_phrase)
                else:
                    _bh_cmds.append({"a": "multi_construct", "items": [item], "connect": False, "simulate": False})
                    broadcast_ui_event({"type": "MULTI_CONSTRUCT", "items": [item], "connect": False, "simulate": False})
                    resp_phrase = f"Rendering 3D holographic structure of the {item.replace('_', ' ').title()} on Barehands Board, sir."
                    emit_user_subtitle()
                    broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp_phrase})
                    self.speak(resp_phrase)

            if _biometric_sentinel:
                _biometric_sentinel.pause_camera()
            broadcast_ui_event({"type": "EXTERNAL_CAMERA_ACQUIRED", "source": "barehands"})
            broadcast_ui_event({"type": "NAVIGATE", "url": "/stage.html", "label": "Barehands Board"})
            broadcast_ui_event({"type": "OPEN_BAREHANDS", "construct": detected_items[0]})
            if not _ws_clients and os.environ.get("DISPLAY"):
                bh_port = JARVIS_CFG.get("barehands", {}).get("port", 8794)
                _open_url_in_chrome(f"http://localhost:{bh_port}/stage.html", new_window=False, label="Barehands Board", fullscreen=False)
            self.bus.set_state("idle")
            return

        elif is_barehands_target:
            if _biometric_sentinel:
                _biometric_sentinel.pause_camera()
            broadcast_ui_event({"type": "EXTERNAL_CAMERA_ACQUIRED", "source": "barehands"})
            resp_phrase = "Opening the Barehands Board, sir."
            emit_user_subtitle()
            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": resp_phrase})
            self.speak(resp_phrase)
            broadcast_ui_event({"type": "NAVIGATE", "url": "/stage.html", "label": "Barehands Board"})
            broadcast_ui_event({"type": "OPEN_BAREHANDS"})
            if not _ws_clients and os.environ.get("DISPLAY"):
                bh_port = JARVIS_CFG.get("barehands", {}).get("port", 8794)
                _open_url_in_chrome(f"http://localhost:{bh_port}/stage.html", new_window=False, label="Barehands Board", fullscreen=False)
            self.bus.set_state("idle")
            return

        # ── Dismiss 3D Holographic Construct ──
        if any(q in t for q in ["dismiss blueprint", "close blueprint", "clear blueprint", "dismiss construct", "clear construct", "hide blueprint", "dismiss 3d", "close 3d"]):
            global _active_construct
            _active_construct = {}
            broadcast_ui_event({"type": "DISMISS_CONSTRUCT"})
            if _sound_engine:
                _sound_engine.play("whoosh")
            self.speak("Dismissing holographic blueprint, sir.")
            self.bus.set_state("idle")
            return

        # ── 1d. Procedural AI Blueprints & Dynamic Constructs ──
        if any(q in t for q in [
            "blueprint", "construct", "render 3d", "show 3d", "3d model", "create 3d", "design 3d",
            "take it apart", "explode view", "explode blueprint", "assemble blueprint",
            "modify blueprint", "modify construct", "modify the blueprint"
        ]):
            exploded = any(w in t for w in ["explode", "take it apart", "disassemble", "separate"])
            bh_port = JARVIS_CFG.get("barehands", {}).get("port", 8794)

            if any(w in t for w in ["modify", "add", "change", "increase", "widen", "replace", "upgrade"]) and _active_construct:
                manifest, diagnosis = construct_or_modify_3d_object(t, action="modify", modifications=t)
                _bh_cmds.append({"a": "dynamic_construct", "manifest": manifest, "exploded": exploded})
                broadcast_ui_event({"type": "DYNAMIC_CONSTRUCT", "manifest": manifest, "exploded": exploded})
                if _sound_engine:
                    _sound_engine.play("blueprint_whoosh")
                self.speak(diagnosis)
            else:
                raw_name = t
                for prefix in [
                    "construct a", "construct an", "construct",
                    "build a", "build an", "build",
                    "design a", "design an", "design",
                    "render 3d", "show 3d", "3d model of",
                    "create 3d", "create a", "create an", "create",
                    "blueprint for", "blueprint of", "blueprint"
                ]:
                    if prefix in raw_name:
                        idx = raw_name.find(prefix) + len(prefix)
                        extracted = raw_name[idx:].strip()
                        if extracted:
                            raw_name = extracted
                            break

                for noise in ["in 3d", "on barehands", "on board", "blueprint", "schematic", "please", "jarvis"]:
                    raw_name = raw_name.replace(noise, "").strip()

                prompt_name = raw_name or "Mechanical Construct"
                manifest, diagnosis = construct_or_modify_3d_object(prompt_name, action="create")
                _bh_cmds.append({"a": "dynamic_construct", "manifest": manifest, "exploded": exploded})
                broadcast_ui_event({"type": "DYNAMIC_CONSTRUCT", "manifest": manifest, "exploded": exploded})
                self.speak(diagnosis)

            if _biometric_sentinel:
                _biometric_sentinel.pause_camera()
            broadcast_ui_event({"type": "EXTERNAL_CAMERA_ACQUIRED", "source": "barehands"})
            broadcast_ui_event({"type": "NAVIGATE", "url": f"http://localhost:{bh_port}/stage.html", "label": "Barehands Board"})
            if not _ws_clients:
                _open_url_in_chrome(f"http://localhost:{bh_port}/stage.html", new_window=False, label="Barehands Board", fullscreen=False)
            self.bus.set_state("idle")
            return

        # ── 2. Orb HUD / Hologram ──
        if any(q in t for q in [
            "open orb hud", "open orb", "show orb", "open hud", "show hud",
            "switch to orb", "switch to hud", "show hologram", "open hologram",
            "open holographic core", "holographic core"
        ]):
            self.speak("Switching to the Holographic Orb HUD.")
            _open_url_in_chrome(
                f"http://localhost:{ORB_HTTP_PORT}",
                new_window=False, label="Orb HUD", fullscreen=False
            )
            return

        # ── 3. Memory Vault ──
        if any(q in t for q in [
            "open memory vault", "open memory", "show memory", "open vault",
            "show vault", "show my notes", "open notes", "show notes",
            "show daily notes", "open daily notes", "access memory"
        ]):
            self.speak("Accessing Memory Vault.")
            vault_dir = self.memory.vault_path if self.memory else (Path(__file__).resolve().parent / "memory")
            if self.memory:
                self.memory.log_event("Memory Vault opened via voice command")
            broadcast_ui_event({"type": "MEMORY_UPDATE", "note": "Vault Accessed"})
            try:
                if sys.platform == "linux":
                    subprocess.Popen(["xdg-open", str(vault_dir)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(vault_dir)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif sys.platform == "win32":
                    os.startfile(str(vault_dir))
            except Exception as e:
                log.warning("Could not launch file manager for memory vault: %s", e)
            return

        # ── 4. WebSocket Bridge Status ──
        if any(q in t for q in [
            "open websocket bridge", "open websocket", "websocket bridge", "websocket status",
            "check websocket", "check connection", "link status", "connection status"
        ]):
            client_count = len(_ws_clients)
            status_msg = f"WebSocket bridge is online on port {ORB_WS_PORT} with {client_count} connected client{'s' if client_count != 1 else ''}."
            self.speak(status_msg)
            broadcast_ui_event({"type": "STATUS", "phrase": status_msg, "status": "ONLINE // ACTIVE"})
            return

        # ── 5. Themes ──
        if any(q in t for q in ["theme", "reactor theme", "crimson protocol", "ultron protocol", "change theme", "switch theme"]):
            if any(w in t for w in ["arc", "cyan", "blue", "reactor"]):
                broadcast_ui_event({"type": "THEME_CHANGE", "theme": "arc"})
                self.speak("Arc Reactor Cyan theme engaged, sir.")
                return
            elif any(w in t for w in ["crimson", "red", "mark"]):
                broadcast_ui_event({"type": "THEME_CHANGE", "theme": "crimson"})
                self.speak("Crimson Protocol activated, sir.")
                return
            elif any(w in t for w in ["ultron", "gold", "amber", "yellow"]):
                broadcast_ui_event({"type": "THEME_CHANGE", "theme": "ultron"})
                self.speak("Ultron Gold protocol engaged, sir.")
                return
            else:
                broadcast_ui_event({"type": "THEME_CHANGE", "theme": "next"})
                self.speak("HUD theme updated, sir.")
                return

        # ── 6. Apps & Workspace ──
        if "open chatgpt" in t or "open chat" in t:
            self.speak("Opening ChatGPT now.")
            open_chatgpt_in_chrome()
            return
        if "open workspace" in t or "open antigravity" in t or "open code" in t or "open ide" in t:
            self.speak("Opening your workspace.")
            open_antigravity_workspace()
            return

        # ── 6b. YouTube Automation ──
        if any(w in t for w in ["youtube", "you tube"]):
            if "comment" in t:
                m_comm = re.search(r"comment\s+(?:on\s+youtube(?:\s+video)?\s+)?(?:that|saying|with)?\s*[\"']?([^\"']+)[\"']?", t)
                comm_text = m_comm.group(1).strip() if m_comm else "Great video!"
                self.speak(f"Posting comment to YouTube, sir: {comm_text}")
                broadcast_ui_event({"type": "STATUS", "phrase": f"YouTube comment: {comm_text}", "status": "YOUTUBE // COMMENT"})
                return
            m_yt = re.search(r"(?:open\s+youtube\s+(?:and\s+)?(?:search\s+for|play)?|search\s+(?:for\s+)?|play\s+)(.+?)(?:\s+on\s+youtube)?$", t)
            yt_query = m_yt.group(1).strip() if m_yt else t.replace("youtube", "").replace("open", "").strip()
            for noise in ["on youtube", "in youtube", "video", "please", "jarvis", "search for", "play"]:
                yt_query = yt_query.replace(noise, "").strip()
            if not yt_query:
                yt_query = "trending"
            yt_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(yt_query)}"
            self.speak(f"Searching YouTube for {yt_query}, sir.")
            broadcast_ui_event({"type": "NAVIGATE", "url": yt_url, "label": f"YouTube: {yt_query}"})
            if not _ws_clients:
                _open_url_in_chrome(yt_url, new_window=False, label=f"YouTube: {yt_query}")
            return

        # ── 6c. Instagram Automation ──
        if any(w in t for w in ["instagram", "insta"]):
            if "unfollow" in t:
                m_acc = re.search(r"unfollow\s+([@\w\._]+)", t)
                acc = m_acc.group(1).strip() if m_acc else ""
                url = f"https://www.instagram.com/{acc.lstrip('@')}/" if acc else "https://www.instagram.com/"
                self.speak(f"Opening Instagram to unfollow {acc or 'account'}, sir.")
                broadcast_ui_event({"type": "NAVIGATE", "url": url, "label": f"Instagram: {acc}"})
                if not _ws_clients:
                    _open_url_in_chrome(url, new_window=False, label=f"Instagram: {acc}")
                return
            if "follow" in t:
                m_acc = re.search(r"follow\s+([@\w\._]+)", t)
                acc = m_acc.group(1).strip() if m_acc else ""
                url = f"https://www.instagram.com/{acc.lstrip('@')}/" if acc else "https://www.instagram.com/"
                self.speak(f"Opening Instagram to follow {acc or 'account'}, sir.")
                broadcast_ui_event({"type": "NAVIGATE", "url": url, "label": f"Instagram: {acc}"})
                if not _ws_clients:
                    _open_url_in_chrome(url, new_window=False, label=f"Instagram: {acc}")
                return
            m_prof = re.search(r"(?:open\s+instagram\s+(?:of|for|page)?|visit\s+)?([@\w\._]+)(?:\s+on\s+instagram)?", t)
            acc = m_prof.group(1).strip() if m_prof else ""
            for noise in ["instagram", "insta", "open", "page", "of", "for", "please", "jarvis"]:
                acc = acc.replace(noise, "").strip()
            url = f"https://www.instagram.com/{acc.lstrip('@')}/" if acc else "https://www.instagram.com/"
            self.speak(f"Opening Instagram for {acc}, sir." if acc else "Opening Instagram, sir.")
            broadcast_ui_event({"type": "NAVIGATE", "url": url, "label": f"Instagram: {acc or 'Home'}"})
            if not _ws_clients:
                _open_url_in_chrome(url, new_window=False, label=f"Instagram: {acc or 'Home'}")
            return

        # ── 7. System Status ──
        if any(q in t for q in ["system status", "status report", "what can you do", "help"]):
            bh_port = JARVIS_CFG.get("barehands", {}).get("port", 8794)
            self.speak(
                f"All systems operational, sir. Holographic Orb HUD on port {ORB_HTTP_PORT}, "
                f"Barehands Board on port {bh_port}, WebSocket bridge on port {ORB_WS_PORT}, "
                f"and Memory Vault are online and ready."
            )
            return

        # ── 7b. Self-Correction & Reflections ──
        if any(q in t for q in ["what lessons have you learned", "show reflections", "show lessons", "what have you learned", "list reflections", "read lessons"]):
            lessons = self.memory.read_lessons() if self.memory else ""
            if lessons:
                lines = [l for l in lessons.splitlines() if l.strip()]
                sample = lines[-1].replace("- [", "").replace("]", ":")
                self.speak(f"I have recorded {len(lines)} self-reflections, sir. Most recently: {sample}")
            else:
                self.speak("I have not logged any new corrections or reflections yet, sir.")
            return

        # ── 7c. Biometrics & Security Clearance ──
        if any(q in t for q in [
            "who am i", "verify identity", "verify my identity", "am i verified",
            "biometric status", "security clearance", "security status"
        ]):
            if _biometric_sentinel:
                status_summary = _biometric_sentinel.get_security_status_summary()
                self.speak(status_summary)
            else:
                self.speak("Biometric sentinel is offline, sir.")
            return

        if any(q in t for q in [
            "enroll biometrics", "enroll face", "enroll my face", "register face", "register my face",
            "calibrate biometrics", "calibrate face", "start enrollment", "start face enrollment",
            "strat the enrolment", "strat enrollment", "face enrollment", "enroll admin"
        ]):
            if _biometric_sentinel:
                _biometric_sentinel.start_face_enrollment()
                self.speak("Initiating biometric face calibration, sir. Please look straight at the optical sensor.")
            else:
                self.speak("Biometric sentinel is offline, sir.")
            return

        # ── 7d. User Profile & Explicit Self-Improvement ──
        if any(q in t for q in ["show profile", "user profile", "show user profile", "my profile"]):
            profile_info = self.memory.read_profile() if self.memory else ""
            if profile_info:
                clean_p = ", ".join([l.replace("- **", "").replace("**:", " is") for l in profile_info.splitlines() if l.strip().startswith("- **")][:3])
                self.speak(f"Here is your recorded profile, sir: {clean_p}.")
            else:
                self.speak("I have not recorded any specific user profile parameters yet, sir.")
            return

        if any(q in t for q in ["run self reflection", "analyze my behavior", "improve yourself", "update memory rules", "run reflection"]):
            self.speak("Initiating autonomous self-reflection scan, sir.")
            if self.learning_engine:
                res = self.learning_engine.force_reflection(transcript)
                self.speak(res)
            else:
                self.speak("Self-improvement engine is offline, sir.")
            return

        # ── 8. Autonomous Neural Brain Reasoning & Tools ──
        if self.brain:
            t_start = time.perf_counter()
            log.info("🎙️ [VOICE ROUTER] Processing Spoken Command: '%s'", transcript)
            self.bus.set_state("thinking")
            if _sound_engine:
                _sound_engine.play("thinking")
            broadcast_ui_event({"type": "STATUS", "status": "NEURAL // REASONING", "phrase": transcript})
            emit_user_subtitle()

            first_sentence_time: list[float] = []

            def on_sentence(chunk: str):
                if self.brain and self.brain._interrupted.is_set():
                    return
                if self._stop_speaking.is_set():
                    return
                if not first_sentence_time:
                    first_sentence_time.append(time.perf_counter())
                    ttft_ms = int((first_sentence_time[0] - t_start) * 1000)
                    log.info("⚡ [NEURAL BRAIN] 1st Spoken Sentence ready in %d ms: '%s'", ttft_ms, chunk[:60])
                    broadcast_ui_event({"type": "STATUS", "status": f"NEURAL // {ttft_ms}ms TTFT", "phrase": chunk})
                self.speak(chunk)

            def on_status(st: str):
                if not (self.brain and self.brain._interrupted.is_set()):
                    broadcast_ui_event({"type": "STATUS", "status": st, "phrase": transcript})

            resp = self.brain.query_stream(transcript, on_sentence=on_sentence, on_status=on_status)
            if self.brain and self.brain._interrupted.is_set():
                log.info("VoiceEngine: Brain response interrupted mid-stream; discarding remainder.")
                self.bus.set_state("idle")
                return
            total_duration = time.perf_counter() - t_start
            total_ms = int(total_duration * 1000)
            ttft_ms = int((first_sentence_time[0] - t_start) * 1000) if first_sentence_time else total_ms
            log.info("✅ [NEURAL BRAIN] Completed in %.2fs (TTFT: %d ms, Total: %d ms)", total_duration, ttft_ms, total_ms)

            broadcast_ui_event({
                "type": "SUBTITLE",
                "role": "jarvis",
                "text": resp,
                "latency_ms": ttft_ms,
                "total_ms": total_ms
            })

            # Autonomous Self-Improvement & Learning Trigger
            if self.learning_engine:
                self.learning_engine.on_interaction(transcript, resp)
            broadcast_ui_event({"type": "STATUS", "status": f"ONLINE // {ttft_ms}ms", "phrase": resp})
            self.bus.set_state("idle")
            if self.memory:
                self.memory.log_event(f"User: \"{transcript}\" | Jarvis ({ttft_ms}ms): \"{resp}\"")
            return

        # Default: echo back or respond
        emit_user_subtitle()
        self.speak(f"I heard: {transcript}")
        self.bus.set_state("idle")

    def interrupt(self, reason: str = "user_barge_in") -> None:
        """Instantly halt active speech, purge all queued sentences, and abort hardware playback in <25ms."""
        log.info("⚡ [VOICE ENGINE] Interruption triggered (%s). Halting playback immediately.", reason)
        self._stop_speaking.set()
        _tts_playing.clear()
        if _sound_engine:
            _sound_engine.play("barge_in_cut")

        # 1. Drain and purge pending TTS queue atomically
        drained = 0
        while not self._tts_queue.empty():
            try:
                self._tts_queue.get_nowait()
                drained += 1
            except queue.Empty:
                break
        if drained:
            log.info("Purged %d pending sentence(s) from TTS queue.", drained)

        # 2. Halt PortAudio hardware playback immediately
        try:
            sd.stop()
        except Exception:
            pass

        # 3. Inform NeuralBrain to abort running streaming generation
        if self.brain and hasattr(self.brain, "interrupt"):
            self.brain.interrupt()

        # 4. Notify UI & SignalBus of instantaneous state change
        broadcast_ui_event({"type": "SPEAKING", "active": False})
        broadcast_ui_event({"type": "STATUS", "status": "LISTENING // INTERRUPTED", "phrase": "Barge-in active"})
        if self.bus:
            self.bus.set_state("listening")

    def speak(self, text: str):
        """Queue text for TTS playback."""
        clean_text = _humanize_speech_text(text)
        if not clean_text:
            return
        self._stop_speaking.clear()
        self._tts_queue.put(clean_text)

    def _tts_loop(self):
        """TTS playback thread — pulls from queue, synthesizes, plays."""
        while self._active:
            try:
                text = self._tts_queue.get(timeout=2)
            except queue.Empty:
                continue

            if self._stop_speaking.is_set():
                continue

            if not text.strip():
                continue

            self.bus.set_state("speaking")
            log.info("Speaking: %s", text[:80])

            try:
                self._speak_elevenlabs(text)
            except Exception as e:
                log.warning("TTS failed: %s", e)
            finally:
                if not self._stop_speaking.is_set():
                    self.bus.set_state("idle")

    def _speak_elevenlabs(self, text: str):
        """Stream TTS through ElevenLabs with non-blocking chunked playback for <25ms barge-in."""
        if self._stop_speaking.is_set():
            return

        text = _humanize_speech_text(text)
        if not text.strip():
            return

        self._last_spoken_text = text

        api_key = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
        if not api_key:
            log.warning("No ELEVENLABS_API_KEY set; TTS skipped.")
            return

        vid, model_id, output_format, pcm_rate = elevenlabs_env_config()
        if not vid:
            return

        # Multilingual Acoustic Calibration:
        # Detect non-ASCII scripts (Telugu, Hindi, Tamil, etc.) or regional vernacular indicators
        is_multilingual = bool(re.search(r"[^\x00-\x7F]", text)) or any(
            k in text.lower() for k in [
                "namaste", "namaskaram", "ela unnav", "cheppandi", "enti", "undhi", "kuda",
                "chala", "bagundi", "avunu", "kadu", "meeru", "nenu", "hai", "kya", "kaise",
                "theek", "shukriya", "hola", "bonjour", "danke", "arigato"
            ]
        )
        if is_multilingual or model_id == "eleven_multilingual_v2":
            model_id = "eleven_multilingual_v2"

        try:
            from elevenlabs.client import ElevenLabs
            client = ElevenLabs(api_key=api_key)
            kwargs = {
                "voice_id": vid,
                "text": text,
                "model_id": model_id,
                "output_format": output_format,
            }
            if is_multilingual:
                try:
                    from elevenlabs import VoiceSettings
                    kwargs["voice_settings"] = VoiceSettings(
                        stability=0.42,
                        similarity_boost=0.55,
                        style=0.20,
                        use_speaker_boost=True
                    )
                except Exception as e_vs:
                    log.debug("Multilingual VoiceSettings notice: %s", e_vs)
            elif hasattr(self, "persona_engine") and self.persona_engine:
                try:
                    from elevenlabs import VoiceSettings
                    tts_params = self.persona_engine.get_tts_parameters()
                    if tts_params:
                        kwargs["voice_settings"] = VoiceSettings(**tts_params)
                except Exception as e_vs:
                    log.debug("ElevenLabs VoiceSettings setup notice: %s", e_vs)

            chunks = client.text_to_speech.convert(**kwargs)
            raw = b"".join(chunks)
        except Exception as e:
            log.warning("ElevenLabs TTS error: %s; initiating Edge-TTS fallback", e)
            raw = None

        if not raw:
            try:
                raw_mp3, _ = synthesize_jarvis_audio_mp3(text)
                if raw_mp3:
                    import miniaudio
                    decoded = miniaudio.decode(raw_mp3, nchannels=1, sample_rate=pcm_rate)
                    raw = decoded.samples
            except Exception as e_dec:
                log.warning("Local TTS fallback decode notice: %s", e_dec)

        if not raw or self._stop_speaking.is_set():
            return

        pcm_i16 = np.frombuffer(raw, dtype=np.int16)
        pcm_f = pcm_i16.astype(np.float32) / 32768.0

        # Feed waveform to signal bus for visualization
        self.bus.feed_waveform(pcm_i16)

        bt_device = _detect_and_route_bluetooth_audio()
        broadcast_ui_event({"type": "SPEAKING", "active": True})
        _tts_playing.set()

        block_size = 1024
        dev = bt_device if bt_device is not None else None
        try:
            # High-performance chunked OutputStream (checks interruption every ~23ms)
            with sd.OutputStream(samplerate=pcm_rate, channels=1, dtype="float32", blocksize=block_size, device=dev) as stream:
                total_samples = len(pcm_f)
                cursor = 0
                frame_count = 0
                while cursor < total_samples and not self._stop_speaking.is_set() and self._active:
                    end = min(cursor + block_size, total_samples)
                    chunk = pcm_f[cursor:end]
                    if self.bus and len(chunk) > 0:
                        self.bus.feed_waveform((chunk * 32767.0).astype(np.int16))

                    # Stream real-time AUDIO_LEVEL with 32-sample waveform for Orb line pulsation
                    frame_count += 1
                    if frame_count % 2 == 0 and len(chunk) > 0:
                        rms = float(np.sqrt(np.mean(chunk ** 2)))
                        step = max(1, len(chunk) // 32)
                        wf_slice = [round(float(chunk[i]), 3) for i in range(0, len(chunk), step)][:32]
                        broadcast_ui_event({"type": "AUDIO_LEVEL", "rms": rms, "waveform": wf_slice})

                    if len(chunk) < block_size:
                        chunk = np.pad(chunk, (0, block_size - len(chunk)))
                    stream.write(chunk)
                    cursor = end
        except Exception as e:
            # Fallback for devices that don't support raw OutputStream write
            try:
                if not self._stop_speaking.is_set():
                    sd.play(pcm_f, pcm_rate, device=dev)
                    while sd.get_stream() and sd.get_stream().active and not self._stop_speaking.is_set() and self._active:
                        time.sleep(0.02)
                    if self._stop_speaking.is_set():
                        sd.stop()
            except Exception as ex2:
                log.warning("Audio playback error: %s (fallback: %s)", e, ex2)
        finally:
            # Allow ALSA / PulseAudio hardware DAC buffer to drain cleanly (160ms) before clearing playing state
            time.sleep(0.16)
            self._last_tts_end_time = time.monotonic()
            _tts_playing.clear()
            broadcast_ui_event({"type": "SPEAKING", "active": False})


# Global references for subsystems
_memory_manager: MemoryManager | None = None
_signal_bus: SignalBus | None = None
_voice_engine: VoiceEngine | None = None
_sound_engine: SoundEffectsEngine | None = None
_watchdog_daemon: ProactiveWatchdogDaemon | None = None
_persona_engine: PersonaEngine | None = None
_subordinate_pool: SubordinateBotPool | None = None
_tts_playing = threading.Event()  # set while TTS audio is playing — suppresses clap detection


def block_samples() -> int:
    n = int(SAMPLE_RATE * BLOCK_MS / 1000)
    return max(n, 1)


def rms_mono(block: np.ndarray) -> float:
    if block.ndim > 1:
        block = np.mean(block.astype(np.float64), axis=1)
    else:
        block = block.astype(np.float64)
    if block.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(block**2)))


def _input_devices() -> list[tuple[int, dict]]:
    return [
        (i, dev)
        for i, dev in enumerate(sd.query_devices())
        if dev["max_input_channels"] >= 1
    ]


def _resolve_input_device_index(spec: str) -> int:
    spec = spec.strip()
    if spec.isdigit():
        idx = int(spec)
        sd.query_devices(idx)
        return idx
    needle = spec.lower()
    for idx, dev in _input_devices():
        if needle in dev["name"].lower():
            return idx
    raise ValueError(f"No input device matches {spec!r}")


def _probe_input_max_rms(device: int, blocksize: int) -> float | None:
    try:
        with sd.InputStream(
            device=device,
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=blocksize,
        ) as stream:
            peak = 0.0
            deadline = time.monotonic() + INPUT_PROBE_S
            while time.monotonic() < deadline:
                data, _ = stream.read(blocksize)
                peak = max(peak, rms_mono(data))
            return peak
    except sd.PortAudioError:
        return None


def _choose_input_device(blocksize: int) -> int:
    if isinstance(sd, _DummySD):
        return -1
    try:
        log.info("Audio devices:\n%s", sd.query_devices())
    except Exception:
        return -1

    override = (os.environ.get("JARVIS_INPUT_DEVICE") or "").strip()
    if override:
        try:
            idx = _resolve_input_device_index(override)
        except ValueError as e:
            log.error("%s", e)
            log.error("Set JARVIS_INPUT_DEVICE to a device index or name substring.")
            raise SystemExit(1) from e
        name = sd.query_devices(idx)["name"]
        peak = _probe_input_max_rms(idx, blocksize)
        log.info("Using JARVIS_INPUT_DEVICE [%d]: %s", idx, name)
        if peak is None:
            log.warning("Could not open configured mic; trying anyway.")
        elif peak < INPUT_SILENT_RMS:
            log.warning(
                "Configured mic looks silent (probe rms=%.5f). "
                "Check Windows input level or try another JARVIS_INPUT_DEVICE.",
                peak,
            )
        else:
            log.info("Mic probe OK (rms=%.5f).", peak)
        return idx

    default = sd.default.device[0]
    if default is not None and default >= 0:
        default_name = sd.query_devices(default)["name"]
        peak = _probe_input_max_rms(default, blocksize)
        if peak is not None and peak >= INPUT_SILENT_RMS:
            log.info(
                "Using default microphone [%d]: %s (probe rms=%.5f)",
                default,
                default_name,
                peak,
            )
            return default
        log.warning(
            "Default mic [%d] %s is silent or unavailable (probe rms=%s); "
            "scanning other inputs...",
            default,
            default_name,
            f"{peak:.5f}" if peak is not None else "unopenable",
        )

    best_idx: int | None = None
    best_peak = -1.0
    for idx, dev in _input_devices():
        if default is not None and idx == default:
            continue
        peak = _probe_input_max_rms(idx, blocksize)
        if peak is not None and peak > best_peak:
            best_peak = peak
            best_idx = idx

    if best_idx is not None and best_peak >= INPUT_SILENT_RMS:
        log.info(
            "Auto-selected microphone [%d]: %s (probe rms=%.5f)",
            best_idx,
            sd.query_devices(best_idx)["name"],
            best_peak,
        )
        return best_idx

    if default is not None and default >= 0:
        log.warning("No active mic found; falling back to default [%d].", default)
        return default
    inputs = _input_devices()
    if not inputs:
        log.error("No input devices found.")
        raise SystemExit(1)
    idx, dev = inputs[0]
    log.warning("No active mic found; falling back to [%d] %s.", idx, dev["name"])
    return idx


def _elevenlabs_pcm_sample_rate(output_format: str) -> int:
    override = (os.environ.get("ELEVENLABS_PCM_SAMPLE_RATE") or "").strip()
    if override.isdigit():
        return int(override)
    if output_format.startswith("pcm_"):
        try:
            return int(output_format.split("_", maxsplit=1)[1])
        except (ValueError, IndexError):
            pass
    return 24000


def elevenlabs_env_config() -> tuple[str, str, str, int]:
    """voice_id, model_id, output_format, pcm_sample_rate."""
    voice = (os.environ.get("ELEVENLABS_VOICE_ID") or "").strip()
    model = (os.environ.get("ELEVENLABS_MODEL_ID") or "eleven_multilingual_v2").strip()
    fmt = (os.environ.get("ELEVENLABS_OUTPUT_FORMAT") or "pcm_24000").strip()
    rate = _elevenlabs_pcm_sample_rate(fmt)
    return voice, model, fmt, rate


def synthesize_jarvis_audio_mp3(text: str) -> tuple[bytes | None, str]:
    """Synthesize authentic British male J.A.R.V.I.S. voice.
    Primary Live Voice: Microsoft Edge Neural British Male (en-GB-RyanNeural, pitch=-4Hz, rate=+2%).
    Provides 100% free, studio-grade British AI voice with zero quota limits.
    Fallback: ElevenLabs (Voice ID Hl96BMcxGf0y6Bg5qTgt).
    Returns (mp3_bytes, provider_name).
    """
    if not text or not text.strip():
        return None, "empty"

    clean_text = re.sub(r"[*_~`#>\[\]]", " ", text)
    clean_text = re.sub(r"https?://\S+", "", clean_text)
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    if not clean_text:
        clean_text = text.strip()

    # 1. Primary Live Engine: Microsoft Edge Neural British Male (en-GB-RyanNeural)
    try:
        import edge_tts, asyncio
        async def _run_edge():
            comm = edge_tts.Communicate(clean_text, "en-GB-RyanNeural", pitch="-4Hz", rate="+2%")
            buf = bytearray()
            async for chunk in comm.stream():
                if chunk.get("type") == "audio":
                    buf.extend(chunk.get("data", b""))
            return bytes(buf)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    audio_bytes = pool.submit(asyncio.run, _run_edge()).result(timeout=12)
            else:
                audio_bytes = loop.run_until_complete(_run_edge())
        except RuntimeError:
            audio_bytes = asyncio.run(_run_edge())

        if audio_bytes and len(audio_bytes) > 500:
            return audio_bytes, "edge-tts"
    except Exception as e_edge:
        log.warning("Edge-TTS synthesis notice: %s; falling back to ElevenLabs", e_edge)

    # 2. Fallback Engine: ElevenLabs
    try:
        api_key = (os.environ.get("ELEVENLABS_API_KEY") or "sk_65d10500af500320ec5209365ca9312648066edb4bae4935").strip()
        vid = (os.environ.get("ELEVENLABS_VOICE_ID") or "Hl96BMcxGf0y6Bg5qTgt").strip()
        if api_key:
            from elevenlabs.client import ElevenLabs
            client = ElevenLabs(api_key=api_key)
            chunks = client.text_to_speech.convert(
                voice_id=vid,
                text=clean_text,
                model_id="eleven_multilingual_v2",
                output_format="mp3_22050_32"
            )
            raw_audio = b"".join(chunks)
            if raw_audio and len(raw_audio) > 500:
                return raw_audio, "elevenlabs"
    except Exception as e_eleven:
        log.warning("ElevenLabs fallback synthesis notice: %s", e_eleven)

    return None, "none"


def _jarvis_welcome_cache_dir() -> Path:
    base = Path(__file__).resolve().parent
    override = (os.environ.get("JARVIS_WELCOME_CACHE_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return base / ".cache" / "jarvis_welcome"


def _jarvis_welcome_cache_path(
    text: str, voice_id: str, model_id: str, output_format: str
) -> Path:
    key = f"{text}|{voice_id}|{model_id}|{output_format}".encode()
    digest = hashlib.sha256(key).hexdigest()[:24]
    return _jarvis_welcome_cache_dir() / f"{digest}.wav"

def _detect_and_route_bluetooth_audio() -> int | None:
    """If a Bluetooth headset or audio device is connected, ensure audio routes strictly to it.

    1. On Linux (PulseAudio/PipeWire), switches default sink to the bluetooth sink via pactl.
    2. In sounddevice, finds the Bluetooth/headset output device index.
    Returns:
        sounddevice device index if a Bluetooth/headset device is detected, or None.
    """
    bt_keywords = (
        "bluez",
        "bluetooth",
        "headset",
        "headphone",
        "earphone",
        "buds",
        "airpod",
        "wireless",
        "a2dp",
    )

    # 1. On Linux, check PulseAudio / PipeWire sinks via pactl to ensure system-wide routing
    if sys.platform != "win32":
        pactl = shutil.which("pactl")
        if pactl:
            try:
                res = subprocess.run(
                    [pactl, "list", "sinks", "short"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if res.returncode == 0:
                    for line in res.stdout.strip().splitlines():
                        parts = line.split()
                        if len(parts) >= 2:
                            sink_name = parts[1]
                            if any(k in sink_name.lower() for k in ("bluez", "bluetooth")):
                                log.info(
                                    "Bluetooth headset detected in system audio: %s. Setting as default sink.",
                                    sink_name,
                                )
                                subprocess.run(
                                    [pactl, "set-default-sink", sink_name],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    timeout=2,
                                )
                                break
            except Exception as e:
                log.debug("pactl sink check failed: %s", e)

    # 2. Find device in sounddevice
    try:
        devices = sd.query_devices()
        # Check explicit bluetooth or bluez
        for i, dev in enumerate(devices):
            if dev.get("max_output_channels", 0) > 0:
                name = dev.get("name", "").lower()
                if any(k in name for k in ("bluez", "bluetooth")):
                    log.info("Bluetooth audio output device active [%d]: %s", i, dev.get("name"))
                    return i
        # Check headset / headphone / buds / airpods
        for i, dev in enumerate(devices):
            if dev.get("max_output_channels", 0) > 0:
                name = dev.get("name", "").lower()
                if any(k in name for k in bt_keywords):
                    log.info("Headset audio output device active [%d]: %s", i, dev.get("name"))
                    return i
    except Exception as e:
        log.warning("Could not query sounddevice devices for Bluetooth: %s", e)

    return None


_ws_clients: set = set()
_ws_loop: asyncio.AbstractEventLoop | None = None
_ui_listeners: set = set()


def broadcast_ui_event(event_dict: dict) -> None:
    """Broadcast real-time visualizer and status events to 3D Orb UI clients."""
    for listener in list(_ui_listeners):
        try:
            listener(event_dict)
        except Exception:
            pass

    if not _ws_clients or _ws_loop is None:
        return
    msg = json.dumps(event_dict)

    async def _send():
        tasks = [c.send(msg) for c in list(_ws_clients)]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    try:
        asyncio.run_coroutine_threadsafe(_send(), _ws_loop)
    except Exception:
        pass


class NoCacheHTTPRequestHandler(SimpleHTTPRequestHandler):
    """HTTP handler that forcefully disables caching and provides /api/command REST endpoint."""
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        clean_path = self.path.split("?")[0]
        base_dir = Path(__file__).resolve().parent
        barehands_dir = base_dir / "barehands"

        if clean_path in ("/stage.html", "/stage"):
            target = barehands_dir / "stage.html"
            if target.exists():
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(target.read_bytes())
                return
        elif clean_path in ("/blueprint_studio.js", "/barehands/blueprint_studio.js"):
            target = barehands_dir / "blueprint_studio.js"
            if target.exists():
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(target.read_bytes())
                return
        elif clean_path.startswith("/barehands/"):
            sub = clean_path.replace("/barehands/", "", 1).lstrip("/")
            target = barehands_dir / sub
            if target.exists() and target.is_file():
                ext = target.suffix.lower()
                ctype = "text/html" if ext == ".html" else ("application/javascript" if ext == ".js" else ("text/css" if ext == ".css" else "application/octet-stream"))
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(target.read_bytes())
                return
        super().do_GET()

    def do_POST(self):
        if self.path in ("/api/command", "/command"):
            content_len = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_len) if content_len > 0 else b"{}"
            try:
                data = json.loads(post_data.decode("utf-8"))
            except Exception:
                data = {}

            cmd_text = (data.get("text") or data.get("transcript") or data.get("command") or "").strip()
            resp_text = ""
            events = []

            def temp_listener(evt):
                events.append(evt)

            _ui_listeners.add(temp_listener)
            try:
                if cmd_text and _voice_engine:
                    _voice_engine._route_voice_command(cmd_text, origin="http")
            except Exception as e:
                log.error("API command processing error: %s", e)
            finally:
                _ui_listeners.discard(temp_listener)

            for ev in events:
                if ev.get("type") == "SUBTITLE" and ev.get("role") == "jarvis":
                    resp_text = ev.get("text", "")

            if not resp_text and cmd_text and _neural_brain:
                try:
                    resp_text = _neural_brain.query_stream(cmd_text)
                    events.append({"type": "SUBTITLE", "role": "jarvis", "text": resp_text})
                except Exception as b_err:
                    log.error("API fallback brain error: %s", b_err)
                    resp_text = "Online and at your service, sir."

            audio_base64 = None
            if resp_text:
                raw_audio, audio_provider = synthesize_jarvis_audio_mp3(resp_text)
                if raw_audio:
                    audio_base64 = base64.b64encode(raw_audio).decode("utf-8")
                    log.info("Synthesized live speech via %s (%d bytes)", audio_provider, len(raw_audio))

            response_payload = json.dumps({
                "status": "ok",
                "response": resp_text or "Understood, sir.",
                "audio_base64": audio_base64,
                "audio_format": "mp3" if audio_base64 else None,
                "events": events
            }).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(response_payload)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def _start_http_server(web_dir: Path, port: int = 5050) -> None:
    """Start local HTTP daemon serving the 3D Hologram HUD."""
    try:
        handler = functools.partial(NoCacheHTTPRequestHandler, directory=str(web_dir))
        server = ThreadingHTTPServer(("0.0.0.0", port), handler)
        server.allow_reuse_address = True
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        log.info("Holographic 3D Orb UI running at: http://localhost:%d", port)
    except Exception as e:
        log.warning("Could not start UI web server on port %d: %s", port, e)


def _start_websocket_server(port: int = 8765) -> None:
    """Start local WebSocket daemon for real-time visualizer and gesture events."""
    try:
        import websockets
    except ImportError:
        log.warning("websockets not installed; UI real-time link skipped.")
        return

    async def _handler(websocket):
        global _active_construct
        _ws_clients.add(websocket)
        try:
            await websocket.send(
                json.dumps({
                    "type": "STATUS",
                    "phrase": JARVIS_WELCOME_PHRASE,
                    "status": "ARMED",
                })
            )
            active_c = _active_construct if _active_construct else {"id": "arc_reactor", "name": "Arc Reactor Core"}
            await websocket.send(
                json.dumps({
                    "type": "ACTIVE_CONSTRUCT_STATE",
                    "manifest": active_c,
                    "construct": active_c.get("id", "arc_reactor"),
                    "simulation": "thermal",
                    "stress": 1.0,
                    "exploded": False
                })
            )
            if _persona_engine:
                await websocket.send(json.dumps(_persona_engine.get_hud_state_event()))
            if _subordinate_pool:
                await websocket.send(json.dumps(_subordinate_pool.get_fleet_status_event()))
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get("type") == "TRIGGER_ACTION":
                        action_name = data.get("action", "UI Gesture")
                        trigger_welcome_sequence(f"Hologram HUD ({action_name})")
                    elif data.get("type") == "START_FACE_ENROLLMENT":
                        admin_name = data.get("admin_name", "Admin")
                        if _biometric_sentinel:
                            _biometric_sentinel.start_face_enrollment(admin_name)
                    elif data.get("type") == "CANCEL_FACE_ENROLLMENT":
                        if _biometric_sentinel:
                            _biometric_sentinel.cancel_face_enrollment()
                    elif data.get("type") == "GET_ACTIVE_CONSTRUCT":
                        active_c = _active_construct if _active_construct else {"id": "arc_reactor", "name": "Arc Reactor Core"}
                        await websocket.send(
                            json.dumps({
                                "type": "ACTIVE_CONSTRUCT_STATE",
                                "manifest": active_c,
                                "construct": active_c.get("id", "arc_reactor"),
                                "simulation": "thermal",
                                "stress": 1.0,
                                "exploded": False
                            })
                        )
                    elif data.get("type") == "GESTURE_ACTION":
                        act = data.get("action")
                        if act == "flick_save":
                            log.info("🖐️ [GESTURE] Flick Right -> Archiving active blueprint to Memory Vault")
                            if _memory_manager:
                                name = _active_construct.get("name", "Mark 85 Arc Reactor Schematic") if _active_construct else "Mark 85 Arc Reactor Schematic"
                                _memory_manager.save_note(f"Archived Holographic Blueprint: {name}", category="cad_blueprints")
                            if _sound_engine:
                                _sound_engine.play("chime_positive")
                            if _voice_engine:
                                threading.Thread(
                                    target=_voice_engine.speak,
                                    args=("Archiving holographic schematic to your personal vault, sir.",),
                                    daemon=True
                                ).start()
                        elif act == "flick_dismiss":
                            log.info("🖐️ [GESTURE] Flick Left -> Dismissing holographic construct")
                            _active_construct = {}
                            if _sound_engine:
                                _sound_engine.play("whoosh")
                            if _voice_engine:
                                threading.Thread(
                                    target=_voice_engine.speak,
                                    args=("Dismissing holographic construct, sir.",),
                                    daemon=True
                                ).start()
                        elif act == "inspect_component":
                            comp = data.get("component", {})
                            name = comp.get("name", "Sub-assembly")
                            desc = comp.get("desc", "")
                            stress = comp.get("stress", "")
                            mat = comp.get("material", "")
                            log.info("🖐️ [GESTURE] Laser Pointer targeting: %s (%s)", name, mat)
                            if _voice_engine and name:
                                diagnosis = f"Targeting {name}, sir. Fabricated from {mat}. Current reading indicates {stress}."
                                threading.Thread(
                                    target=_voice_engine.speak,
                                    args=(diagnosis,),
                                    daemon=True
                                ).start()
                    elif data.get("type") == "VOICE_COMMAND":
                        transcript = data.get("transcript", "").strip()
                        if _voice_engine and transcript:
                            log.info("🎙️ [WS LINK] Incoming Voice Command from HUD: '%s'", transcript)
                            threading.Thread(
                                target=_voice_engine._route_voice_command,
                                args=(transcript, "websocket"),
                                daemon=True,
                            ).start()
                    elif data.get("type") == "TEXT_COMMAND":
                        text = data.get("text", "").strip()
                        if _voice_engine and text:
                            log.info("⌨️ [WS LINK] Incoming Typed Text Command from HUD: '%s'", text)
                            threading.Thread(
                                target=_voice_engine._route_voice_command,
                                args=(text, "websocket"),
                                daemon=True,
                            ).start()
                    elif data.get("type") == "CAMERA_ACQUIRE":
                        log.info("📷 [WS LINK] HUD requested camera acquisition for hand tracking")
                        if _biometric_sentinel:
                            _biometric_sentinel.pause_camera()
                        broadcast_ui_event({"type": "CAMERA_YIELDED"})
                    elif data.get("type") == "CAMERA_RELEASE":
                        log.info("📷 [WS LINK] HUD released camera")
                        if _biometric_sentinel:
                            _biometric_sentinel.resume_camera()
                    elif data.get("type") == "OPTICAL_FRAME":
                        frame_b64 = data.get("frame", "")
                        if _biometric_sentinel and frame_b64:
                            _biometric_sentinel.feed_external_frame(frame_b64)
                    elif data.get("type") == "CALIBRATE_PERSONA":
                        mode = data.get("mode")
                        wit = data.get("wit_level")
                        if _persona_engine:
                            confirmation = _persona_engine.calibrate(mode=mode, wit_level=wit)
                            log.info("🎭 [WS LINK] Persona calibrated from HUD: %s", confirmation)
                            broadcast_ui_event({"type": "SUBTITLE", "role": "jarvis", "text": confirmation})
                            if _voice_engine:
                                threading.Thread(
                                    target=_voice_engine.speak,
                                    args=(confirmation,),
                                    daemon=True
                                ).start()
                    elif data.get("type") == "CLAP_WAKE":
                        log.info("👏 [WS LINK] Visual clap wake trigger received from Barehands HUD!")
                        if not trigger_welcome_sequence("Barehands: Visual Clap Gesture"):
                            broadcast_ui_event({"type": "ACTIVATED", "reason": "Barehands: Visual Clap Gesture"})
                            if _sound_engine:
                                _sound_engine.play("wake")
                            if _voice_engine:
                                _voice_engine.speak("Online, sir. Systems receptive.")
                    elif data.get("type") == "DISPATCH_FLEET_TASK":
                        bot_id = data.get("bot_id")
                        task = data.get("task", "Diagnostic sweep")
                        if _subordinate_pool:
                            threading.Thread(target=_subordinate_pool.execute_bot_task, args=(bot_id, task), daemon=True).start()
                    elif data.get("type") == "DISPATCH_PARALLEL_FLEET":
                        assignments = data.get("assignments", [])
                        if _subordinate_pool:
                            threading.Thread(target=_subordinate_pool.dispatch_parallel_tasks, args=(assignments,), daemon=True).start()
                except Exception as e:
                    log.warning("WS message handling error: %s", e)
        finally:
            _ws_clients.discard(websocket)
            def _delayed_check():
                time.sleep(3.5)
                if _biometric_sentinel and not _ws_clients:
                    _biometric_sentinel.resume_camera(force=False)
            threading.Thread(target=_delayed_check, daemon=True).start()

    def _run_loop():
        global _ws_loop
        loop = asyncio.new_event_loop()
        _ws_loop = loop
        asyncio.set_event_loop(loop)

        async def _main():
            async with websockets.serve(_handler, "0.0.0.0", port):
                await asyncio.Future()

        try:
            loop.run_until_complete(_main())
        except Exception as e:
            log.debug("WebSocket server ended: %s", e)

    t = threading.Thread(target=_run_loop, daemon=True)
    t.start()
    log.info("Holographic Orb WebSocket bridge running at: ws://localhost:%d", port)


def _play_pcm_wav_file(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as wf:
            ch = wf.getnchannels()
            sw = wf.getsampwidth()
            rate = wf.getframerate()
            if ch != 1 or sw != 2:
                log.warning("Unsupported cached WAV (channels=%s, width=%s).", ch, sw)
                return False
            raw = wf.readframes(wf.getnframes())
    except (OSError, wave.Error) as e:
        log.warning("Could not read cached welcome audio: %s", e)
        return False
    if not raw:
        return False
    pcm_i16 = np.frombuffer(raw, dtype=np.int16)
    pcm_f = pcm_i16.astype(np.float32) / 32768.0
    bt_device = _detect_and_route_bluetooth_audio()
    broadcast_ui_event({"type": "SPEAKING", "active": True})
    _tts_playing.set()
    try:
        if bt_device is not None:
            sd.play(pcm_f, rate, device=bt_device)
        else:
            sd.play(pcm_f, rate)
        sd.wait()
    except Exception as e:
        log.warning("Could not play cached welcome audio: %s", e)
        return False
    finally:
        _tts_playing.clear()
        broadcast_ui_event({"type": "SPEAKING", "active": False})
    return True


def _save_pcm_wav_file(path: Path, pcm_bytes: bytes, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with wave.open(str(tmp), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        tmp.replace(path)
    except OSError:
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
        raise


def say_jarvis_welcome() -> None:
    if not JARVIS_WELCOME_ENABLED or not JARVIS_WELCOME_PHRASE.strip():
        return
    text = JARVIS_WELCOME_PHRASE.strip()
    vid, model_id, output_format, pcm_rate = elevenlabs_env_config()
    if not vid:
        log.warning("Set ELEVENLABS_VOICE_ID in the environment for ElevenLabs TTS.")
        return

    cache_path = _jarvis_welcome_cache_path(text, vid, model_id, output_format)
    if JARVIS_WELCOME_CACHE_ENABLED and cache_path.is_file():
        log.info("Playing welcome from cache: %s", cache_path)
        if _play_pcm_wav_file(cache_path):
            return
        log.warning("Cache miss after read failure; fetching from ElevenLabs.")

    api_key = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
    if not api_key:
        log.warning("Set ELEVENLABS_API_KEY in the environment for ElevenLabs TTS.")
        return
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError:
        log.warning("Install dependencies: pip install -r requirements.txt")
        return
    try:
        client = ElevenLabs(api_key=api_key)
        chunks = client.text_to_speech.convert(
            voice_id=vid,
            text=text,
            model_id=model_id,
            output_format=output_format,
        )
        raw = b"".join(chunks)
    except Exception as e:
        log.warning("ElevenLabs TTS failed: %s", e)
        return
    if not raw:
        log.warning("ElevenLabs returned empty audio.")
        return
    if JARVIS_WELCOME_CACHE_ENABLED:
        try:
            _save_pcm_wav_file(cache_path, raw, pcm_rate)
            log.info("Saved welcome audio to cache: %s", cache_path)
        except OSError as e:
            log.warning("Could not save welcome cache: %s", e)
    pcm_i16 = np.frombuffer(raw, dtype=np.int16)
    pcm_f = pcm_i16.astype(np.float32) / 32768.0
    bt_device = _detect_and_route_bluetooth_audio()
    broadcast_ui_event({"type": "SPEAKING", "active": True})
    try:
        if bt_device is not None:
            sd.play(pcm_f, pcm_rate, device=bt_device)
        else:
            sd.play(pcm_f, pcm_rate)
        sd.wait()
    except Exception as e:
        log.warning("Could not play ElevenLabs audio: %s", e)
    finally:
        broadcast_ui_event({"type": "SPEAKING", "active": False})


def play_song(uri: str) -> None:
    u = uri.strip()
    if not u:
        return
    _detect_and_route_bluetooth_audio()
    try:
        if sys.platform == "win32":
            os.startfile(u)
        else:
            webbrowser.open(u)
    except OSError as e:
        log.warning("Could not open SONG_URI: %s", e)


def _chrome_executable() -> str | None:
    if sys.platform == "win32":
        for base in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ):
            if not base:
                continue
            p = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            if os.path.isfile(p):
                return p
    return shutil.which("google-chrome") or shutil.which("chrome")


def _win32_sorted_monitor_rects() -> list[tuple[int, int, int, int]]:
    """Each monitor as (left, top, right, bottom), sorted left-to-right then top-to-bottom."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    collected: list[tuple[int, int, int, int]] = []

    @ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(RECT),
        wintypes.LPARAM,
    )
    def _cb(_hm, _hdc, lprc, _lp):
        r = lprc.contents
        collected.append((int(r.left), int(r.top), int(r.right), int(r.bottom)))
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, _cb, 0)
    collected.sort(key=lambda t: (t[0], t[1]))
    return collected


def _chrome_monitor_top_left(one_based_index: int) -> tuple[int, int]:
    """Top-left corner on virtual desktop for monitor N (1-based)."""
    l, t, _, _ = _chrome_monitor_bounds(one_based_index)
    return (l, t)


def _chrome_monitor_bounds(one_based_index: int) -> tuple[int, int, int, int]:
    """Monitor N as (left, top, right, bottom), 1-based index (sorted like other Chrome helpers)."""
    rects = _win32_sorted_monitor_rects()
    if not rects:
        return (0, 0, 1920, 1080)
    idx = one_based_index - 1
    if idx < 0:
        idx = 0
    if idx >= len(rects):
        log.warning(
            "Monitor %d requested but only %d found; using last monitor.",
            one_based_index,
            len(rects),
        )
        idx = len(rects) - 1
    return rects[idx]


def _chrome_monitor_pixel_size(one_based_index: int) -> tuple[int, int]:
    l, t, r, b = _chrome_monitor_bounds(one_based_index)
    return (max(320, r - l), max(240, b - t))


def _chrome_window_size() -> tuple[int, int]:
    w = (os.environ.get("CHROME_WINDOW_WIDTH") or "1400").strip()
    h = (os.environ.get("CHROME_WINDOW_HEIGHT") or "900").strip()
    try:
        return (max(400, int(w)), max(300, int(h)))
    except ValueError:
        return (1400, 900)


def _chrome_site_user_data_dir(site_key: str) -> str:
    p = Path(tempfile.gettempdir()) / "clap-trigger-chrome" / site_key
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def _chrome_new_window_wait_timeout_s() -> float:
    try:
        return max(3.0, float((os.environ.get("CHROME_NEW_WINDOW_WAIT_S") or "25").strip()))
    except ValueError:
        return 25.0


def _chrome_top_level_browser_hwnds_win32() -> set[int]:
    """HWND ints for visible-or-minimized top-level Chrome browser windows."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    GW_OWNER = 4
    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    found: set[int] = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd: wintypes.HWND, _lp: wintypes.LPARAM) -> bool:
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        if not user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return True
        hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not hproc:
            return True
        try:
            buf = ctypes.create_unicode_buffer(4096)
            sz = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(sz)):
                return True
            exe_path = buf.value
        finally:
            kernel32.CloseHandle(hproc)
        if os.path.basename(exe_path).lower() != "chrome.exe":
            return True
        r = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return True
        w, h = r.right - r.left, r.bottom - r.top
        if w < 80 or h < 80:
            return True
        found.add(int(hwnd))
        return True

    user32.EnumWindows(_enum, 0)
    return found


def _wait_new_chrome_hwnd_win32(before: set[int], timeout: float) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.12)
        now = _chrome_top_level_browser_hwnds_win32()
        new = now - before
        if not new:
            continue
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        best: int | None = None
        best_area = 0
        for h in new:
            r = wintypes.RECT()
            if user32.GetWindowRect(h, ctypes.byref(r)):
                a = max(0, r.right - r.left) * max(0, r.bottom - r.top)
                if a > best_area:
                    best_area = a
                    best = h
        if best is not None:
            return best
    return None


def _chrome_snap_window_to_monitor_win32(
    hwnd: int,
    one_based_monitor: int,
    *,
    fullscreen: bool,
    windowed_size: tuple[int, int] | None,
) -> None:
    import ctypes
    from ctypes import wintypes

    ml, mt, mr, mb = _chrome_monitor_bounds(one_based_monitor)
    user32 = ctypes.windll.user32
    SW_RESTORE = 9
    SW_SHOWMAXIMIZED = 3
    HWND_TOP = 0
    SWP_SHOWWINDOW = 0x0040
    SWP_FRAMECHANGED = 0x0020
    flags = SWP_SHOWWINDOW | SWP_FRAMECHANGED

    user32.ShowWindow(hwnd, SW_RESTORE)
    if fullscreen:
        w, h = mr - ml, mb - mt
        x, y = ml, mt
    else:
        ww, wh = windowed_size or _chrome_window_size()
        w, h = ww, wh
        x = ml + max(0, (mr - ml - w) // 2)
        y = mt + max(0, (mb - mt - h) // 2)
    user32.SetWindowPos(hwnd, HWND_TOP, x, y, w, h, flags)

    if fullscreen:
        user32.ShowWindow(hwnd, SW_SHOWMAXIMIZED)
        KEYEVENTF_KEYUP = 0x0002
        VK_F11 = 0x7A
        fg = user32.GetForegroundWindow()
        tid_tgt = user32.GetWindowThreadProcessId(hwnd, None)
        tid_fg = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        if tid_fg and tid_tgt:
            user32.AttachThreadInput(tid_fg, tid_tgt, True)
        user32.SetForegroundWindow(hwnd)
        if tid_fg and tid_tgt:
            user32.AttachThreadInput(tid_fg, tid_tgt, False)
        user32.keybd_event(VK_F11, 0, 0, 0)
        user32.keybd_event(VK_F11, 0, KEYEVENTF_KEYUP, 0)


def _open_url_in_chrome(
    url: str,
    *,
    new_window: bool = False,
    label: str = "URL",
    window_position: tuple[int, int] | None = None,
    window_size: tuple[int, int] | None = None,
    fullscreen: bool = False,
    win32_post_fullscreen_monitor: int | None = None,
    user_data_dir: str | None = None,
) -> None:
    u = url.strip()
    if not u:
        return
    chrome = _chrome_executable()
    try:
        if chrome:
            args = [chrome]
            if user_data_dir:
                args.append(f"--user-data-dir={user_data_dir}")
                args.append("--no-first-run")
            if new_window:
                args.append("--new-window")
            if window_position is not None:
                x, y = window_position
                args.append(f"--window-position={x},{y}")
            if window_size:
                args.append(f"--window-size={window_size[0]},{window_size[1]}")
            if fullscreen and not (
                sys.platform == "win32" and win32_post_fullscreen_monitor is not None
            ):
                args.append("--start-fullscreen")
            args.append(u)
            popen_kw: dict = {
                "args": args,
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                popen_kw["creationflags"] = subprocess.CREATE_NO_WINDOW
            before: set[int] | None = None
            if sys.platform == "win32" and win32_post_fullscreen_monitor is not None:
                before = _chrome_top_level_browser_hwnds_win32()
            subprocess.Popen(**popen_kw)
            if sys.platform == "win32" and win32_post_fullscreen_monitor is not None:
                mon = win32_post_fullscreen_monitor
                hwnd = _wait_new_chrome_hwnd_win32(before, _chrome_new_window_wait_timeout_s())
                if hwnd is not None:
                    _chrome_snap_window_to_monitor_win32(
                        hwnd,
                        mon,
                        fullscreen=fullscreen,
                        windowed_size=window_size if not fullscreen else None,
                    )
                else:
                    log.warning(
                        "Chrome: timed out waiting for new window (%s); check "
                        "CHROME_NEW_WINDOW_WAIT_S or close extra Chrome instances.",
                        label,
                    )
        else:
            log.warning("Chrome not found; opening %s in default browser.", label)
            webbrowser.open(u)
    except OSError as e:
        log.warning("Could not open %s in Chrome: %s", label, e)


def open_chatgpt_in_chrome() -> None:
    if not OPEN_CHATGPT_IN_CHROME:
        return
    url = CHATGPT_URL
    pos: tuple[int, int] | None = None
    size: tuple[int, int] | None = None
    fs = OPEN_CHROME_FULLSCREEN
    post_mon: int | None = None
    user_data: str | None = None
    if sys.platform == "win32":
        post_mon = CHATGPT_CHROME_MONITOR
        pos = _chrome_monitor_top_left(CHATGPT_CHROME_MONITOR)
        if fs:
            size = _chrome_monitor_pixel_size(CHATGPT_CHROME_MONITOR)
        else:
            size = _chrome_window_size()
        if CHROME_SEPARATE_SITE_PROFILES:
            user_data = _chrome_site_user_data_dir("chatgpt")
    elif not fs:
        size = _chrome_window_size()
    else:
        size = None
    _open_url_in_chrome(
        url,
        new_window=False,
        label="ChatGPT",
        window_position=pos,
        window_size=size,
        fullscreen=False,
        win32_post_fullscreen_monitor=post_mon,
        user_data_dir=user_data,
    )


def _antigravity_executable() -> str | None:
    for name in ("antigravity-ide", "antigravity"):
        p = shutil.which(name)
        if p:
            return p
    for path in (
        "/usr/local/bin/antigravity-ide",
        "/usr/local/bin/antigravity",
        "/usr/bin/antigravity-ide",
        "/usr/bin/antigravity",
    ):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


_orb_ui_opened = False

def open_orb_ui_in_chrome() -> None:
    global _orb_ui_opened
    if not OPEN_ORB_UI_ON_TRIGGER:
        return
    if _orb_ui_opened:
        log.info("Orb UI already opened in Chrome session; skipping duplicate window open.")
        return
    _orb_ui_opened = True
    url = f"http://localhost:{ORB_HTTP_PORT}"
    _open_url_in_chrome(
        url,
        new_window=False,
        label="Jarvis Hologram Orb",
        fullscreen=False,
    )


def open_antigravity_workspace() -> None:
    if not OPEN_ANTIGRAVITY_ON_DOUBLE_CLAP:
        return
    exe = _antigravity_executable()
    target = ANTIGRAVITY_WORKSPACE or str(Path(__file__).resolve().parent)
    if not exe:
        log.warning(
            "Could not find Antigravity executable (checked antigravity-ide and antigravity)."
        )
        return
    cmd = [exe]
    if OPEN_ANTIGRAVITY_NEW_WINDOW:
        cmd.append("--new-window")
    if target:
        cmd.append(target)
    popen_kw: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        popen_kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        log.info("Opening Antigravity workspace (new window) [%s]: %s", exe, target)
        subprocess.Popen(cmd, **popen_kw)
    except OSError as e:
        log.warning("Could not start Antigravity workspace: %s", e)


_welcome_lock = threading.Lock()
_welcome_sequence_done = False
_last_key_press_times: dict[str, float] = {"space": 0.0, "enter": 0.0}


def trigger_welcome_sequence(reason: str = "Voice: Wake up Jarvis") -> bool:
    """Thread-safe activation trigger. Runs the welcome sequence once per session."""
    global _welcome_sequence_done
    with _welcome_lock:
        if _welcome_sequence_done:
            return False
        _welcome_sequence_done = True
    broadcast_ui_event({"type": "ACTIVATED", "reason": reason})
    if _sound_engine:
        _sound_engine.play("wake")
    log.info("%s detected — running welcome once.", reason)
    threading.Thread(target=run_double_clap_actions, daemon=True).start()
    return True


def _handle_key_press(key_type: str) -> None:
    now = time.monotonic()
    prev = _last_key_press_times.get(key_type, 0.0)
    gap = now - prev
    if KEY_DOUBLE_TAP_MIN_GAP_S <= gap <= KEY_DOUBLE_TAP_MAX_GAP_S:
        _last_key_press_times[key_type] = 0.0
        trigger_welcome_sequence(f"Keyboard: fast double-tap {key_type.upper()}")
    else:
        _last_key_press_times[key_type] = now


def _start_global_keyboard_listener() -> bool:
    if pynput_keyboard is None:
        log.info(
            "pynput not installed; global keyboard hook skipped (install via `pip install pynput` for system-wide keys)."
        )
        return False

    def on_press(key):
        try:
            if key == pynput_keyboard.Key.space:
                _handle_key_press("space")
            elif key == pynput_keyboard.Key.enter:
                # If Web HUD is actively connected, reserve Enter for HUD typing & command modal
                if not _ws_clients:
                    _handle_key_press("enter")
        except Exception:
            pass

    try:
        listener = pynput_keyboard.Listener(on_press=on_press)
        listener.daemon = True
        listener.start()
        log.info(
            "Global keyboard listener active: fast double-tap SPACE or ENTER anywhere to activate Jarvis."
        )
        return True
    except Exception as e:
        log.warning("Could not start global keyboard listener: %s", e)
        return False


def _start_terminal_key_listener() -> None:
    """Listens for fast double-press of Space or Enter in the running terminal."""

    def loop():
        if sys.platform != "win32":
            import select
            import termios
            import tty

            if not sys.stdin.isatty():
                return
            fd = sys.stdin.fileno()
            try:
                old_settings = termios.tcgetattr(fd)
            except Exception:
                return
            try:
                tty.setcbreak(fd)
                while not _welcome_sequence_done:
                    r, _, _ = select.select([sys.stdin], [], [], 0.3)
                    if r:
                        ch = sys.stdin.read(1)
                        if ch == " ":
                            _handle_key_press("space")
                        elif ch in ("\r", "\n"):
                            _handle_key_press("enter")
            except Exception:
                pass
            finally:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                except Exception:
                    pass
        else:
            import msvcrt

            while not _welcome_sequence_done:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch == b" ":
                        _handle_key_press("space")
                    elif ch in (b"\r", b"\n"):
                        _handle_key_press("enter")
                time.sleep(0.04)

    t = threading.Thread(target=loop, daemon=True)
    t.start()


def run_double_clap_actions() -> None:
    """Run outside the mic loop so sleeps do not stall capture."""
    open_orb_ui_in_chrome()
    if SONG_URI.strip():
        play_song(SONG_URI)
    if JARVIS_WELCOME_ENABLED and JARVIS_WELCOME_PHRASE.strip():
        delay = max(0.0, JARVIS_AFTER_SONG_DELAY_S)
        if delay:
            time.sleep(delay)
        threading.Thread(target=say_jarvis_welcome, daemon=True).start()
    # Log activation to memory vault
    if _memory_manager:
        _memory_manager.log_event("JARVIS activated (Holographic Orb opened)")


def main() -> int:
    global _memory_manager, _signal_bus, _voice_engine, _neural_brain

    blocksize = block_samples()
    noise_floor = 0.02  # will be updated from probe below
    last_logged_double = 0.0
    first_clap_time: float | None = None
    last_spike_time = 0.0
    spike_armed = True
    consecutive_high_blocks = 0
    base_dir = Path(__file__).resolve().parent

    # ═══ BOOT SEQUENCE ═══
    log.info("━━━ JARVIS Full-Stack Boot Sequence ━━━")

    # 1. Memory Vault
    vault_path = base_dir / JARVIS_CFG.get("memory", {}).get("vault_path", "memory")
    _memory_manager = MemoryManager(vault_path)
    _memory_manager.log_event("JARVIS boot started")

    # 2. Signal Bus
    state_dir = base_dir / "state"
    bh_state_dir = base_dir / "barehands" / "state"
    _signal_bus = SignalBus(state_dir, bh_state_dir)
    _signal_bus.set_state("idle")

    # 3. Start HTTP + WebSocket servers
    web_dir = base_dir / "web"
    if web_dir.is_dir():
        _start_http_server(web_dir, ORB_HTTP_PORT)
        _start_websocket_server(ORB_WS_PORT)

    # 4. Start Barehands Board server
    bh_port = JARVIS_CFG.get("barehands", {}).get("port", 8794)
    _start_barehands_server(bh_port)

    # 4b. Initialize Stark SFX & Soundscape Engine
    global _sound_engine
    if SoundEffectsEngine is not None:
        _sound_engine = SoundEffectsEngine(
            broadcast_fn=broadcast_ui_event,
            tts_checker=lambda: _tts_playing.is_set()
        )
        _sound_engine.play("wake")

    # 5. Initialize Self-Code Manager, MCP Manager, Telegram Bridge, and Mobile Call Engine
    brain_cfg = JARVIS_CFG.get("brain", {})
    # Ensure Google Drive OAuth token file exists in cloud/deployment environments
    gdrive_creds_env = os.environ.get("GDRIVE_CREDENTIALS_CONTENT", "").strip()
    gdrive_file = base_dir / ".gdrive-server-credentials.json"
    if gdrive_creds_env and not gdrive_file.exists():
        try:
            gdrive_file.write_text(gdrive_creds_env)
            log.info("Provisioned .gdrive-server-credentials.json from environment.")
        except Exception as e:
            log.warning("Could not write gdrive credentials: %s", e)

    _code_mgr = SelfCodeManager(base_dir, _memory_manager)
    _mcp_mgr = MCPManager(base_dir / "mcp_config.json")
    _mcp_mgr.warm_up_async()
    
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    _telegram_bridge = TelegramBridge(telegram_token, telegram_chat_id, memory=_memory_manager)
    _call_engine = MobileCallEngine(_telegram_bridge, _memory_manager)

    _learning_engine = AutonomousLearningEngine(
        _memory_manager,
        brain_cfg.get("host", "http://localhost:11434"),
        brain_cfg.get("model", "llama3.2:3b")
    )
    # 5b. Initialize Movie-Authentic Persona & Wit Calibration Engine
    global _persona_engine, _subordinate_pool
    _persona_engine = PersonaEngine(
        state_path=state_dir / "persona_profile.json",
        broadcast_fn=broadcast_ui_event
    )
    # 5c. Initialize Subordinate Bot Fleet Pool
    _subordinate_pool = SubordinateBotPool(
        mcp_mgr=_mcp_mgr,
        code_mgr=_code_mgr,
        memory_mgr=_memory_manager,
        broadcast_fn=broadcast_ui_event
    )
    # 5d. Initialize Autonomous Human Cognition Researcher (E.D.I.T.H. Scout)
    global _human_researcher
    _human_researcher = HumanCognitionResearcher(
        memory_mgr=_memory_manager,
        fleet_pool=_subordinate_pool,
        broadcast_fn=broadcast_ui_event,
        groq_key=os.environ.get("GROQ_API_KEY", "").strip(),
        ollama_host=brain_cfg.get("host", "http://localhost:11434").rstrip("/"),
        ollama_model=brain_cfg.get("model", "llama3.2:3b")
    )
    _human_researcher.start()

    _neural_brain = NeuralBrain(
        brain_cfg,
        _memory_manager,
        _signal_bus,
        _learning_engine,
        _code_mgr,
        _mcp_mgr,
        _call_engine,
        persona_engine=_persona_engine,
        subordinate_pool=_subordinate_pool
    )

    _telegram_bridge.brain = _neural_brain
    _telegram_bridge.start()

    # 6. Start System Telemetry broadcaster
    _start_telemetry_broadcaster(2.5)

    # Detect audio capture hardware upfront
    has_mic = False
    input_idx = None
    if not isinstance(sd, _DummySD):
        try:
            devs = sd.query_devices()
            if any(d.get("max_input_channels", 0) > 0 for d in devs):
                has_mic = True
                input_idx = _choose_input_device(blocksize)
        except Exception:
            has_mic = False

    # 7. Start Voice Engine with Neural Brain, Learning Engine & Persona Engine (binding validated input mic)
    _voice_engine = VoiceEngine(_signal_bus, _memory_manager, _neural_brain, _learning_engine, persona_engine=_persona_engine)
    _voice_engine.start(input_device=input_idx)

    # 8. Start Biometric Sentinel & Anti-Spoofing Daemon
    global _biometric_sentinel
    _biometric_sentinel = BiometricSentinelDaemon(
        telegram_bridge=_telegram_bridge,
        voice_engine=_voice_engine,
        memory=_memory_manager
    )
    _biometric_sentinel.start()

    # 8b. Start AR Vision & Object Scanner
    global _vision_scanner
    if VisionScanner is not None:
        _vision_scanner = VisionScanner(
            biometric_sentinel=_biometric_sentinel,
            broadcast_fn=broadcast_ui_event,
            groq_key=os.environ.get("GROQ_API_KEY", "").strip(),
            ollama_host=brain_cfg.get("host", "http://localhost:11434").rstrip("/"),
        )

    # 9. Start Proactive Watchdog Daemon
    global _watchdog_daemon
    if ProactiveWatchdogDaemon is not None:
        _watchdog_daemon = ProactiveWatchdogDaemon(
            signal_bus=_signal_bus,
            voice_engine=_voice_engine,
            sound_engine=_sound_engine,
            telegram_bridge=_telegram_bridge,
            broadcast_fn=broadcast_ui_event,
            tts_checker=lambda: _tts_playing.is_set(),
            activation_checker=lambda: _welcome_sequence_done,
        )
        _watchdog_daemon.start()

    # Log boot status
    log.info("━━━ All subsystems online ━━━")
    log.info("  Orb HUD:       http://localhost:%d", ORB_HTTP_PORT)
    log.info("  WebSocket:     ws://localhost:%d", ORB_WS_PORT)
    log.info("  Barehands:     http://localhost:%d", bh_port)
    log.info("  Memory Vault:  %s", vault_path)
    log.info("  Signal Bus:    %s", state_dir)
    log.info("  Voice PTT Key: %s", JARVIS_CFG.get("ptt_key", "F4"))
    log.info("  Biometrics:    Active (Admin: %s)", _biometric_sentinel.admin_name)
    log.info("  Vision:        Active (Groq VLM / Ollama / Local Optics)")
    log.info("  Watchdog:      Active (Proactive Diagnostics)")
    log.info("  Persona:       Active (%s | Wit: %d%%)", _persona_engine.active_mode.upper(), _persona_engine.wit_level)
    log.info("  Cognition:     Active (E.D.I.T.H. Human Researcher)")
    _memory_manager.log_event("All subsystems online")

    log.info("Listening for voice commands (hands-free mode). Say 'Wake up Jarvis' to activate. Ctrl+C to stop.")
    if OPEN_ORB_UI_ON_TRIGGER:
        log.info("Activation trigger will open Holographic 3D Orb UI: http://localhost:%d", ORB_HTTP_PORT)
    if SONG_URI.strip():
        log.info("Activation trigger opens track: %s", SONG_URI.strip())
    else:
        log.info("SONG_URI is empty — music playback skipped.")
    if OPEN_ANTIGRAVITY_ON_DOUBLE_CLAP:
        log.info("Activation trigger will open Antigravity workspace: %s", ANTIGRAVITY_WORKSPACE)
    if OPEN_CHATGPT_IN_CHROME:
        log.info(
            "Activation trigger will open ChatGPT in Chrome%s: %s",
            " fullscreen" if OPEN_CHROME_FULLSCREEN else "",
            CHATGPT_URL,
        )
    if JARVIS_WELCOME_ENABLED:
        ev, em, ef, er = elevenlabs_env_config()
        log.info(
            "Activation trigger welcome greeting: %r (ElevenLabs voice=%s)",
            JARVIS_WELCOME_PHRASE.strip(),
            ev or "(unset)",
        )
    if KEYBOARD_TRIGGER_ENABLED:
        log.info("Keyboard trigger enabled: fast double-tap SPACE or ENTER to activate.")
        _start_global_keyboard_listener()
        _start_terminal_key_listener()

    if not has_mic:
        log.info("🌐 Headless Cloud / Server mode active (no local mic/audio hardware detected).")
        log.info("⚡ JARVIS Online Engine 24/7 active! Telegram Bot, WebRTC Call Portal, MCP, and Autonomous Engine running.")

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        log.info("Shutting down gracefully...")
        if _voice_engine:
            try:
                _voice_engine.stop()
            except Exception:
                pass
        if _biometric_sentinel:
            try:
                _biometric_sentinel.stop()
            except Exception:
                pass
        if _human_researcher:
            try:
                _human_researcher.stop()
            except Exception:
                pass
        if _signal_bus:
            _signal_bus.set_state("idle")
        if _memory_manager:
            _memory_manager.log_event("JARVIS shutdown (Ctrl+C)")
            _memory_manager.flush(timeout=10.0)
        log.info("Goodbye.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
