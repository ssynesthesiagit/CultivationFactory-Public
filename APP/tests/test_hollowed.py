"""Hollowed (Void, Sphere Compendium): no CP/Stamina regain, no Temporary HP, no ordinary Invisible, for as long as it lasts
(owner 2026-09-29: it showed "No automatic effect")."""

from combat import typed_executor
from combat.condition_text import all_conditions
from tests.test_effect_durations import _conditions, _ctx, _end_turn, _fight

HOLLOW = {"type": "condition", "condition": "hollowed", "applies_to": "target",
          "evidence": "The target becomes Hollowed until the start of your next turn."}


def _hollow():
    engine, me, foe = _fight("HOLLOWED")
    typed_executor.run_effects(_ctx(engine, me, foe), [HOLLOW])
    return engine, me, foe


def test_hollowed_brings_its_rules_for_as_long_as_it_lasts():
    engine, me, foe = _hollow()
    hollowed, no_temp, no_invisible = (_conditions(foe, name) for name in ("hollowed", "no_temp_hp", "no_invisible"))
    assert len(hollowed) == len(no_temp) == len(no_invisible) == 1
    assert hollowed[0].expires_on == no_temp[0].expires_on == no_invisible[0].expires_on
    assert _end_turn(engine) != me.entity_id  # the Hollowed creature's turn: still Hollowed
    assert _conditions(foe, "hollowed") and _conditions(foe, "no_temp_hp")
    while _end_turn(engine) != me.entity_id:  # "until the start of your next turn": all three go together
        pass
    assert not _conditions(foe, "hollowed") and not _conditions(foe, "no_temp_hp") and not _conditions(foe, "no_invisible")


def test_a_hollowed_creature_gains_no_temporary_hp_and_regains_no_cp():
    engine, me, foe = _fight("HOLLOWED")
    typed_executor.run_effects(_ctx(engine, foe, me), [HOLLOW])  # the user with the Path pools is the one Hollowed
    temp_before = me.temporary_hp
    typed_executor.run_effects(_ctx(engine, me, me), [{"type": "temp_hp", "applies_to": "self", "flat": 5}])
    assert me.temporary_hp == temp_before
    pool = next(resource for resource in me.resources if resource in typed_executor.CP_POOLS)
    me.resources[pool] = 0
    typed_executor.run_effects(_ctx(engine, me, me), [{"type": "gain_resource", "applies_to": "self", "resource": pool, "amount": 2}])
    assert me.resources[pool] == 0


def test_the_table_explains_hollowed():
    row = all_conditions()["hollowed"]
    assert row["automated"] and "It can't gain Temporary Hit Points" in row["mechanics"] and "Void" in row["reading"]
