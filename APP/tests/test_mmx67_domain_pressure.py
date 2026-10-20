"""MMX67 (DeepSeek DS9 #2) and its pre-merge review fixes (MMX67r): Domain Manifestation's free Spiritual-Pressure clause.

The printed Domain Pressure clause (CL15, "Once on each of your turns, when a creature in the Domain fails a
saving throw against one of your Spirit Awakening Path or Subpath features, impose one ordinary Spiritual
Pressure effect on it without additional cost") lived in the feature's own MODIFIER, but
factory_compiler.apply_modifiers skips every owned mechanic whose activation economy is action/bonus_action/
reaction -- and Domain Manifestation is a Bonus Action -- so no modifier row ever compiled, no diagnostic was
emitted, and combat/rules/feature_status.d/spirit.json still claimed the clause was "applied".

The clause now rides on the feature's own compiled action (combat/ext/save_trigger_riders.py) and runs on the
engine's after_save_resolved seam. MMX67r fixed what the independent review found wrong with the first cut:
the trigger list recognised only two of the three record namespaces (so no Subpath save ever qualified), the
rider read the pre-override outcome (so a converted-to-success save was still pressured and a
converted-to-failure one was not), it fired on other turns, it applied its effect without asking the player
which one, and its log line and GM rider leaked a module path. Each of those has a failing test below.

These tests are at the level the bug showed: real engine, real actions, real failed saves, real conditions,
the player's real table choice, plus the once-per-turn limit surviving a real table commit and reload.
"""

import json
import zipfile
from pathlib import Path

from combat import ext
from combat.ext import save_trigger_riders as strig
from combat.ext import spirit_awakening as sa
from combat.ext.ability_source import is_path_or_subpath_feature
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN, BAI
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.domain_manifestation"
MIND_SPIKE = "tianxia.path.spirit_awakening.feature.mind_spike"
DOMAIN = "tianxia.path.spirit_awakening.feature.domain_manifestation"
DOMAIN_PRESSURE = "tianxia.path.spirit_awakening.feature.domain_pressure"
# A Spirit Awakening Subpath feature. The tradition features are filed under tianxia.tradition.*, which is
# the namespace the first cut of this rider never looked at, so its save never qualified.
NIGHTMARE_TOUCH = "tianxia.tradition.spirit.dream_eater.feature.nightmare_touch"


def _sheet(*path_features, cl=15, spheres=True, dc=None):
    """A Spirit Awakening with the given Path and Subpath features. ``spheres=False`` drops the Ash talents so a test can
    prove the clause stays silent for a character that does not own the feature at all; ``dc`` lowers the Cultivation
    Save DC so a test can state the save outcome it needs without touching the roll."""
    stats = {**SHEET["ability_scores_and_statistics"], "primary_resource": {"name": "Resonance", "maximum": 30}}
    if dc is not None:
        stats["technique_save_dc"] = int(dc)
    return {**SHEET, "equipment": [{"starting_kit": KIT}],
            "identity": {**SHEET["identity"], "cultivation_level": cl, "path": "Spirit Awakening", "key_ability": "WIS"},
            "ability_scores_and_statistics": stats,
            "path_and_subpath": {"path_feature_record_ids": list(path_features)},
            "spheres_and_talents": {**SHEET["spheres_and_talents"]} if spheres else
                                   {"sphere_record_ids": [], "learned_talent_record_ids": []}}


def _engine(*path_features, cl=15, spheres=True, seed="MMX67", foes=(AN,), dc=None):
    bundle = compile_character(_sheet(*path_features, cl=cl, spheres=spheres, dc=dc), actor_id=ME)
    teams = {ME: "team:a", **{foe: "team:b" for foe in foes}}
    places = {ME: {"x": 3, "y": 6}, **{foe: {"x": 4 + i * 3, "y": 6} for i, foe in enumerate(foes)}}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, *foes], "team_by_actor": teams,
                                                 "starting_positions": places})
    return engine, bundle


