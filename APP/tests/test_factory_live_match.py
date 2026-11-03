"""A finished Factory character fights a saved live match through the combat service (owner 2026-09-24)."""

import json
import zipfile
from pathlib import Path

from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService

from tests.test_factory_combat_compiler import SHEET

ROOT = Path(__file__).resolve().parents[1]


def _install(userdata: Path, project_id: str) -> None:
    folder = userdata / "portable_characters" / project_id
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(SHEET))


def test_factory_character_fights_and_resumes_a_saved_match(tmp_path):
    _install(tmp_path, "test-project")
    service = CombatService(ROOT, tmp_path)
    assert [row["display_name"] for row in service.factory_characters()] == ["Test Cultivator"]
    view = service.create_factory_match(project_ids=["test-project"], match_seed="FACTORY-LIVE-TEST")
    match_id = view["match_id"]
    actor_id = FACTORY_ACTOR_PREFIX + "test-project"
    assert any(actor["entity_id"] == actor_id for actor in view["state"]["actors"])
    assert view["metadata"]["participant_control_modes"][actor_id] == "LOCAL_AUTO"
    # The Dao policy drives the Factory fighter, not the generic fallback.
    assert service._dao_policy_for_actor(actor_id)["policy_id"] == f"policy:dao.{actor_id}"
    for _ in range(400):
        result = service.local_step(match_id)
        state = (result.get("match") or result).get("state") or service.get_match(match_id)["state"]
        if state.get("terminal_result"):
            break
    final = CombatService(ROOT, tmp_path).get_match(match_id)  # a fresh service resumes from disk
    assert final["state"]["terminal_result"] is not None
    events = {event["event_type"] for event in final["recent_events"]}
    assert events  # the fight left an event trail


def test_two_factory_characters_fight_each_other(tmp_path):
    _install(tmp_path, "left")
    _install(tmp_path, "right")
    service = CombatService(ROOT, tmp_path)
    left, right = FACTORY_ACTOR_PREFIX + "left", FACTORY_ACTOR_PREFIX + "right"
    view = service.create_factory_match(project_ids=["left"], opponent_actor_ids=[right], match_seed="FACTORY-DUEL-TEST")
    actors = {actor["entity_id"]: actor for actor in view["state"]["actors"]}
    assert set(actors) >= {left, right}
    assert actors[left]["team_id"] != actors[right]["team_id"]
    assert actors[left]["position"] != actors[right]["position"]
    match_id = view["match_id"]
    for _ in range(400):
        result = service.local_step(match_id)
        state = (result.get("match") or result).get("state") or service.get_match(match_id)["state"]
        if state.get("terminal_result"):
            break
    assert CombatService(ROOT, tmp_path).get_match(match_id)["state"]["terminal_result"] is not None


