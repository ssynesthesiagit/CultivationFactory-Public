"""Every offered Maple Shrine endpoint must resolve at the same table decision."""
import socket

import pytest

from combat import movement_menu
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
    geometry = set()
    collect = movement_menu.collect

    def observe(engine, actor, destination, path, cost, mode, can_jump_down, *args):
        geometry.add((destination.x, destination.y, destination.z, mode))
        return collect(engine, actor, destination, path, cost, mode, can_jump_down, *args)

    monkeypatch.setattr(movement_menu, 'collect', observe)
    table = TabletopService(combat, tmp_path)
    menu = table.state(mid, lazy=True)['menu']
    assert menu['actor_id'] == OWNER and menu['lazy']
    offered = {(row[0], row[1], row[2], row[4]) for row in menu['movement_grid']}
    assert offered
    failures = []
    for x, y, z, mode in sorted(offered):
        destination = {'x': x, 'y': y, 'z': z}
        try:
            quote = table.preview_destination(mid, menu['decision_id'], menu['state_version'],
                                              OWNER, destination, mode)
        except TabletopError as exc:
            failures.append((destination, mode, exc.status_code, exc.code, str(exc)))
            continue
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
              f'omitted={len(geometry - offered)} offered_preview_422={len(failures)}', flush=True)
    assert not failures, failures
    assert table.state(mid, lazy=True)['menu'] == menu
