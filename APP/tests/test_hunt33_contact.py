"""Retained Hunt33 seeds/geometry with public synthetic sheets, through the table.

No private hunt character documents are repository fixtures. A setup event
applies invisibility before the AI accepts its path, just as in the hunt.
"""
import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.target_knowledge import concealed, located
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install

MOVER = 'actor:factory.hunt33-mover'
BLOCKER = 'actor:factory.hunt33-blocker'


def contact_table(tmp_path, monkeypatch, seed, start, blocker, sense):
    owned = ['tianxia.path.spirit_awakening.feature.spiritual_sense'] if sense else []
    bundles = [compile_character(sheet(owned), actor_id=MOVER),
               compile_character(sheet([]), actor_id=BLOCKER)]
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Hunt33 contact yard', 'width_squares': 14,
        'height_squares': 8, 'walls': [],
        'starts': {'team1': [list(start)], 'team2': [list(blocker)]}})
    mid = service._finish_factory_match(bundles, [MOVER, BLOCKER],
        {MOVER: 'team:a', BLOCKER: 'team:b'},
        {MOVER: dict(x=start[0], y=start[1]), BLOCKER: dict(x=blocker[0], y=blocker[1])},
        service.factory_arenas()['battlefield:map.hunt33-contact-yard'], [MOVER], [BLOCKER],
        control_modes={MOVER: 'MANUAL', BLOCKER: 'MANUAL'}, match_seed=seed,
        display_name='Hunt33 contact regression', maximum_rounds=5)['match_id']
    table = TabletopService(service, tmp_path)
    while table.state(mid)['menu']['actor_id'] != MOVER:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'

    def hide_on_hold(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED':
            engine._apply_condition(engine.state.actors[BLOCKER], 'condition:typed.invisible',
                'test:hunt33-invisibility', BLOCKER, expires_on='UNTIL_REMOVED')
    install(monkeypatch, 'event', hide_on_hold)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    return service, table, mid


@pytest.mark.parametrize('seed,start,blocker,destination,stop,sense', [
    ('HUNT33-44', (3, 4), (9, 4), (9, 4), (8, 4), True),
    ('HUNT33-46', (3, 2), (3, 3), (2, 3), (3, 2), False),
    # The grid also checks the other orthogonal placement of a diagonal step.
    ('HUNT33-46-side-a', (3, 2), (2, 2), (2, 3), (3, 2), False),
    # Hunt34's four retained failure seeds cover both diagonal side squares
    # and a blocker newly located after path acceptance. Public sheets and
    # compact geometry intentionally replace the private captured rosters.
    ('HUNT34-13', (3, 2), (3, 3), (2, 3), (3, 2), False),
    ('HUNT34-23', (3, 4), (9, 4), (9, 4), (8, 4), True),
    ('HUNT34-35', (3, 2), (2, 2), (2, 3), (3, 2), False),
    ('HUNT34-36', (3, 4), (9, 4), (9, 4), (8, 4), True),
])
def test_ai_contact_stops_safely_commits_reloads_and_continues(
        tmp_path, monkeypatch, seed, start, blocker, destination, stop, sense):
    service, table, mid = contact_table(tmp_path, monkeypatch, seed, start, blocker, sense)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    actor, target = engine.state.actors[MOVER], engine.state.actors[BLOCKER]
    assert concealed(target) and not located(engine, actor, target)
    candidate = next(c for c in engine.legal_candidates()
                     if c.kind == 'MOVE' and c.destination == Position(x=destination[0], y=destination[1]))
    assert [(p.x, p.y) for p in candidate.canonical_path] == (
        [(x, 4) for x in range(3, 10)] if sense else [start, destination])
    if sense:
        probe = service._clone_engine(ROOT, engine)
        probe.state.actors[MOVER].position = Position(x=8, y=4)
        assert located(probe, probe.state.actors[MOVER], probe.state.actors[BLOCKER])
    before_sequence = engine.state.event_sequence
    budget = actor.movement_remaining_ft
    service.set_controller_mode(mid, actor_id=MOVER, controller_mode='LOCAL_AUTO')
    original = service.controller

    class ContactController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(original, name)

    service.controller = ContactController()
    state = table.state(mid)
    assert table.auto_step(mid, state['last_sequence'])['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)
    session = fresh._load_session(mid)
    engine = session.engine
    actor = engine.state.actors[MOVER]
    assert actor.position == Position(x=stop[0], y=stop[1])
    assert actor.movement_remaining_ft == budget - (25 if sense else 0)
    assert actor.turn_flags['unseen_blockers'][BLOCKER] == dict(x=blocker[0], y=blocker[1])
    assert dict(x=blocker[0], y=blocker[1]) in actor.turn_flags['unseen_contact_cells']
    assert engine.state.observations[actor.team_id][BLOCKER] == engine.state.actors[BLOCKER].position
    events = [e for e in engine.events if e.sequence > before_sequence]
    movement = next(e for e in events if e.event_type == 'MOVEMENT_COMMITTED')
    assert movement.payload['interrupted'] and movement.payload['cost_ft'] == (25 if sense else 0)
    assert any(e.event_type == 'TARGETS_OBSERVED' and e.payload.get('contacted_cells') for e in events)
    assert any(e.event_type == 'PASSIVE_TRIGGERED' and 'Movement stopped on contact' in e.payload.get('log', '')
               for e in events)
    # A legal detour to the diagonal destination is still allowed; only the
    # path that clipped the contacted side square must disappear.
    assert not any(c.kind == 'MOVE' and c.canonical_path == candidate.canonical_path
                   for c in engine.legal_candidates())
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    # The normal AI can finish the same turn after this interruption, including
    # a zero-foot diagonal stop, without a repeating blocked-move loop.
    table = TabletopService(fresh, tmp_path)
    for _ in range(12):
        state = table.state(mid)
        assert table.auto_step(mid, state['last_sequence'])['status'] == 'COMMITTED'
        if fresh._load_session(mid).engine.state.current_actor_id != MOVER:
            break
    continued = CombatService(ROOT, tmp_path)._load_session(mid)
    assert continued.engine.state.current_actor_id != MOVER
    assert continued.verify()['status'] == continued.mechanical.replay()['status'] == 'PASS'
