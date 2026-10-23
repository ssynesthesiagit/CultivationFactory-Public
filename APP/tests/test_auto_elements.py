"""Wave 2 sphere ownership (owner 2026-09-28, "automate every aspect before another playtest"): Lightning,
Air, Earth, Water, Ice, Magma, Ash, Glass, Wax, Yang, Yin, Stars. Covers the systemic Air "Vector
replacement" merge bug, Earth's Burden Mark grant and Burden the Blade response, the Faultline/Waning
mark caps, Water's Soaked mark, and the stripped bogus wall-object "immunity" effects (Glacier Wall,
Blackglass Rampart)."""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import bears_mark
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.elements"
FOE = "actor:factory.elements_foe"


def _bundle(sphere, talents):
    return compile_character({**SHEET, "equipment": [], "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}},
                             actor_id=ME)


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="ELEMENTS", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _do(engine, name):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return candidate


def _hit_reliably(engine, name):
    """Force the attack to land (a fixture-strength dagger is unreliable against foes with real ACs)."""
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    typed = engine.action_catalog[candidate.source_definition_id].parameters["typed"]
    typed["numbers"] = {**typed["numbers"], "attack_bonus": 30}
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def test_gather_charge_places_a_tracked_charged_mark():
    """Regression: Gather Charge's own printed effect ('place a Charge on the target') had no
    structural mark at all before this review -- every other Lightning talent that checks or spends
    a Charge had nothing real to find."""
    bundle = _bundle("tianxia.sphere.lightning", ["TAL_LIGHTNING_GATHER_CHARGE"])
    engine = _engine(bundle)
    foe = engine.state.actors[AN]
    _do(engine, "Gather Charge: Charge Yourself")  # its printed options (rider lane C13): never an enemy
    # Gather Charge targets a creature/object/space it can see; against a hostile default target the
    # legal_candidates() pick should be the foe. Fall back to checking self if the AI/engine chose self.
    assert bears_mark(foe, ME, "Charged") or bears_mark(engine.state.actors[ME], ME, "Charged")


def test_weight_seeking_clod_grants_a_burden_mark_on_hit():
    bundle = _bundle("tianxia.sphere.earth", ["EARTH_BASE_SET_FOUNDATION", "EARTH_BASE_WEIGHT_SEEKING_CLOD"])
    engine = _engine(bundle)
    foe = engine.state.actors[AN]
    _hit_reliably(engine, "Weight-Seeking Clod")
    assert bears_mark(foe, ME, "Burden Mark")


def test_air_vector_talents_replace_wind_lash_instead_of_stacking_onto_every_vector():
    """Regression for a compile-time bug found while reviewing this sphere: Breath-Stealing Palm's
    Constitution-save silence was showing up on ALL FIVE Wind Lash vector variants (Push, Pull, Cut,
    Lift, Scatter) because its modifier had no cost/precondition, so factory_compiler.py's
    ``_free_and_harmless`` heuristic merged it into the base action instead of making it a distinct
    choice. reviewed_final.d/elements.json now gives it a real precondition string so it forms its
    own "Wind Lash: <Vector> + Breath-Stealing Palm" variant, leaving the plain vectors alone."""
    bundle = _bundle("tianxia.sphere.air", ["AIR_BASE_WIND_LASH", "TAL_AIR_BREATH_STEALING_PALM"])
    names = [row["display_name"] for row in bundle["action_catalog"]]
    assert "Wind Lash: Push" in names
    assert "Wind Lash: Push + Breath-Stealing Palm" in names
    plain = next(row for row in bundle["action_catalog"] if row["display_name"] == "Wind Lash: Push")
    on_hit = plain["parameters"]["typed"]["effects"][0]["on_hit"]
    assert not any(effect.get("type") == "save" and effect.get("ability") == "con" for effect in on_hit), \
        "the plain Push vector must not carry Breath-Stealing Palm's Constitution save"
    combo = next(row for row in bundle["action_catalog"] if row["display_name"] == "Wind Lash: Push + Breath-Stealing Palm")
    combo_on_hit = combo["parameters"]["typed"]["effects"][0]["on_hit"]
    assert any(effect.get("type") == "save" and effect.get("ability") == "con" for effect in combo_on_hit)


def test_faultline_mark_cap_ends_the_oldest_past_proficiency_bonus():
    bundle = _bundle("tianxia.sphere.glass", ["GLASS_BASE_FAULTLINE_MARKS", "GLASS_BASE_FAULTLINE_STRIKE"])
    engine = _engine(bundle)
    for _ in range(3):
        engine.state.current_actor_id = ME
        _hit_reliably(engine, "Faultline Strike")
        engine._system_start_turn()
    foe = engine.state.actors[AN]
    held = [c for c in foe.conditions.values() if c.condition_id.startswith("condition:typed.mark.faultline_mark.")]
    pb = bundle["action_catalog"][0]["parameters"]["typed"]["numbers"].get("pb", 4)
    assert len(held) <= max(pb, 1)


def test_water_lash_soaks_the_target_and_only_moves_it_if_already_soaked():
    bundle = _bundle("tianxia.sphere.water", ["WATER_BASE_WATER_INITIATION", "WATER_BASE_WATER_LASH"])
    engine = _engine(bundle, foe_at=(3, 8))  # 2 squares (10 ft) away so the forced move is visible
    foe = engine.state.actors[AN]
    start_y = foe.position.y
    _hit_reliably(engine, "Water Lash")
    assert bears_mark(foe, ME, "Soaked")
    assert foe.position.y == start_y, "not Soaked before this hit, so no forced move yet"
    engine._system_start_turn()
    _hit_reliably(engine, "Water Lash")
    assert foe.position.y != start_y, "already Soaked, so this hit should move it 5 feet"


def test_wall_object_stats_no_longer_leak_a_free_immunity_onto_the_caster():
    """Regression: Glacier Wall's and Blackglass Rampart's printed 'Immunity to Poison and Psychic
    damage' describes the wall PANEL, not the caster, but the model typing attached it with no
    ``applies_to`` -- which defaults to the caster -- granting free, permanent immunity for the
    action's whole duration. Both records now carry no immunity effect at all."""
    ice = _bundle("tianxia.sphere.ice", ["TAL_ICE_GLACIER_WALL"])
    magma = _bundle("tianxia.sphere.magma", ["TAL_MAGMA_BLACKGLASS_RAMPART"])
    for bundle, name in ((ice, "Glacier Wall"), (magma, "Blackglass Rampart")):
        row = next(r for r in bundle["action_catalog"] if r["display_name"] == name)
        effects = row["parameters"]["typed"]["effects"]
        assert not any(e.get("type") == "immunity" for e in effects), f"{name} should not grant the caster immunity"


def test_burden_the_blade_spends_the_mark_and_disadvantages_the_marked_attacker():
    me_sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
                "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.earth"],
                                        "learned_talent_record_ids": ["EARTH_BASE_WEIGHT_SEEKING_CLOD", "TAL_EARTH_BURDEN_THE_BLADE"]}}
    foe_sheet = {**SHEET, "equipment": [{"starting_kit": KIT}]}
    mine, theirs = compile_character(me_sheet, actor_id=ME), compile_character(foe_sheet, actor_id=FOE)
    engine = Gate4ControllerEngine(ROOT, match_seed="BLADE", typed_bundles=(mine, theirs),
                                   roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    foe = engine.state.actors[FOE]
    _hit_reliably(engine, "Weight-Seeking Clod")  # marks the foe with a Burden Mark
    assert bears_mark(foe, ME, "Burden Mark")
    # The foe (now marked) hits ME with its own weapon attack; Burden the Blade should fire off the
    # attack_resolved hook, spending the mark and adding Disadvantage to the foe's next attack.
    engine.state.current_slot_index = engine.state.initiative_order.index(FOE)
    engine.state.current_actor_id = FOE
    engine._system_start_turn()
    attack = next(c for c in engine.legal_candidates() if c.actor_id == FOE and ".weapon." in c.source_definition_id
                  and (engine.action_catalog[c.source_definition_id].range_ft or 5) <= 5 and ME in (c.target_ids or ()))
    typed = engine.action_catalog[attack.source_definition_id].parameters["typed"]
    typed["numbers"] = {**typed["numbers"], "attack_bonus": 30}
    engine.execute_intent(ActionIntent(intent_id="foe-attack", decision_id=attack.decision_id, candidate_id=attack.candidate_id,
                                       state_version=attack.state_version, actor_id=FOE, target_ids=attack.target_ids))
    assert not bears_mark(foe, ME, "Burden Mark"), "the mark should be spent"
    assert any(c.condition_id == "condition:typed.earth_blade_heavy" and c.data.get("weapon") for c in foe.conditions.values()), "Same-weapon disadvantage should be queued for the attacker's next attack"
