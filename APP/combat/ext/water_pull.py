"""Pull of the River: a chosen 10-foot pull that replaces Water Lash's 5-foot move.

Printed (Sphere Compendium, Water, Pull of the River): "When your Water Lash hits a
Soaked target, you may pull the target 10 feet instead of moving it 5 feet. If the
target is Large or smaller and ends this movement adjacent to a Basin or Current you
created, it must succeed on a Strength saving throw or fall Prone."

``water_pull_of_river`` is the only effect this talent contributes, replacing the
base ability's ordinary post-hit 5-foot move so the two never both happen. It is
inert for characters who do not own the talent: the reviewed modifier only reaches a
Water Lash whose owner holds the row, and the hook checks that row on the compiled
action. Saved catalogs compiled before this change keep their own rows.

The printed order matters and is enforced here: the pull is chosen and resolved
first, and only a target that actually *ended* the movement inside the printed
distance of one of the caster's own Basins or Currents, and that is Large or smaller,
makes the Strength save. A target pulled away from every owned water area, or one
that is Huge or larger, never rolls it.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PULL = "TAL_WATER_PULL_OF_THE_RIVER"
LASH = "WATER_BASE_WATER_LASH"
BASIN = "WATER_BASE_SHAPE_CURRENT"
SOAKED_PREFIX = "condition:typed.mark.soaked."
FEET = 10
# 5e size order; "Large or smaller" is everything up to and including Large.
SIZE_ORDER = ("Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan")


def _walk(rows: Any) -> Any:
    """Every effect row of a compiled action, however deeply the ability nests them.

    A hit-time modifier lands inside the attack's ``on_hit`` list rather than beside it,
    so a top-level scan would never see this talent's own pull row.
    """
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        yield row
        yield from _walk(row.get("on_hit"))
        yield from _walk(row.get("on_fail"))
        yield from _walk(row.get("on_success"))
        yield from _walk(row.get("effects"))


def _owns_pull(typed: dict[str, Any]) -> bool:
    """True when this compiled action carries the talent's own pull row.

    Only an action that already carries it is changed, so an ordinary Water Lash, and
    every saved catalog compiled before the talent existed, keep their own rows.
    """
    return any(row.get("type") == "water_pull_of_river" for row in _walk(typed.get("effects")))


def _base_soaked_move(effect_row: dict[str, Any]) -> bool:
    """The base ability's ordinary 'already Soaked, you may move it 5 feet' block."""
    if effect_row.get("type") != "if_marked" or effect_row.get("mark") != "Soaked":
        return False
    return any((e.get("type") == "forced_movement" and int(e.get("distance_ft") or 0) == 5) or e.get("type") == "water_lash_shift"
               for e in effect_row.get("effects") or [])


@hook("compile_action")
def pull_replaces_base_move(action: Any, info: dict[str, Any]) -> Any:
    """'pull the target 10 feet *instead of* moving it 5 feet': never both.

    The base ability states its post-hit move inside the attack's ``on_hit`` list, so the
    whole effect tree is walked rather than just its top level.
    """
    typed = (action.parameters or {}).get("typed") or {}
    if typed.get("source") != LASH or not _owns_pull(typed):
        return None
    kept = _swap_in_place(typed.get("effects") or [])
    if kept == (typed.get("effects") or []):
        return None
    parameters = {**action.parameters, "typed": {**typed, "effects": kept}}
    return action.model_copy(update={"parameters": parameters})


def _swap_in_place(rows: list[Any]) -> list[Any]:
    """Put the pull exactly where the base ability's ordinary post-hit move was.

    Order is a printed rule, not a detail: "hits a **Soaked** target" is judged before this
    hit's own Soaked mark is applied, and "instead of moving it 5 feet" means the ordinary
    move is not also done. A hit-time modifier is otherwise appended after the mark, which
    would make every target count as already Soaked; taking the base move's own slot avoids that.
    """
    out: list[Any] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("on_hit"), list):
            row = {**row, "on_hit": _swap_in_place(row["on_hit"])}
        out.append(row)
    pull_at = next((i for i, row in enumerate(out)
                    if isinstance(row, dict) and row.get("type") == "water_pull_of_river"), None)
    base_at = next((i for i, row in enumerate(out) if _base_soaked_move(row)), None)
    if pull_at is not None and base_at is not None:
        pull_row = out[pull_at]
        out.pop(pull_at)
        if pull_at < base_at:
            base_at -= 1
        out[base_at] = pull_row
    return [row for i, row in enumerate(out) if not _base_soaked_move(row)]


