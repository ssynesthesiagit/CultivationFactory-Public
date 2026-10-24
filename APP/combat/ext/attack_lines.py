"""Shared helper module (consumers: still_water.py, sun_bow.py, white_heron.py). An Attack action that spends some of its attacks on a line (rider
lane C7, 2026-09-30): One Breath, Three Horizons ("When you take the Attack action, replace two attacks with a line") and
Sun-Chasing Line ("When you take the Attack action with a Bow, replace one attack with a line").

``line_variants(info, mechanic_id, bases, replace=, area=, stamina=, name=, move=)`` builds, for each base weapon action whose
Attack action has at least ``replace`` attacks, "<name> (<weapon>)": aimed at a square (CELL) within the line's length, costing the
base action's costs plus ``stamina``, whose effects are the mechanic's own reviewed save row (a ``dice.weapon`` die becomes the
weapon's die) followed by ``attack_line_after``. The variant's typed ``source`` is the mechanic, so object rows keyed on it
(combat/ext/objects.py technique rows) apply; it is not an attack and has no weapon, so no attack-hit rider fires.

``attack_line_after`` {"remaining": n, "move": "half_speed_beside_line" | None, "name": str}: the once-per-turn mark, then the
asked move (One Breath: "move to any unoccupied space adjacent to it without provoking, up to half your Speed"), then the
Attack action's remaining attacks, each against a creature the player picks (declining ends them). ``candidate_allowed`` keeps
each mechanic's variants to once per turn ("across additional Attack actions").
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

STAMINA = "resource:core.stamina"


def _stamp(engine: Any, mechanic: str | None = None) -> str:
    from . import query
    replies=query('attack_line_turn_key',engine,engine.state.actors[engine.state.current_actor_id],mechanic) if mechanic else []
    if replies:
        if len(replies)!=1 or type(replies[0]) is not str or not replies[0]:
            raise ValueError('One source must supply a nonempty attack-line turn key')
        return replies[0]
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def line_variants(info: dict[str, Any], mechanic_id: str, bases: list[Any], *, replace: int, area: dict[str, Any] | None, stamina: int, name: str,
                  move: str | None = None, lead: str | None = None) -> list[Any]:
    """``lead``: a plug-in effect type that runs the save row itself ({"type": lead, "save": <row>}) -- a sweep around its user
    (Crescent Reaping Circle), aimed at nothing (SELF) when ``area`` is None -- instead of the save row over an aimed area."""
    from ..gate2_runtime_models import EconomyKind

    save_row = next((e for e in (info["mechanics"].get(mechanic_id) or {}).get("effects") or [] if isinstance(e, dict) and e.get("type") == "save"), None)
    if save_row is None:
        return []
    out = []
    for base in sorted(bases, key=lambda a: a.source_definition_id):
        typed = (base.parameters or {}).get("typed") or {}
        attack = next((e for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
        if "#" in base.source_definition_id or base.economy != EconomyKind.ACTION or attack is None:
            continue
        count = int(attack.get("count") or 1)
        if count < replace:
            continue  # "You must have at least two attacks available in the current Attack action"
        line = copy.deepcopy(save_row)
        sides = int(((typed.get("weapon") or {}).get("damage") or {}).get("sides") or 4)
        for row in [*(line.get("on_fail") or []), *(line.get("on_success") or [])]:
            dice = row.get("dice") if isinstance(row, dict) else None
            if isinstance(dice, dict) and dice.get("weapon"):
                row["dice"] = {"count": int(dice.get("count") or 1), "sides": sides}
        first = {"type": lead, "save": line, "reach_ft": int(base.range_ft or 5)} if lead else line
        variant = {"source": mechanic_id, "attack_line_of": base.source_definition_id, "numbers": {**info["numbers"], **(typed.get("numbers") or {}),
                                                                                                 "save_dc": info["numbers"].get("save_dc")},
                   "duration": {"kind": "instant"}, "riders": [], **({"area": dict(area)} if area else {}),
                   "effects": [first, {"type": "attack_line_after", "remaining": count - replace, "move": move, "name": name, "mechanic": mechanic_id}]}
        out.append(base.model_copy(update={
            "source_definition_id": base.source_definition_id + "#line." + mechanic_id.rsplit(".", 1)[-1],
            "display_name": f"{name} ({base.display_name.removesuffix(' attack')})", "target_kind": "CELL" if area else "SELF",
            "range_ft": int(area.get("size_ft") or 30) if area else None,
            "radius_ft": None, "costs": (*base.costs, (STAMINA, stamina)),
            "parameters": {**{k: v for k, v in base.parameters.items() if k != "typed"}, "typed": variant, "attack_line": mechanic_id}}))
    return out


@hook("candidate_allowed")
def attack_line_once(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    mechanic = (getattr(action, "parameters", None) or {}).get("attack_line")
    if mechanic and actor.turn_flags.get(f"_round_attack_line:{mechanic}") == _stamp(engine,mechanic):
        return False  # "Limit: Once per turn"
    return None


@effect("attack_line_after")
def attack_line_after(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from ..gate2_runtime_models import Position
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    engine, actor = ctx.engine, ctx.actor
    name = str(row.get("name") or ctx.action.display_name)
    claim_line(engine,actor,str(row.get('mechanic') or ''))
    aim = ctx.typed.get("_area_aim")
    if row.get("move") == "half_speed_beside_line" and aim is not None and actor.active:
        cells = te.area_cells(engine, actor.position, Position(x=aim[0], y=aim[1]), ctx.typed.get("area") or {})
        paths = {k: p for k, p in routes(engine, actor, int(engine._effective_speed(actor)) // 2).items()
                 if any(engine.grid.distance_ft(p[-1], cell) <= engine.grid.square_size_ft for cell in cells)}
        if paths:
            picked = ask(engine, ctx.intent, checkpoint_id(engine, "attack_line_move", actor.entity_id), actor, "choice:needle.attack_line_move", sorted(paths),
                         allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=actor.entity_id,
                         name=name, prompt=f"{name}: move up to half your Speed without provoking, to a space beside the line?")
            if picked and picked[0] in paths:
                step(engine, actor, paths[picked[0]], str(row.get("mechanic") or ctx.source))
    base_id = str(ctx.typed.get("attack_line_of") or "")
    choices = {k: engine.action_catalog[k] for k in (base_id, base_id + "#integrated_con", base_id + "#integrated_dex") if k in engine.action_catalog}
    if not choices or int(row.get("remaining") or 0) < 1:
        return
    key = next(iter(choices))
    if len(choices) > 1:  # the weapon's own attack or its integrated "(Constitution)" / "(Dexterity)" one
        preferred = [k for k in choices if k.endswith("#integrated_con")] or [key]
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "attack_line_weapon", actor.entity_id), actor, "choice:needle.attack_line_weapon", list(choices),
                     labels={k: a.display_name for k, a in choices.items()}, preferred=preferred, target_id=actor.entity_id, name=name,
                     prompt=f"{name}: which attack for the Attack action's remaining attacks?")
        key = picked[0] if picked and picked[0] in choices else preferred[0]
    base = choices[key]
    typed = (base.parameters or {}).get("typed") or {}
    attack = next((copy.deepcopy(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
    if attack is None:
        return
    attack["count"] = 1
    reach = max(int(base.range_ft or 5), int(typed.get("long_range_ft") or 0))
    for index in range(int(row.get("remaining") or 0)):
        if not actor.active or engine.state.terminal_result is not None:
            return
        foes = {c.entity_id: c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and c.team_id != actor.team_id
                and engine._distance_actor_to_actor(actor, c) <= reach and engine._line_of_sight_actor_to_actor(actor, c)}
        if not foes:
            return
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "attack_line_attack", str(index)), actor, "choice:needle.attack_line_attack", list(foes),
                     labels={k: c.display_name for k, c in foes.items()}, allow_decline=True, target_id=actor.entity_id, name=name,
                     prompt=f"{name}: your Attack action's remaining attack {index + 1} of {row.get('remaining')}. Attack whom?")
        if not picked or picked[0] not in foes:
            return
        foe = foes[picked[0]]
        te.run_effects(te.Context(engine, actor, base, ctx.intent, {**typed, "effects": [attack]}, [foe], foe, {}), [attack])


def claim_line(engine,actor,mechanic):
    """Record an accepted source replacement before its nested effects resolve."""
    actor.turn_flags[f'_round_attack_line:{mechanic}']=_stamp(engine,mechanic)
