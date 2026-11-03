"""Maximum-HP stacking, canonical consumers, setup choices and portable replay."""
import json
import zipfile
import pytest
from combat import ext, maximum_hp
from combat.ext.maximum_hp_riders import MEAL, MODIFY, STEW, MODIFIED, FOCUS
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import lock8_support as S
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act


def adjust(e, a, key, amount, **kw):
    return maximum_hp.change(e, a, key, amount, 'test:hp', a.entity_id, label='Test maximum', **kw)


def test_default_bytes_and_reductions_at_floor_restore_independently():
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND')); a = e.state.actors[S.ME]
    original = a.model_dump(mode='json'); base = a.maximum_hp
    assert 'maximum_hp_base' not in original and 'maximum_hp_adjustments' not in original
    adjust(e, a, 'one', -base); adjust(e, a, 'two', -10)
    assert (a.maximum_hp, a.current_hp) == (1, 1)
    adjust(e, a, 'one', 0)
    assert a.maximum_hp == max(1, base - 10) and a.current_hp == 1
    adjust(e, a, 'two', 0)
    assert a.maximum_hp == base and a.current_hp == 1
    assert 'maximum_hp_base' not in a.model_dump(mode='json')
    from combat.history_feed import format_history_feed
    rows = format_history_feed([ev.model_dump(mode='json') for ev in e.events if ev.event_type == 'MAXIMUM_HP_CHANGED'], [],
        pre_state=None, post_state=e.state.model_dump(mode='json'), actor_names={a.entity_id: 'Test fighter'}, definition_names={})
    assert rows and all('Hit Points' in row['summary'] for row in rows)


@pytest.mark.parametrize('value', [True, 1.5, '2'])
def test_invalid_adjustment_is_rejected_before_mutation(value):
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND')); a = e.state.actors[S.ME]
    before = a.model_dump(mode='json')
    with pytest.raises(ValueError): adjust(e, a, 'bad', value)
    assert a.model_dump(mode='json') == before


@pytest.mark.parametrize('hp', [0, 1, 20])
def test_stew_expiry_uses_own_delta_preserves_other_changes_and_never_revives(hp):
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND')); a = e.state.actors[S.ME]; base = a.maximum_hp
    e._apply_condition(a, STEW, MEAL, a.entity_id, expires_on='UNTIL_REMOVED')
    c = next(c for c in a.conditions.values() if c.condition_id == STEW)
    maximum_hp.bind(e, a, c, 8, label='Iron-Bone Stew', current_delta=8, expiry_current_delta=-8, current_floor=1)
    after = a.current_hp
    maximum_hp.bind(e, a, c, 8, label='Iron-Bone Stew', current_delta=8, expiry_current_delta=-8, current_floor=1)
    assert a.current_hp == after
    adjust(e, a, 'other', -10)
    a.current_hp = hp
    e._remove_condition(a, STEW, MEAL)
    assert a.maximum_hp == base - 10
    assert a.current_hp == (0 if hp == 0 else max(1, hp - 8))
    assert 'other' in a.maximum_hp_adjustments and c.instance_id not in a.maximum_hp_adjustments


def table(tmp_path, features, monkeypatch, *, strike=False, portable_attack=False):
    left, right = 'actor:factory.left', 'actor:factory.right'
    for pid, fs in [('left', features), ('right', ['SAND_BASE_SCOURING_HAND'])]:
        folder = tmp_path / 'portable_characters' / pid; folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet(fs, cl=20)))
    if strike:
        def attacks(info):
            return [ActionDefinition(source_definition_id='test:critical:' + info['actor_id'], owner_id=info['actor_id'],
                display_name='Test critical attack', economy=EconomyKind.ACTION,
                resolution_kind='TYPED' if portable_attack else 'ATTACK',
                target_kind='HOSTILE_ENTITY', range_ft=60, attack_bonus=100,
                parameters={'typed': {'effects': [{'type': 'test_portable_attack'}], 'numbers': info['numbers']}}
                           if portable_attack else {})]
        install(monkeypatch, 'compile_actions', attacks)
        install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:roll', 'operation': 'replace', 'natural_result': 20})
        if portable_attack:
            def resolve(ctx, eff):
                from combat.character_runtime_adapter import CharacterCombatRuntimeEngine
                CharacterCombatRuntimeEngine._resolve_character_attack(ctx.engine, ctx.actor, ctx.target, source_id=ctx.source, attack_bonus=100,
                    damage=None, damage_type='UNTYPED', intent=ctx.intent, ranged=True)
            ext.effects(); monkeypatch.setitem(ext._EFFECTS, 'test_portable_attack', resolve)
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Maximum yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3,4]], 'team2': [[4,4]]}})
    mid = service.create_factory_match(project_ids=['left'], opponent_actor_ids=[right],
        control_modes={left: 'MANUAL', right: 'MANUAL'}, arena_id='battlefield:map.maximum-yard', match_seed='MAXIMUM')['match_id']
    return service, TabletopService(service, tmp_path), mid, left, right


