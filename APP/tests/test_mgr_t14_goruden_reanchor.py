"""Carried native fields use encounter setup squares before any movement."""
from combat import zones
from combat.tabletop_service import TabletopService
from tests.test_mgr_t14_goruden import G, ready
from tests.test_mgr_t14_goruden_continuation import native_journey, end_window
from tests.worker2_support import candidate, reload, settle, turn


def test_acquired_aura_reanchors_before_membership_and_first_turn(
        catalog_environment, monkeypatch, tmp_path):
    cold, jid, owner, foe = native_journey(
        catalog_environment, monkeypatch, tmp_path, foe_first=True)
    state = cold().journey_state(jid)
    # The owner casts last in round one. Let its next native start-turn grant
    # the printed temporary HP before carrying the field into another match.
    result = cold().journey_start_combat(
        jid, state['revision'], {owner: 'gold', foe: 'trial'}, maximum_rounds=2)
    mid = result['match_id']
    table = TabletopService(cold(), tmp_path)
    ready(table, tmp_path, mid)
    turn(table, mid, owner)
    settle(table, mid, candidate(cold(), mid, 'Golden Aura').candidate_id)
    state = end_window(cold, jid, tmp_path, mid)
    before = reload(tmp_path, mid)
    zone = next(z for z in before.state.zones.values()
                if z.active and z.owner_id == owner)
    zid = zone.zone_id
    marks = set(zone.per_turn_triggered)
    spent = before.state.actors[owner].resources.copy()
    assert before.state.actors[owner].temporary_hp > 0
    assert zones.actor_inside_zone(before, before.state.actors[foe], zone)

    result = cold().journey_start_combat(
        jid, state['revision'], {owner: 'gold', foe: 'trial'}, maximum_rounds=1,
        positions={owner: {'x': 12, 'y': 12}, foe: {'x': 4, 'y': 6}})
    mid = result['match_id']

    def check():
        engine = reload(tmp_path, mid)  # Cold load also verifies mechanical replay.
        carried = engine.state.zones[zid]
        assert carried.center == engine.state.actors[owner].position
        assert zones.actor_inside_zone(engine, engine.state.actors[owner], carried)
        assert not zones.actor_inside_zone(engine, engine.state.actors[foe], carried)
        assert any(c.data.get('rule', {}).get('save_against')
                   for c in engine.state.actors[owner].conditions.values())
        assert not any(c.data.get('rule', {}).get('save_against')
                       for c in engine.state.actors[foe].conditions.values())
        assert marks <= set(carried.per_turn_triggered)
        assert engine.state.actors[owner].resources == spent
        assert not any(ev.event_type == 'TEMP_HP_GRANTED' and owner in ev.target_ids
                       for ev in engine.events)
        assert not any(ev.event_type == 'SAVE_ROLLED' and ev.actor_id == foe
                       and ev.source_definition_id == carried.source_definition_id
                       for ev in engine.events)
        return engine

    check()  # Setup committed; no turn or movement is needed to anchor the field.
    ready(TabletopService(cold(), tmp_path), tmp_path, mid)
    engine = check()
    assert engine.state.current_actor_id == foe
    assert not any(ev.event_type == 'MOVED' for ev in engine.events)

    # A second journey preserves the same roster/order. The hostile start in
    # each is round 1, slot 1: carrying its old turn stamp unchanged would
    # suppress the second scene's save.
    collision_path = tmp_path / 'collision'
    cold, jid, owner, foe = native_journey(
        catalog_environment, monkeypatch, collision_path)
    state = cold().journey_state(jid)
    result = cold().journey_start_combat(
        jid, state['revision'], {owner: 'gold', foe: 'trial'}, maximum_rounds=2)
    mid = result['match_id']
    table = TabletopService(cold(), collision_path)
    ready(table, collision_path, mid)
    turn(table, mid, owner)
    settle(table, mid, candidate(cold(), mid, 'Golden Aura').candidate_id)
    turn(table, mid, foe)
    first = reload(collision_path, mid)
    zone = next(z for z in first.state.zones.values() if z.active and z.owner_id == owner)
    zid, source = zone.zone_id, zone.source_definition_id
    stamp = first.state.round_number * 1000 + first.state.current_slot_index
    assert stamp == 1001
    assert len([ev for ev in first.events if ev.event_type == 'SAVE_ROLLED'
                and ev.actor_id == foe and ev.source_definition_id == source]) == 1
    assert stamp in zone.per_turn_triggered.values()
    # Leave the field after the first save, so round two cannot overwrite its
    # stamp. The owner's next turn grants its once-per-activation temporary HP.
    move = next(c for c in first.legal_candidates() if c.kind.value == 'MOVE'
                and c.destination and c.destination.x == 7 and c.destination.y == 6)
    settle(table, mid, move.candidate_id)
    state = end_window(cold, jid, collision_path, mid)
    first = reload(collision_path, mid)
    assert first.state.actors[owner].temporary_hp > 0
    assert stamp in first.state.zones[zid].per_turn_triggered.values()

    result = cold().journey_start_combat(
        jid, state['revision'], {owner: 'gold', foe: 'trial'}, maximum_rounds=1,
        positions={owner: {'x': 3, 'y': 6}, foe: {'x': 4, 'y': 6}})
    mid = result['match_id']
    table = TabletopService(cold(), collision_path)
    ready(table, collision_path, mid)
    turn(table, mid, foe)
    # Cold loads replay the committed transition, including the new save and
    # the once-per-activation temporary-HP receipt, not just the live engine.
    for _ in range(2):
        carried = reload(collision_path, mid)
        assert carried.state.round_number * 1000 + carried.state.current_slot_index == stamp
        assert zones.actor_inside_zone(carried, carried.state.actors[foe], carried.state.zones[zid])
        assert len([ev for ev in carried.events if ev.event_type == 'SAVE_ROLLED'
                    and ev.actor_id == foe and ev.source_definition_id == source]) == 1
        assert not any(ev.event_type == 'TEMP_HP_GRANTED' and owner in ev.target_ids
                       for ev in carried.events)
