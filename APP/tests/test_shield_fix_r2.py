"""Round-two Shield findings: real table transactions, persisted reload and replay."""
import copy
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_auto55_shield import ME, THEM, ALLY, TS, ROOT, _sheet, _conds
from tests.test_shield_fix_r1 import table_action, reload
from tests.test_riders_lane9 import _sheet as plain
from tests.test_lock_choices import install

FOCUS = 'resource:core.martial_focus'
INC = ['TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION', TS + 'projected_shield_face']


def match(tmp_path, talents, *, ally=False, friendly=False, packet=None):
    docs = copy.deepcopy([_sheet(talents, cl=16), plain([], 16, 60)]
                         + ([plain([], 16, 60)] if ally else []))
    ids = [ME, THEM] + ([ALLY] if ally else [])
    names = ['Shield Bearer', 'Attacker', 'Protected Ally']
    bundles = []
    for aid, doc, name in zip(ids, docs, names):
        doc['identity']['display_name'] = name
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=aid, reaction_plan={'ask': True}))
    if packet:
        # Fixture-only action: a save spell, or weapon attack followed by unrelated
        # damage from the same action. These packets exercise the production executor.
        bundle = bundles[1]
        action = copy.deepcopy(next(a for a in bundle['action_catalog']
                                    if a['display_name'] == 'Bi Shou (Dagger) attack'))
        action.update(source_definition_id='action:test.shield_packets', display_name='Packet test')
        typed = action['parameters']['typed']
        damage = {'type': 'damage', 'flat': 10, 'formula': 'none',
                  'damage_types': ['fire'], 'applies_to': 'target'}
        if packet == 'save':
            typed.pop('weapon', None)
            typed['effects'] = [{'type': 'save', 'ability': 'DEX', 'dc': 100,
                                 'on_fail': [damage], 'on_success': [damage]}]
        else:
            typed['effects'].append(damage)
        bundle['action_catalog'].append(action)
        bundle['actor_template']['action_ids'].append(action['source_definition_id'])
        from combat.gate2_runtime_models import ActionDefinition, EconomyKind
        recover = ActionDefinition(source_definition_id='action:test.recover_focus',
            display_name='Recover Focus', owner_id=ME, economy=EconomyKind.ACTION,
            resolution_kind='TYPED', target_kind='SELF', parameters={'typed': {
                'source': 'test:recover_focus', 'numbers': {}, 'duration': {'kind': 'instant'},
                'effects': [{'type': 'gain_resource', 'resource_id': FOCUS, 'flat': 1,
                             'formula': 'none', 'applies_to': 'self'}]}})
        bundles[0]['action_catalog'].append(recover.model_dump(mode='json'))
        bundles[0]['actor_template']['action_ids'].append(recover.source_definition_id)
    if friendly:
        for action in bundles[1]['action_catalog']:
            if action['display_name'] == 'Bi Shou (Dagger) attack':
                action['target_kind'] = 'ANY_CREATURE'
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    mid = service._finish_factory_match(bundles, ids,
        {ME: 'team:a', THEM: 'team:a' if friendly else 'team:b', **({ALLY: 'team:a'} if ally else {})},
        {ME: {'x': 3, 'y': 6}, THEM: {'x': 4, 'y': 6}, **({ALLY: {'x': 3, 'y': 5}} if ally else {})},
        service.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], ['auto55_shield'], [THEM],
        control_modes={aid: 'MANUAL' for aid in ids}, match_seed='SHIELD-R2-TABLE',
        display_name='Shield round two regressions', maximum_rounds=8)['match_id']
    advance(table, mid, ME)
    return service, table, mid


def advance(table, mid, actor):
    for _ in range(8):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        assert table_action(table, mid, 'end')['status'] == 'COMMITTED'
    raise AssertionError('turn did not arrive')


