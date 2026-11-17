"""Shield second pass: committed table intents, cold reload and mechanical replay."""
import copy
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_auto55_shield import ME, THEM, ALLY, ROOT, _sheet
from tests.test_riders_lane9 import _sheet as plain
from tests.test_shield_fix_r1 import reload, table_action
from tests.test_shield_fix_r2 import advance, finish
from tests.test_lock_choices import install

DISC = 'TAL_SHIELD_RETURNING_SHIELD_DISC'
SWEEP = 'TAL_SHIELD_CELESTIAL_DISC_SWEEP'


def match(tmp_path, talents, *, cl=17, distance=25, second_enemy=False, shield=True, blocked_cells=(), target_y=6):
    docs = copy.deepcopy([_sheet(talents, cl=cl, shield=shield), plain([], cl, 1000), plain([], cl, 1000)])
    ids = [ME, THEM, ALLY]
    if second_enemy:
        ids.append(THEM + ':second')
        docs.append(copy.deepcopy(plain([], cl, 1000)))
    for row in docs[0]['ability_scores_and_statistics']['abilities']:
        if row['ability'] in ('STR', 'DEX'):
            row.update(score=18 if row['ability'] == 'STR' else 12, modifier=4 if row['ability'] == 'STR' else 1)
    for aid, doc in zip(ids, docs):
        doc['identity']['display_name'] = {ME: 'Shield Bearer', THEM: 'Enemy', ALLY: 'Ally'}.get(aid, 'Second enemy')
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
        doc['ability_scores_and_statistics']['technique_save_dc'] = 15
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={'ask': True}) for aid, doc in zip(ids, docs)]
    svc = CombatService(ROOT, tmp_path)
    table = TabletopService(svc, tmp_path)
    arena = {**svc.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], 'map_terrain': [], 'terrain_regions': ([{'region_id': 'sweep-blockers', 'terrain_type': 'BLOCKED', 'movement_cost': 0, 'cells': [{'x': x, 'y': y} for x, y in blocked_cells]}] if blocked_cells else []), 'width_squares': 30}
    mid = svc._finish_factory_match(bundles, ids, {ME: 'team:a', THEM: 'team:b', ALLY: 'team:a', **({THEM + ':second': 'team:b'} if second_enemy else {})},
        {ME: {'x': 3, 'y': 6}, THEM: {'x': 3 + distance // 5, 'y': target_y}, ALLY: {'x': 5, 'y': 6}, **({THEM + ':second': {'x': 7, 'y': 6}} if second_enemy else {})},
        arena, ['a2-shield'], [THEM], control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='A2SHIELD', display_name='Shield tests', maximum_rounds=10)['match_id']
    advance(table, mid, ME)
    return svc, table, mid


@pytest.mark.parametrize('cl,count', [(5, 1), (11, 2), (17, 3)])
@pytest.mark.parametrize('ability', ['STR', 'DEX'])
def test_disc_weapon_ability_damage_and_return(tmp_path, monkeypatch, cl, count, ability):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 19})
    svc, table, mid = match(tmp_path, [DISC], cl=cl)
    engine = svc._load_session(mid).engine
    before = engine.state.actors[ME].armor_class + engine._ac_modifier(engine.state.actors[ME])
    from combat import armour
    from combat.ext.shield_wielding import wielding_a_shield
    in_flight = []
    def observe(engine, event_type, kwargs):
        if event_type == 'ATTACK_ROLLED' and engine.events and DISC in engine.events[-1].source_definition_id:
            actor = engine.state.actors[ME]
            in_flight.append((armour.shield_bonus_earning(engine, actor), wielding_a_shield(engine, actor)))
    install(monkeypatch, 'event', observe)
    kinds = []
    def attack_kind(ctx, target, hit, critical):
        if DISC in ctx.source:
            kinds.append(ctx.attack_effect['attack_kind'])
    install(monkeypatch, 'attack_result', attack_kind)
    prompts = finish(table, mid, 'RETURNING SHIELD DISC', lambda p: [ability] if 'shield_disc_ability' in p['context']['reaction_source_id'] else None)
    svc = reload(svc, mid)
    engine = svc._load_session(mid).engine
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and DISC in e.source_definition_id]
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_ROLLED' and DISC in e.source_definition_id]
    assert len(attacks) == 1
    assert attacks[0].payload['modifier'] == (4 if ability == 'STR' else 1) + engine.state.actors[ME].proficiency_bonus
    assert kinds and set(kinds) == {'weapon'}
    assert in_flight and all(row == (0, False) for row in in_flight)
    assert any('shield_disc_ability' in p['context']['reaction_source_id'] for p in prompts)
    assert len(damage) == 1 and len(damage[0].payload['dice']) == count
    assert damage[0].payload['modifier'] == (4 if ability == 'STR' else 1)
    from combat import armour, carry
    me = engine.state.actors[ME]
    assert not carry.lost_to_another_hand(me, armour.shield_item_key(engine, me))
    assert me.armor_class + engine._ac_modifier(me) == before
    assert not any(e.event_type == 'GM_RIDER' and DISC in e.source_definition_id for e in engine.events)


