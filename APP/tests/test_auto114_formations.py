"""AUTO114 Formations Sphere: the Thread Relay relay grant and its sight contract, and Formation Maze at the table.

The relay section is ported from the cloud worker's round-1 review (CW2r1) so this Sphere keeps the reviewed
behaviour after the cherry-pick. The relay offers one Cultivation Attack from an array's Eye or Node; whether the
ally may use it depends on what the ally currently perceives, not on the attack's own sight requirement.

Formation Maze is the lane's own review round (AUTO114r1f1): table cases below commit and reload real moves. The oversized boundary case uses the runtime engine
with its supported growth effect. Successful-save taxation remains explicitly manual until a locked route-cost seam exists.
"""
import pytest

from combat.ext.formation_talents import RELAY
from combat.target_knowledge import can_see, located
from tests.cw2_service_support import add_action, seal
from tests.formation_support import reload, settle, turn
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture


@pytest.mark.parametrize('pinpoint,requires_sight', [(True, False), (False, False), (True, True)])
def test_relay_accepts_perception_and_preserves_attack_sight_contract(tmp_path, pinpoint, requires_sight):
    def prepare(bundles):
        add_action(bundles[0], 'Prepare unseen target', [{'type': 'condition', 'condition': 'invisible',
            'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}])
        if pinpoint:
            bundles[1]['senses'] = {'rows': [{'sense': 'tremorsense', 'range_ft': 30, 'when': 'always'}]}
        for a in bundles[1]['action_catalog']:
            if a['display_name'] == 'Destructive Blast':
                a['parameters']['typed']['requires_seen_target'] = requires_sight
        seal(bundles[1])

    combat, table, mid = fixture(tmp_path, ['tianxia.talent.formations.formation_thread_relay'],
        ally_talents=['TAL_DESTRUCTION_DESTRUCTIVE_BLAST'], seed='AUTO30', bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Combat Array: Nourishing Cycle', at=(5, 6)).candidate_id)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Pulse: Nourishing Cycle', target=ALLY).candidate_id,
           {'choice:needle.formation_thread_relay': ALLY})
    settle(table, mid, candidate(combat, mid, 'Prepare unseen target', target=FOE).candidate_id)
    turn(table, mid, ALLY)
    e = reload(tmp_path, mid)
    actor, target = e.state.actors[ALLY], e.state.actors[FOE]
    assert not can_see(e, actor, target)
    assert located(e, actor, target) == pinpoint
    remotes = [c for c in e.legal_candidates() if c.metadata.get('effect_origin') and c.target_ids == (FOE,)]
    # Owner targeting ruling (2026-10-06): attack rolls need a known square
    # and line of effect; requires_seen_target no longer vetoes an attack.
    # Relay still requires the ally itself to perceive the target.
    assert bool(remotes) == pinpoint
    grant = next(c for c in actor.conditions.values() if c.condition_id.startswith(RELAY + '.'))
    assert 'until the start of ' + e.state.actors[OWNER].display_name + "'s next turn" in grant.data['label']
    if remotes:
        settle(table, mid, remotes[0].candidate_id)
        assert not any(c.condition_id.startswith(RELAY + '.')
                       for c in reload(tmp_path, mid).state.actors[ALLY].conditions.values())


# Formation Maze: table enforcement, cold reload and explicit manual tax fallback.
from combat import ext
from combat.ext import formations as F
from combat.ext import effect_durations
from combat.ext.formation_riders import LOST, MAZE, SLOWED, SOURCE_MAZE, _anchor_live, _maze_anchors, _maze_bar_blocks, maze_entry
from combat.gate2_runtime_models import Position
from tests.h1_support import sheet
from tests.worker2_support import fixture

MAZE_TALENT = 'tianxia.talent.formations.' + MAZE
CHOICE_MAZE = 'choice:needle.' + MAZE
INSIDE = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}}
OUTSIDE = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 8, 'y': 6}}


