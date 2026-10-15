"""Ice review regressions at table commit/reload boundaries.

The delayed-movement fixture seals a synthetic event producer, not a replacement
for any shipped mechanic. It models an origin occupied between movement and its
reaction, with saved wall zones and a bound Large footprint where requested.
"""
import copy
import pytest

from combat import ext, senses, zones
from combat.gate2_runtime_models import Position, ZoneState
from combat.footprints import ActorFootprintDefinition
from combat.footprint_registry import ACTOR_FOOTPRINTS
from combat.target_knowledge import can_see, located
from combat.ext.ice_fracture import BITTER, STORED, T, marked, give_mark, _lattice_at
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload
from tests.test_auto116_ice import setup, reach, asked, FOE_CELL


def kit(*weapons):
    return {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.' + w} for w in weapons]}}


def strike_source(combat, mid, name):
    return candidate(combat, mid, name, target=FOE).source_definition_id


def damage(engine):
    return [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == T + 'BITTER_EDGE']


def free_hits(bundles):
    """Sealed test attacks cost no Action, allowing two hit decisions in one turn."""
    setup(bundles)
    for bundle in bundles:
        action = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Unarmed Strike')
        probe = copy.deepcopy(action)
        probe['source_definition_id'] += '.test_bare'
        probe['display_name'] = 'Bare hit'
        probe['economy'] = 'NONE'
        bundle['action_catalog'].append(probe)
        bundle['actor_template']['action_ids'].append(probe['source_definition_id'])
        seal(bundle)


def test_two_weapons_require_coating_choice_and_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [T + 'BITTER_EDGE'], foe_position=FOE_CELL,
                                 owner_kit=kit('dao', 'bi_shou'), bundle_transform=setup)
    dagger = strike_source(combat, mid, 'Bi Shou (Dagger) attack')
    prompts = settle(table, mid, candidate(combat, mid, 'Bitter Edge', target=OWNER).candidate_id,
                     {'choice:needle.bitter_coat': dagger})
    coat = asked(prompts, 'choice:needle.bitter_coat')
    assert len(coat) == 1
    assert len(coat[0]['choice']['options']) >= 3  # both weapons and Unarmed Strike
    edge = next(c for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values() if c.condition_id == BITTER)
    assert edge.data['strike'] == dagger


@pytest.mark.parametrize('weapons', [(), ('bi_shou',)])
def test_unarmed_can_be_coated_and_hits(tmp_path, weapons):
    combat, table, mid = fixture(tmp_path, [T + 'BITTER_EDGE'], foe_position=FOE_CELL,
                                 owner_kit=kit(*weapons), bundle_transform=setup)
    unarmed = strike_source(combat, mid, 'Unarmed Strike')
    settle(table, mid, candidate(combat, mid, 'Bitter Edge', target=OWNER).candidate_id,
           {'choice:needle.bitter_coat': unarmed})
    edge = next(c for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values() if c.condition_id == BITTER)
    assert edge.data['strike'] == unarmed
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id,
                     {'choice:needle.bitter_type': 'PIERCING'})
    assert asked(prompts, 'choice:needle.bitter_type')
    assert damage(reload(tmp_path, mid))[-1].payload['damage_type'] == 'PIERCING'


def test_uncoated_hit_does_not_ice_but_next_coated_hit_does(tmp_path):
    combat, table, mid = fixture(tmp_path, [T + 'BITTER_EDGE'], foe_position=FOE_CELL,
                                 owner_kit=kit('bi_shou'), bundle_transform=free_hits)
    dagger = strike_source(combat, mid, 'Bi Shou (Dagger) attack')
    prompts = settle(table, mid, candidate(combat, mid, 'Bitter Edge', target=OWNER).candidate_id,
                     {'choice:needle.bitter_coat': dagger})
    assert asked(prompts, 'choice:needle.bitter_coat')
    prompts = settle(table, mid, candidate(combat, mid, 'Bare hit', target=FOE).candidate_id)
    assert not asked(prompts, 'choice:needle.bitter_type')
    assert not damage(reload(tmp_path, mid))
    settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE).candidate_id)
    assert damage(reload(tmp_path, mid))


