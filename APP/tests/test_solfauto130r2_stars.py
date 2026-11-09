"""AUTO130r2: execute the chosen attack through a committed, reloaded table."""
from types import SimpleNamespace
import hashlib

import pytest
from combat.ext import stars
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload
from tests.test_auto130_stars import BOLT, DRAWN, RANGE, PUSH, MELEE, marked, resolve


def yard(arena):
    arena.update(width_squares=50, height_squares=20, terrain_regions=[])


def variant(engine, suffix=None):
    return next(a for a in engine.action_catalog.values() if a.owner_id == LEFT
                and (a.parameters or {}).get('stars_drawn_range')
                and (suffix is None or suffix + '#drawn_range' in a.source_definition_id))


def rolls(engine, source):
    return [e for e in engine.events if e.event_type == 'ATTACK_ROLLED'
            and e.actor_id == LEFT and e.source_definition_id == source]


def test_reach_ten_melee_weapon_neither_extends_nor_spends_the_benefit(tmp_path):
    kit = {'items': [{'item_id': 'tianxia.mortal.weapon.jie_bian'}]}
    combat, table, mid = fight(tmp_path, [DRAWN], left_kit=kit,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 5, 'y': 6}})
    engine = reload(combat, mid)
    melee = [a for a in engine.action_catalog.values() if a.owner_id == LEFT
             and (a.parameters.get('typed') or {}).get('weapon')
             and (a.parameters['typed']).get('range_ft') is None and a.range_ft == 10]
    assert melee, 'fixture must compile a real reach-10 weapon'
    assert not [a for a in engine.action_catalog.values() if a.owner_id == LEFT
                and (a.parameters or {}).get('stars_drawn_range')]
    assert act(table, mid, RANGE)['status'] == 'COMMITTED'
    resolve(lambda answers: act(table, mid, melee[0].display_name, answers, target_id=RIGHT))
    assert any(c.condition_id == stars.DRAWN_RANGE for c in reload(combat, mid).state.actors[LEFT].conditions.values())


def test_marked_miss_cannot_push_on_a_later_melee_hit_after_reload(tmp_path):
    combat, table, mid = fight(tmp_path, [DRAWN, BOLT], prepare=[*marked(), MELEE], left_attack_bonus=-100,
        prepare_attack_bonus=100,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}})
    resolve(lambda answers: act(table, mid, 'Prepare', answers, target_id=RIGHT))
    assert act(table, mid, PUSH)['status'] == 'COMMITTED'
    resolve(lambda answers: act(table, mid, 'Starbolt', answers, target_id=RIGHT))
    engine = reload(combat, mid)
    bolt = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.source_definition_id.endswith(BOLT))
    assert rolls(engine, bolt.source_definition_id) and not rolls(engine, bolt.source_definition_id)[-1].payload['provisional_hit']
    assert not engine.state.actors[LEFT].turn_flags.get('stars_drawn_push_armed')
    before = engine.state.actors[RIGHT].position
    melee = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.display_name == 'Prepare')
    resolve(lambda answers: act(table, mid, melee.display_name, answers, target_id=RIGHT))
    engine = reload(combat, mid)
    assert rolls(engine, melee.source_definition_id)[-1].payload['provisional_hit']
    assert engine.state.actors[RIGHT].position == before


def test_thrown_variant_executes_beyond_ordinary_long_range(tmp_path):
    combat, table, mid = fight(tmp_path, [DRAWN], arena_edit=yard,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 20, 'y': 6}})
    assert act(table, mid, RANGE)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    thrown = variant(engine, '#thrown')
    original = engine.action_catalog[thrown.source_definition_id.removesuffix('#drawn_range')]
    assert original.range_ft < engine.grid.distance_ft(engine.state.actors[LEFT].position, engine.state.actors[RIGHT].position)
    assert thrown.parameters['typed']['range_ft'] == original.parameters['typed']['range_ft'] + 60
    assert thrown.parameters['typed']['long_range_ft'] == original.parameters['typed']['long_range_ft'] + 60
    resolve(lambda answers: act(table, mid, thrown.display_name, answers, target_id=RIGHT))
    engine = reload(combat, mid)
    assert len(rolls(engine, thrown.source_definition_id)) == 1
    assert not any(c.condition_id == stars.DRAWN_RANGE for c in engine.state.actors[LEFT].conditions.values())


def repeated_bolt(bundle):
    """A synthetic multi-strike row, compiled by the same plug-in as a real weapon."""
    if bundle['actor_template']['entity_id'] != LEFT:
        return
    bolt = next(a for a in bundle['action_catalog'] if a['source_definition_id'].endswith(BOLT))
    # Existing compilation has made the clone; give both the same two-strike sequence.
    for a in bundle['action_catalog']:
        if BOLT in a['source_definition_id']:
            for eff in a['parameters']['typed']['effects']:
                if eff.get('type') == 'attack':
                    eff['count'] = 2


