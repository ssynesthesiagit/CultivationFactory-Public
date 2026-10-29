"""The published rider hint reaches real AI choices, and the fight continues.

WHAT THIS PROVES
    The rider hint is not metadata that only a unit call can see. A real Factory
    character is compiled by the shipped compiler, the shipped controller is asked to
    choose, and for one fixture the action it picks is the action the hint promoted:
    the same sheet compiled with only the publication step replaced by the identity
    leaves that ability tied with its printed siblings, and the controller takes a
    different one. That is the paired trace for the decision, in both the duel the
    choice is measured in and a real saved AI-vs-AI fight.

    The promoted ability is then really executed, its printed rider really lands, and
    the fight is dropped and reopened through the service before it carries on, so the
    decision and its consequence survive a table commit.

    A resource refill earns nothing at any pool level: a full pool recovers nothing,
    and this hint is compiled without the caster's remaining supply, so the AI must
    not prefer the refill to a useful alternative. Both a full and a depleted pool are
    checked, and the AI's choice must be the same in both.

    A save whose failure grapples and whose success shoves is one action with two
    exclusive outcomes. Both are worth their weighted value, so the controller sees
    2 condition points plus 2 movement points; the failure branch must not cancel the
    success branch.

WHAT THIS DOES NOT CLAIM
    Nothing about how the fight ends, and nothing about abilities whose riders are not
    in the supported set. Only the listed candidates' ranking, the listed decisions,
    and one real continuation.
"""
from __future__ import annotations

import pytest

from combat import factory_compiler as compiler
from combat.gate3_reducer import canonical_state_sha256
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet, script

ME = "actor:factory.pro16f2"
FOE = "an_eui_early_book1_cl5"

#: A printed "Deliver the Dose" whose poison also leaves a Dose Mark (Bitter Trace).
#: The two candidates are the same attack with the same average damage, so only the
#: published hint separates them.
POISON_MIDS = ["tianxia.talent.poison.bitter_trace"]
#: A printed "Regain Martial Focus" action: a refill whose pool the compiler cannot read.
REFILL_MIDS = ["TAL_BEASTMASTERY_FOCUSING_CONNECTION"]
#: A Sand wielder. "Scouring Hand" is one printed action with three printed options and
#: the same average damage each: deny Opportunity Attacks, reduce the target's Speed by
#: 10 feet, and impose Perception disadvantage. Only the Speed option's printed rider is
#: a supported consequence, so only that option earns a published hint, and the hint is
#: what puts it first.
SAND_MIDS = ["TAL_SAND_GLASS_PRISON"]
SPEED_HAND = "SCOURING_HAND#opt1"
#: The three printed control actions every fighter owns, in the order they are listed here.
LINE = ("unarmed.grapple", "unarmed.shove_prone", "unarmed.shove_push")


def _bundle(mids, *, hints: bool = True, cl: int = 12):
    """Compile a real Factory character, with or without the published hint.

    ``hints=False`` runs the same compiler with only the publication step replaced by
    the identity, which is exactly the pre-publisher behaviour, so the two runs differ
    in nothing else."""
    if hints:
        return compiler.compile_character(sheet(mids, cl=cl), actor_id=ME)
    saved = compiler._with_rider_utility
    compiler._with_rider_utility = lambda row: row
    try:
        return compiler.compile_character(sheet(mids, cl=cl), actor_id=ME)
    finally:
        compiler._with_rider_utility = saved


def _hints(mids, *, cl: int = 12) -> dict:
    return {row["source_definition_id"]: (row.get("parameters") or {}).get("rider_utility")
            for row in _bundle(mids, hints=False, cl=cl)["action_catalog"]}


def _duel(bundle, *, seed: str = "PRO16F2-DUEL"):
    """The compiled character beside the stock sparring foe, on its own turn.

    Its movement is spent, so the decision is between abilities rather than a step
    toward the enemy, and the foe's armour is low enough that any attack roll lands."""
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, FOE],
                                                 "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6},
                                                                        FOE: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    mine = engine.state.actors[ME]
    mine.action_available = mine.bonus_action_available = mine.reaction_available = True
    mine.movement_remaining_ft = 0
    engine.state.actors[FOE].armor_class = 2
    return engine


