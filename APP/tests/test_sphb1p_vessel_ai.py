"""Native Puppetry setup through automatic decisions, commits and cold reloads."""
import json
import zipfile

from combat.ext import placed, vessel
from combat.factory_compiler import compile_character
from combat.gate4_context import build_decision_context, build_reaction_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

LEFT, RIGHT = "actor:factory.sphai-left", "actor:factory.sphai-right"


def fight(root, mode="LOCAL_AUTO"):
    documents = [sheet([vessel.SPHERE.replace("sphere", "talent") + ".joint_catching_needle",
                        "tianxia.talent.puppetry.knot_the_knee"], cl=15),
                 sheet([], cl=15, primary="Stamina", kit={"starting_kit": {
                     "items": [{"item_id": "tianxia.mortal.weapon.dao"}]}})]
    for aid, doc, label in zip((LEFT, RIGHT), documents, ("SPHB1AI Sphere", "SPHB1AI Sparring")):
        doc["identity"]["display_name"] = label
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 180
        folder = root / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    svc = CombatService(ROOT, root)
    mid = svc._finish_factory_match(
        [compile_character(d, actor_id=a) for a, d in zip((LEFT, RIGHT), documents)],
        [LEFT, RIGHT], {LEFT: "team:a", RIGHT: "team:b"},
        {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}},
        svc.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [LEFT], [RIGHT],
        control_modes={LEFT: mode, RIGHT: "LOCAL_AUTO" if mode == "LOCAL_AUTO" else "MANUAL"}, match_seed="SPHB1AI-PUPPETRY-1",
        display_name="Puppetry AI regression", maximum_rounds=6)["match_id"]
    return svc, mid


def test_ai_raises_then_strikes_in_seeded_fight_after_cold_reload(tmp_path):
    svc, mid = fight(tmp_path)
    controller, policies = LocalDeterministicController(), PolicyLibrary(ROOT)
    session = svc._load_session(mid)
    assert not placed.of(session.engine, "vessel")
    raises, strikes = 0, 0
    for _ in range(300):
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        engine = session.engine
        if engine.state.terminal_result:
            break
        policy, _ = policies.for_actor(engine.state.current_actor_id)
        context = build_decision_context(engine, policy, for_ai=True)
        if engine.state.current_actor_id == LEFT and not raises:
            assert any(c.source_definition_id.endswith("vessel.raise") for c in context.legal_candidates)
        choice = controller.choose_primary_action(context)
        candidate = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
        raising = candidate.actor_id == LEFT and candidate.source_definition_id.endswith("vessel.raise")
        striking = candidate.actor_id == LEFT and vessel.STRIKE_BASE in candidate.source_definition_id
        if striking:
            assert raises and candidate.source_definition_id.endswith(".vessel")
            origin = candidate.metadata["effect_origin"]
            zone = engine.state.zones[origin["id"].removeprefix("vessel:")]
            assert zone in vessel.threaded_vessels(engine, engine.state.actors[LEFT], vessel.kit(engine, engine.state.actors[LEFT]))
        qi = engine.state.actors[LEFT].resources["resource:core.qi"]

        def react(request):
            policy, _ = policies.for_actor(request["reactor_id"])
            selected = controller.choose_reaction(build_reaction_context(engine, policy, request))
            if request["reaction_source_id"] == "choice:needle.vessel_raise_move":
                assert selected.decision.selection == "DECLINE"
            return selected.decision, selected.record.model_dump(mode="json")

        session.submit_intent(choice.intent, primary_decision_record=choice.record, reaction_provider=react)
        if raising:
            raises += 1
            after = CombatService(ROOT, tmp_path)._load_session(mid).engine
            owner = after.state.actors[LEFT]
            assert owner.resources["resource:core.qi"] == qi - 1
            assert not owner.action_available
            assert placed.of(after, "vessel")[0].center == candidate.destination
            assert not any(c.source_definition_id.endswith("vessel.raise") for c in
                           build_decision_context(after, policies.for_actor(LEFT)[0], for_ai=True).legal_candidates)
        strikes += int(striking)
    else:
        raise AssertionError("300-decision ceiling")
    assert raises == 1 and strikes > 0
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


def test_human_raise_keeps_optional_movement_and_repeat_raise(tmp_path):
    svc, mid = fight(tmp_path, "MANUAL")
    table = TabletopService(svc, tmp_path)
    from tests.auto28_puppetry_support import resolve
    while svc._load_session(mid).engine.state.current_actor_id != LEFT:
        from tests.hunt15_support import act
        resolve(lambda answers: act(table, mid, "end", answers))
    from combat.placement_menu import CHOICE
    from tests.worker2_support import settle
    root = next(c for c in svc._legal_candidates(svc._load_session(mid))
                if c.display_name.startswith('Raise the Vessel (1 CP)'))
    prompts = settle(table, mid, root.candidate_id,
                     picks={CHOICE: 'cell:4,7,0', 'choice:needle.vessel_raise_move': ['cell:5,7']})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.vessel_raise_move" for p in prompts)
    after = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert placed.of(after, "vessel")[0].center.model_dump()["x"] == 5
    from tests.hunt15_support import act
    resolve(lambda answers: act(table, mid, "end", answers))
    while svc._load_session(mid).engine.state.current_actor_id != LEFT:
        resolve(lambda answers: act(table, mid, "end", answers))
    assert any(g["label"] == "Raise the Vessel (1 CP)" for g in table.state(mid)["menu"]["actions"])


def test_raise_preference_does_not_follow_hidden_live_position(tmp_path):
    from combat import target_knowledge
    from combat.gate2_runtime_models import Position
    from tests.auto28_puppetry_support import resolve
    from tests.hunt15_support import act

    svc, mid = fight(tmp_path, "MANUAL")
    table = TabletopService(svc, tmp_path)
    while svc._load_session(mid).engine.state.current_actor_id != LEFT:
        resolve(lambda answers: act(table, mid, "end", answers))
    engine = svc._load_session(mid).engine
    owner, enemy = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    engine._apply_condition(enemy, "condition:typed.invisible", "test:concealed", RIGHT,
                            expires_on="UNTIL_REMOVED", data={})
    remembered = Position(x=4, y=6)
    engine.state.observations[owner.team_id] = {RIGHT: remembered}
    policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)

    def destination():
        context = build_decision_context(engine, policy, for_ai=True)
        rows = [c for c in context.legal_candidates if c.source_definition_id.endswith("vessel.raise")]
        assert len(rows) == 1
        return rows[0].destination

    enemy.position = Position(x=10, y=10)
    assert target_knowledge.knowledge(engine, owner, enemy).mode == "LAST_OBSERVED"
    before = destination()
    enemy.position = Position(x=11, y=10)
    assert destination() == before
    enemy.position = before.model_copy()
    assert destination() == before
    engine.state.observations.clear()
    assert target_knowledge.knowledge(engine, owner, enemy) is None
    before = destination()
    enemy.position = Position(x=10, y=10)
    assert destination() == before
    enemy.position = before.model_copy()
    assert destination() == before
