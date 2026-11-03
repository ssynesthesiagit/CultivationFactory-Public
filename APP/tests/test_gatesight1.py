"""GATESIGHT1: Gate of the Inner Sea's heavy obscurement distance and hostile-only policy."""

from combat import zones
from combat.gate2_runtime_models import Position
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn

GATE = "tianxia.subpath.qi.black_sea_leviathan_womb.feature.gate_of_the_inner_sea"


def _gate_fight(tmp_path):
    combat, table, mid = fixture(tmp_path, [GATE], ask=False, seed="GATESIGHT1",
                                 positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 6, "y": 6}})
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Gate of the Inner Sea", at=(8, 6)).candidate_id)
    return reload(tmp_path, mid)


def _sight(engine, viewer_id, target_id, viewer_at, target_at):
    viewer, target = engine.state.actors[viewer_id], engine.state.actors[target_id]
    viewer.position, target.position = Position(**viewer_at), Position(**target_at)
    return zones.hidden_from(engine, viewer, target)


def test_gate_hostiles_see_within_ten_feet_beyond_they_do_not(tmp_path):
    engine = _gate_fight(tmp_path)
    assert not _sight(engine, FOE, OWNER, {"x": 7, "y": 6, "z": 0}, {"x": 8, "y": 6, "z": 0})
    assert _sight(engine, FOE, OWNER, {"x": 2, "y": 6, "z": 0}, {"x": 8, "y": 6, "z": 0})


def test_gate_ally_is_unaffected(tmp_path):
    engine = _gate_fight(tmp_path)
    assert not _sight(engine, ALLY, OWNER, {"x": 2, "y": 6, "z": 0}, {"x": 8, "y": 6, "z": 0})


def test_recasting_gate_leaves_one_zone(tmp_path):
    from tests.test_r9i_karma_persistence import end_turn, prompt_turn

    combat, table, mid = fixture(tmp_path, [GATE], ask=False, seed="GATESIGHT1R",
                                 positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 12, "y": 6}})
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Gate of the Inner Sea", at=(8, 6)).candidate_id)
    end_turn(table, mid)
    prompt_turn(table, mid, FOE)
    end_turn(table, mid)
    prompt_turn(table, mid, OWNER)
    engine = combat._load_session(mid).engine
    candidates = [c for c in engine.legal_candidates()
                  if (engine.action_catalog.get(c.source_definition_id).display_name == "Gate of the Inner Sea")]
    assert candidates
    settle(table, mid, candidates[0].candidate_id)
    engine = reload(tmp_path, mid)
    assert len(zones.typed_zones(engine)) == 1
