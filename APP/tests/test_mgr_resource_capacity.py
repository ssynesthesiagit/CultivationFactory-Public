"""General retained-capacity guards, independent of any ability identifier."""
from tests.h1_support import duel, ME


def test_explicit_retention_does_not_make_gain_negative():
    engine = duel([])
    actor = engine.state.actors[ME]
    resource = 'resource:core.qi'
    before = actor.resources[resource]
    engine._set_resource_maximum(actor, resource, 1, 'capacity-test', retain_excess=True)
    assert actor.resource_maximums[resource] == 1
    assert actor.resources[resource] == before
    restored = type(actor).model_validate(actor.model_dump(mode='json'))
    assert restored.resources[resource] == before
    assert restored.resource_maximums[resource] == 1
    engine._gain_resource(actor, resource, 2, 'capacity-test')
    assert actor.resources[resource] == before
    assert engine.events[-1].payload['gained'] == 0


def test_default_capacity_reduction_still_clamps():
    engine = duel([])
    actor = engine.state.actors[ME]
    engine._set_resource_maximum(actor, 'resource:core.qi', 1, 'capacity-test')
    assert actor.resources['resource:core.qi'] == 1


def test_state_classification_requires_explicit_native_metadata():
    import pytest
    from combat.ext.states import context, state, active
    engine = duel([])
    actor = engine.state.actors[ME]
    ctx = context(engine, actor, '', [actor], {'cl': 10, 'pb': 4})
    state(ctx, {'name': 'Unclassified Ward Transformation', 'expires_on': 'START_OF_SOURCE_NEXT_TURN'})
    assert 'rule' not in active(engine, actor, 'Unclassified Ward Transformation').data
    state(ctx, {'name': 'Declared effect', 'effect_kind': 'transformation', 'expires_on': 'START_OF_SOURCE_NEXT_TURN'})
    held = active(engine, actor, 'Declared effect')
    assert held.data['rule']['effect_kind'] == 'transformation'
    assert type(actor).model_validate(actor.model_dump(mode='json')).conditions[held.instance_id].data == held.data
    with pytest.raises(ValueError):
        state(ctx, {'name': 'Unrecognized effect', 'effect_kind': 'permanent_source'})
