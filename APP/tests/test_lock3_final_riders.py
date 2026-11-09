"""Global resource veto and legal final movement survive a terminal table action."""
import copy
import json
import zipfile

import pytest

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.ext import ControllerPause
from combat.gate2_runtime_models import ActionIntent
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET
from tests.test_lock2_persistence import ROOT, table_match, act
from tests.test_auto_tabik import _engine, ME
from tests.test_lock_choices import install


def test_global_gain_veto_applies_to_direct_calls_and_validates_answers(monkeypatch):
    seen = []
    def veto(e, actor, resource, amount, source):
        seen.append((resource, amount, source))
        return False
    install(monkeypatch, 'resource_gain_allowed', veto)
    engine, _ = _engine([])
    actor = engine.state.actors[ME]
    pool = next(k for k, n in actor.resource_maximums.items() if n > 0)
    engine._spend_resource(actor, pool, 1, 'test:open')
    before = actor.resources[pool]
    engine._gain_resource(actor, pool, 1, 'test:direct')
    assert actor.resources[pool] == before
    assert seen == [(pool, 1, 'test:direct')]
    assert not any(e.event_type == 'RESOURCE_GAINED' and e.source_definition_id == 'test:direct' for e in engine.events)
    install(monkeypatch, 'resource_gain_allowed', lambda *args: 'allow')
    with pytest.raises(ValueError, match='resource_gain_allowed'):
        with engine._transaction('test:bad', 'test:bad', ME):
            engine._gain_resource(actor, pool, 1, 'test:bad')


def tiny_table(tmp_path):
    sheet = copy.deepcopy(SHEET)
    sheet['ability_scores_and_statistics']['hit_points'] = json.dumps({'maximum': 1})
    for name in ('left', 'right'):
        archive = tmp_path / 'portable_characters' / name / 'current.zip'
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Final yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3, 4]], 'team2': [[4, 4]]}})
    view = combat.create_factory_match(project_ids=['left'], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + 'right'],
        control_modes={FACTORY_ACTOR_PREFIX + p: 'MANUAL' for p in ('left', 'right')},
        arena_id='battlefield:map.final-yard', match_seed='LOCK3-FINAL-TABLE')
    return combat, TabletopService(combat, tmp_path), view['match_id']


