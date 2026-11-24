"""Opt-in physiology eligibility; shared reader is combat.physiology.trait.

Any effect can declare requires_physiology: {any: [trait names]}.
Only that row's actual recipients are filtered. Legacy rows are inert.
The any form permits an explicitly approved animating-current exception without
claiming that all undead, constructs or spiritual creatures have one.
Any effect can declare forbids_physiology: {any: [trait names]} instead: the row
is refused only for a recipient whose printed record says the trait is absent.
An unstated trait stays unknown, so an ordinary creature is not made immune by a
record that does not mention it (retribution_riders.Haymaker's reading).
A refused recipient gets the row's physiology_note, when it prints one, so the
table reads why the ability did nothing.
The same key on a zone's "inside" rule, trigger or move_through row (the spec
combat/zone_subjects.allowed is asked about) gates that rule's recipients, so a
standing area can be written for breath-dependent creatures alone.
"""
from typing import Any

from . import hook, note
from ..physiology import trait


def eligible(subject: Any, row: dict[str, Any]) -> bool:
    gate = row.get("requires_physiology")
    if gate and not any(trait(subject, name) is True for name in gate["any"]):
        return False
    forbid = row.get("forbids_physiology")
    return not (forbid and any(trait(subject, name) is False for name in forbid["any"]))


def _gate_note(ctx: Any, row: dict[str, Any], subject: Any) -> None:
    text = row.get("physiology_note")
    if not text or subject is None:
        return
    from . import _while_listing

    if _while_listing():
        return  # save_subjects also feeds area-risk previews: never log while the menu is being built
    note(ctx.engine, ctx.source, ctx.actor, str(text).replace("{name}", subject.display_name), (subject,))


@hook("effect_subject_allowed")
def physiology_subject_allowed(ctx: Any, row: dict[str, Any], subject: Any) -> bool | None:
    if eligible(subject, row):
        return None
    _gate_note(ctx, row, subject)
    return False


@hook("zone_recipient_allowed")
def physiology_zone_recipient_allowed(engine: Any, zone: Any, actor: Any, spec: dict[str, Any]) -> bool | None:
    return None if eligible(actor, spec) else False


@hook("candidate_allowed")
def physiology_candidate_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    rows = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or []
    subjects = [engine.state.actors[t] for t in (getattr(candidate, "target_ids", ()) or ()) if t in engine.state.actors]
    # Area creation must remain available: its packet filters each entrant later.
    if subjects and rows and all((row.get("requires_physiology") or row.get("forbids_physiology"))
                                 and row.get("applies_to", "target") == "target"
                                 and all(not eligible(subject, row) for subject in subjects) for row in rows):
        return False
    return None
