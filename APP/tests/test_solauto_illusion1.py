"""Public synthetic Illusion rider regressions through real committed tables."""
import json
from pathlib import Path

import pytest

from combat.ext import figment, placed
from combat.ext.illusion_riders import SUBSTANTIAL
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, turn, resolve
from tests.test_auto41_illusion import cell_action, answer


def mechanics():
    return json.loads((Path(__file__).resolve().parents[1] / "authority" /
                       "Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]


def investigation(bundle):
    if bundle["actor_template"]["entity_id"] == RIGHT:
        bundle["actor_template"].setdefault("skills", {})["Investigation"] = 200
        bundle.setdefault("skills", {})["Investigation"] = 200


@pytest.mark.parametrize("hold,cost", [("grappled", 3), ("restrained", 5)])
@pytest.mark.parametrize("path", ["action", "free", "study"])
def test_substantial_study_recognizes_exact_figment(tmp_path, hold, cost, path):
    combat, table, mid = fight(tmp_path, [SUBSTANTIAL, figment.POTENT],
        spheres=[figment.SPHERE], bundle_edit=investigation)
    assert act(table, mid, "Figment: Potent Phantasm, Deafened (1 CP)")["status"] == "COMMITTED"
    label = f"Create Figment + Substantial Phantasm ({cost} CP; {hold.title()})"
    send = lambda answers: cell_action(table, mid, label, (4, 6), answers)
    result = send([])
    assert result["status"] == "REACTION_REQUIRED"
    assert send([answer(result, [RIGHT])])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    zone, = placed.of(engine, "figment")
    held, = [c for c in engine.state.actors[RIGHT].conditions.values()
             if c.condition_id == "condition:typed." + hold]
    assert engine.state.actors[LEFT].resources["resource:core.qi"] == 100 - cost - 1
    turn(table, mid, RIGHT)
    if path == "action":
        resolve(lambda answers: act(table, mid, "Break free", answers))
    elif path == "study":
        result = act(table, mid, "Study an illusion")
        assert act(table, mid, "Study an illusion", [answer(result, [zone.zone_id])])["status"] == "COMMITTED"
    else:
        resolve(lambda answers: act(table, mid, "end", answers))
    engine = reload(combat, mid)
    zone, = placed.of(engine, "figment")
    assert placed.data(zone)["recognized"] == [RIGHT]
    assert placed.data(zone)["studied"] == [RIGHT]
    assert held.instance_id not in engine.state.actors[RIGHT].conditions
    assert held.data["figment_zone"] == zone.zone_id
    check, = [e for e in engine.events if e.event_type == "CHECK_ROLLED"]
    assert check.payload["actor"]["modifier"] == 200
    assert check.payload["success"] is True
    assert mechanics()[SUBSTANTIAL]["riders"] == []
    # A later turn still runs Potent Phantasm, with successful-Study Advantage.
    turn(table, mid, LEFT)
    assert cell_action(table, mid, "Keep a figment without Concentration (2 CP)", (4, 6))["status"] == "COMMITTED"
    assert cell_action(table, mid, "Create Figment", (9, 6))["status"] == "COMMITTED"
    engine = reload(combat, mid)
    zones = placed.of(engine, "figment")
    assert placed.data(zones[0])["studied"] == [RIGHT]
    assert placed.data(zones[1])["recognized"] == []
    turn(table, mid, RIGHT)
    saves = [e for e in reload(combat, mid).events
             if e.event_type == "SAVE_ROLLED" and e.actor_id == RIGHT]
    assert saves[-1].payload["mode"] == "ADVANTAGE"


def test_failed_substantial_study_keeps_hold_and_does_not_recognize(tmp_path):
    def edit(bundle):
        if bundle["actor_template"]["entity_id"] == RIGHT:
            bundle["actor_template"].setdefault("skills", {})["Investigation"] = -200
            bundle.setdefault("skills", {})["Investigation"] = -200
    combat, table, mid = fight(tmp_path, [SUBSTANTIAL], spheres=[figment.SPHERE], bundle_edit=edit)
    label = "Create Figment + Substantial Phantasm (3 CP; Grappled)"
    result = cell_action(table, mid, label, (4, 6))
    assert cell_action(table, mid, label, (4, 6), [answer(result, [RIGHT])])["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    resolve(lambda answers: act(table, mid, "Break free", answers))
    engine = reload(combat, mid)
    zone, = placed.of(engine, "figment")
    assert placed.data(zone)["recognized"] == []
    assert placed.data(zone)["studied"] == []
    assert any(c.condition_id == "condition:typed.grappled" for c in engine.state.actors[RIGHT].conditions.values())
    check, = [e for e in engine.events if e.event_type == "CHECK_ROLLED"]
    assert check.payload["actor"]["modifier"] == -200
    assert check.payload["success"] is False


def test_control_figment_existing_check_retires_stale_rider(tmp_path):
    combat, table, mid = fight(tmp_path, spheres=[figment.SPHERE],
        right_talents=[figment.CONTROL], right_spheres=[figment.SPHERE], left_save_dc=1)
    assert cell_action(table, mid, "Create Figment", (7, 6))["status"] == "COMMITTED"
    before, = placed.of(reload(combat, mid), "figment")
    original = {key: placed.data(before)[key] for key in ("creator", "cl", "size_ft", "senses", "save_dc")}
    turn(table, mid, RIGHT)
    assert cell_action(table, mid, "Control Figment (1 CP)", (7, 6))["status"] == "COMMITTED"
    engine = reload(combat, mid)
    zone, = placed.of(engine, "figment")
    assert placed.data(zone)["controller"] == RIGHT
    assert all(placed.data(zone)[key] == value for key, value in original.items())
    assert engine.state.actors[RIGHT].resources["resource:core.qi"] == 99
    assert engine.state.actors[RIGHT].concentration is not None
    check, = [e for e in engine.events if e.event_type == "CHECK_ROLLED"]
    assert check.payload["success"] is True
    assert check.payload["actor"]["modifier"] == 6


@pytest.mark.parametrize("hold,cost", [("grappled", 3), ("restrained", 5)])
def test_break_free_by_substantial_hold_recognizes_figment(tmp_path, hold, cost):
    """Breaking free of a Substantial Phantasm hold with the Study check frees the creature AND recognizes the figment."""
    combat, table, mid = fight(tmp_path, [SUBSTANTIAL, figment.POTENT],
        spheres=[figment.SPHERE], bundle_edit=investigation)
    assert act(table, mid, "Figment: Potent Phantasm, Deafened (1 CP)")["status"] == "COMMITTED"
    label = f"Create Figment + Substantial Phantasm ({cost} CP; {hold.title()})"
    result = cell_action(table, mid, label, (4, 6))
    assert cell_action(table, mid, label, (4, 6), [answer(result, [RIGHT])])["status"] == "COMMITTED"
    turn(table, mid, RIGHT)
    resolve(lambda answers: act(table, mid, "Break free", answers))
    engine = reload(combat, mid)
    zone, = placed.of(engine, "figment")
    assert not any(c.condition_id == "condition:typed." + hold
                   for c in engine.state.actors[RIGHT].conditions.values())
    assert RIGHT in placed.data(zone)["recognized"]
    assert RIGHT in placed.data(zone)["studied"]
    check, = [e for e in engine.events if e.event_type == "CHECK_ROLLED"]
    assert check.payload["success"] is True
