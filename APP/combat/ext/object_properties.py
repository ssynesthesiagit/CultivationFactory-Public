"""Shared sealed object properties: inspection evidence and removable afflictions.

Consumers: objects.seed and tabletop map normalization use map_object_components;
talismans' Read the Script uses the shared evidence/learn helpers, and
talisman_preparation.library_read_mode uses evidence for its family check.
Purifying Talisman uses the generic
remove_object_affliction typed effect. Future readers/cleansers use these same
hooks and effects, not a second object store. All mutations use OBJECT_UPDATED.

Map input properties.inspection={kind,dc?,facts:{key:string|integer},...} records world
evidence, never a player's desired answer. Additional inspection fields remain
private and are not automatically revealed. afflictions={id:{kind,grade,...}}
records independent contaminants/curses/etc. Missing metadata means unknown,
not a fabricated clean object. JSON values are strings, integers, lists/dicts.
Learned facts use information_results' private, owner-only replay journal.
"""
from copy import deepcopy

from . import effect, hook, run_strict


def _json_value(value):
    if type(value) in (int, str):
        return True
    if isinstance(value, list):
        return all(_json_value(v) for v in value)
    return isinstance(value, dict) and all(isinstance(k, str) and _json_value(v) for k, v in value.items())


@hook("map_object_components")
def properties(engine, row):
    row = row.get("properties") or {}
    if not isinstance(row, dict):
        raise ValueError("object properties must be a dictionary")
    out = {}
    for key in ("inspection", "afflictions"):
        if key not in row:
            continue
        value = row[key]
        if not isinstance(value, dict) or not _json_value(value):
            raise ValueError(key + " requires string/integer JSON object properties")
        if key == "inspection":
            if not isinstance(value.get("kind"), str) or not isinstance(value.get("facts"), dict):
                raise ValueError("inspection requires kind and facts")
            if "dc" in value and (type(value["dc"]) is not int or value["dc"] < 0):
                raise ValueError("inspection dc must be a nonnegative integer")
            if "proficiencies" in value and (not isinstance(value["proficiencies"], list)
                    or any(not isinstance(v, str) or not v for v in value["proficiencies"])):
                raise ValueError("inspection proficiencies must name relevant checks")
            if any(type(v) not in (str, int) for v in value["facts"].values()):
                raise ValueError("inspection facts must be strings or integers")
        elif any(not isinstance(v, dict) or not all(isinstance(v.get(k), str) for k in ("kind", "grade"))
                 for v in value.values()):
            raise ValueError("afflictions require kind and grade")
        out[key] = deepcopy(value)
    return out or None


def evidence(obj, kind=None):
    """World evidence for a reader (Talismans), not an observer projection."""
    value = (obj.component or {}).get("inspection")
    return value if isinstance(value, dict) and (kind is None or value.get("kind") == kind) else None


def learn(ctx, obj, facts):
    """Retain exactly the reader's allowlisted findings for its actor, privately."""
    from ..information_results import private_records, record_private
    feature = str(ctx.typed.get("source") or ctx.source)
    old = private_records(ctx.engine, ctx.actor, feature, "object_inspection").get(obj.object_id)
    known = dict(old["public"]["facts"]) if old else {}
    known.update(facts)
    record_private(ctx.engine, ctx.actor, ctx.source, feature, "object_inspection", obj.object_id,
                   {"kind": "object_inspection", "ability": ctx.action.display_name,
                    "object_id": obj.object_id, "facts": known})


@hook("observer_information")
def findings(engine, observer):
    # Own journal only: never project sealed object facts or another reader's results.
    from ..information_results import private_records
    features = {row.get("feature") for event in engine.events
                if (row := event.payload.get("private_information") or {}).get("owner") == observer.entity_id
                and row.get("kind") == "object_inspection"}
    labels = {"family": "Formula family", "rank": "Rank", "activation": "Activation",
              "integrity": "Condition of the writing", "connection": "Connected to",
              "safe_touch": "Safe to touch", "trigger_avoidance": "Safe way to avoid triggering"}
    out = []
    for feature in sorted(features):
        for record in private_records(engine, observer, feature, "object_inspection").values():
            result = record["public"]
            def describe(key, value):
                if key == "safe_touch" and type(value) is int:
                    value = "yes" if value else "no"
                return labels.get(key, key) + ": " + str(value)
            out.append({**result, "text": "; ".join(describe(k, v) for k, v in result["facts"].items())})
    return out


