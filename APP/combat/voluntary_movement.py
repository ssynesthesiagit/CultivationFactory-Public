"""Pure physical-path restrictions shared by native and granted movement.

Any condition whose own rule carries ``no_approach`` (combat/rules/typed_conditions.json) keeps a
creature from taking a willing step closer to the creature that applied it: Frightened ("It can't
willingly take a step closer while that source is visible", whose rule also carries
``no_approach_requires_source_visible``) and a printed "cannot willingly move closer to you"
(Name-Striking Tone's Kept at Distance, World-Transfixing Point, Sever the Battle Line, Consume
Fear), which has no such sight exception. The set and the exception are read from the shared rules
table, so a new ability needs no code here. Projected viewers are copies, never substitutions in
state. Forced displacement never uses this query, and neither does a teleport -- see
``approach_restriction`` in combat/ext/, which gates a voluntary teleport on the rules that do not
require sight.
"""


def _blocking_conditions():
    """Condition name -> whether its rule also needs that source in sight."""
    from .typed_executor import rules

    return {name: bool(rule.get("no_approach_requires_source_visible"))
            for name, rule in (rules()["conditions"] or {}).items()
            if isinstance(rule, dict) and rule.get("no_approach")}


def fear_sources(engine, actor):
    """Resolve owned conditions, without treating remembered positions as sight."""
    blocking = _blocking_conditions()
    return tuple(engine.state.actors[aid] for aid in sorted({
        approach_source_id(c) for c in actor.conditions.values()
        if c.condition_id[len('condition:typed.'):] in blocking and approach_source_id(c) in engine.state.actors}))


def approach_source_id(condition):
    """The creature an approach bar protects; defaults to the condition's user.

    General movement_bar rows store a chosen creature in data['avoid']. Shared
    path and teleport queries must use that same identity, rather than imposing
    an additional bar around the caster. Ordinary fear has no override.
    """
    return (condition.data or {}).get('avoid') or condition.source_actor_id


def unconditional_sources(engine, actor):
    """The subset of :func:`fear_sources` whose rule forbids the step with or without sight."""
    blocking = _blocking_conditions()
    return tuple(engine.state.actors[aid] for aid in sorted({
        approach_source_id(c) for c in actor.conditions.values()
        if blocking.get(c.condition_id[len('condition:typed.'):]) is False and approach_source_id(c) in engine.state.actors}))


def blocking_source(engine, actor, previous, destination, *, sources=None):
    """Return the source forbidding this step, or None; no mutation.

    A source that carries at least one rule which needs no sight forbids the step wherever the
    step starts; a source whose only rules require sight (Frightened) forbids it only while it is
    visible from the step's starting space.
    """
    blocking = _blocking_conditions()
    sources = fear_sources(engine, actor) if sources is None else sources
    if not sources:
        return None
    from .target_knowledge import can_see
    viewer = actor if actor.position == previous else actor.model_copy(update={'position': previous})
    for source in sources:
        flags = [blocking.get(c.condition_id[len('condition:typed.'):])
                 for c in actor.conditions.values() if approach_source_id(c) == source.entity_id]
        rules = [flag for flag in flags if flag is not None]
        if not rules or (all(rules) and not can_see(engine, viewer, source)):
            continue
        if (engine._distance_actor_to_actor(viewer, source, actor_position=destination)
                < engine._distance_actor_to_actor(viewer, source)):
            return source
    return None


def path_allowed(engine, actor, path, *, sources=None):
    """Check every canonical step, including a retreat followed by approach."""
    sources = fear_sources(engine, actor) if sources is None else sources
    return not sources or all(blocking_source(engine, actor, a, b, sources=sources) is None
                              for a, b in zip(path, path[1:]))


def edge_predicate(engine, actor):
    """Pure query-scoped restriction for native/granted route search, or None.

    Capture source identities once per query. The grid invokes this only for
    geometrically legal edges; commit still rechecks current fear and sight.
    """
    sources = fear_sources(engine, actor)
    from . import ext
    if not sources and not ext.has('movement_edge_allowed'):
        return None
    return lambda previous, destination: (blocking_source(engine, actor, previous, destination, sources=sources) is None
        and edge_allowed(engine, actor, previous, destination))


def edge_allowed(engine, actor, previous, destination):
    """Pure source-owned physical boundaries; false vetoes, absence is inert."""
    from . import ext
    replies=ext.run_strict('movement_edge_allowed',engine,actor,previous,destination)
    if any(type(value) is not bool for value in replies):
        raise ValueError('movement_edge_allowed must return bool or None')
    return False not in replies


def destination_allowed(engine, actor, destination, *, observed=None):
    """Compatibility query for old grant callers; full paths use path_allowed."""
    return blocking_source(engine, actor, actor.position, destination) is None
