"""Source-compiled owners prove flight grants, launches and safe falling."""
import pytest
from combat import falling, flight
from combat.ext.altitude_abilities import WIND, GATHER, FEATHER, UPPERCUT, FEATHER_CONDITION
from combat.gate2_runtime_models import ReactionDecision, Position
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, ME, FOE, ALLY, duel, script
from tests.test_lock10_flight_movement import request
from tests.test_lock10_falling import prone
from tests.test_tabletop_hunt6 import table_fight, on_hold, HOLD, LEFT
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import answer


@pytest.mark.parametrize('level,speed', [(5,20), (11,30)])
def test_compiled_wind_borne_body_grants_native_flight_after_gather(level, speed):
    e = duel([WIND], cl=level)
    a = e.state.actors[ME]
    candidates = [c for c in e.legal_candidates() if c.source_definition_id in e.action_catalog
                  and e.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source') == GATHER]
    assert candidates
    e.execute_intent(request(candidates[0]))
    assert flight.profile(e, a).speed_ft == speed
    assert any(c.destination.z for c in e.legal_candidates() if c.kind == 'MOVE')
    a.position = a.position.model_copy(update={'z':2})
    script(e, [1])
    e.end_turn()
    assert a.position.z == 0 and flight.profile(e, a).speed_ft == 0


def _choose_all(engine):
    def provider(row):
        spec = row.get('extension_choice') or {}
        options = row.get('legal_option_ids', [])[:spec.get('maximum_selections', 1)]
        return ReactionDecision(checkpoint=row['checkpoint'], reactor_id=row['reactor_id'],
            reaction_source_id=row['reaction_source_id'], selection='USE', option_ids=tuple(options)), None
    engine.set_reaction_provider(provider)


def test_featherfall_selects_multiple_targets_pays_each_and_uses_one_reaction():
    e = duel([FEATHER], ally_mids=[])
    a, ally = e.state.actors[ME], e.state.actors[ALLY]
    _choose_all(e)
    qi, hp = a.resources['resource:core.qi'], (a.current_hp, ally.current_hp)
    for target in (a, ally):
        target.position = target.position.model_copy(update={'z':16})
    # Put the source at their altitude: range is measured in three dimensions.
    intent = request(next(c for c in e.legal_candidates() if c.kind == 'END_TURN'))
    falling.settle(e, 'test:launch', intent)
    assert a.resources['resource:core.qi'] == qi-2 and not a.reaction_available
    assert (a.position.z, ally.position.z) == (4,4)
    assert (a.current_hp, ally.current_hp) == hp
    assert not prone(a) and not prone(ally)
    assert all(any(c.condition_id == FEATHER_CONDITION and c.expires_on.startswith('START_OF_SLOT_AT:')
                   for c in target.conditions.values()) for target in (a,ally))
    falling.settle(e, 'test:same_round', intent)
    assert a.position.z == 4
    e.state.round_number += 1
    falling.settle(e, 'test:next_round', intent)
    assert a.position.z == ally.position.z == 0


@pytest.mark.parametrize('blocked', ['qi','reaction','range'])
def test_featherfall_respects_payment_reaction_and_vertical_range(blocked):
    e = duel([FEATHER], ally_mids=[])
    a, target = e.state.actors[ME], e.state.actors[ALLY]
    if blocked == 'qi':
        a.resources['resource:core.qi'] = 0
    elif blocked == 'reaction':
        e._apply_condition(a, 'condition:typed.stunned', 'test:stun', FOE, expires_on=None)
    target.maximum_hp = 500
    target.current_hp = 500
    script(e, [1]*20)
    falling.displace(e, target, 14 if blocked == 'range' else 2, 'test:launch')
    assert target.position.z == 0 and target.current_hp < 500 and prone(target)
    assert not any(c.condition_id == FEATHER_CONDITION for c in target.conditions.values())


def test_featherfall_table_pause_rolls_back_launch_and_costs_then_reload(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [FEATHER], ask=True)
    def launch(engine):
        falling.displace(engine, engine.state.actors[LEFT], 16, 'test:launch')
    on_hold(monkeypatch, launch)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    state = table.state(mid)
    menu = state['menu']
    group = next(g for g in menu['actions'] if g['source_definition_id'].startswith(HOLD))
    cid = group['options'][0]['candidate_id']
    send = lambda answers=(): table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], list(answers))
    result = send()
    assert result['status'] == 'REACTION_REQUIRED'
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    choice = answer(result['reaction'], use=True)
    result = send([choice])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].position.z == 4
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_launching_uppercut_is_a_real_chosen_counter_after_damage():
    from tests.test_h2_counterstrike import _fighter, _prepare, _attacked, ME as counter_owner
    e = _fighter(talents=['RETRIBUTION_BASE_COUNTERSTRIKE', UPPERCUT])
    _prepare(e, 'Counterstrike + Launching Uppercut')
    e.end_turn()
    original = e._gate4_reaction_provider
    def provider(row):
        if row['reaction_source_id'] == 'choice:needle.launching_uppercut':
            return ReactionDecision(checkpoint=row['checkpoint'], reactor_id=row['reactor_id'],
                reaction_source_id=row['reaction_source_id'], selection='USE', option_ids=('launch',)), None
        return original(row)
    e.set_reaction_provider(provider)
    script(e, [10,2,2,2,2,10,2,2])
    events = _attacked(e)
    assert e.state.actors[counter_owner].resources['resource:core.martial_focus'] == 0
    assert any(ev.event_type == 'MOVEMENT_COMMITTED' and ev.source_definition_id == UPPERCUT
               and ev.payload['destination']['z'] == 2 for ev in events)
    assert any(ev.payload.get('fall_distance_ft') == 10 for ev in events)
    assert e.state.actors[FOE].position.z == 0 and prone(e.state.actors[FOE])


