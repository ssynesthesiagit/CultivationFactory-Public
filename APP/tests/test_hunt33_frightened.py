"""Hunt33 pillar path regression using public sheets and persisted table actions."""
import pytest

from combat.voluntary_movement import path_allowed
from combat.ext.rider_movement import routes, step
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import TabletopError
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import on_hold

ME = 'actor:factory.hunt33-fear'
FOE = 'actor:factory.hunt33-source'


def fear_table(tmp_path, monkeypatch, *, frightened=True, invisible=False):
    bundles = [compile_character(sheet([]), actor_id=a) for a in (ME, FOE)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, [ME, FOE], {ME: 'team:a', FOE: 'team:b'},
        {ME: {'x': 3, 'y': 6}, FOE: {'x': 7, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [ME], [FOE],
        control_modes={ME: 'MANUAL', FOE: 'MANUAL'}, match_seed='HUNT33-FEAR',
        display_name='Hunt33 fear regression', maximum_rounds=5)['match_id']
    while table.state(mid)['menu']['actor_id'] != ME:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'

    def setup(engine):
        if frightened:
            engine._apply_condition(engine.state.actors[ME], 'condition:typed.frightened',
                'test:hunt33-fear', FOE, expires_on='START_OF_SELF_NEXT_TURN')
        if invisible:
            engine._apply_condition(engine.state.actors[FOE], 'condition:typed.invisible',
                'test:hunt33-unseen-source', FOE, expires_on='UNTIL_REMOVED')
    on_hold(monkeypatch, setup)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    return combat, table, mid


def approaches(engine, actor, path):
    source = engine.state.actors[FOE]
    start = engine.grid.distance_ft(actor.position, source.position)
    return any(engine.grid.distance_ft(p, source.position) < start for p in path)


def test_visible_fear_path_veto_at_table_reload_and_ai(tmp_path, monkeypatch):
    combat, table, mid = fear_table(tmp_path, monkeypatch)
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = session.engine
    actor = engine.state.actors[ME]
    # An unafraid diagnostic view identifies the former native defect without
    # changing the saved state: a farther endpoint with a closer intermediate step.
    unafraid = actor.model_copy(update={'conditions': {}})
    before = engine.state.model_dump(mode='json')
    bad = next(c for c in engine._movement_candidates(unafraid)
               if c.destination == Position(x=6, y=12))
    assert approaches(engine, actor, bad.canonical_path)
    assert Position(x=4, y=8) in bad.canonical_path
    assert not path_allowed(engine, actor, bad.canonical_path)
    assert engine.state.model_dump(mode='json') == before
    # Candidate identities bind destinations, not a client's fabricated path.
    # Fear-aware search now finds a different legal route to this destination.
    alternative = next(c for c in engine.legal_candidates() if c.candidate_id == bad.candidate_id)
    assert alternative.canonical_path != bad.canonical_path
    assert path_allowed(engine, actor, alternative.canonical_path)
    forbidden = next(c for c in engine._movement_candidates(unafraid)
                     if c.destination == Position(x=4, y=6))
    assert forbidden.candidate_id not in {c.candidate_id for c in engine.legal_candidates()}
    state = table.state(mid)
    with pytest.raises(TabletopError, match='no longer legal'):
        table.act(mid, forbidden.candidate_id, state['menu']['decision_id'],
                  state['menu']['state_version'], state['last_sequence'], [])
    fresh = CombatService(ROOT, tmp_path)
    assert fresh._load_session(mid).engine.state.actors[ME].position == actor.position
    assert all(path_allowed(engine, actor, c.canonical_path)
               for c in engine._movement_candidates(actor))
    safe = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination != actor.position)
    assert not approaches(engine, actor, safe.canonical_path)
    assert table.act(mid, safe.candidate_id, state['menu']['decision_id'],
                     state['menu']['state_version'], state['last_sequence'], [])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[ME].position == safe.destination
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    combat.set_controller_mode(mid, actor_id=ME, controller_mode='LOCAL_AUTO')
    for _ in range(12):
        state = table.state(mid)
        assert table.auto_step(mid, state['last_sequence'])['status'] == 'COMMITTED'
        if combat._load_session(mid).engine.state.current_actor_id != ME:
            break
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.current_actor_id != ME
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('frightened,invisible', [(False, False), (True, True)])
def test_no_visible_fear_leaves_detour_available(tmp_path, monkeypatch, frightened, invisible):
    combat, table, mid = fear_table(tmp_path, monkeypatch, frightened=frightened, invisible=invisible)
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[ME]
    candidate = next(c for c in engine.legal_candidates()
                     if c.kind == 'MOVE' and c.destination == Position(x=6, y=12))
    assert approaches(engine, actor, candidate.canonical_path)
    assert path_allowed(engine, actor, candidate.canonical_path)
    assert any(approaches(engine, actor, path) for path in routes(engine, actor, 30).values())
    # Hunt35: invisible remembered sources must not suppress a direct approach.
    assert any(c.destination == Position(x=4,y=6) for c in engine._movement_candidates(actor))
    state = table.state(mid)
    assert table.act(mid, candidate.candidate_id, state['menu']['decision_id'],
                     state['menu']['state_version'], state['last_sequence'], [])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[ME].position == candidate.destination
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('frightened,invisible,expected_x', [
    (True, False, 3), (False, False, 4), (True, True, 4),
])
def test_direct_willing_rider_step_checks_fear_at_table_commit_reload(
        tmp_path, monkeypatch, frightened, invisible, expected_x):
    """Direct rider callers obey fear; unfrightened/unseen-source bytes still move.

    A synthetic rider runs inside an accepted table transaction, as in the
    existing Hunt33 regression. This tests the shared helper rather than an
    invented ability or a changed locked movement resolver.
    """
    combat, table, mid = fear_table(tmp_path, monkeypatch,
                                   frightened=frightened, invisible=invisible)

    def rider(engine):
        actor = engine.state.actors[ME]
        step(engine, actor, [actor.position, Position(x=4, y=6)], 'test:direct-rider')

    on_hold(monkeypatch, rider)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[ME].position == Position(x=expected_x, y=6)
    movements = [e for e in loaded.engine.events if e.event_type == 'MOVEMENT_COMMITTED'
                 and e.source_definition_id == 'test:direct-rider']
    assert len(movements) == (0 if expected_x == 3 else 1)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('frightened,expected_x', [(True, 3), (False, 4)])
def test_warleader_voluntary_ally_route_respects_fear_at_table_commit_reload(
        tmp_path, monkeypatch, frightened, expected_x):
    """The Step on My Count planner's fear veto survives an accepted table commit."""
    from combat.ext import warleader_commands

    combat, table, mid = fear_table(tmp_path, monkeypatch, frightened=frightened)

    def command(engine):
        ally = engine.state.actors[ME]
        plan = warleader_commands._plan_move(engine, ally, 5, 'approach', exempt=1)
        if plan is not None:
            warleader_commands._move(engine, ally, plan, 'warleader:step_on_my_count')

    on_hold(monkeypatch, command)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[ME].position.x == expected_x
    moves = [e for e in loaded.engine.events if e.event_type == 'MOVEMENT_COMMITTED'
             and e.source_definition_id == 'warleader:step_on_my_count']
    assert len(moves) == (0 if frightened else 1)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('frightened,expected_x', [(True, 3), (False, 6)])
def test_raging_bull_charge_respects_fear_at_table_commit_reload(
        tmp_path, monkeypatch, frightened, expected_x):
    """The straight reaction charge is rejected only for a frightened fighter."""
    from combat.ext import counterstrike

    combat, table, mid = fear_table(tmp_path, monkeypatch, frightened=frightened)

    def charge(engine):
        actor, source = engine.state.actors[ME], engine.state.actors[FOE]
        route = counterstrike._straight_charge(engine, actor, source, 5)
        if route:
            counterstrike._charge(engine, actor, source, 5, None)

    on_hold(monkeypatch, charge)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[ME].position.x == expected_x
    moves = [e for e in loaded.engine.events if e.event_type == 'MOVEMENT_COMMITTED'
             and e.source_definition_id == counterstrike.SOURCE]
    assert len(moves) == (0 if frightened else 1)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('auto,frightened', [(False, True), (True, True), (False, False)])
def test_white_wing_hit_offers_only_willing_fear_legal_routes(tmp_path, monkeypatch, auto, frightened):
    """Actual owned Polearm hit through the manual/AI table, not just a path query."""
    import copy
    from combat import typed_executor as te
    from tests.test_c7_review_fixup import (table_fight, to_turn, send, load, hold_ai,
                                          ME as player, FOE as enemy, HERON, JI)
    from tests.h1_support import script

    combat, table, mid = table_fight(tmp_path, [HERON + 'white_wing_crosses_the_reed_field'], items=(JI,))
    to_turn(table, mid, player)

    def polearm_hit(engine):
        actor, target = engine.state.actors[player], engine.state.actors[enemy]
        if frightened:
            engine._apply_condition(actor, 'condition:typed.frightened', 'test:wing-fear', enemy,
                                    expires_on='END_OF_SOURCE_NEXT_TURN')
        action = next(a for a in engine.action_catalog.values() if a.owner_id == player
                      and a.display_name.startswith('Ji (Halberd) attack'))
        typed = copy.deepcopy(action.parameters['typed'])
        for effect in typed['effects']:
            if effect.get('type') == 'attack':
                effect['count'] = 1
        # Frightened imposes Disadvantage: both d20s must hit to exercise the rider.
        script(engine, [*([19, 19] if frightened else [19]), *([1] * 80)])
        te.run_effects(te.Context(engine, actor, action, engine._active_intent, typed, [target], target, {}),
                       typed['effects'])

    on_hold(monkeypatch, polearm_hit)
    if auto:
        hold_ai(combat, mid, player)
    result = send(table, mid, auto=auto)
    if frightened:
        assert result['status'] == 'COMMITTED'
    else:
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']
        assert prompt['context']['reaction_source_id'].endswith('white_wing_move')
        result = send(table, mid, answers_=[{**prompt['context'], 'selection': 'DECLINE'}])
        assert result['status'] == 'COMMITTED'
    restored = load(tmp_path, mid)
    actor = restored.engine.state.actors[player]
    assert actor.position == Position(x=3, y=6)
    assert '_round_white_wing' not in actor.turn_flags
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == player and e.payload.get('provisional_hit')
               for e in restored.engine.events)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == player and enemy in e.target_ids
               and e.payload.get('hp_damage', 0) > 0 for e in restored.engine.events)
    assert restored.verify()['status'] == restored.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('frightened,invisible', [(True, False), (False, False), (True, True)])
