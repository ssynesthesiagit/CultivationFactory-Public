"""No-Purchase Body's standing and confirmed-hit clauses through the table.

A2VOID removes the old damage-event reminder. This suite retains the native
Opportunity Attack Disadvantage and forced-movement controls; the new optional
Pressure, confirmed-hit and saved-packet controls are in test_a2_void.py.
"""
import json

from tests.auto_worker1_support import LEFT, RIGHT, fight, reload
from tests.h1_support import ROOT
from tests.void_support import settle, turn
from tests.hunt12_support import send
from tests.auto_worker1_support import action_sender

SHELL = 'TAL_VOID_VOID_SHELL'
NO_PURCHASE = 'TAL_VOID_NO_PURCHASE_BODY'
PUSH = 20
FAR = (1, 1)


def _engine(combat, mid):
    return combat._load_session(mid).engine


def _square(candidate):
    x, y = candidate.display_name.rsplit(' ', 1)[-1].split(',')
    return int(x), int(y)


def _void_fight(tmp_path, talents, *, cause=None, right_score=1):
    return fight(tmp_path, talents, cl=15,
                 positions={LEFT: {'x': 6, 'y': 6}, RIGHT: {'x': 7, 'y': 6}},
                 right_score=right_score, cause=cause if cause is not None else [])


def _push_left(feet):
    """A hostile action that shoves LEFT away: forced movement, never voluntary passage."""
    return [{'type': 'forced_movement', 'applies_to': 'target', 'distance_ft': feet,
             'evidence': f'test: shove LEFT {feet} feet'}]


def _commit_step(combat, table, mid, chosen):
    """Commit one step, taking any Reaction raised on the way so a real Opportunity Attack resolves."""
    result = send(combat, table, mid, chosen)
    for _ in range(4):
        if result['status'] != 'REACTION_REQUIRED':
            return result['status']
        prompt = result['reaction']
        if prompt.get('choice'):
            return result['status']
        result = send(combat, table, mid, chosen, [{**prompt['context'], 'selection': 'USE'}])
    return result['status']


def _walk(combat, table, mid, x, y, *, limit=8):
    """Walk whoever's turn it is to that square, one real 5-foot step at a time."""
    for _ in range(limit):
        engine = _engine(combat, mid)
        actor = engine.state.actors[engine.state.current_actor_id]
        here = (actor.position.x, actor.position.y)
        if here == (x, y):
            return True
        gap = lambda c: max(abs(a - b) for a, b in zip(_square(c), (x, y)))  # noqa: E731
        options = sorted((c for c in engine.legal_candidates()
                          if c.display_name.startswith('Move to ')
                          and max(abs(a - b) for a, b in zip(_square(c), here)) == 1), key=gap)
        if not options or gap(options[0]) >= max(abs(a - b) for a, b in zip(here, (x, y))):
            return False
        assert _commit_step(combat, table, mid, options[0]) == 'COMMITTED', options[0].display_name
    return False


def _walked(event):
    """Forced movement distance actually committed: 5 feet per path step."""
    return (len(event.payload.get('path') or []) - 1) * 5


def _oa_rolls(engine):
    return [e.payload for e in engine.events if e.event_type == 'ATTACK_ROLLED']


# ----------------------------------------------------------------------------------------- forced movement
def test_forced_movement_against_a_shell_is_reduced_by_ten(tmp_path):
    """printed: "forced movement against you is reduced by 10 feet" while Void Shell is active."""
    c, t, m = _void_fight(tmp_path, [SHELL, NO_PURCHASE], cause=_push_left(PUSH))
    settle(action_sender(c, t, m, 'Void Shell', target_id=LEFT))
    e = reload(c, m)
    assert any(str(v.condition_id).endswith('void_shell') for v in e.state.actors[LEFT].conditions.values()), \
        'the Shell must be live before it protects the owner'

    turn(t, m, RIGHT)
    settle(action_sender(c, t, m, 'Cause', target_id=LEFT))
    e = reload(c, m)
    moves = [v for v in e.events if v.event_type == 'MOVEMENT_COMMITTED' and v.actor_id == LEFT]
    assert moves, 'the printed shove must actually move LEFT'
    assert _walked(moves[-1]) == PUSH - 10, \
        f'forced movement must land 10 feet short, got {_walked(moves[-1])}'