class _MazeSave:
    """The outcome of the Maze's own Wisdom save, forced through the engine's ``d20_result`` seam.

    The transaction is rolled back and re-executed, so the save is answered more than once for one decision; a
    standing answer, not a queue, keeps both passes reading the same printed outcome."""

    def __init__(self, outcome='fail'):
        self.outcome = outcome

    def rewrite(self, engine, roll, intent):
        if not str(roll.reason).startswith('SAVE:' + SOURCE_MAZE + ':'):
            return None
        return {"source_id": "test:formation-maze", "operation": "replace",
                "natural_result": 20 if self.outcome == 'pass' else 1}


@pytest.fixture
def maze_save(monkeypatch):
    forced = _MazeSave()
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [*ext._HOOKS.get('d20_result', []), forced.rewrite])
    return forced


def _maze_fight(tmp_path, *, talents, dc, foe_sheet, seed, positions=None, picks=None):
    """The owner has set a Combat Array at (5,6); the hostile's turn is next."""
    combat, table, mid = fixture(tmp_path, talents, seed=seed, positions=positions or INSIDE, dc=dc, foe_sheet=foe_sheet)
    settle(table, mid, candidate(combat, mid, 'Combat Array: Nourishing Cycle', at=(5, 6)).candidate_id)
    settle(table, mid, table.state(mid)['menu']['end_turn'], picks)
    turn(table, mid, FOE)
    return combat, table, mid


def _held(creature, condition_id):
    return [c for c in creature.conditions.values() if c.condition_id == condition_id]


def _moves(engine, actor_id):
    return [c for c in engine.legal_candidates() if c.actor_id == actor_id and c.destination is not None
            and c.display_name.startswith('Move')]


def _move_to(engine, cell, actor_id):
    return next(c for c in _moves(engine, actor_id) if (c.destination.x, c.destination.y) == tuple(cell)).candidate_id


def _spot(data):
    return Position(x=int(data['x']), y=int(data['y']))


def test_maze_turn_start_failure_keeps_the_hostile_off_the_anchor_and_survives_reload(tmp_path):
    """A hostile starting its turn inside the array and failing its Wisdom save may no longer move toward the anchor,
    the printed deadline is the OWNER's next turn, and the restriction is still standing after a real move and a cold
    reload."""
    combat, table, mid = _maze_fight(tmp_path, talents=[MAZE_TALENT], dc=25, foe_sheet=sheet([], cl=15), seed='AUTO114R1F1-FAIL')
    engine = reload(tmp_path, mid)
    foe, owner = engine.state.actors[FOE], engine.state.actors[OWNER]
    held = _held(foe, LOST)
    assert held, 'the failed save leaves the printed Formation Maze restriction'
    data = held[0].data or {}
    assert 'cannot willingly move closer to' in data['label']
    assert data['anchor'].startswith(('object:', 'actor:')), 'the chosen anchor is stored as an identity, not a square'
    assert held[0].expires_on == effect_durations.token('start', owner.entity_id, owner.turns_started + 1), \
        'the printed deadline is the owner next turn, not the creature its'
    spot = _spot(data)
    moves = _moves(engine, FOE)
    assert moves, 'the foe still has somewhere to go'
    for move in moves:
        previous = engine.grid.distance_ft(foe.position, spot)
        for step in (*move.canonical_path, move.destination):
            distance = engine.grid.distance_ft(step, spot)
            assert not distance < previous, f'{move.display_name} would step toward the anchor but is still offered'
            previous = distance
    away = next(move for move in moves
                if engine.grid.distance_ft(move.destination, spot) > engine.grid.distance_ft(foe.position, spot))
    feet = foe.movement_remaining_ft
    settle(table, mid, away.candidate_id)
    after = reload(tmp_path, mid).state.actors[FOE]
    assert (after.position.x, after.position.y) == (away.destination.x, away.destination.y)
    assert after.movement_remaining_ft == feet - away.movement_cost_ft
    still = _held(after, LOST)
    assert still and still[0].data == data, 'the restriction and its anchor survive the table commit'


