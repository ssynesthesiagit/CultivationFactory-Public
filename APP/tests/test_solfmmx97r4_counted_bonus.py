"""One use bonus selects a damage-roll occurrence, not every hit of an attack node."""
import copy

import pytest

from combat.factory_compiler import _attach
from tests.test_solfmmx97r2_damage_stages import damage, dealt, execute, save
from tests.test_typed_executor import _engine_with, _intent


@pytest.mark.parametrize("kind", ["damage", "extra_damage"])
@pytest.mark.parametrize("scaled", [False, True])
@pytest.mark.parametrize("initial_miss", [False, True])
def test_counted_strikes_spend_bonus_on_first_hit_only(kind, scaled, initial_miss):
    attack = {"type": "attack", "attack_kind": "cultivation_melee",
              "on_hit": [damage(10)], "on_miss": []}
    attack.update({"count_by_cl": [[1, 20, 3]]} if scaled else {"count": 2})
    if initial_miss:
        attack["first_roll_bonus"] = -200

    def run(bonus):
        rider = {"type": kind, "formula": "pb", "applies_to": "target"}
        effects = _attach([copy.deepcopy(attack)], [rider], "use") if bonus else [copy.deepcopy(attack)]
        engine, actor = _engine_with({"effects": effects, "numbers": {"pb": 6, "cl": 5,
                                                                     "attack_bonus": 100}}, "SOLFMMX97R4")
        candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
        target = engine.state.actors[candidate.target_ids[0]]
        target.maximum_hp = target.current_hp = 1000
        target.temporary_hp = 0
        before = len(engine.events)
        engine.execute_intent(_intent(candidate))
        return target.entity_id, engine.events[before:]

    target, events = run(True)
    other, control = run(False)
    attacks = [e for e in events if e.event_type == "ATTACK_ROLLED"]
    assert len(attacks) == (3 if scaled else 2)
    assert [e.payload["provisional_hit"] for e in attacks] == ([False] if initial_miss else [True]) + [True] * (len(attacks) - 1)
    assert dealt(events, target) - dealt(control, other) == 6
    packets = [e for e in events if e.event_type == "DAMAGE_COMMITTED"
               and target in e.target_ids and e.payload["hp_damage"] == 6]
    assert len(packets) == 1
    if initial_miss:
        assert not any(e.event_type == "DAMAGE_COMMITTED" for e in events[:events.index(attacks[1])])


@pytest.mark.parametrize("kind", ["damage", "extra_damage"])
@pytest.mark.parametrize("outcome", ["failure", "success", "mixed"])
def test_area_save_recipients_keep_the_same_bonus_roll(kind, outcome):
    branch = save()
    branch["on_success"] = [{"type": "half_damage"}]
    rider = {"type": kind, "dice": {"count": 1, "sides": 100}, "applies_to": "target"}
    effects = _attach([branch], [rider], "use")
    engine, actor = _engine_with({"effects": effects, "numbers": {"save_dc": 15},
                                 "area": {"shape": "sphere", "size_ft": 500,
                                          "centered_on_self": True, "recipients": "enemies"}}, "SOLFMMX97R4-AREA")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    for subject in engine.state.actors.values():
        subject.maximum_hp = subject.current_hp = 1000
        subject.temporary_hp = 0
    opponents = [who for who in engine.state.actors if who != actor]
    outcomes = {who: outcome for who in opponents}
    if outcome == "mixed":
        outcomes = {who: "failure" if index == 0 else "success" for index, who in enumerate(opponents)}
    engine._typed_roll_outcome = outcomes.copy()
    before = len(engine.events)
    engine.execute_intent(_intent(candidate))
    events = engine.events[before:]
    recipients = [e.actor_id for e in events if e.event_type == "SAVE_ROLLED"]
    assert len(recipients) > 1
    totals = [dealt(events, who) for who in recipients]
    if outcome == "mixed":
        full = next(dealt(events, who) - 20 for who in recipients if outcomes[who] == "failure")
        halves = [dealt(events, who) - 10 for who in recipients if outcomes[who] == "success"]
        assert halves and full > 0
        assert halves == [full // 2 if kind == "damage" else full] * len(halves)
        return
    assert len(set(totals)) == 1
    assert totals[0] > (20 if outcome == "failure" else 10)


@pytest.mark.parametrize("kind", ["damage", "extra_damage"])
def test_nested_counted_strikes_do_not_reuse_outer_bonus(kind):
    nested = {"type": "attack", "attack_kind": "cultivation_melee", "count": 2,
              "on_hit": [damage(10)], "on_miss": []}
    outer = {"type": "attack", "attack_kind": "cultivation_melee", "count": 2,
             "on_hit": [damage(10), nested], "on_miss": []}
    _, _, target, events = execute([outer], hit=True, kind=kind)
    _, _, other, control = execute([outer], hit=True, kind=kind, bonus=False)
    assert dealt(events, target) - dealt(control, other) == 6
