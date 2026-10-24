"""AUTO131: the Trap owner names the spaces two printed talents put on the table.

Hundred-Mechanism Scripture says "set up to three traps instead. Each trap must occupy different legal spaces within your
reach", and Trap Within the Trap says "immediately place one additional trap in one unoccupied space within 5 feet of the
original trap". Both are the owner's choice of space; before this the table silently took the nearest free square, which the
coverage report recorded as a GM reminder. These cases drive real table decisions through the compiled character, commit
them, reload the fight from disk and check the traps are where the owner pointed.
"""
import pytest

from combat.ext import placed
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, turn, reload
from tests.test_r9i_karma_persistence import act

HUNDRED = 'tianxia.talent.trap.hundred_mechanism_scripture'
WITHIN = 'TAL_TRAP_TRAP_WITHIN_THE_TRAP'
FALSE = 'TAL_TRAP_FALSE_TRIGGER'
HUNDRED_ACTION = 'Set Trap x3 (Hundred-Mechanism Scripture)'
WITHIN_CHOICE = 'choice:needle.trap_within_cell'
HUNDRED_CHOICE = 'choice:needle.trap_hundred_cells'


def choose(table, mid, cid, picker):
    """Run one candidate, let it ask, hand ``picker`` the offered options, then finish it with that answer.

    The table commits an action only once every prompt it raised is answered, so the answer is chosen from the options the
    table really offered rather than guessed up front.
    """
    result = act(table, mid, cid, [])
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reaction_source_id'] == picker['choice']
    options = [o['id'] for o in prompt['choice']['options']]
    answer = picker['pick'](options)
    result = act(table, mid, cid, [{**prompt['context'], 'selection': 'USE' if answer is not None else 'DECLINE',
                                    'option_ids': answer if isinstance(answer, list) else ([answer] if answer else [])}])
    assert result['status'] == 'COMMITTED', result
    return prompt, options


def test_hundred_mechanism_scripture_sets_the_spaces_the_owner_chose(tmp_path):
    """The owner picks which two extra spaces get a trap; each is a different legal space within reach."""
    combat, table, mid = fixture(tmp_path, [HUNDRED])
    cid = candidate(combat, mid, HUNDRED_ACTION, at=(4, 7)).candidate_id
    prompt, options = choose(table, mid, cid, {
        'choice': HUNDRED_CHOICE,
        'pick': lambda offered: [o for o in ('cell:2,5', 'cell:3,5') if o in offered],
    })
    assert prompt['context']['reactor_id'] == OWNER  # the trap's owner decides, not the table
    assert all(o in options for o in ('cell:2,5', 'cell:3,5'))
    assert 'cell:4,7' not in options  # the action already used this space; "different legal spaces"

    traps = placed.of(reload(tmp_path, mid), 'trap', owner_id=OWNER)
    assert sorted((z.center.x, z.center.y) for z in traps) == [(2, 5), (3, 5), (4, 7)]


def test_hundred_mechanism_scripture_can_set_fewer_than_three_traps(tmp_path):
    """"set up to three traps instead": taking no extra spaces leaves the single trap the owner aimed at."""
    combat, table, mid = fixture(tmp_path, [HUNDRED])
    cid = candidate(combat, mid, HUNDRED_ACTION, at=(4, 7)).candidate_id
    choose(table, mid, cid, {'choice': HUNDRED_CHOICE, 'pick': lambda offered: []})
    traps = placed.of(reload(tmp_path, mid), 'trap', owner_id=OWNER)
    assert [(z.center.x, z.center.y) for z in traps] == [(4, 7)]


@pytest.mark.parametrize('picked', ['cell:3,7', 'cell:5,8'])
def test_trap_within_the_trap_places_the_second_trap_where_the_owner_chose(tmp_path, picked):
    """False Trigger's warning is the moment the owner chooses the extra trap's space within 5 feet.

    The cells picked here are off the walking creature's own route. A cell still ahead of it in the same move is a
    separate finding (AUTO131 report): the move replays its whole path after the new trap exists, so a child placed on a
    square the creature has not left yet is sprung by that same creature. That is pre-existing behaviour, not part of
    choosing the space, and these cases keep the choice itself under test.
    """
    combat, table, mid = fixture(tmp_path, [FALSE, WITHIN])
    settle(table, mid, candidate(combat, mid, 'Trap trigger: False Trigger').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Set Trap', at=(4, 7)).candidate_id)

    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    move = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE' and c.destination
                and (c.destination.x, c.destination.y, c.destination.z) == (4, 7, 0))
    prompt, options = choose(table, mid, move.candidate_id, {'choice': WITHIN_CHOICE, 'pick': lambda offered: picked})
    assert prompt['context']['reactor_id'] == OWNER  # the trap's owner is asked, not the creature that walked in
    assert picked in options

    engine = reload(tmp_path, mid)
    traps = placed.of(engine, 'trap', owner_id=OWNER)
    assert sorted((z.center.x, z.center.y) for z in traps) == sorted([(4, 7), (int(picked[5]), int(picked[7]))])
    child = next(z for z in traps if placed.data(z).get('within_child'))
    assert placed.data(child)['within_child'] is True  # "cannot also use Trap Within the Trap"