"""Shared helper module: combat/ext/qi_path.py uses repeat_one_effect.

Chosen afflictions that last together (owner 2026-09-29: "i want everything we can automated"; combat/ext/menus.py).

Shared public helper: consumed by qi_path.py (repeat_one_effect). Its exported functions are
the stable cross-plugin API; private helpers stay private.

"Failed Save: Choose two symptoms. The symptoms last for the duration. At the end of each of the target's turns, it repeats the
saving throw, ending both symptoms on itself on a success" (Symptom Cascade), "Choose two Venom Effects ... ending all Venom
Effects from this talent on a success" (Five-Venom Formula), "Choose three seals ... ending one seal of its choice on a success"
(Nine-Bell Meridian Palm).  The picks come from the ability's choose-N menu (menus.py); what makes them ONE thing is that a
single repeat saving throw ends them (all of them, or one of them), so the picks are put on the target as ONE condition
("condition:typed.affliction") that carries everything the picks do:

    {"type": "affliction", "applies_to": "target", "menu": "<menu id>", "duration": "concentration",
     "repeat_save": {"ability": "con", "ends": "all"|"one"},           # optional: the repeat saving throw at the end of its turns
     "menu_success": true,                                             # "Successful Save: choose one" -- the first pick only
     "parts": {"<option label>": {"rule": {...}, "speed": -20, "ac": -1, "healing_minus": "pb",
                                  "periodic": {"dice": {"count": 2, "sides": 8}, "types": ["necrotic"]}}}}

What a part may carry (each is read where the engine already reads it; nothing here rolls a save or damage on its own account
except the two turn hooks below):
- ``rule``: a condition rule row (combat/typed_executor.py condition_rules): ``no_reactions``, ``attacks_have``, ``save_mode``
  ({"DEX": "DISADVANTAGE"}), ``concentration_mode``.  Rules of several picks are merged.
- ``speed`` / ``ac``: feet / points added (negative reduces) -- the ``speed`` and ``ac`` hooks read them.
- ``healing_minus``: "pb" or a number taken off each healing it receives (typed_executor._reduced_healing reads the rule row).
- ``periodic``: dice of damage taken at the start of each of its turns (the ``turn_start`` hook below).
- ``start_effects``: reviewed typed effect rows resolved on the holder at each turn
  start by the original caster; stored only with the selected part.
- ``next_concentration``: ADVANTAGE or DISADVANTAGE on the next Concentration
  save while that part remains; its consumed state survives repeat-one saves.

"ends: all" is the engine's own repeat saving throw on the one condition (gate2_engine, ``data.repeat_save``): a success removes
the condition, so every pick ends with it.  "ends: one" is rolled here at the end of its turn (``turn_end``): a success takes
off one pick -- the first still there in the order printed, since nothing printed says which the target would choose -- and
the rest stay.  Concentration, the start of the applier's next turn and the rest end the whole condition, as for any condition.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, menus

NAME = "affliction"


def condition_id() -> str:
    from ..typed_executor import CONDITION_PREFIX

    return CONDITION_PREFIX + NAME


def merged(chosen: list[str], parts: dict[str, Any], pb: int) -> dict[str, Any]:
    """What the picked parts add up to: {"rule", "speed", "ac", "periodic", "parts"} for the condition's data."""
    rule: dict[str, Any] = {}
    speed = ac = 0
    periodic: list[dict[str, Any]] = []
    for label in chosen:
        part = parts.get(label) or {}
        for key, value in (part.get("rule") or {}).items():
            if isinstance(value, dict):
                rule[key] = {**(rule.get(key) or {}), **value}
            else:
                rule[key] = value
        speed += int(part.get("speed") or 0)
        ac += int(part.get("ac") or 0)
        minus = part.get("healing_minus")
        if minus:
            rule["healing_minus"] = int(rule.get("healing_minus") or 0) + (pb if minus == "pb" else int(minus))
        if part.get("periodic"):
            periodic.append({"label": label, **copy.deepcopy(part["periodic"])})
    return {"rule": rule, "speed": speed, "ac": ac, "periodic": periodic}


