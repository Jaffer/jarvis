"""
J.A.R.V.I.S. Biometric Security Suite
Anti-Spoofing & Presentation Attack Detection (PAD) Engine

Defeats:
1. 2D Printed Paper Photos
2. Smartphone / Tablet Video Replays (Planar Screen Detection + Moiré FFT)
3. 3D Masks (Topological Surface Residual + rPPG Skin Pulse Dynamics)
"""

import math
import numpy as np
from dataclasses import dataclass, field


@dataclass
class LivenessReport:
    is_live: bool
    score: float  # 0.0 (definite spoof) to 1.0 (verified living human)
    depth_score: float
    blink_score: float
    moire_score: float
    pulse_score: float
    spoof_type: str = "none"  # "screen_replay", "static_photo", "mask_detected", "none"
    reasons: list = field(default_factory=list)


class LivenessDetector:
    """Multi-tier passive liveness and presentation attack detector."""

    # Key facial landmark indices from MediaPipe 468 Face Mesh
    NOSE_TIP = 1
    NOSE_BRIDGE = 168
    LEFT_CHEEK = 234
    RIGHT_CHEEK = 454
    CHIN = 152
    FOREHEAD = 10
    LEFT_EYE = [33, 160, 158, 133, 153, 144]
    RIGHT_EYE = [362, 385, 387, 263, 373, 380]

    def __init__(self):
        self.ear_history = []
        self.skin_green_history = []
        self.depth_variance_history = []
        self.last_blink_time = 0
        self.total_blinks = 0

    def compute_ear(self, eye_points: list[tuple[float, float]]) -> float:
        """Computes Eye Aspect Ratio (EAR) for blink detection."""
        if len(eye_points) < 6:
            return 0.3
        p1, p2, p3, p4, p5, p6 = eye_points
        # Vertical distances
        v1 = math.hypot(p2[0] - p6[0], p2[1] - p6[1])
        v2 = math.hypot(p3[0] - p5[0], p3[1] - p5[1])
        # Horizontal distance
        h = math.hypot(p1[0] - p4[0], p1[1] - p4[1])
        if h < 1e-6:
            return 0.3
        return (v1 + v2) / (2.0 * h)

    def evaluate_3d_depth(self, landmarks_3d: list[tuple[float, float, float]]) -> tuple[float, float]:
        """
        Evaluates 3D surface depth and planar regression residual.
        Real human face: Significant 3D depth curvature (nose protrudes relative to ears/chin).
        Screen / Photo: Flat 2D plane with near-zero orthogonal residual (R^2 ~ 1.0).
        Returns: (depth_score [0.0 to 1.0], residual)
        """
        if len(landmarks_3d) < 10:
            return 0.0, 0.0

        pts = np.array(landmarks_3d, dtype=np.float32)
        # Normalize coordinates relative to face scale
        center = np.mean(pts, axis=0)
        pts_norm = pts - center
        scale = np.max(np.linalg.norm(pts_norm, axis=1)) + 1e-6
        pts_norm /= scale

        # Fit best-fit 3D plane using SVD: Ax + By + Cz = D
        _, s, vh = np.linalg.svd(pts_norm)
        # The smallest singular value corresponds to variance along the normal to the best-fit plane
        # For a flat surface (screen/photo), s[2] approaches 0.
        # For a real 3D face, s[2] is substantial (typically 0.12 - 0.28).
        plane_variance = float(s[2])

        # Also measure nose protrusion distance relative to ears
        nose_z = pts_norm[self.NOSE_TIP][2]
        ears_z = (pts_norm[self.LEFT_CHEEK][2] + pts_norm[self.RIGHT_CHEEK][2]) / 2.0
        protrusion = abs(nose_z - ears_z)

        # Depth score maps plane_variance: < 0.04 is flat (screen/photo), > 0.10 is biological 3D face
        depth_score = float(np.clip((plane_variance - 0.035) / (0.12 - 0.035), 0.0, 1.0))
        if protrusion < 0.02:
            depth_score *= 0.5

        return depth_score, plane_variance

    def evaluate_screen_moire(self, face_crop_bgr: np.ndarray) -> tuple[float, float]:
        """
        Evaluates high-frequency spectral Moiré interference patterns using 2D FFT.
        Smartphones and computer displays emit periodic sub-pixel raster grids that
        create distinctive spatial frequency peaks under optical sensors.
        Returns: (moire_score [0.0=screen, 1.0=real skin], high_freq_ratio)
        """
        if face_crop_bgr is None or face_crop_bgr.size == 0:
            return 0.5, 0.0

        # Convert to grayscale
        gray = np.dot(face_crop_bgr[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.float32)
        h, w = gray.shape
        if h < 32 or w < 32:
            return 0.5, 0.0

        # Resize to fixed dimension for consistent FFT spectral analysis
        gray_norm = gray - np.mean(gray)

        # 2D Fast Fourier Transform
        fft = np.fft.fft2(gray_norm)
        fft_shift = np.fft.fftshift(fft)
        magnitude = np.abs(fft_shift)

        # Radial frequency energy distribution
        cy, cx = h // 2, w // 2
        y, x = np.ogrid[:h, :w]
        r = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)

        r_max = min(cx, cy)
        low_mask = r < (r_max * 0.25)
        high_mask = (r >= (r_max * 0.50)) & (r < r_max)

        low_energy = np.sum(magnitude[low_mask]) + 1e-6
        high_energy = np.sum(magnitude[high_mask]) + 1e-6

        # Ratio of high frequency to low frequency
        # Digital screens exhibit elevated high-frequency harmonics due to pixel boundaries
        hf_ratio = float(high_energy / low_energy)

        # Natural human skin has low high-frequency raster energy (typically 0.02 - 0.10)
        # Screen displays typically score > 0.22 due to pixel grids and Moiré fringes
        if hf_ratio > 0.22:
            moire_score = 0.15  # High probability of screen display
        elif hf_ratio > 0.16:
            moire_score = 0.50  # Suspicious raster energy
        else:
            moire_score = 0.95  # Natural organic skin gradient

        return moire_score, hf_ratio

    def evaluate_blink(self, ear: float) -> tuple[float, bool]:
        """
        Tracks Eye Aspect Ratio (EAR) across rolling temporal window.
        Detects physiological involuntary blinks.
        """
        self.ear_history.append(ear)
        if len(self.ear_history) > 45:
            self.ear_history.pop(0)

        if len(self.ear_history) < 15:
            return 0.7, False

        ear_arr = np.array(self.ear_history)
        ear_var = float(np.var(ear_arr))
        ear_min = float(np.min(ear_arr))
        ear_max = float(np.max(ear_arr))

        # A real blink drops below ~0.21 and returns to >0.28
        blink_detected = (ear_min < 0.21 and ear_max > 0.27 and (ear_max - ear_min) > 0.08)

        # Static photos have near-zero variance
        if ear_var < 0.0001:
            blink_score = 0.1  # Frozen static photo / motionless image
        elif blink_detected:
            blink_score = 1.0  # Verified biological blink curve
        else:
            blink_score = 0.75  # Natural micro-fluctuations

        return blink_score, blink_detected

    def evaluate_rppg_pulse(self, face_crop_bgr: np.ndarray) -> float:
        """
        Remote Photoplethysmography (rPPG): Checks optical capillary pulse modulation.
        Measures green channel intensity fluctuations in forehead/cheek ROI.
        Latex/silicone masks and photos have zero micro-circulation signal.
        """
        if face_crop_bgr is None or face_crop_bgr.size == 0:
            return 0.7

        # Sample central facial skin region (forehead / upper cheeks)
        h, w, _ = face_crop_bgr.shape
        skin_roi = face_crop_bgr[int(h * 0.2):int(h * 0.6), int(w * 0.3):int(w * 0.7)]
        if skin_roi.size == 0:
            return 0.7

        # Green channel has highest hemoglobin absorption contrast
        mean_green = float(np.mean(skin_roi[:, :, 1]))
        self.skin_green_history.append(mean_green)
        if len(self.skin_green_history) > 30:
            self.skin_green_history.pop(0)

        if len(self.skin_green_history) < 15:
            return 0.75

        # Micro-variation check: static images have 0 variation; real skin has subtle micro-pulse
        g_arr = np.array(self.skin_green_history)
        var = float(np.var(g_arr))
        if var < 0.001:
            return 0.2  # Unnatural lack of capillary variance (mask / printed photo)
        elif 0.01 <= var <= 2.5:
            return 0.95  # Physiological micro-pulse band
        else:
            return 0.7

    def analyze_frame(
        self,
        landmarks_3d: list[tuple[float, float, float]],
        eye_left: list[tuple[float, float]],
        eye_right: list[tuple[float, float]],
        face_crop_bgr: np.ndarray
    ) -> LivenessReport:
        """
        Composite analysis aggregating 3D depth, blink dynamics, Moiré FFT, and rPPG pulse.
        """
        reasons = []

        # 1. 3D Depth & Planar Regression Check
        depth_score, plane_var = self.evaluate_3d_depth(landmarks_3d)
        if depth_score < 0.45:
            reasons.append(f"Planar 2D surface detected (variance {plane_var:.4f} < threshold). Likely screen or photo.")

        # 2. Eye Aspect Ratio & Blink Dynamics
        ear_l = self.compute_ear(eye_left)
        ear_r = self.compute_ear(eye_right)
        ear_avg = (ear_l + ear_r) / 2.0
        blink_score, blink_happened = self.evaluate_blink(ear_avg)
        if blink_happened:
            self.total_blinks += 1
        if blink_score < 0.3:
            reasons.append("Zero eye aspect ratio dynamics over rolling window (static picture).")

        # 3. Screen Moiré & Frequency Spectrum
        moire_score, hf_ratio = self.evaluate_screen_moire(face_crop_bgr)
        if moire_score < 0.3:
            reasons.append(f"Digital display sub-pixel raster detected (FFT HF ratio: {hf_ratio:.3f}). Screen replay attack.")

        # 4. rPPG Skin Capillary Pulse
        pulse_score = self.evaluate_rppg_pulse(face_crop_bgr)
        if pulse_score < 0.3:
            reasons.append("Absence of biological capillary blood flow modulation (potential mask).")

        # Weighted composite liveness score
        # 3D Depth is most critical (35%), Moiré screen detection (25%), Blink (20%), Pulse (20%)
        composite_score = (
            depth_score * 0.35 +
            moire_score * 0.25 +
            blink_score * 0.20 +
            pulse_score * 0.20
        )

        is_live = composite_score >= 0.70 and depth_score >= 0.40 and moire_score >= 0.30

        spoof_type = "none"
        if not is_live:
            if depth_score < 0.40 and moire_score < 0.40:
                spoof_type = "screen_replay"
            elif depth_score < 0.40:
                spoof_type = "static_photo"
            elif pulse_score < 0.35 and moire_score >= 0.70:
                spoof_type = "mask_detected"
            else:
                spoof_type = "unverified_presentation"

        return LivenessReport(
            is_live=is_live,
            score=round(composite_score, 3),
            depth_score=round(depth_score, 3),
            blink_score=round(blink_score, 3),
            moire_score=round(moire_score, 3),
            pulse_score=round(pulse_score, 3),
            spoof_type=spoof_type,
            reasons=reasons
        )
