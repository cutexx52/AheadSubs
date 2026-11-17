import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(os.name == "nt", "Desktop runtime requires Windows")
class DiagnosticsTest(unittest.TestCase):
    def test_logs_are_created_only_when_diagnostics_are_enabled(self):
        from subtitle_relay.desktop import runtime

        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "relay.log"
            with patch.object(runtime, "diagnostics_enabled", return_value=False):
                with runtime.log_output(log, text=True) as output:
                    self.assertIsNone(output)
                self.assertFalse(log.exists())
            with patch.object(runtime, "diagnostics_enabled", return_value=True):
                with runtime.log_output(log, text=True) as output:
                    output.write("diagnostics\n")
                self.assertEqual(log.read_text(encoding="utf-8"), "diagnostics\n")
