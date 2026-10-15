"""Trap placement and off-turn relocation preserve the owner's table decisions."""
import pytest

from combat.canonical import canonical_sha256
from combat.ext import placed
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE, SECOND
from tests.test_r1i_round3 import reload
from tests.test_c4_protection_review import inherited_prompt_loader

T = "TAL_TRAP_"


@pytest.fixture(autouse=True)
def old_trap_control(monkeypatch):
    """Optional negative control selects starting choice helpers, keeping bounds fixes."""
    import ast
    import os
    import subprocess
    from combat.ext import trap
    mode = os.environ.get("C4_OLD_TRAP")
    if mode not in {"1", "scatter", "relocate"}:
        return
    source = subprocess.check_output(["git", "show", "dbef131:APP/combat/ext/trap.py"], text=True)
    names = {"_scatter", "_relocate"} if mode == "1" else {"_" + mode}
    nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name in names]
    namespace = dict(trap.__dict__)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "old_trap_control", "exec"), namespace)
    for name in names:
        monkeypatch.setattr(trap, name, namespace[name])


def scatter_packet(bundles):
    """Activate the owned Road state through a bounded test action packet.

    This isolates placement/relocation from the inheritance's separate reaction
    trigger. Ordinary state, placement, event, controller and persistence paths run.
    """
    owner = bundles[0]
    # Keep Ask me ownership while isolating the packet from initiative reactions.
    owner["typed_reactions"] = [{**row, "held_back": True} for row in owner["typed_reactions"]]
    for action in owner["action_catalog"]:
        if action["display_name"] == "Court of the Hidden Nail":
            typed = action["parameters"]["typed"]
            typed["effects"] = [{"type": "state", "name": "empty_road_was_never_empty",
                                  "duration": {"kind": "minutes", "value": 1}},
                                 {"type": "trap_scatter", "count": "pb", "within_ft": 60}]
    owner.pop("bundle_sha256", None)
    owner["bundle_sha256"] = canonical_sha256(owner)


def setup(tmp_path):
    return fixture(tmp_path, [T + "COURT_OF_THE_HIDDEN_NAIL", T + "THE_EMPTY_ROAD_WAS_NEVER_EMPTY"],
        owner_pb=2, seed="C4-TRAP-CHOICE", bundle_transform=scatter_packet,
        positions={OWNER: {"x": 3, "y": 0}, FOE: {"x": 8, "y": 0}, SECOND: {"x": 12, "y": 0}})


@pytest.mark.parametrize("ai_owner", [False, True])
def test_scatter_selects_spaces_commit_reload(tmp_path, ai_owner):
    combat, table, mid, send, commit = setup(tmp_path)
    cid = candidate(table, mid, "Court of the Hidden Nail", OWNER)
    before = reload(tmp_path, mid).state.model_dump(mode="json")
    if ai_owner:
        force_ai_candidate(combat, mid, OWNER, cid)
        result = send(cid, auto=True)
        assert result["status"] == "COMMITTED", result
    else:
        result = send(cid)
        assert result["status"] == "REACTION_REQUIRED", result
        p = result["reaction"]
        assert p["context"]["reaction_source_id"] == "choice:needle.trap_scatter"
        assert p["context"]["reactor_id"] == OWNER
        assert send(cid)["reaction"] == p
        assert reload(tmp_path, mid).state.model_dump(mode="json") == before
        assert p["choice"]["minimum"] == p["choice"]["maximum"] == 2
        ids = {o["id"] for o in p["choice"]["options"]}
        assert {"cell:3,2", "cell:4,2"} <= ids
        assert "cell:3,0" not in ids  # occupied by the owner
        answer = {**p["context"], "selection": "USE", "option_ids": ["cell:3,2", "cell:4,2"]}
        assert send(cid, [answer])["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    traps = placed.of(engine, "trap")
    assert len(traps) == 2
    if not ai_owner:
        assert {(z.center.x, z.center.y) for z in traps} == {(3, 2), (4, 2)}


@pytest.mark.parametrize("ai_mover", [False, True])
@pytest.mark.parametrize("decline", [False, True])
def test_relocation_owner_chooses_trap_and_destination_on_opposing_turn(tmp_path, ai_mover, decline):
    combat, table, mid, send, commit = setup(tmp_path)
    deploy = candidate(table, mid, "Court of the Hidden Nail", OWNER)
    p = send(deploy)["reaction"]
    assert send(deploy, [{**p["context"], "selection": "USE",
                          "option_ids": ["cell:3,2", "cell:4,2"]}])["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = next(o["candidate_id"] for o in table.state(mid)["menu"]["moves"]
               if o.get("destination") == {"x": 8, "y": 1})
    before_engine = reload(tmp_path, mid)
    before = before_engine.state.model_dump(mode="json")
    traps = {z.zone_id: (z.center.x, z.center.y) for z in placed.of(before_engine, "trap")}
    if ai_mover:
        force_ai_candidate(combat, mid, FOE, cid)
        before = reload(tmp_path, mid).state.model_dump(mode="json")
    result = send(cid, auto=ai_mover)
    assert result["status"] == "REACTION_REQUIRED", result
    p = result["reaction"]
    assert p["context"]["reaction_source_id"] == "choice:needle.trap_relocate"
    assert p["context"]["reactor_id"] == OWNER
    assert send(cid, auto=ai_mover)["reaction"] == p
    assert reload(tmp_path, mid).state.model_dump(mode="json") == before
    assert {o["id"].rsplit("@", 1)[0] for o in p["choice"]["options"]} == set(traps)
    # Pick the last option, rather than the AI's nearest trap/destination.
    chosen = p["choice"]["options"][-1]["id"]
    zid, coords = chosen.rsplit("@", 1)
    destination = tuple(map(int, coords.split(",")))
    answer = {**p["context"], "selection": "DECLINE" if decline else "USE", "option_ids": [] if decline else [chosen]}
    assert send(cid, [answer], auto=ai_mover)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    after = {z.zone_id: (z.center.x, z.center.y) for z in placed.of(engine, "trap")}
    expected = dict(traps)
    if not decline:
        expected[zid] = destination
    assert after == expected
    assert engine.state.actors[OWNER].resources == before_engine.state.actors[OWNER].resources
    assert engine.state.actors[OWNER].reaction_available == before_engine.state.actors[OWNER].reaction_available


@pytest.mark.parametrize("closer", [False, True])
def test_ai_owner_relocates_without_prompt_and_reload(tmp_path, closer):
    combat, table, mid, send, commit = setup(tmp_path)
    deploy = candidate(table, mid, "Court of the Hidden Nail", OWNER)
    p = send(deploy)["reaction"]
    assert send(deploy, [{**p["context"], "selection": "USE",
                          "option_ids": ["cell:3,2", "cell:4,2" if closer else "cell:8,2"]}])["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    engine = reload(tmp_path, mid)
    traps = {z.zone_id: z.center for z in placed.of(engine, "trap")}
    resources = dict(engine.state.actors[OWNER].resources)
    cid = next(o["candidate_id"] for o in table.state(mid)["menu"]["moves"]
               if o.get("destination") == {"x": 8, "y": 1})
    assert send(cid)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    changes = [(traps[z.zone_id], z.center) for z in placed.of(engine, "trap") if z.center != traps[z.zone_id]]
    assert len(changes) == (1 if closer else 0)
    if changes:
        assert engine.grid.distance_ft(*changes[0]) <= 10
    assert engine.state.actors[OWNER].resources == resources
