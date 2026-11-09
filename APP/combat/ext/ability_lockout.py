"""Ability lockout: one creature cannot use one named ability for a while, or pays a printed price if it uses it again (rider
lane C14, 2026-09-30; BLOCKED_CENSUS.md row 21). Shared helper module: the typed effect ``ability_lockout`` below (Technique-
Closing Point, Smothering Mandate, Flaw Within the Golden Technique); any plug-in may call ``used`` / ``last_used`` /
``triggering`` / ``lock``. (Unmaking's own "no Unmaking talents but Black Trace" self-lockout, unmaking_forms.unmaking_lockout,
is a sphere-wide one on the user and stays where it is.)

Which ability. The printed "same named spell, sphere talent, forged technique, monster action, or cultivation ability" is the
printed ability a compiled action resolves (ability_source.mechanic_of): an action compiled from a typed mechanic (it carries
``coverage`` / ``typing_status``). The table's own buttons (Dash, Hide, escapes, Attack an object, weapon and unarmed attacks,
summon commands) are not named abilities and are never locked. What a creature has used is read from the fight's own
INTENT_ACCEPTED events, so nothing extra is stored to remember it.

Record: ``condition:typed.ability_lockout`` on the creature (one per locked ability), filed under its user, ending at the printed
duration's expiry name. Data (JSON only):
  {"ability": mechanic id, "name": its display name, "mode": "barred" | "watch", "when": "before" | "after",
   "on_reuse": [typed rows] (watch only), "source": the locking action id, "label": plain text for the table}
"barred": the creature is not offered that ability (candidate_allowed) -- a player and the AI alike. "watch": it may use it, but its
first use before the record ends runs ``on_reuse`` (the locking user's rows, aimed at the creature) and ends the record --
"before": as the use is accepted, before it resolves (Technique-Closing Point: Disadvantage on the first attack roll of that
activation); "after": once it has resolved (resolution_final; Seal the Repetition's "immediately after the repeated ability
resolves").
Before-reuse NEXT_ATTACK modifiers belong only to that activation. Their exact IDs are tracked in a short-lived condition
and any unconsumed modifiers are removed at resolution_final; unrelated modifiers are left alone. The native transaction
rolls this tracking back along with the reuse on pause/error. Existing saved watch records use the same scope.

Typed effect:
  {"type": "ability_lockout", "applies_to": "target", "pick": "triggering" | "last_used" | "seen", "mode": "barred" | "watch",
   "when": "before" | "after", "on_reuse": [...], "duration": <a typed duration kind> | "expires_on": <name>,
   "excludes": ["domain", "path"]}
"triggering": the ability the creature is using right now (a Reaction to its technique); "last_used": the latest named ability it
used this fight; "seen": one it used this fight -- the user picks (the AI: the latest). "mode": "choose" only picks (before a save:
Technique-Closing Point's "Choose one ... you have seen the target use"), and the save's branches lock it with "pick": "chosen". "excludes": "domain" (an ability named a
Domain) and "path" (a Path, Subpath or Foundation feature) are never chosen. Nothing to pick: a plain log line, no record.
Inert: with no record on a creature, the hooks return at once.
"""
from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note

LOCKOUT = "condition:typed.ability_lockout"
ACTIVATION = "condition:typed.ability_lockout_activation"


# ------------------------------------------------------------------------------------------------ which ability
def key_of(action: Any) -> str:
    """The printed ability a compiled action resolves, or "" for the table's own buttons and attacks."""
    from .ability_source import mechanic_of

    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    if not (typed.get("coverage") or typed.get("typing_status")):
        return ""
    return mechanic_of(action)


def _excluded(engine: Any, action: Any, excludes: Any) -> bool:
    from .ability_source import is_path_or_subpath_feature

    excludes = set(excludes or ())
    typed = ((action.parameters or {}).get("typed") or {})
    if "domain" in excludes and "domain" in f"{action.display_name} {key_of(action)}".lower():
        return True
    return "path" in excludes and not typed.get("sphere") and (
        is_path_or_subpath_feature(key_of(action)) or "foundation." in key_of(action))


def used(engine: Any, creature: Any, excludes: Any = ()) -> list[tuple[str, str]]:
    """(ability key, catalog action id) of every named ability ``creature`` used this fight, latest first, one per ability."""
    seen: dict[str, str] = {}
    for event in reversed(engine.events):
        if event.event_type != "INTENT_ACCEPTED" or event.actor_id != creature.entity_id:
            continue
        action = engine.action_catalog.get(event.source_definition_id)
        key = key_of(action)
        if key and key not in seen and not _excluded(engine, action, excludes):
            seen[key] = event.source_definition_id
    return list(seen.items())


def last_used(engine: Any, creature: Any, excludes: Any = ()) -> tuple[str, str] | None:
    rows = used(engine, creature, excludes)
    return rows[0] if rows else None


