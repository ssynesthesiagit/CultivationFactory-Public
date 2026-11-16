"""The Piercing Needle's Guards that answer a won Disarm (rider lane 10, 2026-09-29): Bind Weapon, Meridian-Sealing Bind and
Traitorous Blade. Rules text: the owner's Sphere Compendium, "The Piercing Needle" (authority/typed_mechanics/rules_text.json).

  Bind Weapon      "When you win a Disarm attempt, you may bind the target's object to your weapon instead of causing the target to
                   drop it. You may also bind a hand, natural weapon, or comparable attacking limb as though it were a held object.
                   While the bind lasts: the target has the Grappled condition; the bound object or limb cannot be used to make
                   attacks; you must remain within the reach of the weapon or Unarmed Strike used to establish the bind; you cannot
                   use the weapon or limb maintaining the bind to make attacks; the bind ends if you become Incapacitated, release it
                   at any time with no Action required, or move beyond the permitted reach. If an object is bound, the target may
                   release that object at any time with no Action required, ending the bind. Otherwise, the target may use its Action
                   to make a Strength (Athletics) or Dexterity (Acrobatics) check against your Cultivation Save DC, ending the bind on
                   a success. Bind Weapon is a special form of Grapple."
  Meridian-Sealing "When a creature fails to escape your Bind Weapon, choose one of the following effects until the bind ends: the
  Bind             creature cannot take Reactions; the creature has Disadvantage on attack rolls against creatures other than you;
                   each foot of the creature's movement costs 1 extra foot. Choose a new effect each time the creature fails an
                   escape attempt."
  Traitorous Blade "When you win a Disarm attempt, you may immediately catch the disarmed object if: you have at least one free hand;
                   the object can be held in that hand; and the object is not physically attached to the target. After catching the
                   object, you may use a Bonus Action to make one attack with it if you can legally do so."

A Disarm is won when the target fails the save of a weapon's Disarm maneuver (its failure knocks the weapon away: typed_executor
block_condition "disarmed"). Bind Weapon asks the binder, after the failed save and before the weapon drops, to bind instead (the AI
binds); the drop is then skipped for that one save (the ``condition_immune`` answer below), and the bind is: the engine's own Grapple
(escape DC = the binder's Cultivation Save DC, the reach of the binding weapon -- it ends past that reach, on an escape and on the
binder's free "Release grapple"), the bound weapon's attacks disabled (a limb when the target holds no weapon), and the binder's
binding weapon disabled. A bound creature has a free "Let go of the bound weapon" (the object stays on the binder's blade and falls at
the binder's feet). Everything ends together when the grapple ends or the binder is Incapacitated.

Meridian-Sealing Bind: a failed escape check against the bind (the escape action's CHECK_ROLLED) lets the binder choose one effect,
replacing the last: no Reactions (the Reaction-denied condition), Disadvantage on attacks against others (attack_mode), or movement
costing double (half Speed, the speed hook).

Traitorous Blade: when the Disarm lands, the knocked-away weapon goes into the catcher's hand instead of the ground (the "Take a
dropped weapon" state, held_by); the free hand, a holdable and an unattached object are settled by combat/ext/hand_occupancy.py (a
Disarm only ever knocks away a held weapon, so only the hand and the weapon's own grip are read). If the catcher still has its
Bonus Action and a compiled attack with that weapon (a fight compiles every other fighter's weapons as ones it might take), it may
attack with it at once, spending the Bonus Action.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from .needle import CHOICE, ask, checkpoint_id, incapacitated, owns, save_dc, say as _say

BOUND = "condition:typed.needle_bound"        # on the bound creature: {binder, disables_action?, grip_reach}
BINDING = "condition:typed.needle_binding"    # on the binder: {target, disables_action}
SEAL = "condition:typed.needle_meridian_seal"  # on the bound creature: {binder, effect}
DENIED = "condition:typed.reaction_denied"
GRAPPLED = "condition:typed.grappled"
BIND_WEAPON, MERIDIAN, TRAITOROUS = "TAL_FENCING_BIND_WEAPON", "TAL_FENCING_MERIDIAN_SEALING_BIND", "TAL_FENCING_TRAITOROUS_BLADE"
_SUPPRESS = "_needle_bind_suppress"   # transient (target id, originating intent id); never saved fight state
_BUSY = "_needle_bind_busy"


def _of(actor: Any, condition_id: str) -> list[tuple[str, Any]]:
    return [(iid, c) for iid, c in actor.conditions.items() if c.condition_id == condition_id]


def _drop(engine: Any, actor: Any, iid: str, source: str) -> None:
    condition = actor.conditions.pop(iid, None)
    if condition is not None:
        engine._append_event("CONDITION_REMOVED", source, actor_id=condition.source_actor_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": iid})


def _weapon_base(action: Any) -> str | None:
    source = str(getattr(action, "source_definition_id", "") or "").split("#")[0]
    return source if ".weapon." in source else None


# ------------------------------------------------------------------------------------------------------------------ Bind Weapon
@hook("after_save")
def bind_on_disarm(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, _SUPPRESS)
    engine, binder = ctx.engine, ctx.actor
    if not failed or "disarmed" not in set(named or ()) or not subject.active or subject.team_id == binder.team_id:
        return
    if not owns(engine, binder, "bind_weapon") or _of(binder, BINDING):
        return  # one bind at a time: the binding weapon is busy
    from .. import typed_executor

    weapon = typed_executor._best_weapon_action(engine, subject)
    options = ["bind", "drop"]
    labels = {"bind": f"Bind {subject.display_name}'s {'weapon' if weapon else 'attacking limb'} to your weapon",
              "drop": "Knock it away (the ordinary Disarm)"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "BIND", binder.entity_id, subject.entity_id), binder, CHOICE + "bind_weapon",
                 options, labels=labels, preferred=["bind"], prompt="Bind Weapon: bind instead of disarming?", target_id=subject.entity_id)
    if picked[:1] != ["bind"]:
        return
    if weapon is not None:
        engine.__dict__[_SUPPRESS] = (subject.entity_id, getattr(ctx.intent, "intent_id", None))
    reach = int(getattr(ctx.action, "range_ft", None) or 5)
    dc = int(ctx.numbers.get("save_dc") or save_dc(engine, binder))
    source = ctx.source
    engine._apply_condition(subject, GRAPPLED, source, binder.entity_id, expires_on="UNTIL_REMOVED",
                            data={"escape_dc": dc, "reach_ft": reach, "label": f"Bound by {binder.display_name}'s Bind Weapon"})
    engine._apply_condition(subject, BOUND, source, binder.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": f"Bind Weapon: its {'weapon' if weapon else 'attacking limb'} is bound to {binder.display_name}'s weapon",
                                  "binder": binder.entity_id, "limb": weapon is None, **({"disables_action": weapon} if weapon else {})})
    held = _weapon_base(ctx.action)
    engine._apply_condition(binder, BINDING, source, binder.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": f"Bind Weapon: holding {subject.display_name}'s bind (that weapon cannot attack)",
                                  "target": subject.entity_id, **({"disables_action": held} if held else {})})
    _say(engine, source, binder, f"Bind Weapon: {binder.display_name} binds {subject.display_name}'s "
                                 f"{'weapon' if weapon else 'attacking limb'} to its own; {subject.display_name} is Grappled.", (subject.entity_id,))


@hook("condition_immune")
def bound_not_dropped(engine: Any, actor: Any, name: str) -> bool | None:
    """Suppress one drop in the binding action, never a later release or Disarm.

    The bound weapon may already be unavailable, so the typed drop can return
    before querying immunity. An unused flag must not survive into another
    action, or prevent a voluntary drop after this bind has ended.
    """
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, _SUPPRESS)
    pending = engine.__dict__.get(_SUPPRESS)
    if name == "disarmed" and pending is not None and pending[0] == actor.entity_id:
        engine.__dict__.pop(_SUPPRESS, None)
        intent_id = getattr(getattr(engine, "_active_intent", None), "intent_id", None)
        if intent_id is not None and pending[1] == intent_id and _of(actor, BOUND):
            return True
    return None


def end_bind(engine: Any, binder_id: str, target_id: str, source: str, why: str) -> None:
    """Everything the bind made ends together: the grapple, the bound and binding weapons, Meridian-Sealing Bind's effect."""
    if engine.__dict__.get(_BUSY):
        return
    engine.__dict__[_BUSY] = True
    try:
        binder, target = engine.state.actors.get(binder_id), engine.state.actors.get(target_id)
        ended = False
        if target is not None:
            for iid, c in _of(target, BOUND) + _of(target, SEAL):
                if (c.data or {}).get("binder") == binder_id:
                    _drop(engine, target, iid, source)
                    ended = True
            for iid, c in _of(target, DENIED):
                if (c.data or {}).get("needle_seal") == binder_id:
                    _drop(engine, target, iid, source)
            for iid, c in _of(target, GRAPPLED):
                if c.source_actor_id == binder_id and "Bind Weapon" in str((c.data or {}).get("label") or ""):
                    _drop(engine, target, iid, source)
        if binder is not None:
            for iid, c in _of(binder, BINDING):
                if (c.data or {}).get("target") == target_id:
                    _drop(engine, binder, iid, source)
                    ended = True
        if ended and binder is not None:
            _say(engine, source, binder, f"The bind ends ({why}).", (target_id,))
    finally:
        engine.__dict__.pop(_BUSY, None)


