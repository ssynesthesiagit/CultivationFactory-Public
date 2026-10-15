"""Foundation review edge cases through table commits and cold replay."""
import pytest

from combat.canonical import canonical_sha256
from combat.typed_numbers import authority_mechanics
from tests.test_a2_foundations_two import table_fixture, use, pressure_action, f
from tests.worker2_support import OWNER, ALLY, FOE, turn, reload


@pytest.mark.parametrize('group,leaf,key,ability,hazard', [
    ('devour', 'shedding_husk_surge', 'husk_surge', 'WIS', 'drain'),
    ('origin', 'origin_bell_surge', 'origin_surge', 'STR', 'formation_pressure')])
def test_allied_tagged_check_preserves_surge_for_hostile_check(
        tmp_path, group, leaf, key, ability, hazard):
    def probe(bundles):
        # Isolate the paid Surge so the passive Frame cannot mask consumption.
        bundles[0]['typed_passives'] = [r for r in bundles[0]['typed_passives']
                                       if r.get('block') != f.BLOCK]
        source = 'action:test.foundation_resistance'
        bundles[0]['action_catalog'].append({
            'source_definition_id': source, 'display_name': 'Resistance check',
            'owner_id': OWNER, 'economy': 'NONE', 'resolution_kind': 'TYPED',
            'target_kind': 'ANY_CREATURE', 'range_ft': 60, 'costs': [],
            'parameters': {'free_primary': True, 'typed': {
                'source': source, 'effects': [{
                    'type': 'contest_against',
                    'actor_check': {'ability': ability, 'hazards': [hazard]},
                    'target_check': {'ability': 'STR'},
                    'on_success': [], 'on_fail': []}]}}})
        bundles[0]['actor_template']['action_ids'].append(source)
        for b in bundles:
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = table_fixture(tmp_path, group, transform=probe)
    use(combat, table, mid, authority_mechanics()[f.feature(group, leaf)]['name'])
    assert f.held(reload(tmp_path, mid).state.actors[OWNER], key)
    for target, expected, remains in [(ALLY, 'NORMAL', True),
                                      (FOE, 'ADVANTAGE', False),
                                      (FOE, 'NORMAL', False)]:
        use(combat, table, mid, 'Resistance check', target)
        engine = reload(tmp_path, mid)
        event = next(e for e in reversed(engine.events) if e.event_type == 'CHECK_ROLLED')
        assert event.payload['actor']['mode'] == expected
        assert bool(f.held(engine.state.actors[OWNER], key)) is remains


@pytest.mark.parametrize('kind,tags,expected', [
    ('cultivation', ['ongoing_technique', 'formation_pressure'], 'ADVANTAGE'),
    ('check', ['ongoing_technique', 'formation_pressure'], 'NORMAL'),
    ('cultivation', ['ongoing_technique', 'ordinary_damage'], 'NORMAL')])
def test_kind_only_cultivation_maintenance_advantage_reload(tmp_path, kind, tags, expected):
    def pressure(bundles):
        pressure_action(bundles, 'wis', 'concentration')
        bundles[2]['action_catalog'][-1]['parameters']['typed']['effects'] = [{
            'type': 'contest_against', 'actor_check': {'ability': 'STR'},
            # Canonical typed Cultivation specs need no redundant skill label.
            'target_check': {'kind': kind, 'ability': 'WIS', 'hazards': tags},
            'on_success': [], 'on_fail': []}]
        for b in bundles:
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = table_fixture(tmp_path, 'origin', current=0,
                                       stage='Refined', transform=pressure)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile pressure', OWNER)
    engine = reload(tmp_path, mid)
    event = next(e for e in reversed(engine.events) if e.event_type == 'CHECK_ROLLED')
    assert event.payload['target']['mode'] == expected
