"""Stone Womb Preservation (Source, auto/lane2 2026-09-29).

"As an Action, spend 4 CP and touch a willing creature at 0 Hit Points or a willing Incapacitated creature. The target is
encased in a thin shell of source-stone until the start of your next turn. While encased, the target has Resistance to all
damage, is stable if it was dying, and cannot move or take actions. The shell ends early if the target regains Hit Points,
if you dismiss it, or if the shell is broken by damage equal to 10 + your Source key ability modifier + your Proficiency
Bonus. This talent does not restore Hit Points."

Effects of the override (authority/typed_mechanics/reviewed_final.d/auto_lane2.json): ``stone_shell`` (this module) and a
``resistance`` row for every damage type, both until the start of the caster's next turn.

- ``stone_shell`` puts "condition:typed.stone_shell" on the target (rule ``stone_shell``: Speed 0 and no actions,
  combat/rules/typed_conditions.json) with the break number in its data. The target is a willing creature that is Incapacitated
  (a condition whose rule takes its actions away) or at 0 Hit Points -- a creature the lock round's Dying/Stable states (combat/ext/
  life_state.py) keep on the map; one that has simply left it, or is dead, is out of reach -- and a Dying one is made Stable
  ("is stable if it was dying"; auto/H3 2026-09-30).
- ``event`` hook: damage that reaches the shell counts (DAMAGE_COMMITTED's ``reduced_to``, after the shell's own
  Resistance -- the shell takes it as a creature does) and breaks it once the total reaches the number; any healing
  (HEALING_APPLIED with a rise in Hit Points) ends it too. Ending it takes the condition and the Resistance it gave away.
- "Dismiss Stone Womb" (compile_actions): a free choice for the caster while one of its shells stands.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

STONE_WOMB = "tianxia.talent.source.stone_womb_preservation"
SHELL = "condition:typed.stone_shell"
TAKEN = "stone_shell_round_taken"  # "_round_": survives the turn reset (combat/ext/__init__.py)


def _typed(action: Any) -> dict[str, Any]:
    return (getattr(action, "parameters", None) or {}).get("typed") or {}


def _incapacitated(actor: Any) -> bool:
    from .. import typed_executor

    return any(row.get("no_actions") for row in typed_executor.condition_rules(actor))


def _touchable(actor: Any) -> bool:
    """"A willing creature at 0 Hit Points or a willing Incapacitated creature" (a dead creature is neither)."""
    from . import life_state

    return actor.active and not life_state.is_dead(actor) and (_incapacitated(actor) or actor.current_hp == 0)


def _shell(actor: Any) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == SHELL), None)


def end_shell(engine: Any, holder: Any, reason: str) -> None:
    shell = _shell(holder)
    if shell is None:
        return
    engine._remove_condition(holder, SHELL, shell.source_definition_id)
    for mid, modifier in list(holder.modifiers.items()):
        if modifier.source_definition_id == shell.source_definition_id and modifier.target_field == "damage_resistance":
            del holder.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", shell.source_definition_id, actor_id=shell.source_actor_id, target_ids=(holder.entity_id,),
                                 payload={"modifier_id": mid, "reason": reason})


@effect("stone_shell")
def stone_shell(ctx: Any, eff: dict[str, Any]) -> None:
    from . import life_state

    target = ctx.target or ctx.actor
    if not _touchable(target):
        ctx.rider(f"{target.display_name} is neither Incapacitated nor at 0 Hit Points: no shell.")
        return
    if life_state.stabilize(ctx.engine, target, ctx.source):
        ctx.rider(f"{target.display_name} is stable.")
    numbers = ctx.numbers
    break_at = 10 + int(numbers.get("key_mod") or 0) + int(numbers.get("pb") or 2)
    target.turn_flags[TAKEN] = 0
    ctx.engine._apply_condition(target, SHELL, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": f"Stone shell (breaks at {break_at} damage)", "break_at": break_at})


@effect("stone_shell_end")
def stone_shell_end(ctx: Any, eff: dict[str, Any]) -> None:
    for holder in list(ctx.engine.state.actors.values()):
        shell = _shell(holder)
        if shell is not None and shell.source_actor_id == ctx.actor.entity_id:
            end_shell(ctx.engine, holder, "DISMISSED")


@hook("event")
def shell_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ("DAMAGE_COMMITTED", "HEALING_APPLIED"):
        return
    for target_id in kwargs.get("target_ids") or ():
        holder = engine.state.actors.get(target_id)
        shell = _shell(holder) if holder is not None else None
        if shell is None:
            continue
        payload = kwargs.get("payload") or {}
        if event_type == "HEALING_APPLIED":
            if int(payload.get("after") or 0) > int(payload.get("before") or 0):
                end_shell(engine, holder, "HEALED")
            continue
        holder.turn_flags[TAKEN] = int(holder.turn_flags.get(TAKEN) or 0) + int(payload.get("reduced_to") or 0)
        if holder.turn_flags[TAKEN] >= int(shell.data.get("break_at") or 0):
            end_shell(engine, holder, "BROKEN")


@hook("compile_actions")
def dismiss_button(info: dict[str, Any]) -> list[Any] | None:
    if STONE_WOMB not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    typed = {"effects": [{"type": "stone_shell_end"}], "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [],
             "source": "stone_womb.dismiss"}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.stone_womb.dismiss", display_name="Dismiss Stone Womb",
                             owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                             parameters={"typed": typed, "expected_damage": 0, "player_only": True,
                                         "description": "Dismiss all Stone Womb shells you created, ending their damage resistance and their restrictions on movement and actions. Costs no action or resource points."})]


@hook("candidate_allowed")
def shell_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    source = _typed(action).get("source") if action is not None else None
    if source == "stone_womb.dismiss":
        return any((_shell(other) is not None and _shell(other).source_actor_id == actor.entity_id) for other in engine.state.actors.values())
    if source == STONE_WOMB:
        target = engine.state.actors.get((getattr(candidate, "target_ids", None) or (None,))[0] or "")
        return target is not None and _touchable(target) and _shell(target) is None
    return None
