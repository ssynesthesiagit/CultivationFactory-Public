"""Forbidden Silence Field's hostile-only entry saving throw."""
from typing import Any

from . import hook

FIELD = 'TAL_SOUND_FORBIDDEN_SILENCE_FIELD'


def fields(engine: Any):
    """Active native zones belonging to this exact ability."""
    result = []
    for zone in engine.state.zones.values():
        action = engine.action_catalog.get(zone.source_definition_id)
        typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
        if zone.active and typed.get('source') == FIELD:
            result.append(zone)
    return result


@hook('zone_recipient_allowed')
def hostile_entry_save(engine: Any, zone: Any, actor: Any, spec: Any):
    """The Field's printed entry save is rolled by hostile creatures only.

    The printed line names its own recipients ("hostile creatures entering for
    the first time on a turn or starting their turns there make Constitution
    saving throws"), and the Field's owner ruling keeps that line hostile-only
    while putting its Inside-the-area rules -- Deafened, voice and verbal
    components fail, Thunder halved -- on every creature inside, the caster
    included. An owner ruling outranks a reviewed roster, so the area's harm
    roster would otherwise roll that save for allies and for the caster too.
    Only this Field's own save packet is bounded; its continuous inside rules
    and every other area keep the roster the table computes.
    """
    rows = spec.get('effects') if isinstance(spec, dict) else None
    if not isinstance(rows, (list, tuple)) or not any(
            isinstance(row, dict) and row.get('type') == 'save' for row in rows):
        return None
    if not any(zone is live for live in fields(engine)):
        return None
    from ..zones import hostile_to
    return hostile_to(engine, zone, actor)
