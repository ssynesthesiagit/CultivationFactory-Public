"""Persistent player loadouts for reviewed additive on-hit attack modifiers.

The compiler calls capture() before losing its modifier composition records and
settings() after weapon delivery. Table presentation calls presentation(). These
public helpers share the same sealed metadata; no ability IDs or live authority
lookups are used at resolution. Legacy catalogs without that metadata are inert.
AI retains its existing variants and paid-hit decisions.

Shared variant_modifiers(action, actions) checks final owned replacement controls;
variant_replaced() exposes the same check to settings and tabletop.auto_buttons,
including sealed catalogs that still carry an orphaned capture marker.
The existing candidate_allowed hook respects disabled controls for recorded human
seats only. Enabling a control restores every exact variant; AI and catalogs
without an owned replacement control retain their legacy candidates.

Shared helpers automatic(), chosen() and family() are used by paid_hit to route
configured players through the same parent preferences. factory_compiler uses
capture()/settings(); tabletop_service uses presentation(). All consumers use
owned sealed metadata, with no resolution change when that metadata is absent.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from . import effect, hook

CONDITION = "condition:typed.attack_modifiers"


@hook("attack_modifier_capture_allowed")
def temporal_prerequisite(row: dict[str, Any]) -> bool | None:
    """Keep hit-time mark gates embedded where the attack samples their marks."""
    if row.get("type") == "if_marked" and row.get("at") == "hit":
        return False
    return None


def capture(base: dict[str, Any]) -> None:
    """Retain additive hit choices and payment alternatives on their parent."""
    from . import run_strict

    def independent(rows):
        return all(not any(answer is False for answer in run_strict("attack_modifier_capture_allowed", row))
                   and all(independent(row.get(field) or [])
                           for field in ("effects", "on_hit", "on_fail", "on_success"))
                   for row in rows if isinstance(row, dict))

    def has_attack(rows):
        return any(row.get("type") == "attack" or any(has_attack(row.get(field) or [])
            for field in ("effects", "on_hit", "on_fail", "on_success")) for row in rows if isinstance(row, dict))
    if not base["typed"].get("weapon") and not has_attack(base["typed"].get("effects") or []):
        return  # saving-throw abilities retain their existing shape/augment semantics
    groups = {g["id"]: copy.deepcopy(g) for g in base["typed"].get("attack_modifier_loadout") or []}
    for variant in base.get("variants") or []:
        part = variant.get("_compose") or {}
        modifier = part.get("modifier") or {}
        if part.get("when") != "hit" or not part.get("added") or part.get("traits"):
            continue
        if not independent(part["added"]):
            continue  # sequence declarations retain their original player route
        # Geometry, dice replacements and activation changes need their own
        # pre-attack semantics; never silently treat them as additive riders.
        if any(modifier.get(k) for k in ("add_range_ft", "range_ft_by_cl", "area_size_ft", "add_area_ft",
                "economy", "replaces_effect_slot", "damage_die_steps", "damage_type", "extra_attacks", "target_requires_mark")):
            continue
        key = part["key"]
        name, _, label = part["name"].partition(": ")
        group = groups.setdefault(key, {"id": key, "name": name, "options": []})
        effects = copy.deepcopy(part["added"])
        signature = json.dumps(effects, sort_keys=True)
        option = next((o for o in group["options"] if json.dumps(o["effects"], sort_keys=True) == signature), None)
        if option is None:
            option = {"id": str(len(group["options"])), "label": label or name, "effects": effects, "payments": []}
            group["options"].append(option)
        costs = {}
        for resource, amount in variant["costs"]:
            costs[resource] = costs.get(resource, 0) + amount
        for resource, amount in base["costs"]:
            costs[resource] = costs.get(resource, 0) - amount
        payment = [[resource, amount] for resource, amount in costs.items() if amount > 0]
        if payment not in option["payments"]:
            option["payments"].append(payment)
        variant["typed"]["attack_modifier_variant"] = base["action_id"]
    if groups:
        base["typed"]["attack_modifier_loadout"] = list(groups.values())


def automatic(engine: Any, actor: Any) -> bool:
    return (getattr(engine, "typed_control_modes", {}) or {}).get(actor.owner_id or actor.entity_id) == "LOCAL_AUTO"


def family(ctx: Any) -> str:
    """Shared preference identity for attack_modifiers and paid_hit routing."""
    return ctx.typed.get("attack_modifier_family") or ctx.source


def chosen(actor: Any, family: str, key: str) -> dict[str, Any]:
    for condition in actor.conditions.values():
        if condition.condition_id == CONDITION and condition.data.get("family") == family and condition.data.get("modifier") == key:
            return dict(condition.data)
    return {"on": 0, "option": "ask", "payment": "ask", "damage": "ask"}


def price(costs: list) -> str:
    return " + ".join(f"{amount} {'CP' if resource in ('resource:core.qi', 'resource:core.resonance') else resource.rsplit('.', 1)[-1].replace('_', ' ').title()}"
                      for resource, amount in costs) or "Free"


def damage_types(effects: list) -> list[str]:
    kinds = []
    for row in effects:
        if not isinstance(row, dict):
            continue
        if row.get("type") in ("damage", "extra_damage") and len(row.get("damage_types") or []) > 1:
            kinds.extend(row["damage_types"])
        for field in ("on_fail", "on_success", "on_hit", "effects"):
            nested = row.get(field)
            # Some effect types (end_effect) use on_success as a plain string such as
            # "suppress"; only a nested list of effects carries damage types.
            if isinstance(nested, list):
                kinds.extend(damage_types(nested))
    return list(dict.fromkeys(kinds))


def payment_choices(group: dict) -> dict[str, list]:
    """Stable group-wide prices; equal indices never mean different costs.

    Used by settings, presentation and hit resolution. First-option indices
    stay unchanged for existing sealed catalogs and persisted preferences.
    """
    payments = []
    for option in group["options"]:
        for payment in option["payments"]:
            if payment not in payments:
                payments.append(payment)
    return {str(i): payment for i, payment in enumerate(payments)}


def description(options: list[dict]) -> str:
    """Printed effects, named conditions and plug-in explanations of custom rows."""
    from . import run
    from .paid_hit import effect_text
    from ..condition_text import condition_reading
    notes = []
    def visit(rows):
        for row in rows:
            # Some branches carry plain strings such as on_success="suppress".
            if not isinstance(row, dict):
                continue
            rule = condition_reading(row.get("condition")) if row.get("type") == "condition" else None
            if rule and rule[1]:
                notes.append(f"{rule[0]}: {rule[1]}")
            notes.extend(note for note in run("effect_description", row) if note)
            for field in ("effects", "on_hit", "on_fail", "on_success"):
                nested = row.get(field)
                if isinstance(nested, list):
                    visit(nested)
    for option in options:
        visit(option["effects"])
    return " ".join([*(effect_text(o["effects"]) for o in options), *dict.fromkeys(notes)])


def settings(actions: list[Any]) -> list[Any]:
    """Add free settings once per parent/talent, never one per payment variant."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .paid_hit import effect_text
    added = []
    parents = {a.source_definition_id: a for a in actions}
    for action in actions:
        typed = action.parameters.get("typed") or {}
        parent = parents.get(typed.get("variant_of"))
        if parent is None or parent.owner_id != action.owner_id:
            continue
        groups = (parent.parameters.get("typed") or {}).get("attack_modifier_loadout") or []
        if not groups:
            continue
        # Single variants precede capture; composed variants may already carry
        # a snapshot. Always use the final parent's sealed loadout. Embedded
        # modifiers have already paid/applied through the original variant.
        embedded = set((typed.get("modifier") or {}).get("id", "").split("+"))
        for modifier in typed.get("selected_modifiers") or []:
            embedded.update(modifier.get("id", "").split("+"))
        typed["attack_modifier_family"] = parent.source_definition_id
        typed["attack_modifier_loadout"] = copy.deepcopy([g for g in groups if g["id"] not in embedded])
    for action in actions:
        typed = action.parameters.get("typed") or {}
        if typed.get("variant_of"):
            continue
        for group in typed.get("attack_modifier_loadout") or []:
            stem = action.source_definition_id + ".rider." + hashlib.sha256(group["id"].encode()).hexdigest()[:8]
            payments = payment_choices(group)
            fields = {"option": [(o["id"], o["label"] + (" — " + effect_text([e for row in o["effects"] for e in row.get("on_fail") or []])
                          if any(row.get("on_fail") for row in o["effects"]) else "")) for o in group["options"]],
                      "payment": [(key, price(p)) for key, p in payments.items()],
                      "damage": [(kind, kind.title()) for kind in damage_types([row for option in group["options"] for row in option["effects"]])]}
            for field, values in {"on": [("toggle", group["name"])], **fields}.items():
                if field != "on":
                    values = [("ask", "Ask me when it hits"), *values]
                for value, label in values:
                    spec = {"family": action.source_definition_id, "modifier": group["id"], "name": group["name"], "field": field, "value": value}
                    setting_text = (f"Turn {group['name']} on or off for {action.display_name}. Choosing is free and stays until changed. "
                                   "It applies only on a qualifying hit; pay the chosen cost for each use. A miss costs nothing. "
                                   "CP means Cultivation Points, paid from your Path resource. "
                                   + description(group["options"]))
                    added.append(ActionDefinition(source_definition_id=f"{stem}.{field}.{value}", display_name=f"{group['name']}: {label}",
                        owner_id=action.owner_id, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                        parameters={"typed": {"effects": [{"type": "attack_modifier_setting", **spec}], "numbers": typed.get("numbers") or {},
                                              "duration": {"kind": "instant"}, "riders": []},
                                    "attack_modifier_setting": spec, "setting_only": True, "player_only": True,
                                    "setting_description": setting_text, "expected_damage": 0} ))
    # Capture precedes final delivery. Some maneuvers deliberately emit only
    # talent variants, so their captured parent never becomes a usable action.
    # Hide a legacy route only when its owner's replacement toggle exists.
    for action in actions:
        typed = action.parameters.get("typed") or {}
        parent_id = typed.get("attack_modifier_variant")
        if parent_id and not variant_replaced(action, [*actions, *added]):
            typed.pop("attack_modifier_variant", None)
    return [*actions, *added]


