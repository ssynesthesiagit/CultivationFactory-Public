"""A menu on 2026-11-14 took 13–90 s: every candidate re-derived weapons and grips.

One menu made 1,461 available_weapons calls and 2.46 million carry.item_of
calls. Weapon facts must be computed once per key, not once per candidate.
"""
from collections import Counter

from combat import weapon_delivery
from combat.ext import hand_occupancy
from combat.ext.equipment_hands import set_weapon_readiness
from tests.hunt51_grapple_support import fight, on_turn
from tests.test_starting_loadout import W, SHIELD


def test_weapon_facts_are_shared_only_within_each_candidate_pass(tmp_path, monkeypatch):
    user, service, table, match, ids = fight(
        tmp_path, "weapon-facts", equipment=(W + "jian", W + "qiang", SHIELD),
        wielded=(W + "jian",))
    on_turn(table, match, ids[0])
    engine = service._load_session(match).engine
    actor = engine.state.actors[ids[0]]
    weapon = next(key for key in hand_occupancy.weapon_grips(engine, actor) if key.endswith(".weapon.jian"))
    weapons = weapon_delivery.available_weapons(engine, actor)
    assert len(weapons) >= 2
    assert any("Two-Handed" in (a.parameters["typed"]["weapon"].get("properties") or "")
               or "Versatile" in (a.parameters["typed"]["weapon"].get("properties") or "")
               for a in weapons.values())

    weapon_reads, grip_reads = Counter(), Counter()
    original_weapons, original_grips = weapon_delivery._available_weapons, hand_occupancy._weapon_grips

    def count_weapons(engine, actor, words=(), *, include_busy=False, include_native=False):
        weapon_reads[(id(actor), tuple(words), include_busy, include_native)] += 1
        return original_weapons(engine, actor, words, include_busy=include_busy, include_native=include_native)

    def count_grips(engine, actor):
        grip_reads[id(actor)] += 1
        return original_grips(engine, actor)

    monkeypatch.setattr(weapon_delivery, "_available_weapons", count_weapons)
    monkeypatch.setattr(hand_occupancy, "_weapon_grips", count_grips)

    def pass_once():
        weapon_reads.clear()
        grip_reads.clear()
        candidates = engine.legal_candidates()
        own = {key: count for key, count in weapon_reads.items() if key[0] == id(actor)}
        assert own and all(count == 1 for count in own.values())
        assert grip_reads[id(actor)] == 1
        return candidates

    first = pass_once()
    assert any(c.source_definition_id == weapon for c in first)
    set_weapon_readiness(engine, actor, weapon, False, source="test:stow", source_actor_id=actor.entity_id)
    assert engine.events[-1].event_type == "EQUIPMENT_READINESS_SET"
    second = pass_once()
    assert not any(c.source_definition_id == weapon for c in second)

    weapon_reads.clear()
    grip_reads.clear()
    for _ in range(2):
        weapon_delivery.available_weapons(engine, actor)
        hand_occupancy.weapon_grips(engine, actor)
    assert weapon_reads[(id(actor), (), False, False)] == 2
    assert grip_reads[id(actor)] == 2
