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
