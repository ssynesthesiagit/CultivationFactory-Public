"""Sand sphere: Sand Step and Abrading Ward, the two "Sand Terrain you control" passives with a clean hook to
attach to (Gu Xiangze, 2026-09-28). Dune Bank and Loose Footing are NOT automated here -- see the notes below and
combat/rules/feature_status.d/gu.json for why, rather than guessing at a gate that might not enforce the printed
precondition.

Sand Step ("You ignore Difficult Terrain created by sand, dust, gravel, or dry loose earth. In addition, while you
are standing on Sand Terrain you control, Opportunity Attacks against you are made with Disadvantage."): the first
sentence is not this module's concern -- the zones a Sand talent creates are already tagged `"difficult": "hostile"`
(combat/zones.py), so they cost hostile creatures extra movement but never the owner; there is nothing left for
Sand Step to add there. The second sentence is a real, missing rider, added through the `attack_mode` hook, gated
on the attack being an opportunity attack (`typed.get("opportunity_of")`, set by factory_compiler._opportunity_
attack) against a target standing in its own Sand Terrain.

Abrading Ward ("Whenever a hostile creature starts its turn in Sand Terrain you control, you may deal Slashing
damage to it equal to your Proficiency Bonus. A creature can take this damage from you only once per round."):
added through the `turn_start` hook, since it needs to see every actor's turn begin, not just Gu's. The printed
"you may" is defaulted to "yes" (there is no cost or downside to decline, so the choice is not worth a separate
player toggle here -- unlike an Exploit-style post-hit choice with real alternatives).

Dune Bank ("Trigger: you or a creature within 5 feet of your Sand Terrain is targeted by an attack roll ...
Half Cover") and Loose Footing ("a hostile creature enters Sand Terrain you control ... Reaction ... Dexterity save
or fall Prone") are both real Reaction-economy mechanics in the authority, but neither is automated:
- Loose Footing's trigger is "a creature enters your Terrain", a shape combat/reaction_triggers.py's classify_trigger
  explicitly excludes by design (`_CREATURE_KIND_TEXT["moved"]`'s second pattern rules out "your ... Terrain"
  triggers as untracked) -- this is an existing, corpus-wide boundary, not something specific to Gu.
- Dune Bank's generic "attacked" reaction row has no way to require "near Sand Terrain you control": the only
  veto point (combat/ext's `reaction_allowed(engine, reactor, other)` hook) does not say *which* of the reactor's
  reactions is being offered, only who is reacting to whom -- returning False there would silence every reaction
  Gu has (Bulwark included), not just this one. Automating it correctly needs a per-row precondition hook this
  engine does not have yet; adding one was judged too broad a change for one talent on one character.
Both are left in the compiler's own "skipped.reaction" list rather than faked.
"""
from __future__ import annotations

from typing import Any

from . import hook
from . import fight_ownership as own


def _in_own_sand(engine: Any, owner_id: str, subject: Any) -> bool:
    from .. import zones

    for zone in zones.typed_zones(engine):
        if zone.owner_id != owner_id:
            continue
        if (zone.trigger_profile.get("visual") or {}).get("material") == "sand" and zones._inside(engine, subject, zone):
            return True
    return False


@hook("compile_block")
def sand_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Sand Step's compiled marker (combat/rules/feature_blocks.d/riders_c4.json), read by difficult_exempt and
    attack_mode below; and Abrading Ward's, read by turn_start below.

    Abrading Ward's row also carries the Proficiency Bonus its damage equals, taken from the character's own
    numbers, so the fight holds everything the rider needs (an integer, so it survives a save and reload)."""
    if block == "sand_step":
        return [{**row, "block": "sand_step"}]
    if block == "sand_ward":
        return [{**row, "block": "sand_ward", "pb": int(numbers.get("pb") or 0),
                 **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}]
    return None


@hook("difficult_exempt")
def sand_step_ground(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    """Sand Step: "You ignore Difficult Terrain created by sand, dust, gravel, or dry loose earth." (rider lane C4,
    2026-09-30). Its own Sand Terrain never slows it anyway; this covers another creature's Sand Terrain and sand on the map
    (areas whose ground is sand). Keyed off the compiled sand_step row, so a fight whose bundles carry no such row is
    unchanged."""
    from .. import zones
    from .sand_terrain import is_sand

    if not own.owns_block(engine, actor, "sand_step"):
        return None
    return {(cell.x, cell.y) for zone in zones.typed_zones(engine)
            if (zone.trigger_profile.get("visual") or {}).get("material") == "sand" or is_sand(engine, zone) for cell in zone.affected_cells} or None


@hook("attack_mode")
def sand_step(ctx: Any, target: Any) -> str | None:
    if not ctx.typed.get("opportunity_of"):
        return None  # only opportunity attacks are named by Sand Step
    # "while you are standing on Sand Terrain you control" -- the creature being attacked is the one that owns the
    # talent, so the row is read for the target; this fight's own row, not a character-wide cache.
    if not own.owns_block(ctx.engine, target, "sand_step"):
        return None
    return "DISADVANTAGE" if _in_own_sand(ctx.engine, target.entity_id, target) else None


@hook("turn_start")
def abrading_ward(engine: Any, actor: Any) -> None:
    for owner in engine.state.actors.values():
        if not owner.active or owner.entity_id == actor.entity_id or owner.team_id == actor.team_id:
            continue  # only a hostile creature (relative to the Sand talent's owner) takes this damage
        if not own.owns_block(engine, owner, "sand_ward"):
            continue
        if not _in_own_sand(engine, owner.entity_id, actor):
            continue
        engine._commit_damage(actor, own.row_number(engine, owner, "sand_ward", "pb"), "SLASHING", "TAL_SAND_ABRADING_WARD",
                              owner.entity_id, None, reaction_depth=0)
