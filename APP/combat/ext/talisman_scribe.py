"""Talisman Scribe's printed Advantage on identifying a formula the fighter personally knows.

Rules text (owner's Sphere Compendium, authority/typed_mechanics/rules_text.json, SHA256
cef68fd6dcae1892b61cc3c9240ef05a9c6cce4773c42eeff51a4e3e904985bc; the full decoded
``rules_text`` hash is the record's own commitment, not the authority file's scope hash):

  TALISMANS_BASE_TALISMAN_SCRIBE
    "When you gain the Talismans sphere, you gain proficiency with Calligrapher's Supplies. If you already
     have this proficiency, gain one additional Common formula.
     You learn three Common formulae of your choice.
     You may craft Common talismans using the Talisman Crafting procedure.
     You can identify your own talismans automatically. You have Advantage on checks to identify a talisman
     formula you personally know."

What this module owns, and only this: the one printed clause of that record this table can resolve during a
fight -- "You have Advantage on checks to identify a talisman formula you personally know."

Delivery, using existing documented seams only (no core file, no runtime patching):

  * Acquisition. The row itself arrives the ordinary way: ``combat/table_advance.py`` ``apply`` ->
    ``base_abilities`` grants a learned Sphere's ``kind == "base_ability"`` records into the sheet's
    ``spheres_and_talents.automatic_sphere_component_record_ids``, which ``combat/factory_compiler.py``
    ``compile_character`` reads back into ``owned_ids``. Nothing here types the record id into a sheet.

  * The printed row. ``APP/authority/typed_mechanics/reviewed_final.d/mgr_t14_talisman_scribe.json`` types
    this record's single deliverable clause as an ordinary ``modifier`` (the public channel:
    ``combat/factory_compiler.py`` ``apply_modifiers`` -> ``_resolve_targets``, ``scope: "named"``,
    ``targets: ["Read the Script"]``). That is the same channel the sibling talent Seal Breaker's Eye already
    uses for its printed Advantage on Read the Script, so no second implementation is added anywhere. The
    generated authority is rebuilt with ``APP/tools/build_typed_mechanics_authority.py``; no generated file
    is hand-edited.

  * The printed knowledge boundary. The modifier's Advantage rides onto the Read the Script action's own
    typed effects, and ``combat/ext/talismans.py`` ``_printed_check_modes`` already reads such a row when the
    check is made. That read is unconditional, because a talent that prints Advantage on a named check needs
    no further gate. This record's print does need one: the Advantage is only for "a talisman formula **you
    personally know**", and nothing on the sheet records which formulae a fighter has read. So this module
    supplies the missing boundary -- and only for this record's own row, leaving every other advantage row on
    that action untouched.

The boundary is asked, never assumed. Nothing on a fighter's sheet says which formulae they know, so this
module does not invent a fact: it asks the fighter whether the writing before them uses a formula they
personally know, offering the printed choices, and grants the Advantage only on the printed yes. An AI
fighter can attest established personal knowledge through the ordinary recorded ``needle.ask`` chooser,
just like the owner. Both answers remain legal for that provider. This module supplies no hidden facts or
formula inference: a provider must use its own information about the writing. The shipped local chooser
and the no-provider fallback prefer the no/unknown branch. Unknown stays unknown.

Inert for everyone else: ``applies`` returns False for an action that is not Read the Script, for a fighter
whose sheet never granted this record, and for an action carrying no Advantage row stamped with this
record's id. A fight saved before this change keeps its own behaviour, and no other sphere, character or
check is affected.
"""
from __future__ import annotations

import re
from typing import Any

from . import hook
from .needle import CHOICE, ask, checkpoint_id

SCRIBE = "TALISMANS_BASE_TALISMAN_SCRIBE"
SCRIPT = "TALISMANS_BASE_READ_THE_SCRIPT"
SCRIPT_NAME = "Read the Script"
# The stamp APP/combat/factory_compiler.py apply_modifiers puts on every effect it merges onto a target
# ability's own action: the id of the record the row came from. Reading it is what keeps this module from
# touching any other printed Advantage on the same action (Seal Breaker's Eye, Formula Library, ...).
STAMP = "source_modifier"

