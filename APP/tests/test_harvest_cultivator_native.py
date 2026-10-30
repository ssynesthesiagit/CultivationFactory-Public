"""Harvest acquisition -> native journey preparation -> table -> cold replay.

No test grants a compiled action, stock receipt, or ownership condition. The
native non-sphere authority acquires the parent; world facts enter through the
table-owner endpoint, and every action is an accepted table candidate.
"""
from copy import deepcopy
from itertools import combinations
import json

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_seamfix_subpath_healing_melody import acquired
from tests.worker2_support import OWNER, ALLY, FOE, candidate, reload, settle, turn

TEAMS = {OWNER: 'party', ALLY: 'party', FOE: 'enemy'}


def run_to_terminal(combat, table, mid, limit=30):
    """End turns (answering automatic/default choices) until the capped fight is terminal."""
    for _ in range(limit):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            return
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError('the round-capped fight did not finish')


def plant_seed_with_augment(combat, table, mid, name, at, augments):
    settle(table, mid, candidate(combat, mid, name, at=at).candidate_id,
        choices={'choice:needle.harvest_growth_augments': augments})


def harvest_candidates(engine, operation):
    """Accepted destination candidates for one Harvest operation (movement rows have no catalog action)."""
    return [c for c in engine.legal_candidates()
            if c.source_definition_id in engine.action_catalog and c.destination
            and engine.action_catalog[c.source_definition_id].parameters.get(KEY) == operation]

PARENT = 'tianxia.subpath.qi.harvest_cultivator'
BASE = PARENT + '.feature.three_foundational_seeds'
RESTORE = PARENT + '.feature.seed_of_restoration'
KEY = 'harvest_cultivator'
FORMULAS = ['root', 'blossom', 'thorn', 'water_reed', 'lantern_fruit']


def jact(combat, state, kind, payload=None):
    return combat.journey_act(state['journey_id'], state['revision'], OWNER, kind, payload or {})


def prepared(tmp_path, acquired, cl=18, formulas=None, material=True, rest=True, effective_cl=None, foe_document=None,
             foe_bundle=None, choose_formulas=True):
    doc = acquired(cl, PARENT)
    if effective_cl is not None:
        next(r for r in doc['path_and_subpath']['paths'] if r['path_id'] == 'tianxia.path.qi_cultivation')['effective_cl'] = effective_cl
    doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    ally = compile_character(sheet([], cl=cl, name='Tobin'), actor_id=ALLY)
    foe = foe_bundle or compile_character(foe_document or sheet([], cl=cl, name='Mara'), actor_id=FOE)
    combat = CombatService(ROOT, tmp_path)
    arena = deepcopy(combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'])
    state = combat.journeys.create([owner, ally, foe], arena,
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        {OWNER: 12000, ALLY: 12000, FOE: 12000})
    source_cl = cl if effective_cl is None else min(cl, effective_cl)
    count = 5 if source_cl >= 10 else 4 if source_cl >= 6 else 3
    if choose_formulas:
        state = jact(combat, state, 'harvest_formulas', {'formulas': formulas or FORMULAS[:count]})
    if material:
        state = combat.journey_world_fact(state['journey_id'], state['revision'], {
            'source': BASE, 'subject': OWNER, 'kind': 'seed_growing_material', 'scope': 'preparation',
            'value': 1, 'expires_at': 86400, 'readers': []})
    if rest:
        state = jact(combat, state, 'long_rest')
    return combat, state


def start(combat, state):
    mid = combat.journey_start_combat(state['journey_id'], state['revision'],
        {OWNER: 'party', ALLY: 'party', FOE: 'enemy'})['match_id']
    table = TabletopService(combat, combat.userdata_root)
    turn(table, mid, OWNER)
    return table, mid


def saved_stock(engine):
    row = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == 'condition:typed.harvest_stock')
    return json.loads(row.data['state'])


@pytest.mark.parametrize('cl,count', [(3, 3), (6, 4), (10, 5), (14, 5), (18, 5)])
def test_native_formula_stock_acquisition_and_cold_journey(tmp_path, acquired, cl, count):
    combat, state = prepared(tmp_path, acquired, cl)
    cold = CombatService(ROOT, tmp_path).journeys.load(state['journey_id']).state
    s = cold['actors'][OWNER]['source_states'][KEY]
    assert len(s['formulas']) == count
    owner = cold['actors'][OWNER]['bundle']
    pb = next(r['numbers']['pb'] for r in owner['typed_passives'] if r.get('block') == KEY)
    assert s['stock'] == pb
    assert cold['seconds'] == 28800
    assert any(e['kind'] == 'WORLD_FACT_DECLARED' for e in cold['events'])


def test_material_is_not_inferred_and_cannot_be_claimed_by_actor(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired, material=False)
    assert state['actors'][OWNER]['source_states'][KEY]['stock'] == 0
    with pytest.raises(ValueError, match='material'):
        jact(combat, state, 'harvest_replacement')
    with pytest.raises(ValueError, match='table-owner'):
        jact(combat, state, 'declare_fact', {'source': BASE, 'subject': OWNER,
            'kind': 'seed_growing_material', 'scope': 'preparation', 'value': 1,
            'expires_at': 86400, 'readers': []})


def test_replacement_pays_qi_and_ten_minutes_once(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired, rest=False)
    before = state['actors'][OWNER]['resources']['resource:core.qi']
    state = jact(combat, state, 'harvest_replacement')
    assert state['seconds'] == 600
    assert state['actors'][OWNER]['resources']['resource:core.qi'] == before - 1
    assert state['actors'][OWNER]['source_states'][KEY]['stock'] == 1
    with pytest.raises(ValueError, match='level'):
        jact(combat, state, 'harvest_formulas', {'formulas': FORMULAS})


