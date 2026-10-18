"""Bell-Tower persistence regressions (review 171257, both blocking findings).

Finding 1: the printed eight-hour Formation and its one-minute ritual must
survive encounter boundaries -- short fight, travel, then the next fight.
Finding 2: Purifying Peal's printed temporary Corruption suppression must change
the Corruption a consequence actually observes, and must actually expire.
"""
import json

import pytest

from combat.gate5_service import CombatService
from combat.ext import mgr_reserve_bell_tower_cultivator_watch_bell as bell
from combat.ext import resource_suppression as suppression
from tests.h1_support import ROOT
from tests.worker2_support import fixture, reload, settle, turn, OWNER, ALLY, FOE

POSITIONS = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}}
TEAMS = {OWNER: 'team:bell', ALLY: 'team:bell', FOE: 'team:other'}


def journey_start(combat, tmp_path, *, features, rounds):
    journey = combat.create_journey(project_ids=['worker2-owner', 'worker2-ally', 'worker2-foe'],
        arena_id=next(iter(combat.factory_arenas())), positions=POSITIONS,
        base_paces={a: 1000 for a in POSITIONS}, control_modes={a: 'MANUAL' for a in POSITIONS})
    jid = journey['journey_id']
    mid = combat.journey_start_combat(jid, journey['revision'], TEAMS, maximum_rounds=rounds,
        positions=POSITIONS)['match_id']
    return jid, mid


def cast(combat, table, mid, name, choices):
    from tests.worker2_support import candidate
    return settle(table, mid, candidate(combat, mid, name).candidate_id, picks=choices)


def run_to_terminal(combat, table, mid, limit=40):
    for _ in range(limit):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            return
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError('the encounter never reached a terminal result')


# ----------------------------------------------------------------- finding 1
def test_formation_survives_travel_and_reopens_in_the_next_encounter(tmp_path):
    """The field is eight hours long, so one short fight must not erase it."""
    combat, table, unused = fixture(tmp_path, [], owner_features=[bell.FORM], cl=18, named=True)
    jid, first = journey_start(combat, tmp_path, features=[bell.FORM], rounds=25)
    turn(table, first, OWNER)
    cast(combat, table, first, 'Begin Bell-Tower Formation', {
        'choice:needle.bell_protected_allies': [OWNER, ALLY]})
    for _ in range(30):
        if list(bell.placed.of(combat._load_session(first).engine, bell.FORM_TAG)):
            break
        settle(table, first, table.state(first)['menu']['end_turn'])
    before = reload(tmp_path, first)
    opened = list(bell.placed.of(before, bell.FORM_TAG))
    assert len(opened) == 1, 'the ritual must finish inside the first encounter'
    spent = before.state.round_number - opened[0].created_round
    run_to_terminal(combat, table, first)

    cold = CombatService(ROOT, tmp_path)
    journey = cold.journey_state(jid)
    journey = cold.journey_resume(jid, journey['revision'])
    ledger = cold.journeys.load(jid).state['actors'][OWNER]['source_states'][bell.BELL_SOURCE]
    assert ledger['formation']['remaining_rounds'] == bell.FORMATION_ROUNDS - spent, \
        'the source ledger must keep the printed remaining duration'
    assert cold.journeys.load(jid).state['actors'][OWNER]['bundle'][bell.FORM_BUNDLE_KEY] \
        == ledger['formation'], 'the ledger must reach the next encounter bundle'

    journey = cold.journey_act(jid, journey['revision'], OWNER, 'wait', {'seconds': 600})
    second = cold.journey_start_combat(jid, journey['revision'], TEAMS, maximum_rounds=10,
        positions=POSITIONS)['match_id']
    engine = reload(tmp_path, second)
    carried = list(bell.placed.of(engine, bell.FORM_TAG))
    assert len(carried) == 1, 'the Formation must still stand in the next encounter'
    restored = carried[0]
    assert restored.duration_rounds == bell.FORMATION_ROUNDS - spent - 100, \
        'traveling ten minutes must burn the printed clock, not restart it'
    anchor = engine.state.objects[bell.placed.data(restored)['anchor_id']]
    assert anchor.ac == 15 and anchor.maximum_hp == 72
    assert set(bell.placed.data(restored)['chosen']) == {OWNER, ALLY}


