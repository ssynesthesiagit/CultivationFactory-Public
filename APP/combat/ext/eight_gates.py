"""Eight Gates of the Heaven-Defying Body: the Gate state (rider lane C7, 2026-09-30: "i want everything we can automated").

Printed Gate Rules (Body Refining Subpath Compendium, "Gate Rules"): once per scene, open your Gates as a Bonus Action,
spending 1 Stamina per Gate, any number up to your maximum (Gate 2 at CL3, 4 at CL6, 5 at CL10, 7 at CL14, 8 at CL18: the
Gate features the character owns); benefits are cumulative. At the start of each of your turns take 1d4 Force per Gate
already open (1d6 per Gate while Gate 8 is open) -- damage that cannot be reduced, prevented, redirected or absorbed
(straight to Hit Points, no reactions), then you may open more unlocked Gates for 1 Stamina each without an action. Close
all Gates as a Bonus Action; they also close when you drop to 0 Hit Points. Once closed they cannot reopen this scene.

Owned rows: ``path_passive`` kind ``eight_gates`` with ``gate`` (the highest Gate that feature unlocks). The state is the
condition ``condition:typed.eight_gates`` (integers: open, max, pb, cl; ``closed`` once closed). Benefits while open:
  Gate 1  Speed +10 feet.
  Gate 2  once per turn an unarmed hit deals extra damage equal to Proficiency Bonus.
  Gate 3  Advantage on Strength and Dexterity ability checks (jump distance and climbing are not modelled).
  Gate 4  +2 AC; Advantage on saves against Prone and forced movement; forced movement against you is 10 feet shorter.
  Gate 5  once per turn, after taking the Attack action, one additional unarmed strike ("Gate of Thunder" free action).
  Gate 6  Fly Speed equal to current walking Speed and Hover.
  Gate 7  Resistance to all damage except Force and Psychic; unarmed strikes ignore Resistance; once per turn after an
          unarmed hit, push the target 10 feet or deny it Reactions until the start of its next turn (asked).
  Gate 8  Speed doubled (after the Gate 1 bonus); Advantage on unarmed attack rolls; once per turn on a hit +4d8 Force;
          lower-CL effects cannot Frighten, Paralyze or Stun you; Gate damage uses d6; if Gate damage drops you to 0 Hit
          Points, all Gates close and you are Stable (remain-at-1 features cannot answer it).
Every hook returns early for a creature without the state.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.eight_gates_of_the_heaven_defying_body.feature."
STATE = "condition:typed.eight_gates"
SOURCE = PREFIX + "first_and_second_gates"
ALL_BUT = ("ACID", "BLUDGEONING", "COLD", "FIRE", "LIGHTNING", "NECROTIC", "PIERCING", "POISON", "RADIANT", "SLASHING", "THUNDER", "VOID")
_UNARMED = ("unarmed",)


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == "eight_gates"]


def maximum(engine: Any, actor: Any) -> int:
    return max([int(row.get("gate") or 0) for row in _rows(engine, actor)] or [0])


def _state(actor: Any) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == STATE), None)


def open_gates(actor: Any) -> int:
    held = _state(actor)
    return 0 if held is None or (held.data or {}).get("closed") else int((held.data or {}).get("open") or 0)


def _set(engine: Any, actor: Any, source: str, **data: Any) -> None:
    held = _state(actor)
    merged = {**((held.data or {}) if held is not None else {}), **data}
    if held is not None:
        actor.conditions.pop(held.instance_id)
        engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": STATE, "instance_id": held.instance_id})
    count = int(merged.get("open") or 0)
    merged["label"] = "Eight Gates: closed for this scene" if merged.get("closed") else f"Eight Gates: {count} Gate{'s' if count != 1 else ''} open"
    engine._apply_condition(actor, STATE, source, actor.entity_id, expires_on="UNTIL_REMOVED", data=merged)
    _sync_resistance(engine, actor, source)


def _sync_resistance(engine: Any, actor: Any, source: str) -> None:
    """Gate 7's Resistance exists exactly while seven or more Gates are open."""
    held = [mid for mid, m in actor.modifiers.items() if m.source_definition_id == PREFIX + "sixth_and_seventh_gates"
            and m.target_field == "damage_resistance"]
    if open_gates(actor) >= 7 and not held:
        for kind in ALL_BUT:
            engine._add_modifier(actor, PREFIX + "sixth_and_seventh_gates", "damage_resistance", "ADD", kind, "SELF", expires_on="UNTIL_REMOVED")
    elif open_gates(actor) < 7 and held:
        for mid in held:
            del actor.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", PREFIX + "sixth_and_seventh_gates", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"modifier_id": mid, "reason": "GATES_CLOSED"})


