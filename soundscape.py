"""
J.A.R.V.I.S. Sci-Fi SFX Engine & Stark Laboratory Soundscape
============================================================
Procedural mathematical DSP audio synthesis and non-blocking sound effect engine.
Generates movie-authentic Iron Man / Stark Industries acoustic cues:
- Holographic Wake Chime
- Arc Reactor Thinking / Processing Pulse
- Biometric Clearance Authorization Chirp
- Barge-In Electronic Cutoff Click
- Defensive Security Alert Tone
- 3D Holographic Blueprint Whoosh

All waveforms are mathematically synthesized at 44.1kHz via NumPy — requiring
zero external .wav/.mp3 dependencies, zero disk I/O, and zero network latency.
Includes priority gating to yield cleanly to TTS and prevent PortAudio device locks.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from typing import Callable, Dict, Optional
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None

log = logging.getLogger("JARVIS.Soundscape")


class SoundEffectsEngine:
    """Procedural Sci-Fi Sound Effects Engine with non-blocking audio dispatch."""

    SAMPLE_RATE = 44100

    def __init__(self, broadcast_fn: Optional[Callable[[dict], None]] = None, tts_checker: Optional[Callable[[], bool]] = None):
        self.broadcast_fn = broadcast_fn
        self.tts_checker = tts_checker
        self.enabled = True
        self.volume = 0.40
        self._lock = threading.Lock()
        self._cache: Dict[str, np.ndarray] = {}
        self._pregenerate_sounds()
        log.info("Stark SFX Engine initialized (Procedural DSP @ 44.1kHz).")

    def _pregenerate_sounds(self) -> None:
        """Pre-compute all procedural waveforms into memory for 0ms latency."""
        self._cache["wake"] = self._generate_wake_chime()
        self._cache["thinking"] = self._generate_thinking_pulse()
        self._cache["auth_confirmed"] = self._generate_auth_confirmed()
        self._cache["barge_in_cut"] = self._generate_barge_in_cut()
        self._cache["security_alert"] = self._generate_security_alert()
        self._cache["blueprint_whoosh"] = self._generate_blueprint_whoosh()
        log.info("Pre-computed %d procedural sci-fi sound effects.", len(self._cache))

    # ── PROCEDURAL DSP SYNTHESIZERS ───────────────────────────────────────

    def _generate_wake_chime(self) -> np.ndarray:
        """Dual-harmonic crystalline bell chime (880Hz + 1760Hz with soft exponential decay)."""
        duration = 0.45
        t = np.linspace(0, duration, int(self.SAMPLE_RATE * duration), endpoint=False)
        # Fundamental A5 (880Hz), Octave A6 (1760Hz), and resonant fifth E6 (1318.5Hz)
        tone = (
            0.55 * np.sin(2 * np.pi * 880.0 * t) +
            0.35 * np.sin(2 * np.pi * 1760.0 * t) +
            0.15 * np.sin(2 * np.pi * 1318.5 * t)
        )
        # Fast attack (6ms) + smooth exponential ring decay
        attack_len = int(self.SAMPLE_RATE * 0.006)
        envelope = np.exp(-t / 0.12)
        envelope[:attack_len] *= np.linspace(0, 1, attack_len)
        return (tone * envelope * 0.7).astype(np.float32)

    def _generate_thinking_pulse(self) -> np.ndarray:
        """Low-frequency resonant Arc Reactor pulse (130Hz -> 220Hz harmonic swell)."""
        duration = 0.50
        t = np.linspace(0, duration, int(self.SAMPLE_RATE * duration), endpoint=False)
        # Smooth frequency sweep upwards simulating neural core excitation
        freq = np.linspace(130.81, 220.0, len(t))
        phase = 2 * np.pi * np.cumsum(freq) / self.SAMPLE_RATE
        # Add rich sub-octave and warm second harmonic
        tone = 0.60 * np.sin(phase) + 0.25 * np.sin(2 * phase) + 0.15 * np.sin(0.5 * phase)
        # Swell and fade envelope
        envelope = np.sin(np.pi * (t / duration)) ** 1.5
        return (tone * envelope * 0.65).astype(np.float32)

    def _generate_auth_confirmed(self) -> np.ndarray:
        """High-tech triad security confirmation chirp (C6 -> E6 -> G6 ascending in 150ms)."""
        duration = 0.35
        sr = self.SAMPLE_RATE
        total_samples = int(sr * duration)
        out = np.zeros(total_samples, dtype=np.float32)

        notes = [
            (1046.50, 0.00, 0.11),   # C6
            (1318.51, 0.07, 0.18),   # E6
            (1567.98, 0.14, 0.34),   # G6
        ]

        for freq, start_s, end_s in notes:
            s_idx = int(start_s * sr)
            e_idx = int(end_s * sr)
            chunk_len = e_idx - s_idx
            t_chunk = np.linspace(0, end_s - start_s, chunk_len, endpoint=False)
            note_tone = 0.65 * np.sin(2 * np.pi * freq * t_chunk) + 0.35 * np.sin(2 * np.pi * (freq * 2) * t_chunk)
            # Envelope: fast 4ms attack, exponential decay
            env = np.exp(-t_chunk / 0.08)
            att_len = min(int(sr * 0.004), chunk_len)
            if att_len > 0:
                env[:att_len] *= np.linspace(0, 1, att_len)
            out[s_idx:e_idx] += (note_tone * env * 0.55).astype(np.float32)

        # Normalize to prevent any clipping
        max_val = np.max(np.abs(out))
        if max_val > 1.0:
            out /= max_val
        return out

    def _generate_barge_in_cut(self) -> np.ndarray:
        """Fast electronic circuit disconnect click (downward sweep 1400Hz -> 280Hz in 35ms)."""
        duration = 0.04
        t = np.linspace(0, duration, int(self.SAMPLE_RATE * duration), endpoint=False)
        # Exponential frequency drop
        freq = 1400.0 * (0.2 ** (t / duration))
        phase = 2 * np.pi * np.cumsum(freq) / self.SAMPLE_RATE
        tone = 0.8 * np.sin(phase) + 0.2 * np.sign(np.sin(phase))
        envelope = np.linspace(1.0, 0.0, len(t)) ** 2.0
        return (tone * envelope * 0.5).astype(np.float32)

    def _generate_security_alert(self) -> np.ndarray:
        """Stark defensive authorization warning frequency (rapid alternating dual frequency)."""
        duration = 0.40
        t = np.linspace(0, duration, int(self.SAMPLE_RATE * duration), endpoint=False)
        # Alternate between 880Hz and 660Hz every 40ms
        f1, f2 = 880.0, 659.25
        freq_mod = np.where((t * 25).astype(int) % 2 == 0, f1, f2)
        phase = 2 * np.pi * np.cumsum(freq_mod) / self.SAMPLE_RATE
        tone = 0.7 * np.sin(phase) + 0.3 * np.sin(3 * phase)
        envelope = np.ones_like(t)
        decay_start = int(len(t) * 0.8)
        envelope[decay_start:] = np.linspace(1.0, 0.0, len(t) - decay_start)
        return (tone * envelope * 0.6).astype(np.float32)

    def _generate_blueprint_whoosh(self) -> np.ndarray:
        """Swept resonant bandpass white noise simulating 3D holographic projection assembly."""
        duration = 0.50
        sr = self.SAMPLE_RATE
        num_samples = int(sr * duration)
        # White noise base
        np.random.seed(42)  # Deterministic seed
        noise = np.random.uniform(-1.0, 1.0, num_samples).astype(np.float32)

        # Simple swept resonant filter emulation using frequency-domain modulation
        t = np.linspace(0, duration, num_samples, endpoint=False)
        carrier_sweep = np.sin(2 * np.pi * (300.0 + 1200.0 * np.sin(np.pi * (t / duration))) * t)
        whoosh = noise * 0.4 + carrier_sweep * 0.6

        # Swell envelope
        envelope = (np.sin(np.pi * (t / duration))) ** 2
        return (whoosh * envelope * 0.55).astype(np.float32)

    # ── PLAYBACK & DISPATCH ───────────────────────────────────────────────

    def play(self, sfx_name: str) -> None:
        """Play a sound effect asynchronously with TTS priority lockout."""
        if not self.enabled:
            return

        # 1. Dispatch Web HUD event immediately for browser WebAudio playback
        if self.broadcast_fn:
            try:
                self.broadcast_fn({"type": "SFX_PLAY", "sfx": sfx_name})
            except Exception as e:
                log.debug("SFX broadcast notice: %s", e)

        # 2. Check if TTS is active: yield PortAudio device to speech
        if self.tts_checker and self.tts_checker():
            log.debug("SFX '%s' suppressed: TTS active.", sfx_name)
            return

        # 3. Play natively on local hardware via background thread
        if sd is None:
            return

        def _play_worker():
            with self._lock:
                # Double-check TTS before opening audio stream
                if self.tts_checker and self.tts_checker():
                    return
                waveform = self._cache.get(sfx_name)
                if waveform is None:
                    log.warning("Unknown SFX: %s", sfx_name)
                    return
                try:
                    scaled = waveform * self.volume
                    sd.play(scaled, self.SAMPLE_RATE)
                    # Non-blocking: do not call sd.wait() so we don't lock threads!
                except Exception as e:
                    log.debug("Native SFX playback notice: %s", e)

        threading.Thread(target=_play_worker, daemon=True, name=f"sfx-{sfx_name}").start()

    def set_volume(self, vol: float) -> None:
        """Adjust SFX master volume (0.0 to 1.0)."""
        self.volume = max(0.0, min(1.0, float(vol)))
        log.info("SFX volume set to %.2f", self.volume)

    def mute(self) -> None:
        """Mute all sound effects."""
        self.enabled = False
        log.info("SFX muted.")

    def unmute(self) -> None:
        """Unmute sound effects."""
        self.enabled = True
        log.info("SFX unmuted.")