def _soaked(creature: Any) -> bool:
    return any(row.condition_id.startswith(SOAKED_PREFIX) for row in creature.conditions.values())


def _source(engine: Any, source_id: str) -> str:
    action = engine.action_catalog.get(source_id)
    return str((((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source") or source_id))


def _size(creature: Any) -> str:
    return str(getattr(creature, "transformed_size_category", None) or creature.size_category or "Medium")


def _large_or_smaller(creature: Any) -> bool:
    size = _size(creature)
    return size in SIZE_ORDER and SIZE_ORDER.index(size) <= SIZE_ORDER.index("Large")


def _beside_own_water(engine: Any, caster: Any, creature: Any) -> bool:
    """True when the creature's own body is within one square of a Basin or Current the caster created.

    Zone cells are the caster's own water; a body touching or standing on those cells is
    adjacent to them. Cells only the caster's footprint reaches still count, so a Large
    body beside a small Basin is not silently excluded.
    """
    from ..space import point
    # Actor volumes are cell tuples and zone cells are Position models; space.point
    # normalises both to the same comparable form the engine's own footprint test uses.
    volume = set(engine._actor_volume(creature))
    if not volume:
        return False
    for zone in engine.state.zones.values():
        if not zone.active or zone.owner_id != caster.entity_id:
            continue
        # Court is a spiritual Domain, not physical water; only an actual
        # Basin/Current created by Shape Current qualifies for this rider.
        if _source(engine, zone.source_definition_id) != BASIN:
            continue
        cells = {point(cell) for cell in zone.affected_cells}
        for x, y, z in cells:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        if (x + dx, y + dy, z + dz) in volume:
                            return True
    return False


@effect("water_pull_of_river")
def pull_of_river(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects
    from . import forced_destination as destinations
    from .needle import CHOICE, checkpoint_id

    engine, caster, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    # The printed trigger is a Soaked target, checked before this hit's own mark.
    if not _soaked(target):
        return
    intent = ctx.intent or getattr(engine, "_active_intent", None)
    if intent is None:
        return
    def toward(previous: Any, destination: Any) -> bool:
        # Each horizontal axis must close on the caster or stay level: a pull
        # cannot detour away even if its endpoint would eventually be closer.
        before = (abs(previous.x - caster.position.x), abs(previous.y - caster.position.y))
        after = (abs(destination.x - caster.position.x), abs(destination.y - caster.position.y))
        return all(b <= a for a, b in zip(before, after)) and after != before

    routes = destinations.routes(engine, target, FEET, step_allowed=toward)
    if not routes:
        return
    started = target.position
    picked = destinations.ask(
        engine, intent, caster, target, routes, ctx=ctx,
        source=PULL,
        checkpoint=checkpoint_id(engine, "WATER_PULL_OF_RIVER", target.entity_id, ctx.source),
        choice_id=CHOICE + "water_pull_of_river",
        name="Pull of the River",
        prompt=(f"Pull of the River: your Water Lash hit {target.display_name}, which is already Soaked. "
                f"Pull it up to {FEET} feet toward you instead of moving it 5 feet? If it ends beside a Basin or "
                "Current you created and it is Large or smaller, it must then succeed on a Strength saving throw "
                "or fall Prone."),
        allow_decline=True)
    if not picked:
        return
    # forced_destination.ask carries the chosen route out through the engine's own forced
    # path, so the travelled distance is read from where the creature actually ended up.
    moved = engine.grid.distance_ft(started, target.position)
    if moved <= 0:
        return
    note(engine, PULL, caster,
         f"Pull of the River pulls {target.display_name} {moved} feet closer.", (target,))
    # The save is printed only for a target that ended beside the caster's own water.
    if not _large_or_smaller(target) or not _beside_own_water(engine, caster, target):
        return
    run_effects(ctx, [{"type": "save", "ability": "str", "applies_to": "target", "on": "",
                       "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target",
                                    "duration": "instant",
                                    "evidence": "ends adjacent to a Basin or Current you created, so it must succeed on a Strength saving throw or fall Prone"}],
                       "on_success": []}])