def _ask_count(engine: Any, actor: Any, intent: Any, most: int, prompt: str, *, allow_decline: bool) -> int:
    from .needle import ask, checkpoint_id

    if most <= 0:
        return 0
    options = [str(n) for n in range(most, 0, -1)]
    picked = ask(engine, intent, checkpoint_id(engine, "eight_gates", actor.entity_id), actor, "choice:needle.eight_gates", options,
                 labels={o: f"{o} Gate{'s' if o != '1' else ''} ({o} Stamina)" for o in options}, prompt=prompt,
                 allow_decline=allow_decline, target_id=actor.entity_id)
    return int(picked[0]) if picked else 0


# ------------------------------------------------------------------------------------------------------ actions
@hook("compile_actions")
def gate_actions(info: dict[str, Any]) -> list[Any] | None:
    owned = [mid for mid in info["owned_ids"] if mid.startswith(PREFIX)]
    if not owned:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    def make(key: str, name: str, eff: str, description: str) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.eight_gates.{key}", display_name=name,
                                owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
                                parameters={"typed": {"source": SOURCE, "effects": [{"type": eff}], "numbers": info["numbers"],
                                                      "duration": {"kind": "instant"}, "riders": []},
                                            "expected_damage": 6 if key == "open" else 0, "eight_gates": key, "description": description})
    made = [make("open", "Open the Gates", "eight_gates_open",
                 "Once per scene: open any number of your unlocked Gates, 1 Stamina each. Each open Gate deals you 1d4 Force damage at the "
                 "start of your turns (1d6 while Gate 8 is open) that nothing can reduce."),
            make("close", "Close the Gates", "eight_gates_close", "Close every open Gate; they cannot reopen this scene.")]
    thunder_owned = any(int(row.get("gate") or 0) >= 5 for mid in owned for row in (info["mechanics"].get(mid) or {}).get("effects") or []
                        if isinstance(row, dict) and row.get("kind") == "eight_gates")
    if thunder_owned:
        unarmed = next((a for a in info["actions"] if ".natural." in a.source_definition_id and a.economy == EconomyKind.ACTION
                        and "#" not in a.source_definition_id), None)
        if unarmed is not None:
            made.append(unarmed.model_copy(update={
                "source_definition_id": unarmed.source_definition_id + ".gate_of_thunder", "display_name": "Gate of Thunder: extra unarmed strike",
                "economy": EconomyKind.NONE, "parameters": {**unarmed.parameters, "eight_gates": "thunder"}}))
    return made


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


@hook("candidate_allowed")
def gate_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    key = (getattr(action, "parameters", None) or {}).get("eight_gates")
    if not key:
        return None
    if key == "open":
        return None if _state(actor) is None and maximum(engine, actor) > 0 and actor.resources.get("resource:core.stamina", 0) >= 1 else False
    if key == "close":
        return None if open_gates(actor) > 0 else False
    ready = actor.turn_flags.get("_round_gate_thunder_ready") == _stamp(engine) and actor.turn_flags.get("_round_gate_thunder_used") != _stamp(engine)
    return None if open_gates(actor) >= 5 and ready else False


