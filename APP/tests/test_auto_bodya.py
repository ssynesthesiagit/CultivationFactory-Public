"""Wave-3 follow-up (bodya 2026-09-29): the Body Refining Path's Core Tempering Expression and Blood Pump, and the
Berserker sphere's Advancing Carnage and Heaven-Crushing Exertion. See combat/ext/bodya_body_refining.py and
combat/ext/bodya_berserker.py for what the printed rules say and why each shortcut was taken. Already-built Berserker
pieces (Adrenaline, Batter, the Exertion toggle) are covered by tests/test_auto_body.py and tests/test_auto_gu.py, not
repeated here."""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.bodya_test"

BODY_REFINING_SHEET = {
    **SHEET, "equipment": [],
    "identity": {**SHEET["identity"], "path": "Body Refining", "cultivation_level": 12},
    "ability_scores_and_statistics": {**SHEET["ability_scores_and_statistics"], "primary_resource": {"name": "Stamina", "maximum": 30}},
    "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []},
    "path_and_subpath": {"path_feature_record_ids": [
        "tianxia.path.body_refining.feature.iron_fist", "tianxia.path.body_refining.feature.stamina_guard",
        "tianxia.path.body_refining.feature.core_tempering_expression", "tianxia.path.body_refining.feature.blood_pump",
    ]},
}


def _bundle(talents, spheres=("tianxia.sphere.berserker",), extra=None):
    sheet = {**SHEET, "equipment": [], "spheres_and_talents": {"sphere_record_ids": list(spheres), "learned_talent_record_ids": talents}}
    if extra:
        sheet = {**sheet, **extra}
    return compile_character(sheet, actor_id=ME)


def _engine(bundle, positions=None):
    positions = positions or {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}
    actor_ids = list(positions)
    engine = Gate4ControllerEngine(ROOT, match_seed="BODYA", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": actor_ids,
                                                 "team_by_actor": {actor_id: ("team:a" if actor_id == ME else "team:b") for actor_id in actor_ids},
                                                 "starting_positions": positions})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _guaranteed_hit(engine, candidate):
    typed = engine.action_catalog[candidate.source_definition_id].parameters["typed"]
    typed["numbers"] = {**typed["numbers"], "attack_bonus": 30, "save_dc": 30}


def _use(engine, display_name, target_ids=()):
    candidate = next((c for c in engine.legal_candidates() if c.display_name == display_name and (not target_ids or c.target_ids == target_ids)), None)
    assert candidate is not None, f"{display_name!r} was not a legal candidate"
    _guaranteed_hit(engine, candidate)
    engine.execute_intent(ActionIntent(intent_id=display_name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids))
    return candidate


# ---------------------------------------------------------------- Core Tempering Expression / Golden Bell Circulation

def test_core_tempering_expression_offers_the_three_expressions_only_before_the_first_turn_ends():
    bundle = compile_character(BODY_REFINING_SHEET, actor_id=ME)
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert "Core Tempering Expression: Golden Bell Circulation" in names
    assert "Core Tempering Expression: Blood-Furnace Circulation" in names
    assert "Core Tempering Expression: Mountain-Rending Pulse" in names
    engine = _engine(bundle)
    engine.state.actors[ME].turns_started = 1  # as if the fight were just beginning (tests/test_auto_tabik.py's own convention)
    choices = [c for c in engine.legal_candidates() if c.display_name.startswith("Core Tempering Expression:")]
    assert len(choices) == 3, "all three expressions should be offered on turn 1"
    engine.state.actors[ME].turns_started = 3
    engine.state.current_actor_id = ME
    choices_later = [c for c in engine.legal_candidates() if c.display_name.startswith("Core Tempering Expression:")]
    assert not choices_later, "the build choice should close after the character's first turn"


