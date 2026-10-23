"""Suppressing or cancelling one ordinary temporary benefit (rider lane C4, 2026-09-30). Shared helper module: used by
combat/ext/void_riders.py (Nullification Seal, Nullifying Strike, Return to Zero, Cause-Emptying Reversal, World of Nothing);
any plug-in may use it. Built on combat/ext/suppressed_effects.py (the same lifetime/restore rules Radiance and Destruction use).

Sphere of Void, "Ordinary Temporary Effect": "a nonpermanent spell, sphere talent, item activation, monster ability, stance, aura,
or technique with a limited duration. Examples include: a temporary AC bonus; Temporary HP; a temporary Speed bonus; a temporary
damage reduction; a temporary Resistance; a temporary source of Invisible ..." -- on this table: a creature's expiring beneficial
modifiers (an AC bonus, a Speed bonus, a Resistance or Immunity, a condition immunity, a cost reduction, Disadvantage on attacks
against it) and an Invisible condition. Permanent features (compiled passives, modifiers without an expiry) are never offered.
A cost reduction is a modifier whose field is ``cost_reduction:<resource>`` (combat/cost_reductions.py), which is also what the
cost quote reads, so suppressing one raises the affected costs back to their listed values.

- ``benefits(engine, creature, fields=None, since=None)``: [{"id", "label"}], ids "modifier:<id>" / "condition:<id>".
  ``fields`` narrows to modifier fields (["damage_resistance"]); ``since`` to rows applied after an event index.
- ``suppress(engine, owner, holder, benefit_id, until, source, repeat=None)``: takes the benefit off and keeps it on a
  ``condition:typed.benefit_suppressed`` row (JSON only). ``until``: "owner_turn" (the start of the owner's next turn),
  "holder_turn" (the start of the holder's next turn), "holder_turn_end" (the END of the holder's next turn, for a
  printed "until the end of its next turn"; auto/paths-b 2026-10-04, Qi Cultivation's Meridian Regulation) or
  "concentration" (while the owner concentrates on ``source``);
  ``repeat``: {"ability": "CHA", "dc": n} -- the holder repeats the save at the end of each of its turns, ending it on a success.
  The benefit comes back then, unless its own time has run out meanwhile.
- ``cancel(engine, holder, benefit_id, source)``: the benefit does not take effect (removed for good).
- ``suppress_component(engine, owner, holder, instance_id, path, until, source, label)``:
  temporarily clear one rule field of a composite condition, preserving its other
  penalties, ongoing damage and native lifetime. ``path`` is a dotted dictionary
  path; restoration requires the same live parent instance. Used by Qi Path.
- ``consume_suppressed_conditions(engine, holder, condition_id)``: discard stored
  one-use conditions when their trigger happens while their penalty is suppressed.
  Used by Poison's next-check effect; other one-use condition owners may use it.
  Returns the number consumed, zero without matching records, and never restores them.

``until`` names a lifetime, not a kind of benefit: ``benefits()`` only offers beneficial rows, but any plug-in that
prints "suppress one penalty" (a harmful condition or modifier) may pass a penalty's id straight to ``suppress()``.
"""
from __future__ import annotations

from typing import Any

from . import hook
from .ability_source import source_label
from ..cost_reductions import PREFIX as REDUCTION, resource

SUPPRESSED = "condition:typed.benefit_suppressed"
_FIELDS = {"armor_class": "AC bonus", "armor_class_vs_melee": "AC bonus against melee", "armor_class_vs_ranged": "AC bonus against ranged",
           "speed_ft": "Speed bonus", "damage_resistance": "Resistance", "damage_immunity": "Immunity", "condition_immunity": "condition immunity",
           "incoming_attack_mode": "attacks against it at Disadvantage"}
_PERMANENT = ("", None, "UNTIL_REMOVED")