def test_decline_bitter_damage_keeps_use_and_does_not_mark(tmp_path):
    combat, table, mid = fixture(tmp_path, [T + 'BITTER_EDGE'], foe_position=FOE_CELL,
                                 owner_kit=kit('bi_shou'), bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id)
    reach(table, mid, ALLY)
    reach(table, mid, OWNER)
    dagger = strike_source(combat, mid, 'Bi Shou (Dagger) attack')
    settle(table, mid, candidate(combat, mid, 'Bitter Edge', target=OWNER).candidate_id,
           {'choice:needle.bitter_coat': dagger})
    settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE).candidate_id,
           {'choice:needle.bitter_type': None})
    engine = reload(tmp_path, mid)
    assert not damage(engine)
    assert not marked(engine.state.actors[FOE], OWNER)
    assert engine.state.actors[OWNER].turn_flags.get('ice_bitter_edge') != engine.state.actors[OWNER].turns_started


def test_adjacent_only_winter_target_cannot_trigger(tmp_path):
    combat, table, mid = fixture(tmp_path, [T + 'WINTER_STORES_THE_BLOW'],
                                 foe_position={'x': 1, 'y': 6}, bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id)
    reach(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Deal impact', target=FOE).candidate_id)
    assert not asked(prompts, 'choice:needle.winter_stores')
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == STORED for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 100


def test_eligible_winter_target_can_store_beside_it_with_plain_terms(tmp_path):
    combat, table, mid = fixture(tmp_path, [T + 'WINTER_STORES_THE_BLOW'], foe_position=FOE_CELL,
                                 bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id)
    reach(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Deal impact', target=FOE).candidate_id,
                     {'choice:needle.winter_stores_space': 'cell:2,6'})
    offer = asked(prompts, 'choice:needle.winter_stores')[0]
    space = asked(prompts, 'choice:needle.winter_stores_space')[0]
    text = str(offer) + str(space)
    assert 'reduce it by 6' in text and 'Reaction' in text and '1 Qi' in text
    assert 'does not charge that cost automatically' not in text
    assert 'adds 6 damage' in text
    assert 'end of your next turn' in text
    engine = reload(tmp_path, mid)
    stored = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == STORED)
    assert (stored.data['x'], stored.data['y'], stored.data['amount']) == (2, 6, 6)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 99
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
              and e.source_definition_id == T + 'WINTER_STORES_THE_BLOW']
    assert len(spends) == 1 and spends[0].payload['amount'] == 1


