"""Native spiritual object profiles and source-clocked object relationships.

Shared by contact providers and spiritual asset movement. Explicit map profiles
and source-created SPIRIT_ASSET objects supply eligibility, never object names.
All mutations use OBJECT_UPDATED; no synthetic creature or initiative is added.
Objects without assigned saving throws fail saves (5.5e Breaking Objects).
"""
import copy
from types import SimpleNamespace

from . import hook, run_strict

KEY = "source_relationships"


def validate_profile(value):
    if not isinstance(value, dict) or set(value) - {"external_anchor", "cultivation_asset", "internal_anchor", "affectable", "saving_throws", "known_to"}:
        raise ValueError("Invalid explicit spiritual object profile")
    for key, val in value.items():
        if key == "known_to":
            if not isinstance(val, list) or any(not isinstance(v, str) for v in val):
                raise ValueError("Spiritual object knowledge must list actor ids")
            continue
        if key == "saving_throws":
            if not isinstance(val, dict) or any(k not in {"STR", "DEX", "CON", "INT", "WIS", "CHA"} or type(v) is not int for k, v in val.items()):
                raise ValueError("Object saving throws require explicit integer modifiers")
        elif type(val) is not int or val not in (0, 1):
            raise ValueError("Spiritual object profile flags must be 0 or 1")
    return copy.deepcopy(value)


def known_to(obj, actor):
    """Explicit anchor knowledge or an openly manifested native spirit asset."""
    return (obj.owner_id == actor.entity_id or obj.object_kind == "SPIRIT_ASSET"
            or actor.entity_id in (obj.component.get("spiritual_profile") or {}).get("known_to", []))


def eligible(obj):
    profile = obj.component.get("spiritual_profile") or {}
    return not obj.destroyed and not profile.get("internal_anchor") and (
        obj.object_kind == "SPIRIT_ASSET" and bool(obj.component.get("spirit_asset"))
        or profile.get("affectable") == 1 and (profile.get("external_anchor") == 1 or profile.get("cultivation_asset") == 1))


def geometry(engine, obj):
    """Read-only body geometry for existing body-aware ray/route enumerators.

    A map object's sealed ``width_cells``/``length_cells``/``rotation`` describe
    the body a targeting consumer already sees (``objects.rectangular_footprint``);
    the movement proxy uses that same footprint, so a route or destination is
    validated against the real rectangle and cannot squeeze through an undersized
    gap or leave its far edge off the battlefield. Objects without explicit
    dimensions keep the native size-category volume.
    """
    from ..footprints import native_actor_footprint
    from ..dynamic_size import category_name
    from .objects import rectangular_footprint
    size = category_name(obj.component.get("size"))
    footprint = rectangular_footprint(obj)
    if footprint is None:
        footprint = native_actor_footprint(obj.object_id, size)
    engine.actor_footprints[obj.object_id] = footprint
    conditions = {str(r["created_sequence"]): SimpleNamespace(condition_id=r["data"]["condition_id"],
        source_actor_id=r["source_actor_id"], source_definition_id=r["data"]["source_record_id"],
        data={"native_source_record": r["data"]}) for r in records(obj, "source_protection")}
    return SimpleNamespace(entity_id=obj.object_id, position=obj.position, active=not obj.destroyed,
        display_name=obj.component.get("name") or "spiritual object", transformed_size_category=None,
        size_category=size, conditions=conditions, team_id="team:object")


def records(obj, kind=None, owner=None):
    return [r for r in obj.component.get(KEY, []) if (kind is None or r["kind"] == kind)
            and (owner is None or r["source_actor_id"] == owner)]


def put(engine, obj, owner, kind, data, source, *, boundary="scene"):
    if boundary not in {"scene", "start", "end"}:
        raise ValueError("Unknown object relationship expiry boundary")
    obj = engine.state.objects[obj.object_id]
    identity = str(data.get("id") or kind)
    rows = [r for r in records(obj) if (r["kind"], r["source_actor_id"], r.get("identity", r["kind"])) != (kind, owner.entity_id, identity)]
    rows.append({"kind": kind, "source_actor_id": owner.entity_id, "source_definition_id": source,
        "source_cl": int(data.get("source_cl") or 0), "created_sequence": int(engine.state.event_sequence + 1),
        "identity": identity, "boundary": boundary, "due_turn": int(owner.turns_started) + 1, "data": copy.deepcopy(data)})
    engine._update_object(obj.model_copy(update={"component": {**obj.component, KEY: rows}}), source, owner.entity_id)


def clear_owner(engine, kind, owner, source):
    for obj in list(engine.state.objects.values()):
        rows = [r for r in records(obj) if not (r["kind"] == kind and r["source_actor_id"] == owner)]
        if len(rows) != len(records(obj)):
            engine._update_object(obj.model_copy(update={"component": {**obj.component, KEY: rows}}), source, owner)