def finish(table, mid, name, choose, *, auto=False, target=None):
    answers, prompts = [], []
    for _ in range(20):
        before = table.combat._load_session(mid).engine.state.model_dump(mode='json')
        if auto:
            result = table.auto_step(mid, 0, answers)
        elif target:
            state = table.state(mid)
            group = next(g for g in state['menu']['actions'] if g['label'] == name)
            engine = table.combat._load_session(mid).engine
            cid = next(o['candidate_id'] for o in group['options']
                       if next(c for c in engine.legal_candidates() if c.candidate_id == o['candidate_id']).target_ids == (target,))
            result = table.act(mid, cid, state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'], answers)
        else:
            result = table_action(table, mid, name, answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        assert table.combat._load_session(mid).engine.state.model_dump(mode='json') == before
        prompt = result['reaction']
        prompts.append(prompt)
        options = choose(prompt)
        answers.append({**prompt['context'], 'selection': 'DECLINE' if options is None else 'USE',
                        'option_ids': options or []})
    raise AssertionError('action did not finish')


def defense(prompt):
    source = prompt['context']['reaction_source_id']
    if 'active_defense_payment' in source or (source == 'reaction:typed.SHIELD_BASE_ACTIVE_DEFENSE'
                                            and prompt.get('choice')):
        return ['reaction']
    if 'ACTIVE_DEFENSE' in source or 'COVER_ALLY' in source:
        return []
    return None


@pytest.mark.parametrize('packet', ['save', 'followup'])
def test_incarnation_does_not_reduce_nonattack_packets(tmp_path, monkeypatch, packet):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 19})
    service, table, mid = match(tmp_path, INC + ['TAL_SHIELD_EXTENSIVE_DEFENSE'], packet=packet)
    table_action(table, mid, 'SOVEREIGN SHIELD-SOUL INCARNATION')
    assert table_action(table, mid, 'Recover Focus')['status'] == 'COMMITTED'
    table_action(table, mid, 'Extensive Defense (Martial Focus)')
    table_action(table, mid, 'end')
    finish(table, mid, 'Packet test', defense)
    service = reload(service, mid)
    engine = service._load_session(mid).engine
    commits = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
               and e.source_definition_id == 'action:test.shield_packets']
    assert commits[-1].payload['reduced_to'] == 10
    if packet == 'followup':
        rolled = next(e for e in engine.events if e.event_type == 'DAMAGE_ROLLED'
                      and e.source_definition_id == 'action:test.shield_packets')
        assert commits[0].payload['reduced_to'] == max(0, rolled.payload['total'] - engine.state.actors[ME].proficiency_bonus)


def test_cracked_shield_stops_working_at_deadline(tmp_path, monkeypatch):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:crit', 'operation': 'replace', 'natural_result': 20})
    service, table, mid = match(tmp_path, ['TAL_SHIELD_UNBROKEN_RIM', TS + 'sacrificial_shield'])
    table_action(table, mid, 'end')
    def choose(p):
        source = p['context']['reaction_source_id']
        if 'unbroken_rim' in source:
            return ['cracked']
        if 'sacrificial_shield' in source:
            return ['break']
        return defense(p)
    finish(table, mid, 'Bi Shou (Dagger) attack', choose)
    service = reload(service, mid)
    me = service._load_session(mid).engine.state.actors[ME]
    assert 'condition:typed.shield_cracked' in _conds(me)
    assert 'condition:typed.shield_broken' not in _conds(me)
    advance(table, mid, ME)
    service = reload(service, mid)
    engine = service._load_session(mid).engine
    me = engine.state.actors[ME]
    # Sample after the prior Active Defense modifier expires, before the
    # cracked Shield's end-of-turn deadline: isolate the Shield bonus itself.
    working_ac = me.armor_class + engine._ac_modifier(me)
    assert table_action(table, mid, 'end')['status'] == 'COMMITTED'
    service = reload(service, mid)
    engine = service._load_session(mid).engine
    me = engine.state.actors[ME]
    assert 'condition:typed.shield_cracked' not in _conds(me)
    assert 'condition:typed.shield_broken' in _conds(me)
    from combat.ext.shield_wielding import wielding_a_shield
    assert not wielding_a_shield(engine, me)
    assert me.armor_class + engine._ac_modifier(me) == working_ac - 2


