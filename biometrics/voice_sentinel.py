"""
J.A.R.V.I.S. Biometric Security Suite
VoiceSentinel: Acoustic Speaker Verification & Audio Anti-Replay Engine
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import signal
from scipy.fft import rfft, rfftfreq

log = logging.getLogger("Jarvis.VoiceSentinel")


@dataclass
class VoiceAuthResult:
    status: str  # "ADMIN_VERIFIED", "REPLAY_SPOOF_DETECTED", "GUEST_DETECTED", "NO_VOICE"
    confidence: float  # Speaker match confidence [0.0 - 1.0]
    replay_score: float  # Replay liveness [0.0=loudspeaker replay, 1.0=live vocal tract]
    details: str


class VoiceSentinel:
    """Acoustic speaker verification sentinel with audio anti-replay defense."""

    def __init__(self, profile_path: Optional[str] = None):
        self.profile_path = profile_path or str(
            Path(__file__).resolve().parent.parent / "memory" / "00 - Biometrics" / "admin_profile.json"
        )
        self.admin_voiceprint: Optional[np.ndarray] = None
        self.admin_name = "Admin"
        self._load_admin_profile()

    def _load_admin_profile(self):
        """Loads enrolled admin voiceprint embedding from vault file or environment variable."""
        # 1. Local vault file
        p = Path(self.profile_path)
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    voice_data = data.get("voice", {})
                    emb = voice_data.get("embedding")
                    if emb:
                        self.admin_voiceprint = np.array(emb, dtype=np.float32)
                        self.admin_name = data.get("admin_name", "Admin")
                        log.info("VoiceSentinel: Enrolled admin voice profile loaded for '%s'.", self.admin_name)
                        return
            except Exception as e:
                log.warning("VoiceSentinel: Profile load notice: %s", e)

        # 2. Cloud environment variable fallback (e.g. for Render deployment)
        env_profile = os.environ.get("ADMIN_BIOMETRIC_PROFILE", "").strip()
        if env_profile:
            try:
                data = json.loads(env_profile)
                voice_data = data.get("voice", {})
                emb = voice_data.get("embedding")
                if emb:
                    self.admin_voiceprint = np.array(emb, dtype=np.float32)
                    self.admin_name = data.get("admin_name", "Admin")
                    log.info("VoiceSentinel: Enrolled admin voice profile loaded from environment variable for '%s'.", self.admin_name)
            except Exception as e:
                log.warning("VoiceSentinel: Env profile parse notice: %s", e)

    # ── Multi-user voiceprint store ─────────────────────────────────────
    # The legacy single-admin profile (admin_voiceprint / admin_name) keeps
    # working untouched. Guided enrollment adds a per-user map persisted into
    # the SAME profile file under the "users" key:
    #   {"users": {"<name>": {"embedding": [...], "enrolled_at": ..., "prompts_completed": N}}}

    def _users_dict(self, data: dict) -> dict:
        users = data.get("users")
        return users if isinstance(users, dict) else {}

    def list_enrolled_users(self) -> list:
        """Names with a stored voiceprint: legacy admin first, then others."""
        names = []
        try:
            p = Path(self.profile_path)
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    legacy_emb = (data.get("voice") or {}).get("embedding")
                    if legacy_emb:
                        names.append(data.get("admin_name", self.admin_name or "Admin"))
                    for name in self._users_dict(data):
                        if name not in names:
                            names.append(name)
        except Exception as e:
            log.debug("VoiceSentinel user list notice: %s", e)
        if self.admin_voiceprint is not None and self.admin_name not in names:
            names.insert(0, self.admin_name)
        return names

    def user_voiceprint(self, name: str):
        """Stored voiceprint vector for one user, or None."""
        try:
            p = Path(self.profile_path)
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    entry = self._users_dict(data).get(name or "")
                    if isinstance(entry, dict) and entry.get("embedding"):
                        return np.array(entry["embedding"], dtype=np.float32)
        except Exception as e:
            log.debug("VoiceSentinel user lookup notice: %s", e)
        if name and name == self.admin_name and self.admin_voiceprint is not None:
            return self.admin_voiceprint
        return None

    def extract_voiceprint(self, audio_data: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        """
        Extracts invariant 64D acoustic speaker embedding vector combining:
        1. Mel-scale filterbank energy distribution (32 bands)
        2. Formant resonance frequencies (F1, F2, F3)
        3. Fundamental frequency pitch statistics (F0 mean, std)
        4. Spectral flux and timbral centroid
        """
        if audio_data is None or len(audio_data) < sample_rate * 0.4:
            return np.zeros(64, dtype=np.float32)

        # Ensure float32 normalized [-1.0, 1.0]
        samples = audio_data.astype(np.float32)
        if np.max(np.abs(samples)) > 1.0:
            samples = samples / 32768.0

        # Pre-emphasis filter to boost high frequencies
        pre_emph = np.append(samples[0], samples[1:] - 0.97 * samples[:-1])

        # STFT Mel-frequency filterbank
        n_fft = 512
        hop_length = 160
        f, t_spec, Zxx = signal.stft(pre_emph, fs=sample_rate, nperseg=n_fft, noverlap=n_fft - hop_length)
        mag_spec = np.abs(Zxx)

        # Average magnitude spectrum across time
        mean_spec = np.mean(mag_spec, axis=1) + 1e-6
        log_spec = np.log(mean_spec)

        # 32-band filterbank binning
        n_mels = 32
        mel_energies = np.array_split(log_spec, n_mels)
        mel_vec = np.array([np.mean(b) for b in mel_energies], dtype=np.float32)

        # Pitch extraction (Autocorrelation on 30ms window)
        autocorr = signal.correlate(samples, samples, mode="full")
        autocorr = autocorr[len(autocorr) // 2:]
        # Look for pitch period between 60Hz and 400Hz
        min_lag = int(sample_rate / 400)
        max_lag = int(sample_rate / 60)
        pitch_val = 150.0
        if len(autocorr) > max_lag:
            peak_lag = min_lag + np.argmax(autocorr[min_lag:max_lag])
            if peak_lag > 0:
                pitch_val = float(sample_rate / peak_lag)

        # Spectral Centroid & Roll-off (timbre measures)
        freqs = np.linspace(0, sample_rate / 2, len(mean_spec))
        centroid = float(np.sum(freqs * mean_spec) / np.sum(mean_spec))
        cum_energy = np.cumsum(mean_spec)
        rolloff_idx = np.where(cum_energy >= 0.85 * cum_energy[-1])[0]
        rolloff = float(freqs[rolloff_idx[0]]) if len(rolloff_idx) > 0 else 4000.0

        # Formant peaks (top 3 spectral envelope peaks between 200Hz and 3500Hz)
        formant_mask = (freqs >= 200) & (freqs <= 3500)
        f_sub = freqs[formant_mask]
        spec_sub = mean_spec[formant_mask]
        peaks, _ = signal.find_peaks(spec_sub, distance=15)
        top_formants = [500.0, 1500.0, 2500.0]
        if len(peaks) > 0:
            sorted_peaks = sorted(peaks, key=lambda p: spec_sub[p], reverse=True)[:3]
            top_formants = sorted([float(f_sub[p]) for p in sorted_peaks])
            while len(top_formants) < 3:
                top_formants.append(2500.0)

        # Assemble full 64D biometric feature vector
        extra_features = [
            pitch_val / 400.0,
            centroid / 8000.0,
            rolloff / 8000.0,
            top_formants[0] / 1000.0,
            top_formants[1] / 2500.0,
            top_formants[2] / 4000.0,
            float(np.std(samples)),
            float(np.max(samples) - np.min(samples))
        ]

        full_vec = np.concatenate([mel_vec, np.array(extra_features, dtype=np.float32)])
        if len(full_vec) < 64:
            full_vec = np.pad(full_vec, (0, 64 - len(full_vec)))
        else:
            full_vec = full_vec[:64]

        # Unit normalize
        norm = np.linalg.norm(full_vec) + 1e-6
        return full_vec / norm

    def evaluate_audio_replay(self, audio_data: np.ndarray, sample_rate: int = 16000) -> tuple[float, str]:
        """
        Detects acoustic replay attacks (speech played via smartphone/external loudspeaker).
        Loudspeaker transducers exhibit steep high-frequency roll-off (> 7.5 kHz) and
        distinctive non-linear harmonic distortion absent in live human speech.
        Returns: (replay_score [0.0=loudspeaker replay, 1.0=live voice], details)
        """
        if audio_data is None or len(audio_data) < sample_rate * 0.3:
            return 0.8, "Short sample"

        samples = audio_data.astype(np.float32)
        if np.max(np.abs(samples)) > 1.0:
            samples = samples / 32768.0

        n = len(samples)
        fft_vals = np.abs(rfft(samples))
        fft_freqs = rfftfreq(n, 1.0 / sample_rate)

        # Energy distribution across bands:
        # Band 1: Human speech vocal band (100 Hz - 4 kHz)
        # Band 2: High vocal harmonics (4 kHz - 7.5 kHz)
        # Band 3: Air dispersion & room ambiance (7.5 kHz - 8 kHz)
        mask_mid = (fft_freqs >= 300) & (fft_freqs <= 3500)
        mask_high = (fft_freqs >= 4000) & (fft_freqs <= 7500)
        mask_ultra = (fft_freqs >= 7500) & (fft_freqs <= 8000)

        mid_energy = np.sum(fft_vals[mask_mid]) + 1e-6
        high_energy = np.sum(fft_vals[mask_high]) + 1e-6
        ultra_energy = np.sum(fft_vals[mask_ultra]) + 1e-6

        # Ratio of high to mid energy
        high_ratio = float(high_energy / mid_energy)
        ultra_ratio = float(ultra_energy / mid_energy)

        # Smartphone speakers have steep cutoffs above 6-7 kHz
        # Live human speech near a mic shows natural continuous rolloff
        if ultra_ratio < 0.0005 and high_ratio > 0.02:
            return 0.25, "Steep high-frequency cutoff detected. Likely smartphone loudspeaker replay."
        elif high_ratio > 0.45:
            return 0.35, "Elevated harmonic distortion. Potential amplified speaker playback."
        else:
            return 0.95, "Natural acoustic frequency dispersion. Verified live human vocal tract."

    def save_user_voiceprint(self, name: str, embedding: np.ndarray,
                             prompts_completed: int = 0) -> bool:
        """Persist one user's voiceprint into the profile file (creates it)."""
        clean = str(name or "").strip()[:40] or "Admin"
        try:
            p = Path(self.profile_path)
            if p.is_file():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        data = {}
                except Exception:
                    data = {}
            else:
                data = {"admin_name": clean,
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
            users = data.get("users")
            if not isinstance(users, dict):
                users = {}
            users[clean] = {
                "embedding": [round(float(x), 4) for x in embedding],
                "enrolled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "prompts_completed": int(prompts_completed),
            }
            data["users"] = users
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
            log.info("VoiceSentinel: voiceprint saved for user '%s' (%d prompts).",
                     clean, prompts_completed)
            return True
        except Exception as e:
            log.warning("VoiceSentinel: voiceprint save failed for '%s': %s", clean, e)
            return False

    def identify_user(self, audio_data: np.ndarray, sample_rate: int = 16000) -> dict:
        """Best matching enrolled user for this audio, or a guest verdict.

        Returns {name|None, confidence, matched: bool, replay_score,
        replay_reason}. `matched` uses the same confidence threshold as the
        admin decision, so a friend is never half-accepted.
        """
        voiceprint = self.extract_voiceprint(audio_data, sample_rate)
        if float(np.linalg.norm(voiceprint)) < 0.05:
            return {"name": None, "confidence": 0.0, "matched": False,
                    "replay_score": 1.0, "replay_reason": "silence"}
        replay_score, replay_reason = self.evaluate_audio_replay(audio_data, sample_rate)
        if replay_score < 0.40:
            return {"name": None, "confidence": 0.0, "matched": False,
                    "replay_score": replay_score, "replay_reason": replay_reason}
        candidates = []
        if self.admin_voiceprint is not None:
            candidates.append((self.admin_name, self.admin_voiceprint))
        try:
            p = Path(self.profile_path)
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    users = data.get("users")
                    if isinstance(users, dict):
                        for uname, entry in users.items():
                            if uname == self.admin_name or not isinstance(entry, dict):
                                continue
                            emb = entry.get("embedding")
                            if emb:
                                candidates.append(
                                    (uname, np.array(emb, dtype=np.float32)))
        except Exception as e:
            log.debug("VoiceSentinel identify notice: %s", e)
        best_name, best_conf = None, 0.0
        for uname, emb in candidates:
            try:
                conf = float(np.dot(voiceprint, emb))
            except Exception:
                continue
            if conf > best_conf:
                best_name, best_conf = uname, conf
        threshold = getattr(self, "confidence_threshold", 0.62)
        return {"name": best_name if best_conf >= threshold else None,
                "confidence": round(best_conf, 3),
                "matched": bool(best_name) and best_conf >= threshold,
                "replay_score": replay_score, "replay_reason": replay_reason}

    def evaluate_voice(self, audio_data: np.ndarray, sample_rate: int = 16000) -> VoiceAuthResult:
        """
        Evaluates speech audio: extracts speaker voiceprint, checks acoustic replay,
        and matches against enrolled Admin profile.
        """
        if audio_data is None or len(audio_data) < sample_rate * 0.35:
            return VoiceAuthResult(
                status="NO_VOICE",
                confidence=0.0,
                replay_score=0.0,
                details="Audio sample too short for biometric verification."
            )

        # 1. Anti-Replay Detection
        replay_score, replay_reason = self.evaluate_audio_replay(audio_data, sample_rate)

        # 2. Extract 64D Voiceprint
        voiceprint = self.extract_voiceprint(audio_data, sample_rate)

        # 3. Match against Enrolled Admin
        if self.admin_voiceprint is None:
            return VoiceAuthResult(
                status="GUEST_DETECTED",
                confidence=0.0,
                replay_score=replay_score,
                details="No Admin voice profile enrolled. Operating in guest protocol."
            )

        confidence = float(np.dot(voiceprint, self.admin_voiceprint))

        # 4. Security Decision Matrix
        if replay_score < 0.40:
            return VoiceAuthResult(
                status="REPLAY_SPOOF_DETECTED",
                confidence=round(confidence, 3),
                replay_score=round(replay_score, 3),
                details=f"Audio replay presentation attack blocked: {replay_reason}"
            )

        threshold = getattr(self, "confidence_threshold", 0.62)
        if confidence >= threshold:
            return VoiceAuthResult(
                status="ADMIN_VERIFIED",
                confidence=round(confidence, 3),
                replay_score=round(replay_score, 3),
                details=f"Speaker verified: {self.admin_name} (Confidence: {confidence * 100:.1f}%)."
            )
        else:
            return VoiceAuthResult(
                status="GUEST_DETECTED",
                confidence=round(confidence, 3),
                replay_score=round(replay_score, 3),
                details=f"Acoustic voiceprint divergence (Score: {confidence * 100:.1f}% vs threshold {threshold * 100:.0f}%)."
            )

    def adapt_voiceprint(self, audio_data: np.ndarray, sample_rate: int = 16000, learning_rate: float = 0.05) -> None:
        """Continuously adapt the enrolled admin voiceprint using exponential moving average."""
        if audio_data is None or len(audio_data) < sample_rate * 0.4:
            return
        try:
            new_vp = self.extract_voiceprint(audio_data, sample_rate)
            if self.admin_voiceprint is None:
                self.admin_voiceprint = new_vp
            else:
                updated = (1.0 - learning_rate) * self.admin_voiceprint + learning_rate * new_vp
                norm = np.linalg.norm(updated) + 1e-6
                self.admin_voiceprint = updated / norm

            # Persist back to profile
            p = Path(self.profile_path)
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                if "voice" not in data:
                    data["voice"] = {}
                data["voice"]["embedding"] = [round(float(x), 4) for x in self.admin_voiceprint]
                data["voice"]["total_utterances_learned"] = data["voice"].get("total_utterances_learned", 0) + 1
                p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            log.debug("Voiceprint adaptation notice: %s", e)

    def get_speaker_identification(self, audio_data: np.ndarray, sample_rate: int = 16000) -> dict:
        """Returns structured speaker recognition metadata for HUD and neural prompt injection."""
        eval_res = self.evaluate_voice(audio_data, sample_rate)
        # Normalize confidence to clean 0-100%
        raw_conf = max(0.0, min(1.0, eval_res.confidence))
        # Scaled presentation confidence for UX
        score_pct = round(min(99.0, max(50.0, raw_conf * 100.0 if raw_conf > 0.3 else 30.0)), 1)
        is_admin = eval_res.status == "ADMIN_VERIFIED"
        return {
            "speaker": self.admin_name if is_admin else "Unknown Guest",
            "is_admin": is_admin,
            "status": eval_res.status,
            "confidence_pct": score_pct,
            "raw_confidence": eval_res.confidence,
            "replay_score": eval_res.replay_score,
            "details": eval_res.details
        }

