"""The committed automation-truth reports reproduce byte for byte from the audited sources.

Local only (TRUTHGEN1, Wang 2026-11-09): every report embeds input_sha256 over all audited sources, which include
modules the public export withholds and rule text it ships prose-transformed, so --check cannot pass on a public tree.
The reports are withheld from the export; this file names them and runs in the local batch gate.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class CommittedReportReproducibilityTests(unittest.TestCase):
    def test_a_fresh_process_with_another_hash_seed_reproduces_the_committed_reports(self):
        """The owner's acceptance check: a second interpreter reproduces every committed byte.

        PYTHONHASHSEED changes set and dict iteration order, so a fresh process with a fixed,
        different seed proves the reports carry no hash-order, clock, or machine dependence, and that
        the checked-in files still match the audited sources they name.
        """
        env = dict(os.environ, PYTHONHASHSEED="20261005", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, "-m", "tools.automation_truth", "--check",
                                 "--json", str(ROOT / "docs/plans/AUTOMATION_TRUTH_R1.json"),
                                 "--summary", str(ROOT / "docs/plans/AUTOMATION_TRUTH_R1.md"),
                                 "--audit", str(ROOT / "docs/plans/AUTOMATION_TRUTH_AUDIT.md")],
                                cwd=ROOT / "APP", env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["mechanics"])
