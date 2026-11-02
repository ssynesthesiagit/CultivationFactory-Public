"""Wax Rampart (Wax; rider lane C11, 2026-09-30).

Source (owner text, authority/typed_mechanics/rules_text.json TAL_WAX_WAX_RAMPART): "When you create Set Shape, you may create a sturdier
rampart. The Set Wax gains additional hit points equal to your Cultivation Level, and creatures behind it may use it as half cover if its
position would reasonably protect them. At CL 5, a rampart can instead provide three-quarters cover to a creature directly behind it, but
each 5-foot section used this way counts as two sections of your Set Shape."  Set Wax (the Wax sphere's rules): "each 5-foot section of
Set Wax has AC 12 + your Proficiency Bonus and hit points equal to 5 + twice your Cultivation Level. It is immune to poison and psychic
damage. It has vulnerability to fire damage".

How it runs. Wax Rampart's reviewed modifier (reviewed_final.d/riders_c11.json) gives Mold Wax: Set Shape two choices, "Wax Rampart: Half
Cover" and "Wax Rampart: Three-Quarters Cover"; each is a named wall of combat/rules/terrain.json (the zone compiler finds a wall by the
ability's name): a line of Set Wax sections across the user's line to the chosen square, as long as Set Shape's cubes allow (10 / 20 / 30
/ 40 feet at CL 1 / 5 / 10 / 15; half that for Three-Quarters: each section counts twice), giving Half (+2) or Three-Quarters (+5) Cover
to attacks through it; each section can be attacked (AC 12 + PB, 5 + 3 x CL hit points, immune to poison and psychic, vulnerable to
fire). It is climbed over like the Humble Wall (double movement). The Three-Quarters choice is offered from CL 5 (``candidate_allowed``).
Tempered Sealant qualifies Fire vulnerability per hit: ordinary fire and sources
at or below the creator's CL do not double the damage. Higher-level sources do.
CR, spell-level and overwhelming-heat rulings without typed metadata remain GM qualifications.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

BLOCK = "wax_rampart"


@hook("compile_block")
def compile_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "kind": spec.get("kind")}]


@hook("wall_defenses")
def tempered(ctx: Any, zone: Any, stats: dict[str, Any]) -> dict[str, Any] | None:
    from .. import typed_reactions

    action = ctx.engine.action_catalog.get(zone.source_definition_id)
    effects = (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or [])
    if not any(e.get("type") == "wax_rampart" for e in effects if isinstance(e, dict)) or "FIRE" not in stats.get("vulnerable", ()):
        return None
    rows = typed_reactions._rows(ctx.engine, zone.owner_id, BLOCK)
    if not any(row.get("kind") == "tempered_sealant" for row in rows):
        return None
    owner_cl = int((zone.trigger_profile.get("numbers") or {}).get("cl") or 1)
    # Wall attacks retain the wielder's numbers. An unknown creature's level
    # is not evidence of ordinary fire; leave that qualification to the GM.
    levels = [int(values[key]) for values, key in ((ctx.numbers, "cl"), (ctx.typed, "challenge_rating"),
                                                 (ctx.typed, "spell_level")) if values.get(key) is not None]
    if not levels and not ctx.typed.get("ordinary_fire"):
        return None
    source_level = max(levels, default=0)
    if source_level > owner_cl or ctx.typed.get("overwhelming_heat"):
        return None
    return {**stats, "vulnerable": [kind for kind in stats["vulnerable"] if kind != "FIRE"]}


@effect("wax_rampart")
def rampart(ctx: Any, row: dict[str, Any]) -> None:
    cover = "Three-Quarters Cover" if row.get("three_quarters") else "Half Cover"
    from .. import typed_reactions

    sealant = any(r.get("kind") == "tempered_sealant" for r in typed_reactions._rows(ctx.engine, ctx.actor.entity_id, BLOCK))
    fire = "Tempered Sealant prevents double fire damage unless the fire source is higher level or overwhelming" if sealant else "takes double damage from fire"
    note(ctx.engine, ctx.source, ctx.actor, f"Wax Rampart: {ctx.actor.display_name} raises a sturdier Set Wax rampart ({cover} to creatures "
         f"behind it; each section can be attacked; {fire}).")


@hook("candidate_allowed")
def three_quarters_from_cl_5(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    rows = [row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "wax_rampart" and row.get("three_quarters")]
    if not rows:
        return None
    return int((typed.get("numbers") or {}).get("cl") or 1) >= 5
