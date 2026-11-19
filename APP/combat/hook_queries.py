"""Pure hook query keys shared by equipment, speech and ability admission.

These are opt-in declarations, never inferred from function bytecode. A provider
using actor_action promises it does not read the candidate or mutate inputs. The
normal body still decides ownership, conditions and costs. Position/origin keys
keep temporary targeting projections apart; revision and engine identity are
supplied by read_queries. Non-enumeration calls always execute the provider.
"""
from .read_queries import enumeration_cache


def actor_action(engine, actor, candidate, action):
    position = actor.position
    shot = getattr(engine, '_shot_geometry', None)
    cache = enumeration_cache(engine)
    if cache is not None:
        # Projected inputs may be temporary copies outside the live catalog.
        # Keep them alive for exactly this pass, so identity keys cannot alias.
        cache.setdefault(('hook_actor', id(actor)), actor)
        cache.setdefault(('hook_action', id(action)), action)
        if shot is not None:
            cache.setdefault(('hook_shot', id(shot)), shot)
    return (id(actor), id(action), position.x, position.y, position.z, id(shot))
