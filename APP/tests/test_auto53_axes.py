"""AUTO53 (automation lane, Axes sphere): the printed Axes mechanics the engine now resolves.

Owner 2026-10-05: "automate everything".  Scope: the Axes Sphere's CORE/RIDERS mechanics whose printed lines reached the table
as nothing at all (an inert typed row) instead of an effect.

Typed data: APP/authority/typed_mechanics/reviewed_final.d/{review_sw-athletics,riders_lane3}.json (rebuilt with
tools/build_typed_mechanics_authority.py), combat/rules/typed_conditions.json (mark_counts_as), and the feature blocks in
combat/rules/feature_blocks.d/auto53.json.
Plug-ins: APP/combat/ext/axes_falling_tree.py, APP/combat/ext/axes_execution.py.
Every test compiles a real Factory Axes fighter, puts it in a real fight with real gate-2 fighters, and reads the events the
shipped code wrote.  Saves are forced with the sheet's technique DC (50: the target fails, -40: it succeeds).
"""
from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate2_runtime_models import Position
from combat.typed_executor import bears_mark, mark_condition_id

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("sw_athletics_harness", _HERE / "test_review_sw-athletics.py")
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)

ME, AN, FOE, AXES, HEWING, AXE_KIT = H.ME, H.AN, H.FOE, H.AXES, H.HEWING, H.AXE_KIT
STRIKE = H.STRIKE
FAIL, PASS = H.FAIL, H.PASS
ALLY = "actor:factory.auto53_ally"
LAW = "TAL_AXES_LAW_OF_THE_FALLING_TREE"
MARK = "TAL_AXES_EXECUTION_MARK"
EXECUTION = mark_condition_id("Execution Mark", ME)


def _axe(talents, *, cl=10, dc=16):
    return H._bundle(AXES, [HEWING, *talents], AXE_KIT, cl=cl, dc=dc)


