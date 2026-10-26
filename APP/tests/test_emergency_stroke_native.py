"""Printed free-hand requirement through acquisition, table commit and cold load."""
import pytest

from combat.ext.hand_occupancy import free_hands
from combat.ext.talismans import EMERGENCY, STROKES
from tests.hunt51_grapple_support import fight, on_turn, send, verify_reloaded
from tests.test_hunt51_grapple_persisted import reload
from tests.test_shared_hand_occupancy import W, options

EMBER = "tianxia.talent.talismans.ember_talisman"


def strokes(table, match):
    return [row for row in options(table, match) if "Emergency Stroke" in row["label"]]


@pytest.mark.parametrize("occupied", [False, True])
def test_stroke_requires_a_real_free_hand_after_table_reload(tmp_path, occupied):
    # Learning a formula acquires the sphere and its automatic base abilities.
    user, service, table, match, ids = fight(
        tmp_path, "stroke-hands", talents=(EMBER,),
        equipment=(W + "bi_shou", W + "fu") if occupied else (W + "bi_shou",))
    on_turn(table, match, ids[0])
    engine = reload(user, service, match)
    actor = engine.state.actors[ids[0]]
    assert bool(free_hands(engine, actor)) == (not occupied)
    before = actor.resources.copy()
    if occupied:
        assert not strokes(table, match), "both occupied hands must block drawing a talisman"
        # Other talisman actions are not gated by Emergency Stroke's requirement.
        assert any("Ember Talisman" in row["label"] for row in options(table, match))
        send(table, match, lambda row: "Stow Bi Shou" in row["label"])
        verify_reloaded(user, service, match)
        assert strokes(table, match)
        send(table, match, lambda row: "Draw Bi Shou" in row["label"])
        verify_reloaded(user, service, match)
        assert not strokes(table, match)
        send(table, match, lambda row: "Stow Bi Shou" in row["label"])
    assert strokes(table, match)
    send(table, match, lambda row: row["label"].startswith("Emergency Stroke")
         and "2 CP" not in row["label"])
    verify_reloaded(user, service, match)
    actor = reload(user, service, match).state.actors[ids[0]]
    assert actor.resources[EMERGENCY] == before[EMERGENCY] + 1
    assert actor.resources[STROKES] == before[STROKES] - 1
    assert actor.resources["resource:core.stamina"] == before["resource:core.stamina"] - 1
    assert not actor.action_available
    send(table, match)
    on_turn(table, match, ids[2])
    assert not strokes(table, match), "a non-owner cannot draw the owner's talisman"


def test_nonowner_never_acquires_emergency_stroke(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "no-stroke", equipment=(W + "bi_shou",))
    on_turn(table, match, ids[0])
    verify_reloaded(user, service, match)
    assert not strokes(table, match)
    assert EMERGENCY not in reload(user, service, match).state.actors[ids[0]].resources
