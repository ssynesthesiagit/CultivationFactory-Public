"""Typing pass 2026-09-28, the Life sphere's rider-only abilities ("automate every aspect before another playtest").

Restorative Mend, Deep Root Restoration and Life-Seal Reach were only GM rider text in a fight; Mend the Pulse never
grew past 1d8 at higher Realms and Read the Pulse could only target enemies (so no Pulse Seal could ever be placed on an
ally, which Life-Seal Reach needs). Each ability is compiled from a small Life sheet and run through a real engine with
a talent-less ally and one foe, checking that its effect actually lands."""

import copy
import json
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import CONDITION_PREFIX, mark_condition_id
from factory_authoring.typed_mechanics import dice_for_cl
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.life"
FRIEND = "actor:factory.life_friend"
QI = "resource:core.qi"
BASE_ABILITIES = ["LIFE_BASE_MEND_THE_PULSE", "LIFE_BASE_READ_THE_PULSE", "LIFE_BASE_PURIFY_THE_PULSE", "LIFE_BASE_BORROWED_BREATH"]


def _bundle(talents, cl=10):
    sheet = {**SHEET, "equipment": [], "identity": {**SHEET["identity"], "cultivation_level": cl},
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.life"],
                                     "automatic_sphere_component_record_ids": BASE_ABILITIES,
                                     "learned_talent_record_ids": [f"tianxia.talent.life.{talent}" for talent in talents]}}
    return compile_character(sheet, actor_id=ME)