def variant_modifiers(action: Any, actions: Any) -> list[dict]:
    """Owned parent groups controlling modifiers embedded in a captured variant.

    Accept compiled model rows or sheet bundle dictionaries. Shared by candidate
    admission and sheet replacement checks; missing parents/toggles are inert.
    """
    def value(row, field):
        return row.get(field) if isinstance(row, dict) else getattr(row, field, None)
    typed = (value(action, "parameters") or {}).get("typed") or {}
    parent_id = typed.get("attack_modifier_variant")
    if not parent_id:
        return []
    rows = list(actions)
    owner = value(action, "owner_id")
    parent = next((a for a in rows if value(a, "source_definition_id") == parent_id
                   and value(a, "owner_id") == owner), None)
    parent_typed = (value(parent, "parameters") or {}).get("typed") or {}
    groups = {g["id"]: g for g in parent_typed.get("attack_modifier_loadout") or []}
    modifiers = set((typed.get("modifier") or {}).get("id", "").split("+"))
    for modifier in typed.get("selected_modifiers") or []:
        modifiers.update(modifier.get("id", "").split("+"))
    if parent is None or parent_typed.get("variant_of") or not groups:
        return []
    controlled = {spec["modifier"] for a in rows
                  if (spec := (value(a, "parameters") or {}).get("attack_modifier_setting"))
                  and value(a, "owner_id") == owner and spec.get("family") == parent_id
                  and spec.get("field") == "on" and spec.get("modifier") in modifiers}
    return [group for key, group in groups.items() if key in controlled]


