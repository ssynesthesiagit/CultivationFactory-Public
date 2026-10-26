"""Recipient exits through CombatService/table intents, cold reload and replay."""
import copy
import pytest
from combat import concentration
from combat.canonical import canonical_sha256
from combat.ext import imbuement_mandates as M
from tests.test_a2_imbuement import fixture, cold, QI, S

PROBE = 'action:typed.test.recipient_probe'


def probes(bundles):
    owner = next(b for b in bundles if b['actor_id'] == S.OWNER)
    template = copy.deepcopy(owner['action_catalog'][0])
    template.update(source_definition_id=PROBE, display_name='Table recipient probe',
                    economy='NONE', target_kind='ANY_CREATURE', concentration=False, costs=[],
                    save=None, damage=None, damage_type=None, resolution_kind='TYPED', range_ft=120)
    template['parameters'] = {'typed': {'source': PROBE, 'range_ft': 120,
        'numbers': {'save_dc': 50}, 'duration': {'kind': 'instant'}, 'riders': [],
        'effects': [
            {'type': 'contest_against', 'actor_check': {'kind': 'check', 'ability': 'DEX', 'skill': 'Sleight of Hand'},
             'target_check': {'kind': 'check', 'ability': 'WIS', 'skill': 'Insight'}, 'on_success': [], 'on_fail': []},
            {'type': 'save', 'ability': 'WIS', 'dc': 50, 'applies_to': 'target', 'on_success': [], 'on_fail': []}]}}
    for action in owner['action_catalog']:
        if action.get('parameters', {}).get('mandate'):
            action['parameters']['typed']['numbers']['save_dc'] = 16
    owner['action_catalog'].append(template)
    owner['actor_template']['action_ids'].append(PROBE)
    owner.pop('bundle_sha256', None)
    owner['bundle_sha256'] = canonical_sha256(owner)


def resolve(send, cid, recipients=(), option=None):
    answers, prompts = [], []
    for _ in range(24):
        result = send(cid, answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']; prompts.append(prompt)
        key = prompt['context']['reaction_source_id']
        answer = {**prompt['context'], 'selection': 'DECLINE'}
        picked = None
        if key == 'choice:needle.mass_mandate': picked = list(recipients)
        elif key == 'choice:needle.mandate_choice': picked = [option]
        elif key == 'choice:needle.d20_floor_use': picked = ['use']
        elif key == 'choice:needle.expose_recheck': picked = ['repeat']
        elif prompt.get('choice') and key != 'choice:needle.d20_floor_keep':
            picked = [prompt['choice']['options'][0]['id']]
        if picked: answer.update(selection='USE', option_ids=picked)
        answers.append(answer)
    raise AssertionError('too many prompts')


def candidate(table, mid, label, target):
    return next(o['candidate_id'] for g in table.state(mid)['menu']['actions']
                if g['label'] == label for o in g['options'] if target in o.get('target_ids', []))


def rows(actor, source):
    return [r for r in (*actor.conditions.values(), *actor.modifiers.values())
            if r.source_definition_id == source and getattr(r, 'condition_id', '') not in (M.MASS_LOAD, concentration.HELD)]


@pytest.mark.parametrize('kind', ['Clarify', 'Expose'])
@pytest.mark.parametrize('other_copy', [False, True])
def test_mass_recipient_exit_preserves_roster_and_other_copy(monkeypatch, tmp_path, kind, other_copy):
    clarify = kind == 'Clarify'
    combat, table, mid, send, commit = fixture(monkeypatch, tmp_path,
        talents=['mass_mandate', 'layered_mandate', 'qi_written_mandate',
                 'clarify_and_cloud' if clarify else 'fortify_and_expose'],
        extra=True, third_ally=clarify, bundle_transform=probes)
    from combat.gate2_rolls import DeterministicRollAuthority
    raw = DeterministicRollAuthority.raw_d20
    cutoff = {'value': 10**9}
    def dice(self, **kwargs):
        natural = 20 if self.counter >= cutoff['value'] and 'expose' in kwargs['reason'] else 1
        def fixed(roller, sides):
            count = roller.counter; roller.counter += 1
            return min(natural, sides), count
        with monkeypatch.context() as patch:
            patch.setattr(DeterministicRollAuthority, '_die', fixed)
            return raw(self, **kwargs)
    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', dice)
    recipients = [S.SECOND, S.THIRD] if clarify else [S.FOE, S.THIRD]
    label = f'Mass {"Place" if clarify else "Fray"} Mandate: {kind}' + ('' if clarify else ' + Augment 2 CP')
    # Labels also print the Mass surcharge; select the exact ability variant.
    label = next(g['label'] for g in table.state(mid)['menu']['actions']
                 if g['label'].startswith(label) and (clarify or '+ Augment' in g['label']))
    before = cold(tmp_path, mid).state.actors[S.OWNER].resources[QI]
    resolve(send, candidate(table, mid, label, recipients[0]), recipients, 'WIS')
    engine = cold(tmp_path, mid); owner = engine.state.actors[S.OWNER]
    source, started = owner.concentration.source_definition_id, owner.concentration.started_sequence
    assert all(rows(engine.state.actors[aid], source) for aid in recipients)
    if other_copy:
        # A newer activation of precisely the same action must survive an older recipient's exit.
        for _ in range(12):
            commit(table.state(mid)['menu']['end_turn'])
            if table.state(mid)['menu']['actor_id'] == S.OWNER: break
        fresh_target = S.OWNER if clarify else S.THIRD
        resolve(send, candidate(table, mid, label, fresh_target), [fresh_target], 'WIS')
        engine = cold(tmp_path, mid)
        newer = engine.state.actors[S.OWNER].concentration.started_sequence
        assert newer > started
    cutoff['value'] = engine.roller.counter
    # The probe's low check uses Clarify; its failed save under Expose opens the actual optional recheck.
    prompts = resolve(send, candidate(table, mid, 'Table recipient probe', recipients[0]))
    engine = cold(tmp_path, mid); owner = engine.state.actors[S.OWNER]
    assert not rows(engine.state.actors[recipients[0]], source)
    assert rows(engine.state.actors[recipients[1]], source), 'another recipient must retain its effects'
    key = 'choice:needle.d20_floor_keep' if clarify else 'choice:needle.expose_recheck'
    exits = [p for p in prompts if p['context']['reaction_source_id'] == key]
    assert len(exits) == 1, 'the actual exit decision belongs to the player'
    assert exits[0]['context']['reactor_id'] == (S.OWNER if clarify else recipients[0])
    if clarify:
        assert owner.resources[QI] == before - (4 if other_copy else 2), 'declining keep costs no extra CP'
        assert M._mandate_weight(engine, owner, source, started) == 1
    else:
        saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == recipients[0]]
        assert saves[-2].payload['success'] is False and saves[-1].payload['success'] is True
    starts = concentration.copies(owner, source)
    assert (started in starts) == (clarify or not other_copy)
    if other_copy: assert newer in starts
    # Ending the final remaining recipient releases just its copy and its load marker.
    resolve(send, candidate(table, mid, 'Table recipient probe', recipients[1]))
    engine = cold(tmp_path, mid); owner = engine.state.actors[S.OWNER]
    assert not rows(engine.state.actors[recipients[1]], source)
    assert started not in concentration.copies(owner, source)
    assert not any(c.condition_id == M.MASS_LOAD and c.data.get('started') == started for c in owner.conditions.values())
    if clarify and other_copy:
        assert rows(owner, source) and newer in concentration.copies(owner, source)
    else:
        assert source not in concentration.sources(owner)