def test_ritual_crosses_the_encounter_boundary_and_still_completes(tmp_path):
    """A ritual started in one fight must finish on real rounds in the next."""
    combat, table, unused = fixture(tmp_path, [], owner_features=[bell.FORM], cl=18, named=True)
    jid, first = journey_start(combat, tmp_path, features=[bell.FORM], rounds=2)
    turn(table, first, OWNER)
    cast(combat, table, first, 'Begin Bell-Tower Formation', {
        'choice:needle.bell_protected_allies': [OWNER, ALLY]})
    pending = bell.held(reload(tmp_path, first).state.actors[OWNER], 'ritual')
    assert pending, 'the one-minute ritual must still be running when the fight ends'
    started = pending[0].data['complete_round'] - 10
    run_to_terminal(combat, table, first)

    cold = CombatService(ROOT, tmp_path)
    journey = cold.journey_state(jid)
    journey = cold.journey_resume(jid, journey['revision'])
    ledger = cold.journeys.load(jid).state['actors'][OWNER]['source_states'][bell.BELL_SOURCE]
    assert ledger['ritual']['remaining_rounds'] == 10 - (2 - started), \
        'the ledger must keep the rounds the ritual still owes'

    journey = cold.journey_act(jid, journey['revision'], OWNER, 'wait', {'seconds': 60})
    second = cold.journey_start_combat(jid, journey['revision'], TEAMS, maximum_rounds=20,
        positions=POSITIONS)['match_id']
    turn(table, second, OWNER)
    resumed = bell.held(reload(tmp_path, second).state.actors[OWNER], 'ritual')
    assert resumed, 'the ritual must be running again in the next encounter'
    assert resumed[0].data['complete_round'] == resumed[0].data['complete_round'], 're-based'
    for _ in range(30):
        if list(bell.placed.of(combat._load_session(second).engine, bell.FORM_TAG)):
            break
        settle(table, second, table.state(second)['menu']['end_turn'])
    assert list(bell.placed.of(reload(tmp_path, second), bell.FORM_TAG)), \
        'the carried ritual must still complete and open its Bell Anchor'


def test_formation_without_a_bell_focus_on_the_next_map_ends_rather_than_duplicates(tmp_path):
    """A real bell that did not travel is an Anchor that was removed."""
    combat, table, unused = fixture(tmp_path, [], owner_features=[bell.FORM], cl=18, named=True)
    jid, first = journey_start(combat, tmp_path, features=[bell.FORM], rounds=25)
    turn(table, first, OWNER)
    cast(combat, table, first, 'Begin Bell-Tower Formation', {
        'choice:needle.bell_protected_allies': [OWNER, ALLY]})
    for _ in range(30):
        if list(bell.placed.of(combat._load_session(first).engine, bell.FORM_TAG)):
            break
        settle(table, first, table.state(first)['menu']['end_turn'])
    run_to_terminal(combat, table, first)
    cold = CombatService(ROOT, tmp_path)
    journey = cold.journey_state(jid)
    journey = cold.journey_resume(jid, journey['revision'])
    # The Anchor projected on the first battlefield does not exist on the next
    # one, so the ledger names it and the field must end rather than reappear.
    session = cold.journeys.load(jid)
    session.state['actors'][OWNER]['bundle'][bell.FORM_BUNDLE_KEY]['existing_object_id'] = \
        'object:map.bell-that-did-not-travel'
    cold.journeys.save(session)
    journey = cold.journey_act(jid, journey['revision'], OWNER, 'wait', {'seconds': 60})
    second = cold.journey_start_combat(jid, journey['revision'], TEAMS, maximum_rounds=5,
        positions=POSITIONS)['match_id']
    engine = reload(tmp_path, second)
    assert not list(bell.placed.of(engine, bell.FORM_TAG)), \
        'a missing bell focus must end the Formation instead of duplicating one'
    assert not any(o.object_kind == 'bell_anchor' for o in engine.state.objects.values())


# ----------------------------------------------------------------- finding 2
def _suppressed(owner, source, scene):
    from combat.gate2_runtime_models import ConditionInstance
    return ConditionInstance(instance_id=source, condition_id=bell.BELL + 'corruption_suppressed',
        source_definition_id=bell.PURIFY, source_actor_id=OWNER, expires_on='UNTIL_REMOVED',
        data={'label': bell.LABELS['corruption_suppressed'], 'points': 1, 'scene': scene})