def variant_replaced(action: Any, actions: Any) -> bool:
    """True only when a captured variant has an owned usable parent/toggle."""
    return bool(variant_modifiers(action, actions))


@hook("candidate_allowed")
def enabled_variant(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """A human loadout cannot silently bypass its disabled rider via a variant.

    Only captured variants with owned replacement controls participate. Settings,
    plain attacks, orphan variants and all built-in AI routes remain unchanged.
    """
    typed = (getattr(action, "parameters", {}) or {}).get("typed") or {}
    parent_id = typed.get("attack_modifier_variant")
    if not parent_id or action.owner_id != actor.entity_id:
        return None
    mode = (getattr(engine, "typed_control_modes", {}) or {}).get(actor.entity_id)
    if mode not in {"MANUAL", "SUGGESTED", "MANUAL_AI_BRIDGE"}:
        return None  # No recorded human seat: preserve legacy engine/AI catalogs.
    for group in variant_modifiers(action, engine.action_catalog.values()):
        saved = chosen(actor, parent_id, group["id"])
        if not saved["on"] and not (group.get("legacy_paid") and not saved.get("family")):
            return False
    return None


@effect("attack_modifier_setting")
def set_choice(ctx: Any, row: dict[str, Any]) -> None:
    catalog = ctx.engine.action_catalog.get(row["family"])
    groups = ((getattr(catalog, "parameters", {}) or {}).get("typed") or {}).get("attack_modifier_loadout") or []
    group = next((g for g in groups if g["id"] == row["modifier"]), None)
    if catalog is None or catalog.owner_id != ctx.actor.entity_id or group is None:
        return
    valid = {"on": ["toggle"], "option": ["ask", *(o["id"] for o in group["options"])],
             "payment": ["ask", *payment_choices(group)],
             "damage": ["ask", *damage_types([e for o in group["options"] for e in o["effects"]])]}
    if row["value"] not in valid.get(row["field"], []):
        return
    data = chosen(ctx.actor, row["family"], row["modifier"])
    if not data.get("family") and any(g["id"] == row["modifier"] and g.get("legacy_paid") for g in groups):
        data["on"] = 1
    data.update(family=row["family"], modifier=row["modifier"], label=row["name"],
                reading="Attack modifier choices stay until changed; only a qualifying hit pays the selected cost.")
    data[row["field"]] = 1 - int(data.get("on", 0)) if row["field"] == "on" else row["value"]
    for iid, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id == CONDITION and condition.data.get("family") == row["family"] and condition.data.get("modifier") == row["modifier"]:
            del ctx.actor.conditions[iid]
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"condition_id": CONDITION, "instance_id": iid})
    ctx.engine._apply_condition(ctx.actor, CONDITION, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data=data)