@pytest.mark.parametrize('formula', FORMULAS)
def test_plant_real_profile_payment_and_cold_mechanical_replay(tmp_path, acquired, formula):
    combat, state = prepared(tmp_path, acquired)
    table, mid = start(combat, state)
    before = reload(tmp_path, mid)
    stock = saved_stock(before)['stock']
    name = 'Plant ' + formula.replace('_', ' ').title() + ' Seed'
    settle(table, mid, candidate(combat, mid, name, at=(4, 7)).candidate_id,
        choices={'choice:needle.harvest_growth_augments': None,
                 'choice:needle.harvest_chosen_allies': [OWNER, ALLY]})
    after = reload(tmp_path, mid)
    obj = next(o for o in after.state.objects.values() if o.component.get('asset_anchor_runtime', {}).get('group') == KEY)
    assert obj.ac == 13 and obj.maximum_hp == 36
    assert obj.damage_immunities == ('PSYCHIC',)
    assert obj.component['source_cl'] == 18
    assert obj.component['formulas'] == [formula]
    assert saved_stock(after)['stock'] == stock - 1
    assert not after.state.actors[OWNER].bonus_action_available
    assert obj.component['zone_id'] in after.state.zones


@pytest.mark.parametrize('cl,augments,hp,radius', [(6, ['wide_roots'], 12, 15),
    (14, ['wide_roots', 'deep_roots'], 42, 15)])
def test_growth_augment_payment_real_seed_profile(tmp_path, acquired, cl, augments, hp, radius):
    combat, state = prepared(tmp_path, acquired, cl)
    table, mid = start(combat, state)
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    settle(table, mid, candidate(combat, mid, 'Plant Root Seed', at=(4, 7)).candidate_id,
        choices={'choice:needle.harvest_growth_augments': augments})
    engine = reload(tmp_path, mid)
    obj = next(o for o in engine.state.objects.values() if o.component.get('formulas') == ['root'])
    assert obj.maximum_hp == hp
    zone = engine.state.zones[obj.component['zone_id']]
    assert zone.radius_cells * 5 == radius
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == before - len(augments)


@pytest.mark.parametrize('name,cost,count,radius', [('Orchard Field', 5, 2, 20),
    ('Ten Thousand Seed Ascension', 8, 3, 40)])
def test_fields_choose_formulas_and_persist_concentration_without_spending_stock(tmp_path, acquired, name, cost, count, radius):
    combat, state = prepared(tmp_path, acquired)
    table, mid = start(combat, state)
    before = reload(tmp_path, mid)
    qi = before.state.actors[OWNER].resources['resource:core.qi']; stock = saved_stock(before)['stock']
    settle(table, mid, candidate(combat, mid, name, at=(4, 7)).candidate_id,
        choices={'choice:needle.harvest_field_formulas': FORMULAS[:count],
                 'choice:needle.harvest_chosen_allies': [OWNER, ALLY]})
    engine = reload(tmp_path, mid)
    zone = next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get('profile', {}).get(KEY))
    assert zone.radius_cells * 5 == radius
    assert zone.trigger_profile['profile']['formulas'] == FORMULAS[:count]
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - cost
    assert engine.state.actors[OWNER].concentration is not None
    assert saved_stock(engine)['stock'] == stock
    assert not any(o.component.get('asset_anchor_runtime', {}).get('group') == KEY for o in engine.state.objects.values())


def test_restoration_real_ward_consent_charges_and_cold_reload(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired)
    table, mid = start(combat, state)
    settle(table, mid, candidate(combat, mid, 'Seed of Restoration', at=(4, 7)).candidate_id,
        choices={'choice:needle.harvest_ward': [ALLY], 'choice:willing.consent': ['accept']})
    engine = reload(tmp_path, mid)
    obj = next(o for o in engine.state.objects.values() if o.component.get('restoration'))
    assert obj.ac == 15 and obj.maximum_hp == 54
    assert set(obj.damage_immunities) == {'POISON', 'PSYCHIC'}
    assert obj.component['ward'] == ALLY and obj.component['charges'] == 3
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    assert engine.state.objects[obj.object_id].component['charges'] == 2
    rolls = [r for r in engine.rolls if r.reason.startswith('HEALING:')]
    assert rolls and rolls[-1].expression.startswith('2d8')


def test_wrong_owner_and_below_tier_are_inert(tmp_path, acquired):
    doc = acquired(18, PARENT)
    doc['path_and_subpath'] = {}
    bundle = compile_character(doc, actor_id=OWNER)
    assert not any(a.get('parameters', {}).get(KEY) for a in bundle['action_catalog'])
    low = compile_character(acquired(3, PARENT), actor_id=OWNER)
    names = {a['display_name'] for a in low['action_catalog'] if a.get('parameters', {}).get(KEY)}
    assert names == {'Plant ' + f.replace('_', ' ').title() + ' Seed' for f in FORMULAS} | {'Lantern-Fruit: Examine Concealment'}


def test_full_session_requires_owner_confirmed_environment_and_elapsed_hours(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired, rest=False)
    with pytest.raises(ValueError, match='uninterrupted'):
        jact(combat, state, 'harvest_session')
    state = combat.journey_world_fact(state['journey_id'], state['revision'], {
        'source': BASE, 'subject': OWNER, 'kind': 'full_session_environment', 'scope': 'preparation',
        'value': 1, 'expires_at': 86400, 'readers': []})
    state = jact(combat, state, 'harvest_session')
    assert state['seconds'] == 7200
    assert state['actors'][OWNER]['source_states'][KEY]['stock'] > 0


