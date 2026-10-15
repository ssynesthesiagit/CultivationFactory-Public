"""Hundred-Venom Body (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Hundred-Venom Body (the five features and their Normalized Procedures).
Owned rows: ``{"type": "path_passive", "kind": "hundred_venom", "role": "furnace" | "sovereign" | "poisoned_world" |
"myriad"}``; Venom Furnace itself is a paid unarmed-hit rider (path_riders ``paid_hit``) whose option runs ``venom_furnace``.

Venom Furnace        after an unarmed hit, 1 Stamina, once per turn (asked): + 2d6 Poison (4d6 with Myriad-Venom Immortal; +
                     Proficiency Bonus once after a Swallow the Poison that avoided the poison), then a Constitution save:
                     failure, Poisoned until the start of your next turn (and Sovereign Venoms, below).
Three Sovereign Venoms  on that failed save, one Venom (asked; two different ones with Myriad-Venom), until the end of your next
                     turn: Nerve (no Reactions, Disadvantage on its next attack roll), Blood (2d6 Poison at the start of its next
                     turn, then it ends), Marrow (Speed -15 feet, Disadvantage on its next Strength or Dexterity save, asked).
                     Only one Venom of yours on a creature: a new one replaces every part of the old. Myriad: on a successful
                     save, one Venom until the start of the creature's next turn.
Swallow the Poison   its Reaction (1 Stamina, once per round) answers acid or poison damage (the compiled reduction; a packet it
                     brings to 0 stores the adaptation), a failed save against poison (a d20 rewrite: + Proficiency Bonus; a save
                     turned into a success stores it) or being Poisoned (asked: the condition waits until the end of your next
                     turn and then begins for what is left of its duration, or never if that has run out -- which stores it).
                     The adaptation: your next Venom Furnace before the end of your next turn deals + Proficiency Bonus Poison.
Poisoned Body, Poisoned World  your Body Refining Poison damage ignores Resistance; once per round, after a hostile creature
                     within your unarmed reach damages you (typed damage), Grapples you, or starts its turn Grappling you, you may
                     spend 1 Stamina (asked): its Constitution save, 3d8 Poison and one Venom, or half and no Venom.
Myriad-Venom Immortal  Poison and Poisoned immunity (compiled defense and condition immunity rows); your Body Refining Poison
                     treats Poison Immunity as Resistance and then ignores it; the Venom Furnace changes above.
"Your Body Refining Poison" is the damage these features deal and your unarmed strikes (which Venom Furnace lets deal Poison).
Every hook returns early for a creature without these rows.
"""

from __future__ import annotations

from ..paid_relocation import activation

from contextlib import contextmanager
from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.hundred_venom_body.feature."
VENOMS = PREFIX + "three_sovereign_venoms"
SWALLOW = PREFIX + "swallow_the_poison"
ADAPTED = "condition:typed.venom_adaptation"
VENOM = "condition:typed.sovereign_venom"
BLOOD = "condition:typed.blood_venom"
DELAYED = "condition:typed.swallowed_poison"
STAMINA = "resource:core.stamina"
LABELS = {"nerve": "Nerve Venom: no Reactions and Disadvantage on its next attack roll",
          "blood": "Blood Venom: 2d6 Poison damage at the start of its next turn",
          "marrow": "Marrow Venom: Speed -15 feet and Disadvantage on its next Strength or Dexterity saving throw"}


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "hundred_venom"}


def _pb(actor: Any) -> int:
    return int(getattr(actor, "proficiency_bonus", 0) or 2)


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


# ----------------------------------------------------------------------------------------- Body Refining Poison
@contextmanager
def body_poison(engine: Any, actor: Any):
    """Damage dealt inside this block is ``actor``'s Body Refining Poison (the flag is transient, never saved)."""
    previous = engine.__dict__.get("_body_poison")
    engine.__dict__["_body_poison"] = actor.entity_id
    try:
        yield
    finally:
        engine.__dict__["_body_poison"] = previous