def test_golden_bell_circulation_grants_ac_and_stamina_guard_zero_grants_temp_hp():
    bundle = compile_character(BODY_REFINING_SHEET, actor_id=ME)
    engine = _engine(bundle)
    me = engine.state.actors[ME]
    me.turns_started = 1
    _use(engine, "Core Tempering Expression: Golden Bell Circulation")
    me.action_available, me.bonus_action_available = True, True
    ac_before = engine._effective_ac(me) if hasattr(engine, "_effective_ac") else None
    bell = next(c for c in engine.legal_candidates() if c.display_name == "Golden Bell Circulation")
    engine.execute_intent(ActionIntent(intent_id="bell", decision_id=bell.decision_id, candidate_id=bell.candidate_id,
                                       state_version=bell.state_version, actor_id=ME, target_ids=bell.target_ids))
    assert any(c.condition_id.startswith("condition:typed.stance.") for c in me.conditions.values()), "Golden Bell should apply a stance condition"
    from combat import ext

    ac_bonus = sum(value for value in (hook(engine, me) for hook in ext._HOOKS.get("ac", [])) if value)
    assert ac_bonus >= 2, "Golden Bell Circulation should add +2 AC while active"
    # Stamina Guard reduces a damage packet to 0 -> Golden Bell's once-per-round Temporary HP. Stamina Guard's own
    # 1d10-per-Stamina-spent roll is not deterministic (and it declines to trigger under its own minimum_damage: 5
    # threshold in the first place), so the event hook that reads its REACTION_RESOLVED outcome is exercised directly,
    # the same shape typed_reactions.on_damage's damage_soak branch actually appends.
    from combat.ext import bodya_body_refining as ctb

    before_temp = me.temporary_hp
    ctb.golden_bell_soak(engine, "REACTION_RESOLVED", {"actor_id": ME, "payload": {"checkpoint": "DAMAGE_APPLICATION", "spend": 1,
                                                                                   "reduction": 6, "pending_before": 5, "pending_after": 0}})
    assert me.temporary_hp > before_temp, "Stamina Guard soaking a hit to 0 should have granted Golden Bell's Temporary HP"


def test_perfected_golden_bell_changes_stamina_guard_to_d12():
    sheet = {**BODY_REFINING_SHEET,
             "identity": {**BODY_REFINING_SHEET["identity"], "cultivation_level": 17},
             "path_and_subpath": {"path_feature_record_ids": [
                 "tianxia.path.body_refining.feature.iron_fist", "tianxia.path.body_refining.feature.stamina_guard",
                 "tianxia.path.body_refining.feature.core_tempering_expression"]}}
    engine = _engine(compile_character(sheet, actor_id=ME))
    me = engine.state.actors[ME]
    me.turns_started = 1
    _use(engine, "Core Tempering Expression: Golden Bell Circulation")
    me.action_available, me.bonus_action_available = True, True
    _use(engine, "Golden Bell Circulation")

    from combat import typed_reactions

    typed_reactions.on_damage(engine, me, 25, 0, source_actor_id=AN)
    guard_rolls = [roll for roll in engine.rolls if roll.reason.startswith("DAMAGE_SOAK:")]
    assert guard_rolls and all("d12" in roll.expression for roll in guard_rolls), \
        "Perfected Golden Bell should make Stamina Guard roll d12s while active"


# ---------------------------------------------------------------------------------------- Advancing Carnage

def test_advancing_carnage_grants_a_bonus_melee_attack_after_reducing_a_creature_to_0_hp():
    from combat.gate2_runtime_content import LEE

    bundle = _bundle(["TAL_BERSERKER_ADVANCING_CARNAGE"])
    engine = _engine(bundle, positions={ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}, LEE: {"x": 3, "y": 5}})
    me, foe, other = engine.state.actors[ME], engine.state.actors[AN], engine.state.actors[LEE]
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith("Advancing Carnage:")]
    foe.current_hp = 1  # any damaging hit reduces it to 0; LEE stays alive as a second hostile for the bonus attack
    strike = next(c for c in engine.legal_candidates() if c.display_name == "Batter" and c.target_ids == (AN,))
    _guaranteed_hit(engine, strike)
    engine.execute_intent(ActionIntent(intent_id="kill", decision_id=strike.decision_id, candidate_id=strike.candidate_id,
                                       state_version=strike.state_version, actor_id=ME, target_ids=strike.target_ids))
    assert not foe.active or foe.current_hp <= 0
    bonus = [c for c in engine.legal_candidates() if c.display_name.startswith("Advancing Carnage:")]
    assert bonus, "reducing a creature to 0 HP with a melee weapon should open a Bonus Action Advancing Carnage attack"
    assert all(c.target_ids == (LEE,) for c in bonus), "the bonus attack should still be able to target the other hostile creature"