def _rows(action):
    return ((action.parameters or {}).get("typed") or {}).get("effects") or []


def _matching(obj, row):
    return [key for key, value in ((obj.component or {}).get("afflictions") or {}).items()
            if value.get("kind") in row.get("kinds", []) and value.get("grade") == row.get("grade")]


@hook("compile_action")
def inspection_target(action, info):
    if any(row.get("type") == "inspect_object" for row in _rows(action)):
        return action.model_copy(update={"target_kind": "OBJECT"})
    return None


@hook("object_targets")
def targets(engine, actor, action):
    if action.owner_id != actor.entity_id:
        return []
    rows = [row for row in _rows(action) if row.get("type") in {"inspect_object", "remove_object_affliction"}]
    if not rows:
        return []
    from ..senses import perceives_object
    return [obj.object_id for obj in engine.state.objects.values() if not obj.destroyed and any(
        (row.get("type") == "inspect_object" and evidence(obj, row.get("kind")) is not None
         and perceives_object(engine, actor, obj))
        or (row.get("type") == "remove_object_affliction" and _matching(obj, row)) for row in rows)]


@effect("inspect_object")
def inspect(ctx, row):
    selected = ctx.damage_cache.get("_object")
    if selected is None:
        raise ValueError("inspection needs an actual object")
    obj = ctx.engine.state.objects.get(selected.object_id)
    if obj is None or obj.destroyed:
        return
    replies = run_strict("object_inspection", ctx, row, obj)
    if len(replies) != 1 or replies[0] is not True:
        raise ValueError("inspection requires exactly one owning reader")


@effect("remove_object_affliction")
def cleanse(ctx, row):
    obj = ctx.damage_cache.get("_object")
    if obj is None:
        return  # creature delivery has its own typed condition effects
    obj = ctx.engine.state.objects[obj.object_id]
    matches = sorted(_matching(obj, row))
    if not matches:
        return
    from .needle import ask, checkpoint_id, CHOICE
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "object_affliction", obj.object_id),
                 ctx.actor, CHOICE + "object_affliction", matches,
                 labels={key: "Remove " + obj.component["afflictions"][key]["grade"] + " "
                              + obj.component["afflictions"][key]["kind"].replace("_", " ") for key in matches},
                 preferred=matches[:1], name=ctx.action.display_name, target_id=obj.object_id,
                 prompt=ctx.action.display_name + ": which " + str(row.get("grade") or "") +
                        " contamination do you end on this object? " +
                        str(row.get("cost_label") or "Uses the action and resource cost displayed for this ability."))
    if not chosen:
        return
    afflictions = dict(obj.component["afflictions"])
    del afflictions[chosen[0]]
    ctx.engine._update_object(obj.model_copy(update={"component": {**obj.component, "afflictions": afflictions}}),
                              ctx.source, ctx.actor.entity_id)


@hook("object_action")
def resolve(engine, actor, action, obj, candidate, intent):
    rows = [row for row in _rows(action) if row.get("type") in {"inspect_object", "remove_object_affliction"}]
    if not rows:
        return None
    from ..typed_executor import Context, activation_reactions, run_effects
    from ..paid_relocation import technique_completed
    ctx = Context(engine, actor, action, intent, action.parameters["typed"], [], None)
    ctx.damage_cache["_object"] = obj
    run_strict("technique_accepted", engine, actor, action)
    if any(value is True for value in run_strict("technique_start", engine, actor, action)):
        return True
    if not activation_reactions(ctx):
        return True
    run_effects(ctx, rows)
    run_strict("technique_used", ctx)
    technique_completed(ctx)
    return True