@pytest.mark.parametrize('choice', ['Prone', 'Push'])
def test_sweep_selects_one_failed_save_rider_and_only_harms_enemies(tmp_path, monkeypatch, choice):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:fail', 'operation': 'replace', 'natural_result': 1})
    svc, table, mid = match(tmp_path, [DISC, SWEEP])
    before = svc._load_session(mid).engine.state.actors[ALLY].model_dump(mode='json')
    state = table.state(mid)
    names = [g['label'] for g in state['menu']['actions']]
    name = next(n for n in names if 'CELESTIAL-DISC SWEEP' in n and 'Line' in n)
    finish_directed(table, mid, name, lambda p: [choice] if 'shield_sweep_rider' in p['context']['reaction_source_id'] else ['north'] if 'directed_movement' in p['context']['reaction_source_id'] else None)
    svc = reload(svc, mid)
    engine = svc._load_session(mid).engine
    assert engine.state.actors[ALLY].model_dump(mode='json') == before
    foe = engine.state.actors[THEM]
    assert ('condition:typed.prone' in {c.condition_id for c in foe.conditions.values()}) == (choice == 'Prone')
    assert (foe.position.y < 6) == (choice == 'Push')
    if choice == 'Push':
        assert (foe.position.x, foe.position.y) == (8, 3)  # exactly 15 feet north, not a shorter step
    if choice == 'Prone':
        assert (foe.position.x, foe.position.y) == (8, 6)


def test_training_utilize_doff_don_uses_action_and_shared_hand_state(tmp_path):
    from combat import armour, carry
    from combat.ext.shield_wielding import wielding_a_shield
    from combat.ext.hand_occupancy import free_hands
    svc, table, mid = match(tmp_path, [DISC])
    engine = svc._load_session(mid).engine
    me = engine.state.actors[ME]
    ac = me.armor_class + engine._ac_modifier(me)
    hands = len(free_hands(engine, me))
    assert table_action(table, mid, 'Doff Shield (Utilize Action)')['status'] == 'COMMITTED'
    svc = reload(svc, mid)
    table.combat = svc
    engine = svc._load_session(mid).engine
    me = engine.state.actors[ME]
    assert me.armor_class + engine._ac_modifier(me) == ac - 2
    assert not wielding_a_shield(engine, me)
    assert len(free_hands(engine, me)) == hands + 1
    assert not any(g['label'] == 'RETURNING SHIELD DISC' for g in table.state(mid)['menu']['actions'])
    assert not me.action_available
    table_action(table, mid, 'end')
    advance(table, mid, ME)
    assert table_action(table, mid, 'Don Shield (Utilize Action)')['status'] == 'COMMITTED'
    svc = reload(svc, mid)
    engine = svc._load_session(mid).engine
    me = engine.state.actors[ME]
    assert me.armor_class + engine._ac_modifier(me) == ac
    assert wielding_a_shield(engine, me)
    assert len(free_hands(engine, me)) == hands
    assert carry.owned_item_location(me, armour.shield_item_key(engine, me)).startswith('hand:')