def _beneficial(modifier: Any) -> bool:
    field, value = modifier.target_field, modifier.value
    if field.startswith(REDUCTION):
        return modifier.expires_on not in _PERMANENT and type(value) is int and value > 0
    if field not in _FIELDS or modifier.expires_on in _PERMANENT:
        return False
    if field.startswith("armor_class") or field == "speed_ft":
        return isinstance(value, int) and value > 0
    if field == "incoming_attack_mode":
        return str(value).upper() == "DISADVANTAGE"
    return True


def _name(modifier: Any) -> str:
    """The plain-language name of one beneficial modifier, before "from <source>"."""
    from ..resource_labels import resource_name

    field, value = modifier.target_field, modifier.value
    if field.startswith(REDUCTION):
        return f"cost reduction ({value} points off {resource_name(resource(field))})"
    if field in ("damage_resistance", "damage_immunity", "condition_immunity"):
        return f"{_FIELDS[field]} {value}"
    return f"{_FIELDS[field]} +{value}" if isinstance(value, int) else _FIELDS[field]


def _made_after(engine: Any, holder: Any, key: str, since: int | None) -> bool:
    if since is None:
        return True
    return any((event.payload or {}).get("modifier_id") == key or (event.payload or {}).get("instance_id") == key
               for event in engine.events[since:] if holder.entity_id in (event.target_ids or ()))


def benefits(engine: Any, creature: Any, fields: list[str] | None = None, since: int | None = None) -> list[dict[str, str]]:
    out = []
    for key, modifier in creature.modifiers.items():
        if _beneficial(modifier) and (not fields or modifier.target_field in fields) and _made_after(engine, creature, key, since):
            name = source_label(engine, modifier.source_definition_id)
            explanation = {"damage_resistance": "halves that damage", "damage_immunity": "prevents that damage",
                           "condition_immunity": "prevents that condition", "speed_ft": "extra feet of movement"}.get(modifier.target_field)
            out.append({"id": f"modifier:{key}", "label": f"{_name(modifier)} from {name}"
                        + (f" ({explanation})" if explanation else "")})
    if not fields:
        for key, condition in creature.conditions.items():
            if condition.condition_id == "condition:typed.invisible" and condition.expires_on not in _PERMANENT and _made_after(engine, creature, key, since):
                out.append({"id": f"condition:{key}", "label": f"Invisible from {source_label(engine, condition.source_definition_id)}"})
            elif (condition.data or {}).get('temporary_benefit') == 1 and condition.expires_on not in _PERMANENT and _made_after(engine, creature, key, since):
                out.append({'id': f'condition:{key}', 'label': str(condition.data.get('label') or source_label(engine, condition.source_definition_id))})
    return out


def _take(engine: Any, holder: Any, benefit_id: str, source: str) -> tuple[str, Any] | None:
    kind, _, key = benefit_id.partition(":")
    if kind == "modifier" and key in holder.modifiers:
        model = holder.modifiers.pop(key)
        engine._append_event("MODIFIER_REMOVED", model.source_definition_id, actor_id=model.source_actor_id, target_ids=(holder.entity_id,),
                             payload={"modifier_id": key, "reason": "SUPPRESSED", "by": source})
        return "modifier", model
    if kind == "condition" and key in holder.conditions:
        model = holder.conditions[key]
        if not engine._remove_condition_instance(holder, key, source, actor_id=model.source_actor_id,
                payload={"condition_id": model.condition_id, "instance_id": key, "reason": "SUPPRESSED"}, expected=model):
            return None
        return "condition", model
    return None


def cancel(engine: Any, holder: Any, benefit_id: str, source: str) -> bool:
    return _take(engine, holder, benefit_id, source) is not None


def consume_suppressed_conditions(engine: Any, holder: Any, condition_id: str) -> int:
    """Consume matching stored conditions; the caller owns their trigger semantics."""
    consumed = 0
    for held in list(holder.conditions.values()):
        if held.condition_id != SUPPRESSED:
            continue
        data = held.data or {}
        model = data.get("model") or {}
        if data.get("kind") != "condition" or not isinstance(model, dict) or model.get("condition_id") != condition_id:
            continue
        consumed += int(cancel(engine, holder, "condition:" + held.instance_id, held.source_definition_id))
    return consumed


