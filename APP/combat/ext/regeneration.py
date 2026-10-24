"""Ordinary regeneration, and the printed clause that switches it off (shared helper; lane OCF8f1).

On this table ordinary regeneration is the Hit Points a creature's own printed regeneration feature gives it -- "At the
start of each of your turns, if you have at least 1 Hit Point, regain 20 Hit Points" (Immortal Regeneration), Marrow
Regeneration, Demon Bone Regeneration. What that feature costs to use is not part of the test: Marrow Regeneration is a
Bonus Action that spends 2 Stamina and Demon Bone Regeneration spends 1 Devoured Essence, and each of those is still the
creature regenerating, so a printed suppression of regeneration refuses them like any other regeneration. Healing
another creature's ability gives it is not regeneration, and neither is a Furnace's recovery after the creature spends
Stamina (Liver Furnace is not printed as regeneration); those keep working while regeneration is switched off.

Provenance is a key on the healing row itself, so nothing here has to recognise an ability id:

    {"type": "healing", "applies_to": "self", "regeneration": true, ...}

A regeneration feature that builds its own row in code sets it there (combat/ext/bodya_body_refining.py's Immortal
Regeneration, combat/ext/ironroot_daemonic.py's Demon Bone Regeneration); a regeneration feature typed in the owner's
reviewed data sets it on the effect (authority/typed_mechanics/reviewed_final.d/ironroot.json's Marrow Regeneration,
rebuilt into authority/Tianxia_Typed_Mechanics_Authority_R1.json by tools/build_typed_mechanics_authority.py). A row
without the key is ordinary healing and is untouched.

Switching it off is one row any ability whose printed text says so can use (the effect ``suppress_regeneration``), which
places this module's condition on the creature and lasts as long as that printed text says -- in Life-Severing Sword,
until the start of its user's next turn. ``effect_allowed`` then refuses a regeneration row whose recipient carries the
condition, before the healing is rolled. That hook is a pure query (its contract is at ``combat/ext/__init__.py``:
"handlers must be pure queries"), so it appends no event, records nothing and changes nothing: the same answer comes back
however often a caller asks. The player is told why nothing was restored by the condition pill below, which repeats the
printed words -- what the creature cannot regain, who put it there and until when. Nothing else about the activation
changes: the regeneration feature's own cost, its condition and its other printed riders still resolve, so a creature
whose regeneration is refused has still paid for the activation it pressed.

Users: combat/ext/sword_core.py (Life-Severing Sword's "it cannot benefit from ordinary regeneration").
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

MARK = "regeneration"
RECORD = "condition:typed.regeneration_suppressed"


def _held(subject: Any) -> list[Any]:
    """The suppression records on one creature, oldest first."""
    return sorted((row for row in (getattr(subject, "conditions", None) or {}).values() if row.condition_id == RECORD),
                  key=lambda row: int(row.applied_sequence or 0))


@effect("suppress_regeneration")
def suppress_regeneration(ctx: Any, row: dict[str, Any]) -> None:
    """"it cannot benefit from ordinary regeneration until the start of your next turn": one condition on the creature,
    lasting as long as this row says. It records no numbers, so a table commit and reload keep it."""
    from .. import typed_executor as te

    name = str(row.get("name") or getattr(ctx.action, "display_name", "") or "This effect")
    for subject in te._default_subject(ctx, row, harmful=False):
        expires = te.effect_expiry(ctx, row, subject, condition=True) or "START_OF_SOURCE_NEXT_TURN"
        from .turn_words import until_words
        until = until_words(ctx.engine, expires, actor=ctx.actor, holder=subject)
        ctx.engine._apply_condition(subject, RECORD, ctx.source, ctx.actor.entity_id, expires_on=expires,
                                    data={"name": name, "label": f"{name}: {subject.display_name} cannot regain Hit "
                                                                 f"Points from regeneration {until}."})


@hook("effect_allowed")
def regeneration_refused(ctx: Any, row: dict[str, Any]) -> bool | None:
    """Refuse a regeneration healing row whose recipient is under a printed suppression of regeneration, before the
    healing is rolled. Without such a record (and on every other row) this answers nothing.

    This hook is called by ``combat/typed_executor.run_effects`` as a pure permission query, so it deliberately writes
    nothing: no event, no log line, no state. Asking twice gives the same answer and asking when nothing is suppressed
    leaves the fight untouched. The explanation belongs to the condition the creature carries, which ``suppressed_text``
    below reads back in the words of the printed ability that placed it."""
    if not isinstance(row, dict) or row.get("type") != "healing" or not row.get(MARK):
        return None
    from .. import typed_executor as te

    for subject in te._default_subject(ctx, row, harmful=False):
        if _held(subject):
            return False
    return None


@hook("status_description")
def suppressed_text(engine: Any, holder: Any, row: Any, data: Any) -> dict[str, Any] | None:
    """The condition pill, in the words the printed ability used."""
    if (row or {}).get("condition_id") != RECORD:
        return None
    text = str((data or {}).get("label") or "")
    return {"text": text} if text else None