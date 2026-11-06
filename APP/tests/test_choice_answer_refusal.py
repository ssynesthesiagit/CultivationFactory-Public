"""An invalid answer to a required plug-in choice is refused at submission (CLOUDMR choice refusal).

Spool and Strand's paid Qi Thread asks where the strand emerges ("choice:needle.strand_origin"), a required
choice with no Pass (THREAD_BASE_SPOOL_AND_STRAND: "If you spend 1 CP, you can create Qi Thread from your
fingertips, breath, weapon, sleeve, hair, blood, or dantian pressure for 1 minute."). A table that answers Pass,
or an origin it was not offered, must get a refusal and keep the fight exactly as it was, not commit the
technique with its cost paid and its strand silently missing.
"""
import pytest

from combat.gate5_service import CombatServiceError
from combat.ext.thread_second_pass import LOCK
from tests.test_a2_thread import fixture, cold, candidate, reach, send, P, F

CHOICE = 'choice:needle.strand_origin'


def _strand_prompt(table, mid, cid):
    result = send(table, mid, cid, [])
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reaction_source_id'] == CHOICE, prompt['context']
    assert prompt['choice']['allow_decline'] is False
    return prompt


@pytest.mark.parametrize('answer,message', [
    ('pass', "This choice has no Pass; choose one of its offered options."),
    # A Pass that still spends is not a missing Pass; it is malformed, whatever the choice allows.
    ('spend_on_pass', "A declined reaction cannot spend resources or select options."),
    ('unoffered', "The answer is not one of this choice's offered options."),
])
def test_invalid_answer_to_required_choice_is_refused_and_commits_nothing(tmp_path, answer, message):
    combat, table, mid = fixture(tmp_path, [LOCK], foe_x=8)
    reach(table, mid, P)
    cid = candidate(table, mid, 'Draw the Line: Guide (Qi Thread)', F)
    prompt = _strand_prompt(table, mid, cid)
    offered = [o['id'] for o in prompt['choice']['options']]
    before = cold(tmp_path, mid).state.model_dump(mode='json')
    bad = ({**prompt['context'], 'selection': 'DECLINE', 'option_ids': []} if answer == 'pass' else
           {**prompt['context'], 'selection': 'DECLINE', 'spend': 1, 'option_ids': []} if answer == 'spend_on_pass' else
           {**prompt['context'], 'selection': 'USE', 'option_ids': ['nowhere']})
    assert 'nowhere' not in offered
    with pytest.raises(CombatServiceError) as refused:
        send(table, mid, cid, [bad])
    assert refused.value.status_code == 422
    assert refused.value.diagnostic.code == 'COMBAT_AI_INTENT_INVALID'
    assert str(refused.value) == message
    after = cold(tmp_path, mid)
    assert after.state.model_dump(mode='json') == before
    assert not [e for e in after.events if e.event_type == 'GM_RIDER' and 'failed:' in str(e.payload)]


def test_valid_answer_to_required_choice_still_creates_the_strand(tmp_path):
    combat, table, mid = fixture(tmp_path, [LOCK], foe_x=8)
    reach(table, mid, P)
    cid = candidate(table, mid, 'Draw the Line: Guide (Qi Thread)', F)
    prompt = _strand_prompt(table, mid, cid)
    origin = prompt['choice']['options'][0]['id']
    result = send(table, mid, cid, [{**prompt['context'], 'selection': 'USE', 'option_ids': [origin]}])
    assert result['status'] == 'COMMITTED', result