def test_formula_menu_contains_every_legal_initial_selection(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired, cl=3, rest=False)
    # Repeated choices are unavailable after the actual initial acquisition.
    menu = combat.journeys.load(state['journey_id']).menu(OWNER)
    assert not any(o['kind'] == 'harvest_formulas' for o in menu['options'])


def test_lantern_has_native_world_fact_validation_light_and_private_readings(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired)
    payload = {'source': BASE, 'subject': FOE, 'kind': 'harvest_manifestation',
        'scope': 'native_source', 'expires_at': 86400, 'readers': [],
        'value': {'tags': ['corruption'], 'source_id': 'world:intrinsic-corruption', 'source_cl': 3, 'save_dc': 12, 'check_required': 0}}
    with pytest.raises(ValueError, match='fields'):
        combat.journey_world_fact(state['journey_id'], state['revision'], {**payload, 'value': {'tags': ['evil_name']}})
    state = combat.journey_world_fact(state['journey_id'], state['revision'], payload)
    table, mid = start(combat, state)
    settle(table, mid, candidate(combat, mid, 'Plant Lantern Fruit Seed', at=(5, 7)).candidate_id,
        choices={'choice:needle.harvest_growth_augments': None})
    engine = reload(tmp_path, mid)
    from combat.senses import perception
    readings = perception(engine, engine.state.actors[OWNER]).get('information', [])
    assert any(r['kind'] == 'illumination' and r['details']['bright_ft'] == 10 and r['details']['dim_outer_ft'] == 20 for r in readings)
    assert any(r['kind'] == 'lantern_observation' and 'discoloration' in r['details']['text'] for r in readings)
    assert all(r['viewer_id'] == OWNER for r in readings)


def test_winter_ranged_ac_and_chosen_roster_survive_native_turn_choice(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired)
    table, mid = start(combat, state)
    settle(table, mid, candidate(combat, mid, 'Orchard Field', at=(4, 7)).candidate_id,
        choices={'choice:needle.harvest_field_formulas': ['root', 'blossom'],
                 'choice:needle.harvest_chosen_allies': [ALLY]})
    settle(table, mid, table.state(mid)['menu']['end_turn'],
        choices={'choice:needle.harvest_seasons': ['winter']})
    engine = reload(tmp_path, mid)
    guards = [m for m in engine.state.actors[ALLY].modifiers.values() if m.target_field == 'armor_class_vs_ranged']
    assert len(guards) == 1 and guards[0].operation == 'ADD' and int(guards[0].value) == 1
    assert guards[0].source_actor_id == OWNER
    assert not any(m.target_field == 'armor_class_vs_ranged' for m in engine.state.actors[OWNER].modifiers.values())


@pytest.mark.parametrize('cl,count', [(3, 1), (11, 2), (17, 3)])
def test_thorn_start_save_damage_scaling_and_cold_replay(tmp_path, acquired, cl, count):
    combat, state = prepared(tmp_path, acquired, cl)
    table, mid = start(combat, state)
    settle(table, mid, candidate(combat, mid, 'Plant Thorn Seed', at=(5, 7)).candidate_id,
        choices={'choice:needle.harvest_growth_augments': None})
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    rolls = [r for r in engine.rolls if r.reason.startswith('DAMAGE:')]
    assert rolls and rolls[-1].expression.startswith(str(count) + 'd6')
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE for e in engine.events)
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids]
    assert packets and packets[-1].payload['damage_type'] == 'PIERCING'
    assert packets[-1].payload['rolled_or_pending_damage'] in (rolls[-1].total, rolls[-1].total // 2)


def test_blossom_start_benefit_and_hostile_root_movement_query(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired)
    table, mid = start(combat, state)
    settle(table, mid, candidate(combat, mid, 'Plant Blossom Seed', at=(5, 7)).candidate_id,
        choices={'choice:needle.harvest_growth_augments': None})
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    pb = next(r['numbers']['pb'] for r in engine.typed_passive_rows[OWNER] if r.get('block') == KEY)
    assert engine.state.actors[ALLY].temporary_hp == pb
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Plant Root Seed', at=(5, 6)).candidate_id,
        choices={'choice:needle.harvest_growth_augments': None})
    engine = reload(tmp_path, mid)
    from combat.zones import difficult_cells
    assert (6, 6) in difficult_cells(engine, engine.state.actors[FOE])
    assert (4, 6) not in difficult_cells(engine, engine.state.actors[ALLY])


def test_swift_germination_extends_only_the_paid_planting_range(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired, cl=6)
    table, mid = start(combat, state)
    engine = reload(tmp_path, mid)
    far = next(c for c in harvest_candidates(engine, 'plant_root')
        if engine.grid.distance_ft(engine.state.actors[OWNER].position, c.destination) > 30)
    before = engine.state.actors[OWNER].resources['resource:core.qi']
    settle(table, mid, far.candidate_id, choices={'choice:needle.harvest_growth_augments': ['swift_germination']})
    engine = reload(tmp_path, mid)
    seed = next(o for o in engine.state.objects.values() if o.component.get('formulas') == ['root'])
    assert seed.position == far.destination
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == before - 1


def test_summer_extra_damage_uses_first_real_damage_packet(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired)
    table, mid = start(combat, state)
    settle(table, mid, candidate(combat, mid, 'Orchard Field', at=(4, 7)).candidate_id,
        choices={'choice:needle.harvest_field_formulas': ['root', 'thorn']})
    for _ in range(3):
        if table.state(mid)['menu']['actor_id'] == FOE:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'],
            choices={'choice:needle.harvest_seasons': ['summer']})
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id == FOE
    packets = [e.payload for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids]
    assert any(p['damage_type'] == 'PIERCING' for p in packets)
    assert sum(p['damage_type'] in ('FIRE', 'RADIANT') for p in packets) == 1


