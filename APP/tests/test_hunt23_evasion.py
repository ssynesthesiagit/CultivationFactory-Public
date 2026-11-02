"""Attack-scoped Flowing Evasion through saved tables and real seeded dice."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.hunt23_support import action_sender, turn

FEATURE = 'tianxia.subpath.qi.abyssal_depths_cultivator.feature.flowing_evasion'
MOON = 'tianxia.subpath.qi.abyssal_depths_cultivator.feature.moon_s_pull'
A, D = 'actor:factory.probe_attacker', 'actor:factory.probe_defender'
ACTION = 'Void Needle: Empty Vitality + Nullifying Strike: Hollowed'


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('selection', ['USE', 'USE_SUBMERGED', 'USE_MOON', 'DECLINE', 'AUTO', 'AUTO_MOON'])
@pytest.mark.parametrize('native', [False, True])
def test_all_attack_packets_one_decision_then_reload(tmp_path, ai, selection, native):
    attacker = sheet(['TAL_VOID_VOID_NEEDLE', 'TAL_VOID_NULLIFYING_STRIKE'], cl=10)
    in_moon = selection.endswith('_MOON')
    defender = sheet([FEATURE, MOON] if in_moon else [FEATURE], cl=10)
    attacker['ability_scores_and_statistics']['technique_attack_bonus'] = 20
    attacker['identity']['display_name'] = 'Attacker'
    defender['identity']['display_name'] = 'Defender'
    svc = CombatService(ROOT, tmp_path); table = TabletopService(svc, tmp_path)
    bundles = [compile_character(attacker, actor_id=A), compile_character(defender, actor_id=D,
        reaction_plan={'mode':'ask', 'ask':True})]
    if in_moon:
        from combat.canonical import canonical_sha256
        # Freeze concentration success in the sealed fixture, without replacing
        # any engine/dice function. The conditional movement needs a live field.
        bundles[1]['actor_template']['saving_throws']['CON'] = 1000
        bundles[1].pop('bundle_sha256', None)
        bundles[1]['bundle_sha256'] = canonical_sha256(bundles[1])
    action_name = ACTION
    if native:
        # Sealed fixture with two separate native attack rolls: movement belongs
        # between them, and the second attack must not inherit the first reduction.
        from combat.canonical import canonical_sha256
        source = 'action:test.hunt23_native'
        action_name = 'Test native attacks'
        bundles[0]['action_catalog'].append({'source_definition_id':source, 'display_name':action_name,
            'owner_id':A, 'economy':'ACTION', 'resolution_kind':'MULTI_ATTACK', 'target_kind':'HOSTILE_ENTITY',
            'range_ft':60, 'attack_bonus':20, 'attack_count':2, 'damage':{'count':1,'sides':2,'modifier':9},
            'damage_type':'FORCE', 'parameters':{}, 'costs':[]})
        bundles[0]['actor_template']['action_ids'].append(source)
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
    mid = svc._finish_factory_match(bundles, [A,D], {A:'a',D:'b'},
        {A:{'x':3,'y':6}, D:{'x':6,'y':6}}, svc.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [A], [D], control_modes={A:'MANUAL',D:'MANUAL'}, match_seed='P4',
        display_name='Evasion regression', maximum_rounds=3)['match_id']
    if in_moon:
        # Cast a real owned field through the table and reload it before the hit.
        # Its edge contains Defender but excludes Attacker, avoiding a turn-start
        # pull that would change the attack fixture.
        turn(table, mid, D)
        state = table.state(mid); menu = state['menu']
        group = next(g for g in menu['actions'] if 'Moon’s Pull' in g['label'])
        cid = next(o['candidate_id'] for o in group['options']
                   if o.get('destination') == {'x':8, 'y':8})
        assert table.act(mid, cid, menu['decision_id'], menu['state_version'],
                         state['last_sequence'], [])['status'] == 'COMMITTED'
        saved = CombatService(ROOT, tmp_path)._load_session(mid)
        zone = next(z for z in saved.engine.state.zones.values() if z.active and z.owner_id == D)
        assert saved.engine._footprint_intersects(saved.engine.state.actors[D], zone.affected_cells)
        assert not saved.engine._footprint_intersects(saved.engine.state.actors[A], zone.affected_cells)
        assert saved.verify()['status'] == saved.mechanical.replay()['status'] == 'PASS'
    turn(table, mid, A)
    if not native and not ai:
        # Player rows now configure the rider on the parent attack instead of
        # offering a composed copy. Preserve the same Hollowed/Qi/Force hit.
        parent = 'Void Needle: Empty Vitality'
        engine = svc._load_session(mid).engine
        family = next(a.source_definition_id for a in engine.action_catalog.values()
                      if a.owner_id == A and a.display_name == parent)
        for field, value in (('on', 'toggle'), ('option', '0'), ('payment', '0'), ('damage', 'force')):
            engine = svc._load_session(mid).engine
            source = next(a.source_definition_id for a in engine.action_catalog.values()
                          if (a.parameters.get('attack_modifier_setting') or {}) == {
                              'family': family, 'modifier': 'TAL_VOID_NULLIFYING_STRIKE',
                              'name': 'Nullifying Strike', 'field': field, 'value': value})
            state = table.state(mid); menu = state['menu']
            cid = next(c.candidate_id for c in engine.legal_candidates() if c.source_definition_id == source)
            assert table.act(mid, cid, menu['decision_id'], menu['state_version'],
                             state['last_sequence'], [])['status'] == 'COMMITTED'
        action_name = parent
    if selection.startswith('AUTO'):
        svc.set_controller_mode(mid, actor_id=D, controller_mode='LOCAL_AUTO')
    send = action_sender(svc, table, mid, action_name, ai=ai)
    answers = []; prompts = []; chosen_destination = None
    for _ in range(8):
        result = send(answers)
        if result['status'] != 'REACTION_REQUIRED':
            break
        prompt = result['reaction']; prompts.append(prompt)
        using = selection.startswith('USE')
        options = ['halve'] if using else []
        if 'distance' in prompt['reaction'].lower():
            options = ['10' if selection == 'USE_SUBMERGED' else '5']
        elif 'movement' in prompt['reaction'].lower():
            option = next(o['id'] for o in prompt['choice']['options'] if '(10 ft)' in o['label']) \
                     if selection in {'USE_SUBMERGED', 'USE_MOON'} else 'cell:6,5'
            options = [option]
            chosen_destination = tuple(int(v) for v in option.removeprefix('cell:').split(','))
        answers.append({**prompt['context'], 'selection':'USE' if using else selection, 'option_ids':options})
    assert result['status'] == 'COMMITTED'
    assert len(prompts) == (0 if selection.startswith('AUTO') else 2 if selection == 'USE_MOON'
                           else 3 if selection.startswith('USE') else 2 if native else 1)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    packets = [e.payload['hp_damage'] for e in loaded.engine.events
               if e.event_type == 'DAMAGE_COMMITTED' and D in e.target_ids]
    if native:
        originals = [e.payload['rolled_or_pending_damage'] for e in loaded.engine.events
                     if e.event_type == 'DAMAGE_COMMITTED' and D in e.target_ids]
        assert len(originals) == 2
        assert sum(packets) == (sum(originals) if selection == 'DECLINE' else originals[0]//2 + originals[1])
    else:
        originals = [e.payload['rolled_or_pending_damage'] for e in loaded.engine.events
                     if e.event_type == 'DAMAGE_COMMITTED' and D in e.target_ids]
        assert sum(packets) == (sum(originals) if selection == 'DECLINE' else sum(originals)//2)
        if not in_moon:
            # Void Needle now retains its printed +2 Path modifier in this fixture.
            assert sum(packets) == (21 if selection == 'DECLINE' else 10)
    assert loaded.engine.state.actors[D].resources['resource:core.qi'] == (30 if selection == 'DECLINE' else 28) - (5 if in_moon else 0)
    position = loaded.engine.state.actors[D].position
    if selection.startswith('AUTO'):
        assert (position.x,position.y) != (6,6)
    else:
        destination = chosen_destination if selection.startswith('USE') else (6,6)
        assert (position.x, position.y) == destination
    if selection.startswith('USE'):
        assert 'Opportunity Attacks' in prompts[-1]['trigger']
        if in_moon:
            assert 'within 10 feet' in prompts[-1]['trigger']
            assert not any('distance' in p['reaction'].lower() for p in prompts)
        movement = [e for e in loaded.engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == D]
        damage = [e.sequence for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED' and D in e.target_ids]
        assert movement and movement[0].sequence > (damage[0] if native else max(damage))
        if native:
            attacks = [e.sequence for e in loaded.engine.events if e.event_type == 'ATTACK_ROLLED']
            assert movement[-1].sequence < attacks[1]
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('dc,escapes', [(1, True), (100, False)])
def test_slip_the_grasp_save_precedes_step(dc, escapes):
    from tests.test_lock4_flowing_evasion import fight, attack, ME, ATTACKER
    engine = fight()
    defender = engine.state.actors[ME]
    grapple = next(a for a in engine.action_catalog.values() if a.owner_id == ATTACKER
                   and (a.parameters.get('typed') or {}).get('unarmed_option') == 'grapple')
    engine._apply_condition(defender, 'condition:typed.grappled', grapple.source_definition_id, ATTACKER,
                            expires_on='UNTIL_REMOVED', data={'save_dc':dc})
    start = defender.position
    attack(engine)
    rolls = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == FEATURE]
    assert len(rolls) == 1 and rolls[0].payload['success'] == escapes
    remains = any(c.condition_id.endswith('.grappled') for c in defender.conditions.values())
    assert remains != escapes
    moves = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ME]
    assert bool(moves) == escapes
    if moves:
        assert moves[0].sequence > rolls[0].sequence and defender.position != start
