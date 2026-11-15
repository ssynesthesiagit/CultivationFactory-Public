"""Empty Palm Stops the Blade: owned ``iron_empty_palm`` reaction modifier.

The marker itself is inert. ``hit_reduced`` runs only after Iron Forearm Guard
actually lowers a melee weapon packet. Expend Focus, roll the compiled Unarmed
Strike against the attacker, then choose one printed result. This is a roll,
not a damaging strike: no Form, Exploit or after-hit strike effects are invoked.
Disarm stores the exact triggering weapon and selected adjacent ground cell
in the existing evented Disarmed state, used by normal pickup and persistence.
Old bundles without the marker retain their behavior.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook
from .needle import ask, checkpoint_id

SOURCE = "TAL_IRON_FIST_EMPTY_PALM_STOPS_THE_BLADE"
GUARD = "TAL_IRON_FIST_IRON_FOREARM_GUARD"
FOCUS = "resource:core.martial_focus"


@effect("iron_empty_palm")
def marker(ctx: Any, row: dict[str, Any]) -> None:
    pass


@hook("hit_reduced")
def follow_up(engine: Any, defender: Any, attacker: Any, source_id: str | None,
              before: int, after: int, reducers: tuple[str, ...]) -> int:
    from .. import typed_executor as te, typed_reactions as tr, zones, motion
    from ..gate2_runtime_models import DiceSpec, Position

    if attacker is None or GUARD not in reducers or before <= after:
        return 0
    rows = (getattr(engine, "typed_reaction_rows", {}) or {}).get(defender.entity_id, [])
    if not any(row.get("feature_id") == GUARD and any(e.get("type") == "iron_empty_palm"
               for e in row.get("effects") or []) for row in rows):
        return 0
    triggering = engine.action_catalog.get(source_id)
    typed_source = (getattr(triggering, "parameters", None) or {}).get("typed") or {}
    if not typed_source.get("weapon") or typed_source.get("range_ft") or not any(
            e.get("type") == "attack" and e.get("attack_kind") == "weapon"
            for e in typed_source.get("effects") or []):
        return 0
    if defender.resources.get(FOCUS, 0) < 1:
        return 0
    strike = next((engine.action_catalog[aid] for aid in defender.action_ids
                   if aid in engine.action_catalog and engine.action_catalog[aid].display_name == "Unarmed Strike (Iron Fist)"), None)
    if strike is None:
        return 0
    intent = getattr(engine, "_active_intent", None)
    prompt = f"Empty Palm Stops the Blade after Iron Forearm Guard reduces {attacker.display_name}'s {triggering.display_name}"

    def choose(name: str, options: list[str], *, decline: bool = False) -> list[str]:
        return ask(engine, intent, checkpoint_id(engine, name, defender.entity_id, attacker.entity_id), defender,
                   "choice:needle.empty_palm." + name, options, target_id=attacker.entity_id,
                   prompt=prompt + ": " + name, allow_decline=decline)

    from .attack_reduction import follow_up_scope
    with follow_up_scope(engine, defender, attacker.entity_id, GUARD):
        if not choose("Expend Martial Focus", ["Expend Martial Focus"], decline=True):
            return 0
        engine._spend_resource(defender, FOCUS, 1, SOURCE)
        typed = strike.parameters["typed"]
        action = strike.model_copy(update={"source_definition_id": SOURCE, "display_name": "Empty Palm Stops the Blade"})
        ctx = te.Context(engine, defender, action, intent, typed, [attacker], attacker)
        from . import run
        shaped = tr.on_d20_pending(engine, defender, "attack")
        shaped_mode = shaped["modes"][0] if len(set(shaped["modes"])) == 1 else None
        for mode in [zones.attack_mode(engine, defender, attacker),
                     motion.attack_mode(engine, defender, attacker, melee=True, source=SOURCE),
                     shaped_mode, *run("attack_mode", ctx, attacker)]:
            if mode in ("ADVANTAGE", "DISADVANTAGE"):
                engine._add_modifier(defender, SOURCE, "attack_mode", "SET", mode, "NEXT_ATTACK", expires_on="CONSUMED")
        spec = {"attack_bonus": int(ctx.numbers.get("attack_bonus") or 0) + int(shaped["bonus"])
                + sum(int(n or 0) for n in run("attack_bonus", ctx, defender)),
                "damage": None, "range_ft": None, "target_check": lambda: True}
        hit = engine._resolve_attack_spec(defender, attacker, spec, intent, reaction_depth=1, source_definition_id=SOURCE)
        tr.on_attack_resolved(engine, defender, attacker, spec, intent)
        if not hit:
            tr.on_attack_missed(engine, defender, attacker, spec, intent)
        tr.after_d20(engine, defender, "attack", success=hit, other=attacker, melee=True,
                     natural=tr._last_natural_roll(engine, defender.entity_id, attacker.entity_id))
        (getattr(engine, "_typed_roll_outcome", None) or {}).pop(defender.entity_id, None)
        if not hit:
            return 0
        occupied = set(engine.grid.footprint_cells(attacker.position, engine._footprint(attacker)))
        adjacent = {(x + dx, y + dy) for x, y in occupied for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                    if (dx or dy) and (x + dx, y + dy) not in occupied}
        cells = [Position(x=x, y=y) for x, y in sorted(adjacent)
                 if engine.grid.in_bounds((x, y)) and (x, y) not in engine.grid.blocked]
        options = (["Disarm"] if cells else []) + ["Reduce damage by 2d8", "Make Opened"]
        picked = choose("Choose one on hit", options)
        if picked == ["Reduce damage by 2d8"]:
            roll = engine.roller.roll(DiceSpec(count=2, sides=8, modifier=0), actor_id=defender.entity_id, reason=SOURCE + ":reduction")
            engine._record_roll(roll)
            return roll.total
        if picked == ["Make Opened"]:
            te.run_effects(ctx, [{"type": "mark", "mark": "Opened", "applies_to": "target",
                                  "duration": {"kind": "until_end_of_your_next_turn"}}])
        elif picked == ["Disarm"]:
            locations = {f"{p.x},{p.y}": p for p in cells}
            selected = choose("Disarm adjacent space", list(locations))
            if selected and not te.condition_immune(engine, attacker, "disarmed") and not tr.offer_condition_gained(engine, attacker, defender, "disarmed"):
                spot = locations[selected[0]].model_dump(mode="json")
                held = triggering.parameters.get("requires_held_weapon")
                transferred = next(((owner, iid, condition) for owner in engine.state.actors.values()
                                    for iid, condition in owner.conditions.items()
                                    if held and condition.data.get("disables_action") == held
                                    and condition.data.get("held_by") == attacker.entity_id), None)
                if transferred:
                    owner, iid, condition = transferred
                    data = {key: value for key, value in condition.data.items() if key != "held_by"}
                    te._reapply_weapon_state(ctx, owner, iid, {**data, "dropped_at": spot})
                else:
                    engine._apply_condition(attacker, te.CONDITION_PREFIX + "disarmed", SOURCE, defender.entity_id,
                                            expires_on="UNTIL_REMOVED", data={"disables_action": source_id.split("#")[0], "dropped_at": spot})
                te._reweigh(ctx)
        return 0