@effect("eight_gates_open")
def open_the_gates(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    most = min(maximum(engine, actor), int(actor.resources.get("resource:core.stamina", 0)))
    count = _ask_count(engine, actor, ctx.intent, most, f"Open the Gates: how many Gates does {actor.display_name} open (1 Stamina each)?",
                       allow_decline=False)
    if count <= 0:
        return
    engine._spend_resource(actor, "resource:core.stamina", count, SOURCE)
    _set(engine, actor, SOURCE, open=count, max=maximum(engine, actor), cl=int(ctx.numbers.get("cl") or 1), pb=int(ctx.numbers.get("pb") or 2))


@effect("eight_gates_close")
def close_the_gates(ctx: Any, row: dict[str, Any]) -> None:
    _close(ctx.engine, ctx.actor, "closed")


def _close(engine: Any, actor: Any, why: str) -> None:
    if _state(actor) is None:
        return
    _set(engine, actor, SOURCE, open=0, closed=True)
    note(engine, SOURCE, actor, f"Eight Gates: {actor.display_name}'s Gates close ({why}); they cannot reopen this scene.")


@hook("action_completed")
def attack_action_taken(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    """Gate 5: "once during each of your turns when you take the Attack action, make one additional unarmed strike"."""
    if open_gates(actor) < 5 or engine.state.current_actor_id != actor.entity_id:
        return
    action = engine.action_catalog.get(source_definition_id)
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    if action is None or str(getattr(action.economy, "value", action.economy)) != "ACTION" or not typed.get("attack_action") \
            or typed.get("reaction_attack") or typed.get("opportunity_of"):
        return
    actor.turn_flags["_round_gate_thunder_ready"] = _stamp(engine)


@hook("technique_used")
def thunder_used(ctx: Any) -> None:
    if ((ctx.action.parameters or {}).get("eight_gates")) == "thunder":
        ctx.actor.turn_flags["_round_gate_thunder_used"] = _stamp(ctx.engine)


# ----------------------------------------------------------------------------------------------- start of turn
@hook("turn_start_choice")
def gate_damage(engine: Any, actor: Any) -> None:
    count = open_gates(actor)
    if count <= 0 or not actor.active:
        return
    if actor.life_state is not None:
        _close(engine, actor, "it is down")
        return
    from ..gate2_runtime_models import DiceSpec

    sides = 6 if count >= 8 else 4
    roll = engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=0), actor_id=actor.entity_id, reason=f"DAMAGE:{SOURCE}:gates",
                              critical=False)
    engine._record_roll(roll)
    amount = max(0, int(roll.total))
    before = actor.current_hp
    actor.current_hp = max(0, before - amount)
    engine._append_event("DAMAGE_COMMITTED", SOURCE, actor_id=actor.entity_id, target_ids=(actor.entity_id,), payload={
        "rolled_or_pending_damage": amount, "reduced_to": amount, "temporary_hp_absorbed": 0, "hp_damage": before - actor.current_hp,
        "damage_type": "FORCE", "remaining_hp": actor.current_hp, "gate_damage": True})
    note(engine, SOURCE, actor, f"Eight Gates: {count} open Gate{'s' if count != 1 else ''} deal {amount} Force damage to {actor.display_name} "
         "(it cannot be reduced).")
    if actor.current_hp == 0:
        eighth = count >= 8
        _close(engine, actor, "Gate damage dropped it to 0 Hit Points")
        engine._defeat(actor, SOURCE)
        if eighth and actor.active and actor.life_state == "DYING":
            engine._set_life_state(actor, "STABLE", SOURCE)
        engine._check_victory()
        return
    if actor.concentration is not None and before > actor.current_hp:
        engine._concentration_check(actor, before - actor.current_hp)
    most = min(maximum(engine, actor) - count, int(actor.resources.get("resource:core.stamina", 0)))
    if most > 0:

        extra = _ask_count(engine, actor, getattr(engine, "_active_intent", None), most,
                           f"Eight Gates: open more Gates for {actor.display_name} (1 Stamina each, no action)?", allow_decline=True)
        if extra > 0:
            engine._spend_resource(actor, "resource:core.stamina", extra, SOURCE)
            _set(engine, actor, SOURCE, open=count + extra)


# ----------------------------------------------------------------------------------------------------- benefits
@hook("speed")
def gate_speed(engine: Any, actor: Any) -> int | None:
    count = open_gates(actor)
    if count <= 0:
        return None
    bonus = 10
    if count >= 8:
        from ..gate2_engine import Gate2Engine

        bonus += Gate2Engine._effective_speed(engine, actor) + 10  # "Speed doubles" after the Gate 1 addition
    return bonus


@hook("flight")
def heaven_gate_flight(engine: Any, actor: Any) -> dict[str, Any] | None:
    if open_gates(actor) >= 6:
        from ..movement_speeds import land_speed_grant
        return {**land_speed_grant(engine, actor), "flight_hover": 1}
    return None


