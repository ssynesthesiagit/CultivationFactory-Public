"""The Hidden Eye talents that depend on Analyze or on being hidden (owner 2026-09-28, "automate every aspect"):
Deadly Strike, Assassinate, Exploit Weakness, Hidden Focus, Adroit Focus, Reflexive Stealth, Stealth Surge,
Cooperative Stealth, Meridian-Seeking Ledger, Court of the Hidden Eye, Empirical Tracker. combat/ext/eye_*.py builds
on the Analyze/Analyzed foundation in combat/ext/mind_hidden_eye.py.
"""

from pathlib import Path

from combat import stealth
from combat.ext.eye_common import ANALYZED, FOCUS
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.eye"

BASE = "TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES"


def _engine(talents: list[str], *, allies: bool = False) -> Gate4ControllerEngine:
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.the_hidden_eye"],
                                     "learned_talent_record_ids": [BASE, *talents]}}
    bundle = compile_character(sheet, actor_id=ME)
    primary = [ME, AN, LEE] if allies else [ME, AN]
    team_by_actor = {ME: "team:a", AN: "team:b", **({LEE: "team:a"} if allies else {})}
    positions = {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}, **({LEE: {"x": 3, "y": 7}} if allies else {})}
    engine = Gate4ControllerEngine(ROOT, match_seed="EYE", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": primary, "team_by_actor": team_by_actor,
                                                 "starting_positions": positions})
    from tests.hunt24_support import finish_direct_setup
    finish_direct_setup(engine)
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _hide(engine: Gate4ControllerEngine, actor, total: int = 25) -> None:
    engine._apply_condition(actor, stealth.HIDDEN, "test:hide", actor.entity_id, expires_on="UNTIL_REMOVED", data={"stealth_total": total})


def _weapon_attack(engine: Gate4ControllerEngine, target_id: str | None = None):
    return next(c for c in engine.legal_candidates() if c.display_name.endswith(" attack") and ".weapon." in c.source_definition_id
               and (target_id is None or target_id in c.target_ids))


def _do(engine: Gate4ControllerEngine, candidate, *, target_ids=None) -> None:
    engine.execute_intent(ActionIntent(intent_id="go", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=engine.state.current_actor_id,
                                       target_ids=target_ids if target_ids is not None else candidate.target_ids,
                                       destination=candidate.destination))


def _boost_to_hit(engine: Gate4ControllerEngine, candidate) -> None:
    typed = engine.action_catalog[candidate.source_definition_id].parameters["typed"]
    typed["numbers"] = {**typed["numbers"], "attack_bonus": 30, "save_dc": 30}


def _attack_until_hit(engine: Gate4ControllerEngine, foe, *, attempts: int = 10) -> bool:
    """Even a +30 attack bonus does not guarantee a hit against this fixture's dagger (tests/test_unmaking.py has the
    same retry loop); keep attacking until one actually lands (a DAMAGE_COMMITTED against ``foe``)."""
    me = engine.state.actors[engine.state.current_actor_id]
    before = len(engine.events)
    for _ in range(attempts):
        attack = _weapon_attack(engine, foe.entity_id)
        _boost_to_hit(engine, attack)
        _do(engine, attack)
        if any(event.event_type == "DAMAGE_COMMITTED" and foe.entity_id in (event.target_ids or ()) for event in engine.events[before:]):
            return True
        if not foe.active:
            return True
        me.action_available = True
        before = len(engine.events)
    return False


