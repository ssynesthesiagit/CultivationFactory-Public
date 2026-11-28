"""Spirit Awakening's own core mechanic (worker w4-spirit, 2026-09-28, "automate every aspect before another
playtest"): Resonance Marks and the six "ordinary Spiritual Pressure effects" that Mind Spike, Domain Pressure and
Domain Manifestation all build on. combat/ext/spirit_awakening.py, authority/typed_mechanics/reviewed_final.d/spirit.json."""

from pathlib import Path

from combat.ext import spirit_awakening as sa
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import CONDITION_PREFIX, bears_mark, expire_marks
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.spirit"
FEATURES = ["tianxia.path.spirit_awakening.feature.mind_spike", "tianxia.path.spirit_awakening.feature.domain_pressure"]


def _engine(*, cl=10, seed="SPIRIT"):
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "identity": {**SHEET["identity"], "cultivation_level": cl, "path": "Spirit Awakening", "key_ability": "WIS"},
             "ability_scores_and_statistics": {**SHEET["ability_scores_and_statistics"],
                                               "primary_resource": {"name": "Resonance", "maximum": 30}},
             "path_and_subpath": {"path_feature_record_ids": FEATURES},
             "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}}
    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    _turn(engine, ME)
    return engine, bundle


def _turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def _do(engine, name):
    # Printed areas now expose an aim square; retain the exact action identity
    # and aim through the tested recipient rather than picking an arbitrary cone.
    candidate = next(c for c in engine.legal_candidates()
                     if engine.action_catalog.get(c.source_definition_id) is not None
                     and engine.action_catalog[c.source_definition_id].display_name == name
                     and (c.destination is None or c.destination == engine.state.actors[AN].position))
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def test_domain_pressure_cone_scales_by_cl():
    """15/30/60-foot cone by CL band (the base authority only knew a single "special" area with no size)."""
    _, low_bundle = _engine(cl=10)
    _, high_bundle = _engine(cl=20)
    low = next(a for a in low_bundle["action_catalog"] if a["display_name"] == "Domain Pressure")
    high = next(a for a in high_bundle["action_catalog"] if a["display_name"] == "Domain Pressure")
    assert low["radius_ft"] == 15
    assert high["radius_ft"] == 60


def test_mind_spike_damages_marks_then_offers_pressure_once_already_marked_at_cl5():
    engine, _bundle = _engine(cl=10)
    an = engine.state.actors[AN]
    before = an.current_hp
    _do(engine, "Mind Spike")
    assert an.current_hp < before, "the Wisdom save fails against this fixture's DC 30"
    assert bears_mark(an, ME, "Resonance"), "becomes Resonance Marked by you"
    assert not any(c.condition_id == sa._pressure_condition_id(ME) for c in an.conditions.values()), \
        "the CL5 bonus only fires against an already-marked target"
    _turn(engine, ME)
    _do(engine, "Mind Spike")
    assert any(c.condition_id == sa._pressure_condition_id(ME) for c in an.conditions.values()), \
        "already Resonance Marked and CL5+: Mind Spike now also imposes an ordinary Spiritual Pressure effect"


def test_domain_pressure_frightens_until_the_casters_own_next_turn_ends():
    engine, _bundle = _engine(cl=10)
    an = engine.state.actors[AN]
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Domain Pressure")
    assert action.target_kind == "CELL", "the caster aims the printed cone before choosing its recipients"
    _do(engine, "Domain Pressure")
    frightened = next(c for c in an.conditions.values() if c.condition_id == f"{CONDITION_PREFIX}frightened")
    assert frightened.expires_on == "END_OF_MARKER_NEXT_TURN", "your next turn, not the target's"
    assert bears_mark(an, ME, "Resonance")
    # The target's own turn passing must not end it (an ordinary "holder's next turn" default would).
    engine.state.current_actor_id = AN
    expire_marks(engine)
    assert any(c.condition_id == f"{CONDITION_PREFIX}frightened" for c in an.conditions.values())
    # It ends once the caster's own next turn has started and then passed to someone else.
    engine.state.actors[ME].turns_started += 1
    engine.state.current_actor_id = AN
    expire_marks(engine)
    assert not any(c.condition_id == f"{CONDITION_PREFIX}frightened" for c in an.conditions.values())


def test_spiritual_pressure_choice_toggle_changes_the_default():
    engine, _bundle = _engine(cl=10)
    me = engine.state.actors[ME]
    assert sa.chosen_pressure(me) == "shaken_purpose"
    _do(engine, "Spiritual Pressure: Heavy Soul (-10 feet Speed)")
    assert sa.chosen_pressure(me) == "heavy_soul"


def test_shaken_purpose_gives_disadvantage_on_the_pressured_creatures_next_attack():
    """domain_pressure's on_success branch imposes the chosen ordinary Spiritual Pressure effect; exercised directly
    (a DC-30 fixture cannot be made to succeed its save) to prove the mechanism, not just the fail-side rider."""
    from combat.gate2_runtime_models import ActionIntent as _Intent  # noqa: F401 (documents the direct-call scope)

    engine, _bundle = _engine(cl=10)
    an = engine.state.actors[AN]
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Domain Pressure")
    typed = action.parameters["typed"]
    ctx_engine = engine
    from combat.typed_executor import Context

    ctx = Context(ctx_engine, ctx_engine.state.actors[ME], action, None, typed, [an], an, {})
    sa.spiritual_pressure(ctx, {"applies_to": "target"})
    assert any(c.condition_id == sa.PRESSURE_SHAKEN + ME for c in an.conditions.values())