def _three(talents, *, dc, cl=10, foe_at=(4, 6), ally_at=(5, 6), foe_hp=None):
    """The axe fighter (3,6), an ally of its own team beside the foe, and a foe it is sure to hit.

    ``foe_hp`` sets the foe's current Hit Points.  The Law of the Falling Tree's printed trigger is a
    *fall* -- knocked Prone, or reduced to 0 HP -- so a test that wants the talent to fire sets the foe
    where one blow actually brings it down (``foe_hp=1``); leaving it wounded but standing is how a test
    shows the talent does *not* fire.
    """
    bundles = (compile_character(H._sheet(AXES, [HEWING, *talents], AXE_KIT, cl=cl, dc=dc), actor_id=ME),
               compile_character(H._sheet(None, [], AXE_KIT), actor_id=ALLY),
               compile_character(H._sheet(None, [], AXE_KIT), actor_id=FOE))
    engine = Gate4ControllerEngine(H.ROOT, match_seed="AUTO53", typed_bundles=bundles, roster_setup={
        "primary_actor_ids": [ME, ALLY, FOE], "team_by_actor": {ME: "team:a", ALLY: "team:a", FOE: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, ALLY: {"x": ally_at[0], "y": ally_at[1]},
                               FOE: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[FOE].armor_class = -50
    engine.state.actors[FOE].current_hp = engine.state.actors[FOE].maximum_hp // 4 if foe_hp is None \
        else max(1, int(foe_hp))
    H._ready(engine)
    return engine


def _duel(talents, *, dc, **kw):
    """The axe fighter and one foe (the shared harness's two-creature engine)."""
    return H._engine(H._bundle(AXES, [HEWING, *talents], AXE_KIT, dc=dc), **kw)


def _conds(actor):
    return {row.condition_id for row in actor.conditions.values()}


def _saves(events):
    return [payload for payload in H._payloads(events, "SAVE_ROLLED")]


def _resources(actor):
    return {key: int(actor.resources.get(key, 0) or 0) for key in ("resource:core.qi", "resource:core.stamina",
                                                                    "resource:core.martial_focus")}


def _heal(engine, creature, amount):
    """Healing that lands through the typed executor's own heal path (the healing_pending seam's caller)."""
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    from combat.typed_executor import Context, run_effects

    action = ActionDefinition(source_definition_id="test:auto53.heal", display_name="Test healing", owner_id=creature.entity_id,
                              economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF",
                              parameters={"typed": {"source": "test:auto53.heal", "numbers": {}, "duration": {"kind": "instant"}}})
    typed = (action.parameters or {})["typed"]
    before = len(engine.events)
    run_effects(Context(engine, creature, action, getattr(engine, "_active_intent", None), typed, [creature], creature, {}),
                [{"type": "healing", "applies_to": "target", "flat": amount}])
    return engine.events[before:]


def _auto_reactions(engine):
    """The shipped gate-4 controller answers every choice (AI actors decide by themselves, checklist item 9)."""
    from combat.gate4_context import build_reaction_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_models import LocalControllerPolicy
    from combat.gate4_policy import PolicyLibrary

    controller, policies = LocalDeterministicController(), PolicyLibrary(H.ROOT)

    def react(request):
        policy, _row = policies.for_actor(request["reactor_id"])
        choice = controller.choose_reaction(build_reaction_context(engine, policy, request))
        return choice.decision, choice.record.model_dump(mode="json")

    engine.set_reaction_provider(react)
    return engine


def _use_as(engine, name, actor_id):
    """One of ``actor_id``'s own legal actions, through the ordinary intent (its own turn must be current)."""
    from combat.gate2_runtime_models import ActionIntent

    while engine.state.current_actor_id != actor_id:
        engine.end_turn()
    matches = [row for row in engine.legal_candidates() if row.display_name == name and row.actor_id == actor_id]
    assert matches, f"{name!r} is not legal for {actor_id}: {sorted({row.display_name for row in engine.legal_candidates()})[:20]}"
    candidate = matches[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"auto53:{name}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor_id, target_ids=candidate.target_ids or (),
                                       destination=candidate.destination))
    return engine.events[before:]


# =============================================================== Law of the Falling Tree
def test_law_of_the_falling_tree_asks_a_creature_beside_the_fallen_one_to_make_a_dexterity_save():
    """"Choose one creature within 10 feet of the fallen target or broken object. That creature makes a Dexterity saving throw."
    The talent used to compile one inert `rider` row, so nothing at all happened after a knockdown."""
    engine = _three([LAW], dc=FAIL, foe_hp=1)
    H._use(engine, STRIKE + "Bite", target=FOE)  # the foe's own Bite choice; this talent is a separate free trigger
    saves = _saves(engine.events)
    assert saves, "no saving throw was rolled for the creature beside the fall"
    assert {payload["actor_id"] for payload in saves} == {ALLY}, saves  # the creature beside the fall, not the one that fell
    assert {int(payload["dc"]) for payload in saves} == {FAIL}, saves  # against the owner's Cultivation Save DC


def test_law_of_the_falling_tree_failure_knocks_the_nearby_creature_prone():
    """"Failed Save: It falls Prone or is pushed 10 feet away from the fall."  A Failed Save (DC 50) ends with it Prone."""
    engine = _three([LAW], dc=FAIL, foe_hp=1)
    H._use(engine, STRIKE + "Bite", target=FOE)
    assert "condition:typed.prone" in _conds(engine.state.actors[ALLY]), sorted(_conds(engine.state.actors[ALLY]))


def test_law_of_the_falling_tree_success_lets_the_creature_step_five_feet_clear():
    """"Successful Save: It moves 5 feet to a space of its choice that is not closer to you, if it can."  A Successful Save
    (DC -40) steps it 5 feet instead."""
    engine = _three([LAW], dc=PASS, foe_hp=1)
    ally = engine.state.actors[ALLY]
    start = ally.position
    H._use(engine, STRIKE + "Bite", target=FOE)
    assert "condition:typed.prone" not in _conds(ally)
    assert ally.position != start, "the creature beside the fall never stepped"
    assert engine.grid.distance_ft(ally.position, start) == 5
    assert engine.grid.distance_ft(ally.position, H._me(engine).position) >= engine.grid.distance_ft(start, H._me(engine).position)


def test_law_of_the_falling_tree_pays_exactly_one_of_its_printed_pools():
    """"you may spend 1 CP, 1 Stamina, or expend Martial Focus": one pool, one point."""
    engine = _three([LAW], dc=FAIL, foe_hp=1)
    me = H._me(engine)
    before = _resources(me)
    H._use(engine, STRIKE + "Bite", target=FOE)
    spent = {pool: before[pool] - _resources(me)[pool] for pool in before if before[pool] != _resources(me)[pool]}
    assert spent and sum(spent.values()) == 1, spent


def test_law_of_the_falling_tree_never_fires_for_a_character_without_the_talent():
    """No feature-block row, no behaviour: the same knockdown resolves nothing else."""
    engine = _three([], dc=FAIL)
    H._use(engine, STRIKE + "Bite", target=FOE)
    assert not _saves(engine.events), _saves(engine.events)


def test_law_of_the_falling_tree_is_still_not_a_modifier_on_every_hewing_strike():
    """The sweep guard (test_review_sw-athletics.py) keeps the trigger off the attack's rider list; this lane does not
    put it back: the talent's own action list is unchanged."""
    bundle = H._bundle(AXES, [HEWING, LAW], AXE_KIT)
    assert not [name for name in H._rows(bundle) if "Falling Tree" in name], sorted(H._rows(bundle))


# =============================================================== Execution Mark
def test_execution_mark_lands_on_a_bloodied_creature_hewing_strike_hits():
    """"When you hit a Bloodied creature with Hewing Strike or Cast Axe, you may place an Execution Mark instead of a normal
    rider": the placement is typed (rider lane 3).  What this lane adds is the Reaction the mark buys, so the test reads the
    mark the typed rider places and then drives that Reaction."""
    engine = H._engine(_axe([MARK]), foe_hp=20)  # at or below half its maximum Hit Points: Bloodied
    H._use(engine, STRIKE + "Bite", target=AN)
    held = _conds(H._foe(engine))
    assert EXECUTION in held, sorted(held)
    assert "condition:typed.mark.bite." + ME in held, sorted(held)  # "counts as Bite for your Axes talents"


def test_execution_mark_reacts_to_the_target_regaining_hit_points():
    """"The first time before the mark ends that the target regains HP ... you may use your Reaction to make one axe weapon
    attack against it."  The owner's own axe attack resolves as a Reaction, and that one trigger is spent.

    (AUTO53f1: the mark itself is no longer deleted here.  The printed mark "lasts until the start of your
    next turn and counts as Bite"; only its one trigger is spent, and it stays spent -- see
    test_execution_mark_is_only_the_first_time_before_it_ends.)"""
    engine = _duel([MARK], dc=FAIL)
    me, foe = H._me(engine), H._foe(engine)
    engine._apply_condition(foe, EXECUTION, MARK, ME, expires_on="UNTIL_REMOVED")
    foe.current_hp = max(1, foe.maximum_hp - 10)
    events = _heal(engine, foe, 5)
    assert H._payloads(events, "REACTION_RESOLVED"), [event.event_type for event in events]
    assert any(int((event.payload or {}).get("hp_damage") or 0) > 0
               for event in events if event.event_type == "DAMAGE_COMMITTED"), events
    assert not me.reaction_available, "the owner's Reaction was not spent"
    assert EXECUTION in _conds(foe), "the mark still lasts until the start of your next turn"


def test_execution_mark_is_only_the_first_time_before_it_ends():
    engine = _duel([MARK], dc=FAIL)
    me, foe = H._me(engine), H._foe(engine)
    engine._apply_condition(foe, EXECUTION, MARK, ME, expires_on="UNTIL_REMOVED")
    foe.current_hp = max(1, foe.maximum_hp - 10)
    _heal(engine, foe, 5)
    me.reaction_available = True
    events = _heal(engine, foe, 5)
    assert not H._payloads(events, "REACTION_RESOLVED"), H._payloads(events, "REACTION_RESOLVED")


def test_execution_mark_needs_the_reaction_it_prints():
    engine = _duel([MARK], dc=FAIL)
    me, foe = H._me(engine), H._foe(engine)
    engine._apply_condition(foe, EXECUTION, MARK, ME, expires_on="UNTIL_REMOVED")
    me.reaction_available = False
    foe.current_hp = max(1, foe.maximum_hp - 10)
    events = _heal(engine, foe, 5)
    assert not H._payloads(events, "REACTION_RESOLVED"), H._payloads(events, "REACTION_RESOLVED")


def test_execution_mark_reacts_to_the_target_taking_the_disengage_action():
    """"... or takes the Disengage action": the same one axe attack, from the foe's own turn."""
    engine = _auto_reactions(_duel([MARK], dc=FAIL, foe_at=(4, 6)))
    me, foe = H._me(engine), H._foe(engine)
    engine._apply_condition(foe, EXECUTION, MARK, ME, expires_on="UNTIL_REMOVED")
    events = _use_as(engine, "Disengage", AN)  # the sparring foe is the harness AN, not my third fighter
    assert H._payloads(events, "REACTION_RESOLVED"), [event.event_type for event in events]
    assert not me.reaction_available


def test_execution_mark_reacts_to_the_target_turning_invisible():
    """"... or turns Invisible": the same one axe attack."""
    engine = _duel([MARK], dc=FAIL)
    me, foe = H._me(engine), H._foe(engine)
    engine._apply_condition(foe, EXECUTION, MARK, ME, expires_on="UNTIL_REMOVED")
    events = _apply_invisible(engine, foe)
    assert H._payloads(events, "REACTION_RESOLVED"), [event.event_type for event in events]
    assert not me.reaction_available


def test_execution_mark_stays_quiet_against_a_creature_out_of_reach():
    """"if it is within your weapon's reach": a marked creature 30 feet away is not answered (the printed axe-line range is
    the GM's, and is reported as the remaining rider)."""
    engine = _duel([MARK], dc=FAIL, foe_at=(12, 6))
    me, foe = H._me(engine), H._foe(engine)
    engine._apply_condition(foe, EXECUTION, MARK, ME, expires_on="UNTIL_REMOVED")
    foe.current_hp = max(1, foe.maximum_hp - 10)
    events = _heal(engine, foe, 5)
    assert not H._payloads(events, "REACTION_RESOLVED"), H._payloads(events, "REACTION_RESOLVED")
    assert me.reaction_available


def test_execution_mark_is_inert_for_a_character_without_the_talent():
    engine = _duel([], dc=FAIL)
    foe = H._foe(engine)
    engine._apply_condition(foe, EXECUTION, "test:stranger", ME, expires_on="UNTIL_REMOVED")
    foe.current_hp = max(1, foe.maximum_hp - 10)
    events = _heal(engine, foe, 5)
    assert not H._payloads(events, "REACTION_RESOLVED"), H._payloads(events, "REACTION_RESOLVED")


def _apply_invisible(engine, creature):
    before = len(engine.events)
    engine._apply_condition(creature, "condition:typed.invisible", "test:auto53.invisible", creature.entity_id,
                            expires_on="UNTIL_REMOVED")
    return engine.events[before:]


# =============================================================== AUTO53f1: the review fixes
def _force(engine, **by_choice):
    """Answer this engine's own choices by name, so a test can pick a printed branch.

    ``_force(engine, axes_falling_tree_fall="push")`` makes the wielder's Prone-or-push question answer
    "push".  Anything else keeps the shipped gate-4 controller's answer.
    """
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate4_context import build_reaction_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_models import LocalControllerPolicy
    from combat.gate4_policy import PolicyLibrary

    controller, policies = LocalDeterministicController(), PolicyLibrary(H.ROOT)

    def react(request):
        for name, option in by_choice.items():
            if str(request.get("reaction_source_id") or "").endswith(name) and option:
                return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                        reaction_source_id=request["reaction_source_id"], selection="USE",
                                        spend=0, option_ids=[option]), None
        policy, _row = policies.for_actor(request["reactor_id"])
        choice = controller.choose_reaction(build_reaction_context(engine, policy, request))
        return choice.decision, choice.record.model_dump(mode="json")

    engine.set_reaction_provider(react)
    return engine


def test_falling_tree_does_not_fire_on_a_hit_that_only_wounds():
    """F1. "reduce a creature to 0 HP" is about the creature's remaining Hit Points.

    The trigger read DAMAGE_COMMITTED's ``reduced_to``, which is the damage the blow dealt, so it fired on
    *every* hit: a wounded foe standing at a quarter of its Hit Points shook the ground loose anyway.
    """
    engine = _three([LAW], dc=FAIL)  # the foe survives the hit
    assert engine.state.actors[FOE].current_hp > 0
    H._use(engine, STRIKE + "Bite", target=FOE)
    assert engine.state.actors[FOE].current_hp > 0, "this test needs the foe to survive its wound"
    assert not _saves(engine.events), "a mere wound is not a fall"


def _owner_axes_action(engine):
    """One of the axe fighter's own compiled Axes-sphere actions ("with an Axes talent")."""
    for action in engine.action_catalog.values():
        typed = ((getattr(action, "parameters", None) or {}).get("typed") or {})
        if action.owner_id == ME and str(action.source_definition_id).startswith("action:") and \
                typed.get("sphere") == "tianxia.sphere.axes":
            return action
    raise AssertionError("the fighter owns no compiled Axes action")


def test_falling_tree_does_not_fire_when_the_foe_was_already_prone():
    """F1. "knock a creature Prone" is a new knockdown, not a Prone it already carried.

    The trigger used to accept any Prone condition landing on the target, so a creature that was already
    down -- a refreshed Prone, a second knock in the same hit -- shook the ground loose again.
    """
    engine = _three([LAW], dc=FAIL)
    source = _owner_axes_action(engine).source_definition_id
    before = len(engine.events)
    engine._apply_condition(engine.state.actors[FOE], "condition:typed.prone", source, ME, expires_on="UNTIL_REMOVED")
    assert _saves(engine.events[before:]), "a new knockdown is a fall"
    before = len(engine.events)
    engine._apply_condition(engine.state.actors[FOE], "condition:typed.prone", source, ME, expires_on="UNTIL_REMOVED")
    assert not _saves(engine.events[before:]), "a creature that is already Prone is not a new fall"


def test_falling_tree_pushes_away_from_the_fall_not_the_wielder():
    """F4. "is pushed 10 feet away from the fall" -- the fall is a different creature than the wielder.

    The row used the engine's ordinary ``forced_movement``, which runs away from *its caster*, so the
    creature was shoved away from the axe wielder instead of away from the body that fell.  Here the two
    anchors are a square apart: the wielder is west of the ally, the fallen foe is north of it, so the
    printed push (due north) and the old caster-anchored push (due east) cannot both pass.
    """
    engine = _force(_three([LAW], dc=FAIL, foe_hp=1, foe_at=(4, 5), ally_at=(4, 6)),
                    axes_falling_tree_fall="push")
    ally = engine.state.actors[ALLY]
    start = ally.position
    H._use(engine, STRIKE + "Bite", target=FOE)
    fallen = engine.state.actors[FOE].position
    assert ally.position != start, "the creature beside the fall was not pushed"
    outward = (start.x - fallen.x, start.y - fallen.y)
    moved = (ally.position.x - fallen.x, ally.position.y - fallen.y)
    # the push must carry it straight out along the ray that starts at the fall
    assert outward[0] * moved[1] == outward[1] * moved[0] and \
        (moved[0] * outward[0] + moved[1] * outward[1]) > 0, \
        (f"pushed to {ally.position} from a fall at {fallen}: the printed push goes away from the fall "
         f"(due {'east' if outward[0] else 'south'} of it), not away from the wielder")


def test_falling_tree_withdrawal_uses_the_creatures_own_movement():
    """F6. "It moves 5 feet" is the creature's own movement, run natively.

    The old code used the free ``step_to`` helper: the creature changed square for nothing, could not be
    stopped, and left its space without provoking anything.  The shared voluntary path spends its own
    movement allowance and records a real MOVEMENT_COMMITTED for it.
    """
    engine = _three([LAW], dc=PASS, foe_hp=1)
    ally = engine.state.actors[ALLY]
    start = ally.position
    H._use(engine, STRIKE + "Bite", target=FOE)
    assert ally.position != start, "the creature beside the fall never stepped"
    moves = [event for event in engine.events if event.event_type == "MOVEMENT_COMMITTED"
             and event.actor_id == ALLY]
    assert moves, "the withdrawal was not recorded as the creature's own movement"
    assert any(int((event.payload or {}).get("cost_ft") or 0) > 0 for event in moves), \
        [(e.payload or {}).get("cost_ft") for e in moves]


def _marked_foe(engine, *, mark=True, hp_below=True):
    """The duel engine with the mark on the foe, as rider lane 3 places it.

    Lane 3 places two separate marks -- the Execution Mark itself and the Bite it counts as -- so both are
    placed here, exactly as the typed rider does.
    """
    me, foe = H._me(engine), H._foe(engine)
    if mark:
        engine._apply_condition(foe, EXECUTION, MARK, ME, expires_on="UNTIL_REMOVED")
        engine._apply_condition(foe, mark_condition_id("Bite", ME), MARK, ME, expires_on="UNTIL_REMOVED")
    if hp_below:
        foe.current_hp = max(1, foe.maximum_hp - 10)
    return me, foe


def _marked_foe_three(engine):
    """The three-creature engine with lane 3's two marks on the foe, wounded."""
    me, foe = H._me(engine), engine.state.actors[FOE]
    engine._apply_condition(foe, EXECUTION, MARK, ME, expires_on="UNTIL_REMOVED")
    engine._apply_condition(foe, mark_condition_id("Bite", ME), MARK, ME, expires_on="UNTIL_REMOVED")
    return me, foe


def test_execution_mark_ignores_a_heal_that_never_landed():
    """F2. "the target regains HP" is committed recovery.

    The reaction used to be offered on ``healing_pending``, the seam that runs *before* Hit Points are
    granted and exists to let another ability take points off a heal.  Here a real amount of healing is
    offered to a creature that is already at full Hit Points: the old hook spent the mark's one trigger and
    the owner's Reaction on a heal that changed nothing.
    """
    engine = _duel([MARK], dc=FAIL)
    me, foe = _marked_foe(engine, hp_below=False)
    assert foe.current_hp == foe.maximum_hp, "this test needs the target already at full Hit Points"
    before = len(engine.events)
    _heal(engine, foe, 5)
    assert H._payloads(engine.events[before:], "HEALING_APPLIED"), "the heal was offered"
    assert not H._payloads(engine.events[before:], "REACTION_RESOLVED"), \
        "no Hit Points were regained, so the mark's one trigger is not spent"
    assert me.reaction_available, "the owner's Reaction was spent on a heal that never landed"


def test_execution_mark_keeps_its_bite_and_lifetime_after_the_reaction():
    """F3. Using the Reaction does not end the mark.

    "The mark lasts until the start of your next turn and counts as Bite for your Axes talents" is
    independent of the one Reaction.  The old code deleted the mark to remember "the first time", which
    also threw away the Bite it counts as.
    """
    engine = _duel([MARK], dc=FAIL)
    me, foe = _marked_foe(engine)
    _heal(engine, foe, 5)
    assert H._payloads(engine.events, "REACTION_RESOLVED"), "the Reaction did not fire"
    held = _conds(foe)
    assert EXECUTION in held, "the mark still lasts until the start of your next turn"
    assert "condition:typed.mark.bite." + ME in held, "the mark still counts as Bite for the owner's Axes talents"


def test_execution_mark_reacts_to_invisibility_granted_by_someone_else():
    """F5. "turns Invisible" is a state of the marked creature; the mark does not care who cast it.

    The trigger required the creature to be the *actor* of its own CONDITION_APPLIED, so an ally's
    Invisibility -- which is how most of it happens in play -- never woke the mark.  Here the mark owner's
    own ally turns the marked foe Invisible.
    """
    engine = _three([MARK], dc=FAIL)  # ME (owner) and ALLY are one team; FOE carries the mark
    me, foe = _marked_foe_three(engine)
    assert engine.state.actors[ALLY].team_id == me.team_id, "the granter must be an ally of the mark's owner"
    before = len(engine.events)
    engine._apply_condition(foe, "condition:typed.invisible", "test:auto53.ally.invisible", ALLY,
                            expires_on="UNTIL_REMOVED")
    assert H._payloads(engine.events[before:], "REACTION_RESOLVED"), \
        "the marked creature turned Invisible, whoever granted it"


def test_execution_mark_ignores_a_forced_drag():
    """F5. A drag is not a teleport.

    The engine records a dragged move with ``forced`` set and no ``teleport``, so the printed "teleports"
    is a real teleport of the creature's own.  This is the filter that keeps a shove from spending the mark.
    """
    engine = _duel([MARK], dc=FAIL, foe_at=(4, 6))
    me, foe = _marked_foe(engine)
    before = len(engine.events)
    engine._append_event("MOVEMENT_COMMITTED", "test:auto53.drag", actor_id=FOE, target_ids=(FOE,),
                         payload={"destination": {"x": 5, "y": 6, "z": 0}, "path": [], "cost_ft": 0,
                                  "forced": True})
    assert not H._payloads(engine.events[before:], "REACTION_RESOLVED"), "a forced drag is not a teleport"
    assert me.reaction_available


def test_execution_mark_first_trigger_survives_a_commit_and_reload():
    """F3 + checklist 7. The "first time" record is read back from the recorded events, not from a field.

    The mark is left in place, so the record has to come from the event log.  Replaying the fight's own
    events through the gate-3 reducer (what a table commit and reload does) must reach the same answer.
    """
    from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
    from combat.ext.axes_execution import _already_triggered
    from combat.typed_executor import mark_condition_id

    engine = _duel([MARK], dc=FAIL)
    # the state as it stood before the mark was placed: the starting point a reload rebuilds from
    committed = engine.state.model_copy(deep=True)
    from_here = int(committed.event_sequence)
    me, foe = _marked_foe(engine)
    _heal(engine, foe, 5)
    assert H._payloads(engine.events, "REACTION_RESOLVED")
    me.reaction_available = True
    before = len(engine.events)
    _heal(engine, foe, 5)
    assert not H._payloads(engine.events[before:], "REACTION_RESOLVED"), "a second recovery is not the first time"

    # rebuild the fight from the committed state plus the recorded events, the way a reload does
    replayed = Gate3EventReducer().apply_events(
        committed, enrich_committed_events(
            [event for event in engine.events if int(event.sequence) > from_here], post_engine=engine),
        expected_start_sequence=from_here + 1)
    marks = [condition for condition in replayed.actors[AN].conditions.values()
             if condition.condition_id == mark_condition_id("Execution Mark", me.entity_id)]
    assert marks, "the mark must survive the commit and reload"
    assert any(int(condition.applied_sequence or 0) > 0 for condition in marks), \
        "the reloaded mark must still know when its window opened"

    class _Reloaded:
        """The little of the engine _already_triggered reads: its actors and its recorded events."""
        def __init__(self, state, events):
            self.state = state
            self.events = events

    # the record is the event log, so the reloaded fight answers the same question as the live one
    reloaded_engine = _Reloaded(replayed, [event for event in engine.events if int(event.sequence) > from_here])
    assert _already_triggered(reloaded_engine, replayed.actors[AN], marks[0]), \
        "the reloaded fight must still know the first trigger has been seen"
    assert not _already_triggered(reloaded_engine, replayed.actors[AN],
                                  _fresh_mark(mark_condition_id("Execution Mark", me.entity_id))), \
        "a mark placed after those events has not seen its first trigger yet"


def _fresh_mark(condition_id):
    from combat.gate2_runtime_models import ConditionInstance

    return ConditionInstance(instance_id="fresh", condition_id=condition_id, source_definition_id=MARK,
                             source_actor_id=ME, target_id=AN, applied_sequence=10_000)


def test_execution_mark_rider_text_carries_no_lane_code():
    """F8/checklist 13. The rider reaches the table, so it names no lane, ticket or internal code."""
    import json as _json
    from pathlib import Path

    rows = _json.loads((Path(__file__).resolve().parents[1] /
                        "authority/typed_mechanics/reviewed_final.d/riders_lane3.json").read_text())
    riders = " ".join(rows["mechanics"]["TAL_AXES_EXECUTION_MARK"].get("riders") or [])
    for code in ("auto53", "AUTO53", "lane3", "lane 3", "2026-10-05"):
        assert code not in riders, f"{code!r} must not appear in player-facing rider text: {riders!r}"


# =============================================================== AUTO53r1f1: review fixes
def _heal_by(engine, healer, target, amount):
    """Healing that lands through the executor's own heal path, applied by ``healer`` to ``target``.

    The recorded HEALING_APPLIED carries the healer as ``actor_id`` and the healed creature in
    ``target_ids`` (combat/gate2_engine.py), which is what the mark's printed trigger has to read.
    """
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    from combat.typed_executor import Context, run_effects

    action = ActionDefinition(source_definition_id="test:auto53.heal_by", display_name="Test healing by another creature",
                              owner_id=healer.entity_id, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                              target_kind="ALLY_OR_SELF",
                              parameters={"typed": {"source": "test:auto53.heal_by", "numbers": {},
                                                    "duration": {"kind": "instant"}}})
    typed = (action.parameters or {})["typed"]
    before = len(engine.events)
    run_effects(Context(engine, healer, action, getattr(engine, "_active_intent", None), typed, [target], target, {}),
                [{"type": "healing", "applies_to": "target", "flat": amount}])
    return engine.events[before:]


def _spy_reactions(engine, *, answers=None, **by_choice):
    """The shipped gate-4 controller, with every question it is asked recorded.

    Returns the list it fills, so a test can tell "the question was put to the table" from
    "the plug-in answered for the owner", which is the whole point of the routing check.
    ``answers`` collects every ``(spec, decision)`` this helper answers itself, so a test can put its own
    answer through the shipped validator (``combat/choice_checkpoints.validate``) instead of assuming it.
    """
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate4_context import build_reaction_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_policy import PolicyLibrary

    asked: list[tuple[str, str]] = []
    controller, policies = LocalDeterministicController(), PolicyLibrary(H.ROOT)

    def react(request):
        asked.append((str(request.get("reaction_source_id") or ""), str(request.get("reactor_id") or "")))
        for name, option in by_choice.items():
            if str(request.get("reaction_source_id") or "").endswith(name) and option:
                if str(option).upper() == "DECLINE":
                    # A real decline: the transport validates a decline as DECLINE with no options and
                    # nothing spent.  Sending "DECLINE" as a USE option id is malformed, and the
                    # validation error is swallowed by the observational event wrapper -- the mark would
                    # then look declined for the wrong reason.
                    decision = ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                                reaction_source_id=request["reaction_source_id"], selection="DECLINE",
                                                spend=0, option_ids=())
                else:
                    decision = ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                                spend=0, option_ids=[option])
                if answers is not None:
                    answers.append((request.get("extension_choice") or {}, decision))
                return decision, None
        policy, _row = policies.for_actor(request["reactor_id"])
        choice = controller.choose_reaction(build_reaction_context(engine, policy, request))
        return choice.decision, choice.record.model_dump(mode="json")

    engine.set_reaction_provider(react)
    return asked


