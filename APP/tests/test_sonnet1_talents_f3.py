"""R3 armor lifecycle findings through table commits and cold replay."""
import pytest
from combat import carry, stealth
from combat.gate4_context import build_decision_context
from tests import auto11_service_support as S
from tests.cw2_service_support import add_action
from tests.test_sonnet1_talents_f1 import STASH, cold
from tests.test_sonnet1_talents_f2 import stash_answer
from tests.test_a2_treasure_armor_enhancements import kit, AUTH


def armor_kit():
    result = kit('fire_shedding_lining')
    result['resolved_treasure_armor']['chassis'] = next(
        r for r in AUTH['chassis'] if r['name'] == 'Full Lamellar Battle Dress')
    return result


@pytest.mark.parametrize('check', ['speed', 'hide'])
def test_stored_armor_penalties_follow_location_after_table_reload(tmp_path, monkeypatch, check):
    original_doc = S._doc
    def weak_wearer(*args, **kwargs):
        doc = original_doc(*args, **kwargs)
        for row in doc['ability_scores_and_statistics']['abilities']:
            if row['ability'] == 'STR':
                row.update(score=12, modifier=1)
        return doc
    monkeypatch.setattr(S, '_doc', weak_wearer)
    # Isolate the armor roll mode from map concealment; still roll real Hide via the table.
    monkeypatch.setattr(stealth, 'can_hide', lambda *a, **kw: True)
    combat, table, mid = S.fight(tmp_path, [STASH], thief_kit=armor_kit())
    engine = S.engine(combat, mid)
    actor = engine.state.actors[S.THIEF]
    [item] = carry.carrying_of(engine, S.THIEF)['items']
    assert item['worn'] and not carry.status(engine, actor)['over']
    assert engine._effective_speed(actor) == 20
    movement = actor.movement_remaining_ft
    identity = f"{S.THIEF}|{item['key']}"
    assert S.play(table, mid, S.candidate(table, mid, 'Store an object'),
                  answer=stash_answer(identity))[0]['status'] == 'COMMITTED'
    combat, table, engine = cold(combat, mid)
    actor = engine.state.actors[S.THIEF]
    if check == 'speed':
        assert carry.status(engine, actor)['speed_ft'] == 30
        assert engine._effective_speed(actor) == 30
        assert actor.movement_remaining_ft == movement + 10
    else:
        assert S.play(table, mid, S.candidate(table, mid, 'Hide'))[0]['status'] == 'COMMITTED'
        _, _, engine = cold(combat, mid)
        checks = [e.payload for e in engine.events if e.event_type == 'CHECK_ROLLED'
                  and e.payload.get('check') == 'Stealth']
        assert checks[-1]['actor']['mode'] == 'NORMAL'


def test_spilled_originally_worn_armor_is_recoverable_by_owner_and_ai_after_reload(tmp_path, monkeypatch):
    original = S.compile_character
    def compile_setup(doc, **kw):
        bundle = original(doc, **kw)
        if kw['actor_id'] == S.THIEF:
            add_action(bundle, 'Receive armor', [{'type': 'transfer_object', 'item': 'treasure_armor',
                'object': f'{S.VICTIM}|treasure_armor', 'as': 'take'}])
        if kw['actor_id'] == S.VICTIM:
            add_action(bundle, 'Fatal wound', [{'type': 'damage', 'flat': 150, 'damage_type': 'FORCE'}])
        return bundle
    monkeypatch.setattr(S, 'compile_character', compile_setup)
    combat, table, mid = S.fight(tmp_path, [STASH], thief_kit=armor_kit(), victim_kit=armor_kit(), ally=True)
    identity = f'{S.VICTIM}|treasure_armor'
    assert S.play(table, mid, S.candidate(table, mid, 'Receive armor', target=S.VICTIM))[0]['status'] == 'COMMITTED'
    assert S.play(table, mid, S.candidate(table, mid, 'Store an object'),
                  answer=stash_answer(identity))[0]['status'] == 'COMMITTED'
    while table.state(mid)['menu']['actor_id'] != S.VICTIM:
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    assert S.play(table, mid, S.candidate(table, mid, 'Fatal wound', target=S.THIEF))[0]['status'] == 'COMMITTED'
    combat, table, engine = cold(combat, mid)
    actor = engine.state.actors[S.VICTIM]
    [record] = [r for r in actor.conditions.values() if r.data.get('object_id') == identity]
    assert record.condition_id == carry.DROPPED
    from combat.gate2_runtime_models import Position
    ground = Position(**record.data['dropped_at'])
    move = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination is not None
                and engine.grid.distance_ft(c.destination, ground) <= 5)
    assert S.play(table, mid, move.candidate_id)[0]['status'] == 'COMMITTED'
    engine = S.engine(combat, mid)
    policy, _ = combat.policies.for_actor(S.VICTIM)
    assert any('Pick up Test treasure armor' in c.display_name
               for c in build_decision_context(engine, policy, for_ai=True).legal_candidates)
    assert S.play(table, mid, S.candidate(table, mid, 'Pick up Test treasure armor'))[0]['status'] == 'COMMITTED'
    combat, table, engine = cold(combat, mid)
    actor = engine.state.actors[S.VICTIM]
    assert carry.holds(engine, actor, 'treasure_armor')
    assert carry.dropped(actor, 'treasure_armor') is None
    assert carry.owned_item_location(actor, 'treasure_armor') == 'carried'
    assert carry.lost_to_another_hand(actor, 'treasure_armor')  # pickup does not don armor
    assert carry.weight(engine, actor) == 55
    assert carry.holds(engine, engine.state.actors[S.THIEF], 'treasure_armor')
    assert not any(r.data.get('stashed_by') for a in engine.state.actors.values() for r in a.conditions.values())
    # Recovered armor is ordinary carried gear, so its next Drop remains reachable.
    assert S.play(table, mid, S.candidate(table, mid, 'Drop Test treasure armor'))[0]['status'] == 'COMMITTED'
    _, _, engine = cold(combat, mid)
    actor = engine.state.actors[S.VICTIM]
    assert carry.dropped(actor, 'treasure_armor') is not None
    assert carry.weight(engine, actor) == 0
