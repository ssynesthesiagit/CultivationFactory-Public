"""Human menu discovery, shared by the engines and tabletop projection.

Headers are offers to inspect an action, never legal execution candidates.
Geometry quotes defer candidate vetoes until the destination is opened. Native
enumeration, AI, pending choices and commit/replay never enter this scope.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_ACTIVE = ContextVar('human_lazy_menu', default=False)


@contextmanager
def query(enabled=True):
    token = _ACTIVE.set(enabled)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def active(engine):
    state = engine.state
    return (_ACTIVE.get() and state.pending_resolution is None
            and not state.setup_tasks and not state.terminal_result
            and getattr(engine, 'typed_control_modes', {}).get(state.current_actor_id, 'MANUAL')
            in {'MANUAL', 'SUGGESTED'})


def header(engine, actor, action, kind):
    """Non-issued identity for a group; native preconditions ran before this."""
    from .gate2_runtime_models import LegalCandidate
    from .canonical import canonical_sha256
    identity = engine._candidate_identity(kind, actor, action.source_definition_id, (), None)
    return LegalCandidate(candidate_id='menu:' + canonical_sha256(identity)[:24],
        decision_id=identity['decision_id'], state_version=engine.state.state_version,
        kind=kind, actor_id=actor.entity_id, source_definition_id=action.source_definition_id,
        display_name=action.display_name, metadata={'lazy_action': True})


def defer(action):
    """Small standing-setting controls retain their existing composition IDs."""
    p = action.parameters or {}
    return not (p.get('zone_shape') or p.get('augment_toggle') or p.get('menu_parent')
                or p.get('setting_only') or p.get('attack_modifier_setting')
                or p.get('item_action') or p.get('requires_disabled_action') or p.get('requires_dropped_nearby'))