def test_training_is_required_and_sheet_and_compiler_agree():
    from combat.armour import sheet_facts
    trained = copy.deepcopy(_sheet([]))
    bare = copy.deepcopy(trained)
    bare['spheres_and_talents'] = {'sphere_record_ids': [], 'automatic_sphere_component_record_ids': [],
                                  'learned_talent_record_ids': []}
    bundles = [compile_character(doc, actor_id=ME) for doc in (trained, bare)]
    assert bundles[0]['actor_template']['armor_class'] == bundles[1]['actor_template']['armor_class'] + 2
    for doc, bundle in zip((trained, bare), bundles):
        assert sheet_facts(doc, doc['equipment'][0]['starting_kit'])['armor_class'] == bundle['actor_template']['armor_class']


def test_ai_sweep_with_ally_and_enemy_in_range(tmp_path, monkeypatch):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:failed_save', 'operation': 'replace', 'natural_result': 1})
    svc, table, mid = match(tmp_path, [DISC, SWEEP])
    before = svc._load_session(mid).engine.state.actors[ALLY].model_dump(mode='json')
    svc.set_controller_mode(mid, actor_id=ME, controller_mode='LOCAL_AUTO')
    result = table.auto_step(mid, 0)
    assert result['status'] == 'COMMITTED', result
    svc = reload(svc, mid)
    engine = svc._load_session(mid).engine
    assert any(e.event_type == 'INTENT_ACCEPTED' and SWEEP in e.source_definition_id for e in engine.events)
    assert engine.state.actors[ALLY].model_dump(mode='json') == before
    assert engine.state.actors[THEM].current_hp < 1000
    assert all(e.target_ids == (THEM,) for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and SWEEP in e.source_definition_id)


@pytest.mark.parametrize('distance,disadvantage', [(25, False), (35, True), (90, True)])
def test_disc_normal_and_long_range(tmp_path, monkeypatch, distance, disadvantage):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 19})
    svc, table, mid = match(tmp_path, [DISC], distance=distance)
    finish(table, mid, 'RETURNING SHIELD DISC', lambda p: ['STR'] if 'shield_disc_ability' in p['context']['reaction_source_id'] else None)
    svc = reload(svc, mid)
    rolls = [e for e in svc._load_session(mid).engine.events if e.event_type == 'ATTACK_ROLLED' and DISC in e.source_definition_id]
    assert len(rolls) == 1
    assert (rolls[0].payload['mode'] == 'DISADVANTAGE') == disadvantage


def finish_directed(table, mid, name, choose):
    answers = []
    for _ in range(20):
        state = table.state(mid)
        engine = table.combat._load_session(mid).engine
        actor = engine.state.actors[ME]
        candidate = next(c for c in engine.legal_candidates()
                         if engine.action_catalog.get(c.source_definition_id) is not None
                         and engine.action_catalog[c.source_definition_id].display_name == name
                         and c.destination is not None and c.destination.x > actor.position.x
                         and c.destination.y == actor.position.y)
        before = engine.state.model_dump(mode='json')
        result = table.act(mid, candidate.candidate_id, state['menu']['decision_id'],
                           state['menu']['state_version'], state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            return
        assert result['status'] == 'REACTION_REQUIRED', result
        assert engine.state.model_dump(mode='json') == before
        prompt = result['reaction']
        options = choose(prompt)
        answers.append({**prompt['context'], 'selection': 'DECLINE' if options is None else 'USE',
                        'option_ids': options or []})
    raise AssertionError('directed ability did not commit')


def test_disc_preserves_extra_attack_remainder_after_cold_reload(tmp_path, monkeypatch):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 19})
    svc, table, mid = match(tmp_path, [DISC, 'tianxia.path.body_refining.feature.extra_attack'], cl=17)
    finish(table, mid, 'RETURNING SHIELD DISC', lambda p: ['STR'] if 'shield_disc_ability' in p['context']['reaction_source_id'] else None)
    svc = reload(svc, mid)
    table.combat = svc
    me = svc._load_session(mid).engine.state.actors[ME]
    assert me.turn_flags['special_attack_rest'] == 3
    names = [g['label'] for g in table.state(mid)['menu']['actions']]
    name = next(n for n in names if 'rest of the Attack action' in n and 'thrown' in n.lower())
    finish(table, mid, name, lambda p: None)
    svc = reload(svc, mid)
    assert svc._load_session(mid).engine.state.actors[ME].turn_flags['special_attack_rest'] == 2


