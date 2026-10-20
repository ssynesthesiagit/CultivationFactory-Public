"""Ash sphere core rules the table runs (rider lane C13, 2026-09-30; owner: "i want everything we can automated, keep going until
its only the non-combat ones left"). Printed source: the Sphere Compendium, Ash, "Core Ash Rules" and "Cinder Brand".

Ashen Brand ("An Ashen Brand is a visible residue mark left on a creature or object. Unless a talent says otherwise: Ashen Brand
lasts until the start of your next turn. A branded creature cannot gain Temporary HP. ... While the visible cinder trail remains
exposed, the creature cannot successfully take the Hide action solely by becoming Heavily Obscured or moving behind cover. Total
Cover or a technique that explicitly conceals the trail can still protect it. ... A creature may bear only one of your Ashen Brands
at a time."): the brand itself is an ordinary typed mark named "Ashen Brand" (typed_executor.block_mark: one per creature per
caster; its duration is on the row that places it). This module adds the rest of the printed rule to every Ashen Brand, whichever
Ash ability placed it:
  - ``mark_applied``: the branded creature gets the engine's own no-Temporary-HP condition (condition:typed.no_temp_hp, read by
    gate4_engine._grant_temp_hp), bound to that brand instance; it goes when the brand goes (``event``) and a ``turn_start``
    sweep removes any whose brand is gone, so it never outlasts the brand.
  - ``candidate_allowed``: a branded creature cannot take a Hide action while any enemy has a line of sight to it (on this table a
    wall that blocks the line is Total Cover; obscurement or partial cover alone no longer hides it).

Remnants ("A Remnant is a small patch of ash ... a Remnant occupies one 5-foot space; a Remnant counts as Ash Terrain; a Remnant
lasts for 1 minute without Concentration; you may maintain a number of Remnants equal to your Proficiency Bonus; when you exceed
that limit, remove the oldest Remnant"): a placed zone (combat/ext/placed.py, tag ``ash_remnant``) carrying the Ash Terrain rule of
combat/rules/terrain.json (Lightly Obscured, difficult terrain for hostile creatures, the Constitution save for a hostile creature
moving more than 10 feet through it), 10 rounds.

Effects (typed rows, e.g. Cinder Brand's options in authority/typed_mechanics/reviewed_final.d/review_sw-air.json):
  ash_remnant            "create one Remnant in an unoccupied space adjacent to the target": the caster picks the square (asked;
                         the AI and an unanswered fight take the free square nearest the caster).
  ash_remnant_move       "move one Remnant within 30 feet up to 10 feet": the caster picks the Remnant and the direction (asked;
                         the AI moves the Remnant nearest the target toward it).
  ash_suppress_temp_hp   "suppress one ordinary source of Temporary HP already affecting the target until the start of your next
                         turn": the target's Temporary HP stops protecting it and comes back (no more than it had; Temporary HP
                         does not stack) at the start of the caster's next turn -- or at the target's own turn if the caster is
                         gone by then.

Hooks added to the framework: none. Inert for every creature that bears no Ashen Brand, no suppression and owns no Remnant.
"""

from __future__ import annotations

from .map_positions import map_position

from typing import Any

from . import effect, hook
from ..hook_queries import actor_action

BRAND = "Ashen Brand"
NO_TEMP_HP = "condition:typed.no_temp_hp"
SUPPRESSED = "condition:typed.ash_temp_hp_suppressed"
TAG = "ash_remnant"
_DIRS = {"north": (0, -1), "north-east": (1, -1), "east": (1, 0), "south-east": (1, 1), "south": (0, 1), "south-west": (-1, 1),
         "west": (-1, 0), "north-west": (-1, -1)}


def _brand_prefix() -> str:
    from ..typed_executor import mark_condition_id

    return mark_condition_id(BRAND, "")  # "condition:typed.mark.ashen_brand." -- every caster's brand


def _brands(actor: Any) -> list[str]:
    prefix = _brand_prefix()
    return [iid for iid, row in actor.conditions.items() if row.condition_id.startswith(prefix)]


# ------------------------------------------------------------------------------------------------ Ashen Brand
@hook("mark_applied")
def brand_denies_temp_hp(ctx: Any, name: str, subject: Any) -> None:
    """"A branded creature cannot gain Temporary HP": one no-Temporary-HP condition per brand instance."""
    if str(name or "").strip().lower() != BRAND.lower() or subject is None or not subject.active:
        return
    engine = ctx.engine
    for brand in _brands(subject):
        if any((row.data or {}).get("ashen_brand") == brand for row in subject.conditions.values() if row.condition_id == NO_TEMP_HP):
            continue
        engine._apply_condition(subject, NO_TEMP_HP, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"ashen_brand": brand, "label": "Ashen Brand: it cannot gain Temporary Hit Points while the brand lasts"})