@pytest.mark.parametrize('choice', ['catch', 'intact'])
def test_catching_a_cracked_shield_preserves_deadline_but_intact_repairs_it(tmp_path, monkeypatch, choice):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:crit', 'operation': 'replace', 'natural_result': 20})
    service, table, mid = match(tmp_path, ['TAL_SHIELD_UNBROKEN_RIM', TS + 'sacrificial_shield'], packet='save')
    table_action(table, mid, 'end')
    def crack(p):
        source = p['context']['reaction_source_id']
        if 'unbroken_rim' in source:
            return ['cracked']
        if 'sacrificial_shield' in source:
            return ['break']
        return defense(p)
    finish(table, mid, 'Bi Shou (Dagger) attack', crack)
    service = reload(service, mid)
    before = next(c for c in service._load_session(mid).engine.state.actors[ME].conditions.values()
                  if c.condition_id == 'condition:typed.shield_cracked').expires_on
    advance(table, mid, ME)
    assert table_action(table, mid, 'Recover Focus')['status'] == 'COMMITTED'
    finish(table, mid, 'Drop Shield', lambda p: [choice] if 'unbroken_rim' in p['context']['reaction_source_id'] else None)
    service = reload(service, mid)
    me = service._load_session(mid).engine.state.actors[ME]
    cracked = [c for c in me.conditions.values() if c.condition_id == 'condition:typed.shield_cracked']
    assert bool(cracked) == (choice == 'catch')
    if cracked:
        assert cracked[0].expires_on == before
    assert table_action(table, mid, 'end')['status'] == 'COMMITTED'
    service = reload(service, mid)
    assert ('condition:typed.shield_broken' in _conds(service._load_session(mid).engine.state.actors[ME])) == (choice == 'catch')


@pytest.mark.parametrize('payment', ['focus', 'reaction', None])
@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO'])
def test_player_selects_defense_payment_on_other_turn(tmp_path, monkeypatch, payment, mode):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:miss', 'operation': 'replace', 'natural_result': 5})
    service, table, mid = match(tmp_path, [])
    table_action(table, mid, 'end')
    service.set_controller_mode(mid, actor_id=THEM, controller_mode=mode)
    def choose(p):
        if ('active_defense_payment' in p['context']['reaction_source_id']
                or p['context']['reaction_source_id'] == 'reaction:typed.SHIELD_BASE_ACTIVE_DEFENSE'):
            assert 'Active Defense' in p['trigger'] and 'Shield Bearer' in p['trigger']
            assert 'Attacker' in p['trigger'] and 'Dagger' in p['trigger']
            return [payment] if payment else None
        return None
    prompts = finish(table, mid, 'Bi Shou (Dagger) attack', choose, auto=mode == 'LOCAL_AUTO')
    service = reload(service, mid)
    payments = [p for p in prompts if ('active_defense_payment' in p['context']['reaction_source_id']
                or p['context']['reaction_source_id'] == 'reaction:typed.SHIELD_BASE_ACTIVE_DEFENSE')]
    assert len(payments) == 1  # one owner handles consent and payment, never two prompts
    me = service._load_session(mid).engine.state.actors[ME]
    assert me.reaction_available == (payment != 'reaction')
    assert me.resources[FOCUS] == (0 if payment == 'focus' else 1)
    rows = service._load_session(mid).engine.typed_reaction_rows[ME]
    assert all(not r.get('shield_focus_payment') and not r.get('costs')
               for r in rows if r.get('feature_id') == 'SHIELD_BASE_ACTIVE_DEFENSE')


