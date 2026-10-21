"""New shipped scenery uses the editor pipeline and real journaled fights."""
import json
import heapq
from pathlib import Path
from statistics import median
from time import perf_counter

import pytest

from combat import object_rules
from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionIntent, CandidateKind, Position
from combat.gate3_reducer import canonical_state_sha256
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop import normalize_map, rasterize, to_battlefield
from combat.tabletop_service import TabletopService
from combat.typed_executor import _clear_line
from tests.test_builtin_arenas import _fight, ROOT
from tests.test_son198_object_catalog_engine import _install

IDS = ['builtin-willow-village-compound', 'builtin-emerald-canopy',
       'builtin-cloudwater-crossing', 'builtin-jade-sutra-hall']
SIZES = dict(zip(IDS, [(40, 30), (56, 40), (48, 32), (32, 24)]))


@pytest.mark.parametrize('map_id', IDS)
def test_editor_validation_starts_and_battlefield(tmp_path, map_id):
    doc = CombatService(ROOT, tmp_path).tabletop_maps.get(map_id)
    assert (doc['width_squares'], doc['height_squares']) == SIZES[map_id]
    assert normalize_map(doc) == {k:v for k,v in doc.items() if k != 'cells'}
    blocked, sight = rasterize(doc)
    assert blocked == set(map(tuple, doc['cells']['blocked']))
    assert sight == set(map(tuple, doc['cells']['sight']))
    object_blocks = {(o['x'], o['y']) for o in doc['objects']
                     if object_rules.stats(o)['blocks'] and not o.get('door_open')}
    starts = [tuple(c) for side in doc['starts'].values() for c in side]
    assert len(starts) == len(set(starts)) == 12
    assert all(len(side) == 6 for side in doc['starts'].values())
    assert all(0 <= x < doc['width_squares'] and 0 <= y < doc['height_squares'] for x,y in starts)
    assert not (blocked | object_blocks).intersection(starts)
    reached, pending = {starts[0]}, [starts[0]]
    while pending:
        x,y = pending.pop()
        for p in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]:
            if (0 <= p[0] < doc['width_squares'] and 0 <= p[1] < doc['height_squares']
                    and p not in blocked | object_blocks and p not in reached):
                reached.add(p); pending.append(p)
    assert set(starts) <= reached
    # A larger arena must not become a long empty approach. Even the farthest
    # start can reach an opposing start within two rounds of combined 30-ft moves.
    difficult = {tuple(c) for row in doc['terrain'] if row['type'] == 'DIFFICULT' for c in row['cells']}
    difficult |= {tuple(c) for row in doc['materials'] if row['material'] == 'terrain:bamboo thicket' for c in row['cells']}
    for side, other in [('team1','team2'), ('team2','team1')]:
        opponents = set(map(tuple, doc['starts'][other]))
        for origin in map(tuple, doc['starts'][side]):
            distances, queue = {origin: 0}, [(0, origin)]
            while queue:
                cost, p = heapq.heappop(queue)
                if cost != distances[p]: continue
                if p in opponents: break
                x,y = p
                for c in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]:
                    if c not in reached: continue
                    new = cost + (2 if c in difficult else 1)
                    if new < distances.get(c, 10000):
                        distances[c] = new
                        heapq.heappush(queue, (new,c))
            assert min(distances.get(c, 10000) for c in opponents) <= 24
    assert doc['picker_order'] > 5 and doc['description']
    canonical_sha256(to_battlefield(doc))
    # Editor copy invokes the same material validator and rasterizer as shipped loading.
    copied = CombatService(ROOT,tmp_path).tabletop_maps.save({**doc,'map_id':'copy-'+map_id})
    assert copied['cells'] == doc['cells'] and copied['objects'] == doc['objects']


@pytest.mark.parametrize('map_id', IDS)
def test_short_real_ai_fight_commit_cold_reload(tmp_path, map_id):
    combat, mid = _fight(tmp_path, 'battlefield:map.'+map_id, size=2, rounds=1)
    sealed = combat._load_session(mid).engine.battlefield_document
    table = TabletopService(combat,tmp_path)
    initial = table.state(mid)
    assert initial['map']['map_id'] == map_id
    # Table auto_step and CombatService.local_step commit via mechanical.execute_intent.
    assert table.auto_step(mid,initial['last_sequence'])['status'] == 'COMMITTED'
    for _ in range(180):
        if combat._load_session(mid).engine.state.terminal_result: break
        combat.local_step(mid)
    cold = CombatService(ROOT,tmp_path)._load_session(mid)
    assert cold.engine.state.terminal_result
    assert cold.engine.battlefield_document == sealed
    assert any(e.event_type == 'MOVEMENT_COMMITTED' for e in cold.engine.events)
    assert cold.mechanical.replay()['status'] == 'PASS'
    assert cold.mechanical.replay()['canonical_state_sha256'] == canonical_state_sha256(cold.engine.state)