@hook("settings_batch_key")
def settings_batch_key(action: Any) -> tuple | None:
    """Approve only absolute rider selections; toggles keep the combat route."""
    spec = (action.parameters or {}).get("attack_modifier_setting")
    effects = ((action.parameters or {}).get("typed") or {}).get("effects") or []
    if (not spec or spec.get("field") not in {"payment", "option", "damage"}
            or effects != [{"type": "attack_modifier_setting", **spec}]):
        return None
    return spec["family"], spec["modifier"], spec["field"]


@hook("option_composition")
def composition(action):
    """Draft toggles are parity changes, bound to an immutable fight version."""
    spec = (action.parameters or {}).get("attack_modifier_setting")
    effects = ((action.parameters or {}).get("typed") or {}).get("effects") or []
    if (not spec or effects != [{"type": "attack_modifier_setting", **spec}]
            or spec.get("field") not in {"on", "payment", "option", "damage"}):
        return None
    return {"key": ["attack_modifier", spec["family"], spec["modifier"], spec["field"]],
            "mode": "toggle" if spec["field"] == "on" else "select", "family": spec["family"]}


def select(ctx, target, group, field, values, saved, *, allow_decline=True):
    if saved != "ask":
        return saved if saved in values else None
    if len(values) == 1 and not allow_decline:
        return next(iter(values))
    from .needle import ask, checkpoint_id
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "attack_modifier", group["id"], field, target.entity_id),
        ctx.actor, "choice:needle.attack_modifier", list(values), labels=values, allow_decline=allow_decline,
        target_id=target.entity_id, name=group["name"], feature_id=group["id"],
        prompt=f"{group['name']}: {ctx.action.display_name} hit {target.display_name}. Choose {field}. "
               + ("You may decline this rider. " if allow_decline else "The target failed its saving throw. ")
               + "This rider is paid once per qualifying hit. CP means Cultivation Points, paid from your Path resource. "
               + description(group.get("options") or []))
    return next((key for key in values if key in picked), None)


def failed_save_menu(group: dict, options: dict) -> list | None:
    """Defer a choose-one failed-save branch until that save actually fails.

    Only identical common effects qualify; menus changing the whole activation
    retain their ordinary on-hit selection. The selected branch uses the same
    transactional choice transport and original reviewed effect rows.
    """
    skeletons = []
    for option in options.values():
        rows = copy.deepcopy(option['effects'])
        for row in rows:
            if row.get('type') == 'save':
                row['on_fail'] = []
        skeletons.append(json.dumps(rows, sort_keys=True))
    if len({json.dumps(o['payments'], sort_keys=True) for o in options.values()}) != 1 or len(set(skeletons)) != 1 or not any(row.get('type') == 'save' and row.get('on_fail')
                                          for option in options.values() for row in option['effects']):
        return None
    effects = copy.deepcopy(next(iter(options.values()))['effects'])
    for index, row in enumerate(effects):
        if row.get('type') == 'save':
            row['on_fail'] = [{'type': 'attack_modifier_failed_choice', 'group': {'id': group['id'], 'name': group['name']},
                'options': [{'id': key, 'label': option['label'], 'effects': copy.deepcopy(option['effects'][index].get('on_fail') or [])}
                            for key, option in options.items()]}]
    return effects


