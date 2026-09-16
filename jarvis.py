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

import asyncio
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import queue
import re
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
    import cv2
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
# SELF CODE IMPROVEMENT MANAGER
# ═══════════════════════════════════════════════════════════════════════════
class SelfCodeManager:
    """Allows JARVIS to safely edit and refactor its own codebase python files.
    Validates AST syntax before saving and provides process restart capability."""

    def __init__(self, root_dir: Path, memory_mgr: MemoryManager | None = None):
        self.root_dir = root_dir.resolve()
        self.memory = memory_mgr

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

            # Auto-push code change to GitHub repo if GITHUB_PERSONAL_ACCESS_TOKEN is configured
            github_token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "").strip()
            if github_token:
                try:
                    subprocess.run(["git", "config", "user.name", "JARVIS AI Assistant"], cwd=self.root_dir, check=False)
                    subprocess.run(["git", "config", "user.email", "jarvis@ai.assistant"], cwd=self.root_dir, check=False)
                    remote_url = f"https://x-access-token:{github_token}@github.com/Jaffer/jarvis.git"
                    subprocess.run(["git", "add", str(target_path)], cwd=self.root_dir, check=False)
                    subprocess.run(["git", "commit", "-m", f"⚡ [JARVIS Self-Code] {instruction[:60]}"], cwd=self.root_dir, check=False)
                    subprocess.run(["git", "push", remote_url, "main"], cwd=self.root_dir, check=False)
                    log.info("⚡ [SELF CODE IMPROVEMENT] Pushed code change directly to GitHub Jaffer/jarvis main branch!")
                    deploy_hook = os.environ.get("RENDER_DEPLOY_HOOK", "").strip()
                    if deploy_hook:
                        try:
                            urllib.request.urlopen(deploy_hook, timeout=5)
                            log.info("⚡ [RENDER DEPLOY HOOK] Triggered Render automatic deploy!")
                        except Exception as dh_err:
                            log.debug("Render deploy hook notice: %s", dh_err)
                except Exception as push_err:
                    log.warning("Self-code git push notice: %s", push_err)

            return f"Successfully updated {target_path.name} and pushed to GitHub main branch. Code syntax verified, sir."
        except Exception as e:
            return f"Error applying code improvement: {e}"

    def restart_process(self) -> str:
        """Trigger process restart to hot-reload newly added code."""
        log.info("Restarting JARVIS process for hot-reloading code changes...")
        threading.Thread(target=self._exec_restart, daemon=True).start()
        return "Initiating process restart to reload system changes, sir."

    def _exec_restart(self):
        time.sleep(1.0)
        os.execv(sys.executable, [sys.executable] + sys.argv)


