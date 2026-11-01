"""Initiative placement choices through the actual table and automatic controller."""
import pytest

from combat import ext
from combat.choice_checkpoints import dynamic_choice
from combat.ext import placed
from combat.fight_setup import SOURCE
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind, Position, ReactionDecision
from combat.gate5_service import CombatService
from tests.test_lock_choices import install
from tests.test_lock2_persistence import ROOT, table_match, act

ABILITY = 'test:prepared-markers:'


def actions(info):
    return [ActionDefinition(source_definition_id=ABILITY + info['actor_id'], owner_id=info['actor_id'],
        display_name='Prepared markers', economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'effects': [], 'numbers': info['numbers']}})]


def tasks(engine):
    return [{'actor_id': aid, 'source_id': ABILITY + aid} for aid in engine.state.actors]


def markers(engine, actor, source, intent):
    if not source.startswith(ABILITY):
        return None
    for index in range(2):
        cells = {f'{x},1': Position(x=x, y=1) for x in range(1, 5)}
        cells = {key: pos for key, pos in cells.items()
                 if not any(pos in zone.affected_cells for zone in engine.state.zones.values())}
        _, answer = dynamic_choice(engine, intent, f'SETUP:{actor.entity_id}:{index}', actor.entity_id, source,
            {'name': 'Prepared markers', 'actor_id': actor.entity_id, 'target_id': actor.entity_id,
             'prompt': f'{actor.display_name}: place marker {index+1} before the first turn. It lasts one minute and costs no action.',
             'labels': {key: f'Place at square {key}' for key in cells}},
            spec_override={'option_ids': tuple(cells), 'allow_decline': True, 'automatic_use': True,
                           'preferred_option_ids': (next(iter(cells)),)})
        if answer is None:
            raise ValueError('a setup choice needs a controller')
        if answer.selection == 'DECLINE':
            break
        placed.place(engine, actor, source=source, tag='test-marker', cells=cells[answer.option_ids[0]],
                     name=f'{actor.display_name} prepared marker', duration_rounds=10)
    return True


def fixture(monkeypatch, tmp_path):
    install(monkeypatch, 'compile_actions', actions)
    install(monkeypatch, 'fight_setup_tasks', tasks)
    install(monkeypatch, 'fight_setup', markers)
    return table_match(tmp_path)


def answer(prompt):
    return {**prompt['context'], 'selection': 'USE', 'option_ids': [prompt['choice']['options'][0]['id']]}


def submit(table, mid, answers):
    state = table.state(mid); menu = state['menu']
    cid = next(g['options'][0]['candidate_id'] for g in menu['actions'] if g['source_definition_id'] == SOURCE)
    return table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)


def test_manual_placements_are_one_setup_transaction_across_reload(monkeypatch, tmp_path):
    service, table, mid = fixture(monkeypatch, tmp_path)
    session = service._load_session(mid)
    before = session.engine.state.model_dump(mode='json')
    assert len(session.engine.state.setup_tasks) == 2
    assert not any(e.event_type in ('ROUND_STARTED', 'TURN_STARTED') for e in session.engine.events)
    assert {c.source_definition_id for c in session.engine.legal_candidates()} == {SOURCE}
    with pytest.raises(ValueError, match='Finish fight setup'):
        session.engine.end_turn()
    answers = []
    for index in range(4):
        result = submit(table, mid, answers)
        assert result['status'] == 'REACTION_REQUIRED'
        assert 'before the first turn' in result['reaction']['moment']
        answers.append(answer(result['reaction']))
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        assert loaded.engine.state.model_dump(mode='json') == before
        assert not loaded.engine.state.zones
    assert submit(table, mid, answers)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not loaded.engine.state.setup_tasks
    assert len(loaded.engine.state.zones) == 4
    assert len({tuple((p.x, p.y) for p in z.affected_cells) for z in loaded.engine.state.zones.values()}) == 4
    assert all(a.action_available and a.reaction_available for a in loaded.engine.state.actors.values())
    kinds = [e.event_type for e in loaded.engine.events]
    assert kinds.index('FIGHT_SETUP_COMPLETED') < kinds.index('ROUND_STARTED') < kinds.index('TURN_STARTED')
    assert loaded.verify()['status'] == 'PASS'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'