# ------------------------------------------------------------------------------------------ Heaven-Crushing Exertion

def test_heaven_crushing_exertion_only_adds_its_bonus_damage_against_an_already_battered_target():
    bundle = _bundle(["TAL_BERSERKER_HEAVEN_CRUSHING_EXERTION"])
    action = next(row for row in bundle["action_catalog"] if row["display_name"] == "Heaven-Crushing Exertion")
    on_hit = action["parameters"]["typed"]["effects"][0]["on_hit"]
    gated = next(effect for effect in on_hit if effect.get("type") == "if_condition")
    assert gated["condition"] == "battered"
    assert any(effect.get("type") == "extra_damage" for effect in gated["effects"])


# --------------------------------------------------------------------------------------------------------- Blood Pump

def test_blood_pump_holds_a_lethal_hit_at_1_hp_once_per_scene():
    # No Stamina Guard on this sheet: it is also a damage_soak reaction, and on_damage returns as soon as one
    # damage-response reaction fires against a hit, so Stamina Guard (offered first) would otherwise eat the
    # response to this same hit before drop_to_zero/Blood Pump is ever reached.
    sheet = {**BODY_REFINING_SHEET, "path_and_subpath": {"path_feature_record_ids": [
        "tianxia.path.body_refining.feature.iron_fist", "tianxia.path.body_refining.feature.blood_pump"]}}
    bundle = compile_character(sheet, actor_id=ME)
    assert any(row.get("name") == "Blood Pump" and row.get("kind") == "drop_to_zero" and
              any(e.get("type") == "hold_at_1hp" for e in row.get("effects") or []) for row in bundle["typed_reactions"]), \
        "Blood Pump should compile as a drop_to_zero response with hold_at_1hp, not sit in skipped.passive"
    engine = _engine(bundle)
    me = engine.state.actors[ME]
    me.resources["resource:core.stamina"] = 10
    me.current_hp = 20
    from combat import typed_reactions

    # Mirrors what block_damage does for a live typed hit (tests/test_auto_ironroot.py's own convention): offer the
    # DAMAGE_APPLICATION reactions (the checkpoint where drop_to_zero/hold_at_1hp is intercepted) first, then commit
    # whatever pending amount survives that offer -- _commit_damage's own reaction hand-off is gated on a real
    # ActionIntent (``if intent is not None``), which a directly-simulated hit in a test does not have.
    pending = typed_reactions.on_damage(engine, me, 999, 0, source_actor_id=AN)
    engine._commit_damage(me, pending, "FORCE", "reaction:test.lethal_hit", AN, None, reaction_depth=0)
    assert me.current_hp == 1, "Blood Pump should have held a lethal hit at 1 HP instead of dropping to 0"


def test_blood_pump_is_checked_after_stamina_guard_reduces_a_lethal_packet():
    sheet = {**BODY_REFINING_SHEET, "identity": {**BODY_REFINING_SHEET["identity"], "cultivation_level": 15},
             "path_and_subpath": {"path_feature_record_ids": [
                 "tianxia.path.body_refining.feature.iron_fist", "tianxia.path.body_refining.feature.stamina_guard",
                 "tianxia.path.body_refining.feature.blood_pump"]}}
    engine = _engine(compile_character(sheet, actor_id=ME))
    me = engine.state.actors[ME]
    me.current_hp = 4
    from combat import typed_reactions

    # The fixed seed makes Guard reduce this packet to exactly the owner's
    # remaining 4 HP. Blood Pump must be offered against that
    # post-soak amount before the damage is committed.
    pending = typed_reactions.on_damage(engine, me, 25, 0, source_actor_id=AN)
    engine._commit_damage(me, pending, "FORCE", "reaction:test.guarded_hit", AN, None, reaction_depth=0)
    assert me.current_hp == 1, "Blood Pump should resolve after Stamina Guard leaves a lethal packet"
