"""Talents that let two of a kind apply at once, for Martial Focus (docket 2026-09-28; owner 2026-09-28: "'apply two X
talents' allowances (Skewer, Two Currents Meet, Double Dip, Greater Deflect, Layered Bouquet)").

  Skewer        "When you apply an Exploit to an attack, you may expend Martial Focus to apply two different Exploits you
                know to that attack instead of one": "Skewer: also <Exploit>" (free, player only) names the second; when
                an Exploit lands (combat/ext/needle.py apply_exploit) and the second is a different one, Martial Focus
                is expended and it lands too
  Double Dip    "When you succeed on Dirty Trick, expend Martial Focus to choose two different Dirty Trick effects instead
                of one": "Double Dip: also <effect>" names the second; a successful Dirty Trick with a different effect
                expends Martial Focus and adds it
Layered Bouquet is a pair of Fragrance shapes (combat/factory_compiler.py _zone_shapes). Greater Deflect waits for Shield
Active Defense, Two Currents Meet for Flowing Response's own Response choice (combat/ext/flowing_river.py) -- other workers'.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

FOCUS = "resource:core.martial_focus"
SKEWER, DOUBLE_DIP = "condition:typed.skewer_pick", "condition:typed.double_dip_pick"
SKEWER_ID, DOUBLE_DIP_ID, DIRTY_TRICK = "TAL_FENCING_SKEWER", "TAL_SCOUNDREL_DOUBLE_DIP", "TAL_SCOUNDREL_DIRTY_TRICK"


# ------------------------------------------------------------------------------------------------ the picks
def _pick(ctx: Any, condition_id: str, value: str | None, label: str) -> None:
    for iid, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id == condition_id:
            ctx.actor.conditions.pop(iid)
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": iid})
    if value:
        ctx.engine._apply_condition(ctx.actor, condition_id, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"pick": value, "label": label})


@effect("pick_second")
def pick_second(ctx: Any, eff: dict[str, Any]) -> None:
    _pick(ctx, str(eff["condition"]), eff.get("pick"), str(eff.get("label") or ""))


def _picked(actor: Any, condition_id: str) -> str | None:
    return next((str((condition.data or {}).get("pick")) for condition in actor.conditions.values() if condition.condition_id == condition_id), None)


def _toggles(info: dict[str, Any], key: str, condition_id: str, talent: str, rows: list[tuple[str, str]]) -> list[Any]:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    out = []
    for value, name in [*rows, (None, None)]:
        label = f"{talent}: also {name}" if value else f"{talent}: off"
        slug = (value or "off").split(".")[-1].split("#")[-1].lower()
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.{key}.{slug}", display_name=label, owner_id=info["actor_id"],
            economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"setting_only": True, "typed": {"effects": [{"type": "pick_second", "condition": condition_id, "pick": value, "label": label}],
                                  "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                        "expected_damage": 0, "player_only": True, "second_pick": condition_id, "second_value": value}))
    return out


@hook("compile_actions")
def allowance_toggles(info: dict[str, Any]) -> list[Any] | None:
    owned, out = info["owned_ids"], []
    if SKEWER_ID in owned:
        exploits = next((row.get("options") or [] for row in info.get("passives") or [] if row.get("block") == "exploits"), [])
        if len(exploits) >= 2:
            out += _toggles(info, "skewer", SKEWER, "Skewer", [(row["name"], row["name"]) for row in exploits])
    if DOUBLE_DIP_ID in owned:
        labels = [option.get("label") for option in (info["mechanics"].get(DIRTY_TRICK) or {}).get("options") or [] if option.get("label")]
        if len(labels) >= 2:
            out += _toggles(info, "double_dip", DOUBLE_DIP, "Double Dip", [(label, label) for label in labels])
    return out or None


@hook("candidate_allowed")
def allowance_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    parameters = getattr(action, "parameters", None) or {}
    if not parameters.get("second_pick"):
        return None
    return False if _picked(actor, parameters["second_pick"]) == parameters.get("second_value") else None


# ------------------------------------------------------------------------------------------------ Skewer
# The second Exploit itself (Martial Focus, "two different", Court's free second) is applied where the first is: combat/ext/needle.py
# apply_exploit reads this talent's standing pick above.


# ------------------------------------------------------------------------------------------------ Double Dip
@hook("technique_used")
def double_dip(ctx: Any) -> None:
    typed = ctx.typed or {}
    if str(typed.get("option_of") or "") != DIRTY_TRICK and str(typed.get("source") or "") != DIRTY_TRICK:
        return
    second = _picked(ctx.actor, DOUBLE_DIP)
    used = str(typed.get("option_label") or "")
    target = ctx.target or next(iter(ctx.targets or []), None)
    if not second or second == used or target is None or not target.active or ctx.actor.resources.get(FOCUS, 0) < 1:
        return
    engine = ctx.engine
    check = next((event for event in reversed(engine.events[-30:]) if event.event_type == "CHECK_ROLLED" and event.actor_id == ctx.actor.entity_id
                  and event.source_definition_id == ctx.source), None)
    if check is None or not (check.payload or {}).get("success"):
        return
    from .. import typed_executor

    option = next((row for row in (ctx.engine.action_catalog.values()) if row.owner_id == ctx.actor.entity_id
                   and ((row.parameters or {}).get("typed") or {}).get("option_of") == DIRTY_TRICK
                   and ((row.parameters or {}).get("typed") or {}).get("option_label") == second), None)
    effects = next((e.get("on_success") for e in ((option.parameters or {}).get("typed") or {}).get("effects") or []
                    if isinstance(e, dict) and e.get("type") == "scoundrel_check"), None) if option is not None else None
    if not effects:
        return
    engine._spend_resource(ctx.actor, FOCUS, 1, ctx.source)
    ctx.rider(f"Double Dip: {second} as well")
    typed_executor.run_effects(typed_executor.Context(engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, {}),
                               copy.deepcopy(effects))
