"""MMX94: the move the table draws is the move the fight committed to.

Owner 2026-10-03: "When it loads the move action it moves forward then jumps back before loading then finally moving
super fast to the location." The board animates from the MOVEMENT_COMMITTED record the table returns, so that record
has to be a real route from the square the fighter stood on to the square it ended on, and the state that arrives
afterwards has to ask for that same square. These tests take a move through the table a player actually uses, check
that record for a move you make and for one the AI makes, and run the board's own animation tests.
"""
import json
import subprocess
import zipfile
from pathlib import Path

from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet


APP = Path(__file__).resolve().parents[1]
OWNER = "actor:factory.57570001"
BOARD_TESTS = APP / "static" / "tabletop" / "board.test.mjs"


def setup(user, label):
    ids = ["57570001", "57570002", "57570003", "57570004"]
    for index, pid in enumerate(ids):
        data = sheet([], cl=10)
        data["identity"]["display_name"] = ["You", "Ally", "Foe", "Second Foe"][index]
        data["ability_scores_and_statistics"]["hit_points"]["maximum"] = 900
        folder = user / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(data))
    ButtonStore(user / "tabletop_buttons").save_reactions(ids[0], {"mode": "ask"}, set())
    service = CombatService(APP, user)
    arena = service.tabletop_maps.save({"display_name": "Open ground", "width_squares": 16, "height_squares": 10,
        "walls": [], "starts": {"team1": [[3, 5], [3, 6]], "team2": [[12, 5], [12, 6]]}})
    match = service.create_factory_match(project_ids=ids[:2], opponent_actor_ids=["actor:factory." + p for p in ids[2:]],
        control_modes={"actor:factory." + p: "MANUAL" for p in ids}, arena_id="battlefield:map." + arena["map_id"],
        match_seed=label, maximum_rounds=14, prefight={p: [] for p in ids})["match_id"]
    return service, TabletopService(service, user), match


def owner_turn(service, table, match, limit=40):
    """Play other fighters' turns out until the fighter you control is up."""
    for _ in range(limit):
        state = table.state(match)
        if service._load_session(match).engine.state.current_actor_id == OWNER:
            return state
        menu = state["menu"]
        if menu is None:
            table.auto_step(match, state["last_sequence"])
            continue
        assert table.act(match, menu["end_turn"], menu["decision_id"], menu["state_version"],
                         state["last_sequence"])["status"] == "COMMITTED"
    raise AssertionError("never came back to the fighter you control")


def movements(envelope):
    """The committed moves in one table response, read the way the board reads them."""
    return [row["raw"]["payload"] for row in envelope["events"]
            if row["event_type"] == "MOVEMENT_COMMITTED" and isinstance((row["raw"].get("payload") or {}).get("path"), list)]


def actor_at(state, actor_id):
    """Where the table is drawing a fighter, in squares."""
    return next(row for row in state["presentation"]["actors"] if row["entity_id"] == actor_id)["position"]


def steps(payload):
    return [(point["x"], point["y"]) for point in payload["path"]]


def test_the_move_a_player_makes_is_a_route_from_where_they_stood_to_where_they_stopped(tmp_path):
    service, table, match = setup(tmp_path, "MMX94-move")
    state = owner_turn(service, table, match)
    stood_at = (actor_at(state, OWNER)["x"], actor_at(state, OWNER)["y"])
    move = max(state["menu"]["moves"], key=lambda row: len(row.get("path") or []))

    result = table.act(match, move["candidate_id"], state["menu"]["decision_id"], state["menu"]["state_version"],
                       state["last_sequence"])

    assert result["status"] == "COMMITTED"
    committed = [payload for payload in movements(result["events"]) if payload["destination"] == move["destination"]]
    assert committed, "the move the fighter made is in the record the table animates"
    payload = committed[0]
    assert not payload.get("teleport"), "an ordinary move is walked, not blinked"
    route = steps(payload)
    assert len(route) >= 2, "a move that arrived somewhere records where it came from and where it went"
    assert route[0] == stood_at, "the route starts on the square the fighter was standing on"
    assert route[-1] == (move["destination"]["x"], move["destination"]["y"]), "the route ends on the square chosen"
    assert (actor_at(result["state"], OWNER)["x"], actor_at(result["state"], OWNER)["y"]) == route[-1], \
        "and the state that arrives with the move asks the table for that same square"
    for earlier, later in zip(route, route[1:]):
        assert max(abs(later[0] - earlier[0]), abs(later[1] - earlier[1])) <= 1, \
            "the route is one square at a time, so the table can walk it at a steady pace"
    assert route[-1] != route[0], "and the route actually arrives somewhere"


def test_the_move_the_ai_makes_is_recorded_the_same_way(tmp_path):
    service, table, match = setup(tmp_path, "MMX94-ai")
    state = owner_turn(service, table, match)
    after = state["last_sequence"]
    service.set_controller_mode(match, actor_id=OWNER, controller_mode="LOCAL_AUTO")

    for _ in range(6):
        committed = movements(table.auto_step(match, after)["events"])
        if committed:
            break
    else:
        raise AssertionError("the AI never moved")

    for payload in committed:
        route = steps(payload)
        assert len(route) >= 2
        assert route[-1] == (payload["destination"]["x"], payload["destination"]["y"]), \
            "an AI move ends on the square the fight recorded, so the table has somewhere to stop"
        if payload.get("teleport"):
            continue  # a blink covers the squares in between
        for earlier, later in zip(route, route[1:]):
            assert max(abs(later[0] - earlier[0]), abs(later[1] - earlier[1])) <= 1, \
                "an AI move is walked square by square, exactly like one of yours"


def test_the_board_draws_a_committed_move_once(tmp_path):
    """The animation itself, played on the real board module without a browser."""
    result = subprocess.run(["node", str(BOARD_TESTS)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
