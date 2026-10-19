"""Round 1F17 regressions for the Cloud Walker Sol review findings.

Each test fails without its fix, at the level the defect showed:

1. Feather triples a high jump once. The printed 7-foot running high jump of a
   Strength 18 creature becomes 21 feet (four whole 5-foot squares), and the
   standing jump becomes 9 feet. Two stacked multipliers produced 63 and 30.
2. Wind Walk's ritual range measures between creature footprints, so a Large
   caster and a Large recipient ten feet apart at their nearest occupied cells
   are still offered as ritual targets. Anchor-to-anchor distance reported
   fifteen feet and hid a legal recipient.
3. A chargeable liquid edge is priced on the table and the same price is
   actually charged when the move commits, surviving a cold reload. A later
   dry edge is priced normally.
"""
import json
import zipfile

from combat import flight
from combat.gate2_runtime_models import Position
from combat.ext.qi_subpaths_five import CLOUD
from tests.h1_support import ROOT, sheet
from tests.worker2_support import fixture, reload, settle, turn, OWNER
from tests.test_mgr_t14_cloud_resume import A, B

FEATHER = CLOUD + 'light_as_a_feather'
WIND = CLOUD + 'wind_walk'


# ----------------------------------------------------------------- 1. Feather multiplies once

def test_feather_high_jump_applies_the_printed_multiplier_exactly_once(tmp_path):
    combat, table, match_id = fixture(
        tmp_path, [], cl=3, owner_features=[FEATHER], owner_speed=60, ask=False)
    engine = reload(tmp_path, match_id)
    actor = engine.state.actors[OWNER]
    actor.strength_score = 18

    # Standing first: no recorded run, so the score-derived height is halved.
    assert flight.jump_steps(engine, actor, (actor.position,)) == 1, \
        'a Strength 18 standing high jump is 3 feet, tripled by Feather to 9 feet'

    # A straight recorded run makes the same jump a running start. A diagonal route
    # is not a run-up, so the test commits one straight line of three squares.
    def straight(row):
        path = row.canonical_path or ()
        return (len(path) >= 3
                and (len({p.x for p in path}) == 1 or len({p.y for p in path}) == 1))

    run = next(row for row in engine.legal_candidates()
               if row.kind.value == 'MOVE' and row.destination.z == actor.position.z
               and engine.grid.distance_cells(actor.position, row.destination) >= 2 and straight(row))
    settle(table, match_id, run.candidate_id)
    engine = reload(tmp_path, match_id)
    actor = engine.state.actors[OWNER]
    actor.strength_score = 18

    score, bonus = flight.jump_score(engine, actor)
    assert (score, bonus) == (18, 0), \
        'the score-derived height is already tripled by jump_distance_multiplier'
    assert flight.jump_distance_multiplier(engine, actor) == 3
    assert flight.jump_steps(engine, actor, (actor.position,)) == 4, \
        'a Strength 18 running high jump is 7 feet, tripled by Feather to 21 feet'
    assert flight.horizontal_jump_feet(engine, actor) == 18 * 3


# ----------------------------------------------------------------- 2. Wind Walk range uses footprints

def _large_journey(tmp_path, companion_position):
    """A Large caster and a Large companion, as their printed sheets declare."""
    from combat.gate5_service import CombatService
    aid, bid = 'actor:factory.largewalker', 'actor:factory.largecompanion'
    for pid, features, cl in [('largewalker', [WIND], 10), ('largecompanion', [], 1)]:
        doc = sheet([], cl=cl, name=pid)
        doc.setdefault('path_and_subpath', {})['path_feature_record_ids'] = features
        doc['identity']['size'] = 'Large'
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))

    def cold():
        return CombatService(ROOT, tmp_path)

    c = cold()
    c.tabletop_maps.save({'display_name': 'Large Wind Walk ritual', 'width_squares': 12, 'height_squares': 14,
                          'walls': [], 'starts': {'team1': [[3, 6]], 'team2': [[6, 6]]}})
    state = c.create_journey(project_ids=['largewalker', 'largecompanion'],
                             arena_id='battlefield:map.large-wind-walk-ritual',
                             positions={aid: {'x': 3, 'y': 6}, bid: companion_position},
                             base_paces={aid: 18000, bid: 18000},
                             control_modes={aid: 'MANUAL', bid: 'MANUAL'})
    jid = state['journey_id']

    def act(kind, payload=None, actor=aid):
        service = cold()
        current = service.journey_state(jid)
        return service.journey_act(jid, current['revision'], actor, kind, payload or {})

    return cold, jid, act, aid, bid


def _invitable(cold, jid, bid):
    return [row for row in cold().journey_menu(jid, 'actor:factory.largewalker')['options']
            if row['id'].split(':')[0] == 'cloud_wind_invite' and row['payload'].get('target_id') == bid]


def test_wind_walk_offers_a_large_recipient_ten_feet_away(tmp_path):
    """A Large caster at x=3-4 and a Large recipient at x=6-7 are 10 feet apart at their
    nearest occupied cells, so the recipient is a legal ritual target."""
    cold, jid, act, aid, bid = _large_journey(tmp_path, {'x': 6, 'y': 6})
    act('cloud_wind_begin')
    act('wait', {'seconds': 600})

    assert _invitable(cold, jid, bid), 'a recipient at the legal ten-foot boundary must be offered'
    act('cloud_wind_invite', {'target_id': bid})
    act('cloud_wind_reply', {'caster_id': aid, 'accept': True}, bid)
    finished = act('cloud_wind_finish')
    assert WIND in finished['actors'][bid]['travel_effects'], \
        'the consented recipient must finish the ritual as travel mist'


