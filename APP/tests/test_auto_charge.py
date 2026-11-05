"""Lightning's Charge spent, Ice's Lattice Space, and Earth's line-crossing trigger (owner 2026-09-28,
"automate every aspect before another playtest", wave 3, follow-up to the elements worker).

Covers the new shared mechanisms directly (run_effects' min_cl gate; if_marked/if_not_marked's list-of-
marks and applies_to "self"; block_spend_mark's mark_spent hook; zones.on_moved's line-crossing check) and
the sphere-specific plug-ins built on them (combat/ext/charge_marks.py, combat/ext/ice_lattice.py), rather
than relying only on the built-in AI to happen to pick the right actions in a full fight."""

from pathlib import Path

from combat import zones
from combat.ext import charge_marks, ice_lattice
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position, ZoneState
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import Context, bears_mark, mark_condition_id, run_effects
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.spark"


def _sheet(sphere: str, talents: list[str]) -> dict:
    return {**SHEET, "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}}


def _engine(bundle, foe_at=(4, 6)) -> Gate4ControllerEngine:
    engine = Gate4ControllerEngine(ROOT, match_seed="CHARGE", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _ctx(engine, actor, target, *, cl: int = 10) -> Context:
    action = next(iter(engine.action_catalog.values()))
    intent = ActionIntent(intent_id="t", decision_id="d", candidate_id="c", state_version=0, actor_id=actor.entity_id,
                          target_ids=(target.entity_id,))
    return Context(engine, actor, action, intent, {"numbers": {"pb": 4, "cl": cl, "key_mod": 2}}, [target], target, {})


# ---------------------------------------------------------------------------------------------- Lightning's Charge


_BOTH = ["TAL_LIGHTNING_GATHER_CHARGE", "TAL_LIGHTNING_LIGHTNING_LASH"]


def test_gather_charge_compiles_as_a_real_action_and_places_the_mark():
    """Regression: a feature_blocks entry marks its mechanic id "automated" (combat/typed_reactions.py
    compile_blocks), which combat/factory_compiler.py's action-building loop then skips entirely. An
    earlier version of this task's own mark_caps entry (combat/rules/feature_blocks.d/charge.json) was
    attached to Gather Charge itself instead of First Circuit Method, silently dropping Gather Charge from
    the action catalog -- caught by tests/test_auto_elements.py's own regression test failing in verify.sh,
    not by this file (a gap in this file's own coverage now closed)."""
    bundle = compile_character(_sheet("tianxia.sphere.lightning", ["TAL_LIGHTNING_GATHER_CHARGE"]), actor_id=ME)
    # Gather Charge's printed targets are its options since rider lane C13 ("Gather Charge: Charge Yourself", a willing creature,
    # your weapon, a space).
    assert "Gather Charge: Charge Yourself" in [row["display_name"] for row in bundle["action_catalog"]]
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Gather Charge: Charge Yourself")
    engine.execute_intent(ActionIntent(intent_id="g", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    assert bears_mark(me, ME, "Charged") or bears_mark(foe, ME, "Charged")


def test_lightning_lash_has_a_charge_option_that_places_the_mark_on_a_hit():
    bundle = compile_character(_sheet("tianxia.sphere.lightning", _BOTH), actor_id=ME)
    charge_option = next(row for row in bundle["action_catalog"] if row["display_name"] == "Lightning Lash: Charge")
    on_hit = charge_option["parameters"]["typed"]["effects"][0]["on_hit"]
    assert any(effect.get("type") == "mark" and effect.get("mark") == "Charged" for effect in on_hit)


def test_lightning_lash_charge_places_the_mark_when_cast_for_real():
    bundle = compile_character(_sheet("tianxia.sphere.lightning", _BOTH), actor_id=ME)
    engine = _engine(bundle)
    foe = engine.state.actors[AN]
    for attempt in range(8):  # until a hit lands (the dice decide)
        candidate = next(c for c in engine.legal_candidates() if c.display_name == "Lightning Lash: Charge")
        engine.execute_intent(ActionIntent(intent_id=f"l{attempt}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                           state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids))
        if bears_mark(foe, ME, "Charged"):
            break
        engine.state.current_actor_id = ME
        engine.state.actors[ME].action_available = True
    assert bears_mark(foe, ME, "Charged")


def test_if_marked_and_if_not_marked_pick_the_complementary_branch():
    """Earthbind Line's own shape: gain a mark if you lack it, or spend it (and do something else) if you
    already have it -- if_marked alone cannot express the "lacks it" half."""
    bundle = compile_character(_sheet("tianxia.sphere.lightning", []), actor_id=ME)
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    ctx = _ctx(engine, me, foe)
    run_effects(ctx, [{"type": "if_not_marked", "mark": "Charged",
                       "effects": [{"type": "mark", "mark": "Charged", "applies_to": "target", "duration": {"kind": "until_removed"}}]}])
    assert bears_mark(foe, ME, "Charged")
    run_effects(ctx, [{"type": "if_not_marked", "mark": "Charged",  # already marked now: this branch must not fire again
                       "effects": [{"type": "condition", "condition": "prone", "applies_to": "target"}]}])
    assert "prone" not in "".join(c.condition_id for c in foe.conditions.values())
    run_effects(ctx, [{"type": "if_marked", "mark": "Charged", "effects": [{"type": "spend_mark", "mark": "Charged", "applies_to": "target"}]}])
    assert not bears_mark(foe, ME, "Charged")


def test_if_marked_accepts_a_list_of_marks_and_a_self_check():
    """Arc Primer: 'If the Arc target is Conductive' -- Conductive is implied by already being Charged, so
    the check is an OR of two mark names; Static Guard: 'If you are Charged' checks the actor, not the
    ability's own target."""
    bundle = compile_character(_sheet("tianxia.sphere.lightning", []), actor_id=ME)
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    engine._apply_condition(foe, mark_condition_id("Conductive", ME), "test", ME, expires_on="UNTIL_REMOVED")
    ctx = _ctx(engine, me, foe)
    hit = []
    run_effects(ctx, [{"type": "if_marked", "mark": ["Charged", "Conductive"], "effects": [{"type": "rider", "evidence": "x"}]}])
    assert any(e.event_type == "GM_RIDER" and e.payload.get("rider") == "x" for e in engine.events)
    engine._apply_condition(me, mark_condition_id("Charged", ME), "test", ME, expires_on="UNTIL_REMOVED")
    run_effects(ctx, [{"type": "if_marked", "mark": "Charged", "applies_to": "self",
                       "effects": [{"type": "spend_mark", "mark": "Charged", "applies_to": "self"}]}])
    assert not bears_mark(me, ME, "Charged")


def test_min_cl_gate_blocks_a_below_threshold_bonus():
    bundle = compile_character(_sheet("tianxia.sphere.lightning", []), actor_id=ME)
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    before = foe.current_hp
    run_effects(_ctx(engine, me, foe, cl=1), [{"type": "damage", "min_cl": 5, "applies_to": "target", "flat": 5,
                                              "formula": "none", "damage_types": ["lightning"], "duration": "instant"}])
    assert foe.current_hp == before  # CL 1: gated out
    run_effects(_ctx(engine, me, foe, cl=5), [{"type": "damage", "min_cl": 5, "applies_to": "target", "flat": 5,
                                              "formula": "none", "damage_types": ["lightning"], "duration": "instant"}])
    assert foe.current_hp == before - 5  # CL 5: the gate opens


def test_storm_heart_engine_grants_temp_hp_once_per_turn_when_a_charge_is_spent():
    bundle = compile_character(_sheet("tianxia.sphere.lightning", ["TAL_LIGHTNING_STORM_HEART_ENGINE"]), actor_id=ME)
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    engine._apply_condition(foe, mark_condition_id("Charged", ME), "test", ME, expires_on="UNTIL_REMOVED")
    engine._apply_condition(me, mark_condition_id("Charged", ME), "test", ME, expires_on="UNTIL_REMOVED")
    ctx = _ctx(engine, me, foe)
    run_effects(ctx, [{"type": "spend_mark", "mark": "Charged", "applies_to": "target"}])
    assert me.temporary_hp == 4  # PB
    run_effects(ctx, [{"type": "spend_mark", "mark": "Charged", "applies_to": "self"}])
    assert me.temporary_hp == 4  # once per turn: the second spend this turn grants nothing more


def test_conductive_strike_cl5_upgrade_consumes_a_charge_and_marks_conductive():
    bundle = compile_character(_sheet("tianxia.sphere.lightning", ["TAL_LIGHTNING_CONDUCTIVE_STRIKE"]), actor_id=ME)
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    engine._apply_condition(foe, mark_condition_id("Charged", ME), "test", ME, expires_on="UNTIL_REMOVED")
    ctx = _ctx(engine, me, foe, cl=10)  # CL 5+
    before = foe.current_hp
    charge_marks._conductive_strike_after_hit(ctx, foe, "weapon")
    assert not bears_mark(foe, ME, "Charged")  # consumed
    assert bears_mark(foe, ME, "Conductive")  # granted
    assert foe.current_hp < before  # the extra 1d8
    # Once per turn: a second qualifying hit the same turn does nothing more (no Charge to consume anyway,
    # but also does not re-mark Conductive from a fresh call).
    hp_after_first = foe.current_hp
    engine._apply_condition(foe, mark_condition_id("Charged", ME), "test", ME, expires_on="UNTIL_REMOVED")
    charge_marks._conductive_strike_after_hit(ctx, foe, "weapon")
    assert foe.current_hp == hp_after_first and bears_mark(foe, ME, "Charged")  # untouched: the gate held


def test_conductive_strike_does_not_fire_off_a_cultivation_attack():
    """The previous typing used an any_attack scoped modifier that also rode Lightning Lash/Chain Bolt hits;
    the after_hit hook is keyed to real weapon/unarmed hits only (kind == "weapon")."""
    bundle = compile_character(_sheet("tianxia.sphere.lightning", ["TAL_LIGHTNING_CONDUCTIVE_STRIKE"]), actor_id=ME)
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    engine._apply_condition(foe, mark_condition_id("Charged", ME), "test", ME, expires_on="UNTIL_REMOVED")
    ctx = _ctx(engine, me, foe, cl=10)
    charge_marks._conductive_strike_after_hit(ctx, foe, "other")  # a Cultivation Attack, e.g. Lightning Lash
    assert bears_mark(foe, ME, "Charged") and not bears_mark(foe, ME, "Conductive")


# --------------------------------------------------------------------------------------------------- Ice's Lattice Space


def test_lattice_spaces_effect_creates_that_many_individually_tracked_zones():
    bundle = compile_character(_sheet("tianxia.sphere.ice", []), actor_id=ME)
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    ctx = _ctx(engine, me, foe)
    ice_lattice._lattice_spaces(ctx, {"formula": "pb", "cap_exempt": True, "duration": {"kind": "until_end_of_next_turn"}})
    spaces = [zone for zone in engine.state.zones.values() if zone.trigger_profile.get("lattice_space")]
    assert len(spaces) == 4  # PB
    assert all(zone.owner_id == ME and len(zone.affected_cells) == 1 for zone in spaces)


def test_lattice_spaces_enforces_the_cap_when_not_exempt():
    bundle = compile_character(_sheet("tianxia.sphere.ice", []), actor_id=ME)
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    ctx = _ctx(engine, me, foe)  # pb=4, key_mod=2 -> cap 6
    ice_lattice._lattice_spaces(ctx, {"formula": "pb", "duration": {"kind": "until_end_of_next_turn"}})  # 4 spaces
    ice_lattice._lattice_spaces(ctx, {"formula": "pb", "duration": {"kind": "until_end_of_next_turn"}})  # +4 -> over the cap of 6
    spaces = [zone for zone in engine.state.zones.values() if zone.active and zone.trigger_profile.get("lattice_space")]
    assert len(spaces) == 6


# -------------------------------------------------------------------------------------------- Earth's line-crossing


def test_zones_crosses_line_is_true_only_for_a_genuine_crossing():
    zone = ZoneState(zone_id="z", source_definition_id="s", owner_id=ME, center=Position(x=5, y=5), radius_cells=0,
                     affected_cells=(Position(x=5, y=0), Position(x=5, y=10)), concentration_link=False, created_round=1,
                     trigger_profile={"shape": "line"})
    assert zones._crosses_line(zone, Position(x=0, y=5), Position(x=10, y=5))  # west side to east side: a real crossing
    assert not zones._crosses_line(zone, Position(x=0, y=5), Position(x=2, y=5))  # stays on the west side
    assert not zones._crosses_line(zone, Position(x=0, y=5), Position(x=5, y=5))  # stops ON the line: not across it
    assert zones._crosses_line(zone, Position(x=10, y=5), Position(x=0, y=5))  # the reverse crossing also counts


def test_factory_compiler_recognizes_crosses_and_moves_across_phrasing():
    from combat.factory_compiler import _CROSS, _MOVE_ACROSS

    assert _CROSS.search("The first time on a turn that a hostile creature crosses the line")
    assert not _CROSS.search("Creatures in the cone make a Constitution saving throw")
    match = _MOVE_ACROSS.search("willingly moves at least 10 feet across, out of, or through your Foundation Spaces")
    assert match and match.group(1) == "10"