def _decide(engine):
    """Ask the shipped controller to choose, and return its choice and context."""
    policy, _ = PolicyLibrary(ROOT).for_actor(ME)
    context = build_decision_context(engine, policy, for_ai=True)
    choice = LocalDeterministicController().choose_primary_action(context)
    picked = next(row for row in context.legal_candidates
                  if row.candidate_id == choice.intent.candidate_id)
    return choice, context, picked


def _scores(context):
    """The controller's own total and rider component for every legal candidate."""
    controller = LocalDeterministicController()
    table = {}
    for row in context.legal_candidates:
        score = controller._score_candidate(context, row, ())
        table[row.source_definition_id] = (round(score.total, 3),
                                           {part.component: part.value for part in score.components})
    return table


def _row(context, needle):
    return next(row for row in context.legal_candidates if needle in row.source_definition_id)


def test_the_published_hint_is_the_ability_the_controller_takes_and_it_lands():
    """Review finding 2: the hint has to be what makes the choice, not a bystander.

    "Scouring Hand" is one action with three printed options and the same average
    damage each. The Speed option's printed rider is a 10-foot speed reduction, the one
    consequence in the supported set, so it is the only option the estimator publishes;
    with the hint it outscores its siblings and the controller takes it, and without the
    hint all three are worth the same and the controller takes one of the others. Then
    the ability it really took is really run, and the speed reduction it was promoted
    for is really on the creature it struck."""
    _choice, context, picked = _decide(_duel(_bundle(SAND_MIDS)))
    _quiet_choice, quiet, quiet_picked = _decide(_duel(_bundle(SAND_MIDS, hints=False)))
    options = {row.source_definition_id: row for row in context.legal_candidates if "SCOURING_HAND#opt" in row.source_definition_id}
    assert len(options) == 3, f"the fixture needs the three printed options, got {sorted(options)}"
    assert SPEED_HAND in picked.source_definition_id, (
        f"the published hint must be what the controller takes; it took {picked.source_definition_id}")
    assert picked.metadata.get("rider_utility") == 1
    assert SPEED_HAND not in quiet_picked.source_definition_id, (
        f"without the published hint the three options are worth the same, so the choice is the "
        f"engine's own; it took {quiet_picked.source_definition_id}")
    assert [quiet_picked.metadata.get("rider_utility")] == [None]
    published_scores, quiet_scores = _scores(context), _scores(quiet)
    ranked = sorted(options, key=lambda source: -published_scores[source][0])
    assert ranked[0] == picked.source_definition_id
    assert len({quiet_scores[source][0] for source in options}) == 1, (
        "the paired ranking: with the hint one option leads, without it all three tie")
    assert published_scores[picked.source_definition_id][0] - max(
        quiet_scores[source][0] for source in options) == 10, (
        "the generic policy weighs a published rider point as immediate effect")

    engine = _duel(_bundle(SAND_MIDS))
    choice, _context, again = _decide(engine)
    assert again.source_definition_id == picked.source_definition_id
    script(engine, [1, 1])  # the target fails the save, so the printed rider is imposed
    before = len(engine.events)
    engine.execute_intent(choice.intent)
    written = [row.event_type for row in engine.events[before:]]
    assert "INTENT_ACCEPTED" in written and "SAVE_ROLLED" in written
    assert any(row.event_type == "DAMAGE_COMMITTED" for row in engine.events[before:])
    imposed = [row for row in engine.state.actors[FOE].modifiers.values()
               if row.target_field == "speed_ft" and row.value == -10]
    assert imposed, (
        "the promoted ability's printed rider, a 10-foot speed reduction on the creature it "
        f"struck, must really be on that creature; its modifiers were "
        f"{list(engine.state.actors[FOE].modifiers)}")
    assert imposed[0].expires_on == "START_OF_SOURCE_NEXT_TURN", (
        "and it must expire at the start of the target's next turn, as printed")


