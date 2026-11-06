"""Unmaking talents that the table now resolves on its own (automation lane AUTO84).

Owner 2026-09-30: "i want everything we can automated". Each test drives the real table -- a compiled Unmaking
fighter in a Gate 4 fight -- and asserts the printed effect happens. The printed text (rules_text.json) is quoted in
each docstring.

    Unmake the Answer            "Make an Unmaking Check against the triggering effect's save DC." (before this the
                                reaction paid 2 CP and applied the failure branch every time: 3d10 Ruin self-damage
                                and 1 Black Vein Strain were unavoidable)
    The Moment Nothing Answers  "reduce your current and maximum HP by 20 until you finish a Long Rest"
    Splintering Trace           "add one extra d10 Ruin damage. At CL 11, add two extra d10 instead"
    Crack the Guard             "the target must succeed on a Strength or Constitution saving throw, target's choice"
    First Ruin Form             "when the chosen Channel would gain Crack, roll a d6. On a 5 or 6, the Crack is
                                delayed until the form ends; when the form ends, all delayed Crack applies at once"
    Fifth Ruin Form             "structures in the area take Ruin damage equal to your Cultivation Level at the
                                start of each of your turns"
    Retired reminder rows       the compiled Unmaking fighter shows no GM reminder for them any more
"""

from __future__ import annotations

import json
from pathlib import Path

from combat import unmaking
from combat.ext import maximum_hp_riders, save_choices, unmaking_channels, unmaking_forms
from combat.ext import objects as object_ext
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position, RuntimeObjectState
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import ME, events, give, ready, script, use
from tests.test_carry import KIT

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
FOE = "actor:factory.h1_ally"
STRAIN = "resource:named.black_vein_strain"
# Enough Unmaking talents that the named Black Vein Strain pool is compiled for the character.
WITH_STRAIN = ("TAL_UNMAKING_RUIN_CHANNEL", "TAL_UNMAKING_LAST_INCH_CONTROL")


def unmaking_ids() -> list[str]:
    mechanics = json.loads(AUTHORITY.read_bytes())["mechanics"]
    return sorted(key for key, row in mechanics.items() if row.get("sphere_id") == unmaking.UNMAKING)


def _sheet(mids, *, cl=18, hp=250, dc=12, kit=None):
    return {
        "identity": {"proficiency_bonus": 4, "cultivation_level": cl, "path": "Qi Cultivation", "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 18, "modifier": 4} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Stamina", "maximum": 60}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": hp}, "speed": {"walking_ft": 30},
            "technique_save_dc": dc, "technique_attack_bonus": 8,
        },
        "spheres_and_talents": {"sphere_record_ids": [unmaking.UNMAKING], "learned_talent_record_ids": list(mids)},
        "equipment": [{"starting_kit": kit or KIT}],
    }


def _fight(mids, *, theirs=(), seed="AUTO84", cl=18, dc=12, objects=(), kit=None):
    """ME owns ``mids``; a hostile Unmaking fighter with ``theirs`` stands two squares away. ME's turn is open."""
    bundles = [compile_character(_sheet(mids, cl=cl, dc=dc, kit=kit), actor_id=ME, reaction_plan={"ask": True})]
    bundles.append(compile_character(_sheet(list(theirs) or ["TAL_UNMAKING_RUIN_CHANNEL"], cl=cl, dc=dc), actor_id=FOE))
    engine = Gate4ControllerEngine(
        ROOT, match_seed=seed, typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [ME, FOE],
                      "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    for index, spec in enumerate(objects, start=1):
        object_id = f"object:map.{index}"
        engine.state.objects[object_id] = RuntimeObjectState(
            object_id=object_id, object_kind=spec.get("kind", "crate"),
            position=Position(x=spec.get("x", 4), y=spec.get("y", 6)), unattended=True, flammable=False, ac=10,
            current_hp=spec.get("hp", 300), maximum_hp=spec.get("hp", 300))
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[FOE].armor_class = 10
    ready(engine)
    draw = next((candidate for candidate in engine.legal_candidates() if candidate.display_name.startswith("Draw ")), None)
    if draw is not None:                     # the starting weapon is sheathed; its melee attack needs it in hand
        engine.execute_intent(ActionIntent(intent_id="draw", decision_id=draw.decision_id, candidate_id=draw.candidate_id,
                                           state_version=draw.state_version, actor_id=ME, target_ids=draw.target_ids))
        ready(engine)
    return engine


def _named(engine, name, owner=ME):
    return next(key for key, action in sorted(engine.action_catalog.items())
                if action.display_name == name and action.owner_id == owner)


def _foe_technique(engine, name, *, concentrating=False):
    """The documented seam a typed, non-weapon action opens before its own effects run
    (combat/typed_executor.py:4003-4006): offer technique_targets / technique_used reactions."""
    from combat import typed_reactions

    actor, foe = engine.state.actors[FOE], engine.state.actors[ME]
    action = engine.action_catalog[_named(engine, name, FOE)]
    typed = copy_typed(action)
    typed["numbers"]["_cost"] = sum(int(amount) for _resource, amount in action.costs)
    typed["numbers"]["_cp_cost"] = sum(int(amount) for resource, amount in action.costs
                                       if resource in {"resource:core.qi", "resource:core.stamina", "resource:core.resonance"})
    engine._typed_pending_technique = {"actor": FOE, "save_dc": int(typed["numbers"].get("save_dc") or 10),
                                       "action_name": action.display_name, "technique": typed.get("source")}
    if concentrating:                                   # damage can end Concentration; the refund has to say so
        engine._start_concentration(actor, action.source_definition_id)   # separately, not as part of the hit itself
    # The engine names the action resolving right now for the whole transaction (combat/gate2_engine.py:1424); a
    # reaction that has to tell "the effect this technique is creating" from the creator's other works reads it there.
    engine._active_action_source_id = action.source_definition_id
    engine.state.current_actor_id = FOE
    engine.state.actors[ME].reaction_available = True
    before = len(engine.events)
    typed_reactions.on_technique_start(engine, actor, [foe], typed, ActionIntent(
        intent_id="probe", decision_id="probe", candidate_id="probe",
        state_version=engine.state.state_version, actor_id=FOE))
    engine._typed_pending_technique = None
    engine._active_action_source_id = None
    return engine.events[before:]


def copy_typed(action):
    typed = json.loads(json.dumps((action.parameters or {}).get("typed") or {}))
    typed["numbers"] = dict(typed.get("numbers") or {})
    return typed


def answers(mapping):
    """A reaction provider for the documented choice transport (Gate4ControllerEngine.set_reaction_provider): every
    ``choice:needle.*`` question whose checkpoint starts with a key in ``mapping`` is answered with its options; anything
    else is declined. Used where the printed rule is the player's own decision, so a headless engine call can play it both
    ways. Checkpoints carry the event sequence (combat/ext/needle.checkpoint_id), so they are matched by prefix."""
    from combat.gate4_models import ReactionDecision

    def provider(request):
        answer = next((options for prefix, options in mapping.items()
                       if str(request["checkpoint"]).startswith(prefix) or not prefix), None)
        spec = request.get("extension_choice") or {}
        if answer is None and not spec.get("allow_decline", True):
            answer = list(spec.get("preferred_option_ids") or spec.get("option_ids") or [])[:1]
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"],
                                selection="USE" if answer else "DECLINE",
                                option_ids=tuple(answer or ())), None

    return provider


def said(engine, start=0):
    """Everything the fight said to its players: the printed rider lines and the plain log lines."""
    return " ".join(str(event.payload.get("rider") or event.payload.get("log") or "")
                    for event in engine.events[start:])


def end_turn(engine, note="auto84:turn"):
    """The engine's own turn boundary, through its own END_TURN candidate, so a turn-end choice has an intent to ride."""
    candidate = next(row for row in engine.legal_candidates() if row.kind.value == "END_TURN")
    engine.execute_intent(ActionIntent(intent_id=note, decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=engine.state.current_actor_id, target_ids=candidate.target_ids))


