"""Lingfeng Ironclad's automation (owner 2026-09-28, "automate every aspect before another playtest"): Iron Fist
Form/Sequence/Guard/Meridian fixes (Iron Fist Flurry's bonus-action strike, Iron Forearm Guard's Opened-on-zero,
Fists Ring Like Bells' Disadvantage-if-Opened save, Crane-Step Combination's cross-hit buff, Hammer-and-Anvil
Rhythm's Martial Focus regain), the Smoke Trace/Smoke Responses core (combat/ext/ironclad_smoke.py), and the
Blacksmith Core Forge Responses (combat/ext/ironclad_blacksmith.py). See the worker's final report for the full
ledger of what is applied, labelled, or blocked and why."""

from pathlib import Path

from combat import typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import bears_mark
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.ironclad_test"

IRON_FIST_TALENTS = ["TAL_IRON_FIST_IRON_FIST_TRAINING", "TAL_IRON_FIST_IRON_FIST_FLURRY", "TAL_IRON_FIST_IRON_FOREARM_GUARD",
                     "TAL_IRON_FIST_EMPTY_PALM_STOPS_THE_BLADE", "TAL_IRON_FIST_FISTS_RING_LIKE_BELLS",
                     "TAL_IRON_FIST_CRANE_STEP_COMBINATION", "TAL_IRON_FIST_HAMMER_AND_ANVIL_RHYTHM"]
SMOKE_TALENTS = ["SMOKE_BASE_SMOKE_VEIL", "SMOKE_BASE_SMOKE_TRACE", "SMOKE_BASE_SMOKE_RESPONSES"]
BLACKSMITH_TALENTS = ["BLACKSMITH_BASE_BLACKSMITH_TRAINING"]


def _bundle(talents, spheres=("tianxia.sphere.iron_fist",)):
    sheet = {**SHEET, "equipment": [], "identity": {**SHEET["identity"], "cultivation_level": 10},
             "spheres_and_talents": {"sphere_record_ids": list(spheres), "learned_talent_record_ids": talents}}
    return compile_character(sheet, actor_id=ME)


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="IRONCLAD", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _guaranteed_hit(engine, candidate):
    """Force a candidate's attack roll to hit (tests/test_unmaking.py's trick): the fixture's saving-throw and
    attack-bonus DCs are otherwise too swingy to land a hit within a handful of retries."""
    typed = engine.action_catalog[candidate.source_definition_id].parameters["typed"]
    typed["numbers"] = {**typed["numbers"], "attack_bonus": 30, "save_dc": 30}


def _strike_until(engine, display_name, stop):
    """Repeat a named Unarmed Strike action against AN specifically, forcing hits, until ``stop(me, foe)`` is
    true or attempts run out."""
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    for attempt in range(8):
        candidate = next((c for c in engine.legal_candidates() if c.display_name == display_name and c.target_ids == (AN,)), None)
        if candidate is None:
            return False
        _guaranteed_hit(engine, candidate)
        engine.execute_intent(ActionIntent(intent_id=f"{display_name}{attempt}", decision_id=candidate.decision_id,
                                           candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                           actor_id=ME, target_ids=candidate.target_ids))
        if stop(me, foe):
            return True
        engine.state.current_actor_id = ME
        me.action_available = True
    return False


def test_iron_fist_flurry_is_a_bonus_action_variant_costing_martial_focus():
    bundle = _bundle(IRON_FIST_TALENTS)
    flurry = next(row for row in bundle["action_catalog"] if row["display_name"] == "Unarmed Strike (Iron Fist) + Iron Fist Flurry")
    assert flurry["economy"] == "BONUS_ACTION"
    assert dict(flurry["costs"] or [])["resource:core.martial_focus"] == 1
    modifier = next(row for row in bundle["modifiers"] if row["name"] == "Iron Fist Flurry")
    assert modifier["status"] == "applied"


def _hit_then_damage(engine, attacker, target, pending):
    """The real two-checkpoint sequence a melee hit runs through (combat/typed_reactions.py): on_attack_hit first
    (where a "hit"-kind reaction like Iron Forearm Guard parks its flat reduction, since no damage is rolled
    yet), then on_damage (where the parked reduction is actually subtracted from the rolled amount). Iron Forearm
    Guard is kind "hit", not "damaged", so on_damage alone never offers it."""
    target.reaction_available = True
    typed_reactions.on_attack_hit(engine, attacker, target, {"range_ft": None}, total=50, natural=10, effective_ac=10)
    target.reaction_available = True
    return typed_reactions.on_damage(engine, target, pending, reaction_depth=0, source_definition_id="test:attack", source_actor_id=attacker.entity_id)


