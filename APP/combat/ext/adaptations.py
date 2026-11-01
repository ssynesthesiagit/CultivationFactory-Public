"""Heaven-Answering Adaptive Body: Damage and Affliction Adaptations (rider lane C7, 2026-09-30: "i want everything we can
automated").

Owned rows: ``path_passive`` kind ``adaptation`` with ``role``: "damage" (Flesh Remembers Pain), "affliction" (Meridians
Remember Affliction), "ten_thousand" (Ten Thousand Answers), "lesson" (Return the Lesson). The records are one condition on
the owner, ``condition:typed.adaptations`` (lists of strings: adapted damage types and conditions, each with the creature
that caused it; round numbers for the once-per-round acquisitions).

Damage Adaptation   once per round after hostile damage of a type reaches the owner's Hit Points, that type is adapted until
                    the fight ends (1 kept; 3 with Ten Thousand Answers). At capacity the owner is asked immediately
                    whether the newest replaces one (declining is legal; an AI owner replaces the oldest). While
                    adapted: the first packet of that type each round is reduced by Proficiency Bonus (Force/Psychic: twice
                    PB with Ten Thousand Answers, which also gives Resistance to the other adapted types). Flesh Remembers
                    Pain's Reaction only answers damage of an adapted type (row_allowed).
Affliction Adaptation  once per round after failing a hostile save that imposes Blinded, Charmed, Frightened, Paralyzed,
                    Poisoned, Restrained or Stunned, that condition is adapted (1 kept; 2 with Ten Thousand Answers; several
                    eligible or at capacity: selected immediately). While it bears the adapted condition: +PB
                    to saves made to end it (d20_bonus on a save from that condition's source), and at the end of its turn,
                    if the condition has no save of its own, it may spend 2 Stamina (asked, once per round) to repeat the
                    original save.
Return the Lesson   once per turn after hitting a creature recorded by an Adaptation, 1 Stamina (asked): +2d8 Force and one
                    result -- push 10 feet, no Reactions or Speed 0 until the start of its next turn, Disadvantage on its next
                    save against one of your Body Refining features before the end of your next turn, or move 10 feet
                    without provoking.
Shared public helpers: acquire is used by d20_rewrite_rules to persist a chosen
Affliction Adaptation even when Perfect Counter-Evolution's reroll succeeds.
ending_save_scope is shared with repeat_saves for explicit saves made to end a
condition. Native repeats enter the same scope through repeat_save_scope.
Everything is inert for a creature without these rows.
"""

from __future__ import annotations

from typing import Any
from contextlib import contextmanager
from contextvars import ContextVar

_ENDING_SAVE = ContextVar("adaptation_ending_save", default=None)

from . import hook, note

PREFIX = "tianxia.subpath.body.heaven_answering_adaptive_body.feature."
RECORD = "condition:typed.adaptations"
LESSON_SAVE = "condition:typed.lesson_save"
AFFLICTIONS = ("blinded", "charmed", "frightened", "paralyzed", "poisoned", "restrained", "stunned")
TYPES = ("ACID", "BLUDGEONING", "COLD", "FIRE", "FORCE", "LIGHTNING", "NECROTIC", "PIERCING", "POISON", "PSYCHIC", "RADIANT", "SLASHING", "THUNDER")
COUNTER = PREFIX + "perfect_counter_evolution"
COUNTER_ROUND = "_round_counter_evolution"


