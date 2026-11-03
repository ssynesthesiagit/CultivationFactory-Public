"""Shield Skate and Riding the Falling Star: what the Shield lets you do with your body (AUTO55, 2026-10-05).

Sphere Compendium, Shield (owner's text: ``APP/authority/typed_mechanics/rules_text.json``):

  Shield Skate, TAL_SHIELD_SHIELD_SKATE
    "When moving down an incline or taking the Dash action, you may use a Bonus Action to throw your Shield beneath
     your feet and skate across the ground. Until the end of the current turn: increase your Speed by 20 feet;
     ignore nonmagical difficult terrain that your Shield can physically cross; do not benefit from the Shield's AC
     bonus during movement made through Shield Skate; recover and re-equip the Shield at the end of your movement
     without using the Utilize action."
  Riding the Falling Star, TAL_SHIELD_RIDING_THE_FALLING_STAR
    "When using Shield Skate: you may cross water, snow, loose sand, unstable rubble, and similar surfaces; you may
     descend vertical surfaces safely; you reduce falling damage by five times your Cultivation Level; if you fall at
     least 20 feet before reaching the ground, you may move up to your Speed along the ground immediately after
     landing."

What the table did before: Shield Skate's compiled row carried the +20 Speed and nothing else, so its terrain
clause never happened and the Shield's +2 Armor Class stayed on; Riding the Falling Star typed its falling-damage
line as a ``damage_modifier``, which only typed *reactions* read, so a passive talent that reduced no falling at
all compiled to nothing -- and the record carried "five times your Cultivation Level" as ``formula: "cl"``, one
fifth of the printed reduction. Both talents' riders were shown to the GM.

Documented seams used, all inert without the talent's own compiled row
(combat/rules/feature_blocks.d/auto55_shield.json): ``difficult_exempt`` for the ground the Shield crosses,
``falling_damage`` for the reduction and safe descent, and ``fall_landed`` for the immediate follow-up move.
The movement-only Shield AC penalty needs a native scoped movement seam and remains a GM reminder.
The shared helper ``sand_terrain.is_sand``
(combat/ext/sand_terrain.py) is this module's consumer for "loose sand" on the map.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .needle import ask, checkpoint_id, CHOICE, cell_id

BLOCK = "auto55_shield"
SKATE = "TAL_SHIELD_SHIELD_SKATE"
FALLING_STAR = "TAL_SHIELD_RIDING_THE_FALLING_STAR"
SKATING = "condition:typed.shield_skating"
LANDING = "condition:typed.riding_falling_star"

#: Ground a Shield can physically cross: "water, snow, loose sand, unstable rubble, and similar surfaces". A zone
#: made Difficult Terrain by a printed barrier the Shield cannot cross (a magical wall of force, thorns) is left
#: alone: only loose ground reads as crossable here.
LOOSE_GROUND = frozenset({"sand", "snow", "water", "rubble", "scree", "gravel", "mud", "ash", "swamp", "ice"})


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Shield Skate's and Riding the Falling Star's own compiled markers (combat/rules/feature_blocks.d/auto55_shield.json)."""
    if block != BLOCK or spec.get('kind') not in ('skating', 'falling_star'):
        return None
    return [{**row, "block": BLOCK, "kind": str(spec.get("kind") or ""), "cl": int(numbers.get("cl") or 1),
             **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}]


def _row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    return next((row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, ())
                 if row.get("block") == BLOCK and row.get("kind") == kind), None)


def skating(engine: Any, actor: Any) -> bool:
    """A usable Shield and the current-turn skating activation; shared by landing consumers."""
    from .shield_wielding import wielding_a_shield

    return (wielding_a_shield(engine, actor) and _row(engine, actor, 'skating') is not None
            and any(c.condition_id == SKATING for c in actor.conditions.values()))


# --------------------------------------------------------------------------- Shield Skate
@effect("shield_skate")
def skate(ctx: Any, eff: dict[str, Any]) -> None:
    """"Until the end of the current turn: increase your Speed by 20 feet; ignore nonmagical difficult terrain that
    your Shield can physically cross; do not benefit from the Shield's AC bonus during movement made through Shield
    Skate". The recorded activation gates terrain and falling benefits; stationary Shield AC is retained."""
    from ..typed_executor import run_effects

    engine, actor = ctx.engine, ctx.actor
    run_effects(ctx, [row for row in (eff.get("effects") or []) if str(row.get("type") or "") == "speed"])
    engine._apply_condition(actor, SKATING, SKATE, actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"label": "Shield Skate: Speed +20 until this turn ends; cross supported nonmagical terrain"})


