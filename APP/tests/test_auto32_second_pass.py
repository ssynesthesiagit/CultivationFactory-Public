"""Scoped Night resistance and permanent Darkness use real table snapshots."""
import pytest

from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, reload, turn

NIGHT = 'TAL_DARK_ONE_WITH_THE_NIGHT'


@pytest.mark.parametrize('case,mundane,kind,expected', [
    ('owned', True, 'bludgeoning', 4), ('owned', False, 'slashing', 8),
    ('owned', None, 'piercing', 8), ('owned', True, 'radiant', 8),
    ('unowned', True, 'bludgeoning', 8), ('legacy', False, 'piercing', 4),
    ('expired', True, 'bludgeoning', 8)])
def test_night_resistance_matches_nonmagical_physical_packets(tmp_path, case, mundane, kind, expected):
    def prepare(bundles):
        for bundle, initiative in zip(bundles, [100, -100, 0]):
            bundle['actor_template']['initiative_bonus'] = initiative
            bundle['actor_template']['maximum_hp'] = 300
            seal(bundle)
        add_action(bundles[2], 'Deal packet', [{'type': 'damage', 'flat': 8,
            'damage_types': [kind], 'applies_to': 'target'}],
            typed={} if mundane is None else {'mundane': mundane})
        add_action(bundles[2], 'Break concentration', [{'type': 'condition', 'condition': 'incapacitated',
            'applies_to': 'target', 'expires_on': 'END_OF_HOLDER_NEXT_TURN'}])
        if case == 'legacy':
            for action in bundles[0]['action_catalog']:
                typed = action.get('parameters', {}).get('typed', {})
                if typed.get('source') == NIGHT:
                    state = next(e for e in typed['effects'] if e['type'] == 'state')
                    state.pop('nonmagical_resistance', None)
                    typed['effects'] = [{'type': 'resistance', 'applies_to': 'self',
                        'damage_types': ['bludgeoning', 'piercing', 'slashing'],
                        'duration': 'concentration'}, state]
            seal(bundles[0])
    combat, table, mid = fixture(tmp_path, [] if case == 'unowned' else [NIGHT], bundle_transform=prepare)
    if case != 'unowned':
        settle(table, mid, candidate(combat, mid, 'One With The Night').candidate_id)
        reload(tmp_path, mid)
    turn(table, mid, FOE)
    if case == 'expired':
        settle(table, mid, candidate(combat, mid, 'Break concentration', target=OWNER).candidate_id)
        assert not any(c.condition_id.endswith('state.one_with_the_night')
                       for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values())
    settle(table, mid, candidate(combat, mid, 'Deal packet', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED')
    assert damage.target_ids == (OWNER,)
    assert damage.payload['hp_damage'] == expected


@pytest.mark.parametrize('eternal', [True, False])
def test_eternal_darkness_native_stationary_clock_and_payment_reload(tmp_path, eternal):
    def prepare(bundles):
        for bundle, initiative in zip(bundles, [100, -100, 0]):
            bundle['actor_template']['initiative_bonus'] = initiative
            seal(bundle)
        add_action(bundles[0], 'Suppress magical area', [{'type': 'suppress_area',
            'magical_only': True, 'until': 'start_of_your_next_turn'}], target='CELL')
        bundles[0]['action_catalog'][-1]['parameters']['any_cell'] = True
        seal(bundles[0])
    talents = ['TAL_DARK_ROLLING_BLACKOUT', 'TAL_DARK_CLINGING_DARKNESS']
    if eternal:
        talents.append('TAL_DARK_ETERNAL_DARKNESS')
    combat, table, mid = fixture(tmp_path, talents, bundle_transform=prepare)
    if eternal:
        settle(table, mid, candidate(combat, mid, 'Augment Darkness: Eternal Darkness').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Darkness' + (' + Eternal Darkness' if eternal else ''), at=(3, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    zone = next(z for z in engine.state.zones.values() if z.active)
    assert zone.duration_rounds == (None if eternal else 10)
    assert zone.concentration_link != eternal
    assert bool(engine.state.actors[OWNER].concentration) != eternal
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == (98 if eternal else 100)
    if eternal:
        assert zone.trigger_profile['source_profile']['mundane'] == 0
    start = zone.center
    offered = [c for c in engine.legal_candidates() if (a := engine.action_catalog.get(c.source_definition_id))
               and a.display_name == 'Rolling Blackout: move Darkness']
    assert bool(offered) != eternal
    if not eternal:
        move = next(c for c in offered if c.destination and c.destination.x == 4 and c.destination.y == 6)
        settle(table, mid, move.candidate_id)
        assert next(z for z in reload(tmp_path, mid).state.zones.values() if z.active).center != start
    else:
        settle(table, mid, candidate(combat, mid, 'Suppress magical area', at=(3, 6)).candidate_id)
        zone = next(z for z in reload(tmp_path, mid).state.zones.values() if z.active)
        assert zone.trigger_profile.get('suppressed')
        assert not zone.affected_cells


def test_rolling_blackout_action_and_explicit_area_selection_reload(tmp_path):
    def prepare(bundles):
        for bundle, initiative in zip(bundles, [100, -100, 0]):
            bundle['actor_template']['initiative_bonus'] = initiative
            seal(bundle)
        add_action(bundles[0], 'Spend Bonus Action', [], target='SELF')
        bundles[0]['action_catalog'][-1]['economy'] = 'BONUS_ACTION'
        seal(bundles[0])
    combat, table, mid = fixture(tmp_path, ['TAL_DARK_ROLLING_BLACKOUT'], bundle_transform=prepare)
    for point in [(3, 6), (3, 9)]:
        settle(table, mid, candidate(combat, mid, 'Darkness', at=point).candidate_id)
        reload(tmp_path, mid)
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    areas = sorted((z for z in engine.state.zones.values() if z.active), key=lambda z: z.created_round)
    assert len(areas) == 2
    selected, untouched = areas
    original = untouched.center
    settle(table, mid, candidate(combat, mid, 'Spend Bonus Action').candidate_id)
    move = candidate(combat, mid, 'Rolling Blackout: move Darkness (Action)', at=(4, 8))
    settle(table, mid, move.candidate_id, {'choice:needle.rolling_blackout_area': selected.zone_id})
    engine = reload(tmp_path, mid)
    assert engine.state.zones[selected.zone_id].center.x == 4
    assert engine.state.zones[selected.zone_id].center.y == 8
    assert engine.state.zones[untouched.zone_id].center == original
