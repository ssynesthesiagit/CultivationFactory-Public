"""SOL150 retained-base captures with isolated worktrees and disk-backed state.

The baseline subprocess imports from a complete registered Git worktree.
The compiler reads the retained authority file supplied by the parent test.
All capture data stays inside the test's disk-backed temporary directory.
"""
import json
from pathlib import Path
import subprocess
import sys

APP = Path(__file__).resolve().parents[1]


def baseline(revision, authority):
    """Load a complete retained tree, including rules data, in an isolated process.

    Register the disposable checkout with Git. Importing Python blobs alone
    cannot restore resources opened relative to module files. The supplied
    authority is retained for callers that intentionally snapshot that input.
    """
    global APP
    repository = APP.parent
    worktree = Path(authority).parent / 'baseline-worktree'
    subprocess.run(['git', 'worktree', 'add', '--detach', str(worktree), revision],
                   cwd=repository, check=True, stdout=sys.stderr, stderr=sys.stderr)
    APP = worktree / 'APP'
    sys.path.insert(0, str(APP))
    from combat import factory_compiler, typed_executor
    assert Path(factory_compiler.__file__).is_relative_to(worktree)
    assert typed_executor.RULES_PATH.is_relative_to(worktree)
    expected_rules = subprocess.check_output(
        ['git', 'show', f'{revision}:APP/combat/rules/typed_conditions.json'], cwd=repository)
    assert typed_executor.RULES_PATH.read_bytes() == expected_rules
    factory_compiler.TYPED_AUTHORITY = Path(authority)
    return repository, worktree


def capture(data, scenario):
    from combat.gate5_service import CombatService
    checkpoint = None
    legal_choices = None
    if scenario.startswith('stock:'):
        from combat.gate4_context import build_decision_context
        service = CombatService(APP, data)
        session = service.persistence.create_match(match_seed=scenario.split(':')[1], maximum_rounds=3)
        choices, legal_choices = [], []
        for _ in range(120):
            if session.engine.state.terminal_result is not None:
                break
            legal_choices.append([[c.candidate_id, c.display_name] for c in session.engine.legal_candidates()])
            policy, _ = service.policies.for_actor(session.engine.state.current_actor_id)
            choice = service.controller.choose_primary_action(build_decision_context(session.engine, policy, for_ai=True))
            choices.append(choice.intent.model_dump(mode='json'))
            session.execute_controller_choice(choice, controller=service.controller, policy_library=service.policies)
        assert session.engine.state.terminal_result is not None, 'stock capture did not finish'
        session = CombatService(APP, data)._load_session(session.match_id)
    else:
        from tests.test_sol150_text_sweep import ME, FOE, fight, my_turn, act
        actions = []
        if scenario == 'meld':
            from combat import ext
            ext.effects()
            @ext.effect('sol150_replay_end')
            def end(ctx, effect):
                ctx.engine._end_concentration(ctx.actor, 'REPLAY_END')
            actions = [('End test concentration', [{'type': 'sol150_replay_end'}], {'kind': 'instant'})]
        talents = ['FIRE_TAL_FIREBALL_ART'] if scenario == 'fireball' else [
            'TAL_DARK_MELD', 'TAL_DARK_DARKVISION', 'TAL_DARK_CLEARSIGHT']
        service, table, mid = fight(data, talents, actions=actions)
        my_turn(table, mid)
        if scenario == 'fireball':
            assert act(table, mid, 'Fireball Art', at={'x': 4, 'y': 6, 'z': 0})['status'] == 'COMMITTED'
        else:
            assert act(table, mid, 'Meld: Darkvision')['status'] == 'COMMITTED'
            act(table, mid); my_turn(table, mid)
            assert act(table, mid, 'Meld: Clearsight')['status'] == 'COMMITTED'
            act(table, mid); my_turn(table, mid)
            assert act(table, mid, 'End test concentration')['status'] == 'COMMITTED'
        engine = service._load_session(mid).engine
        checkpoint = {'state': engine.state.model_dump(mode='json'),
                      'events': [e.model_dump(mode='json') for e in engine.events],
                      'rolls': [r.model_dump(mode='json') for r in engine.rolls]}
        for actor in (ME, FOE):
            service.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')
        choices = []
        for _ in range(12):
            state = table.state(mid)
            if state['presentation']['terminal']:
                break
            response = table.auto_step(mid, state['last_sequence'])
            assert response['status'] == 'COMMITTED', response
        session = service._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    journal = session.store.match_dir / 'ControllerJournal.ndjson'
    records = [json.loads(line) for line in journal.read_text().splitlines()]
    if checkpoint is not None:
        choices = [row['primary_decision_record']['selected_candidate_id'] for row in records
                   if (row.get('primary_decision_record') or {}).get('controller_id') == 'controller:local_deterministic.gate4']
    result = {'choices': choices,
            'controller_journal': records,
            'events': [e.model_dump(mode='json') for e in session.engine.events],
            'rolls': [r.model_dump(mode='json') for r in session.engine.rolls],
            'state': session.engine.state.model_dump(mode='json')}
    if legal_choices is not None:
        result['legal_candidates'] = legal_choices
    if checkpoint is not None:
        result['ability_checkpoint'] = checkpoint
    return result


if __name__ == '__main__':
    retained = None
    try:
        if len(sys.argv) > 3:
            retained = baseline(sys.argv[3], sys.argv[4])
        print(json.dumps(capture(Path(sys.argv[1]), sys.argv[2]), sort_keys=True, separators=(',', ':')))
    finally:
        if retained is not None:
            repository, worktree = retained
            subprocess.run(['git', 'worktree', 'remove', '--force', str(worktree)],
                           cwd=repository, check=True, stdout=sys.stderr, stderr=sys.stderr)