def _accepted_by_the_transport(spec, decision):
    """Whether ``decision`` is an answer the shipped choice transport accepts for ``spec``.

    ``combat/choice_checkpoints.validate`` is what ``gate5_service`` runs on every table answer, so a
    test that answers the table any other way is not testing the mark: it is testing that its own
    malformed answer was swallowed somewhere on the way down.
    """
    from combat.choice_checkpoints import ExtensionChoice, validate

    validate(decision, ExtensionChoice.model_validate(spec))


def _no_hook_failure(engine, *, since=0):
    """Assert the plug-in's own hook raised nothing, and that the observational wrapper logged nothing.

    ``combat/ext.__init__.py`` swallows a hook's exception, records a one-per-fight ``GM_RIDER`` rider
    naming the failing hook, and keeps the fight running -- so a plug-in that fails can leave exactly
    the events a test asserts, with the failure visible only in that rider (or in the log).  A routing
    or decline test that does not check for it proves nothing.
    """
    events = engine.events[since:]
    failures = [event for event in events if event.event_type == "GM_RIDER"
                and "failed:" in str((event.payload or {}).get("rider") or "")]
    assert not failures, [(event.payload or {}).get("rider") for event in failures]
    assert not getattr(engine, "_ext_failures_logged", None), getattr(engine, "_ext_failures_logged", None)


