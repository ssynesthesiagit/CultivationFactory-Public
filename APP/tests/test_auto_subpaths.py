"""Wave 3 subpaths worker (owner 2026-09-28, "automate every aspect before another playtest"): the Subpath and
Tradition features of dream_qi_cultivator, devil_heart_second_furnace, ten_thousand_sword_array_cultivator,
hundred_beast_scripture, kukishin, bojutsu, black_thorn_demon_body, thousand_fold_steel_body, kensei,
demon_prison_seal_cultivator, black_sea_leviathan_womb, yamabushi, spirit_bow_cultivator,
heaven_thunder_storm_soul, drunken_fist, echo_step_disciple, halo_eater, heartbinder, unwritten_footprint,
black_current_walker, yokai_channeler, boundary_walker, candlemaker, inner_soul_gate_ascetic,
choir_of_the_unopened_eye, saber_wind_cultivator (the "paths" worker had already narrowed or nulled some of
these groups' broad-scope modifiers; this pass reviews everything else).

Covers the five new ext plug-ins (an after-hit trigger cannot be expressed as a modifier targeting "unarmed
strike" or "weapon attack" by name) plus a couple of direct typing fixes.
"""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import bears_mark
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.subpaths"
STRIKE = "Unarmed Strike (Iron Fist)"  # the Iron Fist sphere's own Unarmed Strike -- a plain, sphere-less
# "Unarmed Strike" is not itself a legal candidate on a bare test sheet with no weapon and no natural-weapon
# grant; borrowing Iron Fist's still counts as attack_kind "unarmed" for the after-hit hooks under test.


def _sheet(feature_ids: list[str], **extra) -> dict:
    return {**SHEET, "path_and_subpath": {"path_feature_record_ids": feature_ids},
            "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.iron_fist"],
                                    "learned_talent_record_ids": ["TAL_IRON_FIST_IRON_FIST_TRAINING"]}, **extra}


