"""Shared helper module: combat/ext/last_inch_palm.py (cultivation_check, effective_level, movement_protected,
relationship_status), combat/ext/mudang.py (apply_expression) and combat/ext/object_subjects.py (contact_allowed,
effective_level, validate) use these helpers.

Source-qualified classification of native condition instances.

Shared public helper: consumed by last_inch_palm.py, mudang.py and object_subjects.py. Its exported functions are
the stable cross-plugin API; private helpers stay private.

Used by Last-Inch Palm and available to diagnosis, dispelling and movement
providers. A source record classifies an existing permission; it never creates
one. Owners acquire these records on the sheet alongside their source feature.
Compilation rejects unowned sources, unknown fields and incomplete authority.
At runtime a record exists only while its exact source's native condition does.
No names, sphere membership or generic damage tags supply classifications.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re

from . import effect, hook

BLOCK = "native_source_record"
EXPRESSIONS = frozenset({"possession_entry", "disguise_body", "external_control", "incorporeal_passage"})
PROTECTIONS = frozenset({"bodily", "gravity", "space", "boundary", "anchoring", "separation"})
CONTACT_DENIALS = frozenset({"sealed_boundary", "domain_contact_denial", "planar_separation", "perfect_spiritual_concealment"})
FIELDS = {"id", "name", "source_record_id", "condition_id", "category", "scope", "ordinary", "source_cl", "data_match", "known_to"}


def acquire(sheet, record):
    """Return an owner sheet with one explicit source classification acquired.

    This is authoring input, not an assertion that its condition is currently
    active. The source must be among this sheet's earned features/talents.
    ``known_to`` is a list of actor ids that know this particular expression;
    the source owner always knows its own. Empty does not mean public.
    """
    paths = sheet.get("path_and_subpath") or {}
    talents = sheet.get("spheres_and_talents") or {}
    owned = set(paths.get("path_feature_record_ids") or []) | set(talents.get("learned_talent_record_ids") or [])
    owned.update(r.get("feature_id") for r in paths.get("earned_feature_occurrences") or [])
    owned.update(r.get("feature_id") for r in sheet.get("combat_acquisitions") or [])
    validate(record, owned)
    out = copy.deepcopy(sheet)
    records = out.setdefault("combat_source_records", [])
    if any(r["id"] == record["id"] for r in records):
        raise ValueError("Source record identity already acquired")
    records.append(copy.deepcopy(record))
    return out


def validate(record, owned):
    if not isinstance(record, dict) or set(record) - FIELDS:
        raise ValueError("Unknown source record fields")
    required = FIELDS - {"data_match", "known_to"}
    if not required <= record.keys() or not all(isinstance(record[k], str) and record[k].strip()
            for k in ("id", "name", "source_record_id", "condition_id", "category", "scope")):
        raise ValueError("Incomplete native source record")
    if record["source_record_id"] not in owned:
        raise ValueError("Source record must belong to an acquired feature")
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]+", record["id"]):
        raise ValueError("Invalid source record identity")
    if record["category"] not in EXPRESSIONS | PROTECTIONS | CONTACT_DENIALS:
        raise ValueError("Unknown source record category")
    if record["scope"] not in {"contact_expression", "forced_movement", "spiritual_contact"}:
        raise ValueError("Unknown source record scope")
    if record["category"] in EXPRESSIONS and record["scope"] != "contact_expression":
        raise ValueError("An expression requires contact-expression scope")
    if record["category"] in CONTACT_DENIALS and record["scope"] != "spiritual_contact":
        raise ValueError("A contact denial requires spiritual-contact scope")
    if type(record["ordinary"]) is not int or record["ordinary"] not in (0, 1):
        raise ValueError("Ordinary authority must be explicitly recorded as 0 or 1")
    if type(record["source_cl"]) is not int or record["source_cl"] < 0:
        raise ValueError("Source CL must be an explicit nonnegative integer")
    if not isinstance(record.get("known_to", []), list) or any(not isinstance(v, str) for v in record.get("known_to", [])):
        raise ValueError("Source visibility must list actor ids")
    if not isinstance(record.get("data_match", {}), dict) or any(type(v) not in (str, int) for v in record.get("data_match", {}).values()):
        raise ValueError("Source instance selectors must be strings or integers")


@hook("compile_bundle")
def compile_records(bundle, info):
    # Compiled actions and passives are the admitted source set. Merely naming
    # an unavailable source in an authoring record cannot grant its permission.
    owned = {r.get("feature_id") for r in bundle.get("typed_passives") or []}
    for action in bundle["action_catalog"]:
        typed = action.get("parameters", {}).get("typed") or {}
        owned.update((typed.get("source"), typed.get("option_of")))
    records = list(info["owner_sheet"].get("combat_source_records") or [])
    # Source-backed native producers publish their own exact condition
    # contracts; owner records add instance-specific classification/knowledge.
    defaults = json.loads((Path(__file__).parents[1] / "rules/native_source_conditions.json").read_text())
    for row in defaults:
        if row["source_record_id"] in owned and not any(
                r["source_record_id"] == row["source_record_id"] and r["condition_id"] == row["condition_id"] for r in records):
            records.append({**row, "source_cl": int(info["numbers"]["cl"])})
    if not records:
        return None
    ids = set()
    for record in records:
        validate(record, owned)
        if record["id"] in ids:
            raise ValueError("Duplicate native source record identity")
        ids.add(record["id"])
    out = copy.deepcopy(bundle)
    out["typed_passives"].extend({"block": BLOCK, **copy.deepcopy(r)} for r in records)
    return out


def cultivation_check(ctx, condition, label):
    """Native Cultivation Check against the recorded source's Cultivation DC.

    This is the existing source-DC procedure, not an inferred CL-to-DC formula.
    Unknown/absent sources cannot silently lose their expression. The original
    roll and exact source are journaled for table reload and mechanical replay.
    """
    from .source_eligibility import catalog_action
    from .spirit_traditions import numbers
    source = ctx.engine.state.actors.get(condition.source_actor_id)
    native = (condition.data or {}).get("native_source_record") or {}
    saved = (condition.data or {}).get("origin_save") or {}
    action = catalog_action(ctx.engine, condition.source_definition_id)
    recorded = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("numbers") or {}
    dc = saved.get("dc", native.get("save_dc", recorded.get("save_dc")))
    if dc is None:
        if source is None:
            return False
        # Owner Tradition Procedure Addendum R7 section 2: a source with no
        # printed/recorded DC uses 10 + opposing PB + key ability modifier.
        opposing = numbers(ctx.engine, source)
        dc = 10 + int(opposing.get("pb") or source.proficiency_bonus) + int(opposing.get("key_mod", 3))
    dc = int(dc)
    roll = ctx.engine.roll_check(actor_id=ctx.actor.entity_id,
        modifier=int(ctx.numbers.get("pb") or 2) + int(ctx.numbers.get("key_mod") or 0),
        reason=f"CHECK:{ctx.source}:source_expression")
    ctx.engine._record_roll(roll)
    ctx.engine._append_event("CHECK_ROLLED", ctx.source, actor_id=ctx.actor.entity_id,
        target_ids=(condition.target_id,), payload={"actor": roll.model_dump(mode="json"),
        "dc": dc, "success": roll.total >= dc, "source_actor_id": condition.source_actor_id,
        "source_definition_id": condition.source_definition_id, "check": label})
    return roll.total >= dc


def apply_expression(ctx, holder, condition_id, *, category, ordinary, source=None, expires_on="UNTIL_REMOVED", data=None, exclusive_group=None):
    """Produce one native expression with its exact permission and provenance.

    The provider supplies its own actual condition/rule, category and ordinary
    status. Removing that condition disables that expression's existing native
    consumers; unrelated conditions, body traits and Path ownership survive.
    Source CL comes from the activation, not from the feature's unlock level.
    Used by Mudang's Guest Seat and the reusable source_expression typed effect.
    """
    from .spirit_traditions import feature_of
    source = source or feature_of(ctx.action)
    record = {"id": condition_id, "name": (data or {}).get("label") or ctx.action.display_name,
        "source_record_id": source, "condition_id": condition_id, "category": category,
        "scope": "contact_expression", "source_cl": int(ctx.numbers["cl"]), "ordinary": ordinary}
    validate(record, {source})
    if exclusive_group is not None:
        if not isinstance(exclusive_group, str) or not exclusive_group:
            raise ValueError("An exclusive expression group needs a name")
        # Replacing an exclusive source expression retires its suppressed copy
        # too; expiry must not recreate an old Guest beside a new one.
        for key, condition in list(holder.conditions.items()):
            stored = condition.data or {}
            snapshot = next((stored[k] for k in ("condition", "model") if isinstance(stored.get(k), dict)), None) or condition.model_dump(mode="json")
            native = (snapshot.get("data") or {}).get("native_source_record") or {}
            if snapshot.get("source_actor_id") == ctx.actor.entity_id and native.get("exclusive_group") == exclusive_group:
                ctx.engine._remove_condition_instance(holder, key, source, expected=condition)
        record["exclusive_group"] = exclusive_group
    if ctx.numbers.get("save_dc") is not None:
        record["save_dc"] = int(ctx.numbers["save_dc"])
    ctx.engine._apply_condition(holder, condition_id, source, ctx.actor.entity_id, expires_on=expires_on,
        data={**copy.deepcopy(data or {}), "native_source_record": record})


@hook("scene_end")
def scene_conditions_end(engine):
    """Remove only explicitly scene-bound conditions before the terminal event."""
    for holder in list(engine.state.actors.values()):
        for key, condition in list(holder.conditions.items()):
            data = condition.data or {}
            original = next((data[k] for k in ("condition", "model") if isinstance(data.get(k), dict)), {})
            if data.get("ends_with_scene") == 1 or (original.get("data") or {}).get("ends_with_scene") == 1:
                engine._remove_condition_instance(holder, key, "system:scene_end", expected=condition)


@effect("source_expression")
def expression_effect(ctx, row):
    """Explicit typed producer; its condition_data supplies the native permission."""
    from ..typed_executor import effect_expiry
    for holder in ([ctx.actor] if row.get("applies_to") == "self" else ctx.targets or []):
        apply_expression(ctx, holder, row["condition_id"], category=row["category"], ordinary=row["ordinary"],
            expires_on=effect_expiry(ctx, row, holder, condition=True), data=row.get("condition_data"), exclusive_group=row.get("exclusive_group"))


@effect("source_protection")
def protection_effect(ctx, row):
    """Explicit, scoped source-fact producer; no inferred protections or bonuses.

    Source authors select forced_movement or spiritual_contact and the exact
    authority category. The source's separate condition_data.rule retains any
    printed numeric effect. Only matching scoped consumers read this record.
    """
    from .spirit_traditions import feature_of
    from ..typed_executor import effect_expiry
    source = feature_of(ctx.action)
    record = {"id": row["condition_id"], "name": row["name"], "source_record_id": source,
        "condition_id": row["condition_id"], "category": row["category"], "scope": row["scope"],
        "source_cl": effective_level(ctx.engine, ctx.actor), "ordinary": row["ordinary"]}
    validate(record, {source})
    if record["category"] in EXPRESSIONS:
        raise ValueError("Use source_expression for a contact expression")
    for holder in ([ctx.actor] if row.get("applies_to") == "self" else ctx.targets or []):
        ctx.engine._apply_condition(holder, row["condition_id"], source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, row, holder, condition=True),
            data={**copy.deepcopy(row.get("condition_data") or {}), "label": row["name"], "native_source_record": record})


def live(engine, holder, *, scope=None, viewer=None):
    """Return (native condition, explicit classification) pairs, never receipts.

    Unknown authority or visibility does not acquire a default. Suppressing the
    underlying condition removes this entry and its native permission together.
    """
    from .source_eligibility import catalog_action
    from .spirit_traditions import feature_of

    out = []
    for condition in holder.conditions.values():
        source = condition.source_actor_id
        action = catalog_action(engine, condition.source_definition_id)
        source_ids = {condition.source_definition_id, feature_of(action)}
        rows = [r for r in getattr(engine, "typed_passive_rows", {}).get(source, []) if r.get("block") == BLOCK]
        native = (condition.data or {}).get("native_source_record")
        if native and not any(r["source_record_id"] == native["source_record_id"] and r["condition_id"] == condition.condition_id for r in rows):
            rows.append({"block": BLOCK, **native})
        for row in rows:
            if row.get("block") != BLOCK or row["source_record_id"] not in source_ids:
                continue
            if scope is not None and row["scope"] != scope:
                continue
            if condition.condition_id != row["condition_id"]:
                continue
            if any((condition.data or {}).get(k) != v for k, v in row.get("data_match", {}).items()):
                continue
            if viewer is not None and viewer.entity_id != source and viewer.entity_id not in row.get("known_to", []):
                continue
            out.append((condition, row))
    return out


def movement_protected(ctx, target):
    """Explicitly scoped bodily/route protections, including higher Source CL."""
    return any(row["category"] in PROTECTIONS and
               (row["category"] != "separation" or row["source_cl"] > int(ctx.numbers["cl"]))
               for _, row in live(ctx.engine, target, scope="forced_movement"))


def effective_level(engine, actor):
    """Current explicit Realm suppression, bounded by the sealed source level."""
    from .spirit_traditions import numbers
    level = int(numbers(engine, actor).get("cl") or 1)
    for condition in actor.conditions.values():
        value = ((condition.data or {}).get("rule") or {}).get("effective_cultivation_level")
        if type(value) is int and 1 <= value <= level:
            level = min(level, value)
    return level


@hook("effect_resolution_scope")
def effective_source_scope(ctx, row):
    """Opt-in activation Source CL follows currently recorded Realm suppression."""
    if not ctx.typed.get("effective_source_cl"):
        return None
    from contextlib import contextmanager

    @contextmanager
    def scope():
        previous = ctx.typed
        ctx.typed = {**previous, "numbers": {**ctx.numbers, "cl": effective_level(ctx.engine, ctx.actor)}}
        try:
            yield
        finally:
            ctx.typed = previous
    return scope()


def relationship_status(engine, holder, condition):
    """Pure current status of an explicitly conditional spiritual relationship.

    Missing contact_kind is inert. The stored relationship is retained through
    suppression; its permission is recomputed from native level, contact-source
    facts and physical line of effect, without treating it as adjacency.
    """
    data = condition.data or {}
    if data.get("contact_kind") != "spiritual":
        return "ACTIVE"
    source = engine.state.actors.get(condition.source_actor_id)
    if source is None:
        return "SOURCE_UNAVAILABLE"
    level = effective_level(engine, source)
    if level < int(data.get("minimum_source_cl") or 1):
        return "FEATURE_UNAVAILABLE"
    from ..targeting import line_of_effect
    if not line_of_effect(engine, source, target=holder):
        return "NO_LINE_OF_EFFECT"
    return "ACTIVE" if contact_allowed(engine, source, holder, level) else "CONTACT_DENIED"


def contact_allowed(engine, source, target, source_cl):
    """A recorded separation denies only spiritual contact, not sight or speech.

    Higher-authority separation denies contact only above the incoming Source
    CL. Explicit Boundary/Space contact denial applies at its recorded scope.
    Physical total cover is independently enforced by the targeting engine.
    """
    return not any(row["category"] != "separation" or row["source_cl"] > source_cl
                   for holder in (source, target)
                   for _, row in live(engine, holder, scope="spiritual_contact"))