def save(ctx, obj, ability):
    """Return failed/succeeded using assigned object saves, else automatic fail."""
    saves = (obj.component.get("spiritual_profile") or {}).get("saving_throws") or {}
    if ability.upper() not in saves:
        ctx.engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=ctx.actor.entity_id,
            target_ids=(obj.object_id,), payload={"log": f"{obj.component.get('name') or 'The spiritual object'} has no assigned {ability.title()} score and fails its saving throw."})
        return True
    dc = int(ctx.numbers["save_dc"])
    roll = ctx.engine.roller.d20(actor_id=obj.object_id, modifier=saves[ability.upper()], reason=f"SAVE:{ctx.source}:{ability.upper()}")
    ctx.engine._record_roll(roll)
    ctx.engine._append_event("SAVE_ROLLED", ctx.source, actor_id=obj.object_id, target_ids=(obj.object_id,),
        payload={**roll.model_dump(mode="json"), "dc": dc, "success": roll.total >= dc})
    return roll.total < dc


def choose_move(ctx, obj, routes, name):
    from . import needle
    choices = {needle.cell_id(cell): cell for cell in routes}
    selected = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "OBJECT_CONTACT_MOVE", obj.object_id),
        ctx.actor, "choice:needle.object_contact_destination", list(choices),
        labels={key: f"Move {obj.component.get('name') or 'the spiritual object'} to {key.split(':', 1)[1]}" for key in choices},
        prompt=f"{name}: choose a legal destination for {obj.component.get('name') or 'the spiritual object'}.",
        name=name, target_id=obj.object_id)
    if selected and False not in run_strict("object_operation_gate", ctx.engine, ctx.actor, obj, "move", ctx.source, ctx.intent):
        obj = ctx.engine.state.objects[obj.object_id]
        ctx.engine._update_object(obj.model_copy(update={"position": choices[selected[0]]}), ctx.source, ctx.actor.entity_id)
        from ..zones import sync_walls
        sync_walls(ctx.engine)
        refresh_relationships(ctx.engine)


def movement_grid(engine, obj):
    """Omit only this object's own blocking overlay for its path query."""
    from ..zones import query_grid
    return query_grid(engine, excluded_zone_ids=(f"zone:{obj.object_id}",)) if obj.component.get("blocks") else engine.grid


def relationship_status(engine, obj, row):
    if obj.destroyed:
        return "SUBJECT_UNAVAILABLE"
    from .source_records import contact_allowed, effective_level
    from ..targeting import line_of_effect
    source = engine.state.actors.get(row["source_actor_id"])
    if source is None or effective_level(engine, source) < int(row["data"].get("minimum_source_cl") or 1):
        return "FEATURE_UNAVAILABLE"
    proxy = geometry(engine, obj)
    from copy import copy
    view = copy(engine)
    view.grid = movement_grid(engine, obj)
    if not line_of_effect(view, source, target=proxy):
        return "NO_LINE_OF_EFFECT"
    return "ACTIVE" if contact_allowed(engine, source, proxy, effective_level(engine, source)) else "CONTACT_DENIED"


def refresh_relationships(engine):
    for obj in list(engine.state.objects.values()):
        rows = copy.deepcopy(records(obj))
        changed = False
        for row in rows:
            if row["kind"] == "handspan_subject":
                status = relationship_status(engine, obj, row)
                if row["data"].get("contact_status") != status:
                    row["data"]["contact_status"] = status
                    changed = True
        if changed:
            engine._update_object(obj.model_copy(update={"component": {**obj.component, KEY: rows}}), "system:object_contact", None)


@hook("event")
def relationship_events(engine, event_type, kwargs):
    if event_type in {"OBJECT_UPDATED", "MOVEMENT_COMMITTED", "CONDITION_APPLIED", "CONDITION_REMOVED", "CONDITION_DATA_UPDATED"}:
        refresh_relationships(engine)


def movement_held(obj):
    """A native asset's source movement is unavailable while a speed-zero hold lasts."""
    return bool(records(obj, "speed_zero"))


def expression_active(obj, identity, source_actor=None):
    """A source's exact named permission; independent expressions stay active."""
    suppressed = {r["data"]["expression_sequence"] for r in records(obj, "expression_suppression")}
    return any(r["identity"] == identity and (source_actor is None or r["source_actor_id"] == source_actor)
               and r["created_sequence"] not in suppressed for r in records(obj, "contact_expression"))


