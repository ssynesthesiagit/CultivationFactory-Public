"""Opt-in physiology eligibility; shared reader is combat.physiology.trait.

Any effect can declare requires_physiology: {any: [trait names]}.
Only that row's actual recipients are filtered. Legacy rows are inert.
The any form permits an explicitly approved animating-current exception without
claiming that all undead, constructs or spiritual creatures have one.
The same key on a zone's "inside" rule, trigger or move_through row (the spec
combat/zone_subjects.allowed is asked about) gates that rule's recipients, so a
standing area can be written for breath-dependent creatures alone.
"""
from typing import Any

from . import hook
from ..physiology import trait


def eligible(subject: Any, row: dict[str, Any]) -> bool:
    gate = row.get("requires_physiology")
    return not gate or any(trait(subject, name) is True for name in gate["any"])


@hook("effect_subject_allowed")
def physiology_subject_allowed(ctx: Any, row: dict[str, Any], subject: Any) -> bool | None:
    return False if not eligible(subject, row) else None


@hook("zone_recipient_allowed")
def physiology_zone_recipient_allowed(engine: Any, zone: Any, actor: Any, spec: dict[str, Any]) -> bool | None:
    return None if eligible(actor, spec) else False


@hook("candidate_allowed")
def physiology_candidate_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    rows = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or []
    subjects = [engine.state.actors[t] for t in (getattr(candidate, "target_ids", ()) or ()) if t in engine.state.actors]
    # Area creation must remain available: its packet filters each entrant later.
    if subjects and rows and all(row.get("requires_physiology") and row.get("applies_to", "target") == "target"
                                and all(not eligible(subject, row) for subject in subjects) for row in rows):
        return False
    return None