def _turn(engine, actor_id=ME):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def _do(engine, name, *, destination=None):
    candidate = next(c for c in engine.legal_candidates()
                     if (c.display_name == name or c.display_name.startswith(name + " "))
                     and (destination is None or c.destination == destination))
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _open_the_domain(engine):
    """Manifest the Domain, with Resonance to pay for it, and hand the turn back to its owner."""
    _turn(engine)
    engine.state.actors[ME].resources["resource:core.resonance"] = 30
    _do(engine, "Domain Manifestation")


def _pressed(actor):
    return [c.condition_id for c in actor.conditions.values() if c.condition_id.startswith(sa.PRESSURE_PREFIX)]


def _do_on(engine, name, target_id):
    """Use a single-target ability on one chosen creature (each target is its own menu candidate)."""
    candidate = next(c for c in engine.legal_candidates()
                     if (c.display_name == name or c.display_name.startswith(name + " ")) and target_id in (c.target_ids or ()))
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _rider_events(engine):
    return [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED" and e.payload.get(strig.RIDER)]


def _saves(engine, who):
    return [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == who]


def _failed(engine, who):
    return any((e.payload or {}).get("dc") is not None and (e.payload or {}).get("success") is False
               for e in _saves(engine, who))


def _fixed_saves(monkeypatch, natural):
    """Force every saving throw the named creature makes to one natural die, so a test states the outcome
    it is about instead of hoping for one."""
    from combat.gate2_rolls import DeterministicRollAuthority

    real = DeterministicRollAuthority.d20

    def dice(roller, **kwargs):
        while True:
            roll = real(roller, **kwargs)
            if not str(kwargs.get("reason", "")).startswith("SAVE:") or roll.natural_result == natural:
                return roll

    monkeypatch.setattr(DeterministicRollAuthority, "d20", dice)


def _resonance_mark(engine, subject_id):
    from combat import typed_executor

    engine._apply_condition(engine.state.actors[subject_id], typed_executor.mark_condition_id("Resonance", ME), "test", ME,
                            expires_on="UNTIL_REMOVED")


def _owner_mind_spike(engine, target_id):
    """The owner's Mind Spike resolved from a reaction on somebody else's turn, the way Echo Counter's
    "Use Mind Spike against the attacker" option does (combat/ext/echo_step_disciple.py)."""
    from combat.ext import spirit_traditions as st

    return st.mind_spike(engine, engine.state.actors[ME], engine.state.actors[target_id], getattr(engine, "_active_intent", None))


def _answering(engine, pick, seen=None):
    """A real reaction provider that takes one option of this rider's choice and declines every other
    reaction, so the fight's other reactions behave exactly as they do with nobody listening."""
    from combat.gate2_runtime_models import ReactionDecision

    def provider(request):
        if request.get("reaction_source_id") != strig.CHOICE_ID:
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None
        choice = request.get("choice_trigger") or {}
        if seen is not None:
            seen.update(choice)
            seen["_reactor_id"] = request.get("reactor_id")
        option = pick(choice) if callable(pick) else pick
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"],
                                selection="USE", option_ids=(option,)), None

    engine.set_reaction_provider(provider)


# ----------------------------------------------------------------------------------------------- it compiles
def test_the_free_pressure_clause_compiles_onto_the_feature_itself():
    """The dropped modifier rides on Domain Manifestation's own action: no new button, no separate ability, and
    owning the feature adds nothing but the feature's own action."""
    _engine(DOMAIN, MIND_SPIKE)
    plain = _engine(MIND_SPIKE)
    bundle = _engine(DOMAIN, MIND_SPIKE)[1]
    action = next(a for a in bundle["action_catalog"] if "domain_manifestation" in a["source_definition_id"])
    rider = action["parameters"]["save_trigger_rider"]
    assert rider["feature"] == DOMAIN
    assert rider["limit"] == "once_per_turn"
    assert [e["type"] for e in rider["effects"]] == ["spiritual_pressure"]
    assert sorted(rider["features"]) == sorted([DOMAIN, MIND_SPIKE]), "the trigger is 'one of your Path/Subpath features'"
    added = ({a["source_definition_id"] for a in bundle["action_catalog"]}
             - {a["source_definition_id"] for a in plain[1]["action_catalog"]})
    assert added == {action["source_definition_id"]}, "the clause adds no action of its own"