def _roles(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    return {str(row.get("role")): row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == "adaptation"}


def _record(actor: Any) -> dict[str, Any]:
    held = next((c for c in actor.conditions.values() if c.condition_id == RECORD), None)
    return dict((held.data or {}) if held is not None else {})


def _save_record(engine: Any, actor: Any, data: dict[str, Any], source: str) -> None:
    held = next((c for c in actor.conditions.values() if c.condition_id == RECORD), None)
    if held is not None:
        actor.conditions.pop(held.instance_id)
        engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": RECORD, "instance_id": held.instance_id})
    kinds = [row["type"].title() for row in data.get("damage") or []]
    afflictions = [row["condition"].title() for row in data.get("afflictions") or []]
    data["label"] = "Adapted to " + ", ".join(kinds + afflictions) if kinds or afflictions else "Adaptations: none yet"
    engine._apply_condition(actor, RECORD, source, actor.entity_id, expires_on="UNTIL_REMOVED", data=data)
    _sync_resistance(engine, actor)


def _capacity(engine: Any, actor: Any, kind: str) -> int:
    roles = _roles(engine, actor)
    if kind == "damage":
        return 3 if {"ten_thousand", "counter"}.intersection(roles) else 1 if "damage" in roles else 0
    return 2 if {"ten_thousand", "counter"}.intersection(roles) else 1 if "affliction" in roles else 0


def acquire(engine: Any, actor: Any, category: str, record: dict[str, Any], *, source: str) -> None:
    """Record one selected Adaptation immediately, with an explicit replacement choice at capacity."""
    from .needle import ask, checkpoint_id

    data = _record(actor)
    key = "type" if category == "damage" else "condition"
    rows = list(data.get(category) or [])
    existing = next((row for row in rows if row[key] == record[key]), None)
    if existing is not None:
        existing.update(record)
    elif len(rows) < _capacity(engine, actor, category):
        rows.append(record)
    else:
        options = [row[key] for row in rows]
        picked = ask(engine, _intent(engine), checkpoint_id(engine, "adapt_replace_" + category, actor.entity_id),
                     actor, "choice:needle.adapt_replace_" + category, options, allow_decline=source != COUNTER,
                     labels={o: f"Replace {o.title()} with {record[key].title()}" for o in options},
                     prompt=f"{actor.display_name}: choose which Adaptation to replace with {record[key].title()}.")
        if not picked:
            return
        rows = [record if row[key] == picked[0] else row for row in rows]
    data[category] = rows
    _save_record(engine, actor, data, source)


@hook("before_damage_defenses")
def adaptation_response(engine: Any, actor: Any, amount: int, kind: str, source: Any, by: Any) -> list[dict[str, Any]] | None:
    from .needle import ask, checkpoint_id
    from ..typed_reactions import spend_reaction, can_use_reaction

    roles = _roles(engine, actor)
    attacker = engine.state.actors.get(by)
    if kind not in TYPES or not actor.reaction_available or (attacker is not None and attacker.team_id == actor.team_id):
        return None
    new = kind not in adapted_types(actor)
    counter = new and "counter" in roles and actor.turn_flags.get(COUNTER_ROUND) != engine.state.round_number
    flesh = not new and "damage" in roles and actor.turn_flags.get("_round_flesh_response") != engine.state.round_number
    if not counter and not flesh:
        return None
    feature = COUNTER if counter else PREFIX + "flesh_remembers_pain"
    price = 2 if counter else 1
    if (actor.resources.get("resource:core.stamina", 0) < price
            or not can_use_reaction(engine, actor, attacker, {"feature_id": feature, "adaptation_response": True})):
        return None
    chosen = ask(engine, _intent(engine), checkpoint_id(engine, "adapt_response", actor.entity_id), actor,
                 "choice:needle.adapt_response", ["use"], allow_decline=True,
                 labels={"use": f"Spend {price} Stamina and your Reaction"},
                 prompt=f"{'Perfect Counter-Evolution' if counter else 'Flesh Remembers Pain'}: {actor.display_name} faces {kind.title()} damage. Spend {price} Stamina and your Reaction to {'adapt before it lands' if counter else 'gain Resistance for this damage'}?")
    if not chosen:
        return None
    engine._spend_resource(actor, "resource:core.stamina", price, feature)
    spend_reaction(engine, actor, {"feature_id": feature, "adaptation_response": True})
    actor.turn_flags[COUNTER_ROUND if counter else "_round_flesh_response"] = engine.state.round_number
    if counter:
        acquire(engine, actor, "damage", {"type": kind, "by": by or ""}, source=feature)
    engine._append_event("REACTION_RESOLVED", feature, actor_id=actor.entity_id,
                         target_ids=(actor.entity_id,), payload={"checkpoint": "BEFORE_DAMAGE_DEFENSES", "damage_type": kind})
    # Counter's CL14 benefit is synchronized by acquire; Force/Psychic get only
    # their normal first-instance flat reduction, never packet Resistance.
    return [] if counter else [{"kind": "resistance"}]


def adapted_types(actor: Any) -> set[str]:
    return {str(row["type"]).upper() for row in _record(actor).get("damage") or []}


def _sync_resistance(engine: Any, actor: Any) -> None:
    """Ten Thousand Answers: Resistance to every adapted type but Force and Psychic, for as long as it stays adapted."""
    source = PREFIX + "ten_thousand_answers"
    want = {kind for kind in adapted_types(actor) if kind not in ("FORCE", "PSYCHIC")} if {"ten_thousand", "counter"}.intersection(_roles(engine, actor)) else set()
    have = {m.value: mid for mid, m in actor.modifiers.items() if m.source_definition_id == source and m.target_field == "damage_resistance"}
    for kind, mid in have.items():
        if kind not in want:
            del actor.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"modifier_id": mid, "reason": "ADAPTATION_REPLACED"})
    for kind in sorted(want - set(have)):
        engine._add_modifier(actor, source, "damage_resistance", "ADD", kind, "SELF", expires_on="UNTIL_REMOVED")


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