@pytest.mark.parametrize('map_id', IDS)
def test_twelve_person_fight_has_all_twelve_legal_starts(tmp_path, map_id):
    combat,mid = _fight(tmp_path,'battlefield:map.'+map_id,size=6,rounds=1)
    engine = combat._load_session(mid).engine
    assert len(engine.state.actors) == 12
    positions = {(a.position.x,a.position.y) for a in engine.state.actors.values()}
    assert len(positions) == 12
    assert positions == {tuple(c) for side in combat.tabletop_maps.get(map_id)['starts'].values() for c in side}
    table=TabletopService(combat,tmp_path)
    state=table.state(mid)
    assert table.auto_step(mid,state['last_sequence'])['status'] == 'COMMITTED'
    assert CombatService(ROOT,tmp_path)._load_session(mid).mechanical.replay()['status']=='PASS'


def test_largest_map_six_per_side_ai_step_timing(tmp_path, capsys):
    combat,mid = _fight(tmp_path,'battlefield:map.builtin-emerald-canopy',size=6,rounds=2)
    timings = []
    for _ in range(180):
        if combat._load_session(mid).engine.state.terminal_result: break
        before = perf_counter()
        combat.local_step(mid)
        timings.append(perf_counter()-before)
    cold = CombatService(ROOT,tmp_path)._load_session(mid)
    assert cold.engine.state.terminal_result and len(timings) >= 12
    assert any(e.event_type == 'MOVEMENT_COMMITTED' for e in cold.engine.events)
    # These cultivators use save-based Mountain-Moving Palm as well as weapons.
    # Actor damage proves engagement within two rounds for either kind of attack.
    assert any(e.event_type == 'DAMAGE_COMMITTED' and any(t in cold.engine.state.actors for t in e.target_ids)
               for e in cold.engine.events)
    assert cold.mechanical.replay()['status'] == 'PASS'
    # Informational timing, including local_step persistence, with no flaky SLA.
    with capsys.disabled():
        print('SOL215 Emerald Canopy 6v6 AI local_step seconds: '+json.dumps({
            'steps': len(timings), 'median': round(median(timings),4),
            'mean': round(sum(timings)/len(timings),4), 'max': round(max(timings),4),
            'total': round(sum(timings),4)}), flush=True)


@pytest.mark.parametrize('map_id', [IDS[0], IDS[3]])
def test_furniture_against_walls_with_clear_door_and_table_approaches(tmp_path, map_id):
    doc = CombatService(ROOT,tmp_path).tabletop_maps.get(map_id)
    blocked,_ = rasterize(doc)
    solid_objects = {(o['x'],o['y']) for o in doc['objects'] if object_rules.stats(o)['blocks']}
    solid = blocked | solid_objects
    for o in doc['objects']:
        x,y = o['x'],o['y']
        neighbors = {(x-1,y),(x+1,y),(x,y-1),(x,y+1)}
        if o['kind'] in ('bookcase','sutra_shelf'):
            assert neighbors & solid, 'Shelves must stand against a wall'
            assert any(c in blocked or any(w['kind']=='wall_section' and (w['x'],w['y'])==c
                       for w in doc['objects']) for c in neighbors)
        if o['kind'] == 'dining_table':
            assert not neighbors & solid, 'Leave walking room on each side of a table'
        if o['kind'] == 'door':
            assert o['mount_axis'] == 'h'
            assert not {(x,y-1),(x,y+1)} & solid, 'Keep both door approaches clear'
        if o['kind'] not in ('door','wall_section'):
            assert (x,y) not in blocked
    if map_id == IDS[3]:
        assert {w['look'] for w in doc['walls']} == {'red_palace'}
        assert len([o for o in doc['objects'] if o['kind']=='door']) == 6
    else:
        for prefix in ('compound-', 'west-home-', 'east-home-', 'west-cottage-', 'east-cottage-'):
            assert len({w['look'] for w in doc['walls'] if w['id'].startswith(prefix)}) == 1
        # Stalls face the market lanes, keeping the lane centres unobstructed.
        assert all(o['y'] in (12,18) for o in doc['objects'] if o['kind']=='market_stall')


def test_river_has_two_dry_crossings_and_a_walkable_difficult_ford(tmp_path):
    doc = CombatService(ROOT,tmp_path).tabletop_maps.get(IDS[2])
    floors = {row['material']: set(map(tuple,row['cells'])) for row in doc['materials']}
    wet = {tuple(c) for row in doc['terrain'] if row['type']=='DIFFICULT' for c in row['cells']}
    assert floors['floor:cloud_stone'] and floors['floor:wood']
    assert not wet & (floors['floor:cloud_stone']|floors['floor:wood'])
    assert floors['floor:packed_dirt'] <= wet  # the ford is shallow water, not a third dry bridge
    blocked,_ = rasterize(doc)
    assert not blocked & floors['floor:packed_dirt']
    assert {y for x,y in wet | floors['floor:cloud_stone'] | floors['floor:wood']} == set(range(32))


