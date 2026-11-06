"""Read the Thread through owner acquisition, native intents and cold replay.

No injected ownership, effect probes, live model calls or browsers. Campaign
observations enter exclusively through the new owner table producer.
"""
import copy
from pathlib import Path

import pytest

from combat import table_advance, typed_executor
from combat.ext.fate_reader import READ, BRANCH, THREAD_ANSWER, THREAD_QUESTIONS
from combat.factory_compiler import compile_character
from combat.feature_access import acquire
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.table_facts import TableFact, records
from combat.target_knowledge import recent_events
from tests.test_riders_c8 import sheet, MIND_SPIKE
from tests.test_a2_group_traditions_2 import use, commit, advance, end, cold, held

ROOT = Path(__file__).resolve().parents[1]
ME = 'actor:factory.thread-reader'
FOE = 'actor:factory.thread-subject'
ALLY = 'actor:factory.thread-ally'
PATH = 'tianxia.path.spirit_awakening'
ACCESS = {'kind': 'teacher', 'classification': 'Secret', 'reference': 'campaign:recorded-secret-teacher'}
PROJECT = '0badc0de-0000-4000-8000-000000000001'
CELL_SOURCE = 'test:seamfix-read-thread.cell-blast'


def add_cell_action(bundle):
    """Give a creature a native aimed (CELL) action to fulfil or miss a prediction.

    A synthetic native action is the existing convention for testing exact cell
    aim (tests/test_area_shapes.py); the aim itself travels the real engine and
    table placement paths below.
    """
    from combat.canonical import canonical_sha256
    typed = {'effects': [{'type': 'damage', 'dice': {'count': 1, 'sides': 4}, 'damage_types': ['force']}],
             'numbers': {'save_dc': 100, 'cl': 6, 'pb': 3, 'key_mod': 1},
             'duration': {'kind': 'instant'}, 'riders': [],
             'area': {'shape': 'sphere', 'size_ft': 10}}
    bundle['action_catalog'].append({'source_definition_id': CELL_SOURCE, 'display_name': 'Test: cell blast',
        'owner_id': bundle['actor_id'], 'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'CELL',
        'range_ft': 30, 'radius_ft': 10,
        'parameters': {'typed': typed, 'expected_damage': 2, 'description': 'Aimed test blast'}})
    bundle['actor_template']['action_ids'].append(CELL_SOURCE)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def setup_scene(tmp_path, *, cl=6, effective=None, auto=False, foe_auto=False, ally_ask=True, resonance=60, foe_position=(4, 6), foe_cell=False):
    original = sheet([], cl=cl, resonance=resonance)
    original['path_and_subpath']['path_record_ids'] = [PATH]
    if effective is not None:
        original['identity']['effective_path_cls'] = {PATH: effective}
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    # The installed-sheet reader is the only substituted I/O. Acquisition,
    # overlay persistence, compiler, combat/table and journals are real.
    combat._factory_owner_sheet = lambda project_id: table_advance.apply(
        original, table.buttons.get(project_id).get('advancement'))
    table.acquire_feature(PROJECT, READ, ACCESS)
    acquired = combat._factory_owner_sheet(PROJECT)
    assert acquired['feature_access'][READ] == ACCESS
    assert not acquired.get('spheres_and_talents', {}).get('sphere_record_ids')
    docs = [acquired, sheet([MIND_SPIKE], cl=6), sheet([], cl=6)]
    for doc in docs:
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
    bundles = [compile_character(doc, actor_id=actor_id, reaction_plan={'ask': ally_ask if actor_id == ALLY else True})
               for doc, actor_id in zip(docs, (ME, FOE, ALLY))]
    if foe_cell:
        add_cell_action(bundles[1])
    mid = combat._finish_factory_match(bundles, [ME, FOE, ALLY],
        {ME: 'team:a', FOE: 'team:b', ALLY: 'team:a'},
        {ME: {'x': 3, 'y': 6}, FOE: {'x': foe_position[0], 'y': foe_position[1]}, ALLY: {'x': 3, 'y': 7}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [ME, ALLY], [FOE],
        control_modes={ME: 'LOCAL_AUTO' if auto else 'MANUAL', FOE: 'LOCAL_AUTO' if foe_auto else 'MANUAL', ALLY: 'MANUAL'},
        match_seed='READ-THREAD-NATIVE', display_name='Observed branch', maximum_rounds=20)['match_id']
    advance(combat, table, mid, ME)
    return combat, table, mid


def fact_document(combat, mid, *, kind='creature', question=None, source_cl=0, dc=None,
                  aware=True, condition='', predictions=True, witness=ME, action_prediction=None):
    engine = combat._load_session(mid).engine
    action = next(a for a in engine.action_catalog.values() if a.owner_id == FOE and a.display_name == 'Mind Spike')
    prediction = action_prediction if action_prediction is not None else {
        'actor_id': FOE, 'kind': 'ACTION', 'source_definition_id': action.source_definition_id,
        'target_ids': [ME], 'aware_actor_ids': [FOE] if aware else [],
        'description': 'Use Mind Spike against the reader', 'requires_facts': []}
    answer = {'fact': 'An exposed approach leaves the reader in the next attack line.',
              'category': 'Secret protection', 'visible_sign': 'A silver thread knots around the visible weapon.',
              'source_cl': source_cl, 'check_dc': dc, 'condition': condition,
              'predictions': [prediction] if predictions else []}
    return {'record_id': 'observed-branch', 'subject_id': FOE if kind == 'creature' else f'observed-{kind}',
            'subject_name': 'The observed approach', 'subject_kind': kind,
            'position': {'x': 4, 'y': 6}, 'source_reference': 'campaign:owner-recorded-visible-approach',
            'witness_ids': [witness], 'valid_through_round': engine.state.round_number + 3,
            'answers': {key: copy.deepcopy(answer) for key in THREAD_QUESTIONS if question is None or key == question}}


def record(combat, table, mid, document):
    version = combat._load_session(mid).engine.state.state_version
    assert table.record_fact(mid, document, expected_state_version=version)['status'] == 'COMMITTED'


def record_move(combat, table, mid, destination):
    doc = fact_document(combat, mid)
    for answer in doc['answers'].values():
        answer['predictions'] = [{'actor_id': FOE, 'kind': 'MOVE', 'source_definition_id': 'system:combat.movement',
            'target_ids': [], 'destination': destination, 'aware_actor_ids': [FOE], 'description': 'Move to the exposed approach'}]
    record(combat, table, mid, doc)
    use(combat, table, mid, 'Read the Thread', picks=('danger',))
    use(combat, table, mid, 'Mark the Branch: record a prediction', picks=(FOE, '0'))


@pytest.mark.parametrize('kind,question', [
    ('creature', 'next_action'), ('object', 'protection'), ('location', 'danger'),
    ('plan', 'improve'), ('event', 'fail'), ('creature', 'authority'),
    ('creature', 'branch'), ('event', 'omen'), ('object', 'cause')])
def test_native_subject_question_acquisition_commit_reload(tmp_path, kind, question):
    s, t, m = setup_scene(tmp_path)
    doc = fact_document(s, m, kind=kind, condition='If the approach remains exposed')
    record(s, t, m, doc)
    before = cold(tmp_path, m).state.actors[ME].resources['resource:core.resonance']
    prompts = use(s, t, m, 'Read the Thread', picks=('observed-branch', question))
    question_prompt = next(p for p in prompts if p.get('choice', {}).get('choice_id') == 'choice:needle.fate_reader.question'
                          or 'chance of success' in str(p))
    assert len(question_prompt['choice']['options']) == len(THREAD_QUESTIONS)
    e = cold(tmp_path, m)
    answer = next(ev for ev in reversed(e.events) if ev.event_type == 'OBSERVATION_ANSWERED')
    assert answer.payload['question'] == question
    assert answer.payload['answer'].startswith('If the approach remains exposed:')
    assert e.state.actors[ME].resources['resource:core.resonance'] == before - 3
    assert not e.state.actors[ME].action_available
    assert held(e.state.actors[ME], THREAD_ANSWER)
    assert not any(ev.event_type == 'GM_RIDER' and ev.source_definition_id == READ for ev in e.events)
    assert records(e, e.state.actors[ME])['observed-branch'].subject_kind == kind
    assert not records(e, e.state.actors[ALLY])
    assert not any(ev['event_type'] in ('TABLE_FACT_RECORDED', 'OBSERVATION_ANSWERED')
                   for ev in recent_events(e, e.state.actors[ALLY], e.events))


@pytest.mark.parametrize('boundary', ['missing_access', 'wrong_path', 'below_cl', 'suppressed', 'wrong_owner'])
def test_access_and_effective_cl_boundaries(boundary):
    doc = sheet([], cl=6)
    doc['path_and_subpath']['path_record_ids'] = [PATH]
    if boundary != 'missing_access':
        doc = acquire(doc, READ, ACCESS)
    else:
        doc['path_and_subpath']['path_feature_record_ids'] = [READ]
    if boundary == 'wrong_path':
        doc['path_and_subpath']['path_record_ids'] = ['tianxia.path.qi_cultivation']
    elif boundary == 'below_cl':
        doc['identity']['cultivation_level'] = 5
    elif boundary == 'suppressed':
        doc['identity']['effective_path_cls'] = {PATH: 5}
    elif boundary == 'wrong_owner':
        doc = sheet([], cl=6)
    bundle = compile_character(doc, actor_id=ME)
    assert not any(a['display_name'] in ('Read the Thread', 'Mark the Branch: record a prediction')
                   for a in bundle['action_catalog'])


@pytest.mark.parametrize('source', [
    {'kind': 'teacher', 'classification': 'Secret', 'reference': ''},
    {'kind': 'event', 'classification': 'Ordinary', 'reference': 'permission'},
    {'kind': 'name', 'classification': 'Secret', 'reference': 'Fate Reader'}])
def test_acquisition_requires_explicit_source(source):
    doc = sheet([], cl=6)
    doc['path_and_subpath']['path_record_ids'] = [PATH]
    with pytest.raises(ValueError):
        acquire(doc, READ, source)


@pytest.mark.parametrize('source_cl,dc,success', [(0, 100, True), (5, 100, True), (6, 100, False), (8, 1, True), (8, None, True)])
def test_authority_check_and_visible_failure(tmp_path, source_cl, dc, success):
    s, t, m = setup_scene(tmp_path)
    record(s, t, m, fact_document(s, m, source_cl=source_cl, dc=dc))
    use(s, t, m, 'Read the Thread', picks=('danger',))
    e = cold(tmp_path, m)
    answer = next(ev for ev in reversed(e.events) if ev.event_type == 'OBSERVATION_ANSWERED')
    assert answer.payload['success'] is success
    checks = [ev for ev in e.events if ev.event_type == 'CHECK_ROLLED' and ev.source_definition_id == READ]
    assert bool(checks) == (source_cl >= 6 and dc is not None)
    if not success:
        assert answer.payload['answer'] == 'Secret protection is obscured. Visible sign: A silver thread knots around the visible weapon..'
        assert not held(e.state.actors[ME], THREAD_ANSWER)
        assert not any(c.display_name == 'Mark the Branch: record a prediction' for c in e.legal_candidates())


@pytest.mark.parametrize('aware', [True, False])
def test_knowing_exact_nonattack_action_marks_once_and_offturn_step(tmp_path, aware):
    s, t, m = setup_scene(tmp_path)
    record(s, t, m, fact_document(s, m, aware=aware))
    use(s, t, m, 'Read the Thread', picks=('danger',))
    use(s, t, m, 'Mark the Branch: record a prediction', picks=(FOE, '0'))
    advance(s, t, m, FOE)
    prompts = use(s, t, m, 'Mind Spike', ME, picks=(ME, 'cell:2,6'))
    e = cold(tmp_path, m)
    assert typed_executor.bears_mark(e.state.actors[FOE], ME, 'Resonance') is aware
    assert bool(held(e.state.actors[FOE], BRANCH)) is not aware
    if aware:
        assert any('Mind Spike' in str(p) and 'Read the Thread' in str(p) for p in prompts)
        assert (e.state.actors[ME].position.x, e.state.actors[ME].position.y) == (2, 6)
        moves = [ev for ev in e.events if ev.event_type == 'MOVEMENT_COMMITTED' and ev.actor_id == ME]
        assert moves[-1].payload['cost_ft'] == 0
        assert not any(ev.event_type == 'REACTION_RESOLVED' and ev.actor_id == FOE for ev in e.events)


def test_exact_target_and_unfulfilled_expiry(tmp_path):
    s, t, m = setup_scene(tmp_path)
    record(s, t, m, fact_document(s, m))
    use(s, t, m, 'Read the Thread', picks=('danger',))
    use(s, t, m, 'Mark the Branch: record a prediction', picks=(FOE, '0'))
    advance(s, t, m, FOE)
    use(s, t, m, 'Mind Spike', ALLY)
    e = cold(tmp_path, m)
    assert held(e.state.actors[FOE], BRANCH)
    assert not typed_executor.bears_mark(e.state.actors[FOE], ME, 'Resonance')
    advance(s, t, m, ME)
    assert held(cold(tmp_path, m).state.actors[FOE], BRANCH)
    end(s, t, m)
    assert not held(cold(tmp_path, m).state.actors[FOE], BRANCH)


def test_record_correction_range_horizon_and_private_audience(tmp_path):
    s, t, m = setup_scene(tmp_path)
    doc = fact_document(s, m)
    doc['witness_ids'] = [ALLY]
    record(s, t, m, doc)
    e = cold(tmp_path, m)
    assert not records(e, e.state.actors[ME])
    assert len(records(e, e.state.actors[ALLY])) == 1
    with pytest.raises(ValueError, match='fight changed'):
        t.record_fact(m, doc, expected_state_version=-1)
    doc['witness_ids'] = [ME]
    doc['subject_kind'] = 'location'
    doc['position'] = {'x': 30, 'y': 6}
    record(s, t, m, doc)
    from combat.ext.fate_reader import thread_subjects
    e = cold(tmp_path, m)
    assert not thread_subjects(e, e.state.actors[ME])
    doc['position'] = {'x': 4, 'y': 6}
    doc['active'] = False
    record(s, t, m, doc)
    assert not records(cold(tmp_path, m))
    doc['active'] = True
    doc['valid_through_round'] = 1
    with pytest.raises(ValueError):
        TableFact.model_validate({**doc, 'horizon': 'next year'})
    # The named horizon test must test round expiry, not only schema validation:
    # a record past its printed round horizon is gone from every viewer's facts.
    for _ in range(3):
        end(s, t, m)  # ME, FOE, ALLY (three fighters) -> back to ME in round 2
    assert cold(tmp_path, m).state.round_number >= 2
    record(s, t, m, doc)
    assert not records(cold(tmp_path, m))


@pytest.mark.parametrize('blocked', [False, True])
def test_native_movement_completion_requires_actual_endpoint(tmp_path, monkeypatch, blocked):
    s, t, m = setup_scene(tmp_path, foe_position=(6, 6))
    record_move(s, t, m, {'x': 5, 'y': 6})
    advance(s, t, m, FOE)
    e = cold(tmp_path, m)
    move = next(c for c in e.legal_candidates() if c.kind.value == 'MOVE' and c.destination.x == 5 and c.destination.y == 6)
    if blocked:
        # Fault injection at the native movement seam. No injected receipt,
        # ownership or effect; the real resolver emits its interrupted path.
        cls = type(e)
        original = cls._voluntary_step_allowed
        monkeypatch.setattr(cls, '_voluntary_step_allowed', lambda self, actor, previous, destination:
                            False if actor.entity_id == FOE else original(self, actor, previous, destination))
    commit(s, t, m, move)
    e = cold(tmp_path, m)
    assert typed_executor.bears_mark(e.state.actors[FOE], ME, 'Resonance') is not blocked
    assert bool(held(e.state.actors[FOE], BRANCH)) is blocked
    if blocked:
        event = next(ev for ev in reversed(e.events) if ev.event_type == 'MOVEMENT_COMMITTED' and ev.actor_id == FOE)
        assert event.payload.get('interrupted') and len(event.payload['path']) == 1


def test_human_reader_owns_ally_step_on_ai_turn(tmp_path):
    s, t, m = setup_scene(tmp_path, foe_auto=True)
    record(s, t, m, fact_document(s, m))
    use(s, t, m, 'Read the Thread', picks=('danger',))
    use(s, t, m, 'Mark the Branch: record a prediction', picks=(FOE, '0'))
    advance(s, t, m, FOE)
    prompts = use(s, t, m, 'Mind Spike', ME, picks=(ALLY, 'cell:2,7'), auto=True)
    assert len(prompts) >= 2
    e = cold(tmp_path, m)
    assert (e.state.actors[ALLY].position.x, e.state.actors[ALLY].position.y) == (2, 7)
    assert typed_executor.bears_mark(e.state.actors[FOE], ME, 'Resonance')
    assert len([ev for ev in e.events if ev.event_type == 'CONDITION_APPLIED'
                and ev.payload.get('condition_id') == typed_executor.mark_condition_id('Resonance', ME)]) == 1


@pytest.mark.parametrize('known', [False, True])
def test_automatic_reader_uses_only_its_own_recorded_observation(tmp_path, known):
    s, t, m = setup_scene(tmp_path, auto=True)
    record(s, t, m, fact_document(s, m, witness=ME if known else ALLY))
    use(s, t, m, 'Read the Thread', auto=True)
    e = cold(tmp_path, m)
    assert bool([ev for ev in e.events if ev.event_type == 'OBSERVATION_ANSWERED']) is known
    assert not any(ev['event_type'] == 'TABLE_FACT_RECORDED' for ev in recent_events(e, e.state.actors[ME], e.events))


@pytest.mark.parametrize('resonance,effective', [(2, 6), (60, 5)])
def test_insufficient_resonance_and_suppressed_native_menu(tmp_path, resonance, effective):
    s, t, m = setup_scene(tmp_path, resonance=resonance, effective=effective)
    e = cold(tmp_path, m)
    assert not any(c.display_name == 'Read the Thread' for c in e.legal_candidates())
    assert any(a.display_name == 'Read the Thread' for a in e.action_catalog.values() if a.owner_id == ME) is (effective >= 6)


@pytest.mark.parametrize('revoke', ['correction', 'withdraw', 'condition'])
def test_branch_uses_current_source_and_conditional_prerequisites(tmp_path, revoke):
    s, t, m = setup_scene(tmp_path)
    doc = fact_document(s, m, condition='If the recorded oath remains intact')
    if revoke == 'condition':
        for answer in doc['answers'].values():
            answer['predictions'][0]['requires_facts'] = ['oath-intact']
    record(s, t, m, doc)
    use(s, t, m, 'Read the Thread', picks=('danger',))
    use(s, t, m, 'Mark the Branch: record a prediction', picks=(FOE, '0'))
    if revoke != 'condition':
        doc['active'] = revoke != 'withdraw'
        doc['answers']['danger']['fact'] = 'The recorded approach changed.'
        record(s, t, m, doc)
    advance(s, t, m, FOE)
    use(s, t, m, 'Mind Spike', ME)
    e = cold(tmp_path, m)
    assert not typed_executor.bears_mark(e.state.actors[FOE], ME, 'Resonance')
    assert held(e.state.actors[FOE], BRANCH)


def test_committed_known_native_reaction_fulfills_branch(tmp_path):
    from tests.hunt12_support import send
    s, t, m = setup_scene(tmp_path)
    doc = fact_document(s, m)
    for answer in doc['answers'].values():
        answer['predictions'] = [{'actor_id': FOE, 'kind': 'REACTION',
            'source_definition_id': 'system:combat.opportunity_attack', 'target_ids': [ME],
            'aware_actor_ids': [FOE], 'description': 'Make an opportunity attack against the reader'}]
    record(s, t, m, doc)
    use(s, t, m, 'Read the Thread', picks=('danger',))
    use(s, t, m, 'Mark the Branch: record a prediction', picks=(FOE, '0'))
    e = cold(tmp_path, m)
    move = next(c for c in e.legal_candidates() if c.kind.value == 'MOVE' and c.destination.x == 2 and c.destination.y == 6)
    answers = []
    for _ in range(12):
        response = send(s, t, m, move, answers)
        if response['status'] == 'COMMITTED':
            break
        assert response['status'] == 'REACTION_REQUIRED'
        prompt = response['reaction']
        answer = {**prompt['context'], 'selection': 'DECLINE'}
        if not prompt.get('choice') and prompt['context'].get('reactor_id') == FOE:
            answer['selection'] = 'USE'
        answers.append(answer)
    else:
        raise AssertionError('The native opportunity reaction did not finish.')
    e = cold(tmp_path, m)
    assert any(ev.event_type == 'REACTION_RESOLVED' and ev.actor_id == FOE
               and ev.source_definition_id == 'system:combat.opportunity_attack' for ev in e.events)
    assert typed_executor.bears_mark(e.state.actors[FOE], ME, 'Resonance')
    assert not held(e.state.actors[FOE], BRANCH)


def test_branch_step_only_exempts_the_predicted_creature(tmp_path):
    s, t, m = setup_scene(tmp_path, ally_ask=False)
    version = cold(tmp_path, m).state.state_version
    s.change_relations(m, change={'kind': 'ACTOR_RELATION', 'subject': ME, 'other': ALLY, 'relation': 'ENEMY'},
                       expected_state_version=version)
    record(s, t, m, fact_document(s, m))
    use(s, t, m, 'Read the Thread', picks=('danger',))
    use(s, t, m, 'Mark the Branch: record a prediction', picks=(FOE, '0'))
    advance(s, t, m, FOE)
    use(s, t, m, 'Mind Spike', ME, picks=(ME, 'cell:1,6'))
    e = cold(tmp_path, m)
    assert (e.state.actors[ME].position.x, e.state.actors[ME].position.y) == (1, 6)
    windows = [ev for ev in e.events if ev.event_type == 'REACTION_WINDOW_OPENED'
               and ev.source_definition_id == 'system:combat.opportunity_attack']
    assert any(ALLY in ev.target_ids for ev in windows)
    assert not any(FOE in ev.target_ids for ev in windows)


PREDICTED_CELL = {'x': 3, 'y': 6}   # on the reader
OTHER_CELL = {'x': 3, 'y': 7}       # on the ally


def cell_prediction(aim):
    return {'actor_id': FOE, 'kind': 'ACTION', 'source_definition_id': CELL_SOURCE,
            'target_ids': [], 'destination': aim, 'aware_actor_ids': [FOE],
            'description': 'Aim the test blast at the marked square', 'requires_facts': []}


def predicted_branch(s, t, m, prediction):
    record(s, t, m, fact_document(s, m, action_prediction=prediction))
    use(s, t, m, 'Read the Thread', picks=('danger',))
    use(s, t, m, 'Mark the Branch: record a prediction', picks=(FOE, '0'))


def commit_placement(s, t, m, source, cell):
    """Commit the service's lazy CELL placeholder and answer its square picker."""
    state = t.state(m)
    menu = state['menu']
    group = next(g for g in menu['actions'] if g['source_definition_id'] == source)
    assert group.get('placement_picker'), group
    candidate_id = group['options'][0]['candidate_id']
    cell_id = f'cell:{cell["x"]},{cell["y"]}' + (f',{cell["z"]}' if cell.get('z') else ',0')
    answers, prompts, saw_square = [], [], False
    for _ in range(12):
        result = t.act(m, candidate_id, menu['decision_id'], menu['state_version'],
                       state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            assert saw_square, 'the deferred square picker never ran'
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        if prompt['context']['reaction_source_id'] == 'choice:placement_menu.square':
            assert not saw_square
            saw_square = True
            ids = [o['id'] for o in prompt['choice']['options']]
            assert cell_id in ids, (cell_id, ids)
            answers.append({**prompt['context'], 'selection': 'USE', 'option_ids': [cell_id]})
        else:
            # Choosing the predicted square fulfilled the branch, which then asks
            # the reader for its optional step; take a legal default, as the
            # shared commit helper does for other prompts.
            ids = [o['id'] for o in prompt['choice']['options']] if prompt.get('choice') else []
            answer = {**prompt['context'], 'selection': 'USE' if ids else 'DECLINE'}
            if ids:
                answer['option_ids'] = ids[:prompt['choice'].get('minimum_selections', 1)]
            answers.append(answer)
    raise AssertionError('The lazy placement picker did not finish.')


@pytest.mark.parametrize('aimed', [True, False])
def test_predicted_cell_action_fulfils_only_the_exact_aimed_square(tmp_path, aimed):
    """An exact-cell action at another square is a different action (finding 1)."""
    s, t, m = setup_scene(tmp_path, foe_cell=True)
    aim = PREDICTED_CELL if aimed else OTHER_CELL
    predicted_branch(s, t, m, cell_prediction(PREDICTED_CELL))
    advance(s, t, m, FOE)
    engine = cold(tmp_path, m)
    chosen = next(c for c in engine.legal_candidates()
                  if c.source_definition_id == CELL_SOURCE
                  and c.destination.model_dump(mode='json') == aim)
    commit(s, t, m, chosen)
    engine = cold(tmp_path, m)
    assert typed_executor.bears_mark(engine.state.actors[FOE], ME, 'Resonance') is aimed
    assert bool(held(engine.state.actors[FOE], BRANCH)) is not aimed


@pytest.mark.parametrize('chosen_is_predicted', [True, False])
def test_lazy_placement_binds_the_chosen_square_to_the_prediction(tmp_path, chosen_is_predicted):
    """The completion seam publishes the square the lazy picker resolved (finding 2)."""
    s, t, m = setup_scene(tmp_path, foe_cell=True)
    predicted_branch(s, t, m, cell_prediction(PREDICTED_CELL))
    advance(s, t, m, FOE)
    chosen = PREDICTED_CELL if chosen_is_predicted else OTHER_CELL
    prompts = commit_placement(s, t, m, CELL_SOURCE, chosen)
    assert prompts  # the real deferred square picker ran
    engine = cold(tmp_path, m)
    assert typed_executor.bears_mark(engine.state.actors[FOE], ME, 'Resonance') is chosen_is_predicted
    assert bool(held(engine.state.actors[FOE], BRANCH)) is not chosen_is_predicted


@pytest.mark.parametrize('predict_resolved', [True, False])
def test_redirected_action_fulfils_only_the_resolved_recipient(tmp_path, monkeypatch, predict_resolved):
    """The completion seam publishes the recipient after interception (finding 2)."""
    from combat import ext
    s, t, m = setup_scene(tmp_path)
    engine = cold(tmp_path, m)
    spike = next(a.source_definition_id for a in engine.action_catalog.values()
                 if a.owner_id == FOE and a.display_name == 'Mind Spike')

    def redirect(_engine, user, action, candidate, _intent):
        if user.entity_id == FOE and action.source_definition_id == spike and candidate.target_ids == (ME,):
            return {'source_id': 'test:seamfix-read-thread.reflection',
                    'label': 'A test reflection turns the strike onto the ally',
                    'retarget_id': ALLY, 'retarget_kind': 'ANY_CREATURE'}
        return None

    monkeypatch.setitem(ext._HOOKS, 'technique_declared', [*ext._HOOKS['technique_declared'], redirect])
    recipient = ALLY if predict_resolved else ME
    prediction = {'actor_id': FOE, 'kind': 'ACTION', 'source_definition_id': spike,
                  'target_ids': [recipient], 'aware_actor_ids': [FOE],
                  'description': 'Use Mind Spike', 'requires_facts': []}
    predicted_branch(s, t, m, prediction)
    advance(s, t, m, FOE)
    use(s, t, m, 'Mind Spike', ME)
    engine = cold(tmp_path, m)
    # The native interception really changed the recipient.
    landed = [ev for ev in engine.events if ev.event_type == 'PASSIVE_TRIGGERED'
              and ev.source_definition_id == spike and ev.actor_id == FOE]
    assert landed, 'the interception did not run'
    assert typed_executor.bears_mark(engine.state.actors[FOE], ME, 'Resonance') is predict_resolved
    assert bool(held(engine.state.actors[FOE], BRANCH)) is not predict_resolved
