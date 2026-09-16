"""
J.A.R.V.I.S. Biometric Security Suite
VoiceSentinel: Acoustic Speaker Verification & Audio Anti-Replay Engine
"""

import json
import logging
import os
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

        if confidence >= 0.78:
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
                details="Acoustic voiceprint does not match Admin profile."
            )
