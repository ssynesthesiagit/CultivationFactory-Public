"""Public, isolated table continuations for the four reviewed appraisal records.

The Trace case selects its compiled source, not a stale exact menu label.
All answers are explicit human decisions; no model transport is used.
"""
import json

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.knowledge_inputs_support import (
    OWNER, FOE, QI, TRACE, VESSEL, VENOM, make, candidates, answers,
)
from tests.worker2_support import reload


@pytest.mark.parametrize('row,values,questions,expected', [
    (QI, {'qi.expression': 'Cold qi'}, ['qi.expression'],
     {'Strongest obvious qi expression': 'Cold qi'}),
    (TRACE, {'subject.kind': 'inscription', 'trace.nature': 'Spiritual'},
     ['trace.nature'], {'Ordinary, magical, spiritual, forged or sphere-created?': 'Spiritual'}),
    (VESSEL, {'vessel.dc': 0, 'vessel.safe': 'Weight', 'vessel.resists': 'Speed'},
     ['vessel.safe', 'vessel.resists'],
     {'One property it can receive safely': 'Weight', 'One property it resists': 'Speed'}),
    (VENOM, {'poison.present': True, 'poison.kind': 'Spiritual'},
     ['poison.kind'], {'Is poison present?': 'Yes', 'Poison family': 'Spiritual'}),
])
def test_table_reading_accepts_saved_choice_and_commits_private_answers(
        tmp_path, row, values, questions, expected):
    combat, table, mid = make(tmp_path, row, values)
    candidate = candidates(combat, mid, row, FOE)[0]
    menu = table.state(mid)['menu']
    replies, prompts = [], []
    for _ in range(6):
        result = table.act(mid, candidate.candidate_id, menu['decision_id'],
                           menu['state_version'], 0, replies)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']
        prompts.append(prompt)
        context = prompt['context']
        rid = context['reaction_source_id']
        if rid == 'choice:needle.reading_questions':
            assert context['reactor_id'] == OWNER
            assert {o['id'] for o in prompt['choice']['options']} >= set(questions)
            chosen = questions
        elif rid == 'choice:needle.fact_admission.qi_nature':
            assert context['reactor_id'] == FOE
            assert all(name in json.dumps(prompt) for name in ('Taste the Qi', 'Wren', 'Mara'))
            chosen = ['open']
        elif rid == 'choice:needle.reading_check':
            chosen = ['INT:Arcana']
        elif rid == 'choice:needle.reading_profile':
            chosen = []
        else:
            raise AssertionError(rid)
        replies.append({**context, 'selection': 'USE' if chosen else 'DECLINE',
                        'option_ids': chosen})
        # The next request must consume the saved table pause in a cold service.
        combat = CombatService(ROOT, tmp_path)
        table = TabletopService(combat, tmp_path)
    else:
        raise AssertionError('Reading never committed')
    assert answers(tmp_path, mid)[-1]['details']['answers'] == expected
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == 'condition:information.reading'
                   for c in engine.state.actors[FOE].conditions.values())
    if row == VESSEL:
        assert prompts[0]['context']['reaction_source_id'] == 'choice:needle.reading_check'
        assert any(e.event_type == 'CHECK_ROLLED' for e in engine.events)
    # Private source declarations are hidden; visible condition labels must
    # remain ordinary language, not a dotted runtime condition identifier.
    from combat.presentation import condition_label
    for actor in engine.state.actors.values():
        for condition in actor.conditions.values():
            if condition.condition_id in {'condition:information.reading',
                                          'condition:typed.fact_consent_admission'}:
                label = condition_label(condition.condition_id, condition.data)
                assert label and 'condition:' not in label and 'typed.' not in label