def test_wind_walk_still_hides_a_large_recipient_beyond_ten_feet(tmp_path):
    cold, jid, act, aid, bid = _large_journey(tmp_path, {'x': 8, 'y': 6})
    act('cloud_wind_begin')
    act('wait', {'seconds': 600})
    assert not _invitable(cold, jid, bid), '20 feet apart is outside the ritual range'


# ----------------------------------------------------------------- 3. Liquid edge is charged

def _surface_game(tmp_path, surfaces):
    """A native match on an owner map that declares the Cloud Walker surfaces.

    Reuses the shared Cloud review yard so initiative, measurements and starting
    squares stay identical to the other Cloud Walker surface tests.
    """
    from tests.test_mgr_t14_cloud_resume import game
    owner = sheet([], cl=3, name='Native Walker')
    owner.setdefault('path_and_subpath', {})['path_feature_record_ids'] = [FEATHER]
    return game(tmp_path, owner, surfaces=surfaces)


def test_chargeable_liquid_edge_is_charged_on_commit_and_survives_reload(tmp_path):
    """A real liquid edge is charged as movement when the move commits, and the charge
    survives a cold reload. Without the shared segment surcharge the committed cost is a
    plain dry step, which is the menu-price-versus-execution defect this protects."""
    surface = {'id': 'swim-edge', 'kind': 'water', 'cells': [[2, 6], [1, 6]], 'z': 0, 'capacity_lb': 0,
               'fragile': False, 'trigger': 'weight'}
    c, t, mid = _surface_game(tmp_path, [surface])
    engine = c._load_session(mid).engine
    before = engine.state.actors[A].movement_remaining_ft
    liquid = next(row for row in engine.legal_candidates()
                  if row.kind.value == 'MOVE' and row.destination == Position(x=2, y=6))
    settle(t, mid, liquid.candidate_id)

    engine = c._load_session(mid).engine
    assert c._load_session(mid).mechanical.replay()['status'] == 'PASS'
    spent = before - engine.state.actors[A].movement_remaining_ft
    assert spent > 5, 'a chargeable liquid edge spends more movement than a dry square'
    committed = next(e for e in reversed(engine.events)
                     if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == A)
    assert committed.payload['cost_ft'] == spent, 'the committed event records what was spent'

    # The surface is recorded, so the next liquid edge stays chargeable after the reload.
    settle(t, mid, t.state(mid)['menu']['end_turn'])
    turn(t, mid, A)
    engine = c._load_session(mid).engine
    assert [c for c in engine.state.actors[A].conditions.values()
            if c.data.get('surface_id') == 'swim-edge'], 'standing in water records the surface'
    before = engine.state.actors[A].movement_remaining_ft
    deeper = next(row for row in engine.legal_candidates()
                  if row.kind.value == 'MOVE' and row.destination == Position(x=1, y=6))
    settle(t, mid, deeper.candidate_id)
    engine = c._load_session(mid).engine
    assert before - engine.state.actors[A].movement_remaining_ft > 5, \
        'the liquid surcharge is still charged on the second edge'


def test_a_dry_edge_costs_one_plain_step(tmp_path):
    """The liquid surcharge must not leak onto ordinary ground."""
    c, t, mid = _surface_game(tmp_path, [])
    engine = c._load_session(mid).engine
    before = engine.state.actors[A].movement_remaining_ft
    dry = next(row for row in engine.legal_candidates()
               if row.kind.value == 'MOVE' and row.destination == Position(x=3, y=5))
    assert dry.movement_cost_ft == 5, 'a dry square costs one plain 5-foot step'
    settle(t, mid, dry.candidate_id)
    engine = c._load_session(mid).engine
    assert before - engine.state.actors[A].movement_remaining_ft == 5


# ------------------------------------------------- 4. A stuck descent cannot spin forever

def test_a_descent_that_never_gets_lower_stops_with_an_explicit_error(tmp_path, monkeypatch):
    """The journey fall resolver used to spin for unlimited rounds when a falling
    creature kept changing position without ever losing altitude, which is what
    stalled the Cloud Walker test files at full CPU. It must stop promptly instead."""
    import pytest
    from combat import falling, journey_falling
    from combat.journey_replay import body

    cold, jid, act, aid, bid = _large_journey(tmp_path, {'x': 4, 'y': 6})
    session = cold().journeys.load(jid)
    session.state['actors'][aid]['position'] = {'x': 3, 'y': 6, 'z': 3}
    session.state['journey_falls_due'] = {aid: 'flight_withdrawn'}
    genesis = body(session.state)

    # Every settle moves the creature sideways but never lower, so the old guard,
    # which only fired when nothing moved at all, never triggered.
    def sideways_only(engine, checkpoint, intent):
        for creature in engine.state.actors.values():
            creature.position = creature.position.model_copy(update={'x': creature.position.x + 1})

    monkeypatch.setattr(falling, 'settle', sideways_only)
    monkeypatch.setattr(falling, 'required', lambda engine, creature: True)

    with pytest.raises(ValueError, match='supporting space'):
        journey_falling.resolve(session, genesis, [])