def suppress(engine: Any, owner: Any, holder: Any, benefit_id: str, until: str, source: str, repeat: dict[str, Any] | None = None,
             label: str = "") -> bool:
    from .suppressed_effects import lifetime

    model = holder.modifiers.get(benefit_id.partition(":")[2]) or holder.conditions.get(benefit_id.partition(":")[2])
    if model is None:
        return False
    clock = lifetime(engine, holder, model)
    taken = _take(engine, holder, benefit_id, source)
    if taken is None:
        return False
    kind, model = taken
    engine._apply_condition(holder, SUPPRESSED, source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": label or "A benefit is suppressed", "kind": kind, "model": model.model_dump(mode="json"),
                                  "lifetime": clock, "until": until, "owner_turn": int(owner.turns_started),
                                  "holder_turn": int(holder.turns_started), **({"repeat_save": dict(repeat)} if repeat else {})})
    return True


def _give_back(engine: Any, holder: Any, key: str, condition: Any, reason: str) -> None:
    from .suppressed_effects import restore, saved_lifetime

    if not engine._remove_condition_instance(holder, key, "system:benefit_suppression",
            payload={"condition_id": SUPPRESSED, "instance_id": key, "reason": reason}, expected=condition):
        return
    data = condition.data or {}
    if data.get("kind") == "component":
        from .suppressed_effects import alive
        model = data.get("model") or {}
        parent = holder.conditions.get(model.get("instance_id"))
        if parent is not None and alive(engine, saved_lifetime(holder, condition)):
            _set_component(engine, holder, parent, str(model["path"]), model["value"], condition.source_definition_id)
        return
    restore(engine, holder, data.get("model") or {}, saved_lifetime(holder, condition), modifier=data.get("kind") == "modifier")
    if data.get("kind") == "condition":
        restored = holder.conditions.get((data.get("model") or {}).get("instance_id"))
        if restored is not None and (restored.data or {}).get("reaction_suppression_restore") is not None:
            engine._update_condition_data(holder, restored,
                {**restored.data, "reaction_suppression_restore": _unspent_reaction(holder, restored)}, condition.source_definition_id)
            holder.reaction_available = False


def _unspent_reaction(holder: Any, excluded: Any) -> bool:
    """An active denial may hold an unspent Reaction even while availability is false.

    The restored row's saved bit belongs to its old suppression, not the current
    Reaction. Only the holder and other live denials can supply the new bit.
    """
    return bool(holder.reaction_available or any(
        held is not excluded and (held.data or {}).get("reaction_suppression_restore")
        for held in holder.conditions.values()))


def _set_component(engine: Any, holder: Any, parent: Any, path: str, value: Any, source: str) -> None:
    import copy
    data = copy.deepcopy(parent.data or {})
    node = data
    keys = path.split(".")
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    if value is None:
        node.pop(keys[-1], None)
    else:
        node[keys[-1]] = value
    previous = parent.model_copy(deep=True) if path == "rule.no_reactions" else None
    if path == "rule.no_reactions":
        if value:
            data["reaction_suppression_restore"] = _unspent_reaction(holder, parent)
        else:
            # A suppressed field no longer owns a withheld Reaction. Reconcile
            # from its old snapshot, then discard the bit so later parent removal
            # cannot refund a Reaction spent during the suppression window.
            data.pop("reaction_suppression_restore", None)
    engine._update_condition_data(holder, parent, data, source)
    if path == "rule.no_reactions":
        if value:
            holder.reaction_available = False
        else:
            engine._reconcile_reaction_after_condition_removal(holder, [previous])


