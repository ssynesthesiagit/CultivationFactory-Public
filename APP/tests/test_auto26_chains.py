"""Printed armor/anchor consequences survive normal table persistence."""
import pytest

from combat.ext.chains_sphere import ARMOR, INCARNATION, ANCHOR
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, turn, action_sender


def cast(combat, table, mid, name, *, ai=False, damage_type="BLUDGEONING"):
    send = action_sender(combat, table, mid, name, ai=ai)
    result = send([])
    if name == "Chain Armor" and not ai:
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert "Chain Armor" in str(prompt) and "3 cultivation points" in str(prompt)
        option = next(o for o in prompt["choice"]["options"] if o["id"] == damage_type)
        result = send([{**prompt["context"], "selection": "USE", "option_ids": [option["id"]]}])
    assert result["status"] == "COMMITTED", result
    if ai:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="MANUAL")


@pytest.mark.parametrize("talent,name,reduction,ai", [
    (ARMOR, "Chain Armor", 10, False), (ARMOR, "Chain Armor", 10, True),
    (INCARNATION, "Chain-Sovereign Incarnation", 20, False),
])
def test_chains_protection_reduces_push_after_commit_reload(tmp_path, talent, name, reduction, ai):
    combat, table, mid = fight(tmp_path, [talent], cause=[
        {"type": "forced_movement", "direction": "away", "distance_ft": 20, "applies_to": "target"},
    ], positions={LEFT: {"x": 4, "y": 8}, RIGHT: {"x": 4, "y": 7}})
    cast(combat, table, mid, name, ai=ai)
    engine = reload(combat, mid)
    row = next(c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == ANCHOR)
    assert row.data["reduction_ft"] == reduction
    assert all(type(v) in (int, str) for v in row.data.values())
    turn(table, mid, RIGHT)
    before = reload(combat, mid).state.actors[LEFT].position
    assert act(table, mid, "Cause", target_id=LEFT)["status"] == "COMMITTED"
    after = reload(combat, mid).state.actors[LEFT].position
    assert after.x == before.x and after.y - before.y == (20 - reduction) // 5


@pytest.mark.parametrize("damage_type", ["BLUDGEONING", "SLASHING"])
def test_chain_armor_damages_its_grappler_at_turn_start(tmp_path, damage_type):
    combat, table, mid = fight(tmp_path, [ARMOR], cause=[
        {"type": "condition", "condition": "grappled", "applies_to": "target", "duration": "until_removed"},
    ])
    cast(combat, table, mid, "Chain Armor", damage_type=damage_type)
    turn(table, mid, RIGHT)
    assert act(table, mid, "Cause", target_id=LEFT)["status"] == "COMMITTED"
    before = reload(combat, mid).state.actors[RIGHT].current_hp
    turn(table, mid, LEFT)
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].current_hp == before - engine.state.actors[LEFT].proficiency_bonus
    packets = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == ARMOR]
    assert len(packets) == 1
    assert packets[0].payload["damage_type"] == damage_type


def test_unowned_chain_armor_does_not_damage_grappler(tmp_path):
    combat, table, mid = fight(tmp_path, cause=[
        {"type": "condition", "condition": "grappled", "applies_to": "target", "duration": "until_removed"},
    ])
    turn(table, mid, RIGHT)
    assert act(table, mid, "Cause", target_id=LEFT)["status"] == "COMMITTED"
    before = reload(combat, mid).state.actors[RIGHT].current_hp
    turn(table, mid, LEFT)
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].current_hp == before
    assert not any(e.source_definition_id == ARMOR for e in engine.events)


@pytest.mark.parametrize("owns", [False, True])
def test_sovereign_prone_immunity_is_active_and_persistent(tmp_path, owns):
    combat, table, mid = fight(tmp_path, [INCARNATION] if owns else [], cause=[
        {"type": "condition", "condition": "prone", "applies_to": "target", "duration": "until_removed"},
    ])
    if owns:
        cast(combat, table, mid, "Chain-Sovereign Incarnation")
        reload(combat, mid)
    turn(table, mid, RIGHT)
    assert act(table, mid, "Cause", target_id=LEFT)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert any(c.condition_id.endswith(".prone") for c in engine.state.actors[LEFT].conditions.values()) == (not owns)


def test_chain_armor_protection_ends_with_concentration(tmp_path):
    combat, table, mid = fight(tmp_path, [ARMOR], cause=[
        {"type": "damage", "flat": 100, "damage_type": "FORCE", "applies_to": "target"},
    ])
    cast(combat, table, mid, "Chain Armor")
    turn(table, mid, RIGHT)
    assert act(table, mid, "Cause", target_id=LEFT)["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert not any(c.condition_id == ANCHOR for c in engine.state.actors[LEFT].conditions.values())
