"""Selected deterministic AI saves: base event bytes and replay remain unchanged.

Only two changed Python files are materialized at the base revision. Everything
else is linked to this checkout; no full checkout or private saved data is copied.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.h1_support import ROOT

BASE = "672ec109"
SCRIPT = r'''
import json, sys
from pathlib import Path
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT

data, scenario, existing = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
if existing:
    combat = CombatService(ROOT, data)
    mid = existing
else:
    if scenario == "gilded":
        from tests.test_tabletop_gilded_context import gilded_fight
        combat, table, mid = gilded_fight(data)
    else:
        from tests.test_hunt5_player_choices import fixture
        combat, table, mid, _, _ = fixture(data, "TAL_FENCING_FOOTWORK")
    for actor in combat._load_session(mid).engine.state.actors:
        combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")
    combat = CombatService(ROOT, data)
    table = TabletopService(combat, data)
    for _ in range(20):
        state = table.state(mid)
        if state["presentation"]["terminal"]:
            break
        assert table.auto_step(mid, state["last_sequence"])["status"] == "COMMITTED"
session = combat._load_session(mid)
assert session.verify()["status"] == "PASS"
replay = session.mechanical.replay()
assert replay["status"] == "PASS"
print(json.dumps({"match_id": mid, "events": canonical_sha256(replay["events"]),
    "rolls": canonical_sha256(replay["rolls"]), "state": replay["canonical_state_sha256"],
    "event_count": len(replay["events"]), "roll_count": len(replay["rolls"])}))
'''


def base_overlay(path):
    path.mkdir()
    # Only the table service and ability implementation differ at this base.
    replacements = {"combat/tabletop_service.py", "combat/ext/goruden.py"}
    def link_tree(relative):
        source, target = ROOT / relative, path / relative
        for item in source.iterdir():
            name = (relative / item.name).as_posix()
            dest = target / item.name
            if item.name in {"__pycache__", ".pytest_cache"}:
                continue
            if name in replacements:
                content = subprocess.check_output(["git", "show", f"{BASE}:APP/{name}"], cwd=ROOT)
                dest.write_bytes(content)
            elif any(r.startswith(name + "/") for r in replacements):
                dest.mkdir()
                link_tree(relative / item.name)
            else:
                dest.symlink_to(item, target_is_directory=item.is_dir())
    link_tree(Path("."))
    return path


def run(root, data, scenario, existing=""):
    env = {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-c", SCRIPT, str(data), scenario, existing],
                            cwd=root, env=env, text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr[-4000:] + result.stdout[-4000:]
    return json.loads(result.stdout.splitlines()[-1])


@pytest.mark.parametrize("scenario", ["footwork", "gilded"])
def test_base_ai_events_and_saved_replay_are_byte_identical(tmp_path, scenario):
    overlay = base_overlay(tmp_path / "base-app")
    baseline = run(overlay, tmp_path / "base-data", scenario)
    tip = run(ROOT, tmp_path / "tip-data", scenario)
    assert tip == baseline
    # Reopen the save actually written by the base, with the new implementation.
    before = {p: p.read_bytes() for p in (tmp_path / "base-data").rglob("Journal.ndjson")}
    assert run(ROOT, tmp_path / "base-data", scenario, baseline["match_id"]) == baseline
    assert all(p.read_bytes() == content for p, content in before.items())
