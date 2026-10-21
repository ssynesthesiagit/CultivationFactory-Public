"""Iron Interposition riders on the existing, paid Iron Oath Guard provider.

This does not infer protected duty, suppression, threats or technique scope.
Those upstream source facts remain unresolved; see the packet clause matrix.
"""
from . import hook
from . import foundation_combat as foundation
from .. import engine_seam as seam
from .needle import ask, checkpoint_id, CHOICE

INTERPOSITION = foundation.feature('oath', 'iron_interposition')


@hook('foundation_expression_options')
def expressions(info):
    return [INTERPOSITION] if INTERPOSITION in info['owned_ids'] else None


def eligible(engine, owner, target, group, leaf):
    """Only an owned, selected expression on an adjacent ally's actual Guard."""
    return (group == 'oath' and leaf == 'iron_oath_guard' and owner is not target
            and owner.team_id == target.team_id
            and engine._distance_actor_to_actor(owner, target) <= 5
            and foundation.row(engine, owner, 'oath', 'iron_interposition') is not None
            and foundation.selected(engine, owner, INTERPOSITION))


@hook('foundation_guard_bonus')
def bonus(engine, owner, target, group, leaf):
    if eligible(engine, owner, target, group, leaf):
        return foundation.values(engine, owner)[0]
    return None


@hook('foundation_guard_spent')
def step(engine, owner, target, group, leaf):
    if not eligible(engine, owner, target, group, leaf):
        return
    declaration = foundation.held(owner, 'protected_subject')
    if declaration is None or declaration.data.get('subject') != target.entity_id:
        return
    intent = seam.active_intent(engine)
    if intent is None:
        return
    from .granted_movement import choices, move
    from ..senses import perceives_cell
    from ..stealth import sees

    def distance_squared(position):
        return sum((getattr(position, axis, 0) - getattr(target.position, axis, 0)) ** 2
                   for axis in ('x', 'y', 'z'))

    distance = distance_squared(owner.position)
    options = [candidate for candidate in choices(engine, owner, 5)
               if candidate.destination is not None
               and distance_squared(candidate.destination) < distance]
    if not options:
        return
    by_id = {candidate.candidate_id: candidate for candidate in options}
    candidate = seam.active_candidate(engine)
    action = engine.action_catalog.get(getattr(intent, 'source_definition_id', '') or
                                      getattr(candidate, 'source_definition_id', ''))
    action_name = action.display_name if action is not None else 'the triggering damage'
    selected = ask(engine, intent, checkpoint_id(engine, 'IRON_INTERPOSITION', owner.entity_id, target.entity_id),
                   owner, CHOICE + 'iron_interposition', list(by_id), allow_decline=True,
                   name='Iron Interposition', feature_id=INTERPOSITION, target_id=target.entity_id,
                   labels={key: f'Move 5 feet toward {target.display_name} to ({candidate.destination.x}, {candidate.destination.y})'
                           for key, candidate in by_id.items()},
                   automatic_options=[key for key, candidate in by_id.items()
                                      if sees(engine, owner, target)
                                      and perceives_cell(engine, owner, candidate.destination)],
                   preferred=list(by_id),
                   prompt=f'Iron Interposition: after paying for Iron Oath Guard against {action_name} affecting {target.display_name}, '
                          'you may move 5 feet toward your declared ally before reducing the damage. '
                          'This costs no additional resource or Reaction; ordinary movement hazards and opportunity attacks apply.')
    if selected:
        move(engine, owner, by_id[selected[0]], intent, 5, [], name='Iron Interposition')