def test_factory_fights_default_to_the_sect_trial_platform(tmp_path):
    from combat.gate2_runtime_models import Position
    from combat.gate5_service import DEFAULT_FACTORY_ARENA

    _install(tmp_path, "left")
    _install(tmp_path, "right")
    service = CombatService(ROOT, tmp_path)
    view = service.create_factory_match(project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"], match_seed="FACTORY-ARENA-TEST")
    match_id = view["match_id"]
    assert view["metadata"]["battlefield_id"] == DEFAULT_FACTORY_ARENA
    # A resumed fight rebuilds the same arena from the copy saved with the match.
    engine = CombatService(ROOT, tmp_path)._load_session(match_id).engine
    arena = service.factory_arenas()[DEFAULT_FACTORY_ARENA]
    pillars = {(c["x"], c["y"]) for region in arena["terrain_regions"] if region["terrain_type"] == "BLOCKED" for c in region["cells"]}
    assert pillars and engine.grid.blocked == pillars
    # Pillars break line of sight.
    assert not engine.grid.line_of_sight(Position(x=1, y=3), Position(x=4, y=3))
    presentation = service.presentation(match_id)
    drawn = json.dumps(presentation)
    assert "Sect Trial Platform" in drawn and "Opponents" in drawn
    assert {(c["x"], c["y"]) for c in presentation["battlefield"]["blocked_cells"]} == pillars


def test_a_calm_dao_fighter_in_reach_attacks_instead_of_pacing_or_guarding(tmp_path):
    """Tournament 2026-09-24: Dao Dodge/Disengage priorities and in-band moves outscored every attack."""
    from combat.gate2_runtime_models import CandidateKind, Position
    from combat.gate4_context import build_decision_context
    from combat.gate4_controller import LocalDeterministicController, _option_sets
    from combat.gate4_models import LocalControllerPolicy

    _install(tmp_path, "left")
    _install(tmp_path, "right")
    service = CombatService(ROOT, tmp_path)
    view = service.create_factory_match(project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"], match_seed="FACTORY-CALM")
    engine = service._load_session(view["match_id"]).engine
    actor = engine.state.actors[engine.state.current_actor_id]
    foe = next(a for a in engine.state.actors.values() if a.entity_id != actor.entity_id)
    foe.position = Position(x=actor.position.x + 1, y=actor.position.y)
    policy = dict(service._dao_policy_for_actor(actor.entity_id))
    policy["action_priorities"] = {"system:combat.dodge": 7, "system:combat.disengage": 7}  # the strongest Dao guard preference
    context = build_decision_context(engine, LocalControllerPolicy.model_validate(policy))
    controller = LocalDeterministicController()
    scores = {(c.kind, c.display_name): controller._score_candidate(context, c, opts).total
              for c in context.legal_candidates for opts in _option_sets(c)}
    best_strike = max(total for (kind, name), total in scores.items() if kind == CandidateKind.ACTION and "attack" in name.lower())
    assert best_strike > scores[(CandidateKind.ACTION, "Dodge")]
    assert best_strike > scores[(CandidateKind.ACTION, "Disengage")]
    assert best_strike > max(total for (kind, _), total in scores.items() if kind == CandidateKind.MOVE)


def _scored(tmp_path, seed, arrange, guard=7):
    from combat.gate4_context import build_decision_context
    from combat.gate4_controller import LocalDeterministicController, _option_sets
    from combat.gate4_models import LocalControllerPolicy

    _install(tmp_path, "left")
    _install(tmp_path, "right")
    service = CombatService(ROOT, tmp_path)
    view = service.create_factory_match(project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"], match_seed=seed)
    engine = service._load_session(view["match_id"]).engine
    actor = engine.state.actors[engine.state.current_actor_id]
    foe = next(a for a in engine.state.actors.values() if a.entity_id != actor.entity_id)
    arrange(actor, foe)
    policy = dict(service._dao_policy_for_actor(actor.entity_id))
    policy["action_priorities"] = {"system:combat.dodge": guard, "system:combat.disengage": guard}
    context = build_decision_context(engine, LocalControllerPolicy.model_validate(policy))
    controller = LocalDeterministicController()
    return actor, [(c, controller._score_candidate(context, c, opts).total) for c in context.legal_candidates for opts in _option_sets(c)]


def test_a_wounded_dao_fighter_that_is_winning_presses_instead_of_dodging(tmp_path):
    """Tournament 2026-09-24: 41 of 95 fights hit the round limit with both sides dodging in the stress posture."""
    from combat.gate2_runtime_models import CandidateKind, Position

    def arrange(actor, foe):
        foe.position = Position(x=actor.position.x + 1, y=actor.position.y)
        actor.current_hp = actor.maximum_hp * 30 // 100  # stressed (I Ching change at 40%)
        foe.current_hp = foe.maximum_hp * 10 // 100      # but the foe is worse off

    def best(scored, pick):
        return max(total for c, total in scored if c.kind == CandidateKind.ACTION and pick(c.display_name))

    # An overwhelming Dao guard preference, as a Kan-heavy character's stress posture can have.
    _, scored = _scored(tmp_path / "winning", "FACTORY-PRESS", arrange, guard=30)
    assert best(scored, lambda n: "attack" in n.lower()) > best(scored, lambda n: n == "Dodge")

    def losing(actor, foe):
        foe.position = Position(x=actor.position.x + 1, y=actor.position.y)
        actor.current_hp = actor.maximum_hp * 30 // 100
        foe.current_hp = foe.maximum_hp  # the foe is fresh: the Dao's retreat or guard still wins

    _, scored = _scored(tmp_path / "losing", "FACTORY-GUARD", losing, guard=30)
    assert best(scored, lambda n: n == "Dodge") > best(scored, lambda n: "attack" in n.lower())


def test_a_dao_fighter_with_nothing_in_reach_closes_the_distance(tmp_path):
    from combat.gate2_runtime_models import CandidateKind, Position

    def arrange(actor, foe):
        foe.position = Position(x=actor.position.x + 3, y=actor.position.y)  # 15 ft: inside most Dao bands
        actor.action_available = False                                        # nothing can strike this step

    actor, scored = _scored(tmp_path, "FACTORY-CLOSE", arrange)
    moves = [(c, total) for c, total in scored if c.kind == CandidateKind.MOVE]
    best = max(moves, key=lambda row: row[1])[0]
    assert max(abs(best.destination.x - actor.position.x), abs(best.destination.y - actor.position.y)) >= 1
    closest = min(max(abs(c.destination.x - (actor.position.x + 3)), abs(c.destination.y - actor.position.y)) for c, _ in moves)
    assert max(abs(best.destination.x - (actor.position.x + 3)), abs(best.destination.y - actor.position.y)) == closest


def test_a_lone_low_hp_fighter_that_can_strike_does_not_dodge_for_survival(tmp_path):
    """Step 12 (owner 2026-09-26): losing fighters Dodged dozens of times (Du Daoyuan x68) into the round limit.
    Alone on its side and able to strike, low HP no longer adds a survival bonus to Dodge; with an ally still
    fighting it does."""
    from combat.gate2_runtime_models import CandidateKind, Position
    from combat.gate4_context import build_decision_context
    from combat.gate4_controller import LocalDeterministicController, _option_sets
    from combat.gate4_models import LocalControllerPolicy

    def survival(project_ids, folder):
        for pid in (*project_ids, "right"):
            _install(folder, pid)
        service = CombatService(ROOT, folder)
        view = service.create_factory_match(project_ids=list(project_ids), opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"],
                                            match_seed="FACTORY-LOW-HP")
        engine = service._load_session(view["match_id"]).engine
        actor = engine.state.actors[engine.state.current_actor_id]
        foe = next(a for a in engine.state.actors.values() if a.team_id != actor.team_id)
        foe.position = Position(x=actor.position.x + 1, y=actor.position.y)
        actor.current_hp = actor.maximum_hp * 15 // 100
        policy = dict(service._dao_policy_for_actor(actor.entity_id))
        policy["action_priorities"] = {}
        context = build_decision_context(engine, LocalControllerPolicy.model_validate(policy))
        controller = LocalDeterministicController()
        dodge = next(c for c in context.legal_candidates if c.kind == CandidateKind.ACTION and c.display_name == "Dodge")
        assert any(c.kind == CandidateKind.ACTION and "attack" in c.display_name.lower() for c in context.legal_candidates)
        score = controller._score_candidate(context, dodge, next(iter(_option_sets(dodge))))
        return next(row.value for row in score.components if row.component == "survival")

    assert survival(["left"], tmp_path / "alone") == 0
    assert survival(["left", "ally"], tmp_path / "with-ally") > 0
