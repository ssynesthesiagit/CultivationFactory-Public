"""Heaven-Answering Adaptive Body: Damage and Affliction Adaptations (rider lane C7, 2026-09-30: "i want everything we can
automated").

Owned rows: ``path_passive`` kind ``adaptation`` with ``role``: "damage" (Flesh Remembers Pain), "affliction" (Meridians
Remember Affliction), "ten_thousand" (Ten Thousand Answers), "lesson" (Return the Lesson). The records are one condition on
the owner, ``condition:typed.adaptations`` (lists of strings: adapted damage types and conditions, each with the creature
that caused it; round numbers for the once-per-round acquisitions).

Damage Adaptation   once per round after hostile damage of a type reaches the owner's Hit Points, that type is adapted until
                    the fight ends (1 kept; 3 with Ten Thousand Answers). At capacity the owner is asked at the start of its
                    next turn whether the newest replaces one (declining is legal; an AI owner replaces the oldest). While
                    adapted: the first packet of that type each round is reduced by Proficiency Bonus (Force/Psychic: twice
                    PB with Ten Thousand Answers, which also gives Resistance to the other adapted types). Flesh Remembers
                    Pain's Reaction only answers damage of an adapted type (row_allowed).
Affliction Adaptation  once per round after failing a hostile save that imposes Blinded, Charmed, Frightened, Paralyzed,
                    Poisoned, Restrained or Stunned, that condition is adapted (1 kept; 2 with Ten Thousand Answers; several
                    eligible or at capacity: asked at the owner's next turn start). While it bears the adapted condition: +PB
                    to saves made to end it (d20_bonus on a save from that condition's source), and at the end of its turn,
                    if the condition has no save of its own, it may spend 2 Stamina (asked, once per round) to repeat the
                    original save.
Return the Lesson   once per turn after hitting a creature recorded by an Adaptation, 1 Stamina (asked): +2d8 Force and one
                    result -- push 10 feet, no Reactions or Speed 0 until the start of its next turn, Disadvantage on its next
                    save against one of your Body Refining features before the end of your next turn, or move 10 feet
                    without provoking.
Everything is inert for a creature without these rows.
"""

from __future__ import annotations

from typing import Any

from . import hook, note

PREFIX = "tianxia.subpath.body.heaven_answering_adaptive_body.feature."
RECORD = "condition:typed.adaptations"
LESSON_SAVE = "condition:typed.lesson_save"
AFFLICTIONS = ("blinded", "charmed", "frightened", "paralyzed", "poisoned", "restrained", "stunned")
TYPES = ("ACID", "BLUDGEONING", "COLD", "FIRE", "FORCE", "LIGHTNING", "NECROTIC", "PIERCING", "POISON", "PSYCHIC", "RADIANT", "SLASHING", "THUNDER")


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
        return 3 if "ten_thousand" in roles else 1 if "damage" in roles else 0
    return 2 if "ten_thousand" in roles else 1 if "affliction" in roles else 0


def adapted_types(actor: Any) -> set[str]:
    return {str(row["type"]).upper() for row in _record(actor).get("damage") or []}


def _sync_resistance(engine: Any, actor: Any) -> None:
    """Ten Thousand Answers: Resistance to every adapted type but Force and Psychic, for as long as it stays adapted."""
    source = PREFIX + "ten_thousand_answers"
    want = {kind for kind in adapted_types(actor) if kind not in ("FORCE", "PSYCHIC")} if "ten_thousand" in _roles(engine, actor) else set()
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
        if actor is None or source is None or source.team_id == actor.team_id or _capacity(engine, actor, "damage") <= 0:
            continue
        data = _record(actor)
        if int(data.get("damage_round") or -1) == int(engine.state.round_number):
            continue
        data["damage_round"] = int(engine.state.round_number)
        rows = list(data.get("damage") or [])
        existing = next((row for row in rows if row["type"] == kind), None)
        if existing is not None:
            existing["by"] = by
        elif len(rows) < _capacity(engine, actor, "damage"):
            rows.append({"type": kind, "by": by})
        else:
            data["offer_damage"] = {"type": kind, "by": by}
        data["damage"] = rows
        _save_record(engine, actor, data, PREFIX + "flesh_remembers_pain")


