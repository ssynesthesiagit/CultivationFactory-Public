"""Crimson Court's live, owner-scoped combat riders on existing zone hooks.

The marker is sealed in new actions. Old Court bundles never enter this path.
Native zone membership owns volume, line of effect, suppression and allegiance.
Shared helper courts supplies live membership to blood_court_healing; it is
also used here for saves, sensing and Bloodied notices.
"""
from . import effect, hook, note

MARKER = "blood_court_runtime"
SENSED = "condition:typed.crimson_court_sensed"
HEALED = "blood_court_healing_turn"


@effect(MARKER)
def court_marker(ctx, row):
    """Ownership marker; the zone and its standing rules resolve natively."""


def courts(engine, creature, *, owner=None, who="any"):
    from ..spatial_areas import zone_contains
    from ..zones import continuous_rule_applies
    from ..relations import ALLY, ENEMY, relation
    for zone in engine.state.zones.values():
        if not zone.active or (owner is not None and zone.owner_id != owner.entity_id):
            continue
        action = engine.action_catalog.get(zone.source_definition_id)
        typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
        if not any(row.get("type") == MARKER for row in typed.get("effects") or []):
            continue
        caster = engine.state.actors.get(zone.owner_id)
        if caster is not None and who != "any" and relation(engine, caster, creature) != (ALLY if who == "ally" else ENEMY):
            continue
        if (caster is not None and caster.active and zone_contains(engine, creature, zone)
                and continuous_rule_applies(engine, zone, creature, {"who": who})):
            yield zone, caster


@hook("save_mode")
def court_save(engine, target, ability, dc, source_id, roll_context):
    from .blood_bloodied import is_bloodied
    if not is_bloodied(target):
        return None
    action = engine.action_catalog.get(source_id)
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("sphere") != "tianxia.sphere.blood":
        return None
    owner = engine.state.actors.get(getattr(action, "owner_id", ""))
    if owner is not None and any(courts(engine, target, owner=owner, who="hostile")):
        return "DISADVANTAGE"
    return None


@hook("event", nested=True)
def court_events(engine, event_type, kwargs):
    payload = kwargs.get("payload") or {}
    if event_type == "ZONE_REMOVED":
        zone_id = payload.get("zone_id")
        for creature in engine.state.actors.values():
            for iid, condition in list(creature.conditions.items()):
                if condition.condition_id == SENSED and condition.data.get("zone_id") == zone_id:
                    from .condition_ownership import remove_instance
                    remove_instance(engine, creature, iid, condition.source_definition_id)
        return
    if event_type != "DAMAGE_COMMITTED":
        return
    for aid in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(aid)
        if target is None or not target.active:
            continue
        damage = int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0)
        if damage <= 0:
            continue
        for zone, owner in courts(engine, target, who="hostile"):
            if not any(c.condition_id == SENSED and c.data.get("zone_id") == zone.zone_id
                       for c in target.conditions.values()):
                engine._apply_condition(target, SENSED, zone.source_definition_id, owner.entity_id,
                                        expires_on="UNTIL_REMOVED", data={"zone_id": zone.zone_id,
                                        "label": "Crimson Court: ordinary invisibility does not conceal you from this Domain's owner while inside"})
        hp_damage = int(payload.get("hp_damage") or 0)
        if target.current_hp * 2 <= target.maximum_hp < (target.current_hp + hp_damage) * 2:
            for zone, owner in courts(engine, target, who="ally"):
                recipients = [other for other in engine.state.actors.values()
                              if any(z.zone_id == zone.zone_id for z, _ in courts(engine, other, who="ally"))]
                note(engine, zone.source_definition_id, owner,
                     f"Crimson Court: {target.display_name}, an ally inside your Domain, becomes Bloodied.",
                     targets=tuple(recipients))


@hook("masked_conditions")
def court_sense(engine, viewer, target):
    if getattr(target, "perception_cell", False) or getattr(viewer, "perception_cell", False):
        return None
    zones = {zone.zone_id for zone, _ in courts(engine, target, owner=viewer, who="hostile")}
    if not zones or not any(c.condition_id == SENSED and c.data.get("zone_id") in zones
                            for c in target.conditions.values()):
        return None
    ids = {iid for iid, c in target.conditions.items() if c.condition_id == "condition:typed.invisible"}
    return {"conditions": {target.entity_id: ids}, "visual": False} if ids else None