def test_the_published_hint_reorders_the_real_abilities_the_ai_chooses_between():
    """Real characters, real candidates, the controller's own ordering and its choice.

    Unarmed Grapple, Shove: Prone and Shove: Push are three printed control actions.
    The published hint is what puts the grapple first and the prone shove second;
    compiled without the hint all three are worth the same, so their order is the
    engine's own. The state is one where a stocked control action outranks all three
    either way, and the controller takes it either way: the hint reorders real
    abilities, and this state is not where it changes what the AI does. The decision it
    does change is above."""
    def line(table):
        return {name: table[next(item for item in table if name in item)] for name in LINE}

    _choice, context, picked = _decide(_duel(_bundle(REFILL_MIDS)))
    quiet_choice, quiet, quiet_picked = _decide(_duel(_bundle(REFILL_MIDS, hints=False)))
    hinted = {row.source_definition_id: row.metadata.get("rider_utility") for row in context.legal_candidates}
    unvalued = {row.source_definition_id: row.metadata.get("rider_utility") for row in quiet.legal_candidates}
    with_hints, without = line(hinted), line(unvalued)
    assert [with_hints[name] for name in LINE] == [2, 1, None]
    assert [without[name] for name in LINE] == [None, None, None]
    scores, quiet_scores = _scores(context), _scores(quiet)
    assert [scores[next(k for k in scores if name in k)][0] for name in LINE] == [36.0, 26.0, 16.0]
    assert [quiet_scores[next(k for k in quiet_scores if name in k)][0] for name in LINE] == [16.0, 16.0, 16.0], (
        "without the published hint the three control actions are worth the same, so their order "
        "is the engine's own and not this publisher's")
    assert picked.source_definition_id == quiet_picked.source_definition_id, (
        "this state's choice is made by something else; the pairing above is a ranking claim only")
    assert max(scores.values(), key=lambda item: item[0])[0] > 36.0


def test_only_the_published_hints_differ_between_the_two_compilations():
    """The paired trace for every decision above, byte for byte.

    The two catalogs are the same compiled character; the only difference anywhere is
    the integer the estimator published on some actions. The pre-existing reliable
    replacement value is in both, because it is not this publisher's to set."""
    with_hints = {row["source_definition_id"]: row for row in _bundle(POISON_MIDS)["action_catalog"]}
    without = {row["source_definition_id"]: row for row in _bundle(POISON_MIDS, hints=False)["action_catalog"]}
    assert set(with_hints) == set(without)
    published = []
    for source, row in with_hints.items():
        mine, other = dict(row["parameters"]), dict(without[source]["parameters"])
        mine_hint, other_hint = mine.pop("rider_utility", None), other.pop("rider_utility", None)
        assert mine == other, f"{source} differs in more than its published hint"
        assert {key: value for key, value in row.items() if key != "parameters"} == \
               {key: value for key, value in without[source].items() if key != "parameters"}
        if mine_hint != other_hint:
            published.append((source, mine_hint))
    assert published, "the fixture must publish at least one hint"
    for source, hint in published:
        assert isinstance(hint, int) and hint > 0, f"{source} published {hint!r}"


