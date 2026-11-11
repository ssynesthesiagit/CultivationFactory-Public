"""AUTO50 Sand rules at the committed table and cold-reload boundary."""
import pytest
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn

P = 'TAL_SAND_'


@pytest.mark.parametrize('kind,owned,dc', [('slashing', True, 100), ('piercing', True, 100),
                                        ('piercing', True, -100), ('slashing', False, 100)])
def test_glass_edge_owner_chooses_scour_damage_each_use(tmp_path, kind, owned, dc):
    combat, table, mid = fixture(tmp_path, [P + 'GLASS_EDGE_SCRIPTURE'] if owned else ['SAND_BASE_SCOURING_HAND'], owner_dc=dc)
    cast = candidate(combat, mid, 'Scouring Hand: Reduce Speed', target=FOE)
    prompts = settle(table, mid, cast.candidate_id, {'choice:needle.glass_edge_type': kind})
    e = reload(tmp_path, mid)
    damage = next(x for x in reversed(e.events) if x.event_type == 'DAMAGE_COMMITTED')
    assert damage.payload['damage_type'] == (kind.upper() if owned else 'SLASHING')
    assert any(p['context']['reaction_source_id'] == 'choice:needle.glass_edge_type' for p in prompts) == owned


def prepare_sand(bundles):
    for b in bundles:
        add_action(b, 'Prepare Sand Terrain', [{'type': 'zone', 'terrain': ['shallow sand terrain'],
            'applies_to': 'self', 'distance_ft': 5, 'duration': 'one_minute'}], target='SELF',
            typed={'sphere': 'tianxia.sphere.sand',
                   'area': {'shape': 'sphere', 'size_ft': 15, 'centered_on_self': True},
                   'zone_spec': {'name': 'Prepared Sand Terrain', 'size_ft': 15, 'centered_on_self': True,
                                 'terrain': ['shallow sand terrain'],
                                 'visual': {'material': 'sand'}, 'duration': {'kind': 'rounds', 'amount': 10}}})


@pytest.mark.parametrize('terrain_owner', [OWNER, ALLY])
def test_needle_volley_filters_actual_terrain_and_allows_chosen_allies(tmp_path, terrain_owner):
    combat, table, mid = fixture(tmp_path, [P + 'SAND_NEEDLE_VOLLEY'], owner_dc=100,
                               foe_position={'x': 14, 'y': 12}, bundle_transform=prepare_sand)
    turn(table, mid, terrain_owner)
    settle(table, mid, candidate(combat, mid, 'Prepare Sand Terrain').candidate_id)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    prompts = settle(table, mid, candidate(combat, mid, 'Sand Needle Volley').candidate_id,
                     {'choice:needle.rider_targets': [ALLY]})
    options = next(p['choice']['options'] for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.rider_targets')
    assert ALLY in {o['id'] for o in options} and FOE not in {o['id'] for o in options}
    e = reload(tmp_path, mid)
    assert e.state.actors[ALLY].current_hp < 60 and e.state.actors[FOE].current_hp == before
    assert e._effective_speed(e.state.actors[ALLY]) == 20
    turn(table, mid, ALLY)
    assert reload(tmp_path, mid)._effective_speed(reload(tmp_path, mid).state.actors[ALLY]) == 20
    turn(table, mid, OWNER)
    e = reload(tmp_path, mid)
    assert e._effective_speed(e.state.actors[ALLY]) == 30


@pytest.mark.parametrize('success', [False, True])
def test_sand_coffin_applies_only_the_printed_save_outcome_and_expiry(tmp_path, success):
    def prepare(bundles):
        prepare_sand(bundles)
        add_action(bundles[0], 'Prepare Burial', [{'type': 'sand_bury', 'applies_to': 'target',
            'duration': 'one_minute'}])
        bundles[2]['actor_template']['saving_throws'].update(STR=100 if success else -100, CON=100 if success else -100)
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [P + 'SAND_COFFIN'], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Prepare Sand Terrain').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Prepare Burial', target=FOE).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Sand Coffin', target=FOE).candidate_id)
    e = reload(tmp_path, mid)
    names = {c.condition_id for c in e.state.actors[FOE].conditions.values()}
    assert ('condition:typed.restrained' in names) != success
    assert ('condition:typed.silenced' in names) != success
    assert ('condition:typed.reaction_denied' in names) == success
    turn(table, mid, FOE)
    names = {c.condition_id for c in reload(tmp_path, mid).state.actors[FOE].conditions.values()}
    assert ('condition:typed.reaction_denied' in names) == success
    turn(table, mid, OWNER)
    e = reload(tmp_path, mid)
    assert not any(c.condition_id == 'condition:typed.reaction_denied' for c in e.state.actors[FOE].conditions.values())
    if not success:
        assert any(c.condition_id == 'condition:typed.silenced' for c in e.state.actors[FOE].conditions.values())
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        assert not any(c.condition_id == 'condition:typed.silenced' for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())


def test_glass_edge_persists_chosen_type_in_sandstorm_triggers(tmp_path):
    combat, table, mid = fixture(tmp_path, [P + 'GLASS_EDGE_SCRIPTURE', P + 'THOUSAND_MILE_SANDSTORM_BODY'], owner_dc=100)
    settle(table, mid, candidate(combat, mid, 'Thousand-Mile Sandstorm Body').candidate_id,
           {'choice:needle.glass_edge_type': 'piercing'})
    e = reload(tmp_path, mid)
    zone = next(z for z in e.state.zones.values() if z.active and 'THOUSAND_MILE' in z.source_definition_id)
    assert zone.trigger_profile['triggers'][0]['effects'][0]['on_fail'][0]['damage_types'] == ['piercing']
    turn(table, mid, FOE)
    damage = next(x for x in reversed(reload(tmp_path, mid).events) if x.event_type == 'DAMAGE_COMMITTED')
    assert damage.payload['damage_type'] == 'PIERCING'