def _check_binds(engine: Any) -> None:
    for binder in list(engine.state.actors.values()):
        for _iid, binding in _of(binder, BINDING):
            target_id = str((binding.data or {}).get("target") or "")
            target = engine.state.actors.get(target_id)
            gripped = target is not None and target.active and any(c.source_actor_id == binder.entity_id for _i, c in _of(target, GRAPPLED))
            if not binder.active or incapacitated(binder):
                end_bind(engine, binder.entity_id, target_id, "system:needle.bind", f"{binder.display_name} is Incapacitated")
            elif not gripped:
                end_bind(engine, binder.entity_id, target_id, "system:needle.bind", "the grapple is over")


@hook("event")
def bind_watch(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ("CONDITION_REMOVED", "CONDITION_APPLIED", "ACTOR_DEFEATED", "ENTITY_DEFEATED", "CHECK_ROLLED") or engine.__dict__.get(_BUSY):
        return
    if event_type == "CHECK_ROLLED":
        _failed_escape(engine, kwargs)
        return
    if any(_of(actor, BINDING) for actor in engine.state.actors.values()):
        _check_binds(engine)


@effect("needle_release_bound")
def release_bound(ctx: Any, eff: dict[str, Any]) -> None:
    """The bound creature lets go of its bound weapon (no Action): the bind ends and the weapon stays with the binder's blade, falling
    at the binder's feet."""
    engine, actor = ctx.engine, ctx.actor
    for _iid, bound in _of(actor, BOUND):
        data = bound.data or {}
        binder = engine.state.actors.get(str(data.get("binder") or ""))
        weapon = data.get("disables_action")
        end_bind(engine, str(data.get("binder") or ""), actor.entity_id, ctx.source, f"{actor.display_name} lets go of its weapon")
        if weapon:
            spot = (binder or actor).position.model_dump(mode="json")
            engine._apply_condition(actor, "condition:typed.disarmed", ctx.source, str(data.get("binder") or actor.entity_id),
                                    expires_on="UNTIL_REMOVED", data={"disables_action": weapon, "dropped_at": spot})
        from .. import typed_executor

        typed_executor._reweigh(ctx)


@hook("compile_actions")
def release_action(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.let_go_bound", display_name="Let go of the bound weapon", owner_id=info["actor_id"],
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "needle_release_bound"}], "numbers": info.get("numbers") or {}, "duration": {"kind": "instant"},
                              "riders": []}, "expected_damage": 0, "player_only": True, "requires_condition": BOUND, "needle_release": True,
                    "description": "Bind Weapon: let go of the weapon bound to the enemy's blade (no Action); the bind and its grapple end, "
                                   "and the weapon falls at the binder's feet."})]