@pytest.mark.parametrize('friendly,target', [(False, ALLY), (True, ALLY), (True, ME)])
def test_incarnation_focus_belongs_to_cover_bearer_only_on_hostile_miss(tmp_path, monkeypatch, friendly, target):
    # The ally's AC is 16; +2 attack rolls 14 (16 total), so Cover Ally turns it aside.
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:near', 'operation': 'replace',
                                               'natural_result': 14 if target == ALLY else 16})
    service, table, mid = match(tmp_path, INC, ally=True, friendly=friendly)
    table_action(table, mid, 'SOVEREIGN SHIELD-SOUL INCARNATION')
    table_action(table, mid, 'end')
    advance(table, mid, THEM)
    # Friendly fire is a test fixture action with general creature targeting.
    finish(table, mid, 'Bi Shou (Dagger) attack', defense, target=target)
    service = reload(service, mid)
    engine = service._load_session(mid).engine
    roll = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED')
    assert roll.payload['target_ac'] - 2 <= roll.payload['modified_total'] < roll.payload['target_ac']
    assert any(e.event_type == 'REACTION_WINDOW_OPENED' and e.source_definition_id == ('TAL_SHIELD_COVER_ALLY' if target == ALLY else 'SHIELD_BASE_ACTIVE_DEFENSE')
               for e in engine.events)
    assert engine.state.actors[ME].resources[FOCUS] == (0 if friendly else 1)
    assert not any(e.event_type == 'RESOURCE_GAINED' and e.actor_id == ALLY for e in engine.events)


def test_incarnation_free_grant_precedes_focus_payment(tmp_path, monkeypatch):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:miss', 'operation': 'replace', 'natural_result': 5})
    service, table, mid = match(tmp_path, INC, packet='save')
    table_action(table, mid, 'SOVEREIGN SHIELD-SOUL INCARNATION')
    table_action(table, mid, 'Recover Focus')
    table_action(table, mid, 'end')
    prompts = finish(table, mid, 'Bi Shou (Dagger) attack', defense)
    service = reload(service, mid)
    me = service._load_session(mid).engine.state.actors[ME]
    assert not any('active_defense_payment' in p['context']['reaction_source_id'] for p in prompts)
    assert me.reaction_available and me.resources[FOCUS] == 1


def test_ai_bearer_chooses_reaction_automatically(tmp_path, monkeypatch):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:miss', 'operation': 'replace', 'natural_result': 5})
    service, table, mid = match(tmp_path, [])
    table_action(table, mid, 'end')
    service.set_controller_mode(mid, actor_id=ME, controller_mode='LOCAL_AUTO')
    prompts = finish(table, mid, 'Bi Shou (Dagger) attack', lambda p: None)
    service = reload(service, mid)
    me = service._load_session(mid).engine.state.actors[ME]
    assert not any('active_defense_payment' in p['context']['reaction_source_id'] for p in prompts)
    assert not me.reaction_available and me.resources[FOCUS] == 1


def test_landing_options_are_plain_words(tmp_path):
    # Reuse the real high jump -> landing transaction; inspect its rendered menu.
    from tests.test_shield_fix_r1 import table_match
    service, table, mid = table_match(tmp_path,
        ['TAL_SHIELD_SHIELD_SKATE', 'TAL_SHIELD_RIDING_THE_FALLING_STAR'], strength=50)
    table_action(table, mid, 'SHIELD SKATE')
    state = table.state(mid)
    engine = service._load_session(mid).engine
    jump = next(c for c in engine.legal_candidates() if c.destination is not None
                and c.kind.value == 'MOVE' and c.destination.z == 4
                and (c.destination.x, c.destination.y) == (3, 4))
    answers, saw_landing = [], False
    for _ in range(10):
        result = table.act(mid, jump.candidate_id, state['menu']['decision_id'],
                           state['menu']['state_version'], state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            break
        p = result['reaction']
        landing = 'falling_star_landing' in p['context']['reaction_source_id']
        if landing:
            saw_landing = True
            assert all('cell:' not in o['label'] and 'Move to' in o['label'] for o in p['choice']['options'])
        answers.append({**p['context'], 'selection': 'USE' if landing else 'DECLINE',
                        'option_ids': ['cell:3,5'] if landing else []})
    else:
        raise AssertionError('landing did not finish')
    assert saw_landing
    service = reload(service, mid)
    pos = service._load_session(mid).engine.state.actors[ME].position
    assert (pos.x, pos.y, pos.z) == (3, 5, 0)