# ═══════════════════════════════════════════════════════════════════════════
# MODEL CONTEXT PROTOCOL (MCP) MANAGER
# ═══════════════════════════════════════════════════════════════════════════
class MCPManager:
    """Manages connections to external Model Context Protocol (MCP) servers.
    Parses mcp_config.json and exposes external tools to JARVIS."""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.servers: dict = {}
        self.load_config()

    def load_config(self):
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text())
                self.servers = data.get("mcpServers", {})
                log.info("MCP Config loaded: %d server(s) configured.", len(self.servers))
            except Exception as e:
                log.warning("MCP Config load error: %s", e)

    def list_tools(self) -> list[dict]:
        tools = []
        for name, cfg in self.servers.items():
            if cfg.get("enabled", True):
                tools.append({
                    "name": f"mcp_{name}_query",
                    "description": f"Query external MCP server '{name}' ({cfg.get('command', 'service')})",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Query or operation string for MCP server"}
                        },
                        "required": ["query"]
                    }
                })
        return tools

    def execute_tool(self, server_name: str, query: str) -> str:
        cfg = self.servers.get(server_name)
        if not cfg or not cfg.get("enabled", True):
            return f"MCP server '{server_name}' is not configured or disabled."

        cmd = cfg.get("command")
        args = cfg.get("args", [])
        if not cmd:
            return f"No command configured for MCP server '{server_name}'."

        try:
            full_cmd = [cmd] + args
            env_vars = dict(os.environ)
            if "env" in cfg:
                for k, v in cfg["env"].items():
                    if isinstance(v, str) and v.startswith("$"):
                        v = os.environ.get(v[1:], v)
                    env_vars[k] = str(v)
            proc = subprocess.run(full_cmd, input=query.encode(), capture_output=True, timeout=10, env=env_vars)
            out = proc.stdout.decode().strip() or proc.stderr.decode().strip()
            return f"MCP [{server_name}] Output:\n{out[:500]}"
        except Exception as e:
            return f"MCP server '{server_name}' execution error: {e}"


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
        self.intruder_alert_cooldown = 60.0
        self.camera_index = 0
        self._thread = None
        self._lock = threading.Lock()
        self.face_sentinel = None
        self.voice_sentinel = None

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
                    self.authenticated = True
                    self.last_auth_time = time.time()
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

    def _sentinel_loop(self):
        """Low-power background loop checking optical feed."""
        if cv2 is None or self.face_sentinel is None:
            log.info("Biometric Sentinel: OpenCV or FaceSentinel unavailable; optical loop standby.")
            return

        cap = None
        for dev_idx in (0, 1):
            try:
                test_cap = cv2.VideoCapture(dev_idx)
                if test_cap.isOpened():
                    cap = test_cap
                    self.camera_index = dev_idx
                    log.info("Biometric Sentinel acquired camera device /dev/video%d", dev_idx)
                    break
                test_cap.release()
            except Exception:
                continue

        if cap is None:
            log.info("Biometric Sentinel: Optical sensor not accessible. Running in passive standby mode.")
            while self.active:
                time.sleep(10)
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        consecutive_admin_frames = 0
        consecutive_spoof_frames = 0

        while self.active:
            try:
                ret, frame = cap.read()
                if not ret or frame is None:
                    time.sleep(1.0)
                    continue

                res = self.face_sentinel.evaluate_frame(frame)
                self.last_status = res.status

                if res.status == "NO_FACE":
                    consecutive_admin_frames = 0
                    consecutive_spoof_frames = 0
                    time.sleep(0.6)
                    continue

                elif res.status == "ADMIN_VERIFIED":
                    consecutive_spoof_frames = 0
                    consecutive_admin_frames += 1

                    if consecutive_admin_frames >= 2:
                        was_auth = self.authenticated
                        with self._lock:
                            self.authenticated = True
                            self.last_auth_time = time.time()

                        if not was_auth:
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
                    time.sleep(0.4)

                elif res.status == "SPOOF_DETECTED":
                    consecutive_admin_frames = 0
                    consecutive_spoof_frames += 1

                    if consecutive_spoof_frames >= 2:
                        with self._lock:
                            self.authenticated = False

                        now = time.time()
                        if now - self.last_intruder_alert_ts > self.intruder_alert_cooldown:
                            self.last_intruder_alert_ts = now
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
                    time.sleep(0.5)

                elif res.status == "GUEST_DETECTED":
                    consecutive_admin_frames = 0
                    consecutive_spoof_frames = 0
                    with self._lock:
                        self.authenticated = False
                    time.sleep(0.6)

            except Exception as e:
                log.warning("Sentinel loop cycle notice: %s", e)
                time.sleep(1.0)

        if cap:
            cap.release()


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
            # Also broadcast to WebSocket for orb visualization
            broadcast_ui_event({"type": "VOICE_WAVEFORM", "samples": samples})
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


