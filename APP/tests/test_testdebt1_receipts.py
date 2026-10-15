"""TESTDEBT1: projections must check new metadata and preserve combat fields."""
import pytest

from tests.replay_assertions import remove_checked_receipt_additions


def test_checked_receipt_projection_preserves_existing_fields():
    events = [
        {'event_type': 'MOVEMENT_COMMITTED', 'source_definition_id': 'system:combat.movement',
         'payload': {'forced': False, 'path': [1, 2]}},
        {'event_type': 'MOVEMENT_COMMITTED', 'source_definition_id': 'action:fixture.command',
         'payload': {'path': [3, 4]}},
        {'event_type': 'DAMAGE_COMMITTED', 'payload': {'hp_before': 3, 'hp_damage': 5, 'remaining_hp': 0}},
        {'event_type': 'OTHER', 'payload': {'hp_before': 7, 'forced': True}},
    ]
    remove_checked_receipt_additions(events)
    assert events == [
        {'event_type': 'MOVEMENT_COMMITTED', 'source_definition_id': 'system:combat.movement',
         'payload': {'path': [1, 2]}},
        {'event_type': 'MOVEMENT_COMMITTED', 'source_definition_id': 'action:fixture.command',
         'payload': {'path': [3, 4]}},
        {'event_type': 'DAMAGE_COMMITTED', 'payload': {'hp_damage': 5, 'remaining_hp': 0}},
        {'event_type': 'OTHER', 'payload': {'hp_before': 7, 'forced': True}},
    ]


@pytest.mark.parametrize('event_type,payload', [
    ('MOVEMENT_COMMITTED', {'forced': True}),
    ('MOVEMENT_COMMITTED', {'forced': 0}),
    ('DAMAGE_COMMITTED', {'hp_before': True, 'hp_damage': 1, 'remaining_hp': 0}),
    ('DAMAGE_COMMITTED', {'hp_before': -1, 'hp_damage': 1, 'remaining_hp': 0}),
    ('DAMAGE_COMMITTED', {'hp_before': 10, 'hp_damage': 3, 'remaining_hp': 8}),
])
def test_checked_receipt_projection_rejects_incorrect_additions(event_type, payload):
    with pytest.raises(AssertionError):
        remove_checked_receipt_additions([{'event_type': event_type,
                                         'source_definition_id': 'system:combat.movement', 'payload': payload}])