def test_a_character_who_does_not_own_the_feature_carries_nothing():
    """Inert for everyone else: the plug-in never attaches a rider to a character without the feature."""
    _, bundle = _engine(MIND_SPIKE)
    assert not any(strig.RIDER in (a.get("parameters") or {}) for a in bundle["action_catalog"])


# ------------------------------------------------------------------------------- it fires on a failed save
def test_a_creature_in_the_domain_that_fails_a_save_against_a_path_feature_suffers_one_free_pressure_effect():
    """The bug: a failed Wisdom save against Mind Spike inside the live Domain left only the Resonance Mark."""
    engine, _bundle = _engine(DOMAIN, MIND_SPIKE)
    _open_the_domain(engine)
    an = engine.state.actors[AN]
    _turn(engine)
    _do(engine, "Mind Spike")
    assert _pressed(an), "Domain Pressure: the free ordinary Spiritual Pressure now fires on the failed save"
    assert any(c.condition_id.startswith(sa.PRESSURE_SHAKEN) for c in an.conditions.values()), \
        "the chosen ordinary effect (Shaken Purpose) is applied, not just an empty marker"
    assert len(_rider_events(engine)) == 1


def test_the_free_pressure_costs_nothing():
    """"without additional cost": no Resonance, no extra action economy, no extra Resonance spent by the free rider."""
    engine, _bundle = _engine(DOMAIN, MIND_SPIKE)
    _open_the_domain(engine)
    before = engine.state.actors[ME].resources["resource:core.resonance"]
    _turn(engine)
    _do(engine, "Mind Spike")
    assert engine.state.actors[ME].resources["resource:core.resonance"] == before, "the free clause spends no Resonance"


def test_it_can_happen_only_once_on_your_turn():
    """"This can occur only once during the turn, regardless of the number of failed saves, targets, echoes, or
    origins created by the activation" -- one cone, two creatures inside the Domain, both fail: only the first
    suffers the free ordinary Spiritual Pressure."""
    engine, _bundle = _engine(DOMAIN, MIND_SPIKE, DOMAIN_PRESSURE, foes=(AN, BAI))
    _open_the_domain(engine)
    an, bai = engine.state.actors[AN], engine.state.actors[BAI]
    _turn(engine)
    from combat.gate2_runtime_models import Position
    engine.typed_control_modes = {ME: "LOCAL_AUTO"}  # choose the two foes, excluding the caster
    _do(engine, "Domain Pressure", destination=Position(x=4, y=6))  # aim the printed cone at both creatures
    assert len(_rider_events(engine)) == 1, "one activation, one free Spiritual Pressure"
    pressed = [c for c in _pressed(an) + _pressed(bai)]
    assert pressed, "one of the two creatures that failed is pressured"
    assert len(pressed) <= 2, "no stacking: the clause imposes one effect on one creature"


def test_it_is_available_again_on_your_next_turn_and_stays_quiet_through_the_enemy_turn(monkeypatch):
    """"Once on each of your turns" -- the enemy's turn in between neither fires it (that is not your turn) nor
    spends it, so it is still waiting for you when your turn comes round again."""
    _fixed_saves(monkeypatch, 1)
    engine, _bundle = _engine(DOMAIN, MIND_SPIKE, foes=(AN, BAI))
    _open_the_domain(engine)
    _turn(engine)
    _do(engine, "Mind Spike")
    assert len(_rider_events(engine)) == 1
    _turn(engine, AN)                                     # the Domain owner's turn passes
    _owner_mind_spike(engine, AN)                         # ... and the owner lands a save from a reaction on it
    assert len(_rider_events(engine)) == 1, "no second free pressure on somebody else's turn"
    _turn(engine)                                         # and comes round again
    _do(engine, "Mind Spike")
    assert len(_rider_events(engine)) == 2, "once on each of your turns"