def test_no_cp_regain_blocks_direct_rider_gain_at_table_level(monkeypatch, tmp_path):
    def spend_and_restore(engine, kind, kwargs):
        if kind != 'HOLD_POSITION_COMMITTED':
            return
        actor = engine.state.actors[kwargs['actor_id']]
        engine._apply_condition(actor, 'condition:typed.no_cp_regain', 'test:no-gain', actor.entity_id,
                                expires_on='UNTIL_REMOVED')
        engine._spend_resource(actor, 'resource:core.stamina', 1, 'test:open')
        engine._gain_resource(actor, 'resource:core.stamina', 1, 'test:direct')
    install(monkeypatch, 'event', spend_and_restore)
    combat, table, mid = table_match(tmp_path)
    actor_id = table.state(mid)['menu']['actor_id']
    before = combat._load_session(mid).engine.state.actors[actor_id].resources['resource:core.stamina']
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[actor_id].resources['resource:core.stamina'] == before - 1
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_terminal_action_runs_final_cost_and_movement_before_persisting(monkeypatch, tmp_path):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20})
    calls = []
    def finish(engine, actor, action, candidate, intent):
        assert engine.state.terminal_result is not None
        calls.append(action.source_definition_id)
        engine._spend_resource(actor, 'resource:core.stamina', 1, 'test:final-cost')
        move = next(c for c in engine._movement_candidates(actor)
                    if c.destination.x == actor.position.x and c.destination.y == actor.position.y + 1)
        engine._resolve_movement(actor, move, intent)
    install(monkeypatch, 'resolution_final', finish)
    combat, table, mid = tiny_table(tmp_path)
    state = table.state(mid)
    menu = state['menu']
    before = combat._load_session(mid).engine.state.actors[menu['actor_id']]
    group = next(g for g in menu['actions'] if g['source_definition_id'].endswith('.weapon.dao'))
    result = table.act(mid, group['options'][0]['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[menu['actor_id']]
    assert loaded.engine.state.terminal_result is not None
    assert actor.position.x == before.position.x and actor.position.y == before.position.y + 1
    assert actor.resources['resource:core.stamina'] == before.resources['resource:core.stamina'] - 1
    assert actor.movement_remaining_ft == before.movement_remaining_ft - 5
    assert not getattr(loaded.engine, '_final_rider_active', False)
    assert calls and len(set(calls)) == 1
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_typed_final_backlash_keeps_activation_context_after_terminal_damage(monkeypatch, tmp_path):
    from combat.typed_executor import run_effects
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20})
    seen = []
    def finish(ctx):
        assert ctx.engine.state.terminal_result is not None
        assert ctx.intent is ctx.engine._active_intent
        assert ctx.damage_cache  # same activation, including its damage rolls
        terminal = ctx.engine.state.terminal_result.model_copy(deep=True)
        run_effects(ctx, [{'type': 'damage', 'flat': 4, 'damage_types': ['poison'], 'applies_to': 'self'}])
        assert ctx.engine.state.terminal_result == terminal
        seen.append(ctx.source)
    install(monkeypatch, 'technique_final', finish)
    combat, table, mid = tiny_table(tmp_path)
    state = table.state(mid)
    menu = state['menu']
    group = next(g for g in menu['actions'] if g['source_definition_id'].endswith('.weapon.dao'))
    result = table.act(mid, group['options'][0]['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    own_damage = [e for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED'
                  and e.target_ids == (menu['actor_id'],)]
    assert len(own_damage) == 1 and own_damage[0].payload['damage_type'] == 'POISON'
    assert own_damage[0].sequence > loaded.engine.state.terminal_result.event_sequence
    assert loaded.engine.state.actors[menu['actor_id']].current_hp == 0
    assert seen and len(set(seen)) == 1
    assert loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('failed', [True, False])
def test_terminal_final_self_save_uses_scoped_pipeline_and_persists(monkeypatch, tmp_path, failed):
    from dataclasses import replace
    from combat.typed_executor import active_save_pending, block_save, run_effects

    contexts, saves = [], []
    def roll_result(engine, roll, intent):
        context = engine.d20_context()
        if context['kind'] == 'save':
            assert engine._final_rider_active
            assert active_save_pending(engine, context['source_id'], context['target_id'])
            saves.append(dict(context))
        return {'source_id': 'test:result', 'operation': 'replace',
                'natural_result': 1 if failed and context['kind'] == 'save' else 20}
    install(monkeypatch, 'd20_result', roll_result)
    shaped, resolved = [], []
    def shape(ctx, subject, ability, named):
        shaped.append((subject.entity_id, ability, named))
        return {'bonus': 2, 'modes': ['ADVANTAGE']}
    install(monkeypatch, 'save', shape)
    install(monkeypatch, 'after_save_resolved', lambda ctx, subject, ability, named, outcome:
            resolved.append((subject.entity_id, outcome)))
    checkpoints = []
    def before_save(engine, subject, intent, context):
        assert engine._final_rider_active
        assert intent is engine._active_intent
        checkpoints.append(context)
        return {'mode': 'ADVANTAGE'}
    install(monkeypatch, 'before_dex_save', before_save)
    effect = {'type': 'save', 'ability': 'dex',
              'on_fail': [{'type': 'damage', 'flat': 4, 'damage_types': ['poison']}]}
    terminals = []
    def finish(ctx):
        assert ctx.engine.state.terminal_result is not None
        terminals.append(ctx.engine.state.terminal_result.model_copy(deep=True))
        backlash = replace(ctx, targets=[ctx.actor], target=ctx.actor,
                           typed={**ctx.typed, 'numbers': {**ctx.numbers, 'save_dc': 10}})
        contexts.append(backlash)
        # Final riders may resolve saves, but may not start post-terminal attacks.
        rolls = len(ctx.engine.rolls)
        run_effects(backlash, [{'type': 'attack', 'no_damage': True}])
        assert len(ctx.engine.rolls) == rolls
        run_effects(backlash, [effect])
        assert ctx.engine.state.terminal_result == terminals[-1]
    install(monkeypatch, 'technique_final', finish)
    combat, table, mid = tiny_table(tmp_path)
    state = table.state(mid)
    menu = state['menu']
    group = next(g for g in menu['actions'] if g['source_definition_id'].endswith('.weapon.dao'))
    result = table.act(mid, group['options'][0]['candidate_id'], menu['decision_id'],
                       menu['state_version'], state['last_sequence'])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[menu['actor_id']]
    events = loaded.engine.events
    save = [e for e in events if e.event_type == 'SAVE_ROLLED' and e.actor_id == actor.entity_id]
    damage = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (actor.entity_id,)]
    assert len(save) == 1
    assert save[0].sequence > loaded.engine.state.terminal_result.event_sequence
    assert save[0].payload['success'] is not failed
    assert save[0].payload['mode'] == 'ADVANTAGE'
    assert save[0].payload['dc'] == 8
    assert len(damage) == int(failed)
    if failed:
        assert damage[0].sequence > save[0].sequence
        assert damage[0].payload['damage_type'] == 'POISON'
    assert actor.current_hp == (0 if failed else 1)
    assert loaded.engine.state.terminal_result == terminals[-1]
    assert shaped and resolved and saves and checkpoints
    assert all(row == (actor.entity_id, failed) for row in resolved)
    assert not getattr(loaded.engine, '_final_rider_active', False)
    assert loaded.engine.d20_context() is None
    assert loaded.mechanical.replay()['status'] == 'PASS'
    # Ordinary effects, including direct save entry, remain suppressed after scope exit.
    ctx = contexts[-1]
    before = len(ctx.engine.events), len(ctx.engine.rolls)
    run_effects(ctx, [effect, {'type': 'damage', 'flat': 4}])
    block_save(ctx, effect)
    assert (len(ctx.engine.events), len(ctx.engine.rolls)) == before
    assert not active_save_pending(ctx.engine, ctx.source, ctx.actor.entity_id)


