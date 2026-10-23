"""Needle Through Ten Thousand Guards (task F, 2026-09-29). Rules text: the owner's Sphere Compendium, "The Piercing Needle"
(authority/typed_mechanics/rules_text.json TAL_FENCING_NEEDLE_THROUGH_TEN_THOUSAND_GUARDS):

  "Cost: Expend Martial Focus. Use Limit: Once per Long Rest. Move up to your Speed. This movement does not provoke Opportunity
   Attacks. During this movement, choose a number of hostile creatures no greater than your Proficiency Bonus. Each chosen creature
   must come within your melee reach at some point during the movement. Make one melee attack against each chosen creature. Each
   attack has Advantage. You may apply one different Exploit you know to each successful attack without counting those Exploits
   against your normal once-per-round limit. You cannot apply more than one Exploit to the same attack through this talent.
   Needle Through Ten Thousand Guards does not allow you to move through occupied spaces or end your movement in an illegal
   destination."

The fencer chooses the square the movement ends on (only squares a hostile comes within reach of on the way), then which of those
hostiles it attacks (up to its Proficiency Bonus); it walks the path, stops where each chosen creature first comes within reach,
attacks it there with its own melee weapon attack and Advantage, and finishes the move. The Exploit half is in
combat/ext/needle.py apply_exploit (the ``_needle_guards`` state below): not counted against the round, one per attack, each different.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from .needle import CHOICE, ask, checkpoint_id, incapacitated, melee_weapon_action, cell_id, say as _say
from .frightened_movement import path_allowed
from .rider_movement import step

NTTG = "TAL_FENCING_NEEDLE_THROUGH_TEN_THOUSAND_GUARDS"


def _path_cells(start: Any, path: Any) -> list[Any]:
    cells = [start]
    for cell in path:
        if cell != cells[-1]:
            cells.append(cell)
    return cells


def _comers(engine: Any, actor: Any, cells: list[Any], hostiles: list[Any], reach: int) -> list[tuple[int, Any]]:
    """(index of the first square on ``cells`` that has the hostile within reach, hostile), in the order they are met."""
    found: list[tuple[int, Any]] = []
    for other in hostiles:
        for index, cell in enumerate(cells):
            if engine.grid.distance_ft(cell, other.position) <= reach:
                found.append((index, other))
                break
    return sorted(found, key=lambda pair: (pair[0], pair[1].entity_id))


@effect("needle_ten_thousand")
def ten_thousand(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import Context, run_effects

    engine, actor = ctx.engine, ctx.actor
    action = melee_weapon_action(engine, actor)
    if action is None:
        _say(engine, ctx.source, actor, f"{actor.display_name} has no melee weapon attack to make with Needle Through Ten Thousand Guards.")
        return
    reach = int(getattr(action, "range_ft", None) or 5)
    found = engine.grid.reachable(actor.position, movement_ft=int(engine._effective_speed(actor)),
                                  occupied_cells=engine._occupied_cells_except(actor.entity_id),
                                  difficult_cells=engine._hostile_difficult_cells(actor), footprint=engine._footprint(actor))
    found[actor.position] = ((), 0)  # "up to your Speed": staying where you are is allowed
    hostiles = [other for other in engine.state.actors.values() if other.active and other.team_id != actor.team_id and other.entity_id != actor.entity_id]
    limit = max(1, int(actor.proficiency_bonus))
    routes: dict[str, tuple[Any, list[Any], list[tuple[int, Any]], int]] = {}
    for destination, (path, cost) in found.items():
        cells = _path_cells(actor.position, path)
        if not path_allowed(engine, actor, cells):
            continue
        met = _comers(engine, actor, cells, hostiles, reach)
        if met:
            routes[cell_id(destination)] = (destination, cells, met, int(cost))
    if not routes:
        _say(engine, ctx.source, actor, f"{actor.display_name} has no hostile creature to come within reach of on the way (Needle Through Ten Thousand Guards).")
        return
    ordered = sorted(routes, key=lambda cid: (-min(limit, len(routes[cid][2])), routes[cid][3], routes[cid][0].y, routes[cid][0].x))[:49]
    labels = {cid: f"{'Stay put' if not routes[cid][3] else 'Move to ' + str(routes[cid][0].x) + ',' + str(routes[cid][0].y) + ' (' + str(routes[cid][3]) + ' ft)'}: "
                   f"{', '.join(o.display_name for _i, o in routes[cid][2][:limit])} in reach" for cid in ordered}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "GUARDS_PATH", actor.entity_id), actor, CHOICE + "guards_path", ordered, labels=labels,
                 preferred=ordered[:1], automatic=False, prompt="Needle Through Ten Thousand Guards: where does the movement end?", target_id=actor.entity_id)
    destination_id = picked[0] if picked and picked[0] in routes else ordered[0]
    destination, cells, met, _cost = routes[destination_id]
    by_id = {other.entity_id: (index, other) for index, other in met}
    target_labels = {other.entity_id: f"{other.display_name} (met {engine.grid.distance_ft(actor.position, cells[index]) if index else 0} ft along)" for index, other in met}
    chosen_ids = ask(engine, ctx.intent, checkpoint_id(engine, "GUARDS_TARGETS", actor.entity_id), actor, CHOICE + "guards_targets",
                     [other.entity_id for _i, other in met], labels=target_labels, preferred=[other.entity_id for _i, other in met][:limit],
                     minimum=1, maximum=min(limit, len(met)), automatic=False, target_id=actor.entity_id,
                     prompt=f"Needle Through Ten Thousand Guards: attack up to {limit} of them")
    chosen = [by_id[i] for i in chosen_ids if i in by_id][:limit] or list(met[:limit])
    _say(engine, ctx.source, actor, f"{actor.display_name} slips through the guards toward {destination.x},{destination.y}: "
                                    f"{', '.join(other.display_name for _i, other in chosen)}.")
    typed = copy.deepcopy((action.parameters or {}).get("typed") or {})
    if typed.get("effects"):
        typed["effects"][0]["count"] = 1  # "one melee attack against each chosen creature"
    typed.pop("opens", None)
    previous = getattr(engine, "_needle_guards", None)
    engine._needle_guards = {"actor": actor.entity_id, "target": None, "used": []}
    try:
        # This is physical movement, not Needle's teleport-style step_to.
        # Follow every square with entry effects, stopping on changed occupancy,
        # immobilization or displacement; never attack at an unreached position.
        for index, cell in enumerate(cells):
            if not actor.active or incapacitated(actor) or engine.state.terminal_result is not None:
                break
            if index:
                if actor.position != cells[index - 1] or engine._effective_speed(actor) <= 0:
                    break
                if not engine.grid.step_legal(actor.position, cell,
                        occupied_cells=engine._occupied_cells_except(actor.entity_id), footprint=engine._footprint(actor)):
                    break
                step(engine, actor, [actor.position, cell], ctx.source)
            if actor.position != cell or not actor.active or incapacitated(actor) or engine.state.terminal_result is not None:
                break
            for attack_index, other in sorted(chosen, key=lambda pair: (pair[0], pair[1].entity_id)):
                if actor.position != cell or not actor.active or incapacitated(actor) or engine.state.terminal_result is not None:
                    break
                if attack_index != index or not other.active or engine.grid.distance_ft(actor.position, other.position) > reach:
                    continue
                engine._needle_guards["target"] = other.entity_id
                run_effects(Context(engine, actor, action, ctx.intent, typed, [other], other), copy.deepcopy(typed.get("effects") or []))
    finally:
        engine._needle_guards = previous


@hook("attack_mode")
def guards_advantage(ctx: Any, target: Any) -> str | None:
    """"Each attack has Advantage.\""""
    state = getattr(ctx.engine, "_needle_guards", None)
    if state and state.get("actor") == ctx.actor.entity_id and target is not None and state.get("target") == target.entity_id:
        return "ADVANTAGE"
    return None