# ------------------------------------------------------------------------------- review fix 1: Subpaths
def test_the_own_feature_list_counts_path_subpath_and_tradition_records():
    """"one of your Path or Subpath features" -- a Path record, a Subpath record and the Spirit Awakening
    subpaths filed under tianxia.tradition.* are all one of yours; a Sphere talent, a sphere record and a
    Foundation base ability are not."""
    for feature_id in (MIND_SPIKE, DOMAIN,
                       "tianxia.subpath.qi.banner_cultivator.feature.banner_call",
                       NIGHTMARE_TOUCH, "tianxia.tradition.spirit.echo_step_disciple.feature.echo_counter"):
        assert is_path_or_subpath_feature(feature_id), feature_id
    for feature_id in ("TAL_SCOUNDREL_DOUBLE_DIP", "tianxia.talent.beauty.beauty_in_motion",
                       "tianxia.sphere.the_piercing_needle", "foundation.ancient_desolate_sacred_body_v0_2C.saint_body_rebuke",
                       "action:typed.abc123.weapon.held", ""):
        assert not is_path_or_subpath_feature(feature_id), feature_id


def test_a_subpath_feature_save_qualifies(monkeypatch):
    """Review finding 1: Nightmare Touch is a Subpath feature and it makes a Wisdom save, so a creature that
    fails it inside the Domain suffers the free ordinary Spiritual Pressure. The first cut compiled a trigger
    list of Path ids only, so a subpath could never reach this clause."""
    _fixed_saves(monkeypatch, 1)
    engine, bundle = _engine(DOMAIN, MIND_SPIKE, NIGHTMARE_TOUCH)
    rider = next(a for a in bundle["action_catalog"]
                 if "domain_manifestation" in a["source_definition_id"])["parameters"][strig.RIDER]
    assert NIGHTMARE_TOUCH in rider["features"], "a Subpath feature is one of your own Path/Subpath features"
    _open_the_domain(engine)
    an = engine.state.actors[AN]
    _resonance_mark(engine, AN)            # Nightmare Touch reaches a Resonance Marked creature
    _turn(engine)
    _do_on(engine, "Nightmare Touch", AN)
    assert _failed(engine, AN), "the foe's Wisdom save against the Subpath feature failed"
    assert _pressed(an), "the free ordinary Spiritual Pressure fires on a failed Subpath save"
    assert len(_rider_events(engine)) == 1


def test_a_sphere_talent_save_does_not_qualify(monkeypatch):
    """The nonqualifying control for the same run: the character's own Sphere talent is not a Path or Subpath
    feature, however it is the same character's ability and the target is standing in the Domain."""
    _fixed_saves(monkeypatch, 1)
    engine, _bundle = _engine(DOMAIN, MIND_SPIKE)
    _open_the_domain(engine)
    an = engine.state.actors[AN]
    _turn(engine)
    _do(engine, f"Ashfall at {an.position.x},{an.position.y}")
    assert not _pressed(an)
    assert not _rider_events(engine)


# ------------------------------------------------------------------- review fix 2: the final save outcome
def test_pressure_does_not_fire_when_the_failed_save_is_converted_to_a_success(monkeypatch):
    """Review finding 2: Omen Witness, Unbroken Brace and the War Leader all buy a rolled failure back after
    ``after_save`` has already run. The creature survives, so it suffers nothing, and the use is not spent."""
    _fixed_saves(monkeypatch, 1)
    engine, _bundle = _engine(DOMAIN, MIND_SPIKE)
    _open_the_domain(engine)
    an = engine.state.actors[AN]
    _turn(engine)
    engine._typed_roll_outcome = {AN: "success"}   # the engine's own outcome channel, as Omen Witness uses it
    _do(engine, "Mind Spike")
    assert not _pressed(an), "a save that finally succeeded reaches the creature with no pressure"
    assert not _rider_events(engine)
    assert f"{strig.TURN_FLAG}:{DOMAIN}" not in engine.state.actors[ME].turn_flags, "the use was not spent"


