"""Recorded minor Returns commit and replay; fixture ignition uses native events."""
from copy import deepcopy
import pytest
from combat.ext import effect
from combat.canonical import canonical_sha256
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_hunt27_table import commit

COURT = 'TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'
STREAMS = 'TAL_WATER_TEN_THOUSAND_RETURNING_STREAMS'
RETURN_NAME = 'Return the Flow: Soak a Creature + Ten Thousand Returning Streams (free)'
CONCENTRATION_RESOURCE = 'combat/rules/concentration.json'


@effect('test_mgr_t15_ignite', harmful=False)
def ignite_fixture(ctx, eff):
    """Only arrange recorded ordinary ignition; production Return resolves removal."""
    from combat.ext.objects import ignite
    for obj in ctx.engine.state.objects.values():
        if obj.object_id in {'object:map.81', 'object:map.82'}:
            ignite(ctx.engine, obj.object_id, ctx.source, ctx.actor.entity_id)
    if eff.get('burn_ally'):
        ctx.engine._apply_condition(ctx.engine.state.actors[ALLY], 'condition:typed.burning',
                                    ctx.source, ctx.actor.entity_id, expires_on='UNTIL_REMOVED')
    if eff.get('blind'):
        from combat.typed_executor import run_effects
        run_effects(ctx, [{'type': 'condition', 'condition': 'blinded', 'applies_to': 'self', 'duration': 'one_minute'}])


def setup_bundle(operation, blind=False):
    def prepare(bundles):
        owner = next(b for b in bundles if b['actor_id'] == OWNER)
        base = deepcopy(next(a for a in owner['action_catalog']
                             if a.get('parameters', {}).get('typed', {}).get('source') == 'WATER_BASE_WATER_LASH'))
        base.update(source_definition_id='action:test.mgr_t15_ignite', display_name='Fixture ordinary ignition',
                    economy='NONE', target_kind='SELF', costs=[])
        base['parameters']['free_primary'] = True
        base['parameters']['typed'].update(source='test_mgr_t15_ignite', effects=[
            {'type': 'test_mgr_t15_ignite', 'burn_ally': operation == 'creature_flame', 'blind': blind}])
        owner['action_catalog'].append(base)
        owner['actor_template']['action_ids'].append(base['source_definition_id'])
        for action in owner['action_catalog']:
            for row in action.get('parameters', {}).get('typed', {}).get('effects', []):
                if row.get('type') == 'water_returning_streams_minor':
                    # Scenario chooses this legal operation automatically, while
                    # using production recipient choices/resolution and replay.
                    row['preferred'] = 'flame' if operation == 'creature_flame' else operation
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)
    return prepare


def map_scene(arena):
    arena['map_objects'] = [
        {'id': 81, 'kind': 'crate', 'x': 3, 'y': 7},
        {'id': 82, 'kind': 'crate', 'x': 4, 'y': 7}]
    arena['map_terrain'] = [
        {'terrain': 'Water Source', 'cells': [[2, 6]]},
        {'terrain': 'Water Source', 'cells': [[1, 6]]}]


@pytest.mark.parametrize('operation', ['flame', 'source', 'creature_flame'])
@pytest.mark.parametrize('manual', [True, False], ids=['player', 'ai'])
def test_streams_recorded_minor_return_cold_reload(tmp_path, operation, manual):
    combat, table, mid = fixture(tmp_path, [COURT, STREAMS], bundle_transform=setup_bundle(operation),
                                 battlefield_transform=map_scene)
    settle(table, mid, candidate(combat, mid, 'Fixture ordinary ignition').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Shape Current: Mist Basin', at=(3, 6)).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Court of the Endless Tide').candidate_id)
    engine = reload(tmp_path, mid)
    basin = next(z for z in engine.state.zones.values() if z.active and z.owner_id == OWNER
                 and z.trigger_profile.get('name') == 'Shape Current')
    assert all(engine.state.objects[k].ignited for k in ('object:map.81', 'object:map.82'))
    if not manual:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    before = len(engine.events)

    def choose(prompt):
        kind = prompt['context']['reaction_source_id']
        if kind.endswith('returning_streams_select'):
            return [basin.zone_id]
        if kind.endswith('returning_streams_operation'):
            return ['flame' if operation == 'creature_flame' else operation]
        if kind.endswith('returning_streams_flame'):
            return [ALLY if operation == 'creature_flame' else 'object:map.81']
        return [prompt['choice']['options'][0]['id']]

    commit(combat, table, mid, tmp_path, candidate(combat, mid, RETURN_NAME).candidate_id, choose=choose)
    engine = reload(tmp_path, mid)
    assert not engine.state.zones[basin.zone_id].active
    events = engine.events[before:]
    if operation == 'flame':
        assert sum(not engine.state.objects[k].ignited for k in ('object:map.81', 'object:map.82')) == 1
        assert any(e.event_type == 'OBJECT_UPDATED' and not e.payload['object']['ignited'] for e in events)
    elif operation == 'source':
        source = next(e for e in events if 'water_source' in e.payload)
        assert source.payload['water_source'] == {'x': 2, 'y': 6, 'z': 0}
        assert all(engine.state.objects[k].ignited for k in ('object:map.81', 'object:map.82'))
    else:
        assert not any(c.condition_id == 'condition:typed.burning' for c in engine.state.actors[ALLY].conditions.values())
        assert all(engine.state.objects[k].ignited for k in ('object:map.81', 'object:map.82'))
    # The compiler may still report the separate two-ended-effects healing
    # precondition. This row must eliminate only its obsolete flame/source rider.
    assert not any(e.event_type == 'GM_RIDER' and
                   ('ordinary flame' in e.payload.get('rider', '') or 'Water Source' in e.payload.get('rider', ''))
                   for e in events)


def test_minor_return_does_not_reveal_unperceived_map_water(tmp_path):
    combat, table, mid = fixture(tmp_path, [COURT, STREAMS], bundle_transform=setup_bundle('source', blind=True),
                                 battlefield_transform=map_scene)
    settle(table, mid, candidate(combat, mid, 'Shape Current: Mist Basin', at=(3, 6)).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Court of the Endless Tide').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Fixture ordinary ignition').candidate_id)
    engine = reload(tmp_path, mid)
    start = len(engine.events)
    basin = next(z for z in engine.state.zones.values() if z.active and z.owner_id == OWNER
                 and z.trigger_profile.get('name') == 'Shape Current')
    settle(table, mid, candidate(combat, mid, RETURN_NAME).candidate_id, {
        'choice:needle.returning_streams_select': [basin.zone_id],
        'choice:needle.returning_streams_operation': 'source'})
    engine = reload(tmp_path, mid)
    assert not any('water_source' in e.payload for e in engine.events[start:])