@hook("candidate_allowed")
def expression_permission(engine, actor, candidate, action):
    rows = source_effects(action)
    # This primitive has an object consumer only. Source protections alone
    # still support creatures through their ordinary typed effect handler.
    if any(row["type"] == "object_source_expression" for row in rows):
        targets = getattr(candidate, "target_ids", ())
        if not targets or any(target not in engine.state.objects for target in targets):
            return False
    required = (getattr(action, "parameters", None) or {}).get("requires_object_expression")
    if not required:
        return None
    obj = engine.state.objects.get(required["object_id"])
    return None if obj is not None and expression_active(obj, required["expression_id"], required["source_actor_id"]) else False


def produce_expression(ctx, obj, row):
    """Source-authored native object expression, consumed by exact action gates.

    The descriptor names its category/authority and visibility explicitly. It
    grants no generic control or movement; its original source's native actions
    opt into requires_object_expression for that one permission.
    """
    from .source_records import EXPRESSIONS
    if row["category"] not in EXPRESSIONS or type(row["ordinary"]) is not int or row["ordinary"] not in (0, 1):
        raise ValueError("Object expression needs explicit category and ordinary authority")
    if not all(isinstance(row.get(k), str) and row[k].strip() for k in ("id", "name")):
        raise ValueError("Object expression must name its exact permission")
    known = row.get("known_to", [])
    if not isinstance(known, list) or any(not isinstance(v, str) for v in known):
        raise ValueError("Object expression knowledge must list actor ids")
    put(ctx.engine, obj, ctx.actor, "contact_expression", {"id": row["id"], "name": row["name"],
        "category": row["category"], "ordinary": row["ordinary"], "known_to": list(known),
        "source_cl": int(ctx.numbers["cl"]), "save_dc": int(ctx.numbers["save_dc"])}, ctx.source,
        boundary=row.get("boundary", "scene"))


def produce_protection(ctx, obj, row):
    from .source_records import validate, effective_level, EXPRESSIONS
    from .spirit_traditions import feature_of
    source = feature_of(ctx.action)
    data = {"id": row["condition_id"], "condition_id": row["condition_id"], "name": row["name"],
        "category": row["category"], "scope": row["scope"], "ordinary": row["ordinary"],
        "source_record_id": source, "source_cl": effective_level(ctx.engine, ctx.actor)}
    validate(data, {source})
    if data["category"] in EXPRESSIONS:
        raise ValueError("Use object_source_expression for a named expression")
    kind = (row.get("duration") or {}).get("kind", "scene")
    boundaries = {"scene": "scene", "until_start_of_your_next_turn": "start", "until_end_of_your_next_turn": "end"}
    if kind not in boundaries:
        raise ValueError("Object source protections need an explicit source-turn or scene duration")
    put(ctx.engine, obj, ctx.actor, "source_protection", data, ctx.source, boundary=boundaries[kind])


def source_effects(action):
    """Pure object-expression/protection packets supported by this consumer."""
    rows = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or []
    return rows if rows and all(r.get("type") == "object_source_expression" or
        r.get("type") == "source_protection" and r.get("applies_to") == "target" for r in rows) else []


@hook("object_targets")
def expression_targets(engine, actor, action):
    if source_effects(action):
        return [obj.object_id for obj in engine.state.objects.values() if eligible(obj) and known_to(obj, actor)]
    return None


@hook("object_action")
def expression_action(engine, actor, action, obj, candidate, intent):
    rows = source_effects(action)
    if not rows:
        return None
    from .spirit_traditions import context
    ctx = context(engine, actor, action, [], intent=intent)
    from ..typed_executor import activation_reactions
    run_strict("technique_accepted", engine, actor, action)
    if any(reply is True for reply in run_strict("technique_start", engine, actor, action)) or not activation_reactions(ctx):
        return True
    for row in rows:
        (produce_expression if row["type"] == "object_source_expression" else produce_protection)(ctx, obj, row)
    run_strict("technique_used", ctx)
    return True


def expire(engine, actor=None, boundary="scene", *, nominal=False):
    from .effect_durations import custom_turn_due
    for obj in list(engine.state.objects.values()):
        rows = [r for r in records(obj) if not (r["boundary"] == boundary
            and (actor is None or r["source_actor_id"] == actor.entity_id
                 and custom_turn_due(actor, r["due_turn"], actor.turn_flags,
                     f"object:{obj.object_id}:{r['created_sequence']}", nominal=nominal)))]
        if len(rows) != len(records(obj)):
            engine._update_object(obj.model_copy(update={"component": {**obj.component, KEY: rows}}), "system:object_relationships", getattr(actor, "entity_id", None))


@hook("turn_start")
def start_expiry(engine, actor):
    expire(engine, actor, "start")


@hook("turn_end")
def end_expiry(engine, actor, *, nominal=False):
    expire(engine, actor, "end")


@hook("nominal_slot_boundary")
def nominal_expiry(engine, actor, checkpoint):
    expire(engine, actor, "start" if checkpoint == "START_OF_TURN" else "end", nominal=True)


@hook("scene_end")
def scene_expiry(engine):
    expire(engine)
