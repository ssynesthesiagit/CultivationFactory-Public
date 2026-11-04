"""The source-qualified GM ruling is required, never inferred from learned features."""
import pytest

from combat.ext.life_riders import REACH, _reach_permission


@pytest.mark.parametrize('record', [
    'GM said yes', {}, {'talent_id': REACH},
    {'talent_id': REACH, 'record_id': 'ruling-1', 'note': '  '},
    {'talent_id': REACH, 'note': 'A physical connection exists'},
    {'talent_id': 'unrelated', 'record_id': 'ruling-1', 'note': 'Physical connection'},
])
def test_incomplete_or_unrelated_permission_is_rejected(record):
    assert _reach_permission({'path_and_subpath': {'life_seal_reach_permission': record}}) is None


def test_permission_requires_a_source_and_connection_explanation():
    record = {'talent_id': REACH, 'record_id': 'gm-ruling-1', 'note': 'A bodily thread joins the seal wearer'}
    assert _reach_permission({'path_and_subpath': {'life_seal_reach_permission': record}}) == record


def test_untracked_cleanup_preserves_unrelated_and_separately_linked_markers():
    from types import SimpleNamespace as Row
    from combat.ext.trap import NETTED, net_hold_companions

    def condition(kind, source='trap:one', owner='trapper', **data):
        return Row(condition_id=kind, source_definition_id=source, source_actor_id=owner, data=data)

    held = condition('condition:typed.restrained')
    actor = Row(conditions={
        'hold': held, 'own': condition(NETTED),
        'other_trap': condition(NETTED, source='trap:two'),
        'other_owner': condition(NETTED, owner='other'),
        'separately_linked': condition(NETTED, hold_id='missing-other-hold'),
    })
    engine = Row(action_catalog={'trap:one': Row(parameters={'set_trap': True}, owner_id='trapper')},
                 state=Row(actors={'patient': actor}))
    assert net_hold_companions(engine, actor, 'hold') == ['own']
