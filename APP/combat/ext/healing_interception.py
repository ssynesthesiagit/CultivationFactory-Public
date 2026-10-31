"""Healing cut down as it lands, knowing who heals (rider lane C15, 2026-09-30; BLOCKED_CENSUS.md row 25) -- shared helper.

"Until the start of your next turn, the first time the target would regain Hit Points or gain Temporary HP, reduce that amount
by your Proficiency Bonus. At CL 11, the reduction applies to each instance" (Wound That Refuses Dawn); "Trigger: A creature
bearing one of your Pressure Points within 30 feet would regain HP, gain Temporary HP ... Failed Save: Halve the HP or Temporary
HP gained. Successful Save: Reduce the HP or Temporary HP gained by your Proficiency Bonus" (Reversing Pulse). The table could
only reduce healing by stored reductions on the healed creature; nothing could answer the moment healing is about to land, nor
see the healer.

  healing_pending(engine, target, amount, healer, source, kind) -> int | None   documented hook: points to take off this
      healing before it lands; ``kind`` "hp" or "temp_hp"; ``healer`` the creature healing (None when unknown), ``source`` the
      ability. Answers add up, never past the amount. Asked by typed_executor._reduced_healing (every typed heal, and the
      plug-ins that heal through it) after the creature's own reductions, and by typed_executor.block_temp_hp (typed
      Temporary Hit Points). Native and plug-in heals that bypass both are not reached (the engine's own healing is a
      saved-fight lock file: seam request in the census, row 25).

Records (typed effect "intercept_healing"): a small condition on the target, ``condition:typed.healing_intercept``:
  {"type": "intercept_healing", "applies_to": "target", "reduce": "pb", "kinds": ["hp", "temp_hp"], "each_from_cl": 11,
   "duration": "until_start_of_your_next_turn", "name": "Wound That Refuses Dawn"}
  data {"reduce": n, "kinds": [...], "each": 0|1, "name": str, "label": str}. A "first time" record is used up by the first
  healing it cuts (CONDITION_REMOVED, reason CONSUMED); an "each" one lasts its duration. Healing of 0 is not cut.
Reversing Pulse (feature block "reversing_pulse", combat/rules/feature_blocks.d/riders_c15.json): the owner's Reaction when a
  creature bearing its Pressure Point within 30 feet would regain HP or gain Temporary HP: the player is asked (an AI owner uses
  it on a foe); the creature makes a Constitution save against the owner's save DC: failure halves the healing, success takes
  off the owner's Proficiency Bonus. Its third trigger (delaying a condition's removal) stays the GM's.
Diminish Recovery (Yin, Spending a Waning Mark; feature block "diminish_recovery"): "Trigger: the marked creature regains Hit Points,
  gains Temporary HP ... Reduce the amount gained or restored by your Proficiency Bonus + your Key Ability modifier, to a minimum
  of 0" -- once a round (shared with the other Diminishing Responses: the Waning Mark spending's own once-a-round flag), when a
  creature bearing the owner's Waning Mark that the owner can see would regain HP or gain Temporary HP: the player is asked (an
  AI owner spends it on a foe), the mark is spent. Marked Allies permits this response only if it benefits the ally;
  the player judges that circumstance, with the restriction stated in the prompt. If the owner has Wound That Refuses Dawn (feature block
  "wound_that_refuses_dawn"), its record then goes on the creature ("the target's recovery continues to wane").
Stillness Has Teeth (AUTO33): the existing mark_spent hook offers its owner Cold or Necrotic
  damage equal to PB + Key Ability modifier for 1 CP, without an action. Diminish Recovery
  publishes the same hook after its successful mark removal; ordinary typed mark spending
  already publishes it. Declining does not pay, undo the response, or consume another mark.
Inert: no record and no owner in the fight answers nothing.
Users: Wound That Refuses Dawn, Diminish Recovery and Stillness Has Teeth (Yin), Reversing Pulse (Pressure Points).

Yin second pass: owned follow-up blocks consume Diminish Force's existing
DAMAGE_APPLICATION receipt (pending_before - pending_after), never its die quote.
Borrowed Consequence uses singleton_benefit for attributable Temporary HP expiry;
Return the Overextension asks for a paid damage type after the reduction; Still
the Bright Strike reads the successful mark_spent notification for Force/Aim.
Older sealed rows without these blocks keep their original behavior.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note

RECORD = "condition:typed.healing_intercept"
DIMINISH, WOUND = "diminish_recovery", "wound_that_refuses_dawn"
YIN_SPEND = "TAL_YIN_SPENDING_A_WANING_MARK"
WOUND_ID = "TAL_YIN_WOUND_THAT_REFUSES_DAWN"
TEETH = "yin_stillness_has_teeth"
TEETH_ID = "TAL_YIN_STILLNESS_HAS_TEETH"
BORROWED = "yin_borrowed_consequence"
RETURN = "yin_return_overextension"
BRIGHT = "yin_still_bright_strike"
FORCE_ID = YIN_SPEND + "#diminish_force"
ONCE = "once_per_round:typed." + YIN_SPEND  # the Diminishing Responses' shared once a round (typed_reactions._once_key)
PULSE = "reversing_pulse"
PULSE_ID = "tianxia.talent.pressure_points.reversing_pulse"
WORDS = {"hp": "healing", "temp_hp": "Temporary Hit Points"}


@effect("intercept_healing")
def intercept_healing(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    for subject in te._default_subject(ctx, row, harmful=True):
        if subject.active:
            place(ctx, subject, row)


def place(ctx: Any, subject: Any, row: dict[str, Any]) -> None:
    """Put one interception record (the ``intercept_healing`` row's shape) on ``subject``, from ``ctx.actor``."""
    from .. import typed_executor as te

    reduce = int(ctx.numbers.get("pb") or 2) if row.get("reduce") == "pb" else int(row.get("reduce") or 0)
    if reduce <= 0:
        return
    each = int(ctx.numbers.get("cl") or 1) >= int(row.get("each_from_cl") or 99)
    kinds = [str(kind) for kind in row.get("kinds") or ["hp"]]
    name = str(row.get("name") or ctx.action.display_name)
    what = " or ".join(WORDS.get(kind, kind) for kind in kinds)
    label = (f"{name}: {'each' if each else 'the first'} {what} it receives is {reduce} less "
             f"(until the start of {ctx.actor.display_name}'s next turn).")
    ctx.engine._apply_condition(subject, RECORD, ctx.source, ctx.actor.entity_id,
                                expires_on=te.effect_expiry(ctx, row, subject, condition=True) or "START_OF_SOURCE_NEXT_TURN",
                                data={"reduce": reduce, "kinds": kinds, "each": 1 if each else 0, "name": name, "label": label})


@hook("healing_pending")
def records(engine: Any, target: Any, amount: int, healer: Any, source: str, kind: str) -> int | None:
    held = sorted((c for c in target.conditions.values() if c.condition_id == RECORD and kind in ((c.data or {}).get("kinds") or [])),
                  key=lambda c: (int(c.applied_sequence or 0), c.instance_id))
    if not held or amount <= 0:
        return None
    from .condition_ownership import remove_instance

    total = 0
    for record in held:
        data = record.data or {}
        cut = min(int(data.get("reduce") or 0), amount - total)
        if cut <= 0:
            break
        total += cut
        note(engine, record.source_definition_id, target, f"{data.get('name') or 'A wound'}: {target.display_name}'s "
             f"{WORDS.get(kind, kind)} is {cut} less.", targets=[target])
        if not data.get("each"):
            remove_instance(engine, target, record.instance_id, record.source_definition_id)
    return total or None


@hook("status_description")
def _status(engine: Any, holder: Any, row: Any, data: Any) -> dict[str, Any] | None:
    if (row or {}).get("condition_id") != RECORD:
        return None
    text = str((data or {}).get("label") or "")
    return {"text": text} if text else None


# ---------------------------------------------------------------------------------------------------- Reversing Pulse
@hook("compile_block")
def _compile(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    followups = (BORROWED, RETURN, BRIGHT)
    # Keep the registration guard literal so the static audit can enumerate it.
    if block not in (PULSE, DIMINISH, WOUND, TEETH, BORROWED, RETURN, BRIGHT):
        return None
    data = {key: value for key, value in spec.items() if key not in ("why", "covers")} if block in followups else {}
    return [{**row, **data, "block": block, "save_dc": int(numbers.get("save_dc") or 10), "pb": int(numbers.get("pb") or 2),
             "key_mod": int(numbers.get("key_mod") or 0), "cl": int(numbers.get("cl") or 1),
             "range_ft": int(spec.get("range_ft") or 30), "keeps_compiling": block not in (TEETH, *followups)}]


@hook("mark_spent")
def still_bright_strike(ctx: Any, name: str, subject: Any) -> None:
    if name.strip().lower() != "waning mark":
        return
    rows = (getattr(ctx.engine, "typed_passive_rows", {}) or {}).get(ctx.actor.entity_id, [])
    row = next((r for r in rows if r.get("block") == BRIGHT and ctx.source in r.get("responses", [])), None)
    if row is not None:
        from ..typed_executor import run_effects

        run_effects(ctx.with_source(row["feature_id"]), row["effects"])


@hook("event")
def reduction_followups(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if (event_type != "REACTION_RESOLVED" or kwargs.get("source_definition_id") != FORCE_ID
            or payload.get("checkpoint") != "DAMAGE_APPLICATION"):
        return
    owner = engine.state.actors.get(kwargs.get("actor_id"))
    rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(owner, "entity_id", None), [])
    rows = [r for r in rows if r.get("block") in (BORROWED, RETURN)]
    if not rows:
        return
    before, after = payload.get("pending_before"), payload.get("pending_after")
    if type(before) is not int or type(after) is not int or not 0 <= after < before:
        return
    from ..pending_damage import current

    packet = current(engine)
    if packet is None or packet.target_id != owner.entity_id:
        return
    source = engine.state.actors.get(packet.source_actor_id)
    if source is None or tuple(kwargs.get("target_ids") or ()) != (source.entity_id,):
        return
    from .states import context
    from ..typed_executor import run_effects

    cut = before - after
    for row in rows:
        feature = row["feature_id"]
        ctx = context(engine, owner, feature, [source], row)
        ctx.action = ctx.action.model_copy(update={"source_definition_id": feature, "display_name": row["name"]})
        ctx.typed["source"] = feature
        ctx.intent = getattr(engine, "_active_intent", None)
        if row["block"] == BORROWED:
            action = engine.action_catalog.get(packet.source_id)
            typed = ((action.parameters or {}).get("typed") or {}) if action else {}
            enhanced = (packet.damage_type.lower() in row["bonus_damage_types"]
                        or "yang_aspected" in packet.source_flags or typed.get("yang_aspected") is True)
            amount = cut // int(row["divisor"]) + (int(row["pb"]) if enhanced else 0)
            ctx.action = ctx.action.model_copy(update={"display_name": f"Borrowed Consequence: {owner.display_name} "
                f"gains {amount} Temporary HP until the start of its next turn (no cost)."})
            run_effects(ctx, [{"type": "singleton_benefit", "mechanic_id": feature,
                "expires_on": row["expires_on"], "effects": [{"type": "temp_hp", "flat": amount, "applies_to": "self"}]}])
            continue
        from . import run
        from .choice_costs import payable
        from .cp_pools import of
        from .needle import ask, checkpoint_id
        from .choice_prompt import action_context

        cost = int(row["extra_cp"])
        payment = payable(owner, of(owner, at_least=cost) or "", cost)
        if payment is None or any(answer is False for answer in run(
                "cost_available", engine, owner, payment.pool, payment.amount, {})):
            continue
        amount = min(cut, int(row["cap_cl"]) * int(row["cl"]))
        origin = action_context(engine, source, packet.source_id, owner)
        picked = ask(engine, ctx.intent, checkpoint_id(engine, RETURN, source.entity_id), owner,
            "choice:needle.yin_return_overextension", row["damage_types"], allow_decline=True,
            target_id=source.entity_id, payment=payment, name=row["name"], feature_id=feature, prompt_context=origin,
            labels={kind: f"Deal {amount} {kind.title()} damage to {source.display_name} ({payment.quote()})"
                    for kind in row["damage_types"]},
            prompt=f"Return the Overextension: Diminish Force reduced {source.display_name}'s damage from "
                   f"{origin['action_name'] or 'the triggering effect'} by {cut}. "
                   f"Spend {payment.quote()} to deal {amount} Psychic, Cold or Necrotic damage back to it? No action needed.")
        if picked:
            payment.pay(engine, owner, feature)
            run_effects(ctx, [{"type": "damage", "applies_to": "target", "flat": amount,
                              "damage_types": [picked[0]]}])


@hook("mark_spent")
def stillness_has_teeth(ctx: Any, name: str, subject: Any) -> None:
    """A spent Waning Mark can deal PB + key damage for 1 CP; never spend a second mark."""
    if name.strip().lower() != "waning mark":
        return
    from . import run
    from .choice_costs import payable
    from .cp_pools import of
    from .needle import ask, checkpoint_id
    from .. import typed_executor as te

    rows = (getattr(ctx.engine, "typed_passive_rows", {}) or {}).get(ctx.actor.entity_id, [])
    row = next((r for r in rows if r.get("block") == TEETH), None)
    if row is None:
        return
    payment = payable(ctx.actor, of(ctx.actor, at_least=1) or "", 1)
    if payment is None or any(result is False for result in run(
            "cost_available", ctx.engine, ctx.actor, payment.pool, payment.amount, {})):
        return
    amount = max(0, int(row["pb"]) + int(row["key_mod"]))
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "stillness_has_teeth", subject.entity_id), ctx.actor,
                 "choice:needle.stillness_has_teeth", ["cold", "necrotic"], allow_decline=True,
                 target_id=subject.entity_id, payment=payment, name="Stillness Has Teeth", feature_id=TEETH_ID,
                 labels={kind: f"Deal {amount} {kind.title()} damage to {subject.display_name} ({payment.quote()})"
                         for kind in ("cold", "necrotic")},
                 prompt=f"Stillness Has Teeth: {ctx.action.display_name} spent your Waning Mark on {subject.display_name}. "
                        f"Spend {payment.quote()} to deal {amount} Cold or Necrotic damage? No action needed.")
    if not picked:
        return
    payment.pay(ctx.engine, ctx.actor, TEETH_ID)
    inner = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [subject], subject, {})
    te.run_effects(inner.with_source(TEETH_ID), [{"type": "damage", "applies_to": "target", "flat": amount,
                                              "damage_types": [picked[0]], "duration": "instant"}])


