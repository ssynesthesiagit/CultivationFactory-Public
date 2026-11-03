"""Review regressions through table transactions, persisted receipts and reload.

The attack-on-step subscriber is an offline fixture for a reacting attack; it
uses the real attack resolver and never patches engine functions.
"""
import pytest

from combat import ext
from combat.ext import athletics
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_mgr_t16_athletics import (
    game, commit, move_at, ROOT, OWNER, FOE, MULTIPLE, MOVING, MOBILITY,
    SHARK, GLIDE, reload_identical,
)
from tests.athletics_action_support import add_action

PURSUIT = 'TAL_ATHLETICS_FLOWING_PURSUIT'


def select(feature):
    return lambda p: ['one'] if 'motion_count' in p['context']['reaction_source_id'] else [feature]


def action(table, mid, label):
    return next(o for group in table.state(mid)['menu']['actions'] for o in group['options']
                if o['label'] == label)


@pytest.mark.parametrize('ranged,purchases,expected', [(True, 1, 2), (False, 2, 2), (False, 1, 0)])
def test_earned_cover_survives_second_selection_during_attack_and_reload(tmp_path, monkeypatch, ranged, purchases, expected):
    def prepare(bundles):
        owner = next(b for b in bundles if b['actor_id'] == OWNER)
        next(r for r in owner['typed_passives'] if r.get('kind') == 'moving_target')['purchases'] = purchases
    service, table, mid = game(tmp_path, [MULTIPLE, MOVING, MOBILITY], prepare=prepare)
    commit(table, mid, move_at(table, mid, 8), select(MOVING))
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    cold = service._load_session(mid).engine
    assert athletics._moving_target(cold, cold.state.actors[OWNER]) == 2
    ext._load()
    prior = list(ext._HOOKS.get('movement_step', ()))
    source = 'test:reacting.attack'
    def react(engine, mover, previous, nxt, intent):
        if mover.entity_id != OWNER or not any(
                e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER for e in engine.events):
            return
        if any(e.source_definition_id == source and e.event_type == 'ATTACK_ROLLED' for e in engine.events):
            return
        spec = {'attack_bonus': -100, 'damage': {'count': 1, 'sides': 4},
                **({'range_ft': 120} if ranged else {'reach_ft': 120})}
        engine._resolve_attack_spec(engine.state.actors[FOE], mover, spec, intent,
                                   source_definition_id=source)
    monkeypatch.setitem(ext._HOOKS, 'movement_step', [*prior, react])
    commit(table, mid, move_at(table, mid, 9), select(MOBILITY))
    cold = CombatService(ROOT, tmp_path)._load_session(mid).engine
    attacks = [e for e in cold.events if e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == source]
    assert len(attacks) == 1 and attacks[0].payload['cover_bonus'] == expected
    assert athletics._moving_target(cold, cold.state.actors[OWNER]) == 2
    reload_identical(service, mid, tmp_path)
    # Continue the saved table to the next owner turn: the earned defense ends.
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    for _ in range(2):
        commit(table, mid, {'candidate_id': table.state(mid)['menu']['end_turn']})
    cold = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert cold.state.current_actor_id == OWNER
    assert athletics._moving_target(cold, cold.state.actors[OWNER]) == 0
    reload_identical(service, mid, tmp_path)


@pytest.mark.parametrize('material,end,cost', [(None, 4, 10), ('stone', 4, 10), ('soil', 5, 20)])
def test_prone_glide_prices_dry_and_mixed_routes_as_ground_steps(tmp_path, material, end, cost):
    def prepare(bundles):
        add_action(next(b for b in bundles if b['actor_id'] == OWNER), 'Lie down',
                   [{'type': 'condition', 'condition': 'prone', 'applies_to': 'self'}])
    # Stone is a labelled open floor, not permission to traverse a stone wall.
    service, table, mid = game(tmp_path, [SHARK, GLIDE],
                               material='soil' if material == 'soil' else None, prepare=prepare,
                               floor_material='stone' if material == 'stone' else None)
    commit(table, mid, action(table, mid, 'Lie down'))
    cold = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert any(c.condition_id == 'condition:typed.prone' for c in cold.state.actors[OWNER].conditions.values())
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    menu = table.state(mid)['menu']
    path = [{'x': x, 'y': 6} for x in range(3, end + 1)]
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], OWNER, path, 'swim')
    assert quote['candidate']['movement_cost_ft'] == cost
    assert move_at(table, mid, end, mode='swim')['cost_ft'] == cost
    before = cold.state.actors[OWNER].movement_remaining_ft
    result = table.commit_move_path(mid, quote['candidate']['candidate_id'], menu['decision_id'],
                                   menu['state_version'], OWNER, path, movement_mode='swim')
    assert result['status'] == 'COMMITTED'
    cold = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert cold.state.actors[OWNER].movement_remaining_ft == before - cost
    reload_identical(service, mid, tmp_path)


@pytest.mark.parametrize('first_end,second_end,earned', [(4, 7, False), (7, 8, True)])
def test_pursuit_counts_only_selected_legs_after_cold_reload(tmp_path, first_end, second_end, earned):
    def prepare(bundles):
        add_action(next(b for b in bundles if b['actor_id'] == OWNER), 'Check pursuit', [])
    service, table, mid = game(tmp_path, [MULTIPLE, PURSUIT, MOBILITY], prepare=prepare)
    commit(table, mid, move_at(table, mid, first_end), select(PURSUIT))
    commit(table, mid, move_at(table, mid, second_end), select(MOBILITY))
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    prompts = commit(table, mid, action(table, mid, 'Check pursuit'), lambda p: ['ac'])
    assert bool(prompts) is earned
    if earned:
        assert all('Flowing Pursuit' in str(p) for p in prompts)
    cold = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert any(c.condition_id == athletics.AC_AGAINST for c in cold.state.actors[OWNER].conditions.values()) is earned
    reload_identical(service, mid, tmp_path)
