"""Main's movement selections and existing source-tagged grants must compose."""
import pytest

from combat.ext.granted_movement import choices, move
from combat.gate2_runtime_models import Position
from combat.gate2_engine import SYSTEM_MOVE
from tests import lock8_support as S
from tests.h1_support import script
from tests.test_lock9_granted_paths import request


@pytest.mark.parametrize("source",[None,"test:printed-grant"])
def test_granted_path_accepts_source_and_movement_context_together(source):
    engine=S.fight(S.bundle("SAND_BASE_SCOURING_HAND"),foe_at=(10,6))
    actor=engine.state.actors[S.ME]
    intent=request(engine)
    script(engine,[12]*40)
    before=actor.movement_remaining_ft
    path=next(c for c in choices(engine,actor,5) if c.destination==Position(x=2,y=6))
    move(engine,actor,path,intent,5,list(engine.state.actors),
         source=source,movement_context={"feature_id":"test:printed-grant"})
    assert actor.position==Position(x=2,y=6)
    assert actor.movement_remaining_ft==before
    receipt=next(e for e in reversed(engine.events) if e.event_type=="MOVEMENT_COMMITTED")
    assert receipt.source_definition_id==(source or SYSTEM_MOVE)
    assert receipt.payload["granted_cost_ft"]==5
    assert receipt.payload["cost_ft"]==0
