"""Review r2 regressions through session transactions, cold verify and replay.

The practice fixture spends ordinary arrows through the public stock mutation
in a journaled setup action. It avoids nineteen irrelevant turns; no inventory
or saved fight is edited after creation. Strike vetoes are test hook providers.
"""
from copy import deepcopy
import json
import pytest
from combat import ext
from combat.ext.ammunition import spend_unrolled_projectile
from combat.ext.hand_occupancy import weapon_grips
from tests import test_a2_barrage_transactions as transactions
from tests.test_a2_barrage import finish, option, ready, reload, SUPPRESS, PRESSURE
from tests.test_a2_barrage_fix_round import QUICK, THROWN_KIT
from tests.test_auto58_barrage_projectiles import ARROW_KIT
from tests.test_tabletop_hunt6 import LEFT, ROOT


def practice(monkeypatch, kit, pieces):
    """Compile an explicit NONE-economy practice action using the owner's bow."""
    ext.effects()
    def spend(ctx, row):
        for _ in range(row['pieces']):
            spend_unrolled_projectile(ctx)
    monkeypatch.setitem(ext._EFFECTS, 'test:practice_arrows', spend)
    real = transactions.compile_character
    def compile_owner(doc, *, actor_id, **kwargs):
        if actor_id == LEFT:
            doc = deepcopy(doc)
            doc['equipment'] = [kit]
        bundle = real(doc, actor_id=actor_id, **kwargs)
        if actor_id == LEFT:
            bow = next(a for a in bundle['action_catalog']
                       if (a['parameters'].get('typed') or {}).get('ammunition'))
            action = deepcopy(bow)
            action.update(source_definition_id='test:practice', display_name='Practice arrows',
                          economy='NONE', target_kind='SELF')
            action['parameters']['typed']['effects'] = [{'type': 'test:practice_arrows', 'pieces': pieces}]
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append('test:practice')
        return bundle
    monkeypatch.setattr(transactions, 'compile_character', compile_owner)


def pressure(engine, target):
    return any(c.condition_id == PRESSURE for c in engine.state.actors[target].conditions.values())


def spent(engine):
    return sum(v for k, v in engine.state.actors[LEFT].turn_flags.items()
               if k.startswith('_round_ammunition_spent:'))