def _body_poison(engine: Any, kind: str, typed: Any, source_actor_id: Any) -> bool:
    if str(kind).upper() != "POISON" or not source_actor_id:
        return False
    if engine.__dict__.get("_body_poison") == source_actor_id:
        return True
    source = str((typed or {}).get("source") or "")
    if source.startswith(("tianxia.subpath.body.", "tianxia.path.body_refining.feature.")):
        return True
    # The ordinary unarmed strike's Furnace conversion is a bodily feature.
    # A Sphere technique merely containing an unarmed attack is not one.
    return source in {"unarmed_strike", "body_refining_unarmed_strike"}


@hook("resistance_ignored")
def poison_ignores_resistance(engine: Any, kind: str, typed: Any, source_actor_id: Any, target: Any = None) -> bool | None:
    source = engine.state.actors.get(str(source_actor_id or ""))
    if source is None or not ({"poisoned_world", "myriad"} & _roles(engine, source)) or not _body_poison(engine, kind, typed, source_actor_id):
        return None
    return True


@hook("immunity_as_resistance")
def immunity_is_resistance(engine: Any, kind: str, typed: Any, source_actor_id: Any, target: Any) -> bool | None:
    source = engine.state.actors.get(str(source_actor_id or ""))
    if source is None or "myriad" not in _roles(engine, source) or not _body_poison(engine, kind, typed, source_actor_id):
        return None
    return True


