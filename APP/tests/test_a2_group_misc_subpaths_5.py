"""A2 group misc-subpaths 5 (Spirit Awakening): the printed weapon-proficiency gates and the Bearing
back-and-forth rule that the table previously left to the GM.

Printed owner rules enforced here (source of truth: authority/typed_mechanics/rules_text.json):
  * Enter the Black Current -- "Flow After the Strike ... an unarmed strike, or a weapon attack with a weapon you
    are proficient with". A compiled weapon row that the owner is NOT proficient with no longer qualifies.
  * Three-Bearing Footwork -- "a Martial Strike needs a weapon you are proficient with" and "Moving back and forth
    between the same spaces does not complete a Bearing unless it advanced a meaningful hostile objective".

The bare fixture sheets carry no weapon training, so their improvised weapon (and the test staff) compile with
``proficient=False``; the unarmed strike is the qualifying Martial Strike on those sheets. Table-level tests run on
the real Gate 4 engine through execute_intent; the Bearing progress test also commits through persistence and
cold-reloads to prove the tracked bearing data is engine state, not test-local.
"""

import pytest

from combat.gate2_runtime_models import ActionIntent
from tests.test_riders_c8 import (
    ROOT, ME, FOE, MIND_SPIKE, bundle, fight, held, payloads, turn, use,
)

BC = "tianxia.tradition.spirit.black_current_walker.feature."
CB = "tianxia.tradition.spirit.compass_breaking_hand.feature."
TOKEN = {k: f"resource:named.bearing_{k}" for k in ("approach", "orbit", "depart")}