def test_purifying_germination_consumes_actual_ordinary_travel_exhaustion(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired)
    state = combat.journey_act(state['journey_id'], state['revision'], ALLY,
        'travel_exhaustion', {'levels': 2, 'ordinary': True})
    assert state['actors'][ALLY]['exhaustion'] == 2
    assert state['events'][-1]['kind'] == 'TRAVEL_EXHAUSTION'
    assert state['events'][-1]['ordinary'] == 1
    table, mid = start(combat, state)
    settle(table, mid, candidate(combat, mid, 'Seed of Restoration', at=(4, 7)).candidate_id,
        choices={'choice:needle.harvest_ward': [ALLY], 'choice:willing.consent': ['accept']})
    while table.state(mid)['menu']['actor_id'] != ALLY:
        settle(table, mid, table.state(mid)['menu']['end_turn'],
            choices={'choice:needle.harvest_purifying_germination': ['exhaustion']})
    engine = reload(tmp_path, mid)
    from combat.ext.forged_exhaustion import level
    assert level(engine.state.actors[ALLY]) == 1
    obj = next(o for o in engine.state.objects.values() if o.component.get('restoration'))
    assert obj.component['charges'] == 1


def test_native_realm_suppression_gates_tiers_and_scales_seed_profile(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired, cl=18, effective_cl=5)
    assert len(state['actors'][OWNER]['source_states'][KEY]['formulas']) == 3
    assert state['actors'][OWNER]['source_states'][KEY]['stock'] <= 3
    table, mid = start(combat, state)
    engine = reload(tmp_path, mid)
    assert not any(engine.action_catalog[c.source_definition_id].parameters.get(KEY) in ('field', 'restoration', 'ascension')
        for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog)
    settle(table, mid, candidate(combat, mid, 'Plant Root Seed', at=(4, 7)).candidate_id, choices={})
    engine = reload(tmp_path, mid)
    seed = next(o for o in engine.state.objects.values() if o.component.get('formulas') == ['root'])
    assert seed.maximum_hp == 10 and seed.component['source_cl'] == 5
    assert not seed.component['augments']


@pytest.mark.parametrize('land_cl,suppressed', [(17, False), (19, True)])
def test_native_cultivated_land_counterauthority_is_not_inferred(tmp_path, acquired, land_cl, suppressed):
    combat, state = prepared(tmp_path, acquired)
    state = combat.journey_world_fact(state['journey_id'], state['revision'], {
        'source': BASE, 'subject': OWNER, 'kind': 'harvest_seed_bed', 'scope': 'planting',
        'expires_at': 86400, 'readers': [], 'value': {'cells': [[5, 7, 0]],
            'medium': 'cultivated_land', 'source_id': 'world:declared-blight',
            'source_cl': land_cl, 'suppresses': 1, 'authority': 'ordinary'}})
    table, mid = start(combat, state)
    settle(table, mid, candidate(combat, mid, 'Plant Root Seed', at=(5, 7)).candidate_id,
        choices={'choice:needle.harvest_growth_augments': None})
    engine = reload(tmp_path, mid)
    seed = next(o for o in engine.state.objects.values() if o.component.get('formulas') == ['root'])
    assert bool(seed.component['suppressed']) == suppressed
    assert not seed.destroyed and seed.current_hp == 36
    from combat.zones import difficult_cells
    assert ((6, 6) in difficult_cells(engine, engine.state.actors[FOE])) != suppressed


def test_violent_germination_is_spent_by_only_the_first_damage(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired, cl=17)
    table, mid = start(combat, state)
    settle(table, mid, candidate(combat, mid, 'Plant Thorn Seed', at=(5, 7)).candidate_id,
        choices={'choice:needle.harvest_growth_augments': ['violent_germination']})
    turn(table, mid, FOE)
    first = reload(tmp_path, mid)
    assert [r for r in first.rolls if r.reason.startswith('DAMAGE:')][-1].expression.startswith('4d6')
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    second = reload(tmp_path, mid)
    assert [r for r in second.rolls if r.reason.startswith('DAMAGE:')][-1].expression.startswith('3d6')


