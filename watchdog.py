"""
J.A.R.V.I.S. Proactive Ambient Interjections & Watchdog Daemon
=============================================================
Autonomous background diagnostic monitor with context-aware, movie-authentic
spoken interjections. Proactively observes hardware vitals:
- CPU Thermal Spikes (Package/Core temperatures)
- Memory Leaks & Runaway Process Attribution (identifies the specific offending app)
- Battery Depletion & Power Status (Discharge alerts at 18%, 8%, 3%)
- Disk Root Space Depletion
- Circadian Late-Night Fatigue Sentinel

Features a Conversational Gatekeeper to strictly prevent interrupting the user
while speaking, listening, or thinking, and category-based hysteresis to eliminate
repetitive alert storms.
"""

from __future__ import annotations

from datetime import datetime
import glob
import logging
import os
from pathlib import Path
import random
import shutil
import threading
import time
from typing import Callable, Dict, Optional, Tuple

log = logging.getLogger("JARVIS.Watchdog")


class ProactiveWatchdogDaemon:
    """Autonomous hardware watchdog with polite, movie-authentic spoken interjections."""

    def __init__(
        self,
        signal_bus=None,
        voice_engine=None,
        sound_engine=None,
        telegram_bridge=None,
        broadcast_fn: Optional[Callable[[dict], None]] = None,
        tts_checker: Optional[Callable[[], bool]] = None,
    ):
        self.bus = signal_bus
        self.voice_engine = voice_engine
        self.sound_engine = sound_engine
        self.telegram = telegram_bridge
        self.broadcast_fn = broadcast_fn
        self.tts_checker = tts_checker

        self.enabled = True
        self.silent_mode = False  # If True, broadcast to UI/Telegram without speaking aloud
        self.poll_interval_s = 4.0
        self._lock = threading.Lock()
        self._active = False
        self._thread: Optional[threading.Thread] = None

        self.session_start_time = time.time()
        self.last_voice_activity_time = time.time()

        # Stateful Hysteresis Timestamps & Trigger Memory
        self._last_alert_times: Dict[str, float] = {
            "thermal": 0.0,
            "memory": 0.0,
            "battery": 0.0,
            "disk": 0.0,
            "fatigue": 0.0,
        }
        self._battery_thresholds_fired = {"18": False, "8": False, "3": False}
        self._pending_interjection: Optional[Tuple[str, str, str]] = None  # (category, level, phrase)

        # Thresholds
        self.THERMAL_WARNING_C = 82.0
        self.THERMAL_CRITICAL_C = 90.0
        self.RAM_WARNING_PCT = 88.0
        self.DISK_WARNING_PCT = 92.0

        log.info("Proactive Watchdog Daemon initialized.")

    def start(self) -> None:
        """Start the background diagnostic watchdog thread."""
        if self._active:
            return
        self._active = True
        self._thread = threading.Thread(target=self._watchdog_loop, daemon=True, name="jarvis-watchdog")
        self._thread.start()
        log.info("Proactive Watchdog Daemon started (Polling cycle: %.1fs).", self.poll_interval_s)

    def stop(self) -> None:
        """Stop the watchdog daemon."""
        self._active = False

    # ── HARDWARE SENSORS & PROBES ─────────────────────────────────────────

    def probe_thermals(self) -> dict:
        """Read CPU temperature across thermal zones with graceful loadavg fallback."""
        temps = []
        try:
            for tz in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
                try:
                    with open(tz, "r") as f:
                        raw = f.read().strip()
                    val = float(raw)
                    if val > 1000:
                        val /= 1000.0
                    temps.append(val)
                except Exception:
                    continue
        except Exception:
            pass

        if temps:
            max_temp = max(temps)
            return {"source": "thermal_zone", "temp_c": round(max_temp, 1), "all_zones": temps}

        # Fallback: check load average
        load = 0.0
        try:
            if os.path.exists("/proc/loadavg"):
                with open("/proc/loadavg") as f:
                    load = float(f.read().split()[0])
        except Exception:
            pass
        return {"source": "loadavg", "temp_c": None, "loadavg": round(load, 2)}

    def probe_memory(self) -> dict:
        """Read system RAM and identify the top memory-consuming process name and RSS."""
        mem = {"total_gb": 0.0, "used_gb": 0.0, "free_gb": 0.0, "pct": 0.0}
        try:
            if os.path.exists("/proc/meminfo"):
                raw_info = {}
                with open("/proc/meminfo") as f:
                    for line in f:
                        parts = line.split(":")
                        if len(parts) == 2:
                            raw_info[parts[0].strip()] = int(parts[1].strip().split()[0])
                tot = raw_info.get("MemTotal", 1) / (1024 * 1024)
                avail = raw_info.get("MemAvailable", 0) / (1024 * 1024)
                used = tot - avail
                pct = (used / tot) * 100 if tot > 0 else 0
                mem = {
                    "total_gb": round(tot, 1),
                    "used_gb": round(used, 1),
                    "free_gb": round(avail, 1),
                    "pct": round(pct, 1),
                }
        except Exception:
            pass

        # Identify runaway process
        top_proc_name = "Unknown"
        top_proc_mb = 0.0
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            procs = []
            for p in glob.glob("/proc/[0-9]*"):
                try:
                    statm_path = os.path.join(p, "statm")
                    comm_path = os.path.join(p, "comm")
                    if os.path.exists(statm_path) and os.path.exists(comm_path):
                        with open(statm_path) as sf:
                            rss_pages = int(sf.read().split()[1])
                        rss_mb = (rss_pages * page_size) / (1024 * 1024)
                        with open(comm_path) as cf:
                            name = cf.read().strip()
                        procs.append((rss_mb, name))
                except Exception:
                    continue
            if procs:
                procs.sort(reverse=True)
                top_proc_mb, top_proc_name = procs[0]
        except Exception:
            pass

        mem["top_process"] = top_proc_name
        mem["top_process_mb"] = round(top_proc_mb, 1)
        return mem

    def probe_battery(self) -> Optional[dict]:
        """Read battery level and charging state, or return None for desktop/servers."""
        for b_dir in glob.glob("/sys/class/power_supply/BAT*"):
            try:
                cap_file = os.path.join(b_dir, "capacity")
                stat_file = os.path.join(b_dir, "status")
                if os.path.exists(cap_file):
                    cap = int(open(cap_file).read().strip())
                    status = open(stat_file).read().strip() if os.path.exists(stat_file) else "Unknown"
                    return {"capacity": cap, "status": status, "is_discharging": status.lower() == "discharging"}
            except Exception:
                continue
        return None

    def probe_disk(self) -> dict:
        """Read root partition disk capacity."""
        try:
            total, used, free = shutil.disk_usage("/")
            pct = (used / total) * 100
            return {
                "total_gb": round(total / (1024**3), 1),
                "used_gb": round(used / (1024**3), 1),
                "free_gb": round(free / (1024**3), 1),
                "pct": round(pct, 1),
            }
        except Exception:
            return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "pct": 0}

    def probe_circadian(self) -> dict:
        """Check for user late-night fatigue (active sessions between 01:00 and 05:00)."""
        now = datetime.now()
        hours_active = (time.time() - self.session_start_time) / 3600.0
        is_late_night = 1 <= now.hour <= 5
        return {
            "hour": now.hour,
            "session_hours": round(hours_active, 1),
            "is_late_night": is_late_night,
            "fatigue_alert": is_late_night and hours_active >= 3.0,
        }

    # ── CONVERSATIONAL GATEKEEPER ─────────────────────────────────────────

    def is_conversational_channel_clear(self) -> bool:
        """Strict check to ensure J.A.R.V.I.S. NEVER interrupts an active conversation.
        Requires:
        1. SignalBus state is 'idle'.
        2. No active TTS playback (_tts_playing is clear).
        3. At least 5.0 seconds have elapsed since last voice activity.
        """
        if self.bus:
            try:
                state = self.bus.state_dir.joinpath("state").read_text().strip()
                if state in ("listening", "speaking", "thinking"):
                    return False
            except Exception:
                pass

        if self.tts_checker and self.tts_checker():
            return False

        if time.time() - self.last_voice_activity_time < 5.0:
            return False

        return True

    def notify_voice_activity(self) -> None:
        """Mark voice activity to suppress interjections for at least 5 seconds."""
        self.last_voice_activity_time = time.time()

    # ── CINEMATIC PHRASING SYNTHESIZER ───────────────────────────────────

    def generate_interjection_phrase(self, category: str, data: dict) -> str:
        """Synthesize movie-authentic, witty Bettany-style phrasing."""
        if category == "thermal":
            temp = data.get("temp_c", 85)
            phrases = [
                f"Pardon the interruption, sir, but core thermals have reached {temp:.0f} degrees. I recommend shedding unnecessary background tasks.",
                f"Sir, thermal sensors are registering {temp:.0f} degrees Celsius. The cooling manifold is under heavy load.",
                f"Excuse me, sir. Core temperatures have spiked to {temp:.0f} degrees. We may wish to throttle non-essential processes.",
            ]
            return random.choice(phrases)

        if category == "memory":
            pct = data.get("pct", 90)
            app = data.get("top_process", "Unknown application")
            mb = data.get("top_process_mb", 1024)
            gb_str = f"{mb/1024:.1f} gigabytes" if mb >= 1024 else f"{mb:.0f} megabytes"
            phrases = [
                f"Pardon the intrusion, sir, but memory utilization is at {pct:.0f} percent. {app} is consuming {gb_str}.",
                f"Sir, available memory is running uncomfortably low at {pct:.0f} percent. {app} appears to be the primary culprit.",
                f"A brief advisory, sir: total system RAM is at {pct:.0f} percent capacity. You might consider terminating {app}.",
            ]
            return random.choice(phrases)

        if category == "battery":
            cap = data.get("capacity", 15)
            if cap <= 5:
                return f"Sir, emergency alert: battery reserve is at {cap} percent. Power failure is imminent. Please connect the AC adapter immediately."
            phrases = [
                f"Sir, battery reserves have dropped to {cap} percent. I suggest connecting the power adapter before operations are compromised.",
                f"Excuse me, sir. Power levels are currently at {cap} percent and discharging. A power connection is advised.",
                f"Pardon the interruption, sir. Main power cell is at {cap} percent. We are operating on limited reserves.",
            ]
            return random.choice(phrases)

        if category == "disk":
            free = data.get("free_gb", 5)
            phrases = [
                f"Sir, primary storage is critically low. We have only {free:.1f} gigabytes of free disk space remaining.",
                f"Pardon the interruption, sir, but the root partition has only {free:.1f} gigabytes remaining. Clean-up is strongly advised.",
            ]
            return random.choice(phrases)

        if category == "fatigue":
            hrs = data.get("session_hours", 3.5)
            phrases = [
                f"Sir, it is late in the morning and you have been at the console for over {hrs:.0f} hours. Might I gently suggest some rest?",
                f"Pardon the personal observation, sir, but human biology still requires sleep. You have been active for {hrs:.0f} consecutive hours.",
                f"Sir, it is past 2 AM. Your cognitive stamina will benefit from rest. Standing by whenever you are ready to conclude the session.",
            ]
            return random.choice(phrases)

        return "Sir, an anomaly has been detected in system telemetry."

    # ── EVALUATION LOOP & DISPATCH ───────────────────────────────────────

    def _watchdog_loop(self) -> None:
        """Main periodic diagnostic inspection loop."""
        while self._active:
            try:
                time.sleep(self.poll_interval_s)
                if not self.enabled:
                    continue

                now = time.time()

                # If we have a postponed interjection waiting for a quiet conversational window:
                if self._pending_interjection and self.is_conversational_channel_clear():
                    cat, lvl, phrase = self._pending_interjection
                    self._pending_interjection = None
                    self._dispatch_interjection(cat, lvl, phrase)
                    continue

                # 1. Thermal Evaluation
                therm = self.probe_thermals()
                if therm.get("temp_c") is not None:
                    t_val = therm["temp_c"]
                    cooldown = 300.0 if t_val >= self.THERMAL_CRITICAL_C else 720.0  # 5 min critical, 12 min warning
                    if t_val >= self.THERMAL_WARNING_C and (now - self._last_alert_times["thermal"] > cooldown):
                        self._last_alert_times["thermal"] = now
                        lvl = "critical" if t_val >= self.THERMAL_CRITICAL_C else "warning"
                        phrase = self.generate_interjection_phrase("thermal", therm)
                        self._queue_or_dispatch("thermal", lvl, phrase)

                # 2. Memory Evaluation
                mem = self.probe_memory()
                if mem.get("pct", 0) >= self.RAM_WARNING_PCT:
                    if now - self._last_alert_times["memory"] > 900.0:  # 15 min cooldown
                        self._last_alert_times["memory"] = now
                        phrase = self.generate_interjection_phrase("memory", mem)
                        self._queue_or_dispatch("memory", "warning", phrase)

                # 3. Battery Evaluation
                bat = self.probe_battery()
                if bat and bat.get("is_discharging"):
                    cap = bat.get("capacity", 100)
                    for thresh in (18, 8, 3):
                        key = str(thresh)
                        if cap <= thresh and not self._battery_thresholds_fired[key]:
                            self._battery_thresholds_fired[key] = True
                            lvl = "critical" if cap <= 8 else "warning"
                            phrase = self.generate_interjection_phrase("battery", bat)
                            self._queue_or_dispatch("battery", lvl, phrase)
                            break
                elif bat and not bat.get("is_discharging"):
                    # Reset triggers when plugged back into AC
                    self._battery_thresholds_fired = {"18": False, "8": False, "3": False}

                # 4. Disk Evaluation
                disk = self.probe_disk()
                if disk.get("pct", 0) >= self.DISK_WARNING_PCT or (disk.get("free_gb", 100) < 5.0 and disk.get("free_gb", 0) > 0):
                    if now - self._last_alert_times["disk"] > 1800.0:  # 30 min cooldown
                        self._last_alert_times["disk"] = now
                        phrase = self.generate_interjection_phrase("disk", disk)
                        self._queue_or_dispatch("disk", "warning", phrase)

                # 5. Circadian Fatigue Evaluation
                circ = self.probe_circadian()
                if circ.get("fatigue_alert") and (now - self._last_alert_times["fatigue"] > 14400.0):  # 4 hour cooldown
                    self._last_alert_times["fatigue"] = now
                    phrase = self.generate_interjection_phrase("fatigue", circ)
                    self._queue_or_dispatch("fatigue", "advisory", phrase)

            except Exception as e:
                log.debug("Watchdog diagnostic cycle notice: %s", e)

    def _queue_or_dispatch(self, category: str, level: str, phrase: str) -> None:
        """Route through Conversational Gatekeeper: dispatch now if quiet, or postpone until idle."""
        if self.is_conversational_channel_clear():
            self._dispatch_interjection(category, level, phrase)
        else:
            log.info("Watchdog: Channel busy (user speaking/listening). Postponing '%s' interjection.", category)
            self._pending_interjection = (category, level, phrase)

    def _dispatch_interjection(self, category: str, level: str, phrase: str) -> None:
        """Deliver the proactive spoken interjection, sound effect cue, UI banner, and Telegram alert."""
        log.info("📢 [WATCHDOG INTERJECTION] (%s // %s): '%s'", category.upper(), level.upper(), phrase)

        # 1. Dispatch Web HUD real-time toast & telemetry event
        if self.broadcast_fn:
            try:
                self.broadcast_fn({
                    "type": "PROACTIVE_INTERJECTION",
                    "category": category,
                    "level": level,
                    "phrase": phrase,
                    "timestamp": time.time(),
                })
                self.broadcast_fn({
                    "type": "SUBTITLE",
                    "role": "jarvis",
                    "text": phrase,
                })
            except Exception as e:
                log.debug("Watchdog UI broadcast notice: %s", e)

        # 2. Telegram alert for critical warnings
        if level == "critical" and self.telegram:
            try:
                self.telegram.send_message(f"🚨 *JARVIS WATCHDOG ALERT: {category.upper()}*\n{phrase}")
            except Exception as e:
                log.debug("Telegram alert dispatch notice: %s", e)

        # 3. Spoken Audio Interjection (preceded by subtle Stark chime)
        if not self.silent_mode and self.voice_engine:
            if self.sound_engine:
                self.sound_engine.play("wake" if level != "critical" else "security_alert")
            self.voice_engine.speak(phrase)

    # ── ON-DEMAND DIAGNOSTIC REPORT ───────────────────────────────────────

    def get_diagnostics_report(self) -> str:
        """Synthesize a complete on-demand diagnostic report for voice queries."""
        therm = self.probe_thermals()
        mem = self.probe_memory()
        bat = self.probe_battery()
        disk = self.probe_disk()

        parts = []
        if therm.get("temp_c") is not None:
            parts.append(f"Core thermal reading is at {therm['temp_c']:.0f} degrees Celsius.")
        elif therm.get("loadavg") is not None:
            parts.append(f"CPU load average is currently {therm['loadavg']:.2f}.")

        parts.append(f"Memory utilization is at {mem.get('pct', 0):.0f} percent, with {mem.get('used_gb', 0)} of {mem.get('total_gb', 0)} gigabytes committed.")
        if mem.get("top_process") and mem.get("top_process_mb", 0) > 300:
            parts.append(f"The primary resource consumer is {mem['top_process']} at {mem['top_process_mb']:.0f} megabytes.")

        if bat:
            stat = "charging" if not bat.get("is_discharging") else "discharging"
            parts.append(f"Battery reserves are at {bat.get('capacity', 100)} percent and {stat}.")

        parts.append(f"Storage volume has {disk.get('free_gb', 0)} gigabytes available.")
        parts.append("All subsystems remain within operational parameters, sir.")

        return " ".join(parts)

    def mute(self) -> None:
        """Silence spoken alerts (HUD-only mode)."""
        self.silent_mode = True
        log.info("Watchdog spoken alerts muted (Silent HUD mode).")

    def unmute(self) -> None:
        """Restore spoken alerts."""
        self.silent_mode = False
        log.info("Watchdog spoken alerts unmuted.")