@hook("healing_pending")
def reversing_pulse(engine: Any, target: Any, amount: int, healer: Any, source: str, kind: str) -> int | None:
    if amount <= 0:
        return None
    from .. import typed_executor as te
    from .. import typed_reactions

    for owner in engine.state.actors.values():
        rows = typed_reactions._rows(engine, owner.entity_id, PULSE) if owner.active else []
        if not rows:
            continue
        row = rows[0]
        if not te.bears_mark(target, owner.entity_id, "Pressure Point") or engine._distance_actor_to_actor(owner, target) > int(row["range_ft"]):
            continue
        if not typed_reactions._can_react(engine, owner, row):
            continue
        from .needle import ask, checkpoint_id
        from .choice_prompt import action_context

        hostile = owner.team_id != target.team_id
        action = action_context(engine, healer, source, target)
        origin = f" from {healer.display_name if healer is not None else 'an unknown healer'} using {action['action_name'] or 'a healing effect'}"
        picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "reversing_pulse", target.entity_id), owner,
                     "choice:needle.reversing_pulse", ["use"], allow_decline=True, target_id=target.entity_id,
                     automatic=hostile, default="first" if hostile else "decline", prompt_context=action,
                     labels={"use": f"Reversing Pulse on {target.display_name} (your Reaction): a Constitution save; its "
                                    f"{WORDS.get(kind, kind)} is halved on a failure, {row['pb']} less on a success"},
                     prompt=f"Reversing Pulse: {target.display_name}, who bears your Pressure Point, is about to gain {amount} "
                            f"{WORDS.get(kind, kind)}{origin}. "
                            f"Use your Reaction?", name="Reversing Pulse", feature_id=PULSE_ID)
        if not picked:
            continue
        with activation(engine, owner, PULSE_ID):
            typed_reactions._open(engine, row, owner, (target.entity_id,), "HEALING_PENDING")
            typed_reactions.spend_reaction(engine, owner, row)
            roll = engine._roll_save(target, "CON", int(row["save_dc"]), PULSE_ID)
            failed = roll is not None and roll.total < int(row["save_dc"])
            cut = amount - amount // 2 if failed else min(amount, int(row["pb"]))
            engine._append_event("REACTION_RESOLVED", PULSE_ID, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                                 payload={"checkpoint": "HEALING_PENDING", "kind": kind, "offered": amount, "reduced_by": cut,
                                          "log": f"Reversing Pulse: {target.display_name} {'fails' if failed else 'makes'} its Constitution save; "
                                                 f"its {WORDS.get(kind, kind)}{origin} is {'halved' if failed else str(cut) + ' less'}."})
            return cut
    return None


