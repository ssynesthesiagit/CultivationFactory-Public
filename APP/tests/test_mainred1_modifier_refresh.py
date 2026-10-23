"""Refresh policy must not erase independently owned modifiers or their expiry owner."""
import pytest

from combat import typed_executor as te
from tests.h1_support import ME, FOE, duel


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("shared_cache", [False, True])
def test_owned_modifier_refresh_scope_keeps_latest_expiry_owner(shared, shared_cache):
    engine = duel("HUNGER_BASE_TASTE_THE_QI")
    first, second = engine.state.actors[ME], engine.state.actors[FOE]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.parameters.get("typed"))
    effect = {"type": "ac_bonus", "flat": -1, "applies_to": "target", "source_owned": True,
              "duration": {"kind": "until_start_of_next_turn"}}
    if shared:
        effect["refresh_across_owners"] = True
    cache = {}
    for actor in (first, second):
        ctx = te.Context(engine, actor, action.model_copy(update={"owner_id": actor.entity_id}), None,
                         action.parameters["typed"], [second], second, cache if shared_cache else {})
        te.run_effects(ctx.with_source("test:mainred1.shared_penalty"), [effect])
    modifiers = [m for m in second.modifiers.values() if m.source_definition_id == "test:mainred1.shared_penalty"]
    assert len(modifiers) == (1 if shared else 2)
    assert {m.source_actor_id for m in modifiers} == ({FOE} if shared else {ME, FOE})
    assert all(m.expires_on == "START_OF_SOURCE_NEXT_TURN" for m in modifiers)
