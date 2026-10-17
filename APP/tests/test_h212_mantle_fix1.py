"""HUNT212 #2: native unarmed Fist / melee-weapon Conductive hit producers.

Kept in its own file because public CI currently expands node selections to
whole files. Shared deterministic setup comes from test_h212_fix1.
"""
import pytest

from tests.test_h212_fix1 import L, prepare, events
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, reload, turn

BODY = L + "LIGHTNING_GOD_BODY"
MANTLE = L + "TRUE_LIGHTNING_GOD_MANTLE"
FIST = L + "ELECTRIC_FIST_METHOD"
CONDUCTIVE = L + "CONDUCTIVE_STRIKE"


def mantle_rolls(engine):
    return [e for e in events(engine, "DAMAGE_ROLLED")
            if e.payload["expression"].startswith(("1d8", "2d8")) and "True Lightning-God Mantle" in
            engine.action_catalog[e.source_definition_id].display_name]


def method_hit(combat, table, mid, tmp_path, fist):
    """A confirmed legal melee hit, with actual Fist execution asserted."""
    for _ in range(3):
        engine = reload(tmp_path, mid)
        before = len(engine.events)
        count = len(mantle_rolls(engine))
        def matches(c):
            action = engine.action_catalog.get(c.source_definition_id)
            if c.target_ids != (FOE,) or action is None:
                return False
            typed = action.parameters.get("typed") or {}
            return typed.get("range_ft", "missing") is None and (
                action.display_name == "Unarmed Strike" if fist else action.display_name.startswith("Dao"))
        hit = next(c for c in engine.legal_candidates() if matches(c))
        action = engine.action_catalog[hit.source_definition_id]
        prompts = settle(table, mid, hit.candidate_id, picks={"choice:needle.electric_fist": "SHOCK"})
        engine = reload(tmp_path, mid)
        after = engine.events[before:]
        attacks = [e for e in after if e.event_type == "ATTACK_ROLLED"
                   and e.source_definition_id == hit.source_definition_id]
        assert attacks, action.display_name
        if any(e.payload.get("provisional_hit") for e in attacks):
            if fist:
                assert any(e.event_type == "SAVE_ROLLED" and e.source_definition_id == FIST for e in after), (
                    action.display_name, action.parameters["typed"].get("range_ft"),
                    [(p["context"]["reaction_source_id"], p.get("reaction")) for p in prompts],
                    [(e.event_type, e.source_definition_id) for e in after])
            return hit
        assert len(mantle_rolls(engine)) == count, "A miss must not spend the Mantle bonus"
        turn(table, mid, FOE)
        turn(table, mid, OWNER)
    raise AssertionError("Three seeded attacks missed")


@pytest.mark.parametrize("strike", ["Electric Fist Method", "Conductive Strike"])
def test_mantle_first_qualifying_hit_each_turn_survives_reload(tmp_path, strike):
    # "Your first Electric Fist Method or Conductive Strike hit each turn
    # deals additional lightning damage equal to 1d8."
    fist = strike == "Electric Fist Method"
    combat, table, mid = fixture(tmp_path, [BODY, MANTLE, FIST if fist else CONDUCTIVE], owner_kit={"starting_kit": {
        "items": [{"item_id": "tianxia.mortal.weapon.dao"}]}},
        bundle_transform=prepare, foe_position={"x": 4, "y": 7}, seed="H212-MANTLE-" + strike)
    settle(table, mid, candidate(combat, mid, "Lightning-God Body + True Lightning-God Mantle").candidate_id)
    engine = reload(tmp_path, mid)
    assert not mantle_rolls(engine), "Mantle never rolls targetless damage on activation"
    assert any(m.target_field == "typed_on_hit" and "Your first" in str(m.value)
               for m in engine.state.actors[OWNER].modifiers.values())
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Lightning Lash: Jolt", target=FOE).candidate_id)
    assert not mantle_rolls(reload(tmp_path, mid))
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    hit = method_hit(combat, table, mid, tmp_path, fist)
    engine = reload(tmp_path, mid)
    rolls = mantle_rolls(engine)
    assert len(rolls) == 1, [(e.event_type, e.source_definition_id, e.payload.get("expression"), e.payload.get("total"))
                             for e in engine.events if e.event_type in {"DAMAGE_ROLLED", "SAVE_ROLLED"}]
    dealt = [e for e in events(engine, "DAMAGE_COMMITTED", rolls[0].source_definition_id)
             if e.sequence > rolls[0].sequence and FOE in e.target_ids]
    assert any(e.payload["damage_type"] == "LIGHTNING" and e.payload["hp_damage"] == rolls[0].payload["total"] for e in dealt)
    assert any(e.payload.get("provisional_hit") for e in events(engine, "ATTACK_ROLLED", hit.source_definition_id))
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    method_hit(combat, table, mid, tmp_path, fist)
    assert len(mantle_rolls(reload(tmp_path, mid))) == 2