def _acting(engine, actor_id=ME):
    """Run a block with an action of ``actor_id`` in flight, the way a real trigger rides one."""
    from contextlib import contextmanager
    from combat.gate2_runtime_models import ActionIntent

    @contextmanager
    def block():
        candidate = next(row for row in engine.legal_candidates() if row.actor_id == actor_id)
        saved = getattr(engine, "_active_intent", None)
        engine._active_intent = ActionIntent(intent_id="auto53:in-flight", decision_id=candidate.decision_id,
                                             candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                             actor_id=actor_id, target_ids=candidate.target_ids or ())
        try:
            yield
        finally:
            engine._active_intent = saved

    return block()


# ---------------------------------------------------------------------------------- #1 healing from any source
def test_execution_mark_reacts_to_the_target_healing_from_someone_else():
    """R1 #1. "the target regains HP" is about the marked creature's Hit Points, not about who healed it.

    The trigger required the healer to be the recipient, so a heal from an ally never woke the mark and
    did not spend its one trigger either -- the owner could then be offered a *later* recovery as if it
    were the first.  Here an ally heals the marked foe: the mark offers, and the window is spent.
    """
    engine = _three([MARK], dc=FAIL)  # ME (owner) and ALLY are one team; FOE carries the mark
    me, foe = _marked_foe_three(engine)
    ally = engine.state.actors[ALLY]
    assert ally.entity_id != me.entity_id, "this test needs the healing to come from another creature"
    before = len(engine.events)
    healed = _heal_by(engine, ally, foe, 5)
    assert H._payloads(healed, "HEALING_APPLIED"), "the ally's heal did not land"
    assert H._payloads(engine.events[before:], "REACTION_RESOLVED"), \
        "the marked creature regained Hit Points, so the mark's one trigger is spent whoever healed it"
    assert not me.reaction_available, "the owner's Reaction was spent on the ally's healing"


def test_execution_mark_spends_its_one_trigger_on_a_declined_reaction():
    """R1 #1. The printed window is "the first time", so the recovery spends it whether or not the owner takes it."""
    engine = _three([MARK], dc=FAIL)
    me, foe = _marked_foe_three(engine)
    asked = _spy_reactions(engine, axes_execution_mark="")  # record the question, then let the controller answer
    with _acting(engine):
        _heal_by(engine, engine.state.actors[ALLY], foe, 5)
    assert [row for row in asked if "axes_execution_mark" in row[0]], "the owner was never asked"
    me.reaction_available = True
    before = len(engine.events)
    with _acting(engine):
        _heal_by(engine, engine.state.actors[ALLY], foe, 5)
    assert not H._payloads(engine.events[before:], "REACTION_RESOLVED"), \
        "a second recovery is not 'the first time', whatever the owner answered to the first"


