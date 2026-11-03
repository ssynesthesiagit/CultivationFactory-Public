"""Review-round regressions: explicit rows, nested expiry and Water choices."""
import json
import hashlib
from pathlib import Path

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
    fixture = json.loads((Path(__file__).parent / "fixtures/typed_teleport_rows_c4326a2c.json").read_text())
    assert fixture["_source_commit"] == "c4326a2c"
    original_rows = fixture["teleport_row_sha256"]
    assert fixture["_runtime_field_updates_commit"] == "96b20b47cadad4a06e8a73ee152016118269b92b"
    assert set(original_rows) == {path for path, _ in rows}
    opted = []
    for path, row in rows:
        if row.get("choose_subject_destination"):
            opted.append(path)
        else:
            encoded = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
            assert hashlib.sha256(encoded).hexdigest() == original_rows[path], path
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
        option = next(o for o in group["options"]
                      if (o.get("destination") or {}).get("x") == destination.x
                      and (o.get("destination") or {}).get("y") == destination.y
                      and (o.get("destination") or {}).get("z", 0) == destination.z)
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

