"""Sound BASE consumers through native table transactions and cold replay."""
import pytest

from combat.canonical import canonical_sha256
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn

DAMPEN = 'TAL_SOUND_DAMPEN_SOUND'


def checks(metadata, *, ability='WIS', skill='Perception', damage=None, area=None, flat=20):
    """Seal an ordinary scene check/delivery, then run the native menu and dice.

    No live transport, forced roll, helper invocation or direct state change.
    The source metadata is exactly what a contextual check caller supplies.
    """
    def transform(bundles):
        for bundle in bundles:
            source = 'action:test.sound_scene.' + ('damage.' if damage else 'check.') + bundle['actor_id'].rsplit('-', 1)[-1]
            effect = {'type': 'skill_check', 'ability': ability, 'skill': skill,
                      'metadata': metadata, 'dc': 15, 'applies_to': 'self'}
            if damage:
                effect = {'type': 'damage', 'damage_types': [damage], 'flat': flat,
                          'applies_to': 'creatures_in_area' if area else 'target'}
            typed = {'source': source, 'effects': [effect], 'numbers': {'pb': 4, 'key_mod': 2}}
            if area:
                # This synthetic delivery hurts every creature in its volume,
                # including allies. Geometry alone does not grant friendly fire.
                typed['area'] = {**area, 'explicit_harmful_recipients': 'every_creature'}
            row = {'source_definition_id': source, 'display_name': 'Scene check' if not damage else 'Thunder delivery',
                   'owner_id': bundle['actor_id'], 'economy': 'ACTION', 'resolution_kind': 'TYPED',
                   'target_kind': 'SELF' if not damage else ('CELL' if area else 'ANY_CREATURE'),
                   'range_ft': 60, 'costs': [], 'parameters': {'typed': typed}}
            bundle['action_catalog'].append(row)
            bundle['actor_template']['action_ids'].append(source)
            bundle['actor_template']['maximum_hp'] = 1000
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    return transform


def cast(combat, table, mid):
    e = combat._load_session(mid).engine
    before = e.state.actors[OWNER].resources['resource:core.qi']
    settle(table, mid, candidate(combat, mid, 'Dampen Sound', at=(3, 6)).candidate_id)
    assert combat._load_session(mid).engine.state.actors[OWNER].resources['resource:core.qi'] == before - 1


@pytest.mark.parametrize('senses,source,observer_at,expected', [
    (['hearing'], OWNER, (7, 6), 'DISADVANTAGE'),
    (['vision'], OWNER, (7, 6), 'NORMAL'),
    (['hearing', 'vision'], OWNER, (7, 6), 'NORMAL'),
    (['hearing'], FOE, (7, 6), 'NORMAL'),
    (['hearing'], OWNER, (2, 6), 'NORMAL'),
])
def test_dampen_exterior_hearing_requires_inside_source(tmp_path, senses, source, observer_at, expected):
    metadata = {'purpose': 'notice_sound', 'senses': senses, 'source_actor_id': source, 'observer_id': ALLY}
    combat, table, mid = fixture(tmp_path, [DAMPEN], ally_position={'x': observer_at[0], 'y': observer_at[1]},
                                 bundle_transform=checks(metadata), ask=False)
    cast(combat, table, mid)
    assert reload(tmp_path, mid).state.zones
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Scene check').candidate_id)
    events = [v for v in reload(tmp_path, mid).events if v.event_type == 'CHECK_ROLLED' and 'sound_scene' in v.source_definition_id]
    assert events[-1].payload['actor']['mode'] == expected
    assert events[-1].payload['check_metadata'] == metadata


@pytest.mark.parametrize('issues,inside,expected', [(['sound'], True, 'ADVANTAGE'),
    (['sound', 'sight'], True, 'NORMAL'), (['sight'], True, 'NORMAL'), (['sound'], False, 'NORMAL')])