def test_pinpointed_unseen_winter_target_is_not_offered(tmp_path, monkeypatch):
    def grant_sense(ctx, eff):
        ctx.engine._apply_condition(ctx.actor, senses.SENSE, ctx.source, ctx.actor.entity_id,
                                    expires_on='UNTIL_REMOVED', data={'sense': 'tremorsense', 'range_ft': 60})
    monkeypatch.setitem(ext.effects(), 'test_ice_sense', grant_sense)
    def prepare(bundles):
        setup(bundles)
        add_action(bundles[0], 'Sense ground', [{'type': 'test_ice_sense'}], target='SELF')
    combat, table, mid = fixture(tmp_path, [T + 'WINTER_STORES_THE_BLOW'], foe_position=FOE_CELL,
                                 bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Sense ground', target=OWNER).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Blind myself', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert located(engine, engine.state.actors[OWNER], engine.state.actors[FOE])
    assert not can_see(engine, engine.state.actors[OWNER], engine.state.actors[FOE])
    reach(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Deal impact', target=FOE).candidate_id)
    assert not asked(prompts, 'choice:needle.winter_stores')
    assert reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi'] == 100


@pytest.mark.parametrize('case', ['wall', 'large', 'second_ring'])
def test_reversal_returns_to_nearest_legal_full_footprint_table(tmp_path, monkeypatch, case):
    start, end = (8, 10), (12, 10)
    if case == 'large':
        monkeypatch.setitem(ACTOR_FOOTPRINTS, FOE, ActorFootprintDefinition.rectangle(
            2, 2, footprint_id='test:ice.large', source_definition_id='test:ice.large'))
    blocked = [(7, 9)] if case == 'wall' else []
    if case == 'second_ring':
        blocked = [(x, y) for x in range(7, 10) for y in range(9, 12) if (x, y) != start]

    def delayed_movement(ctx, eff):
        engine = ctx.engine
        mover = engine.state.actors[FOE]
        owner = engine.state.actors[OWNER]
        give_mark(engine, owner, mover, ctx.source)
        _lattice_at(engine, owner, mover, 'ICE_BASE_CRYSTALLIZE_PATH')
        before = mover.position
        mover.position = Position(x=end[0], y=end[1])
        _lattice_at(engine, owner, mover, 'ICE_BASE_CRYSTALLIZE_PATH')
        blocker = engine.state.actors[ALLY]
        blocker_start = blocker.position
        blocker.position = Position(x=start[0], y=start[1])
        engine._append_event('MOVEMENT_COMMITTED', ctx.source, actor_id=ALLY,
            payload={'destination': blocker.position.model_dump(mode='json'),
                     'path': [blocker_start.model_dump(mode='json'), blocker.position.model_dump(mode='json')],
                     'cost_ft': 0, 'forced': True})
        if blocked:
            center = Position(x=blocked[0][0], y=blocked[0][1])
            zone = ZoneState(zone_id='zone:test.ice.wall', source_definition_id=ctx.source, owner_id=OWNER,
                center=center, radius_cells=0, affected_cells=tuple(Position(x=x, y=y) for x, y in blocked),
                concentration_link=False, created_round=engine.state.round_number,
                trigger_profile={'kind': 'TYPED', 'wall': {'blocks_movement': True}})
            engine.state.zones[zone.zone_id] = zone
            engine._append_event('ZONE_CREATED', ctx.source, actor_id=OWNER, payload={'zone': zone.model_dump(mode='json')})
            zones.sync_walls(engine)
        engine._append_event('MOVEMENT_COMMITTED', ctx.source, actor_id=mover.entity_id,
            payload={'destination': mover.position.model_dump(mode='json'),
                     'path': [before.model_dump(mode='json'), mover.position.model_dump(mode='json')],
                     'cost_ft': 0, 'teleport': True})

    monkeypatch.setitem(ext.effects(), 'test_ice_delayed_move', delayed_movement)
    def prepare(bundles):
        setup(bundles)
        add_action(bundles[0], 'Finish delayed movement', [{'type': 'test_ice_delayed_move'}], target='SELF')
    combat, table, mid = fixture(tmp_path, [T + 'FROZEN_RIVER_REVERSAL'],
                                 foe_position={'x': start[0], 'y': start[1]}, bundle_transform=prepare)
    prompts = settle(table, mid, candidate(combat, mid, 'Finish delayed movement', target=OWNER).candidate_id,
                     {'choice:needle.river_reversal': 'use'})
    assert asked(prompts, 'choice:needle.river_reversal')
    engine = reload(tmp_path, mid)
    mover = engine.state.actors[FOE]
    assert engine.grid.placement_legal(mover.position, footprint=engine._footprint(mover),
                                       occupied_cells=engine._occupied_cells_except(FOE))
    assert mover.position != Position(x=end[0], y=end[1])
    expected_distance = 2 if case == 'second_ring' else 1
    assert max(abs(mover.position.x-start[0]), abs(mover.position.y-start[1])) == expected_distance
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 97
    assert not engine.state.actors[OWNER].reaction_available
    assert not asked(prompts, 'choice:needle.fracture_response')
    assert marked(mover, OWNER)
    assert 'ice_spent_round' not in engine.state.actors[OWNER].turn_flags


def test_natural_strike_can_be_selected_and_hits(tmp_path):
    def prepare(bundles):
        setup(bundles)
        bundle = bundles[0]
        original = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Unarmed Strike')
        natural = copy.deepcopy(original)
        natural['source_definition_id'] = original['source_definition_id'] + '.natural.test_claw'
        natural['display_name'] = 'Claw attack'
        bundle['action_catalog'].append(natural)
        bundle['actor_template']['action_ids'].append(natural['source_definition_id'])
        seal(bundle)
    combat, table, mid = fixture(tmp_path, [T + 'BITTER_EDGE'], foe_position=FOE_CELL, bundle_transform=prepare)
    claw = strike_source(combat, mid, 'Claw attack')
    prompts = settle(table, mid, candidate(combat, mid, 'Bitter Edge', target=OWNER).candidate_id,
                     {'choice:needle.bitter_coat': claw})
    assert asked(prompts, 'choice:needle.bitter_coat')
    settle(table, mid, candidate(combat, mid, 'Claw attack', target=FOE).candidate_id,
           {'choice:needle.bitter_type': 'PIERCING'})
    engine = reload(tmp_path, mid)
    assert damage(engine)[-1].payload['damage_type'] == 'PIERCING'
    assert next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == BITTER).data['strike'] == claw


def test_ai_bitter_wielder_chooses_automatically(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = fixture(tmp_path, [T + 'BITTER_EDGE'], foe_position=FOE_CELL,
                                 owner_kit=kit('bi_shou'), bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Bitter Edge', target=OWNER).candidate_id)
    cid = candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE).candidate_id
    real = combat.controller
    class HitController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = HitController()
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    assert table.auto_step(mid, 0, [])['status'] == 'COMMITTED'
    assert damage(reload(tmp_path, mid))