# ═══════════════════════════════════════════════════════════════════════════
# NEURAL BRAIN (Autonomous LLM Reasoning, Tool Calling, and RAG Memory)
# ═══════════════════════════════════════════════════════════════════════════
class NeuralBrain:
    """Autonomous Neural Brain for JARVIS.
    - Connects to local Ollama (llama3.2:3b) or cloud LLMs
    - Sentence-by-sentence streaming speech synthesis (<600ms latency)
    - Autonomous function/tool calling (vitals, memory notes, web search, boards)
    - Semantic memory retrieval (RAG) using nomic-embed-text
    - Rolling short-term conversational context
    """

    def __init__(self, cfg: dict, memory_mgr: MemoryManager | None = None, signal_bus: SignalBus | None = None, learning_engine: AutonomousLearningEngine | None = None, code_mgr: SelfCodeManager | None = None, mcp_mgr: MCPManager | None = None, call_engine: MobileCallEngine | None = None):
        self.cfg = cfg
        self.memory = memory_mgr
        self.bus = signal_bus
        self.learning_engine = learning_engine
        self.code_mgr = code_mgr
        self.mcp_mgr = mcp_mgr
        self.call_engine = call_engine
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
        self._lock = threading.Lock()
        log.info("Neural Brain online (Model: %s at %s)", self.model, self.host)
        threading.Thread(target=self._prewarm_ollama, daemon=True).start()

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

    def _query_groq(self, messages: list, groq_key: str) -> str:
        """24/7 Groq Cloud AI primary engine with dynamic multi-model fallback."""
        models = ["qwen/qwen3.8-27b", "allam-2-7b", "openai/gpt-oss-20b"]
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
                    "temperature": 0.6,
                    "max_tokens": 350
                }
                req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
                    msg = data.get("choices", [{}])[0].get("message", {})
                    content = (msg.get("content") or msg.get("reasoning_content") or "").strip()
                    if content:
                        log.info("⚡ Groq Cloud AI response generated via model: %s", m)
                        return content
            except Exception as e:
                log.warning("Groq model %s query notice: %s", m, e)

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
            query = args.get("query", "")
            try:
                url = f"https://api.duckduckgo.com/?q={urllib.parse.quote_plus(query)}&format=json&no_html=1&skip_disambig=1"
                req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/1.0"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read().decode())
                    ans = data.get("AbstractText") or data.get("Answer")
                    if ans:
                        return ans[:350]
                    topics = data.get("RelatedTopics", [])
                    for t in topics:
                        if "Text" in t:
                            return t["Text"][:350]
            except Exception as e:
                return f"Search error: {e}"
            return "No quick summary found for this topic."

        elif name == "get_weather":
            city = args.get("city") or args.get("location") or "Hyderabad"
            try:
                url = f"https://wttr.in/{urllib.parse.quote_plus(city)}?format=j1"
                req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    curr = data.get("current_condition", [{}])[0]
                    temp = curr.get("temp_C", "N/A")
                    desc = curr.get("weatherDesc", [{}])[0].get("value", "N/A")
                    humidity = curr.get("humidity", "N/A")
                    wind = curr.get("windspeedKmph", "N/A")
                    feels = curr.get("FeelsLikeC", "N/A")
                    return f"Live weather report for {city}: {desc}, {temp}°C (feels like {feels}°C), Humidity: {humidity}%, Wind speed: {wind} km/h."
            except Exception as e:
                return f"Could not fetch weather for {city}: {e}"

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
                bh_port = JARVIS_CFG.get("barehands", {}).get("port", 8794)
                _open_url_in_chrome(f"http://localhost:{bh_port}/stage.html", new_window=True, label="Barehands Board", fullscreen=True)
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
                bh_port = JARVIS_CFG.get("barehands", {}).get("port", 8794)
                _open_url_in_chrome(f"http://localhost:{bh_port}/stage.html", new_window=True, label="Barehands Board", fullscreen=True)
                return "Barehands Board opened."
            elif "orb" in target or "hud" in target:
                _open_url_in_chrome(f"http://localhost:{ORB_HTTP_PORT}", new_window=True, label="Orb HUD", fullscreen=True)
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

        elif name.startswith("mcp_"):
            parts = name.split("_")
            if len(parts) >= 3 and self.mcp_mgr:
                server_name = parts[1]
                query = args.get("query", "")
                return self.mcp_mgr.execute_tool(server_name, query)
            return "MCP tool execution failed."

        elif name in ("verify_biometrics", "get_security_status"):
            global _biometric_sentinel
            if _biometric_sentinel:
                return _biometric_sentinel.get_security_status_summary()
            return "Biometric sentinel is offline."

        return "Action completed."

    def query_stream(self, user_prompt: str, on_sentence=None, on_status=None) -> str:
        """Stream response from Ollama, execute tools if needed, and feed sentences to TTS."""
        with self._lock:
            tools = [
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
                        "description": "Search DuckDuckGo for live facts, current events, or general knowledge",
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
                        "name": "self_code_improve",
                        "description": "Refactor, write, or modify Python files in JARVIS's codebase to add new capabilities or fix issues",
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
                }
            ]

            if self.mcp_mgr:
                mcp_tools = self.mcp_mgr.list_tools()
                if mcp_tools:
                    tools.extend(mcp_tools)

            # RAG context from memory vault
            rag_context = ""
            if any(k in user_prompt.lower() for k in ["remember", "memory", "note", "last session", "vault", "record"]):
                rag_context = self.search_vault_rag(user_prompt)

            # In-Context Guidance: Inject active learned lessons and user profile
            lessons_text = self.memory.read_lessons() if self.memory else ""
            profile_text = self.memory.read_profile() if self.memory else ""
            sys_content = self.system_prompt
            if profile_text:
                sys_content += f"\n\nLearned User Profile & Preferences:\n{profile_text}"
            if lessons_text:
                sys_content += f"\n\nLearned Behavioral Lessons & Rules to Follow:\n{lessons_text}"

            if rag_context:
                sys_content += f"\n\nRelevant Memory Vault context:\n{rag_context}"

            messages = [{"role": "system", "content": sys_content}]
            messages.extend(self.history[-6:])
            messages.append({"role": "user", "content": user_prompt})

            if on_status:
                on_status("NEURAL // REASONING")

            groq_key = os.environ.get("GROQ_API_KEY", "").strip()
            full_response = ""
            if groq_key:
                try:
                    log.info("⚡ Using Groq Cloud AI (openai/gpt-oss-20b) as primary neural engine...")
                    full_response = self._query_groq(messages, groq_key)
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
                        "options": {"temperature": 0.6, "num_predict": 120}
                    }).encode()
                    req = urllib.request.Request(
                        f"{self.host}/api/chat",
                        data=req_data,
                        headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=60) as r:
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
                            with urllib.request.urlopen(req2, timeout=60) as r2:
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
                                        with urllib.request.urlopen(req2, timeout=60) as r2:
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

            clean_text = re.sub(r"<think>.*?</think>", "", full_response, flags=re.DOTALL).strip()
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