# ------------------------------------------------------------------------------------------------ Unmake the Answer
ANSWER = ["TAL_UNMAKING_UNMAKE_THE_ANSWER", *WITH_STRAIN]


def test_unmake_the_answer_rolls_the_printed_unmaking_check_and_a_failure_is_the_printed_price():
    """ Make an Unmaking Check against the triggering effect's save DC. ... Failure: You take Ruin self-damage equal
    to 3d10 and gain 1 Black Vein Strain."""
    engine = _fight(ANSWER, theirs=("TAL_UNMAKING_HOLLOWING_FIELD",), seed="ANSWER", cl=10, dc=30)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    give(engine, ME, stamina=30)
    script(engine, [1])                        # a natural 1 never beats a save DC
    events_ = _foe_technique(engine, "Hollowing Field")
    checks = [event for event in events_ if event.event_type == "CHECK_ROLLED"]
    assert checks, sorted({event.event_type for event in events_})
    assert checks[-1].payload.get("skill") == "Unmaking Check"
    assert checks[-1].payload["success"] is False and checks[-1].payload["dc"] == 30
    assert me.current_hp < me.maximum_hp, "the printed 3d10 Ruin self-damage"
    assert me.resources[STRAIN] == 1, "the printed 1 Black Vein Strain"
    assert not any(c.condition_id == unmaking_forms.CRACKED_PROTECTION for c in foe.conditions.values())


def test_a_successful_unmaking_check_costs_no_self_damage_and_cracks_the_effect():
    """ Success: The effect still appears, but it begins cracked."""
    engine = _fight(ANSWER, theirs=("TAL_UNMAKING_HOLLOWING_FIELD",), seed="ANSWER2", cl=10, dc=12)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    give(engine, ME, stamina=30)
    script(engine, [20])
    events_ = _foe_technique(engine, "Hollowing Field")
    checks = [event for event in events_ if event.event_type == "CHECK_ROLLED"]
    assert checks and checks[-1].payload["success"] is True, checks[-1].payload if checks else events_
    assert me.current_hp == me.maximum_hp, "a successful check costs no Ruin self-damage"
    assert me.resources[STRAIN] == 0
    assert any(c.condition_id == unmaking_forms.CRACKED_PROTECTION for c in foe.conditions.values()), \
        "the effect still appears but begins cracked, until the end of its creator's next turn"


def test_unmake_the_answer_costs_two_points_and_a_reaction():
    """**Cost:** 2 CP. The printed cost is charged before the check, so a successful check is not free."""
    engine = _fight(ANSWER, theirs=("TAL_UNMAKING_HOLLOWING_FIELD",), seed="ANSWER3", cl=10, dc=12)
    me = engine.state.actors[ME]
    give(engine, ME, stamina=30)
    script(engine, [20])
    before = me.resources["resource:core.stamina"]
    _foe_technique(engine, "Hollowing Field")
    assert me.resources["resource:core.stamina"] == before - 2
    assert me.reaction_available is False


def _standing_barrier(engine, at=(4, 6), made_by=None):
    """A barrier its creator has standing up. ``made_by`` names the creator's technique, stamped exactly as that
    technique's own object is stamped (combat/ext/objects.record_creator): the record names the ability that put the
    barrier up, not the one cast that did it, which is why a barrier from an earlier round of the same technique cannot
    be told apart from this round's by the record. Without a maker it is simply some other work -- the arena's
    furniture, or an object put up before the record existed."""
    from combat.ext import objects

    component = {"name": "Stone barrier", "kind": "barrier", "structure": True}
    if made_by:
        component = objects.record_creator(component, engine.action_catalog[_named(engine, made_by, FOE)].source_definition_id)
    obj = RuntimeObjectState(object_id="object:test.barrier", object_kind="barrier", position=Position(x=at[0], y=at[1]),
                             unattended=True, flammable=False, ac=12, current_hp=80, maximum_hp=80, owner_id=FOE,
                             component=component)
    engine.state.objects[obj.object_id] = obj
    return obj


def test_unmake_the_answer_never_offers_an_older_object_the_creator_happens_to_own():
    """"Also deal 5d10 Ruin damage to the effect or its creator" -- the effect is the one this technique is creating, not
    every work its creator has standing up. A barrier from an earlier round is a different effect: it is not offered, and
    it is not called the Hollowing Field the creator is making."""
    engine = _fight(ANSWER, theirs=("TAL_UNMAKING_HOLLOWING_FIELD",), seed="ANSWER4", cl=10, dc=12)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    barrier = _standing_barrier(engine)                 # standing before this technique, and no maker recorded
    give(engine, ME, stamina=30)
    asked = []
    provider = answers({})

    def watching(request):
        asked.append(request)
        return provider(request)

    engine.set_reaction_provider(watching)
    script(engine, [20] + [4] * 5)                      # the check succeeds by 8, then 5d10 = 20
    _foe_technique(engine, "Hollowing Field")
    offers = [row for row in asked if str(row["checkpoint"]).startswith("NEEDLE:ANSWER_DAMAGE")]
    assert not offers, f"an unrelated standing object is not a choice: {offers}"
    assert barrier.object_id not in str(engine.events), "and it is never named as the effect being made"
    assert engine.state.objects[barrier.object_id].current_hp == barrier.maximum_hp, \
        "the printed 5d10 lands on the one legal target, its creator"
    assert foe.current_hp == foe.maximum_hp - 20


def test_an_earlier_cast_of_the_same_technique_is_never_the_effect_being_created():
    """"Success by 5 or more: Also deal 5d10 Ruin damage to the effect or its creator, chosen by you if both are legal
    targets." The effect is the one this cast is creating. A barrier its creator put up with the *same* technique on an
    earlier turn records the same maker, because an object's record names the ability and not the one cast that did it
    (combat/ext/objects.record_creator), so the earlier cast is a different effect: it is never offered, never damaged,
    and never called the Hollowing Field being made now. This is the AUTO84r2 review's finding: the game used to offer
    it, so the owner could choose an earlier cast's barrier as if it were this cast's work."""
    engine = _fight(ANSWER, theirs=("TAL_UNMAKING_HOLLOWING_FIELD",), seed="ANSWER4", cl=10, dc=12)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    barrier = _standing_barrier(engine, made_by="Hollowing Field")   # stamped exactly as the technique's own earlier cast
    give(engine, ME, stamina=30)
    asked = []
    provider = answers({})

    def watching(request):
        asked.append(request)
        return provider(request)

    engine.set_reaction_provider(watching)
    script(engine, [20] + [4] * 5)                      # the check succeeds by 8, then 5d10 = 20
    _foe_technique(engine, "Hollowing Field")
    offers = [row for row in asked if str(row["checkpoint"]).startswith("NEEDLE:ANSWER_DAMAGE")]
    assert not offers, f"an earlier cast of the same technique is not a choice: {offers}"
    assert barrier.object_id not in str(engine.events), "and it is never named as the effect being made"
    assert engine.state.objects[barrier.object_id].current_hp == barrier.maximum_hp, \
        "the earlier cast's effect takes none of the printed 5d10"
    assert foe.current_hp == foe.maximum_hp - 20, "the one target the game can name, the creature making it, takes it"
    assert any(c.condition_id == unmaking_forms.CRACKED_PROTECTION for c in foe.conditions.values())