@pytest.mark.parametrize('cell,origin,beyond,hp,ac', [
    ((14,6),(13,6),(15,6),27,17), ((19,10),(19,11),(19,9),18,15)])
def test_hall_wall_and_door_break_through_table_actions_and_reload(tmp_path,cell,origin,beyond,hp,ac):
    # Real characters, existing map, ordinary weapon attack; no patched dice or state.
    for pid in ['left','right']: _install(tmp_path,pid)
    combat=CombatService(ROOT,tmp_path)
    doc=combat.tabletop_maps.get(IDS[0])
    target=next(o for o in doc['objects'] if (o['x'],o['y']) == cell)
    oid='object:map.'+str(target['id'])
    stats=object_rules.stats(target)
    assert (stats['hp'],stats['ac']) == (hp,ac)
    # Place the attacker next to the selected building section in an editor copy.
    saved=combat.tabletop_maps.save({**doc,'map_id':'hall-break-test',
        'starts':{'team1':[list(origin)],'team2':[[26,15]]}})
    left,right=FACTORY_ACTOR_PREFIX+'left',FACTORY_ACTOR_PREFIX+'right'
    mid=combat.create_factory_match(project_ids=['left'],opponent_actor_ids=[right],
        control_modes={left:'MANUAL',right:'MANUAL'},arena_id='battlefield:map.'+saved['map_id'],
        maximum_rounds=80,match_seed='SOL212-break-'+str(cell))['match_id']
    table=TabletopService(combat,tmp_path)
    engine=combat._load_session(mid).engine
    engine.legal_candidates()
    assert cell in engine.grid.blocked
    assert not engine.grid.line_of_sight(Position(x=origin[0],y=origin[1]),Position(x=beyond[0],y=beyond[1]))
    assert not _clear_line(engine,origin,beyond)
    assert not any(c.destination==Position(x=cell[0],y=cell[1]) for c in engine.legal_candidates())
    def act(cid):
        state=table.state(mid); menu=state['menu']
        result=table.act(mid,cid,menu['decision_id'],menu['state_version'],state['last_sequence'])
        assert result['status']=='COMMITTED'
    for _ in range(160):
        state=table.state(mid); menu=state['menu']
        engine=combat._load_session(mid).engine
        if engine.state.objects[oid].destroyed: break
        attacks=[c for c in engine.legal_candidates() if menu['actor_id']==left
                 and oid in (c.target_ids or ()) and 'Attack an object' in c.display_name and '+' not in c.display_name]
        act(attacks[0].candidate_id if attacks else menu['end_turn'])
    assert engine.state.objects[oid].destroyed
    assert any(e.event_type=='ATTACK_ROLLED' for e in engine.events)
    assert engine.state.objects[oid].current_hp == 0
    cold=CombatService(ROOT,tmp_path); loaded=cold._load_session(mid)
    loaded.engine.legal_candidates()
    assert loaded.engine.state.objects[oid].destroyed
    assert cell not in loaded.engine.grid.blocked
    assert loaded.engine.grid.line_of_sight(Position(x=origin[0],y=origin[1]),Position(x=beyond[0],y=beyond[1]))
    assert _clear_line(loaded.engine,origin,beyond)
    # The adjacent section stays solid: a breach must not erase the whole hall.
    neighbor=(cell[0],cell[1]-1) if cell[0]==14 else (cell[0]+1,cell[1])
    assert neighbor in loaded.engine.grid.blocked
    cold_table=TabletopService(cold,tmp_path)
    for _ in range(3):
        state=cold_table.state(mid); menu=state['menu']
        loaded=cold._load_session(mid)
        if menu['actor_id']==left: break
        assert cold_table.act(mid,menu['end_turn'],menu['decision_id'],menu['state_version'],state['last_sequence'])['status']=='COMMITTED'
    move=next(c for c in loaded.engine.legal_candidates() if c.kind==CandidateKind.MOVE and c.destination==Position(x=cell[0],y=cell[1]))
    state=cold_table.state(mid);menu=state['menu']
    assert cold_table.act(mid,move.candidate_id,menu['decision_id'],menu['state_version'],state['last_sequence'])['status']=='COMMITTED'
    final=CombatService(ROOT,tmp_path)._load_session(mid)
    assert final.engine.state.actors[left].position==Position(x=cell[0],y=cell[1])
    assert final.mechanical.replay()['status']=='PASS'