@pytest.mark.parametrize('failure', [ControllerPause, ValueError])
def test_terminal_final_save_checkpoint_failure_rolls_back(monkeypatch, tmp_path, failure):
    from dataclasses import replace
    from combat.typed_executor import active_save_pending, run_effects

    install(monkeypatch, 'd20_result', lambda *a:
            {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20})
    seen = []
    def checkpoint(engine, subject, intent, context):
        assert engine.state.terminal_result is not None
        assert engine._final_rider_active
        assert active_save_pending(engine, context['source_id'], subject.entity_id)
        seen.append((context['source_id'], subject.entity_id))
        raise failure('final save choice')
    install(monkeypatch, 'before_dex_save', checkpoint)
    def finish(ctx):
        run_effects(replace(ctx, targets=[ctx.actor], target=ctx.actor),
                    [{'type': 'save', 'ability': 'dex', 'on_fail': [{'type': 'damage', 'flat': 4}]}])
    install(monkeypatch, 'technique_final', finish)
    combat, table, mid = tiny_table(tmp_path)
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id.endswith('.weapon.dao'))
    request = ActionIntent(intent_id='test:final-save', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=candidate.actor_id, target_ids=candidate.target_ids, option_ids=candidate.option_ids)
    before = engine.state.model_dump(mode='json'), list(engine.events), list(engine.rolls), engine.roller.counter
    with pytest.raises(failure, match='final save choice'):
        engine.execute_intent(request)
    assert (engine.state.model_dump(mode='json'), engine.events, engine.rolls, engine.roller.counter) == before
    assert seen and not engine._final_rider_active and engine.d20_context() is None
    assert all(not active_save_pending(engine, source, subject) for source, subject in seen)


@pytest.mark.parametrize('failure', ['pause', 'error'])
def test_final_callback_failure_rolls_back_action_and_clears_scope(monkeypatch, failure):
    caught = ControllerPause if failure == 'pause' else ValueError
    def finish(engine, actor, *args):
        pool = next(key for key, amount in actor.resources.items() if amount > 0)
        engine._spend_resource(actor, pool, 1, 'test:final')
        raise caught('final choice')
    install(monkeypatch, 'resolution_final', finish)
    engine, _ = _engine([])
    candidate = next(c for c in engine.legal_candidates() if c.kind == 'ACTION')
    request = ActionIntent(intent_id='test:final', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=candidate.actor_id, target_ids=candidate.target_ids,
        destination=candidate.destination, option_ids=candidate.option_ids)
    before = engine.state.model_dump(mode='json'), list(engine.events), list(engine.rolls), engine.roller.counter
    with pytest.raises(caught, match='final choice'):
        engine.execute_intent(request)
    assert (engine.state.model_dump(mode='json'), engine.events, engine.rolls, engine.roller.counter) == before
    assert not engine._final_rider_active
