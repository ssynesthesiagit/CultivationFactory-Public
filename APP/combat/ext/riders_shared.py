"""Shared rider helpers used by riders_metal, next_damage_bonus, thread_lines and sniper_lines.

``expose`` -- "The next attack against the target before the start of your next turn gains a bonus to the attack roll equal to your
  Proficiency Bonus" (Metal, White Tiger Seven-Slaughter Canon: Open the Guard).  Effect
  {"type": "expose", "applies_to": "target", "bonus": "pb" | number, "next": true, "expires_on": "START_OF_SOURCE_NEXT_TURN"} puts an
  ``exposed`` condition on the target; the hook ``attack_bonus`` adds the bonus to a roll made against a creature that bears one
  (from any attacker, since the printed line names the attack, not its maker) and, when it is a "next" one, uses it up.  The
  attack's target is remembered by the ``attack_mode`` hook below: typed_executor calls attack_mode(ctx, target) just before
  attack_bonus(ctx, actor) for the same roll, and attack_bonus is not given the target.

``sphere_check`` -- "Make a Metal Check against DC 15 ... Success: ... Failure: ..." (any Sphere's own check).  Effect
  {"type": "sphere_check", "name": "Metal Check", "dc": 15 | "dc_of": "ac" | "save_dc" | "target_save_dc", "on_success": [...],
   "on_success_by_5": [...], "on_failure": [...]}: the user rolls d20 + Proficiency Bonus + the ability's key ability modifier (the
  same Cultivation-style
  check combat/ext/end_effect.py and Contesting Light roll) plus any check_bonus a plug-in gives, against the DC (a number, the
  target's Armor Class including active general AC modifiers (without attack-only
  cover), the ability's own save DC, or the target creature's own Cultivation Save DC -- "the target's Save DC", read through the
  public combat.ext.eye_common.numbers_of lookup exactly as Eight-Gate Diagnosis reads it; a target with no compiled numbers has no
  Save DC on the table, so the check is left to the GM as a rider and no branch runs), and the matching rows run.
  ``on_success_by_5`` runs in addition on a
  success by 5 or more.

  ``success_choices`` lists labeled effect bundles selected after a successful
  check; ``success_choices_by_5`` increases the selection count on a margin of
  five. Bell-Monastery Listening Sutra uses the shared choose_effects transport.
  With no choices these fields are inert and existing check branches are unchanged.

"""

from __future__ import annotations

from typing import Any

from . import effect, hook

# Shared helpers used by riders_metal, next_damage_bonus and thread_lines.
EXPOSED = "condition:typed.exposed"

# This is bookkeeping, not a separately selectable beneficial condition.
# end_effect's public selection rules exclude the existing mark.* namespace.
SINGLETON = "condition:typed.mark.singleton_benefit:"
SINGLETON_HP = "singleton_temp_hp:"


@effect("resistance_next")
def resistance_next(ctx: Any, eff: dict[str, Any]) -> None:
    """Grant self Resistance to one next qualifying damage packet, then consume all types.

    Iron-Bone uses this reusable self-buff; other typed self-buffs may use the
    same schema: damage_types plus the ordinary duration/expiry fields. Modifiers
    use damage_resistance_next, grouped by compiled source and source actor.
    typed_reactions weighs them without mutation and consumes the group only
    when a positive matching packet reaches defend, even if Resistance is ignored
    or Immunity prevents damage. Nonmatching/zero packets do not consume it.
    No owned typed action or non-self effect means no operation. Persistent state
    contains ordinary string modifiers; no new expiry or hook is introduced.
    """
    from ..typed_executor import effect_expiry

    if not ctx.typed.get("source") or eff.get("applies_to") != "self":
        return
    for kind in dict.fromkeys(str(k).upper() for k in eff.get("damage_types") or []):
        ctx.engine._add_modifier(ctx.actor, ctx.source, "damage_resistance_next", "SET", kind, "ALWAYS",
                                 expires_on=effect_expiry(ctx, eff, ctx.actor))


def remove_benefit_condition(engine: Any, actor: Any, condition: Any, reason: str) -> None:
    """Remove one instance for singleton benefits, Metal Canon, Thread and Sniper cleanup.

    Preserve unrelated conditions sharing its condition ID.
    """
    if actor.conditions.pop(condition.instance_id, None) is not None:
        engine._append_event("CONDITION_REMOVED", condition.source_definition_id,
                             actor_id=condition.source_actor_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": condition.condition_id,
                                      "instance_id": condition.instance_id, "reason": reason})