def suppress_component(engine: Any, owner: Any, holder: Any, instance_id: str, path: str,
                       until: str, source: str, label: str = "") -> bool:
    """Suppress exactly one field without removing its composite parent or companions.

    Reuses the ordinary suppression clock and marker. Absent fields are inert;
    restoration never creates an expired/replaced parent or overwrites siblings.
    """
    import copy
    from .suppressed_effects import lifetime
    parent = holder.conditions.get(instance_id)
    node = parent.data if parent is not None else {}
    for key in path.split("."):
        node = node.get(key) if isinstance(node, dict) else None
    if node is None:
        return False
    clock, value = lifetime(engine, holder, parent), copy.deepcopy(node)
    _set_component(engine, holder, parent, path, None, source)
    engine._apply_condition(holder, SUPPRESSED, source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": label or "One penalty is suppressed", "kind": "component",
                                  "model": {"instance_id": instance_id, "path": path, "value": value},
                                  "lifetime": clock, "until": until, "owner_turn": int(owner.turns_started),
                                  "holder_turn": int(holder.turns_started)})
    return True


def _rows(engine: Any) -> list[tuple[Any, str, Any]]:
    return [(holder, key, c) for holder in engine.state.actors.values() for key, c in list(holder.conditions.items()) if c.condition_id == SUPPRESSED]


@hook("turn_start")
def turn_restores(engine: Any, actor: Any) -> None:
    for holder, key, condition in _rows(engine):
        data = condition.data or {}
        if (data.get("until") == "owner_turn" and condition.source_actor_id == actor.entity_id) or \
                (data.get("until") == "holder_turn" and holder.entity_id == actor.entity_id):
            _give_back(engine, holder, key, condition, "DURATION_ENDED")


@hook("turn_end")
def turn_end_restores(engine: Any, actor: Any, *, nominal: bool = False) -> None:
    """"until the end of the holder's next turn": the holder's NEXT turn, not the one in progress when the effect was
    applied. ``holder_turn`` records how many turns the holder had already taken, so the row comes back at the end of
    the first turn after that -- which is the target's next turn whether the effect was applied before or after it."""
    from .effect_durations import custom_turn_due
    for holder, key, condition in _rows(engine):
        data = condition.data or {}
        if data.get("until") != "holder_turn_end" or holder.entity_id != actor.entity_id:
            continue
        if custom_turn_due(actor, int(data.get("holder_turn") or 0) + 1, holder.turn_flags, key, nominal=nominal):
            _give_back(engine, holder, key, condition, "DURATION_ENDED")


@hook("nominal_slot_boundary")
def nominal_benefits(engine: Any, actor: Any, checkpoint: str) -> None:
    if checkpoint == "START_OF_TURN":
        turn_restores(engine, actor)
    else:
        turn_end_restores(engine, actor, nominal=True)


@hook("turn_end")
def repeat_saves(engine: Any, actor: Any) -> None:
    for holder, key, condition in _rows(engine):
        rule = (condition.data or {}).get("repeat_save")
        if holder is not actor or not rule or not holder.active:
            continue
        roll = engine._roll_save(holder, str(rule["ability"]).upper(), int(rule["dc"]), condition.source_definition_id)
        if roll is not None and roll.total >= int(rule["dc"]):
            _give_back(engine, holder, key, condition, "SAVE_SUCCEEDED")


@hook("event")
def concentration_restores(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONCENTRATION_ENDED":
        return
    """Activation-specific: with two copies of the same technique (one current, one held), only the rows the ended
    copy made come back (combat/concentration.py copies/owner_copy/made_at, as Space Prison does). A single copy,
    or an ending without started_sequence, restores every row of that technique as before."""
    from ..concentration import copies, made_at, owner_copy

    event = kwargs.get("originating_event")
    source = kwargs.get("source_definition_id") or getattr(event, "source_definition_id", "")
    owner = engine.state.actors.get(kwargs.get("actor_id"))
    started = (kwargs.get("payload") or {}).get("started_sequence")
    starts = copies(owner, source, started) if owner is not None and started is not None else []
    for holder, key, condition in _rows(engine):
        if (condition.data or {}).get("until") == "concentration" and condition.source_actor_id == kwargs.get("actor_id") \
                and condition.source_definition_id == source:
            if len(starts) > 1 and owner_copy(made_at(key, condition), starts) != int(started):
                continue  # another, still-active copy of this technique made it
            _give_back(engine, holder, key, condition, "CONCENTRATION_ENDED")
