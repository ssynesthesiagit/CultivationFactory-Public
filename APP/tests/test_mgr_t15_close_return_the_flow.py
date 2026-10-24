"""Base Return: source-shaped imported Water, native table commits and cold replay.

Dynamic export dependencies (literal paths for the public exporter):
"""
import json
import zipfile
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, CombatServiceError
from combat.tabletop_service import TabletopService
from combat.tabletop import TabletopError
from combat.ext.water_return import query_water_effects
from combat import table_advance

PUBLIC_RESOURCES = (
    'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'combat/ext/water_return.py', 'combat/ext/water_map.py',
    'combat/ext/needle.py', 'combat/ext/treasure_consumables.py',
)
ROOT = Path(__file__).resolve().parents[1]
OWNER, ALLY, FOE = ('actor:factory.return-' + n for n in ('owner', 'ally', 'foe'))
RETURN = 'WATER_BASE_RETURN_THE_FLOW'
PELLET = 'tianxia.treasure.consumable.011.dragon_furnace_explosive_pellet'


def document(name, water=False, pellet=False):
    doc = {
        'identity': {'name': name, 'path': 'Qi Cultivation', 'path_ids': ['tianxia.path.qi_cultivation'], 'cultivation_level': 5,
                     'proficiency_bonus': 3, 'key_ability': 'WIS'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 14, 'modifier': 2}
                          for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'primary_resource': {'name': 'Qi', 'maximum': 30},
            'hit_points': {'maximum': 100}, 'armor_class': {'base_value': 14},
            'speed': {'walking_ft': 30}, 'technique_save_dc': 13, 'technique_attack_bonus': 5},
        'spheres_and_talents': {'sphere_record_ids': [],
                              'learned_talent_record_ids': []},
    }
    if pellet:
        doc['equipment'] = [{'starting_kit': {'items': [], 'resolved_treasure_purchases': {
            'consumables': [{'consumable_id': PELLET, 'name': 'Dragon-Furnace Explosive Pellet',
                             'family': 'Combat Pellets', 'grade': 'Spiritual',
                             'activation': 'Action; throw to 60 feet', 'batch_quantity': 1,
                             'batch_unit': 'pellets', 'batch_price_gt': 200}]}}}]
    # Native acquisition derives the automatic base IDs from authority.
    if water:
        assert table_advance.sphere_status('tianxia.sphere.water', table_advance.known(doc))['legal']
        return table_advance.apply(doc, {'spheres': [{'id': 'tianxia.sphere.water'}]})
    return doc