def test_unmake_the_answer_resolves_through_a_real_technique_action():
    """The same printed 5d10, resolved the way the table actually resolves it: the Unmaking fighter really takes Hollowing
    Field as a legal action on their own turn (tests/h1_support.use), the reaction fires inside that action's own
    resolution -- the engine sets up the pending technique itself, combat/typed_executor.py:4003-4006 -- and the damage
    lands on the creature making the effect while the earlier cast's barrier is left alone. Companion to the seam-level
    tests above, which call the reaction hook directly and so cannot show that the real action reaches it."""
    engine = _fight(ANSWER, theirs=("TAL_UNMAKING_HOLLOWING_FIELD",), seed="ANSWER5", cl=10, dc=12)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    barrier = _standing_barrier(engine, made_by="Hollowing Field")
    give(engine, ME, stamina=30)
    give(engine, FOE, stamina=30)
    asked = []

    def watching(request):
        asked.append(request)
        return []

    engine.set_reaction_provider(watching)
    script(engine, [20] + [4] * 5)                      # the check succeeds by 8, then 5d10 = 20
    engine.state.current_actor_id = FOE
    foe.action_available, foe.bonus_action_available, foe.reaction_available = True, True, True
    me.reaction_available = True
    field = next(candidate for candidate in engine.legal_candidates()       # the ability compiles one button per cell,
                 if candidate.actor_id == FOE and candidate.display_name.startswith("Hollowing Field at 3,6"))  # this one over us
    use(engine, field.display_name, actor_id=FOE)   # a real action, not a direct call into the reaction hook
    resolved = [row for row in asked if str(row["checkpoint"]).startswith("NEEDLE:ANSWER_DAMAGE")]
    assert not resolved, "the printed choice is never asked on an object the game cannot identify as this cast's effect"
    assert any(event.event_type == "REACTION_RESOLVED" and "UNMAKE_THE_ANSWER" in str(event.source_definition_id)
               for event in events(engine, "REACTION_RESOLVED")), "the reaction did fire inside the real action"
    assert foe.current_hp == foe.maximum_hp - 20, "5d10 Ruin damage, unmodified, on the creature making the effect"
    assert engine.state.objects[barrier.object_id].current_hp == barrier.maximum_hp, \
        "and not on the earlier cast's barrier, which the same technique also made"
    assert "only one of the two takes the 5d10" in said(engine).lower(), \
        "the log tells a Game Master reading the choice as the effect to move the damage, not add a second one"


def test_unmake_the_answer_names_the_creature_when_the_effect_does_not_exist_yet():
    """Nothing to name: the triggering technique has not created anything yet, and an earlier cast's barrier cannot be told
    apart from this cast's work, so the creature making the effect is the one target the game can name -- and the log says
    so, instead of presenting creator damage as the whole printed outcome."""
    engine = _fight(ANSWER, theirs=("TAL_UNMAKING_HOLLOWING_FIELD",), seed="ANSWER6", cl=10, dc=12)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    give(engine, ME, stamina=30)
    script(engine, [20] + [4] * 5)                  # the check succeeds by 8, then 5d10 = 20
    _foe_technique(engine, "Hollowing Field")
    damage = next(event.payload["hp_damage"] for event in events(engine, "DAMAGE_COMMITTED")
                  if FOE in tuple(event.target_ids))
    assert damage == 20 and foe.current_hp == foe.maximum_hp - damage, "the printed 5d10 Ruin damage lands on the creator"
    assert "not on the table yet" in said(engine)
    assert any(c.condition_id == unmaking_forms.CRACKED_PROTECTION for c in foe.conditions.values())


def test_the_refund_instruction_is_the_hit_points_lost_not_the_dice_roll_when_resistance_halves_it():
    """The AUTO84r3 review's finding 1: the log used to tell the Game Master to "give back those 20 hit points" after a
    roll of 20, which heals a creature that only lost 10 to its Resistance. The refund is read off the committed hit, so
    it names the two values to set and never more than the damage actually dealt."""
    engine = _fight(ANSWER, theirs=("TAL_UNMAKING_HOLLOWING_FIELD",), seed="ANSWER7", cl=10, dc=12)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.current_hp, foe.maximum_hp = 70, 100            # the review's own example: 70 of 100
    engine._add_modifier(foe, "test:stone_skin", "damage_resistance", "ADD", "FORCE", "SELF",
                         expires_on="UNTIL_REMOVED")
    give(engine, ME, stamina=30)
    script(engine, [20] + [4] * 5)                      # the check succeeds by 8, then 5d10 = 20
    _foe_technique(engine, "Hollowing Field")
    committed = next(event.payload for event in events(engine, "DAMAGE_COMMITTED") if FOE in tuple(event.target_ids))
    assert committed["rolled_or_pending_damage"] == 20 and committed["hp_damage"] == 10, \
        "20 were rolled and Resistance halved them"
    assert foe.current_hp == 60, "so the creature is 10 lower, not 20"
    refund = said(engine)
    assert f"set {foe.display_name} back to 70 hit points" in refund, \
        f"the instruction restores the 70 it started the hit on: {refund}"
    assert "lost 10 hit points, not the 20 that were rolled" in refund, \
        f"and says the 10 it lost, so nobody hands back the roll: {refund}"


def test_the_refund_instruction_gives_back_temporary_hit_points_that_soaked_the_damage():
    """Temporary hit points are spent before hit points are, so after this hit the creature has fewer of both and no hit
    points missing at all. The instruction has to name both, and has to say so even when no hit points were touched."""
    engine = _fight(ANSWER, theirs=("TAL_UNMAKING_HOLLOWING_FIELD",), seed="ANSWER8", cl=10, dc=12)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.temporary_hp = 15
    give(engine, ME, stamina=30)
    script(engine, [20] + [4] * 5)                      # the check succeeds by 8, then 5d10 = 20
    _foe_technique(engine, "Hollowing Field")
    committed = next(event.payload for event in events(engine, "DAMAGE_COMMITTED") if FOE in tuple(event.target_ids))
    assert (committed["temporary_hp_absorbed"], committed["hp_damage"]) == (15, 5), \
        "15 of the 20 went into temporary hit points and 5 into hit points"
    refund = said(engine)
    assert f"back to {foe.maximum_hp} hit points and 15 temporary hit points" in refund, \
        f"the instruction gives the spent temporary hit points back, not a repeat of the roll: {refund}"
    assert "lost 5 hit points and 15 temporary hit points, not the 20 that were rolled" in refund, \
        f"and it says both numbers it actually lost: {refund}"


def test_the_refund_instruction_says_that_hit_points_alone_do_not_undo_a_broken_concentration():
    """Damage can end Concentration or knock a creature out (combat/gate2_engine.py). Handing the hit points back is only
    the arithmetic of the printed choice, so the log has to separate the two rather than imply the hit was undone."""
    engine = _fight(ANSWER, theirs=("TAL_UNMAKING_HOLLOWING_FIELD",), seed="ANSWER9", cl=10, dc=12)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    give(engine, ME, stamina=30)
    script(engine, [20, 1] + [4] * 5)                  # the check by 8, then the concentration save fails, then 5d10 = 20
    _foe_technique(engine, "Hollowing Field", concentrating=True)
    refund = said(engine)
    assert "putting its hit points back does not undo" in refund and "Concentration" in refund, \
        f"the log says what the refund does not undo: {refund}"
    assert "set " in refund and "hit points and" in refund, "and still gives the arithmetic of the printed choice"


def test_an_undefended_knockout_is_explained_without_blaming_resistance_and_says_it_was_knocked_out():
    """The AUTO84r4 review's finding 1, the half no test covered: an undefended lethal hit. A creature at 10 Hit Points
    loses only 10 of a roll of 20 because its hit points bottom out at zero (combat/gate2_engine.py floors current Hit
    Points at 0) -- no Resistance and no Immunity were involved, so the log must not say they were. And a knockout is not
    undone by handing the hit points back, so the log has to say that too."""
    engine = _fight(ANSWER, theirs=("TAL_UNMAKING_HOLLOWING_FIELD",), seed="ANSWER10", cl=10, dc=12)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.current_hp, foe.maximum_hp = 10, 100           # nothing defends it, and 10 will not survive 20
    give(engine, ME, stamina=30)
    script(engine, [20] + [4] * 5)                      # the check succeeds by 8, then 5d10 = 20
    _foe_technique(engine, "Hollowing Field")
    committed = next(event.payload for event in events(engine, "DAMAGE_COMMITTED") if FOE in tuple(event.target_ids))
    assert (committed["rolled_or_pending_damage"], committed["reduced_to"], committed["hp_damage"]) == (20, 20, 20), \
        "nothing reduced the roll: the packet was worth the whole 20 and the creature simply ran out"
    assert foe.current_hp == 0 and not foe.active, "so it is a knockout"
    refund = said(engine)
    assert "Resistance or Immunity" not in refund, \
        f"nothing reduced this hit, so blaming its defences would be false: {refund}"
    assert f"{foe.display_name} lost 10 hit points, not the 20 that were rolled" in refund, \
        f"and it says the 10 it actually lost: {refund}"
    assert "hit points ran out at 0" in refund, \
        f"the reason given is the one that actually applied: {refund}"
    assert f"set {foe.display_name} back to 10 hit points" in refund, \
        f"the printed arithmetic is still spelled out: {refund}"
    assert "putting its hit points back does not undo" in refund and "knocked out" in refund, \
        f"and it warns that giving the hit points back does not undo the knockout: {refund}"


