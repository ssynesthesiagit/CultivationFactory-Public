"""Common pre-reaction forced displacement gate, used by pushes and chosen paths.

A caller supplies its resolving Context where available. Otherwise the original
native action supplies Source CL; an unknown source remains unknown. This query
never manufactures cultivation authority from an actor's name or damage type.
"""
from .ext import run_strict


def permitted(engine,subject,source_actor_id,source_definition_id,*,ctx=None):
    from .ext.source_eligibility import catalog_action
    source=engine.state.actors.get(source_actor_id)
    action=catalog_action(engine,source_definition_id)
    numbers=dict(ctx.numbers) if ctx is not None else dict(((action.parameters or {}).get('typed') or {}).get('numbers') or {}) if action is not None else {}
    replies=run_strict('forced_displacement_attempt',engine,subject,source,source_definition_id,numbers)
    if any(type(value) is not bool for value in replies):raise ValueError('forced_displacement_attempt requires bool or None')
    return False not in replies
