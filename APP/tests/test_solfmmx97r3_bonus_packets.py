"""Action-level authoring controls for modifier prices and bonus-only attacks."""
import copy

import pytest

from combat.factory_compiler import _attach
from tests.test_solfmmx97r2_damage_stages import damage, dealt, execute, save
from tests.test_typed_executor import _engine_with, _intent


@pytest.mark.parametrize("outcome", ["success", "failure"])
@pytest.mark.parametrize("area", [False, True])
def test_modifier_self_cost_is_paid_once_even_with_multiple_save_recipients(outcome, area):
    cost = damage(10, "self")
    bonus = {"type": "extra_damage", "formula": "pb", "applies_to": "target"}
    tree = _attach([save()], [cost, bonus], "use")
    typed = {"effects": tree, "numbers": {"pb": 6, "save_dc": 15}}
    if area:
        typed["area"] = {"shape": "sphere", "size_ft": 500, "centered_on_self": True,
                         "recipients": "enemies"}
    engine, actor = _engine_with(typed, "SOLFMMX97R3-COST")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    for subject in engine.state.actors.values():
        subject.maximum_hp = subject.current_hp = 1000
        subject.temporary_hp = 0
    engine._typed_roll_outcome = {who: outcome for who in engine.state.actors if who != actor}
    before = len(engine.events)
    engine.execute_intent(_intent(candidate))
    events = engine.events[before:]
    saves = [e for e in events if e.event_type == "SAVE_ROLLED"]
    assert len(saves) > 1 if area else len(saves) == 1
    assert dealt(events, actor) == 10
    costs = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and actor in e.target_ids]
    assert len(costs) == 1
    for event in saves:
        assert dealt(events, event.actor_id) == (26 if outcome == "failure" else 0)


@pytest.mark.parametrize("kind", ["damage", "extra_damage"])
@pytest.mark.parametrize("hit", [True, False])
@pytest.mark.parametrize("sequential", [False, True])
def test_extra_damage_only_attacks_do_not_promote_a_use_bonus_to_primary(kind, hit, sequential):
    attack = {"type": "attack", "attack_kind": "cultivation_melee",
              "on_hit": [{"type": "extra_damage", "flat": 10, "applies_to": "target"}],
              "on_miss": []}
    effects = [attack, copy.deepcopy(attack)] if sequential else [attack]
    _, _, target, events = execute(effects, hit=hit, kind=kind)
    _, _, other, control = execute(effects, hit=hit, kind=kind, bonus=False)
    assert dealt(events, target) - dealt(control, other) == (6 if hit else 0)
    packets = [e for e in events if e.event_type == "DAMAGE_COMMITTED"
               and target in e.target_ids and e.payload["hp_damage"] == 6]
    assert len(packets) == int(hit)