def test_a_fully_immune_creature_is_told_the_damage_was_reduced_not_that_its_own_defences_stopped_it():
    """The other half of the same wording: nothing lost at all. Only one of the creature's defences, an HP floor or a
    deferred packet can stop a packet outright, and the engine does not record which, so the words offer the
    possibilities rather than assert one cause."""
    engine = _fight(ANSWER, theirs=("TAL_UNMAKING_HOLLOWING_FIELD",), seed="ANSWER11", cl=10, dc=12)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    engine._add_modifier(foe, "test:undead", "damage_immunity", "ADD", "FORCE", "SELF", expires_on="UNTIL_REMOVED")
    give(engine, ME, stamina=30)
    script(engine, [20] + [4] * 5)                      # the check succeeds by 8, then 5d10 = 20
    _foe_technique(engine, "Hollowing Field")
    committed = next(event.payload for event in events(engine, "DAMAGE_COMMITTED") if FOE in tuple(event.target_ids))
    assert committed["reduced_to"] == 0 and foe.current_hp == foe.maximum_hp, "the whole packet was stopped"
    refund = said(engine)
    assert f"{foe.display_name} lost no hit points and no temporary hit points at all" in refund, \
        f"the log says nothing was lost: {refund}"
    assert "stopped all 20 of that damage" not in refund and "own defences stopped" not in refund, \
        f"and does not assert which of several possible causes did it: {refund}"
    assert "there is nothing to give back" in refund, \
        f"so it does not order a refund for a hit that never landed: {refund}"


# ------------------------------------------------------------------------------------------------ The Moment Nothing Answers
def test_the_moment_nothing_answers_takes_twenty_off_current_and_maximum_hit_points():
    """ reduce your current and maximum HP by 20 until you finish a Long Rest"."""
    engine = _fight(["tianxia.talent.unmaking.the_moment_nothing_answers", *WITH_STRAIN], seed="MOMENT", cl=17, dc=12)
    me = engine.state.actors[ME]
    give(engine, ME, stamina=60)
    script(engine, [1] * 12)                       # the target's Constitution save fails first
    maximum, current = me.maximum_hp, me.current_hp
    use(engine, "The Moment Nothing Answers", target=FOE)
    assert me.maximum_hp == maximum - 20, "the printed maximum Hit Point loss"
    assert me.current_hp <= current - 20, "the printed current Hit Point loss, on top of the two Ruin Backlashes"
    assert any(c.condition_id.startswith(maximum_hp_riders.LOST) for c in me.conditions.values())


def test_the_maximum_hit_point_loss_survives_a_table_commit_and_reload():
    """Checklist 7: the reduction is stored as an integer on a keyed condition, so a saved fight keeps it."""
    engine = _fight(["tianxia.talent.unmaking.the_moment_nothing_answers", *WITH_STRAIN], seed="MOMENT2", cl=17, dc=12)
    me = engine.state.actors[ME]
    give(engine, ME, stamina=60)
    script(engine, [1] * 12)
    maximum = me.maximum_hp
    use(engine, "The Moment Nothing Answers", target=FOE)
    assert me.maximum_hp == maximum - 20
    reloaded = type(me).model_validate(json.loads(json.dumps(me.model_dump(mode="json"), sort_keys=True)))
    assert reloaded.maximum_hp == maximum - 20
    assert reloaded.maximum_hp_adjustments, "the adjustment travels with the saved actor"
    assert all(isinstance(row.amount, int) and isinstance(row.source_id, str) for row in reloaded.maximum_hp_adjustments.values())


# ------------------------------------------------------------------------------------------------ Splintering Trace
def test_splintering_trace_adds_one_extra_d10_to_a_black_trace_hit_on_an_object():
    """ When Black Trace hits an object ... add one extra d10 Ruin damage. At CL 11, add two extra d10 instead."""
    engine = _fight(["TAL_UNMAKING_BLACK_TRACE", "TAL_UNMAKING_SPLINTERING_TRACE"], seed="SPLINT", cl=10,
                    objects=({"hp": 300},))
    give(engine, ME, stamina=10)
    script(engine, [7])
    object_ext.deal(engine, engine.state.actors[ME], engine.state.objects["object:map.1"], [(10, "FORCE")],
                   _named(engine, "Black Trace: Fray"))
    assert engine.state.objects["object:map.1"].current_hp == 300 - 17, "one extra d10 (7) joins the same damage instance"


def test_splintering_trace_rolls_two_extra_d10_from_cl_11():
    engine = _fight(["TAL_UNMAKING_BLACK_TRACE", "TAL_UNMAKING_SPLINTERING_TRACE"], seed="SPLINT11", cl=12,
                    objects=({"hp": 300},))
    give(engine, ME, stamina=10)
    script(engine, [4, 4])
    object_ext.deal(engine, engine.state.actors[ME], engine.state.objects["object:map.1"], [(10, "FORCE")],
                   _named(engine, "Black Trace: Fray"))
    assert engine.state.objects["object:map.1"].current_hp == 300 - 18, "2d10 (4 + 4) at CL 11"


def test_splintering_trace_adds_nothing_to_an_object_from_another_ability():
    engine = _fight(["TAL_UNMAKING_BLACK_TRACE", "TAL_UNMAKING_SPLINTERING_TRACE"], seed="SPLINT3", cl=12,
                    objects=({"hp": 300},))
    give(engine, ME, stamina=10)
    script(engine, [4, 4])
    object_ext.deal(engine, engine.state.actors[ME], engine.state.objects["object:map.1"], [(10, "FORCE")],
                   "action:typed.some_other_ability")
    assert engine.state.objects["object:map.1"].current_hp == 290, "the printed line only widens a Black Trace hit"


def test_splintering_trace_keys_the_printed_construct_case_on_a_printed_creature_label():
    """The same printed line against a creature the table labels a construct (nothing is inferred from a name)."""
    from combat.ext import creature_kinds

    engine = _fight(["TAL_UNMAKING_BLACK_TRACE", "TAL_UNMAKING_SPLINTERING_TRACE"], seed="SPLINT4", cl=12)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert "splintering_trace" in unmaking.kinds(engine, me), "the fighter compiled this talent"
    foe.creature_types = ("construct",)
    assert creature_kinds.matches(foe, ("construct",)), "the printed label is what the printed line turns on"
    foe.creature_types = ()
    assert not creature_kinds.matches(foe, ("construct",)), "an unlabelled creature never matches"

    def black_trace_damage():
        hp = foe.current_hp
        use(engine, "Black Trace: Fray", target=FOE)
        return hp - foe.current_hp

    give(engine, ME, stamina=60)
    script(engine, [20, 6])                    # the attack hits, then the extra d10
    foe.creature_types = ("construct",)
    with_kind = black_trace_damage()
    ready(engine)
    foe.creature_types = ()
    script(engine, [20, 6])
    without_kind = black_trace_damage()
    assert with_kind > without_kind, "a creature labelled a construct takes the printed extra d10"



# ------------------------------------------------------------------------------------------------ Crack the Guard
GUARD_CHECKPOINT = "CRACK_THE_GUARD_IMPLEMENT"