def _friend_bundle():
    return compile_character({**SHEET, "equipment": [], "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}},
                             actor_id=FRIEND)


def _engine(talents=(), cl=10, friend_at=(4, 6), seed="LIFE", bundle=None):
    """The healer at (3, 6) on the 20 x 14 grid, an ally, and one foe far in the corner."""
    engine = Gate4ControllerEngine(
        ROOT, match_seed=seed, typed_bundles=(copy.deepcopy(bundle) if bundle else _bundle(talents, cl), _friend_bundle()),
        roster_setup={"primary_actor_ids": [ME, FRIEND, AN], "team_by_actor": {ME: "team:a", FRIEND: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FRIEND: {"x": friend_at[0], "y": friend_at[1]}, AN: {"x": 19, "y": 13}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _offered(engine, target):
    return {c.display_name for c in engine.legal_candidates() if tuple(c.target_ids) == (target,)}


def _do(engine, name, target):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name and tuple(c.target_ids) == (target,))
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _move(engine, actor_id, x, y):
    engine.state.actors[actor_id].position = Position(x=x, y=y)


def _afflict(engine, actor, *names):
    for name in names:
        engine._apply_condition(actor, CONDITION_PREFIX + name, "test:affliction", AN, expires_on="UNTIL_REMOVED")


def _conditions(actor):
    return sorted(condition.condition_id.removeprefix(CONDITION_PREFIX) for condition in actor.conditions.values())


def _row(bundle, name):
    return next(row for row in bundle["action_catalog"] if row["display_name"] == name)


def _healings(engine):
    return [event.payload for event in engine.events if event.event_type == "HEALING_APPLIED"]


def test_mend_the_pulse_dice_follow_the_printed_realm_table():
    # "Mortal: 1d8 ... Foundation: 2d8 ... Core Formation: 3d8 ... Nascent Soul: 4d8, each + your key ability modifier."
    # The typed healing effect was a flat 1d8 at every Realm.
    for cl, count in ((1, 1), (4, 1), (5, 2), (9, 2), (10, 3), (14, 3), (15, 4), (20, 4)):
        typed = _row(_bundle([], cl), "Mend the Pulse")["parameters"]["typed"]
        assert typed["numbers"]["cl"] == cl
        assert dice_for_cl(typed["effects"][0]["dice_by_cl"], cl) == {"count": count, "sides": 8}, cl


def test_mend_the_pulse_rolls_the_realm_dice_in_a_fight():
    bundle = _bundle([], 20)
    key_mod = _row(bundle, "Mend the Pulse")["parameters"]["typed"]["numbers"]["key_mod"]
    best = 0
    for seed in range(6):
        engine = _engine(cl=20, seed=f"MEND{seed}", bundle=bundle)
        ally = engine.state.actors[FRIEND]
        ally.current_hp = 1
        _do(engine, "Mend the Pulse", FRIEND)
        (healing,) = _healings(engine)
        assert 4 + key_mod <= healing["offered"] <= 32 + key_mod  # 4d8 + key ability modifier
        assert ally.current_hp == min(ally.maximum_hp, 1 + healing["offered"])
        best = max(best, healing["offered"])
    assert best > 8 + key_mod  # a single d8 could never reach this


def test_read_the_pulse_can_seal_an_ally_and_oneself():
    # Read the Pulse could only target an enemy, so a Pulse Seal could never be placed on an ally.
    engine = _engine(cl=10)
    ally = engine.state.actors[FRIEND]
    targets = {tuple(c.target_ids) for c in engine.legal_candidates() if c.display_name == "Read the Pulse"}
    assert {(FRIEND,), (ME,)} <= targets
    _do(engine, "Read the Pulse", FRIEND)
    assert mark_condition_id("Pulse Seal", ME) in {condition.condition_id for condition in ally.conditions.values()}


def test_life_seal_reach_range_follows_the_realm():
    # "within 30 feet ... At Core Formation Realm, this range becomes 60 feet. At Nascent Soul Realm ... 120 feet."
    seal = mark_condition_id("Pulse Seal", ME)
    for cl, feet in ((5, 30), (9, 30), (10, 60), (14, 60), (15, 120), (20, 120)):
        bundle = _bundle(["life_seal_reach"], cl)
        for base in ("Mend the Pulse", "Borrowed Breath", "Purify the Pulse: Remove Poisoned"):
            reach = _row(bundle, f"{base} + Life-Seal Reach")
            assert reach["range_ft"] == feet, (cl, base)
            assert reach["parameters"]["target_requires_condition"] == seal
            assert _row(bundle, base)["range_ft"] == 5  # the plain use is still touch


def test_life_seal_reach_heals_a_sealed_ally_at_range_and_never_an_unsealed_one():
    engine = _engine(["life_seal_reach"], cl=10, friend_at=(12, 6))  # 9 cells = 45 ft from the healer, inside Core Formation's 60 ft
    ally, me = engine.state.actors[FRIEND], engine.state.actors[ME]
    ally.current_hp = 10
    assert _offered(engine, FRIEND) == set()  # no Pulse Seal on the ally yet: touch only
    _move(engine, FRIEND, 4, 6)
    _do(engine, "Read the Pulse", FRIEND)
    _move(engine, FRIEND, 12, 6)
    assert _offered(engine, FRIEND) == {
        "Mend the Pulse + Life-Seal Reach", "Borrowed Breath + Life-Seal Reach", "Purify the Pulse: Remove Blinded + Life-Seal Reach",
        # Borrowed Breath's printed Lasting Breath option remains reachable
        # through the same seal extension; keep the complete exact menu.
        "Borrowed Breath + Life-Seal Reach + Lasting Breath (1 extra cultivation point; until your Long Rest)",
        "Purify the Pulse: Remove Deafened + Life-Seal Reach", "Purify the Pulse: Remove Paralyzed + Life-Seal Reach",
        "Purify the Pulse: Remove Poisoned + Life-Seal Reach"}
    qi = me.resources[QI]
    _do(engine, "Mend the Pulse + Life-Seal Reach", FRIEND)
    assert ally.current_hp > 10 and _healings(engine)
    assert qi - me.resources[QI] == 1  # the reach costs nothing extra
    _move(engine, FRIEND, 16, 6)  # 13 cells = 65 ft, past the 60 ft
    assert _offered(engine, FRIEND) == set()


def test_deep_root_restoration_clears_every_condition_purify_could_in_one_use():
    engine = _engine(["deep_root_restoration"], cl=10)
    ally, me = engine.state.actors[FRIEND], engine.state.actors[ME]
    _afflict(engine, ally, "blinded", "deafened", "poisoned")
    qi = me.resources[QI]
    _do(engine, "Purify the Pulse: Remove Poisoned + Deep Root Restoration", FRIEND)
    assert _conditions(ally) == []
    assert qi - me.resources[QI] == 3  # Purify the Pulse's 1 CP plus the augment's 2 CP

    plain = _engine(["deep_root_restoration"], cl=10)
    ally = plain.state.actors[FRIEND]
    _afflict(plain, ally, "blinded", "deafened", "poisoned")
    _do(plain, "Purify the Pulse: Remove Poisoned", FRIEND)
    assert _conditions(ally) == ["blinded", "deafened"]  # without the augment Purify still removes one


def test_restorative_mend_also_purifies_one_condition_for_purifys_cp():
    engine = _engine(["restorative_mend"], cl=10)
    ally, me = engine.state.actors[FRIEND], engine.state.actors[ME]
    ally.current_hp = 10
    _afflict(engine, ally, "blinded", "paralyzed", "deafened")
    assert {"Mend the Pulse + Restorative Mend", "Borrowed Breath + Restorative Mend"} <= _offered(engine, FRIEND)
    qi = me.resources[QI]
    _do(engine, "Mend the Pulse + Restorative Mend", FRIEND)
    assert ally.current_hp > 10
    assert _conditions(ally) == ["blinded", "deafened"]  # one condition, the worst (Paralyzed), not all three
    assert qi - me.resources[QI] == 2  # Mend the Pulse 1 CP plus Purify the Pulse 1 CP


def test_restorative_mend_still_heals_when_there_is_nothing_to_purify():
    engine = _engine(["restorative_mend"], cl=10)
    ally, me = engine.state.actors[FRIEND], engine.state.actors[ME]
    ally.current_hp = 10
    qi = me.resources[QI]
    _do(engine, "Mend the Pulse + Restorative Mend", FRIEND)
    assert ally.current_hp > 10 and _conditions(ally) == []
    assert qi - me.resources[QI] == 2  # the printed rule: pay Purify's CP normally


def test_generated_authority_carries_the_life_typings():
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
    for key in ("LIFE_BASE_MEND_THE_PULSE", "LIFE_BASE_READ_THE_PULSE", "tianxia.talent.life.deep_root_restoration",
                "tianxia.talent.life.life_seal_reach", "tianxia.talent.life.restorative_mend"):
        assert authority[key]["typing_status"] == "reviewed_final", key
        assert authority[key]["coverage"] != "RIDERS_ONLY", key
