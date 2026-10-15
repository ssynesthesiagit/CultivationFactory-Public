"""Oath-Ledger acquisition, owner facts, controller consent and cold journals.

No synthetic ownership rows, source/activity receipts, model servers or GUI.
Only installed-sheet I/O is substituted; acquisition/compilation/commit/reload
and actual native movement remain production paths.
"""
import copy
import json
from pathlib import Path

import pytest

from combat import table_advance
from combat.ext.oath_ledger import PREFIX, ROWS, RECORD, MARK, QI
from combat.factory_compiler import compile_character
from combat.feature_access import acquire
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
A = 'actor:factory.ledger'
B = 'actor:factory.party'
PATH = 'tianxia.path.qi_cultivation'
ACCESS = {'kind': 'scripture', 'classification': 'Restricted Scripture', 'reference': 'campaign:acquired-ledger-scripture'}
PROJECT = '0badc0de-0000-4000-8000-000000000058'


def base_sheet(cl=18):
    doc = sheet([], cl=cl, name='Ledger keeper')
    doc['path_and_subpath'] = {'path_record_ids': [PATH]}
    return doc


def setup(tmp_path, *, owned=True):
    original = base_sheet()
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    combat._factory_owner_sheet = lambda project_id: table_advance.apply(original, table.buttons.get(project_id).get('advancement'))
    if owned:
        for fid in ROWS:
            table.acquire_feature(PROJECT, fid, ACCESS)
    owner = combat._factory_owner_sheet(PROJECT)
    bundles = [compile_character(owner, actor_id=A, reaction_plan={'ask': True}),
               compile_character(base_sheet(), actor_id=B, reaction_plan={'ask': True})]
    mid = combat._finish_factory_match(bundles, [A, B], {A: 'team:a', B: 'team:b'},
        {A: {'x': 3, 'y': 6}, B: {'x': 4, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [A], [B],
        control_modes={A: 'MANUAL', B: 'MANUAL'}, match_seed='OATH-LEDGER',
        display_name='Witnessed obligations', maximum_rounds=20)['match_id']
    advance(combat, table, mid, A)
    return combat, table, mid


def cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def commit(combat, table, mid, candidate, picks=()):
    answers = []
    prompts = []
    for _ in range(30):
        state = table.state(mid)
        menu = state['menu']
        result = table.act(mid, candidate.candidate_id, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        answer = {**prompt['context'], 'selection': 'DECLINE'}
        if prompt.get('choice'):
            ids = [o['id'] for o in prompt['choice']['options']]
            chosen = next((p for p in picks if p in ids), None)
            if chosen is not None:
                answer.update(selection='USE', option_ids=[chosen])
            elif not prompt['choice'].get('allow_decline'):
                answer.update(selection='USE', option_ids=ids[:prompt['choice'].get('minimum_selections', 1)])
        answers.append(answer)
    raise AssertionError('Unresolved native choice')


def advance(combat, table, mid, actor):
    for _ in range(8):
        engine = combat._load_session(mid).engine
        if engine.state.current_actor_id == actor:
            return
        commit(combat, table, mid, next(c for c in engine.legal_candidates() if c.kind.value == 'END_TURN'))
    raise AssertionError(actor)


def use(combat, table, mid, operation, picks=()):
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id.endswith('.oath_ledger.' + operation))
    return commit(combat, table, mid, candidate, picks)


def document(engine, *, duration=3600):
    return {'record_id': 'delivery-promise', 'subject_id': B, 'subject_name': 'The accepted passage term',
        'subject_kind': 'creature', 'position': {'x': 4, 'y': 6},
        'source_reference': 'campaign:terms-stated-aloud', 'witness_ids': [A, B],
        'valid_through_round': engine.state.round_number + 5,
        'answers': {'oath_ledger': {'category': 'witnessed_obligation', 'visible_sign': 'The terms are spoken aloud.',
            'source_cl': 18, 'fact': json.dumps({'obligation_id': 'passage', 'parties': [B], 'beneficiaries': [A],
                'term': 'Reach the east doorway while escorting the keeper.', 'duration': 'One hour',
                'acceptance': 'The traveler explicitly agrees after hearing the condition.',
                'fulfillment': 'Reach the agreed square under pressure.', 'breach': 'Knowingly abandon the route.',
                'release': 'The keeper announces release.', 'duration_seconds': duration,
                'comprehensible': 1, 'possible': 1, 'meaningful': 1, 'self_manufactured': 0,
                'fulfilled_by': [{'actor_id': B, 'kind': 'MOVE', 'source_definition_id': 'system:combat.movement',
                    'destination': {'x': 5, 'y': 6}, 'aware_actor_ids': [B],
                    'description': 'Reach the east doorway under pressure.'}]})}}}


def record(combat, table, mid, doc):
    version = combat._load_session(mid).engine.state.state_version
    assert table.record_fact(mid, doc, expected_state_version=version)['status'] == 'COMMITTED'


@pytest.mark.parametrize('fid,level', ROWS.items())
def test_actual_restricted_acquisition_and_boundaries(fid, level):
    doc = base_sheet(level)
    acquired = acquire(doc, fid, ACCESS)
    assert fid in acquired['path_and_subpath']['path_feature_record_ids']
    assert not doc.get('feature_access')
    assert acquired['feature_access'][fid] == ACCESS
    with pytest.raises(ValueError, match='CL'):
        acquire(base_sheet(level - 1), fid, ACCESS)
    with pytest.raises(ValueError, match='classification'):
        acquire(doc, fid, {**ACCESS, 'classification': 'Common'})
    wrong = copy.deepcopy(doc)
    wrong['path_and_subpath']['path_record_ids'] = []
    with pytest.raises(ValueError, match='Path'):
        acquire(wrong, fid, ACCESS)
    suppressed = copy.deepcopy(acquired)
    suppressed['identity']['effective_path_cls'] = {PATH: level - 1}
    bundle = compile_character(suppressed, actor_id=A)
    assert not any(r.get('feature_id') == fid for r in bundle['typed_passives'])


def test_owner_fact_is_not_acceptance_and_refusal_never_charges(tmp_path):
    combat, table, mid = setup(tmp_path)
    before = cold(tmp_path, mid).state.actors[A].resources[QI]
    record(combat, table, mid, document(combat._load_session(mid).engine))
    assert not any(c.condition_id == RECORD for c in cold(tmp_path, mid).state.actors[A].conditions.values())
    prompts = use(combat, table, mid, 'record')
    assert any('accept' in str(p).lower() for p in prompts)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[A].resources[QI] == before
    assert engine.state.actors[A].reaction_available
    assert not any(c.condition_id in {RECORD, MARK} for a in engine.state.actors.values() for c in a.conditions.values())


def test_acceptance_real_move_mark_payment_and_cold_replay(tmp_path):
    combat, table, mid = setup(tmp_path)
    record(combat, table, mid, document(combat._load_session(mid).engine))
    before = cold(tmp_path, mid).state.actors[A].resources[QI]
    use(combat, table, mid, 'record', picks=['accept'])
    engine = cold(tmp_path, mid)
    assert engine.state.actors[A].resources[QI] == before - 1
    assert not engine.state.actors[A].reaction_available
    assert any(c.condition_id == RECORD for c in engine.state.actors[A].conditions.values())
    # The reaction refreshes on the owner's next real turn; unrelated movement
    # produces no mark, and the exact committed destination does.
    commit(combat, table, mid, next(c for c in engine.legal_candidates() if c.kind.value == 'END_TURN'))
    advance(combat, table, mid, A)
    engine = combat._load_session(mid).engine
    commit(combat, table, mid, next(c for c in engine.legal_candidates() if c.kind.value == 'END_TURN'))
    advance(combat, table, mid, B)
    engine = combat._load_session(mid).engine
    move = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE' and c.destination.x == 5 and c.destination.y == 6)
    commit(combat, table, mid, move, picks=['record'])
    engine = cold(tmp_path, mid)
    held = [c for c in engine.state.actors[B].conditions.values() if c.condition_id == MARK]
    assert len(held) == 1 and held[0].data['kind'] == 'fulfillment'


def test_unowned_default_inert_and_invalid_obligation_rejected(tmp_path):
    combat, table, mid = setup(tmp_path, owned=False)
    engine = cold(tmp_path, mid)
    assert not any('.oath_ledger.' in c.source_definition_id for c in engine.legal_candidates())
    bad = document(engine)
    terms = json.loads(bad['answers']['oath_ledger']['fact'])
    terms['possible'] = 0
    bad['answers']['oath_ledger']['fact'] = json.dumps(terms)
    with pytest.raises(Exception, match='possible'):
        record(combat, table, mid, bad)
    assert not any(e.event_type == 'TABLE_FACT_RECORDED' for e in cold(tmp_path, mid).events)