def _charged_guard_fight(seed, confirm):
    """A real Ruin Channel weapon hit, so the printed trigger ("when you hit a creature ... with a Ruin Channel
    attack") fires at the table; ``confirm`` is the answer to the printed defensive-implement precondition, or None for
    nobody to ask. Returns the engine and every question the fight put to its players."""
    engine = _fight(["TAL_UNMAKING_RUIN_CHANNEL", "TAL_UNMAKING_CRACK_THE_GUARD"], theirs=("TAL_UNMAKING_RUIN_CHANNEL",),
                    seed=seed)
    me = engine.state.actors[ME]
    weapon = next(iter(unmaking_channels.channels(engine, me)))
    script(engine, [20] * 40)
    asked = []
    provider = answers({f"NEEDLE:{GUARD_CHECKPOINT}": ["defended"]} if confirm else {})

    def watching(request):
        asked.append(request)
        return provider(request)

    engine.set_reaction_provider(watching)
    assert _charged_weapon_hit(engine, weapon), "the Ruin Channel landed on a held weapon"
    return engine, asked


def test_crack_the_guard_asks_the_attacker_for_the_printed_defensive_implement():
    """ "When you hit a creature using a shield, armor, parrying weapon, warding bracer, or comparable defensive
    implement" -- the table carries one Armor Class number per creature and no shield record, so the attacker confirms it."""
    engine = _fight(["TAL_UNMAKING_RUIN_CHANNEL", "TAL_UNMAKING_CRACK_THE_GUARD"], theirs=("TAL_UNMAKING_RUIN_CHANNEL",),
                    seed="GUARD")
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert "crack_the_guard" in unmaking.kinds(engine, me), "the fighter compiled this talent"
    assert save_choices.has_target_choice([{"type": "save", "ability": "STR_OR_CON", "target_choice": True}]), \
        "and it is the target's own choice, through combat/ext/save_choices.py"
    assert unmaking_channels.channels(engine, me), "the starting kit does give this fighter a weapon to answer with"
    before = len(engine.events)
    unmaking_forms._crack_the_guard(unmaking_forms.context_of(engine, me, _named(engine, "Ruin Channel"), foe), foe)
    assert not events(engine, "SAVE_ROLLED", before), \
        "a creature with no defensive implement has nothing to save, and nothing is asked of the target"


def test_crack_the_guard_makes_the_defended_target_roll_its_own_strength_or_constitution_save():
    """ When you hit a creature using a shield, armor, parrying weapon, warding bracer, or comparable defensive implement
    with a Ruin Channel attack, the target must succeed on a Strength or Constitution saving throw, target's choice."""
    engine, asked = _charged_guard_fight("GUARD2", True)
    save = [request for request in asked if str(request["reaction_source_id"]).endswith("save_choice")]
    assert save, f"the target's own Strength-or-Constitution choice was asked ({[r['reaction_source_id'] for r in asked]})"
    assert save[-1]["reactor_id"] == FOE, "the target chooses, not the attacker"
    assert set(save[-1]["extension_choice"]["option_ids"]) == {"STR", "CON"}
    rolls = events(engine, "SAVE_ROLLED")
    assert rolls and rolls[-1].payload["actor_id"] == FOE, "the printed save was made by the target"
    lines = said(engine)
    assert "Crack the Guard" in lines, lines
    assert "until the start of your next turn" in lines, \
        "the attacker's next turn, as the printed text says"


def test_crack_the_guard_leaves_a_creature_with_no_defensive_implement_alone():
    """ The printed save needs a defensive implement; nobody confirms one, so nothing is asked of the target."""
    engine, asked = _charged_guard_fight("GUARD6", None)
    assert "crack_the_guard" in unmaking.kinds(engine, engine.state.actors[ME])
    assert not events(engine, "SAVE_ROLLED"), "no defensive implement, no save"
    assert not [request for request in asked if str(request["reaction_source_id"]).endswith("save_choice")], \
        "and the target is never asked to choose"
    assert "not using a defensive implement" in said(engine)


def test_crack_the_guard_only_answers_a_channel_attack_through_a_weapon():
    """An unarmed strike is not "a Ruin Channel attack with a shield, armor or parrying weapon": the table asks nothing."""
    engine = _fight(["TAL_UNMAKING_RUIN_CHANNEL", "TAL_UNMAKING_CRACK_THE_GUARD"], theirs=("TAL_UNMAKING_RUIN_CHANNEL",),
                    seed="GUARD3")
    me = engine.state.actors[ME]
    unarmed = unmaking_forms.context_of(engine, me, _named(engine, "Unarmed Strike"), engine.state.actors[FOE])
    assert unmaking_channels.channel_weapon_identity(unarmed) is None
    assert unmaking_channels.channels(engine, me), "the starting kit does give this fighter a weapon to answer with"


def test_crack_the_guard_enrolls_the_defenders_of_a_fight_that_has_a_cracker():
    """The save is built when the hit lands, so the service's AI-step probe cannot find it in a catalog row: the
    enrollment that gate5_service._ask_reactors reads is what puts a manual defender in front of the question."""
    engine = _fight(["TAL_UNMAKING_RUIN_CHANNEL", "TAL_UNMAKING_CRACK_THE_GUARD"], theirs=(), seed="GUARD4")
    assert set(unmaking_forms.guard_defenders(engine)) == set(engine.state.actors)
    plain = _fight(["TAL_UNMAKING_RUIN_CHANNEL"], theirs=(), seed="GUARD5")
    assert unmaking_forms.guard_defenders(plain) == (), "a fight with no Crack the Guard enrolls nobody"


# ------------------------------------------------------------------------------------------------ First Ruin Form
FORM = "First Ruin Form: External Vessel Mandate"
VESSEL = ["TAL_UNMAKING_FIRST_RUIN_FORM_EXTERNAL_VESSEL_MANDATE", *WITH_STRAIN]


def _charged_weapon_hit(engine, weapon_id):
    """Charge a Ruin Channel through a held weapon and land the hit, so the printed Crack happens at the table."""
    use(engine, "Ruin Channel")
    me = engine.state.actors[ME]
    assert any(c.condition_id == unmaking.CHANNEL for c in me.conditions.values())
    for attempt in range(8):
        candidate = next((c for c in engine.legal_candidates()
                          if c.display_name.endswith("attack") and ".weapon." in c.source_definition_id
                          and c.source_definition_id.split("#")[0].endswith(weapon_id.split("#")[0])), None)
        if candidate is None:
            break
        engine.execute_intent(ActionIntent(intent_id=f"hit{attempt}", decision_id=candidate.decision_id,
                                           candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                           actor_id=ME, target_ids=candidate.target_ids))
        if not any(c.condition_id == unmaking.CHANNEL for c in me.conditions.values()):
            return True
        ready(engine)
    return False


def _run_to_the_form_s_end(engine, limit=48):
    """End real turns (the engine's own END_TURN candidate) until the form's printed minute runs out at the end of its
    owner's turn -- the moment the printed Black Trace belongs to."""
    for _ in range(limit):
        if unmaking_channels.vessel_form(engine.state.actors[ME]) is None:
            return True
        end_turn(engine, "auto84:form-ends")
    return False


def _asked(checkpoints):
    return [checkpoint for checkpoint in checkpoints if checkpoint.startswith("NEEDLE:VESSEL_BLACK_TRACE")]


def _vessel_fight(seed, mids=VESSEL, *, strike=True):
    """Take the form on one turn and charge the Channel on the next: one Bonus Action a turn, as printed."""
    engine = _fight(list(mids), seed=seed, dc=12)
    me = engine.state.actors[ME]
    give(engine, ME, stamina=60)
    weapon = next(iter(unmaking_channels.channels(engine, me)))
    use(engine, FORM)
    assert unmaking_channels.vessel_form(me) is not None, "the form is up for its printed 1 minute"
    assert unmaking_channels.chosen_channel(me) == weapon, \
        "the form asked which held weapon or implement it binds its qi to, and recorded that one Channel"
    for turn in range(4):                            # the foe's turn, then ours again
        engine.end_turn("auto84:vessel")
        if engine.state.current_actor_id == ME:
            break
    assert engine.state.current_actor_id == ME
    engine.state.actors[FOE].position = Position(x=4, y=6)     # the foe's own turn may have walked it off our reach
    ready(engine)
    return engine, me, weapon