# ------------------------------------------------------------------------------------------------ Venom Furnace
def _context(engine: Any, owner: Any, target: Any, intent: Any, source: str, name: str) -> Any:
    """A Context of ``owner`` against ``target`` whose conditions and damage carry ``source`` (exact removal later)."""
    from .. import typed_executor as te
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    action = ActionDefinition(source_definition_id=source, display_name=name, owner_id=owner.entity_id, economy=EconomyKind.NONE,
                              resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
    numbers = {"pb": _pb(owner), "cl": int(getattr(owner, "cultivation_level", 0) or 0) or 1}
    row = next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(owner.entity_id, []) if r.get("kind") == "hundred_venom"), {})
    numbers.update({"save_dc": int(row.get("save_dc") or 10), "cl": int(row.get("cl") or numbers["cl"]), "pb": int(row.get("pb") or numbers["pb"])})
    return te.Context(engine, owner, action, intent, {"effects": [], "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                      [target], target, {})


@effect("venom_furnace")
def venom_furnace(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    roles = _roles(engine, owner)
    bonus = 0
    adapted = next((c for c in owner.conditions.values() if c.condition_id == ADAPTED), None)
    if adapted is not None:
        owner.conditions.pop(adapted.instance_id)
        engine._append_event("CONDITION_REMOVED", adapted.source_definition_id, actor_id=owner.entity_id, target_ids=(owner.entity_id,),
                             payload={"condition_id": ADAPTED, "instance_id": adapted.instance_id, "reason": "CONSUMED"})
        bonus = _pb(owner)
    sub = _context(engine, owner, target, ctx.intent, PREFIX + "venom_furnace", "Venom Furnace")
    with body_poison(engine, owner):
        te.run_effects(sub, [{"type": "damage", "applies_to": "target", "dice": {"count": 4 if "myriad" in roles else 2, "sides": 6}, "flat": bonus,
                              "damage_types": ["poison"], "evidence": "Venom Furnace"}])
    if not target.active:
        return
    fail: list[dict[str, Any]] = [{"type": "condition", "applies_to": "target", "condition": "poisoned", "expires_on": "START_OF_SOURCE_NEXT_TURN"}]
    success: list[dict[str, Any]] = []
    if "sovereign" in roles:
        fail.append({"type": "sovereign_venom", "count": 2 if "myriad" in roles else 1})
        if "myriad" in roles:
            success.append({"type": "sovereign_venom", "count": 1, "brief": True})
    te.run_effects(sub, [{"type": "save", "ability": "con", "evidence": "Venom Furnace: Constitution saving throw", "on_fail": fail, "on_success": success}])


# --------------------------------------------------------------------------------------------- Sovereign Venoms
def _clear(engine: Any, owner: Any, target: Any, names: set[str] | None = None) -> None:
    """End selected named states and exactly their associated mechanical rows."""
    markers = [c for c in target.conditions.values() if c.condition_id == VENOM
               and c.source_definition_id == VENOMS and c.source_actor_id == owner.entity_id
               and (names is None or (c.data or {}).get("venom") in names)]
    condition_ids = {iid for c in markers for iid in (c.data or {}).get("condition_ids", [])}
    condition_ids.update(c.instance_id for c in markers)
    modifier_ids = {mid for c in markers for mid in (c.data or {}).get("modifier_ids", [])}
    for iid, held in list(target.conditions.items()):
        if held.source_definition_id == VENOMS and held.source_actor_id == owner.entity_id and (names is None or iid in condition_ids):
            engine._remove_condition_instance(target, iid, VENOMS, expected=held)
    for mid, held in list(target.modifiers.items()):
        if held.source_definition_id == VENOMS and held.source_actor_id == owner.entity_id and (names is None or mid in modifier_ids):
            del target.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", VENOMS, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                                 payload={"modifier_id": mid, "reason": "REPLACED"})


@effect("sovereign_venom")
def sovereign_venom(ctx: Any, row: dict[str, Any]) -> None:
    apply_venoms(ctx.engine, ctx.actor, ctx.target, ctx.intent, int(row.get("count") or 1), brief=bool(row.get("brief")))


def apply_venoms(engine: Any, owner: Any, target: Any, intent: Any, count: int, *, brief: bool = False) -> None:
    from .. import typed_executor as te
    from .effect_durations import token
    from .needle import ask, checkpoint_id

    if target is None or not target.active or "sovereign" not in _roles(engine, owner):
        return
    existing = {c.data.get("venom"): c for c in target.conditions.values()
                if c.condition_id == VENOM and c.source_actor_id == owner.entity_id}
    preserved: set[str] = set()
    myriad = "myriad" in _roles(engine, owner)
    if myriad and existing:
        # Reapplication may replace either or both named states. Keeping a
        # state keeps its original clock and unspent rider; it is not renewed.
        modes = (["replace_all"] if count == 2 else []) + ["keep:" + v for v in sorted(existing)]
        mode_labels = {"replace_all": "Replace both Sovereign Venoms"}
        mode_labels.update({"keep:" + v: "Keep " + v.title() + " Venom with its remaining duration; replace the other Venom"
                            for v in existing})
        if count == 1 and len(existing) == 1:
            modes = ["replace_all", *modes]
            mode_labels["replace_all"] = "Replace the existing Sovereign Venom"
        mode = ask(engine, intent, checkpoint_id(engine, "sovereign_reapply", target.entity_id), owner,
                   "choice:needle.sovereign_reapply", modes, labels=mode_labels,
                   target_id=target.entity_id, name="Three Sovereign Venoms",
                   prompt=f"Three Sovereign Venoms on {target.display_name}: choose which existing Venoms to replace.")
        if mode and mode[0].startswith("keep:"):
            preserved.add(mode[0].split(":", 1)[1])
            count = 1
    options = [v for v in ["blood", "nerve", "marrow"] if v not in preserved]
    picked = ask(engine, intent, checkpoint_id(engine, "sovereign_venom", target.entity_id), owner, "choice:needle.sovereign_venom", options,
                 labels=LABELS, minimum=count, maximum=count, preferred=options[:count], target_id=target.entity_id, name="Three Sovereign Venoms",
                 prompt=f"Three Sovereign Venoms: choose {'one Venom' if count == 1 else f'{count} different Venoms'} for {target.display_name}"
                        f"{' (until the start of its next turn)' if brief else ' (until the end of your next turn)' }.")
    chosen = [o for o in options if o in (picked or options[:count])][:count]
    expires = token("start", target.entity_id, int(target.turns_started) + 1) if brief else token("end", owner.entity_id, int(owner.turns_started) + 1)
    _clear(engine, owner, target, set(existing) - preserved if preserved else None)
    ctx = _context(engine, owner, target, intent, VENOMS, "Three Sovereign Venoms")
    for venom in chosen:
        before_conditions, before_modifiers = set(target.conditions), set(target.modifiers)
        engine._apply_condition(target, VENOM, VENOMS, owner.entity_id, expires_on=expires, data={"venom": venom, "source_cl": int(ctx.numbers["cl"]), "label": LABELS[venom]})
        if venom == "nerve":
            te.run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "expires_on": expires},
                                 {"type": "disadvantage", "applies_to": "target", "on": "its next attack roll", "expires_on": expires}])
        elif venom == "blood":
            engine._apply_condition(target, BLOOD, VENOMS, owner.entity_id, expires_on=expires,
                                    data={"label": "Blood Venom: 2d6 Poison at the start of its next turn"})
        elif venom == "marrow":
            ability = ask(engine, intent, checkpoint_id(engine, "marrow_venom", target.entity_id), owner, "choice:needle.marrow_venom", ["Strength", "Dexterity"],
                          target_id=target.entity_id, prompt=f"Marrow Venom: {target.display_name}'s next Strength or Dexterity saving throw has Disadvantage.")
            te.run_effects(ctx, [{"type": "speed", "applies_to": "target", "flat": -15, "expires_on": expires},
                                 {"type": "disadvantage", "applies_to": "target", "on": f"its next {(ability or ['Strength'])[0]} saving throw", "expires_on": expires}])
        marker = next(c for iid, c in target.conditions.items()
                      if iid not in before_conditions and c.condition_id == VENOM)
        engine._update_condition_data(target, marker, {**marker.data,
            "condition_ids": [iid for iid in target.conditions if iid not in before_conditions and iid != marker.instance_id],
            "modifier_ids": [mid for mid in target.modifiers if mid not in before_modifiers]}, VENOMS)
    note(engine, VENOMS, owner, f"Three Sovereign Venoms: {', '.join(v.title() for v in chosen)} Venom on {target.display_name}.", (target,))


