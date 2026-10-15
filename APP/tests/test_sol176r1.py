"""Review-round regressions: explicit rows, nested expiry and Water choices."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from combat import ext
from combat.ext.subject_repositioning import reposition
from combat.ext.scoundrel_riders import ANCHOR
from combat.gate2_runtime_models import Position
from combat.typed_executor import Context
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY, RIGHT, HOLD
from tests.test_sol176_subject_displacement import send, automatic_action
from tests.r10_fixup_support import fixed_dice


def teleport_rows(value, path=""):
    if isinstance(value, dict):
        if value.get("type") == "teleport" or value.get("mode") == "teleport":
            yield path, value
        for key, child in value.items():
            yield from teleport_rows(child, path + "/" + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from teleport_rows(child, path + "/" + str(index))


def test_every_unopted_teleport_row_retains_historical_interpreter(tmp_path):
    combat, _, mid = table_fight(tmp_path, ["tianxia.talent.space.spatial_displacement"], ally_talents=[])
    engine = combat._load_session(mid).engine
    action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.display_name == "Spatial Displacement")
    subject = engine.state.actors[RIGHT]
    ctx = Context(engine, engine.state.actors[LEFT], action, None, action.parameters["typed"], [subject], subject, {})
    mechanics = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
    rows = list(teleport_rows(mechanics))
    assert rows
    original = json.loads(subprocess.check_output(
        ["git", "show", "c4326a2c:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"], cwd=ROOT))["mechanics"]
    original_rows = dict(teleport_rows(original))
    assert set(original_rows) == {path for path, _ in rows}
    opted = []
    for path, row in rows:
        if row.get("choose_subject_destination"):
            opted.append(path)
        else:
            assert row == original_rows[path], path
            assert reposition(ctx, row) is None, path
    assert opted == ["/tianxia.talent.space.spatial_displacement/effects/0/on_fail/0"]


@pytest.mark.parametrize("route", ["away_back", "intermediate"])
def test_nested_anchor_loss_is_final_after_table_commit_reload(tmp_path, monkeypatch, route):
    combat, table, mid = table_fight(tmp_path, ["TAL_SCOUNDREL_BOB_AND_WEAVE"], ally_talents=[])
    group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"].casefold() == "bob and weave")
    cid = group["options"][0]["candidate_id"]
    answers = []
    for _ in range(12):
        result = send(table, mid, cid, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        suffix = prompt["context"]["reaction_source_id"].rsplit(".", 1)[-1]
        wanted = {"bob_and_weave": ALLY, "bob_and_weave_willing": "accept", "bob_and_weave_covers": "yes"}[suffix]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [wanted]})
    assert result["status"] == "COMMITTED"
    assert any(c.condition_id == ANCHOR for c in combat._load_session(mid).engine.state.actors[LEFT].conditions.values())

    def triggered_move(engine, event_type, kwargs):
        if event_type != "HOLD_POSITION_COMMITTED":
            return
        anchor = engine.state.actors[ALLY]
        origin = anchor.position
        away = Position(x=0, y=0)
        paths = [(origin, away), (away, origin)] if route == "away_back" else [(origin, away, origin)]
        for path in paths:
            anchor.position = path[-1]
            engine._append_event("MOVEMENT_COMMITTED", "test:nested-anchor", actor_id=ALLY,
                                 payload={"path": [p.model_dump() for p in path], "cost_ft": 0,
                                          "origin": path[0].model_dump(), "destination": path[-1].model_dump(),
                                          "movement_remaining_ft": anchor.movement_remaining_ft})

    # A real event subscriber emits child events inside an accepted transaction;
    # no engine method is replaced. Rollback/replay sees the same subscriber.
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS["event"], triggered_move])
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[ALLY].position == Position(x=3, y=5)
    assert not any(c.condition_id == ANCHOR for c in loaded.engine.state.actors[LEFT].conditions.values())
    removed = [e for e in loaded.engine.events if e.event_type == "CONDITION_REMOVED" and e.payload.get("condition_id") == ANCHOR]
    assert len(removed) == 1
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_r1_regressions_fail_without_each_fix(tmp_path):
    """Sparse source overlay, no checkout copy or mutation of production files.

    Reverse only the two r1 plug-in fixes and the two original Water selector
    additions. All seven positive tests must fail at their behavior assertion.
    """
    root = tmp_path / "before" / "APP"
    root.mkdir(parents=True)
    changed = {"combat/ext/subject_repositioning.py", "combat/ext/scoundrel_riders.py",
               "combat/factory_compiler.py",  # __file__.resolve() must bind overlay authority
               "authority/Tianxia_Typed_Mechanics_Authority_R1.json"}
    dirs = {Path(p).parent for p in changed} | {Path(".")}
    dirs |= {parent for d in list(dirs) for parent in d.parents}

    def stage(relative):
        for path in (ROOT / relative).iterdir():
            rel = relative / path.name
            dest = root / rel
            if path.name == "__pycache__":
                continue
            if rel in dirs:
                dest.mkdir()
                stage(rel)
            elif str(rel) in changed:
                blob = subprocess.check_output(["git", "show", f"3b597c0b:APP/{rel}"], cwd=ROOT)
                if str(rel).startswith("authority/"):
                    authority = json.loads(blob)
                    for ability in ("TAL_WATER_TIDAL_WAVE", "TAL_WATER_WAVE_BURST"):
                        effects = authority["mechanics"][ability]["modifier"]["effects"]
                        effects[:] = [e for e in effects if e.get("type") != "rider_choose_area_recipients"]
                    blob = json.dumps(authority).encode()
                dest.write_bytes(blob)
            else:
                dest.symlink_to(path, target_is_directory=path.is_dir())

    stage(Path("."))
    code = "import sys;sys.path.insert(0,sys.argv[1]);import combat.factory_compiler;import pytest;raise SystemExit(pytest.main(sys.argv[2:]))"
    result = subprocess.run([sys.executable, "-c", code, str(root), "-q", "--tb=short", "-p", "no:cacheprovider",
                             f"--basetemp={tmp_path / 'negative-pytest'}", str(Path(__file__)),
                             "-k", "not regressions_fail"], cwd=root, capture_output=True, text=True,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "7 failed" in result.stdout and "ERROR collecting" not in result.stdout, result.stdout + result.stderr
    assert "KeyError" not in result.stdout and "CombatServiceError" not in result.stdout, result.stdout


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("ability,label", [("TAL_WATER_TIDAL_WAVE", "Tidal Wave"), ("TAL_WATER_WAVE_BURST", "Wave Burst")])
def test_water_modifier_recipient_choices_through_table_reload(tmp_path, monkeypatch, mode, ability, label):
    combat, table, mid = table_fight(tmp_path, [ability], ally_talents=[],
                                   control_modes={LEFT: mode, ALLY: "MANUAL", RIGHT: "MANUAL"})
    fixed_dice(monkeypatch, [1] * 100)
    engine = combat._load_session(mid).engine
    def unaffected(a):
        # Shape Current itself requires Concentration; that caster condition
        # is legitimate. The modifier must not damage, push or mark friends.
        return a.current_hp, a.position, {c.condition_id for c in a.conditions.values()
                                         if c.condition_id != "condition:typed.concentration_deadline"}
    before = {a.entity_id: unaffected(a) for a in engine.state.actors.values()}
    name = "Shape Current: Flowing Current + " + label
    destination = Position(x=4, y=4)
    if mode == "LOCAL_AUTO":
        result = automatic_action(combat, mid, name, destination=destination)
    else:
        group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"] == name)
        option = next(o for o in group["options"] if o.get("destination") == {"x": 4, "y": 4})
        result = send(table, mid, option["candidate_id"])
    answers, choices = [], []
    for _ in range(20):
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        if prompt["context"]["reaction_source_id"] == "choice:needle.area_recipients":
            choices.append(prompt)
            assert label in prompt["moment"]
            assert {LEFT, ALLY, RIGHT} <= {o["id"] for o in prompt["choice"]["options"]}
            answers.append({**prompt["context"], "selection": "USE", "option_ids": [RIGHT]})
        else:
            answers.append({**prompt["context"], "selection": "DECLINE"})
        fresh = CombatService(ROOT, tmp_path)
        assert not any(e.event_type == "SAVE_ROLLED" for e in fresh._load_session(mid).engine.events)
        table = TabletopService(fresh, tmp_path)
        result = send(table, mid, option["candidate_id"], answers)
    assert result["status"] == "COMMITTED", result
    assert len(choices) == (1 if mode == "MANUAL" else 0)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    saves = [e for e in loaded.engine.events if e.event_type == "SAVE_ROLLED"]
    assert {e.actor_id for e in saves} == {RIGHT}
    for who in (LEFT, ALLY):
        a = loaded.engine.state.actors[who]
        assert unaffected(a) == before[who]
    assert any("soaked" in c.condition_id.casefold() for c in loaded.engine.state.actors[RIGHT].conditions.values())
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
