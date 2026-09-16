#!/usr/bin/env python3
"""
J.A.R.V.I.S. Biometric Enrollment Wizard
Calibrates and stores 3D facial landmarks and acoustic voiceprint for Admin authorization.
"""

import json
import math
import os
import sys
import time
from pathlib import Path

# Ensure virtualenv libraries are loaded
curr_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(curr_dir))

import cv2
import numpy as np
import sounddevice as sd

from biometrics.anti_spoofing import LivenessDetector
from biometrics.face_sentinel import FaceSentinel
from biometrics.voice_sentinel import VoiceSentinel


def print_banner():
    print("\n" + "═" * 70)
    print("  ⚛ J.A.R.V.I.S. BIOMETRIC SECURITY PROTOCOL // ADMIN ENROLLMENT WIZARD")
    print("  Stark Industries Presentation Attack Defense & Voiceprint Suite")
    print("═" * 70 + "\n")


def enroll_face(face_sentinel: FaceSentinel, camera_idx: int = 0) -> dict:
    print("📷 STAGE 1: OPTICAL 3D FACE & DEPTH CALIBRATION")
    print("──────────────────────────────────────────────────────────────────────")
    print("Initializing optical sensor... Please sit directly in front of camera.")
    
    cap = cv2.VideoCapture(camera_idx)
    if not cap.isOpened():
        print(f"⚠️ Warning: Could not open camera {camera_idx}. Trying camera 1...")
        cap = cv2.VideoCapture(1)
        if not cap.isOpened():
            print("❌ Error: No optical sensor (webcam) detected. Please check camera connections.")
            return {}

    embeddings = []
    depth_variances = []
    
    print("\n1. [CENTER] Looking straight at the camera (Hold steady for 3 seconds)...")
    start_time = time.time()
    
    while time.time() - start_time < 3.5:
        ret, frame = cap.read()
        if not ret:
            continue
        
        pts_3d = face_sentinel.extract_landmarks(frame)
        if pts_3d:
            emb = face_sentinel.extract_face_embedding(pts_3d)
            embeddings.append(emb)
            _, var = face_sentinel.detector.evaluate_3d_depth(pts_3d)
            depth_variances.append(var)
            print(f"\r  ⚡ Capturing 3D topological mesh: {len(embeddings)} frames...", end="", flush=True)
        time.sleep(0.05)
    
    print(f"\n  ✓ Neutral 3D facial mesh captured ({len(embeddings)} frames).")

    print("\n2. [ANGLES] Slowly tilt your head slightly left, then right (3 seconds)...")
    start_time = time.time()
    while time.time() - start_time < 3.5:
        ret, frame = cap.read()
        if not ret:
            continue
        pts_3d = face_sentinel.extract_landmarks(frame)
        if pts_3d:
            emb = face_sentinel.extract_face_embedding(pts_3d)
            embeddings.append(emb)
            _, var = face_sentinel.detector.evaluate_3d_depth(pts_3d)
            depth_variances.append(var)
        time.sleep(0.05)
    
    print(f"  ✓ 3D depth and surface parallax calibrated ({len(embeddings)} total frames).")
    cap.release()

    if not embeddings:
        print("❌ Error: Failed to capture facial landmarks. Please ensure your face is well-lit.")
        return {}

    # Average embeddings for canonical representation
    mean_emb = np.mean(embeddings, axis=0)
    norm = np.linalg.norm(mean_emb) + 1e-6
    canonical_emb = (mean_emb / norm).tolist()
    mean_depth = float(np.mean(depth_variances)) if depth_variances else 0.15

    print(f"  ✓ Facial biometric signature computed (64D vector, baseline depth variance: {mean_depth:.4f})")
    return {
        "embedding": canonical_emb,
        "depth_variance_baseline": mean_depth,
        "enrolled_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }


def enroll_voice(voice_sentinel: VoiceSentinel, sample_rate: int = 16000) -> dict:
    print("\n🎙️ STAGE 2: ACOUSTIC SPEAKER VERIFICATION (VOICEPRINT)")
    print("──────────────────────────────────────────────────────────────────────")
    print("You will speak 2 authorization phrases into your microphone.")
    
    phrases = [
        "I am Tony Stark, and this is my system.",
        "JARVIS, initialize defensive protocols."
    ]
    
    voiceprints = []
    
    for i, phrase in enumerate(phrases, 1):
        input(f"\nPress [ENTER] when ready to speak Phrase {i}: \"{phrase}\"...")
        print(f"  🔴 RECORDING NOW: Speak clearly -> \"{phrase}\"")
        duration_s = 3.5
        try:
            recording = sd.rec(int(duration_s * sample_rate), samplerate=sample_rate, channels=1, dtype="int16")
            sd.wait()
            audio_data = recording.flatten()
            print("  ✓ Processing acoustic resonant formants...")
            vprint = voice_sentinel.extract_voiceprint(audio_data, sample_rate)
            if np.linalg.norm(vprint) > 0.1:
                voiceprints.append(vprint)
                print(f"  ✓ Phrase {i} captured successfully.")
            else:
                print(f"  ⚠️ Warning: Audio level was low for Phrase {i}.")
        except Exception as e:
            print(f"  ❌ Audio recording error: {e}")

    if not voiceprints:
        print("❌ Error: Failed to capture acoustic voice samples.")
        return {}

    mean_vprint = np.mean(voiceprints, axis=0)
    norm = np.linalg.norm(mean_vprint) + 1e-6
    canonical_voiceprint = (mean_vprint / norm).tolist()

    print(f"  ✓ Voice biometric signature computed (64D acoustic vector).")
    return {
        "embedding": canonical_voiceprint,
        "sample_rate": sample_rate,
        "enrolled_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }


def main():
    print_banner()
    
    # Check admin name from profile if available
    profile_dir = Path(__file__).resolve().parent / "memory" / "00 - Biometrics"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_file = profile_dir / "admin_profile.json"
    
    default_name = "Boss"
    user_prof = Path(__file__).resolve().parent / "memory" / "02 - Knowledge" / "Profile.md"
    if user_prof.is_file():
        try:
            with open(user_prof, "r") as f:
                for line in f:
                    if "name" in line.lower() or "user" in line.lower():
                        parts = line.split(":")
                        if len(parts) > 1 and parts[1].strip():
                            default_name = parts[1].strip()
                            break
        except Exception:
            pass

    print(f"Admin Identity: {default_name}")
    name_input = input(f"Enter Admin display name [{default_name}]: ").strip()
    admin_name = name_input if name_input else default_name

    face_sentinel = FaceSentinel(str(profile_file))
    voice_sentinel = VoiceSentinel(str(profile_file))

    # Stage 1: Face
    face_data = enroll_face(face_sentinel)
    if not face_data:
        print("\n❌ Face calibration aborted. Please ensure your camera is working and re-run.")
        return

    # Stage 2: Voice
    voice_data = enroll_voice(voice_sentinel)
    if not voice_data:
        print("\n❌ Voice calibration aborted. Please check your microphone.")
        return

    # Assemble and Save Profile
    admin_profile = {
        "admin_name": admin_name,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "face": face_data,
        "voice": voice_data,
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

    print("\n" + "═" * 70)
    print(f"  ✅ BIOMETRIC ENROLLMENT COMPLETE FOR ADMIN: {admin_name.upper()}")
    print(f"  Vault location: {profile_file}")
    print("  Defensive anti-spoofing protocols are now active.")
    print("═" * 70 + "\n")


if __name__ == "__main__":
    main()