@hook("turn_boundary_start")
def blood_venom(engine: Any, actor: Any) -> None:
    """"At the start of the target's next turn, it takes one 2d6 Poison damage packet, then Blood Venom ends"."""
    from .. import typed_executor as te

    for held in [c for c in actor.conditions.values() if c.condition_id == BLOOD]:
        owner = engine.state.actors.get(held.source_actor_id)
        actor.conditions.pop(held.instance_id, None)
        engine._append_event("CONDITION_REMOVED", VENOMS, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": BLOOD, "instance_id": held.instance_id, "reason": "RESOLVED"})
        if owner is None or not actor.active:
            continue
        # Blood resolves once. Its marker is part of the same named state.
        for iid, marker in list(actor.conditions.items()):
            if marker.condition_id == VENOM and marker.source_actor_id == held.source_actor_id and (marker.data or {}).get("venom") == "blood":
                engine._remove_condition_instance(actor, iid, VENOMS, expected=marker)
        with body_poison(engine, owner):
            te.run_effects(_context(engine, owner, actor, _intent(engine), VENOMS, "Blood Venom"),
                           [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 6}, "damage_types": ["poison"], "evidence": "Blood Venom"}])


# ------------------------------------------------------------------------------------------- Swallow the Poison
def _adapt(engine: Any, owner: Any) -> None:
    """The stored adaptation: the next Venom Furnace before the end of the owner's next turn deals + Proficiency Bonus Poison."""
    from .effect_durations import token

    for iid, held in list(owner.conditions.items()):
        if held.condition_id == ADAPTED:
            engine._remove_condition_instance(owner, iid, SWALLOW, expected=held)
    engine._apply_condition(owner, ADAPTED, SWALLOW, owner.entity_id, expires_on=token("end", owner.entity_id, int(owner.turns_started) + 1),
                            data={"label": "Swallow the Poison: next Venom Furnace + Proficiency Bonus Poison"})