# --------------------------------------------------------------- Flow After the Strike: weapon you are proficient with
def test_flow_proficiency_gate_through_table_commit_and_cold_reload(tmp_path):
    from combat.ext.hand_occupancy import weapon_allowed, weapon_requirement
    from combat.gate4_persistence import Gate4Persistence
    from tests.test_riders_c8 import STAFF, answers, fixed_d20

    persistence = Gate4Persistence(ROOT, tmp_path)

    def staff_session(training, seed):
        session = persistence.create_match(match_seed=seed,
            typed_bundles=(bundle([BC + "enter_the_black_current"], items=[STAFF], weapon_training=training),),
            roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                          "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})

        def commit(candidate):
            session.mechanical.execute_intent(ActionIntent(intent_id=f"a2gm5-flow-{len(session.engine.events)}",
                decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                state_version=candidate.state_version, actor_id=candidate.actor_id,
                target_ids=candidate.target_ids, destination=candidate.destination))

        while session.engine.state.current_actor_id != ME:
            commit(next(c for c in session.engine.legal_candidates() if c.display_name == "End turn"))

        # Ready the staff with ordinary committed equipment actions, if needed.
        action = next(a for a in session.engine.action_catalog.values()
                      if a.owner_id == ME and a.display_name == "Gun (Staff) attack")
        for _ in range(12):
            if weapon_allowed(session.engine, session.engine.state.actors[ME], action) is not False:
                break
            identity, _ = weapon_requirement(session.engine, action)
            grips = [(c, row.parameters["equipment_grip"]) for c in session.engine.legal_candidates()
                     if (row := session.engine.action_catalog.get(c.source_definition_id)) is not None
                     and row.parameters.get("equipment_grip")]
            candidate = next((c for c, grip in grips if grip["weapon"] == identity and grip["held"]), None)
            candidate = candidate or next((c for c, grip in grips if grip["weapon"] != identity and not grip["held"]), None)
            assert candidate is not None
            commit(candidate)
        else:
            raise AssertionError("staff was not readied through committed equipment actions")

        assert action.parameters["typed"].get("proficient") is training
        return session, commit

    accepts_a_legal_step = lambda options: (next((option for option in options if option != "cell:3,6"), options[0]),)
    denied, commit = staff_session(False, "A2GMISSUB5-FLOW-UNTRAINED")
    offered = answers(denied.engine, {"flow_after_the_strike": accepts_a_legal_step})
    fixed_d20(denied.engine, 20)
    attack = next(c for c in denied.engine.legal_candidates()
                  if c.display_name == "Gun (Staff) attack" and FOE in (c.target_ids or ()))
    commit(attack)
    assert not any("flow_after_the_strike" in r["reaction_source_id"] for r in offered), \
        "an accepting player provider must not receive Flow after a non-proficient attack"
    denied = persistence.load_match(denied.match_id)
    assert not denied.engine.state.actors[ME].turn_flags.get("flow_after_the_strike")
    assert denied.verify()["status"] == "PASS"
    assert denied.mechanical.replay()["status"] == "PASS"

    trained, commit = staff_session(True, "A2GMISSUB5-FLOW-TRAINED")
    answers(trained.engine, {"flow_after_the_strike": accepts_a_legal_step})
    fixed_d20(trained.engine, 20)
    attack = next(c for c in trained.engine.legal_candidates()
                  if c.display_name == "Gun (Staff) attack" and FOE in (c.target_ids or ()))
    commit(attack)
    trained = persistence.load_match(trained.match_id)
    assert trained.engine.state.actors[ME].turn_flags.get("flow_after_the_strike"), \
        "a proficient compiled weapon attack offers Flow and commits its accepted movement"
    assert trained.verify()["status"] == "PASS"
    assert trained.mechanical.replay()["status"] == "PASS"


# --------------------------------------------------------------------- Compass Strike: Martial Strike needs proficiency
def test_compass_strike_expression_does_not_ride_a_non_proficient_weapon():
    from tests.test_riders_c8 import STAFF
    engine = fight([CB + "three_bearing_footwork", CB + "no_fixed_compass"], foe_at=(8, 6), items=[STAFF])
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Choose Pole", FOE)
    turn(engine, ME)  # the start of your turn: the AI declares Approach (the Pole is out of reach)
    use(engine, "Move to 7,6")  # completes the Approach bearing -> the expression rides the next Martial Strike
    assert me.turn_flags.get("compass_strike_pending") == "approach"
    foe.armor_class = -50
    # The staff is non-proficient: only its own strike damage lands, Enter the Line does not ride it.
    events = use(engine, "Gun (Staff) attack", FOE)
    assert len(payloads(events, "DAMAGE_COMMITTED")) == 1
    assert not held(foe, "condition:typed.no_opportunity_attacks", ME)


# ------------------------------------------------------------------------ Bearing back-and-forth does not complete
def test_productive_orbit_survives_table_commit_cold_reload_and_replay(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    typed = (bundle([CB + "three_bearing_footwork", CB + "no_fixed_compass"]),)
    roster = {"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
              "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 7}}}

    def create(seed):
        return persistence.create_match(match_seed=seed, typed_bundles=typed, roster_setup=roster)

    def act(session, name, *, target=None):
        engine = session.engine
        candidate = next(c for c in engine.legal_candidates()
                         if c.display_name == name and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"a2gm5-{name}-{len(engine.events)}",
            decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=ME,
            target_ids=(target,) if target else (candidate.target_ids or ()), destination=candidate.destination))

    def end_turn(session):
        engine = session.engine
        candidate = next(c for c in engine.legal_candidates() if c.display_name == "End turn")
        session.mechanical.execute_intent(ActionIntent(intent_id=f"a2gm5-end-{len(engine.events)}",
            decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids))

    def fresh_bearing(seed):
        session = create(seed)
        while session.engine.state.current_actor_id != ME:
            end_turn(session)
        act(session, "Choose Pole", target=FOE)
        # Return to the next turn so the engine declares Orbit relative to the Pole.
        for _ in range(4):
            end_turn(session)
            if session.engine.state.current_actor_id == ME:
                break
        assert session.engine.state.current_actor_id == ME
        [bearing] = held(session.engine.state.actors[ME], "condition:typed.compass_bearing", ME)
        assert bearing.data["kind"] == "orbit"
        return session

    # An unproductive out-and-back cannot complete Orbit, including after a cold load.
    session = fresh_bearing("A2GMISSUB5-ORBIT-EMPTY")
    act(session, "Move to 4,6")
    act(session, "Move to 3,6")
    session = persistence.load_match(session.match_id)
    [bearing] = held(session.engine.state.actors[ME], "condition:typed.compass_bearing", ME)
    assert session.engine.state.actors[ME].resources[TOKEN["orbit"]] == 0
    assert session.verify()["status"] == "PASS"

    # In a fresh Orbit, a Martial Strike damages the hostile Pole between the
    # outward and return steps; this meaningful objective progress permits the exception.
    from tests.test_riders_c8 import fixed_d20
    session = fresh_bearing("A2GMISSUB5-ORBIT-PRODUCTIVE")
    act(session, "Move to 4,6")
    fixed_d20(session.engine, 20)
    act(session, "Unarmed Strike", target=FOE)
    act(session, "Move to 3,6")
    session = persistence.load_match(session.match_id)
    [bearing] = held(session.engine.state.actors[ME], "condition:typed.compass_bearing", ME)
    assert bearing.data["kind"] == "orbit"
    assert bearing.data.get("objective_advanced") == 1
    assert session.engine.state.actors[ME].resources[TOKEN["orbit"]] == 1, "productive return token survives reload"
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"

    # The printed objective exception also allows progress after returning
    # home: movement already satisfied Orbit's route, so the later strike
    # must reevaluate completion without counting any feet again.
    session = fresh_bearing("A2GMISSUB5-ORBIT-RETURN-STRIKE")
    act(session, "Move to 4,6")
    act(session, "Move to 3,6")
    [bearing] = held(session.engine.state.actors[ME], "condition:typed.compass_bearing", ME)
    assert session.engine.state.actors[ME].resources[TOKEN["orbit"]] == 0
    assert not bearing.data.get("done")
    fixed_d20(session.engine, 20)
    act(session, "Unarmed Strike", target=FOE)
    session = persistence.load_match(session.match_id)
    [bearing] = held(session.engine.state.actors[ME], "condition:typed.compass_bearing", ME)
    assert bearing.data.get("objective_advanced") == 1
    assert bearing.data.get("done") == 1
    assert session.engine.state.actors[ME].resources[TOKEN["orbit"]] == 1, \
        "a qualifying strike after a valid return completes Orbit and persists its token"
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("sequence,productive,lethal", [
    (("out", "strike", "back"), True, False),
    (("out", "back", "strike"), True, False),
    (("out", "back"), False, False),
    (("out", "strike", "back"), True, True),
    (("out", "back", "strike"), True, True),
])
def test_chosen_orbit_hostile_progress_is_independent_of_personal_footwork_and_pole(
        tmp_path, sequence, productive, lethal):
    """An ordinary ally completes its aura owner's Chosen Orbit through committed session intents."""
    import copy
    from combat.ext.compass_breaking_hand import CHOSEN, CHOSEN_ORBIT, HEAVEN
    from combat.gate5_service import CombatService
    from tests.test_riders_c8 import ALLY, answers, fixed_d20

    from combat.factory_compiler import compile_character
    from tests.test_riders_c8 import TYPED_FOE, authority, sheet

    hostile = TYPED_FOE if lethal else FOE
    bundles = [bundle([HEAVEN]), bundle([], actor_id=ALLY, cl=5, pb=3)]
    if lethal:
        # Supported character creation, persisted in the initial typed bundle:
        # a one-HP opponent guarantees this strike is a finishing blow.
        opponent_sheet = sheet([], cl=5, pb=3)
        opponent_sheet["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1
        bundles.append(compile_character(opponent_sheet, actor_id=hostile, typed_authority=authority()))
    primary = [ME, ALLY, hostile] + ([FOE] if lethal else [])
    teams = {ME: "team:a", ALLY: "team:a", hostile: "team:b"}
    positions = {ME: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 7}, hostile: {"x": 4, "y": 8}}
    if lethal:
        teams[FOE] = "team:b"
        positions[FOE] = {"x": 12, "y": 12}
    combat = CombatService(ROOT, tmp_path)
    arena = copy.deepcopy(combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"])
    arena["terrain_regions"] = []
    match_id = combat._finish_factory_match(
        bundles, primary, teams, positions,
        arena, [b["actor_id"] for b in bundles], [hostile] + ([FOE] if lethal else []),
        control_modes={aid: "MANUAL" for aid in primary},
        match_seed=f"A2GMISSUB5-CHOSEN-{'-'.join(sequence)}-{lethal}",
        display_name="A2GMISSUB5 Chosen Orbit regression", maximum_rounds=8)["match_id"]
    session = combat._load_session(match_id)
    engine = session.engine

    def commit(actor_id, name, target=None):
        candidate = next(c for c in engine.legal_candidates()
                         if c.display_name == name
                         and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"a2gm5-chosen-{name}-{len(engine.events)}",
            decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=actor_id,
            target_ids=(target,) if target else (candidate.target_ids or ()),
            destination=candidate.destination))

    def end_current_turn():
        commit(engine.state.current_actor_id, "End turn")

    # The aura owner's explicit action establishes the field. The ally then
    # chooses Orbit through the normal choice provider; it has no Footwork and
    # never chooses or receives a personal Pole.
    for _ in range(4):
        if engine.state.current_actor_id == ME:
            break
        end_current_turn()
    else:
        raise AssertionError("aura owner did not receive a turn")
    commit(ME, "Heaven Has No Fixed North")
    answers(engine, {"compass.chosen": ("orbit",)})
    end_current_turn()
    for _ in range(3):
        if engine.state.current_actor_id == ALLY:
            break
        end_current_turn()
    else:
        raise AssertionError("Chosen Bearing ally did not receive a turn")
    assert engine.state.current_actor_id == ALLY
    [chosen] = held(engine.state.actors[ALLY], CHOSEN, ME)
    assert chosen.data["kind"] == "orbit"
    assert not held(engine.state.actors[ALLY], "condition:typed.compass_bearing")
    assert not held(engine.state.actors[ALLY], "condition:typed.compass_pole")

    fixed_d20(engine, 20)
    for step_name in sequence:
        if step_name == "out":
            commit(ALLY, "Move to 3,9")
        elif step_name == "back":
            commit(ALLY, "Move to 3,7")
        else:
            commit(ALLY, "Unarmed Strike", hostile)
            if lethal:
                assert engine.state.actors[hostile].current_hp == 0
                assert not engine.state.actors[hostile].active
                assert engine.state.actors[FOE].active
                assert engine.state.terminal_result is None
                [bearing] = held(engine.state.actors[ALLY], CHOSEN, ME)
                assert bearing.data.get("objective_advanced") == 1

    session = CombatService(ROOT, tmp_path)._load_session(match_id)
    ally = session.engine.state.actors[ALLY]
    if lethal:
        assert session.engine.state.actors[hostile].current_hp == 0
        assert not session.engine.state.actors[hostile].active
        assert session.engine.state.actors[FOE].active
        assert session.engine.state.terminal_result is None
    if productive:
        assert held(ally, CHOSEN_ORBIT, ME), "productive Orbit benefit must persist after cold reload"
        [bearing] = held(ally, CHOSEN, ME)
        assert bearing.data.get("objective_advanced") == 1
        assert bearing.data.get("done") == 1
    else:
        assert not held(ally, CHOSEN_ORBIT, ME), "movement without hostile progress cannot complete Chosen Orbit"
        [bearing] = held(ally, CHOSEN, ME)
        assert not bearing.data.get("objective_advanced")
        assert not bearing.data.get("done")
    assert not held(ally, "condition:typed.compass_bearing")
    assert not held(ally, "condition:typed.compass_pole")
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("kind", ["depart", "approach"])
def test_completed_chosen_bearing_awards_once_after_later_hits(tmp_path, kind):
    """Later damage packets cannot regrant movement or refill consumed Temporary HP."""
    import copy
    from combat.ext.compass_breaking_hand import CHOSEN, HEAVEN
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from tests.test_riders_c8 import ALLY, TYPED_FOE, answers, authority, fixed_d20, sheet

    extra_attack = "tianxia.path.body_refining.feature.extra_attack"
    ally_sheet = sheet([extra_attack], cl=11, pb=4)
    ally_sheet["identity"]["path"] = "Body Refining"
    foe_sheet = sheet([], cl=5, pb=3)
    # A strong, healthy opponent consumes the four awarded Temporary HP with
    # an ordinary evented opportunity attack and survives the ally's later hits.
    foe_sheet["ability_scores_and_statistics"]["abilities"][0].update(score=30, modifier=10)
    combat = CombatService(ROOT, tmp_path)
    arena = copy.deepcopy(combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"])
    arena["terrain_regions"] = []
    start = (3, 7) if kind == "depart" else (2, 10)
    foe_at = (4, 9) if kind == "depart" else (3, 8)
    primary = [ME, ALLY, TYPED_FOE]
    match_id = combat._finish_factory_match(
        [bundle([HEAVEN], cl=5, pb=2),
         compile_character(ally_sheet, actor_id=ALLY, typed_authority=authority()),
         compile_character(foe_sheet, actor_id=TYPED_FOE, typed_authority=authority())],
        primary, {ME: "team:a", ALLY: "team:a", TYPED_FOE: "team:b"},
        {ME: {"x": 3, "y": 6}, ALLY: {"x": start[0], "y": start[1]},
         TYPED_FOE: {"x": foe_at[0], "y": foe_at[1]}},
        arena, primary, [TYPED_FOE], control_modes={aid: "MANUAL" for aid in primary},
        match_seed=f"A2GMISSUB5-REPEAT-{kind}", display_name="Chosen Bearing once per turn",
        maximum_rounds=8)["match_id"]
    session = combat._load_session(match_id)
    engine = session.engine

    def commit(name, target=None):
        candidate = next(c for c in engine.legal_candidates() if c.display_name == name
                         and (target is None or target in (c.target_ids or ())))
        before = len(engine.events)
        session.mechanical.execute_intent(ActionIntent(
            intent_id=f"a2gm5-repeat-{len(engine.events)}", decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))
        return engine.events[before:]

    for _ in range(4):
        if engine.state.current_actor_id == ME:
            break
        commit("End turn")
    assert engine.state.current_actor_id == ME
    commit("Heaven Has No Fixed North")
    answers(engine, {"compass.chosen": (kind,)})
    commit("End turn")
    for _ in range(4):
        if engine.state.current_actor_id == ALLY:
            break
        commit("End turn")
    assert engine.state.current_actor_id == ALLY
    ally = engine.state.actors[ALLY]
    [bearing] = held(ally, CHOSEN, ME)
    assert bearing.data["kind"] == kind
    fixed_d20(engine, 20)
    commit("Move to 3,9" if kind == "depart" else "Move to 2,8")
    [bearing] = held(ally, CHOSEN, ME)
    assert bearing.data.get("done") == 1
    if kind == "approach":
        assert ally.temporary_hp == 4
        hp_before = ally.current_hp
        damage_events = commit("Move to 2,6")
        assert payloads(damage_events, "DAMAGE_COMMITTED"), "leaving reach must consume HP through an evented attack"
        assert ally.temporary_hp == 0
        assert ally.current_hp < hp_before
        commit("Move to 2,7")
    movement_before = ally.movement_remaining_ft
    strike_events = commit("Unarmed Strike", TYPED_FOE)
    assert len(payloads(strike_events, "DAMAGE_COMMITTED")) >= 2, "exercise repeated hit callbacks"
    assert ally.movement_remaining_ft == movement_before
    assert ally.temporary_hp == 0

    grants = [e for e in engine.events
              if e.event_type == ("MOVEMENT_GRANTED" if kind == "depart" else "TEMP_HP_GRANTED")
              and (e.actor_id == ALLY if kind == "depart" else ALLY in e.target_ids)
              and e.source_definition_id == HEAVEN]
    assert len(grants) == 1, "a completed Chosen Bearing awards its benefit only once"
    if kind == "depart":
        assert grants[0].payload["distance_ft"] == 10
    session = CombatService(ROOT, tmp_path)._load_session(match_id)
    cold_ally = session.engine.state.actors[ALLY]
    [bearing] = held(cold_ally, CHOSEN, ME)
    assert bearing.data.get("done") == 1
    assert cold_ally.temporary_hp == 0
    assert cold_ally.movement_remaining_ft == movement_before
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
