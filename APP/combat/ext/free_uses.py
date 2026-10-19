"""Use an ability "without an action" while a talent's state is on (rider lane 1, 2026-09-29: "i want everything we can automated").

"Once on each of your turns, you may use Gather Charge without an action" (Court of Charged Paths), "... Lightning Lash or Gather
Charge without an action" (Lightning Sovereign Incarnation): a free copy of the ability that is offered while the state is running
and once used is gone for the turn (or the round).  It is declared on the talent's own ``state`` effect (combat/ext/states.py):

  {"type": "state", "name": "court_of_charged_paths", "duration": "one_minute",
   "free_use": [{"of": ["Gather Charge"], "once": "turn"}]}          # "once": "turn" (default) or "round"

A declaration may add ``"costless": true`` (the copy costs nothing) and ``"keep_economy": true`` (the copy keeps the ability's own
Action/Bonus Action) for "use Empty Step once per turn without spending CP or Stamina" (rider lane C4: Void's Court of the Empty
Horizon and Void-Sovereign Incarnation); such a copy is named "... (no cost)". Without them a copy is as before.

At compile time each named ability of the character (an option of a choose-one ability, "Lightning Lash: Arc", counts as that
ability) gets a sibling action with no economy ("... (free)") that costs what the ability costs and does what it does.  Every
sibling of one declaration shares its one use; it is offered only while ``states.active`` says the state is on
(``candidate_allowed``), and ``technique_used`` spends the use.
"""

from __future__ import annotations

from typing import Any

from . import hook


def _declarations(info: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key in info["owned_ids"]:
        mechanic = info["mechanics"].get(key) or {}
        rows = [*(mechanic.get("effects") or []), *(row for option in mechanic.get("options") or [] for row in option.get("effects") or [])]
        for row in rows:
            if isinstance(row, dict) and row.get("type") == "state" and row.get("free_use"):
                out.extend({"state": str(row["name"]), "mechanic": key, "range_for": row.get("range_for") or {}, **spec}
                           for spec in row["free_use"])
    return out


@hook("compile_actions")
def _free_copies(info: dict[str, Any]) -> list[Any] | None:
    declared = _declarations(info)
    if not declared:
        return None
    from ..gate2_runtime_models import EconomyKind

    made = []
    for index, spec in enumerate(declared):
        wanted = [str(name) for name in spec.get("of") or []]
        for action in info["actions"]:
            name = str(action.display_name)
            if action.economy == EconomyKind.NONE or not any(name == want or name.startswith(want + ":") for want in wanted):
                continue
            typed = dict((action.parameters or {}).get("typed") or {})
            feet = spec["range_for"].get(typed.get("source"))
            if feet is not None:
                typed["range_ft"] = int(feet)
            # "without spending CP or Stamina" (Void's Empty Step in a Court or Incarnation): the same economy, no cost.
            costless, keep = bool(spec.get("costless")), bool(spec.get("keep_economy"))
            made.append(action.model_copy(update={
                "source_definition_id": f"{action.source_definition_id}+free{index}",
                "display_name": f"{name} ({'no cost' if costless and keep else 'free'})",
                "economy": action.economy if keep else EconomyKind.NONE, **({"costs": ()} if costless else {}),
                "range_ft": int(feet) if feet is not None else action.range_ft,
                "parameters": {**action.parameters, "typed": typed, "free_use": {"state": spec["state"], "once": spec.get("once") or "turn",
                                                                                 "key": f"{spec['mechanic']}:{index}"},
                               **({"state_range_rule": {"state": spec["state"]}} if feet is not None else {})}}))
    return made or None


def _flag(engine: Any, rule: dict[str, Any]) -> str:
    return f"free_use_{rule['key']}" + (f"_round_{engine.state.round_number}" if rule["once"] == "round" else "")


@hook("candidate_allowed")
def _offered_while_the_state_lasts(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    rule = ((action.parameters or {}).get("free_use") if action is not None else None)
    if not rule:
        return None
    from . import states

    return False if states.active(engine, actor, rule["state"]) is None or actor.turn_flags.get(_flag(engine, rule)) else None


@hook("technique_used")
def _spend_the_free_use(ctx: Any) -> None:
    rule = (ctx.action.parameters or {}).get("free_use")
    if rule:
        ctx.actor.turn_flags[_flag(ctx.engine, rule)] = True