@effect("venom_adaptation")
def venom_adaptation(ctx: Any, row: dict[str, Any]) -> None:
    # Acid is eligible for reduction, but only zero matching Poison stores
    # adaptation. The shared reduction dispatcher still owns the actual roll.
    if str(getattr(ctx.engine, "_typed_pending_damage_type", "")).upper() == "POISON":
        _adapt(ctx.engine, ctx.actor)


def _swallow_key() -> str:
    return "once_per_round:typed." + SWALLOW  # the Reaction row's own once-per-round key (typed_reactions._once_key)


def _swallow_ready(engine: Any, owner: Any) -> bool:
    from ..typed_executor import condition_rules

    return (any(r.get("feature_id") == SWALLOW for r in (getattr(engine, "typed_reaction_rows", {}) or {}).get(owner.entity_id, []))
            and owner.turn_flags.get(_swallow_key()) != int(engine.state.round_number) and int(owner.resources.get(STAMINA, 0) or 0) >= 1
            and owner.active and owner.reaction_available and not any(rule.get("no_reactions") for rule in condition_rules(owner)))


def _swallow_guard(engine: Any, holder: Any, rctx: Any) -> bool:
    named = set(rctx.named or ())
    return (rctx.roller is holder.actor and (bool(named & {"poisoned", "damage:poison", "category:poison", "category:disease", "category:ordinary_disease"})) and rctx.dc is not None
            and rctx.total + _pb(holder.actor) >= int(rctx.dc) and _swallow_ready(engine, holder.actor))


def _swallow_used(engine: Any, holder: Any, rctx: Any) -> None:
    holder.actor.turn_flags[_swallow_key()] = int(engine.state.round_number)


def _swallow_after(engine: Any, holder: Any, rctx: Any, new: Any) -> None:
    if rctx.dc is not None and int(new.total) + _pb(holder.actor) >= int(rctx.dc):
        _adapt(engine, holder.actor)


def _register_swallow() -> None:
    from .d20_rewrite import Rule, register, row_holders

    register(Rule("swallow_the_poison_save", "Swallow the Poison (+ Proficiency Bonus to a failed save against poison)", feature=SWALLOW,
                  rolls=("save",), who="self", when="failed", op="choose", reaction=True, costs=((("stamina", 1),),), checkpoint="D20_REROLL_SAVE",
                  finder=row_holders("swallow_the_poison_save", SWALLOW), guard=_swallow_guard, on_use=_swallow_used, after=_swallow_after,
                  choose=lambda engine, holder, rctx: rctx.natural, bonus=lambda engine, holder, rctx: _pb(holder.actor),
                  say=lambda engine, holder, rctx, new: f"Swallow the Poison: {holder.actor.display_name} adds its Proficiency Bonus to the save."))


_register_swallow()