def _as_artifact(engine, weapon_id):
    """Mark a held weapon's compiled row as an artifact implement, the way one reaches the table: its typed row carries
    ``artifact``. combat/ext/unmaking_channels.crack reads that same flag to keep an artifact from ever breaking."""
    action = engine.action_catalog[weapon_id]
    typed = {**((action.parameters or {}).get("typed") or {}), "artifact": True}
    engine.action_catalog[weapon_id] = action.model_copy(update={"parameters": {**(action.parameters or {}), "typed": typed}})
    return engine.action_catalog[weapon_id]


def test_first_ruin_form_offers_an_artifact_weapon_as_its_channel():
    """"Choose one held weapon or implement" -- an artifact is an implement, so it is a legal Channel. The list used to be
    the weapons that can take Crack, which excludes artifacts, so a fighter holding only an artifact was told it held
    nothing suitable."""
    engine = _fight(VESSEL, seed="VESSELARTIFACT", dc=12)
    me = engine.state.actors[ME]
    weapon = next(iter(unmaking_channels.held_forms(engine, me)))
    _as_artifact(engine, weapon)
    assert unmaking_channels.channels(engine, me) == {}, "an artifact can never take Crack, so it is not a Channel for it"
    assert weapon in unmaking_channels.held_forms(engine, me), "but it is still a weapon the form may bind its qi to"
    give(engine, ME, stamina=60)
    use(engine, FORM)
    assert unmaking_channels.vessel_form(me) is not None, "the form is up for its printed 1 minute"
    assert unmaking_channels.chosen_channel(me) == weapon, \
        "an artifact-only fighter is offered its artifact, not told it holds no suitable weapon"


def test_first_ruin_form_offers_an_artifact_alongside_an_ordinary_weapon():
    """Mixed equipment: every held implement is a legal Channel; only the ordinary one can take Crack."""
    engine = _fight(VESSEL, seed="VESSELMIXED", dc=12, kit={"items": [*KIT["items"],
                                                                       {"item_id": "tianxia.mortal.weapon.dao", "name": "Dao (Saber)", "quantity": 1}]})
    me = engine.state.actors[ME]
    held = unmaking_channels.held_forms(engine, me)
    assert len(held) == 2, sorted(held)
    artifact = _as_artifact(engine, next(key for key in held if key.endswith("bi_shou")))
    ordinary = next(key for key in held if key != artifact.source_definition_id)
    assert set(unmaking_channels.channels(engine, me)) == {ordinary}, \
        "only the ordinary weapon can pay a Crack price; the artifact stays out of that list alone"
    give(engine, ME, stamina=60)
    engine.set_reaction_provider(answers({"NEEDLE:FORM_CHANNEL": [artifact.source_definition_id]}))
    use(engine, FORM)
    assert unmaking_channels.chosen_channel(me) == artifact.source_definition_id, \
        "the owner may choose the artifact implement over the ordinary weapon"
    assert unmaking_channels.cracks(me, artifact.source_definition_id) == 0


def test_first_ruin_form_delays_the_channel_crack_on_a_five_or_six():
    """ when the chosen Channel would gain Crack, roll a d6. On a 5 or 6, the Crack is delayed until the form ends;
    when the form ends, all delayed Crack applies at once"""
    engine, me, weapon = _vessel_fight("VESSEL")
    script(engine, [6] * 40)                        # every d20 and every d6 is a 6: the hit lands and the delay d6 delays
    assert _charged_weapon_hit(engine, weapon), "the Ruin Channel landed on the weapon"
    assert unmaking_channels.cracks(me, weapon) == 0, "a 6 on the delay d6 holds the Crack back"
    held = next(c for c in me.conditions.values() if c.condition_id == unmaking_channels.DELAYED_CRACK)
    assert int(held.data["count"]) == 1 and held.data["weapon"] == weapon, \
        "an integer and a string on their own condition, so a saved fight keeps them"
    assert _run_to_the_form_s_end(engine)
    assert unmaking_channels.cracks(me, weapon) == 1, "when the form ends, all delayed Crack applies at once"


def test_first_ruin_form_applies_the_crack_normally_on_a_one_to_four():
    engine, me, weapon = _vessel_fight("VESSEL2")
    script(engine, [20] + [4] * 40)                 # the attack hits on a 20, then every d6 is a 4: no delay
    assert _charged_weapon_hit(engine, weapon)
    assert unmaking_channels.cracks(me, weapon) == 1, "1-4 on the delay d6 lets the Crack land at once"


def test_only_the_chosen_channels_crack_is_delayed():
    """"when the chosen Channel would gain Crack" -- another held weapon's Crack lands at once, and the held-back Crack
    never moves from one weapon to another."""
    engine, me, weapon = _vessel_fight("VESSEL6")
    other = "action:typed.another.held.weapon"
    ctx = unmaking_forms.context_of(engine, me, _named(engine, "Ruin Channel"), me)
    script(engine, [6] * 12)
    assert unmaking_channels.delay_or_crack(ctx, other, 1) is False, \
        "the printed d6 is the chosen Channel's, so another weapon's Crack is not delayed at all"
    assert unmaking_channels.delayed_crack(me) is None
    assert unmaking_channels.delay_or_crack(ctx, weapon, 1) is True
    assert unmaking_channels.delay_or_crack(ctx, other, 1) is False, \
        "and after the Channel is named, nothing can be held back against a different weapon"
    held = unmaking_channels.delayed_crack(me)
    assert held.data["weapon"] == weapon and int(held.data["count"]) == 1
    settled, broke = unmaking_channels.settle_delayed_crack(engine, me, "auto84:settle")
    assert (settled, broke) == (weapon, False)
    assert unmaking_channels.cracks(me, weapon) == 1 and unmaking_channels.cracks(me, other) == 0


def test_the_free_black_trace_is_offered_at_the_form_s_own_turn_end_and_is_the_printed_attack():
    """ If the Channel breaks when the form ends, you may immediately make one Black Trace attack against a creature
    within 30 feet as the weapon dies. This attack cannot Overdraw."""
    asked = []
    engine, me, weapon = _vessel_fight("VESSEL3", [*VESSEL, "TAL_UNMAKING_BLACK_TRACE"])
    script(engine, [6] * 40)
    assert _charged_weapon_hit(engine, weapon)
    unmaking_channels.crack(engine, me, weapon, 2, "test:already_cracked")   # the Channel was at 2 Crack
    provider = answers({"NEEDLE:VESSEL_BLACK_TRACE": [FOE]})

    def watching(request):
        asked.append(request["checkpoint"])
        return provider(request)

    engine.set_reaction_provider(watching)
    script(engine, [20] + [6] * 20)              # the free Black Trace hits, and its damage dice
    hp = engine.state.actors[FOE].current_hp
    assert _run_to_the_form_s_end(engine), "the form's printed minute ran out at the end of its owner's turn"
    assert _asked(asked), f"the free Black Trace is offered the moment the Channel breaks ({asked})"
    assert any(c.condition_id.startswith(unmaking_channels.BROKEN) for c in me.conditions.values()), "3 Crack breaks the weapon"
    strikes = [event for event in engine.events
               if event.event_type == "ATTACK_ROLLED" and "BLACK_TRACE" in str(event.source_definition_id)]
    assert strikes, "the printed Black Trace was made as the weapon died"
    assert engine.state.actors[FOE].current_hp < hp, "against the creature its owner chose"