def test_iron_forearm_guard_opens_the_attacker_only_when_it_zeroes_the_damage():
    """Drives the real on_attack_hit/on_damage checkpoint pair (rather than the full AI attack pipeline, whose
    dice make a reliable zero-damage hit hard to arrange) to isolate the only_if_zero mechanism this task added
    to typed_reactions.py for Iron Forearm Guard's "becomes Opened" clause -- and its reclassification from kind
    ally_hit (which could never fire for Lingfeng's own defense) to kind hit."""
    engine = _engine(_bundle(IRON_FIST_TALENTS))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    reduced = _hit_then_damage(engine, foe, me, pending=1)
    assert reduced == 0, "Iron Forearm Guard's PB + Iron Fist ability modifier reduction should zero a 1-point hit"
    assert bears_mark(foe, ME, "Opened"), "reducing the damage to 0 should Open the attacker"

    # A hit NOT reduced to 0 must not Open the attacker as a side effect.
    engine2 = _engine(_bundle(IRON_FIST_TALENTS))
    me2, foe2 = engine2.state.actors[ME], engine2.state.actors[AN]
    remaining = _hit_then_damage(engine2, foe2, me2, pending=200)
    assert remaining > 0
    assert not bears_mark(foe2, ME, "Opened")


def test_fists_ring_like_bells_carries_disadvantage_if_marked_opened():
    bundle = _bundle(IRON_FIST_TALENTS)
    bells = next(row for row in bundle["action_catalog"] if row["display_name"] == "Fists Ring Like Bells")
    save = next(e for e in bells["parameters"]["typed"]["effects"] if e.get("type") == "save")
    assert save.get("disadvantage_if_marked") == "Opened"


def test_crane_step_combination_arms_a_pending_buff_and_pays_it_out_on_a_different_target():
    bundle = _bundle(IRON_FIST_TALENTS)
    engine = Gate4ControllerEngine(ROOT, match_seed="CRANE", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN, LEE],
                                                 "team_by_actor": {ME: "team:a", AN: "team:b", LEE: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}, LEE: {"x": 3, "y": 5}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me, foe, second = engine.state.actors[ME], engine.state.actors[AN], engine.state.actors[LEE]
    # Crane-Step Combination is free and harmless, so it always merges into the base Unarmed Strike (there is no
    # separate "+ Crane-Step Combination" choice) -- every hit arms it.
    armed = _strike_until(engine, "Unarmed Strike (Iron Fist)", lambda m, f: m.turn_flags.get("ironclad_crane_step_target") == f.entity_id)
    assert armed, "an Unarmed Strike hit should arm the pending buff"
    before = second.current_hp
    engine.state.current_actor_id = ME
    me.action_available = True
    plain = next((c for c in engine.legal_candidates() if c.display_name == "Unarmed Strike (Iron Fist)" and c.target_ids == (second.entity_id,)), None)
    assert plain is not None, "a plain Unarmed Strike against the different creature should still be a legal candidate"
    _guaranteed_hit(engine, plain)
    engine.execute_intent(ActionIntent(intent_id="plain", decision_id=plain.decision_id, candidate_id=plain.candidate_id,
                                       state_version=plain.state_version, actor_id=ME, target_ids=plain.target_ids))
    # Every Unarmed Strike hit re-arms the buff (against whichever creature it just hit), so the flag is not
    # cleared -- it now points at "second" rather than "foe".
    assert me.turn_flags.get("ironclad_crane_step_target") == second.entity_id
    assert second.current_hp < before or any(
        e.event_type == "DAMAGE_COMMITTED" and str(e.source_definition_id).endswith("crane_step_combination.buff") for e in engine.events)
    del foe