@hook("condition_attempt")
def delay_poisoned(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    """"Delay Poisoned until the end of your next turn" (the Reaction, asked)."""
    if subject is None or str((effect_row or {}).get("condition") or "").lower() != "poisoned" or ctx.actor is subject or not _swallow_ready(ctx.engine, subject):
        return None
    from .. import typed_executor as te

    if te.condition_immune(ctx.engine, subject, "poisoned"):
        return None
    from .effect_durations import token
    from .needle import ask, checkpoint_id

    engine = ctx.engine
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "swallow_delay", subject.entity_id), subject, "choice:needle.swallow_the_poison_delay", ["delay"],
                 labels={"delay": "Delay Poisoned until the end of your next turn (Reaction, 1 Stamina)"}, allow_decline=True, target_id=subject.entity_id,
                 name="Swallow the Poison", prompt=f"Swallow the Poison: {ctx.action.display_name} would Poison {subject.display_name}.")
    if not picked:
        return None
    original = te.effect_expiry(ctx, effect_row, subject, condition=True) or "UNTIL_REMOVED"
    # Capture an absolute turn token now: the engine-native names are only
    # meaningful at their own boundary and cannot be compared later at onset.
    if original == "START_OF_SOURCE_NEXT_TURN":
        original = token("start", ctx.actor.entity_id, int(ctx.actor.turns_started) + 1)
    elif original == "END_OF_HOLDER_NEXT_TURN":
        original = token("end", subject.entity_id, int(subject.turns_started) + 1)
    condition_data = te.condition_save_data(ctx, effect_row)
    if isinstance(effect_row.get("condition_label"), str):
        condition_data["label"] = effect_row["condition_label"]
    from .. import typed_reactions

    with activation(engine, subject, SWALLOW):
        typed_reactions._open(engine, {"feature_id": SWALLOW}, subject, (ctx.actor.entity_id,), "CONDITION_PENDING")
        subject.reaction_available = False
        subject.turn_flags[_swallow_key()] = int(engine.state.round_number)
        engine._spend_resource(subject, STAMINA, 1, SWALLOW)
        engine._apply_condition(subject, DELAYED, SWALLOW, ctx.actor.entity_id, expires_on=token("end", subject.entity_id, int(subject.turns_started) + 1),
                                data={"label": "Swallow the Poison: Poisoned is delayed", "expires_on": original, "source": ctx.source,
                                      "condition_data": condition_data})
        note(engine, SWALLOW, subject, f"Swallow the Poison: {subject.display_name} holds the poison until the end of its next turn.", (ctx.actor,))
        return False


@hook("effect_expiring")
def delayed_poison_begins(engine: Any, holder: Any, row: Any) -> None:
    if getattr(row, "condition_id", None) != DELAYED:
        return
    from .effect_durations import due

    original = str((row.data or {}).get("expires_on") or "UNTIL_REMOVED")
    if due(engine, original):
        _adapt(engine, holder)  # its source ran out during the delay: the poison never began
        return
    # Old saved delays have no condition_data: retain their label-only behavior.
    # New delays restore only the captured data, even if the caster or its DC changed.
    from copy import deepcopy

    data = deepcopy((row.data or {}).get("condition_data") or {})
    data.setdefault("label", "Poisoned (delayed by Swallow the Poison)")
    engine._apply_condition(holder, "condition:typed.poisoned", str((row.data or {}).get("source") or SWALLOW), row.source_actor_id,
                            expires_on=original, data=data)