def test_pressure_fires_when_a_successful_save_is_converted_to_a_failure(monkeypatch):
    """The other direction: a rolled success turned into a failure (Rewrite Fate) is a failure the clause
    must see, which the pre-override hook could not. The Cultivation Save DC is dropped so the rolled save
    really does succeed before the conversion, which is what makes this the opposite case."""
    _fixed_saves(monkeypatch, 20)
    engine, _bundle = _engine(DOMAIN, MIND_SPIKE, dc=5)
    _open_the_domain(engine)
    an = engine.state.actors[AN]
    _turn(engine)
    engine._typed_roll_outcome = {AN: "failure"}
    _do(engine, "Mind Spike")
    [save] = _saves(engine, AN)
    assert (save.payload or {}).get("success") is True, "the save really did succeed on the roll"
    assert _pressed(an), "a save that finally failed is pressured"
    assert len(_rider_events(engine)) == 1


# ------------------------------------------------------------------------------- review fix 3: your turn
def test_it_does_not_fire_off_the_owners_own_turn(monkeypatch):
    """Review finding 3: Echo Counter lets the defender resolve Mind Spike on the attacker's turn (see
    combat/ext/echo_step_disciple.py, which drives the same helper). That is somebody else's turn, so the
    "once on each of your turns" clause is silent and the attacker's save is spared -- while the same save on
    the owner's own turn still pressures."""
    _fixed_saves(monkeypatch, 1)
    engine, _bundle = _engine(DOMAIN, MIND_SPIKE, foes=(AN, BAI))
    _open_the_domain(engine)
    an = engine.state.actors[AN]
    _turn(engine, AN)                                 # the foe's turn: the owner resolves Mind Spike as a reaction
    assert _owner_mind_spike(engine, AN)
    assert _failed(engine, AN), "the foe's save against Mind Spike did fail"
    assert not _pressed(an), "the free clause is not available on somebody else's turn"
    assert not _rider_events(engine)
    _turn(engine)                                     # the owner's own turn: the same save does qualify
    _do_on(engine, "Mind Spike", AN)
    assert _pressed(an)
    assert len(_rider_events(engine)) == 1


# ----------------------------------------------------------------------- review fix 4: the player chooses
def test_the_player_is_asked_which_effect_the_free_clause_imposes():
    """Review finding 4: free is not automatic. The trigger opens a real table choice naming the ability, the
    action that failed and the creature, with the character's standing effect offered first; an AI owner
    answers for itself, and an owner nobody is answering for takes the standing effect."""
    engine, _bundle = _engine(DOMAIN, MIND_SPIKE)
    _open_the_domain(engine)
    seen = {}
    _answering(engine, "heavy_soul", seen)
    _turn(engine)
    _do(engine, "Mind Spike")
    an = engine.state.actors[AN]
    assert seen, "the free clause asks the player once"
    assert "Domain Manifestation" in seen["prompt"], seen["prompt"]
    assert "Mind Spike" in seen["prompt"], "the prompt names the action that made it fail"
    assert an.display_name in seen["prompt"], "the prompt names the creature affected"
    assert "nothing" in seen["prompt"].lower(), "the prompt says what it costs"
    assert seen["automatic"] is True, "an AI actor answers for itself"
    assert seen["_reactor_id"] == ME
    assert sorted(seen["needle_options"]) == sorted(sa.PRESSURE_LABELS), "every ordinary effect is on offer"
    assert seen["preferred"] == seen["needle_options"][:1], "the standing effect is offered first"
    assert any("Heavy Soul" in str(label) for label in seen["labels"].values()), seen["labels"]
    assert _pressed(an)
    assert any(c.data.get("option") == "heavy_soul" for c in an.conditions.values()), \
        "the effect the player picked is the one imposed, not the standing one"