def test_dampen_quiet_movement_is_not_broad_stealth(tmp_path, issues, inside, expected):
    metadata = {'purpose': 'quiet_movement', 'issues': issues, 'source_actor_id': ALLY}
    combat, table, mid = fixture(tmp_path, [DAMPEN], ally_position={'x': 2 if inside else 7, 'y': 6},
                                 bundle_transform=checks(metadata, ability='DEX', skill='Stealth'), ask=False)
    cast(combat, table, mid)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Scene check').candidate_id)
    events = [v for v in reload(tmp_path, mid).events if v.event_type == 'CHECK_ROLLED' and 'sound_scene' in v.source_definition_id]
    assert events[-1].payload['actor']['mode'] == expected


@pytest.mark.parametrize('source_at,target_at,kind,reduced', [
    ((2, 6), (3, 6), 'THUNDER', True), ((7, 6), (3, 6), 'THUNDER', False),
    ((2, 6), (6, 6), 'THUNDER', False), ((2, 6), (3, 6), 'FIRE', False),
    ((2, 6), (3, 6, 3), 'THUNDER', False),
])
def test_dampen_entire_source_recipient_thunder_geometry(tmp_path, source_at, target_at, kind, reduced):
    positions = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': source_at[0], 'y': source_at[1]},
                 FOE: {'x': target_at[0], 'y': target_at[1], 'z': target_at[2] if len(target_at) == 3 else 0}}
    # Keep hostile away from the caster for creation, except a recipient cell
    # coinciding with the owner is represented by the owner itself.
    target = OWNER if target_at == (3, 6) else FOE
    if target == OWNER:
        positions[FOE] = {'x': 8, 'y': 6}
    def setup(bundles):
        checks({}, damage=kind)(bundles)
        if len(target_at) == 3:
            bundles[2]['actor_template'].update(fly_speed_ft=30, hover=True)
            bundles[2].pop('bundle_sha256', None)
            bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])
    combat, table, mid = fixture(tmp_path, [DAMPEN], positions=positions, bundle_transform=setup, ask=False,
                                 owner_pb=6 if reduced else 4)
    cast(combat, table, mid)
    turn(table, mid, ALLY)
    before = reload(tmp_path, mid).state.actors[target].current_hp
    settle(table, mid, candidate(combat, mid, 'Thunder delivery', target=target).candidate_id)
    e = reload(tmp_path, mid)
    assert before - e.state.actors[target].current_hp == 20 - (e.state.actors[OWNER].proficiency_bonus if reduced else 0)


@pytest.mark.parametrize('area,reduced', [({'shape': 'cube', 'size_ft': 5}, True),
                                        ({'shape': 'cube', 'size_ft': 15}, False)])
def test_dampen_entire_area_not_just_recipient(tmp_path, area, reduced):
    combat, table, mid = fixture(tmp_path, [DAMPEN], bundle_transform=checks({}, damage='THUNDER', area=area), ask=False)
    cast(combat, table, mid)
    turn(table, mid, ALLY)
    before = reload(tmp_path, mid).state.actors[OWNER].current_hp
    settle(table, mid, candidate(combat, mid, 'Thunder delivery', at=(3, 6)).candidate_id)
    e = reload(tmp_path, mid)
    damage = [v for v in e.events if v.event_type == 'DAMAGE_COMMITTED'
              and v.actor_id == ALLY and OWNER in v.target_ids
              and 'sound_scene.damage' in v.source_definition_id]
    assert len(damage) == 1, 'The area must actually deliver its Thunder packet to the ally'
    assert damage[0].payload['hp_damage'] == (16 if reduced else 20)
    assert before - e.state.actors[OWNER].current_hp == 20 - (e.state.actors[OWNER].proficiency_bonus if reduced else 0)


