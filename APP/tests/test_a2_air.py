"""Air second pass: production table commits, cold reload and mechanical replay."""
import pytest

from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn

DOWNBURST = 'TAL_AIR_DOWNBURST_SEAL'
CYCLONE = 'TAL_AIR_CYCLONE_PRISON'


def prepare(bundles, hover=False, flying=False):
    for bundle, initiative in zip(bundles, (100, -100, 0)):
        bundle['actor_template']['initiative_bonus'] = initiative
        bundle['actor_template']['maximum_hp'] = 500
        seal(bundle)
    if flying:
        bundles[2]['actor_template']['fly_speed_ft'] = 60
        bundles[2]['actor_template']['hover'] = hover
        seal(bundles[2])


def prone(actor):
    return any(c.condition_id.endswith('.prone') for c in actor.conditions.values())


def area_candidate(combat, mid, name):
    engine = combat._load_session(mid).engine
    return next(c for c in engine.legal_candidates()
                if engine.action_catalog.get(c.source_definition_id)
                and engine.action_catalog[c.source_definition_id].display_name == name
                and c.destination and (c.destination.x, c.destination.y, c.destination.z) == (6, 6, 0))


@pytest.mark.parametrize('height,hover,dc,expected,knocked', [
    (0, False, 100, 0, True), (4, False, 100, 0, True),
    (8, False, 100, 8, False), (4, True, 100, 4, False),
    (4, False, -100, 4, False),
])
def test_downburst_resolves_landing_without_grounding_hover_or_success(tmp_path, height, hover, dc, expected, knocked):
    combat, table, mid = fixture(tmp_path, [DOWNBURST], owner_dc=dc,
        bundle_transform=lambda b: prepare(b, hover, bool(height)), positions={
            OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6},
            FOE: {'x': 6, 'y': 6, 'z': height}}, seed=f'A2-DOWN-{height}-{hover}-{dc}')
    # Native flight is sealed into the starting bundle, rather than mutating a live actor.
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].position.z == height
    cast = area_candidate(combat, mid, 'Downburst Seal')
    settle(table, mid, cast.candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].position.z == expected
    assert prone(engine.state.actors[FOE]) is knocked
    # The printed save explicitly targets creatures in the area, including allies.
    assert prone(engine.state.actors[ALLY]) is (dc == 100)
    assert not any(e.event_type == 'GM_ADJUDICATION_REQUIRED' and e.source_definition_id == cast.source_definition_id
                   for e in engine.events)


@pytest.mark.parametrize('dc,lift', [(100, True), (-100, False)])
def test_cyclone_lifts_and_releases_through_native_expiry(tmp_path, dc, lift):
    combat, table, mid = fixture(tmp_path, [CYCLONE], owner_dc=dc,
        bundle_transform=prepare, seed=f'A2-CYCLONE-{dc}')
    cast = candidate(combat, mid, 'Cyclone Prison', at=(6, 6))
    settle(table, mid, cast.candidate_id)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert foe.position.z == (2 if lift else 0)
    holds = [c for c in foe.conditions.values() if c.condition_id.endswith('.restrained')]
    assert bool(holds) is lift
    if lift:
        assert holds[0].data['flight_suspended'] == 1
        assert holds[0].data['repeat_save']['ability'] == 'STR'
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].position.z == 0
    assert not any(c.data.get('flight_suspended') for c in engine.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('cl,damage_type,penalty', [(10, 'slashing', False), (11, 'bludgeoning', False), (11, 'slashing', True)])
def test_cutting_wind_penalizes_only_the_next_concentration_save(tmp_path, cl, damage_type, penalty):
    def setup(bundles):
        prepare(bundles)
        bundles[2]['actor_template']['armor_class'] = 0
        bundles[2]['actor_template']['saving_throws']['CON'] = 100
        seal(bundles[2])
        for action in bundles[0]['action_catalog']:
            if action['display_name'].startswith('Wind Lash:'):
                action['parameters']['typed']['numbers']['attack_bonus'] = 100
                action['parameters']['typed']['effects'][0]['on_hit'][0]['damage_types'] = [damage_type]
        seal(bundles[0])
        add_action(bundles[2], 'Hold concentration', [], target='SELF',
                   typed={'duration': {'kind': 'minutes', 'amount': 1, 'concentration': True}})
        add_action(bundles[0], 'Test damage', [{'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'}])
    combat, table, mid = fixture(tmp_path, ['TAL_AIR_CUTTING_WIND'], cl=cl,
        bundle_transform=setup, seed=f'A2-CUT-{cl}-{damage_type}')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Hold concentration').candidate_id)
    turn(table, mid, OWNER)
    assert reload(tmp_path, mid).state.actors[FOE].concentration is not None
    settle(table, mid, candidate(combat, mid, 'Wind Lash: Cut', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    modes = [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id.endswith('.concentration_mode')]
    assert bool(modes) is penalty
    if penalty:
        assert modes[0].data['rule']['next'] is True
    settle(table, mid, candidate(combat, mid, 'Test damage', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].concentration is not None
    assert not any(c.condition_id.endswith('.concentration_mode') for c in engine.state.actors[FOE].conditions.values())
    settle(table, mid, candidate(combat, mid, 'Test damage', target=FOE).candidate_id)
    assert reload(tmp_path, mid).state.actors[FOE].concentration is not None


def test_explicit_cylinder_height_is_independent_of_radius_and_cache_key():
    from types import SimpleNamespace
    from combat.gate2_runtime_models import Position
    from combat.typed_executor import in_area
    from combat.area_projection import geometry_key
    engine = SimpleNamespace(grid=SimpleNamespace(square_size_ft=5, blocked=set()))
    aim = Position(x=3, y=3, z=2)
    short = {'shape': 'cylinder', 'size_ft': 10, 'height_ft': 30}
    tall = {**short, 'height_ft': 40}
    legacy = {'shape': 'cylinder', 'size_ft': 10}
    assert in_area(engine, aim, aim, Position(x=3, y=3, z=7), short)
    assert not in_area(engine, aim, aim, Position(x=3, y=3, z=8), short)
    assert in_area(engine, aim, aim, Position(x=3, y=3, z=8), tall)
    assert not in_area(engine, aim, aim, Position(x=3, y=3, z=1), tall)
    assert not in_area(engine, aim, aim, Position(x=6, y=3, z=2), tall)
    assert not in_area(engine, aim, aim, Position(x=3, y=3, z=7), legacy)
    assert geometry_key(short) != geometry_key(tall) != geometry_key(legacy)