@hook("candidate_allowed")
def release_only_an_object(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not (getattr(action, "parameters", None) or {}).get("needle_release"):
        return None
    return any(not (c.data or {}).get("limb") for _i, c in _of(actor, BOUND)) or False  # a bound limb cannot be let go of


# ------------------------------------------------------------------------------------------------------ Meridian-Sealing Bind
SEALS = {"reactions": "It cannot take Reactions", "others": "Disadvantage on attack rolls against creatures other than the binder",
         "movement": "Each foot of its movement costs 1 extra foot"}


def _failed_escape(engine: Any, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if payload.get("success") is not False:
        return
    escaper = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    last = engine.events[-1] if getattr(engine, "events", None) else None  # the CHECK_ROLLED just appended: its source is the action
    action = (getattr(engine, "action_catalog", {}) or {}).get(str(getattr(last, "source_definition_id", "") or ""))
    if escaper is None or action is None or not any(isinstance(e, dict) and e.get("type") == "escape_grapple"
                                                    for e in ((action.parameters or {}).get("typed") or {}).get("effects") or []):
        return
    for _iid, bound in _of(escaper, BOUND):
        binder = engine.state.actors.get(str((bound.data or {}).get("binder") or ""))
        if binder is None or not binder.active or not owns(engine, binder, "meridian_sealing_bind"):
            continue
        intent = getattr(engine, "_active_intent", None)
        picked = ask(engine, intent, checkpoint_id(engine, "MERIDIAN", binder.entity_id, escaper.entity_id), binder, CHOICE + "meridian_seal",
                     list(SEALS), labels=dict(SEALS), preferred=["reactions"], target_id=escaper.entity_id,
                     prompt=f"Meridian-Sealing Bind: {escaper.display_name} failed to escape; choose one effect until the bind ends")
        if not picked:
            continue
        choice, source = picked[0], f"passive:{MERIDIAN}"
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, binder, source, independent=True):
            engine.__dict__[_BUSY] = True
            try:
                for iid, c in _of(escaper, SEAL):
                    if (c.data or {}).get("binder") == binder.entity_id:
                        _drop(engine, escaper, iid, source)  # "Choose a new effect each time": the new one replaces the last
                for iid, c in _of(escaper, DENIED):
                    if (c.data or {}).get("needle_seal") == binder.entity_id:
                        _drop(engine, escaper, iid, source)
                engine._apply_condition(escaper, SEAL, source, binder.entity_id, expires_on="UNTIL_REMOVED",
                                        data={"label": f"Meridian-Sealing Bind: {SEALS[choice]}", "binder": binder.entity_id, "effect": choice})
                if choice == "reactions":
                    engine._apply_condition(escaper, DENIED, source, binder.entity_id, expires_on="UNTIL_REMOVED",
                                            data={"label": "Meridian-Sealing Bind: cannot take Reactions", "needle_seal": binder.entity_id})
                    escaper.reaction_available = False
            finally:
                engine.__dict__.pop(_BUSY, None)
            _say(engine, source, binder, f"Meridian-Sealing Bind: {escaper.display_name} -- {SEALS[choice]} until the bind ends.", (escaper.entity_id,))


def _seal(actor: Any, which: str) -> Any | None:
    return next((c for _i, c in _of(actor, SEAL) if (c.data or {}).get("effect") == which), None)


@hook("attack_mode")
def sealed_attacks(ctx: Any, target: Any) -> str | None:
    found = _seal(ctx.actor, "others")
    return "DISADVANTAGE" if found is not None and target is not None and target.entity_id != (found.data or {}).get("binder") else None


@hook("speed")
def sealed_movement(engine: Any, actor: Any) -> int | None:
    if _seal(actor, "movement") is None:
        return None
    return -(int(getattr(actor, "speed_ft", 0) or 0) // 2)  # every foot costs 2: half as far


# ------------------------------------------------------------------------------------------------------------ Traitorous Blade
@hook("condition_applied")
def traitorous_catch(ctx: Any, name: str, target: Any) -> None:
    engine, catcher = ctx.engine, ctx.actor
    if name != "disarmed" or engine.__dict__.get(_BUSY):
        return
    if catcher is None or target is None or catcher.team_id == target.team_id or not owns(engine, catcher, "traitorous_blade"):
        return
    found = next((c for c in reversed(list(target.conditions.values())) if c.condition_id.endswith(".disarmed")
                  and c.source_actor_id == catcher.entity_id), None)
    iid = found.instance_id if found is not None else ""
    if found is None or not isinstance((found.data or {}).get("dropped_at"), dict) or not (found.data or {}).get("disables_action"):
        return
    weapon = str(found.data["disables_action"])
    intent = ctx.intent
    hand = _catching_hand(engine, catcher, weapon)
    if not hand:
        # "if you have at least one free hand" and "the object can be held in that hand": a Disarm only ever knocks away a held
        # weapon (combat/typed_executor.py block_condition "disarmed"), so the grip model settles both the object and the hand.
        # Say which of the two failed: one free hand is enough for anything but a Paired weapon, which rests in two.
        from .hand_occupancy import free_hands, holding_hands

        if not free_hands(engine, catcher):
            why = f"no free hand to catch {target.display_name}'s {_weapon_label(engine, weapon)} with"
        else:
            why = (f"one free hand is not enough to hold {target.display_name}'s {_weapon_label(engine, weapon)}, "
                   f"which rests in {holding_hands(engine, weapon)} hands")
        _say(engine, f"passive:{TRAITOROUS}", catcher, f"Traitorous Blade: {why}, so it falls.")
        return
    picked = ask(engine, intent, checkpoint_id(engine, "TRAITOROUS", catcher.entity_id, target.entity_id), catcher, CHOICE + "traitorous_blade",
                 ["catch", "let_fall"], labels={"catch": f"Catch the weapon in your {hand}", "let_fall": "Let it fall"}, preferred=["catch"],
                 name="Traitorous Blade", prompt=f"Traitorous Blade: {ctx.action.display_name} disarms {target.display_name}. Catch the object?",
                 target_id=target.entity_id)
    if picked[:1] != ["catch"]:
        return
    source = f"passive:{TRAITOROUS}"
    engine.__dict__[_BUSY] = True
    try:
        data = {key: value for key, value in (found.data or {}).items() if key != "dropped_at"}
        _drop(engine, target, iid, source)
        engine._apply_condition(target, found.condition_id, source, catcher.entity_id, expires_on="UNTIL_REMOVED", data={**data, "held_by": catcher.entity_id})
    finally:
        engine.__dict__.pop(_BUSY, None)
    _say(engine, source, catcher, f"Traitorous Blade: {catcher.display_name} catches {target.display_name}'s weapon in its {hand}.",
         (target.entity_id,))
    if getattr(engine, "_ext_in_event", False):
        ctx.rider(f"Traitorous Blade: GM resolves the bonus attack against {target.display_name}; event-triggered damage needs lock round 3's downstream dispatch seam.")
    else:
        _traitorous_attack(engine, catcher, target, weapon, intent)


def _weapon_label(engine: Any, weapon: str) -> str:
    """The caught object's own name for the fight log ("dagger", "warhammer"), never a catalog id."""
    action = engine.action_catalog.get(weapon)
    return getattr(action, "display_name", "weapon").removesuffix(" attack") if action is not None else "weapon"


def _catching_hand(engine: Any, catcher: Any, weapon: str) -> str:
    """The free hand Traitorous Blade's catch needs: "you have at least one free hand" and "the object can be held in that hand".

    The caught object is the weapon a Disarm knocked away, so the hands it takes are the hands that weapon
    *rests* in (combat/ext/hand_occupancy.py holding_hands: a Paired weapon occupies two, everything else one).
    A Two-Handed or Versatile weapon is held in one hand and needs its second hand only to attack, so one free
    hand catches it -- attacking with what you caught is the separate check in ``_traitorous_attack``. Default-inert:
    a character whose catalog has no managed grips still answers from its hand parts.
    """
    from .hand_occupancy import free_hands, holding_hands

    hands = free_hands(engine, catcher)
    return "" if len(hands) < holding_hands(engine, weapon) else str(hands[0]).removeprefix("hand:")


def _traitorous_attack(engine: Any, catcher: Any, target: Any, weapon: str, intent: Any) -> None:
    """"After catching the object, you may use a Bonus Action to make one attack with it if you can legally do so": the catcher's
    compiled attack with that weapon (requires_held_weapon), against the disarmed creature if it is still within reach."""
    if not catcher.bonus_action_available or not target.active:
        return
    action = next((engine.action_catalog[a] for a in catcher.action_ids if a in engine.action_catalog
                   and (engine.action_catalog[a].parameters or {}).get("requires_held_weapon") == weapon and "#" not in a), None)
    if action is None or engine.grid.distance_ft(catcher.position, target.position) > int(action.range_ft or 5):
        return
    picked = ask(engine, intent, checkpoint_id(engine, "TRAITOROUS_ATTACK", catcher.entity_id, target.entity_id), catcher,
                 CHOICE + "traitorous_attack", ["attack", "pass"], labels={"attack": "Bonus Action: attack with the caught weapon", "pass": "Not now"},
                 preferred=["attack"], name="Traitorous Blade",
                 prompt=f"Traitorous Blade: after disarming {target.display_name}, make one attack with the caught weapon?", target_id=target.entity_id)
    if picked[:1] != ["attack"]:
        return
    from ..typed_executor import Context, run_effects

    typed = copy.deepcopy((action.parameters or {}).get("typed") or {})
    attack = next((r for r in typed.get("effects") or [] if r.get("type") == "attack"), None)
    if attack is None:
        return
    catcher.bonus_action_available = False
    attack["count"] = 1
    attack.pop("count_by_cl", None)
    typed["effects"] = [attack]
    _say(engine, f"passive:{TRAITOROUS}", catcher, f"Traitorous Blade: {catcher.display_name} attacks with the caught weapon (Bonus Action).",
         (target.entity_id,))
    run_effects(Context(engine, catcher, action, intent, typed, [target], target), copy.deepcopy(typed.get("effects") or []))
