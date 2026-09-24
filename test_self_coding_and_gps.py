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
        before = self.profile.read_text(encoding="utf-8")
        with patch.object(jarvis, "_reverse_geocode_live_gps", return_value="Meerpet"):
            result = jarvis.update_live_gps_telemetry(17.3207, 78.5369, 6)
            self.assertTrue(result["ok"])
            time.sleep(0.03)
        self.assertEqual(before, self.profile.read_text(encoding="utf-8"))
        self.assertEqual(jarvis._live_user_gps["lat"], 17.3207)
        self.assertTrue(any(event["type"] == "GPS_LOCATION" for event in self.events))


if __name__ == "__main__":
    unittest.main()