@effect('attack_modifier_failed_choice')
def failed_choice(ctx: Any, row: dict) -> None:
    from ..typed_executor import run_effects
    options = {o['id']: o for o in row['options']}
    picked = select(ctx, ctx.target, row['group'], 'failed-save effect',
                    {key: f"{o['label']}. {description([o])}" for key, o in options.items()}, 'ask', allow_decline=False)
    if picked is not None:
        run_effects(ctx, options[picked]['effects'])


def effect_can_apply(ctx: Any, row: dict[str, Any]) -> bool:
    """Pure loadout eligibility before consent/payment, on the hit context.

    Ordinary mark wrappers read live owner marks, including Opened's existing
    pre-strike contract. Explicit hit-time gates read only the captured snapshot;
    capture still vetoes detaching those rows. Nested gates must expose at least
    one eligible effect. This query never executes effects or consumes a use.
    """
    from . import run_strict
    from ..effect_eligibility import eligible
    from ..typed_executor import bears_mark, mark_condition_id, opened_before

    if not eligible(ctx, row) or any(answer is False for answer in run_strict("effect_allowed", ctx, row)):
        return False
    if row.get("type") not in ("if_marked", "if_not_marked"):
        return True
    raw = row.get("mark")
    names = [str(name).strip() for name in (raw if isinstance(raw, list) else [raw]) if str(name or "").strip()]
    if not names:
        return False
    subject = ctx.actor if row.get("applies_to") == "self" else ctx.target
    if subject is None:
        return False
    def marked(name):
        if row.get("type") == "if_marked" and row.get("at") == "hit":
            return bool(ctx.damage_cache.get("_marks_at_hit", {}).get(subject.entity_id, {}).get(name))
        before = (opened_before(ctx.engine, ctx.actor.entity_id, subject.entity_id)
                  if mark_condition_id(name, ctx.actor.entity_id) == mark_condition_id("Opened", ctx.actor.entity_id) else None)
        return before if before is not None else bears_mark(subject, ctx.actor.entity_id, name)
    has_mark = any(marked(name) for name in names)
    if has_mark != (row["type"] == "if_marked"):
        return False
    from dataclasses import replace
    inner = replace(ctx, target=subject, targets=[subject])
    return any(effect_can_apply(inner, nested) for nested in row.get("effects") or [])


@hook("confirmed_hit_roll_bonus")
def selected_roll_bonus(engine, attacker, target, spec, intent, source):
    """Resolve fixed and Ask-me loadouts through the same confirmed-hit delivery.

    The typed scope is an explicit context bridge, never an engine replacement.
    Mixed menus retain their selected non-roll effects for after_hit_choice.
    """
    frame = getattr(engine, "_typed_critical_scope", None)
    if not frame or frame[0].actor is not attacker or frame[0].source != source:
        return None
    ctx = frame[0]
    if automatic(engine, attacker):
        return None
    from .roll_modifiers import is_roll_modifier
    groups = [g for g in ctx.typed.get("attack_modifier_loadout") or []
              if any(is_roll_modifier(row) for o in g["options"] for row in o["effects"])]
    if not groups:
        return None
    ctx.damage_cache["_selected_hit_loadouts"] = {}
    return apply_selected(ctx, target, "other", roll_groups=groups)