def test_the_reliable_replacement_floor_survives_its_own_execution():
    """Bitter Trace guarantees its mark; ordinary Deliver the Dose still needs a failed save."""
    engine = _duel(_bundle(POISON_MIDS))
    engine.state.actors[FOE].saving_throws['CON'] = 100
    choice, context, picked = _decide(engine)
    scores = _scores(context)
    top = max(scores.items(), key=lambda item: item[1][0])
    assert picked.source_definition_id == top[0], "the controller must take what it scores highest"
    # The printed Bitter Trace replacement gives up the additional saving-throw
    # effect in exchange for an automatic Dose Mark on a hit.
    action = engine.action_catalog[picked.source_definition_id]
    reliable = action.parameters['typed']['replacement']['reliable']
    assert len(reliable) == 1
    assert reliable[0]['type'] == 'mark' and reliable[0]['mark'] == 'Dose Mark'
    assert reliable[0]['source_modifier'] == POISON_MIDS[0]
    assert top[1][1]['rider_utility'] > 0
    assert "DELIVER_THE_DOSE" in picked.source_definition_id
    before = len(engine.events)
    engine.execute_intent(choice.intent)
    written = [row.event_type for row in engine.events[before:]]
    assert "INTENT_ACCEPTED" in written and "ATTACK_ROLLED" in written
    assert any(row.event_type == "DAMAGE_COMMITTED" for row in engine.events[before:])
    saves = [row for row in engine.events[before:] if row.event_type == 'SAVE_ROLLED' and row.actor_id == FOE]
    assert not saves
    marks = [row.condition_id for row in engine.state.actors[FOE].conditions.values()]
    assert any("dose_mark" in name for name in marks), (
        f"the chosen ability's printed rider, a Dose Mark on the creature it struck, must really be "
        f"on that creature; its conditions were {marks}")

    # Keep the ordinary failed-save regression and add its successful-save
    # counterpart. Owning Bitter Trace does not force it onto the base action.
    for success in (False, True):
        base = _duel(_bundle(POISON_MIDS))
        base.state.actors[FOE].saving_throws['CON'] = 100 if success else -100
        _, base_context, _ = _decide(base)
        candidate = next(row for row in base_context.legal_candidates
                         if row.source_definition_id.endswith('POISON_BASE_DELIVER_THE_DOSE'))
        typed = base.action_catalog[candidate.source_definition_id].parameters['typed']
        assert not (typed.get('replacement') or {}).get('reliable')
        intent = LocalDeterministicController().choose_primary_action(
            base_context.model_copy(update={'legal_candidates': (candidate,)})).intent
        before = len(base.events)
        base.execute_intent(intent)
        saves = [row for row in base.events[before:] if row.event_type == 'SAVE_ROLLED' and row.actor_id == FOE]
        assert len(saves) == 1 and saves[0].payload['success'] == success
        marked = any('dose_mark' in row.condition_id for row in base.state.actors[FOE].conditions.values())
        assert marked == (not success)


