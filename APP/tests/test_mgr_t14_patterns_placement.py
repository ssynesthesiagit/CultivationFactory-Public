"""Native intents, committed placement state and cold replay."""
import pytest
from combat.ext import placed
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
DART = 'TRAP_BASE_DART_MECHANISM'
TRIP = 'TRAP_BASE_TRIPWIRE'
SET = 'FORMATIONS_BASE_SET_ARRAY'


def setup(tmp_path, row, cl=5):
    return fixture(tmp_path, [row], cl=cl, positions={OWNER: {'x': 3, 'y': 6},
        ALLY: {'x': 2, 'y': 6}, FOE: {'x': 6, 'y': 5}})


def arm(combat, table, mid, form, cells=()):
    settle(table, mid, candidate(combat, mid, 'Trap form: ' + form).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Trap aim: east').candidate_id)
    return settle(table, mid, candidate(combat, mid, 'Set Trap', at=(4, 7)).candidate_id,
                  {'choice:needle.trap_footprint': tuple([*cells, 'finish'])})


@pytest.mark.parametrize('cl,cap', [(1, 1), (5, 2), (10, 3), (15, 4)])
def test_connected_footprint_cap_reload(tmp_path, cl, cap):
    combat, table, mid = setup(tmp_path, TRIP, cl)
    prompts = arm(combat, table, mid, 'Tripwire', ['cell:3,7,0', 'cell:2,7,0', 'cell:2,6,0'][:cap-1])
    e = reload(tmp_path, mid)
    z = placed.of(e, 'trap')[0]
    assert len(z.affected_cells) == cap
    assert all(e._distance_actor_to_cell(e.state.actors[OWNER], p) <= 5 for p in z.affected_cells)
    for p in prompts:
        if p['context']['reaction_source_id'] == 'choice:needle.trap_footprint':
            assert 'cell:3,6,0' not in {o['id'] for o in p['choice']['options']}


@pytest.mark.parametrize('form,row', [('Dart Mechanism', DART), ('Tripwire', TRIP)])
def test_trigger_second_cell_and_reload(tmp_path, form, row):
    combat, table, mid = setup(tmp_path, row)
    arm(combat, table, mid, form, ['cell:4,6,0'])
    turn(table, mid, FOE)
    e = combat._load_session(mid).engine
    move = next(c for c in e.legal_candidates() if c.kind.value == 'MOVE' and c.destination and
                (c.destination.x, c.destination.y) == (4, 6))
    prompts = settle(table, mid, move.candidate_id, {'choice:needle.trap_dart_origin': 'cell:4,6,0'})
    e = reload(tmp_path, mid)
    if row == DART:
        origins = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.trap_dart_origin']
        assert origins
        assert {o['id'] for o in origins[0]['choice']['options']} == {'cell:4,7,0', 'cell:4,6,0'}
        assert not placed.of(e, 'trap')
    else:
        assert placed.of(e, 'trap')
        assert any(v.event_type == 'SAVE_ROLLED' and v.actor_id == FOE for v in e.events)


def test_pulse_bound_array_round_key(tmp_path):
    combat, table, mid = setup(tmp_path, SET, 15)
    settle(table, mid, candidate(combat, mid, 'Combat Array: Locking Gate', at=(5, 6)).candidate_id)
    e = reload(tmp_path, mid)
    row = candidate(combat, mid, 'Pulse: Locking Gate', target=FOE)
    z = next(z for z in e.state.zones.values() if z.active and z.trigger_profile.get('formation'))
    assert row.metadata['effect_origin']['id'] == 'formation:' + z.zone_id
    settle(table, mid, row.candidate_id)
    e = reload(tmp_path, mid)
    assert e.state.actors[FOE].turn_flags['formation_round_pulse:locking_gate'] == e.state.round_number
