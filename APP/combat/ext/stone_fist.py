"""Stone Fist riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Stone Fist (Breaking Fist, Overwhelming Blow, Shattering Palm, Earth-Shattering Fist,
Heaven-Cracking Blow and their Normalized Procedures). The hit riders are path_riders.py ``paid_hit`` rows (asked, paid, limited
there); this module supplies their effects:

stone_fist_mark        marks the activation (Overwhelming Blow's collisions belong to it alone)
overwhelming_step_in   "Push the target 5 feet and enter its former space": the push, then, if it left, you move into the space
                       (Opportunity Attacks from other creatures still apply; the target's do not)
heaven_cracking        + 10d10 Bludgeoning or Force; against a target whose Source CL is no higher than yours (a typed fighter's
                       CL; any other creature counts as mundane, Source CL 0) it ignores Resistance to both types
break_the_guard        Shattering Palm's creature form: a Constitution save; failure: AC - 2 for 1 minute, repeating the save at
                       the end of each of its turns; success: AC - 1 until the start of your next turn. Never stacks: a new
                       failure replaces the old reduction, a success never shortens or weakens a standing failure.
Overwhelming Blow's collisions (hook ``collision``): stopped by a solid surface, the target takes Proficiency Bonus Bludgeoning;
driven into a creature, that creature makes a Dexterity save: on a failure both take it, on a success only the target. Each
creature takes it once per activation. Every hook returns early without a matching marker, modifier or flag.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.stone_fist.feature."
PALM = PREFIX + "shattering_palm"
GUARD_FLAG = "_round_shattering_palm_guard"  # kept across turns ("_round_" keys survive the turn reset)


def _cl(engine: Any, actor_id: str) -> int:
    """A fighter's Source CL: a typed fighter's CL; anything else is mundane (0)."""
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor_id), None)
    return int((bundle or {}).get("cl") or 0)


@effect("stone_fist_mark")
def stone_fist_mark(ctx: Any, row: dict[str, Any]) -> None:
    ctx.damage_cache["_stone_fist"] = str(row.get("feature") or "")


# -------------------------------------------------------------------------------------------------- Overwhelming Blow
@effect("overwhelming_step_in")
def overwhelming_step_in(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .rider_movement import step

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    former = target.position
    te.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}])
    if target.position == former or not actor.active:
        return  # "only if the target actually leaves that space"
    if not engine.grid.placement_legal(former, footprint=engine._footprint(actor), occupied_cells=engine._occupied_cells_except(actor.entity_id)):
        return
    start = actor.position
    if engine.grid.distance_ft(start, former) > engine.grid.square_size_ft:
        return
    # "does not provoke Opportunity Attacks from the target but can provoke from other creatures"
    ready = target.reaction_available
    target.reaction_available = False
    try:
        engine._resolve_leave_reach(actor, start, former, ctx.intent)
    finally:
        target.reaction_available = ready
    if actor.active and actor.position == start:
        step(engine, actor, [start, former], PREFIX + "overwhelming_blow")


@hook("collision")
def overwhelming_collision(ctx: Any, target: Any, blocked_at: Any, remaining_ft: int) -> None:
    if ctx.damage_cache.get("_stone_fist") != "overwhelming" or target is None or not target.active:
        return
    from .. import typed_executor as te

    engine, actor = ctx.engine, ctx.actor
    pb = int(actor.proficiency_bonus or 2)
    done = ctx.damage_cache.setdefault("_stone_fist_collided", [])
    spot = (blocked_at.x, blocked_at.y)
    other = next((c for c in engine.state.actors.values() if c.active and c.entity_id != target.entity_id and spot in engine._actor_cells(c)), None)
    slam = {"type": "damage", "applies_to": "target", "flat": pb, "damage_types": ["bludgeoning"], "evidence": "Overwhelming Blow: collision"}
    if other is None:
        if target.entity_id not in done:
            done.append(target.entity_id)
            note(engine, PREFIX + "overwhelming_blow", actor, f"Overwhelming Blow: {target.display_name} slams into a solid surface.", (target.entity_id,))
            te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}), [slam])
        return
    note(engine, PREFIX + "overwhelming_blow", actor, f"Overwhelming Blow: {target.display_name} is driven into {other.display_name}.",
         (target.entity_id, other.entity_id))
    box: dict[str, Any] = {}
    sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [other], other, box)
    te.run_effects(sub, [{"type": "save", "ability": "dex", "evidence": "Overwhelming Blow: the second creature's Dexterity saving throw",
                          "on_fail": [{"type": "stone_fist_flag"}], "on_success": []}])
    for creature in ([target, other] if box.get("_stone_fist_failed") else [target]):
        if creature.active and creature.entity_id not in done:
            done.append(creature.entity_id)
            te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [creature], creature, {}), [slam])


@effect("stone_fist_flag")
def stone_fist_flag(ctx: Any, row: dict[str, Any]) -> None:
    ctx.damage_cache["_stone_fist_failed"] = True  # the second creature failed its Dexterity save


# ------------------------------------------------------------------------------------------------ Heaven-Cracking Blow
@effect("heaven_cracking")
def heaven_cracking(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    pierce = _cl(engine, target.entity_id) <= max(1, _cl(engine, actor.entity_id))
    engine._stone_fist_pierce = actor.entity_id if pierce else None
    try:
        te.run_effects(ctx, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 10, "sides": 10}, "damage_types": ["bludgeoning", "force"],
                              "evidence": "Heaven-Cracking Blow: + 10d10" + (" (ignoring Resistance)" if pierce else "")}])
    finally:
        engine._stone_fist_pierce = None


@hook("resistance_ignored")
def heaven_cracking_pierces(engine: Any, kind: str, typed: Any, source_actor_id: Any, target: Any = None) -> bool | None:
    if getattr(engine, "_stone_fist_pierce", None) and engine._stone_fist_pierce == source_actor_id and str(kind).upper() in ("BLUDGEONING", "FORCE"):
        return True
    return None


# ------------------------------------------------------------------------------------------ Shattering Palm: Break the Guard
def _guard(target: Any) -> list[tuple[str, Any]]:
    return [(mid, m) for mid, m in target.modifiers.items() if m.source_definition_id == PALM and m.target_field == "armor_class"]


def _drop_guard(engine: Any, target: Any, reason: str) -> None:
    for mid, _m in _guard(target):
        del target.modifiers[mid]
        engine._append_event("MODIFIER_REMOVED", PALM, actor_id=target.entity_id, target_ids=(target.entity_id,), payload={"modifier_id": mid, "reason": reason})
    target.turn_flags.pop(GUARD_FLAG, None)


@effect("break_the_guard")
def break_the_guard(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    target = ctx.target
    if target is None or not target.active:
        return
    te.run_effects(ctx, [{"type": "save", "ability": "con", "evidence": "Shattering Palm (Break the Guard): Constitution saving throw",
                          "on_fail": [{"type": "break_the_guard_result", "failed": True}], "on_success": [{"type": "break_the_guard_result", "failed": False}]}])


@effect("break_the_guard_result")
def break_the_guard_result(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .effect_durations import token

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None:
        return
    failed = bool(row.get("failed"))
    standing = [m for _mid, m in _guard(target)]
    if not failed and any(int(m.value) <= -2 for m in standing):
        return  # a success never weakens or shortens a standing failed-save reduction
    _drop_guard(engine, target, "REPLACED")
    if failed:
        engine._add_modifier(target, PALM, "armor_class", "ADD", -2, "ALWAYS", expires_on=te.clock_expiry(engine, "minutes", 1))
        target.turn_flags[GUARD_FLAG] = {"dc": int(ctx.numbers.get("save_dc") or 10), "owner": owner.entity_id}
    else:
        expires = "START_OF_SOURCE_NEXT_TURN" if engine.state.current_actor_id == owner.entity_id else token("start", owner.entity_id, int(owner.turns_started) + 1)
        engine._add_modifier(target, PALM, "armor_class", "ADD", -1, "ALWAYS", expires_on=expires)


@hook("turn_end")
def guard_repeat_save(engine: Any, actor: Any) -> None:
    """"It repeats the save at the end of each turn, ending the reduction on a success" (the affected creature's turns)."""
    record = actor.turn_flags.get(GUARD_FLAG)
    if not record:
        return
    if not any(int(m.value) <= -2 for _mid, m in _guard(actor)):
        actor.turn_flags.pop(GUARD_FLAG, None)  # it ran out
        return
    from .. import typed_executor as te
    from .states import context

    owner = engine.state.actors.get(str(record.get("owner") or "")) or actor
    ctx = context(engine, owner, PALM, [actor], {"save_dc": int(record.get("dc") or 10)})
    te.run_effects(ctx, [{"type": "save", "ability": "con", "evidence": "Shattering Palm: repeated Constitution saving throw",
                          "on_fail": [], "on_success": [{"type": "break_the_guard_end"}]}])


@effect("break_the_guard_end")
def break_the_guard_end(ctx: Any, row: dict[str, Any]) -> None:
    if ctx.target is not None:
        _drop_guard(ctx.engine, ctx.target, "SAVED")
