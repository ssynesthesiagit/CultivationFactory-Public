"""Iron Fist follow-up choices explain the real held object and terrain."""
import pytest
from tests.hunt23_support import LEFT, RIGHT, fight, turn, action_sender, reload


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('kind', ['elbow', 'wrist'])
def test_form_choice_meaning_and_reload(tmp_path, ai, kind):
    talent = 'TAL_IRON_FIST_ELBOW_IN_THE_DOOR' if kind == 'elbow' else 'TAL_IRON_FIST_WRIST_TRAPPING_HAND'
    effects = ([{'type':'damage', 'damage_type':'BLUDGEONING', 'flat':2, 'applies_to':'target'},
                {'type':'iron_elbow_space'}] if kind == 'elbow' else
               [{'type':'save', 'ability':'str', 'on_fail':[{'type':'iron_wrist'}]}])
    svc, table, mid = fight(tmp_path, [talent], right=['TAL_VOID_NULLIFYING_STRIKE'], effects=effects, target='HOSTILE_ENTITY',
        typed_parameters={'unarmed_option':'grapple'} if kind == 'wrist' else None)
    turn(table, mid, LEFT)
    send = action_sender(svc, table, mid, 'Test setup', ai=ai)
    result = send([])
    if ai:
        assert result['status'] == 'COMMITTED'  # the AI owner makes its own decision
        engine = reload(svc, mid)
        if kind == 'elbow':
            assert any('Elbow in the Door' in str(z.trigger_profile) for z in engine.state.zones.values())
        else:
            assert any(c.condition_id.endswith('iron_wrist') for c in engine.state.actors[RIGHT].conditions.values())
        return
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert 'No printed rule summary' not in prompt['summary']
    assert 'next turn' in prompt['rules']
    assert 'Test setup' in prompt['trigger'] and 'Visiting Fighter' in prompt['trigger']
    options = prompt['choice']['options']
    if kind == 'elbow':
        assert all('difficult terrain' in o['label'] for o in options)
        assert 'Elbow in the Door' in prompt['reaction']
    else:
        assert all('Disadvantage' in o['description'] for o in options)
        assert len({o['label'].split(':')[0] for o in options}) == len(options)
        assert all('Unarmed' not in o['label'] and 'Hollowed' not in o['label'] for o in options)
    answer = {**prompt['context'], 'selection':'USE', 'option_ids':[options[0]['id']]}
    assert send([answer])['status'] == 'COMMITTED'
    engine = reload(svc, mid)
    if kind == 'elbow':
        assert any(z.trigger_profile.get('placed', {}).get('tag') == 'iron_elbow' or
                   'Elbow in the Door' in str(z.trigger_profile) for z in engine.state.zones.values())
    else:
        assert any(c.condition_id.endswith('iron_wrist') for c in engine.state.actors[RIGHT].conditions.values())