def _data(chosen: list[str], parts: dict[str, Any], pb: int, name: str, menu_id: str) -> dict[str, Any]:
    return {**merged(chosen, parts, pb), "menu": menu_id, "picks": list(chosen), "parts": {label: parts.get(label) or {} for label in chosen},
            "pb": pb, "name": name, "label": f"{name}: {'; '.join(chosen)}"}


def _chosen(ctx: Any, eff: dict[str, Any]) -> list[str]:
    menu_id = str(eff.get("menu"))
    chosen = menus.picks(ctx.engine, ctx.actor, menu_id)
    if not eff.get("menu_success"):
        return chosen
    menu = menus.catalog(ctx.engine).get(menu_id) or {}
    allowed = menu.get("success_options") or menu.get("options") or []
    if eff.get("choose_success"):
        from .rider_choices import pick
        return pick(ctx.engine, ctx.actor, str(eff.get("menu")) + "_success", str(eff.get("name") or "Symptoms"),
                    list(allowed), labels=eff.get("choice_labels"), subject=ctx.target, optional=False,
                    trigger="The target succeeded on its saving throw; choose one symptom until the start of your next turn",
                    preferred=chosen[:1])
    first = next((label for label in allowed if label in chosen), None)  # "Successful Save: Choose one": the first pick, as menus.picked
    return [first] if first else []


