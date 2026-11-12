"""Owned selector status providers outrank the generic fallback, whatever module was imported first.

The status_description hooks are a process-global list in registration order. A module that imports a plug-in
directly (test modules do: tests/test_condition_tooltips.py imports generated_status_text) registers that plug-in's
hooks before the plug-in loader runs. This runs a fresh interpreter in exactly that order.
"""
import json
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]

PROBE = """
import json
import combat.ext.generated_status_text  # imported before the other plug-ins, as a test module does
import combat.ext.docket_walls
import combat.ext.destruction_blast
from combat import ext
order = [fn.__module__ for fn in ext._HOOKS["status_description"]]
print(json.dumps({"docket": order.index("combat.ext.docket_walls"),
                  "deepen": order.index("combat.ext.destruction_blast"),
                  "generic": order.index("combat.ext.generated_status_text")}))
"""


def test_selector_providers_precede_generic_status_fallback_after_early_import():
    done = subprocess.run([sys.executable, "-c", PROBE], cwd=APP, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-2000:]
    index = json.loads(done.stdout.strip().splitlines()[-1])
    assert index["docket"] < index["generic"], index
    assert index["deepen"] < index["generic"], index
