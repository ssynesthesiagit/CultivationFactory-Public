"""Mandatory shared Mass options through accepted transactions and cold replay."""
import json
import pytest
from tests.test_a2_imbuement import fixture, cold, QI, S


@pytest.mark.parametrize('talent,label,option,token', [
    ('fortify_and_expose', 'Expose', 'DEX', 'DEX'),
    ('harden_and_brittle', 'Brittle (creature)', 'lose_slashing', 'SLASHING'),
    ('suppress_function', 'Seal Sense', 'deafened', 'condition:typed.deafened'),
    (None, 'Physique', 'DEX', 'DEX'),
])
def test_mass_shared_option_reaches_selected_recipients(monkeypatch, tmp_path, talent, label, option, token):
    friendly = talent is None
    combat, table, mid, send, _ = fixture(monkeypatch, tmp_path,
        talents=['mass_mandate'] + ([talent] if talent else []), extra=True, third_ally=friendly)
    recipients = [S.SECOND, S.THIRD] if friendly else [S.FOE, S.THIRD]
    from combat.gate2_rolls import DeterministicRollAuthority
    def fixed(self, sides):
        count = self.counter
        self.counter += 1
        return 1, count
    monkeypatch.setattr(DeterministicRollAuthority, '_die', fixed)
    before = cold(tmp_path, mid).state.actors[S.OWNER].resources[QI]
    prefix = f'Mass {"Place" if friendly else "Fray"} Mandate: {label}'
    cid = next(o['candidate_id'] for g in table.state(mid)['menu']['actions']
               if prefix in g['label'] and '+ Augment' not in g['label']
               for o in g['options'] if recipients[0] in o.get('target_ids', []))
    answers, choices = [], []
    for _ in range(16):
        result = send(cid, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        key = prompt['context']['reaction_source_id']
        answer = {**prompt['context'], 'selection': 'DECLINE'}
        if key == 'choice:needle.mass_mandate':
            answer.update(selection='USE', option_ids=recipients)
        elif key == 'choice:needle.mandate_choice':
            choices.append(prompt)
            answer.update(selection='USE', option_ids=[option])
        elif prompt.get('choice'):
            answer.update(selection='USE', option_ids=[prompt['choice']['options'][0]['id']])
        answers.append(answer)
    else:
        raise AssertionError('too many prompts')
    # Observe committed state via a new service and verify journal replay first.
    engine = cold(tmp_path, mid)
    assert len(choices) == 1, 'one mandatory player-owned shared option must be requested'
    prompt = choices[0]
    names = [engine.state.actors[aid].display_name for aid in recipients]
    assert all(name in prompt['moment'] for name in names)
    assert 'same option' in prompt['moment']
    assert prompt['affected'] == names[0]
    assert prompt['by'] == names[0]
    assert prompt['trigger_actor'] == 'Owner'
    assert ' on Owner' not in prompt['moment']
    owner = engine.state.actors[S.OWNER]
    assert owner.resources[QI] == before - (4 if label == 'Brittle (creature)' else 2)
    assert owner.action_available is False
    source = owner.concentration.source_definition_id
    for aid in recipients:
        actor = engine.state.actors[aid]
        rows = [row.model_dump(mode='json') for row in (*actor.conditions.values(), *actor.modifiers.values())
                if row.source_definition_id == source]
        assert token in json.dumps(rows), rows
        if option == 'deafened':
            assert not any(row.condition_id == 'condition:typed.blinded' for row in actor.conditions.values())
    if friendly:
        assert not any(row.source_definition_id == source
                       for row in (*owner.conditions.values(), *owner.modifiers.values())
                       if getattr(row, 'condition_id', '') == 'condition:typed.check_mode')
    else:
        saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id in recipients]
        assert len(saves) == 2
        assert all(not e.payload['success'] for e in saves)
