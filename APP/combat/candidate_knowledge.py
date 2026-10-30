"""Pure AI placement view shared by Gate 2 generation and Gate 4 context.

The scope contains observed actors, never replaces engine.state or execution
recipients, and ends before an intent is executed. Outside it, historical and
player candidate generation is unchanged. Context-local storage isolates nested
queries on different engines and restores the previous view on exceptions.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_VIEW = ContextVar('combat_candidate_knowledge', default=None)
_BINDING = ContextVar('combat_candidate_binding', default=None)


@contextmanager
def prepared_binding(engine, candidates):
    """Reuse one internally validated menu for unchanged-state acceptance only.

    Callers supply generated candidates, never external payloads. This does not
    scope execution geometry or replace an engine function. Any state change,
    including an unversioned in-transaction change, invalidates the menu.
    """
    from .canonical import canonical_sha256
    digest = canonical_sha256(engine.state.model_dump(mode='json'))
    token = _BINDING.set((engine, digest, tuple(candidates)))
    try:
        yield
    finally:
        _BINDING.reset(token)


def binding_candidates(engine):
    """Return the unchanged engine's prepared menu, otherwise regenerate."""
    from .canonical import canonical_sha256
    value = _BINDING.get()
    if (value is not None and value[0] is engine
            and value[1] == canonical_sha256(engine.state.model_dump(mode='json'))):
        return value[2]
    return None


@contextmanager
def query(engine, *, perceived_actor_ids=None):
    """Scope observed estimates, optionally freezing a prospective target set.

    A detached future-position query may retain all effect-owner records while
    limiting creature targets to those perceived before moving. Native sight,
    senses and occupancy still re-evaluate those targets at the new position.
    The cap applies to targets, not viewers, so an unseen effect source can
    still ask whether it sees a known recipient. It never scopes execution.
    Nested queries on this engine retain any outer cap; they cannot widen it.
    """
    actor_id = (engine.state.pending_resolution.actor_id if engine.state.pending_resolution
                else engine.state.current_actor_id)
    actor = engine.state.actors[actor_id]
    inherited = perceived_ids(engine)
    permitted = inherited if perceived_actor_ids is None else frozenset(perceived_actor_ids)
    if inherited is not None and permitted is not None:
        permitted = inherited & permitted
    # A service may supply an already-prepared knowledge menu. Delay roster
    # projection until geometry needs it, so that cache reuse remains cheap.
    token = _VIEW.set((engine, actor, {'actors': None, 'squares': None, 'aims': {},
                                     'perceived_actor_ids': permitted}))
    try:
        yield
    finally:
        _VIEW.reset(token)


def active(engine):
    view = _VIEW.get()
    return view is not None and view[0] is engine


def perceived_ids(engine):
    """Optional prospective target cap; None leaves ordinary queries unchanged."""
    view = _VIEW.get()
    return view[2]['perceived_actor_ids'] if view is not None and view[0] is engine else None


def target_allowed(engine, target):
    permitted = perceived_ids(engine)
    return permitted is None or target.entity_id in permitted


def roster(engine):
    """Explicit projected roster for estimates; None keeps the real roster."""
    if not active(engine):
        return None
    _, actor, data = _VIEW.get()
    if data['actors'] is None:
        from .target_knowledge import actors_for
        data['actors'] = tuple(actors_for(engine, actor))
        data['squares'] = {(a.position.x, a.position.y, a.position.z) for a in data['actors']}
    return data['actors']


def aim_allowed(engine, actor, cell, action=None):
    """AI areas aim at perceived cells or a recorded creature's last location.

    A self-originating line/cone's aim is only a direction; it does not need a
    perceived destination cell. Placed areas and other actions retain this gate.
    """
    if action is not None:
        from .targeting import directional_area_aim
        if directional_area_aim(action):
            return True
    if not active(engine):
        return True
    roster(engine)
    data = _VIEW.get()[2]
    square = (cell.x, cell.y, cell.z)
    if square in data['squares']:
        return True
    from .senses import perceives_cell
    key = (actor.entity_id, square)
    if key not in data['aims']:
        data['aims'][key] = perceives_cell(engine, actor, cell)
    return data['aims'][key]
