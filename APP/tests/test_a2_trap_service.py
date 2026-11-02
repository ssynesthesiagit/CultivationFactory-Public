"""Printed aerial traps and dual triggers through table/session commits and cold replay."""
import pytest

from combat.ext import placed
from combat.flight import profile
from combat.gate5_service import CombatService
from tests.cw2_service_support import add_action, seal
from tests.h1_support import ROOT
from tests.r1i_service_support import force_ai_candidate
from tests.test_r9i_karma_persistence import act
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn

AERIAL = 'TAL_TRAP_AERIAL_RIGGING'
SKY = 'TAL_TRAP_FALLING_SKY_MECHANISM'
HEAVEN = 'TAL_TRAP_HEAVEN_NET_BATTLEFIELD'
ROAD = 'TAL_TRAP_THE_EMPTY_ROAD_WAS_NEVER_EMPTY'
NET = 'tianxia.talent.trap.net'


def setup(tmp_path, talents, *, height=2, hover=False, cl=15, str_save=-100,
          dex_save=-100, foe_x=5, foe_y=7, legacy=False, immune=False, raised=False, grounded=False, ally_x=4, foe_fly_speed=10, restore_focus=False):
    def tune(bundles):
        if restore_focus:
            add_action(bundles[0], 'Prepare focus', [{'type': 'gain_resource',
                'resource_id': 'resource:core.martial_focus', 'flat': 1, 'applies_to': 'self'}])
        b = bundles[2]
        b['actor_template'].update(fly_speed_ft=foe_fly_speed, hover=hover, armor_class=0,
                                   saving_throws={'DEX': dex_save, 'STR': str_save})
        if immune:
            add_action(bundles[0], 'Prepare piercing immunity', [{'type': 'immunity', 'damage_types': ['piercing'], 'applies_to': 'target', 'duration': 'until_removed'}])
        if grounded:
            add_action(bundles[0], 'Prepare grounded flight', [{'type': 'condition', 'condition': 'a2_trap_test_grounded',
                'duration': 'until_removed', 'applies_to': 'target', 'condition_data': {'fly_speed_zero': 1}}])
        for a in b['action_catalog']:
            for eff in a['parameters'].get('typed', {}).get('effects', []):
                if eff.get('type') == 'trap_escape':
                    eff['bonus'] = 100
        bundles[0]['actor_template']['saving_throws']['DEX'] = -100
        bundles[1]['actor_template']['saving_throws']['DEX'] = -100
        if raised:
            for friendly in bundles[:2]:
                friendly['actor_template'].update(fly_speed_ft=10, hover=True)
        if legacy:
            for a in bundles[0]['action_catalog']:
                a['parameters'].pop('trap_runtime', None)
        for b in bundles:
            seal(b)
    return fixture(tmp_path, talents, cl=cl, seed='A2TRAP-SERVICE', bundle_transform=tune,
                   positions={OWNER: {'x': 3, 'y': 6, 'z': 3 if raised else 0},
                              ALLY: {'x': ally_x, 'y': 6, 'z': 3 if raised else 0},
                              FOE: {'x': foe_x, 'y': foe_y, 'z': height}})


def pick(combat, table, mid, title):
    settle(table, mid, candidate(combat, mid, title).candidate_id)


def arm(combat, table, mid, *, form='Tripwire', aerial=True, at=(4, 7)):
    pick(combat, table, mid, 'Trap form: ' + form)
    if aerial:
        pick(combat, table, mid, 'Aerial Rigging: on')
    return settle(table, mid, candidate(combat, mid, 'Set Trap', at=at).candidate_id,
                  {'choice:needle.trap_terrain_corner': 'ne'})


def move(combat, table, mid, actor, xyz, *, auto=False, picks=None):
    turn(table, mid, actor)
    e = combat._load_session(mid).engine
    cs = [c for c in e.legal_candidates() if c.kind.value == 'MOVE' and c.destination
          and (c.destination.x, c.destination.y, c.destination.z) == xyz]
    assert cs, (actor, xyz)
    if auto:
        force_ai_candidate(combat, mid, actor, cs[0].candidate_id)
    return settle(table, mid, cs[0].candidate_id, picks, auto=auto)