# ------------------------------------------------------------------------------------------------- acquiring records
@hook("event")
def damage_adaptation(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    kind = str(payload.get("damage_type") or "").upper()
    by = str(kwargs.get("actor_id") or "")
    if int(payload.get("hp_damage") or 0) < 1 or kind not in TYPES or payload.get("gate_damage"):
        return
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        source = engine.state.actors.get(by)
        if actor is None or (source is not None and source.team_id == actor.team_id) or _capacity(engine, actor, "damage") <= 0:
            continue
        data = _record(actor)
        if int(data.get("damage_round") or -1) == int(engine.state.round_number):
            continue
        data["damage_round"] = int(engine.state.round_number)
        _save_record(engine, actor, data, PREFIX + "flesh_remembers_pain")
        acquire(engine, actor, "damage", {"type": kind, "by": by}, source=PREFIX + "flesh_remembers_pain")


@hook("save_effects_settled")
def affliction_adaptation(ctx: Any, subject: Any, ability: str, failed: bool) -> None:
    if (subject is None or not failed or not ctx.origin_save or ctx.actor.team_id == subject.team_id
            or _capacity(ctx.engine, subject, "affliction") <= 0):
        return
    eligible = sorted({c.condition_id.removeprefix("condition:typed.") for c in subject.conditions.values()
                       if c.condition_id.removeprefix("condition:typed.") in AFFLICTIONS
                       and c.source_definition_id == ctx.source and c.applied_sequence > int(ctx.damage_cache.get("adapt_save_start", 0))})
    if not eligible:
        return
    data = _record(subject)
    if int(data.get("affliction_round") or -1) == int(ctx.engine.state.round_number):
        return
    from .needle import ask, checkpoint_id
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "adapt_affliction", subject.entity_id), subject,
                 "choice:needle.adapt_affliction", eligible, preferred=eligible[:1], labels={name:name.title() for name in eligible},
                 prompt=f"Meridians Remember Affliction: choose {subject.display_name}'s Affliction Adaptation from the conditions this save imposed.")
    if not picked:
        return
    data["affliction_round"] = int(ctx.engine.state.round_number)
    _save_record(ctx.engine, subject, data, PREFIX + "meridians_remember_affliction")
    acquire(ctx.engine, subject, "afflictions", {"condition": picked[0], "by": ctx.actor.entity_id,
            "source": ctx.source, **ctx.origin_save}, source=PREFIX + "meridians_remember_affliction")