def test_an_ai_owner_answers_the_choice_itself():
    """The AI path: LocalDeterministicController answers the same choice without a player, and the effect it
    picked is the one that lands."""
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_context import build_reaction_context
    from combat.gate4_policy import PolicyLibrary

    engine, _bundle = _engine(DOMAIN, MIND_SPIKE)
    _open_the_domain(engine)
    controller, policies = LocalDeterministicController(), PolicyLibrary(ROOT)

    def react(request, engine=engine):
        policy, _ = policies.for_actor(request["reactor_id"])
        choice = controller.choose_reaction(build_reaction_context(engine, policy, request))
        return choice.decision, choice.record.model_dump(mode="json")

    engine.set_reaction_provider(react)
    _turn(engine)
    _do(engine, "Mind Spike")
    an = engine.state.actors[AN]
    assert _pressed(an), "the AI owner resolved the free pressure without a player"
    assert len(_rider_events(engine)) == 1


# ------------------------------------------------------------------------------ the gates that keep it honest
def test_a_creature_outside_the_domain_gets_nothing():
    """"a creature in the Domain" -- the rider rides the live aura, so a creature that walked out of it is spared."""
    engine, _bundle = _engine(DOMAIN, MIND_SPIKE, foes=(AN, BAI))
    _open_the_domain(engine)
    an, bai = engine.state.actors[AN], engine.state.actors[BAI]
    bai.position = bai.position.model_copy(update={"x": bai.position.x + 4})   # 40 feet out: outside the 30-foot
                                                                          # aura, still inside Mind Spike's reach
    _turn(engine)
    _do_on(engine, "Mind Spike", BAI)           # aimed at the creature that left the Domain
    assert not _pressed(bai), "outside the aura there is no free Spiritual Pressure"
    assert not _rider_events(engine)


def test_nothing_happens_before_the_domain_is_manifested():
    engine, _bundle = _engine(DOMAIN, MIND_SPIKE)
    an = engine.state.actors[AN]
    _turn(engine)
    _do(engine, "Mind Spike")
    assert not _pressed(an), "the clause belongs to the Domain, not to the character"
    assert not _rider_events(engine)


def test_a_save_against_something_that_is_not_a_path_feature_gets_nothing():
    """"one of your Spirit Awakening Path or Subpath features" -- the owner's own Sphere talent is not one, even
    though it is the same character's ability and the target is standing in the Domain."""
    engine, _bundle = _engine(DOMAIN, MIND_SPIKE)
    _open_the_domain(engine)
    an = engine.state.actors[AN]
    _turn(engine)
    _do(engine, f"Ashfall at {an.position.x},{an.position.y}")   # a Sphere talent, not a Path/Subpath feature
    assert not _pressed(an)
    assert not _rider_events(engine)


# -------------------------------------------------------------------------- review fix 5: player-facing text
def test_the_log_line_names_what_happens_what_it_suffers_and_for_how_long():
    """Review finding 5: the passive line must not leak the plug-in, and must name the effect that landed."""
    engine, _bundle = _engine(DOMAIN, MIND_SPIKE)
    _open_the_domain(engine)
    _turn(engine)
    _do(engine, "Mind Spike")
    [event] = _rider_events(engine)
    text = event.payload["text"]
    assert "save_trigger_riders" not in text and "combat/ext" not in text and ".py" not in text, text
    assert "Shaken Purpose" in text and "Disadvantage" in text, text
    assert "your next turn" in text, text
    assert "Mind Spike" in text and "Bloodied" not in text, "it names the action that made the creature fail"
    assert "30" not in text and "1d" not in text, "no internal numbers"


def test_the_choices_read_for_someone_new():
    """Item 13: every option says what it does, to whom, and how long it lasts; no internal ids, no jargon."""
    engine, _bundle = _engine(DOMAIN, MIND_SPIKE)
    _open_the_domain(engine)
    seen = {}
    _answering(engine, lambda choice: choice["needle_options"][0], seen)
    _turn(engine)
    _do(engine, "Mind Spike")
    for option, label in seen["labels"].items():
        assert "Disadvantage" in label or "Reactions" in label or "Speed" in label or "move closer" in label \
            or "learn" in label, f"{option} says what it does: {label}"
        assert "your next turn" in label, f"{option} says how long it lasts: {label}"
        assert engine.state.actors[AN].display_name in label, f"{option} says who it affects: {label}"
        for leak in (".py", "combat/", "tianxia.", "condition:", "START_OF", "clamp", "effect type"):
            assert leak not in label, f"{option} leaks {leak!r}: {label}"


