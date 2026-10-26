"""Native Body scene seam: owner-only records, live availability, receipts.

Every clause runs the real compiled character, the real table commit and a cold
reload whose replay must PASS. The scene, the suppression and the paid receipt
are derived native data; nothing here is a caller-supplied flag or a test-only
shortcut.
"""
import json

import pytest

from combat import ext
from combat.ext import body_modes_scene_resources as seam
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, resolve, turn
from tests.h1_support import ROOT, sheet

GUARD = seam.BODY_PATH + '.feature.stamina_guard'
STAMINA = 'resource:core.stamina'
RULE = 'A printed opposing technique suppresses one Body feature until the scene ends.'
REASON = 'The printed suppression applies for this scene.'


def body_bundle(actor_id, features=(GUARD,), *, cl=15, effective_cl=None):
    """A real compiled character whose owning Body Path profile carries its CL."""
    document = sheet(list(features), cl=cl, primary='Stamina')
    document.setdefault('path_and_subpath', {})['paths'] = [
        {'path_id': seam.BODY_PATH, 'effective_cl': cl if effective_cl is None else effective_cl}]
    return compile_character(document, actor_id=actor_id)


def value(feature=GUARD, **extra):
    return {'source_rule': RULE, 'source_cl': 15, 'system': 'body', 'feature_id': feature, **extra}


def travel(combat, me, foe, *, effective_cl=15):
    arena = combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    places = {me: {'x': 3, 'y': 6}, foe: {'x': 5, 'y': 6}}
    return combat.journeys.create([body_bundle(me, effective_cl=effective_cl),
                                   body_bundle(foe, features=())], arena, places,
                                  {me: 3000, foe: 3000})


def admit(combat, journey_id, revision, me, *, seconds=6, payload=None):
    return combat.journey_admit(journey_id, revision, me, 'body_suppression',
                                {'scope': 'stamina guard', 'seconds': seconds,
                                 'value': value() if payload is None else payload},
                                gm=True, reason=REASON)


def end_turn(table, mid):
    menu = table.state(mid)['menu']
    table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
              table.state(mid)['last_sequence'], [])


def test_scene_record_belongs_only_to_the_creature_that_owns_the_source(tmp_path):
    combat, table, mid = fight(tmp_path, [GUARD], left_resource='Stamina')
    engine = reload(combat, mid)
    owner = engine.state.actors[LEFT]
    records = [c for c in owner.conditions.values() if c.condition_id == seam.SCENE]
    assert len(records) == 1
    assert records[0].data['source'] == seam.BODY_PATH
    assert records[0].data['scene_id'] == 'match:' + engine.state.match_seed
    assert records[0].data['source_cl'] == 15 == seam.effective_body_cl(engine, owner)
    assert records[0].source_definition_id == seam.AUTHORITY
    # The review defect: the other combatant must never receive someone else's scene.
    assert not [c for c in engine.state.actors[RIGHT].conditions.values()
                if c.condition_id == seam.SCENE]


def test_scene_and_suppression_stay_out_of_the_player_projection(tmp_path):
    combat, table, mid = fight(tmp_path, [GUARD], left_resource='Stamina')
    engine = reload(combat, mid)
    assert seam.scene_record(engine, engine.state.actors[LEFT], seam.BODY_PATH) is not None
    projection = CombatService(ROOT, tmp_path).presentation(mid)
    row = next(a for a in projection['actors'] if a['entity_id'] == LEFT)
    shown = [c for c in row['conditions'] if c['condition_id'] == seam.SCENE]
    assert len(shown) == 1 and shown[0]['hidden'] is True and shown[0]['detail'] is None
    record = seam.scene_record(engine, engine.state.actors[LEFT], seam.BODY_PATH)
    assert record.data['scene_id'] not in json.dumps(projection)
    assert 'Body Refining scene' not in json.dumps(projection.get('feed'))
    # The option list prices nothing from the scene record itself.
    menu = table.state(mid)['menu']
    assert seam.AUTHORITY not in {group['source_definition_id'] for group in menu['actions']}


def test_compiled_body_cl_caps_the_scene_cl_and_its_availability(tmp_path):
    def cap(document, aid):
        if aid == LEFT:
            document.setdefault('path_and_subpath', {})['paths'] = [
                {'path_id': seam.BODY_PATH, 'effective_cl': 5}]
    combat, table, mid = fight(tmp_path, [GUARD], left_resource='Stamina', cl=15, sheet_edit=cap)
    engine = reload(combat, mid)
    owner = engine.state.actors[LEFT]
    assert seam.source_cl(engine, owner) == 5 == seam.effective_body_cl(engine, owner)
    assert seam.scene_record(engine, owner, seam.BODY_PATH).data['source_cl'] == 5
    assert seam.available(engine, owner, GUARD, 5) is True
    # Above the capped attainment the printed feature is no longer available, and
    # that answer survives a cold reload of the same fight.
    assert seam.available(engine, owner, GUARD, 6) is False
    assert seam.available(reload(combat, mid), engine.state.actors[LEFT], GUARD, 6) is False


