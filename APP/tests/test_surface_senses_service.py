"""Owned source grants on real table actions, represented contacts and cold reloads."""
import pytest

from combat import senses
from combat.gate2_runtime_models import Position
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn

AVATAR = 'tianxia.subpath.body.yamabushi.feature.avatar_of_the_mountain'
DRUM = 'tianxia.subpath.body.heaven_thunder_drum_body.feature.heaven_drum_circulation'


def press(combat, table, mid, name, target=None):
    settle(table, mid, candidate(combat, mid, name, target=target).candidate_id)


def contact(material='stone', **extra):
    return {'material': material, 'stable': False, 'touching': True, **extra}


def setup(bundles, owner_rule=None, target_rule=None, independent=False, flying=False):
    for bundle, initiative in zip(bundles, (100, 0, -100)):
        bundle['actor_template']['initiative_bonus'] = initiative
        if flying:
            bundle['actor_template']['fly_speed_ft'] = 30
        seal(bundle)
    for name, rule, target in [('Source contact', owner_rule, 'SELF'),
                               ('Target contact', target_rule, 'ANY_CREATURE')]:
        if rule is not None:
            add_action(bundles[0], name, [{'type': 'condition', 'condition': name.lower().replace(' ', '_'),
                'applies_to': 'self' if target == 'SELF' else 'target',
                'condition_data': {'rule': rule}, 'duration': {'kind': 'minutes', 'amount': 1}}], target=target)
    if independent:
        # Another real native sense activation; no invented owner passive grant.
        add_action(bundles[0], 'Independent sense', [{'type': 'gain_sense', 'sense': 'tremorsense', 'range_ft': 10}],
                   target='SELF', typed={'duration': {'kind': 'minutes', 'amount': 2}})


def make(tmp_path, feature, *, owner_rule=None, target_rule=None, independent=False,
         flying=False, owns=True, altitude=0, target_altitude=None, battlefield_transform=None):
    combat, table, mid = fixture(tmp_path, [], cl=18, primary='Stamina', owner_path='Body Refining',
        owner_features=[feature] if owns else [], seed='SURFACE-SENSES',
        positions={OWNER: {'x': 3, 'y': 8, 'z': altitude}, ALLY: {'x': 3, 'y': 3},
                   FOE: {'x': 6, 'y': 8, 'z': altitude if target_altitude is None else target_altitude}},
        bundle_transform=lambda bs: setup(bs, owner_rule, target_rule, independent, flying),
        battlefield_transform=battlefield_transform)
    if owner_rule is not None:
        press(combat, table, mid, 'Source contact')
    if target_rule is not None:
        press(combat, table, mid, 'Target contact', FOE)
    if independent:
        press(combat, table, mid, 'Independent sense')
    if feature == AVATAR and owns:
        before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.stamina']
        press(combat, table, mid, 'Avatar of the Mountain')
        e = reload(tmp_path, mid)
        assert e.state.actors[OWNER].resources['resource:core.stamina'] == before - 6
        state = next(c for c in e.state.actors[OWNER].conditions.values()
                     if c.condition_id == 'condition:typed.state.avatar_of_the_mountain')
        assert e.action_catalog[state.source_definition_id].parameters['typed']['source'] == AVATAR
        assert any(c.condition_id == senses.SENSE and c.data['source'] == state.source_definition_id
                   for c in e.state.actors[OWNER].conditions.values())
    return combat, table, mid


@pytest.mark.parametrize('target_rule,target_altitude', [
    (None, 2),
    ({'no_physical_contact': True}, 0),
    ({'incorporeal': True}, 0),
])
def test_drum_real_compiled_source_excludes_unconnected_target(tmp_path, target_rule, target_altitude):
    _, _, mid = make(tmp_path, DRUM, target_rule=target_rule, flying=True, target_altitude=target_altitude)
    e = reload(tmp_path, mid)
    bundle = next(b for b in e.typed_bundle_documents if b['actor_id'] == OWNER)
    assert any(r['feature_id'] == DRUM and r['range_ft'] == 30 for r in bundle['senses']['rows'])
    assert any(r.get('feature_id') == DRUM for r in e.typed_passive_rows[OWNER])
    owner, foe = e.state.actors[OWNER], e.state.actors[FOE]
    assert owner.position.z == 0 and foe.position.z == target_altitude
    assert senses.of(e, owner)['tremorsense']['range_ft'] == 30
    assert senses.reach(e, owner, 'tremorsense', foe) == 0
    assert not senses.pinpoints(e, owner, foe)


