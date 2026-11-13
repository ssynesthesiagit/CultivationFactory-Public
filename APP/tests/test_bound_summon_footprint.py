"""Explicit geometry belongs to a bound summon, never another fight's actor ID."""
import pytest

from combat.footprint_registry import resolve_actor_footprint


@pytest.mark.parametrize('record,width,mode', [
    ({'footprint': 'large'}, 2, 'TYPED'),
    ({'size': 'large'}, 2, 'TYPED'),
    ({'size': 'medium', 'footprint': 'large'}, 1, 'TYPED'),
    ({}, 1, 'LEGACY_SINGLE_CELL'),
])
def test_bound_geometry_alias_and_size_precedence(record, width, mode):
    shape, compatibility = resolve_actor_footprint('test:bound-summon', summon_record=record)
    assert shape.width_cells == shape.height_cells == width
    assert compatibility == mode


def test_explicit_footprint_cannot_leak_to_another_save():
    actor_id = 'test:reused-summon'
    large, _ = resolve_actor_footprint(actor_id, summon_record={'footprint': 'large'})
    legacy, mode = resolve_actor_footprint(actor_id, summon_record={})
    missing, missing_mode = resolve_actor_footprint(actor_id)
    assert large.width_cells == 2
    assert legacy.width_cells == missing.width_cells == 1
    assert mode == missing_mode == 'LEGACY_SINGLE_CELL'
