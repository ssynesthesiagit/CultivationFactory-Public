"""Life/Dawn damage integration must not silently downgrade a broken reaction to a GM rider."""
import pytest

from combat import typed_reactions, pending_damage
from combat.ext.yang_sun_marks import LIFE, DAWN
from tests.worker2_support import fixture, OWNER, ALLY, FOE


@pytest.mark.parametrize("source", [LIFE, DAWN])
def test_protection_dispatch_has_no_bad_row_rider(tmp_path, source):
    combat, table, mid = fixture(tmp_path, [source], ask=False)
    engine = combat._load_session(mid).engine
    rows = [r for r in engine.typed_reaction_rows[OWNER] if r["feature_id"] == source]
    assert any(r.get("kind") == "ally_drop_to_zero" for r in rows), repr(rows)
    ally = engine.state.actors[ALLY]
    ally.current_hp = 5
    engine._active_intent = None
    with pending_damage.scope(engine, ally, 30, "SLASHING", "action:test.attack", FOE):
        amount = typed_reactions.on_damage(
            engine, ally, 30, 0, source_definition_id="action:test.attack", source_actor_id=FOE)
    errors = [e.payload.get("rider") for e in engine.events
              if e.event_type == "GM_RIDER" and e.source_definition_id == source]
    assert not errors, "; ".join(errors)
    assert amount == 4
