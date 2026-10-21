"""Opt-in paired headless AI measurement, real maps and damaging starts.

Only task-owned temporary map copies. No private sheets, live service, model
endpoint or GUI. Queue: -o combatai2_batch=1 -o combatai2_output=<json>.
Both sides share each arm's flag; wins describe behavior, not new/old strength.
"""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import statistics
import time
import pytest
from tests.combat_ai_slices_options import opt_in_options

from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.gate4_context import build_decision_context, build_reaction_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_policy import PolicyLibrary
from combat.tabletop import normalize_map, to_battlefield
from tests.test_combat_ai_slices import ROOT, hazard_engine, hazard_sheet, _cast, OWNER, AN


def test_offline_paired_maps(tmp_path, monkeypatch, request):
    opts = opt_in_options(request.config)
    if opts.get('combatai2_batch') != '1':
        pytest.skip('opt-in offline paired experiment via heavyq')
    output = Path(opts['combatai2_output'])
    def deny(*a, **k):
        raise AssertionError('Offline batch cannot contact a live server')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)
    map_root = Path('/var/tmp/auto-audit/auto2/audit_userdata_2663758/combat_maps')
    sources = [map_root / 'bamboo-road.json', map_root / 'wooden-dungeon.json',
               ROOT / 'combat/maps/builtin-ricefield-bamboo-valley.json',
               ROOT / 'combat/maps/builtin-realm-market-quarter.json',
               ROOT / 'combat/maps/builtin-river-delta-isles.json']
    from factory_authoring.sphere_dao import character_dao, controller_policy, sheet_sphere_talents
    from combat.factory_compiler import primary_resource
    from combat.ai_observation import goal_from_sheet
    sheet = hazard_sheet()
    dao = character_dao(sheet_sphere_talents(sheet))
    owner_policy = controller_policy(dao, OWNER, primary_resource=primary_resource(sheet))
    owner_policy['goal_description'] = goal_from_sheet(sheet)
    policies = PolicyLibrary(ROOT, actor_policy=lambda aid: owner_policy if aid == OWNER else None)
    controller = LocalDeterministicController()
    rows, manifests = [], {}
    def save(complete=False):
        output.write_text(json.dumps({'complete': complete, 'maps_sha256': manifests,
            'protocol': 'two seeds per map; both sides off vs both on; side swap by seed; damaging start; two-round cap',
            'rows': rows}, indent=2) + '\n')
    for source in sources:
        copied = tmp_path / source.name
        shutil.copyfile(source, copied)
        manifests[source.stem] = hashlib.sha256(copied.read_bytes()).hexdigest()
        battlefield = to_battlefield(normalize_map(json.loads(copied.read_text())))
        grid = SquareGrid(battlefield)
        # Pick a passable damaging start near native cover when available;
        # otherwise nearest passable central cell. Never fabricate map geometry.
        cells = [(x, y) for y in range(grid.height) for x in range(grid.width)
                 if not grid.terrain_at(Position(x=x, y=y), 'BLOCKED')]
        def cover_distance(p):
            return min((max(abs(p[0]-x), abs(p[1]-y)) for x, y in grid.cover), default=999)
        pairs = [(p, (p[0]-5, p[1])) for p in cells if (p[0]-5, p[1]) in cells
                 and grid.line_of_sight(Position(x=p[0]-5, y=p[1]), Position(x=p[0], y=p[1]))]
        assert pairs, 'Map must have two legal starts within spell range'
        foe_cell, owner_cell = min(pairs, key=lambda pair: (cover_distance(pair[0]),
            abs(pair[0][0]-grid.width//2)+abs(pair[0][1]-grid.height//2), pair))
        for index, seed in enumerate(('AI2-A', 'AI2-B')):
            for flag in ('0', '1'):
                monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', flag)
                # Swap the geography, keeping each actor's native abilities.
                foe_at, owner_at = (foe_cell, owner_cell) if not index else (owner_cell, foe_cell)
                positions = {OWNER: {'x': owner_at[0], 'y': owner_at[1]},
                             AN: {'x': foe_at[0], 'y': foe_at[1]}}
                engine = hazard_engine(battlefield=battlefield, positions=positions,
                                       seed=seed, rounds=2)
                def react(request):
                    policy, _ = policies.for_actor(request['reactor_id'])
                    choice = controller.choose_reaction(build_reaction_context(engine, policy, request))
                    return choice.decision, choice.record.model_dump(mode='json')
                engine.set_reaction_provider(react)
                _cast(engine, 'Conflagration', Position(x=foe_at[0], y=foe_at[1]))
                engine.state.current_actor_id = AN
                engine.state.current_slot_index = engine.state.initiative_order.index(AN)
                engine._system_start_turn()
                from combat.target_knowledge import observe
                observe(engine)
                area = next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get('kind') == 'TYPED')
                boundary = {(p.x, p.y, p.z) for p in area.affected_cells}
                assert (foe_at[0], foe_at[1], 0) in boundary
                times, exits = [], 0
                # Measure only the played phase, excluding the setup cast.
                first_event = len(engine.events)
                deadline = time.monotonic() + 600
                for step in range(120):
                    if engine.state.terminal_result:
                        break
                    assert time.monotonic() < deadline, '10-minute per-fight budget exceeded'
                    aid = engine.state.current_actor_id
                    policy, _ = policies.for_actor(aid)
                    tick = time.perf_counter()
                    ctx = build_decision_context(engine, policy, for_ai=True)
                    choice = controller.choose_primary_action(ctx)
                    times.append((time.perf_counter()-tick)*1000)
                    before = engine.state.actors[AN].position
                    inside = (before.x, before.y, before.z) in boundary
                    engine.execute_intent(choice.intent)
                    after = engine.state.actors[AN].position
                    if inside and (after.x, after.y, after.z) not in boundary:
                        exits += 1
                assert engine.state.terminal_result, '120-decision budget exceeded'
                played = engine.events[first_event:]
                damage = sum(int(e.payload.get('hp_damage') or 0) for e in played if e.event_type == 'DAMAGE_COMMITTED')
                all_damage = sum(int(e.payload.get('hp_damage') or 0) for e in engine.events if e.event_type == 'DAMAGE_COMMITTED')
                rows.append({'map': source.stem, 'seed': seed, 'swap': bool(index), 'flag': flag,
                    'hazard_exits': exits, 'damage_taken': all_damage, 'played_damage': damage,
                    'winner': engine.state.terminal_result.winning_team_id,
                    'terminal': engine.state.terminal_result.kind.value, 'decisions': len(times),
                    'mean_decision_ms': statistics.mean(times),
                    'p95_decision_ms': sorted(times)[max(0, int(len(times)*.95)-1)]})
                save()
                print(f'COMBATAI2 map={source.stem} seed={seed} flag={flag} exits={exits} damage={all_damage}', flush=True)
    save(True)
    assert len(rows) == 20
