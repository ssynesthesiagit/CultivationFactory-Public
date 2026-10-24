"""Keep a Concentration area without Concentration after making it (rider lane C10, 2026-09-30).

Several base abilities print the same augment for the area they leave on the map, e.g. Ashfall's:
  "Lingering Ashfall - Augment - 2 CP: Ashfall persists for its remaining duration without Concentration. You may apply this
   augment after creating Ashfall on your turn without spending an Action."
(Conflagration, Darkness, Dreamscape, Fragrance, Turbulent Field print the same shape.)

How it runs, for each ability listed in LINGERING (its record id -> the augment's name and CP cost, from its printed line):
  * The owner has a free action "<augment name> (<n> CP)", offered on its own turn while one of its areas from that ability is
    still held by its Concentration (combat/zones.py places the area; concentration_link ties it to the Concentration).
  * Using it pays the CP (the character's Path resource), asks which area when there are two or more, and lets that area go on
    for the rest of its duration: the area is re-recorded without the Concentration link (a ZONE_CREATED re-record, like
    combat/ext/placed.py's update), and the Concentration that held it ends through the engine's
    shared copy-ending path for current and held copies. Its area stays; everything else the
    Concentration kept ends as it would.
Choosing the augment when the area is made is the same thing done at once (the action is free on that same turn).
Only characters with a listed ability get the action; nothing changes for anyone else. To reuse this for another ability with the
same printed augment, add its record id to LINGERING (one implementation per ability: Create Figment and Revitalizing Thread have
their own in figment.py and life_riders.py).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

LINGERING = {
    "ASH_BASE_ASHFALL": {"name": "Lingering Ashfall", "cost": 2, "area": "Ashfall"},
}
KEY = "lingering_area"


def _technique(engine: Any, source_id: str) -> str:
    action = engine.action_catalog.get(str(source_id))
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    return str(typed.get("option_of") or typed.get("source") or "")


def held_areas(engine: Any, actor: Any, record: str) -> list[Any]:
    """This actor's areas from ``record`` that its Concentration still holds."""
    return [zone for _key, zone in sorted(engine.state.zones.items()) if zone.active and zone.owner_id == actor.entity_id
            and zone.concentration_link and _technique(engine, zone.source_definition_id) == record]


@hook("compile_actions")
def actions(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    made = []
    # The area itself (zone_spec) is written after this hook runs (factory_compiler._zone_abilities): the ability's own action is enough.
    have = {str(((row.parameters or {}).get("typed") or {}).get("source") or "") for row in info.get("actions") or []}
    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
    for record, rule in LINGERING.items():
        if record not in (info.get("owned_ids") or []) or record not in have:
            continue
        typed = {"effects": [{"type": "linger_area", "record": record,
                              "evidence": f"{rule['name']}: {rule['area']} persists for its remaining duration without Concentration."}],
                 "numbers": dict(info["numbers"]), "duration": {"kind": "instant"}, "riders": [], "coverage": "FULL",
                 "source": f"{KEY}:{record}"}  # not the record itself: the compiler would give this action the record's area
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.{KEY}.{record}", display_name=f"{rule['name']} ({rule['cost']} CP)",
            owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            costs=((pool, int(rule["cost"])),),
            parameters={"typed": typed, "expected_damage": 0, "player_only": True, KEY: record,
                        "description": (f"On your turn, without using an action, spend {rule['cost']} cultivation points: your "
                                        f"{rule['area']} stays for the rest of its duration without your Concentration.")}))
    return made or None


@hook("candidate_allowed")
def offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    record = ((getattr(action, "parameters", None) or {}).get(KEY)) if action is not None else None
    if not record:
        return None
    return None if engine.state.current_actor_id == actor.entity_id and held_areas(engine, actor, record) else False


def _release(engine: Any, actor: Any, zone: Any, source: str) -> None:
    """End the Concentration that holds ``zone`` without ending the zone."""
    from .. import concentration

    current = actor.concentration
    if current is not None and current.zone_id == zone.zone_id:
        concentration.end_copy(engine, actor, current.started_sequence, "LINGERING", retain_zone=True)
        return
    for _instance_id, state in concentration.held(actor):
        if state.zone_id != zone.zone_id:
            continue
        concentration.end_copy(engine, actor, state.started_sequence, "LINGERING", retain_zone=True)
        return


@effect("linger_area")
def linger(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import CHOICE, ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    record = str(row.get("record") or "")
    rule = LINGERING.get(record) or {"name": "Lingering area", "area": "area"}
    zones = held_areas(engine, actor, record)
    if not zones:
        return
    zone = zones[0]
    if len(zones) > 1:
        labels = {z.zone_id: f"{rule['area']} centred at ({z.center.x}, {z.center.y})" for z in zones}
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "LINGER", actor.entity_id), actor, CHOICE + KEY, list(labels),
                     labels=labels, name=rule["name"], feature_id=record,
                     prompt=f"{rule['name']}: which of {actor.display_name}'s areas stays without Concentration?")
        zone = next((z for z in zones if z.zone_id in picked), zone)
    _release(engine, actor, zone, ctx.source)
    zone.concentration_link = False
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})
    ctx.rider(f"{rule['name']}: {actor.display_name}'s {rule['area']} at ({zone.center.x}, {zone.center.y}) now lasts for the rest "
              "of its duration without Concentration.")