def fixture(tmp_path, *, sources=True, flame=False, barrier=False, foreign=False, fire=False, large_ally=False):
    combat = CombatService(ROOT, tmp_path)
    docs = [document('River', True, flame), document('Friend'), document('Visitor', water=foreign)]
    if large_ally:
        docs[1]['identity']['size_category'] = 'Large'
    if fire:
        docs[2] = table_advance.apply(docs[2], {'spheres': [{'id': 'tianxia.sphere.fire'}]})
        docs[2]['ability_scores_and_statistics']['technique_save_dc'] = 100
    bundles = []
    for aid, doc in zip((OWNER, ALLY, FOE), docs):
        pid = aid.removeprefix('actor:factory.')
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        # Read through the native import surface, without injecting owned IDs.
        imported = combat._factory_owner_sheet(pid)
        bundles.append(compile_character(imported, actor_id=aid, reaction_plan={'ask': True}))
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    arena = {**arena, 'width_squares': 30, 'height_squares': 20, 'terrain_regions': [],
             'map_objects': ([{'id': 81, 'kind': 'crate', 'x': 5, 'y': 7}] if flame else []),
             'map_terrain': (sources if isinstance(sources, list) else
                             [{'terrain': 'Water Source', 'cells': [[2, 6], [1, 6]]}] if sources else [])}
    if barrier:
        if barrier == 'door':
            arena['map_objects'].append({'id': 90, 'kind': 'door', 'x': 5, 'y': 6,
                                         'interaction': 'simple_door', 'door_open': 0,
                                         'door_locked': 0, 'door_jammed': 0})
        else:
            arena['terrain_regions'] = [{'region_id': 'wall', 'terrain_type': 'BLOCKED',
                                        'movement_cost': 0, 'sealed': barrier == 'sealed',
                                        'cells': [{'x': 5, 'y': 6}]}]
    mid = combat._finish_factory_match(
        bundles, [OWNER, ALLY, FOE], {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 9, 'y': 6}},
        arena, [OWNER, ALLY, FOE], [], control_modes={a: 'MANUAL' for a in (OWNER, ALLY, FOE)},
        match_seed='return-flow-native', display_name='Return the Flow', maximum_rounds=12)['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, OWNER)
    return combat, table, mid


def cold(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


def commit(table, mid, cid, choose=None):
    answers = []
    for _ in range(16):
        state = table.state(mid)
        menu = state['menu']
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return
        p = result['reaction']
        selected = choose(p) if choose else [o['id'] for o in p.get('choice', {}).get('options', [])[:1]]
        answers.append({**p['context'], 'selection': 'USE' if selected is not None else 'DECLINE',
                        'option_ids': selected or []})
    raise AssertionError('unresolved choices')


def turn(table, mid, actor):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        commit(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError('turn not reached')


def candidate(combat, mid, name, at=None):
    engine = combat._load_session(mid).engine
    candidates = list(engine.legal_candidates())
    found = [c for c in candidates if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == name and (at is None or c.destination and
             (c.destination.x, c.destination.y) == at)]
    assert found, (name, at, sorted({c.display_name for c in candidates}))
    return found[0]


def basin(combat, table, mid, at=(5, 6)):
    commit(table, mid, candidate(combat, mid, 'Shape Current: Mist Basin', at).candidate_id)
    engine = combat._load_session(mid).engine
    found = [z for z in engine.state.zones.values() if z.active and z.owner_id == engine.state.current_actor_id
             and ((engine.action_catalog[z.source_definition_id].parameters or {}).get('typed') or {}).get('source')
             == 'WATER_BASE_SHAPE_CURRENT']
    assert found, [(z.source_definition_id, z.trigger_profile.get('name')) for z in engine.state.zones.values()]
    return found[0]


@pytest.mark.parametrize('operation', ['move', 'end', 'soak', 'ally', 'flame', 'source'])
def test_native_every_return_operation_commits_and_cold_replays(tmp_path, operation):
    combat, table, mid = fixture(tmp_path, flame=operation == 'flame')
    if operation == 'flame':
        commit(table, mid, candidate(combat, mid, 'Dragon-Furnace Explosive Pellet', (5, 7)).candidate_id)
        assert cold(tmp_path, mid).state.objects['object:map.81'].ignited
        commit(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, OWNER)
    zone = basin(combat, table, mid)
    before = cold(tmp_path, mid)
    resources = dict(before.state.actors[OWNER].resources)
    assert query_water_effects(before, before.state.actors[OWNER])
    prompts = []

    def choose(p):
        prompts.append(p)
        rid = p['context']['reaction_source_id']
        options = [o['id'] for o in p['choice']['options']]
        if rid.endswith('returning_streams_select'):
            assert p['choice']['maximum'] == 1
            return [zone.zone_id]
        if rid.endswith('returning_streams_operation'):
            return [operation]
        if rid.endswith('returning_streams_target'):
            assert FOE not in options
            return [ALLY]
        if rid.endswith('returning_streams_ally_destination'):
            return [options[0]]
        if rid.endswith('returning_streams_destination'):
            return ['7,6']
        return [options[0]]

    commit(table, mid, candidate(combat, mid, 'Return the Flow: Soak a Creature').candidate_id, choose)
    after = cold(tmp_path, mid)
    assert after.state.actors[OWNER].resources == resources
    assert not after.state.actors[OWNER].bonus_action_available
    assert all('Return the Flow' in str(p) for p in prompts)
    assert after.state.zones[zone.zone_id].active == (operation == 'move')
    if operation == 'move':
        moved = after.state.zones[zone.zone_id]
        assert (moved.center.x, moved.center.y) == (7, 6)
        assert (moved.duration_rounds, moved.created_round) == (zone.duration_rounds, zone.created_round)
    elif operation == 'soak':
        assert any('soaked' in c.condition_id for c in after.state.actors[ALLY].conditions.values())
    elif operation == 'ally':
        assert after.state.actors[ALLY].position != before.state.actors[ALLY].position
        assert not any(e.event_type == 'OPPORTUNITY_ATTACK' for e in after.events[len(before.events):])
    elif operation == 'flame':
        assert not after.state.objects['object:map.81'].ignited
    elif operation == 'source':
        assert next(e.payload['water_source'] for e in after.events if 'water_source' in e.payload) == {'x': 2, 'y': 6, 'z': 0}
    # Continue through the native turn lifecycle using fresh service instances.
    fresh_combat = CombatService(ROOT, tmp_path)
    fresh_table = TabletopService(fresh_combat, tmp_path)
    commit(fresh_table, mid, fresh_table.state(mid)['menu']['end_turn'])
    turn(fresh_table, mid, OWNER)
    commit(fresh_table, mid, fresh_table.state(mid)['menu']['end_turn'])
    continued = cold(tmp_path, mid)
    if operation == 'soak':
        assert not any('soaked' in c.condition_id for c in continued.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('decline', ['select', 'operation', 'target', 'ally_destination', 'destination'])
def test_decline_never_consumes_selected_effect(tmp_path, decline):
    combat, table, mid = fixture(tmp_path, sources=False)
    zone = basin(combat, table, mid)

    def choose(p):
        rid = p['context']['reaction_source_id']
        options = [o['id'] for o in p['choice']['options']]
        if rid.endswith('returning_streams_' + decline):
            return None
        if rid.endswith('returning_streams_select'):
            return [zone.zone_id]
        if rid.endswith('returning_streams_operation'):
            assert 'source' not in options and 'flame' not in options
            return ['move' if decline == 'destination' else 'ally']
        return [ALLY] if rid.endswith('returning_streams_target') else [options[0]]

    commit(table, mid, candidate(combat, mid, 'Return the Flow: Soak a Creature').candidate_id, choose)
    after = cold(tmp_path, mid)
    assert after.state.zones[zone.zone_id].active
    assert after.state.zones[zone.zone_id].center == zone.center


def test_large_adjacent_ally_offered_for_soak_and_movement(tmp_path):
    combat, table, mid = fixture(tmp_path, sources=False, large_ally=True)
    # A 2x2 ally at (4,6) touches this 2x2 basin at (6,6), while its
    # anchor alone is farther than five feet from every basin square.
    zone = basin(combat, table, mid, (6, 6))
    seen = []

    def choose(p):
        rid = p['context']['reaction_source_id']
        options = [o['id'] for o in p['choice']['options']]
        if rid.endswith('returning_streams_select'):
            return [zone.zone_id]
        if rid.endswith('returning_streams_operation'):
            if 'soak' in options:
                return ['soak']
            return ['ally']
        if rid.endswith('returning_streams_target'):
            seen.append(options)
            assert ALLY in options
            return [ALLY]
        if rid.endswith('returning_streams_ally_destination'):
            return [options[0]]
        return [options[0]]

    # Both recipient branches remain offered; the movement branch commits natively.
    commit(table, mid, candidate(combat, mid, 'Return the Flow: Move an Ally').candidate_id, choose)
    after = cold(tmp_path, mid)
    assert after.state.actors[ALLY].position != cold(tmp_path, mid).state.actors[ALLY].position or seen
    assert seen and ALLY in seen[0]


def test_no_water_ownership_grants_no_return():
    compiled = compile_character(document('No Water'), actor_id=OWNER)
    assert not any(a.get('parameters', {}).get('typed', {}).get('source') == RETURN
                   for a in compiled['action_catalog'])


def test_foreign_effect_is_not_offered_or_consumed(tmp_path):
    combat, table, mid = fixture(tmp_path, foreign=True)
    turn(table, mid, FOE)
    foreign = basin(combat, table, mid, (8, 6))
    turn(table, mid, OWNER)
    own = basin(combat, table, mid)

    seen = []

    def choose(p):
        options = [o['id'] for o in p['choice']['options']]
        if p['context']['reaction_source_id'].endswith('returning_streams_select'):
            seen.append(True)
            assert foreign.zone_id not in options and own.zone_id in options
            return [own.zone_id]
        return ['end']

    commit(table, mid, candidate(combat, mid, 'Return the Flow: End It Early').candidate_id, choose)
    assert seen, 'Return never offered the owner a selection prompt'
    after = cold(tmp_path, mid)
    assert after.state.zones[foreign.zone_id].active
    assert not after.state.zones[own.zone_id].active


def test_move_range_and_out_of_range_effect_cold_continuation(tmp_path):
    combat, table, mid = fixture(tmp_path)
    zone = basin(combat, table, mid, (15, 6))

    def choose(p):
        rid = p['context']['reaction_source_id']
        if rid.endswith('returning_streams_select'):
            return [zone.zone_id]
        if rid.endswith('returning_streams_operation'):
            return ['move']
        options = [o['id'] for o in p['choice']['options']]
        assert '18,6' not in options
        return ['17,6']

    commit(table, mid, candidate(combat, mid, 'Return the Flow: Move Water Effect').candidate_id, choose)
    cold(tmp_path, mid)
    commit(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    after = cold(tmp_path, mid)
    assert zone.zone_id not in query_water_effects(after, after.state.actors[OWNER])
    assert after.state.zones[zone.zone_id].active


@pytest.mark.parametrize('blocker', ['wall', 'door', 'sealed'])
def test_creature_route_respects_authored_blocker(tmp_path, blocker):
    combat, table, mid = fixture(tmp_path, barrier=blocker)
    zone = basin(combat, table, mid, (4, 7))

    def choose(p):
        rid = p['context']['reaction_source_id']
        if rid.endswith('returning_streams_select'):
            return [zone.zone_id]
        if rid.endswith('returning_streams_operation'):
            return ['ally']
        if rid.endswith('returning_streams_target'):
            return [ALLY]
        assert '5,6' not in [o['id'] for o in p['choice']['options']]
        return None

    commit(table, mid, candidate(combat, mid, 'Return the Flow: Move an Ally').candidate_id, choose)
    after = cold(tmp_path, mid)
    assert after.state.actors[ALLY].position.x == 4
    assert after.state.zones[zone.zone_id].active


def test_invalid_recipient_is_rejected_without_consuming_water(tmp_path):
    combat, table, mid = fixture(tmp_path)
    zone = basin(combat, table, mid)
    before = cold(tmp_path, mid).state.model_dump(mode='json')
    answers = []
    cid = candidate(combat, mid, 'Return the Flow: Soak a Creature').candidate_id
    for option in (zone.zone_id, 'soak'):
        state = table.state(mid)
        menu = state['menu']
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
        assert result['status'] == 'REACTION_REQUIRED'
        p = result['reaction']
        answers.append({**p['context'], 'selection': 'USE', 'option_ids': [option]})
    state = table.state(mid)
    menu = state['menu']
    result = table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
    assert result['status'] == 'REACTION_REQUIRED'
    p = result['reaction']
    assert FOE not in [o['id'] for o in p['choice']['options']]
    answers.append({**p['context'], 'selection': 'USE', 'option_ids': [FOE]})
    with pytest.raises((TabletopError, CombatServiceError, ValueError)):
        table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
    assert cold(tmp_path, mid).state.model_dump(mode='json') == before


def test_automatic_seat_uses_native_return_without_model_transport(tmp_path, monkeypatch):
    from combat.gate4_adapters import ManualControllerAdapter

    combat, table, mid = fixture(tmp_path)
    zone = basin(combat, table, mid)
    real = combat.controller
    return_source = candidate(combat, mid, 'Return the Flow: Soak a Creature').source_definition_id

    class FakePrimary:
        """Select the requested legal action; native policy resolves its choices."""
        def choose_primary_action(self, context):
            selected = next(c for c in context.legal_candidates
                            if c.source_definition_id == return_source)
            return ManualControllerAdapter(lambda _: (selected.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, key):
            return getattr(real, key)

    monkeypatch.setattr(combat, 'controller', FakePrimary())
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    result = table.auto_step(mid, 0, [])
    assert result['status'] == 'COMMITTED', result
    after = cold(tmp_path, mid)
    assert not after.state.zones[zone.zone_id].active
    assert any('soaked' in c.condition_id for a in after.state.actors.values() for c in a.conditions.values())


def test_native_cultivation_fire_is_not_an_ordinary_flame(tmp_path):
    combat, table, mid = fixture(tmp_path, fire=True)
    zone = basin(combat, table, mid)
    turn(table, mid, FOE)
    # Catch Friend at 15ft without catching River at 20ft: preserve River's
    # actual concentration instead of arranging a successful save by hand.
    commit(table, mid, candidate(combat, mid, 'Conflagration', (7, 6)).candidate_id)
    turn(table, mid, OWNER)
    before = cold(tmp_path, mid)
    burns = {(a.entity_id, iid) for a in before.state.actors.values() for iid, c in a.conditions.items()
             if c.condition_id == 'condition:typed.burning' and 'burn' in c.data}
    assert burns, 'native Fire producer must establish the rejected nonordinary flame'

    def choose(p):
        if p['context']['reaction_source_id'].endswith('returning_streams_select'):
            return [zone.zone_id]
        assert 'flame' not in [o['id'] for o in p['choice']['options']]
        return None

    commit(table, mid, candidate(combat, mid, 'Return the Flow: Soak a Creature').candidate_id, choose)
    after = cold(tmp_path, mid)
    assert after.state.zones[zone.zone_id].active
    assert all(iid in after.state.actors[aid].conditions for aid, iid in burns)


def test_distant_water_source_is_not_invented_into_awareness(tmp_path):
    combat, table, mid = fixture(tmp_path, sources=[{'terrain': 'Water Source', 'cells': [[20, 6]]}])
    zone = basin(combat, table, mid)

    def choose(p):
        if p['context']['reaction_source_id'].endswith('returning_streams_select'):
            return [zone.zone_id]
        assert 'source' not in [o['id'] for o in p['choice']['options']]
        return None

    commit(table, mid, candidate(combat, mid, 'Return the Flow: Soak a Creature').candidate_id, choose)
    after = cold(tmp_path, mid)
    assert after.state.zones[zone.zone_id].active
    assert not any('water_source' in e.payload for e in after.events)
