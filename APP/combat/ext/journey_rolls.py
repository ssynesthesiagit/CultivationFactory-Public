"""Shared deterministic journey dice used by institution, check, and rest providers.

Keep roll creation outside individual providers so they can share one persisted
counter and event contract without reaching into each other's implementation.
"""

from ..gate2_rolls import DeterministicRollAuthority
from ..gate2_runtime_models import DiceSpec


def roll(session, aid, sides, source):
    roller = DeterministicRollAuthority(session.state['journey_id'], session.state.get('roll_counter', 0))
    result = roller.roll(DiceSpec(count=1, sides=sides, modifier=0), actor_id=aid, reason=source)
    session.state['roll_counter'] = roller.counter
    session.emit('JOURNEY_ROLL', aid, roll=result.model_dump(mode='json'))
    return result.total