def _unarmed(ctx: Any) -> bool:
    return ".natural." in ctx.source or any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                            for e in ctx.typed.get("effects") or [])


def _once(ctx: Any, key: str) -> bool:
    flag = "_round_gates_" + key
    if ctx.actor.turn_flags.get(flag) == _stamp(ctx.engine):
        return False
    ctx.actor.turn_flags[flag] = _stamp(ctx.engine)
    return True


@hook("after_hit")
def gate_hits(ctx: Any, target: Any, kind: str) -> None:
    count = open_gates(ctx.actor)
    if count < 2 or target is None or not target.active:
        return
    from .. import typed_executor
    from .needle import ask, checkpoint_id

    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    if kind == "unarmed" and _once(ctx, "blood"):
        types = [str(t).lower() for t in ((ctx.typed.get("weapon") or {}).get("damage_types") or ["bludgeoning"])]
        typed_executor.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": int(ctx.numbers.get("pb") or 2),
                                          "damage_types": types[:1], "evidence": "Gate of Blood: +Proficiency Bonus damage"}])
    if count >= 8 and target.active and _once(ctx, "heaven"):
        typed_executor.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 4, "sides": 8},
                                          "damage_types": ["force"], "evidence": "Heaven-Defying Gate: once per turn +4d8 Force"}])
    if count >= 7 and kind == "unarmed" and target.active and ctx.actor.turn_flags.get("_round_gates_tyrant") != _stamp(ctx.engine):
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "gate_tyrant", target.entity_id), ctx.actor, "choice:needle.gate_tyrant",
                     ["push", "no_reactions"], allow_decline=True, target_id=target.entity_id,
                     labels={"push": f"Push {target.display_name} 10 feet", "no_reactions": f"{target.display_name} takes no Reactions until the start of its next turn"},
                     prompt=f"Gate of the Tyrant: {ctx.action.display_name} hit {target.display_name} (once per turn).")
        if picked:
            ctx.actor.turn_flags["_round_gates_tyrant"] = _stamp(ctx.engine)
            row = {"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"} if picked[0] == "push" else \
                {"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_next_turn"}
            typed_executor.run_effects(sub, [row])


@hook("attack_mode")
def heaven_advantage(ctx: Any, target: Any) -> str | None:
    return "ADVANTAGE" if open_gates(ctx.actor) >= 8 and _unarmed(ctx) else None


@hook("ac")
def bone_gate_ac(engine: Any, target: Any) -> int | None:
    return 2 if open_gates(target) >= 4 else None


@hook("save")
def bone_gate_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if open_gates(subject) >= 4 and {"prone", "forced_movement"} & set(named or ()):
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("forced_movement_reduction")
def bone_gate_forced(ctx: Any, subject: Any) -> int | None:
    return 10 if subject is not None and open_gates(subject) >= 4 else None


@hook("ability_check_mode")
def tendon_gate_checks(engine: Any, actor: Any, ability: str, skill: Any, against: Any) -> str | None:
    return "ADVANTAGE" if open_gates(actor) >= 3 and str(ability).upper() in ("STR", "DEX") else None


@hook("resistance_ignored")
def tyrant_fists(engine: Any, kind: str, typed: dict[str, Any], source_actor_id: str | None, target: Any = None) -> bool | None:
    actor = engine.state.actors.get(str(source_actor_id or ""))
    if actor is None or open_gates(actor) < 7:
        return None
    unarmed = str((typed or {}).get("source") or "").find(".natural.") >= 0 or any(
        isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed" for e in (typed or {}).get("effects") or [])
    return True if unarmed else None


@hook("condition_attempt")
def heaven_gate_mind(ctx: Any, subject: Any, eff: dict[str, Any]) -> bool | None:
    """Gate 8: "Ordinary effects cannot Frighten, Paralyze, or Stun you" -- an effect whose source CL is lower than yours."""
    if subject is None or open_gates(subject) < 8 or str((eff or {}).get("condition") or "").lower() not in ("frightened", "paralyzed", "stunned"):
        return None
    held = _state(subject)
    return False if int(ctx.numbers.get("cl") or 1) < int((held.data or {}).get("cl") or 1) else None
