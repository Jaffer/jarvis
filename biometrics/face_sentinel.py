"""
J.A.R.V.I.S. Biometric Security Suite
FaceSentinel: Optical Face Recognition & 3D Anti-Spoofing Engine
"""

import json
import logging
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

try:
    import mediapipe as mp
except ImportError:
    mp = None

from .anti_spoofing import LivenessDetector, LivenessReport

log = logging.getLogger("Jarvis.FaceSentinel")


@dataclass
class FaceAuthResult:
    status: str  # "ADMIN_VERIFIED", "SPOOF_DETECTED", "GUEST_DETECTED", "NO_FACE"
    confidence: float  # Identity match confidence [0.0 - 1.0]
    liveness_score: float  # Liveness score [0.0 - 1.0]
    spoof_type: str  # "none", "screen_replay", "static_photo", "mask_detected"
    details: str
    frame_bgr: Optional[np.ndarray] = None


class FaceSentinel:
    """Continuous facial recognition sentinel with 3D anti-spoofing defense."""

    KEY_ANCHORS = [
        1, 10, 33, 61, 133, 152, 168, 197, 234, 263,
        291, 362, 385, 387, 454, 159, 145, 386, 374,
        0, 17, 61, 291, 57, 287, 164, 18, 200, 9, 8
    ]

    def __init__(self, profile_path: Optional[str] = None):
        self.profile_path = profile_path or str(
            Path(__file__).resolve().parent.parent / "memory" / "00 - Biometrics" / "admin_profile.json"
        )
        self.detector = LivenessDetector()
        self.task_detector = None
        self.mesh_detector = None
        self.admin_embedding: Optional[np.ndarray] = None
        self.admin_name = "Admin"
        self._load_admin_profile()
        self._init_mediapipe()

    def _init_mediapipe(self):
        """Initializes MediaPipe Face Mesh detector (supports modern Tasks API and legacy Solutions)."""
        if mp is None:
            log.warning("FaceSentinel: mediapipe library not available.")
            return

        # 1. Try modern MediaPipe FaceLandmarker Tasks API
        try:
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision

            model_dir = Path(__file__).resolve().parent / "models"
            model_dir.mkdir(parents=True, exist_ok=True)
            model_path = model_dir / "face_landmarker.task"

            if not model_path.is_file() or model_path.stat().st_size < 1000000:
                log.info("Downloading official MediaPipe FaceLandmarker model...")
                url = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
                import urllib.request
                urllib.request.urlretrieve(url, str(model_path))

            base_options = python.BaseOptions(model_asset_path=str(model_path))
            options = vision.FaceLandmarkerOptions(
                base_options=base_options,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
                num_faces=1
            )
            self.task_detector = vision.FaceLandmarker.create_from_options(options)
            log.info("FaceSentinel: MediaPipe FaceLandmarker task initialized successfully.")
            return
        except Exception as e:
            log.info("FaceSentinel: Modern FaceLandmarker task fallback notice: %s", e)

        # 2. Try legacy solutions.face_mesh
        try:
            import importlib
            sol = importlib.import_module("mediapipe.python.solutions.face_mesh")
            self.mesh_detector = sol.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5
            )
            log.info("FaceSentinel: Legacy MediaPipe 3D Face Mesh initialized.")
        except Exception as e:
            log.debug("FaceSentinel: MediaPipe legacy solutions unavailable: %s", e)

    def _load_admin_profile(self):
        """Loads enrolled admin face embedding and parameters from vault file or environment variable."""
        # 1. Local vault file
        p = Path(self.profile_path)
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    face_data = data.get("face", {})
                    emb = face_data.get("embedding")
                    if emb:
                        self.admin_embedding = np.array(emb, dtype=np.float32)
                        self.admin_name = data.get("admin_name", "Admin")
                        log.info("FaceSentinel: Enrolled admin profile loaded for '%s'.", self.admin_name)
                        return
            except Exception as e:
                log.warning("FaceSentinel: Profile load notice: %s", e)

        # 2. Cloud environment variable fallback (e.g. for Render deployment)
        env_profile = os.environ.get("ADMIN_BIOMETRIC_PROFILE", "").strip()
        if env_profile:
            try:
                data = json.loads(env_profile)
                face_data = data.get("face", {})
                emb = face_data.get("embedding")
                if emb:
                    self.admin_embedding = np.array(emb, dtype=np.float32)
                    self.admin_name = data.get("admin_name", "Admin")
                    log.info("FaceSentinel: Enrolled admin profile loaded from environment variable for '%s'.", self.admin_name)
            except Exception as e:
                log.warning("FaceSentinel: Env profile parse notice: %s", e)

    def extract_face_embedding(self, landmarks_3d: list[tuple[float, float, float]]) -> np.ndarray:
        """
        Extracts invariant 64D facial geometric embedding vector based on 3D topological ratios
        and canonical anchor relations.
        """
        pts = np.array(landmarks_3d, dtype=np.float32)
        # Center on nose tip (index 1)
        nose = pts[1]
        pts_rel = pts - nose

        # Compute inter-ocular distance for scale normalization
        eye_dist = float(np.linalg.norm(pts[33] - pts[263])) + 1e-6
        pts_norm = pts_rel / eye_dist

        features = []
        # Key distance ratios and angles
        for idx in self.KEY_ANCHORS:
            if idx < len(pts_norm):
                features.extend(pts_norm[idx][:2].tolist())

        # Inter-anchor structural ratios
        d_eyes = float(np.linalg.norm(pts[33] - pts[263]))
        d_nose_chin = float(np.linalg.norm(pts[1] - pts[152]))
        d_forehead_chin = float(np.linalg.norm(pts[10] - pts[152]))
        d_cheeks = float(np.linalg.norm(pts[234] - pts[454]))
        d_mouth = float(np.linalg.norm(pts[61] - pts[291]))

        features.extend([
            d_nose_chin / (d_forehead_chin + 1e-6),
            d_eyes / (d_cheeks + 1e-6),
            d_mouth / (d_cheeks + 1e-6),
            d_eyes / (d_forehead_chin + 1e-6)
        ])

        # Pad or trim to exactly 64 floats
        feat_arr = np.array(features, dtype=np.float32)
        if len(feat_arr) < 64:
            feat_arr = np.pad(feat_arr, (0, 64 - len(feat_arr)))
        else:
            feat_arr = feat_arr[:64]

        # Unit normalize for cosine similarity
        norm = np.linalg.norm(feat_arr) + 1e-6
        return feat_arr / norm

    def compute_similarity(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """Calculates Cosine Similarity between two normalized face embeddings."""
        if emb1 is None or emb2 is None:
            return 0.0
        return float(np.dot(emb1, emb2))

    def extract_landmarks(self, frame_bgr: np.ndarray) -> Optional[list[tuple[float, float, float]]]:
        """Extracts 468-point 3D facial landmarks from BGR frame."""
        if frame_bgr is None or (self.task_detector is None and self.mesh_detector is None):
            return None
        h, w, _ = frame_bgr.shape
        if self.task_detector is not None and mp is not None:
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
            res = self.task_detector.detect(mp_image)
            if res.face_landmarks:
                return [(lm.x * w, lm.y * h, lm.z * w) for lm in res.face_landmarks[0]]
            return None
        elif self.mesh_detector is not None:
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            res = self.mesh_detector.process(frame_rgb)
            if res.multi_face_landmarks:
                return [(lm.x * w, lm.y * h, lm.z * w) for lm in res.multi_face_landmarks[0].landmark]
            return None
        return None

    def evaluate_frame(self, frame_bgr: np.ndarray) -> FaceAuthResult:
        """
        Processes a camera frame, extracts landmarks, checks anti-spoofing liveness,
        and matches against enrolled admin embedding.
        """
        if frame_bgr is None or (self.task_detector is None and self.mesh_detector is None):
            return FaceAuthResult(
                status="NO_FACE",
                confidence=0.0,
                liveness_score=0.0,
                spoof_type="none",
                details="Optical sensor feed unavailable."
            )

        h, w, _ = frame_bgr.shape
        pts_3d = self.extract_landmarks(frame_bgr)
        if pts_3d is None:
            return FaceAuthResult(
                status="NO_FACE",
                confidence=0.0,
                liveness_score=0.0,
                spoof_type="none",
                details="No face detected in sensor field of view."
            )

        eye_l = [(pts_3d[i][0], pts_3d[i][1]) for i in self.detector.LEFT_EYE]
        eye_r = [(pts_3d[i][0], pts_3d[i][1]) for i in self.detector.RIGHT_EYE]

        # Bounding box crop for texture & Moiré analysis
        xs = [p[0] for p in pts_3d]
        ys = [p[1] for p in pts_3d]
        x1, x2 = max(0, int(min(xs) - 20)), min(w, int(max(xs) + 20))
        y1, y2 = max(0, int(min(ys) - 20)), min(h, int(max(ys) + 20))
        face_crop = frame_bgr[y1:y2, x1:x2]

        # 1. Evaluate Anti-Spoofing Liveness
        liveness: LivenessReport = self.detector.analyze_frame(pts_3d, eye_l, eye_r, face_crop)

        # 2. Extract Facial Identity Embedding
        curr_embedding = self.extract_face_embedding(pts_3d)

        # 3. Match Against Enrolled Admin Profile
        confidence = 0.0
        if self.admin_embedding is not None:
            confidence = self.compute_similarity(curr_embedding, self.admin_embedding)
        else:
            # If no admin profile has been enrolled yet, report pending enrollment
            return FaceAuthResult(
                status="GUEST_DETECTED",
                confidence=0.0,
                liveness_score=liveness.score,
                spoof_type=liveness.spoof_type,
                details="No Admin profile enrolled. Operating in standard guest protocol.",
                frame_bgr=frame_bgr
            )

        # 4. Security Decision Matrix
        # Presentation attack check: if not live, flag attack regardless of matching features
        if not liveness.is_live:
            reasons_str = "; ".join(liveness.reasons) if liveness.reasons else "Liveness threshold failed."
            return FaceAuthResult(
                status="SPOOF_DETECTED",
                confidence=round(confidence, 3),
                liveness_score=liveness.score,
                spoof_type=liveness.spoof_type,
                details=f"Presentation attack detected ({liveness.spoof_type}): {reasons_str}",
                frame_bgr=frame_bgr
            )

        # Threshold for authenticating Admin identity:
        # Cosine similarity >= 0.82 with verified 3D depth and Moiré clearance
        if confidence >= 0.82 and liveness.is_live:
            return FaceAuthResult(
                status="ADMIN_VERIFIED",
                confidence=round(confidence, 3),
                liveness_score=liveness.score,
                spoof_type="none",
                details=f"Identity confirmed: {self.admin_name}. 3D liveness verified ({liveness.score * 100:.1f}%).",
                frame_bgr=frame_bgr
            )
        else:
            return FaceAuthResult(
                status="GUEST_DETECTED",
                confidence=round(confidence, 3),
                liveness_score=liveness.score,
                spoof_type="none",
                details="Living subject detected, but facial signature does not match Admin profile.",
                frame_bgr=frame_bgr
            )