# -------------------------------------------------------------------------------------------- Diminish Recovery (Yin)
@hook("healing_pending")
def diminish_recovery(engine: Any, target: Any, amount: int, healer: Any, source: str, kind: str) -> int | None:
    if amount <= 0:
        return None
    from .. import stealth, typed_executor as te
    from ..typed_reactions import _rows
    from .needle import ask, checkpoint_id, incapacitated

    for owner in engine.state.actors.values():
        rows = _rows(engine, owner.entity_id, DIMINISH) if owner.active else []
        if not rows or incapacitated(owner):
            continue
        if owner.turn_flags.get(ONCE) == engine.state.round_number or not te.bears_mark(target, owner.entity_id, "Waning Mark"):
            continue
        if owner is not target and not stealth.sees(engine, owner, target):
            continue  # "a marked creature you can perceive"
        row = rows[0]
        cut = min(amount, int(row["pb"]) + int(row["key_mod"]))
        from .choice_prompt import action_context

        hostile = owner.team_id != target.team_id
        action = action_context(engine, healer, source, target)
        origin = f" from {healer.display_name if healer is not None else 'an unknown healer'} using {action['action_name'] or 'a healing effect'}"
        ally_limit = " Use this on an ally or yourself only if it benefits that creature." if not hostile else ""
        picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "diminish_recovery", target.entity_id), owner,
                     "choice:needle.diminish_recovery", ["spend"], allow_decline=True, target_id=target.entity_id,
                     automatic=hostile, default="first" if hostile else "decline", prompt_context=action,
                     labels={"spend": f"Spend {target.display_name}'s Waning Mark: {cut} less {WORDS.get(kind, kind)} (no action)"},
                     prompt=f"Diminish Recovery: {target.display_name}, who bears your Waning Mark, is about to gain {amount} "
                            f"{WORDS.get(kind, kind)}{origin}. Spend the mark to reduce it by {cut}? (Once a round; no action.){ally_limit}",
                     name="Diminish Recovery", feature_id=YIN_SPEND)
        if not picked:
            continue
        owner.turn_flags[ONCE] = int(engine.state.round_number)
        mark = te.mark_condition_id("Waning Mark", owner.entity_id)
        held = next((iid for iid, c in target.conditions.items() if c.condition_id == mark), None)
        if held is not None:
            target.conditions.pop(held)
            engine._append_event("CONDITION_REMOVED", YIN_SPEND, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                                 payload={"condition_id": mark, "instance_id": held, "reason": "CONSUMED"})
            from . import run
            from .states import context

            spent = context(engine, owner, YIN_SPEND, [target], {"pb": row["pb"], "key_mod": row["key_mod"]})
            spent.action = spent.action.model_copy(update={"source_definition_id": YIN_SPEND,
                                                          "display_name": "Diminish Recovery"})
            spent.intent = getattr(engine, "_active_intent", None)
            run("mark_spent", spent, "Waning Mark", target)
        note(engine, YIN_SPEND, owner, f"Diminish Recovery: {owner.display_name} spends {target.display_name}'s Waning Mark; its "
             f"{WORDS.get(kind, kind)}{origin} is {cut} less.", targets=[target])
        wound = _rows(engine, owner.entity_id, WOUND)
        if wound:
            from .states import context

            ctx = context(engine, owner, WOUND_ID, [target], {"pb": wound[0]["pb"], "cl": wound[0]["cl"]})
            place(ctx, target, {"reduce": "pb", "kinds": ["hp", "temp_hp"], "each_from_cl": 11,
                                "expires_on": "START_OF_SOURCE_NEXT_TURN", "name": "Wound That Refuses Dawn"})
        return cut
    return None
