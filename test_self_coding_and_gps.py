"""Focused regression tests for dynamic HUD coding and in-memory mobile GPS telemetry."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import jarvis


class SelfCodingAndGpsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "web").mkdir()
        (self.root / "web" / "index.html").write_text("<body><section id='dynamic-hud-stage'></section></body>", encoding="utf-8")
        (self.root / "web" / "app.js").write_text("// HUD client\n", encoding="utf-8")
        self.profile = self.root / "memory" / "02 - Knowledge" / "Profile.md"
        self.profile.parent.mkdir(parents=True)
        self.profile.write_text("# Profile\nUntouched\n", encoding="utf-8")
        self.events = []
        self.broadcast = patch.object(jarvis, "broadcast_ui_event", self.events.append)
        self.broadcast.start()

    def tearDown(self):
        self.broadcast.stop()
        self.temp_dir.cleanup()

    def test_inspect_inject_and_backup(self):
        manager = jarvis.SelfCodeManager(self.root)
        architect = jarvis.AutonomousCodeArchitect(self.root, manager)
        report = architect.inspect_codebase("web/index.html", "security-progress")
        self.assertTrue(report["ok"])
        self.assertFalse(report["exists"])
        result = architect.synthesize_and_inject_hud_feature(
            "security-progress", '<div class="security-progress">42%</div>',
            ".security-progress { color: cyan; }", "mount.dataset.active = 'true';")
        self.assertTrue(result["ok"])
        self.assertTrue(any(event["type"] == "INJECT_HUD_COMPONENT" for event in self.events))
        self.assertIn("security-progress", (self.root / "web" / "index.html").read_text(encoding="utf-8"))
        self.assertTrue(list((self.root / ".cache" / "code_backups").glob("*.bak")))

    def test_python_patch_rejects_invalid_ast(self):
        target = self.root / "module.py"
        target.write_text("def ready():\n    return True\n", encoding="utf-8")
        manager = jarvis.SelfCodeManager(self.root)
        # Relative paths must be rooted at the managed workspace, not the test process CWD.
        result = manager.apply_code_patch("module.py", "return True", "return (", "break syntax")
        self.assertIn("SyntaxError", result)
        self.assertIn("return True", target.read_text(encoding="utf-8"))

    def test_gps_telemetry_is_memory_only(self):
        """Coordinates stay in the per-session in-memory store (`_session_gps`):
        Profile.md is never touched, the resolved area lands back in that session
        only, and nothing is fanned out to every HUD client."""
        before = self.profile.read_text(encoding="utf-8")
        with patch.object(jarvis, "_reverse_geocode_live_gps", return_value="Meerpet"):
            result = jarvis.update_live_gps_telemetry(17.3207, 78.5369, 6,
                                                      session_id="mobile-1")
            self.assertTrue(result["ok"])
            self.assertEqual(result["session_id"], "mobile-1")
            # The reverse lookup resolves on a daemon thread; wait for it.
            deadline = time.time() + 3.0
            while time.time() < deadline:
                if jarvis._session_gps.get("mobile-1", {}).get("area") == "Meerpet":
                    break
                time.sleep(0.01)
        self.assertEqual(before, self.profile.read_text(encoding="utf-8"))
        session = jarvis._session_gps["mobile-1"]
        self.assertEqual(session["lat"], 17.3207)
        self.assertEqual(session["lon"], 78.5369)
        self.assertEqual(session["accuracy"], 6.0)
        self.assertEqual(session["area"], "Meerpet")
        # Session-scoped by design: other sessions untouched, and GPS is never
        # broadcast to every HUD client (only echoed to the reporting session).
        self.assertNotIn("default", jarvis._session_gps)
        self.assertFalse(any(evt.get("type") == "GPS_LOCATION" for evt in self.events))
        # Invalid coordinates are refused instead of stored.
        self.assertFalse(jarvis.update_live_gps_telemetry(999.0, 0.0, 5)["ok"])


if __name__ == "__main__":
    unittest.main()