def _sweep(engine: Any, holder: Any, source: str) -> None:
    from .condition_ownership import remove_instance

    live = set(_brands(holder))
    for iid, row in list(holder.conditions.items()):
        brand = (row.data or {}).get("ashen_brand")
        if row.condition_id == NO_TEMP_HP and brand and brand not in live:
            remove_instance(engine, holder, iid, source)


@hook("event", nested=True)
def brand_gone(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_REMOVED":
        return
    payload = kwargs.get("payload") or {}
    if not str(payload.get("condition_id") or payload.get("instance_id") or "").startswith(("condition-instance:" + _brand_prefix(), _brand_prefix())):
        return
    for target_id in kwargs.get("target_ids") or ():
        holder = engine.state.actors.get(target_id)
        if holder is not None:
            _sweep(engine, holder, str(kwargs.get("source_definition_id") or "ash"))


@hook("candidate_allowed", query_key=actor_action,
      present=lambda engine: any(_brands(actor) for actor in engine.state.actors.values()))
def branded_cannot_hide(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """A branded creature's cinder trail: no Hide while an enemy has a clear line to it (only a wall -- Total Cover -- hides it)."""
    if action is None or not _brands(actor):
        return None
    effects = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or []
    if not any(isinstance(row, dict) and row.get("type") == "hide" for row in effects):
        return None
    from .. import stealth

    return not any(engine._line_of_sight_actor_to_cell(foe, actor.position) for foe in stealth.foes(engine, actor))


# ------------------------------------------------------------------------------------------------ Remnants
def _pb(ctx: Any) -> int:
    return max(1, int(ctx.numbers.get("pb") or ctx.numbers.get("proficiency_bonus") or 2))


def remnants(engine: Any, owner: Any) -> list[Any]:
    """The caster's Remnants, oldest first."""
    from . import placed

    return placed.of(engine, TAG, owner_id=owner.entity_id)


def _place(ctx: Any, cell: Any) -> None:
    from .. import zones
    from . import placed

    engine, owner = ctx.engine, ctx.actor
    terrain = (zones.terrain_rules().get("terrains") or {}).get("ash terrain") or {}
    placed.place(engine, owner, source=ctx.source, tag=TAG, cells=[cell], name="Remnant (Ash Terrain)", duration_rounds=10,
                 color=terrain.get("color"), material=terrain.get("material") or "ash", terrain=["ash terrain"], difficult="hostile",
                 obscured=terrain.get("obscured") or "light", numbers=dict(ctx.numbers),
                 extra={"move_through": dict(terrain.get("move_through") or {}) or None})
    mine = remnants(engine, owner)
    while len(mine) > _pb(ctx):  # "when you exceed that limit, remove the oldest Remnant"
        placed.drop(engine, mine.pop(0), "REMNANT_LIMIT")
    placed.note(engine, ctx.source, owner, f"{owner.display_name} leaves a Remnant of ash at ({cell.x}, {cell.y}): Ash Terrain for 1 minute "
                f"(lightly obscured; difficult for enemies; an enemy moving more than 10 feet through ash makes a Constitution save or "
                f"cannot take Reactions until its next turn).")


def _on_map(engine: Any, cell: Any) -> bool:
    grid = engine.grid
    return 0 <= cell.x < grid.width and 0 <= cell.y < grid.height and (cell.x, cell.y) not in grid.blocked


def _free(engine: Any, cell: Any) -> bool:
    from .rider_support import occupant

    return _on_map(engine, cell) and occupant(engine, cell) is None


@effect("ash_remnant")
def create_remnant(ctx: Any, eff: dict[str, Any]) -> None:
    """Cinder Brand: "create one Remnant in an unoccupied space adjacent to the target"."""
    from ..gate2_runtime_models import Position
    from .needle import cell_id, position_of
    from .rider_choices import pick

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None:
        return
    around = {Position(x=x, y=y) for cell in engine.grid.footprint_cells(target.position, engine._footprint(target.entity_id))
              for x, y in [((cell.x if hasattr(cell, "x") else cell[0]) + dx, (cell.y if hasattr(cell, "y") else cell[1]) + dy)
                           for dx in (-1, 0, 1) for dy in (-1, 0, 1)]}
    cells = sorted((cell for cell in around if _free(engine, cell)), key=lambda c: (engine.grid.distance_ft(owner.position, c), c.y, c.x))
    if not cells:
        ctx.rider("Cinder Brand: no unoccupied square next to the target for a Remnant.")
        return
    options = [cell_id(cell) for cell in cells]
    labels = {cell_id(cell): f"Leave the Remnant at {cell.x},{cell.y} ({engine.grid.distance_ft(owner.position, cell)} ft from you)"
              for cell in cells}
    chosen = pick(engine, owner, "ash_remnant", "Cinder Brand: create a Remnant", options, subject=target, labels=labels,
                  preferred=[options[0]], optional=False, trigger=f"Cinder Brand hits {target.display_name}")
    _place(ctx, position_of((chosen or options)[0]))


@effect("ash_remnant_move")
def move_remnant(ctx: Any, eff: dict[str, Any]) -> None:
    """Cinder Brand: "move one Remnant within 30 feet up to 10 feet"."""
    from ..gate2_runtime_models import Position
    from . import placed
    from .rider_choices import pick

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    near = [zone for zone in remnants(engine, owner) if engine.grid.distance_ft(owner.position, zone.center) <= 30]
    if not near:
        ctx.rider("Cinder Brand: none of your Remnants is within 30 feet to move.")
        return
    options, labels, moves = [], {}, {}
    for zone in near:
        for word, (dx, dy) in _DIRS.items():
            for steps in (2, 1):
                cell = map_position(engine, zone.center.x + dx * steps, zone.center.y + dy * steps)
                if cell is not None and _on_map(engine, cell):
                    key = f"{zone.zone_id}|{word}"
                    options.append(key)
                    labels[key] = f"Move the Remnant at {zone.center.x},{zone.center.y} {steps * 5} feet {word}"
                    moves[key] = (zone, cell)
                    break
    if not options:
        return
    focus = target.position if target is not None else owner.position
    preferred = min(options, key=lambda key: (engine.grid.distance_ft(moves[key][1], focus), options.index(key)))
    chosen = pick(engine, owner, "ash_remnant_move", "Cinder Brand: move a Remnant", options, subject=target or owner, labels=labels,
                  preferred=[preferred], optional=True, trigger="Cinder Brand hits")
    if not chosen:
        return
    zone, cell = moves[chosen[0]]
    before = zone.center
    placed.reshape(engine, zone, cells=[cell], center=cell)
    placed.note(engine, ctx.source, owner, f"{owner.display_name} moves a Remnant of ash from ({before.x}, {before.y}) to ({cell.x}, {cell.y}).")


# ------------------------------------------------------------------------------------------------ Temporary HP suppression
def _flag(subject: Any) -> str:
    return f"_round_ash_suppressed_temp_hp:{subject.entity_id}"


@effect("ash_suppress_temp_hp")
def suppress_temp_hp(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    amount = int(target.temporary_hp or 0)
    if amount <= 0:
        ctx.rider(f"Cinder Brand: {target.display_name} has no Temporary Hit Points to suppress.")
        return
    owner.turn_flags[_flag(target)] = int(owner.turn_flags.get(_flag(target)) or 0) + amount
    target.temporary_hp = 0
    engine._append_event("TEMP_HP_GRANTED", ctx.source, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                         payload={"offered": 0, "before": amount, "after": 0, "removed_by": "Cinder Brand (suppressed)"})
    engine._apply_condition(target, SUPPRESSED, ctx.source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"amount": amount, "label": f"Temporary Hit Points ({amount}) suppressed by Cinder Brand until "
                                                             f"the start of {owner.display_name}'s next turn"})


def _restore(engine: Any, owner: Any, holder: Any) -> None:
    from .condition_ownership import remove_instance

    for iid, row in list(holder.conditions.items()):
        if row.condition_id != SUPPRESSED or row.source_actor_id != owner.entity_id:
            continue
        amount = int((row.data or {}).get("amount") or 0)
        remove_instance(engine, holder, iid, row.source_definition_id)
        owner.turn_flags.pop(_flag(holder), None)
        before = int(holder.temporary_hp or 0)
        after = max(before, amount) if holder.active else before  # Temporary HP does not stack
        if after != before:
            holder.temporary_hp = after
            engine._append_event("TEMP_HP_GRANTED", row.source_definition_id, actor_id=owner.entity_id, target_ids=(holder.entity_id,),
                                 payload={"offered": amount, "before": before, "after": after, "restored_by": "Cinder Brand suppression ends"})


@hook("turn_start")
def suppression_ends(engine: Any, actor: Any) -> None:
    for holder in engine.state.actors.values():
        if any(row.condition_id == SUPPRESSED and row.source_actor_id == actor.entity_id for row in holder.conditions.values()):
            _restore(engine, actor, holder)
    # The caster left the fight before its next turn: the suppression on this creature ends at its own turn.
    for row in [row for row in actor.conditions.values() if row.condition_id == SUPPRESSED]:
        caster = engine.state.actors.get(row.source_actor_id)
        if caster is not None and not caster.active:
            _restore(engine, caster, actor)
    _sweep(engine, actor, "ash")
