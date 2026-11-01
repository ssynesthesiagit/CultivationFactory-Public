"""Sand Step and Abrading Ward through the established terrain and turn hooks.

New Ward rows seal ward_optional=1: consent is asked at the hostile creature's turn start,
with an event-derived once-per-creature-per-round allowance. Glass Edge's public
ward_damage_type adapter supplies the printed Slashing/Piercing choice and its own
sealed numbers supply glass-grain damage. Frozen predecessor rows keep their automatic
Slashing behavior. Dune Bank and Loose Footing are implemented by the later Sand riders.
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
        return [{**row, "block": "sand_ward", "pb": int(numbers.get("pb") or 0), "ward_optional": 1,
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
        if not owner.active or owner.entity_id == actor.entity_id:
            continue  # only a hostile creature (relative to the Sand talent's owner) takes this damage
        if not own.owns_block(engine, owner, "sand_ward"):
            continue
        rows = own.block_rows(engine, owner, "sand_ward")
        optional = any(r.get("ward_optional") for r in rows)
        if optional:
            from ..relations import ENEMY, relation
            if relation(engine, owner, actor) != ENEMY:
                continue
        elif owner.team_id == actor.team_id:
            continue  # frozen rows retain the predecessor relation rule
        from .sand_terrain import standing_in
        inside = (standing_in(engine, owner.entity_id, actor) if optional
                  else _in_own_sand(engine, owner.entity_id, actor))
        if not inside:
            continue
        damage_type = "SLASHING"
        if optional:
            round_start = next((e.sequence for e in reversed(engine.events) if e.event_type == "ROUND_STARTED"), 0)
            if any(event.event_type == "DAMAGE_COMMITTED" and event.source_definition_id == "TAL_SAND_ABRADING_WARD"
                   and event.actor_id == owner.entity_id and actor.entity_id in event.target_ids
                   and event.sequence > round_start for event in engine.events):
                continue
            from .needle import CHOICE, ask, checkpoint_id
            chosen = ask(engine, getattr(engine, "_active_intent", None),
                         checkpoint_id(engine, "sand_ward", owner.entity_id, actor.entity_id), owner,
                         CHOICE + "sand_ward", ["use"], allow_decline=True, preferred=["use"],
                         labels={"use": "Deal Abrading Ward damage"}, name="Abrading Ward",
                         target_id=actor.entity_id,
                         prompt=f"Abrading Ward: {actor.display_name} starts its turn in Sand Terrain you control. "
                                f"Deal {own.row_number(engine, owner, 'sand_ward', 'pb')} damage? "
                                "No Action, Reaction or CP is needed. Each creature can take it only once per round.")
            if not chosen:
                continue
            from .sand_riders import ward_damage_type
            damage_type = ward_damage_type(engine, owner, actor)
        engine._commit_damage(actor, own.row_number(engine, owner, "sand_ward", "pb"), damage_type, "TAL_SAND_ABRADING_WARD",
                              owner.entity_id, None, reaction_depth=0)