@pytest.mark.parametrize('rule,altitude,flying,feet', [
    (None, 0, False, 30),
    (None, 2, True, 0),
    ({'surface_contact': contact('wood')}, 2, True, 30),
    ({'surface_contact': contact('water')}, 0, False, 0),
    ({'surface_contact': contact(touching=False)}, 0, False, 0),
    ({'surface_contact': contact(), 'no_physical_contact': True}, 0, False, 0),
    ({'surface_contact': contact(), 'incorporeal': True}, 0, False, 0),
    ({'surface_contact': contact('unknown', solid=True)}, 2, True, 30),
    ({'surface_contact': contact(solid=False)}, 0, False, 0),
])
def test_avatar_live_solid_contact_creature_and_cell_reload(tmp_path, rule, altitude, flying, feet):
    _, _, mid = make(tmp_path, AVATAR, owner_rule=rule, altitude=altitude, flying=flying)
    e = reload(tmp_path, mid)
    owner, foe = e.state.actors[OWNER], e.state.actors[FOE]
    assert senses.of(e, owner).get('tremorsense', {}).get('range_ft', 0) == feet
    assert senses.reach(e, owner, 'tremorsense', foe) == feet
    assert senses.reach(e, owner, 'tremorsense', senses.cell_probe(foe.position)) == feet
    assert senses.pinpoints(e, owner, foe) is bool(feet)
    assert not any(x.event_type == 'GM_RIDER' and AVATAR in x.source_definition_id for x in e.events)


@pytest.mark.parametrize('source,target,altitude,flying,feet', [
    (None, None, 0, False, 30),
    (None, None, 2, True, 0),
    (contact(surface_id='bridge-west'), contact(surface_id='bridge-east'), 0, False, 0),
    (contact('wood', surface_id='bridge'), contact('metal', surface_id='bridge'), 2, True, 30),
    (contact(surface_id='bridge'), contact(touching=False, surface_id='bridge'), 0, False, 0),
    (contact('water', surface_id='bridge'), contact(surface_id='bridge'), 0, False, 0),
    (contact(), contact(), 2, True, 0),
])
def test_drum_owned_connected_source_target_reload(tmp_path, source, target, altitude, flying, feet):
    _, _, mid = make(tmp_path, DRUM,
        owner_rule={'surface_contact': source} if source else None,
        target_rule={'surface_contact': target} if target else None,
        altitude=altitude, flying=flying)
    e = reload(tmp_path, mid)
    owner, foe = e.state.actors[OWNER], e.state.actors[FOE]
    assert senses.reach(e, owner, 'tremorsense', foe) == feet
    assert senses.pinpoints(e, owner, foe) is bool(feet)
    # Untagged supported cell belongs to the floor; a tagged bridge is not
    # inferred from the projected coordinate of an empty square.
    cell_feet = 30 if source is None and altitude == 0 else 0
    assert senses.reach(e, owner, 'tremorsense', senses.cell_probe(foe.position)) == cell_feet
    assert not any(x.event_type == 'GM_RIDER' and DRUM in x.source_definition_id for x in e.events)


@pytest.mark.parametrize('joined', [False, True])
def test_drum_native_finite_platform_connection_reload(tmp_path, joined):
    def arena(data):
        data['terrain_regions'] = [{'region_id': 'surface-test', 'terrain_type': 'BLOCKED',
            'movement_cost': 0, 'height_ft': 10,
            'cells': [{'x': x, 'y': 8} for x in (range(3, 7) if joined else (3, 6))]}]
    _, _, mid = make(tmp_path, DRUM, altitude=2, battlefield_transform=arena)
    e = reload(tmp_path, mid)
    from combat.falling import supported
    owner, foe = e.state.actors[OWNER], e.state.actors[FOE]
    assert supported(e, owner) and supported(e, foe)
    assert senses.reach(e, owner, 'tremorsense', foe) == (30 if joined else 0)
    assert senses.reach(e, owner, 'tremorsense', senses.cell_probe(foe.position)) == (30 if joined else 0)