def test_a_newly_published_hint_drives_a_saved_fight_through_a_commit_and_a_reopen(tmp_path):
    """Continuation at the service: the fight is really saved, dropped and reopened.

    The Sand wielder really takes the ability this publisher promoted, and that ability's
    hint is one the pre-publisher compilation does not carry, so the decision this fight
    made is one the published hint made."""
    combat = CombatService(ROOT, tmp_path)
    left, right = ME, "actor:factory.pro16f2-foe"
    bundles = [compiler.compile_character(sheet(SAND_MIDS, cl=12), actor_id=left),
               compiler.compile_character(sheet([], cl=12), actor_id=right)]
    match = combat._finish_factory_match(
        bundles, [left, right], {left: "team:a", right: "team:b"},
        {left: {"x": 3, "y": 6}, right: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [left], [right],
        control_modes={left: "LOCAL_AUTO", right: "LOCAL_AUTO"},
        match_seed="PRO16F2-CONTINUATION", display_name="PRO16f2 continuation",
        maximum_rounds=3)["match_id"]

    def play(root, steps, *, stop_after_promoted=False):
        session = CombatService(ROOT, root)._load_session(match)
        controller, policies = LocalDeterministicController(), PolicyLibrary(ROOT)
        taken = []
        for _ in range(steps):
            if session.engine.state.terminal_result is not None:
                break
            policy, _p = policies.for_actor(session.engine.state.current_actor_id)
            choice = controller.choose_primary_action(build_decision_context(session.engine, policy, for_ai=True))
            row = next(item for item in session.engine.legal_candidates()
                       if item.candidate_id == choice.intent.candidate_id)
            taken.append((row.source_definition_id, row.metadata.get("rider_utility")))
            session.execute_controller_choice(choice, controller=controller, policy_library=policies)
            if stop_after_promoted and SPEED_HAND in row.source_definition_id and row.metadata.get("rider_utility"):
                break
        return session, taken

    # Cut after the promoted ability's real commit, not after an assumed
    # number of menu choices. An AI that no longer paces can finish this
    # three-round fixture before choice 16; that would test reopening a
    # completed fight, rather than the continuation this test promises.
    session, taken = play(tmp_path, 16, stop_after_promoted=True)
    assert session.engine.state.terminal_result is None, "the continuation cut must be inside the fight"
    assert taken, "the saved fight must actually reach AI decisions"
    promoted = [(source, hint) for source, hint in taken
                if SPEED_HAND in source and hint]
    assert promoted, (
        f"the ability this publisher promoted must be one the AI really takes in a saved fight; "
        f"it took {taken}")
    unvalued = _hints(SAND_MIDS)
    fresh = [(source, hint) for source, hint in taken
             if hint and unvalued.get(source) != hint]
    assert fresh, (
        f"a real AI decision in a saved fight must carry a value this publisher produced; it "
        f"took {taken}, and the pre-publisher compilation of the same sheet published {unvalued}")
    assert canonical_state_sha256(session.engine.state) == canonical_state_sha256(
        CombatService(ROOT, tmp_path)._load_session(match).engine.state)

    reopened = CombatService(ROOT, tmp_path)._load_session(match)
    assert reopened.verify()["status"] == reopened.mechanical.replay()["status"] == "PASS"
    session, more = play(tmp_path, 16)
    assert more, "the reopened fight must go on making decisions"
    assert len(session.engine.events) > len(reopened.engine.events)
    assert CombatService(ROOT, tmp_path)._load_session(match).verify()["status"] == "PASS"


@pytest.mark.parametrize("supply", [1, 0], ids=["full-pool", "depleted-pool"])
def test_a_refill_earns_no_credit_at_any_pool_level_and_is_not_chosen(supply):
    """Review finding 1, at the level the bug showed: which ability the AI takes.

    Focusing Connection prints "Regain Martial Focus." A full pool recovers nothing,
    and the compiler cannot read the caster's supply, so the refill earns no hint at
    either level and never takes the fighter's action; the AI's choice is the same in
    both states and the same as the pre-publisher choice."""
    engine = _duel(_bundle(REFILL_MIDS))
    engine.state.actors[ME].resources["resource:core.martial_focus"] = supply
    _choice, context, picked = _decide(engine)
    refill = _row(context, "FOCUSING_CONNECTION")
    scores = _scores(context)
    assert "rider_utility" not in refill.metadata
    assert "rider_utility" not in scores[refill.source_definition_id][1]
    assert picked.source_definition_id != refill.source_definition_id, (
        "a refill that recovers nothing must not take the fighter's action")
    unvalued = _decide(_duel(_bundle(REFILL_MIDS, hints=False)))[2]
    empty = _duel(_bundle(REFILL_MIDS))
    empty.state.actors[ME].resources["resource:core.martial_focus"] = 0
    assert picked.source_definition_id == unvalued.source_definition_id
    assert picked.source_definition_id == _decide(empty)[2].source_definition_id


def test_both_branches_of_one_save_reach_the_controller():
    """Review finding 2, at the controller: one action, two exclusive outcomes.

    The save grapples on failure and shoves on success. Each outcome is worth its own
    weighted value, 2 condition points plus 2 movement points, so the controller reads
    four points; the grappled branch must not delete the shoved one."""
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    from combat.factory_compiler import _with_rider_utility
    effects = [{"type": "save", "ability": "CON", "applies_to": "target", "on_fail": [
        {"type": "condition", "condition": "grappled", "applies_to": "target"}],
        "on_success": [{"type": "forced_movement", "distance_ft": 20, "applies_to": "target"}]}]
    action = ActionDefinition(source_definition_id="action:test.pro16f2_grapple_or_shove",
                               display_name="Grapple or Shove", owner_id=ME,
                               economy=EconomyKind.ACTION, resolution_kind="TYPED",
                               target_kind="HOSTILE_ENTITY", range_ft=5,
                               parameters={"typed": {"effects": effects,
                                                     "numbers": {"pb": 4, "cl": 12, "key_mod": 3}},
                                           "expected_damage": 0})
    published = _with_rider_utility(action)
    assert published.parameters["rider_utility"] == 4, (
        "one grappled outcome and one shoved outcome, each halved, are four points")

    engine = _duel(_bundle(POISON_MIDS))
    engine.action_catalog[published.source_definition_id] = published
    engine.state.actors[ME].action_ids = (*engine.state.actors[ME].action_ids,
                                          published.source_definition_id)
    _, context, _picked = _decide(engine)
    row = next(item for item in context.legal_candidates
               if item.source_definition_id == published.source_definition_id)
    assert row.metadata["rider_utility"] == 4
    components = _scores(context)[published.source_definition_id][1]
    assert components["rider_utility"] == 4 * 10, "the generic policy weights the rider as immediate effect"
    assert components["defeat_prevention_or_finish"] == 0