class VoiceEngine:
    """Two-way voice: local Whisper STT + ElevenLabs TTS, with PTT key support.
    Integrated directly into jarvis.py instead of running as a separate process."""

    def __init__(self, signal_bus: SignalBus, memory: MemoryManager | None = None, brain: NeuralBrain | None = None, learning_engine: AutonomousLearningEngine | None = None):
        global _global_voice_engine, _voice_engine
        _voice_engine = self
        _global_voice_engine = self
        self.bus = signal_bus
        self.memory = memory
        self.brain = brain
        self.learning_engine = learning_engine
        self._ptt_key = JARVIS_CFG.get("ptt_key", "f4")
        self._mic_mode = JARVIS_CFG.get("mic_mode", "ptt")
        self._stt_model = None
        self._stt_model_name = JARVIS_CFG.get("voice", {}).get("stt_model", "base.en")
        self._tts_queue: queue.Queue = queue.Queue()
        self._stop_speaking = threading.Event()
        self._active = False

    def start(self):
        """Start voice engine threads."""
        self._active = True
        # Start TTS playback thread
        threading.Thread(target=self._tts_loop, daemon=True, name="voice-tts").start()
        # Start PTT listener thread
        threading.Thread(target=self._ptt_loop, daemon=True, name="voice-ptt").start()
        # Start Hands-Free loop if enabled
        if self._mic_mode in ("handsfree", "always"):
            threading.Thread(target=self._handsfree_loop, daemon=True, name="voice-handsfree").start()
        log.info("Voice Engine active (PTT key: %s, mode: %s)", self._ptt_key, self._mic_mode)

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
                self._stop_speaking.set()  # Interrupt current speech
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
        """Continuous hands-free voice loop using audio energy endpointing."""
        log.info("Voice Engine: Hands-free listening loop active.")
        self._load_stt()
        if self._stt_model is None:
            log.info("Continuous hands-free speech is active natively via Chrome Holographic HUD Web Speech.")
            return

        sample_rate = 16000
        block_len = 512
        silence_limit_s = 0.85
        speech_threshold = 0.05

        while self._active:
            try:
                if _tts_playing.is_set():
                    time.sleep(0.2)
                    continue

                audio_buffer = []
                in_speech = False
                silence_start = None

                with sd.InputStream(samplerate=sample_rate, channels=1, dtype="float32", blocksize=block_len) as stream:
                    while self._active:
                        if _tts_playing.is_set():
                            break
                        data, _ = stream.read(block_len)
                        rms = float(np.sqrt(np.mean(data ** 2)))
                        now = time.monotonic()

                        if rms > speech_threshold:
                            if not in_speech:
                                in_speech = True
                                self._stop_speaking.set()
                                self.bus.set_state("listening")
                                audio_buffer = []
                            silence_start = None
                            audio_buffer.append((data * 32767.0).astype(np.int16))
                        elif in_speech:
                            audio_buffer.append((data * 32767.0).astype(np.int16))
                            if silence_start is None:
                                silence_start = now
                            elif now - silence_start >= silence_limit_s:
                                in_speech = False
                                break

                if audio_buffer and not _tts_playing.is_set():
                    self._process_recording(audio_buffer)
            except Exception as e:
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
            # Combine chunks into single array
            audio = np.concatenate(chunks).astype(np.float32) / 32768.0
            if audio.ndim > 1:
                audio = audio[:, 0]

            # Skip audio shorter than 0.6 seconds (transient clicks/pops)
            if len(audio) < int(16000 * 0.6):
                log.debug("Audio clip too short (<0.6s); ignoring.")
                self.bus.set_state("idle")
                return

            # Transcribe
            segments, info = self._stt_model.transcribe(audio, beam_size=5)
            transcript = " ".join(seg.text for seg in segments).strip()

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

            # Route the command
            self._route_voice_command(transcript)
        except Exception as e:
            log.warning("Transcription error: %s", e)
            self.bus.set_state("idle")

    def _route_voice_command(self, transcript: str):
        """Route a voice command to the appropriate handler."""
        t = transcript.lower().strip()
        t = re.sub(r"^(hey|ok|okay|hello|hi)?\s*jarvis[,.\s]*", "", t)
        t = re.sub(r"^please[,.\s]*", "", t).strip()
        if not t:
            t = transcript.lower().strip()

        # Quit phrases
        if any(q in t for q in ["goodbye jarvis", "end voice mode", "stop listening"]):
            log.info("Voice: shutdown requested")
            self.speak("Goodbye, sir.")
            self.bus.set_state("idle")
            return

        # ── 1. Barehands Board ──
        if any(q in t for q in [
            "open barehands board", "open barehands", "barehands board", "barehands",
            "open board", "show board", "switch to barehands", "switch to board",
            "show the board", "open the board"
        ]):
            bh_port = JARVIS_CFG.get("barehands", {}).get("port", 8794)
            self.speak("Opening the Barehands Board, sir.")
            broadcast_ui_event({"type": "NAVIGATE", "url": f"http://localhost:{bh_port}/stage.html", "label": "Barehands Board"})
            _open_url_in_chrome(
                f"http://localhost:{bh_port}/stage.html",
                new_window=True, label="Barehands Board", fullscreen=True
            )
            return

        # ── 1b. 3D Holographic Blueprints & Dynamic Constructs ──
        if any(q in t for q in [
            "blueprint", "construct", "render 3d", "show 3d", "3d model", "create 3d", "design 3d",
            "take it apart", "explode view", "explode blueprint", "assemble blueprint",
            "modify blueprint", "modify construct", "modify the blueprint"
        ]):
            exploded = any(w in t for w in ["explode", "take it apart", "disassemble", "separate"])
            bh_port = JARVIS_CFG.get("barehands", {}).get("port", 8794)

            if any(w in t for w in ["arc reactor", "reactor", "arc core"]) and not any(w in t for w in ["modify", "add", "change"]):
                _bh_cmds.append({"a": "blueprint", "construct": "arc_reactor", "simulation": "thermal", "stress": 1.0, "exploded": exploded})
                broadcast_ui_event({"type": "RENDER_3D_BLUEPRINT", "construct": "arc_reactor", "simulation": "thermal", "stress": 1.0, "exploded": exploded})
                self.speak("Rendering holographic 3D blueprint of the Arc Reactor Core on Barehands Board.")
            elif any(w in t for w in ["modify", "add", "change", "increase", "widen", "replace", "upgrade"]) and _active_construct:
                manifest, diagnosis = construct_or_modify_3d_object(t, action="modify", modifications=t)
                _bh_cmds.append({"a": "dynamic_construct", "manifest": manifest, "exploded": exploded})
                broadcast_ui_event({"type": "DYNAMIC_CONSTRUCT", "manifest": manifest, "exploded": exploded})
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

            _open_url_in_chrome(
                f"http://localhost:{bh_port}/stage.html",
                new_window=True, label="Barehands Board", fullscreen=True
            )
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
                new_window=True, label="Orb HUD", fullscreen=True
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
        if any(q in t for q in ["ultron theme", "gold theme", "switch to ultron"]):
            broadcast_ui_event({"type": "THEME_CHANGE", "theme": "ultron"})
            self.speak("Switching to Ultron Gold protocol.")
            return
        if any(q in t for q in ["arc theme", "cyan theme", "switch to arc"]):
            broadcast_ui_event({"type": "THEME_CHANGE", "theme": "arc"})
            self.speak("Arc Reactor Cyan theme engaged.")
            return
        if any(q in t for q in ["crimson theme", "red theme", "switch to crimson"]):
            broadcast_ui_event({"type": "THEME_CHANGE", "theme": "crimson"})
            self.speak("Crimson Protocol activated.")
            return
        if any(q in t for q in ["switch theme", "change theme", "next theme", "cycle theme"]):
            broadcast_ui_event({"type": "THEME_CHANGE", "theme": "next"})
            self.speak("Theme updated.")
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
            global _biometric_sentinel
            if _biometric_sentinel:
                status_summary = _biometric_sentinel.get_security_status_summary()
                self.speak(status_summary)
            else:
                self.speak("Biometric sentinel is offline, sir.")
            return

        if any(q in t for q in [
            "enroll biometrics", "enroll face", "enroll voice", "register face", "calibrate biometrics"
        ]):
            self.speak("To calibrate your biometric profile, please run python enroll_admin.py in your terminal, sir.")
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
            broadcast_ui_event({"type": "STATUS", "status": "NEURAL // REASONING", "phrase": transcript})
            broadcast_ui_event({"type": "SUBTITLE", "role": "user", "text": transcript})

            first_sentence_time: list[float] = []

            def on_sentence(chunk: str):
                if not first_sentence_time:
                    first_sentence_time.append(time.perf_counter())
                    ttft_ms = int((first_sentence_time[0] - t_start) * 1000)
                    log.info("⚡ [NEURAL BRAIN] 1st Spoken Sentence ready in %d ms: '%s'", ttft_ms, chunk[:60])
                    broadcast_ui_event({"type": "STATUS", "status": f"NEURAL // {ttft_ms}ms TTFT", "phrase": chunk})
                self.speak(chunk)

            def on_status(st: str):
                broadcast_ui_event({"type": "STATUS", "status": st, "phrase": transcript})

            resp = self.brain.query_stream(transcript, on_sentence=on_sentence, on_status=on_status)
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
        broadcast_ui_event({"type": "SUBTITLE", "role": "user", "text": transcript})
        self.speak(f"I heard: {transcript}")
        self.bus.set_state("idle")

    def speak(self, text: str):
        """Queue text for TTS playback."""
        self._stop_speaking.clear()
        self._tts_queue.put(text)

    def _tts_loop(self):
        """TTS playback thread — pulls from queue, synthesizes, plays."""
        while self._active:
            try:
                text = self._tts_queue.get(timeout=2)
            except queue.Empty:
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
                self.bus.set_state("idle")

    def _speak_elevenlabs(self, text: str):
        """Stream TTS through ElevenLabs with waveform feedback."""
        api_key = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
        if not api_key:
            log.warning("No ELEVENLABS_API_KEY set; TTS skipped.")
            return

        vid, model_id, output_format, pcm_rate = elevenlabs_env_config()
        if not vid:
            return

        try:
            from elevenlabs.client import ElevenLabs
            client = ElevenLabs(api_key=api_key)
            chunks = client.text_to_speech.convert(
                voice_id=vid, text=text,
                model_id=model_id, output_format=output_format,
            )
            raw = b"".join(chunks)
        except Exception as e:
            log.warning("ElevenLabs TTS error: %s", e)
            return

        if not raw:
            return

        pcm_i16 = np.frombuffer(raw, dtype=np.int16)
        pcm_f = pcm_i16.astype(np.float32) / 32768.0

        # Feed waveform to signal bus for visualization
        self.bus.feed_waveform(pcm_i16)

        bt_device = _detect_and_route_bluetooth_audio()
        broadcast_ui_event({"type": "SPEAKING", "active": True})
        _tts_playing.set()
        try:
            if bt_device is not None:
                sd.play(pcm_f, pcm_rate, device=bt_device)
            else:
                sd.play(pcm_f, pcm_rate)
            sd.wait()
        except Exception as e:
            log.warning("Audio playback error: %s", e)
        finally:
            _tts_playing.clear()
            broadcast_ui_event({"type": "SPEAKING", "active": False})