def test_forced_movement_is_untouched_without_the_shell(tmp_path):
    """The control: the same printed shove moves the full 20 feet when Void Shell is not active."""
    c, t, m = _void_fight(tmp_path, [NO_PURCHASE], cause=_push_left(PUSH))
    turn(t, m, RIGHT)
    settle(action_sender(c, t, m, 'Cause', target_id=LEFT))
    e = reload(c, m)
    moves = [v for v in e.events if v.event_type == 'MOVEMENT_COMMITTED' and v.actor_id == LEFT]
    assert moves and _walked(moves[-1]) == PUSH, \
        f'no Shell, no reduction: got {_walked(moves[-1])}'


# ----------------------------------------------------------------------------------------- opportunity attacks
def _hand_turn_back(c, t, m):
    """End the owner's turn and come back around to it, with the foe holding a dagger."""
    turn(t, m, RIGHT)
    turn(t, m, LEFT)


def test_an_opportunity_attack_against_a_shell_wearer_is_disadvantage(tmp_path):
    """printed: "Opportunity Attacks against you have Disadvantage" while Void Shell is active.

    A real Opportunity Attack, made by the other fighter as this one walks out of reach, rolls its
    d20 with Disadvantage (one die dropped).
    """
    c, t, m = _void_fight(tmp_path, [SHELL, NO_PURCHASE], right_score=18)
    settle(action_sender(c, t, m, 'Void Shell', target_id=LEFT))
    _hand_turn_back(c, t, m)
    assert _walk(c, t, m, *FAR), "the owner must actually leave the attacker's reach"
    e = reload(c, m)
    rolls = _oa_rolls(e)
    assert rolls, 'walking out of reach must provoke a real Opportunity Attack'
    assert [row.get('mode') for row in rolls] == ['DISADVANTAGE'], rolls
    assert len(rolls[0].get('discarded') or []) == 1, rolls[0]  # the dropped die is what Disadvantage is
    assert any(v.event_type == 'REACTION_RESOLVED'
               and v.source_definition_id == 'system:combat.opportunity_attack' for v in e.events)


def test_an_opportunity_attack_without_the_shell_is_a_normal_roll(tmp_path):
    """The control: the same printed walk rolls normally for a fighter who wears no Void Shell."""
    c, t, m = _void_fight(tmp_path, [NO_PURCHASE], right_score=18)
    _hand_turn_back(c, t, m)
    assert _walk(c, t, m, *FAR)
    e = reload(c, m)
    rolls = _oa_rolls(e)
    assert rolls, 'walking out of reach must provoke a real Opportunity Attack'
    assert [row.get('mode') for row in rolls] == ['NORMAL'], rolls


# ----------------------------------------------------------------------------------------- the printed reminder
def _no_purchase_record():
    """The record the fight engine compiles from: the built authority, not the reviewed source."""
    authority = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text(encoding='utf-8'))
    return authority['mechanics'][NO_PURCHASE]


AUTOMATIC = ('While Void Shell is active the game applies Opportunity Attack Disadvantage and '
             'reduces forced movement against you by 10 feet automatically')


def test_no_purchase_retains_only_the_unresolved_invisibility_scope():
    record = _no_purchase_record()
    assert record['coverage'] == 'CORE_WITH_RIDERS'
    assert len(record['riders']) == 1
    assert 'permanent or protected sources' in record['riders'][0]
    assert 'confirmed melee' in ' '.join(record['notes'])


def test_a_compiled_gm_line_does_not_repeat_no_purchase_effects():
    from combat.factory_compiler import _gm_lines
    record = _no_purchase_record()
    lines = _gm_lines(record['riders'], record, record['effects'])
    assert len(lines) == 1 and 'ordinary temporary supernatural' in lines[0]
    assert 'Opportunity Attack' not in lines[0] and 'forced movement' not in lines[0]