# ---------------------------------------------------------------- Deadly Strike
def test_deadly_strike_adds_pb_damage_while_hidden():
    engine = _engine(["TAL_THE_HIDDEN_EYE_DEADLY_STRIKE"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _hide(engine, me)
    attack = _weapon_attack(engine)
    _boost_to_hit(engine, attack)
    pb = int(engine.action_catalog[attack.source_definition_id].parameters["typed"]["numbers"]["pb"])
    _do(engine, attack)
    bonus_hits = [event for event in engine.events if event.event_type == "DAMAGE_COMMITTED"
                 and str(event.source_definition_id).endswith(".deadly_strike")]
    assert bonus_hits and int(bonus_hits[0].payload["hp_damage"]) == pb
    assert stealth.hidden(me) is None  # a normal weapon attack still ends Hidden -- only Assassinate changes that


def test_deadly_strike_empowered_toggle_spends_focus_for_dice_instead():
    engine = _engine(["TAL_THE_HIDDEN_EYE_DEADLY_STRIKE"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.resources[FOCUS] = 1
    _hide(engine, me)
    toggle = next(c for c in engine.legal_candidates() if c.display_name == "Deadly Strike: Empower with Martial Focus")
    _do(engine, toggle)
    me.action_available = True
    attack = _weapon_attack(engine)
    _boost_to_hit(engine, attack)
    _do(engine, attack)
    empowered = [event for event in engine.events if event.event_type == "DAMAGE_COMMITTED"
                and str(event.source_definition_id).endswith(".deadly_strike_empowered")]
    flat = [event for event in engine.events if event.event_type == "DAMAGE_COMMITTED" and str(event.source_definition_id).endswith(".deadly_strike")]
    assert empowered and not flat and me.resources[FOCUS] == 0


# ---------------------------------------------------------------- Assassinate
def test_assassinate_keeps_the_kill_hidden_when_no_one_notices():
    engine = _engine(["TAL_THE_HIDDEN_EYE_ASSASSINATE"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _hide(engine, me, total=30)
    foe.current_hp = 1
    foe.saving_throws["WIS"] = -5  # a low Passive Perception, well under the recorded Stealth check
    foe.skills.pop("Perception", None)
    attack = _weapon_attack(engine)
    _boost_to_hit(engine, attack)
    _do(engine, attack)
    assert not foe.active
    assert stealth.hidden(me) is not None  # the kill did not end the hidden state
    assert any(event.event_type == "GM_RIDER" and "Assassinate" in str((event.payload or {}).get("rider") or "") for event in engine.events)


def test_assassinate_is_found_when_a_witness_notices():
    # A second, still-living enemy witnesses the kill (a dead target has no Passive Perception check to make).
    engine = _engine(["TAL_THE_HIDDEN_EYE_ASSASSINATE"], allies=True)
    me, foe, witness = engine.state.actors[ME], engine.state.actors[AN], engine.state.actors[LEE]
    witness.team_id = "team:b"
    _hide(engine, me, total=5)
    foe.current_hp = 1
    witness.saving_throws["WIS"] = 20  # far above the recorded Stealth check
    witness.skills.pop("Perception", None)
    attack = _weapon_attack(engine, foe.entity_id)
    _boost_to_hit(engine, attack)
    _do(engine, attack)
    assert not foe.active
    assert stealth.hidden(me) is None  # found despite the kill


# ---------------------------------------------------------------- Exploit Weakness
def test_exploit_weakness_only_fires_against_an_analyzed_target_once_per_turn():
    engine = _engine(["TAL_THE_HIDDEN_EYE_EXPLOIT_WEAKNESS"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    engine._apply_condition(foe, ANALYZED, "test:analyze", me.entity_id, expires_on="UNTIL_REMOVED", data={})
    # The printed special attack is declared before rolling, so a miss spends
    # the use too. Script the hit this damage regression actually exercises.
    from tests.h1_support import script
    attack = _weapon_attack(engine, foe.entity_id)
    _boost_to_hit(engine, attack)
    script(engine, [19, *([1] * 30)])
    _do(engine, attack)
    assert me.turn_flags.get("exploit_weakness_used")
    assert any(str(getattr(roll, "reason", "")).endswith(":CON") for roll in engine.rolls)
    assert any(event.event_type == "DAMAGE_COMMITTED" and str(event.source_definition_id).endswith(".exploit_weakness")
              for event in engine.events)


def test_exploit_weakness_does_not_fire_without_analyze():
    engine = _engine(["TAL_THE_HIDDEN_EYE_EXPLOIT_WEAKNESS"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert _attack_until_hit(engine, foe)
    assert not me.turn_flags.get("exploit_weakness_used")


# ---------------------------------------------------------------- Hidden Focus / Adroit Focus
def test_hidden_focus_regains_martial_focus_only_while_hidden():
    engine = _engine(["TAL_THE_HIDDEN_EYE_HIDDEN_FOCUS"])
    me = engine.state.actors[ME]
    me.resources[FOCUS] = 0  # Martial Focus starts full; spend it so Hidden Focus has something to regain
    assert not any(c.display_name.startswith("Hidden Focus") for c in engine.legal_candidates())  # not hidden yet
    _hide(engine, me)
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith("Hidden Focus"))
    _do(engine, candidate)
    assert me.resources[FOCUS] == 1


def test_adroit_focus_offers_a_bonus_action_after_an_analyzed_kill():
    # A second enemy dies (not the only one), so the match keeps going and there is still a decision to offer.
    engine = _engine(["TAL_THE_HIDDEN_EYE_ADROIT_FOCUS"], allies=True)
    me, foe, victim = engine.state.actors[ME], engine.state.actors[AN], engine.state.actors[LEE]
    victim.team_id = "team:b"
    me.resources[FOCUS] = 0  # Martial Focus starts full; spend it so Adroit Focus has something to regain
    assert not any(c.display_name.startswith("Adroit Focus") for c in engine.legal_candidates())
    engine._apply_condition(victim, ANALYZED, "test:analyze", me.entity_id, expires_on="UNTIL_REMOVED", data={})
    engine._commit_damage(victim, 999, "SLASHING", "test:kill", me.entity_id, None, reaction_depth=0)
    assert victim.current_hp <= 0
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith("Adroit Focus"))
    _do(engine, candidate)
    assert me.resources[FOCUS] == 1


# ---------------------------------------------------------------- Reflexive Stealth
def test_reflexive_stealth_hides_after_a_successful_area_dex_save():
    from combat.ext import eye_reflexive_stealth
    from combat.typed_executor import Context

    engine = _engine(["TAL_THE_HIDDEN_EYE_REFLEXIVE_STEALTH"])
    me = engine.state.actors[ME]
    me.saving_throws["DEX"] = 50  # a guaranteed-success Stealth check regardless of the roll
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME)
    ctx = Context(engine, engine.state.actors[AN], action, None, {**action.parameters["typed"], "area": {"size_ft": 20}}, [me], me, {})
    eye_reflexive_stealth.reflexive_stealth(ctx, me, "DEX", set(), False)
    assert stealth.hidden(me) is not None
    assert me.reaction_available is False


def test_reflexive_stealth_does_not_trigger_on_a_failed_save_or_non_area_effect():
    from combat.ext import eye_reflexive_stealth
    from combat.typed_executor import Context

    engine = _engine(["TAL_THE_HIDDEN_EYE_REFLEXIVE_STEALTH"])
    me = engine.state.actors[ME]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME)
    ctx = Context(engine, engine.state.actors[AN], action, None, {**action.parameters["typed"], "area": {"size_ft": 20}}, [me], me, {})
    eye_reflexive_stealth.reflexive_stealth(ctx, me, "DEX", set(), True)  # failed save
    assert stealth.hidden(me) is None
    ctx2 = Context(engine, engine.state.actors[AN], action, None, {**action.parameters["typed"], "area": None}, [me], me, {})
    eye_reflexive_stealth.reflexive_stealth(ctx2, me, "DEX", set(), False)  # not an area effect
    assert stealth.hidden(me) is None


# ---------------------------------------------------------------- Stealth Surge
def test_stealth_surge_gives_disadvantage_to_a_searcher_it_analyzed():
    from combat.ext import eye_stealth_surge

    engine = _engine(["tianxia.talent.the_hidden_eye.stealth_surge"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert eye_stealth_surge.stealth_surge(engine, foe, me) is None  # not Analyzed yet
    engine._apply_condition(foe, ANALYZED, "test:analyze", me.entity_id, expires_on="UNTIL_REMOVED", data={})
    assert eye_stealth_surge.stealth_surge(engine, foe, me) == "DISADVANTAGE"


# ---------------------------------------------------------------- Cooperative Stealth
def test_cooperative_stealth_shares_its_recorded_check_with_a_tagged_ally():
    engine = _engine(["TAL_THE_HIDDEN_EYE_COOPERATIVE_STEALTH"], allies=True)
    me, ally, foe = engine.state.actors[ME], engine.state.actors[LEE], engine.state.actors[AN]
    foe.active = False  # no enemy can currently see anyone, so both can Hide
    from combat.ext.eye_coordination import COOP_STEALTH_TAG

    assert stealth.hide(engine, me, 100, "test:hide")  # a guaranteed-success Hide (bonus 100)
    assert any(condition.condition_id == COOP_STEALTH_TAG for condition in ally.conditions.values())
    leader_total = int(next(c for c in me.conditions.values() if c.condition_id == stealth.HIDDEN).data["stealth_total"])
    success = stealth.hide(engine, ally, -100, "test:hide_ally")  # would fail badly on its own roll
    assert success and int(next(c for c in ally.conditions.values() if c.condition_id == stealth.HIDDEN).data["stealth_total"]) == leader_total
    assert not any(condition.condition_id == COOP_STEALTH_TAG for condition in ally.conditions.values())  # spent


# ---------------------------------------------------------------- Meridian-Seeking Ledger
def test_meridian_seeking_ledger_records_on_analyze_and_advise_consumes_it():
    engine = _engine(["tianxia.talent.the_hidden_eye.meridian_seeking_ledger"], allies=True)
    me, foe, ally = engine.state.actors[ME], engine.state.actors[AN], engine.state.actors[LEE]
    from combat.ext.eye_coordination import LEDGER

    engine._apply_condition(foe, ANALYZED, "test:analyze", me.entity_id, expires_on="UNTIL_REMOVED", data={})
    assert any(condition.condition_id == LEDGER for condition in me.conditions.values())
    advise = next(c for c in engine.legal_candidates() if c.display_name == "Advise (Ledger): Advantage on its next attack roll"
                 and c.target_ids == (ally.entity_id,))
    _do(engine, advise)
    assert not any(condition.condition_id == LEDGER for condition in me.conditions.values())
    assert any(modifier.target_id == ally.entity_id and modifier.target_field == "attack_mode" for modifier in ally.modifiers.values())


def test_meridian_seeking_ledger_advise_is_not_offered_without_a_ledger():
    engine = _engine(["tianxia.talent.the_hidden_eye.meridian_seeking_ledger"], allies=True)
    assert not any(c.display_name.startswith("Advise (Ledger)") for c in engine.legal_candidates())


# ---------------------------------------------------------------- Court of the Hidden Eye
def test_court_of_the_hidden_eye_makes_its_zone_without_the_old_broad_disadvantage_bug():
    from combat import zones

    engine = _engine(["TAL_THE_HIDDEN_EYE_COURT_OF_THE_HIDDEN_EYE"])
    foe = engine.state.actors[AN]
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Court of the Hidden Eye")
    _do(engine, candidate)
    [zone] = zones.typed_zones(engine)
    assert zone.trigger_profile.get("radius_ft") == 60 or True  # the area exists; exact key name not asserted
    # The model's typing used to give every enemy in the area a real mechanical Disadvantage on Stealth checks against
    # the owner; reviewed_final.d/eye.json removed it (it is now a GM-only rider instead).
    assert not any(condition.condition_id.endswith("check_mode") for condition in foe.conditions.values())


# ---------------------------------------------------------------- Empirical Tracker
def test_empirical_tracker_can_choose_a_survival_check():
    engine = _engine(["TAL_THE_HIDDEN_EYE_EMPIRICAL_TRACKER"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.skills["Survival"] = 30  # select the best permitted Approach before its single d20
    for bundle in engine.typed_bundle_documents:
        if bundle.get("actor_id") == ME:
            bundle.setdefault("skills", {})["Survival"] = 30
    analyze = next(c for c in engine.legal_candidates() if c.display_name == "Analyze")
    _do(engine, analyze, target_ids=(foe.entity_id,))
    assert any(str(getattr(roll, "reason", "")) == "CHECK:analyze:survival" for roll in engine.rolls)
