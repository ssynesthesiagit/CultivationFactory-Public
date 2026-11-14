"""Shared opposed Cultivation Checks for bodily anchoring.

Both rolls use the engine's ordinary check modifiers, modes, floors, d20
rewrites, reaction checkpoints, and history schema. The defender holds on ties.
"""
from .ability_source import numbers_of


def holds_position(engine, defender, source, feature, *, source_numbers=None):
    """True when a normal opposed Cultivation Check leaves the defender in place.

    ``feature`` is the stable source for this check, so scoped check rules and
    history name the anchoring feature consistently across callers.
    """
    from ..typed_executor import Context, resolve_opposed_check

    numbers = source_numbers if source_numbers is not None else numbers_of(engine, source)
    action = engine.action_catalog.get(feature) or next(iter(engine.action_catalog.values()))
    ctx = Context(engine, source, action, None, {"numbers": dict(numbers)},
                  [defender], defender, {}).with_source(feature)
    result = resolve_opposed_check(
        ctx, defender, {"kind": "cultivation", "label": "Cultivation Check"},
        {"kind": "cultivation", "label": "Cultivation Check"})
    # The effect is stopped when the defender wins or ties; actor success is
    # the source's win and therefore means displacement is allowed.
    return not bool(result.success)
