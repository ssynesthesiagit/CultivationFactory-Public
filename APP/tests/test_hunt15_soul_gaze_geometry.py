"""Table acceptance for Soul Gaze's printed mark exception and 60-foot limit.

Ordinary stone pillars block sight; this fixture supplies no spiritual
concealment. The own-mark case promotes FIX15's locked geometry regression.
"""
import pytest

from combat.typed_executor import bears_mark
from tests.hunt15_support import ALLY, LEFT, RIGHT, act, action_sender, fight, reload, turn


SOUL_GAZE = "tianxia.path.spirit_awakening.feature.soul_gaze"
MARK = [{"type": "mark", "mark": "Resonance", "applies_to": "target",
         "duration": {"kind": "until_removed"}}]


def _move(table, mid, destination):
    state = table.state(mid)
    menu = state["menu"]
    choice = next(c for c in menu["moves"] if c["destination"] == destination)
    assert table.act(mid, choice["candidate_id"], menu["decision_id"],
                     menu["state_version"], state["last_sequence"], [])["status"] == "COMMITTED"


def _mark_and_return(combat, table, mid, marker, ai):
    turn(table, mid, marker)
    assert action_sender(combat, table, mid, "Test setup", ai=ai,
                         target_id=ALLY)([])["status"] == "COMMITTED"
    if ai:
        combat.set_controller_mode(mid, actor_id=marker, controller_mode="MANUAL")
    assert act(table, mid, "end")["status"] == "COMMITTED"
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[ALLY], marker, "Resonance")


def _offered(table, mid):
    return any(ALLY in o.get("target_ids", [])
               for g in table.state(mid)["menu"]["actions"]
               if g["label"] == "Soul Gaze" for o in g["options"])


def _diagnose(combat, table, mid, ai):
    before = reload(combat, mid).state.actors[LEFT].resources["resource:core.resonance"]
    assert action_sender(combat, table, mid, "Soul Gaze", ai=ai,
                         target_id=ALLY)([])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources["resource:core.resonance"] == before - 1
    assert bears_mark(engine.state.actors[ALLY], LEFT, "Resonance")
    assert any("Soul Gaze on Guarding Friend:" in r["summary"] and ALLY not in r["summary"]
               for r in table.events(mid, 0)["events"])


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("marker", [
    LEFT,
    RIGHT,
])
def test_soul_gaze_mark_exception_behind_an_ordinary_pillar(tmp_path, ai, marker):
    combat, table, mid = fight(tmp_path, [SOUL_GAZE], primary="Resonance", ally=[],
        effects=MARK, target="ALLY_OR_SELF" if marker == LEFT else "HOSTILE_ENTITY",
        positions={LEFT: {"x": 8, "y": 5}, ALLY: {"x": 11, "y": 5},
                   RIGHT: {"x": 11, "y": 4}})
    _mark_and_return(combat, table, mid, marker, ai)
    engine = reload(combat, mid)
    assert engine._line_of_sight_actor_to_actor(engine.state.actors[LEFT], engine.state.actors[ALLY])
    _move(table, mid, {"x": 8, "y": 6})
    engine = reload(combat, mid)
    observer, target = engine.state.actors[LEFT], engine.state.actors[ALLY]
    assert observer.position.model_dump(mode="json") == {"x": 8, "y": 6}
    assert engine._distance_actor_to_actor(observer, target) < 60
    assert not engine._line_of_sight_actor_to_actor(observer, target)
    assert bears_mark(target, marker, "Resonance")
    assert _offered(table, mid) == (marker == LEFT), \
        "Soul Gaze must allow only the caster's mark through ordinary blocked sight"
    if marker == LEFT:
        _diagnose(combat, table, mid, ai)


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("distance_ft", [60, 65])
def test_soul_gaze_own_mark_preserves_the_printed_range(tmp_path, ai, distance_ft):
    combat, table, mid = fight(tmp_path, [SOUL_GAZE], primary="Resonance", ally=[],
        effects=MARK, target="ALLY_OR_SELF",
        positions={LEFT: {"x": 1, "y": 1}, ALLY: {"x": 13, "y": 1},
                   RIGHT: {"x": 17, "y": 12}})
    _mark_and_return(combat, table, mid, LEFT, ai)
    if distance_ft == 65:
        _move(table, mid, {"x": 0, "y": 1})
    engine = reload(combat, mid)
    observer, target = engine.state.actors[LEFT], engine.state.actors[ALLY]
    assert engine._distance_actor_to_actor(observer, target) == distance_ft
    assert engine._line_of_sight_actor_to_actor(observer, target)
    assert bears_mark(target, LEFT, "Resonance")
    assert _offered(table, mid) == (distance_ft == 60)
    if distance_ft == 60:
        _diagnose(combat, table, mid, ai)
