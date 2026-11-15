"""Foundation conversion receipts through Table -> session execute_intent."""
import pytest
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, fixture, settle, candidate, reload, turn, sealed_native_attack
DRAGON = 'dragon_wind_vessel_v0_2E'
FURNACE = 'furnace_heart_record_v0_2B'


def setup(tmp_path, foundation=DRAGON, stage='Awakened', held=0, flying=False, blink=False, attacks=1, refill=False,
          speed_debuff=False, speed_restore=False, prone_setup=False, extra_reaction=None, foe_attack=False, ask=False):
    name = 'Dragon-Wind Momentum' if foundation == DRAGON else 'Furnace Heat'
    doc = sheet([])
    doc['foundation'] = {'foundation_id': foundation, 'stage': stage,
        'resource': {'name': name, 'resource_id': 'tianxia.resource.foundation.' + foundation,
                     'maximum': 1, 'current': held}}
    owner = compile_character(doc, actor_id=OWNER)
    sealed_native_attack(owner, 'Settled hit', attack_bonus=100, modifier=0, attacks=attacks)
    if refill:
        source = 'action:test.foundation_heat_refill'
        owner['action_catalog'].append({'source_definition_id': source, 'display_name': 'Test Furnace Heat Refill',
            'owner_id': OWNER, 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
            'parameters': {'typed': {'source': source, 'numbers': {}, 'effects': [
                {'type': 'gain_resource', 'resource_id': 'resource:foundation.furnace_heat', 'flat': 1, 'applies_to': 'self'}],
                'riders': [], 'duration': {'kind': 'instant'}}}})
        owner['actor_template']['action_ids'].append(source)
        from combat.canonical import canonical_sha256
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)
    if prone_setup:
        from combat.canonical import canonical_sha256
        source = 'action:test.foundation_prone_setup'
        owner['action_catalog'].append({'source_definition_id': source, 'display_name': 'Test Lie Down',
            'owner_id': OWNER, 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
            'parameters': {'typed': {'source': source, 'numbers': {}, 'effects': [
                {'type': 'condition', 'condition': 'prone', 'applies_to': 'self'}],
                'riders': [], 'duration': {'kind': 'instant'}}}})
        owner['actor_template']['action_ids'].append(source)
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)
    if speed_debuff:
        from combat.canonical import canonical_sha256
        source = 'action:test.foundation_speed_debuff'
        owner['action_catalog'].append({'source_definition_id': source, 'display_name': 'Test Speed Reduction',
            'owner_id': OWNER, 'economy': 'BONUS_ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
            'parameters': {'typed': {'source': source, 'numbers': {}, 'effects': [
                {'type': 'speed', 'flat': -10, 'applies_to': 'self', 'duration': 'until_end_of_turn'}],
                'riders': [], 'duration': {'kind': 'instant'}}}})
        owner['actor_template']['action_ids'].append(source)
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)
    if speed_restore:
        from combat.canonical import canonical_sha256
        source = 'action:test.foundation_speed_restore'
        owner['action_catalog'].append({'source_definition_id': source, 'display_name': 'Test Speed Restoration',
            'owner_id': OWNER, 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
            'parameters': {'typed': {'source': source, 'numbers': {}, 'effects': [
                {'type': 'speed', 'flat': 10, 'applies_to': 'self', 'duration': 'until_end_of_turn'}],
                'riders': [], 'duration': {'kind': 'instant'}}}})
        owner['actor_template']['action_ids'].append(source)
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)
    if flying or blink:
        from combat.canonical import canonical_sha256
        if flying:
            owner['actor_template']['fly_speed_ft'] = 30
        if blink:
            source = 'action:test.foundation_blink'
            owner['action_catalog'].append({'source_definition_id': source, 'display_name': 'Fixture Blink',
                'owner_id': OWNER, 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
                'range_ft': 20, 'parameters': {'typed': {'source': source, 'numbers': {},
                    'effects': [{'type': 'teleport', 'applies_to': 'self', 'distance_ft': 20}], 'riders': []}}})
            owner['actor_template']['action_ids'].append(source)
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)
    def transform(bundles):
        from combat.canonical import canonical_sha256
        if extra_reaction:
            reactions = extra_reaction if isinstance(extra_reaction, list) else [extra_reaction]
            bundles[0]['typed_reactions'].extend(reactions)
            bundles[0].pop('bundle_sha256', None)
            bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
        if foe_attack:
            for label, economy in [('Enemy test strike', 'ACTION'), ('Enemy follow-up strike', 'BONUS_ACTION')]:
                source = 'action:test.' + label.lower().replace(' ', '_')
                bundles[2]['action_catalog'].append({'source_definition_id': source,
                    'display_name': label, 'owner_id': FOE, 'economy': economy,
                    'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60,
                    'parameters': {'typed': {'source': source, 'numbers': {'attack_bonus': 100}, 'effects': [
                        {'type': 'attack', 'attack_kind': 'unarmed', 'count': 1,
                         'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['bludgeoning']}]}],
                        'riders': [], 'duration': {'kind': 'instant'}}}})
                bundles[2]['actor_template']['action_ids'].append(source)
            bundles[2].pop('bundle_sha256', None)
            bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])
    # These deliberately injected free activations use the same explicit
    # primary-action contract as real plug-in action builders.
    for action in owner['action_catalog']:
        if action['economy'] == 'NONE' and action['source_definition_id'].startswith('action:test.'):
            action['parameters']['free_primary'] = True
    from combat.canonical import canonical_sha256
    owner.pop('bundle_sha256', None)
    owner['bundle_sha256'] = canonical_sha256(owner)
    return fixture(tmp_path, [], owner_bundle=owner, ask=ask or bool(extra_reaction), seed='A2GFOU1', ally_position={'x': 4, 'y': 7},
                   foe_position={'x': 8, 'y': 6} if extra_reaction else None,
                   bundle_transform=transform if extra_reaction or foe_attack else None)