def test_ai_first_turn_asks_other_manual_setup_owner(monkeypatch, tmp_path):
    service, table, mid = fixture(monkeypatch, tmp_path)
    engine = service._load_session(mid).engine
    first = engine.state.current_actor_id
    other = next(a for a in engine.state.actors if a != first)
    service.set_controller_mode(mid, actor_id=first, controller_mode='LOCAL_AUTO')
    answers = []
    for _ in range(2):
        result = service.local_step(mid, reactions=answers)
        assert result['status'] == 'AWAITING_REACTION'
        # The service envelope carries the general choice request, unlike the table presentation.
        prompt = result['reaction_context']
        assert prompt['reactor_id'] == other
        answers.append({'checkpoint': prompt['checkpoint'], 'reactor_id': other,
                        'reaction_source_id': prompt['reaction_source_id'], 'selection': 'USE',
                        'option_ids': [prompt['legal_option_ids'][0]]})
    assert service.local_step(mid, reactions=answers)['status'] == 'COMMITTED'
    loaded = service._load_session(mid)
    assert len(loaded.engine.state.zones) == 4 and not loaded.engine.state.setup_tasks
    assert loaded.verify()['status'] == 'PASS'


def test_setup_failure_and_invalid_answer_restore_everything(monkeypatch, tmp_path):
    service, table, mid = fixture(monkeypatch, tmp_path)
    engine = service._load_session(mid).engine
    candidate = engine.legal_candidates()[0]
    intent = ActionIntent(intent_id='test:setup-failure', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=candidate.actor_id)
    before = engine.state.model_dump(mode='json'), list(engine.events), list(engine.rolls), engine.roller.counter
    def fail(e, a, s, i):
        e._grant_temp_hp(a, 3, s, a.entity_id)
        raise ext.ControllerPause('choose next placement')
    install(monkeypatch, 'fight_setup', fail)
    with pytest.raises(ext.ControllerPause):
        engine.execute_intent(intent)
    assert (engine.state.model_dump(mode='json'), engine.events, engine.rolls, engine.roller.counter) == before
    install(monkeypatch, 'fight_setup', lambda *args: None)
    with pytest.raises(ValueError, match='exactly one consumer'):
        engine.execute_intent(intent)
    assert engine.state.model_dump(mode='json') == before[0]
    install(monkeypatch, 'fight_setup', markers)
    task = engine.state.setup_tasks[0]
    bad = {'checkpoint': f'SETUP:{task.actor_id}:0', 'reactor_id': task.actor_id,
           'reaction_source_id': task.source_id, 'selection': 'USE', 'option_ids': ['99,99']}
    with pytest.raises(ValueError, match='invalid extension choice'):
        engine.execute_intent(intent.model_copy(update={'reaction_decisions': (ReactionDecision.model_validate(bad),)}))
    assert engine.state.model_dump(mode='json') == before[0]


def test_unowned_tasks_are_inert(monkeypatch, tmp_path):
    install(monkeypatch, 'fight_setup_tasks', tasks)
    service, _, mid = table_match(tmp_path)
    engine = service._load_session(mid).engine
    assert not engine.state.setup_tasks and 'setup_tasks' not in engine.state.model_dump(mode='json')
    assert any(e.event_type == 'TURN_STARTED' for e in engine.events)
    assert not any(c.source_definition_id == SOURCE for c in engine.legal_candidates())


def test_all_ai_setup_is_automatic_and_manual_decline_is_allowed(monkeypatch, tmp_path):
    service, table, mid = fixture(monkeypatch, tmp_path)
    engine = service._load_session(mid).engine
    for aid in engine.state.actors:
        service.set_controller_mode(mid, actor_id=aid, controller_mode='LOCAL_AUTO')
    assert service.local_step(mid)['status'] == 'COMMITTED'
    assert len(service._load_session(mid).engine.state.zones) == 4


def test_manual_can_decline_each_optional_placement(monkeypatch, tmp_path):
    service, table, mid = fixture(monkeypatch, tmp_path)
    answers = []
    for _ in range(2):
        result = submit(table, mid, answers)
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE'})
    assert submit(table, mid, answers)['status'] == 'COMMITTED'
    loaded = service._load_session(mid)
    assert not loaded.engine.state.zones and not loaded.engine.state.setup_tasks
    assert loaded.verify()['status'] == 'PASS'