def test_set_mass_clarify_exit_preserves_newer_live_copy(monkeypatch, tmp_path):
    """A Set copy has explicit kept-row ownership; its exit cannot touch a live copy."""
    combat, table, mid, send, commit = fixture(monkeypatch, tmp_path,
        talents=['mass_mandate', 'layered_mandate', 'qi_written_mandate', 'clarify_and_cloud'],
        extra=True, bundle_transform=probes)
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.ext import persist_augment as P
    def fixed(self, sides):
        count = self.counter; self.counter += 1
        return 1, count
    monkeypatch.setattr(DeterministicRollAuthority, '_die', fixed)
    label = next(g['label'] for g in table.state(mid)['menu']['actions']
                 if g['label'].startswith('Mass Place Mandate: Clarify'))
    resolve(send, candidate(table, mid, label, S.SECOND), [S.SECOND, S.THIRD], 'WIS')
    engine = cold(tmp_path, mid)
    source = engine.state.actors[S.OWNER].concentration.source_definition_id
    started = engine.state.actors[S.OWNER].concentration.started_sequence
    commit(S.candidate(table, mid, 'Set Mandate:'))
    engine = cold(tmp_path, mid)
    assert len(P.persisted(engine, engine.state.actors[S.OWNER], P.MANDATE)) == 1
    assert source not in concentration.sources(engine.state.actors[S.OWNER])
    for _ in range(12):
        commit(table.state(mid)['menu']['end_turn'])
        if table.state(mid)['menu']['actor_id'] == S.OWNER: break
    resolve(send, candidate(table, mid, label, S.OWNER), [S.OWNER], 'WIS')
    engine = cold(tmp_path, mid); newest = engine.state.actors[S.OWNER].concentration.started_sequence
    before = engine.state.actors[S.OWNER].resources[QI]
    prompts = resolve(send, candidate(table, mid, 'Table recipient probe', S.SECOND))
    engine = cold(tmp_path, mid); owner = engine.state.actors[S.OWNER]
    assert any(p['context']['reaction_source_id'] == 'choice:needle.d20_floor_keep' for p in prompts)
    assert not rows(engine.state.actors[S.SECOND], source), 'ending removes both the replacement and its check benefit'
    assert rows(engine.state.actors[S.THIRD], source) and rows(owner, source)
    assert concentration.copies(owner, source) == [newest]
    assert owner.resources[QI] == before
    assert M._mandate_weight(engine, owner, source, started) == 1
    resolve(send, candidate(table, mid, 'Table recipient probe', S.THIRD))
    engine = cold(tmp_path, mid); owner = engine.state.actors[S.OWNER]
    assert not rows(engine.state.actors[S.THIRD], source)
    assert not P.persisted(engine, owner, P.MANDATE)
    assert rows(owner, source) and concentration.copies(owner, source) == [newest]
