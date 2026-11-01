"""Adversarial sibling identities after native acquisition, commit and reload."""
import pytest

from combat.ext.afterimage_targeting import destroy_image, image_for_condition
from tests.auto8f1_table_support import OWNER, FOE, reload_identical
from tests.test_mgr_t14_afterimage_map import game, move, image


@pytest.mark.parametrize("reload_snapshot", [False, True])
def test_unbound_record_cannot_destroy_live_replacement(tmp_path, reload_snapshot):
    g = game(tmp_path)
    move(g)
    reload_identical(g["combat"], g["match_id"], g["userdata"])
    session = g["combat"]._load_session(g["match_id"])
    engine = session.engine
    held, live = image(engine)
    # Deliberately adversarial record: it claims the real condition, but that
    # condition binds the live record, never this stale sibling request.
    stale = live.model_copy(deep=True, update={"object_id": live.object_id + ".stale"})
    engine._update_object(stale, "action:test.stale-image", FOE)
    if reload_snapshot:
        # Use the native saved-state schema and cold engine reconstruction, so
        # equality cannot accidentally depend on pre-serialization identities.
        snapshot = tmp_path / "adversarial-state.json"
        snapshot.write_text(engine.state.model_dump_json(), encoding="utf-8")
        state = type(engine.state).model_validate_json(snapshot.read_text(encoding="utf-8"))
        engine = session.persistence._engine_from_loaded(
            state, [e.model_dump(mode="json") for e in engine.events],
            [r.model_dump(mode="json") for r in engine.rolls],
            commanded_cui_this_turn=engine._commanded_cui_this_turn)
    owner = engine.state.actors[OWNER]
    condition = owner.conditions[held.instance_id]
    before = engine.state.model_dump(mode="json")
    events = [e.model_dump(mode="json") for e in engine.events]
    assert not destroy_image(engine, stale.object_id, "action:test.targeting", FOE, "intent:test")
    assert engine.state.model_dump(mode="json") == before
    assert [e.model_dump(mode="json") for e in engine.events] == events
    assert image_for_condition(engine, owner, condition).object_id == live.object_id
    assert not engine.state.map_images[stale.object_id].destroyed
    assert not engine.state.map_images[live.object_id].destroyed
    # The binding guard must still admit the actual live target exactly once.
    assert destroy_image(engine, live.object_id, "action:test.targeting", FOE, "intent:test")
    assert engine.state.map_images[live.object_id].destroyed
    assert condition.instance_id not in owner.conditions
    assert not destroy_image(engine, live.object_id, "action:test.targeting", FOE, "intent:test")