YES = "a formula I personally know"
NO = "a formula I have not learned"

# The printed knowledge boundary, in the player's own words: what the Advantage is for, which writing it
# applies to, and that nothing is invented when the fighter has not established the writing (checklist 13).
_PROMPT = ("Read the Script: is this writing a talisman formula you personally know? "
           "Talisman Scribe gives you Advantage on identifying a formula you have learned yourself. "
           "A formula you have not learned is read normally.")


def _check_named(row: dict[str, Any]) -> bool:
    """Whether this effect row prints Advantage/Disadvantage on some check (talismans._printed_check_modes)."""
    if str(row.get("type") or "").lower() not in ("advantage", "disadvantage"):
        return False
    return bool(re.search(r"check", f"{row.get('on') or ''} {row.get('evidence') or ''}", re.I))


def _scribe_rows(ctx: Any) -> list[dict[str, Any]]:
    """This record's own printed check rows, as stamped onto this action's typed effects.

    Only rows whose stamp is this record count: another record's printed Advantage on Read the Script keeps
    whatever delivery it already had, and this module never widens or narrows it.
    """
    return [row for row in (ctx.typed.get("effects") or [])
            if isinstance(row, dict) and row.get(STAMP) == SCRIBE and _check_named(row)]


def _owns_scribe(engine: Any, actor: Any) -> bool:
    """Whether this fighter's compiled fight actually carries the row (never injected test metadata).

    The row reaches the fight only through the table's own acquisition path and the compiler, so this reads
    the compiled action catalogue the engine was built with -- the same object every other ability reads --
    rather than any test-only field. A fighter whose sheet never granted the record compiles no such action
    and no such stamped row, so the check is inert for them.
    """
    for action in (getattr(engine, "action_catalog", None) or {}).values():
        if action.owner_id != actor.entity_id:
            continue
        typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
        if str(typed.get("source") or "") == SCRIBE:
            return True
        if any(isinstance(row, dict) and row.get(STAMP) == SCRIBE for row in typed.get("effects") or []):
            return True
    return False


@hook("effect_allowed")
def scribe_row_is_not_narrated(ctx: Any, row: Any) -> bool | None:
    """Skip this record's own printed check row when its action resolves its effects.

    The row's only delivery is the check path (talismans._printed_check_modes reads it and asks the printed
    question). Left to run_effects it has no roll descriptor ("checks to identify a talisman formula you
    personally know" names no skill or ability), so block_advantage would print it as a GM rider on every
    Read the Script, on both answers. Only this record's stamped check rows are refused here.
    """
    if not isinstance(row, dict) or row.get(STAMP) != SCRIBE or row.get("type") not in ("advantage", "disadvantage"):
        return None
    return False if _check_named(row) else None


def applies(ctx: Any) -> bool:
    """Whether this action's printed check is one this record's Advantage may cover.

    False for every other action, every other fighter and every other printed Advantage row. This is the
    one call ``combat/ext/talismans.py`` makes, so the rest of this file stays a plain helper.
    """
    engine, actor = ctx.engine, ctx.actor
    if not str(ctx.source or "").endswith(SCRIPT):
        return False
    if not _owns_scribe(engine, actor):
        return False
    rows = _scribe_rows(ctx)
    if not any(str(row.get("type") or "").lower() == "advantage" for row in rows):
        return False
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "talisman_scribe_known_formula", actor.entity_id),
                 actor, CHOICE + "talisman_scribe_known_formula", [YES, NO],
                 labels={YES: "Read the Script: this writing is a formula I personally know (Talisman Scribe: "
                               "Advantage on the check)",
                         NO: "Read the Script: this writing is not a formula I personally know (read normally)"},
                 # Knowledge is an owner/controller attestation through the ordinary
                 # recorded choice channel, not inferred from other actors' sheets.
                 # Keep YES reachable for a provider with established personal
                 # knowledge; absent that information the preference/fallback is NO.
                 preferred=[NO],
                 prompt=_PROMPT, name="Talisman Scribe", feature_id=SCRIBE,
                 target_id=actor.entity_id)
    return picked == [YES]