@hook("after_save_resolved")
def remember_save_start(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    # The shared damage cache is resolution-local and copied into this save's
    # outcome context. Only newly applied conditions qualify for acquisition.
    ctx.damage_cache["adapt_save_start"] = ctx.engine.state.event_sequence


# -------------------------------------------------------------------------------------------------------- benefits
@hook("damage_reduction")
def first_instance(engine: Any, target: Any, damage_type: str, typed: Any, source_actor_id: Any, applied: bool = False) -> int | None:
    kind = str(damage_type).upper()
    if kind not in adapted_types(target):
        return None
    flag = "_round_adapted_first_" + kind
    if target.turn_flags.get(flag) == int(engine.state.round_number):
        return None
    pb = int(_roles(engine, target).get("damage", {}).get("pb") or target.proficiency_bonus or 2)
    amount = 2 * pb if kind in ("FORCE", "PSYCHIC") and {"ten_thousand", "counter"}.intersection(_roles(engine, target)) else pb
    if applied:
        target.turn_flags[flag] = int(engine.state.round_number)
    return amount


@hook("row_allowed")
def adapted_reaction(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """Flesh Remembers Pain's Reaction answers only damage of an adapted type."""
    if str(row.get("feature_id") or "") not in {PREFIX + "flesh_remembers_pain", COUNTER}:
        return None
    if row.get("adaptation_response"):
        return None
    return False if row.get("effects") else None  # generic damage rows only; d20 windows remain legal


@contextmanager
def ending_save_scope(engine: Any, actor: Any, condition: Any):
    """Bound ending-save provenance; native repeats and Meridians' own repeat share it."""
    token = _ENDING_SAVE.set((engine, actor.entity_id, condition.condition_id, condition.source_definition_id))
    try:
        yield
    finally:
        _ENDING_SAVE.reset(token)


@hook("repeat_save_scope")
def native_ending_scope(engine: Any, resolution: dict[str, Any]) -> Any:
    actor = engine.state.actors.get(resolution["holder_id"])
    condition = actor.conditions.get(resolution["instance_id"]) if actor else None
    return ending_save_scope(engine, actor, condition) if condition is not None else None


@hook("d20_bonus")
def end_the_affliction(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    ending = _ENDING_SAVE.get()
    if not ending or ending[0] is not engine or ending[1] != roll.actor_id or not str(roll.reason).startswith("SAVE:"):
        return None
    actor = engine.state.actors.get(roll.actor_id)
    if actor is not None and any("condition:typed." + row["condition"] == ending[2]
                                 for row in _record(actor).get("afflictions") or []):
        return {"source_id": PREFIX + "meridians_remember_affliction", "bonus": int(actor.proficiency_bonus or 2)}
    return None


@hook("turn_end")
def repeat_without_a_save(engine: Any, actor: Any) -> None:
    rows = _record(actor).get("afflictions") or []
    if not rows or actor.resources.get("resource:core.stamina", 0) < 2 or actor.turn_flags.get("_round_meridian_repeat") == int(engine.state.round_number):
        return
    from .repeat_saves import save_of

    held = [(iid, c) for row in rows for iid, c in actor.conditions.items() if c.condition_id == "condition:typed." + row["condition"]
            and not (c.data or {}).get("repeat_save") and save_of(c) is not None]
    if not held:
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, _intent(engine), checkpoint_id(engine, "meridian_repeat", actor.entity_id), actor, "choice:needle.meridian_repeat",
                 [iid for iid, _c in held], allow_decline=True, labels={iid: f"Spend 2 Stamina: repeat the save against {c.condition_id.rsplit('.', 1)[-1].title()}"
                                                                        for iid, c in held},
                 prompt=f"Meridians Remember Affliction: {actor.display_name} may spend 2 Stamina to repeat the original save.", target_id=actor.entity_id)
    if not picked:
        return
    iid, condition = next(pair for pair in held if pair[0] == picked[0])
    actor.turn_flags["_round_meridian_repeat"] = int(engine.state.round_number)
    engine._spend_resource(actor, "resource:core.stamina", 2, PREFIX + "meridians_remember_affliction")
    save = save_of(condition)
    with ending_save_scope(engine, actor, condition):
        roll = engine._roll_save(actor, str(save["ability"]).upper(), int(save["dc"]), condition.source_definition_id)
    if roll is not None and roll.total >= int(save["dc"]) and iid in actor.conditions:
        actor.conditions.pop(iid)
        engine._append_event("CONDITION_REMOVED", PREFIX + "meridians_remember_affliction", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": iid, "repeat_save": True})


# ------------------------------------------------------------------------------------------------- Return the Lesson
def _teachers(actor: Any) -> set[str]:
    data = _record(actor)
    return {row["by"] for row in [*(data.get("damage") or []), *(data.get("afflictions") or [])] if row.get("by")}


@hook("after_hit")
def return_the_lesson(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active or "lesson" not in _roles(engine, actor) or target.entity_id not in _teachers(actor):
        return
    stamp = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    if actor.turn_flags.get("_round_return_lesson") == stamp or actor.resources.get("resource:core.stamina", 0) < 1:
        return
    from .needle import ask, checkpoint_id

    options = {"push": f"Push {target.display_name} 10 feet", "no_reactions": f"{target.display_name} takes no Reactions until the start of its next turn",
               "speed": f"{target.display_name}'s Speed is 0 until the start of its next turn",
               "save": f"{target.display_name} has Disadvantage on its next save against your Body Refining features",
               "move": "Move 10 feet without provoking"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "return_lesson", target.entity_id), actor, "choice:needle.return_lesson", list(options),
                 allow_decline=True, labels=options, target_id=target.entity_id,
                 prompt=f"Return the Lesson: {ctx.action.display_name} hit {target.display_name}; spend 1 Stamina for +{4 if 'counter' in _roles(engine, actor) else 2}d8 Force and one result?")
    if not picked:
        return
    actor.turn_flags["_round_return_lesson"] = stamp
    engine._spend_resource(actor, "resource:core.stamina", 1, PREFIX + "return_the_lesson")
    from .. import typed_executor as te

    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    rows = [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 4 if "counter" in _roles(engine, actor) else 2, "sides": 8}, "damage_types": ["force"],
             "evidence": "Return the Lesson: +2d8 Force"}]
    choice = picked[0]
    if choice == "push":
        rows.append({"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"})
    elif choice == "no_reactions":
        rows.append({"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"})
    elif choice == "speed":
        rows.append({"type": "speed", "applies_to": "target", "becomes": 0, "expires_on": "START_OF_TARGET_NEXT_TURN"})
    te.run_effects(sub, rows)
    if choice == "save" and target.active:
        features = {str((a.parameters.get("typed") or {}).get("source") or ""): a.display_name
                    for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                    and str((a.parameters.get("typed") or {}).get("source") or "").startswith(("tianxia.subpath.body.", "tianxia.path.body_refining"))}
        feature = ask(engine, ctx.intent, checkpoint_id(engine, "lesson_feature", target.entity_id), actor,
                      "choice:needle.lesson_feature", sorted(features), labels=features,
                      prompt=f"Return the Lesson: name your Body Refining feature for {target.display_name}'s next saving throw.")
        if not feature:
            return
        engine._apply_condition(target, LESSON_SAVE, PREFIX + "return_the_lesson", actor.entity_id,
                                expires_on=f"END_OF_SOURCE_TURN_AT:{int(actor.turns_started) + 1}",
                                data={"feature": feature[0], "label": f"Disadvantage on its next save against {features[feature[0]]}"})
    elif choice == "move":
        from .rider_movement import routes, step

        paths = routes(engine, actor, 10)
        if paths:
            where = ask(engine, ctx.intent, checkpoint_id(engine, "return_lesson_move", actor.entity_id), actor, "choice:needle.return_lesson_move",
                        sorted(paths), allow_decline=True, labels={k: "Move to " + k.removeprefix("cell:") for k in paths},
                        prompt=f"Return the Lesson: {actor.display_name} may move up to 10 feet without provoking.", target_id=actor.entity_id)
            if where and where[0] in paths:
                step(engine, actor, paths[where[0]], PREFIX + "return_the_lesson")


@hook("save")
def lesson_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    held = next((c for c in subject.conditions.values() if c.condition_id == LESSON_SAVE and c.source_actor_id == ctx.actor.entity_id), None) \
        if subject is not None else None
    source = str(ctx.typed.get("source") or ctx.source)
    if held is None or source != held.data.get("feature"):
        return None
    subject.conditions.pop(held.instance_id)
    ctx.engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                             payload={"condition_id": LESSON_SAVE, "instance_id": held.instance_id, "reason": "CONSUMED"})
    return {"bonus": 0, "modes": ["DISADVANTAGE"]}