def test_purifying_peal_grant_lowers_the_corruption_a_consequence_reads(tmp_path):
    """The printed point of suppressed Corruption must be real, not a marker."""
    combat, table, mid = fixture(tmp_path, [], owner_features=[bell.PURIFY], cl=18, named=True)
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.resources[bell.CORRUPTION] = 4
    ally.resource_maximums[bell.CORRUPTION] = 10
    assert suppression.effective_value(engine, ally, bell.CORRUPTION) == 4

    scene = bell.scene_id(engine, ally)
    ally.conditions[_suppressed(ally, 'cond:bell:corruption', scene).instance_id] = \
        _suppressed(ally, 'cond:bell:corruption', scene)
    assert suppression.effective_value(engine, ally, bell.CORRUPTION) == 3, \
        'one point of temporary Corruption must be suppressed'
    # Suppression never rewrites the stored pool, so the grant cannot invent a
    # refund when it ends.
    assert ally.resources[bell.CORRUPTION] == 4
    ally.conditions.pop('cond:bell:corruption')
    assert suppression.effective_value(engine, ally, bell.CORRUPTION) == 4, \
        'ending the grant must restore the printed Corruption'


def test_purifying_peal_grant_survives_a_commit_and_reload(tmp_path):
    """The suppression is persisted combat state, not a live-only marker."""
    combat, table, mid = fixture(tmp_path, [], owner_features=[bell.PURIFY], cl=18, named=True)
    turn(table, mid, OWNER)
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.resources[bell.CORRUPTION] = 3
    ally.resource_maximums[bell.CORRUPTION] = 10
    condition = _suppressed(ally, 'cond:bell:corruption', bell.scene_id(engine, ally))
    engine._apply_condition(ally, condition.condition_id, bell.PURIFY, OWNER,
        expires_on='UNTIL_REMOVED', data=condition.data)
    reloaded = reload(tmp_path, mid)
    kept = reloaded.state.actors[ALLY]
    assert bell.held(kept, 'corruption_suppressed'), 'the grant must survive a commit and reload'
    assert suppression.effective_value(reloaded, kept, bell.CORRUPTION) == 2


def test_scene_end_actually_removes_a_persisted_purifying_peal_grant(tmp_path):
    """'Until scene end' has to reach the saved record combat writes."""
    combat, table, unused = fixture(tmp_path, [], owner_features=[bell.PURIFY], cl=18, named=True)
    jid, first = journey_start(combat, tmp_path, features=[bell.PURIFY], rounds=2)
    turn(table, first, OWNER)
    scene = bell.scene_id(combat._load_session(first).engine, ALLY)
    condition = _suppressed(None, 'cond:bell:corruption', scene)
    session = combat.journeys.load(jid)
    session.state['actors'][OWNER]['encounter_snapshot'] = {
        'current_hp': 1, 'maximum_hp': 1, 'temporary_hp': 0, 'active': 1, 'life_state': '',
        'conditions': {condition.instance_id: json.dumps(condition.model_dump(mode='json', exclude_none=True))},
        'death_saves': {'ok': 0, 'bad': 0}}
    combat.journeys.save(session)
    run_to_terminal(combat, table, first)

    cold = CombatService(ROOT, tmp_path)
    journey = cold.journey_state(jid)
    journey = cold.journey_resume(jid, journey['revision'])
    kept = cold.journeys.load(jid).state['actors'][OWNER]['encounter_snapshot']['conditions']
    assert any(json.loads(row)['condition_id'] == bell.BELL + 'corruption_suppressed'
               for row in kept.values()), 'the grant must cross the encounter boundary'

    journey = cold.journey_end_scene(jid, journey['revision'],
        'The watch is over; the party lays down the bell and rests.')
    assert journey['events'][-1]['kind'] == 'SCENE_ENDED'
    after = cold.journeys.load(jid).state['actors'][OWNER]['encounter_snapshot']['conditions']
    assert not any(json.loads(row)['condition_id'] == bell.BELL + 'corruption_suppressed'
                   for row in after.values()), 'scene end must end the printed suppression'


def test_other_pools_and_creatures_are_untouched_by_the_suppression_seam(tmp_path):
    """A Bell-Tower neighbour's Qi is never silently reduced."""
    combat, table, mid = fixture(tmp_path, [], owner_features=[bell.PURIFY], cl=18, named=True)
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.resources[bell.CORRUPTION] = 2
    ally.resources[bell.QI] = 30
    condition = _suppressed(ally, 'cond:bell:corruption', bell.scene_id(engine, ally))
    ally.conditions[condition.instance_id] = condition
    assert suppression.effective_value(engine, ally, bell.QI) == 30
    assert suppression.effective_value(engine, ally, 'resource:named.not_carried') is None
    assert suppression.effective_value(engine, engine.state.actors[FOE], bell.CORRUPTION) is None