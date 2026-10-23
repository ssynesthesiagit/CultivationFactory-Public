"""Sanctuary entry is a live membership trigger, not an activation-only pulse."""
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload

BASE = 'tianxia.subpath.qi.hearthfire_cultivator.feature.'
WELCOME = BASE + 'flame_that_welcomes_all'



def test_late_entry_receives_one_chosen_recovery_and_reentry_does_not_repeat(tmp_path):
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_pb=6,
        owner_features=[BASE + 'homefire_recovery', WELCOME],
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 12, 'y': 6}, FOE: {'x': 15, 'y': 8}})
    choices = {'choice:needle.welcome_recipients': [OWNER, ALLY],
               'choice:needle.homefire_recovery': 'temp_hp'}
    settle(table, mid, candidate(combat, mid, 'Flame That Welcomes All').candidate_id, choices=choices)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == 0, 'a chosen ally outside receives no benefit yet'
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    row = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE' and c.destination
               and (c.destination.x, c.destination.y) == (11, 6))
    prompts = settle(table, mid, row.candidate_id, choices=choices)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == 12
    assert any(p['context']['reactor_id'] == ALLY for p in prompts)
    count = sum(e.event_type == 'PASSIVE_TRIGGERED' and e.payload.get('receipt_kind') == 'homefire_recovery'
                and ALLY in e.target_ids for e in engine.events)
    assert count == 1
    for point in ((12, 6), (11, 6)):
        engine = reload(tmp_path, mid)
        row = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE' and c.destination
                   and (c.destination.x, c.destination.y) == point)
        settle(table, mid, row.candidate_id, choices=choices)
    engine = reload(tmp_path, mid)
    assert sum(e.event_type == 'PASSIVE_TRIGGERED' and e.payload.get('receipt_kind') == 'homefire_recovery'
               and ALLY in e.target_ids for e in engine.events) == 1
