"""Forbidden Silence Field: continuous membership, sound paths and caster admission.

Native zone inside grants own Deafened and Thunder resistance. Pure queries
below are inert without a live field. Delivery exceptions must be declared as
``sound_delivery`` (silent_vibration/contact_resonance/soul_sound) or a boolean
``pierces_silence`` in typed action/effect metadata; ordinary Sound is not an
exception. The printed Soul-Sound header is also an explicit delivery qualifier.
These are source capabilities, never guessed from a creature's instrument/name.
"""
from typing import Any
from functools import lru_cache
from pathlib import Path
import json

from . import hook

FIELD = 'TAL_SOUND_FORBIDDEN_SILENCE_FIELD'
SOUND = 'tianxia.sphere.sound'
DELIVERIES = {'silent_vibration', 'contact_resonance', 'soul_sound'}


def fields(engine: Any):
    """Active native zones belonging to this exact ability."""
    result = []
    for zone in engine.state.zones.values():
        action = engine.action_catalog.get(zone.source_definition_id)
        typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
        if zone.active and typed.get('source') == FIELD:
            result.append(zone)
    return result


@lru_cache(maxsize=1)
def printed_headers():
    """Immutable checkout's printed delivery tags, shared by path/admission."""
    text = json.loads((Path(__file__).resolve().parents[2] /
                       'authority/typed_mechanics/rules_text.json').read_text())
    return {key: value.split('\n', 1)[0] for key, value in text.items()}


def silent_source(engine: Any, source: str, action: Any = None) -> bool:
    """An explicit source capability; no inferred ordinary audible exception."""
    if action is None:
        action = engine.action_catalog.get(source)
    typed = ((getattr(action, 'parameters', None) or {}).get('typed') or {})
    if typed.get('sound_delivery') in DELIVERIES or typed.get('pierces_silence') is True:
        return True
    record = str(typed.get('option_of') or typed.get('source') or source)
    # Header tags are authoritative and avoid treating a mention in a negated
    # exclusion or a prerequisite as a delivery grant.
    return 'Soul-Sound' in printed_headers().get(record, '')


@hook('sound_path_allowed')
def sound_path(engine: Any, speaker: Any, listener: Any, source: str):
    from ..space import ray
    from ..typed_executor import in_area
    from ..gate2_runtime_models import Position
    live = fields(engine)
    if not live or silent_source(engine, source):
        return None
    for zone in live:
        if any(in_area(engine, zone.center, zone.center, Position(x=x, y=y, z=z),
                       {'shape': 'sphere', 'size_ft': 20})
               for x, y, z in ray(speaker.position, listener.position)):
            return False
    return None


@hook('candidate_allowed')
def caster_admission(engine: Any, actor: Any, candidate: Any, action: Any):
    from ..zones import actor_inside_zone
    typed = ((getattr(action, 'parameters', None) or {}).get('typed') or {})
    if typed.get('sphere') != SOUND:
        return None
    if any(z.owner_id == actor.entity_id and actor_inside_zone(engine, actor, z)
           for z in fields(engine)) and not silent_source(engine, action.source_definition_id, action):
        return False
    return None