@pytest.mark.parametrize('flying', [False, True])
def test_launching_uppercut_ends_move_even_when_safe_fall_returns_to_start(flying):
    from tests.test_h2_counterstrike import _fighter, _answering, _use, _foe_does
    e = _fighter(talents=['RETRIBUTION_BASE_COUNTERSTRIKE', UPPERCUT])
    _answering(e, trigger='leaves')
    _use(e, 'Counterstrike + Launching Uppercut')
    e.end_turn()
    target = e.state.actors[FOE]
    target.fly_speed_ft = 30 if flying else 0
    e._apply_condition(target, 'condition:typed.test_safe_fall', 'test:safe', FOE,
        expires_on=None, data={'fall_damage_immune':1, 'fall_lands_upright':1})
    original = e._gate4_reaction_provider
    def provider(row):
        if row['reaction_source_id'] == 'choice:needle.launching_uppercut':
            return ReactionDecision(checkpoint=row['checkpoint'], reactor_id=row['reactor_id'],
                reaction_source_id=row['reaction_source_id'], selection='USE', option_ids=('launch',)), None
        return original(row)
    e.set_reaction_provider(provider)
    script(e, [10,2,2,2])
    start, remaining = target.position, target.movement_remaining_ft
    events = _foe_does(e, lambda c: c.kind == 'MOVE' and c.destination == Position(x=6,y=6))
    assert target.position == start.model_copy(update={'z':2 if flying else 0}) and target.movement_remaining_ft == remaining
    assert not prone(target)
    assert any(ev.source_definition_id == UPPERCUT for ev in events)
    if not flying:
        _foe_does(e, lambda c: c.kind == 'MOVE' and c.destination == Position(x=6,y=6))
        assert target.position == Position(x=6,y=6)  # later movement is still available


def test_featherfall_holder_can_end_effect_at_own_turn_start():
    from combat.ext.altitude_abilities import flight_turn
    e = duel([FEATHER])
    a = e.state.actors[ME]
    falling.displace(e, a, 16, 'test:launch')
    assert a.position.z == 4
    def provider(row):
        return ReactionDecision(checkpoint=row['checkpoint'], reactor_id=row['reactor_id'],
            reaction_source_id=row['reaction_source_id'], selection='USE', option_ids=('end',)), None
    e.set_reaction_provider(provider)
    e._active_intent = request(next(c for c in e.legal_candidates() if c.kind == 'END_TURN'))
    script(e, [1,1])
    flight_turn(e,a)
    assert a.position.z == 0 and not any(c.condition_id == FEATHER_CONDITION for c in a.conditions.values())
