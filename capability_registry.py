"""Autonomous capability registry for J.A.R.V.I.S.

A *capability* is a self-contained voice feature JARVIS can write for itself at
runtime. One Python module per capability, living in ``capabilities/``:

    CAPABILITY = {
        "name": "coffee_timer",
        "description": "Sets a coffee timer, e.g. 'coffee timer 5 minutes'.",
        "intents": [r"^coffee\\s+timer\\s+(?:for\\s+)?(\\d+)\\s*min"],
    }

    def handle(text, match):
        minutes = int(match.group(1)) if match.groups() else 5
        return f"Coffee timer set for {minutes} minutes, sir."

Why a separate directory rather than patching jarvis.py: a generated module that
is wrong can only break itself. The main file, its boot sequence, and every
hand-written subsystem stay untouched, and removing a capability is deleting a
file — no merge, no revert, nothing to untangle.

Every install is validated in an isolated subprocess BEFORE it is imported into
the live process, so a capability that crashes, hangs, or explodes on import can
never take JARVIS down with it.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import logging
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("jarvis")

CAPABILITY_DIRNAME = "capabilities"
MANIFEST_NAME = "manifest.json"
_VALID_NAME = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
# Wall-clock ceiling for the isolated import/dry-run. A capability that blocks
# forever is a failure, not a hang.
VALIDATION_TIMEOUT_S = 8.0
# Defensive ceiling on generated source size.
MAX_CAPABILITY_BYTES = 64_000


class CapabilityError(Exception):
    """Raised when a generated capability is refused. Never fatal."""


def capability_dir(root: Path | None = None) -> Path:
    base = Path(root) if root else Path(__file__).resolve().parent
    return base / CAPABILITY_DIRNAME


# ── validation ────────────────────────────────────────────────────────────

_BANNED_SUBSTRINGS = (
    "subprocess", "os.system", "shutil.rmtree", "socket.socket",
    "eval(", "exec(", "__import__", "compile(", "sys.exit",
)
_BANNED_MODULES = ("subprocess", "socket", "ctypes", "multiprocessing", "pty")


def _preflight(source: str) -> None:
    """Cheap static checks before anything is written or imported."""
    if not source or not source.strip():
        raise CapabilityError("the capability is empty")
    if len(source.encode("utf-8")) > MAX_CAPABILITY_BYTES:
        raise CapabilityError("the capability is too large to be safe")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise CapabilityError(f"Python syntax error: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            for n in [getattr(node, "names", None) and a.name for a in node.names or []] + [mod]:
                if any(n == b or n.startswith(b + ".") for b in _BANNED_MODULES):
                    raise CapabilityError(f"module '{n}' is not permitted in a capability")
    for bad in _BANNED_SUBSTRINGS:
        if bad in source:
            raise CapabilityError(f"capabilities may not use '{bad.strip('(.').strip()}'")


def _validate_contract(tree: ast.AST) -> None:
    """The module must expose CAPABILITY (with name/intents) and handle()."""
    has_capability = False
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "CAPABILITY":
                    has_capability = True
        if isinstance(node, ast.FunctionDef) and node.name == "handle":
            if not node.args.args:
                raise CapabilityError("handle() must accept the utterance text")
    if not has_capability:
        raise CapabilityError("the module does not define CAPABILITY")


def isolated_check(module_path: Path) -> tuple[bool, str]:
    """Import + contract-check the module in a SUBPROCESS so a crash cannot land here.

    This proves the module IMPORTS, declares a valid CAPABILITY, exposes a
    callable handle(), and has compilable regexes. It deliberately does NOT
    treat a raising handle() as a rejection: at this point match is synthetic,
    so a handler written against a real match (match.group(1)) would fail for
    reasons that say nothing about the capability's safety. Handler exceptions
    are guarded at the call site instead.
    """
    probe = (
        "import importlib.util,re\n"
        f"spec = importlib.util.spec_from_file_location('cap', {str(module_path)!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "c = getattr(m, 'CAPABILITY', None)\n"
        "assert isinstance(c, dict), 'CAPABILITY missing or not a dict'\n"
        "assert c.get('name'), 'CAPABILITY.name missing'\n"
        "assert c.get('intents'), 'CAPABILITY.intents missing'\n"
        "for p in c['intents']:\n"
        "    re.compile(p)\n"
        "assert callable(getattr(m, 'handle', None)), 'handle() missing'\n"
        "print('OK')\n"
    )
    try:
        out = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                             text=True, timeout=VALIDATION_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f"validation timed out after {VALIDATION_TIMEOUT_S:.0f}s"
    if out.returncode != 0:
        tail = (out.stderr or out.stdout or "").strip().splitlines()
        return False, "validation failed: " + (tail[-1] if tail else "unknown error")
    return True, "ok"


class CapabilityRegistry:
    """Loads, serves, and removes self-written voice capabilities."""

    def __init__(self, root: Path | None = None):
        self.dir = capability_dir(root)
        self._lock = threading.RLock()
        self._capabilities: dict[str, dict] = {}
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("Capability directory unavailable: %s", exc)

    # ── discovery ──
    def reload(self) -> list[dict]:
        with self._lock:
            self._capabilities.clear()
            for path in sorted(self.dir.glob("*.py")):
                if path.name.startswith(("_", ".")):
                    continue
                try:
                    self._load_file(path)
                except Exception as exc:
                    log.warning("Capability %s skipped: %s", path.name, exc)
            self._write_manifest()
            return self.describe()

    def _load_file(self, path: Path) -> None:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        _validate_contract(tree)
        spec = importlib.util.spec_from_file_location(f"jarvis_cap_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)          # caller wraps this in try/except
        meta = dict(module.CAPABILITY)
        name = str(meta.get("name") or path.stem).strip().lower()
        if not _VALID_NAME.match(name):
            raise CapabilityError(f"invalid capability name '{name}'")
        patterns = [re.compile(p, re.IGNORECASE) for p in meta["intents"]]
        self._capabilities[name] = {
            "name": name,
            "description": str(meta.get("description", "")).strip(),
            "patterns": patterns,
            "handle": module.handle,
            "path": path,
        }

    # ── serving ──
    def match(self, text: str):
        """Return (capability, match) for the first capability that claims it."""
        with self._lock:
            items = list(self._capabilities.values())
        for cap in items:
            for pat in cap["patterns"]:
                m = pat.search(text or "")
                if m:
                    return cap, m
        return None, None

    @staticmethod
    def invoke(cap: dict, text: str, match) -> str:
        """Call a capability's handler. A handler that raises must never take
        the voice loop down with it, so failures degrade to an apology."""
        try:
            return str(cap["handle"](text, match) or "").strip()
        except Exception as exc:
            name = cap.get("name", "unknown")
            log.exception("Capability '%s' raised during handling", name)
            return f"The {name.replace('_', ' ')} ran into trouble, sir — {exc}."

    def describe(self) -> list[dict]:
        with self._lock:
            return [{"name": c["name"], "description": c["description"]}
                    for c in sorted(self._capabilities.values(), key=lambda c: c["name"])]

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._capabilities)

    def __len__(self) -> int:
        with self._lock:
            return len(self._capabilities)

    # ── install / remove ──
    def install(self, name: str, source: str) -> dict:
        """Validate in isolation, write, then activate. Never raises."""
        name = str(name or "").strip().lower()
        try:
            if not _VALID_NAME.match(name):
                raise CapabilityError(f"'{name}' is not a valid capability name")
            _preflight(source)
            _validate_contract(ast.parse(source))
        except CapabilityError as exc:
            return {"ok": False, "installed": False, "error": str(exc)}

        try:
            path = self.dir / f"{name}.py"
        except Exception as exc:
            return {"ok": False, "installed": False, "error": str(exc)}
        if path.exists():
            return {"ok": False, "installed": False,
                    "error": f"a capability named '{name}' already exists"}

        # Stage to a temp file so the isolated import runs against the exact
        # bytes we intend to keep, and a failure leaves no partial module.
        staging = self.dir / f".staging_{name}_{int(time.time())}.py"
        try:
            staging.write_text(source, encoding="utf-8")
            ok, detail = isolated_check(staging)
            if not ok:
                return {"ok": False, "installed": False, "error": detail}
            shutil.move(str(staging), str(path))
        except Exception as exc:
            return {"ok": False, "installed": False, "error": f"write failed: {exc}"}
        finally:
            if staging.exists():
                try:
                    staging.unlink()
                except OSError:
                    pass

        try:
            with self._lock:
                self._load_file(path)
            self._write_manifest()
        except Exception as exc:
            try:
                path.unlink()          # never leave a half-loaded module behind
            except OSError:
                pass
            return {"ok": False, "installed": False,
                    "error": f"activation failed, rolled back: {exc}"}

        log.info("🧬 [AUTONOMY] Installed capability '%s'", name)
        return {"ok": True, "name": name, "installed": True, "path": str(path)}

    def remove(self, name: str) -> dict:
        name = str(name or "").strip().lower()
        with self._lock:
            known = name in self._capabilities
            self._capabilities.pop(name, None)
        try:
            path = self.dir / f"{name}.py"
            if not known and not path.exists():
                return {"ok": False, "error": f"no capability named '{name}'"}
            if path.exists():
                path.unlink()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        self._write_manifest()
        log.info("🧬 [AUTONOMY] Removed capability '%s'", name)
        return {"ok": True, "name": name, "removed": True}

    # ── audit ──
    def _write_manifest(self) -> None:
        try:
            payload = {"updated": datetime.now().isoformat(timespec="seconds"),
                       "capabilities": self.describe()}
            (self.dir / MANIFEST_NAME).write_text(json.dumps(payload, indent=2),
                                                  encoding="utf-8")
        except Exception as exc:
            log.debug("Capability manifest write notice: %s", exc)