def test_maze_bar_ends_at_the_owners_next_turn_and_not_before(tmp_path):
    """"Until the start of your next turn": the affected creature ending its own turn does not take it away, and the
    owner's next turn does."""
    combat, table, mid = _maze_fight(tmp_path, talents=[MAZE_TALENT], dc=25, foe_sheet=sheet([], cl=15), seed='AUTO114R1F1-EXPIRY')
    settle(table, mid, table.state(mid)['menu']['end_turn'])           # the affected creature's own turn ends here
    assert _held(reload(tmp_path, mid).state.actors[FOE], LOST), 'the affected creature own turn ended the restriction'
    turn(table, mid, OWNER)
    assert _held(reload(tmp_path, mid).state.actors[FOE], LOST) == [], 'the restriction outlived the owner next turn'


def test_maze_entry_failure_refuses_the_step_that_triggered_it(tmp_path):
    """A hostile that walks into the array and fails its save does not get the step: the printed restriction begins the
    moment it is failed, so the creature stays outside and the table is told why."""
    combat, table, mid = _maze_fight(tmp_path, talents=[MAZE_TALENT], dc=25, foe_sheet=sheet([], cl=15),
                                     seed='AUTO114R1F1-ENTRY', positions=OUTSIDE)
    engine = reload(tmp_path, mid)
    zone = F.arrays(engine, OWNER)[0]
    entering = [c for c in _moves(engine, FOE)
                if F.inside_at(engine, engine.state.actors[FOE], zone, c.destination)
                and not F.inside(engine, engine.state.actors[FOE], zone)]
    assert entering, 'the hostile has somewhere inside the array to walk to'
    settle(table, mid, min(entering, key=lambda c: len(c.canonical_path)).candidate_id)
    after = reload(tmp_path, mid)
    foe = after.state.actors[FOE]
    assert (foe.position.x, foe.position.y) == (8, 6), 'the refused step was taken anyway'
    assert not F.inside(after, foe, zone)
    assert _held(foe, LOST), 'the failed save left nothing behind'
    events = reload(tmp_path, mid).events
    riders = [str((event.payload or {}).get('rider') or '') for event in events if event.event_type == 'GM_RIDER']
    assert any('Formation Maze' in text and 'cannot willingly move closer' in text for text in riders), riders
    committed = [(event.payload or {}) for event in events if event.event_type == 'MOVEMENT_COMMITTED']
    assert committed[-1].get('interrupted') is True


