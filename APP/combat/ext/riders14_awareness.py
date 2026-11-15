"""Hidden Eye's single-roll Thousand-Lantern Search (lane 14).

Uses existing Hidden/Stealth totals, actual senses, grid line of sight, and
placed traps' save DC/awareness records. Unrepresented hidden objects, remote
sensors and the magical classification of arbitrary effects remain GM riders.
No zone, duplicate Search rolls or invented detection DC is created.
"""
from __future__ import annotations

import json
from typing import Any

from . import effect, hook, floored
from .eye_common import FOCUS, numbers_of, skill
from .riders14_eye import has
from .condition_events import drop_condition as _drop

PERCEPTION = "condition:typed.eye_cooperative_perception"


@hook("event")
def cooperative_perception(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    roll = payload.get("actor") or {}
    if event_type != "CHECK_ROLLED" or not roll or not (payload.get("check") == "Perception"
            or str(roll.get("reason") or "").endswith("analyze:perception")) or payload.get("same_search"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    intent = getattr(engine, "_active_intent", None)
    if actor is None or intent is None or not has(engine, actor, "cooperative_perception") or actor.resources.get(FOCUS, 0) < 1:
        return
    totals = payload.get("observation_totals") or {
        tid: int(roll["total"]) for tid in kwargs.get("target_ids", ()) if tid in engine.state.actors}
    if not totals:
        engine._append_event("GM_RIDER", "passive:eye.cooperative_perception", actor_id=actor.entity_id,
                             payload={"rider": "Cooperative Perception: the triggering observation has no represented scope; qualify sharing with the GM."})
        return
    from .needle import CHOICE, ask, checkpoint_id
    from ..typed_executor import clock_expiry

    options = [a.entity_id for a in engine.state.actors.values() if a.active and a.team_id == actor.team_id
               and a.entity_id != actor.entity_id and engine._distance_actor_to_actor(actor, a) <= 60]
    if not options:
        return
    observation = ", ".join(engine.state.actors[tid].display_name for tid in totals if tid in engine.state.actors)
    trigger = "Analyze (Perception)" if str(roll.get("reason") or "").endswith("analyze:perception") else "Perception check"
    selected = ask(engine, intent, checkpoint_id(engine, "EYE_COOPERATIVE_PERCEPTION", actor.entity_id, str(roll.get("counter_start"))), actor,
        CHOICE + "eye_cooperative_perception", options, maximum=min(len(options), int(numbers_of(engine, actor).get("pb") or 2)),
        allow_decline=True, automatic=False, labels={aid: engine.state.actors[aid].display_name for aid in options},
        prompt=f"Cooperative Perception after {actor.display_name}'s {trigger} observing {observation}: share this result with allies (expend Martial Focus)?")
    if not selected:
        return
    engine._spend_resource(actor, FOCUS, 1, "passive:eye.cooperative_perception")
    for other in engine.state.actors.values():
        for iid, old in list(other.conditions.items()):
            if old.condition_id == PERCEPTION and old.source_actor_id == actor.entity_id:
                _drop(engine, other, iid, "passive:eye.cooperative_perception")
    for tid in selected:
        engine._apply_condition(engine.state.actors[tid], PERCEPTION, "passive:eye.cooperative_perception", actor.entity_id,
            expires_on=clock_expiry(engine, "hours", 1), data={"total": int(roll["total"]),
                "observation_source": str(kwargs.get("source_definition_id") or roll.get("reason") or ""),
                "observation_roll": str(roll.get("roll_id") or ""),
                "observation_totals": json.dumps(totals, sort_keys=True)})


@hook("passive_perception_override")
def shared_passive(engine: Any, actor: Any, observed: Any, baseline: int) -> int | None:
    if observed is None:
        return None  # never share an unqualified sense or sight through cover
    from .. import stealth

    values = []
    for condition in actor.conditions.values():
        if condition.condition_id != PERCEPTION:
            continue
        totals = json.loads(condition.data.get("observation_totals") or "{}")
        if observed.entity_id not in totals:
            continue
        owner = engine.state.actors.get(condition.source_actor_id)
        if owner and owner.active and engine._distance_actor_to_actor(owner, actor) <= 60 \
                and stealth.sees(engine, owner, observed) and stealth.sees(engine, actor, observed):
            values.append(int(totals[observed.entity_id]))
    return max([baseline, *values]) if values else None


@effect("eye_lantern_search")
def lantern_search(ctx: Any, rule: dict[str, Any]) -> None:
    from .. import stealth, senses
    from . import placed

    engine, actor = ctx.engine, ctx.actor
    targets = [foe for foe in stealth.foes(engine, actor) if stealth.hidden(foe) is not None
               and engine._distance_actor_to_actor(actor, foe) <= 120
               and engine._line_of_sight_actor_to_cell(actor, foe.position)]
    own_mode = stealth.resolved_search_mode(engine, actor)
    target_modes = {}
    for foe in targets:
        # Sense-only discovery needs no check and opens no check reaction.
        modes = (stealth.search_modes(engine, actor, foe) if senses.finds(engine, actor, foe)
                 else stealth.pending_search_modes(engine, actor, foe, ctx.source))
        target_modes[foe.entity_id] = next(iter(modes)) if len(modes) == 1 else "NORMAL"
    # One check's dice cover all qualified modes. Draw a second die only if a
    # non-normal view needs it; normal targets always use the first die.
    draw_mode = next((mode for mode in [own_mode, *target_modes.values()] if mode != "NORMAL"), "NORMAL")
    shared = engine.roller.d20(modifier=skill(engine, actor, "Perception", actor.saving_throws.get("WIS", 0)),
        actor_id=actor.entity_id, reason=f"CHECK:{ctx.source}:LANTERN", mode=draw_mode)
    engine._record_roll(shared)
    roll = floored(engine, actor, stealth.search_roll_view(shared, own_mode))
    views = {foe.entity_id: floored(engine, actor, stealth.search_roll_view(shared, target_modes[foe.entity_id]))
             for foe in targets}
    engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(),
                         payload={"actor": roll.model_dump(mode="json"), "check": "Perception", "skill": "Perception", "lantern_search": True,
                                  "observation_totals": {tid: view.total for tid, view in views.items()}})
    for foe in targets:
        iid = stealth.hidden(foe)
        dc = int((foe.conditions[iid].data or {}).get("stealth_total") or stealth.HIDE_DC)
        view = views[foe.entity_id]
        found = senses.finds(engine, actor, foe) or view.total >= dc
        engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(foe.entity_id,),
            payload={"actor": view.model_dump(mode="json"), "check": "Perception", "skill": "Perception", "dc": dc, "success": found, "same_search": True})
        if found:
            stealth.reveal(engine, foe, ctx.source, "Thousand-Lantern Sweep")
    for zone in placed.of(engine, "trap"):
        data = placed.data(zone)
        if zone.owner_id == actor.entity_id or data.get("shield") or actor.entity_id in (data.get("aware") or ()) \
                or engine.grid.distance_ft(actor.position, zone.center) > 120 or not engine._line_of_sight_actor_to_cell(actor, zone.center):
            continue
        dc = int((zone.trigger_profile.get("numbers") or {}).get("save_dc") or 10)
        found = roll.total >= dc
        engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(),
            payload={"actor": roll.model_dump(mode="json"), "check": "Perception", "skill": "Perception", "dc": dc, "success": found,
                     "same_search": True, "zone_id": zone.zone_id})
        if found:
            placed.update(engine, zone, aware=[*(data.get("aware") or ()), actor.entity_id])
