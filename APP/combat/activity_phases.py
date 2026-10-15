"""Native activity beginnings observed by persisted preparations.

No observer means no additional event or change to historical fights. Producers
call at their real declaration boundary, before their ordinary continuation.
Reactions may prevent continuation; they never replace the original resolver.
"""


class ActivityPrevented(BaseException):
    """Unwind the interrupted resolver while retaining the real reaction.

    Caught only at the native action-resolution boundary, inside its existing
    transaction. Observational plug-in exception guards must not swallow this
    control signal and allow the prevented activity to continue.
    """


def can_continue(engine, actor):
    from .typed_executor import condition_rules
    return (actor.active and actor.life_state in (None, 'CONSCIOUS')
            and engine.state.terminal_result is None
            and not any(row.get('no_actions') for row in condition_rules(actor)))


def begin(engine, actor, event_type, source, *, targets=(), payload=None):
    from .prepared_actions import observes
    if not observes(engine, event_type):
        return True
    engine._append_event(event_type, source, actor_id=actor.entity_id,
                         target_ids=targets, payload=payload or {})
    return can_continue(engine, actor)


def contest(engine, actor, target, source):
    if not begin(engine, actor, 'CONTEST_DECLARED', source,
                 targets=(target.entity_id,), payload={'kind': 'contested_check'}):
        raise ActivityPrevented()


def sphere_talent(action):
    """Classify the actual bound canonical talent; no name/cost inference."""
    if action is None:
        return False
    source = (action.parameters.get('typed') or {}).get('source')
    return _sphere_talent(source) if isinstance(source, str) else False


from functools import lru_cache


@lru_cache(maxsize=4096)
def _sphere_talent(source):
    from pathlib import Path
    from canonical_catalog.service import CanonicalCatalogAuthorityService
    from app.core import FoundryError
    authority = CanonicalCatalogAuthorityService(Path(__file__).resolve().parents[1])
    try:
        row = authority.get_talent(source)
    except FoundryError:
        return False
    return bool(row.get('owning_canonical_sphere_id'))