@pytest.mark.parametrize('choice', ['Prone', 'Push'])
def test_sweep_success_halves_damage_without_rider(tmp_path, monkeypatch, choice):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:save', 'operation': 'replace', 'natural_result': 19})
    svc, table, mid = match(tmp_path, [DISC, SWEEP])
    state = table.state(mid)
    name = next(g['label'] for g in state['menu']['actions'] if 'CELESTIAL-DISC SWEEP' in g['label'] and 'Line' in g['label'])
    finish_directed(table, mid, name, lambda p: None)
    svc = reload(svc, mid)
    engine = svc._load_session(mid).engine
    foe = engine.state.actors[THEM]
    assert foe.position.y == 6
    assert not any(c.condition_id == 'condition:typed.prone' for c in foe.conditions.values())
    rolled = next(e for e in engine.events if e.event_type == 'DAMAGE_ROLLED' and SWEEP in e.source_definition_id)
    assert 1000 - foe.current_hp == int(rolled.payload['total']) // 2


def test_disc_outside_long_range_has_no_target(tmp_path):
    svc, table, mid = match(tmp_path, [DISC], distance=95)
    state = table.state(mid)
    assert not any(THEM in option['target_ids'] for group in state['menu']['actions']
                   if group['label'] == 'RETURNING SHIELD DISC' for option in group['options'])
    reload(svc, mid)


def test_sweep_can_choose_different_riders_for_two_enemies(tmp_path, monkeypatch):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:failed_save', 'operation': 'replace', 'natural_result': 1})
    svc, table, mid = match(tmp_path, [DISC, SWEEP], second_enemy=True)
    before = svc._load_session(mid).engine.state.actors[ALLY].model_dump(mode='json')
    name = next(g['label'] for g in table.state(mid)['menu']['actions'] if 'CELESTIAL-DISC SWEEP' in g['label'] and 'Line' in g['label'])
    def choose(prompt):
        source = prompt['context']['reaction_source_id']
        if 'shield_sweep_rider' in source:
            return ['Push'] if 'Second enemy' in str(prompt) else ['Prone']
        return ['north'] if 'directed_movement' in source else None
    finish_directed(table, mid, name, choose)
    svc = reload(svc, mid)
    engine = svc._load_session(mid).engine
    assert any(c.condition_id == 'condition:typed.prone' for c in engine.state.actors[THEM].conditions.values())
    second = engine.state.actors[THEM + ':second']
    assert second.position.y < 6
    assert not any(c.condition_id == 'condition:typed.prone' for c in second.conditions.values())
    assert engine.state.actors[ALLY].model_dump(mode='json') == before


