"""Maple Shrine parity: one full native pass, then bounded table endpoint probes."""
import json
import socket

import pytest

from combat import ext, motion, movement_menu
from combat.movement_routes import explicit_candidate
from combat.read_queries import candidate_pass
from combat.zones import sync_walls
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopError, TabletopService
from tests.h1_support import ROOT, sheet

OWNER = 'actor:factory.movepreview-owner'
FOE = 'actor:factory.movepreview-foe'


def test_maple_shrine_offered_destinations_preview(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('CF_EMBED_MENU', '0')

    def no_network(*args, **kwargs):
        raise AssertionError('No live model server in movement previews')

    monkeypatch.setattr(socket.socket, 'connect', no_network)
    combat = CombatService(ROOT, tmp_path)
    arena = combat.tabletop_maps.get('builtin-realm-maple-shrine')
    arena['map_id'] = 'deployplay-maple-shrine'
    arena['starts'] = {'team1': [[23, 19]], 'team2': [[27, 19]]}
    combat.tabletop_maps.save(arena)
    owner = sheet(['tianxia.path.body_refining.feature.stamina_guard'], cl=2, primary='Stamina')
    owner['ability_scores_and_statistics']['speed']['walking_ft'] = 60
    # Fix initiative without changing movement, footprint or either start.
    owner['ability_scores_and_statistics']['initiative'] = {'bonus': 100}
    bundles = [compile_character(owner, actor_id=OWNER),
               compile_character(sheet([], cl=2), actor_id=FOE)]
    mid = combat._finish_factory_match(
        bundles, [FOE, OWNER], {FOE: 'team1', OWNER: 'team2'},
        {FOE: {'x': 23, 'y': 19}, OWNER: {'x': 27, 'y': 19}},
        combat.factory_arenas()['battlefield:map.deployplay-maple-shrine'],
        [FOE, OWNER], [], control_modes={OWNER: 'LOCAL_AUTO', FOE: 'LOCAL_AUTO'},
        match_seed='DEPLOYPLAY:MOVEPREVIEW1', display_name='Movement preview', maximum_rounds=20)['match_id']
    engine = combat._load_session(mid).engine
    assert engine.state.initiative_order[0] == OWNER
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    assert engine.state.round_number == 1
    assert actor.position == Position(x=27, y=19)
    assert actor.speed_ft == actor.movement_remaining_ft == 60
    assert engine._footprint(actor).width_cells == engine._footprint(actor).height_cells == 1
    assert [c.condition_id for c in actor.conditions.values()] == ['condition:typed.body_scene']

    # Record the native geometry presented to admission, so a refused endpoint
    # can be attributed without copying an older implementation into the test.
    geometry = {}
    collect = movement_menu.collect

    def observe(engine, actor, destination, path, cost, mode, can_jump_down, *args):
        geometry[destination.x, destination.y, destination.z, mode] = {
            'cost_ft': cost, 'path': [p.model_dump(mode='json') for p in path]}
        return collect(engine, actor, destination, path, cost, mode, can_jump_down, *args)

    monkeypatch.setattr(movement_menu, 'collect', observe)
    table = TabletopService(combat, tmp_path)
    menu = table.state(mid, lazy=True)['menu']
    assert menu['actor_id'] == OWNER and menu['lazy']
    offered = {(row[0], row[1], row[2], row[4]) for row in menu['movement_grid']}
    assert offered
    # preview_destination's native enumeration narrows only the final emission
    # by intent.destination (gate2_engine._movement_candidates). Enumerate once
    # and run its admission + explicit path validation over the WHOLE offered
    # set, rather than rebuilding that same search for every square (quadratic).
    # Real service probes below also check the targeted search, without mocking
    # it or replacing any of its admission/validation functions.
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    resolved, refusals, native_modes = {}, {}, {}
    with candidate_pass(engine), motion.terrain_for(engine, actor):
        sync_walls(engine)
        for candidate in engine._movement_candidates(actor):
            p = candidate.destination
            mode = candidate.metadata.get('movement_mode', 'walk')
            key = (p.x, p.y, p.z, mode)
            native_modes.setdefault((p.x, p.y, p.z), set()).add(mode)
            vetoes = ext.vetoing_hooks('candidate_allowed', engine, actor, candidate,
                                     engine.action_catalog.get(candidate.source_definition_id))
            if vetoes:
                refusals[key] = {'candidate_allowed': vetoes}
                continue
            try:
                bound = explicit_candidate(engine, OWNER, candidate.canonical_path, mode)
            except ValueError as exc:
                refusals[key] = {'explicit_candidate': str(exc)}
                continue
            assert bound.destination == p and bound.canonical_path[0] == actor.position
            assert bound.metadata.get('movement_mode', 'walk') == mode
            resolved.setdefault(key, bound)
    geometry_refused = set(geometry) - resolved.keys()
    offered_refused = offered - resolved.keys()
    detail = {str(key): refusals.get(key, {'native_modes': sorted(native_modes.get(key[:3], ()))})
              for key in sorted(geometry_refused)}

    # Bound real service calls to eight endpoints: the reported square first,
    # a refused geometry endpoint if any, each offered mode, then set extrema
    # and the median. This includes omissions as negative controls, not only
    # successful endpoints; the whole set was checked above.
    reported = (21, 18, 0, 'walk')
    ordered = sorted(offered)
    probes = [reported] if reported in geometry else []
    probes += sorted(geometry_refused)[:1]
    probes += [next(key for key in ordered if key[3] == mode)
               for mode in sorted({key[3] for key in offered})]
    probes += [ordered[0], ordered[len(ordered) // 2], ordered[-1]]
    probes = list(dict.fromkeys(probes))[:8]
    service_failures, service_trace = [], {}
    for x, y, z, mode in probes:
        key = (x, y, z, mode)
        destination = {'x': x, 'y': y, 'z': z}
        try:
            quote = table.preview_destination(mid, menu['decision_id'], menu['state_version'],
                                              OWNER, destination, mode)
        except TabletopError as exc:
            service_trace[str(key)] = {'status': exc.status_code, 'code': exc.code, 'message': str(exc)}
            if key in resolved or exc.status_code != 422 or exc.code != 'TABLETOP_ROUTE_INVALID':
                service_failures.append((key, service_trace[str(key)]))
            continue
        service_trace[str(key)] = {'status': 200}
        if key not in resolved:
            service_failures.append((key, 'service accepted a route refused by native admission'))
        candidate = quote['candidate']
        assert Position.model_validate(candidate['destination']) == Position.model_validate(destination)
        assert Position.model_validate(candidate['canonical_path'][0]) == Position(x=27, y=19)
        assert candidate['metadata'].get('movement_mode', 'walk') == mode
        assert quote['authoritative_state_unchanged']

    with pytest.raises(TabletopError) as refused:
        table.preview_destination(mid, menu['decision_id'], menu['state_version'], OWNER,
                                  {'x': 0, 'y': 0, 'z': 0}, 'walk')
    assert refused.value.status_code == 422
    assert refused.value.code == 'TABLETOP_ROUTE_INVALID'
    with capsys.disabled():
        print(f'MOVEPREVIEW1: geometry={len(geometry)} offered={len(offered)} '
              f'omitted={len(geometry.keys() - offered)} geometry_refused={len(geometry_refused)} '
              f'offered_refused={len(offered_refused)} service_probes={len(probes)} '
              f'service_mismatches={len(service_failures)}', flush=True)
        print('MOVEPREVIEW1 refusal trace: ' + json.dumps(detail, sort_keys=True), flush=True)
        print('MOVEPREVIEW1 reported geometry: ' + json.dumps(geometry.get(reported)), flush=True)
        print('MOVEPREVIEW1 service trace: ' + json.dumps(service_trace, sort_keys=True), flush=True)
    assert not offered_refused, {str(key): detail.get(str(key)) for key in sorted(offered_refused)}
    assert not service_failures, service_failures
    assert table.state(mid, lazy=True)['menu'] == menu