def test_table_owner_suppression_is_a_recorded_fact_that_expires_in_travel(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    me, foe = 'actor:factory.seam-traveller', 'actor:factory.seam-foe'
    session = travel(combat, me, foe)
    journey_id = session['journey_id']
    admit(combat, journey_id, session['revision'], me)
    loaded = combat.journeys.load(journey_id)
    records = [r for r in loaded.state['fact_consent_admission']
               if (r['source'], r['subject'], r['kind']) == (seam.AUTHORITY, me, 'cultivation_suppression')]
    assert len(records) == 1
    record = records[0]
    # The fact is stamped at the journey's current second and expires six later;
    # nothing has elapsed yet, so the record is live until the rest crosses it.
    assert record['authority'] == 'table_owner' and record['created_at'] == 0
    assert record['expires_at'] == 6 and loaded.clock() == 0
    assert record['scope'] == 'stamina guard'
    assert sorted(record['readers']) == sorted([me, foe])
    assert record['receipt_id'] != '' and record['value'] == value()
    assert seam.journey_available(loaded, me, GUARD, 1) is False
    # The encounter-only scene bookkeeping never enters a player's journey view.
    assert 'body_scene' not in json.dumps(combat.journey_state(journey_id))
    # A creature with no Body scene cannot receive the fact at all.
    with pytest.raises(ValueError):
        admit(combat, journey_id, loaded.state['revision'], foe)
    # Resting crosses the recorded expiry; the record stays as evidence.
    combat.journey_act(journey_id, loaded.state['revision'], me, 'long_rest')
    rested = combat.journeys.load(journey_id)
    assert rested.clock() == 28800
    assert seam.journey_available(rested, me, GUARD, 1) is True
    assert len(rested.state['fact_consent_admission']) == 1


def test_suppression_carries_into_the_encounter_and_expires_on_the_slot_clock(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    me, foe = 'actor:factory.seam-carry', 'actor:factory.seam-carry-foe'
    session = travel(combat, me, foe)
    journey_id = session['journey_id']
    admit(combat, journey_id, session['revision'], me)
    loaded = combat.journeys.load(journey_id)
    scene_id = loaded.state['scene_id']
    receipt = loaded.state['fact_consent_admission'][0]['receipt_id']
    mid = combat.journey_start_combat(journey_id, loaded.state['revision'],
                                      {me: 'team:a', foe: 'team:b'})['match_id']
    engine = reload(combat, mid)
    assert seam.scene_record(engine, engine.state.actors[me], seam.BODY_PATH).data['scene_id'] == scene_id
    suppressed = [c for c in engine.state.actors[me].conditions.values()
                  if c.condition_id == seam.SUPPRESSION]
    assert len(suppressed) == 1
    data = suppressed[0].data
    assert data['receipt_id'] == receipt and data['feature_id'] == GUARD
    assert (data['body_expires_num'], data['body_expires_den']) == (6, 1)
    assert seam.available(engine, engine.state.actors[me], GUARD, 1) is False
    assert not [c for c in engine.state.actors[foe].conditions.values()
                if c.condition_id in (seam.SCENE, seam.SUPPRESSION)]
    # Two slots of scene time (three seconds each) run out the recorded six.
    end_turn(table, mid)
    still = reload(combat, mid)
    assert still.state.round_number == 1 and seam.available(still, still.state.actors[me], GUARD, 1) is False
    end_turn(table, mid)
    expired = reload(combat, mid)
    assert expired.state.round_number == 2
    assert not [c for c in expired.state.actors[me].conditions.values()
                if c.condition_id == seam.SUPPRESSION]
    assert seam.available(expired, expired.state.actors[me], GUARD, 1) is True
    assert any(e.event_type == 'CONDITION_REMOVED' and e.source_definition_id == seam.AUTHORITY
               and e.payload.get('condition_id') == seam.SUPPRESSION for e in expired.events)


def test_the_next_encounter_rederives_the_record_instead_of_importing_it(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    me, foe = 'actor:factory.seam-second', 'actor:factory.seam-second-foe'
    session = travel(combat, me, foe)
    journey_id = session['journey_id']
    admit(combat, journey_id, session['revision'], me, seconds=20)
    mid = combat.journey_start_combat(journey_id, combat.journey_state(journey_id)['revision'],
                                      {me: 'team:a', foe: 'team:b'}, maximum_rounds=1)['match_id']
    for _ in range(20):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            break
        end_turn(table, mid)
    else:
        raise AssertionError('the round cap did not end the encounter')
    resumed = combat.journey_resume(journey_id, combat.journey_state(journey_id)['revision'])
    # Six encounter seconds leave fourteen; ten seconds of travel must leave four,
    # even after the journey is committed and reloaded.
    combat.journey_act(journey_id, resumed['revision'], me, 'wait', {'seconds': 10})
    resumed = combat.journey_state(journey_id)
    snapshot = combat.journeys.load(journey_id).state['actors'][me]['encounter_snapshot']
    # The continuation snapshot carries neither the scene record nor the recorded
    # suppression: both are re-derived from the current scene and the live fact.
    assert all(seam.SCENE not in raw and seam.SUPPRESSION not in raw
               for raw in snapshot['conditions'].values())
    mid = combat.journey_start_combat(journey_id, resumed['revision'],
                                      {me: 'team:a', foe: 'team:b'})['match_id']
    engine = reload(combat, mid)
    owner = engine.state.actors[me]
    assert seam.scene_record(engine, owner, seam.BODY_PATH).data['scene_id'] == journey_id + ':scene:0'
    suppressed = [c for c in owner.conditions.values() if c.condition_id == seam.SUPPRESSION]
    assert len(suppressed) == 1
    assert seam.available(engine, owner, GUARD, 1) is False
    assert (suppressed[0].data['body_expires_num'],
            suppressed[0].data['body_expires_den']) == (4, 1)
    assert not [c for c in engine.state.actors[foe].conditions.values()
                if c.condition_id in (seam.SCENE, seam.SUPPRESSION)]


def test_only_the_table_owner_scene_end_renews_the_scene_identity(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    me, foe = 'actor:factory.seam-scene', 'actor:factory.seam-scene-foe'
    session = travel(combat, me, foe)
    journey_id = session['journey_id']
    start = combat.journey_state(journey_id)
    assert start['scene_id'] == journey_id + ':scene:0' and start['scene_number'] == 0
    with pytest.raises(ValueError):
        combat.journey_end_scene(journey_id, start['revision'], '  ')
    with pytest.raises(ValueError):
        combat.journey_end_scene(journey_id, start['revision'] + 7, REASON)
    rested = combat.journey_act(journey_id, start['revision'], me, 'long_rest')
    assert rested['scene_id'] == start['scene_id']
    ended = combat.journey_end_scene(journey_id, rested['revision'], REASON)
    assert (ended['scene_id'], ended['scene_number']) == (journey_id + ':scene:1', 1)
    event = combat.journeys.load(journey_id).state['events'][-1]
    assert event['kind'] == 'SCENE_ENDED' and event['authority'] == 'table_owner'
    assert (event['previous_scene'], event['next_scene']) == (start['scene_id'], ended['scene_id'])
    assert event['reason'] == REASON
    again = combat.journey_act(journey_id, ended['revision'], me, 'long_rest')
    assert again['scene_id'] == ended['scene_id']
    mid = combat.journey_start_combat(journey_id, again['revision'],
                                      {me: 'team:a', foe: 'team:b'})['match_id']
    engine = reload(combat, mid)
    assert seam.scene_record(engine, engine.state.actors[me], seam.BODY_PATH).data['scene_id'] == ended['scene_id']


def test_paid_activation_receipt_comes_from_the_real_stamina_payment(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, [GUARD], left_resource='Stamina',
                              cause=[{'type': 'damage', 'flat': 5, 'damage_types': ['force']}],
                              cause_save_dc=8)
    turn(table, mid, RIGHT)
    ext._load()
    receipts = []
    monkeypatch.setitem(ext._HOOKS, 'paid_activation_resolved',
                        [*ext._HOOKS.get('paid_activation_resolved', []),
                         lambda engine, actor, receipt: receipts.append((engine, actor.entity_id, receipt))])
    resolve(lambda answers: act(table, mid, 'Cause', answers, target_id=LEFT))
    engine = reload(combat, mid)
    assert receipts, 'the owning source notified its paid activation'
    assert len({id(item[0]) for item in receipts}) == len(receipts), 'one receipt per engine instance'
    payloads = {json.dumps(item[2], sort_keys=True) for item in receipts}
    assert len(payloads) == 1, 'the derived receipt is identical on every engine instance'
    receipt = receipts[0][2]
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
             and e.source_definition_id == GUARD]
    assert len(spent) == 1 and receipt['paid'] == int(spent[0].payload['amount']) == 1
    assert receipt['source'] == GUARD
    assert receipt['payment_sequences'] == [spent[0].sequence]
    assert receipt['turn'] == seam.turn_key(engine) and receipt['round'] == 1
    assert receipt['source_cl'] == 15 and receipt['completion_sequence'] > spent[0].sequence
    assert engine.state.actors[LEFT].resources[STAMINA] == 99
    # The receipt is a notification: it never pays back, and a non-owner never notifies.
    assert not [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
                and e.source_definition_id == GUARD]
    assert all(item[1] == LEFT for item in receipts)
