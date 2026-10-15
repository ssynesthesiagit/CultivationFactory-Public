"""Share Vessel's once-per-round conversion benefit with native save rescues.

Guard (foundation_combat) and Strike (foundation_resources) already use the
persisted foundation_round_vessel flag. Rejection's compiled bonus includes PB
for Vessel; query-time adjustment removes only that evolution once consumed.
The original rescue provider retains eligibility, consent, payment and timing.
No resource is generated here and no sibling conversion is implemented here.
"""
from . import hook
from .passive_rows import row_of

PREFIX = 'foundation.heavenly_body_v0_2F.'
REJECTION = PREFIX + 'integrity_rejection'
FLAG = 'foundation_round_vessel'


def vessel(engine, actor):
    return row_of(engine, actor.entity_id, 'foundation_spend', 'heaven_recognized_vessel')


@hook('save_rescue_bonus')
def remaining_bonus(engine, actor, row, ability, dc, roll, source_id):
    if row.get('feature_id') != REJECTION:
        return None
    owned = vessel(engine, actor)
    if owned is not None and actor.turn_flags.get(FLAG) == engine.state.round_number:
        return -int(owned['pb'])
    return None


@hook('event', nested=True)
def claim_bonus(engine, event_type, kw):
    if event_type != 'REACTION_RESOLVED' or kw.get('source_definition_id') != REJECTION:
        return
    actor = engine.state.actors.get(kw.get('actor_id'))
    if actor is None:
        return
    owned = vessel(engine, actor)
    if (owned is not None and int((kw.get('payload') or {}).get('bonus') or 0) > int(owned['pb'])):
        actor.turn_flags[FLAG] = engine.state.round_number