def test_maze_bar_follows_a_keyed_ally_that_walks(tmp_path):
    """The chosen anchor is an identity, not a square: when the keyed ally really walks (a table commit and a cold
    reload) the bar reads where the ally stands now.  This asserts the one reader every enforcement seam asks -- the
    step gate, the menu filter and the stored condition all go through it -- because the printed lifetime ends at the
    owner's next turn, which comes before this creature's next menu, so a second menu cannot show the difference."""
    combat, table, mid = _maze_fight(tmp_path, talents=[MAZE_TALENT], dc=25, foe_sheet=sheet([], cl=15),
                                     seed='AUTO114R1F1-ANCHOR', positions=INSIDE,
                                     picks={CHOICE_MAZE: [f'actor:{ALLY}']})
    engine = reload(tmp_path, mid)
    held = _held(engine.state.actors[FOE], LOST)
    assert held and (held[0].data or {})['anchor'] == f'actor:{ALLY}', \
        (held[0].data or {}) if held else 'the ally is not the anchor'
    frozen = _spot(held[0].data or {})
    assert (frozen.x, frozen.y) == (4, 6), 'the keyed ally was not where the maze saw it'
    assert _maze_bar_blocks(engine, engine.state.actors[FOE], Position(x=6, y=6), Position(x=5, y=6)) is not None
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, ALLY)
    settle(table, mid, _move_to(reload(tmp_path, mid), (7, 7), ALLY))     # the ally walks, and it is committed
    engine = reload(tmp_path, mid)
    foe, ally = engine.state.actors[FOE], engine.state.actors[ALLY]
    assert (ally.position.x, ally.position.y) == (7, 7), 'the keyed ally did not walk'
    held = _held(foe, LOST)
    assert held, 'the restriction ended before the owner next turn'
    assert (held[0].data or {})['anchor'] == f'actor:{ALLY}'
    live = Position(x=ally.position.x, y=ally.position.y)
    assert engine.grid.distance_ft(foe.position, live) < engine.grid.distance_ft(foe.position, frozen)
    assert _maze_bar_blocks(engine, foe, Position(x=6, y=6), Position(x=7, y=7)) is not None, \
        'a step toward where the ally stands now is still allowed: the bar reads the remembered square'
    assert _maze_bar_blocks(engine, foe, Position(x=6, y=6), Position(x=5, y=6)) is None, \
        'a step toward the square the ally left is still refused: the bar does not follow the ally'
    # The same gate is invoked for granted paths without a native movement menu.
    assert maze_entry(engine, foe, Position(x=6, y=6), Position(x=7, y=7), None)['stop'] is True
    before = foe.model_dump(mode='json')
    ally.active = False
    assert _maze_bar_blocks(engine, foe, Position(x=6, y=6), Position(x=7, y=7)) is None
    assert foe.model_dump(mode='json') == before, 'checking a missing anchor mutated saved state'
    zone = F.arrays(engine, OWNER)[0]
    eye = engine.state.objects[F.record(zone)['eye']]
    held[0].data['anchor'] = f'object:{eye.object_id}'
    eye.position = Position(x=8, y=8)
    assert _anchor_live(engine, held[0])[1] == eye.position
    eye.destroyed = True
    assert _anchor_live(engine, held[0]) is None
    assert f'object:{eye.object_id}' not in _maze_anchors(engine, zone, foe)
    other = held[0].model_copy(deep=True, update={'instance_id': 'maze:second',
        'data': {'anchor': f'actor:{OWNER}'}})
    foe.conditions[other.instance_id] = other
    assert _maze_bar_blocks(engine, foe, Position(x=6, y=6), Position(x=5, y=6)) is not None, \
        'a vanished first anchor masked another standing restriction'


