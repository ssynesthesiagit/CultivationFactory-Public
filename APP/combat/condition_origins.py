"""Pure condition-origin projection shared by fear movement and roll visibility.

An origin can be a source-controlled projected point rather than its creature.
Providers return only a Position; the original creature identity, ownership and
rules remain intact. No provider retains the ordinary source actor verbatim.
"""
def source_actor(engine, holder, condition):
    from .voluntary_movement import approach_source_id
    from .gate2_runtime_models import Position
    from . import ext
    source = engine.state.actors.get(approach_source_id(condition))
    if source is None:
        return None
    replies = ext.run_strict('condition_origin', engine, holder, condition, source)
    if len(replies) > 1 or any(not isinstance(p, Position) for p in replies):
        raise ValueError('One condition-origin provider may supply a native Position.')
    return source.model_copy(update={'position': replies[0]}) if replies else source
