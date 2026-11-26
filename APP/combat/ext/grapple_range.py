"""End range-limited grapples when movement separates either participant.

Uses the saved condition's integer reach and the engine's footprint distance.
Only typed Grappled/Pinned rows carrying reach opt in; unrelated restraints
and legacy conditions without range data are inert. The existing nested event
hook covers typed pushes, pulls and movement inside other plug-ins. A grip lost because the held creature itself was moved
(pushed, pulled, teleported) is reported as an escape (combat/ext/hold_escapes.py).
"""
from . import hook


@hook("event", nested=True)
def moved_out_of_reach(engine, event_type, kwargs):
    if event_type != "MOVEMENT_COMMITTED":
        return
    moved = kwargs.get("actor_id")
    for target in engine.state.actors.values():
        for iid, held in list(target.conditions.items()):
            if held.condition_id not in ("condition:typed.grappled", "condition:typed.pinned"):
                continue
            reach = (held.data or {}).get("reach_ft")
            if type(reach) is not int or reach < 0 or moved not in (target.entity_id, held.source_actor_id):
                continue
            source = engine.state.actors.get(held.source_actor_id)
            if source is None or engine._distance_actor_to_actor(source, target) <= reach:
                continue
            del target.conditions[iid]
            engine._append_event("CONDITION_REMOVED", held.source_definition_id,
                                 actor_id=held.source_actor_id, target_ids=(target.entity_id,),
                                 payload={"instance_id": iid, "condition_id": held.condition_id,
                                          "reason": "OUT_OF_REACH"})
            if moved == target.entity_id:  # the held creature was moved out: an escape (combat/ext/hold_escapes.py)
                from .hold_escapes import escaped, movement_how

                escaped(engine, target, [held], movement_how(kwargs.get("payload")), source=held.source_definition_id,
                        way="movement")