def triggering(engine: Any, creature: Any) -> tuple[str, str] | None:
    """The named ability ``creature`` is using right now (its accepted action this transaction), if it is the one acting."""
    source = str(getattr(engine, "_active_action_source_id", "") or "")
    intent = getattr(engine, "_active_intent", None)
    if not source or (intent is not None and getattr(intent, "actor_id", None) != creature.entity_id):
        return None
    key = key_of(engine.action_catalog.get(source))
    return (key, source) if key else None


def records(creature: Any) -> list[Any]:
    return [c for c in creature.conditions.values() if c.condition_id == LOCKOUT]


def _drop(engine: Any, creature: Any, record: Any, reason: str) -> None:
    """Remove exactly this record (another ability's lockout on the same creature stays), with the ordinary removal event."""
    for iid, condition in list(creature.conditions.items()):
        if condition is record:
            del creature.conditions[iid]
            engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id,
                                 target_ids=(creature.entity_id,), payload={"condition_id": LOCKOUT, "instance_id": iid, "reason": reason})


# ------------------------------------------------------------------------------------------------ the record
def _effect_name(ctx: Any) -> str:
    return str(ctx.typed.get("effect_name") or ctx.action.display_name)


def lock(ctx: Any, creature: Any, key: str, action_id: str, row: dict[str, Any]) -> None:
    """Put one lockout record on ``creature`` for ability ``key`` (its catalog action ``action_id``), as ``ctx``'s user."""
    from ..typed_executor import effect_expiry

    engine = ctx.engine
    name = str(getattr(engine.action_catalog.get(action_id), "display_name", "") or key)
    mode = "watch" if row.get("mode") == "watch" else "barred"
    expires = effect_expiry(ctx, row, creature, condition=True) or "END_OF_HOLDER_NEXT_TURN"
    for old in records(creature):  # the same user locking the same ability again replaces it
        if (old.data or {}).get("ability") == key and old.source_actor_id == ctx.actor.entity_id:
            _drop(engine, creature, old, "REPLACED")
    source_name = _effect_name(ctx)
    label_text = (f"{source_name}: {creature.display_name} cannot use {name}" if mode == "barred" else
                  f"{source_name}: if {creature.display_name} uses {name} again, " + str(row.get("reuse_text") or "a price is paid"))
    label = label_text + f" ({_until_words(engine, expires, ctx.actor, creature)})"
    engine._apply_condition(creature, LOCKOUT, ctx.source, ctx.actor.entity_id, expires_on=expires,
                            data={"ability": key, "name": name, "mode": mode, "when": "before" if row.get("when") == "before" else "after",
                                  "on_reuse": copy.deepcopy(row.get("on_reuse") or []), "source": ctx.source, "label": label,
                                  "label_text": label_text, "source_name": source_name})
    note(engine, ctx.source, ctx.actor, label + ".", (creature,))


def _until_words(engine: Any, expires: str, source: Any = None, holder: Any = None) -> str:
    from .effect_durations import parse

    row = parse(expires)
    if row is None and source is not None:
        if expires == "START_OF_SOURCE_NEXT_TURN":
            row = ("start", source.entity_id, int(source.turns_started) + 1)
        elif expires.startswith("END_OF_SOURCE_TURN_AT:"):
            number = expires.rsplit(":", 1)[-1]
            if number.isdigit():
                row = ("end", source.entity_id, int(number))
    if row is None and expires == "END_OF_HOLDER_NEXT_TURN" and holder is not None:
        row = ("end", holder.entity_id, int(holder.turns_started) + (
            engine.state.current_actor_id != holder.entity_id))
    who = engine.state.actors.get(row[1]) if row else None
    if who is None:
        return "for now"
    started = int(who.turns_started)
    turn = "next turn" if row[2] == started + 1 else "turn" if row[2] == started else f"turn {row[2]}"
    return f"until the {row[0]} of {who.display_name}'s {turn}"


@effect("ability_lockout")
def ability_lockout(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject
    from .needle import CHOICE, ask, checkpoint_id

    for creature in _default_subject(ctx, row, harmful=True):
        if creature is None or not creature.active:
            continue
        pick = str(row.get("pick") or "last_used")
        memo = f"ability_lockout:{creature.entity_id}"
        if pick == "chosen":
            found = ctx.damage_cache.get(memo)
        elif pick == "triggering":
            found = triggering(ctx.engine, creature)
            found = found if found and not _excluded(ctx.engine, ctx.engine.action_catalog.get(found[1]), row.get("excludes")) else None
        elif pick == "seen":
            options = used(ctx.engine, creature, row.get("excludes"))
            found = options[0] if options else None
            if len(options) > 1:
                labels = {key: str(ctx.engine.action_catalog[action_id].display_name) for key, action_id in options}
                picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "ability_lockout", creature.entity_id), ctx.actor,
                             CHOICE + "ability_lockout", list(labels), labels=labels, preferred=[options[0][0]], target_id=creature.entity_id,
                             name=_effect_name(ctx),
                             prompt=f"{_effect_name(ctx)}, delivered by {ctx.action.display_name}: choose one ability you have seen "
                                    f"{creature.display_name} use this fight. This choice costs no extra action or resource.")
                found = next((row_ for row_ in options if picked and row_[0] == picked[0]), found)
        else:
            found = last_used(ctx.engine, creature, row.get("excludes"))
        if row.get("mode") == "choose":  # chosen before a save; the save's branches lock it with "pick": "chosen"
            ctx.damage_cache[memo] = found
        if found is None:
            if pick != "chosen":
                note(ctx.engine, ctx.source, ctx.actor, f"{_effect_name(ctx)}: {creature.display_name} has used no ability "
                     "it could lock.", (creature,))
            continue
        if row.get("mode") != "choose":
            lock(ctx, creature, found[0], tuple(found)[1], row)