def test_execution_mark_spends_its_one_trigger_when_the_owner_has_no_reaction_left():
    """R1 #1/#7. An owner with no Reaction to spend is still the owner of a mark whose first time has come."""
    engine = _three([MARK], dc=FAIL)
    me, foe = _marked_foe_three(engine)
    me.reaction_available = False
    before = len(engine.events)
    with _acting(engine):
        _heal_by(engine, engine.state.actors[ALLY], foe, 5)
    assert not H._payloads(engine.events[before:], "REACTION_RESOLVED"), "there was no Reaction to spend"
    me.reaction_available = True
    before = len(engine.events)
    with _acting(engine):
        _heal_by(engine, engine.state.actors[ALLY], foe, 5)
    assert not H._payloads(engine.events[before:], "REACTION_RESOLVED"), \
        "the first recovery spent the window even though the owner could not use it"


# ---------------------------------------------------------------------------------- #2 the originating event's identity
def test_execution_mark_answers_for_its_own_event_not_the_mutable_log_tail():
    """R1 #2. The trigger window is measured from the triggering event's own recorded sequence.

    A Ready response runs before extension delivery and appends its own events
    (combat/prepared_actions.py), so the mutable ``state.event_sequence`` tail has already run past the
    trigger.  Reading the tail made the trigger look spent and suppressed the owner's first Reaction.
    The engine preserves the exact recorded event as ``kwargs["originating_event"]`` for this.
    """
    from combat.ext.axes_execution import _already_triggered, _event_sequence

    engine = _duel([MARK], dc=FAIL)
    me, foe = _marked_foe(engine)
    mark = foe.conditions[next(instance for instance, row in foe.conditions.items() if row.condition_id == EXECUTION)]
    trigger = engine._append_event("HEALING_APPLIED", "test:auto53.heal", actor_id=AN, target_ids=(AN,),
                                   payload={"offered": 5, "before": max(0, foe.current_hp - 5), "after": foe.current_hp})
    # the Ready response's own events, recorded after the trigger was and before the hook runs
    for index in range(3):
        engine._append_event("CONDITION_APPLIED", "test:auto53.ready", actor_id=ME, target_ids=(ME,),
                             payload={"condition_id": f"test:auto53.ready{index}", "instance_id": f"ready{index}"})
    tail = int(engine.state.event_sequence)
    assert tail > trigger.sequence, "the log tail has run past the trigger, as a Ready response makes it"
    assert not _already_triggered(engine, foe, mark, _event_sequence(engine, {"originating_event": trigger})), \
        "the recovery happening now is not a spent trigger"
    assert _already_triggered(engine, foe, mark, tail), \
        "reading the mutable tail really does mistake the current trigger for a spent one"


# ---------------------------------------------------------------------------------- #3 withdrawal budget
def test_falling_tree_withdrawal_leaves_a_creature_that_has_spent_its_movement():
    """R1 #3. "if it can" is the creature's own movement allowance.

    Candidates were generated from a five-foot grant and then executed against the creature's real
    budget, so a recipient that had already moved was asked a question whose only legal answer raised
    GATE2_MOVEMENT_BUDGET_EXCEEDED.  It is now left standing, and nobody is asked.
    """
    engine = _three([LAW], dc=PASS, foe_hp=1)
    ally = engine.state.actors[ALLY]
    ally.movement_remaining_ft = 0
    start = ally.position
    asked = _spy_reactions(engine)
    H._use(engine, STRIKE + "Bite", target=FOE)
    said = " ".join(str((event.payload or {}).get("rider") or "") for event in engine.events if event.event_type == "GM_RIDER")
    assert ally.position == start, "a creature with no movement left cannot step clear of the fall"
    assert not [row for row in asked if "axes_falling_tree_withdraw" in row[0]], \
        "the creature was asked to move when it had no movement to pay for"
    assert "has not the movement left" in said, f"and this is the reason the table is told: {said!r}"


def test_falling_tree_withdrawal_moves_a_creature_that_still_has_movement():
    """R1 #3. The budget filter must not cost the printed withdrawal: a creature with movement left still steps."""
    engine = _three([LAW], dc=PASS, foe_hp=1)
    ally = engine.state.actors[ALLY]
    start = ally.position
    H._use(engine, STRIKE + "Bite", target=FOE)
    assert ally.position != start, "a creature with movement left must still get its printed 5-foot withdrawal"
    assert ally.movement_remaining_ft < engine._effective_speed(ally), \
        "the withdrawal is paid out of the creature's own movement allowance"


