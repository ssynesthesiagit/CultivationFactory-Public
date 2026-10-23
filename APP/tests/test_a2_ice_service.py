"""Ice second pass: actual table/session intents, cold reload and replay.

Sealed setup actions supply damage, terrain study and movement triggers only.
Shipped Ice rows supply every tested benefit and player choice.
"""
import copy
import pytest

from combat import ext, zones
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, turn
from tests.cw2_service_support import add_action, seal
from tests.test_auto116_ice import setup, reach, asked, FOE_CELL
from combat.ext.ice_fracture import lattice_zones, lattice_cells, marked, GUARD

T = 'TAL_ICE_'
WINTER = 'insight.winter-tempered-body'
WASTE = 'insight.shatter-without-waste'
FOOT = 'insight.ice-sure-footwork'
SCHOLAR = 'insight.lattice-scholar'
QUIET = {'choice:needle.fracture_response': None}


def settle(table, mid, cid, picks=None, *, auto=False):
    from tests.test_r9i_karma_persistence import act
    answers, prompts = [], []
    for _ in range(50):
        result = table.auto_step(mid, 0, answers) if auto else act(table, mid, cid, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        p = result['reaction']; prompts.append(p)
        rid = p['context']['reaction_source_id']
        choice = (picks or {}).get(rid, 'first' if rid.startswith('choice:') else None)
        answer = {**p['context'], 'selection':'USE' if choice is not None else 'DECLINE'}
        if choice is not None and p.get('choice'):
            answer['option_ids'] = ([o['id'] for o in p['choice']['options'][:int(p['choice'].get('minimum') or 1)]]
                                    if choice == 'first' else choice if isinstance(choice,list) else [choice])
        answers.append(answer)
    raise AssertionError('Too many prompts')


def settle_path(table, mid, actor_id, waypoints, picks=None):
    """Commit an explicit voluntary route and answer its real reaction checkpoints."""
    decision = table.state(mid)['menu']
    preview = table.preview_move_path(mid, decision['decision_id'], decision['state_version'], actor_id, waypoints)
    route = preview['candidate']
    answers, prompts = [], []
    for _ in range(50):
        result = table.commit_move_path(mid, route['candidate_id'], route['decision_id'], route['state_version'],
                                        actor_id, waypoints, reactions=answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        prompt = result['reaction']; prompts.append(prompt)
        rid = prompt['context']['reaction_source_id']
        choice = (picks or {}).get(rid, 'first' if rid.startswith('choice:') else None)
        answer = {**prompt['context'], 'selection':'USE' if choice is not None else 'DECLINE'}
        if choice is not None and prompt.get('choice'):
            answer['option_ids'] = ([o['id'] for o in prompt['choice']['options'][:int(prompt['choice'].get('minimum') or 1)]]
                                    if choice == 'first' else choice if isinstance(choice,list) else [choice])
        answers.append(answer)
    raise AssertionError('Too many movement prompts')


def legal_route(engine, actor, start, goal):
    """Find a shortest adjacent route with movement's own per-step validator."""
    from collections import deque
    from combat.gate2_runtime_models import Position
    from combat import flight
    start = Position.model_validate(start)
    goal = Position.model_validate(goal)
    queue, previous = deque([start]), {start: None}
    while queue:
        current = queue.popleft()
        if current == goal:
            break
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not (dx or dy):
                    continue
                nx, ny = current.x+dx, current.y+dy
                if not (0 <= nx < engine.grid.width and 0 <= ny < engine.grid.height):
                    continue
                nxt = Position(x=nx, y=ny, z=current.z)
                if nxt in previous or not flight.step_allowed(engine, actor, current, nxt, mode='walk', observed=True):
                    continue
                previous[nxt] = current
                queue.append(nxt)
    if goal not in previous:
        raise AssertionError(f'No legal route from {start} to {goal}')
    path, cell = [], goal
    while cell is not None:
        path.append(cell.model_dump(mode='json'))
        cell = previous[cell]
    return list(reversed(path))


def prepare(bundles):
    setup(bundles)
    for b in bundles:
        b['actor_template']['maximum_hp'] = 1000
        # A genuine sealed native melee attack supplies a hit that consumes all
        # the guard's HP; another native attack is explicitly ranged.
        owner = b['actor_id']
        from tests.worker2_support import sealed_native_attack
        for name, melee in [('Melee impact', True), ('Ranged impact', False)]:
            sid = sealed_native_attack(b, name, attack_bonus=100, modifier=40, range_ft=5 if melee else 60)
            a = next(a for a in b['action_catalog'] if a['source_definition_id'] == sid)
            a['economy'] = 'NONE'
            if melee:
                a['reach_ft'] = 5
                a['range_ft'] = None
        add_action(b, 'Knock down', [{'type': 'condition', 'condition': 'prone', 'applies_to': 'self'}], target='SELF')
        add_action(b, 'Bigger guard', [{'type': 'temp_hp', 'flat': 100, 'applies_to': 'self'}], target='SELF')
        add_action(b, 'End winter', [{'type': 'remove_condition', 'condition': 'winter_crucible', 'applies_to': 'self'}], target='SELF')
        add_action(b, 'Ice study', [{'type': 'contest_against', 'actor_check': {
            'kind': 'ability', 'ability': 'INT', 'skill': 'Arcana', 'hazards': ['ice_structure']},
            'target_check': {'kind': 'dc', 'dc': 10}, 'on_success': [], 'on_fail': []}])
        add_action(b, 'Ordinary study', [{'type': 'contest_against', 'actor_check': {
            'kind': 'ability', 'ability': 'INT', 'skill': 'Arcana'},
            'target_check': {'kind': 'dc', 'dc': 10}, 'on_success': [], 'on_fail': []}])
        add_action(b, 'Move foe', [{'type': 'forced_movement', 'mode': 'push', 'distance_ft': 10, 'applies_to': 'target'}])
        add_action(b, 'Wall breaker', [{'type':'wall_attack','count':1}], target='CELL', typed={'wall_weapon': {'fixed_damage':50,'damage_type':'FIRE'}, 'numbers': {'pb':4,'cl':15,'key_mod':2,'attack_bonus':100}})
        add_action(b, 'Erase mark', [{'type': 'spend_mark', 'mark': 'Fracture Mark', 'applies_to': 'target'}])
        next(a for a in b['action_catalog'] if a['display_name']=='Wall breaker')['parameters'].update(any_cell=True, wall_attack=True)
        seal(b)


def cold(tmp_path, mid):
    service = CombatService(ROOT, tmp_path)
    loaded = service._load_session(mid)
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


def owned_insight(monkeypatch):
    """Put Insights in their real sheet field before the compiler sees them."""
    import tests.worker2_support as support
    real = support.sheet
    def documents(ids, **kw):
        doc = real(ids, **kw)
        selected = [k for k in ids if k.startswith('insight.')]
        doc.setdefault('spheres_and_talents', {})['cultivation_insight_record_ids'] = selected
        return doc
    monkeypatch.setattr(support, 'sheet', documents)


def hit(table, combat, mid, name, target, picks=None):
    # Native natural 1 remains a real miss: find an actual hit rather than
    # replacing the roller. These free setup attacks do not replace Ice rows.
    for _ in range(5):
        before = len(combat._load_session(mid).engine.events)
        prompts = settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, picks or QUIET)
        events = combat._load_session(mid).engine.events[before:]
        if any(e.event_type == 'DAMAGE_COMMITTED' for e in events):
            return prompts
    raise AssertionError('No landed native hit')


@pytest.mark.parametrize('target', [OWNER, ALLY])
def test_guard_consuming_hit_still_marks_once_and_reloads(tmp_path, target):
    combat, table, mid = fixture(tmp_path, [T+'FROST_SHEATHED_GUARD'], owner_ac=0,
                               foe_position={'x':3,'y':5}, ally_position={'x':4,'y':5}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Frost-Sheathed Guard', target=target).candidate_id, QUIET)
    e = cold(tmp_path, mid)
    assert e.state.actors[target].temporary_hp == 6
    assert next(c for c in e.state.actors[target].conditions.values() if c.condition_id == GUARD).data.get('grant_sequence')
    turn(table, mid, FOE)
    hit(table, combat, mid, 'Melee impact', target)
    e = cold(tmp_path, mid)
    assert e.state.actors[target].temporary_hp == 0
    assert marked(e.state.actors[FOE], OWNER)
    assert next(c for c in e.state.actors[target].conditions.values() if c.condition_id == GUARD).data['used'] == 1


@pytest.mark.parametrize('case', ['ranged', 'replaced', 'rejected'])
def test_guard_requires_its_actual_pool_and_melee_hit(tmp_path, case):
    combat, table, mid = fixture(tmp_path, [T+'FROST_SHEATHED_GUARD'], owner_ac=0,
                               foe_position={'x':3,'y':5}, bundle_transform=prepare)
    if case == 'rejected':
        settle(table, mid, candidate(combat, mid, 'Bigger guard').candidate_id, QUIET)
    settle(table, mid, candidate(combat, mid, 'Frost-Sheathed Guard', target=OWNER).candidate_id, QUIET)
    if case == 'replaced':
        settle(table, mid, candidate(combat, mid, 'Bigger guard').candidate_id, QUIET)
    turn(table, mid, FOE)
    hit(table, combat, mid, 'Ranged impact' if case == 'ranged' else 'Melee impact', OWNER)
    assert not marked(cold(tmp_path, mid).state.actors[FOE], OWNER)


@pytest.mark.parametrize('accept', [True, False])
def test_winter_native_prone_is_optional_once_per_fight(tmp_path, monkeypatch, accept):
    owned_insight(monkeypatch)
    combat, table, mid = fixture(tmp_path, [T+'FROST_SHEATHED_GUARD', WINTER], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id, QUIET)
    # Both setup paths ultimately call the same native condition boundary.
    prompts = settle(table, mid, candidate(combat, mid, 'Knock down').candidate_id,
                     {**QUIET, 'choice:needle.winter_foot': 'stay' if accept else None})
    p = asked(prompts, 'choice:needle.winter_foot')
    assert p and p[0]['context']['reactor_id'] == OWNER
    e = cold(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.prone' for c in e.state.actors[OWNER].conditions.values()) == (not accept)
    assert any(c.condition_id == 'condition:typed.winter_sure_foot_used' for c in e.state.actors[OWNER].conditions.values()) == accept
    if accept:
        second = settle(table, mid, candidate(combat, mid, 'Knock down').candidate_id, QUIET)
        assert not asked(second, 'choice:needle.winter_foot')
        assert any(c.condition_id == 'condition:typed.prone' for c in cold(tmp_path, mid).state.actors[OWNER].conditions.values())


def test_winter_bonus_is_one_addition_to_self_ice_grant(tmp_path, monkeypatch):
    owned_insight(monkeypatch)
    combat, table, mid = fixture(tmp_path, [T+'FROST_SHEATHED_GUARD', WINTER], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Frost-Sheathed Guard', target=OWNER).candidate_id, QUIET)
    e = cold(tmp_path, mid)
    assert e.state.actors[OWNER].temporary_hp == 10
    offers = [ev for ev in e.events if ev.event_type == 'TEMP_HP_GRANTED' and ev.target_ids == (OWNER,)]
    assert len(offers) == 1 and offers[0].payload['offered'] == 10
    assert e.state.actors[ALLY].temporary_hp == 0


@pytest.mark.parametrize('keep', [True, False])
def test_shatter_without_waste_keeps_only_chosen_space_and_expires(tmp_path, monkeypatch, keep):
    owned_insight(monkeypatch)
    combat, table, mid = fixture(tmp_path, [T+'SHATTER_BLOOM', WASTE], foe_position=FOE_CELL, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id, QUIET)
    reach(table, mid, FOE, QUIET); reach(table, mid, OWNER, QUIET)
    before = lattice_cells(cold(tmp_path, mid), OWNER)
    assert (2,5) in before
    prompts = settle(table, mid, candidate(combat, mid, 'Shatter Bloom').candidate_id,
                     {**QUIET, 'choice:needle.bloom_spaces': ['2,5'], 'choice:needle.bloom_type': 'COLD',
                      'choice:needle.preserve_lattice': 'keep' if keep else None})
    assert asked(prompts, 'choice:needle.preserve_lattice')
    e = cold(tmp_path, mid)
    assert ((2,5) in lattice_cells(e, OWNER)) == keep
    if keep:
        z = next(z for z in lattice_zones(e, OWNER) if (z.center.x,z.center.y) == (2,5))
        assert z.trigger_profile['end_after_owner_turn'] == e.state.actors[OWNER].turns_started + 1
        reach(table, mid, FOE, QUIET); reach(table, mid, OWNER, QUIET)
        settle(table, mid, table.state(mid)['menu']['end_turn'], QUIET)
        assert (2,5) not in lattice_cells(cold(tmp_path, mid), OWNER)


@pytest.mark.parametrize('extra', [True, False])
def test_scholar_additional_space_has_its_own_short_deadline(tmp_path, monkeypatch, extra):
    owned_insight(monkeypatch)
    combat, table, mid = fixture(tmp_path, [T+'SHATTER_BLOOM', SCHOLAR], bundle_transform=prepare)
    prompts = settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id,
                     {**QUIET, 'choice:needle.scholar_space': 'cell:6,6' if extra else None})
    assert asked(prompts, 'choice:needle.scholar_space')
    e = cold(tmp_path, mid)
    added = [z for z in lattice_zones(e, OWNER) if z.trigger_profile.get('name') == 'Lattice Scholar']
    assert len(lattice_zones(e, OWNER)) == 4 + int(extra)
    assert len(added) == int(extra)
    if extra:
        assert added[0].center.x == 6 and added[0].center.y == 6
        reach(table, mid, FOE, QUIET); reach(table, mid, OWNER, QUIET)
        settle(table, mid, table.state(mid)['menu']['end_turn'], QUIET)
        e = cold(tmp_path, mid)
        assert not e.state.zones[added[0].zone_id].active
        assert len(lattice_zones(e, OWNER)) == 4


def test_scholar_advantage_is_scoped_to_printed_intelligence_topics(tmp_path, monkeypatch):
    owned_insight(monkeypatch)
    combat, table, mid = fixture(tmp_path, [T+'SHATTER_BLOOM', SCHOLAR], bundle_transform=prepare)
    for name, mode in [('Ice study','ADVANTAGE'), ('Ordinary study','NORMAL')]:
        settle(table, mid, candidate(combat, mid, name, target=FOE).candidate_id, QUIET)
        e = cold(tmp_path, mid)
        checks = [ev for ev in e.events if ev.event_type == 'CHECK_ROLLED']
        assert checks[-1].payload['actor']['mode'] == mode


def painted_arena(monkeypatch, name):
    original = CombatService.factory_arenas
    def arena(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        bid = self.tabletop_maps.save({'display_name':'Ice second pass test', 'width_squares':14,
            'height_squares':12, 'walls':[], 'materials':[{'material':'terrain:'+name,'cells':[[4,6],[5,6]]}],
            'starts':{'team1':[[3,6],[3,7]], 'team2':[[8,6]]}})['map_id']
        result['battlefield:factory_pillar_arena'] = original(self, *args, **kwargs)['battlefield:map.'+bid]
        return result
    monkeypatch.setattr(CombatService, 'factory_arenas', arena)


@pytest.mark.parametrize('terrain', ['mundane ice', 'mundane snow', 'loose rubble'])
def test_sure_footwork_mundane_terrain_cost_is_narrow(tmp_path, monkeypatch, terrain):
    owned_insight(monkeypatch); painted_arena(monkeypatch, terrain)
    combat, table, mid = fixture(tmp_path, [T+'SHATTER_BLOOM', FOOT], foe_position={'x':8,'y':6}, ally_position={'x':3,'y':7}, bundle_transform=prepare)
    settle(table, mid, next(c for c in combat._load_session(mid).engine.legal_candidates() if c.kind == 'MOVE' and c.destination and (c.destination.x,c.destination.y) == (4,6)).candidate_id, QUIET)
    e = cold(tmp_path, mid)
    assert e.state.actors[OWNER].movement_remaining_ft == (25 if terrain != 'loose rubble' else 20)


def test_sure_footwork_stands_for_five_on_own_lattice_with_disciple(tmp_path, monkeypatch):
    owned_insight(monkeypatch)
    combat, table, mid = fixture(tmp_path, [T+'SURE_FOOTED_DISCIPLE', FOOT], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id, QUIET)
    settle(table, mid, candidate(combat, mid, 'Knock down').candidate_id, QUIET)
    before = cold(tmp_path, mid).state.actors[OWNER].movement_remaining_ft
    settle(table, mid, next(c for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id == 'system:combat.stand_up').candidate_id, QUIET)
    assert cold(tmp_path, mid).state.actors[OWNER].movement_remaining_ft == before - 5


@pytest.mark.parametrize('auto', [False, True])
def test_crucible_extra_creation_and_enemy_only_destruction_choice(tmp_path, auto):
    combat, table, mid = fixture(tmp_path, [T+'IMMORTAL_WINTER_CRUCIBLE', T+'SHATTER_BLOOM'],
        foe_position={'x':2,'y':6}, ally_position={'x':3,'y':5}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Immortal Winter Crucible').candidate_id, QUIET)
    reach(table, mid, FOE, QUIET); reach(table, mid, OWNER, QUIET)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id, QUIET)
    assert len(lattice_zones(cold(tmp_path, mid), OWNER)) == 5
    reach(table, mid, FOE, QUIET); reach(table, mid, OWNER, QUIET)
    cid = candidate(combat, mid, 'Shatter Bloom').candidate_id
    if auto:
        real = combat.controller
        class BloomController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = BloomController()
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, cid, {**QUIET, 'choice:needle.bloom_spaces':['2,5'],
        'choice:needle.crucible_damage':FOE, 'choice:needle.crucible_type':'PIERCING'}, auto=auto)
    e = cold(tmp_path, mid)
    extra = [ev for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED' and ev.source_definition_id == T+'IMMORTAL_WINTER_CRUCIBLE']
    assert extra and all(ev.target_ids == (FOE,) and ev.payload['rolled_or_pending_damage'] == 4 for ev in extra)
    # Ally and owner are also within five feet of the shattered space, but
    # the printed hostile-only Crucible rider can never choose them.
    if not auto:
        p = asked(prompts, 'choice:needle.crucible_damage')[0]
        assert {o['id'] for o in p['choice']['options']} == {FOE}


def test_crucible_ending_requires_half_of_active_spaces(tmp_path):
    combat, table, mid = fixture(tmp_path, [T+'IMMORTAL_WINTER_CRUCIBLE'], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Immortal Winter Crucible').candidate_id, QUIET)
    reach(table, mid, FOE, QUIET); reach(table, mid, OWNER, QUIET)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id, QUIET)
    before = lattice_cells(cold(tmp_path, mid), OWNER)
    assert len(before) == 5
    prompts = settle(table, mid, candidate(combat, mid, 'End winter').candidate_id, QUIET)
    p = asked(prompts, 'choice:needle.crucible_half')[0]
    assert p['context']['reactor_id'] == OWNER
    e = cold(tmp_path, mid)
    assert len(lattice_cells(e, OWNER)) == 3


def test_icefall_initial_every_creature_and_free_shatter_without_mark(tmp_path):
    combat, table, mid = fixture(tmp_path, [T+'WORLD_FANG_ICEFALL'], owner_ac=0, foe_position={'x':6,'y':6}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'World-Fang Icefall', at=(6,6)).candidate_id, QUIET)
    e = cold(tmp_path, mid)
    damage = [ev for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED']
    assert {ev.target_ids[0] for ev in damage} >= {OWNER, ALLY, FOE}
    assert any(z.trigger_profile.get('ice_free_shatter') and z.trigger_profile.get('difficult') == 'hostile' for z in lattice_zones(e, OWNER))
    settle(table, mid, candidate(combat, mid, 'Erase mark', target=FOE).candidate_id, QUIET)
    assert not marked(cold(tmp_path, mid).state.actors[FOE], OWNER)
    prompts = settle(table, mid, candidate(combat, mid, 'Move foe', target=FOE).candidate_id,
                     {**QUIET, 'choice:needle.icefall_free':'shatter'})
    assert asked(prompts, 'choice:needle.icefall_free')
    e = cold(tmp_path, mid)
    hits = [ev for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED' and ev.source_definition_id == 'ICE_BASE_SPENDING_A_FRACTURE_MARK']
    assert hits and hits[-1].target_ids == (FOE,)
    assert e.state.actors[OWNER].turn_flags['ice_spent_round'].endswith(':1')
    assert e.state.actors[OWNER].resources['resource:core.qi'] == 94


@pytest.mark.parametrize('start_x,center_x,end_x', [(4, 2, 10), (0, 7, 17)])
def test_icefall_qualifying_traversal_survives_exit_and_resolves_at_path_checkpoint(tmp_path, monkeypatch, start_x, center_x, end_x):
    """The first 10 feet inside count even when one forced move exits the cylinder."""
    owned_insight(monkeypatch)
    from tests.h1_support import sheet
    fast_foe = sheet([])
    fast_foe['ability_scores_and_statistics']['speed']['walking_ft'] = 240
    owner_position = {'x':2,'y':8} if center_x == 7 else {'x':2,'y':6}
    combat, table, mid = fixture(tmp_path, [T+'WORLD_FANG_ICEFALL', FOOT],
        foe_position={'x':start_x,'y':6}, positions={OWNER:owner_position, ALLY:{'x':3,'y':7}, FOE:{'x':start_x,'y':6}},
        foe_sheet=fast_foe, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'World-Fang Icefall', at=(center_x,6)).candidate_id, QUIET)
    settle(table, mid, candidate(combat, mid, 'Erase mark', target=FOE).candidate_id, QUIET)
    e = cold(tmp_path, mid)
    stand = next((c for c in e.legal_candidates() if c.source_definition_id == 'system:combat.stand_up'), None)
    if stand:
        settle(table, mid, stand.candidate_id, QUIET)
    turn(table, mid, FOE)
    e = cold(tmp_path, mid)
    path = (legal_route(e, e.state.actors[FOE], e.state.actors[FOE].position, {'x':5,'y':6})[:-1]
            + legal_route(e, e.state.actors[FOE], {'x':5,'y':6}, {'x':17,'y':5})
            if center_x == 7 else
            [{'x':4,'y':6},{'x':5,'y':6},{'x':6,'y':6},{'x':7,'y':6},
             {'x':8,'y':5},{'x':9,'y':5},{'x':10,'y':5}])
    prompts = settle_path(table, mid, FOE, path,
                          {'choice:needle.icefall_free':'shatter',
                           'choice:needle.shatter_space':'first', 'choice:needle.shatter_type':'COLD'})
    e = cold(tmp_path, mid)
    assert asked(prompts, 'choice:needle.icefall_free')
    assert e.state.actors[FOE].position.x >= end_x
    assert any(ev.event_type == 'DAMAGE_COMMITTED' and ev.source_definition_id == 'ICE_BASE_SPENDING_A_FRACTURE_MARK'
               and ev.target_ids == (FOE,) for ev in e.events)


def test_crucible_partial_radial_lattice_uses_saved_cells_after_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [T+'IMMORTAL_WINTER_CRUCIBLE', T+'WORLD_FANG_ICEFALL'],
        foe_position={'x':6,'y':6}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Immortal Winter Crucible').candidate_id, QUIET)
    reach(table, mid, FOE, QUIET); reach(table, mid, OWNER, QUIET)
    settle(table, mid, candidate(combat, mid, 'World-Fang Icefall', at=(6,6)).candidate_id, QUIET)
    before = cold(tmp_path, mid)
    radial = next(z for z in zones.typed_zones(before) if z.owner_id == OWNER and z.active
                  and z.radius_cells > 0 and z.trigger_profile.get('ice_free_shatter'))
    assert radial.radius_cells > 0 and len(radial.affected_cells) > 1
    chosen_cell = radial.affected_cells[0]
    settle(table, mid, candidate(combat, mid, 'End winter').candidate_id, QUIET)
    # The table choice removes half the global lattice. Select a radial cell
    # explicitly so the test exercises the root geometry seam.
    e = cold(tmp_path, mid)
    remaining = e.state.zones[radial.zone_id]
    assert chosen_cell not in remaining.affected_cells
    from combat.spatial_areas import zone_contains, display_cells
    from combat.gate2_runtime_models import Position
    point_actor = e.state.actors[FOE]
    point_actor.position = Position(x=chosen_cell.x, y=chosen_cell.y)
    assert not zone_contains(e, point_actor, remaining)
    assert (chosen_cell.x, chosen_cell.y) not in {(p.x,p.y) for p in display_cells(e, remaining)}


def test_preserved_radial_lattice_cell_is_single_after_reload(tmp_path, monkeypatch):
    owned_insight(monkeypatch)
    def failed_concentration_save(bundles):
        prepare(bundles)
        bundles[0]['actor_template']['saving_throws']['CON'] = -100
        seal(bundles[0])
    combat, table, mid = fixture(tmp_path, [T+'SHATTER_BLOOM', T+'ICE_DOMAIN_PALACE_OF_WRITTEN_WINTER', WASTE],
        foe_position={'x':4,'y':6}, positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':7},FOE:{'x':4,'y':6}},
        bundle_transform=failed_concentration_save)
    settle(table, mid, candidate(combat, mid, 'Ice Domain: Palace of Written Winter').candidate_id, QUIET)
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, 'Shatter Bloom').candidate_id,
        {'choice:needle.bloom_spaces':'first', 'choice:needle.bloom_type':'COLD',
         'choice:needle.preserve_lattice':'keep'})
    assert asked(prompts, 'choice:needle.preserve_lattice')
    e = cold(tmp_path, mid)
    kept = next(z for z in zones.typed_zones(e) if z.owner_id == OWNER and z.active
                and z.trigger_profile.get('footprint_is_authoritative')
                and z.trigger_profile.get('end_after_owner_turn'))
    assert len(kept.affected_cells) == 1
    from combat.spatial_areas import zone_contains, display_cells
    from combat.gate2_runtime_models import Position
    cell = kept.affected_cells[0]
    probe = e.state.actors[FOE].model_copy(update={'position':Position(x=cell.x,y=cell.y,z=cell.z)})
    assert zone_contains(e, probe, kept)
    probe.position = Position(x=cell.x+1,y=cell.y,z=cell.z)
    assert not zone_contains(e, probe, kept)
    assert {(p.x,p.y) for p in display_cells(e, kept)} == {(cell.x,cell.y)}
    # The long-lived radial parent must stop supplying the preserved cell;
    # otherwise the short-lived copy expires while the old radius still covers it.
    parent = next(z for z in zones.typed_zones(e) if z.owner_id == OWNER and z.active
                  and z.zone_id != kept.zone_id and z.radius_cells > 0
                  and z.source_definition_id == kept.source_definition_id)
    probe.position = Position(x=cell.x, y=cell.y, z=cell.z)
    assert parent.trigger_profile.get('footprint_is_authoritative')
    assert not zone_contains(e, probe, parent)
    assert (cell.x, cell.y) not in {(p.x, p.y) for p in display_cells(e, parent)}
    assert parent.concentration_link
    assert not kept.concentration_link
    assert kept.trigger_profile.get('ends_with') == parent.zone_id
    # Damage forces a failed native Concentration save through the service.
    turn(table, mid, FOE)
    hit(table, combat, mid, 'Melee impact', OWNER)
    e = cold(tmp_path, mid)
    assert not any(z.active and z.zone_id == kept.zone_id for z in e.state.zones.values())


@pytest.mark.parametrize('case', ['accept', 'decline', 'no_domain', 'ally'])
def test_palace_post_movement_panels_are_optional_defended_and_expire(tmp_path, case):
    combat, table, mid = fixture(tmp_path, [T+'PALACE_WHERE_FOOTSTEPS_BECOME_WALLS',
        T+'ICE_DOMAIN_PALACE_OF_WRITTEN_WINTER'], foe_position={'x':6,'y':6}, bundle_transform=prepare)
    if case != 'no_domain':
        settle(table, mid, candidate(combat, mid, 'Ice Domain: Palace of Written Winter').candidate_id, QUIET)
    before = cold(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    target = ALLY if case == 'ally' else FOE
    prompts = settle(table, mid, candidate(combat, mid, 'Move foe', target=target).candidate_id,
                     {**QUIET, 'choice:needle.palace_panels':None if case == 'decline' else 'first'})
    e = cold(tmp_path, mid)
    panels = [z for z in zones.typed_zones(e) if z.source_definition_id == T+'PALACE_WHERE_FOOTSTEPS_BECOME_WALLS']
    expected = case == 'accept'
    assert bool(asked(prompts, 'choice:needle.palace_panels')) == (case in {'accept','decline'})
    assert len(panels) == (4 if expected else 0)
    assert e.state.actors[OWNER].resources['resource:core.qi'] == before - (2 if expected else 0)
    if panels:
        from combat.ext.docket_walls import stats
        occupied = {c for a in e.state.actors.values() for c in e._actor_cells(a)}
        assert all((z.center.x,z.center.y) not in occupied for z in panels)
        assert all(z.trigger_profile['start_of_owner_turn'] == e.state.actors[OWNER].turns_started+1 for z in panels)
        assert all(stats(z)['ac'] == 16 and stats(z)['hp'] == 40 and 'FIRE' in stats(z)['vulnerable'] for z in panels)
        assert all((z.center.x,z.center.y) in e.grid.blocked and (z.center.x,z.center.y) in e.grid.opaque for z in panels)
        reach(table, mid, FOE, QUIET); reach(table, mid, OWNER, QUIET)
        assert not any(z.active for z in cold(tmp_path, mid).state.zones.values() if z.zone_id in {p.zone_id for p in panels})


def test_crucible_native_wall_creation_and_destroyed_section(tmp_path):
    combat, table, mid = fixture(tmp_path, [T+'IMMORTAL_WINTER_CRUCIBLE', T+'GLACIER_WALL'],
        foe_position={'x':6,'y':6}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Immortal Winter Crucible').candidate_id, QUIET)
    reach(table, mid, FOE, QUIET); reach(table, mid, OWNER, QUIET)
    prompts = settle(table, mid, candidate(combat, mid, 'Glacier Wall', at=(6,5)).candidate_id,
                     {**QUIET, 'choice:needle.crucible_space':'cell:3,4'})
    assert asked(prompts, 'choice:needle.crucible_space')
    e = cold(tmp_path, mid)
    assert any(z.trigger_profile.get('name') == 'Immortal Winter Crucible' and (z.center.x,z.center.y) == (3,4)
               for z in zones.typed_zones(e))
    for _ in range(5):
        e = cold(tmp_path, mid)
        wall = next((z for z in zones.typed_zones(e) if z.trigger_profile.get('wall') and
                     any((p.x,p.y)==(6,5) for p in z.affected_cells)), None)
        if wall is None:
            break
        settle(table, mid, candidate(combat, mid, 'Wall breaker', at=(6,5)).candidate_id,
               {**QUIET, 'choice:needle.crucible_damage':FOE, 'choice:needle.crucible_type':'COLD'})
    e = cold(tmp_path, mid)
    assert not any((p.x,p.y)==(6,5) for z in zones.typed_zones(e) if z.trigger_profile.get('wall') for p in z.affected_cells)
    assert any(ev.event_type=='DAMAGE_COMMITTED' and ev.source_definition_id==T+'IMMORTAL_WINTER_CRUCIBLE'
               and ev.target_ids==(FOE,) and ev.payload['rolled_or_pending_damage']==4 for ev in e.events)


@pytest.mark.parametrize('feature', ['WORLD_FANG_ICEFALL', 'PALACE_WHERE_FOOTSTEPS_BECOME_WALLS'])
@pytest.mark.parametrize('altitude', [0, 20])
def test_movement_trigger_uses_actual_area_volume_not_ground_projection(tmp_path, feature, altitude):
    def flying(bundles):
        prepare(bundles)
        bundles[2]['actor_template'].update(fly_speed_ft=60, hover=True, speed_ft=60)
        seal(bundles[2])
    ids = [T+feature]
    if feature.startswith('PALACE'):
        ids.append(T+'ICE_DOMAIN_PALACE_OF_WRITTEN_WINTER')
    combat, table, mid = fixture(tmp_path, ids, foe_position={'x':6,'y':6,'z':altitude}, bundle_transform=flying)
    if feature.startswith('PALACE'):
        settle(table, mid, candidate(combat, mid, 'Ice Domain: Palace of Written Winter').candidate_id, QUIET)
        question = 'choice:needle.palace_panels'
    else:
        settle(table, mid, candidate(combat, mid, 'World-Fang Icefall', at=(6,6)).candidate_id, QUIET)
        question = 'choice:needle.icefall_free'
    e = cold(tmp_path, mid)
    if altitude:
        assert not any(ev.event_type=='DAMAGE_COMMITTED' and ev.target_ids==(FOE,) for ev in e.events)
    reach(table, mid, FOE, QUIET)
    # A ground creature may have been knocked Prone by Icefall's initial save.
    e = cold(tmp_path, mid)
    stand = next((c for c in e.legal_candidates() if c.source_definition_id=='system:combat.stand_up'), None)
    if stand:
        settle(table, mid, stand.candidate_id, QUIET)
    e = cold(tmp_path, mid)
    step = next(c for c in e.legal_candidates() if c.kind=='MOVE' and c.destination and
                (c.destination.x,c.destination.y,c.destination.z)==(8,6,altitude))
    prompts = settle(table, mid, step.candidate_id, QUIET)
    assert bool(asked(prompts, question)) == (altitude == 0)
    e = cold(tmp_path, mid)
    assert e.state.actors[FOE].position.z == altitude


def test_crucible_free_mark_is_separate_from_markless_icefall_round_debit(tmp_path):
    combat, table, mid = fixture(tmp_path, [T+'IMMORTAL_WINTER_CRUCIBLE', T+'WORLD_FANG_ICEFALL'],
        foe_position={'x':6,'y':6}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Immortal Winter Crucible').candidate_id, QUIET)
    reach(table, mid, FOE, QUIET); reach(table, mid, OWNER, QUIET)
    settle(table, mid, candidate(combat, mid, 'World-Fang Icefall', at=(6,6)).candidate_id, QUIET)
    settle(table, mid, candidate(combat, mid, 'Erase mark', target=FOE).candidate_id, QUIET)
    settle(table, mid, candidate(combat, mid, 'Move foe', target=FOE).candidate_id,
           {**QUIET,'choice:needle.icefall_free':'shatter'})
    e = cold(tmp_path, mid)
    assert e.state.actors[OWNER].turn_flags['ice_spent_round'].endswith(':1')
    assert 'ice_crucible_free_turn' not in e.state.actors[OWNER].turn_flags
    settle(table, mid, candidate(combat, mid, 'Mark foe', target=FOE).candidate_id, QUIET)
    prompts = hit(table, combat, mid, 'Ranged impact', FOE, {'choice:needle.fracture_response':'brittle'})
    assert asked(prompts, 'choice:needle.fracture_response')
    e = cold(tmp_path, mid)
    assert not marked(e.state.actors[FOE], OWNER)
    assert e.state.actors[OWNER].turn_flags['ice_spent_round'].endswith(':1')
    assert e.state.actors[OWNER].turn_flags['ice_crucible_free_turn'] == e.state.actors[OWNER].turns_started
    settle(table, mid, candidate(combat, mid, 'Mark foe', target=FOE).candidate_id, QUIET)
    prompts = hit(table, combat, mid, 'Ranged impact', FOE, QUIET)
    assert not asked(prompts, 'choice:needle.fracture_response')
    assert marked(cold(tmp_path, mid).state.actors[FOE], OWNER)


def test_icefall_forms_lattice_before_winter_body_prevents_initial_prone(tmp_path, monkeypatch):
    owned_insight(monkeypatch)
    def failed_save(bundles):
        prepare(bundles)
        bundles[0]['actor_template']['saving_throws']['DEX'] = -100
        seal(bundles[0])
    combat, table, mid = fixture(tmp_path, [T+'WORLD_FANG_ICEFALL', WINTER],
        foe_position={'x':6,'y':6}, bundle_transform=failed_save)
    prompts = settle(table, mid, candidate(combat, mid, 'World-Fang Icefall', at=(6,6)).candidate_id,
                     {**QUIET,'choice:needle.winter_foot':'stay'})
    assert asked(prompts, 'choice:needle.winter_foot')
    e = cold(tmp_path, mid)
    owner = e.state.actors[OWNER]
    assert owner.current_hp < owner.maximum_hp
    assert not any(c.condition_id=='condition:typed.prone' for c in owner.conditions.values())
    assert any(c.condition_id=='condition:typed.winter_sure_foot_used' for c in owner.conditions.values())


def test_authoritative_footprint_keeps_native_vertical_bounds_after_reload(tmp_path, monkeypatch):
    """A reduced footprint narrows columns only; it never invents altitude.

    Shatter Without Waste preserves one Lattice Space whose stamped footprint
    is authoritative. Its native zero-radius rule owns exactly its own plane,
    so a creature on that column one level up is outside the space.
    """
    owned_insight(monkeypatch)
    combat, table, mid = fixture(tmp_path, [T+'SHATTER_BLOOM', WASTE],
                                 foe_position=FOE_CELL, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id, QUIET)
    reach(table, mid, FOE, QUIET); reach(table, mid, OWNER, QUIET)
    prompts = settle(table, mid, candidate(combat, mid, 'Shatter Bloom').candidate_id,
                     {**QUIET, 'choice:needle.bloom_spaces': 'first', 'choice:needle.bloom_type': 'COLD',
                      'choice:needle.preserve_lattice': 'keep'})
    assert asked(prompts, 'choice:needle.preserve_lattice')
    e = cold(tmp_path, mid)
    from combat.spatial_areas import zone_contains
    from combat.gate2_runtime_models import Position
    kept = next(z for z in zones.typed_zones(e) if z.owner_id == OWNER and z.active
                and z.trigger_profile.get('footprint_is_authoritative')
                and len(z.affected_cells) == 1)
    # The preserved space is a zero-radius single cell: it owns its own plane.
    assert kept.radius_cells == 0
    cell = kept.affected_cells[0]

    def probe(z):
        actor = e.state.actors[FOE].model_copy(update={'position': Position(x=cell.x, y=cell.y, z=z)})
        return zone_contains(e, actor, kept)

    assert probe(cell.z) is True, 'the preserved space still contains its own cell'
    # Clipping the footprint must not extend the space above or below its plane.
    assert probe(cell.z + 1) is False
    assert probe(cell.z + 2) is False


def test_crucible_damage_prompt_names_the_affected_creature(tmp_path):
    """The damage-type choice must identify the victim it applies to."""
    combat, table, mid = fixture(tmp_path, [T+'IMMORTAL_WINTER_CRUCIBLE', T+'GLACIER_WALL'],
                                 foe_position={'x':6,'y':6}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Immortal Winter Crucible').candidate_id, QUIET)
    reach(table, mid, FOE, QUIET); reach(table, mid, OWNER, QUIET)
    settle(table, mid, candidate(combat, mid, 'Glacier Wall', at=(6,5)).candidate_id,
           {**QUIET, 'choice:needle.crucible_space':'cell:3,4'})
    prompts = []
    for _ in range(5):
        e = cold(tmp_path, mid)
        wall = next((z for z in zones.typed_zones(e) if z.trigger_profile.get('wall') and
                     any((p.x,p.y)==(6,5) for p in z.affected_cells)), None)
        if wall is None:
            break
        prompts = settle(table, mid, candidate(combat, mid, 'Wall breaker', at=(6,5)).candidate_id,
                         {**QUIET, 'choice:needle.crucible_damage':FOE, 'choice:needle.crucible_type':'COLD'})
    asked_type = asked(prompts, 'choice:needle.crucible_type')
    assert asked_type, 'the damage-type question was never asked'
    p = asked_type[0]
    victim = cold(tmp_path, mid).state.actors[FOE].display_name
    # The isolated question still tells the player which creature takes the damage.
    shown = ' '.join(str(p.get(k) or '') for k in ('title', 'summary', 'trigger', 'moment'))
    assert victim in shown, f'the damage-type question never names {victim}: {shown!r}'
    # The choice is transported against the victim it damages, not the chooser.
    assert p.get('affected') == victim
    assert any(ev.event_type == 'DAMAGE_COMMITTED' and ev.source_definition_id == T+'IMMORTAL_WINTER_CRUCIBLE'
               and ev.target_ids == (FOE,) for ev in cold(tmp_path, mid).events)


def test_winter_sure_foot_prompt_names_the_triggering_action(tmp_path, monkeypatch):
    """Sure Foot must name the action that would knock the subject down."""
    owned_insight(monkeypatch)
    combat, table, mid = fixture(tmp_path, [T+'FROST_SHEATHED_GUARD', WINTER], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id, QUIET)
    prompts = settle(table, mid, candidate(combat, mid, 'Knock down').candidate_id,
                     {**QUIET, 'choice:needle.winter_foot': 'stay'})
    p = asked(prompts, 'choice:needle.winter_foot')[0]
    context = p['context']
    action = next(a for a in combat._load_session(mid).engine.action_catalog.values()
                  if a.display_name == 'Knock down')
    # The player is told what is causing the knockdown, not just that it may happen.
    shown = ' '.join(str(p.get(k) or '') for k in ('title', 'trigger', 'moment', 'action'))
    assert action.display_name in shown, f'the Sure Foot question never names its trigger: {shown!r}'
    assert cold(tmp_path, mid).state.actors[OWNER].display_name in shown



def test_authoritative_finite_wall_retained_columns_keep_native_height_after_reload(tmp_path):
    """Crucible narrows a finite native wall and its authoritative footprint survives reload."""
    def finite_wall(bundles):
        prepare(bundles)
        for action in bundles[0]['action_catalog']:
            if action['display_name'] == 'Glacier Wall':
                wall = action['parameters']['typed']['zone_spec']['wall']
                wall.update(height_ft=10, base_altitude_ft=0)
        seal(bundles[0])

    combat, table, mid = fixture(tmp_path, [T+'IMMORTAL_WINTER_CRUCIBLE', T+'GLACIER_WALL'], foe_position={'x':6,'y':6},
                                 bundle_transform=finite_wall)
    settle(table, mid, candidate(combat, mid, 'Immortal Winter Crucible').candidate_id, QUIET)
    reach(table, mid, FOE, QUIET); reach(table, mid, OWNER, QUIET)
    settle(table, mid, candidate(combat, mid, 'Glacier Wall', at=(6,5)).candidate_id, QUIET)
    e = cold(tmp_path, mid)
    wall = next(z for z in zones.typed_zones(e) if (z.trigger_profile.get('wall') or {}).get('height_ft') == 10)
    assert len(wall.affected_cells) > 1
    original_columns = {(p.x, p.y) for p in wall.affected_cells}
    assert len(original_columns) > 1
    from tests.test_r9i_karma_persistence import act
    end_candidate = candidate(combat, mid, 'End winter').candidate_id
    pending = act(table, mid, end_candidate)
    assert pending['status'] == 'REACTION_REQUIRED', pending
    prompt = pending['reaction']
    assert prompt['context']['reaction_source_id'] == 'choice:needle.crucible_half'
    wall_options = [o for o in prompt['choice']['options']
                    if any(f'({x}, {y},' in o.get('label', '') for x, y in original_columns)]
    assert wall_options, 'the native wall sections must participate in Crucible ending choices'
    count = int(prompt['choice'].get('minimum') or 1)
    # Choose a proper subset of the wall columns for removal, then fill any
    # remaining required selections with non-wall lattice spaces.
    wall_option_ids = {o['id'] for o in wall_options}
    selected = [wall_options[0]['id']]
    selected.extend(o['id'] for o in prompt['choice']['options']
                    if o['id'] not in wall_option_ids and len(selected) < count)
    selected.extend(o['id'] for o in wall_options
                    if o['id'] not in selected and len(selected) < count)
    assert len(selected) == count and len(selected) < len(wall_options)
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': selected}
    try:
        result = act(table, mid, end_candidate, [answer])
    except Exception as exc:
        raise AssertionError(f'Crucible ending choice was rejected: selected={selected!r}, '
                             f'choice={prompt.get("choice")!r}, context={prompt.get("context")!r}') from exc
    if result['status'] == 'REACTION_REQUIRED':
        raise AssertionError(f'unexpected additional prompt after Crucible choice: {result["reaction"]}')
    assert result['status'] == 'COMMITTED', result
    e = cold(tmp_path, mid)
    from combat.spatial_areas import zone_contains
    from combat.gate2_runtime_models import Position
    live = next(z for z in zones.typed_zones(e) if z.zone_id == wall.zone_id)
    assert live.trigger_profile.get('footprint_is_authoritative'), 'Crucible ending must stamp the general footprint seam'
    surviving = next(p for p in live.affected_cells if (p.x,p.y) in original_columns)
    removed = next(cell for cell in original_columns if cell not in {(p.x,p.y) for p in live.affected_cells})
    def probe(x, y, z):
        actor = e.state.actors[FOE].model_copy(update={'position':Position(x=x,y=y,z=z)})
        return zone_contains(e, actor, live)
    assert len(live.affected_cells) < len(wall.affected_cells)
    assert not probe(*removed, 0), 'the removed column must not remain in the retained footprint'
    assert probe(surviving.x, surviving.y, surviving.z), 'surviving ground-level wall section must remain'
    assert not probe(surviving.x, surviving.y, 2), 'finite wall membership must stop at its native top'


def test_icefall_split_movement_accumulates_distance_across_a_cold_reload(tmp_path, monkeypatch):
    """Two separately committed movements still earn the one 10-foot response.

    The response is spent on the round's cumulative distance through the zone.
    A mover who crosses it in two commitments keeps the chance: the second
    commitment is measured against what the first already banked, and the
    crossing is resolved from saved state after a cold reload.
    """
    owned_insight(monkeypatch)
    from tests.h1_support import sheet
    fast_foe = sheet([])
    fast_foe['ability_scores_and_statistics']['speed']['walking_ft'] = 240
    combat, table, mid = fixture(tmp_path, [T+'WORLD_FANG_ICEFALL'], foe_position={'x':4,'y':6},
                                 positions={OWNER:{'x':2,'y':6}, FOE:{'x':4,'y':6}},
                                 foe_sheet=fast_foe, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'World-Fang Icefall', at=(2,6)).candidate_id, QUIET)
    settle(table, mid, candidate(combat, mid, 'Erase mark', target=FOE).candidate_id, QUIET)
    turn(table, mid, FOE)
    # First commitment: a single 5-foot step inside the zone banks five of the
    # required ten feet, so it is not yet a qualifying crossing.
    prompts_a = settle_path(table, mid, FOE,
                            [{'x':4,'y':6},{'x':5,'y':6}], QUIET)
    assert not asked(prompts_a, 'choice:needle.icefall_free'), 'five feet is not a qualifying crossing'
    # The cold reload must not reset the distance already banked this round.
    e = cold(tmp_path, mid)
    key = next(k for k in e.state.actors[FOE].turn_flags if k.startswith('icefall_distance_round'))
    assert int(e.state.actors[FOE].turn_flags[key]) == 5, 'the first commitment must bank 5 feet'
    # Second commitment: one more 5-foot step reaches the cumulative ten.
    prompts_b = settle_path(table, mid, FOE, [{'x':5,'y':6},{'x':6,'y':6}],
                            {**QUIET, 'choice:needle.icefall_free':'shatter',
                             'choice:needle.shatter_space':'first', 'choice:needle.shatter_type':'COLD'})
    assert asked(prompts_b, 'choice:needle.icefall_free'), 'the banked distance was lost across the reload'
    e = cold(tmp_path, mid)
    assert any(ev.event_type == 'DAMAGE_COMMITTED' and ev.source_definition_id == 'ICE_BASE_SPENDING_A_FRACTURE_MARK'
               and ev.target_ids == (FOE,) for ev in e.events)
    assert int(e.state.actors[FOE].turn_flags[key]) == -1


def test_icefall_free_shatter_preserves_accepted_rime_hook_relocation(tmp_path, monkeypatch):
    """An accepted Rime Hook after a movement-triggered Shatter Space survives.

    The response resolves at the qualifying path checkpoint, not at the movement
    endpoint. A nested Rime Hook displacement is the player's accepted choice and
    must not be overwritten when the checkpoint bookkeeping finishes.
    """
    owned_insight(monkeypatch)
    from tests.h1_support import sheet
    fast_foe = sheet([])
    fast_foe['ability_scores_and_statistics']['speed']['walking_ft'] = 240
    combat, table, mid = fixture(tmp_path, [T+'WORLD_FANG_ICEFALL', T+'RIME_HOOK'],
                                 owner_ac=0, foe_position={'x':4,'y':6},
                                 positions={OWNER:{'x':2,'y':6}, FOE:{'x':4,'y':6}},
                                 foe_sheet=fast_foe, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'World-Fang Icefall', at=(2,6)).candidate_id, QUIET)
    settle(table, mid, candidate(combat, mid, 'Erase mark', target=FOE).candidate_id, QUIET)
    turn(table, mid, FOE)
    prompts = settle_path(table, mid, FOE,
                          [{'x':4,'y':6},{'x':5,'y':6},{'x':6,'y':6},{'x':7,'y':6}],
                          {**QUIET, 'choice:needle.icefall_free':'shatter',
                           'choice:needle.shatter_space':'first', 'choice:needle.shatter_type':'COLD',
                           'choice:needle.rime_hook':'first'})
    assert asked(prompts, 'choice:needle.icefall_free')
    assert asked(prompts, 'choice:needle.rime_hook'), 'Rime Hook was never offered after Shatter Space'
    e = cold(tmp_path, mid)
    hooks = [ev for ev in e.events if ev.event_type == 'MOVEMENT_COMMITTED'
             and ev.source_definition_id == T+'RIME_HOOK' and ev.actor_id == FOE]
    assert hooks, 'Rime Hook did not relocate the target'
    # The accepted hook destination is the committed position, not the path endpoint.
    assert e.state.actors[FOE].position.model_dump(mode='json') == hooks[-1].payload['destination']


def test_off_turn_sure_foot_names_nested_shatter_response(tmp_path, monkeypatch):
    """A real Icefall Shatter Space uses a readable off-turn Sure Foot trigger."""
    owned_insight(monkeypatch)
    import tests.worker2_support as support
    foe_sheet = support.sheet([WINTER])
    def weak_foe_save(bundles):
        prepare(bundles)
        # Let the initial Icefall save succeed (roll 12 + 4); its later
        # nested Shatter save fails (roll 2 + 4), reaching Winter's response.
        bundles[2]['actor_template']['saving_throws']['DEX'] = 4
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [T+'WORLD_FANG_ICEFALL'],
        positions={OWNER:{'x':2,'y':6}, ALLY:{'x':3,'y':7}, FOE:{'x':4,'y':6}},
        foe_sheet=foe_sheet, bundle_transform=weak_foe_save)
    settle(table, mid, candidate(combat, mid, 'World-Fang Icefall', at=(2,6)).candidate_id, QUIET)
    settle(table, mid, candidate(combat, mid, 'Erase mark', target=FOE).candidate_id, QUIET)
    turn(table, mid, FOE)
    prompts = settle_path(table, mid, FOE,
        [{'x':4,'y':6},{'x':5,'y':6},{'x':6,'y':6}],
        {**QUIET, 'choice:needle.icefall_free':'shatter',
         'choice:needle.shatter_space':'first', 'choice:needle.shatter_type':'COLD',
         'choice:needle.winter_foot':'stay'})
    prompt = asked(prompts, 'choice:needle.winter_foot')[0]
    shown = ' '.join(str(prompt.get(k) or '') for k in ('title','trigger','moment','action'))
    assert 'Shatter Space (Ice Fracture Response)' in shown
    assert 'ICE_BASE_SPENDING_A_FRACTURE_MARK' not in shown
    e = cold(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.winter_sure_foot_used'
               for c in e.state.actors[FOE].conditions.values())