@hook("after_hit_choice", priority=-10)
def apply_selected(ctx: Any, target: Any, kind: str, *, roll_groups=None):
    if roll_groups is None and ctx.attack_damage_context is not None:
        target = ctx.engine.state.actors[ctx.attack_damage_context.target_id]
    if automatic(ctx.engine, ctx.actor) or not target.active:
        return
    from .paid_hit import apply_paid_effects
    from .roll_modifiers import is_roll_modifier, fold_confirmed_rows
    hit_ctx = ctx.on_hit_context(target)
    total = 0
    held = ctx.damage_cache.setdefault("_selected_hit_loadouts", {})
    if roll_groups is None:
        for source, (costs, effects) in list(held.items()):
            if effects:
                apply_paid_effects(ctx, target, source, [], effects)
            held[source] = (costs, [])
    for group in (roll_groups if roll_groups is not None else ctx.typed.get("attack_modifier_loadout") or []):
        if group["id"] in held:
            continue
        if roll_groups is not None:
            held[group["id"]] = ([], [])  # Declining must not ask again after damage.
        saved = chosen(ctx.actor, family(ctx), group["id"])
        if group.get("legacy_paid") and not saved.get("family"):
            continue  # retain the established Ask-me transport until configured
        if not saved["on"]:
            continue
        options = {o["id"]: o for o in group["options"] if any(effect_can_apply(hit_ctx, e) for e in o["effects"])
                   and any(ctx.engine._can_pay(ctx.actor, payment) for payment in o["payments"])}
        if not options:
            continue
        deferred = failed_save_menu(group, options) if saved['option'] == 'ask' else None
        oid = (next(iter(options)) if deferred is not None else select(ctx, target, group, "effect",
                {k: f"{o['label']}. {description([o])}" for k, o in options.items()}, saved["option"]))
        if oid is None:
            continue
        option = options[oid]
        option_payments = {key: p for key, p in payment_choices(group).items() if p in option["payments"]}
        payments = {key: p for key, p in option_payments.items() if ctx.engine._can_pay(ctx.actor, p)}
        if not payments:
            continue
        payment_choice = saved["payment"] if saved["payment"] in option_payments else "ask"
        pid = select(ctx, target, group, "payment", {k: price(p) for k, p in payments.items()}, payment_choice)
        if pid is None:
            continue
        # A deferred failed-save menu is still an optional activation. When
        # neither payment nor damage type asks, retain consent before spending.
        if deferred is not None and payment_choice != 'ask' and (saved['damage'] in damage_types(deferred) or not damage_types(deferred)):
            if select(ctx, target, group, "activation", {"use": f"Apply this rider: pay {price(payments[pid])} for this hit"}, 'ask') is None:
                continue
        effects = deferred if deferred is not None else copy.deepcopy(option["effects"])
        kinds = damage_types(effects)
        if kinds:
            damage_choice = saved["damage"] if saved["damage"] in kinds else "ask"
            damage = select(ctx, target, group, "damage type", {k: k.title() for k in kinds}, damage_choice)
            if damage is None:
                continue
            def bind(rows):
                for row in rows:
                    if len(row.get("damage_types") or []) > 1 and damage in row["damage_types"]:
                        row["damage_types"] = [damage]
                    for field in ("on_hit", "on_fail", "on_success", "effects"):
                        bind(row.get(field) or [])
            bind(effects)
        if roll_groups is not None:
            bonus_rows = [row for row in effects if is_roll_modifier(row)]
            total += fold_confirmed_rows(ctx, target, bonus_rows)
            for resource, amount in payments[pid]:
                ctx.engine._spend_resource(ctx.actor, resource, amount, group["id"])
            held[group["id"]] = (payments[pid], [row for row in effects if not is_roll_modifier(row)])
        else:
            apply_paid_effects(ctx, target, group["id"], payments[pid], effects)
    return total


@hook("settings_project_rows")
def project_rows(actions, actor_id, saved, affected_sources):
    """Project defaults use the same rider renderer as a live fight."""
    from types import SimpleNamespace
    grouped = {}
    for source in saved:
        spec = actions[source].parameters.get("attack_modifier_setting")
        if not spec:
            continue
        data = grouped.setdefault((spec["family"], spec["modifier"]), {
            "family": spec["family"], "modifier": spec["modifier"], "on": 0,
            "option": "ask", "payment": "ask", "damage": "ask"})
        data[spec["field"]] = spec["value"]
    actor = SimpleNamespace(entity_id=actor_id, conditions={str(i): SimpleNamespace(
        condition_id=CONDITION, data=data) for i, data in enumerate(grouped.values())})
    engine = SimpleNamespace(action_catalog=actions, state=SimpleNamespace(actors={actor_id: actor}))
    if affected_sources:
        return batch_rows(engine, actor_id, affected_sources)
    out = {}
    presentation(None, engine, out)
    return [row for entry in out.get(actor_id, []) for row in entry.get("modifiers", [])]


