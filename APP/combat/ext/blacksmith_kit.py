"""Portable Forge Kit's prepared Forge Mark (Blacksmith; rider lane C10, 2026-09-30).

Owner text (tianxia.talent.blacksmith.portable_forge_kit): "During a short rest, choose one weapon, shield, suit of armor, tool, or
object owned by you or an ally. That item gains one Forge Mark at the start of the next action scene that day. You can prepare a
number of items this way equal to your Proficiency Bonus, and an item can hold only one prepared mark from this talent."

How it runs (feature block "blacksmith_kit", kind "portable_forge_kit"): the table keeps a smith's Forge Mark on the smith itself
(the workpiece the Blacksmith abilities work: Hammer the Mark's typed "mark ... applies_to self", spent by Set Edge / Fit Armor,
combat/ext/ironclad_blacksmith.py), so a fight starts with the smith holding a Forge Mark from its own prepared item
(``match_start``: before anyone's first turn, evented, placed as Hammer the Mark places it). Items of allies prepared the same way
have no Forge Mark of their own on this table and stay with the GM.
"""

from __future__ import annotations

from typing import Any

from . import hook

KIT = "tianxia.talent.blacksmith.portable_forge_kit"
BLOCK = "blacksmith_kit"


@hook("compile_block")
def kit_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": BLOCK, "kind": spec.get("kind")}] if block == BLOCK else None


@hook("match_start")
def prepared_mark(engine: Any) -> None:
    from .passive_rows import row_of
    from ..typed_executor import mark_condition_id

    # Idempotent: a reloaded fight's engine runs this on its constructor state, which its saved state then replaces.
    for _key, smith in sorted(engine.state.actors.items()):
        if not smith.active or row_of(engine, smith.entity_id, BLOCK, "portable_forge_kit") is None:
            continue
        mark = mark_condition_id("Forge Mark", smith.entity_id)
        if any(c.condition_id == mark for c in smith.conditions.values()):
            continue
        engine._apply_condition(smith, mark, KIT, smith.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Forge Mark (Portable Forge Kit: prepared during your last short rest)"})