def cold(tmp_path, mid):
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.verify()['status'] == 'PASS'
    assert fresh.mechanical.replay()['status'] == 'PASS'
    return fresh.engine


@pytest.mark.parametrize('hover', [False, True])
@pytest.mark.parametrize('ai', [False, True])
def test_rigged_tripwire_falls_unless_hovering(tmp_path, hover, ai):
    combat, table, mid = setup(tmp_path, [AERIAL], hover=hover)
    arm(combat, table, mid)
    before = cold(tmp_path, mid)
    assert placed.of(before, 'trap')[0].trigger_profile['footprint_height_ft'] == 35
    hp = before.state.actors[FOE].current_hp
    move(combat, table, mid, FOE, (4, 7, 2), auto=ai)
    e = cold(tmp_path, mid)
    target = e.state.actors[FOE]
    assert any(c.condition_id == 'condition:typed.prone' for c in target.conditions.values())
    assert target.position.z == (2 if hover else 0)
    assert (target.current_hp < hp) != hover
    assert placed.of(e, 'trap')  # Tripwire survives triggering.


@pytest.mark.parametrize('cl,cap', [(5, 2), (10, 4), (15, 6)])
@pytest.mark.parametrize('above', [False, True])
def test_rigging_height_cap_and_above_cap(tmp_path, cl, cap, above):
    height = cap + int(above)
    combat, table, mid = setup(tmp_path, [AERIAL], cl=cl, height=height, hover=True)
    arm(combat, table, mid)
    move(combat, table, mid, FOE, (4, 7, height))
    e = cold(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.prone' for c in e.state.actors[FOE].conditions.values()) != above
    assert placed.of(e, 'trap')[0].trigger_profile['footprint_height_ft'] == cap * 5 + 5


@pytest.mark.parametrize('form,talent', [('Net (Snare use)', NET), ('Noose', 'TAL_TRAP_NOOSE')])
def test_hovering_net_and_noose_pull_before_restraint(tmp_path, form, talent):
    combat, table, mid = setup(tmp_path, [AERIAL, talent], hover=True)
    arm(combat, table, mid, form=form)
    hp = cold(tmp_path, mid).state.actors[FOE].current_hp
    move(combat, table, mid, FOE, (4, 7, 2))
    e = cold(tmp_path, mid)
    target = e.state.actors[FOE]
    assert (target.position.x, target.position.y, target.position.z) == (4, 7, 0)
    assert target.current_hp == hp
    assert any(c.condition_id == 'condition:typed.restrained' for c in target.conditions.values())
    if talent.endswith('NOOSE'):
        assert any(c.condition_id == 'condition:typed.silenced' for c in target.conditions.values())
    events = e.events
    pull = next(i for i, v in enumerate(events) if v.event_type == 'MOVEMENT_COMMITTED'
                and v.actor_id == FOE and v.payload.get('forced'))
    hold = next(i for i, v in enumerate(events) if v.event_type == 'CONDITION_APPLIED'
                and v.payload.get('condition_id') == 'condition:typed.restrained')
    assert pull < hold


@pytest.mark.parametrize('hover,str_save,immune', [(False, -100, False), (True, -100, False),
                                                  (False, 100, False), (False, -100, True)])
def test_falling_sky_hit_save_hover_and_expiry(tmp_path, hover, str_save, immune):
    combat, table, mid = setup(tmp_path, [AERIAL, SKY], hover=hover, str_save=str_save,
                               immune=immune)
    if immune:
        settle(table, mid, candidate(combat, mid, 'Prepare piercing immunity', target=FOE).candidate_id)
    pick(combat, table, mid, 'Trap form: Dart Mechanism + Falling-Sky Mechanism')
    pick(combat, table, mid, 'Trap aim: upward')
    pick(combat, table, mid, 'Aerial Rigging: on')
    settle(table, mid, candidate(combat, mid, 'Set Trap', at=(4, 7)).candidate_id)
    move(combat, table, mid, FOE, (4, 7, 2))
    e = cold(tmp_path, mid)
    target = e.state.actors[FOE]
    failed = str_save < 0
    assert any(c.condition_id == 'condition:typed.falling_sky_grounded' for c in target.conditions.values()) == failed
    assert target.position.z == (0 if failed and not hover else 2)
    assert profile(e, target).speed_ft == (0 if failed else 10)
    if immune:
        assert any(v.event_type == 'SAVE_ROLLED' and v.actor_id == FOE for v in e.events)
        assert any(v.event_type == 'DAMAGE_COMMITTED' and v.payload.get('damage_type') == 'PIERCING'
                   and v.payload.get('reduced_to') == 0 for v in e.events)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    e = cold(tmp_path, mid)
    assert not any(c.condition_id == 'condition:typed.falling_sky_grounded' for c in e.state.actors[FOE].conditions.values())
    assert profile(e, e.state.actors[FOE]).speed_ft == 10


def test_heaven_net_pulls_nonhovering_flyer_and_prices_its_lattice(tmp_path):
    from combat.gate2_runtime_models import Position
    from combat.flight import step_cost
    combat, table, mid = setup(tmp_path, [AERIAL, HEAVEN, NET])
    arm(combat, table, mid, form='Net (Snare use)', aerial=False)
    e = cold(tmp_path, mid)
    assert step_cost(e, e.state.actors[FOE], Position(x=5, y=7, z=2), Position(x=4, y=7, z=2), 'fly') == 10
    assert (4, 7) not in e._hostile_difficult_cells(e.state.actors[ALLY])
    hp = e.state.actors[FOE].current_hp
    move(combat, table, mid, FOE, (4, 7, 2))
    e = cold(tmp_path, mid)
    target = e.state.actors[FOE]
    assert target.position.z == 0 and target.current_hp == hp
    assert any(c.condition_id == 'condition:typed.restrained' and c.data.get('flight_suspended') == 1
               for c in target.conditions.values())
    assert placed.of(e, 'heaven_lattice')
    settle(table, mid, candidate(combat, mid, 'Escape the net').candidate_id)
    e = cold(tmp_path, mid)
    assert not placed.of(e, 'heaven_lattice')


def test_heaven_terrain_affects_full_height_and_expires(tmp_path):
    combat, table, mid = setup(tmp_path, [AERIAL, HEAVEN, 'TAL_TRAP_TERRAIN_TRAP'], hover=True)
    arm(combat, table, mid, form='Terrain Trap (sprung at once)')
    e = cold(tmp_path, mid)
    zone = placed.of(e, 'terrain_trap')[0]
    assert zone.trigger_profile['footprint_height_ft'] == 35
    move(combat, table, mid, FOE, (6, 7, 2))
    e = cold(tmp_path, mid)
    event = next(v for v in reversed(e.events) if v.event_type == 'MOVEMENT_COMMITTED' and v.actor_id == FOE)
    assert event.payload['cost_ft'] == 10
    for _ in range(10):
        turn(table, mid, OWNER)
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    e = cold(tmp_path, mid)
    assert not placed.of(e, 'terrain_trap')


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'SUGGESTED', 'MANUAL_AI_BRIDGE'])
def test_warning_respects_controller_choice_authority(tmp_path, mode):
    combat, table, mid = setup(tmp_path, [AERIAL, 'TAL_TRAP_WARNING_TRIGGER'], height=0)
    pick(combat, table, mid, 'Trap form: Tripwire')
    pick(combat, table, mid, 'Trap trigger: Warning Trigger')
    cid = candidate(combat, mid, 'Set Trap: choose a space').candidate_id
    if mode == 'LOCAL_AUTO':
        force_ai_candidate(combat, mid, OWNER, cid)
        settle(table, mid, cid, auto=True)
    else:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
        prompts = settle(table, mid, cid, {'choice:needle.trap_raised_space': 'cell:4,7,0',
                                          'choice:needle.trap_warn': [OWNER, ALLY, FOE]})
        warning = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.trap_warn')
        assert {o['id'] for o in warning['choice']['options']} == {OWNER, ALLY, FOE}
    e = cold(tmp_path, mid)
    assert set(placed.data(placed.of(e, 'trap')[0])['warned']) == ({OWNER, ALLY} if mode == 'LOCAL_AUTO' else {OWNER, ALLY, FOE})
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    move(combat, table, mid, FOE, (4, 7, 0), picks={'choice:needle.trap_warned_trigger': None})
    e = cold(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.prone' for c in e.state.actors[FOE].conditions.values()) == (mode == 'LOCAL_AUTO')


def test_markerless_saved_trap_packet_keeps_ground_geometry(tmp_path):
    combat, table, mid = setup(tmp_path, [AERIAL], legacy=True, hover=True)
    arm(combat, table, mid)
    e = cold(tmp_path, mid)
    assert 'footprint_height_ft' not in placed.of(e, 'trap')[0].trigger_profile
    move(combat, table, mid, FOE, (4, 7, 2))
    assert not any(c.condition_id == 'condition:typed.prone' for c in cold(tmp_path, mid).state.actors[FOE].conditions.values())


def prepare_road(tmp_path, pair, extra, spaces=None):
    from tests.test_hunt35_trap_setup import fixture as road_fixture, OWNER as R_OWNER
    from tests.test_hunt25_mantle_setup import send
    combat, table, mid = road_fixture(tmp_path, [ROAD, 'TAL_TRAP_FALSE_TRIGGER', 'TAL_TRAP_WARNING_TRIGGER', *extra])
    answers, prompts = [], []
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    for _ in range(15):
        result = send(table, mid, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']; prompts.append(p)
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        rid = p['context']['reaction_source_id']
        options = p.get('choice', {}).get('options', [])
        ids = ((spaces or [o['id'] for o in options][-4:]) if rid.endswith('trap_scatter') else
               pair if rid.endswith('trap_second_trigger') else
               [R_OWNER] if rid.endswith('trap_warn') else [])
        answers.append({**p['context'], 'selection': 'USE', 'option_ids': ids})
    else:
        pytest.fail('Road setup did not commit')
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert len(placed.of(loaded.engine, 'trap')) == 4
    assert all(placed.data(z).get('triggers') == pair and placed.data(z).get('warned') == ([R_OWNER] if 'warning' in pair else [])
               for z in placed.of(loaded.engine, 'trap'))
    if 'aerial' in pair:
        assert all(z.trigger_profile.get('footprint_height_ft') == 35 for z in placed.of(loaded.engine, 'trap'))
    assert any(p['context']['reaction_source_id'].endswith('trap_second_trigger') for p in prompts)
    assert loaded.engine.state.actors[R_OWNER].resources['resource:core.martial_focus'] == 1

    return combat, table, mid


@pytest.mark.parametrize('pair,extra', [(['false', 'warning'], []), (['false', 'aerial'], [AERIAL]),
                                       (['false', 'remote'], ['TAL_TRAP_REMOTE_TRIGGER']),
                                       (['false', 'within'], ['TAL_TRAP_TRAP_WITHIN_THE_TRAP']),
                                       (['false', 'chained'], ['TAL_TRAP_CHAINED_MECHANISM'])])
def test_empty_road_chooses_second_trigger_with_no_extra_focus(tmp_path, pair, extra):
    prepare_road(tmp_path, pair, extra)


def test_empty_road_false_warning_resolves_both_triggers_after_reload(tmp_path):
    from tests.test_hunt35_trap_setup import OWNER as R_OWNER, FOE as R_FOE
    combat, table, mid = prepare_road(tmp_path, ['false', 'warning'], [])
    combat.set_controller_mode(mid, actor_id=R_FOE, controller_mode='MANUAL')
    turn(table, mid, R_OWNER)
    pick(combat, table, mid, 'Trap form: Tripwire')
    pick(combat, table, mid, 'Trap trigger: False Trigger')
    settle(table, mid, candidate(combat, mid, 'Set Trap', at=(4, 7)).candidate_id,
           {'choice:needle.trap_second_trigger': 'warning', 'choice:needle.trap_warn': [R_OWNER]})
    move(combat, table, mid, R_FOE, (4, 7, 0), picks={'choice:needle.trap_relocate': None})
    e = cold(tmp_path, mid)
    z = next(z for z in placed.of(e, 'trap') if (z.center.x, z.center.y) == (4, 7))
    assert placed.data(z)['false_used']
    assert not any(c.condition_id == 'condition:typed.prone' for c in e.state.actors[R_FOE].conditions.values())
    move(combat, table, mid, R_FOE, (5, 7, 0), picks={'choice:needle.trap_relocate': None})
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, R_FOE)
    move(combat, table, mid, R_FOE, (4, 7, 0), picks={'choice:needle.trap_relocate': None})
    e = cold(tmp_path, mid)
    save = [v for v in e.events if v.event_type == 'SAVE_ROLLED' and v.actor_id == R_FOE][-1]
    assert any(c.condition_id == 'condition:typed.prone' for c in e.state.actors[R_FOE].conditions.values()) == (not save.payload['success'])


@pytest.mark.parametrize('blocked,grounded', [(False, False), (True, False), (False, True)])
def test_raised_dart_downward_diagonal_stops_at_solid_surface(tmp_path, monkeypatch, blocked, grounded):
    arenas = CombatService.factory_arenas
    def physical_arena(service, *args, **kwargs):
        walls = [{'shape': 'rect', 'points': [[4, 7], [5, 8]],
                  'blocks': 'sight_and_movement', 'height_ft': 15}]
        if blocked:
            walls.append({'shape': 'rect', 'points': [[5, 7], [6, 8]],
                          'blocks': 'sight_and_movement', 'height_ft': 15})
        if grounded:
            walls.append({'shape': 'rect', 'points': [[6, 7], [7, 8]],
                          'blocks': 'sight_and_movement', 'height_ft': 5})
        service.tabletop_maps.save({'display_name': 'Rigging yard', 'width_squares': 14,
            'height_squares': 14, 'walls': walls,
            'starts': {'team1': [[3, 6]], 'team2': [[6, 7]]}})
        available = arenas(service, *args, **kwargs)
        return {**available, 'battlefield:factory_pillar_arena': available['battlefield:map.rigging-yard']}
    monkeypatch.setattr(CombatService, 'factory_arenas', physical_arena)
    combat, table, mid = setup(tmp_path, [AERIAL, SKY], raised=True, height=1, foe_x=6)
    pick(combat, table, mid, 'Trap form: Dart Mechanism + Falling-Sky Mechanism')
    pick(combat, table, mid, 'Trap aim: east and downward')
    cid = candidate(combat, mid, 'Set Trap on a raised surface').candidate_id
    pending = act(table, mid, cid)
    assert pending['status'] == 'REACTION_REQUIRED'
    p = pending['reaction']
    assert 'cell:4,7,3' in {o['id'] for o in p['choice']['options']}
    assert '15 feet above ground' in next(o['label'] for o in p['choice']['options'] if o['id'] == 'cell:4,7,3')
    assert act(table, mid, cid, [{**p['context'], 'selection': 'USE', 'option_ids': ['cell:4,7,3']}])['status'] == 'COMMITTED'
    assert placed.of(cold(tmp_path, mid), 'trap')[0].center.z == 3
    move(combat, table, mid, ALLY, (4, 7, 3))
    e = cold(tmp_path, mid)
    attacks = [v for v in e.events if v.event_type == 'ATTACK_ROLLED' and v.actor_id == OWNER]
    assert bool(attacks) != blocked
    assert e.state.actors[FOE].position.z == (1 if blocked or grounded else 0)
    assert any(c.condition_id == 'condition:typed.falling_sky_grounded' for c in e.state.actors[FOE].conditions.values()) == (not blocked and not grounded)


def test_aerial_flash_includes_every_creature_in_its_printed_burst(tmp_path):
    combat, table, mid = setup(tmp_path, [AERIAL, 'TAL_TRAP_FLASH_TRAP'], hover=True)
    arm(combat, table, mid, form='Flash Trap')
    move(combat, table, mid, FOE, (4, 7, 2), auto=True)
    e = cold(tmp_path, mid)
    assert all(any(c.condition_id == 'condition:typed.blinded' for c in e.state.actors[aid].conditions.values())
               for aid in (OWNER, ALLY, FOE))


def test_successful_aerial_net_save_does_not_pull_or_restrain(tmp_path):
    combat, table, mid = setup(tmp_path, [AERIAL, NET], hover=True, dex_save=100)
    arm(combat, table, mid, form='Net (Snare use)')
    move(combat, table, mid, FOE, (4, 7, 2))
    e = cold(tmp_path, mid)
    assert e.state.actors[FOE].position.z == 2
    assert not any(c.condition_id == 'condition:typed.restrained' for c in e.state.actors[FOE].conditions.values())


def test_empty_road_chained_choice_resolves_a_rigged_second_trap(tmp_path):
    from tests.test_hunt35_trap_setup import OWNER as R_OWNER, FOE as R_FOE
    combat, table, mid = prepare_road(tmp_path, ['false', 'aerial'], [AERIAL, 'TAL_TRAP_CHAINED_MECHANISM'],
                                    spaces=['cell:3,7', 'cell:3,8', 'cell:4,8', 'cell:5,8'])
    combat.set_controller_mode(mid, actor_id=R_FOE, controller_mode='MANUAL')
    turn(table, mid, R_OWNER)
    pick(combat, table, mid, 'Trap form: Tripwire')
    pick(combat, table, mid, 'Trap trigger: Chained Mechanism')
    pick(combat, table, mid, 'Aerial Rigging: on')
    prompts = settle(table, mid, candidate(combat, mid, 'Set Trap', at=(4, 7)).candidate_id)
    assert not any(p['context']['reaction_source_id'].endswith('trap_second_trigger') for p in prompts)
    e = cold(tmp_path, mid)
    first = next(z for z in placed.of(e, 'trap') if (z.center.x, z.center.y) == (4, 7))
    second = next(z for z in placed.of(e, 'trap') if (z.center.x, z.center.y) == (3, 7))
    assert placed.data(first)['triggers'] == ['chained', 'aerial']
    prompts = move(combat, table, mid, R_FOE, (4, 7, 0),
                   picks={'choice:needle.trap_chained_pick': second.zone_id, 'choice:needle.trap_relocate': None})
    assert any(p['context']['reaction_source_id'].endswith('trap_chained_pick') for p in prompts)
    e = cold(tmp_path, mid)
    second = e.state.zones[second.zone_id]
    assert placed.data(second)['false_used']
    assert placed.data(second)['chain_turn'] == e.state.round_number * 1000 + e.state.current_slot_index
    assert second.trigger_profile['footprint_height_ft'] == 35
    assert sum(bool(placed.data(z).get('false_used')) for z in placed.of(e, 'trap')) == 1


def test_heaven_lattice_still_hinders_a_creature_whose_fly_speed_is_zero(tmp_path):
    combat, table, mid = setup(tmp_path, [AERIAL, HEAVEN, NET], height=0, grounded=True, dex_save=100)
    settle(table, mid, candidate(combat, mid, 'Prepare grounded flight', target=FOE).candidate_id)
    arm(combat, table, mid, form='Net (Snare use)', aerial=False)
    e = cold(tmp_path, mid)
    assert profile(e, e.state.actors[FOE]).speed_ft == 0
    move(combat, table, mid, FOE, (4, 7, 0))
    e = cold(tmp_path, mid)
    event = next(v for v in reversed(e.events) if v.event_type == 'MOVEMENT_COMMITTED' and v.actor_id == FOE)
    assert event.payload['cost_ft'] == 10


def test_rigging_and_another_trigger_need_the_two_trigger_inheritance(tmp_path):
    combat, table, mid = setup(tmp_path, [AERIAL, 'TAL_TRAP_WARNING_TRIGGER'])
    pick(combat, table, mid, 'Trap trigger: Warning Trigger')
    pick(combat, table, mid, 'Aerial Rigging: on')
    e = cold(tmp_path, mid)
    assert not any((e.action_catalog.get(c.source_definition_id).parameters or {}).get('set_trap') or
                   (e.action_catalog.get(c.source_definition_id).parameters or {}).get('trap_raised')
                   for c in e.legal_candidates() if c.source_definition_id in e.action_catalog)
    pick(combat, table, mid, 'Aerial Rigging: off')
    assert candidate(combat, mid, 'Set Trap', at=(4, 7))
    cold(tmp_path, mid)


def test_falling_sky_hits_a_hovering_creature_already_at_zero_fly_speed(tmp_path):
    combat, table, mid = setup(tmp_path, [AERIAL, SKY], height=1, hover=True, grounded=True)
    settle(table, mid, candidate(combat, mid, 'Prepare grounded flight', target=FOE).candidate_id)
    pick(combat, table, mid, 'Trap form: Dart Mechanism + Falling-Sky Mechanism')
    pick(combat, table, mid, 'Trap aim: east and upward')
    settle(table, mid, candidate(combat, mid, 'Set Trap', at=(4, 7)).candidate_id)
    move(combat, table, mid, ALLY, (4, 7, 0))
    e = cold(tmp_path, mid)
    assert e.state.actors[FOE].position.z == 1
    assert any(c.condition_id == 'condition:typed.falling_sky_grounded' for c in e.state.actors[FOE].conditions.values())
    assert any(v.event_type == 'SAVE_ROLLED' and v.actor_id == FOE for v in e.events)



def test_wall_anchor_accepts_suspended_device_but_rejects_unanchored_air(tmp_path, monkeypatch):
    arenas = CombatService.factory_arenas
    def physical_arena(service, *args, **kwargs):
        service.tabletop_maps.save({'display_name': 'Wall rigging yard', 'width_squares': 14,
            'height_squares': 14, 'walls': [{'shape': 'rect', 'points': [[4, 7], [5, 8]],
                'blocks': 'sight_and_movement', 'height_ft': 15}],
            'starts': {'team1': [[3, 6]], 'team2': [[6, 7]]}})
        available = arenas(service, *args, **kwargs)
        return {**available, 'battlefield:factory_pillar_arena': available['battlefield:map.wall-rigging-yard']}
    monkeypatch.setattr(CombatService, 'factory_arenas', physical_arena)
    combat, table, mid = setup(tmp_path, [AERIAL], raised=True, height=1, foe_x=6, ally_x=2)
    pick(combat, table, mid, 'Trap form: Tripwire')
    pick(combat, table, mid, 'Aerial Rigging: on')
    cid = candidate(combat, mid, 'Set Trap on a raised surface').candidate_id
    pending = act(table, mid, cid)
    p = pending['reaction']
    ids = {o['id'] for o in p['choice']['options']}
    assert 'cell:3,7,2' in ids  # A solid wall face is beside the device.
    assert 'cell:3,7,3' not in ids  # Above that face, no solid anchor exists.
    settle(table, mid, cid, {'choice:needle.trap_raised_space': 'cell:3,7,2'})
    e = cold(tmp_path, mid)
    assert placed.of(e, 'trap')[0].center.z == 2
    move(combat, table, mid, ALLY, (3, 7, 2))
    e = cold(tmp_path, mid)
    assert e.state.actors[ALLY].position.z == 2  # Its Hover prevents falling.
    assert any(c.condition_id == 'condition:typed.prone' for c in e.state.actors[ALLY].conditions.values())



@pytest.mark.parametrize('fly_speed,cost', [(0, 5), (10, 10)])
def test_heaven_terrain_covers_legal_upper_spaces_above_solid_columns(tmp_path, monkeypatch, fly_speed, cost):
    arenas = CombatService.factory_arenas
    def physical_arena(service, *args, **kwargs):
        service.tabletop_maps.save({'display_name': 'Lattice platform yard', 'width_squares': 14,
            'height_squares': 14, 'walls': [{'shape': 'rect', 'points': [[6, 6], [7, 8]],
                'blocks': 'sight_and_movement', 'height_ft': 10}],
            'starts': {'team1': [[3, 6]], 'team2': [[6, 6]]}})
        available = arenas(service, *args, **kwargs)
        return {**available, 'battlefield:factory_pillar_arena': available['battlefield:map.lattice-platform-yard']}
    monkeypatch.setattr(CombatService, 'factory_arenas', physical_arena)
    combat, table, mid = setup(tmp_path, [AERIAL, HEAVEN, 'TAL_TRAP_TERRAIN_TRAP'],
                               height=2, foe_x=6, foe_y=6, foe_fly_speed=fly_speed)
    arm(combat, table, mid, form='Terrain Trap (sprung at once)', aerial=False)
    e = cold(tmp_path, mid)
    zone = placed.of(e, 'terrain_trap')[0]
    assert (6, 7) in {(p.x, p.y) for p in zone.affected_cells}
    move(combat, table, mid, FOE, (6, 7, 2))
    e = cold(tmp_path, mid)
    event = next(v for v in reversed(e.events) if v.event_type == 'MOVEMENT_COMMITTED' and v.actor_id == FOE)
    assert event.payload['cost_ft'] == cost


@pytest.mark.parametrize('raised', [False, True])
def test_reviewed_ordinary_dart_uses_actual_altitude(tmp_path, monkeypatch, raised):
    if raised:
        arenas = CombatService.factory_arenas
        def physical_arena(service, *args, **kwargs):
            service.tabletop_maps.save({'display_name': 'Dart altitude yard', 'width_squares': 14,
                'height_squares': 14, 'walls': [
                    {'shape': 'rect', 'points': [[4, 7], [5, 8]], 'blocks': 'sight_and_movement', 'height_ft': 15},
                    {'shape': 'rect', 'points': [[5, 7], [6, 8]], 'blocks': 'sight_and_movement', 'height_ft': 10}],
                'starts': {'team1': [[3, 6]], 'team2': [[6, 7]]}})
            available = arenas(service, *args, **kwargs)
            return {**available, 'battlefield:factory_pillar_arena': available['battlefield:map.dart-altitude-yard']}
        monkeypatch.setattr(CombatService, 'factory_arenas', physical_arena)
    combat, table, mid = setup(tmp_path, [AERIAL], raised=raised, hover=True,
                              height=3 if raised else 2, foe_x=6 if raised else 5)
    pick(combat, table, mid, 'Trap form: Dart Mechanism')
    pick(combat, table, mid, 'Trap aim: east')
    if raised:
        pick(combat, table, mid, 'Aerial Rigging: on')
        cid = candidate(combat, mid, 'Set Trap on a raised surface').candidate_id
        pending = act(table, mid, cid)['reaction']
        assert act(table, mid, cid, [{**pending['context'], 'selection': 'USE',
                                    'option_ids': ['cell:4,7,3']}])['status'] == 'COMMITTED'
    else:
        settle(table, mid, candidate(combat, mid, 'Set Trap', at=(4, 7)).candidate_id)
    before = cold(tmp_path, mid)
    assert placed.data(placed.of(before, 'trap')[0])['physical_3d'] == 1
    hp = before.state.actors[FOE].current_hp
    move(combat, table, mid, ALLY, (4, 7, 3 if raised else 0))
    e = cold(tmp_path, mid)
    attacks = [v for v in e.events if v.event_type == 'ATTACK_ROLLED' and v.actor_id == OWNER]
    assert bool(attacks) == raised
    assert (e.state.actors[FOE].current_hp < hp) == raised
    assert not placed.of(e, 'trap')


def test_supported_placement_at_map_border_keeps_legal_choices(tmp_path):
    combat, table, mid = fixture(tmp_path, [AERIAL], cl=15, seed='A2TRAP-BORDER',
        positions={OWNER: {'x': 0, 'y': 6}, ALLY: {'x': 2, 'y': 6}, FOE: {'x': 5, 'y': 7}})
    cid = candidate(combat, mid, 'Set Trap: choose a space').candidate_id
    pending = act(table, mid, cid)
    assert pending['status'] == 'REACTION_REQUIRED'
    p = pending['reaction']
    assert 'cell:0,7,0' in {o['id'] for o in p['choice']['options']}
    assert all(int(v) >= 0 for o in p['choice']['options'] for v in o['id'].split(':')[1].split(','))
    assert act(table, mid, cid, [{**p['context'], 'selection': 'USE', 'option_ids': ['cell:0,7,0']}])['status'] == 'COMMITTED'
    e = cold(tmp_path, mid)
    assert placed.of(e, 'trap')[0].center.x == 0