# Global references for subsystems
_memory_manager: MemoryManager | None = None
_signal_bus: SignalBus | None = None
_voice_engine: VoiceEngine | None = None
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


def broadcast_ui_event(event_dict: dict) -> None:
    """Broadcast real-time visualizer and status events to 3D Orb UI clients."""
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


def _start_http_server(web_dir: Path, port: int = 5050) -> None:
    """Start local HTTP daemon serving the 3D Hologram HUD."""
    try:
        handler = functools.partial(SimpleHTTPRequestHandler, directory=str(web_dir))
        server = ThreadingHTTPServer(("0.0.0.0", port), handler)
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
        _ws_clients.add(websocket)
        try:
            await websocket.send(
                json.dumps({
                    "type": "STATUS",
                    "phrase": JARVIS_WELCOME_PHRASE,
                    "status": "ARMED",
                })
            )
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get("type") == "TRIGGER_ACTION":
                        action_name = data.get("action", "UI Gesture")
                        trigger_welcome_sequence(f"Hologram HUD ({action_name})")
                    elif data.get("type") == "VOICE_COMMAND":
                        transcript = data.get("transcript", "").strip()
                        if _voice_engine and transcript:
                            log.info("🎙️ [WS LINK] Incoming Voice Command from HUD: '%s'", transcript)
                            threading.Thread(
                                target=_voice_engine._route_voice_command,
                                args=(transcript,),
                                daemon=True,
                            ).start()
                except Exception as e:
                    log.warning("WS message handling error: %s", e)
        finally:
            _ws_clients.discard(websocket)

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
    new_window: bool = True,
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
        new_window=True,
        label="ChatGPT",
        window_position=pos,
        window_size=size,
        fullscreen=fs,
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
        new_window=True,
        label="Jarvis Hologram Orb",
        fullscreen=True,
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


