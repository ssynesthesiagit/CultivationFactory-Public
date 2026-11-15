"""Repeat-group anchor cleanup preserves unrelated casts and earlier deadlines."""
from types import SimpleNamespace

from combat.ext.rider_repeat_groups import PREFIX, anchor_removed


def test_anchor_cleanup_uses_exact_instances_and_waits_for_last_anchor():
    def condition(iid, *, expiry='END_OF_TARGET_TURN', data=None):
        return SimpleNamespace(instance_id=iid, condition_id=iid, expires_on=expiry,
                               source_definition_id='same technique', source_actor_id='caster', data=data or {})

    companion = condition('check')
    concentration_row = condition('concentration row', expiry='CONCENTRATION_END')
    other_cast = condition('other cast check')
    other_caster = condition('other caster check')
    second_anchor = condition('second anchor', expiry='CONCENTRATION_END')
    ledger = condition(PREFIX + 'one', expiry='CONCENTRATION_END',
                       data={'anchors': ['first anchor', 'second anchor'],
                             'conditions': ['check', 'concentration row']})
    ledgers = [ledger, condition(PREFIX + 'two', expiry='CONCENTRATION_END', data={'anchors': ['other cast anchor'],
                                                    'conditions': ['other cast check']}),
               condition(PREFIX + 'three', expiry='CONCENTRATION_END', data={'anchors': ['other caster anchor'],
                                                'conditions': ['other caster check']})]
    ledgers[2].source_actor_id = 'other caster'
    other_caster.source_actor_id = 'other caster'
    holder = SimpleNamespace(entity_id='target', conditions={c.instance_id: c for c in
                             [companion, concentration_row, other_cast, other_caster, second_anchor, *ledgers]})
    events = []
    engine = SimpleNamespace(state=SimpleNamespace(actors={'target': holder}),
                             _append_event=lambda *args, **kwargs: events.append((args, kwargs)))

    def removed(iid):
        event = SimpleNamespace(payload={'instance_id': iid, 'reason': 'SEALED'}, target_ids=('target',))
        anchor_removed(engine, 'CONDITION_REMOVED', {'originating_event': event})

    removed('first anchor')
    assert 'check' in holder.conditions  # One of this group's anchors still lives.
    del holder.conditions['second anchor']
    removed('second anchor')
    assert 'check' not in holder.conditions
    assert all(iid in holder.conditions for iid in ['concentration row', 'other cast check', 'other caster check'])
    assert len(events) == 1
    assert events[0][1]['payload']['instance_id'] == 'check'
    removed('check')  # A child removal cannot recurse into another group's cleanup.
    assert len(events) == 1