@pytest.mark.parametrize('empty_at_start', [True, False])
def test_quick_draw_empty_bow_unforced_auto_step(tmp_path, monkeypatch, empty_at_start):
    kit = deepcopy(ARROW_KIT)
    next(i for i in kit['starting_kit']['items'] if i['item_id'].endswith('arrows_20'))['quantity'] = 1
    kit['starting_kit']['items'].append(deepcopy(THROWN_KIT['starting_kit']['items'][0]))
    if empty_at_start:
        next(i for i in kit['starting_kit']['items'] if i['item_id'].endswith('arrows_20'))['quantity'] = 0
    practice(monkeypatch, kit, 19)
    combat, table, mid, enemy = transactions.battle(tmp_path, [QUICK], hit=False)
    finish(table, mid, option(table, mid, 'Stow Fei Biao'))
    ready(table, mid)
    if not empty_at_start:
        finish(table, mid, option(table, mid, 'Practice arrows'))
        finish(table, mid, option(table, mid, 'Gong Jian (Bow and Arrow) attack', enemy), lambda p: False)
        assert spent(reload(tmp_path, mid)) == 20
    engine = reload(tmp_path, mid)
    before = len(engine.events)
    owner = engine.state.actors[LEFT]
    economy = (owner.action_available, owner.bonus_action_available)
    assert any('gong_jian' in wid for wid in weapon_grips(engine, owner))
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    assert table.auto_step(mid, table.state(mid)['last_sequence'], [])['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[LEFT]
    assert owner.turn_flags.get('barrage_quick_draw_used') is True
    grips = weapon_grips(engine, owner)
    assert any('fei_biao' in wid for wid in grips)
    assert (owner.action_available, owner.bonus_action_available) == economy
    assert any(e.source_definition_id == QUICK for e in engine.events[before:])


@pytest.mark.parametrize('remaining', [1, 2])
def test_evade_tracked_ammunition_requires_two_fired_shots(tmp_path, monkeypatch, remaining):
    kit = deepcopy(ARROW_KIT)
    next(i for i in kit['starting_kit']['items'] if i['item_id'].endswith('arrows_20'))['quantity'] = 1
    practice(monkeypatch, kit, 19 - remaining)
    combat, table, mid, enemy = transactions.battle(tmp_path, [SUPPRESS], hit=False)
    ready(table, mid)
    finish(table, mid, option(table, mid, 'Practice arrows'))
    finish(table, mid, option(table, mid, 'Barrage: Gong Jian (Bow and Arrow) + Suppressing Fire', enemy), lambda p: False)
    engine = reload(tmp_path, mid)
    assert spent(engine) == 20 - remaining
    before = len(engine.events)
    finish(table, mid, option(table, mid, 'Suppressing Fire: Gong Jian', enemy), lambda p: 'evade')
    engine = reload(tmp_path, mid)
    assert spent(engine) == 20
    assert pressure(engine, enemy) == (remaining == 2)
    target = engine.state.actors[enemy]
    assert engine._effective_speed(target) == (target.speed_ft // 2 if remaining == 2 else target.speed_ft)
    messages = [e.payload.get('text', '') for e in engine.events[before:]
                if e.source_definition_id == SUPPRESS and e.event_type == 'PASSIVE_TRIGGERED']
    assert messages
    assert any('both wild shots automatically miss' in m for m in messages) == (remaining == 2)
    if remaining == 1:
        assert any('1 wild shot' in m and 'no suppression penalties' in m for m in messages)


@pytest.mark.parametrize('returning', [False, True])
def test_evade_physical_thrown_copy_and_returning_exception(tmp_path, monkeypatch, returning):
    kit = deepcopy(THROWN_KIT)
    if returning:
        from factory_authoring.starting_kits import _authorities
        authority = json.loads((ROOT / 'authority/Tianxia_Treasure_Weapon_Authority_R1.json').read_text())
        enchantment = next(r for r in authority['enchantments'] if r['enchantment_id'].endswith('.returning_inscription'))
        kit['starting_kit']['resolved_treasure_weapon'] = {
            'name': 'Returning dart', 'chassis': _authorities()[1]['tianxia.mortal.weapon.fei_biao'],
            'refinement_bonus': 1, 'enchantments': [enchantment]}
    real = transactions.compile_character
    def compile_owner(doc, *, actor_id, **kwargs):
        if actor_id == LEFT:
            doc = deepcopy(doc)
            doc['equipment'] = [kit]
        bundle = real(doc, actor_id=actor_id, **kwargs)
        if actor_id == LEFT and not returning:
            # Setup-only recovery uses the native physical recovery effect. The
            # shipped pickup costs a Bonus Action, already reserved for the volley.
            pickup = next(a for a in bundle['action_catalog'] if a['display_name'].startswith('Pick up Fei Biao'))
            recovery = deepcopy(pickup)
            recovery.update(source_definition_id='test:recover_dart', display_name='Test recover dart', economy='NONE')
            bundle['action_catalog'].append(recovery)
            bundle['actor_template']['action_ids'].append('test:recover_dart')
        return bundle
    monkeypatch.setattr(transactions, 'compile_character', compile_owner)
    combat, table, mid, enemy = transactions.battle(tmp_path, [SUPPRESS], hit=False)
    engine = reload(tmp_path, mid)
    primary = next(a.display_name for a in engine.action_catalog.values()
                   if a.owner_id == LEFT and a.display_name.startswith('Barrage:') and 'Suppressing Fire' in a.display_name)
    finish(table, mid, option(table, mid, primary, enemy), lambda p: False)
    if not returning:
        # Recover the actual physical copy through a journaled native effect.
        finish(table, mid, option(table, mid, 'Test recover dart'))
    engine = reload(tmp_path, mid)
    before = len(engine.events)
    follow = next(a.display_name for a in engine.action_catalog.values()
                  if a.owner_id == LEFT and a.display_name.startswith('Suppressing Fire:'))
    finish(table, mid, option(table, mid, follow, enemy), lambda p: 'evade')
    engine = reload(tmp_path, mid)
    assert pressure(engine, enemy) == returning
    from combat.carry import DROPPED
    drops = [e for e in engine.events[before:] if e.event_type == 'CONDITION_APPLIED'
             and e.payload.get('condition_id') == DROPPED]
    # Actual physical availability decides each release, including automatic return.
    assert len(drops) == (2 if returning else 1)
    messages = [e.payload.get('text', '') for e in engine.events[before:] if e.source_definition_id == SUPPRESS]
    assert any('both wild shots automatically miss' in m for m in messages) == returning


def test_evade_first_strike_veto_never_grants_pressure(tmp_path, monkeypatch):
    ext.effects()
    def veto(ctx, target, shot):
        if ctx.action.display_name.startswith('Suppressing Fire:'):
            return False
        return None
    monkeypatch.setitem(ext._HOOKS, 'attack_allowed', [*ext._HOOKS['attack_allowed'], veto])
    combat, table, mid, enemy = transactions.battle(tmp_path, [SUPPRESS], hit=False)
    ready(table, mid)
    finish(table, mid, option(table, mid, 'Barrage: Gong Jian (Bow and Arrow) + Suppressing Fire', enemy), lambda p: False)
    before = spent(reload(tmp_path, mid))
    finish(table, mid, option(table, mid, 'Suppressing Fire: Gong Jian', enemy), lambda p: 'evade')
    engine = reload(tmp_path, mid)
    assert spent(engine) == before and not pressure(engine, enemy)
    assert engine._effective_speed(engine.state.actors[enemy]) == engine.state.actors[enemy].speed_ft
    assert not any('both wild shots automatically miss' in e.payload.get('text', '')
                   for e in engine.events if e.source_definition_id == SUPPRESS)
