"""Condition rules through accepted Table actions, persisted events and reload."""
import pytest
from combat import ext, typed_executor
from combat.gate2_runtime_models import DiceSpec
from combat.gate5_service import CombatService
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT, script
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install
from tests.test_lock9_critical_range import HELMET


def apply(e, who, name, *, source=H.LEFT, rule=None):
    cid = name if name.startswith('condition:') else 'condition:typed.' + name
    e._apply_condition(e.state.actors[who], cid, 'test:condition', source,
                       expires_on='UNTIL_REMOVED', data={'rule': rule} if rule else None)


def commit(monkeypatch, tmp_path, callback, *, talents=(), covered=False):
    from combat.tabletop import TabletopMapStore
    save = TabletopMapStore.save
    def map_save(store, document):
        document['starts']['team1'][1] = [3, 6] if covered else [2, 5]
        if covered:
            document['walls'] = [{'shape':'line','points':[[0,5],[11,5]],'blocks':'sight_and_movement'}]
        return save(store, document)
    monkeypatch.setattr(TabletopMapStore, 'save', map_save)
    combat, table, mid = H.table_fight(tmp_path, [], ally_talents=list(talents))
    H.on_hold(monkeypatch, callback)
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


def commit_native(monkeypatch, tmp_path, callback):
    from combat.gate4_persistence import Gate4Persistence
    from combat.gate2_runtime_content import AN, LEE
    from combat.tabletop_service import TabletopService
    session = Gate4Persistence(ROOT, tmp_path).create_match(match_seed='L18-CONDITIONS', roster_setup={
        'primary_actor_ids':[AN, LEE], 'team_by_actor':{AN:'team:a',LEE:'team:b'},
        'starting_positions':{AN:{'x':3,'y':6},LEE:{'x':4,'y':6}}})
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    combat.set_controller_mode(session.match_id, actor_id=session.engine.state.current_actor_id, controller_mode='MANUAL')
    H.on_hold(monkeypatch, callback)
    assert act(table, session.match_id, H.HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


@pytest.mark.parametrize('condition,attacker,ranged,natural,critical', [
    ('paralyzed', H.LEFT, False, 15, True),
    ('unconscious', H.LEFT, False, 15, True),
    ('life_unconscious', H.LEFT, True, 15, True),
    ('paralyzed', H.LEFT, True, 15, True),
    ('petrified', H.LEFT, False, 15, False),
    ('paralyzed', H.ALLY, False, 15, False),
    ('unconscious', H.ALLY, True, 15, False),
    ('paralyzed', H.LEFT, False, 1, False),
])
def test_table_condition_critical_one_packet(monkeypatch, tmp_path, condition, attacker, ranged, natural, critical):
    def attack(e):
        a, target = e.state.actors[attacker], e.state.actors[H.RIGHT]
        assert e._distance_actor_to_actor(a, target) == (5 if attacker == H.LEFT else 10)
        apply(e, H.RIGHT, condition)
        script(e, [natural] * 2 + [4] * 30)
        spec = {'attack_bonus': 0, 'damage': DiceSpec(count=1, sides=6, modifier=3), 'damage_type': 'FORCE'}
        spec['range_ft' if ranged else 'reach_ft'] = 100
        e._resolve_attack_spec(a, target, spec, e._active_intent, source_definition_id='test:critical')
        if natural != 1:
            assert spec['resolved_attack_context'].critical is critical
    e = commit(monkeypatch, tmp_path, attack)
    rolls = [ev for ev in e.events if ev.event_type == 'DAMAGE_ROLLED' and ev.source_definition_id == 'test:critical']
    assert len(rolls) == (natural != 1)
    if rolls:
        row = rolls[0].payload
        assert row['critical'] is critical and len(row['dice']) == (2 if critical else 1)
        assert row['modifier'] == 3
        assert len([ev for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED' and ev.source_definition_id == 'test:critical']) == 1


def test_table_condition_critical_cancellation_once(monkeypatch, tmp_path):
    seen = []
    install(monkeypatch, 'critical_cancel', lambda *args: seen.append(args[2].entity_id) or True)
    def attack(e):
        before = len(seen)
        apply(e, H.RIGHT, 'paralyzed')
        script(e, [15, 15, 4, 4])
        spec = {'attack_bonus': 0, 'reach_ft': 100, 'damage': DiceSpec(count=1, sides=6, modifier=3), 'damage_type': 'FORCE'}
        e._resolve_attack_spec(e.state.actors[H.LEFT], e.state.actors[H.RIGHT], spec, e._active_intent, source_definition_id='test:cancel')
        assert not spec['resolved_attack_context'].critical
        assert spec['resolved_attack_context'].critical_cancelled
        assert seen[before:] == [H.RIGHT]
    e = commit(monkeypatch, tmp_path, attack)
    assert seen
    assert next(ev for ev in e.events if ev.event_type == 'DAMAGE_ROLLED').payload['critical'] is False


@pytest.mark.parametrize('invisible', [False, True])
def test_table_dodge_sight_and_independent_save(monkeypatch, tmp_path, invisible):
    def run(e):
        apply(e, H.RIGHT, 'condition:core.dodge')
        if invisible:
            apply(e, H.LEFT, 'invisible')
        a, target = e.state.actors[H.LEFT], e.state.actors[H.RIGHT]
        assert e._attack_mode(a, target) == ('ADVANTAGE' if invisible else 'DISADVANTAGE')
        assert e._roll_save(target, 'DEX', 10, 'test:dodge').mode == 'ADVANTAGE'
        apply(e, H.RIGHT, 'test_save_penalty', rule={'save_mode': {'DEX': 'DISADVANTAGE'}})
        apply(e, H.RIGHT, 'test_extra_adv', rule={'save_mode': {'DEX': 'ADVANTAGE'}})
        assert e._roll_save(target, 'DEX', 10, 'test:cancel_modes').mode == 'NORMAL'
    commit(monkeypatch, tmp_path, run)


@pytest.mark.parametrize('cause', ['incapacitated', 'speed', 'paralyzed', 'petrified', 'unconscious'])
def test_table_dodge_loss_is_permanent(monkeypatch, tmp_path, cause):
    def run(e):
        a, target = e.state.actors[H.LEFT], e.state.actors[H.RIGHT]
        apply(e, H.RIGHT, 'condition:core.dodge')
        if cause == 'speed':
            mid = e._add_modifier(target, 'test:stop', 'speed_ft', 'ADD', -100, 'SELF', expires_on='UNTIL_REMOVED')
        else:
            apply(e, H.RIGHT, cause)
        assert not e._has_condition(target, 'condition:core.dodge')
        assert e._roll_save(target, 'DEX', 10, 'test:lost_dodge').mode != 'ADVANTAGE'
        if cause == 'speed':
            del target.modifiers[mid]
            e._append_event('MODIFIER_REMOVED', 'test:stop', target_ids=(H.RIGHT,), payload={'modifier_id': mid})
        else:
            e._remove_condition(target, 'condition:typed.' + cause, 'test:recover')
        assert e._effective_speed(target) > 0
        # Waking does not stand the creature up: Unconscious leaves Prone.
        assert e._attack_mode(a, target) == ('ADVANTAGE' if cause == 'unconscious' else 'NORMAL')
        assert e._roll_save(target, 'DEX', 10, 'test:recovered').mode == 'NORMAL'
        if cause == 'unconscious':
            assert e._has_condition(target, 'condition:typed.prone')
            e._remove_condition(target, 'condition:typed.prone', 'test:stand')
            assert e._attack_mode(a, target) == 'NORMAL'
    e = commit(monkeypatch, tmp_path, run)
    assert not e._has_condition(e.state.actors[H.RIGHT], 'condition:core.dodge')
    assert sum(ev.event_type == 'CONDITION_REMOVED' and ev.payload.get('condition_id') == 'condition:core.dodge' for ev in e.events) == 1


@pytest.mark.parametrize('visibility,penalty,expected', [('visible',False,'DISADVANTAGE'), ('invisible',False,'NORMAL'), ('missing',False,'NORMAL'), ('cover',False,'NORMAL'), ('invisible',True,'DISADVANTAGE'), ('multiple',False,'DISADVANTAGE')])
def test_table_fear_uses_source_sight_and_keeps_other_penalties(monkeypatch, tmp_path, visibility, penalty, expected):
    def run(e):
        a, target = e.state.actors[H.LEFT], e.state.actors[H.RIGHT]
        source = 'missing' if visibility == 'missing' else H.ALLY
        if visibility in ('invisible', 'multiple'):
            apply(e, H.ALLY, 'invisible')
        if visibility == 'cover':
            from combat.target_knowledge import can_see
            assert not can_see(e, a, e.state.actors[H.ALLY])
            assert can_see(e, a, target)
        apply(e, H.LEFT, 'frightened', source=source)
        if visibility == 'multiple':
            apply(e, H.LEFT, 'frightened', source=H.RIGHT)
        if penalty:
            apply(e, H.LEFT, 'independent', rule={'attacks_have':'DISADVANTAGE','check_mode':{'ALL':'DISADVANTAGE'}})
        rows = typed_executor.condition_rules(a, engine=e)
        assert typed_executor.check_mode(a, 'INT', 'Investigation', engine=e) == expected
        assert e._attack_mode(a, target) == expected
        roll = e.roller.d20(modifier=0, actor_id=a.entity_id, reason='CHECK:test:fear', mode=typed_executor.check_mode(a,'INT',engine=e))
        e._record_roll(roll)
    commit(monkeypatch, tmp_path, run, covered=visibility == 'cover')


@pytest.mark.parametrize('damage,dc', [(1,10),(19,10),(20,10),(59,29),(60,30),(80,30)])
def test_table_concentration_damage_cap(monkeypatch, tmp_path, damage, dc):
    def run(e):
        target = e.state.actors[H.ALLY]
        # Evented temporary HP keeps an 80-point packet nonlethal.
        e._grant_temp_hp(target, 100, 'test:buffer', H.LEFT)
        e._start_concentration(target, 'test:concentration')
        e._commit_damage(target, damage, 'FORCE', 'test:concentration_hit', H.RIGHT, None, reaction_depth=0)
    e = commit(monkeypatch, tmp_path, run)
    checks = [ev for ev in e.events if ev.event_type == 'SAVE_ROLLED' and ev.source_definition_id == 'system:combat.concentration']
    assert len(checks) == 1 and checks[0].payload['dc'] == dc


@pytest.mark.parametrize('native,existing,penetrate', [(False,False,False),(False,True,False),(True,False,False),(True,True,False),(True,True,True),(False,True,True)])
def test_table_condition_defense_once_and_immunity(monkeypatch, tmp_path, native, existing, penetrate):
    from combat.gate2_runtime_content import AN, LEE
    target_id, attacker = (AN, LEE) if native else (H.RIGHT, H.LEFT)
    if penetrate:
        install(monkeypatch, 'resistance_ignored', lambda *args: True)
    def run(e):
        target = e.state.actors[target_id]
        assert (target_id not in e.typed_actor_ids) is native
        apply(e, target_id, 'petrified', source=attacker)
        apply(e, target_id, 'poisoned', source=attacker)
        assert not e._has_condition(target,'condition:typed.poisoned')
        if existing:
            e._add_modifier(target,'test:resist','damage_resistance','SET','POISON','SELF',expires_on='UNTIL_REMOVED')
        e._commit_damage(target, 19, 'POISON', 'test:defense', attacker, None, reaction_depth=0)
    e = (commit_native if native else commit)(monkeypatch, tmp_path, run)
    hit = next(ev for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED' and ev.source_definition_id == 'test:defense')
    assert hit.payload['hp_damage'] == (19 if penetrate else 9)


@pytest.mark.parametrize('use', [False, True])
def test_table_helmet_can_cancel_a_condition_critical(monkeypatch, tmp_path, use):
    from tests.test_lock9_critical_range import hold_sender, native
    from tests.r10_fixup_support import answer
    combat, table, mid = H.table_fight(tmp_path, [HELMET], ally_talents=[])
    def attack(e):
        apply(e,H.LEFT,'paralyzed',source=H.RIGHT)
        native(e,15,attacker=H.RIGHT,target=H.LEFT)
    H.on_hold(monkeypatch,attack)
    send=hold_sender(table,mid)
    before=combat._load_session(mid).engine.state.model_dump(mode='json')
    prompt=send()
    assert prompt['status']=='REACTION_REQUIRED' and 'Helmet Discipline' in str(prompt)
    assert CombatService(ROOT,tmp_path)._load_session(mid).engine.state.model_dump(mode='json')==before
    assert send([answer(prompt['reaction'],use=use)])['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    rolls=[ev for ev in loaded.engine.events if ev.event_type=='DAMAGE_ROLLED']
    assert len(rolls)==1 and rolls[0].payload['critical'] is (not use)
    receipts=[ev for ev in loaded.engine.events if ev.payload.get('critical_turned_normal')]
    assert len(receipts)==int(use)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