def test_maze_success_keeps_tax_manual_and_does_not_misprice_real_moves(tmp_path, maze_save):
    """The successful-save fallback says exactly what the GM must charge; no unsafe automatic tax is installed."""
    maze_save.outcome = 'pass'
    combat, table, mid = _maze_fight(tmp_path, talents=[MAZE_TALENT], dc=10,
        foe_sheet=sheet([], cl=15, score=30), seed='AUTO114R1F1-MANUAL-TAX')
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert not _held(foe, SLOWED)
    riders = [str((e.payload or {}).get('text') or '') for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED']
    assert any('Formation Maze' in text and '10 additional feet' in text and 'no turn deadline' in text
               and 'does not charge this tax automatically' in text for text in riders), riders
    move = next(c for c in _moves(engine, FOE) if (c.destination.x, c.destination.y) == (5, 6))
    feet = foe.movement_remaining_ft
    settle(table, mid, move.candidate_id)
    after = reload(tmp_path, mid).state.actors[FOE]
    assert (after.position.x, after.position.y) == (5, 6)
    assert after.movement_remaining_ft == feet - move.movement_cost_ft
    assert not _held(after, SLOWED)
    assert combat._load_session(mid).mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('owner_mode', ['MANUAL', 'LOCAL_AUTO'])
def test_maze_owner_decides_during_an_ai_movers_entry(tmp_path, maze_save, owner_mode):
    """Manual Ask-me owners can decline on an AI turn; AI owners resolve their own reaction automatically."""
    combat, table, mid = _maze_fight(tmp_path, talents=[MAZE_TALENT], dc=25,
        foe_sheet=sheet([], cl=15), seed='AUTO114R1F1-AI-ENTRY', positions=OUTSIDE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=owner_mode)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    before = dict(owner.resources)
    zone = F.arrays(engine, OWNER)[0]
    entries = [c for c in _moves(engine, FOE) if F.inside_at(engine, engine.state.actors[FOE], zone, c.destination)]
    move = min(entries, key=lambda c: len(c.canonical_path))
    payload = {'candidate_id': move.candidate_id, 'decision_id': move.decision_id,
        'state_version': move.state_version, 'actor_id': FOE, 'target_ids': list(move.target_ids),
        'destination': move.destination.model_dump(mode='json'), 'option_ids': list(move.option_ids)}
    token = combat.ai_validate(mid, payload)['validation_token']
    result = combat.ai_execute(mid, payload, token)
    if owner_mode == 'MANUAL':
        assert result['status'] == 'AWAITING_REACTION', result
        prompt = table._reaction_prompt(mid, result['reaction_context'])
        assert prompt['context']['reactor_id'] == OWNER
        assert prompt['context']['reaction_source_id'] == CHOICE_MAZE
        assert 'Formation Maze' in str(prompt)
        result = combat.ai_execute(mid, payload, token,
            reactions=[{**prompt['context'], 'selection': 'DECLINE', 'option_ids': []}])
        assert result['status'] == 'COMMITTED', result
        after = reload(tmp_path, mid)
        assert not _held(after.state.actors[FOE], LOST)
        assert after.state.actors[OWNER].resources == before
        assert after.state.actors[OWNER].reaction_available
    else:
        assert result['status'] == 'COMMITTED', result
        after = reload(tmp_path, mid)
        assert _held(after.state.actors[FOE], LOST)
        assert not after.state.actors[OWNER].reaction_available


def test_maze_is_inert_for_an_owner_without_the_talent(tmp_path):
    """An owner who sets an array with another Formations talent is never asked for a Maze."""
    combat, table, mid = _maze_fight(tmp_path, talents=['tianxia.talent.formations.court_of_the_ninefold_array'],
                                     dc=10, foe_sheet=sheet([], cl=15, score=30), seed='AUTO114R1F1-NONE')
    engine = reload(tmp_path, mid)
    assert F.arrays(engine, OWNER), 'the control still has an array'
    assert not _held(engine.state.actors[FOE], LOST) and not _held(engine.state.actors[FOE], SLOWED)

# --------------------------------------------------------------- entry is read from the whole body
# A factory character is compiled with a one-square body (combat/footprint_registry.py resolves every factory actor
# from the stock registry), so the oversized case is played on the engine, where a creature's recorded size is the
# engine's own state: a real Formations array, a real Movement Check and a real Move, at the level the boundary
# question is asked.  A table fight cannot show it and does not pretend to.
def test_maze_entry_is_read_from_the_whole_body_and_not_the_anchor_square(maze_save):
    """A Large creature whose leading squares reach the array while its own square stays outside is asked the printed
    entry question -- the array is a whole-body area, so entry is read the same way -- and it is not asked a second
    time when its own square finally crosses the line."""
    from combat.factory_compiler import compile_character
    from combat.gate2_runtime_content import AN
    from combat.gate2_runtime_models import ActionIntent
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.h1_support import ROOT

    def engine_at(size, foe_at):
        document = sheet([MAZE_TALENT], cl=15, dc=10)
        document['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
        bundle = compile_character(document, actor_id='actor:factory.auto114r1f1-owner')
        engine = Gate4ControllerEngine(ROOT, match_seed='AUTO114R1F1-BODY', typed_bundles=(bundle,),
                                       roster_setup={"primary_actor_ids": ['actor:factory.auto114r1f1-owner', AN],
                                                     "team_by_actor": {'actor:factory.auto114r1f1-owner': "team:a", AN: "team:b"},
                                                     "starting_positions": {'actor:factory.auto114r1f1-owner': {"x": 3, "y": 5},
                                                                           AN: {"x": foe_at, "y": 6}}})
        engine.state.current_slot_index = engine.state.initiative_order.index('actor:factory.auto114r1f1-owner')
        engine.state.current_actor_id = 'actor:factory.auto114r1f1-owner'
        engine._system_start_turn()
        return engine

    def act(engine, name, actor, *, at=None):
        def label(candidate):
            return getattr(engine.action_catalog.get(candidate.source_definition_id), 'display_name', None) or candidate.display_name

        row = next(c for c in engine.legal_candidates()
                   if label(c) == name and c.actor_id == actor
                   and (at is None or (c.destination and (c.destination.x, c.destination.y) == at)))
        engine.execute_intent(ActionIntent(intent_id=f'{name}{engine.state.event_sequence}', decision_id=row.decision_id,
                                           candidate_id=row.candidate_id, state_version=row.state_version, actor_id=actor,
                                           target_ids=row.target_ids, destination=row.destination))

    def maze_saves(engine):
        return [event for event in engine.events if event.event_type == 'SAVE_ROLLED'
                and event.source_definition_id == SOURCE_MAZE]

    maze_save.outcome = 'pass'                       # the creature walks in and saves, so the step is its own
    owner = 'actor:factory.auto114r1f1-owner'
    engine = engine_at('Medium', 1)
    act(engine, "Combat Array: Nourishing Cycle", owner, at=(5, 6))
    zone = F.arrays(engine, owner)[0]
    assert (3, 6) in F.cells_of(zone)
    from combat import dynamic_size
    dynamic_size.apply_growth(engine, engine.state.actors[AN], 'Large', 'test:auto114r1f1-size',
                              source_actor_id=owner, expires_on='UNTIL_REMOVED')
    assert engine.state.actors[AN].transformed_size_category == 'Large', engine._actor_cells(engine.state.actors[AN])
    engine.state.current_slot_index = engine.state.initiative_order.index(AN)
    engine.state.current_actor_id = AN
    engine._system_start_turn()
    assert not F.inside(engine, engine.state.actors[AN], zone), 'the body starts clear of the array'
    assert F.inside_at(engine, engine.state.actors[AN], zone, Position(x=2, y=6)), \
        'the leading square of a 2x2 body does not reach the array here, so this proves nothing'
    act(engine, 'Move to 2,6', AN, at=(2, 6))
    assert engine.state.actors[AN].transformed_size_category == 'Large', 'the creature stopped being large'
    assert F.inside(engine, engine.state.actors[AN], zone), 'the Large creature is not inside the array it walked into'
    assert (engine.state.actors[AN].position.x, engine.state.actors[AN].position.y) == (2, 6), \
        'its own square stayed outside the array'
    assert len(maze_saves(engine)) == 1, 'the entry question was not asked from the leading square'
    act(engine, 'Move to 3,6', AN, at=(3, 6))                          # its own square now crosses in
    assert (engine.state.actors[AN].position.x, engine.state.actors[AN].position.y) == (3, 6)
    assert len(maze_saves(engine)) == 1, 'the anchor square entering late asked the entry question a second time'

    plain = engine_at('Medium', 1)                                      # the same walk by a one-square body asks nothing
    act(plain, "Combat Array: Nourishing Cycle", owner, at=(5, 6))
    plain.state.current_slot_index = plain.state.initiative_order.index(AN)
    plain.state.current_actor_id = AN
    plain._system_start_turn()
    act(plain, 'Move to 2,6', AN, at=(2, 6))
    assert not F.inside(plain, plain.state.actors[AN], F.arrays(plain, owner)[0])
    assert maze_saves(plain) == [], 'a one-square body was asked about an array it did not enter'