def test_no_player_facing_text_leaks_an_implementation_path():
    """Review finding 5: the GM rider the table prints, and the passive line it logs, must not tell a player
    which file implements them. The rider text lives in the shipped typed authority, and nothing the engine
    compiles from it may name a module."""
    engine, bundle = _engine(DOMAIN, MIND_SPIKE)
    _open_the_domain(engine)
    _turn(engine)
    _do(engine, "Mind Spike")
    [event] = _rider_events(engine)
    text = event.payload["text"]
    assert "save_trigger_riders" not in text and "combat/ext" not in text and ".py" not in text, text
    assert "Shaken Purpose" in text and "Disadvantage" in text, "it names the effect that landed"
    assert "your next turn" in text, "and how long it lasts"
    assert "Mind Spike" in text, "and the action that made the creature fail"
    assert "30" not in text and "1d" not in text, "no internal numbers"
    assert "combat/ext" not in json.dumps(bundle), "nothing the engine compiles names a module"
    riders = [str(r) for r in
              (json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/spirit.json").read_text())
               ["mechanics"][DOMAIN].get("riders") or [])]
    assert not any("combat/ext" in r or ".py" in r for r in riders), riders
    assert any("one of your own Spirit Awakening Path or Subpath features" in r for r in riders), \
        "the shipped rider still says what the clause does, in plain words"


# ------------------------------------------------------------------------------ the real table boundary
def _table_sheet():
    from tests.test_factory_combat_compiler import SHEET as FULL

    return {**json.loads(json.dumps(FULL)),
            "ability_scores_and_statistics": {**FULL["ability_scores_and_statistics"],
                                              "primary_resource": {"name": "Resonance", "maximum": 30}},
            "path_and_subpath": {"path_feature_record_ids": [MIND_SPIKE, DOMAIN]},
            "identity": {**FULL["identity"], "path": "Spirit Awakening", "key_ability": "WIS"}}


def _table(tmp_path, seed="MMX67-TABLE"):
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService

    for side in ("left", "right"):
        folder = tmp_path / "portable_characters" / side
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(_table_sheet()))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "MMX67 yard", "width_squares": 12, "height_squares": 8, "walls": [],
                               "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    modes = {FACTORY_ACTOR_PREFIX + side: "MANUAL" for side in ("left", "right")}
    view = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"],
                                       control_modes=modes, arena_id="battlefield:map.mmx67-yard", match_seed=seed)
    return combat, TabletopService(combat, tmp_path), view["match_id"]


def _send(table, mid, source_fragment, answer_for=None, answers=()):
    """Click a menu action by its source id, exactly as the table offers it, answering a choice if the
    table asks for one. Returns (result, prompts)."""
    prompts = []
    for _ in range(8):
        state = table.state(mid)
        menu = state["menu"]
        group = next(g for g in menu["actions"] if source_fragment in g["source_definition_id"])
        result = table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                           state["last_sequence"], list(answers))
        if result["status"] != "REACTION_REQUIRED":
            return result, prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        if answer_for is None:
            return result, prompts
        answers = [{**prompt["context"], "selection": "USE", "option_ids": [answer_for]}]


