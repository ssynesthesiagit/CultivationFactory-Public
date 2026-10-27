"""Palace delivery receipts cannot borrow a surrounding or previous strike."""
from types import SimpleNamespace

import pytest

from combat.ext.taiyin_palace import STATE, aligned_damage_type


@pytest.mark.parametrize('packet,type_name,expected', [
    ({'source': 'strike', 'actor': 'owner', 'target': 'foe'}, 'PIERCING',
     {'taiyin_palace': 'piercing'}),
    ({'source': 'strike', 'actor': 'owner', 'target': 'foe'}, 'COLD',
     {'taiyin_palace': 'cold'}),
    ({'source': 'outer', 'actor': 'owner', 'target': 'foe'}, 'COLD', None),
    ({'source': 'strike', 'actor': 'other', 'target': 'foe'}, 'COLD', None),
    # A settled hit may be redirected away from the declared packet target.
    ({'source': 'strike', 'actor': 'owner', 'target': 'other'}, 'COLD',
     {'taiyin_palace': 'cold'}),
    ({'source': 'strike', 'actor': 'owner', 'target': 'foe'}, 'UNTYPED', None),
])
def test_snapshot_requires_the_actual_typed_delivery(packet, type_name, expected):
    actor = SimpleNamespace(entity_id='owner', conditions={
        STATE: SimpleNamespace(condition_id=STATE, source_actor_id='owner')})
    target = SimpleNamespace(entity_id='foe')
    context = SimpleNamespace(source_id='strike')
    engine = SimpleNamespace(_typed_damage_packet=packet,
                             _typed_pending_damage_type=type_name)
    receipt = aligned_damage_type(engine, actor, target, context, None)
    assert receipt == expected
    # A nested response delivered after the strike neither publishes a receipt
    # under the strike's source nor changes the strike's receipt value.
    engine._typed_pending_damage_type = 'COLD'
    engine._typed_damage_packet = {'source': 'response', 'actor': 'owner', 'target': 'foe'}
    assert aligned_damage_type(engine, actor, target, context, None) is None
    assert receipt == expected


def test_nonowner_does_not_publish_a_hit_receipt():
    actor = SimpleNamespace(entity_id='other', conditions={})
    engine = SimpleNamespace(_typed_pending_damage_type='COLD')
    assert aligned_damage_type(engine, actor, SimpleNamespace(entity_id='foe'),
                               SimpleNamespace(source_id='strike'), None) is None