# ------------------------------------------------------------------------------------------------ enforcing it
@hook("candidate_allowed")
def barred(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    rows = records(actor)
    if not rows or action is None:
        return None
    key = key_of(action)
    if key and any((c.data or {}).get("mode") == "barred" and (c.data or {}).get("ability") == key for c in rows):
        return False
    return None


def _run_reuse(engine: Any, creature: Any, record: Any) -> None:
    from .. import typed_executor
    from .effect_durations import token

    data = record.data or {}
    user = engine.state.actors.get(record.source_actor_id)
    action = engine.action_catalog.get(str(data.get("source") or record.source_definition_id))
    _drop(engine, creature, record, "USED")
    if user is None or action is None:
        return
    typed = copy.deepcopy((action.parameters or {}).get("typed") or {})
    ctx = typed_executor.Context(engine, user, action, getattr(engine, "_active_intent", None), typed, [creature], creature, {})
    note(engine, action.source_definition_id, user, f"{creature.display_name} uses {data.get('name')} again: {data.get('source_name') or action.display_name} "
         "takes effect.", (creature,))
    before = set(creature.modifiers)
    typed_executor.run_effects(ctx, copy.deepcopy(list(data.get("on_reuse") or [])))
    if data.get("when") == "before":
        ids = [mid for mid, modifier in creature.modifiers.items() if mid not in before
               and modifier.target_field == "attack_mode" and modifier.applies_to == "NEXT_ATTACK"]
        if ids:
            engine._apply_condition(creature, ACTIVATION, ctx.source, user.entity_id,
                                    expires_on=token("end", creature.entity_id, int(creature.turns_started)),
                                    data={"intent": str(engine._active_intent_id), "modifiers": ids})


def _finish_activation(engine: Any, creature: Any, intent: Any) -> None:
    """Remove only unused next-attack modifiers installed by this activation's before-reuse rows."""
    for iid, record in list(creature.conditions.items()):
        data = record.data or {}
        if record.condition_id != ACTIVATION or data.get("intent") != getattr(intent, "intent_id", None):
            continue
        for mid in data.get("modifiers") or []:
            modifier = creature.modifiers.pop(mid, None)
            if modifier is not None:
                engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=creature.entity_id,
                                     target_ids=(creature.entity_id,), payload={"modifier_id": mid, "reason": "ACTIVATION_ENDED"})
        del creature.conditions[iid]
        engine._append_event("CONDITION_REMOVED", record.source_definition_id, actor_id=record.source_actor_id,
                             target_ids=(creature.entity_id,), payload={"condition_id": ACTIVATION, "instance_id": iid,
                                                                      "reason": "ACTIVATION_ENDED"})


@hook("event")
def reused_before(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A watched ability being used again: "before" rows run as the use is accepted."""
    if event_type != "INTENT_ACCEPTED":
        return
    creature = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if creature is None or not records(creature) or not engine.events or engine.events[-1].event_type != event_type:
        return
    key = key_of(engine.action_catalog.get(engine.events[-1].source_definition_id))  # the event just recorded
    for record in records(creature):
        data = record.data or {}
        if key and data.get("mode") == "watch" and data.get("when") == "before" and data.get("ability") == key:
            _run_reuse(engine, creature, record)


@hook("resolution_final")
def reused_after(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    """A watched ability used again: "after" rows run once it has resolved."""
    if actor is not None:
        _finish_activation(engine, actor, intent)
    if actor is None or not records(actor):
        return
    key = key_of(action)
    for record in records(actor):
        data = record.data or {}
        if key and data.get("mode") == "watch" and data.get("when") != "before" and data.get("ability") == key:
            _run_reuse(engine, actor, record)


@hook("status_description")
def describe(engine: Any, holder: Any, row: Any, data: Any) -> dict[str, Any] | None:
    if (row or {}).get("condition_id") != LOCKOUT:
        return None
    data = data or {}
    source = engine.state.actors.get((row or {}).get("source_actor_id"))
    label = str(data.get("label_text") or data.get("label") or "An ability is locked.")
    text = label + f" ({_until_words(engine, str((row or {}).get('expires_on') or ''), source, holder)})"
    return {"text": text, "display_name": text,
            "source_ability": str(data.get("source_name") or
                getattr(engine.action_catalog.get(str(data.get("source") or "")), "display_name", "") or "")}
