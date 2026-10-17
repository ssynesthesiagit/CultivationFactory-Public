"""Area policy shared by candidate origins, collateral labels and risk previews.

Execution uses the real engine. Preview callers get a separate, read-only
engine/state projection built from target_knowledge's public actor view, so
remembered footprints never follow live hidden movement. No methods are patched.
"""
from copy import copy
import json
from pathlib import Path
import re

STAMP = 'area_knowledge_policy'
ORIGIN_AUTHORITY = 'area_origin_permissions'


def saved_policy(events):
    """Absent stamps mean predecessor rules; continuations inherit explicitly."""
    for event in reversed(events):
        kind = event.event_type if hasattr(event, 'event_type') else event['event_type']
        if kind in {'MATCH_CREATED', 'SAVED_FIGHT_CONTINUED'}:
            payload = event.payload if hasattr(event, 'payload') else event.get('payload', {})
            value = payload.get(STAMP)
            if value is not None:
                if type(value) is not int or value not in (0, 1):
                    raise ValueError('The saved area targeting rules are invalid.')
                return value
    return 0


def enabled(engine):
    return saved_policy(engine.events) == 1


def printed_rules(source_root):
    """Read prose only while binding a new fight, never during targeting."""
    return json.loads((Path(source_root) /
                       'authority/typed_mechanics/rules_text.json').read_text())


def bind_origin_permissions(source_root):
    """Sparse source permission map: absent sources require sight by default.

    Values are saved integers; typed action overrides remain in saved bundles.
    Store only printed exceptions so new actions still use the owner's default.
    """
    permissions = {}
    for source, prose in printed_rules(source_root).items():
        text = ' '.join(prose.lower().split())
        seen = re.search(r'(?:point|square|space|location)[^.\n]{0,80}\byou can see\b', text)
        unseen = re.search(r'\b(?:anywhere within range|unseen (?:point|square|space)|'
                           r'(?:point|square|space)[^.]{0,60}whether or not you can see)\b', text)
        if unseen and not seen:
            permissions[source] = 0
    return permissions


def saved_origin_permissions(events):
    """Latest binding is authoritative; never infer from current prose on load."""
    for event in reversed(events):
        kind = event.event_type if hasattr(event, 'event_type') else event['event_type']
        if kind in {'MATCH_CREATED', 'SAVED_FIGHT_CONTINUED'}:
            payload = event.payload if hasattr(event, 'payload') else event.get('payload', {})
            if ORIGIN_AUTHORITY in payload:
                permissions = payload[ORIGIN_AUTHORITY]
                if not isinstance(permissions, dict) or any(
                        not isinstance(key, str) or type(value) is not int or value != 0
                        for key, value in permissions.items()):
                    raise ValueError('The saved area origin permissions are invalid.')
                return dict(permissions)
    raise ValueError('This fight has no saved area origin permissions; its original authority must be restored.')


def requires_seen_origin(engine, action):
    """Owner LoS default, with typed/printed permission for an unseen origin.

    Explicit typed requires_seen_origin is authoritative. Text that allows a
    center anywhere within range (e.g. Darkness) keeps that permission. The
    general owner LoS ruling covers point areas whose text is silent about sight.
    """
    typed = action.parameters.get('typed') or {}
    if 'requires_seen_origin' in typed:
        return bool(typed['requires_seen_origin'])
    if typed.get('requires_seen_target') or action.parameters.get('requires_seen_target'):
        return True
    return bool(saved_origin_permissions(engine.events).get(typed.get('source'), 1))


def origin_allowed(engine, actor, action, destination):
    """Square sight only; callers also enforce range and line of effect."""
    from .senses import perceives_cell
    return (not enabled(engine) or not requires_seen_origin(engine, action) or
            perceives_cell(engine, actor, destination))


def preview_engine(engine, actor):
    """Pure knowledge projection; never pass this engine to execution."""
    if not enabled(engine):
        return engine
    from .target_knowledge import actors_for
    view = copy(engine)
    view.state = engine.state.model_copy(update={
        'actors': {other.entity_id: other for other in actors_for(engine, actor)}})
    return view