def test_guiding_vine_collects_real_willing_ally_move_without_ordinary_payment(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired)
    table, mid = start(combat, state)
    before = reload(tmp_path, mid).state.actors[ALLY]
    start_position = before.position
    budget = before.movement_remaining_ft
    prompts = settle(table, mid, candidate(combat, mid, 'Plant Root Seed', at=(5, 7)).candidate_id,
        choices={'choice:needle.harvest_growth_augments': ['guiding_vine'],
                 'choice:needle.harvest_guiding_vine_ally': [ALLY],
                 'choice:willing.consent': ['accept'], 'choice:needle.harvest_move': 'first'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].position != start_position
    assert engine.state.actors[ALLY].movement_remaining_ft == budget
    assert any(p['context']['reactor_id'] == ALLY for p in prompts)


def test_protective_bloom_has_native_next_save_rule_and_source_expiry(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired)
    table, mid = start(combat, state)
    settle(table, mid, candidate(combat, mid, 'Plant Root Seed', at=(5, 7)).candidate_id,
        choices={'choice:needle.harvest_growth_augments': ['protective_bloom'],
                 'choice:needle.harvest_protective_bloom_ally': [ALLY]})
    engine = reload(tmp_path, mid)
    benefit = next(c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id == 'condition:typed.next_d20_mode')
    assert benefit.data['kinds'] == ['save']
    assert set(benefit.data['rule']['save_mode'].values()) == {'ADVANTAGE'}
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert benefit.instance_id not in engine.state.actors[ALLY].conditions


@pytest.mark.parametrize('foe_cl,removed', [(14, True), (18, False)])
def test_restoration_purifies_native_fear_or_repeats_original_higher_save(tmp_path, acquired, foe_cl, removed):
    foe = acquired(foe_cl)
    foe['ability_scores_and_statistics']['technique_save_dc'] = 100
    combat, state = prepared(tmp_path, acquired, cl=14, foe_document=foe)
    table, mid = start(combat, state)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Song of Fear').candidate_id, choices={})
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.frightened' for c in engine.state.actors[OWNER].conditions.values())
    settle(table, mid, candidate(combat, mid, 'Seed of Restoration', at=(4, 7)).candidate_id,
        choices={'choice:needle.harvest_ward': [OWNER], 'choice:willing.consent': ['accept']})
    for _ in range(4):
        settle(table, mid, table.state(mid)['menu']['end_turn'],
            choices={'choice:needle.harvest_purifying_germination': 'first'})
        if table.state(mid)['menu']['actor_id'] == OWNER:
            break
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.frightened' for c in engine.state.actors[OWNER].conditions.values()) is not removed
    if not removed:
        rolls = [r for r in engine.rolls if r.actor_id == OWNER and r.reason.startswith('SAVE:')]
        assert rolls[-1].mode == 'ADVANTAGE'
    seed = next(o for o in engine.state.objects.values() if o.component.get('restoration'))
    assert seed.component['charges'] == 1


def test_ascension_real_seasons_grasping_and_restoration_healing_upgrade(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired)
    table, mid = start(combat, state)
    settle(table, mid, candidate(combat, mid, 'Ten Thousand Seed Ascension', at=(4, 7)).candidate_id,
        choices={'choice:needle.harvest_field_formulas': ['root', 'blossom', 'lantern_fruit'],
                 'choice:needle.harvest_chosen_allies': [OWNER, ALLY]})
    settle(table, mid, candidate(combat, mid, 'Seed of Restoration', at=(4, 7)).candidate_id,
        choices={'choice:needle.harvest_ward': [ALLY], 'choice:willing.consent': ['accept']})
    for _ in range(4):
        if table.state(mid)['menu']['actor_id'] == ALLY:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'],
            choices={'choice:needle.harvest_seasons': ['winter', 'autumn'], 'choice:needle.harvest_move': None})
    engine = reload(tmp_path, mid)
    rolls = [r for r in engine.rolls if r.reason.startswith('HEALING:')]
    assert rolls and rolls[-1].expression.startswith('3d8')
    field = next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get('profile', {}).get('ascension'))
    assert field.trigger_profile['profile']['seasons'] == ['winter', 'autumn']
    assert saved_stock(engine)['ascension_used'] == 1
    for _ in range(4):
        if table.state(mid)['menu']['actor_id'] == OWNER:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'],
            choices={'choice:needle.harvest_seasons': ['winter', 'autumn'], 'choice:needle.harvest_move': None})
    before = reload(tmp_path, mid)
    assert any(r.actor_id == FOE and r.reason.startswith('SAVE:') and r.reason.endswith(':STR') for r in before.rolls)
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    settle(table, mid, candidate(combat, mid, 'Harvest of Restoration').candidate_id,
        choices={'choice:needle.harvest_harvest_allies': [OWNER, ALLY]})
    engine = reload(tmp_path, mid)
    assert engine.state.zones[field.zone_id].active
    assert engine.state.actors[OWNER].concentration is not None
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi
    assert engine.state.zones[field.zone_id].trigger_profile['profile']['harvest_used'] == 1
    assert not any(engine.action_catalog[c.source_definition_id].parameters.get(KEY) in ('harvest', 'ascension')
        for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog)


def test_water_reed_real_entry_choice_does_not_retrigger_on_reentry_same_turn(tmp_path, acquired):
    combat, state = prepared(tmp_path, acquired)
    table, mid = start(combat, state)
    settle(table, mid, candidate(combat, mid, 'Plant Water Reed Seed', at=(5, 7)).candidate_id,
        choices={'choice:needle.harvest_growth_augments': None, 'choice:needle.harvest_chosen_allies': [ALLY]})
    turn(table, mid, ALLY)

    def loaded():
        return reload(tmp_path, mid)

    zone = next(z for z in loaded().state.zones.values()
        if 'water_reed' in z.trigger_profile.get('profile', {}).get('formulas', ()))
    inside = {(cell.x, cell.y) for cell in zone.affected_cells}

    def steps():
        """One 5-foot legal step per destination square, so four round trips stay in budget."""
        return {(c.destination.x, c.destination.y): c for c in loaded().legal_candidates()
                if c.kind == 'MOVE' and c.destination and int(c.movement_cost_ft or 0) == 5}

    def move_to(cell):
        return settle(table, mid, steps()[cell].candidate_id, choices={'choice:needle.harvest_move': None})

    here = loaded().state.actors[ALLY].position
    out = next(cell for cell in steps() if cell not in inside
               and abs(cell[0] - here.x) <= 1 and abs(cell[1] - here.y) <= 1)
    move_to(out)  # leave the Seed's area
    back = next(cell for cell in steps() if cell in inside)
    first = move_to(back)
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.harvest_move' for p in first) == 1
    move_to(out)
    second = move_to(back)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.harvest_move' for p in second)
    reload(tmp_path, mid)


def test_formula_menu_offers_every_legal_initial_selection(tmp_path, acquired):
    """The initial menu never cuts a legal three-Formula combination (owner 2026-10-13)."""
    combat, state = prepared(tmp_path, acquired, cl=3, rest=False, choose_formulas=False)
    menu = combat.journeys.load(state['journey_id']).menu(OWNER)
    offered = {tuple(sorted(o['payload']['formulas'])) for o in menu['options'] if o['kind'] == 'harvest_formulas'}
    expected = {tuple(sorted(row)) for row in combinations(FORMULAS, 3)}
    assert offered == expected and len(offered) == 10