def test_the_clause_and_its_once_per_turn_mark_survive_a_real_table_commit_and_reload(tmp_path):
    """The whole thing, through the real table: the Domain is manifested, a creature inside it fails a save against
    a Path feature, the player is asked which effect lands, and both the effect and the once-per-turn mark that
    spent it are still there after the fight is written to disk and loaded back (plain strings and conditions,
    no floats and no objects)."""
    from combat.gate5_service import CombatService

    combat, table, mid = _table(tmp_path)
    assert _send(table, mid, "domain_manifestation")[0]["status"] == "COMMITTED"
    result, prompts = _send(table, mid, "mind_spike", answer_for="heavy_soul")
    assert result["status"] == "COMMITTED", result
    assert len(prompts) == 1, "the table asked the player which ordinary effect lands"
    prompt = prompts[0]
    assert "Domain Manifestation" in prompt["trigger"] and "Mind Spike" in prompt["trigger"], prompt["trigger"]
    assert {o["id"] for o in prompt["choice"]["options"]} == set(sa.PRESSURE_LABELS), prompt["choice"]
    assert not prompt["choice"]["allow_decline"], "the printed clause imposes the effect; it is not optional"

    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = reloaded.engine
    rider = [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED" and e.payload.get(strig.RIDER)]
    assert len(rider) == 1, "the free Spiritual Pressure fired through the real table"
    pressed = [c for actor in engine.state.actors.values() for c in actor.conditions.values()
               if c.condition_id.startswith(sa.PRESSURE_PREFIX)]
    assert pressed, "and the ordinary Spiritual Pressure effect is on a creature after the reload"
    assert any(c.data.get("option") == "heavy_soul" for c in pressed), "the effect the player chose survived the reload"
    flag = f"{strig.TURN_FLAG}:{DOMAIN}"
    spent = next((a.turn_flags.get(flag) for a in engine.state.actors.values()
                  if a.entity_id.startswith("actor:factory")), None)
    assert isinstance(spent, str) and spent, "the once-per-turn mark survived commit + reload as a plain string"
    assert reloaded.mechanical.replay()["status"] == "PASS", "the saved fight still replays"


def test_revealed_disturbance_promises_only_the_information_in_the_committed_and_reloaded_table_log(tmp_path):
    """SOL101: choose the reveal at the real table, then check its promise against the saved result.

    This effect reports a health band and the owner's mark, rather than exact HP or afflictions.
    The choice, success description, and actual information must agree after commit and reload.
    """
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.typed_executor import bears_mark

    _combat, table, mid = _table(tmp_path)
    assert _send(table, mid, "domain_manifestation")[0]["status"] == "COMMITTED"
    after = table.state(mid)["last_sequence"]
    # The save-trigger reveal happens before Mind Spike's damage and new mark, so verify the
    # information against the state at the trigger, rather than the action's later final state.
    before_actors = _combat._load_session(mid).engine.state.actors
    result, prompts = _send(table, mid, "mind_spike", answer_for="revealed_disturbance")
    assert result["status"] == "COMMITTED", result
    [prompt] = prompts
    label = next(o["label"] for o in prompt["choice"]["options"] if o["id"] == "revealed_disturbance")
    assert "only its health band" in label, label
    assert "0 Hit Points" in label and "Bloodied" in label, label
    assert "half its maximum Hit Points or less" in label, label
    assert "more than half" in label, label
    assert "whether it bears your Resonance Mark (your spiritual mark)" in label, label
    assert "afflictions" not in label and "its current state" not in label, label
    assert "costs you nothing" in prompt["trigger"], prompt

    combat = CombatService(ROOT, tmp_path)
    session = combat._load_session(mid)
    [rider] = [e for e in session.engine.events if e.payload.get(strig.RIDER)]
    [target_id] = rider.target_ids
    target = session.engine.state.actors[target_id]
    assert target.display_name in label and "your next turn" in label
    at_trigger = before_actors[target_id]
    band = ("at 0 HP" if at_trigger.current_hp <= 0 else
            "Bloodied" if at_trigger.current_hp <= at_trigger.maximum_hp // 2 else "not Bloodied")
    marked = bears_mark(at_trigger, rider.actor_id, sa.RESONANCE_MARK)
    reveal = (f"Revealed Disturbance: {target.display_name} is {band}; "
              f"{'has' if marked else 'does not have'} your Resonance Mark.")
    assert any(c.data.get("option") == "revealed_disturbance" for c in target.conditions.values())
    committed = result["events"]
    reloaded = TabletopService(combat, tmp_path).events(mid, after)
    assert committed == reloaded, "the table's committed information survives a fresh service reload"
    summaries = [row["summary"] for row in reloaded["events"]]
    assert reveal in summaries, (reveal, summaries)
    assert label in rider.payload["text"], "the success description makes the same promise as the option"
    assert rider.payload["text"] in summaries, summaries
    assert session.mechanical.replay()["status"] == "PASS"