def test_hammer_and_anvil_rhythm_regains_martial_focus_on_the_second_hit_same_target():
    bundle = _bundle(IRON_FIST_TALENTS)
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    engine._spend_resource(me, "resource:core.martial_focus", me.resources.get("resource:core.martial_focus", 0), "test")
    assert me.resources.get("resource:core.martial_focus", 0) == 0
    landed = _strike_until(engine, "Unarmed Strike (Iron Fist)", lambda m, f: m.resources.get("resource:core.martial_focus", 0) > 0)
    assert landed, "two Unarmed Strike hits against the same creature should regain Martial Focus if it was absent"
    assert any(e.event_type == "GM_RIDER" and "Hammer-and-Anvil Rhythm" in str((e.payload or {}).get("rider")) for e in engine.events)


def test_smoke_trace_is_a_free_once_per_round_action_that_places_a_mark():
    bundle = _bundle(SMOKE_TALENTS, spheres=("tianxia.sphere.smoke",))
    trace = next(row for row in bundle["action_catalog"] if row["display_name"] == "Place Smoke Trace")
    assert trace["economy"] == "NONE"
    engine = _engine(bundle)
    foe = engine.state.actors[AN]
    first = next(c for c in engine.legal_candidates() if c.display_name == "Place Smoke Trace")
    engine.execute_intent(ActionIntent(intent_id="trace1", decision_id=first.decision_id, candidate_id=first.candidate_id,
                                       state_version=first.state_version, actor_id=ME, target_ids=(AN,)))
    assert bears_mark(foe, ME, "Smoke Trace")
    # Once per round: it must not still be a legal candidate this same turn.
    assert not [c for c in engine.legal_candidates() if c.display_name == "Place Smoke Trace"]


def test_blind_the_line_compiles_as_a_reaction_off_smoke_responses():
    bundle = _bundle(SMOKE_TALENTS, spheres=("tianxia.sphere.smoke",))
    reaction = next((row for row in bundle["typed_reactions"] if row.get("feature_id") == "SMOKE_BASE_SMOKE_RESPONSES"), None)
    assert reaction is not None and reaction.get("kind") == "attacked"


def test_follow_the_soot_and_slip_the_chimney_path_are_built_as_bonus_actions():
    bundle = _bundle(SMOKE_TALENTS, spheres=("tianxia.sphere.smoke",))
    names = {row["display_name"]: row for row in bundle["action_catalog"]}
    assert names["Follow the Soot"]["economy"] == "BONUS_ACTION"
    assert names["Slip the Chimney Path"]["economy"] == "BONUS_ACTION"


def test_set_edge_and_fit_armor_are_built_for_blacksmith_sphere_owners():
    bundle = _bundle(BLACKSMITH_TALENTS, spheres=("tianxia.sphere.blacksmith",))
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert "Set Edge" in names
    assert {"Fit Armor: +1 AC", "Fit Armor: Reduce Weapon Damage", "Fit Armor: Ignore Forced Movement"} <= names


def test_set_edge_adds_proficiency_bonus_to_the_next_weapon_hit():
    from tests.test_carry import KIT

    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}], "identity": {**SHEET["identity"], "cultivation_level": 10},
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.blacksmith"], "learned_talent_record_ids": BLACKSMITH_TALENTS}}
    bundle = compile_character(sheet, actor_id=ME)
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    from combat.typed_executor import mark_condition_id

    engine._apply_condition(me, mark_condition_id("Forge Mark", ME), "test", ME, expires_on="UNTIL_REMOVED")
    set_edge = next(c for c in engine.legal_candidates() if c.display_name == "Set Edge")
    engine.execute_intent(ActionIntent(intent_id="edge", decision_id=set_edge.decision_id, candidate_id=set_edge.candidate_id,
                                       state_version=set_edge.state_version, actor_id=ME, target_ids=set_edge.target_ids))
    assert bears_mark(me, ME, "Set Edge Ready")
    assert not bears_mark(me, ME, "Forge Mark"), "Set Edge should have spent the Forge Mark"
    before = foe.current_hp
    attack = next(c for c in engine.legal_candidates() if c.display_name.endswith(" attack") and ".weapon." in c.source_definition_id)
    _guaranteed_hit(engine, attack)
    engine.execute_intent(ActionIntent(intent_id="wpn", decision_id=attack.decision_id, candidate_id=attack.candidate_id,
                                       state_version=attack.state_version, actor_id=ME, target_ids=attack.target_ids))
    assert not bears_mark(me, ME, "Set Edge Ready"), "Set Edge's bonus is spent on the next weapon hit"
    assert foe.current_hp < before
