"""Only adjacent, equivalent nonstacking mode records share a feed line."""
from copy import deepcopy

import pytest

from combat.history_feed import format_history_feed


def feed(events, pre_state=None):
    return format_history_feed(events, [], pre_state=pre_state, post_state={},
        actor_names={'a': 'Attacker'}, definition_names={'strike': 'Strike', 'other': 'Other'})


def applied(mid, **changes):
    record = {'modifier_id': mid, 'source_definition_id': 'strike', 'target_id': 'a',
              'target_field': 'attack_mode', 'operation': 'SET', 'value': 'DISADVANTAGE',
              'applies_to': 'NEXT_ATTACK', 'expires_on': 'CONSUMED', **changes}
    return {'event_type': 'MODIFIER_APPLIED', 'actor_id': 'a', 'target_ids': ['a'],
            'source_definition_id': record['source_definition_id'],
            'payload': {**record, 'gate3_modifier_after': record}}


def removed(mid):
    return {'event_type': 'MODIFIER_REMOVED', 'actor_id': 'a', 'target_ids': [],
            'source_definition_id': 'strike', 'payload': {'modifier_id': mid, 'reason': 'CONSUMED'}}


def test_adjacent_equivalent_modes_and_endings_share_lines_without_changing_events():
    events = [applied('one'), applied('two'), removed('one'), removed('two')]
    before = deepcopy(events)
    assert len(feed(events)) == 2
    assert events == before


def test_removal_only_boundary_uses_recorded_pre_state():
    pre = {'actors': {'a': {'modifiers': {mid: applied(mid)['payload']['gate3_modifier_after']
                                       for mid in ('one', 'two')}}}}
    assert len(feed([removed('one'), removed('two')], pre)) == 1
    # No old record means unknown effects must remain visible.
    assert len(feed([removed('one'), removed('two')])) == 2


@pytest.mark.parametrize('changes', [
    {'value': 'ADVANTAGE'}, {'source_definition_id': 'other'},
    {'expires_on': 'END_OF_TURN'}, {'expires_actor_id': 'b'},
    {'expires_turn_count': 2}, {'applies_to': 'ALWAYS'}, {'target_id': 'b'},
    {'target_field': 'attack_bonus', 'operation': 'ADD', 'value': 2},
])
def test_distinct_effects_are_not_combined(changes):
    assert len(feed([applied('one'), applied('two', **changes)])) == 2


def test_separate_attacks_and_additive_modifiers_keep_all_lines():
    separator = {'event_type': 'ATTACK_ROLLED', 'actor_id': 'a', 'source_definition_id': 'strike', 'payload': {}}
    assert len(feed([applied('one'), separator, applied('two')])) == 3
    events = [applied(mid, target_field='attack_bonus', operation='ADD', value=2) for mid in ('one', 'two')]
    assert len(feed(events)) == 2