@effect("singleton_benefit")
def singleton_benefit(ctx: Any, eff: dict[str, Any]) -> None:
    """Replace one owned benefit across compiled choice/cost variants, then run its effects.

    Iron-Bone Internal Method uses this wrapper for its three choices. Any self
    benefit with the same printed singleton rule can reuse it. The source-bound
    mechanic ID is the group; only effects from the prior activation are ended.
    A provenance modifier records attributable temporary HP (integer only). Larger/equal
    pre-existing HP is kept; a later larger grant transfers ownership away.
    The marker's normal engine expiry also ends its attributable temporary HP.
    No matching owned mechanic means no operation.
    """
    from ..typed_executor import effect_expiry, run_effects

    mechanic = str(eff.get("mechanic_id") or "")
    if not mechanic or ctx.typed.get("source") != mechanic:
        return
    actor, engine = ctx.actor, ctx.engine
    cid = SINGLETON + mechanic
    old = [c for c in actor.conditions.values() if c.condition_id == cid
           and c.source_actor_id == actor.entity_id]
    for state in old:
        remove_benefit_condition(engine, actor, state, "REPLACED")
        # A cast triggered inside another event does not re-enter event hooks.
        clear_singleton_hp(engine, actor, cid)
        for condition in list(actor.conditions.values()):
            if condition.instance_id != state.instance_id and condition.source_definition_id == state.source_definition_id \
                    and condition.source_actor_id == actor.entity_id:
                remove_benefit_condition(engine, actor, condition, "REPLACED")
        for mid, modifier in list(actor.modifiers.items()):
            if modifier.source_definition_id == state.source_definition_id and modifier.source_actor_id == actor.entity_id:
                del actor.modifiers[mid]
                engine._append_event("MODIFIER_REMOVED", state.source_definition_id, actor_id=actor.entity_id,
                                     target_ids=(actor.entity_id,), payload={"modifier_id": mid, "reason": "REPLACED"})
    before = actor.temporary_hp
    run_effects(ctx, list(eff.get("effects") or []))
    owned = actor.temporary_hp if actor.temporary_hp > before else 0
    if owned:
        engine._add_modifier(actor, ctx.source, SINGLETON_HP + cid, "SET", int(owned), "ALWAYS",
                             expires_on="UNTIL_REMOVED")
    engine._apply_condition(actor, cid, ctx.source, actor.entity_id,
                            expires_on=effect_expiry(ctx, eff, actor, condition=True),
                            data={"label": ctx.action.display_name})