def test_moon_table_routes_filter_fear_before_movement_and_sweep(tmp_path, monkeypatch, frightened, invisible):
    """A rejected route cannot consume payment or sweep squares never traversed."""
    from combat.ext.white_heron import _moon_paths
    from tests.test_c7_review_fixup import (table_fight, to_turn, send, settle, load,
                                          ME as player, FOE as enemy, HERON, JI, STAMINA)

    combat, table, mid = table_fight(tmp_path, [HERON + 'moon_over_the_reed_sea'], items=(JI,))
    to_turn(table, mid, player)

    def setup(engine):
        target = engine.state.actors[enemy]
        origin = target.position
        target.position = Position(x=7, y=6)
        engine._append_event('MOVEMENT_COMMITTED', 'test:moon-layout', actor_id=enemy,
            payload={'destination': target.position.model_dump(mode='json'), 'cost_ft': 0, 'forced': True,
                     'path': [origin.model_dump(mode='json'), target.position.model_dump(mode='json')]})
        if frightened:
            engine._apply_condition(engine.state.actors[player], 'condition:typed.frightened',
                                    'test:moon-fear', enemy, expires_on='UNTIL_REMOVED')
        if invisible:
            engine._apply_condition(engine.state.actors[enemy], 'condition:typed.invisible',
                                    'test:moon-unseen', enemy, expires_on='UNTIL_REMOVED')

    on_hold(monkeypatch, setup)
    assert send(table, mid)['status'] == 'COMMITTED'
    assert send(table, mid, label='end')['status'] == 'COMMITTED'
    to_turn(table, mid, player)
    restored = load(tmp_path, mid)
    engine, actor = restored.engine, restored.engine.state.actors[player]
    before = actor.resources[STAMINA]
    state = table.state(mid)
    group = next(g for g in state['menu']['actions'] if g['label'] == 'Moon over the Reed Sea')
    options = {(o['destination']['x'], o['destination']['y']) for o in group['options']}
    blocked = frightened and not invisible
    assert ((6, 6) in options) is not blocked
    # The same query runs again during execution, including warm geometry.
    assert ((6, 6) in _moon_paths(engine, actor)) is not blocked
    assert ((6, 6) in _moon_paths(engine, actor)) is not blocked
    assert actor.resources[STAMINA] == before
    result, prompts = settle(table, mid, label='Moon over the Reed Sea', at=(2, 6),
                             picks={'moon_over_the_reed_sea': None})
    assert result['status'] == 'COMMITTED'
    final = load(tmp_path, mid)
    assert final.engine.state.actors[player].position == Position(x=2, y=6)
    assert final.engine.state.actors[player].resources[STAMINA] == before - 7
    assert final.engine.state.actors[enemy].current_hp == engine.state.actors[enemy].current_hp
    assert final.verify()['status'] == final.mechanical.replay()['status'] == 'PASS'