@pytest.mark.parametrize('geometry,feet', [
    ('continuous', 30),
    ('separate', 0),
    ('open-trapdoor', 0),
    ('closed-skylight', 30),
    ('split-footprint', 0),
    ('around-opening', 30),
])
def test_drum_native_roof_connection_commit_reload(tmp_path, geometry, feet):
    def arena(data):
        data['terrain_regions'] = []  # Native roofs are not BLOCKED columns.
        cells = [{'x': x, 'y': 8} for x in range(3, 7)]
        roof = {'id': 'native-roof', 'height_ft': 10, 'cells': cells}
        data['roof_surfaces'] = [roof]
        if geometry == 'separate':
            # Even adjacent but independently authored roofs stay separate.
            roof['cells'] = cells[:2]
            data['roof_surfaces'].append({'id': 'other-roof', 'height_ft': 10, 'cells': cells[2:]})
        elif geometry == 'split-footprint':
            roof['cells'] = [cells[0], cells[-1]]
        elif geometry in ('open-trapdoor', 'closed-skylight', 'around-opening'):
            roof['openings'] = [{'x': 4, 'y': 8,
                'kind': 'skylight' if geometry == 'closed-skylight' else 'trapdoor',
                'open': geometry != 'closed-skylight'}]
            if geometry == 'around-opening':
                roof['cells'] += [{'x': x, 'y': 7} for x in range(3, 7)]
    combat, table, mid = make(tmp_path, DRUM, altitude=2, battlefield_transform=arena)
    from combat.falling import supported
    # Assert native compiled ownership before and after a table commit/cold load.
    for cold in (False, True):
        if cold:
            turn(table, mid, FOE)
            turn(table, mid, OWNER)
        e = reload(tmp_path, mid) if cold else combat._load_session(mid).engine
        owner, foe = e.state.actors[OWNER], e.state.actors[FOE]
        assert owner.position.z == foe.position.z == 2
        assert supported(e, owner) and supported(e, foe)
        assert not e.grid.terrain_at((3, 8, 1), 'BLOCKED')
        assert senses.of(e, owner)['tremorsense']['range_ft'] == 30
        assert senses.reach(e, owner, 'tremorsense', foe) == feet
        assert senses.pinpoints(e, owner, foe) is bool(feet)
        assert senses.reach(e, owner, 'tremorsense', senses.cell_probe(foe.position)) == feet


@pytest.mark.parametrize('feature', [AVATAR, DRUM])
@pytest.mark.parametrize('owns', [False, True])
def test_surface_restrictions_preserve_independent_native_sense_and_nonowner(tmp_path, feature, owns):
    _, _, mid = make(tmp_path, feature, owns=owns, independent=True,
        owner_rule={'surface_contact': contact(touching=False)})
    e = reload(tmp_path, mid)
    owner, foe = e.state.actors[OWNER], e.state.actors[FOE]
    assert senses.of(e, owner)['tremorsense']['range_ft'] == 10
    assert senses.reach(e, owner, 'tremorsense', foe) == 10
    assert not senses.pinpoints(e, owner, foe)  # 15 feet away: independent range is only 10.
    assert senses.pinpoints(e, owner, senses.cell_probe(Position(x=4, y=8)))


def test_avatar_expires_through_native_turns_independent_source_survives(tmp_path):
    _, table, mid = make(tmp_path, AVATAR, independent=True)
    e = reload(tmp_path, mid)
    assert senses.of(e, e.state.actors[OWNER])['tremorsense']['range_ft'] == 30
    for _ in range(10):
        turn(table, mid, FOE)
        turn(table, mid, OWNER)
    e = reload(tmp_path, mid)
    assert not any(c.condition_id == 'condition:typed.state.avatar_of_the_mountain'
                   for c in e.state.actors[OWNER].conditions.values())
    assert not any(c.condition_id == senses.SENSE and str(c.data.get('source') or '').endswith(AVATAR)
                   for c in e.state.actors[OWNER].conditions.values())
    assert senses.of(e, e.state.actors[OWNER])['tremorsense']['range_ft'] == 10


@pytest.mark.parametrize('surface,owns,ac', [
    ({'material': 'stone', 'stable': True, 'touching': True}, True, 15),
    ({'material': 'wood', 'stable': True, 'touching': True}, True, 14),
    ({'material': 'stone', 'stable': False, 'touching': True}, True, 14),
    ({'material': 'stone', 'stable': True, 'touching': True}, False, 14),
])
def test_mountain_core_contact_defaults_on_native_attack_reload(tmp_path, surface, owns, ac):
    from tests.worker2_support import sealed_native_attack
    earth = 'tianxia.subpath.qi.mountain_core_cultivator.feature.earth_resilience'
    def prepare(bundles):
        setup(bundles, {'surface_contact': surface})
        sealed_native_attack(bundles[2], 'Surface attack', damage_type='BLUDGEONING', attack_bonus=20)
    combat, table, mid = fixture(tmp_path, [], cl=6, owner_features=[earth] if owns else [],
        bundle_transform=prepare, seed='SURFACE-MOUNTAIN-DEFAULT')
    press(combat, table, mid, 'Source contact')
    turn(table, mid, FOE)
    press(combat, table, mid, 'Surface attack', OWNER)
    e = reload(tmp_path, mid)
    event = next(x for x in e.events if x.event_type == 'ATTACK_ROLLED' and x.actor_id == FOE)
    assert event.payload['target_ac'] == ac