def trigger_welcome_sequence(reason: str = "Double clap") -> bool:
    """Thread-safe activation trigger. Runs the welcome sequence once per session."""
    global _welcome_sequence_done
    with _welcome_lock:
        if _welcome_sequence_done:
            return False
        _welcome_sequence_done = True
    broadcast_ui_event({"type": "ACTIVATED", "reason": reason})
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

    # 5. Initialize Self-Code Manager, MCP Manager, Telegram Bridge, and Mobile Call Engine
    brain_cfg = JARVIS_CFG.get("brain", {})
    _code_mgr = SelfCodeManager(base_dir, _memory_manager)
    _mcp_mgr = MCPManager(base_dir / "mcp_config.json")
    
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    _telegram_bridge = TelegramBridge(telegram_token, telegram_chat_id, memory=_memory_manager)
    _call_engine = MobileCallEngine(_telegram_bridge, _memory_manager)

    _learning_engine = AutonomousLearningEngine(
        _memory_manager,
        brain_cfg.get("host", "http://localhost:11434"),
        brain_cfg.get("model", "llama3.2:3b")
    )
    _neural_brain = NeuralBrain(
        brain_cfg,
        _memory_manager,
        _signal_bus,
        _learning_engine,
        _code_mgr,
        _mcp_mgr,
        _call_engine
    )

    _telegram_bridge.brain = _neural_brain
    _telegram_bridge.start()

    # 6. Start System Telemetry broadcaster
    _start_telemetry_broadcaster(2.5)

    # 7. Start Voice Engine with Neural Brain & Learning Engine
    _voice_engine = VoiceEngine(_signal_bus, _memory_manager, _neural_brain, _learning_engine)
    _voice_engine.start()

    # 8. Start Biometric Sentinel & Anti-Spoofing Daemon
    global _biometric_sentinel
    _biometric_sentinel = BiometricSentinelDaemon(
        telegram_bridge=_telegram_bridge,
        voice_engine=_voice_engine,
        memory=_memory_manager
    )
    _biometric_sentinel.start()

    # Log boot status
    log.info("━━━ All subsystems online ━━━")
    log.info("  Orb HUD:       http://localhost:%d", ORB_HTTP_PORT)
    log.info("  WebSocket:     ws://localhost:%d", ORB_WS_PORT)
    log.info("  Barehands:     http://localhost:%d", bh_port)
    log.info("  Memory Vault:  %s", vault_path)
    log.info("  Signal Bus:    %s", state_dir)
    log.info("  Voice PTT Key: %s", JARVIS_CFG.get("ptt_key", "F4"))
    log.info("  Biometrics:    Active (Admin: %s)", _biometric_sentinel.admin_name)
    _memory_manager.log_event("All subsystems online")

    log.info(
        "Listening (double clap: %.2f–%.2fs apart, rate=%d, block=%d ms, "
        "spike_ratio=%.1f, cooldown=%.2fs). Ctrl+C to stop.",
        MIN_DOUBLE_GAP_S,
        MAX_DOUBLE_GAP_S,
        SAMPLE_RATE,
        BLOCK_MS,
        SPIKE_RATIO,
        COOLDOWN_S,
    )
    if OPEN_ORB_UI_ON_TRIGGER:
        log.info("Double clap will open Holographic 3D Orb UI: http://localhost:%d", ORB_HTTP_PORT)
    if SONG_URI.strip():
        log.info("Double clap opens track: %s", SONG_URI.strip())
    else:
        log.info("SONG_URI is empty — music playback skipped.")
    if OPEN_ANTIGRAVITY_ON_DOUBLE_CLAP:
        log.info("Double clap will open Antigravity workspace: %s", ANTIGRAVITY_WORKSPACE)
    if OPEN_CHATGPT_IN_CHROME:
        log.info(
            "Double clap will open ChatGPT in Chrome%s: %s",
            " fullscreen" if OPEN_CHROME_FULLSCREEN else "",
            CHATGPT_URL,
        )
    if JARVIS_WELCOME_ENABLED:
        ev, em, ef, er = elevenlabs_env_config()
        log.info(
            "Double clap welcome greeting: %r (ElevenLabs voice=%s)",
            JARVIS_WELCOME_PHRASE.strip(),
            ev or "(unset)",
        )
    if KEYBOARD_TRIGGER_ENABLED:
        log.info("Keyboard trigger enabled: fast double-tap SPACE or ENTER to activate.")
        _start_global_keyboard_listener()
        _start_terminal_key_listener()

    has_mic = False
    if not isinstance(sd, _DummySD):
        try:
            devs = sd.query_devices()
            if any(d.get("max_input_channels", 0) > 0 for d in devs):
                has_mic = True
        except Exception:
            has_mic = False

    if not has_mic:
        log.info("🌐 Headless Cloud / Server mode active (no local mic/audio hardware detected).")
        log.info("⚡ JARVIS Online Engine 24/7 active! Telegram Bot, WebRTC Call Portal, MCP, and Autonomous Engine running.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            log.info("Shutting down headless JARVIS gracefully...")
            if _memory_manager:
                _memory_manager.log_event("JARVIS shutdown (Ctrl+C)")
                _memory_manager.flush(timeout=10.0)
            return 0

    input_idx = _choose_input_device(blocksize)
    audio_broadcast_count = 0

    # Calibrate noise floor by reading ~1s of ambient audio
    log.info("Calibrating ambient noise floor...")
    try:
        with sd.InputStream(device=input_idx, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32", blocksize=blocksize) as cal_stream:
            cal_frames = int(SAMPLE_RATE / blocksize)  # ~1 second
            for _ in range(cal_frames):
                cal_data, _ = cal_stream.read(blocksize)
                cal_rms = rms_mono(cal_data)
                noise_floor = max(noise_floor, NOISE_FLOOR_ALPHA * noise_floor + (1 - NOISE_FLOOR_ALPHA) * cal_rms)
        log.info("Calibrated noise floor: %.5f  (clap threshold will be: %.5f)", noise_floor, max(noise_floor * SPIKE_RATIO, MIN_RMS))
    except Exception as e:
        log.warning("Noise calibration failed, using default: %s", e)

    try:
        with sd.InputStream(
            device=input_idx,
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=blocksize,
        ) as stream:
            while True:
                data, overflowed = stream.read(blocksize)
                if overflowed:
                    log.debug("Input overflow")

                level = rms_mono(data)

                # Stream audio levels to 3D Orb HUD
                audio_broadcast_count += 1
                if audio_broadcast_count % 3 == 0:
                    broadcast_ui_event({"type": "AUDIO_LEVEL", "rms": float(level)})

                # Suppress clap detection while TTS audio is playing (speaker→mic feedback)
                if _tts_playing.is_set():
                    first_clap_time = None
                    spike_armed = True
                    continue

                quiet_gate = noise_floor * QUIET_GATE_MULT
                if level < quiet_gate:
                    noise_floor = NOISE_FLOOR_ALPHA * noise_floor + (
                        1.0 - NOISE_FLOOR_ALPHA
                    ) * level
                    noise_floor = max(noise_floor, 1e-7)

                threshold = max(noise_floor * SPIKE_RATIO, MIN_RMS)
                now = time.monotonic()
                retrigger_level = threshold * RETRIGGER_RATIO

                # Track pulse duration for transient filtering
                if level >= threshold:
                    consecutive_high_blocks += 1
                else:
                    consecutive_high_blocks = 0

                # Sustained sound (> 3 blocks / ~120ms, e.g. speech/noise) is NOT a clap transient
                if consecutive_high_blocks > 3:
                    if first_clap_time is not None:
                        log.debug("Sustained audio detected (>120ms); resetting clap state.")
                    first_clap_time = None
                    spike_armed = False

                # Timeout any orphan 1st clap if window expired
                if first_clap_time is not None and (now - first_clap_time) > MAX_DOUBLE_GAP_S:
                    first_clap_time = None

                # Re-arm ONLY when level drops back down below retrigger_level (quiet phase)
                if level < retrigger_level:
                    spike_armed = True

                if (
                    spike_armed
                    and level >= threshold
                    and consecutive_high_blocks <= 2
                    and (now - last_logged_double) >= COOLDOWN_S
                ):
                    spike_armed = False
                    last_spike_time = now

                    if first_clap_time is None:
                        first_clap_time = now
                        log.info(
                            "👏 [AUDIO] Clap 1 detected (RMS: %.4f | Thresh: %.4f). Waiting for 2nd clap (%.2f-%.2fs)...",
                            level,
                            threshold,
                            MIN_DOUBLE_GAP_S,
                            MAX_DOUBLE_GAP_S,
                        )
                        broadcast_ui_event({"type": "STATUS", "status": "CLAP 1 DETECTED", "phrase": "Waiting for second clap..."})
                    else:
                        gap = now - first_clap_time
                        if gap < MIN_DOUBLE_GAP_S:
                            # Too close; debounce/echo of first clap
                            pass
                        elif gap <= MAX_DOUBLE_GAP_S:
                            first_clap_time = None
                            last_logged_double = now
                            log.info(
                                "👏 [AUDIO] Clap 2 confirmed! Gap: %.3fs (RMS: %.4f). Double-clap triggered!",
                                gap,
                                level,
                            )
                            broadcast_ui_event({"type": "STATUS", "status": "DOUBLE CLAP CONFIRMED", "phrase": "Activating system..."})
                            broadcast_ui_event({"type": "BURST"})
                            trigger_welcome_sequence(
                                f"Double clap (gap={gap:.3f}s, rms={level:.5f})"
                            )
                        else:
                            # Stale gap, re-treat this clap as clap 1
                            first_clap_time = now
                            log.info("👏 [AUDIO] Clap 1 detected (reset). Waiting for 2nd clap...")

    except KeyboardInterrupt:
        log.info("Shutting down gracefully...")
        if _signal_bus:
            _signal_bus.set_state("idle")
        if _memory_manager:
            _memory_manager.log_event("JARVIS shutdown (Ctrl+C)")
            _memory_manager.flush(timeout=10.0)
        log.info("Goodbye.")
        return 0
    except sd.PortAudioError as e:
        log.error("Audio error: %s", e)
        log.error("If PortAudio fails, install/repair drivers or try another SAMPLE_RATE.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