@effect("affliction")
def run_affliction(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te

    chosen = _chosen(ctx, eff)
    if not chosen:
        return
    menu = menus.catalog(ctx.engine).get(str(eff.get("menu"))) or {}
    parts = eff.get("parts") or {}
    pb = int(ctx.numbers.get("pb") or 2)
    for subject in te._default_subject(ctx, eff, harmful=True):
        if not subject.active:
            continue
        data = _data(chosen, parts, pb, str(eff.get("name") or menu.get("name") or "Afflictions"), str(eff.get("menu")))
        if any((parts.get(label) or {}).get("next_concentration") for label in chosen):
            data["affliction_token"] = f"{ctx.source}:{ctx.engine.state.event_sequence + 1}"
        repeat = eff.get("repeat_save")
        if repeat:
            check = {"ability": str(repeat.get("ability") or "con").upper(), "dc": int(ctx.numbers.get("save_dc") or 10)}
            if repeat.get("ends") == "one" and len(chosen) > 1:
                data["repeat_one"] = check
                if repeat.get("choice"):
                    data["repeat_one_choice"] = True
            else:  # one pick, or all of them: the engine's own repeat saving throw removes the condition
                data["repeat_save"] = {**check, "when": repeat.get("when", "end")}
        expires = te.effect_expiry(ctx, eff, subject, condition=True) or "END_OF_HOLDER_NEXT_TURN"
        for iid, old in list(subject.conditions.items()):  # the same ability again replaces what it put on before
            if old.condition_id == condition_id() and old.source_actor_id == ctx.actor.entity_id and (old.data or {}).get("menu") == data["menu"]:
                ctx.engine._remove_condition_instance(subject, iid, ctx.source, actor_id=ctx.actor.entity_id,
                    payload={"condition_id": old.condition_id, "instance_id": iid}, expected=old)
        ctx.engine._apply_condition(subject, condition_id(), ctx.source, ctx.actor.entity_id, expires_on=expires, data=data)
        if data["rule"].get("no_reactions"):
            subject.reaction_available = False  # as typed_executor.block_condition does for a condition that takes Reactions
        _companions(ctx.engine, subject, data, ctx.source, ctx.actor.entity_id, expires)


def _companions(engine: Any, actor: Any, data: dict[str, Any], source: str, setter: str, expires: str) -> None:
    from .effect_durations import apply_condition_preserving_clock
    from ..typed_executor import CONDITION_PREFIX

    chosen, parts = data["picks"], data["parts"]
    parent = next((c for c in actor.conditions.values() if c.condition_id == condition_id()
                   and c.source_definition_id == source and c.source_actor_id == setter
                   and (c.data or {}).get("menu") == data["menu"]), None)
    for companion in {c for label in chosen for c in (parts.get(label) or {}).get("companions") or []}:
        apply_condition_preserving_clock(engine, actor, parent, CONDITION_PREFIX + companion, source, setter, expires_on=expires,
                                data={"companion_of": NAME, "companion_menu": data["menu"]})
    token = data.get("affliction_token")
    if token and not actor.turn_flags.get("affliction_round_concentration_used:" + token):
        for label in chosen:
            mode = (parts.get(label) or {}).get("next_concentration")
            if mode in ("ADVANTAGE", "DISADVANTAGE"):
                apply_condition_preserving_clock(engine, actor, parent, CONDITION_PREFIX + "concentration_mode", source, setter, expires_on=expires,
                                        data={"rule": {"concentration_mode": mode, "next": True},
                                              "companion_of": NAME, "companion_menu": data["menu"]})


def _held(actor: Any):
    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id == condition_id():
            yield iid, condition


@hook("speed")
def speed(engine: Any, actor: Any) -> int:
    from ..speed_contributions import SpeedContribution

    return SpeedContribution((condition.source_definition_id, condition.data.get("label") or "Affliction",
                              int(condition.data.get("speed") or 0)) for _, condition in _held(actor))


@hook("ac")
def ac(engine: Any, target: Any) -> int:
    return sum(int((condition.data or {}).get("ac") or 0) for _, condition in _held(target))


@hook("turn_start")
def periodic(engine: Any, actor: Any) -> None:
    """Damage taken at the start of each of its turns ("The target takes 2d8 Poison damage at the start of each of its turns")."""
    from ..gate2_runtime_models import DiceSpec
    from ..typed_executor import Context, run_effects
    from .rider_choices import intent_for

    for iid, condition in _held(actor):
        owner = engine.state.actors.get(condition.source_actor_id)
        action = engine.action_catalog.get(condition.source_definition_id)
        for part in (condition.data or {}).get("parts", {}).values():
            effects = part.get("start_effects") or []
            if not effects or owner is None or action is None:
                continue
            if not actor.active or iid not in actor.conditions:
                break
            typed = dict((action.parameters or {}).get("typed") or {})
            ctx = Context(engine, owner, action, intent_for(engine), typed, [actor], actor, {})
            run_effects(ctx, effects)

        for row in (condition.data or {}).get("periodic") or []:
            if not actor.active or iid not in actor.conditions:
                return
            dice = row.get("dice") or {}
            roll = engine.roller.roll(DiceSpec(count=int(dice.get("count") or 1), sides=int(dice.get("sides") or 6), modifier=0),
                                      actor_id=condition.source_actor_id, reason=f"DAMAGE:{condition.source_definition_id}:{row.get('label')}")
            engine._record_roll(roll)
            kind = str((row.get("types") or ["necrotic"])[0]).upper()
            engine._commit_damage(actor, roll.total, kind, condition.source_definition_id, condition.source_actor_id, None, reaction_depth=0)


@hook("turn_end")
def repeat_one(engine: Any, actor: Any) -> None:
    """Resolve each native end-turn repeat-one affliction through its public delivery seam."""
    for iid, condition in _held(actor):
        repeat_one_effect(engine, actor, iid, condition)


def repeat_one_effect(engine: Any, actor: Any, iid: str, condition: Any, *,
                      extra_mode: str | None = None, roll_source: str | None = None) -> None:
    """Repeat one exact affliction save with its normal choose-one success result.

    Shared by native turn expiry and external repeat grants (Meridian Regulation).
    No effect on unrelated conditions. Original source, remaining parts and clocks
    survive; optional roll mode/source default to the ordinary native repeat.
    """
    from .effect_durations import apply_condition_preserving_clock, skipped_expiry_slots
    check = (condition.data or {}).get("repeat_one")
    if not check or not actor.active or iid not in actor.conditions:
        return
    roll = engine._roll_save(actor, str(check["ability"]), int(check["dc"]), condition.source_definition_id,
                             extra_mode=extra_mode, **({"receipt_source_id": roll_source} if roll_source else {}))
    if roll is None or roll.total < int(check["dc"]) or iid not in actor.conditions:
        return
    choices = list((condition.data or {}).get("picks") or [])
    removed = choices[:1]
    if condition.data.get("repeat_one_choice"):
        from .needle import ask, checkpoint_id
        removed = ask(engine, getattr(engine, "_active_intent", None),
                      checkpoint_id(engine, "End one seal", iid), actor,
                      "choice:needle.end_one_seal", choices, name=str(condition.data.get("name") or "Afflictions"),
                      prompt=f"{condition.data.get('name') or 'Afflictions'}: {actor.display_name} succeeds on its repeated saving throw; choose one seal to end",
                      target_id=actor.entity_id)
    left = [label for label in choices if label not in removed]
    skipped = skipped_expiry_slots(actor, condition)
    if not engine._remove_condition_instance(actor, iid, condition.source_definition_id,
            payload={"condition_id": condition.condition_id, "instance_id": iid, "repeat_save": True}, expected=condition):
        return
    if left:
        parts = (condition.data or {}).get("parts") or {}
        data = _data(left, parts, int((condition.data or {}).get("pb") or 2), str((condition.data or {}).get("name") or "Afflictions"),
                     str((condition.data or {}).get("menu")))
        if condition.data.get("affliction_token"):
            data["affliction_token"] = condition.data["affliction_token"]
        if len(left) > 1:
            data["repeat_one"] = check
            if condition.data.get("repeat_one_choice"):
                data["repeat_one_choice"] = True
        else:  # one left: the repeat saving throw ends it, as the engine's own does
            data["repeat_save"] = {**check, "when": "end"}
        apply_condition_preserving_clock(engine, actor, condition, condition_id(), condition.source_definition_id, condition.source_actor_id,
                                expires_on=condition.expires_on, data=data, skipped_slots=skipped)
        _companions(engine, actor, data, condition.source_definition_id, condition.source_actor_id, condition.expires_on)


@hook("event")
def remove_companions(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Removing an affliction also removes the voice/other companion it supplied.

    Repeat-one reapplies companions for the surviving picks. Match source and menu
    so another ability's silence or another actor's affliction remains intact.
    """
    if event_type != "CONDITION_REMOVED":
        return
    payload = kwargs.get("payload") or {}
    ended = kwargs.get("ended_effect") or {}
    event = kwargs.get("originating_event")
    # Deadline events name the clock and its boundary actor. The removed
    # instance retains the affliction's actual source and caster.
    source = ended.get("source_definition_id") or kwargs.get("source_definition_id") or getattr(event, "source_definition_id", "")
    owner = ended.get("source_actor_id") or kwargs.get("actor_id")
    if payload.get("condition_id") == "condition:typed.concentration_mode" and payload.get("reason") == "CONSUMED":
        for aid in kwargs.get("target_ids") or ():
            actor = engine.state.actors.get(aid)
            if actor:
                for _, held in _held(actor):
                    token = held.data.get("affliction_token")
                    if held.source_definition_id == source and token:
                        actor.turn_flags["affliction_round_concentration_used:" + token] = True
        return
    if payload.get("condition_id") != condition_id():
        return
    for aid in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(aid)
        if actor is None:
            continue
        live = {(c.source_definition_id, c.source_actor_id, (c.data or {}).get("menu")) for _, c in _held(actor)}
        for iid, c in list(actor.conditions.items()):
            data = c.data or {}
            if data.get("companion_of") == NAME and data.get("companion_menu") and c.source_definition_id == source \
                    and c.source_actor_id == owner \
                    and (source, c.source_actor_id, data["companion_menu"]) not in live:
                engine._remove_condition_instance(actor, iid, source, actor_id=actor.entity_id,
                    payload={"condition_id": c.condition_id, "instance_id": iid}, expected=c)