def move(combat, table, mid, feet, mode=None):
    rows = [c for c in combat._load_session(mid).engine.legal_candidates()
            if c.kind.value == 'MOVE' and c.movement_cost_ft == feet
            and (mode is None or c.metadata.get('movement_mode', 'walk') == mode)]
    assert rows, feet
    settle(table, mid, rows[0].candidate_id)


@pytest.mark.parametrize('feet,expected', [(0, 0), (15, 0), (20, 1)])
def test_momentum_generation_requires_twenty_feet_and_a_resolved_hit(tmp_path, feet, expected):
    combat, table, mid = setup(tmp_path)
    if feet:
        move(combat, table, mid, feet)
    engine = reload(tmp_path, mid)
    pool = 'resource:foundation.dragon_wind_momentum'
    assert engine.state.actors[OWNER].resources[pool] == 0
    settle(table, mid, candidate(combat, mid, 'Settled hit', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool] == expected
    if expected:
        gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.actor_id == OWNER
                 and e.payload.get('resource_id') == pool]
        assert len(gains) == 1
        damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER)
        assert engine.events.index(gains[0]) > engine.events.index(damage)


def test_off_turn_willing_reaction_move_can_feed_the_later_resolved_hit(tmp_path):
    from combat import typed_reactions
    movement_row = {'feature_id': 'test:foundations1.offturn_step', 'name': 'Off-turn step',
        'block': 'generic', 'kind': 'attacked', 'free': True, 'range_ft': 60, 'costs': [],
        'effects': [{'type': 'reaction_move', 'direction': 'toward', 'distance_ft': 20}]}
    hit_row = {'feature_id': 'test:foundations1.offturn_counter', 'name': 'Off-turn counter',
        'block': 'generic', 'kind': 'attacked', 'ask': True, 'range_ft': 60, 'costs': [],
        'numbers': {'attack_bonus': 100}, 'effects': [
            {'type': 'attack', 'attack_kind': 'unarmed', 'count': 1,
             'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['bludgeoning']}]}]}
    original = typed_reactions._rows
    def rows(engine, actor_id, block):
        if actor_id == OWNER and block == 'generic':
            moved = any(e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == movement_row['feature_id']
                        for e in engine.events)
            return [hit_row if moved else movement_row] + original(engine, actor_id, block)
        return original(engine, actor_id, block)
    typed_reactions._rows = rows
    try:
        combat, table, mid = setup(tmp_path, extra_reaction=[movement_row, hit_row], foe_attack=True)
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Enemy test strike', target=OWNER).candidate_id)
        engine = reload(tmp_path, mid)
        movement = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED'
                    and e.actor_id == OWNER and e.source_definition_id == movement_row['feature_id']]
        assert movement and len(movement[-1].payload['path']) >= 5
        assert engine.state.actors[OWNER].turn_flags['foundations1_dragon_moved_ft'] == 20
        pool = 'resource:foundation.dragon_wind_momentum'
        assert engine.state.actors[OWNER].resources[pool] == 0
        settle(table, mid, candidate(combat, mid, 'Enemy follow-up strike', target=OWNER).candidate_id,
               picks={'reaction:typed.' + hit_row['feature_id']: 'first'})
        engine = reload(tmp_path, mid)
        assert engine.state.actors[OWNER].resources[pool] == 1
        gain = next(e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.actor_id == OWNER
                    and e.payload.get('resource_id') == pool)
        damage = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                      and e.source_definition_id == hit_row['feature_id'])
        assert engine.events.index(gain) > engine.events.index(damage)
        assert reload(tmp_path, mid).state.actors[OWNER].resources[pool] == 1
    finally:
        typed_reactions._rows = original


@pytest.mark.parametrize('marker', ['forced', 'dragged_by'])
def test_forced_and_dragged_path_receipts_do_not_generate_momentum(tmp_path, marker):
    from combat.ext.foundations1 import controlled_distance, DISTANCE
    combat, table, mid = setup(tmp_path)
    engine = reload(tmp_path, mid)
    path = [{'x': 3 + index, 'y': 6} for index in range(5)]
    payload = {'path': path}
    payload[marker] = True if marker == 'forced' else FOE
    controlled_distance(engine, 'MOVEMENT_COMMITTED', {'actor_id': OWNER, 'payload': payload})
    assert engine.state.actors[OWNER].turn_flags.get(DISTANCE, 0) == 0
    settle(table, mid, candidate(combat, mid, 'Settled hit', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources['resource:foundation.dragon_wind_momentum'] == 0


def test_wind_opened_body_returns_at_real_turn_after_walking_step(tmp_path):
    combat, table, mid = setup(tmp_path, held=1)
    assert reload(tmp_path, mid)._effective_speed(reload(tmp_path, mid).state.actors[OWNER]) == 40
    move(combat, table, mid, 40)
    settle(table, mid, candidate(combat, mid, 'Momentum Step').candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    # The walking option is automated: the speed reads higher and
    # the movement allowance gains the step's feet.
    assert engine._effective_speed(actor) == 50
    assert actor.movement_remaining_ft == 10
    assert actor.resources['resource:foundation.dragon_wind_momentum'] == 0
    assert 'ordinary_movement_remaining_ft' not in actor.turn_flags
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine._effective_speed(engine.state.actors[OWNER]) == 40
    assert engine.state.actors[OWNER].movement_remaining_ft == 40


@pytest.mark.parametrize('dash', [False, True])
@pytest.mark.parametrize('prone', [False, True])
@pytest.mark.parametrize('left', [0, 5])
def test_walking_step_credits_the_automated_boost(tmp_path, dash, prone, left):
    combat, table, mid = setup(tmp_path, held=1, prone_setup=prone, ask=True)
    if dash:
        settle(table, mid, next(c for c in combat._load_session(mid).engine.legal_candidates()
                               if 'Dash' in c.display_name).candidate_id)
    if prone:
        settle(table, mid, candidate(combat, mid, 'Test Lie Down').candidate_id)
        stand = next(c for c in combat._load_session(mid).engine.legal_candidates()
                     if c.source_definition_id == 'system:combat.stand_up')
        settle(table, mid, stand.candidate_id)
    move(combat, table, mid, (20 if prone else 40) - left, mode='walk')
    before = reload(tmp_path, mid).state.actors[OWNER]
    assert before.resources['resource:foundation.dragon_wind_momentum'] == 1
    remaining = (40 if dash else 0) + left
    assert before.movement_remaining_ft == remaining
    settle(table, mid, candidate(combat, mid, 'Momentum Step').candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    # The walking option is automated: the speed reads higher and the
    # allowance gains the step's feet (Dash doubles a movement grant).
    assert engine._effective_speed(actor) == 50
    assert actor.movement_remaining_ft == remaining + (20 if dash else 10)
    assert actor.position == before.position
    assert actor.resources['resource:foundation.dragon_wind_momentum'] == 0
    assert 'ordinary_movement_remaining_ft' not in actor.turn_flags
    assert 'ordinary_movement_shortfall_ft' not in actor.turn_flags
    assert not any('GM reminder' in str(e.payload) for e in engine.events)
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
             and e.actor_id == OWNER and e.payload.get('resource_id') == 'resource:foundation.dragon_wind_momentum']
    assert len(spent) == 1 and spent[0].payload['amount'] == 1


def test_momentum_step_credits_dash_doubled_boost_through_table_and_reload(tmp_path):
    combat, table, mid = setup(tmp_path, held=1)
    settle(table, mid, next(c for c in combat._load_session(mid).engine.legal_candidates()
                           if 'Dash' in c.display_name).candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].movement_remaining_ft == 80
    settle(table, mid, candidate(combat, mid, 'Momentum Step').candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].movement_remaining_ft == 100
    assert engine._effective_speed(engine.state.actors[OWNER]) == 50


def test_shared_pool_keeps_main_contract_after_speed_reduction(tmp_path):
    combat, table, mid = setup(tmp_path, speed_debuff=True)
    settle(table, mid, next(c for c in combat._load_session(mid).engine.legal_candidates()
                           if 'Dash' in c.display_name).candidate_id)
    move(combat, table, mid, 40)
    settle(table, mid, candidate(combat, mid, 'Test Speed Reduction').candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert engine._effective_speed(actor) == 30
    assert actor.movement_remaining_ft == 40
    assert 'ordinary_movement_remaining_ft' not in actor.turn_flags


@pytest.mark.parametrize('left', [0, 5])
def test_speed_reduction_does_not_rewrite_shared_flight_basis(tmp_path, left):
    from combat.flight import remaining
    combat, table, mid = setup(tmp_path, held=1, speed_debuff=True, flying=True)
    settle(table, mid, next(c for c in combat._load_session(mid).engine.legal_candidates()
                           if 'Dash' in c.display_name).candidate_id)
    move(combat, table, mid, 40 - left, mode='walk')
    engine = reload(tmp_path, mid)
    fly_before = remaining(engine, engine.state.actors[OWNER], 'fly')
    settle(table, mid, candidate(combat, mid, 'Test Speed Reduction').candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.movement_remaining_ft == 40 + left
    assert remaining(engine, actor, 'fly') == fly_before
    assert 'ordinary_movement_remaining_ft' not in actor.turn_flags


def test_walking_momentum_step_does_not_increase_flying_allowance(tmp_path):
    from combat.flight import remaining
    combat, table, mid = setup(tmp_path, held=1, flying=True)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert remaining(engine, actor, 'fly') == 30
    prompts = settle(table, mid, candidate(combat, mid, 'Momentum Step').candidate_id,
                     choices={'choice:needle.momentum_speed': 'walk'})
    assert prompts
    walk = next(o for o in prompts[0]['choice']['options'] if o['id'] == 'walk')
    assert 'GM reminder' not in str(walk)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    # The walking option is automated: only the walking speed
    # and its allowance change; the flying allowance is untouched.
    assert engine._effective_speed(actor) == 50
    assert remaining(engine, actor, 'fly') == 30


@pytest.mark.parametrize('stage,expected', [('Awakened', 6), ('Perfected', 10)])
def test_banked_coals_has_one_temporary_hp_offer_and_one_payment(tmp_path, stage, expected):
    combat, table, mid = setup(tmp_path, FURNACE, stage, held=1)
    settle(table, mid, candidate(combat, mid, 'Banked Coals').candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == expected
    assert engine.state.actors[OWNER].resources['resource:foundation.furnace_heat'] == 0
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER
             and e.payload.get('resource_id') == 'resource:foundation.furnace_heat']
    assert len(spent) == 1 and spent[0].payload['amount'] == 1
    assert not any(c.display_name == 'Banked Coals' for c in engine.legal_candidates())


def test_perfected_banked_coals_rider_caps_each_round_across_repeated_spends(tmp_path):
    combat, table, mid = setup(tmp_path, FURNACE, 'Perfected', held=1, refill=True)
    pool = 'resource:foundation.furnace_heat'
    offers = []
    settle(table, mid, candidate(combat, mid, 'Banked Coals').candidate_id)
    engine = reload(tmp_path, mid)
    offers.extend(int(e.payload['offered']) for e in engine.events if e.event_type == 'TEMP_HP_GRANTED'
                  and e.actor_id == OWNER)
    assert engine.state.actors[OWNER].resources[pool] == 0

    settle(table, mid, candidate(combat, mid, 'Test Furnace Heat Refill').candidate_id)
    reload(tmp_path, mid)
    settle(table, mid, candidate(combat, mid, 'Banked Coals').candidate_id)
    engine = reload(tmp_path, mid)
    offers = [int(e.payload['offered']) for e in engine.events if e.event_type == 'TEMP_HP_GRANTED'
              and e.actor_id == OWNER]
    assert offers == [10, 6]

    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Test Furnace Heat Refill').candidate_id)
    reload(tmp_path, mid)
    settle(table, mid, candidate(combat, mid, 'Banked Coals').candidate_id)
    engine = reload(tmp_path, mid)
    offers = [int(e.payload['offered']) for e in engine.events if e.event_type == 'TEMP_HP_GRANTED'
              and e.actor_id == OWNER]
    assert offers == [10, 6, 10]


def test_momentum_runs_out_at_end_of_next_owner_turn(tmp_path):
    combat, table, mid = setup(tmp_path)
    move(combat, table, mid, 20)
    settle(table, mid, candidate(combat, mid, 'Settled hit', target=FOE).candidate_id)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].resources['resource:foundation.dragon_wind_momentum'] == 1
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path, mid).state.actors[OWNER].resources['resource:foundation.dragon_wind_momentum'] == 0


def test_momentum_generation_round_cap_and_refresh_survive_cold_reload(tmp_path):
    combat, table, mid = setup(tmp_path, attacks=2)
    move(combat, table, mid, 20)
    settle(table, mid, candidate(combat, mid, 'Settled hit', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    pool = 'resource:foundation.dragon_wind_momentum'
    gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.actor_id == OWNER
             and e.payload.get('resource_id') == pool]
    assert len(gains) == 1

    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    move(combat, table, mid, 20)
    settle(table, mid, candidate(combat, mid, 'Settled hit', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool] == 1
    assert len([e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.actor_id == OWNER
                and e.payload.get('resource_id') == pool]) == 1

    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[pool] == 1
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path, mid).state.actors[OWNER].resources[pool] == 0


def test_repeated_native_teleports_do_not_generate_momentum(tmp_path):
    combat, table, mid = setup(tmp_path, blink=True)
    for _ in range(4):
        settle(table, mid, candidate(combat, mid, 'Fixture Blink').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Settled hit', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources['resource:foundation.dragon_wind_momentum'] == 0
    assert len([e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.payload.get('teleport')]) == 4


def test_momentum_step_player_chooses_existing_flying_speed(tmp_path):
    from combat import flight
    combat, table, mid = setup(tmp_path, held=1, flying=True)
    prompts = settle(table, mid, candidate(combat, mid, 'Momentum Step').candidate_id,
                     choices={'choice:needle.momentum_speed': 'fly'})
    assert prompts and {o['id'] for o in prompts[0]['choice']['options']} == {'walk', 'fly'}
    engine = reload(tmp_path, mid)
    assert engine._effective_speed(engine.state.actors[OWNER]) == 40
    assert flight.profile(engine, engine.state.actors[OWNER]).speed_ft == 40
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    assert flight.profile(engine, engine.state.actors[OWNER]).speed_ft == 30


def test_speed_bonus_does_not_grant_or_preserve_a_flight_mode():
    from combat import flight
    from types import SimpleNamespace
    from tests.h1_support import duel, ME
    engine = duel([])
    actor = engine.state.actors[ME]
    engine._apply_condition(actor, 'condition:test.fly_bonus', 'test:bonus', ME,
        expires_on='END_OF_CURRENT_TURN', data={'fly_speed_bonus_ft': 10})
    assert flight.profile(engine, actor).speed_ft == 0
    actor.fly_speed_ft = 30
    assert flight.profile(engine, actor).speed_ft == 40
    actor.fly_speed_ft = 0
    assert flight.profile(engine, actor).speed_ft == 0


@pytest.mark.parametrize('left', [0, 5])
@pytest.mark.parametrize('dash', [False, True])
def test_generic_speed_modifiers_leave_main_shared_pool_unchanged(tmp_path, left, dash):
    combat, table, mid = setup(tmp_path, held=1, speed_debuff=True, speed_restore=True)
    if dash:
        settle(table, mid, next(c for c in combat._load_session(mid).engine.legal_candidates()
                               if 'Dash' in c.display_name).candidate_id)
    move(combat, table, mid, 40 - left, mode='walk')
    expected = (40 if dash else 0) + left
    for name, speed in [('Test Speed Reduction', 30), ('Test Speed Restoration', 40)]:
        settle(table, mid, candidate(combat, mid, name).candidate_id)
        engine = reload(tmp_path, mid)
        actor = engine.state.actors[OWNER]
        assert engine._effective_speed(actor) == speed
        assert actor.movement_remaining_ft == expected
        assert 'ordinary_movement_remaining_ft' not in actor.turn_flags
        assert 'ordinary_movement_shortfall_ft' not in actor.turn_flags


@pytest.mark.parametrize('left', [0, 5])
@pytest.mark.parametrize('dash', [False, True])
def test_paid_standing_and_speed_changes_keep_main_shared_pool(tmp_path, left, dash):
    combat, table, mid = setup(tmp_path, held=1, prone_setup=True, speed_debuff=True, speed_restore=True)
    settle(table, mid, candidate(combat, mid, 'Test Lie Down').candidate_id)
    if dash:
        settle(table, mid, next(c for c in combat._load_session(mid).engine.legal_candidates()
                               if 'Dash' in c.display_name).candidate_id)
    stand = next(c for c in combat._load_session(mid).engine.legal_candidates()
                 if c.source_definition_id == 'system:combat.stand_up')
    settle(table, mid, stand.candidate_id)
    engine = reload(tmp_path, mid)
    assert next(e for e in reversed(engine.events) if e.event_type == 'STOOD_UP').payload['cost_ft'] == 20
    assert engine.state.actors[OWNER].movement_remaining_ft == (40 if dash else 0) + 20
    move(combat, table, mid, 20 - left, mode='walk')
    for name, speed in [('Test Speed Reduction', 30), ('Test Speed Restoration', 40)]:
        settle(table, mid, candidate(combat, mid, name).candidate_id)
        engine = reload(tmp_path, mid)
        actor = engine.state.actors[OWNER]
        assert engine._effective_speed(actor) == speed
        assert actor.movement_remaining_ft == (40 if dash else 0) + left
        assert 'ordinary_movement_remaining_ft' not in actor.turn_flags
        assert 'ordinary_movement_shortfall_ft' not in actor.turn_flags
