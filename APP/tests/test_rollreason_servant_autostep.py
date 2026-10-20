"""Synthetic public table regression for commanded summoned AI turns."""
import json
import socket
import subprocess
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

OWNER = 'actor:factory.servant-owner'
FOE = 'actor:factory.servant-foe'


def test_commanded_servants_advance_through_deferred_auto_steps(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    def no_network(*args, **kwargs):
        raise AssertionError('No live model or embedding server in this regression')
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    owner = compile_character(sheet(['TAL_DEATH_CORPSE_SERVANT'], name='Summoner'), actor_id=OWNER,
                              summon_plan={'corpse_servant': 2, 'lesser_corpse_servant': 0})
    foe = compile_character(sheet([], name='Opponent'), actor_id=FOE)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match([owner, foe], [OWNER, FOE],
        {OWNER: 'team:a', FOE: 'team:b'},
        {OWNER: {'x': 35, 'y': 11}, FOE: {'x': 9, 'y': 10}},
        combat.factory_arenas(include_retired=True)['battlefield:map.builtin-realm-maple-shrine'],
        [OWNER], [FOE], control_modes={OWNER: 'MANUAL', FOE: 'MANUAL'},
        match_seed='ROLLREASON-SERVANTS', display_name='Commanded servants', maximum_rounds=5)['match_id']
    for _ in range(4):
        state = table.state(mid)
        menu = state['menu']
        if menu['actor_id'] == OWNER:
            break
        assert table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
                         state['last_sequence'])['status'] == 'COMMITTED'
    else:
        raise AssertionError('Summoner never received its turn')
    command = next(group for group in menu['actions'] if group['source_definition_id'].endswith('.command.death'))
    assert table.act(mid, command['options'][0]['candidate_id'], menu['decision_id'], menu['state_version'],
                     state['last_sequence'])['status'] == 'COMMITTED'
    state = table.state(mid)
    menu = state['menu']
    assert table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
                     state['last_sequence'])['status'] == 'COMMITTED'
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    servants = [actor.entity_id for actor in combat._load_session(mid).engine.state.actors.values()
                if actor.summon and actor.summon.get('group') == 'corpse_servant']
    seen = set()
    fixtures = []
    for _ in range(8):
        before = table.state(mid, fog=True, compact_moves=True)
        menu = before['menu']
        if menu['actor_id'] not in servants:
            break
        seen.add(menu['actor_id'])
        result = table.auto_step(mid, before['last_sequence'], [], menu['decision_id'], menu['state_version'],
                                 defer_menu=True)
        assert result['status'] == 'COMMITTED', result.get('reaction')
        assert result['state']['last_sequence'] > before['last_sequence']
        expanded = table.state(mid, fog=True, compact_moves=True)
        assert 'menu_pending' not in expanded
        assert expanded['last_sequence'] == result['state']['last_sequence']
        fixtures.append({'before': before, 'result': result, 'expanded': expanded})
    assert seen == set(servants)
    subprocess.run(['node', str(Path(__file__).with_name('servant_autostep_ui.test.mjs'))],
                   input=json.dumps(fixtures), text=True, check=True, timeout=90)
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.mechanical.replay()['status'] == 'PASS'