def test_only_first_strike_uses_extended_range(tmp_path):
    combat, table, mid = fight(tmp_path, [DRAWN, BOLT], arena_edit=yard, bundle_edit=repeated_bolt,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 30, 'y': 6}})
    assert act(table, mid, RANGE)['status'] == 'COMMITTED'
    extended = variant(reload(combat, mid), BOLT)
    resolve(lambda answers: act(table, mid, extended.display_name, answers, target_id=RIGHT))
    engine = reload(combat, mid)
    assert len(rolls(engine, extended.source_definition_id)) == 1
    assert not any(c.condition_id == stars.DRAWN_RANGE for c in engine.state.actors[LEFT].conditions.values())


def test_multistrike_keeps_later_strikes_within_ordinary_range(tmp_path):
    combat, table, mid = fight(tmp_path, [DRAWN, BOLT], arena_edit=yard, bundle_edit=repeated_bolt,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 8, 'y': 6}})
    assert act(table, mid, RANGE)['status'] == 'COMMITTED'
    extended = variant(reload(combat, mid), BOLT)
    resolve(lambda answers: act(table, mid, extended.display_name, answers, target_id=RIGHT))
    assert len(rolls(reload(combat, mid), extended.source_definition_id)) == 2


def test_pending_push_is_scoped_across_nested_attacks_and_cancellation():
    actor = SimpleNamespace(conditions={'state': SimpleNamespace(condition_id=stars.DRAWN_PUSH)}, turn_flags={})
    ctx = SimpleNamespace(actor=actor, typed={'range_ft': 60}, damage_cache={},
                          action=SimpleNamespace(parameters={}))
    receipt = ('attack:outer', RIGHT, DRAWN)
    with stars.drawn_attack_scope(ctx, {'type': 'attack'}):
        ctx.damage_cache[stars._DRAWN_RECEIPT] = receipt
        with pytest.raises(RuntimeError, match='cancelled'):
            with stars.drawn_attack_scope(ctx, {'type': 'attack'}):
                assert stars._DRAWN_RECEIPT not in ctx.damage_cache
                ctx.damage_cache[stars._DRAWN_RECEIPT] = ('attack:nested', RIGHT, DRAWN)
                raise RuntimeError('cancelled')
        assert ctx.damage_cache[stars._DRAWN_RECEIPT] == receipt
    assert stars._DRAWN_RECEIPT not in ctx.damage_cache


def test_range_clone_keeps_the_original_action_condition():
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    action = ActionDefinition(source_definition_id='action:test.thrown', display_name='Thrown weapon', owner_id=LEFT,
        economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='HOSTILE_ENTITY', range_ft=60,
        parameters={'requires_condition': 'condition:test.held', 'typed': {'range_ft': 20, 'long_range_ft': 60,
                    'effects': [{'type': 'attack', 'attack_kind': 'weapon'}]}})
    clone = stars.drawn_range({'owned_ids': [DRAWN], 'actions': [action]})[0]
    actor = SimpleNamespace(conditions={'range': SimpleNamespace(condition_id=stars.DRAWN_RANGE)})
    engine = SimpleNamespace(_has_condition=lambda actor, condition: condition in actor.conditions)
    assert stars.drawn_range_allowed(engine, actor, None, clone) is False
    actor.conditions['condition:test.held'] = SimpleNamespace(condition_id='condition:test.held')
    assert stars.drawn_range_allowed(engine, actor, None, clone) is True


def test_current_repair_retains_the_verified_unowned_ai_trace(tmp_path):
    """Same eight-step event/roll stream verified on 2daa09c0 before this repair.

    This is current-range evidence, separate from CW1r2's historical capture.
    It is a bounded unowned replay, not coverage of every owned-Stars AI fight.
    """
    from combat.canonical import canonical_bytes
    from tests.test_hunt24_replay import capture
    steps, events = capture(tmp_path)
    assert steps == 8
    # The owner removed concealment miss chances. New fights record that
    # policy in genesis; prove it is the ONLY addition to the pinned stream.
    import copy
    historical = copy.deepcopy(events)
    genesis, = [e for e in historical if e['event_type'] == 'MATCH_CREATED']
    assert genesis['payload'].pop('targeting_policy') == {
        'concealment_miss_percent': 0, 'total_concealment_miss_percent': 0}
    assert hashlib.sha256(canonical_bytes(historical)).hexdigest() == '659e837747c4f8db852c00d060fb4f73a8891e7f644343d7f9ee6e15583b544e'