def _box_in(ally_at, owner_at, foe_at):
    """The same duel on a small arena that walls the creature in on every side but the wielder's.

    "a space of its choice that is not closer to you" is a question about *which* square question is being
    asked, so a test about the answer needs an arena that can produce it.  Every square beside the creature
    that is not nearer to the wielder than where it stands is walled off, which leaves it open squares to
    step to and takes away every one of them -- no dice, budget or creature can produce that on the stock
    battlefield.
    """
    def apart(a, b):
        return max(abs(a.x - b.x), abs(a.y - b.y))  # the grid's own measure (combat/gate2_grid.distance_cells)

    walled = [{"x": x, "y": y} for x in range(12) for y in range(8)
              if max(abs(x - ally_at.x), abs(y - ally_at.y)) == 1
              and apart(Position(x=x, y=y), owner_at) >= apart(ally_at, owner_at)]
    battlefield = {"battlefield_id": "test:auto53.boxed", "width_squares": 12, "height_squares": 8,
                   "square_size_ft": 5, "starting_positions": {},
                   "terrain_regions": [{"terrain_type": "BLOCKED", "movement_cost": 0, "cells": walled}]}
    bundles = (compile_character(H._sheet(AXES, [HEWING, LAW], AXE_KIT, dc=PASS), actor_id=ME),
               compile_character(H._sheet(None, [], AXE_KIT), actor_id=ALLY),
               compile_character(H._sheet(None, [], AXE_KIT), actor_id=FOE))
    engine = Gate4ControllerEngine(H.ROOT, match_seed="AUTO53-BOXED", typed_bundles=bundles, battlefield=battlefield,
                                   roster_setup={"primary_actor_ids": [ME, ALLY, FOE],
                                                 "team_by_actor": {ME: "team:a", ALLY: "team:a", FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": owner_at.x, "y": owner_at.y},
                                                                        ALLY: {"x": ally_at.x, "y": ally_at.y},
                                                                        FOE: {"x": foe_at.x, "y": foe_at.y}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[FOE].armor_class = -50
    engine.state.actors[FOE].current_hp = 1  # one blow takes it down, which is the talent's printed trigger
    H._ready(engine)
    return engine


def test_falling_tree_withdrawal_names_the_space_it_refuses_rather_than_the_movement():
    """R2 #4. "a space of its choice that is not closer to you" -- when every space is nearer to the wielder,
    that is what the table has to be told.

    An earlier version reported "has not the movement left" for every empty menu, which is wrong here: this
    creature has its whole allowance and squares it could step to, and only the *direction* is ruled out.
    """
    engine = _box_in(Position(x=4, y=6), Position(x=2, y=6), Position(x=2, y=5))
    ally = engine.state.actors[ALLY]
    assert engine._effective_speed(ally) > 0 and ally.movement_remaining_ft > 0, "this test needs movement to spare"
    start = ally.position
    asked = _spy_reactions(engine)
    H._use(engine, STRIKE + "Bite", target=FOE)
    said = " ".join(str((event.payload or {}).get("rider") or "") for event in engine.events if event.event_type == "GM_RIDER")
    assert ally.position == start, "there is no space that is not nearer to the wielder"
    assert not [row for row in asked if "axes_falling_tree_withdraw" in row[0]], \
        "a creature with no legal square of its choice is not asked to choose one"
    assert "no space of its choice" in said and "not the movement left" not in said, \
        f"the table must be told about the space, not about movement it still has: {said!r}"


def test_falling_tree_withdrawal_tells_a_creature_with_no_movement_of_its_own_that_it_cannot_step():
    """R2 #4, the other misreport.  A creature whose speed is zero has not spent its movement: it never had
    any, so "has not the movement left" would be as wrong as the space claim.
    """
    engine = _three([LAW], dc=PASS, foe_hp=1)
    ally = engine.state.actors[ALLY]
    engine._apply_condition(ally, "condition:core.grappled", "test:grappled", FOE,
                            expires_on="UNTIL_REMOVED")  # a speed of zero
    assert engine._effective_speed(ally) == 0, "this test needs a creature that cannot move at all"
    start = ally.position
    asked = _spy_reactions(engine)
    H._use(engine, STRIKE + "Bite", target=FOE)
    said = " ".join(str((event.payload or {}).get("rider") or "") for event in engine.events if event.event_type == "GM_RIDER")
    assert ally.position == start
    assert not [row for row in asked if "axes_falling_tree_withdraw" in row[0]], \
        "a creature that cannot move at all is not asked to move"
    assert "cannot step clear of the fall" in said, f"the table has to hear the plain reason: {said!r}"
    assert "not the movement left" not in said


# ---------------------------------------------------------------------------------- #4 strict push failures
def test_falling_tree_push_lets_a_failed_movement_step_roll_the_payment_back():
    """R1 #4. A strict movement failure must unwind the owning transaction, not commit half a push.

    The push swallowed every CheckpointError and returned normally, so the owner's point stayed paid
    for a push that never happened.  CheckpointError is the shared "a paid checkpoint failed" signal
    (combat/ext/__init__.py) and must escape: ordinary collision and interruption are reported by the
    movement resolver itself, not raised.
    """
    from combat import ext
    from combat.ext import CheckpointError

    engine = _force(_three([LAW], dc=FAIL, foe_hp=1, foe_at=(4, 5), ally_at=(4, 6)),
                    axes_falling_tree_fall="push")
    paid = _resources(H._me(engine))

    def fail(*_args, **_kwargs):
        raise CheckpointError("the paid movement step failed")

    ext.hook("forced_movement_attempt")(fail)  # a documented plug-in point, not a patched engine class
    try:
        with pytest.raises(CheckpointError):
            H._use(engine, STRIKE + "Bite", target=FOE)
    finally:
        ext._HOOKS["forced_movement_attempt"].remove(fail)
        ext._HOOK_PRIORITIES.pop((("forced_movement_attempt"), fail), None)
    # the engine replaced its state wholesale when it unwound, so the fight is read back from the engine
    assert _resources(engine.state.actors[ME]) == paid, \
        "the owner's point must not stay paid for a push that failed"


# ---------------------------------------------------------------------------------- #5 independent marks
def test_two_axe_fighters_mark_the_same_creature_and_each_mark_keeps_its_own_first_time():
    """R1 #5. Each mark is its own "the first time", so one owner's spent mark cannot block another's fresh one.

    The owner loop stopped at the first mark whose trigger had already been seen, so with two axe
    fighters on the same creature an older spent mark silently denied a newly placed mark its first
    Reaction.
    """
    bundles = (compile_character(H._sheet(AXES, [HEWING, MARK], AXE_KIT, cl=10, dc=FAIL), actor_id=ME),
               compile_character(H._sheet(AXES, [HEWING, MARK], AXE_KIT, cl=10, dc=FAIL), actor_id=ALLY),
               compile_character(H._sheet(None, [], AXE_KIT), actor_id=FOE))
    engine = Gate4ControllerEngine(H.ROOT, match_seed="AUTO53R1", typed_bundles=bundles, roster_setup={
        "primary_actor_ids": [ME, ALLY, FOE], "team_by_actor": {ME: "team:a", ALLY: "team:a", FOE: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, ALLY: {"x": 5, "y": 6}, FOE: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[FOE].armor_class = -50
    engine.state.actors[FOE].current_hp = 1
    H._ready(engine)
    me, foe = H._me(engine), engine.state.actors[FOE]
    foe.maximum_hp, foe.current_hp = 40, 30
    ally = engine.state.actors[ALLY]

    # the ally's mark is older, and its one trigger has already been spent by an earlier recovery
    engine._apply_condition(foe, mark_condition_id("Execution Mark", ally.entity_id), MARK, ally.entity_id,
                            expires_on="UNTIL_REMOVED")
    engine._append_event("HEALING_APPLIED", "test:auto53.spent", actor_id=ALLY, target_ids=(FOE,),
                         payload={"offered": 5, "before": 25, "after": 30})
    engine._apply_condition(foe, mark_condition_id("Execution Mark", me.entity_id), MARK, me.entity_id,
                            expires_on="UNTIL_REMOVED")
    assert [condition.source_actor_id for condition in foe.conditions.values()
            if condition.condition_id.startswith("condition:typed.mark")], "both axe fighters marked the foe"

    before = len(engine.events)
    ally_ready = ally.reaction_available
    _heal_by(engine, ally, foe, 5)
    reacted = H._payloads(engine.events[before:], "REACTION_RESOLVED")
    assert reacted, "the freshly placed mark never got its first Reaction"
    assert [event.actor_id for event in engine.events[before:] if event.event_type == "REACTION_RESOLVED"] == [ME], \
        "only the fresh mark reacts: the ally's own one trigger was already spent"
    assert engine.state.actors[ALLY].reaction_available == ally_ready, \
        "the mark spent the ally's Reaction on a trigger it had already used"


# ---------------------------------------------------------------------------------- #6 a true fall to 0 HP
def test_falling_tree_needs_the_blow_that_actually_took_a_standing_creature_to_zero():
    """R1 #6. "reduce a creature to 0 HP" is a change of state, not any hit on something already at 0.

    The trigger read only the final Hit Points, so a packet that was entirely absorbed, or a creature
    already down in death saves, could shake the ground loose again without ever being reduced to 0.
    """
    # a packet entirely absorbed by Temporary Hit Points takes no Hit Points off at all
    engine = _three([LAW], dc=FAIL, foe_hp=20)
    engine.state.actors[FOE].temporary_hp = 500
    before = len(engine.events)
    H._use(engine, STRIKE + "Bite", target=FOE)
    assert engine.state.actors[FOE].current_hp > 0, "this test needs the foe to survive its wound"
    assert not _saves(engine.events[before:]), "a blow absorbed by Temporary Hit Points reduces nothing to 0"
    assert not _saves(engine.events[before:]), "an absorbed packet is not a fall"


def test_falling_tree_fires_on_the_blow_that_takes_a_standing_creature_to_zero():
    """R1 #6. The positive case must survive the stricter test: a standing creature put to 0 is still a fall."""
    engine = _three([LAW], dc=FAIL, foe_hp=1)
    before = len(engine.events)
    H._use(engine, STRIKE + "Bite", target=FOE)
    assert engine.state.actors[FOE].current_hp == 0, "this test needs the blow to be lethal"
    assert _saves(engine.events[before:]), "a creature reduced to 0 Hit Points is a fall"


def test_falling_tree_reads_a_creature_already_down_as_no_new_fall():
    """R1 #6. A living creature at 0 HP is in death saves; the engine settles that state right after this event.

    The packet for a further blow on it still ends at 0, so the final value alone cannot tell the two
    apart -- the settled life state does.
    """
    from combat.ext.axes_falling_tree import _reduced_to_zero

    engine = _three([LAW], dc=FAIL, foe_hp=20)
    foe = engine.state.actors[FOE]
    lethal = {"remaining_hp": 0, "hp_damage": 12, "reduced_to": 12, "rolled_or_pending_damage": 12,
              "temporary_hp_absorbed": 0, "damage_type": "slashing"}
    absorbed = {**lethal, "hp_damage": 0, "temporary_hp_absorbed": 12, "remaining_hp": 9}
    assert _reduced_to_zero(foe, lethal), "a standing creature put to 0 HP is a fall"
    assert not _reduced_to_zero(foe, absorbed), "a packet entirely absorbed reduces nothing to 0"
    foe.current_hp, foe.life_state = 0, "DYING"
    assert not _reduced_to_zero(foe, lethal), "a creature already down at 0 HP is not reduced to 0 again"
    foe.life_state = None
    foe.active = False
    assert not _reduced_to_zero(foe, lethal), "a defeated creature is not a fall"


# ---------------------------------------------------------------------------------- #7 player routing
def _mode(engine, **by_actor):
    """Record the table's own control modes on this engine, the way ``combat/gate5_service.py`` does.

    The Execution Mark asks whether its owner is a player from the *recorded control mode*
    (``engine.typed_control_modes``), not from whether a reaction provider is installed, so a routing test
    that means "this fighter is played by a person" has to say so here.
    """
    engine.typed_control_modes = dict(getattr(engine, "typed_control_modes", None) or {})
    engine.typed_control_modes.update(by_actor)
    return engine


def test_execution_mark_defers_for_a_player_owner_outside_an_action():
    """R2 #1. Checklist 9. A player-owned Reaction is asked for, never spent by the plug-in.

    A turn-boundary or zone recovery carries no action of the owner's to attach the question to, and
    the choice transport then answers for them.  The mark leaves their Reaction alone and says so.
    """
    engine = _duel([MARK], dc=FAIL)
    me, foe = _marked_foe(engine)
    _mode(engine, **{ME: "MANUAL"})
    asked = _spy_reactions(engine)
    assert getattr(engine, "_active_intent", None) is None, "this test needs a trigger with no action in flight"
    _heal(engine, foe, 5)
    _no_hook_failure(engine)
    assert not [row for row in asked if "axes_execution_mark" in row[0]], \
        "there is no checkpoint to ask at, so the question must not be silently answered"
    assert me.reaction_available, "a player's Reaction was spent on an answer they never gave"


def test_a_deferred_trigger_spends_the_marks_first_time_and_leaves_the_reaction_intact():
    """R2 #1, the deferral's own cost, pinned.  The triggering event is recorded whether it is answered or
    not, and "the first time" is read back from that record -- so a trigger that could not be put to the
    table is a lost opportunity, permanently, and the table must be told exactly that.  This is the
    lock-round limitation the lane discloses, not a defect to fix here; the test exists so the note the
    player reads cannot quietly start claiming otherwise.
    """
    engine = _duel([MARK], dc=FAIL)
    me, foe = _marked_foe(engine)
    _mode(engine, **{ME: "MANUAL"})
    asked = _spy_reactions(engine)
    assert getattr(engine, "_active_intent", None) is None, "this test needs the trigger with no action in flight"
    _heal(engine, foe, 5)
    _no_hook_failure(engine)
    notes = [str((event.payload or {}).get("log") or "") for event in engine.events
             if event.event_type == "PASSIVE_TRIGGERED" and (event.payload or {}).get("log")]
    assert any("first time is spent" in note and "Reaction itself is untouched" in note for note in notes), \
        f"the deferral has to say what it costs and what it does not: {notes}"
    assert me.reaction_available, "the owner's own Reaction was not spent on an answer nobody gave"

    # the recovery is on the record, so a later trigger is no longer this mark's first time
    before = len(engine.events)
    with _acting(engine):
        _heal(engine, foe, 5)
    _no_hook_failure(engine, since=before)
    assert not [row for row in asked if "axes_execution_mark" in row[0]], \
        "the mark's one time was already spent by the trigger that could not be asked about"
    assert me.reaction_available


def test_execution_mark_defers_for_an_ask_me_owner_even_with_nobody_answering():
    """R2 #1. The other half of the same finding: no provider does not make a player an AI.

    The old test read the *provider* to decide who owns the Reaction, so an owner whose control mode
    says a person plays them was spent automatically whenever no provider happened to be installed --
    which is exactly the silent-spending case.  The recorded control mode is the authority now.
    """
    engine = _duel([MARK], dc=FAIL)
    me, foe = _marked_foe(engine)
    _mode(engine, **{ME: "SUGGESTED"})
    assert getattr(engine, "_gate4_reaction_provider", None) is None, "this test needs no provider"
    _heal(engine, foe, 5)
    _no_hook_failure(engine)
    assert me.reaction_available, "a player-owned Reaction was spent with nobody at the table to ask"
    assert not H._payloads(engine.events, "REACTION_RESOLVED"), "the mark struck without its owner choosing to"


def test_execution_mark_lets_an_ai_owner_decide_with_a_provider_installed():
    """R2 #1. The other way round: a provider serves AI fighters too, so its presence is not ownership.

    ``combat/gate5_service.py`` installs one provider per preview and commit and routes each reactor
    by its own control mode, so an AI owner in a table fight has a provider installed while its own
    choice still has to be made by its controller.  Reading the provider suppressed the mark's first
    Reaction for every AI fighter in a real table.
    """
    engine = _duel([MARK], dc=FAIL)
    me, foe = _marked_foe(engine)
    _mode(engine, **{ME: "LOCAL_AUTO"})
    asked = _spy_reactions(engine)
    _heal(engine, foe, 5)
    _no_hook_failure(engine)
    assert H._payloads(engine.events, "REACTION_RESOLVED"), \
        "an AI owner decides for itself even while a provider is installed for the table"
    assert not me.reaction_available, "the automatic answer still pays the printed cost"
    assert not [row for row in asked if "axes_execution_mark" in row[0]], \
        "nobody answers an AI fighter's own choice; its controller does"


def test_execution_mark_still_answers_for_an_ai_owner_with_nobody_at_the_table():
    """R1 #7, kept. Checklist 9 the other way: an unattended fight still resolves."""
    engine = _duel([MARK], dc=FAIL)
    me, foe = _marked_foe(engine)
    assert getattr(engine, "_gate4_reaction_provider", None) is None, "nobody is answering this fight"
    _heal(engine, foe, 5)
    _no_hook_failure(engine)
    assert H._payloads(engine.events, "REACTION_RESOLVED"), "an unattended fight is decided automatically"
    assert not me.reaction_available, "the automatic answer still pays the printed cost"


def test_execution_mark_asks_the_table_during_a_players_turn_and_honours_a_decline():
    """R1 #7, repaired by R2 #2. Checklist 9 on both sides: the question reaches the table in flight, and
    a decline spends nothing.

    The old version answered the question with ``selection="USE"`` and ``option_ids=["DECLINE"]``,
    which ``combat/choice_checkpoints.validate`` rejects; the observational event wrapper swallowed the
    ValueError, so the assertions passed for the wrong reason.  The answer is a real decline here, the
    test puts that answer through the shipped validator itself (so restoring the malformed one fails the
    test instead of passing quietly), and it also fails if the plug-in's own hook raised anything.
    """
    engine = _duel([MARK], dc=FAIL)
    me, foe = _marked_foe(engine)
    _mode(engine, **{ME: "MANUAL"})
    answers: list = []
    asked = _spy_reactions(engine, answers=answers, axes_execution_mark="DECLINE")
    before = len(engine.events)
    with _acting(engine):
        _heal(engine, foe, 5)
    _no_hook_failure(engine, since=before)
    assert [row for row in asked if "axes_execution_mark" in row[0]], "the owner was never asked"
    assert answers, "the decline has to be an answer the transport accepted, not one it threw away"
    for spec, decision in answers:
        _accepted_by_the_transport(spec, decision)
    assert me.reaction_available, "a declined Reaction is not spent"
    assert not H._payloads(engine.events, "REACTION_RESOLVED"), "a declined mark does not strike"


def test_execution_mark_stays_spent_after_a_commit_and_reload_and_a_second_trigger():
    """R1 checklist 7. The "first time" has to survive a real table commit and reload, and still stop a later one.

    The mark itself is never removed, so the record lives in the event log; rebuilding the fight through
    the gate-3 reducer (what a reload does) and then *driving the rebuilt fight again* is the only way to
    show the record survived, rather than merely that a helper agrees with itself in memory.
    """
    from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events

    engine = _duel([MARK], dc=FAIL)
    me = H._me(engine)
    foe = H._foe(engine)
    _marked_foe(engine)
    before = len(engine.events)
    _heal(engine, foe, 5)
    assert H._payloads(engine.events[before:], "REACTION_RESOLVED"), "the first recovery did not fire"

    reloaded = Gate3EventReducer().apply_events(
        engine.state.model_copy(deep=True),
        enrich_committed_events(engine.events[before:], post_engine=engine),
        expected_start_sequence=int(engine.events[before - 1].sequence) + 1)
    assert any(condition.condition_id == EXECUTION for condition in reloaded.actors[AN].conditions.values()), \
        "the mark must survive the commit and reload"

    # drive the reloaded fight: the owner is owed nothing more from this mark
    engine.state = reloaded
    engine.events = list(engine.events)
    me = engine.state.actors[ME]
    me.reaction_available = True
    before = len(engine.events)
    _heal(engine, engine.state.actors[AN], 5)
    assert not H._payloads(engine.events[before:], "REACTION_RESOLVED"), \
        "a reloaded fight must still know its mark's one trigger was spent"
    assert me.reaction_available, "a reloaded fight must not spend a Reaction on a spent trigger"


def test_execution_mark_ends_at_the_start_of_its_owners_next_turn():
    """R1 checklist 7/8. "The mark lasts until the start of your next turn" is a real expiry, not a permanent condition.

    The mark is placed here the way rider lane 3 places it -- by the printed rider itself, through the
    ordinary Hewing Strike -- so the expiry under test is the typed one, not a test's own UNTIL_REMOVED.
    """
    engine = _duel([MARK], dc=FAIL, foe_hp=20)
    foe = H._foe(engine)
    H._use(engine, STRIKE + "Bite", target=AN)
    assert EXECUTION in _conds(foe), "the printed rider places the mark"
    turns = 0
    while turns < 4 and EXECUTION in _conds(engine.state.actors[AN]):
        engine.end_turn()
        turns += 1
    assert EXECUTION not in _conds(engine.state.actors[AN]), \
        "the mark must end at the start of its owner's next turn"
    assert "condition:typed.mark.bite." + ME not in _conds(engine.state.actors[AN]), \
        "the Bite it counts as ends with it"


# =============================== AUTO53r2f1 #3: a real table, a real commit, a real reload
#
# The reload tests above rebuild the fight through the gate-3 reducer, which is a copy of the live engine's own
# state.  These drive the fight the way a table does -- ``TabletopService.act`` into ``CombatService``, committed to
# ``tmp_path``, read back by a *second* ``CombatService`` -- so "the first trigger survives a reload" is a claim about
# saved fights and not about two objects agreeing inside one process.
ADAMANT = "TAL_GUARDIAN_ADAMANT_GUARDIAN_INCARNATION"
HEALING_TALISMAN = "tianxia.talent.talismans.healing_talisman"
MARK_CHOICE = "choice:needle.axes_execution_mark"
LEFT, RIGHT = "auto53_owner", "auto53_marked"
OWNER, MARKED = "actor:factory." + LEFT, "actor:factory." + RIGHT
#: The roll authority is deterministic, so the seed is part of the fixture: this one lands the Hewing Strike and leaves
#: the marked fighter at 7 of 14 Hit Points -- standing, but Bloodied, which is what the printed rider asks for.
TABLE_SEED = "AXES-2"


def _installed(tmp_path, project_id, mids, *, name, hp=None, ac=None):
    """A finished Factory character installed on this machine, the way the table's own characters are."""
    from tests.h1_support import sheet as factory_sheet

    doc = factory_sheet(mids, cl=10, dc=16, kit=AXE_KIT)
    doc["identity"]["display_name"] = name
    if hp is not None:
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = hp
    if ac is not None:
        doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = ac
    folder = tmp_path / "portable_characters" / project_id
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))


def _axes_table(tmp_path, *, owner_mode):
    """A persisted fight: an Axes owner next to the fighter it marks, and nobody else in the way.

    ``owner_mode`` is the control mode the match records for the mark's owner, which is what decides who answers
    its printed Reaction at the table.  The marked fighter owns a Healing Talisman so it can recover inside the
    mark's window, and the owner takes Adamant Guardian Incarnation first because the printed rider spends the
    owner's Reaction to place the mark (see the Inherited note in the lane report): the printed Reaction underneath
    it is only reachable for a fighter who has another one.
    """
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    _installed(tmp_path, LEFT, [HEWING, MARK, ADAMANT], name="Axe Owner")
    _installed(tmp_path, RIGHT, [HEALING_TALISMAN], name="Marked", hp=14, ac=5)
    combat = CombatService(H.ROOT, tmp_path)
    combat.tabletop_maps.save({"map_id": "auto53-yard", "display_name": "Axe Yard", "width_squares": 12,
                               "height_squares": 8, "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    mid = combat.create_factory_match(
        project_ids=[LEFT], opponent_actor_ids=[MARKED], control_modes={OWNER: owner_mode, MARKED: "MANUAL"},
        arena_id="battlefield:map.auto53-yard", match_seed=TABLE_SEED, maximum_rounds=8)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def _candidate(menu, needle, *, label=None, target=None):
    for group in menu["actions"]:
        if needle not in group["source_definition_id"]:
            continue
        for option in group["options"]:
            if label is not None and label not in (option.get("label") or ""):
                continue
            if target is not None and target not in option["target_ids"]:
                continue
            return option["candidate_id"]
    raise AssertionError(f"{needle!r} is not a choice on the table's menu")


def _play(table, mid, needle, *, label=None, target=None, answer="USE", auto=False):
    """One action at the table, answering every question it raises; returns the questions that reached the table.

    ``auto`` drives an AI fighter's own turn through the table's auto step with its controller pinned to the
    candidate under test, which is how a LOCAL_AUTO fighter's actions are committed.
    """
    state, prompts, answers = table.state(mid), [], []
    menu = state["menu"]
    original = table.combat.controller
    if auto:
        # an AI fighter's own turn is not offered at the table: its controller picks the action, so the candidate
        # under test comes from the engine and the controller is pinned to it
        from combat.gate4_adapters import ManualControllerAdapter

        engine = table.combat._load_session(mid).engine
        chosen = next(row for row in engine.legal_candidates()
                      if (row.kind.value == "END_TURN" if needle == "end" else needle in row.source_definition_id)
                      and (target is None or target in row.target_ids)
                      and (label is None or label in row.display_name))

        class PinnedController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(original, name)

        table.combat.controller = PinnedController()
    else:
        cid = menu["end_turn"] if needle == "end" else _candidate(menu, needle, label=label, target=target)
    try:
        for _ in range(20):
            if auto:
                result = table.auto_step(mid, state["last_sequence"], answers)
            else:
                result = table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
            if result["status"] != "REACTION_REQUIRED":
                assert result["status"] == "COMMITTED", result
                return prompts
            prompt = result["reaction"]
            prompts.append(prompt["context"]["reaction_source_id"])
            reply = {**prompt["context"], "selection": answer}
            if prompt.get("choice") and answer == "USE":
                reply["option_ids"] = [prompt["choice"]["options"][0]["id"]]
            answers.append(reply)
        raise AssertionError(f"{needle!r} was asked again and again without committing")
    finally:
        table.combat.controller = original


def _advance(table, mid, actor):
    """End turns until ``actor``'s is the one on the table (an AI fighter ends its own through an auto step)."""
    from combat.tabletop_service import MANUAL_MODES

    for _ in range(12):
        state = table.state(mid)
        if state["menu"].get("actor_id") == actor:
            return
        _play(table, mid, "end", auto=state["menu"]["control_mode"] not in MANUAL_MODES)
    raise AssertionError(f"{actor} never came to the table")


def _mark_then_reload(tmp_path, *, owner_mode, first_trigger):
    """The printed sequence at a real table, then a fresh service reads the fight back, then the second trigger.

    Returns ``(questions_raised_by_the_first_trigger, questions_raised_by_the_second, reloaded_session)``.
    """
    from combat.gate5_service import CombatService
    from combat.tabletop_service import MANUAL_MODES

    combat, table, mid = _axes_table(tmp_path, owner_mode=owner_mode)
    auto = owner_mode not in MANUAL_MODES
    _advance(table, mid, OWNER)
    _play(table, mid, "ADAMANT_GUARDIAN_INCARNATION", auto=auto)
    _play(table, mid, "HEWING", label="Bite", target=MARKED, auto=auto)

    placed = combat._load_session(mid).engine
    marked = placed.state.actors[MARKED]
    assert mark_condition_id("Execution Mark", OWNER) in _conds(marked), \
        "the printed rider has to place the mark through an ordinary Hewing Strike"
    assert marked.current_hp * 2 <= marked.maximum_hp, "the printed trigger is a hit on a Bloodied creature"
    assert not placed.state.actors[OWNER].reaction_available, \
        "the mark's placement is the owner's printed Reaction, spent by the rider itself"

    _advance(table, mid, MARKED)
    first = _play(table, mid, "healing_talisman", target=MARKED, answer="DECLINE") if first_trigger else []
    # the fight is committed; a second service reads the saved fight off disk, as a reopened table does
    reloaded = CombatService(H.ROOT, tmp_path)._load_session(mid)
    assert reloaded.mechanical.replay()["status"] == "PASS", "the committed fight must replay"
    assert mark_condition_id("Execution Mark", OWNER) in _conds(reloaded.engine.state.actors[MARKED]), \
        "the mark has to outlive the reload"
    second = _play(table, mid, "system:combat.disengage", answer="DECLINE")
    return first, second, reloaded


def test_a_reloaded_table_remembers_that_the_marks_first_trigger_was_spent(tmp_path):
    """R2 #3. Checklist 7 at the real table: the "first time" survives a commit and a reload, and stops the next one.

    The mark is never removed, so what has to survive is the record that the owner already spent the mark's one
    Reaction on the marked fighter's recovery.  The check is a question that does *not* reach the table after the
    reload, on a fight the second service read back from ``tmp_path``.
    """
    first, second, reloaded = _mark_then_reload(tmp_path, owner_mode="MANUAL", first_trigger=True)
    assert MARK_CHOICE in first, "a player's own Reaction is asked for, not spent for them"
    healed = reloaded.engine.state.actors[MARKED]
    assert healed.current_hp == healed.maximum_hp, \
        "the owner declined, so the marked fighter healed back to full and the mark's swing bought nothing"
    assert MARK_CHOICE not in second, "the mark's first time is over: a reloaded table must not ask again"


def test_a_reloaded_table_still_asks_when_the_marks_trigger_is_unspent(tmp_path):
    """R2 #3, the other half: the same fight, reloaded the same way, with the trigger still unspent.

    Without this the test above would also pass if the second trigger were silent for some unrelated reason -- an
    owner with no Reaction left, a window that had closed.  Here the identical fixture does ask.
    """
    first, second, _reloaded = _mark_then_reload(tmp_path, owner_mode="MANUAL", first_trigger=False)
    assert not first, "no recovery happened, so nothing could have been asked"
    assert MARK_CHOICE in second, "an unspent mark still asks its owner, reload or not"


def test_an_ai_owners_mark_is_resolved_by_its_own_controller_at_the_table(tmp_path):
    """R2 #1 at the real table.  ``gate5_service`` installs a reaction provider per preview and commit and routes
    each reactor by its own control mode, so an AI owner in a table fight has a provider installed while its choice
    is still its own.  Reading the provider would have suppressed the mark for every AI fighter in a real table.
    """
    first, second, reloaded = _mark_then_reload(tmp_path, owner_mode="LOCAL_AUTO", first_trigger=True)
    assert not first, "nobody at the table answers an AI fighter's own Reaction"
    assert [event for event in reloaded.engine.events
            if event.event_type == "REACTION_WINDOW_OPENED" and event.source_definition_id == MARK], \
        "the AI owner's Reaction window is still resolved; its controller decides"
    assert MARK_CHOICE not in second, "the AI owner's one trigger is spent too"