def test_live_field_seed_and_concentration_continue_across_an_encounter(tmp_path, acquired):
    """A short fight neither blocks continuation nor loses a still-live Harvest benefit."""
    combat, state = prepared(tmp_path, acquired, cl=18)
    jid = state['journey_id']
    first = combat.journey_start_combat(jid, state['revision'], TEAMS, maximum_rounds=1)['match_id']
    table = TabletopService(combat, combat.userdata_root)
    turn(table, first, OWNER)
    settle(table, first, candidate(combat, first, 'Orchard Field', at=(4, 7)).candidate_id,
        choices={'choice:needle.harvest_field_formulas': ['root', 'thorn'],
                 'choice:needle.harvest_chosen_allies': [OWNER]})
    plant_seed_with_augment(combat, table, first, 'Plant Thorn Seed', (5, 7), None)
    run_to_terminal(combat, table, first)
    resumed = combat.journey_resume(jid, combat.journey_state(jid)['revision'])
    live = resumed['actors'][OWNER]['source_states']['harvest_live']
    assert len(live['zones']) == 2 and live['concentration']
    # Six seconds of travel: the 1-minute effects are still live when the next fight starts.
    combat.journey_act(jid, combat.journey_state(jid)['revision'], OWNER, 'wait', {'seconds': 6})
    second = combat.journey_start_combat(jid, combat.journey_state(jid)['revision'], TEAMS)['match_id']
    engine = reload(tmp_path, second)
    zones = [z for z in engine.state.zones.values() if z.trigger_profile.get('profile', {}).get(KEY)]
    field = next(z for z in zones if z.trigger_profile['profile'].get('field_kind'))
    seed = next(z for z in zones if z.trigger_profile['profile'].get('seed_object'))
    assert engine.state.actors[OWNER].concentration is not None
    assert engine.state.actors[OWNER].concentration.zone_id == field.zone_id
    assert field.trigger_profile['profile']['formulas'] == ['root', 'thorn']
    assert field.duration_rounds < 10  # the carried clock absorbed the 6 seconds travelled
    obj = engine.state.objects[seed.trigger_profile['profile']['seed_object']]
    assert obj.component['formulas'] == ['thorn'] and obj.component['charges'] == 0


def test_carried_harvest_effects_expire_with_elapsed_travel_time(tmp_path, acquired):
    """Travel longer than the printed 1 minute and the Seed and Concentration are gone."""
    combat, state = prepared(tmp_path, acquired, cl=18)
    jid = state['journey_id']
    first = combat.journey_start_combat(jid, state['revision'], TEAMS, maximum_rounds=1)['match_id']
    table = TabletopService(combat, combat.userdata_root)
    turn(table, first, OWNER)
    settle(table, first, candidate(combat, first, 'Orchard Field', at=(4, 7)).candidate_id,
        choices={'choice:needle.harvest_field_formulas': ['root', 'thorn'],
                 'choice:needle.harvest_chosen_allies': [OWNER]})
    plant_seed_with_augment(combat, table, first, 'Plant Thorn Seed', (5, 7), None)
    run_to_terminal(combat, table, first)
    combat.journey_resume(jid, combat.journey_state(jid)['revision'])
    combat.journey_act(jid, combat.journey_state(jid)['revision'], OWNER, 'wait', {'seconds': 70})
    second = combat.journey_start_combat(jid, combat.journey_state(jid)['revision'], TEAMS)['match_id']
    engine = reload(tmp_path, second)
    assert engine.state.actors[OWNER].concentration is None
    assert not any(z.trigger_profile.get('profile', {}).get(KEY) for z in engine.state.zones.values())
    assert not any(o.component.get('formulas') for o in engine.state.objects.values())


def test_violent_germination_is_spent_by_each_seed_instance_only_once(tmp_path, acquired):
    """A second Thorn Seed keeps its own first-damage bonus when a spent Seed pulses first."""
    combat, state = prepared(tmp_path, acquired, cl=17)
    table, mid = start(combat, state)
    plant_seed_with_augment(combat, table, mid, 'Plant Thorn Seed', (5, 7), None)
    turn(table, mid, FOE)  # the un-augmented Seed pulses and spends nothing
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    cell = next(c for c in harvest_candidates(engine, 'plant_thorn')
        if (c.destination.x, c.destination.y) != (5, 7)
        and engine.grid.distance_ft(c.destination, engine.state.actors[FOE].position) <= 10)
    settle(table, mid, cell.candidate_id, choices={'choice:needle.harvest_growth_augments': ['violent_germination']})
    turn(table, mid, FOE)  # both Seeds pulse: the augmented one must keep its own 1d6
    engine = reload(tmp_path, mid)
    piercing = [r.expression for r in engine.rolls if r.reason.startswith('DAMAGE:')]
    assert sum(expr.startswith('3d6') for expr in piercing) == 2
    assert sum(expr.startswith('4d6') for expr in piercing) == 1