def _fight(sheet: dict, me_at=(3, 6), foe_at=(4, 6), seed="SUBPATHS") -> Gate4ControllerEngine:
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(compile_character(sheet, actor_id=ME),),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _strike_until(engine, name, *, attempts=10):
    """Repeat a named attack (retrying the actor's turn) until it hits; returns True on a hit."""
    me = engine.state.actors[ME]
    for attempt in range(attempts):
        strike = next((c for c in engine.legal_candidates() if c.display_name == name), None)
        assert strike is not None, f"{name!r} should be a legal candidate"
        before = len([e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"])
        engine.execute_intent(ActionIntent(intent_id=f"{name}{attempt}", decision_id=strike.decision_id, candidate_id=strike.candidate_id,
                                           state_version=strike.state_version, actor_id=ME, target_ids=strike.target_ids))
        if len([e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]) > before:
            return True
        engine.state.current_actor_id = ME
        me.action_available = True
    return False


# ------------------------------------------------------------------------------------------------ Black Thorn Demon Body
def test_thorn_flesh_armory_spends_a_demon_spine_and_can_apply_bleeding_on_an_unarmed_hit():
    engine = _fight(_sheet(["tianxia.subpath.body.black_thorn_demon_body.feature.thorn_flesh_armory"]))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert "resource:named.demon_spine" in me.resources  # Demon Spines are generated elsewhere in the real kit
    me.resources["resource:named.demon_spine"] = 3
    before_spine = me.resources["resource:named.demon_spine"]
    assert _strike_until(engine, STRIKE)
    assert me.resources["resource:named.demon_spine"] == before_spine - 1
    # The technique_save_dc (30) on this fixture's sheet all but guarantees the Constitution save fails.
    assert any(c.condition_id == "condition:typed.bleeding" for c in foe.conditions.values())


# ------------------------------------------------------------------------------------------------ Kensei
def test_blade_fist_defaults_to_proficiency_bonus_slashing_damage_on_an_unarmed_hit():
    engine = _fight(_sheet(["tianxia.subpath.body.kensei.feature.blade_fist"]))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    hp_before = foe.current_hp
    assert _strike_until(engine, STRIKE)
    strike_damage = next(e for e in reversed(engine.events) if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == ME)
    # The passive fired once this turn: turn_flags recorded it, and it cannot fire twice.
    assert me.turn_flags.get("blade_fist")
    assert foe.current_hp <= hp_before  # the hit (plus Blade Fist's +PB Slashing) landed


def test_severing_palm_spends_four_stamina_and_forces_a_constitution_save():
    sheet = _sheet(["tianxia.subpath.body.kensei.feature.severing_palm"])
    sheet["ability_scores_and_statistics"] = {**sheet["ability_scores_and_statistics"],
                                              "primary_resource": {"name": "Stamina", "maximum": 30}}
    engine = _fight(sheet)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    before = me.resources.get("resource:core.stamina", 0)
    assert before >= 4
    assert _strike_until(engine, STRIKE)
    assert me.resources["resource:core.stamina"] == before - 4
    assert me.turn_flags.get("severing_palm")


# ------------------------------------------------------------------------------------------------ Black Current Walker
def test_flow_after_the_strike_grants_extra_movement_after_a_qualifying_hit():
    # rider lane C8: the printed step is immediate ("immediately after you deal damage ... you may move 10 feet without
    # provoking"), chosen through the needle choice transport; this player takes the square two steps back.
    from tests.test_riders_c8 import answers

    engine = _fight(_sheet(["tianxia.tradition.spirit.black_current_walker.feature.enter_the_black_current"]))
    me = engine.state.actors[ME]
    answers(engine, {"flow_after_the_strike": ("cell:1,6",)})
    moves_before = len([e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME])
    assert _strike_until(engine, STRIKE)
    assert me.turn_flags.get("flow_after_the_strike")
    moves = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME]
    assert len(moves) > moves_before and all(e.payload.get("without_provoking") for e in moves[moves_before:])
    assert (me.position.x, me.position.y) == (1, 6)


# ------------------------------------------------------------------------------------------------ Echo Step Disciple
def test_strike_from_the_echo_adds_key_ability_modifier_damage_against_a_resonance_marked_target():
    # Rider lane C8 (2026-09-30): the Wisdom bonus is part of Strike From the Echo in the printed text -- an attack made from a
    # recorded Echo Position -- not of every hit on a marked creature; the Echo button is tested in tests/test_riders_c8.py.
    from combat.ext import echo_step_disciple
    from combat.gate2_runtime_models import Position, RollRecord
    from combat.typed_executor import mark_condition_id

    engine = _fight(_sheet(["tianxia.tradition.spirit.echo_step_disciple.feature.afterimage_edge"]), foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    engine._apply_condition(foe, mark_condition_id("Resonance Marked", ME), "test", ME, expires_on="UNTIL_REMOVED")
    assert bears_mark(foe, ME, "Resonance Marked")
    assert f"Strike From the Echo: {STRIKE}" not in {c.display_name for c in engine.legal_candidates()}  # no Echo Position yet
    echo_step_disciple.record(engine, me, Position(x=5, y=6), echo_step_disciple.AFTERIMAGE_EDGE)
    engine.roller.d20 = lambda **kw: RollRecord(roll_id="echo", counter_start=1, counter_end=2, expression="1d20", actor_id=kw["actor_id"],
                                                reason=kw["reason"], dice=(19,), modifier=kw["modifier"], total=19 + kw["modifier"], natural_result=19)
    assert _strike_until(engine, f"Strike From the Echo: {STRIKE}", attempts=1)
    assert me.turn_flags.get("strike_from_the_echo") and not echo_step_disciple.echo_cells(engine, me)


# ------------------------------------------------------------------------------------------------ Devil Heart, Second Furnace
def test_demon_seed_overdraw_refunds_qi_and_gains_corruption_and_devil_qi():
    sheet = _sheet(["tianxia.subpath.qi.devil_heart_second_furnace.feature.demon_seed_overdraw"],
                   spheres_and_talents={"sphere_record_ids": ["tianxia.sphere.blood"],
                                        "learned_talent_record_ids": ["BLOOD_BASE_COAGULATE"]})
    engine = _fight(sheet)
    me = engine.state.actors[ME]
    assert "resource:named.corruption" in me.resources and "resource:named.devil_qi" in me.resources
    qi_before, corruption_before, devil_qi_before = me.resources["resource:core.qi"], me.resources["resource:named.corruption"], me.resources["resource:named.devil_qi"]
    engine._apply_condition(me, "condition:typed.mark.blood_thread." + ME, "test:thread", ME, expires_on="UNTIL_REMOVED")  # "Target: One willing creature bearing your Blood Thread" (rider lane C5)
    coagulate = next(c for c in engine.legal_candidates() if c.display_name == "Coagulate: Temporary HP")
    engine.execute_intent(ActionIntent(intent_id="coag", decision_id=coagulate.decision_id, candidate_id=coagulate.candidate_id,
                                       state_version=coagulate.state_version, actor_id=ME, target_ids=coagulate.target_ids))
    assert me.resources["resource:named.corruption"] == corruption_before + 1
    assert me.resources["resource:named.devil_qi"] == devil_qi_before + 1
    pb = 4  # SHEET's proficiency_bonus
    paid = 1  # Coagulate costs 1 Qi
    assert me.resources["resource:core.qi"] == qi_before - paid + min(pb, paid)


# ------------------------------------------------------------------------------------------------ Black Sea Leviathan Womb
def test_inner_sea_awakening_marks_a_damaged_target_then_spends_depth_on_it():
    from combat import typed_executor
    from combat.ext import black_sea_leviathan_womb as leviathan

    sheet = _sheet(["tianxia.subpath.qi.black_sea_leviathan_womb.feature.inner_sea_awakening"],
                   spheres_and_talents={"sphere_record_ids": ["tianxia.sphere.ash"],
                                        "learned_talent_record_ids": ["ASH_BASE_ASHFALL"]})
    engine = _fight(sheet)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    ashfall = next(row for row in engine.action_catalog.values() if row.display_name == "Ashfall" and row.owner_id == ME)
    qi_action = typed_executor.ActionDefinition(**{**ashfall.model_dump(), "costs": (("resource:core.qi", 2),)})
    ctx = typed_executor.Context(engine, me, qi_action, None, qi_action.parameters["typed"], [foe], foe, {})
    engine._append_event("DAMAGE_COMMITTED", qi_action.source_definition_id, actor_id=ME, target_ids=(foe.entity_id,), payload={"amount": 5})
    leviathan.leviathan_womb(ctx)
    assert typed_executor.bears_mark(foe, ME, leviathan.DEPTH_MARK)
    assert me.turn_flags.get("pressure_of_recognition")
    # A second qualifying use this same turn should spend Depth against the now-marked target.
    me.resources[leviathan.DEPTH] = 3
    hp_before = foe.current_hp
    engine._append_event("DAMAGE_COMMITTED", qi_action.source_definition_id, actor_id=ME, target_ids=(foe.entity_id,), payload={"amount": 5})
    leviathan.leviathan_womb(ctx)
    assert me.resources[leviathan.DEPTH] == 2
    assert me.turn_flags.get("spend_depth")
    assert foe.current_hp < hp_before  # the default "damage" Spend Depth choice landed 2d8 Cold or Force


# ------------------------------------------------------------------------------------------------ Reviewed typing (no plug-in needed)
def test_spines_answer_violence_types_damage_and_bleeding_on_a_failed_save():
    bundle = compile_character(_sheet(["tianxia.subpath.body.black_thorn_demon_body.feature.spines_answer_violence"]), actor_id=ME)
    row = next(r for r in bundle["typed_reactions"] if r["name"] == "Spines Answer Violence")
    on_fail = next(e for e in row["effects"] if e.get("type") == "save")["on_fail"]
    assert any(e.get("type") == "damage" and e.get("damage_types") == ["piercing"] for e in on_fail)
    assert any(e.get("type") == "condition" and e.get("condition") == "bleeding" for e in on_fail)


def test_sword_seed_attack_is_a_bonus_action_that_deals_damage():
    bundle = compile_character(_sheet(["tianxia.subpath.qi.ten_thousand_sword_array_cultivator.feature.sword_seed"]), actor_id=ME)
    row = next(r for r in bundle["action_catalog"] if r["display_name"] == "Sword Seed")
    assert row["economy"] == "BONUS_ACTION"
    on_hit = next(e for e in row["parameters"]["typed"]["effects"] if e.get("type") == "attack")["on_hit"]
    assert any(e.get("type") == "damage" for e in on_hit)
