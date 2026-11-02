"""AI uses the actual increased same-roll benefit, with no live model calls."""
from tests.test_a2_foundations4 import setup, S, POOLS
from tests.test_bone_perfected_parent import PREFIX, receipts
from tests.worker2_support import OWNER, FOE, candidate, settle, reload, turn


def test_ai_clarity_uses_perfected_quote_when_base_pb_would_not_succeed(tmp_path):
    # Establish the actual native roll in a separate, declined control. No
    # roller or engine method is replaced, and the two trials use the same seed.
    probe_path = tmp_path / 'probe'
    combat, table, mid = setup(probe_path, stage='Refined', held=1, ask=True, prepare=True)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Prone pressure', target=OWNER).candidate_id,
           choices={'reaction:typed.' + PREFIX + 'severing_clarity': None})
    engine = reload(probe_path, mid)
    first_save = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER)
    unboosted = first_save.payload['total']
    trial_path = tmp_path / 'trial'
    combat, table, mid = setup(trial_path, stage='Perfected', held=1, ask=True, prepare=True,
                              pressure_dc=unboosted + 6)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, candidate(combat, mid, 'Prone pressure', target=OWNER).candidate_id)
    engine = reload(trial_path, mid)
    assert not prompts
    save = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER)
    assert save.payload['modifier'] == 10
    assert save.payload['total'] == unboosted + 8
    assert save.payload['success']
    assert len(receipts(engine)) == 1
    assert engine.state.actors[OWNER].resources[POOLS[S]] == 0
    assert engine.state.actors[OWNER].reaction_available
