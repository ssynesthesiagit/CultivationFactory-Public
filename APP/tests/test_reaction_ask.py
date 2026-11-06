"""Ask me reactions (owner 2026-09-26, step 16): "a mode where we have manual reactions, when a reaction can happen it
stops and hands priority over to the player who then hits something to keep going if they dont use the reaction".

A character whose reaction plan is Ask me, played by a person, gets asked (Use or Pass) at each reaction moment:
combat/typed_reactions.py _consent goes through the engine's reaction decision (combat/gate4_engine.py), the
service's preview pauses with COMBAT_REACTION_DECISION_REQUIRED, and the tabletop turns that into a prompt and
sends the same action again with the answers. Nothing is committed until every prompt is answered.
"""

import json
import zipfile
from pathlib import Path

from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.test_factory_live_match import SHEET

ROOT = Path(__file__).resolve().parents[1]
MOVER = "0f6a2d9e-1b3c-4d5e-8f70-112233445566"
GUARD = "7c1e4b2a-9d8f-4e6a-b5c4-665544332211"


def _install(userdata: Path, project_id: str) -> None:
    folder = userdata / "portable_characters" / project_id
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(SHEET))


def _fight(tmp_path: Path) -> tuple[CombatService, TabletopService, str]:
    for pid in (MOVER, GUARD):
        _install(tmp_path, pid)
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(GUARD, {"mode": "ask"}, {"opportunity_attack"})
    service = CombatService(ROOT, tmp_path)
    modes = {FACTORY_ACTOR_PREFIX + MOVER: "MANUAL", FACTORY_ACTOR_PREFIX + GUARD: "MANUAL"}
    view = service.create_factory_match(project_ids=[MOVER], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + GUARD],
                                        control_modes=modes, match_seed="ASK-ME-OA")
    return service, TabletopService(service, tmp_path), view["match_id"]


def _cells(position: dict) -> tuple[int, int]:
    return int(position["x"]), int(position["y"])


def _gap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def test_the_fight_asks_before_an_ask_me_opportunity_attack_and_uses_the_answer(tmp_path):
    service, table, match_id = _fight(tmp_path)
    mover_id, guard_id = FACTORY_ACTOR_PREFIX + MOVER, FACTORY_ACTOR_PREFIX + GUARD
    assert service._load_session(match_id).engine.typed_ask_reactors == frozenset({guard_id})  # the mover is on Auto

    def menu():
        context = service.decision(match_id)["context"]
        engine = service._load_session(match_id).engine
        where = {actor_id: (actor.position.x, actor.position.y) for actor_id, actor in engine.state.actors.items()}
        return context, where

    def send(candidate, reactions=()):
        context = service.decision(match_id)["context"]
        return table.act(match_id, candidate["candidate_id"], context["decision_id"], context["state_version"], 0, list(reactions))

    prompt = None
    for _ in range(40):
        context, where = menu()
        actor = context["active_actor_id"]
        moves = [c for c in context["legal_candidates"] if c["kind"] == "MOVE" and c.get("destination")]
        end = next(c for c in context["legal_candidates"] if c["kind"] == "END_TURN")
        if actor == guard_id or not moves:
            send(end)
            continue
        if _gap(where[mover_id], where[guard_id]) > 1:
            closer = min(moves, key=lambda c: (_gap(_cells(c["destination"]), where[guard_id]), c["candidate_id"]))
            if _gap(_cells(closer["destination"]), where[guard_id]) >= _gap(where[mover_id], where[guard_id]):
                send(end)
            else:
                send(closer)
            continue
        away = [c for c in moves if _gap(_cells(c["destination"]), where[guard_id]) >= 3]
        if not away:
            send(end)
            continue
        leave = max(away, key=lambda c: (_gap(_cells(c["destination"]), where[guard_id]), c["candidate_id"]))
        result = send(leave)
        assert result["status"] == "REACTION_REQUIRED"  # the guard's Ask me opportunity attack stops the move
        prompt = result["reaction"]
        engine = service._load_session(match_id).engine
        assert (engine.state.actors[mover_id].position.x, engine.state.actors[mover_id].position.y) == where[mover_id]  # nothing committed
        assert prompt["reaction"] == "Opportunity Attack" and prompt["context"]["reactor_id"] == guard_id
        done = send(leave, [{**prompt["context"], "selection": "USE"}])
        assert done["status"] == "COMMITTED"
        break
    assert prompt is not None, "the mover never got next to the guard"
    events = service._load_session(match_id).engine.events
    assert any(e.event_type == "ATTACK_ROLLED" and e.source_definition_id.endswith(".opportunity_attack") and e.actor_id == guard_id
               for e in events)