def answer(table, mid, source, prompt, options):
    state = table.state(mid); menu = state['menu']
    group = next(g for g in menu['actions'] if g['source_definition_id'].startswith(source))
    return table.act(mid, group['options'][0]['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'],
        [{**prompt['context'], 'selection': 'USE' if options else 'DECLINE', 'option_ids': options}])


@pytest.mark.parametrize('take', [False, True])
def test_prepared_stew_setup_pause_reload_commit_and_expiry(tmp_path, monkeypatch, take):
    service, ui, mid, left, right = table(tmp_path, [MEAL], monkeypatch)
    before = service._load_session(mid).engine.state.model_dump(mode='json')
    first = act(ui, mid, 'system:combat.fight_setup')
    assert first['status'] == 'REACTION_REQUIRED'
    assert service._load_session(mid).engine.state.model_dump(mode='json') == before
    service = CombatService(ROOT, tmp_path); ui = TabletopService(service, tmp_path)
    result = answer(ui, mid, 'system:combat.fight_setup', first['reaction'], [left] if take else [])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid); actor = loaded.engine.state.actors[left]
    amount = 2 * actor.proficiency_bonus
    assert actor.maximum_hp == before['actors'][left]['maximum_hp'] + (amount if take else 0)
    assert actor.current_hp == before['actors'][left]['current_hp'] + (amount if take else 0)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    if take:
        def remove(engine, kind, kwargs):
            if kind == 'HOLD_POSITION_COMMITTED': engine._remove_condition(engine.state.actors[left], STEW, MEAL)
        ext.effects(); monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), remove])
        assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        assert loaded.engine.state.actors[left].maximum_hp == before['actors'][left]['maximum_hp']
        assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('take', [False, True])
@pytest.mark.parametrize('portable_attack', [False, True])
def test_modify_critical_knowledge_confirmation_focus_and_portable_replay(tmp_path, monkeypatch, take, portable_attack):
    def known(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == 'actor:factory.left':
            from combat.ext.mind_hidden_eye import mark_analyzed
            a, b = engine.state.actors['actor:factory.left'], engine.state.actors['actor:factory.right']
            mark_analyzed(engine, a, b, 'test:known')
            engine._gain_resource(a, FOCUS, 1, 'test:ready')
    ext.effects(); monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), known])
    service, ui, mid, left, right = table(tmp_path, [MODIFY], monkeypatch, strike=True, portable_attack=portable_attack)
    turn(ui, mid, left); assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    before = service._load_session(mid).engine.state.model_dump(mode='json')
    first = act(ui, mid, 'test:critical:')
    assert first['status'] == 'REACTION_REQUIRED'
    assert service._load_session(mid).engine.state.model_dump(mode='json') == before
    service = CombatService(ROOT, tmp_path); ui = TabletopService(service, tmp_path)
    assert answer(ui, mid, 'test:critical:', first['reaction'], ['maximum_hp'] if take else [])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid); a, b = loaded.engine.state.actors[left], loaded.engine.state.actors[right]
    assert b.maximum_hp == before['actors'][right]['maximum_hp'] - (10 if take else 0)
    assert b.current_hp == min(before['actors'][right]['current_hp'], b.maximum_hp)
    assert a.resources[FOCUS] == (0 if take else 1)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    if take:
        loaded.engine.state.round_number += 600
        from combat.ext.maximum_hp_riders import hour_expiry
        hour_expiry(loaded.engine, a)
        assert b.maximum_hp == before['actors'][right]['maximum_hp']
        assert b.current_hp == before['actors'][right]['current_hp'] - 10