def test_the_vessel_black_trace_cannot_overdraw():
    engine, me, weapon = _vessel_fight("VESSEL4", [*VESSEL, "TAL_UNMAKING_BLACK_TRACE"])
    script(engine, [6] * 40)
    assert _charged_weapon_hit(engine, weapon)
    unmaking_channels.crack(engine, me, weapon, 2, "test:already_cracked")
    engine.set_reaction_provider(answers({"NEEDLE:VESSEL_BLACK_TRACE": [FOE]}))
    engine._apply_condition(me, unmaking.OVERDRAW, "test:ready", me.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Overdraw: ready"})
    before = len(engine.events)
    assert _run_to_the_form_s_end(engine)
    made = engine.events[before:]
    assert [event for event in made if event.event_type == "ATTACK_ROLLED" and "BLACK_TRACE" in str(event.source_definition_id)]
    assert not any(str(event.source_definition_id).endswith(".overdraw") for event in made), \
        "the printed Black Trace as the weapon dies cannot Overdraw"
    assert me.resources[STRAIN] == 0, "and gains no Black Vein Strain for it"


def test_declining_the_free_black_trace_leaves_the_broken_channel_spent():
    engine, me, weapon = _vessel_fight("VESSEL5", [*VESSEL, "TAL_UNMAKING_BLACK_TRACE"])
    script(engine, [6] * 40)
    assert _charged_weapon_hit(engine, weapon)
    unmaking_channels.crack(engine, me, weapon, 2, "test:already_cracked")
    engine.set_reaction_provider(answers({}))
    hp = engine.state.actors[FOE].current_hp
    assert _run_to_the_form_s_end(engine)
    assert any(c.condition_id.startswith(unmaking_channels.BROKEN) for c in me.conditions.values())
    assert engine.state.actors[FOE].current_hp == hp, "declining the printed offer hits nothing"
    assert "declined" in said(engine), "and the log says so"


def test_a_channel_broken_long_ago_does_not_earn_the_free_black_trace():
    """"If the Channel breaks when the form ends" -- an unrelated weapon that broke earlier is not the Channel dying."""
    asked = []
    engine, me, weapon = _vessel_fight("VESSEL7", [*VESSEL, "TAL_UNMAKING_BLACK_TRACE"])
    unmaking_channels.destroy(engine, me, "action:typed.some.older.weapon", "test:broke_long_ago")
    script(engine, [6] * 40)
    assert _charged_weapon_hit(engine, weapon)
    assert unmaking_channels.cracks(me, weapon) == 0, "the delay d6 held this Crack back, so the Channel is intact"
    provider = answers({"NEEDLE:VESSEL_BLACK_TRACE": [FOE]})

    def watching(request):
        asked.append(request["checkpoint"])
        return provider(request)

    engine.set_reaction_provider(watching)
    hp = engine.state.actors[FOE].current_hp
    assert _run_to_the_form_s_end(engine)
    assert any(c.condition_id.startswith(unmaking_channels.BROKEN) for c in me.conditions.values()), \
        "the older weapon is still broken"
    assert not _asked(asked), "the intact Channel did not die as the form ended, so there is no free Black Trace"
    assert engine.state.actors[FOE].current_hp == hp


# ------------------------------------------------------------------------------------------------ Fifth Ruin Form
def _structures(engine, *, at=(4, 6)):
    """The printed structures, and the things that are not: a hostile summoned construct, a hostile summoned living
    creature, a barrier a creature raised, and an ordinary crate the map itself placed."""
    from combat.gate2_runtime_models import ActorState

    def creature(name, types):
        actor = ActorState(entity_id=f"actor:test.{name}", display_name=name.title(), team_id="team:b",
                           primary_combatant=False, creature_types=tuple(types), armor_class=10,
                           maximum_hp=50, current_hp=50,
                           position=Position(x=at[0], y=at[1]), speed_ft=30, movement_remaining_ft=30, initiative_bonus=0,
                           dexterity_score=10, proficiency_bonus=2, saving_throws={}, resources={}, resource_maximums={},
                           action_ids=[], reaction_ids=[], summon={"owner": FOE, "group": f"group:{name}"})
        engine.state.actors[actor.entity_id] = actor
        return actor

    construct = creature("construct", ("construct",))
    living = creature("living", ("humanoid",))
    barrier = engine.state.objects["object:test.barrier"] = RuntimeObjectState(
        object_id="object:test.barrier", object_kind="barrier", position=Position(x=at[0], y=at[1]), unattended=True,
        flammable=False, ac=12, current_hp=80, maximum_hp=80, owner_id=FOE,
        component={"name": "Stone barrier", "kind": "barrier", "structure": True})
    crate = engine.state.objects["object:test.crate"] = RuntimeObjectState(
        object_id="object:test.crate", object_kind="crate", position=Position(x=at[0], y=at[1]), unattended=True,
        flammable=False, ac=10, current_hp=300, maximum_hp=300, component={"name": "Crate", "kind": "crate"})
    return construct, living, barrier, crate


def _domain(seed, cl=15):
    engine = _fight(["TAL_UNMAKING_FIFTH_RUIN_FORM_DOMAIN_OF_COLLAPSE", *WITH_STRAIN], seed=seed, cl=cl)
    give(engine, ME, stamina=30)
    script(engine, [1] * 12)
    use(engine, "Fifth Ruin Form: Domain of Collapse")
    return engine, engine.state.actors[ME]


def test_fifth_ruin_form_damages_its_printed_structures_at_the_start_of_each_of_your_turns():
    """ "temporary qi structures, summoned constructs, barriers, wards, and non-Secret defensive effects in the area
    take Ruin damage equal to your Cultivation Level at the start of each of your turns" """
    engine, me = _domain("DOMAIN")
    assert unmaking.cultivation_level(engine, me) == 15
    construct, living, barrier, crate = _structures(engine)
    engine._system_start_turn()
    assert construct.current_hp == 50 - 15, "a summoned construct takes the printed Cultivation Level damage"
    assert engine.state.objects[barrier.object_id].current_hp == 80 - 15, \
        "a barrier a creature raised is one of the printed qi structures"
    assert living.current_hp == 50, "a summoned living creature is not a construct"
    assert engine.state.objects[crate.object_id].current_hp == 300, "and ordinary furniture is not a qi structure at all"


def test_fifth_ruin_form_damages_an_allied_construct_but_leaves_what_is_outside_the_area_alone():
    """"summoned constructs ... in the area take Ruin damage equal to your Cultivation Level". The printed bullet says no
    "hostile" in front of them, and the hostility words belong to the other bullets, so a construct the owner summoned
    itself falls like any other -- the domain is hostile ground, not a team filter."""
    engine, me = _domain("DOMAIN2")
    construct, living, barrier, crate = _structures(engine)
    construct.team_id = me.team_id                       # your own summoned construct, inside the area
    engine.state.objects[barrier.object_id] = barrier.model_copy(update={"position": Position(x=20, y=20)})
    engine._system_start_turn()
    assert construct.current_hp == 50 - unmaking.cultivation_level(engine, me), \
        "an allied construct inside the domain is one of the printed structures"
    assert engine.state.objects[barrier.object_id].current_hp == 80, "and only the printed 60-foot area"
    assert living.current_hp == 50, "a summoned living creature is still not a construct"
    assert engine.state.objects[crate.object_id].current_hp == 300, "and ordinary furniture is not a qi structure at all"


# ------------------------------------------------------------------------------------------------ the printed HP prices
def test_the_fifth_ruin_form_upkeep_pays_its_ten_hit_point_price_at_the_end_of_your_turn():
    """"reduce your current and maximum HP by 10 until you finish a Long Rest" -- the upkeep price an Unmaking fighter
    may choose. Before the review fix choosing it raised NameError instead of paying."""
    engine = _fight(["TAL_UNMAKING_FIFTH_RUIN_FORM_DOMAIN_OF_COLLAPSE", *WITH_STRAIN], seed="UPRIGHT", cl=15)
    me = engine.state.actors[ME]
    give(engine, ME, stamina=30)
    script(engine, [1] * 12)
    use(engine, "Fifth Ruin Form: Domain of Collapse")
    maximum, current = me.maximum_hp, me.current_hp
    engine.set_reaction_provider(answers({"NEEDLE:UNMAKING_COST": ["3:max_hp_loss"]}))
    for _ in range(4):                              # the upkeep runs at the end of each of its user's turns
        before = len(engine.events)
        end_turn(engine, "auto84:upkeep")
        if me.maximum_hp < maximum:
            break
    paid = [c for c in me.conditions.values() if c.condition_id.startswith("condition:typed.maximum_hp_lost")]
    assert paid, "the printed price must be paid, not raise"
    lost = int(paid[0].data["lost"])
    assert lost >= 10 and me.maximum_hp == maximum - lost, "the printed maximum Hit Point loss"
    assert me.current_hp == current - lost, "and the printed current Hit Point loss"
    assert engine.events[before:], "the price reached the log"


def test_two_maximum_hit_point_prices_accumulate_and_each_one_takes_current_hit_points():
    engine = _fight(["TAL_UNMAKING_RUIN_CHANNEL", *WITH_STRAIN], seed="HPLOSS")
    me = engine.state.actors[ME]
    from combat.ext.maximum_hp_riders import LOST, max_hp_loss

    maximum, current = me.maximum_hp, me.current_hp
    assert max_hp_loss(engine, me, 10, "test:first", name="First price", key="test") == -10
    after_first = me.current_hp
    assert (me.maximum_hp, after_first) == (maximum - 10, current - 10)
    assert max_hp_loss(engine, me, 10, "test:second", name="First price", key="test") == -10
    assert (me.maximum_hp, me.current_hp) == (maximum - 20, after_first - 10), \
        "the second payment is ten more, not another twenty"
    held = next(c for c in me.conditions.values() if c.condition_id.startswith(LOST))
    assert int(held.data["lost"]) == 20 and int(held.data["amount"]) == 10, "integers only, so a save keeps them"
    reloaded = type(me).model_validate(json.loads(json.dumps(me.model_dump(mode="json"), sort_keys=True)))
    assert reloaded.maximum_hp == maximum - 20 and reloaded.current_hp == current - 20


def test_a_maximum_hit_point_price_saved_before_the_running_total_keeps_its_earlier_payment():
    """Checklist 7, and the AUTO84r1 review: a fight saved before this condition carried a running total stored only as
    ``amount`` -- everything paid so far -- with that reduction already on the creature's maximum. Paying again has to
    stack onto it. Reading only ``lost`` (absent there) paid nothing for the earlier amount and restored its reduction, so
    two 20s on a base of 250 left the maximum at 230 instead of 210."""
    from combat import maximum_hp
    from combat.ext.maximum_hp_riders import LOST, max_hp_loss

    engine = _fight(["TAL_UNMAKING_RUIN_CHANNEL", *WITH_STRAIN], seed="HPLOSSLEGACY")
    me = engine.state.actors[ME]
    maximum, current = me.maximum_hp, me.current_hp
    assert max_hp_loss(engine, me, 20, "test:first", name="First price", key="test") == -20
    # rebuild the exact shape a pre-change save holds: a condition with `amount` and no running total
    held = next(c for c in me.conditions.values() if c.condition_id.startswith(LOST))
    label = str(held.data["label"])
    engine._remove_condition(me, held.condition_id, "test:first")
    engine._apply_condition(me, held.condition_id, "test:first", me.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": label, "amount": 20})
    legacy = next(c for c in me.conditions.values() if c.condition_id == held.condition_id)
    assert "lost" not in legacy.data, "the pre-change shape"
    maximum_hp.bind(engine, me, legacy, -20, label=label, current_floor=1)

    # commit and reload: the earlier payment must come back off the saved maximum, not only off this session's
    reloaded = type(me).model_validate(json.loads(json.dumps(me.model_dump(mode="json"), sort_keys=True)))
    engine.state.actors[ME] = reloaded
    assert reloaded.maximum_hp == maximum - 20, "the saved reduction travels with the actor"
    paid_before = reloaded.current_hp

    assert max_hp_loss(engine, reloaded, 20, "test:first", name="First price", key="test") == -20, \
        "this payment is worth 20 on its own"
    assert reloaded.maximum_hp == maximum - 40, "both payments are on the maximum, neither forgotten"
    assert reloaded.current_hp == paid_before - 20, \
        "and only the new payment reaches current Hit Points; the earlier one is not charged again"
    again = next(c for c in reloaded.conditions.values() if c.condition_id == legacy.condition_id)
    assert int(again.data["lost"]) == 40 and int(again.data["amount"]) == 20, "integers only, so a save keeps them"


def test_a_maximum_hit_point_price_never_drops_a_living_creature_to_zero():
    engine = _fight(["TAL_UNMAKING_RUIN_CHANNEL", *WITH_STRAIN], seed="HPFLOOR")
    me = engine.state.actors[ME]
    from combat.ext.maximum_hp_riders import max_hp_loss

    me.current_hp = 5
    max_hp_loss(engine, me, 10, "test:floor", name="First price", key="test")
    assert me.current_hp == 1, "the printed wound is lasting, not a death"


# ------------------------------------------------------------------------------------------------ retired reminder rows
def _reminders(mids=None):
    bundle = compile_character(_sheet(mids or unmaking_ids(), dc=100), actor_id="actor:factory.ruin",
                               reaction_plan={"ask": True})
    return " ".join(str(rider) for action in bundle["action_catalog"]
                    for rider in ((action.get("parameters") or {}).get("typed") or {}).get("riders") or [])


def test_the_unmaking_fighter_no_longer_shows_a_gm_reminder_for_these_talents():
    """Each of these rows described work the table now does itself; the compiled action must carry no GM line for it."""
    lines = _reminders()
    for stale in ("Unbound Trace's cost here is 1 Black Vein Strain",
                  "Fourth Ruin Form: Black-Vein Body costs 2 CP",
                  "the GM ends that summoning effect",
                  "The d6 that delays the chosen Channel's Crack",
                  "Ruin damage (damage type not in allowed list)",
                  "the GM applies the extra 3d8 + PB Ruin damage",
                  "(story, not combat)",
                  "This does not prevent resurrection"):
        assert stale not in lines, f"{stale!r} is still a GM reminder"


def test_no_unmaking_reminder_still_reads_like_an_engine_note():
    """Checklist 13: what is left is a limitation or a manual ruling the game cannot decide, said to a player."""
    lines = _reminders()
    for jargon in ("(the GM applies it", "the table tracks", "the table has no", "(story, not combat)",
                   "Ruin damage (damage type not in allowed list)"):
        assert jargon not in lines, f"{jargon!r} is engine wording in a player-facing reminder"


def test_the_unmaking_cover_in_the_coverage_report():
    """The report the lead reads: nothing in the RIDERS column, and the retired talents are FULL."""
    mechanics = json.loads(AUTHORITY.read_bytes())["mechanics"]
    counts: dict[str, int] = {}
    for row in mechanics.values():
        # P13 added manual Insight records associated with this sphere; this census
        # describes the Unmaking talents whose AUTO84 implementation it verifies.
        if row.get("sphere_id") == unmaking.UNMAKING and not row["mechanic_id"].startswith("insight."):
            counts[row["coverage"]] = counts.get(row["coverage"], 0) + 1
    assert counts.get("RIDERS_ONLY", 0) == 0
    assert counts["FULL"] == 25, counts
    for key in ("TAL_UNMAKING_FOURTH_RUIN_FORM_BLACK_VEIN_BODY", "TAL_UNMAKING_FIRST_RUIN_FORM_EXTERNAL_VESSEL_MANDATE",
                "TAL_UNMAKING_UNBODY_THE_FALSE_VESSEL", "TAL_UNMAKING_WOUND_THAT_REFUSES",
                "TAL_UNMAKING_DEVOURING_DREGS", "TAL_UNMAKING_RUIN_NEEDLE"):
        assert mechanics[key]["coverage"] == "FULL", f"{key} is {mechanics[key]['coverage']}"
