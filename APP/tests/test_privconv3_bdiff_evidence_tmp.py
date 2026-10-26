"""PRIVCONV3F6 behaviour diff: the four records this lane turns on, replayed side by side.

Runs the Factory's own fight script on the base checkout (the branch before this fix
round) and on the head checkout (this branch's head), through the Factory's bdiff tool,
and compares the two runs. The test fails when the comparison did not happen (a script
problem, a crash, a missing report) instead of when the two sides differ.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
TOOLS = ROOT / ".bdiff/tools"
BASE = ROOT / ".bdiff/base"
HEAD = ROOT / ".bdiff/head"
SCRIPT = ROOT / ".bdiff/script.json"


def _run(checkout, out, work):
    env = dict(os.environ)
    env["TMPDIR"] = str(work)
    env["BDIFF_TMP"] = str(work)
    run = subprocess.run(
        [sys.executable, str(TOOLS / "bdiff_script.py"), "run", str(SCRIPT), str(checkout / "APP"), str(out)],
        capture_output=True, text=True, timeout=1800, cwd=str(checkout / "APP"), env=env)
    print(run.stdout[-2000:])
    print(run.stderr[-2000:])
    assert run.returncode == 0, (run.returncode, run.stdout[-2000:], run.stderr[-2000:])
    return json.loads(Path(out).read_text())


def test_the_four_records_are_replayed_side_by_side():
    sys.path.insert(0, str(TOOLS))
    import bdiff_script

    work = Path(tempfile.mkdtemp(prefix="bdiff-evidence-"))
    base = _run(BASE, work / "base.json", work)
    head = _run(HEAD, work / "head.json", work)
    comparison = bdiff_script.compare(base, head)
    print("COMPARISON " + json.dumps(comparison, indent=1, default=str))
    (work / "comparison.json").write_text(json.dumps(comparison, indent=1, default=str))
    assert comparison["result"] in ("same", "differs"), comparison
    assert not comparison["problems"], comparison
    # The four records really ran on both sides.
    for side, run in (("base", base), ("head", head)):
        sources = {event.get("source") or "" for step in run.get("steps", []) for event in step.get("events", [])}
        for wanted in ("TAL_YANG_KINDLED_RESPONSES#complete_force",
                       "TAL_YANG_OVERKINDLED_RESPONSES#overheat_force",
                       "TAL_YANG_APPLYING_A_RISING_MARK#force_the_rising",
                       "defensive_discipline.tempered_response"):
            assert any(wanted in source for source in sources), (side, wanted)
        assert any("painted_beast" in source for source in sources), (side, "painted_beast")