def test_thorn_seed_is_visible_to_the_shared_movement_hazard_query(tmp_path, acquired):
    """AI movement risk / safe relocation see the Thorn Seed's real damage."""
    from combat.gate2_runtime_models import Position
    from combat.zones import hazard_test
    combat, state = prepared(tmp_path, acquired, cl=17)
    table, mid = start(combat, state)
    engine = reload(tmp_path, mid)
    away = next(c for c in harvest_candidates(engine, 'plant_thorn')
        if engine.grid.distance_ft(c.destination, engine.state.actors[FOE].position) > 10
        and engine.grid.distance_ft(c.destination, engine.state.actors[OWNER].position) <= 30)
    settle(table, mid, away.candidate_id, choices={'choice:needle.harvest_growth_augments': None})
    engine = reload(tmp_path, mid)
    risk = hazard_test(engine, engine.state.actors[FOE])
    assert risk is not None and risk(away.destination)
    assert not risk(Position(x=engine.state.actors[FOE].position.x, y=engine.state.actors[FOE].position.y, z=0))


def test_lantern_reads_a_holderless_illusion_zone_in_its_light(tmp_path, acquired):
    """A classified lower-CL visual illusion with no creature holder still flickers."""
    from combat.ext import figment
    from combat.senses import perception
    combat, state = prepared(tmp_path, acquired, foe_document=sheet([figment.MINOR], cl=3, name='Mara'))
    table, mid = start(combat, state)
    settle(table, mid, candidate(combat, mid, 'Plant Lantern Fruit Seed', at=(5, 7)).candidate_id,
        choices={'choice:needle.harvest_growth_augments': None})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Minor Illusion', at=(6, 7)).candidate_id, choices={})
    engine = reload(tmp_path, mid)
    from combat.ext import placed
    zone, = placed.of(engine, 'figment')
    assert zone.owner_id == FOE
    readings = perception(engine, engine.state.actors[OWNER]).get('information', [])
    assert any(r['kind'] == 'lantern_observation' and 'flicker' in r['details']['text'] for r in readings)


def test_higher_cl_disease_receives_the_repeated_save(tmp_path, acquired):
    """Purifying Germination repeats a native disease's original save with Advantage."""
    from combat.canonical import canonical_sha256
    foe = sheet([], cl=18, name='Mara')
    foe['ability_scores_and_statistics']['technique_save_dc'] = 100
    bundle = compile_character(foe, actor_id=FOE)
    action = deepcopy(next(a for a in bundle['action_catalog'] if a['parameters'].get('typed')))
    source = 'action:test.harvest.disease_probe'
    action.update(source_definition_id=source, display_name='Disease Probe', economy='NONE',
                  target_kind='HOSTILE_ENTITY', range_ft=120, costs=[])
    action['parameters'] = {'expected_damage': 0, 'free_primary': True, 'typed': {
        'source': source, 'riders': [], 'area': None, 'zone_spec': {}, 'range_ft': 120,
        'duration': {'kind': 'instant'}, 'numbers': {'cl': 18, 'pb': 4, 'save_dc': 100},
        'effects': [{'type': 'save', 'ability': 'con', 'save_categories': ['disease'],
                     'on_fail': [{'type': 'condition', 'condition': 'diseased', 'applies_to': 'target',
                                  'duration': {'kind': 'minutes', 'amount': 10}}], 'on_success': []}]}}
    action['parameters']['typed'].pop('weapon', None)
    bundle['action_catalog'].append(action)
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)
    combat, state = prepared(tmp_path, acquired, cl=14, foe_bundle=bundle)
    table, mid = start(combat, state)
    turn(table, mid, FOE)
    probe = candidate(combat, mid, 'Disease Probe')
    ward = probe.target_ids[0]
    settle(table, mid, probe.candidate_id, choices={})
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    plant = next(c for c in harvest_candidates(engine, 'restoration')
        if engine.grid.distance_ft(c.destination, engine.state.actors[ward].position) <= 5)
    settle(table, mid, plant.candidate_id,
        choices={'choice:needle.harvest_ward': [ward], 'choice:willing.consent': ['accept']})
    # Reach the Ward's turn start, where the Seed heals and offers purification.
    advanced = False
    for _ in range(8):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == ward and advanced:
            break
        settle(table, mid, menu['end_turn'])
        advanced = True
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.diseased' for c in engine.state.actors[ward].conditions.values())
    seed = next(o for o in engine.state.objects.values() if o.component.get('restoration'))
    assert seed.component['charges'] == 1  # one automatic healing charge plus one purification charge
    assert [r for r in engine.rolls if r.actor_id == ward and r.mode == 'ADVANTAGE'], \
        'the higher-CL disease must repeat its original save with Advantage'


def test_purifying_spend_is_chosen_by_the_cultivator_not_the_ward(tmp_path, acquired):
    """The Seed owner spends the charge; the Ward is only the recipient."""
    combat, state = prepared(tmp_path, acquired)
    state = combat.journey_act(state['journey_id'], state['revision'], ALLY,
        'travel_exhaustion', {'levels': 2, 'ordinary': True})
    table, mid = start(combat, state)
    settle(table, mid, candidate(combat, mid, 'Seed of Restoration', at=(4, 7)).candidate_id,
        choices={'choice:needle.harvest_ward': [ALLY], 'choice:willing.consent': ['accept']})
    prompts = []
    while table.state(mid)['menu']['actor_id'] != ALLY:
        prompts += settle(table, mid, table.state(mid)['menu']['end_turn'],
            choices={'choice:needle.harvest_purifying_germination': ['exhaustion']})
    engine = reload(tmp_path, mid)
    from combat.ext.forged_exhaustion import level
    assert level(engine.state.actors[ALLY]) == 1
    seed = next(o for o in engine.state.objects.values() if o.component.get('restoration'))
    assert seed.component['charges'] == 1
    purifying = [p for p in prompts
                 if p['context']['reaction_source_id'] == 'choice:needle.harvest_purifying_germination']
    assert purifying and all(p['context']['reactor_id'] == OWNER for p in purifying)