@hook("after_save_resolved")
def affliction_adaptation(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    if subject is None or not failed or ctx.actor.team_id == subject.team_id or _capacity(ctx.engine, subject, "affliction") <= 0:
        return
    eligible = [name for name in AFFLICTIONS if name in set(named or ())]
    if not eligible:
        return
    data = _record(subject)
    if int(data.get("affliction_round") or -1) == int(ctx.engine.state.round_number):
        return
    data["affliction_round"] = int(ctx.engine.state.round_number)
    rows = list(data.get("afflictions") or [])
    known = {row["condition"] for row in rows}
    fresh = [name for name in eligible if name not in known]
    for row in rows:
        if row["condition"] in eligible:
            row["by"], row["source"] = ctx.actor.entity_id, ctx.source
    if fresh and len(fresh) == 1 and len(rows) < _capacity(ctx.engine, subject, "affliction"):
        rows.append({"condition": fresh[0], "by": ctx.actor.entity_id, "source": ctx.source})
    elif fresh:
        data["offer_afflictions"] = [{"condition": name, "by": ctx.actor.entity_id, "source": ctx.source} for name in fresh]
    data["afflictions"] = rows
    _save_record(ctx.engine, subject, data, PREFIX + "meridians_remember_affliction")


@hook("turn_start_choice")
def settle_offers(engine: Any, actor: Any) -> None:
    """A new Adaptation over capacity (or one of several eligible conditions) is decided at the owner's turn start."""
    data = _record(actor)
    if not data.get("offer_damage") and not data.get("offer_afflictions"):
        return
    from .needle import ask, checkpoint_id

    changed = False
    offer = data.pop("offer_damage", None)
    if offer and offer["type"] not in {row["type"] for row in data.get("damage") or []}:
        rows = list(data.get("damage") or [])
        options = [row["type"] for row in rows]
        picked = ask(engine, _intent(engine), checkpoint_id(engine, "adapt_damage", actor.entity_id), actor, "choice:needle.adapt_damage",
                     options, allow_decline=True, preferred=options[:1], labels={o: f"Replace {o.title()} with {offer['type'].title()}" for o in options},
                     prompt=f"Flesh Remembers Pain: {actor.display_name} may adapt to {offer['type'].title()} damage by replacing one Damage Adaptation.",
                     target_id=actor.entity_id)
        if picked:
            data["damage"] = [offer if row["type"] == picked[0] else row for row in rows]
        changed = True
    offers = data.pop("offer_afflictions", None) or []
    if offers:
        rows = list(data.get("afflictions") or [])
        options = [f"{new['condition']}>{old['condition']}" for new in offers for old in rows] if len(rows) >= _capacity(engine, actor, "affliction") \
            else [f"{new['condition']}>" for new in offers]
        picked = ask(engine, _intent(engine), checkpoint_id(engine, "adapt_affliction", actor.entity_id), actor, "choice:needle.adapt_affliction",
                     options, allow_decline=True, preferred=options[:1],
                     labels={o: (f"Adapt to {o.split('>')[0].title()}" + (f", replacing {o.split('>')[1].title()}" if o.split(">")[1] else "")) for o in options},
                     prompt=f"Meridians Remember Affliction: choose {actor.display_name}'s Affliction Adaptation.", target_id=actor.entity_id)
        if picked:
            new_name, old_name = picked[0].split(">")
            new = next(row for row in offers if row["condition"] == new_name)
            data["afflictions"] = [row for row in rows if row["condition"] != old_name] + [new]
        changed = True
    if changed:
        _save_record(engine, actor, data, PREFIX + "flesh_remembers_pain")


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
    amount = 2 * pb if kind in ("FORCE", "PSYCHIC") and "ten_thousand" in _roles(engine, target) else pb
    if applied:
        target.turn_flags[flag] = int(engine.state.round_number)
    return amount


@hook("row_allowed")
def adapted_reaction(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """Flesh Remembers Pain's Reaction answers only damage of an adapted type."""
    if str(row.get("feature_id") or "") != PREFIX + "flesh_remembers_pain":
        return None
    kind = str(getattr(engine, "_typed_pending_damage_type", None) or "").upper()
    return None if kind in adapted_types(actor) else False


@hook("d20_bonus")
def end_the_affliction(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    """+Proficiency Bonus to a save made to end the adapted condition (a save from the source of the condition it bears)."""
    if not str(roll.reason).startswith("SAVE:"):
        return None
    actor = engine.state.actors.get(roll.actor_id)
    if actor is None:
        return None
    rows = _record(actor).get("afflictions") or []
    source = str(roll.reason).split(":", 1)[1].rsplit(":", 1)[0]
    if any(c.condition_id == "condition:typed." + row["condition"] and c.source_definition_id == source
           for row in rows for c in actor.conditions.values()):
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
                 prompt=f"Return the Lesson: {ctx.action.display_name} hit {target.display_name}; spend 1 Stamina for +2d8 Force and one result?")
    if not picked:
        return
    actor.turn_flags["_round_return_lesson"] = stamp
    engine._spend_resource(actor, "resource:core.stamina", 1, PREFIX + "return_the_lesson")
    from .. import typed_executor as te

    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    rows = [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["force"],
             "evidence": "Return the Lesson: +2d8 Force"}]
    choice = picked[0]
    if choice == "push":
        rows.append({"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"})
    elif choice == "no_reactions":
        rows.append({"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_next_turn"})
    elif choice == "speed":
        rows.append({"type": "speed", "applies_to": "target", "becomes": 0, "expires_on": "START_OF_TARGET_NEXT_TURN"})
    te.run_effects(sub, rows)
    if choice == "save" and target.active:
        engine._apply_condition(target, LESSON_SAVE, PREFIX + "return_the_lesson", actor.entity_id,
                                expires_on=f"END_OF_SOURCE_TURN_AT:{int(actor.turns_started) + 1}",
                                data={"label": f"Disadvantage on its next save against {actor.display_name}'s Body Refining features"})
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
    if held is None or not (source.startswith("tianxia.subpath.body.") or source.startswith("tianxia.path.body_refining")):
        return None
    subject.conditions.pop(held.instance_id)
    ctx.engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                             payload={"condition_id": LESSON_SAVE, "instance_id": held.instance_id, "reason": "CONSUMED"})
    return {"bonus": 0, "modes": ["DISADVANTAGE"]}