def test_dampen_concentration_ends_all_check_consumers(tmp_path):
    metadata = {'purpose': 'notice_sound', 'senses': ['hearing'], 'source_actor_id': OWNER, 'observer_id': FOE}
    def setup(bundles):
        checks(metadata)(bundles)
        checks({}, damage='FIRE', flat=100)(bundles)
    combat, table, mid = fixture(tmp_path, [DAMPEN], bundle_transform=setup, ask=False)
    cast(combat, table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Thunder delivery', target=OWNER).candidate_id)
    e = reload(tmp_path, mid)
    assert any(v.event_type == 'CONCENTRATION_ENDED' for v in e.events)
    assert not any(zone.active for zone in e.state.zones.values())
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Scene check').candidate_id)
    events = [v for v in reload(tmp_path, mid).events if v.event_type == 'CHECK_ROLLED' and 'sound_scene' in v.source_definition_id]
    assert events[-1].payload['actor']['mode'] == 'NORMAL'


def test_dampen_one_minute_deadline_retires_zone_and_quiet_bonus(tmp_path):
    metadata = {'purpose': 'quiet_movement', 'issues': ['sound'], 'source_actor_id': ALLY}
    combat, table, mid = fixture(tmp_path, [DAMPEN], ally_position={'x': 2, 'y': 6},
        bundle_transform=checks(metadata, ability='DEX', skill='Stealth'), ask=False)
    cast(combat, table, mid)
    start = reload(tmp_path, mid).state.round_number
    for _ in range(36):
        if not any(z.active for z in combat._load_session(mid).engine.state.zones.values()):
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    e = reload(tmp_path, mid)
    assert not any(z.active for z in e.state.zones.values())
    assert start + 10 <= e.state.round_number <= start + 11
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Scene check').candidate_id)
    check = next(v for v in reversed(reload(tmp_path, mid).events) if v.event_type == 'CHECK_ROLLED' and 'sound_scene' in v.source_definition_id)
    assert check.payload['actor']['mode'] == 'NORMAL'


@pytest.mark.parametrize('size,caster_inside,reduced', [(5, True, True), (15, True, False), (5, False, True)])
def test_dampen_standing_thunder_uses_live_source_zone_geometry(tmp_path, size, caster_inside, reduced):
    def setup(bundles):
        for bundle in bundles:
            bundle['actor_template']['maximum_hp'] = 1000
        bundle = bundles[1]
        source = 'action:test.standing_thunder'
        bundle['action_catalog'].append({'source_definition_id': source, 'display_name': 'Standing Thunder field',
            'owner_id': ALLY, 'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'CELL',
            'range_ft': 60, 'costs': [], 'parameters': {'typed': {'source': source, 'numbers': {'pb': 4, 'key_mod': 2},
            'area': {'shape': 'cube', 'size_ft': size}, 'duration': {'kind': 'rounds', 'amount': 2},
            'zone_spec': {'shape': 'cube', 'size_ft': size, 'name': 'Standing Thunder field',
                'duration': {'kind': 'rounds', 'amount': 2},
                'triggers': [{'on': ['start'], 'who': 'hostile', 'effects': [
                    {'type': 'damage', 'applies_to': 'target', 'flat': 20, 'damage_types': ['thunder']}]}]},
            'effects': [{'type': 'zone', 'applies_to': 'creatures_in_area',
                'triggers': [{'on': ['start'], 'who': 'hostile', 'effects': [
                    {'type': 'damage', 'applies_to': 'target', 'flat': 20, 'damage_types': ['thunder']}]}]}]}}})
        bundle['actor_template']['action_ids'].append(source)
        for bundle in bundles:
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    combat, table, mid = fixture(tmp_path, [DAMPEN], positions={OWNER: {'x': 3, 'y': 6},
        ALLY: {'x': 2 if caster_inside else 7, 'y': 6}, FOE: {'x': 3, 'y': 5}},
        bundle_transform=setup, ask=False)
    cast(combat, table, mid)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Standing Thunder field', at=(3, 5)).candidate_id)
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    turn(table, mid, FOE)
    e = reload(tmp_path, mid)
    assert before - e.state.actors[FOE].current_hp == (16 if reduced else 20)
    assert any(v.event_type == 'PASSIVE_TRIGGERED' and v.payload.get('zone_id')
               and v.actor_id == ALLY for v in e.events)