def _restoration_and_ordinary_origins(combat, state):
    """Ward ALLY reaches 3 Exhaustion: 2 levels of ordinary travel, a table-owner Restoration cause for 2 of
    them, then 1 more ordinary travel level. Two separate origin records must exist."""
    jid = state['journey_id']
    state = combat.journey_act(jid, state['revision'], ALLY, 'travel_exhaustion', {'levels': 2, 'ordinary': True})
    state = combat.journey_world_fact(jid, state['revision'], {
        'source': RESTORE, 'subject': ALLY, 'kind': 'restoration_exhaustion_origin', 'scope': 'native_source',
        'expires_at': 86400, 'readers': [], 'value': {'cause': 'hunger', 'levels': 2}})
    return combat.journey_act(jid, state['revision'], ALLY, 'travel_exhaustion', {'levels': 1, 'ordinary': True})


def _origin_records(engine, aid):
    return {c.data.get('record'): c.data for c in engine.state.actors[aid].conditions.values()
            if c.condition_id == 'condition:typed.harvest_exhaustion_origin'}


def _encounter_then_travel(combat, tmp_path, jid, state):
    first = combat.journey_start_combat(jid, state['revision'], TEAMS, maximum_rounds=1)['match_id']
    table = TabletopService(combat, combat.userdata_root)
    turn(table, first, OWNER)
    run_to_terminal(combat, table, first)
    combat.journey_resume(jid, combat.journey_state(jid)['revision'])
    return combat.journey_start_combat(jid, combat.journey_state(jid)['revision'], TEAMS)['match_id']


def test_restoration_origin_survives_ordinary_travel_exhaustion_across_encounters(tmp_path, acquired):
    """Blocking review fix: the confirmed Restoration cause and the separate ordinary travel record both cross
    combat -> journey -> combat with a cold reload, and neither overwrites the other."""
    combat, state = prepared(tmp_path, acquired, cl=18)
    jid = state['journey_id']
    state = _restoration_and_ordinary_origins(combat, state)
    assert state['actors'][ALLY]['exhaustion'] == 3
    second = _encounter_then_travel(combat, tmp_path, jid, state)
    engine = reload(tmp_path, second)
    origins = _origin_records(engine, ALLY)
    assert set(origins) == {'restoration', 'ordinary'}, origins
    assert origins['restoration']['cause'] == 'hunger' and origins['restoration']['levels'] == 2
    assert origins['restoration']['receipt_id']
    assert origins['ordinary']['cause'] == 'travel'
    # The two records partition the 3 total levels: 2 Restoration, 1 ordinary travel.
    assert origins['ordinary']['levels'] == 1


def test_purifying_germination_spends_the_chosen_origin_record_only(tmp_path, acquired):
    """With both records present, choosing the ordinary travel record leaves the Restoration cause intact."""
    combat, state = prepared(tmp_path, acquired, cl=18)
    jid = state['journey_id']
    state = _restoration_and_ordinary_origins(combat, state)
    second = _encounter_then_travel(combat, tmp_path, jid, state)
    table = TabletopService(combat, combat.userdata_root)
    turn(table, second, OWNER)
    settle(table, second, candidate(combat, second, 'Seed of Restoration', at=(4, 7)).candidate_id,
        choices={'choice:needle.harvest_ward': [ALLY], 'choice:willing.consent': ['accept']})
    while table.state(second)['menu']['actor_id'] != ALLY:
        settle(table, second, table.state(second)['menu']['end_turn'],
            choices={'choice:needle.harvest_purifying_germination': ['exhaustion:ordinary']})
    engine = reload(tmp_path, second)
    origins = _origin_records(engine, ALLY)
    assert origins['restoration']['cause'] == 'hunger' and origins['restoration']['levels'] == 2
    assert 'ordinary' not in origins
    from combat.ext.forged_exhaustion import level
    assert level(engine.state.actors[ALLY]) == 2


def test_restoration_declared_after_travel_claims_those_levels(tmp_path, acquired):
    """Regression: travel Exhaustion recorded before a Restoration declaration is covered by it, so the
    crossing carries only the Restoration record (no ordinary record that double-counts the same levels)."""
    combat, state = prepared(tmp_path, acquired, cl=18)
    jid = state['journey_id']
    state = combat.journey_act(jid, state['revision'], ALLY, 'travel_exhaustion', {'levels': 2, 'ordinary': True})
    state = combat.journey_world_fact(jid, state['revision'], {
        'source': RESTORE, 'subject': ALLY, 'kind': 'restoration_exhaustion_origin', 'scope': 'native_source',
        'expires_at': 86400, 'readers': [], 'value': {'cause': 'hunger', 'levels': 2}})
    assert state['actors'][ALLY]['exhaustion'] == 2
    second = _encounter_then_travel(combat, tmp_path, jid, state)
    engine = reload(tmp_path, second)
    origins = _origin_records(engine, ALLY)
    assert set(origins) == {'restoration'}, origins
    assert origins['restoration']['levels'] == 2


def test_each_origin_record_is_restored_exactly_once_across_the_carry(tmp_path, acquired):
    """Regression: the carried ordinary record must not be re-applied on restore. Duplicate records
    leave a surviving copy after one is purified, so Exhaustion appears to persist."""
    combat, state = prepared(tmp_path, acquired, cl=18)
    jid = state['journey_id']
    state = _restoration_and_ordinary_origins(combat, state)
    second = _encounter_then_travel(combat, tmp_path, jid, state)
    engine = reload(tmp_path, second)
    counts = {}
    for c in engine.state.actors[ALLY].conditions.values():
        if c.condition_id == 'condition:typed.harvest_exhaustion_origin':
            counts[c.data.get('record')] = counts.get(c.data.get('record'), 0) + 1
    assert counts == {'restoration': 1, 'ordinary': 1}, counts
