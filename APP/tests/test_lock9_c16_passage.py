"""C16 target-scoped passage contracts; ability activation remains rider-owned."""
import pytest

from combat import ext
from combat.creature_passage import geometry
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests import lock8_support as S
from tests.h1_support import ROOT, sheet
from tests.test_lock_choices import install
from tests.test_lock8_passage import corridor, move, use
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import on_hold, HOLD, LEFT, RIGHT

OVERRUN = "BRUTE_BASE_SPECIAL_ATTACKS"
RAM = "TAL_BRUTE_LIVING_BATTERING_RAM"
BREAKER = "TAL_BRUTE_FORTRESS_LINE_BREAKER"
MARK = "condition:typed.c16_target_passage"


def grant(engine, mover, occupant, source):
    engine._apply_condition(mover, MARK, source, mover.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"occupant": occupant.entity_id, "used": False})


def install_contract(monkeypatch):
    def marker(mover, occupant):
        return next((c for c in mover.conditions.values() if c.condition_id == MARK
                     and c.data.get("occupant") == occupant.entity_id), None)
    def passage(engine, mover, occupant):
        held = marker(mover, occupant)
        if held and (not held.data["used"] or set(engine._actor_cells(mover)) & set(engine._actor_cells(occupant))):
            return "difficult"
    def entered(engine, mover, occupant, intent):
        held = marker(mover, occupant)
        if held:
            held.data["used"] = True
            instance_id = next(key for key, condition in mover.conditions.items() if condition is held)
            engine._append_event("CONDITION_APPLIED", held.source_definition_id, actor_id=mover.entity_id,
                                 target_ids=(mover.entity_id,), payload={"condition_id": MARK,
                                 "instance_id": instance_id, "expires_on": held.expires_on})
            ext.note(engine, held.source_definition_id, mover,
                     f"{mover.display_name} uses its passage through {occupant.display_name}.")
    install(monkeypatch, "pass_through", passage)
    install(monkeypatch, "pass_through_entered", entered)


def test_overrun_survives_short_move_and_expires_if_unused(monkeypatch):
    install_contract(monkeypatch)
    e = S.fight(S.bundle(OVERRUN), foe_at=(5, 6))
    corridor(e)
    actor, foe = e.state.actors[S.ME], e.state.actors[S.FOE]
    grant(e, actor, foe, OVERRUN)
    for _ in range(3):
        assert move(e, 6) is not None
    assert not next(c for c in actor.conditions.values() if c.condition_id == MARK).data["used"]
    use(e, move(e, 4))
    assert move(e, 6) is not None
    e.end_turn()
    S.turn(e, S.ME)
    assert not any(c.condition_id == MARK for c in actor.conditions.values())
    assert move(e, 6) is None


@pytest.mark.parametrize("source", [OVERRUN, RAM, BREAKER])
def test_selected_creature_straight_crossing_cost_and_no_reentry(monkeypatch, source):
    install_contract(monkeypatch)
    e = S.fight(S.bundle(source), foe_at=(4, 6), ally=S.bundle(actor_id=S.ALLY), ally_at=(7, 6))
    corridor(e)
    actor, foe = e.state.actors[S.ME], e.state.actors[S.FOE]
    grant(e, actor, foe, source)
    blocked, ends, difficult, permissions = geometry(e, actor)
    assert permissions == {S.FOE: "difficult"}
    assert (7, 6) in blocked and (4, 6) in ends
    c = move(e, 5)
    assert c is not None and c.movement_cost_ft == 15
    assert [p.y for p in c.canonical_path] == [6, 6, 6]
    assert move(e, 4) is None
    use(e, c)
    assert actor.position == Position(x=5, y=6)
    assert actor.movement_remaining_ft == 15
    assert move(e, 3) is None
    assert move(e, 8) is None


def test_once_only_passage_remains_valid_until_large_footprint_is_cleared(monkeypatch):
    install_contract(monkeypatch)
    e = S.fight(S.bundle(OVERRUN), foe_at=(4, 6))
    corridor(e)
    actor, foe = e.state.actors[S.ME], e.state.actors[S.FOE]
    # Two adjoining occupied cells prove that consuming entry does not strand a
    # mover inside the granted creature. The engine still validates every step.
    original = e._actor_cells
    monkeypatch.setattr(e, "_actor_cells", lambda a, position=None: {(4, 6), (5, 6)} if
                        (a if isinstance(a, str) else a.entity_id) == S.FOE else original(a, position))
    grant(e, actor, foe, OVERRUN)
    c = move(e, 6)
    assert c is not None and c.movement_cost_ft == 25
    use(e, c)
    assert actor.position == Position(x=6, y=6)


def test_one_creature_grant_and_consumption_survive_table_reload(monkeypatch, tmp_path):
    import json
    import zipfile
    from combat.tabletop_service import TabletopService
    from tests.test_hidden_targeting import turn
    install_contract(monkeypatch)
    for pid, owned in [("11111111", [OVERRUN]), ("33333333", [])]:
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet(owned)))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "C16 passage hall", "width_squares": 12, "height_squares": 10,
        "walls": [{"shape": "rect", "points": [[0, 0], [12, 4]]}, {"shape": "rect", "points": [[0, 5], [12, 10]]}],
        "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    mid = combat.create_factory_match(project_ids=["11111111"], opponent_actor_ids=[RIGHT],
        control_modes={LEFT: "MANUAL", RIGHT: "MANUAL"}, arena_id="battlefield:map.c16-passage-hall", match_seed="C16-PASSAGE")["match_id"]
    table = TabletopService(combat, tmp_path)
    turn(table, mid, LEFT)
    on_hold(monkeypatch, lambda e: grant(e, e.state.actors[LEFT], e.state.actors[RIGHT], OVERRUN))
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    marker = next(c for c in reloaded.engine.state.actors[LEFT].conditions.values() if c.condition_id == MARK)
    assert marker.data == {"occupant": RIGHT, "used": False}
    state = table.state(mid)
    e = combat._load_session(mid).engine
    c = next(c for c in e.legal_candidates() if c.kind.value == "MOVE" and c.destination == Position(x=5, y=4))
    assert Position(x=4, y=4) in c.canonical_path
    assert table.act(mid, c.candidate_id, c.decision_id, c.state_version, state["last_sequence"])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    marker = next(c for c in loaded.engine.state.actors[LEFT].conditions.values() if c.condition_id == MARK)
    assert marker.data["used"] is True
    assert loaded.mechanical.replay()["status"] == "PASS"
