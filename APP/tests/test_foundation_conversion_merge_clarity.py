"""The shared multi-resource provider still settles native Severing Clarity."""
from combat.ext.foundation_conversion_bonus import CLOCK
from tests.test_a2_foundations4 import setup, S, POOLS
from tests.worker2_support import OWNER, FOE, candidate, settle, reload, turn


def test_perfected_clarity_settles_explicit_pool_and_cold_replays(tmp_path):
    combat, table, mid = setup(tmp_path, stage='Perfected', held=1, ask=True, prepare=True)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Pin owner', target=OWNER).candidate_id)
    turn(table, mid, OWNER)
    source = 'foundation.sword_bones_v0_2B.severing_clarity'
    settle(table, mid, candidate(combat, mid, 'Escape grapple').candidate_id,
           choices={'reaction:typed.' + source: 'USE'})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == OWNER]
    assert checks[-1].payload['actor']['modifier'] == 10
    assert len(checks[-1].payload['actor']['dice']) == 1
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
             and e.actor_id == OWNER and e.payload.get('resource_id') == POOLS[S]]
    assert len(spent) == 1 and spent[0].payload['amount'] == 1
    receipt = actor.turn_flags[CLOCK]['receipt']
    assert receipt['bonus'] == 4
    assert receipt['payment_sequence'] == spent[0].sequence
    assert all(type(value) in (str, int) for value in receipt.values())
    assert not actor.resources[POOLS[S]]
    assert combat._load_session(mid).verify()['status'] == 'PASS'