def test_an_ai_turn_waits_for_the_players_answer_and_a_pass_uses_nothing(tmp_path):
    """The AI's action runs on a copy first; the table asks, and the AI, deterministic from this state, steps again
    with the answer."""
    from combat.gate4_adapters import ManualControllerAdapter

    for pid in (MOVER, GUARD):
        _install(tmp_path, pid)
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(GUARD, {"mode": "ask"}, {"opportunity_attack"})
    service = CombatService(ROOT, tmp_path)
    mover_id, guard_id = FACTORY_ACTOR_PREFIX + MOVER, FACTORY_ACTOR_PREFIX + GUARD
    match_id = service.create_factory_match(project_ids=[MOVER], opponent_actor_ids=[guard_id], match_seed="ASK-ME-AI",
                                            control_modes={mover_id: "LOCAL_AUTO", guard_id: "MANUAL"})["match_id"]
    table = TabletopService(service, tmp_path)
    assert service._load_session(match_id).engine.typed_ask_reactors == frozenset({guard_id})

    def where():
        engine = service._load_session(match_id).engine
        return {actor_id: (actor.position.x, actor.position.y) for actor_id, actor in engine.state.actors.items()}

    plan = {"leave": False}

    def pick(context):
        spot = where()
        moves = [c for c in context.legal_candidates if c.kind.value == "MOVE" and c.destination]
        end = next(c for c in context.legal_candidates if c.kind.value == "END_TURN")
        gap_now = _gap(spot[mover_id], spot[guard_id])
        if gap_now > 1:
            closer = min(moves, key=lambda c: (_gap((c.destination.x, c.destination.y), spot[guard_id]), c.candidate_id), default=None)
            if closer is None or _gap((closer.destination.x, closer.destination.y), spot[guard_id]) >= gap_now:
                return end.candidate_id
            return closer.candidate_id
        away = [c for c in moves if _gap((c.destination.x, c.destination.y), spot[guard_id]) >= 3]
        if not away:
            return end.candidate_id
        plan["leave"] = True
        return max(away, key=lambda c: (_gap((c.destination.x, c.destination.y), spot[guard_id]), c.candidate_id)).candidate_id

    real = service.controller

    class Scripted:
        def choose_primary_action(self, context):
            chosen = pick(context)
            return ManualControllerAdapter(lambda _context: (chosen, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    service.controller = Scripted()
    asked = None
    for _ in range(60):
        context = service.decision(match_id)["context"]
        if context["active_actor_id"] == guard_id:
            end = next(c for c in context["legal_candidates"] if c["kind"] == "END_TURN")
            table.act(match_id, end["candidate_id"], context["decision_id"], context["state_version"], 0, [])
            continue
        before = where()
        result = table.auto_step(match_id, 0, [])
        if result["status"] == "REACTION_REQUIRED":
            asked = result["reaction"]
            assert plan["leave"] and where() == before  # nothing committed while the player decides
            assert asked["reaction"] == "Opportunity Attack" and asked["context"]["reactor_id"] == guard_id
            done = table.auto_step(match_id, 0, [{**asked["context"], "selection": "DECLINE"}])
            assert done["status"] == "COMMITTED" and where()[mover_id] != before[mover_id]
            break
    assert asked is not None, "the AI never walked away from the guard"
    events = service._load_session(match_id).engine.events
    assert not any(e.source_definition_id.endswith(".opportunity_attack") and e.event_type == "ATTACK_ROLLED" for e in events)