@hook("settings_batch_rows")
def batch_rows(engine: Any, actor_id: str, sources: list[str]) -> list[dict]:
    """Shared settings_service view: rerender only affected families with the existing renderer."""
    from types import SimpleNamespace
    families = {spec["family"] for source in sources
                if (spec := engine.action_catalog[source].parameters.get("attack_modifier_setting"))}
    if not families:
        return []
    catalog = {source: action for source, action in engine.action_catalog.items()
               if source in families or (action.parameters.get("attack_modifier_setting") or {}).get("family") in families}
    view = SimpleNamespace(action_catalog=catalog, state=engine.state)
    out = {}
    presentation(None, view, out)
    return [row for entry in out.get(actor_id, []) for row in entry.get("modifiers", [])]


def presentation(menu: dict | None, engine: Any, out: dict) -> None:
    """Add modifier rows/selectors to the existing Darkness Options transport."""
    from .paid_hit import effect_text
    # Settings select future on-hit behaviour, not the exact legal variant
    # candidate (including its targets, destination and options). Keep each
    # issued action group admitted by the human loadout gate so human and
    # model-seat pages can select every enabled route.
    choices = {}
    for group in (menu or {}).get("actions") or []:
        action = engine.action_catalog.get(group["source_definition_id"])
        spec = (getattr(action, "parameters", {}) or {}).get("attack_modifier_setting")
        if spec and group.get("options"):
            choices[action.source_definition_id] = group["options"][0]["candidate_id"]
            group["shape"] = spec["family"]
    for action in engine.action_catalog.values():
        typed = action.parameters.get("typed") or {}
        if typed.get("variant_of"):
            continue
        for modifier in typed.get("attack_modifier_loadout") or []:
            actor = engine.state.actors.get(action.owner_id)
            if actor is None:
                continue
            settings_ = [a for a in engine.action_catalog.values() if (a.parameters.get("attack_modifier_setting") or {}).get("family") == action.source_definition_id
                         and a.parameters["attack_modifier_setting"]["modifier"] == modifier["id"]]
            toggle = next((a for a in settings_ if a.parameters["attack_modifier_setting"]["field"] == "on"), None)
            if toggle is None:
                continue  # an Opportunity Attack uses the existing off-turn Ask-me flow
            rows = out.setdefault(action.owner_id, [])
            entry = next((e for e in rows if e["base"] == action.source_definition_id), None)
            if entry is None:
                entry = {"base": action.source_definition_id, "name": action.display_name, "zone": None, "options": [],
                         "augments": [], "current": None, "augments_label": None, "clear_candidate": None}
                rows.append(entry)
            saved = chosen(actor, action.source_definition_id, modifier["id"])
            if modifier.get("legacy_paid") and not saved.get("family"):
                saved["on"] = 1
            selectors = []
            selected = next((o for o in modifier["options"] if o["id"] == saved["option"]), None)
            applicable = {
                "payment": {key for key, p in payment_choices(modifier).items() if selected is None or p in selected["payments"]},
                "damage": set(damage_types(selected["effects"])) if selected else None,
            }
            for field, label in (("payment", "Pay on hit"), ("option", "Effect on hit / failed save"), ("damage", "Damage type")):
                all_options = [{"value": a.parameters["attack_modifier_setting"]["value"], "label": a.display_name.split(": ", 1)[-1],
                         "button_id": f"act:{a.source_definition_id}", "candidate_id": choices.get(a.source_definition_id)}
                        for a in settings_ if a.parameters["attack_modifier_setting"]["field"] == field]
                opts = [o for o in all_options if field not in applicable or applicable[field] is None
                        or o['value'] == 'ask' or o['value'] in applicable[field]]
                if len(all_options) > 1:
                    current = saved[field] if any(o["value"] == saved[field] for o in opts) else "ask"
                    allowed = {}
                    for option in modifier['options']:
                        values = ({key for key, p in payment_choices(modifier).items() if p in option['payments']}
                                  if field == 'payment' else set(damage_types(option['effects'])) if field == 'damage' else None)
                        if values is not None:
                            allowed[option['id']] = sorted({'ask', *values})
                    selectors.append({"field": field, "label": label, "current": current, "options": opts,
                                      "all_options": all_options, "allowed_by_effect": allowed})
            entry.setdefault("modifiers", []).append({"name": modifier["name"], "on": bool(saved["on"]), "selectors": selectors,
                "button_id": f"act:{toggle.source_definition_id}", "candidate_id": choices.get(toggle.source_definition_id),
                "description": description(modifier["options"]),
                "cost": " or ".join(price(p) for p in payment_choices(modifier).values())})