@hook("event")
def singleton_temp_hp(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Clear attributable HP when its marker is removed outside a nested event."""
    if event_type != "CONDITION_REMOVED":
        return
    payload = kwargs.get("payload") or {}
    cid = str(payload.get("condition_id") or "")
    if not cid.startswith(SINGLETON):
        return
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        if actor is not None:
            clear_singleton_hp(engine, actor, cid)


def clear_singleton_hp(engine: Any, actor: Any, cid: str) -> None:
    """Derive remaining owned HP from the retained event log, including nested events.

    The engine suppresses recursive event hooks. Reading the event stream rather
    than updating ownership on each hook also covers damage/grants inside other
    hooks and survives persistent table reload. Stop at this modifier's creation;
    no earlier fight history contributes. Remove provenance before clearing HP.
    """
    from .retained_updates import is_retained_update

    for mid, modifier in list(actor.modifiers.items()):
        if modifier.target_field != SINGLETON_HP + cid:
            continue
        later = []
        for event in reversed(engine.events):
            if is_retained_update(event.event_type, event.payload or {}):
                continue
            if event.event_type == "MODIFIER_APPLIED" and event.payload.get("modifier_id") == mid:
                break
            if actor.entity_id in event.target_ids and event.event_type in ("TEMP_HP_GRANTED", "DAMAGE_COMMITTED"):
                later.append(event)
        else:
            # Without creation evidence ownership is unknown. Preserve the HP.
            later = None
        owned = int(modifier.value) if later is not None else 0
        for event in reversed(later or []):
            p = event.payload
            if event.event_type == "TEMP_HP_GRANTED" and int(p.get("after") or 0) > int(p.get("before") or 0):
                owned = 0
            elif event.event_type == "DAMAGE_COMMITTED":
                owned = max(0, owned - int(p.get("temporary_hp_absorbed") or 0))
        del actor.modifiers[mid]
        engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=actor.entity_id,
                             target_ids=(actor.entity_id,), payload={"modifier_id": mid, "reason": "BENEFIT_ENDED"})
        if owned:
            before = actor.temporary_hp
            actor.temporary_hp = max(0, before - owned)
            engine._append_event("TEMP_HP_GRANTED", modifier.source_definition_id,
                                 actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"offered": 0, "before": before, "after": actor.temporary_hp})


@hook("turn_start")
@hook("turn_end")
def expired_singleton_hp(engine: Any, actor: Any) -> None:
    """Expiry hooks run inside TURN events, where nested event hooks are suppressed.

    The standard duration sweep precedes this module's turn hook. Clear orphaned
    provenance markers after it, without introducing a new expiry token.
    """
    for holder in engine.state.actors.values():
        for modifier in list(holder.modifiers.values()):
            if modifier.target_field.startswith(SINGLETON_HP):
                cid = modifier.target_field.removeprefix(SINGLETON_HP)
                if not any(c.condition_id == cid for c in holder.conditions.values()):
                    clear_singleton_hp(engine, holder, cid)


@effect("replace_owned_zones")
def replace_owned_zones(ctx: Any, eff: dict[str, Any]) -> None:
    """End this actor's zones from the listed mechanic IDs before creating a replacement.

    Used by Metal's Ten Thousand Blades singleton domain. Other singleton areas
    can use the same effect with their own ``mechanic_ids``. Match the compiled
    mechanic source, not the action ID: damage/choice variants are one ability.
    Removal uses zones.remove so terrain, inside conditions and events stay in
    sync. No listed IDs, or no matching owned zone, means no change.
    """
    from .. import zones

    ids = set(eff.get("mechanic_ids") or [])
    for zone in list(ctx.engine.state.zones.values()):
        if zone.owner_id != ctx.actor.entity_id:
            continue
        action = ctx.engine.action_catalog.get(zone.source_definition_id)
        typed = (action.parameters or {}).get("typed") or {} if action else {}
        if typed.get("source") in ids:
            zones.remove(ctx.engine, zone, "REPLACED")


# ------------------------------------------------------------------------------------------------ the attack's target
@hook("attack_mode")
def remember_target(ctx: Any, target: Any) -> str | None:
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_rs_attack_target")
    ctx.engine._rs_attack_target = target.entity_id
    return None


def attack_target(engine: Any) -> Any:
    return engine.state.actors.get(getattr(engine, "_rs_attack_target", None) or "")


# ------------------------------------------------------------------------------------------------ expose
@effect("expose")
def expose(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry

    bonus = ctx.numbers.get("pb", 2) if str(eff.get("bonus")) == "pb" else int(eff.get("bonus") or 0)
    for subject in _default_subject(ctx, eff, harmful=True):
        ctx.engine._apply_condition(subject, EXPOSED, ctx.source, ctx.actor.entity_id,
                                    expires_on=effect_expiry(ctx, eff, subject, condition=True) or "START_OF_SOURCE_NEXT_TURN",
                                    data={"bonus": int(bonus), "next": bool(eff.get("next", True)), "label": f"Exposed (+{bonus} to the next attack against it)"})


@hook("attack_bonus")
def exposed_bonus(ctx: Any, actor: Any) -> int | None:
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_rs_attack_target")
    engine = ctx.engine
    target = attack_target(engine)
    engine._rs_attack_target = None
    if target is None:
        return None
    total = 0
    for condition in list(target.conditions.values()):
        if condition.condition_id == EXPOSED:
            total += int((condition.data or {}).get("bonus") or 0)
            if (condition.data or {}).get("next", True):
                engine._remove_condition(target, condition.condition_id, ctx.source)
    return total or None


# ------------------------------------------------------------------------------------------------ sphere_check
@effect("sphere_check")
def sphere_check(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor
    from . import floored, run

    engine, actor = ctx.engine, ctx.actor
    numbers = ctx.numbers or {}
    bonus = int(numbers.get("pb") or 0) + int(numbers.get("key_mod") or 0) + sum(int(x) for x in run("check_bonus", ctx, actor) if isinstance(x, int))
    if eff.get("dc_of") == "ac" and ctx.target is not None:
        dc = int(ctx.target.armor_class) + engine._ac_modifier(ctx.target)
    elif eff.get("dc_of") == "save_dc":
        dc = int(numbers.get("save_dc") or 10)
    elif eff.get("dc_of") == "target_save_dc":
        # "against the target's Save DC": the target
        # creature's own Cultivation Save DC, the way Eight-Gate Diagnosis reads it. A target the table has no compiled
        # numbers for has no Save DC, so the printed check stays with the GM rather than rolling against a number invented here.
        from .eye_common import numbers_of

        target_dc = numbers_of(engine, ctx.target).get("save_dc") if ctx.target is not None else None
        if target_dc is None:
            ctx.rider(f"{eff.get('name') or 'Check'}: {ctx.target.display_name if ctx.target is not None else 'the target'}"
                      " has no Cultivation Save DC on the table, so the GM makes this check by hand.")
            return
        dc = int(target_dc)
    else:
        dc = int(eff.get("dc") or 10)
    roll = engine.roll_check(modifier=bonus, actor_id=actor.entity_id, reason=f"CHECK:{ctx.source}:{eff.get('name') or 'Check'}")
    engine._record_roll(roll)
    roll = floored(engine, actor, roll, dc)
    success = roll.total >= dc
    engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success, "skill": eff.get("name")})
    rows = list(eff.get("on_success" if success else "on_failure") or [])
    if success and roll.total - dc >= 5:
        rows += list(eff.get("on_success_by_5") or [])
    if rows:
        typed_executor.run_effects(ctx, [dict(row) for row in rows])
    if success and eff.get("success_choices"):
        typed_executor.run_effects(ctx, [{"type": "choose_effects",
            "name": str(eff.get("choice_name") or eff.get("name") or ctx.action.display_name),
            "count": int(eff.get("success_choices_by_5") or 1) if roll.total - dc >= 5 else 1,
            "options": list(eff["success_choices"])}])
