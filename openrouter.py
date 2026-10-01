"""
OpenRouter free-model pool for J.A.R.V.I.S.

Wraps OpenRouter's OpenAI-compatible chat endpoint with a pool of *free*
models (ids ending ':free') and the policy to use them:

  * purpose-based ordering  — 'default' chat prefers fast+strong models,
    'fast' puts the small ones first, 'code' leads with coding models;
  * per-model health        — rate limits (429), quota/token exhaustion
    (402 / daily limits), retired models, and transient server errors each
    get an appropriate cooldown instead of breaking the whole assistant;
  * automatic self-switching — when the acting model is out of tokens,
    rate-limited, or dead, the next healthy model takes over immediately;
    tool-unsupported models are retried once without tools and remembered;
  * stickiness              — the last model that answered well is tried
    first next time (subject to cooldown), so JARVIS 'learns' its pool.

Configuration:
  OPENROUTER_API_KEY   (env)  — required; without it the pool is disabled.
  jarvis.json brain.openrouter_models (optional) — replace the default order.

No key is ever written into this file or the repo — only into .env.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Iterable

log = logging.getLogger("Jarvis.OpenRouter")

# NOTE: the API lives on the main domain (api.openrouter.ai does NOT resolve).
API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Verified against https://openrouter.ai/api/v1/models (2026-09-30): all ids
# below end in ':free' and cost 0. Order is the default purpose order — fast,
# strong, long-context first; tiny models last as availability backstops.
DEFAULT_MODELS: tuple[str, ...] = (
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "qwen/qwen3.8-27b:free",
    "google/gemma-4-31b-it:free",
    "thinkingmachines/inkling:free",
    "poolside/laguna-s-2.1:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "thinkingmachines/inkling-small:free",
    "inclusionai/ling-3.0-flash-sante:free",
    "poolside/laguna-xs-2.1:free",
    "liquid/lfm-2.5-2.6b:free",
)

# Per-purpose leaders; the rest keep DEFAULT_MODELS order behind them.
_PURPOSE_PRIORITY: dict[str, tuple[str, ...]] = {
    "fast": (
        "inclusionai/ling-3.0-flash-sante:free",
        "liquid/lfm-2.5-2.6b:free",
        "poolside/laguna-xs-2.1:free",
        "nvidia/nemotron-3.5-lightning:free",
    ),
    "code": (
        "cohere/north-mini-code:free",
        "poolside/laguna-s-2.1:free",
        "poolside/laguna-xs-2.1:free",
    ),
}

# Cooldown policy per failure class (seconds).
_COOLDOWN = {
    "rate": 60.0,            # 429 per-minute rate limit -> brief pause
    "quota": 6 * 3600.0,     # 402 / daily token limits -> long pause
    "dead": 24 * 3600.0,     # model retired / not found
    "bad_request": 3600.0,   # our payload rejected repeatedly
    "server": 120.0,         # 5xx from the provider
}
_MAX_TOKENS_DEFAULT = 500


class OpenRouterPoolError(RuntimeError):
    """All candidate models were unavailable for this request."""


def _classify_error(code: int, body: str) -> str:
    """Map an HTTP failure to a cooldown class (see _COOLDOWN) or a
    request-local class: 'tools' (retry without tools) or 'context' (switch
    model for this request only — a bigger context window may still work)."""
    b = (body or "").lower()
    if code == 402 or "insufficient" in b or "credit" in b:
        return "quota"
    if code == 429:
        if any(k in b for k in ("daily", "usage limit", "token limit", "quota", "tokens")):
            return "quota"
        return "rate"
    if code in (400, 404, 409, 410, 422):
        if "reasoning" in b and ("unsupported" in b or "not supported" in b
                                 or "unknown" in b or "invalid" in b):
            return "reasoning"
        if "tool" in b and ("unsupported" in b or "not supported" in b or "not allow" in b or "unknown" in b):
            return "tools"
        if ("context" in b or "too long" in b or "too many tokens" in b
                or ("maximum" in b and "token" in b) or "max_tokens" in b
                or "prompt is too large" in b):
            return "context"
        if "model" in b and any(k in b for k in ("not found", "unavailable", "retired", "no endpoints")):
            return "dead"
        return "bad_request"
    if code >= 500:
        return "server"
    return "server"


class OpenRouterPool:
    """Health-aware pool over OpenRouter free models with automatic failover."""

    def __init__(self, api_key: str | None = None, models: Iterable[str] | None = None,
                 timeout: float = 25.0, sender: Callable | None = None):
        self.api_key = (api_key if api_key is not None
                        else os.environ.get("OPENROUTER_API_KEY", "")).strip()
        base = tuple(str(m).strip() for m in (models or DEFAULT_MODELS) if str(m).strip())
        self.models: tuple[str, ...] = base
        self.timeout = timeout
        # Injectable transport for offline tests: fn(payload, headers, timeout)
        # -> dict (parsed JSON body); raises urllib.error.HTTPError/URLError.
        self._send = sender or self._http_send
        self._lock = threading.RLock()
        self._health: dict[str, dict] = {}
        self._preferred: dict[str, str] = {}   # purpose -> last good model
        self._listeners: list[Callable[[dict], None]] = []
        self.usage: dict[str, int] = {}        # model -> completion tokens seen

    # ── configuration / observers ───────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) and bool(self.models)

    def add_listener(self, fn: Callable[[dict], None]) -> None:
        if fn not in self._listeners:
            self._listeners.append(fn)

    def _emit(self, event: dict) -> None:
        for fn in list(self._listeners):
            try:
                fn(dict(event))
            except Exception as exc:
                log.debug("OpenRouter listener notice: %s", exc)

    # ── health bookkeeping ──────────────────────────────────────────────

    def _state(self, model: str) -> dict:
        st = self._health.get(model)
        if st is None:
            st = {"failures": 0, "cooldown_until": 0.0, "reason": "",
                  "tools_ok": True, "reasoning_ok": True}
            self._health[model] = st
        return st

    def _now(self) -> float:
        return time.time()

    def cooldown_remaining(self, model: str) -> float:
        with self._lock:
            st = self._state(model)
            return max(0.0, st["cooldown_until"] - self._now())

    def _mark_success(self, model: str) -> None:
        with self._lock:
            st = self._state(model)
            st["failures"] = 0
            st["cooldown_until"] = 0.0
            st["reason"] = ""

    def _mark_failure(self, model: str, kind: str, detail: str = "") -> None:
        cooldown = 0.0
        with self._lock:
            st = self._state(model)
            if kind in ("tools", "reasoning"):
                # Optional parameter this model refuses: drop it forever (cheap,
                # no cooldown — the model itself is still perfectly usable).
                st["tools_ok" if kind == "tools" else "reasoning_ok"] = False
                return
            if kind == "context":
                # Message-size problem, not a model problem: try elsewhere,
                # but leave the model eligible for shorter requests.
                return
            st["failures"] += 1
            cooldown = _COOLDOWN.get(kind) or min(
                300.0, 15.0 * (2 ** (st["failures"] - 1)))
            st["cooldown_until"] = self._now() + cooldown
            st["reason"] = kind
        log.warning("OpenRouter: model %s cooling down %.0fs (%s) %s",
                    model, cooldown, kind,
                    f"— {detail[:120]}" if detail else "")

    def _candidates(self, purpose: str) -> list[str]:
        """Healthy models, preferred-first, purpose-ordered."""
        with self._lock:
            configured = set(self.models)
            order = [m for m in _PURPOSE_PRIORITY.get(purpose, ())
                     if m in configured]
            order += [m for m in self.models if m not in order]
            preferred = self._preferred.get(purpose)
            if preferred in order:
                order.remove(preferred)
                order.insert(0, preferred)
            now = self._now()
            healthy = []
            for m in order:
                st = self._state(m)
                if st["cooldown_until"] <= now:
                    healthy.append(m)
            return healthy

    def status(self) -> dict:
        """Snapshot for HUD/logging: who is ready, who is cooling, why."""
        with self._lock:
            now = self._now()
            return {
                "enabled": self.enabled,
                "preferred": dict(self._preferred),
                "usage_tokens": dict(self.usage),
                "models": {
                    m: {
                        "ready": self._state(m)["cooldown_until"] <= now,
                        "cooldown_remaining": round(max(0.0, self._state(m)["cooldown_until"] - now), 1),
                        "reason": self._state(m)["reason"],
                        "tools_ok": self._state(m)["tools_ok"],
                        "reasoning_ok": self._state(m)["reasoning_ok"],
                        "failures": self._state(m)["failures"],
                    }
                    for m in self.models
                },
            }

    # ── transport ───────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5050",
            "X-Title": "JARVIS",
            "User-Agent": "JARVIS/3.0 (Stark Core)",
        }

    @staticmethod
    def _http_send(payload: dict, headers: dict, timeout: float) -> dict:
        req = urllib.request.Request(
            API_URL, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def _error_parts(self, exc: Exception) -> tuple[int, str]:
        """(http_status, body) from an urllib error; (0, str) otherwise."""
        if isinstance(exc, urllib.error.HTTPError):
            try:
                body = exc.read().decode(errors="ignore")
            except Exception:
                body = ""
            return int(exc.code), body
        if isinstance(exc, urllib.error.URLError):
            return 0, str(getattr(exc, "reason", exc))
        return 0, str(exc)

    def _one_model(self, model: str, messages: list, tools, temperature: float,
                   max_tokens: int, tool_executor, on_status,
                   timeout: float | None = None) -> tuple:
        """Try one model. Returns (True, content, '') or (False, kind, detail).

        Handles the OpenAI tool-calling loop locally; a 'tools' or 'reasoning'
        failure means the model rejected that optional parameter (the caller
        retries it without it, and the pool remembers for next time)."""
        with self._lock:
            st = self._state(model)
            state_tools = st["tools_ok"]
            state_reasoning = st["reasoning_ok"]
        send_tools = tools if (tools and state_tools) else None
        convo = [dict(m) for m in messages]
        detail = ""
        for _round in range(3):
            payload = {
                "model": model,
                "messages": convo,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if send_tools:
                payload["tools"] = send_tools
                payload["tool_choice"] = "auto"
            if state_reasoning:
                # Ask reasoning models to keep their chain-of-thought out of the
                # content, so JARVIS never speaks "Here's a thinking process:".
                payload["reasoning"] = {"exclude": True}
            try:
                data = self._send(payload, self._headers(),
                                  timeout or self.timeout)
            except Exception as exc:
                status, body = self._error_parts(exc)
                kind = _classify_error(status, body) if status else "server"
                return False, kind, (body or str(exc))[:300]
            msg = ((data.get("choices") or [{}])[0]).get("message", {})
            usage = data.get("usage") or {}
            if usage:
                with self._lock:
                    self.usage[model] = self.usage.get(model, 0) + int(
                        usage.get("completion_tokens") or 0)
            tool_calls = msg.get("tool_calls")
            if tool_calls and tool_executor:
                convo.append(msg)
                for tc in tool_calls:
                    fn = tc.get("function", {}) or {}
                    name = fn.get("name") or ""
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except Exception:
                        args = {}
                    if on_status:
                        try:
                            on_status(f"EXECUTING // {str(name).upper()}")
                        except Exception:
                            pass
                    try:
                        result = tool_executor(name, args)
                    except Exception as exc:
                        result = f"Tool error: {exc}"
                    convo.append({"role": "tool", "tool_call_id": tc.get("id", "call_1"),
                                  "content": str(result)})
                send_tools = None   # synthesis round runs tool-less
                continue
            content = (msg.get("content") or msg.get("reasoning_content") or "").strip()
            if content:
                return True, content, ""
            # Nothing usable (e.g. finish_reason=length — out of tokens for
            # this request): switch models now, but don't punish the model.
            return False, "context", "empty content"
        return False, "context", detail

    def query(self, messages: list, tools=None, purpose: str = "default",
              temperature: float = 0.6, max_tokens: int = _MAX_TOKENS_DEFAULT,
              tool_executor=None, on_status=None, timeout: float | None = None,
              budget: float | None = None) -> dict:
        """Ask the pool; returns {content, model} or raises OpenRouterPoolError.

        Walks the healthy models for `purpose`; on rate limits, quota/token
        exhaustion, dead models or errors it cools that model down and switches
        immediately to the next healthy one — the caller never sees the outage.
        Context/token-fit misses ('context') skip the model for THIS request
        only, so a bigger-context free model can still answer.

        `timeout` overrides the per-attempt HTTP timeout and `budget` caps the
        whole walk (seconds) so a real-time caller (voice, Telegram) can fall
        through to the next engine tier instead of waiting on slow models.
        """
        if not self.enabled:
            raise OpenRouterPoolError("OpenRouter pool disabled (no API key or models)")
        deadline = (self._now() + budget) if budget else None

        def _out_of_budget() -> bool:
            return deadline is not None and self._now() >= deadline

        attempted: list[str] = []
        last_kind = last_detail = ""
        for model in self._candidates(purpose):
            if _out_of_budget():
                last_kind = last_kind or "budget"
                last_detail = f"budget {budget:.0f}s exceeded"
                break
            if on_status:
                try:
                    on_status(f"NEURAL // {model.split('/')[-1][:28].upper()}")
                except Exception:
                    pass
            ok, content_or_kind, detail = self._one_model(
                model, messages, tools, temperature, max_tokens,
                tool_executor, on_status, timeout=timeout)
            attempted.append(model)
            if ok:
                self._mark_success(model)
                with self._lock:
                    self._preferred[purpose] = model
                log.info("⚡ OpenRouter %s response via %s", purpose, model)
                return {"content": content_or_kind, "model": model}
            kind = content_or_kind
            last_kind, last_detail = kind, detail
            # Optional parameter refused (tools / reasoning): drop it for this
            # model and re-attempt it right away — the model is still healthy.
            for _retry in range(2):
                if kind not in ("tools", "reasoning"):
                    break
                self._mark_failure(model, kind)
                if _out_of_budget():
                    break
                ok2, res2, detail2 = self._one_model(
                    model, messages, tools, temperature, max_tokens,
                    tool_executor, on_status, timeout=timeout)
                if ok2:
                    self._mark_success(model)
                    with self._lock:
                        self._preferred[purpose] = model
                    log.info("⚡ OpenRouter %s response via %s (minus '%s')",
                             purpose, model, kind)
                    return {"content": res2, "model": model}
                kind, detail = res2, detail2
                last_kind, last_detail = kind, detail
            self._mark_failure(model, kind, detail)
            nxt = next((c for c in self._candidates(purpose)
                        if c not in attempted), "")
            self._emit({"type": "MODEL_SWITCH", "away": model, "reason": kind,
                        "detail": (detail or "")[:160], "next": nxt})
        raise OpenRouterPoolError(
            f"OpenRouter pool exhausted for purpose '{purpose}' after "
            f"{len(attempted)} models (last: {last_kind} {last_detail[:120]})")


_pool_singleton: OpenRouterPool | None = None
_pool_lock = threading.Lock()


def get_openrouter_pool(models: Iterable[str] | None = None,
                        on_switch: Callable[[dict], None] | None = None) -> OpenRouterPool:
    """Process-wide pool: one HTTP client, one health map, one stickiness."""
    global _pool_singleton
    with _pool_lock:
        if _pool_singleton is None:
            _pool_singleton = OpenRouterPool(models=models)
        if on_switch is not None:
            _pool_singleton.add_listener(on_switch)
        return _pool_singleton



