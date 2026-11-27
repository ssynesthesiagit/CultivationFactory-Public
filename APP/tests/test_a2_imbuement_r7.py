"""Live Mass copy accounting through accepted table intents, reload and replay."""
import pytest

from combat import concentration
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from tests.test_a2_imbuement import fixture, cold, turn, M, S


@pytest.mark.parametrize('extra_load', [False, True])
def test_same_live_mass_option_keeps_weight_and_evicts_oldest(monkeypatch, tmp_path, extra_load):
    fourth = FACTORY_ACTOR_PREFIX + 'r7-fourth'
    finish = CombatService._finish_factory_match

    def with_fourth(self, *args, **kwargs):
        args = list(args)
        doc = S.sheet([], cl=17)
        doc['identity']['display_name'] = 'Fourth'
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 500
        args[0].append(S.compile_character(doc, actor_id=fourth))
        args[1].append(fourth)
        args[2][fourth] = 'team:a'
        args[3][fourth] = {'x': 6, 'y': 6}
        args[6].append(fourth)
        kwargs['control_modes'][fourth] = 'MANUAL'
        return finish(self, *args, **kwargs)

    monkeypatch.setattr(CombatService, '_finish_factory_match', with_fourth)
    combat, table, mid, send, commit = fixture(monkeypatch, tmp_path,
        insights=['insight.dual-mandate-adept'] if extra_load else [],
        talents=['mass_mandate', 'layered_mandate'], extra=True)

    def selected_cast(recipients):
        cid = S.candidate(table, mid, 'Mass Place Mandate: Quicken', recipients[0])
        answers = []
        prompts = []
        for _ in range(16):
            result = send(cid, answers)
            if result['status'] == 'COMMITTED':
                assert len(prompts) == 1, 'the player chooses the recipient roster'
                assert prompts[0]['context']['reactor_id'] == S.OWNER
                return
            assert result['status'] == 'REACTION_REQUIRED', result
            prompt = result['reaction']
            answer = {**prompt['context'], 'selection': 'DECLINE'}
            if prompt.get('choice'):
                mass = prompt['context']['reaction_source_id'] == 'choice:needle.mass_mandate'
                if mass:
                    prompts.append(prompt)
                answer.update(selection='USE', option_ids=recipients if mass else
                              [prompt['choice']['options'][0]['id']])
            answers.append(answer)
        raise AssertionError('too many prompts')

    older_recipients = [S.OWNER, S.SECOND, S.THIRD]
    selected_cast(older_recipients)
    engine = cold(tmp_path, mid)
    owner = engine.state.actors[S.OWNER]
    source = owner.concentration.source_definition_id
    started = owner.concentration.started_sequence
    older_marker = next(c for c in owner.conditions.values() if c.condition_id == M.MASS_LOAD)
    assert older_marker.data['recipients'] == older_recipients
    assert M._mandate_weight(engine, owner, source, started) == 2
    assert M.load(engine, owner, 4) == (3 if extra_load else 2)
    turn(table, mid, commit)
    selected_cast([fourth])
    # cold() independently loads CombatService and replays the committed mechanical journal.
    engine = cold(tmp_path, mid)
    owner = engine.state.actors[S.OWNER]
    newest = owner.concentration.started_sequence
    assert owner.concentration.source_definition_id == source and newest > started
    assert M._mandate_weight(engine, owner, source, newest) == 1
    starts = concentration.copies(owner, source)
    markers = [c for c in owner.conditions.values() if c.condition_id == M.MASS_LOAD]
    if extra_load:
        assert starts == [started, newest]
        assert M._mandate_weight(engine, owner, source, started) == 2, 'older live roster still costs two slots'
        assert {c.data['started'] for c in markers} == {started, newest}
        assert older_marker.instance_id in owner.conditions
        assert not any(e.event_type == 'CONDITION_REMOVED' and
                       e.payload.get('instance_id') == older_marker.instance_id for e in engine.events)
    else:
        assert starts == [newest], 'Load two must evict the older weight-two activation'
        assert [c.data['started'] for c in markers] == [newest]
        removed = [e for e in engine.events if e.event_type == 'CONDITION_REMOVED' and
                   e.payload.get('instance_id') == older_marker.instance_id]
        assert len(removed) == 1 and removed[0].payload['reason'] == 'MANDATE_LOAD'
    for aid in older_recipients:
        assert any(m.source_definition_id == source for m in engine.state.actors[aid].modifiers.values()) == extra_load
    assert any(m.source_definition_id == source for m in engine.state.actors[fourth].modifiers.values())
