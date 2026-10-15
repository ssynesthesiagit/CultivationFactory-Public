"""Deterministic elapsed-scene checks without inventing a combat encounter.

Used by Saber Wound Medicine; construction/repair and other native procedures
can use the same seeded counter, source scope and replayable integer/string
record. Callers supply actual sheet/condition numbers and own time/outcomes.
"""
import json
from .ext import run_strict
from .gate2_rolls import DeterministicRollAuthority
from .journey import require


def resolve(session, actor_id, *, source, ability, skill, modifier, dc, source_actor_id=''):
    """Resolve one ordinary d20 check; no natural-20 automatic success.

    journey_check_bonus(session,request) -> int | None and
    journey_check_mode(session,request) -> ADVANTAGE/DISADVANTAGE | None are
    strict source-owned pre-draw contributions. No provider is default-inert.
    The request is a fresh read-only description, never player-supplied rolls.
    """
    require(actor_id in session.state['actors'] and session.state['phase'] == 'travel',
        'Choose an actual travelling creature for this check.')
    require(type(modifier) is int and type(dc) is int and all(type(value) is str and value
        for value in (source, ability, skill)), 'A scene check needs actual integer statistics and named scope.')
    request = {'actor_id': actor_id, 'source': source, 'source_actor_id': source_actor_id,
        'ability': ability, 'skill': skill, 'modifier': modifier, 'dc': dc}
    bonuses = run_strict('journey_check_bonus', session, dict(request))
    modes = run_strict('journey_check_mode', session, dict(request))
    require(all(type(value) is int for value in bonuses), 'Scene check bonuses must be integers.')
    require(all(value in ('ADVANTAGE', 'DISADVANTAGE') for value in modes), 'Use a known scene check mode.')
    modifier += sum(bonuses)
    modes = set(modes)
    mode = next(iter(modes)) if len(modes) == 1 else 'NORMAL'
    counter = session.state.get('roll_counter', 0)
    require(type(counter) is int and counter >= 0, 'The scene roll counter is invalid.')
    seed = session.state['journey_id']
    roller = DeterministicRollAuthority(seed, counter)
    reason = f'CHECK:{source}:{skill}'
    roll = roller.d20(modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
    record = {**request, 'modifier': modifier, 'mode': mode, 'seed': seed,
        'counter_start': counter, 'counter_end': roller.counter,
        'roll': roll.model_dump_json(), 'success': int(roll.total >= dc)}
    session.state['roll_counter'] = roller.counter
    session.emit('JOURNEY_CHECK_RESOLVED', actor_id, **{k: v for k, v in record.items() if k != 'actor_id'})
    return record


def replay(state):
    """Verify each recorded native draw/outcome and the persisted global counter."""
    counter = 0
    count = 0
    try:
        for record in state['events']:
            if record['kind'] != 'JOURNEY_CHECK_RESOLVED':
                continue
            if record['seed'] != state['journey_id'] or record['counter_start'] != counter:
                return {'status': 'FAIL', 'reason': 'Scene check seed/counter mismatch.'}
            roller = DeterministicRollAuthority(record['seed'], counter)
            roll = roller.d20(modifier=record['modifier'], actor_id=record['actor_id'],
                reason=f'CHECK:{record["source"]}:{record["skill"]}', mode=record['mode'])
            if (json.loads(roll.model_dump_json()) != json.loads(record['roll'])
                    or roller.counter != record['counter_end'] or record['success'] != int(roll.total >= record['dc'])):
                return {'status': 'FAIL', 'reason': 'Scene check draw/outcome mismatch.'}
            counter = roller.counter
            count += 1
        if state.get('roll_counter', 0) != counter:
            return {'status': 'FAIL', 'reason': 'Scene roll counter differs from its records.'}
    except (KeyError, TypeError, ValueError):
        return {'status': 'FAIL', 'reason': 'Invalid scene check record.'}
    return {'status': 'PASS', 'checks': count, 'counter': counter}
