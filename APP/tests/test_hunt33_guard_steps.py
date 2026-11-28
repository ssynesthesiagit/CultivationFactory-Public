"""One-Legged Guard's actual hit rider offers only legal willing destinations.

Public synthetic melee hits run inside accepted table transactions, following
the C7 service harness; the granted Polearm attack and guard payment are real.
"""
import pytest

from combat import typed_executor as te
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import script
from tests.test_c7_review_fixup import (ROOT, ME, FOE, HERON, JI, STAMINA, sheet, bundle,
                                      send, hold_ai, load, context)
from tests.test_tabletop_hunt6 import on_hold

ALLY = 'actor:factory.guard-ally'
SOURCE = 'actor:factory.guard-fear'


@pytest.mark.parametrize('frightened,invisible', [(True, False), (False, False), (True, True)])
@pytest.mark.parametrize('off_turn_ai', [False, True])
@pytest.mark.parametrize('protect_ally', [False, True])
def test_guard_hit_filters_the_protected_creatures_fear_before_table_choice(
        tmp_path, monkeypatch, frightened, invisible, off_turn_ai, protect_ally):
    mine = compile_character(sheet([HERON + 'one_legged_guard'], items=(JI,), name='Guard'),
                             actor_id=ME, reaction_plan={'ask': True})
    bundles = [mine, bundle([], actor_id=FOE, name='Attacker'), bundle([], actor_id=SOURCE, name='Fear source')]
    ids = [ME, FOE, SOURCE]
    positions = {ME: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, SOURCE: {'x': 3, 'y': 2}}
    if protect_ally:
        ids.append(ALLY)
        bundles.append(compile_character(sheet([], name='Protected ally'), actor_id=ALLY, reaction_plan={'ask': True}))
        positions.update({ME: {'x': 2, 'y': 7}, ALLY: {'x': 3, 'y': 7}})
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, ids,
        {a: 'team:a' if a in (ME, ALLY) else 'team:b' for a in ids}, positions,
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [ME], [FOE, SOURCE],
        control_modes={a: 'MANUAL' for a in ids}, match_seed='HUNT33-GUARD-FEAR',
        display_name='Guard fear regression', maximum_rounds=5)['match_id']
    # Advance without the two-actor C7 helper's three-step limit.
    turn_actor = FOE if off_turn_ai else ME
    for _ in range(8):
        if table.state(mid)['menu']['actor_id'] == turn_actor:
            break
        assert send(table, mid, label='end')['status'] == 'COMMITTED'
    assert table.state(mid)['menu']['actor_id'] == turn_actor
    protected_id = ALLY if protect_ally else ME

    def incoming_hit(engine):
        protected = engine.state.actors[protected_id]
        if frightened:
            engine._apply_condition(protected, 'condition:typed.frightened', 'test:guard-fear', SOURCE,
                                    expires_on='UNTIL_REMOVED')
        if invisible:
            engine._apply_condition(engine.state.actors[SOURCE], 'condition:typed.invisible',
                                    'test:guard-unseen', SOURCE, expires_on='UNTIL_REMOVED')
        # Both d20s hit even when the guard itself has Disadvantage from fear.
        script(engine, [19, 19, *([1] * 80)])
        attacker = engine.state.actors[FOE]
        ctx = context(engine, attacker, protected)
        te.run_effects(ctx, [{'type': 'attack', 'attack_kind': 'unarmed', 'count': 1,
                             'on_hit': [{'type': 'damage', 'dice': {'count': 1, 'sides': 4},
                                         'damage_types': ['bludgeoning']}]}])

    on_hold(monkeypatch, incoming_hit)
    if off_turn_ai:
        hold_ai(combat, mid, FOE)
    before = load(tmp_path, mid).engine.state.model_dump(mode='json')
    answers, prompts = [], []
    blocked = frightened and not invisible
    y = 7 if protect_ally else 6
    toward, away = f'cell:3,{y - 1}', f'cell:3,{y + 1}'
    for _ in range(20):
        result = send(table, mid, auto=off_turn_ai, answers_=answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']
        prompts.append(prompt)
        assert load(tmp_path, mid).engine.state.model_dump(mode='json') == before
        answer = {**prompt['context'], 'selection': 'USE'}
        source = prompt['context']['reaction_source_id']
        if source.endswith('one_legged_guard_move'):
            assert prompt['context']['reactor_id'] == protected_id
            options = {o['id'] for o in prompt['choice']['options']}
            assert (toward in options) is not blocked
            assert away in options
            assert send(table, mid, auto=off_turn_ai, answers_=answers)['reaction'] == prompt
            answer['option_ids'] = [away if blocked else toward]
        elif source.endswith('one_legged_guard') and prompt.get('choice'):
            answer['option_ids'] = ['move']
        elif prompt.get('choice'):
            answer['option_ids'] = [(prompt['choice'].get('preferred') or
                                     [prompt['choice']['options'][0]['id']])[0]]
        answers.append(answer)
    assert result['status'] == 'COMMITTED'
    assert any(p['context']['reaction_source_id'].endswith('one_legged_guard_move') for p in prompts)
    restored = load(tmp_path, mid)
    guard = restored.engine.state.actors[ME]
    protected = restored.engine.state.actors[protected_id]
    assert protected.position == Position(x=3, y=y + 1 if blocked else y - 1)
    assert guard.resources[STAMINA] == before['actors'][ME]['resources'][STAMINA] - 1
    assert not guard.reaction_available
    assert protected.movement_remaining_ft == before['actors'][protected_id]['movement_remaining_ft']
    if protect_ally:
        assert guard.position == Position(x=2, y=7)
    recent = [e for e in restored.engine.events if e.sequence > before['event_sequence']]
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == ME and e.payload['provisional_hit'] for e in recent)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == ME and FOE in e.target_ids
               and e.payload['hp_damage'] > 0 for e in recent)
    assert len([e for e in recent if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == protected_id]) == 1
    assert restored.verify()['status'] == restored.mechanical.replay()['status'] == 'PASS'