# ------------------------------------------------------------------------------ Poisoned Body, Poisoned World
def _retaliate(engine: Any, owner: Any, other: Any, intent: Any, why: str) -> None:
    from .. import typed_executor as te
    from ..typed_reactions import attack_reaches
    from .needle import ask, checkpoint_id

    from ..relations import relation, ENEMY
    from ..stealth import sees

    if (not owner.active or other is None or not other.active or relation(engine, owner, other) != ENEMY
            or "poisoned_world" not in _roles(engine, owner)):
        return
    # Actual contact identifies a maintained grappler; otherwise consult the
    # owner's native senses rather than granting AI omniscient targeting.
    contact = any(c.condition_id.endswith(".grappled") and c.source_actor_id == other.entity_id
                  for c in owner.conditions.values())
    if not contact and not sees(engine, owner, other):
        return
    if owner.turn_flags.get("_round_poisoned_world") == int(engine.state.round_number) or int(owner.resources.get(STAMINA, 0) or 0) < 1:
        return
    if not attack_reaches(engine, owner, other, {"attack_kind": "unarmed"}):
        return
    picked = ask(engine, intent, checkpoint_id(engine, "poisoned_world", other.entity_id), owner, "choice:needle.poisoned_body_poisoned_world", ["use"],
                 labels={"use": f"Spend 1 Stamina: {other.display_name} makes a Constitution save (3d8 Poison and a Venom)"}, allow_decline=True,
                 target_id=other.entity_id, name="Poisoned Body, Poisoned World", prompt=f"Poisoned Body, Poisoned World: {why}.")
    if not picked:
        return
    with activation(engine, owner, PREFIX + "poisoned_body_poisoned_world"):
        owner.turn_flags["_round_poisoned_world"] = int(engine.state.round_number)
        engine._spend_resource(owner, STAMINA, 1, PREFIX + "poisoned_body_poisoned_world")
        sub = _context(engine, owner, other, intent, PREFIX + "poisoned_body_poisoned_world", "Poisoned Body, Poisoned World")
        with body_poison(engine, owner):
            te.run_effects(sub, [{"type": "save", "ability": "con", "evidence": "Poisoned Body, Poisoned World: Constitution saving throw",
                                  "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "damage_types": ["poison"]},
                                              {"type": "sovereign_venom", "count": 1}],
                                  "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["poison"]}]}])


@hook("event", nested=True)
def poisoned_world_damaged(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Native and typed committed packets share one post-damage caller.

    Exclude retaliation by its actual source, never by its displayed name or
    damage type. A child copy therefore cannot cause a retaliation chain.
    """
    if event_type != "DAMAGE_COMMITTED" or kwargs.get("source_definition_id") == PREFIX + "poisoned_body_poisoned_world":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    other = engine.state.actors.get(kwargs.get("actor_id"))
    for aid in kwargs.get("target_ids") or ():
        owner = engine.state.actors.get(aid)
        if owner is not None and owner is not other and "poisoned_world" in _roles(engine, owner):
            _retaliate(engine, owner, other, _intent(engine), f"{other.display_name} damaged {owner.display_name}" if other else "hostile damage")


@hook("condition_applied")
def poisoned_world_grappled(ctx: Any, name: str, subject: Any) -> None:
    if subject is not None and str(name).lower() == "grappled" and subject is not ctx.actor and _roles(ctx.engine, subject):
        _retaliate(ctx.engine, subject, ctx.actor, ctx.intent, f"{ctx.actor.display_name} Grappled {subject.display_name}")


@hook("turn_start_choice")
def poisoned_world_grappler(engine: Any, actor: Any) -> None:
    for owner in list(engine.state.actors.values()):
        if owner is actor or not _roles(engine, owner):
            continue
        if any(c.condition_id.endswith(".grappled") and c.source_actor_id == actor.entity_id for c in owner.conditions.values()):
            _retaliate(engine, owner, actor, _intent(engine), f"{actor.display_name} starts its turn Grappling {owner.display_name}")


@hook("row_allowed")
def swallow_source_allowed(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """Retaliation is expressly not hostile poison intake for Swallow."""
    if row.get("feature_id") != SWALLOW:
        return None
    from .damage_delivery import identity
    return False if identity(engine) == PREFIX + "poisoned_body_poisoned_world" else None


@hook("save_roll_tags")
def poison_save_tags(ctx: Any, subject: Any, ability: str, named: frozenset[str]) -> list[str] | None:
    """Carry only explicit source categories into this owner's rewrite prompt."""
    if not _swallow_ready(ctx.engine, subject):
        return None
    return sorted(named & {"category:poison", "category:disease", "category:ordinary_disease"})


@hook("save")
def disease_save_advantage(ctx: Any, actor: Any, ability: str, named: set[str]) -> dict | None:
    if "furnace" in _roles(ctx.engine, actor) and set(named or ()) & {"category:disease", "category:ordinary_disease"}:
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("effect_subject_allowed")
def ordinary_disease_immunity(ctx: Any, row: dict[str, Any], subject: Any) -> bool | None:
    """Only a source's explicit ordinary-disease category invokes immunity.

    Neither a toxic name nor a disease-only category supplies ordinary status.
    Higher authority categories take precedence over ordinary classification.
    """
    if "myriad" not in _roles(ctx.engine, subject):
        return None
    categories = set(row.get("save_categories") or row.get("source_categories") or ())
    if "ordinary_disease" in categories and not categories & {"tribulation", "curse", "foundation", "secret", "conceptual", "higher_authority"}:
        return False
    return None