@hook("difficult_exempt")
def loose_ground_is_crossable(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    """Shield Skate's "ignore nonmagical difficult terrain that your Shield can physically cross" and Riding the
    Falling Star's "you may cross water, snow, loose sand, unstable rubble, and similar surfaces"."""
    if not skating(engine, actor):
        return None
    from .. import zones
    from .sand_terrain import is_sand

    cells: set[tuple[int, int]] = set()
    magical: set[tuple[int, int]] = set()
    for zone in zones.typed_zones(engine):
        material = str((zone.trigger_profile.get("visual") or {}).get("material") or "").lower()
        # Only map terrain is known nonmagical. Spell-created sand is not exempt.
        if zone.owner_id != zones.MAP_OWNER:
            if zone.trigger_profile.get('difficult'):
                magical.update((cell.x, cell.y) for cell in zone.affected_cells)
            continue
        if _row(engine, actor, 'falling_star') is None and material in {'water', 'snow', 'sand', 'rubble', 'swamp'}:
            continue
        if material in LOOSE_GROUND or is_sand(engine, zone):
            cells.update((cell.x, cell.y) for cell in zone.affected_cells)
    return cells - magical or None


# --------------------------------------------------------------------------- Riding the Falling Star
@effect("riding_falling_star")
def ride(ctx: Any, eff: dict[str, Any]) -> None:
    """The talent's own marker. Riding the Falling Star is read at the moment of a fall, not at a cast, so this
    records the Cultivation Level the reduction is five times of -- an integer, so it survives a save and reload --
    and the ``falling_damage`` / ``fall_landed`` hooks below do the rest."""
    ctx.engine._apply_condition(ctx.actor, LANDING, FALLING_STAR, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "While Shield Skate is active: land upright and reduce falling damage by 5 x Cultivation Level",
                                      "cl": int(ctx.numbers.get("cl") or 1)})


@hook("falling_damage")
def falling_star(engine: Any, target: Any, defended: int, fall: Any, intent: Any) -> dict[str, Any] | None:
    """"you may descend vertical surfaces safely; you reduce falling damage by five times your Cultivation Level".

    While skating with a usable Shield, reduce damage by five times Cultivation
    Level and land upright. Owning the passive alone grants neither benefit.
    """
    row = _row(engine, target, "falling_star")
    if row is None or not skating(engine, target) or int(getattr(fall, "distance_ft", 0) or 0) <= 0:
        return None
    return {"amount": max(0, defended - 5 * max(1, int(row.get("cl") or 1))), "land_prone": False}


@hook("fall_landed")
def ride_the_falling_star(engine: Any, actor: Any, fall: Any, intent: Any) -> None:
    """Immediate optional ground movement after a real landing; never a lasting Dash budget."""
    from . import granted_moves

    feet = int(fall.distance_ft)
    if feet < 20 or not actor.active or not skating(engine, actor) or _row(engine, actor, 'falling_star') is None:
        return
    speed = engine._effective_speed(actor)
    routes = granted_moves.destinations(engine, actor, speed, lambda pos: pos.z == actor.position.z)
    options = {cell_id(pos): path for pos, path, _ in routes if pos != actor.position}
    labels = {cell_id(pos): f'Move to square ({pos.x}, {pos.y}), '
              + (f'{pos.z * 5} feet high' if pos.z else 'at ground level')
              + f' ({cost} feet of movement; no Action cost)'
              for pos, _, cost in routes if pos != actor.position}
    picked = ask(engine, intent, checkpoint_id(engine, 'FALLING_STAR', actor.entity_id), actor,
                 CHOICE + 'falling_star_landing', list(options), labels=labels, allow_decline=True,
                 target_id=actor.entity_id, name='Riding the Falling Star', feature_id=FALLING_STAR,
                 prompt=f'Riding the Falling Star: {actor.display_name} lands from {feet} feet. Move up to {speed} feet along the ground now (no Action cost)?',
                 default='decline')
    if picked:
        granted_moves.commit(engine, actor, options[picked[0]], FALLING_STAR,
                             budget_ft=speed, provokes=True, intent=intent)