def test_guarded_stance_returns_its_selected_weapon_and_suspends_permission_in_flight(tmp_path, monkeypatch):
    from combat import armour, carry
    from combat.ext.shield_wielding import guarded_weapon, wielding_a_shield
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 19})
    svc, table, mid = match(tmp_path, [DISC, 'TAL_SHIELD_GUARDED_STANCE'], shield=False)
    engine = svc._load_session(mid).engine
    key = next(row['key'] for row in carry.carrying_of(engine, ME)['items'] if row.get('weapon_action'))
    name = next(g['label'] for g in table.state(mid)['menu']['actions'] if 'Guarded Stance: choose' in g['label'])
    finish(table, mid, name, lambda p: [key] if 'guarded_stance' in p['context']['reaction_source_id'] else None)
    svc = reload(svc, mid)
    table.combat = svc
    engine = svc._load_session(mid).engine
    assert armour.shield_item_key(engine, engine.state.actors[ME]) is None
    assert guarded_weapon(engine, engine.state.actors[ME]) == key
    in_flight = []
    def observe(engine, event_type, kwargs):
        if event_type == 'ATTACK_ROLLED' and DISC in kwargs.get('source_definition_id', ''):
            actor = engine.state.actors[ME]
            in_flight.append((carry.holds(engine, actor, key), wielding_a_shield(engine, actor)))
    install(monkeypatch, 'event', observe)
    finish(table, mid, 'RETURNING SHIELD DISC', lambda p: ['STR'] if 'shield_disc_ability' in p['context']['reaction_source_id'] else None)
    svc = reload(svc, mid)
    engine = svc._load_session(mid).engine
    actor = engine.state.actors[ME]
    assert in_flight and all(row == (False, False) for row in in_flight)
    assert guarded_weapon(engine, actor) == key and carry.holds(engine, actor, key)
    assert not carry.lost_to_another_hand(actor, key)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and DISC in e.source_definition_id for e in engine.events)


@pytest.mark.parametrize(('target_y', 'blocked'), [(6, [(8, 5), (8, 7)]), (7, [(8, 6)])])
def test_sweep_blocked_lateral_push_never_falls_back_to_away_route(tmp_path, monkeypatch, target_y, blocked):
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:failed_save', 'operation': 'replace', 'natural_result': 1})
    svc, table, mid = match(tmp_path, [DISC, SWEEP], blocked_cells=blocked, target_y=target_y)
    name = next(g['label'] for g in table.state(mid)['menu']['actions'] if 'CELESTIAL-DISC SWEEP' in g['label'] and 'Line' in g['label'])
    finish_directed(table, mid, name, lambda p: ['Push'] if 'shield_sweep_rider' in p['context']['reaction_source_id'] else ['east'])
    svc = reload(svc, mid)
    foe = svc._load_session(mid).engine.state.actors[THEM]
    assert (foe.position.x, foe.position.y) == (8, target_y)


def test_orbiting_shield_retains_bonus_and_permission_while_disc_flies(tmp_path, monkeypatch):
    from combat import armour
    from combat.ext.shield_wielding import wielding_a_shield
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 19})
    svc, table, mid = match(tmp_path, [DISC, 'TAL_SHIELD_ORBITING_SHIELD_DISC'])
    state = table.state(mid)
    orbit = next(g['label'] for g in state['menu']['actions'] if 'ORBITING SHIELD DISC' in g['label'])
    finish(table, mid, orbit, lambda p: None)
    svc = reload(svc, mid)
    table.combat = svc
    engine = svc._load_session(mid).engine
    baseline_ac = engine.state.actors[ME].armor_class + engine._ac_modifier(engine.state.actors[ME])
    in_flight = []
    def observe(engine, event_type, kwargs):
        if event_type == 'ATTACK_ROLLED' and DISC in engine.events[-1].source_definition_id:
            actor = engine.state.actors[ME]
            in_flight.append((actor.armor_class + engine._ac_modifier(actor), wielding_a_shield(engine, actor), armour.compiled_shield_bonus(engine, actor)))
    install(monkeypatch, 'event', observe)
    finish(table, mid, 'RETURNING SHIELD DISC', lambda p: ['STR'] if 'shield_disc_ability' in p['context']['reaction_source_id'] else None)
    svc = reload(svc, mid)
    assert in_flight and all(row == (baseline_ac, True, 2) for row in in_flight)
    actor = svc._load_session(mid).engine.state.actors[ME]
    assert actor.armor_class + svc._load_session(mid).engine._ac_modifier(actor) == baseline_ac
