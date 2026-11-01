"""Unmaking talents that ride the table's hooks (rider lane C5, owner 2026-09-30: "i want everything we can automated").
The sphere's own flow (Ruin Channel, Overdraw, Black Vein Strain, Ruin Backlash) is combat/unmaking.py; the printed costs and
Crack are combat/ext/unmaking_channels.py. Every hook returns early unless the actor owns the talent (its compiled "unmaking"
block row) or the ability's own typed row carries the marker below, so other characters and older saved fights are untouched.

  Black Star Vessel   resistance_ignored: while the state lasts, the holder's Ruin (Force) damage from Unmaking talents
                      ignores Resistance; damage_source_alias maps the derived Unmaking packets (".overdraw", ".ruin_channel",
                      ...) to their Unmaking action only while a holder's state is up, so older fights replay unchanged.
                      event: when the state runs out, the second Ruin Backlash (combat/unmaking.black_star_ends).
  Black-Vein Step     opportunity_allowed: during the 10 free feet after an Overdraw, the creatures the talent damaged make
                      no Opportunity Attacks against you; "Black-Vein Step: unarmed strike" (free, once, for 1 more Strain)
                      against one of them within reach.
  Meridian Ruin Shock channel_delivered observes owned charged hits; after_hit_choice offers the CP/save/Strain rider.
  Shred the Temporary Shape damage_dealt on Unmaking packets and after_hit_choice on charged weapon hits;
                      once per damaged summoned target per activation, with its optional CP cost and refund.
  Ruin Forms          ruin_backlash: Second Form denies healing; surge(engine, actor, source): a form whose hit rider has "surge_effects" (Fourth
                      Ruin Form: 3d10 becomes 4d10) re-applies its stance with "surge". A stance's "on_end" rows run on its
                      user when its duration runs out (Fourth Ruin Form: no healing until the end of your next turn).
                      attack_damage_types: a stance with "unarmed_ruin" lets its Unarmed Strikes deal Ruin (Force) damage.
  Ruin Sheath Method  technique_used: a Ruin Channel lasts until the end of your next turn (the unspent-Channel choice is
                      combat/unmaking.channel_fizzled).
  Typed markers (inert effects on the ability's own row, read by the hooks here or by combat/unmaking.py):
    unmaking_upkeep          {"options": [...], "name"}: at the end of each of your turns while you concentrate on it, pay one
                             printed cost (unmaking_channels.pay).
    concentration_backlash   {"times": n, "reasons": [...]}: when your Concentration on it ends for one of those reasons
                             (FAILED_DAMAGE_CHECK: "breaks because of damage"), suffer Ruin Backlash n times.
    unmaking_domain          {"radius_ft", "healing_lock": bool, "concentration_save": {"dice_pb": sides}, "structures":
                             {"cl_damage": bool}}: while you concentrate on it, hostile creatures within radius that take
                             Ruin damage from you cannot regain HP that turn, one that starts a Concentration technique
                             there makes a Constitution save or takes PB dN Ruin, and the printed structures in the area
                             take Cultivation Level Ruin damage at the start of each of your turns (domain_structure_damage).
    overdraw_rule            {"targets": "one_failed_save" | "every_failed_save", "then_backlash": bool} (combat/unmaking.py).
  Unmake the Answer         unmaking_answer: the printed Unmaking Check against the triggering effect's save DC, from the
                            reaction's own context; success marks its creator's new effect cracked until the end of their next
                            turn and a success by 5 or more deals 5d10 Ruin damage to "the effect or its creator, chosen by
                            you if both are legal targets" (_answer_damage). The game can only put one of the two targets on
                            the roll, the creature making the effect: an object records the ability that put it on the map
                            but not which cast of it did (combat/ext/objects.created_by), and the check runs before the
                            triggering technique creates anything, so no standing object can honestly be called the effect
                            this cast is making. The log tells a Game Master who reads the choice as the effect how to move
                            the damage there instead of adding it. Failure is the printed 3d10 self-damage and 1 Strain.
  The Moment Nothing Answers  unmaking_max_hp_loss {"amount": n, "applies_to": "self"}: "reduce your current and maximum HP
                            by n until you finish a Long Rest", through combat/ext/maximum_hp_riders.max_hp_loss.
  First Ruin Form           unmaking_form_channel: "Choose one held weapon or implement" (an artifact weapon is a legal
                            choice; it simply never takes Crack), recorded on the form's own
                            condition so its delayed Crack and its Black Trace follow the chosen Channel; the free Black
                            Trace itself is offered through the ordinary checkpoint the moment the Channel breaks as the
                            form ends (combat/ext/unmaking_channels.py delay_or_crack / settle_delayed_crack).
  Splintering Trace         object_packets on a Black Trace instance, and damage_dealt against a creature the table labels a
                            construct: one extra d10 Ruin damage, two at CL 11.
  Crack the Guard           after a Ruin Channel hit through a weapon: its printed Strength-or-Constitution saving throw, of
                            its own choice (combat/ext/save_choices.py).
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from ..object_rules import label

STEP_STRIKE = "black_vein_step_strike"
# The form itself is a printed Bonus Action with its own button, so it carries NO feature_blocks row: an "unmaking"
# block row marks a feature automated, which stops its button compiling (combat/typed_reactions.compile_blocks) and
# stops its modifier applying (combat/factory_compiler.apply_modifiers). Its ownership is read from the character's
# own compiled record ids instead.
VESSEL_MANDATE = "TAL_UNMAKING_FIRST_RUIN_FORM_EXTERNAL_VESSEL_MANDATE"


@hook("channel_delivered")
def remember_charged_hit(ctx: Any, target: Any, weapon_id: str | None) -> None:
    """Record actual Ruin Channel delivery and its equipment; transient, per actual hit."""
    from .. import unmaking

    owned = unmaking.kinds(ctx.engine, ctx.actor)
    if not owned.intersection({"meridian_ruin_shock", "shred_the_temporary_shape", "crack_the_guard"}):
        return
    ctx.damage_cache[("unmaking_charged_hit", target.entity_id)] = {"weapon_id": weapon_id}


@hook("after_hit_choice")
def charged_talents(ctx: Any, target: Any, kind: str) -> None:
    from .. import unmaking
    delivery = ctx.damage_cache.pop(("unmaking_charged_hit", target.entity_id), None)
    if not target.active or delivery is None:
        return
    owned = unmaking.kinds(ctx.engine, ctx.actor)
    weapon_id = delivery["weapon_id"]
    weapon = ctx.engine.action_catalog.get(weapon_id) if weapon_id else None
    needle = weapon is not None and any(word in weapon.display_name.lower() for word in unmaking.NEEDLE_WORDS)
    if "meridian_ruin_shock" in owned and (weapon_id is None or (needle and "ruin_needle" in owned)):
        _meridian_ruin_shock(ctx, target)
    if "crack_the_guard" in owned and weapon_id is not None:
        _crack_the_guard(ctx, target)
    if ctx.typed.get("sphere") != unmaking.UNMAKING:
        _shred_damage(ctx, target)


def _crack_the_guard(ctx: Any, target: Any) -> None:
    """Crack the Guard: "When you hit a creature using a shield, armor, parrying weapon, warding bracer, or comparable
    defensive implement with a Ruin Channel attack, the target must succeed on a Strength or Constitution saving
    throw, target's choice."

    The printed save is mandatory and the target owns the choice, so it runs through combat/ext/save_choices.py. The
    printed precondition is asked first: the game carries one Armor Class number per creature and no shield or suit record,
    so only the attacker knows the target is behind a defensive implement (the same confirmation combat/ext/
    maximum_hp_riders.py asks for a prepared meal). The two answers the save gives are the GM's: the game tracks Crack on
    your own weapons, not on a shield or suit of armor, and it sums Armor Class as one number, so it cannot take a shield
    bonus away for one attacker.
    """
    from ..typed_executor import Context, run_effects
    from . import needle

    confirmed = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "CRACK_THE_GUARD_IMPLEMENT", ctx.source, target.entity_id),
                           ctx.actor, needle.CHOICE + "crack_the_guard_implement", ["defended"], allow_decline=True, default="decline",
                           labels={"defended": f"{target.display_name} is using a shield, armor, a parrying weapon, a warding bracer, "
                                               f"or a comparable defensive implement"},
                           name="Crack the Guard", feature_id="TAL_UNMAKING_CRACK_THE_GUARD",
                           prompt=f"Crack the Guard: {target.display_name} was hit by {ctx.action.display_name}. Confirm it is using a "
                                  f"shield, armor, a parrying weapon, a warding bracer, or a comparable defensive implement -- it must "
                                  f"succeed on a Strength or Constitution saving throw of its own choice. Decline when it has no "
                                  f"defensive implement; nothing is saved then.")
    if not confirmed:
        ctx.rider(f"Crack the Guard: {target.display_name} is not using a defensive implement, so nothing is saved.")
        return

    run_effects(Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache), [
        {"type": "save", "ability": "STR_OR_CON", "applies_to": "target", "target_choice": True,
         "name": "Crack the Guard", "dc": "technique_save_dc", "on_fail": [], "on_success": [],
         "choice_text": "Its defensive implement gains 1 Crack either way. A failure also leaves it unable to add its "
                        "shield AC against your attacks until the start of your next turn.",
         "evidence": "the target must succeed on a Strength or Constitution saving throw, target's choice"}])
    ctx.rider("Crack the Guard: on either result the target's defensive implement gains 1 Crack unless it is an artifact; "
              "a failure leaves it unable to add shield AC against your attacks until the start of your next turn.")


@hook("choice_reactors")
def guard_defenders(engine: Any) -> tuple[str, ...]:
    """Crack the Guard's Strength-or-Constitution save is built when the hit lands, so it is in no action catalog row for
    combat/ext/save_choices.potential_targets to find. Tell the service's AI-step probe that this fight has a possible
    defender to ask, so a manual defender is not silently decided by the attacker's controller. Only a character that owns
    Crack the Guard enrolls anybody, and the checkpoint itself still decides who is asked."""
    if any("crack_the_guard" in _kinds(engine, actor) for actor in engine.state.actors.values()):
        return tuple(engine.state.actors)
    return ()


def _meridian_ruin_shock(ctx: Any, target: Any) -> None:
    from .. import unmaking
    from ..typed_executor import Context, run_effects

    if not unmaking.optional_cp(ctx, target, "Meridian Ruin Shock", 1,
                                "Constitution save or no CP recovery, Reactions, and Disadvantage on Concentration saves until its next turn ends"):
        return
    until = "until_end_of_next_turn"
    run_effects(Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache), [
        {"type": "save", "ability": "con", "applies_to": "target", "evidence": "The target makes a Constitution saving throw.",
         "on_fail": [{"type": "condition", "condition": "no_cp_regain", "applies_to": "target", "duration": until,
                      "evidence": "Until the end of its next turn, the target cannot regain CP"},
                     {"type": "disadvantage", "applies_to": "target", "on": "Constitution saving throws to maintain Concentration", "duration": until,
                      "evidence": "has Disadvantage on Constitution saving throws to maintain Concentration"},
                     {"type": "condition", "condition": "reaction_denied", "applies_to": "target", "duration": until,
                      "evidence": "and cannot take Reactions"}],
         "on_success": [{"type": "condition", "condition": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                         "evidence": "Until the start of your next turn, the target cannot take Reactions."}]}])
    unmaking.gain_strain_checked(ctx, 1, "passive:meridian_ruin_shock")


@hook("damage_dealt")
def shred_unmaking_damage(ctx: Any, target: Any, amount: int) -> None:
    from .. import unmaking

    if amount > 0 and ctx.typed.get("sphere") == unmaking.UNMAKING:
        _shred_damage(ctx, target)


def _shred_damage(ctx: Any, target: Any) -> None:
    from .. import unmaking
    from ..gate2_runtime_models import DiceSpec

    key = ("shred_target", target.entity_id)
    if (not target.active or target.summon is None or ctx.damage_cache.get(key)
            or "shred_the_temporary_shape" not in unmaking.kinds(ctx.engine, ctx.actor)):
        return
    ctx.damage_cache[key] = True
    pb = int(ctx.numbers.get("pb") or 2)
    if not unmaking.optional_cp(ctx, target, "Shred the Temporary Shape", 1, f"3d8 + {pb} more Ruin damage to {target.display_name}"):
        return
    roll = ctx.engine.roller.roll(DiceSpec(count=3, sides=8, modifier=pb), actor_id=ctx.actor.entity_id, reason=f"SHRED:{ctx.source}")
    ctx.engine._record_roll(roll)
    added = int(roll.total)
    ctx.engine._commit_damage(target, added, "FORCE", f"{ctx.source}.shred_the_temporary_shape", ctx.actor.entity_id, None, reaction_depth=0)
    ctx.rider(f"Shred the Temporary Shape: +{added} Ruin damage to {target.display_name}.")
    if not target.active and not ctx.actor.turn_flags.get("shred_cp_regained"):
        ctx.actor.turn_flags["shred_cp_regained"] = True
        pool = next((pool for pool in ("resource:core.qi", "resource:core.stamina", "resource:core.resonance") if pool in ctx.actor.resources), None)
        if pool is not None:
            ctx.engine._gain_resource(ctx.actor, pool, 1, f"{ctx.source}.shred_the_temporary_shape")
            ctx.rider("Shred the Temporary Shape: 1 CP regained.")
_DERIVED = (".overdraw", ".black_trace_mark", ".execution_through_the_fault", ".black_star_vessel", ".shred_the_temporary_shape",
            ".ruin_channel")


def _kinds(engine: Any, actor: Any) -> set[Any]:
    from .. import unmaking

    return unmaking.kinds(engine, actor)


def _typed(engine: Any, source_id: str) -> dict[str, Any]:
    action = engine.action_catalog.get(str(source_id or ""))
    return ((action.parameters or {}).get("typed") or {}) if action is not None else {}


def _marker(typed: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == name), None)


def context_of(engine: Any, actor: Any, source_id: str, target: Any = None) -> Any:
    """A typed Context for one of the actor's own actions (turn and event hooks have none of their own)."""
    from ..typed_executor import Context

    action = engine.action_catalog[source_id]
    typed = copy.deepcopy((action.parameters or {}).get("typed") or {})
    return Context(engine, actor, action, getattr(engine, "_active_intent", None), typed,
                   [target] if target is not None else [], target, {})


# ------------------------------------------------------------------------------------------------ inert markers
@effect("overdraw_rule")
def overdraw_rule(ctx: Any, eff: dict[str, Any]) -> None:
    """Read by combat/unmaking.py when the technique Overdraws; nothing to do when the row itself runs."""


@effect("unmaking_upkeep")
def unmaking_upkeep(ctx: Any, eff: dict[str, Any]) -> None:
    """Read at the end of each of the user's turns (upkeep below)."""


@effect("concentration_backlash")
def concentration_backlash(ctx: Any, eff: dict[str, Any]) -> None:
    """Read when Concentration on the technique ends (on_event below)."""


@effect("unmaking_domain")
def unmaking_domain(ctx: Any, eff: dict[str, Any]) -> None:
    """Read while the user concentrates on the technique (_domain_healing_lock, domain_concentration_save)."""


# ------------------------------------------------------------------------------------------------ Black Star Vessel
def _black_star(actor: Any) -> bool:
    from ..unmaking import BLACK_STAR_ACTIVE

    return actor is not None and any(c.condition_id == BLACK_STAR_ACTIVE for c in actor.conditions.values())


@hook("resistance_ignored")
def black_star_resistance(engine: Any, kind: str, typed: dict[str, Any], source_actor_id: str | None, target: Any = None) -> bool | None:
    from ..unmaking import UNMAKING

    actor = engine.state.actors.get(source_actor_id or "")
    if kind != "FORCE" or (typed or {}).get("sphere") != UNMAKING or not _black_star(actor):
        return None
    return True


@hook("damage_source_alias")
def unmaking_packet(engine: Any, source: str | None) -> str | None:
    text = str(source or "")
    suffix = next((end for end in _DERIVED if text.endswith(end)), None)
    if suffix is None:
        return None
    parent = text[:-len(suffix)]
    action = engine.action_catalog.get(parent) or engine.action_catalog.get(parent.split("#", 1)[0])
    owner = engine.state.actors.get(action.owner_id) if action is not None else None
    if owner is None or not _black_star(owner):
        return None
    from ..unmaking import UNMAKING

    if suffix == ".ruin_channel":  # the charged hit of a weapon or unarmed strike: the owner's Ruin Channel ability
        return next((key for key, row in sorted(engine.action_catalog.items()) if row.owner_id == owner.entity_id
                     and any(isinstance(e, dict) and e.get("type") == "ruin_channel" for e in _typed(engine, key).get("effects") or [])), None)
    return action.source_definition_id if _typed(engine, action.source_definition_id).get("sphere") == UNMAKING else None


# ------------------------------------------------------------------------------------------------ events
def _this_event(engine: Any, event_type: str, kwargs: Any) -> Any:
    """Prefer the recorded identity; retain exact-field lookup for legacy callers."""
    recorded = (kwargs or {}).get("originating_event")
    if recorded is not None and recorded.event_type == event_type:
        return recorded
    payload = (kwargs or {}).get("payload") or {}
    targets = tuple((kwargs or {}).get("target_ids") or ())
    return next((event for event in reversed(engine.events) if event.event_type == event_type and event.actor_id == (kwargs or {}).get("actor_id")
                 and tuple(event.target_ids or ()) == targets and (event.payload or {}) == payload), None)


@hook("event")
def on_event(engine: Any, event_type: str, kwargs: Any) -> None:
    payload = (kwargs or {}).get("payload") or {}
    if event_type == "CONDITION_REMOVED" and payload.get("checkpoint"):
        from .. import stances, unmaking

        holder = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
        if holder is None:
            return
        if payload.get("condition_id") == unmaking.BLACK_STAR_ACTIVE:
            unmaking.black_star_ends(engine, holder, "passive:TAL_UNMAKING_BLACK_STAR_VESSEL")
        elif str(payload.get("condition_id") or "").startswith(stances.PREFIX):
            _stance_ended(engine, holder, str(payload["condition_id"]))
    elif event_type == "CONCENTRATION_ENDED":
        event = _this_event(engine, event_type, kwargs)
        if event is not None:
            _concentration_ended(engine, event)
    elif event_type == "DAMAGE_COMMITTED":
        _domain_healing_lock(engine, kwargs, payload)


def _concentration_ended(engine: Any, event: Any) -> None:
    """"If Concentration breaks because of damage, suffer Ruin Backlash" (concentration_backlash rows).

    The shared ending dispatcher delivers this once, including loss caused by
    upkeep's own self-damage inside a turn hook.
    """
    actor = engine.state.actors.get(event.actor_id or "")
    source = str(event.source_definition_id or "")
    row = _marker(_typed(engine, source), "concentration_backlash") if actor is not None else None
    if row and str((event.payload or {}).get("reason")) in (row.get("reasons") or ["FAILED_DAMAGE_CHECK"]) and actor.active:
        from .. import unmaking

        for _ in range(int(row.get("times") or 1)):
            unmaking.self_damage(engine, actor, unmaking.backlash(engine, actor, source), f"{source}.ruin_backlash")
        engine._append_event("PASSIVE_TRIGGERED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"trigger": f"Concentration broke: Ruin Backlash x{int(row.get('times') or 1)}."})


def _stance_ended(engine: Any, holder: Any, condition_id: str) -> None:
    """A form's own "When the form ends" rows, from the holder's own action that starts that stance."""
    from .. import stances
    from . import unmaking_channels

    if condition_id == unmaking_channels.VESSEL_FORM:
        _vessel_ended(engine, holder)
    for key, action in sorted(engine.action_catalog.items()):
        if action.owner_id != holder.entity_id or "#" in key:
            continue
        for row in _typed(engine, key).get("effects") or []:
            if isinstance(row, dict) and row.get("type") == "stance" and stances.PREFIX + stances.slug(row.get("name") or action.display_name) == condition_id \
                    and row.get("on_end"):
                from ..typed_executor import run_effects

                ctx = context_of(engine, holder, key, holder)
                run_effects(ctx, copy.deepcopy(row["on_end"]))
                return


def _vessel_ended(engine: Any, holder: Any) -> None:
    """First Ruin Form: External Vessel Mandate -- "when the form ends, all delayed Crack applies at once. If the
    Channel breaks when the form ends, you may immediately make one Black Trace attack against a creature within 30
    feet as the weapon dies. This attack cannot Overdraw."

    The delayed Crack lands here, and a Channel that breaks as it applies offers its free Black Trace at once. The offer is
    a checkpoint, so it reaches the owner whether the form ends at the end of its own turn (its printed 1 minute, swept by
    the engine's own end-of-turn expiry) or off-turn: the fight pauses for the answer and the attack resolves in the same
    transaction, the way a granted reaction attack does (combat/ext/needle.py parry_riposte)."""
    from . import unmaking_channels

    weapon_id, broke = unmaking_channels.settle_delayed_crack(engine, holder, VESSEL_MANDATE)
    if weapon_id and broke:
        _vessel_black_trace(engine, holder, weapon_id)


def _vessel_black_trace(engine: Any, holder: Any, weapon_id: str) -> None:
    """The free Black Trace: one optional attack, against a visible creature within 30 feet, as the Channel dies."""
    from .. import typed_executor
    from ..stealth import sees
    from . import note, needle, unmaking_channels

    if not holder.active or holder.life_state not in (None, "CONSCIOUS"):
        return
    targets = [a for a in sorted(engine.state.actors.values(), key=lambda row: row.entity_id)
               if a.active and a.life_state in (None, "CONSCIOUS") and a.entity_id != holder.entity_id
               and a.team_id != holder.team_id and engine._distance_actor_to_actor(holder, a) <= 30 and sees(engine, holder, a)]
    strike = next(iter(_black_trace_attacks(engine, holder)), None)
    if strike is None or not targets:
        note(engine, VESSEL_MANDATE, holder,
             f"First Ruin Form: {unmaking_channels.channel_name(engine, weapon_id)} breaks as the form ends. "
             + ("You have no Black Trace to use as the weapon dies." if strike is None
                else "No visible creature is within 30 feet for the free Black Trace."))
        return
    picked = needle.ask(engine, getattr(engine, "_active_intent", None),
                        needle.checkpoint_id(engine, "VESSEL_BLACK_TRACE", holder.entity_id), holder,
                        needle.CHOICE + "vessel_black_trace", [a.entity_id for a in targets],
                        allow_decline=True, default="decline", name="First Ruin Form: Black Trace", feature_id=VESSEL_MANDATE,
                        labels={a.entity_id: f"{a.display_name}, {engine._distance_actor_to_actor(holder, a)} feet away" for a in targets},
                        prompt=f"First Ruin Form: {unmaking_channels.channel_name(engine, weapon_id)} breaks as the form ends, so "
                               f"you may make one Black Trace attack against a visible creature within 30 feet. It costs no Action "
                               f"and cannot Overdraw. Choose a creature, or decline to keep the attack for nothing.")
    if not picked:
        note(engine, VESSEL_MANDATE, holder, "First Ruin Form: the free Black Trace is declined; the broken Channel is spent.")
        return
    target = engine.state.actors.get(picked[0])
    if target is None or not target.active:
        return
    key, attack = strike
    typed = {**_typed(engine, key), "numbers": needle.numbers_of(engine, holder) or {}}
    # "This attack cannot Overdraw": the Overdraw only rides a sphere Unmaking use (combat/typed_executor.py:4045), and
    # this row carries no sphere, so nothing is added and no Black Vein Strain is gained for it.
    note(engine, VESSEL_MANDATE, holder, f"First Ruin Form: {holder.display_name} traces {target.display_name} as the Channel dies.",
         (target.entity_id,))
    typed_executor.run_effects(typed_executor.Context(engine, holder, engine.action_catalog[key],
                                                      getattr(engine, "_active_intent", None), typed, [target], target, {}),
                               [copy.deepcopy(attack)])


# ------------------------------------------------------------------------------------------------ Ruin Forms
@hook("ruin_backlash")
def form_backlash(engine: Any, actor: Any, source: str) -> None:
    """Second Form denies healing until it ends; Fourth Form increases its owned damage rider."""
    from .. import stances

    for condition in stances.active(actor):
        if condition.condition_id == stances.PREFIX + "second_ruin_form":
            from .effect_durations import continuing_expiry, transfer_expiry_clock
            mid = engine._add_modifier(actor, f"{source}.second_ruin_form", "healing_reduction", "ADD", "none", "ALWAYS",
                                      expires_on=continuing_expiry(actor, condition, condition.expires_on,
                                                                  engine.state.current_actor_id))
            transfer_expiry_clock(actor, condition, actor, actor.modifiers[mid])
    surge(engine, actor, source)


def surge(engine: Any, actor: Any, source: str) -> None:
    """After a Ruin Backlash: a form whose hit rider carries "surge_effects" uses them until it ends (Fourth Ruin Form: 4d10)."""
    from .effect_durations import apply_condition_preserving_clock, skipped_expiry_slots
    from .. import stances

    for condition in list(stances.active(actor)):
        data = dict(condition.data or {})
        if data.get("surge") or not any(rider.get("surge_effects") for rider in data.get("hit_riders") or []):
            continue
        skipped = skipped_expiry_slots(actor, condition)
        engine._remove_condition(actor, condition.condition_id, source)
        apply_condition_preserving_clock(engine, actor, condition, condition.condition_id, condition.source_definition_id, actor.entity_id, expires_on=condition.expires_on,
                                data={**data, "surge": True, "label": f"{data.get('name')}: Ruin Backlash -- the added damage is greater until it ends"},
                                skipped_slots=skipped)


@hook("attack_damage_types")
def unarmed_ruin(ctx: Any, attack: dict[str, Any], kinds: list[str]) -> list[str] | None:
    """A stance's "unarmed_ruin" (Second Ruin Form: Unarmed Strikes) or "melee_ruin" (Fourth Ruin Form: melee weapon attacks and
    Unarmed Strikes) lets those attacks deal Ruin (Force) damage; the engine's damage-type pick takes whichever lands best."""
    from .. import stances
    from ..typed_executor import ranged_attack_now

    unarmed = attack.get("attack_kind") == "unarmed" or ".natural." in ctx.source
    melee_weapon = ctx.typed.get("weapon") is not None and not ranged_attack_now(ctx)
    flags = [c.data or {} for c in stances.active(ctx.actor)]
    if not any((unarmed and (f.get("unarmed_ruin") or f.get("melee_ruin"))) or (melee_weapon and f.get("melee_ruin")) for f in flags):
        return None
    upper = bool(kinds) and str(kinds[0]).isupper()
    return list(dict.fromkeys([*kinds, "FORCE" if upper else "force"]))


# ------------------------------------------------------------------------------------------------ Ruin Sheath Method
@hook("technique_used")
def ruin_sheath(ctx: Any) -> None:
    if not any(isinstance(row, dict) and row.get("type") == "ruin_channel" for row in ctx.typed.get("effects") or []) \
            or "ruin_sheath_method" not in _kinds(ctx.engine, ctx.actor):
        return
    from ..unmaking import CHANNEL

    charge = next((c for c in ctx.actor.conditions.values() if c.condition_id == CHANNEL), None)
    if charge is None:
        return
    data = dict(charge.data or {})
    ctx.engine._remove_condition(ctx.actor, CHANNEL, ctx.source)
    ctx.engine._apply_condition(ctx.actor, CHANNEL, charge.source_definition_id, ctx.actor.entity_id,
                                expires_on=f"END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started) + 1}",
                                data={**data, "label": "Ruin Channel (charged, until the end of your next turn: Ruin Sheath Method)"})


# ------------------------------------------------------------------------------------------------ upkeep and domains
@hook("turn_end")
def vessel_settle_safety(engine: Any, actor: Any) -> None:
    """A held-back Crack settles at the end of any turn on which the form is no longer up, so a form that was removed
    without the engine's expiry checkpoint still pays out."""
    from . import unmaking_channels

    if unmaking_channels.vessel_form(actor) is None and unmaking_channels.delayed_crack(actor) is not None:
        _vessel_ended(engine, actor)


@hook("turn_end")
def upkeep(engine: Any, actor: Any) -> None:
    from .. import concentration
    from . import unmaking_channels

    for source in concentration.sources(actor):
        row = _marker(_typed(engine, source), "unmaking_upkeep")
        if row and actor.active and source in engine.action_catalog:
            unmaking_channels.pay(context_of(engine, actor, source), list(row.get("options") or []),
                                  name=str(row.get("name") or engine.action_catalog[source].display_name))


def _domains(engine: Any, owner: Any) -> list[dict[str, Any]]:
    from .. import concentration

    return [row for source in concentration.sources(owner) if (row := _marker(_typed(engine, source), "unmaking_domain"))]


def _domain_healing_lock(engine: Any, kwargs: Any, payload: dict[str, Any]) -> None:
    owner = engine.state.actors.get(kwargs.get("actor_id") or "")
    target = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    if owner is None or target is None or not target.active or target.team_id == owner.team_id or str(payload.get("damage_type")).upper() != "FORCE" \
            or int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    rows = [row for row in _domains(engine, owner) if row.get("healing_lock")]
    if not rows or engine._distance_actor_to_actor(owner, target) > max(int(row.get("radius_ft") or 0) for row in rows):
        return
    from ..unmaking import my_unmaking_source

    event = _this_event(engine, "DAMAGE_COMMITTED", kwargs)
    if event is None or not my_unmaking_source(engine, owner, str(event.source_definition_id or "")):
        return
    if any(m.target_field == "healing_reduction" and m.expires_on == "END_OF_CURRENT_TURN" and m.source_definition_id == "domain_of_collapse:" + owner.entity_id
           for m in target.modifiers.values()):
        return
    engine._add_modifier(target, "domain_of_collapse:" + owner.entity_id, "healing_reduction", "ADD", "none", "ALWAYS", expires_on="END_OF_CURRENT_TURN")


# "summoned constructs" -- the printed creature label, nothing inferred from a name, a condition or an immunity
# (combat/ext/creature_kinds.py).
STRUCTURE_KINDS = ("construct", "summoned construct", "animated construct")


def printed_structure(actor: Any) -> bool:
    """Whether a creature is one of Fifth Ruin Form's printed "summoned constructs": a summoned creature the table labels a
    construct. A summoned living creature (a called animal, a reanimated corpse) is not a construct, and an ordinary creature
    is not a structure at all."""
    from . import creature_kinds

    return actor.summon is not None and creature_kinds.matches(actor, STRUCTURE_KINDS)


def printed_object_structure(obj: Any) -> bool:
    """Whether a map object is one of the form's printed structures: "temporary qi structures, ... barriers, wards". A
    creature built it (it carries that creature's id as its owner), so it is one of the qi's own works. The arena's own
    furniture -- a crate, a barrel, a wooden door, a stone wall -- is a permanent thing, not a qi structure, and nothing
    here damages it."""
    return getattr(obj, "owner_id", None) is not None


@hook("turn_start")
def domain_structure_damage(engine: Any, actor: Any) -> None:
    """Fifth Ruin Form: Domain of Collapse -- "temporary qi structures, summoned constructs, barriers, wards, and
    non-Secret defensive effects in the area take Ruin damage equal to your Cultivation Level at the start of each
    of your turns". A typed ``unmaking_domain`` row opts in with ``structures: {"cl_damage": true}``.

    The table's structures are its summoned constructs and the barriers and wards a creature put up (a map object with an
    owner). A summoned living creature and the arena's own furniture are not structures, so they are untouched. The printed
    bullet names "summoned constructs" with no "hostile" in front of them, and the hostility words live on the other bullets,
    so a construct the owner itself summoned falls like any other -- the area is hostile ground, not a team filter. No other
    kind of "temporary qi structure" or "non-Secret defensive effect" is a thing this table tracks; the remainder of the
    printed line stays a reminder.
    """
    from . import objects

    for row in _domains(engine, actor):
        if not (row.get("structures") or {}).get("cl_damage"):
            continue
        source = next((key for key in engine.action_catalog
                       if _marker(_typed(engine, key), "unmaking_domain") is row), None)
        if source is None:
            continue
        amount = int(unmaking_cultivation_level(engine, actor))
        radius = int(row.get("radius_ft") or 0)
        ctx = context_of(engine, actor, source, actor)
        structures = 0
        for summon in sorted(engine.state.actors.values(), key=lambda row_: row_.entity_id):
            if (summon.active and printed_structure(summon)
                    and engine._distance_actor_to_actor(actor, summon) <= radius):
                engine._commit_damage(summon, amount, "FORCE", f"{source}.domain_of_collapse", actor.entity_id, None, reaction_depth=0)
                structures += 1
        for obj in sorted(engine.state.objects.values(), key=lambda row_: row_.object_id):
            if obj.destroyed or not printed_object_structure(obj) or engine._distance_actor_to_cell(actor, obj.position) > radius:
                continue
            objects.deal(engine, actor, obj, [(amount, "FORCE")], f"{source}.domain_of_collapse")
            structures += 1
        ctx.rider(f"{engine.action_catalog[source].display_name}: {structures} summoned construct(s) or qi "
                  f"structure(s) within {radius} feet take {amount} Ruin damage.")


def unmaking_cultivation_level(engine: Any, actor: Any) -> int:
    from .. import unmaking

    return unmaking.cultivation_level(engine, actor)


@hook("technique_start")
def domain_concentration_save(engine: Any, actor: Any, action: Any) -> None:
    """A hostile creature in the domain starting a Concentration technique: a Constitution save or PB dN Ruin damage."""
    typed = (action.parameters or {}).get("typed") or {}
    if not (typed.get("duration") or {}).get("concentration"):
        return None
    for owner in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        if not owner.active or owner.team_id == actor.team_id:
            continue
        from .. import concentration

        for source in concentration.sources(owner):
            row = _marker(_typed(engine, source), "unmaking_domain")
            save = (row or {}).get("concentration_save")
            if not save or engine._distance_actor_to_actor(owner, actor) > int(row.get("radius_ft") or 0):
                continue
            from ..typed_executor import run_effects

            ctx = context_of(engine, owner, source, actor)
            pb = int(ctx.numbers.get("pb") or 2)
            run_effects(ctx, [{"type": "save", "ability": "con", "applies_to": "target",
                               "evidence": "A hostile creature in the domain starts a Concentration technique: Constitution save.",
                               "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": pb, "sides": int(save.get("dice_pb") or 10)},
                                            "damage_types": ["force"], "evidence": "Ruin damage equal to your Proficiency Bonus d10"}],
                               "on_success": []}])
    return None


# ------------------------------------------------------------------------------------------------ Black-Vein Step
def _step(actor: Any) -> tuple[int, list[str]] | None:
    raw = str(actor.turn_flags.get("black_vein_step") or "")
    if "|" not in raw:
        return None
    budget, _, ids = raw.partition("|")
    return int(budget), [part for part in ids.split(",") if part]


@hook("event")
def step_window(engine: Any, event_type: str, kwargs: Any) -> None:
    actor = engine.state.actors.get((kwargs or {}).get("actor_id"))
    if actor is None or _step(actor) is None:
        return
    payload = (kwargs or {}).get("payload") or {}
    if event_type == "MOVEMENT_COMMITTED" and not payload.get("forced"):
        spent = int(actor.turn_flags.get("black_vein_step_moved") or 0) + int(payload.get("cost_ft") or 0)
        actor.turn_flags["black_vein_step_moved"] = spent
        if spent > 10:
            actor.turn_flags["black_vein_step_closed"] = 1
    elif event_type == "INTENT_ACCEPTED" and payload.get("kind") != "MOVE":
        event = _this_event(engine, event_type, kwargs)
        action = engine.action_catalog.get(event.source_definition_id) if event else None
        if action is None or not (action.parameters or {}).get("black_vein_step_strike"):
            actor.turn_flags["black_vein_step_closed"] = 1


@hook("opportunity_allowed")
def step_no_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    step = _step(mover)
    if step is None or reactor.entity_id not in step[1]:
        return None
    return False if not mover.turn_flags.get("black_vein_step_closed") and step[0] - int(mover.movement_remaining_ft) < 10 else None


@hook("compile_actions")
def step_strike(info: dict[str, Any]) -> list[Any] | None:
    if not any(row.get("block") == "unmaking" and row.get("kind") == "black_vein_step" for row in info["passives"]):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.black_vein_step.strike", display_name="Black-Vein Step: unarmed strike",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
        parameters={"typed": {"effects": [{"type": STEP_STRIKE, "evidence": "If you end this movement adjacent to a creature damaged by the talent, "
                                                                              "you may gain 1 additional Black Vein Strain to make one unarmed strike against that creature."}],
                              "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 3, "black_vein_step_strike": True,
                    "description": "After Overdraw, move up to 10 feet without provoking Opportunity Attacks from creatures "
                                   "that talent damaged. At the end of that movement, strike one of them within 5 feet once "
                                   "without using an Action. Gain 1 Black Vein Strain: at 3 Strain, your first Unmaking use "
                                   "each turn deals self-damage equal to your Proficiency Bonus; at 6, you take 2d6 plus "
                                   "your Cultivation Level in self-damage and Strain normally falls to 3. Further ordinary "
                                   "movement closes this option."})]


@hook("candidate_allowed")
def step_strike_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not (action.parameters or {}).get("black_vein_step_strike"):
        return None
    step = _step(actor)
    targets = tuple(getattr(candidate, "target_ids", None) or ())
    spent = step[0] - int(actor.movement_remaining_ft) if step else 0
    return bool(step and 0 < spent <= 10 and not actor.turn_flags.get("black_vein_step_closed")
                and not actor.turn_flags.get("black_vein_step_struck") and targets and all(t in step[1] for t in targets))


@effect("unmaking_form_channel")
def unmaking_form_channel(ctx: Any, eff: dict[str, Any]) -> None:
    """First Ruin Form: External Vessel Mandate -- "Choose one held weapon or implement." Ask which one, and record it on
    the form's own condition as one action id (a string, so a saved fight keeps it), because the form's printed d6, its
    delayed Crack and its settling Black Trace are all about the chosen Channel. The list is every weapon or implement
    the fighter holds, an artifact included: the printed line does not except artifacts, and an artifact that cannot
    Crack simply never breaks (the prompt says so). A form with no held weapon to choose keeps whatever Channel its
    first Crack names (combat/ext/unmaking_channels.chosen_channel)."""
    from .effect_durations import apply_condition_preserving_clock, skipped_expiry_slots
    from .. import stances
    from . import needle, unmaking_channels

    form = next((c for c in stances.active(ctx.actor) if str((c.data or {}).get("source") or "") == ctx.source), None)
    if form is None:
        return
    held = unmaking_channels.held_forms(ctx.engine, ctx.actor)
    if not held:
        ctx.rider("First Ruin Form: you hold no weapon or implement to bind this form's qi, so it has no Channel.")
        return
    options = list(held)
    artifact = [key for key in options if ((held[key].parameters or {}).get("typed") or {}).get("artifact")]
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "FORM_CHANNEL", ctx.source, ctx.actor.entity_id),
                        ctx.actor, needle.CHOICE + "form_channel", options,
                        labels={key: f"Bind this form to {unmaking_channels.channel_name(ctx.engine, key)}" for key in options},
                        name="First Ruin Form: choose your Channel",
                        prompt=f"First Ruin Form: choose the one held weapon or implement this form binds its qi to. Only its Crack "
                               f"can be delayed when the form ends, and only if it breaks as the form ends do you get the free Black "
                               f"Trace attack."
                               + (f" An artifact weapon is a legal choice and keeps its own printed protection, so it never takes Crack, "
                                  f"never breaks, and never gives the free Black Trace attack." if artifact else ""))
    channel = str((picked or [options[0]])[0])
    data = dict(form.data or {})
    engine, source = ctx.engine, ctx.source
    skipped = skipped_expiry_slots(ctx.actor, form)
    engine._remove_condition(ctx.actor, form.condition_id, source)
    apply_condition_preserving_clock(engine, ctx.actor, form, form.condition_id, form.source_definition_id, ctx.actor.entity_id,
                            expires_on=form.expires_on,
                            data={**data, "channel": channel,
                                  "label": f"{data.get('name') or 'Ruin Form'}: bound to {unmaking_channels.channel_name(engine, channel)}"},
                            skipped_slots=skipped)
    ctx.rider(f"First Ruin Form: {unmaking_channels.channel_name(engine, channel)} is this form's Channel.")


def _black_trace_attacks(engine: Any, actor: Any) -> list[tuple[str, dict[str, Any]]]:
    """The holder's own compiled Black Trace attack rows, by action id."""
    return [(key, effect) for key, action in sorted(engine.action_catalog.items())
            if action.owner_id == actor.entity_id and "BLACK_TRACE" in key
            for effect in (_typed(engine, key).get("effects") or [])
            if isinstance(effect, dict) and effect.get("type") == "attack"]


@effect(STEP_STRIKE)
def black_vein_step_strike(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor
    from . import unmaking_channels

    target = ctx.target
    if target is None or not target.active:
        return
    ctx.actor.turn_flags["black_vein_step_struck"] = True
    ctx.actor.turn_flags["black_vein_step_closed"] = 1
    step = _step(ctx.actor)
    if step:
        unused = max(0, 10 - (step[0] - int(ctx.actor.movement_remaining_ft)))
        ctx.actor.movement_remaining_ft = max(0, int(ctx.actor.movement_remaining_ft) - unused)
    unarmed = [action for action in ctx.engine.action_catalog.values() if action.owner_id == ctx.actor.entity_id and "#" not in action.source_definition_id
               and ".natural." in action.source_definition_id and ((action.parameters or {}).get("typed") or {}).get("weapon")]
    pick = max(unarmed, key=lambda action: (int((action.parameters or {}).get("expected_damage") or 0), action.source_definition_id), default=None)
    if pick is not None:
        typed = copy.deepcopy(pick.parameters["typed"])
        attack = next((row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "attack"), None)
    else:
        # No natural weapon: the 2024 Unarmed Strike (1 + Strength modifier), the profile of the character's own Grapple/Shove options.
        option = next((action for action in sorted(ctx.engine.action_catalog.values(), key=lambda row: row.source_definition_id)
                       if action.owner_id == ctx.actor.entity_id and ((action.parameters or {}).get("typed") or {}).get("unarmed_option")
                       and ((action.parameters or {}).get("typed") or {}).get("weapon")), None)
        if option is None:
            ctx.rider("Black-Vein Step: no unarmed strike to make.")
            return
        pick = ctx.action
        weapon = copy.deepcopy(option.parameters["typed"]["weapon"])
        strength = int((weapon.get("damage") or {}).get("modifier") or 0)
        attack = {"type": "attack", "attack_kind": "unarmed", "count": 1, "on_hit": [{"type": "damage", "weapon_damage": True}]}
        typed = {"effects": [attack], "weapon": weapon, "numbers": {**ctx.numbers, "attack_bonus": int(ctx.numbers.get("pb") or 2) + strength},
                 "duration": {"kind": "instant"}, "riders": [], "source": "unarmed_strike"}
    if attack is None:
        return
    unmaking_channels.pay(ctx, [{"strain": 1}], name="Black-Vein Step")
    typed["effects"] = [{**attack, "count": 1}]
    typed_executor.run_effects(typed_executor.Context(ctx.engine, ctx.actor, pick, ctx.intent, typed, [target], target, {}), typed["effects"])


# ------------------------------------------------------------------------------------------------ target filters and costs
@effect("if_summoned")
def if_summoned(ctx: Any, eff: dict[str, Any]) -> None:
    """{"type": "if_summoned", "effects": [...]}: the nested rows run only against a summoned or bound creature (a creature with a
    summon record: "summoned construct, puppet body, clone, projection ... non-true body"). Shared: any ability may use it."""
    from ..typed_executor import run_effects

    if ctx.target is not None and ctx.target.active and ctx.target.summon is not None:
        run_effects(ctx, copy.deepcopy(eff.get("effects") or []))


@effect("sustainer_damage")
def sustainer_damage(ctx: Any, eff: dict[str, Any]) -> None:
    """Unbody the False Vessel: "If the target is sustained by a visible caster, master, owner, or summoner within 120 feet, that
    creature also takes Ruin damage equal to your Proficiency Bonus d10 on a failed save." Put in the failed-save branch."""
    from ..typed_executor import Context, run_effects

    record = ctx.target.summon if ctx.target is not None else None
    owner = ctx.engine.state.actors.get((record or {}).get("owner") or "")
    if owner is None or not owner.active or ctx.engine._distance_actor_to_actor(ctx.actor, owner) > int(eff.get("range_ft") or 120):
        return
    from ..stealth import sees

    if not sees(ctx.engine, ctx.actor, owner):
        return
    pb = int(ctx.numbers.get("pb") or 2)
    run_effects(Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [owner], owner, {}),
                [{"type": "damage", "applies_to": "target", "dice": {"count": pb, "sides": 10}, "damage_types": ["force"],
                  "evidence": "that creature also takes Ruin damage equal to your Proficiency Bonus d10"}])


@effect("summoned_targets_only")
def summoned_targets_only(ctx: Any, eff: dict[str, Any]) -> None:
    """Marker: summoned/bound creatures, plus explicit ``or_kinds`` labels (candidate_allowed below)."""


@hook("candidate_allowed")
def summoned_only_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    markers = [row for row in typed.get("effects") or [] if row.get("type") == "summoned_targets_only"]
    if not markers:
        return None
    from .creature_kinds import matches
    kinds = [kind for row in markers for kind in row.get("or_kinds") or []]
    targets = [engine.state.actors.get(target_id) for target_id in getattr(candidate, "target_ids", None) or ()]
    return bool(targets) and all(target is not None and (target.summon is not None or matches(target, kinds)) for target in targets)


@effect("if_unmaking_weakened")
def if_unmaking_weakened(ctx: Any, eff: dict[str, Any]) -> None:
    """The Moment Nothing Answers: "If the target is Bloodied, cracked, Impaired, restrained, incapacitated, unable to take
    Reactions, or already under healing denial from your Unmaking" -- read before the technique's own damage lands. A creature is
    never "cracked" (Crack is an object's); Impaired is 3 or more Black Vein Strain."""
    from .. import unmaking
    from ..typed_executor import run_effects

    target = ctx.target
    if target is None or not target.active:
        return
    weakened = target.current_hp * 2 <= target.maximum_hp or int(target.resources.get(unmaking.STRAIN, 0)) >= 3 or any(
        c.condition_id in {"condition:typed.restrained", "condition:typed.incapacitated", "condition:typed.reaction_denied"}
        for c in target.conditions.values()) or any(
        m.target_field == "healing_reduction" and unmaking.my_unmaking_source(ctx.engine, ctx.actor, m.source_definition_id)
        for m in target.modifiers.values())
    if weakened:
        run_effects(ctx, copy.deepcopy(eff.get("effects") or []))


@effect("ruin_backlash")
def ruin_backlash(ctx: Any, eff: dict[str, Any]) -> None:
    """{"type": "ruin_backlash", "times": n}: "suffer Ruin Backlash" (twice)."""
    from .. import unmaking

    for _ in range(int(eff.get("times") or 1)):
        if ctx.actor.active:
            unmaking.self_damage(ctx.engine, ctx.actor, unmaking.backlash(ctx.engine, ctx.actor, ctx.source), f"{ctx.source}.ruin_backlash")


@effect("strain_becomes")
def strain_becomes(ctx: Any, eff: dict[str, Any]) -> None:
    """{"type": "strain_becomes", "value": 6}: "your Black Vein Strain becomes 6" -- set, not a Backlash of its own."""
    from .. import unmaking

    have, want = int(ctx.actor.resources.get(unmaking.STRAIN, 0)), int(eff.get("value") or 0)
    if unmaking.STRAIN not in ctx.actor.resources or have == want:
        return
    if want > have:
        ctx.engine._gain_resource(ctx.actor, unmaking.STRAIN, want - have, f"{ctx.source}{unmaking.BLACK_STAR_REMAIN}")
    else:
        ctx.engine._spend_resource(ctx.actor, unmaking.STRAIN, have - want, ctx.source)


@effect("unmaking_max_hp_loss")
def unmaking_max_hp_loss(ctx: Any, eff: dict[str, Any]) -> None:
    """{"type": "unmaking_max_hp_loss", "amount": n, "applies_to": "self", "until": "long_rest"}: "reduce your current
    and maximum HP by n until you finish a Long Rest" (The Moment Nothing Answers). The keyed step itself is
    combat/ext/maximum_hp_riders.max_hp_loss, shared with the printed prices that cost maximum Hit Points."""
    target = ctx.actor if (eff.get("applies_to") in (None, "self") or ctx.target is None) else ctx.target
    from . import maximum_hp_riders

    amount = maximum_hp_riders.max_hp_loss(ctx.engine, target, int(eff.get("amount") or 0), ctx.source,
                                           name=ctx.action.display_name, key=ctx.source)
    if amount:
        ctx.rider(f"{ctx.action.display_name}: {target.display_name} loses {abs(amount)} maximum Hit Points until they finish a Long Rest.")


CRACKED_PROTECTION = "condition:typed.unmaking_cracked_protection"


@effect("unmaking_answer")
def unmaking_answer(ctx: Any, eff: dict[str, Any]) -> None:
    """Unmake the Answer: "Make an Unmaking Check against the triggering effect's save DC."

    The check is the printed Unmaking Check (Proficiency Bonus plus the Unmaking key ability) against the DC the
    triggering technique was already using, exactly as the object checks below resolve it. A success leaves the
    effect cracked -- a marker on its creator until the end of their next turn, because the printed reduction of
    that protection is the GM's -- and a success by 5 or more also deals 5d10 Ruin damage "to the effect or its
    creator, chosen by you if both are legal targets". A failure is the printed 3d10 Ruin self-damage and 1 Black
    Vein Strain. Before this row the reaction paid its 2 CP and applied the failure branch on every trigger.
    """
    from .. import unmaking
    from ..gate2_runtime_models import DiceSpec

    engine, actor = ctx.engine, ctx.actor
    creator = ctx.target
    pending = getattr(engine, "_typed_pending_technique", None) or {}
    if creator is None or not creator.active:
        return
    numbers = ctx.numbers
    dc = int(pending.get("save_dc") or numbers.get("save_dc") or 10)
    roll = engine.roller.d20(modifier=int(numbers.get("pb") or 2) + int(numbers.get("key_mod") or 0),
                             actor_id=actor.entity_id, reason=f"CHECK:{ctx.source}:unmaking",
                             mode=typed_executor_check_mode(ctx))
    engine._record_roll(roll)
    total = int(roll.total)
    success = total >= dc
    engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(creator.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success,
                                  "margin": total - dc, "skill": "Unmaking Check", "check": "Unmaking Check"})
    ctx.rider(f"Unmake the Answer: Unmaking Check {total} against DC {dc} -- {'success' if success else 'failure'}."
              + (f" By {total - dc}." if success and total - dc >= 5 else ""))
    if not success:
        unmaking.self_damage(engine, actor, _dice(engine, actor, 3, 10, 0, f"RUIN_SELF:{ctx.source}"), f"{ctx.source}.fail")
        unmaking.gain_strain_checked(ctx, 1, f"{ctx.source}.fail")
        return
    engine._apply_condition(creator, CRACKED_PROTECTION, ctx.source, actor.entity_id,
                            expires_on="END_OF_HOLDER_NEXT_TURN",
                            data={"label": f"Cracked by {actor.display_name}'s Unmake the Answer: it starts at less than full "
                                            f"protection until the end of its next turn (work out by hand)"})
    ctx.rider(f"Unmake the Answer: {creator.display_name}'s new {pending.get('action_name') or 'effect'} begins cracked.")
    if total - dc < 5:
        return
    damage = _dice(engine, actor, 5, 10, 0, f"RUIN_DAMAGE:{ctx.source}")
    _answer_damage(ctx, creator, damage, pending)


def _answer_damage(ctx: Any, creator: Any, damage: int, pending: dict[str, Any]) -> None:
    """"deal 5d10 Ruin damage to the effect or its creator, chosen by you if both are legal targets."

    One target is put on the roll, and it is the creature making the effect. Two things stop the game from naming an
    object, and both are facts about when this runs rather than choices:

    - An object records the ability that put it on the map, never which single cast of that ability did
      (:func:`combat.ext.objects.created_by`). Two casts of one technique leave two objects with the same record, so the
      record cannot tell this cast's effect from the one the same technique put up last round.
    - This check runs before the triggering technique's own effects create anything
      (combat/typed_executor.py opens the reaction seam before the effects), so the effect being made is not standing
      yet either way.

    Offering a standing object here would name an earlier cast's barrier as the effect being created and then let the
    owner decide on that, so the choice stays with the Game Master and the game says exactly how to move the damage.

    Game Master: if you read the printed choice as the effect, that damage belongs to the effect instead of the
    creature. The refund is the hit points and temporary hit points the creature actually lost, read off the hit itself
    -- not the dice roll, because resistances, damage immunity, temporary hit points and any reaction of the creature's
    own can all make the creature lose less than was rolled. The log names those two numbers so the arithmetic cannot go
    wrong in either direction.

    Restoring the hit points is only the arithmetic of the printed choice. Damage can do more than cost hit points, and
    the log says so when it did: losing Concentration and being knocked out are not undone by handing the hit points
    back.
    """
    engine, actor = ctx.engine, ctx.actor
    effect_name = pending.get("action_name") or "effect"
    before_hp, before_temp = int(creator.current_hp), int(creator.temporary_hp)
    was_concentrating = creator.concentration is not None
    engine._commit_damage(creator, damage, "FORCE", ctx.source, actor.entity_id, None, reaction_depth=0)
    hp_lost = max(0, before_hp - int(creator.current_hp))
    temp_lost = max(0, before_temp - int(creator.temporary_hp))
    ctx.rider(f"Unmake the Answer: {creator.display_name} takes {damage} Ruin damage. This is one of the two printed "
              f"targets -- the creature making the effect. The {effect_name} it is creating is not on the table yet, and "
              f"the game cannot tell one cast of a technique's object from an earlier cast of the same technique, so "
              f"{creator.display_name} is the only target the game can name.")
    ctx.rider(_refund_explanation(creator, effect_name, damage, before_hp, before_temp, hp_lost, temp_lost,
                                   _reduced_to(engine, creator)))
    after = _refund_side_effects(creator, was_concentrating)
    if after:
        ctx.rider(f"Give {creator.display_name} its hit points back anyway -- that is the arithmetic the printed choice "
                  f"asks for -- but ask your Game Master about the rest: {after}")


def _reduced_to(engine: Any, creator: Any) -> int | None:
    """What the Ruin damage was actually worth after the creature's own defences, or None when that cannot be read.

    The committed packet records it (combat/gate2_engine.py ``DAMAGE_COMMITTED``'s ``reduced_to``), and that one number
    is the difference between naming a cause and only guessing at one: a packet worth less than the roll means one of
    the creature's defences, an HP floor or a deferred packet took some of it; a packet worth the whole roll means
    nothing reduced it and the hit points simply ran out at zero. The engine does not record *which* defence, so this
    helper reports the amount and the wording stays neutral about the reason.
    """
    for event in reversed(engine.events):
        if event.event_type == "DAMAGE_COMMITTED" and creator.entity_id in (event.target_ids or ()):
            value = (event.payload or {}).get("reduced_to")
            return int(value) if value is not None else None
    return None


def _refund_explanation(creator: Any, effect_name: str, damage: int, before_hp: int, before_temp: int,
                        hp_lost: int, temp_lost: int, reduced_to: int | None = None) -> str:
    """Plain-language instructions for moving the printed 5d10 off the creature and onto its effect.

    The refund is the hit points actually lost, not the dice roll: ``_commit_damage`` applies resistance, damage immunity
    and temporary hit points before anything touches Hit Points (combat/gate2_engine.py), and a reaction of the creature's
    own can reduce it further. So the sentence states what the creature lost and then the two values to set, which is
    correct whichever defenses were involved and never hands back more than was taken.

    ``reduced_to`` is what the damage was worth by the time it landed (``_reduced_to`` above). It is what keeps the
    explanation from inventing a cause: a creature at 10 Hit Points loses only 10 of a roll of 20 because its hit
    points bottom out at zero, and telling the Game Master that its Resistance or Immunity reduced the hit would be
    false. When the reason is not knowable the words stay neutral instead.
    """
    name = creator.display_name
    if not hp_lost and not temp_lost:
        return (f"{name} lost no hit points and no temporary hit points at all -- "
                f"{_loss_reason(creator, damage, temp_lost, reduced_to)}. If your Game Master reads the printed choice "
                f"as the effect instead, there is nothing to give back: just deal {damage} Ruin damage to the "
                f"{effect_name}. Only one of the two takes the 5d10, never both.")
    lost = f"{hp_lost} hit points" + (f" and {temp_lost} temporary hit points" if temp_lost else "")
    if not temp_lost and hp_lost == damage:
        taken = f"{name} lost {lost} -- the whole roll, nothing reduced it"
    else:
        taken = (f"{name} lost {lost}, not the {damage} that were rolled -- "
                 f"{_loss_reason(creator, damage, temp_lost, reduced_to)}")
    return (f"{taken}. If your Game Master reads the printed choice as the effect, move this damage onto it instead "
            f"of adding it: set {name} back to {before_hp} hit points and {before_temp} temporary hit points, and deal "
            f"{damage} Ruin damage to the {effect_name}. Only one of the two takes the 5d10, never both.")


def _loss_reason(creator: Any, damage: int, temp_lost: int, reduced_to: int | None) -> str:
    """Why a creature lost fewer hit points than were rolled, in words that stay true whatever actually did it.

    Temporary hit points are the one cause this plug-in can name outright. A packet worth less than the roll means one
    of the creature's defences, an HP floor or a deferred packet took some of it, and the engine does not record which,
    so the words offer the possibilities instead of asserting one. A packet worth the whole roll means nothing reduced
    it and the creature's hit points ran out at zero (combat/gate2_engine.py floors current Hit Points at 0), which is
    what an undefended lethal hit looks like.
    """
    if temp_lost:
        return "temporary hit points soak up damage before hit points do"
    if reduced_to is None:
        return "the damage was worth less than the roll by the time it landed"
    if reduced_to < damage:
        return ("the damage was reduced before it landed, by its Resistance, its Immunity, or another effect "
                "protecting it")
    return (f"nothing reduced it, but its hit points ran out at {int(creator.current_hp)}, so the rest of the roll had "
            "nothing left to take")


def _refund_side_effects(creator: Any, was_concentrating: bool) -> str:
    """What the damage did besides cost hit points, for a creature whose hit points are about to be handed back.

    Damage can end Concentration (combat/gate2_engine.py ``_concentration_check``) or knock the creature out
    (``_defeat``); neither is part of the printed "the damage moves to the effect" arithmetic, so the Game Master has to
    settle them separately. Empty string when the damage only cost hit points.
    """
    lost: list[str] = []
    if was_concentrating and creator.concentration is None:
        lost.append("it lost the Concentration it was holding")
    if not creator.active:
        lost.append("it was knocked out")
    if not lost:
        return ""
    return ("putting its hit points back does not undo " + " or ".join(lost)) + "."


def typed_executor_check_mode(ctx: Any) -> str | None:
    from .. import typed_executor

    ability = str(ctx.numbers.get("key_ability") or "INT").upper()[:3]
    return typed_executor.check_mode(ctx.actor, ability, engine=ctx.engine)


def _dice(engine: Any, actor: Any, count: int, sides: int, bonus: int, reason: str) -> int:
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=bonus), actor_id=actor.entity_id, reason=reason)
    engine._record_roll(roll)
    return int(roll.total)


def _splinter_extra(engine: Any, actor: Any, source: str) -> int:
    """"add one extra d10 Ruin damage. At CL 11, add two extra d10 instead" -- the printed CL step."""
    from . import needle

    cl = int((needle.numbers_of(engine, actor) or {}).get("cl") or 1)
    return _dice(engine, actor, 2 if cl >= 11 else 1, 10, 0, f"RUIN_DAMAGE:{source}.splintering_trace")


@hook("object_packets")
def splintering_trace(engine: Any, actor: Any, obj: Any, packets: list[Any], source: str) -> dict[str, Any] | None:
    """Splintering Trace: "When Black Trace hits an object, construct, armor, shield, barrier, or temporary qi
    structure, add one extra d10 Ruin damage." The structure's half: the extra dice join the same damage instance
    as the Black Trace's own packet. A creature target of a construct kind takes the same bonus from
    ``construct_kind_bonus`` below.
    """
    from . import note

    if "BLACK_TRACE" not in str(source or "") or not any(int(amount) > 0 for amount, _kind in packets) \
            or "splintering_trace" not in _kinds(engine, actor):
        return None
    amount = _splinter_extra(engine, actor, str(source))
    note(engine, source, actor, f"Splintering Trace: {label(obj)} takes {amount} more Ruin damage from this hit.")
    return {"object": obj, "packets": [(amount, "FORCE")]}


@hook("damage_dealt")
def construct_kind_bonus(ctx: Any, target: Any, amount: int) -> None:
    """The same printed line against a creature the table labels a construct (combat/ext/creature_kinds.matches): the
    extra d10 (two at CL 11) is committed after Black Trace's own damage. No printed label, no bonus -- nothing is
    inferred from a name, a condition or an immunity."""
    from . import creature_kinds

    if amount <= 0 or "splintering_trace" not in _kinds(ctx.engine, ctx.actor) \
            or "BLACK_TRACE" not in str(ctx.source) or not creature_kinds.matches(target, ("construct",)):
        return
    extra = _splinter_extra(ctx.engine, ctx.actor, f"{ctx.source}.splintering_trace")
    ctx.engine._commit_damage(target, extra, "FORCE", f"{ctx.source}.splintering_trace", ctx.actor.entity_id, None, reaction_depth=0)
    ctx.rider(f"Splintering Trace: {target.display_name} takes {extra} more Ruin damage.")




LOCKOUT = "condition:typed.unmaking_lockout"


@effect("unmaking_lockout")
def unmaking_lockout(ctx: Any, eff: dict[str, Any]) -> None:
    """{"type": "unmaking_lockout", "except": ["<mechanic id>"]}: "you cannot use Unmaking talents other than Black Trace until the
    end of your next turn"."""
    ctx.engine._remove_condition(ctx.actor, LOCKOUT, ctx.source)
    ctx.engine._apply_condition(ctx.actor, LOCKOUT, ctx.source, ctx.actor.entity_id, expires_on=f"END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started) + 1}",
                                data={"except": list(eff.get("except") or []),
                                      "label": "No Unmaking talents but Black Trace until the end of its next turn"})


@hook("candidate_allowed")
def lockout_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    lock = next((c for c in actor.conditions.values() if c.condition_id == LOCKOUT), None)
    if lock is None or action is None:
        return None
    from ..unmaking import UNMAKING

    typed = (action.parameters or {}).get("typed") or {}
    if typed.get("sphere") != UNMAKING or str(typed.get("option_of") or typed.get("source") or "") in (lock.data or {}).get("except", []):
        return None
    return False


# ------------------------------------------------------------------------------------------------ Anti-Structure object checks
def _object_check_row(action: Any) -> dict[str, Any] | None:
    return _marker(((getattr(action, "parameters", None) or {}).get("typed") or {}), "unmaking_object_check")


@hook("object_targets")
def object_check_targets(engine: Any, actor: Any, action: Any) -> list[str]:
    if _object_check_row(action) is None:
        return []
    return [obj.object_id for obj in engine.state.objects.values() if not obj.destroyed and obj.ac is not None and obj.current_hp is not None]


@hook("candidate_allowed")
def object_check_only_objects(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Dissolve the Seam and Sever the Mountain's Memory target an object or structure, never a creature."""
    if _object_check_row(action) is None:
        return None
    return bool((getattr(candidate, "metadata", None) or {}).get("object_target"))


def check_dc(obj: Any) -> int:
    """"Make an Unmaking Check against the object or effect's DC. If no DC is known, use DC 13 for ordinary objects": a map
    object's own "check_dc" if its record carries one, else 13 (reinforced, cultivation-grade and sect-grade DCs are the GM's)."""
    component = getattr(obj, "component", None) or {}
    if isinstance(component.get("check_dc"), int):
        return int(component["check_dc"])
    return 13


@hook("object_action")
def object_check_action(engine: Any, actor: Any, action: Any, obj: Any, candidate: Any, intent: Any) -> bool | None:
    row = _object_check_row(action)
    if row is None:
        return None
    from .. import typed_executor, unmaking
    from ..gate2_runtime_models import DiceSpec
    from . import objects, unmaking_channels

    typed = copy.deepcopy((action.parameters or {}).get("typed") or {})
    ctx = typed_executor.Context(engine, actor, action, intent, typed, [], None)
    numbers = typed.get("numbers") or {}
    dc = check_dc(obj)
    roll = engine.roller.d20(modifier=int(numbers.get("pb") or 2) + int(numbers.get("key_mod") or 0), actor_id=actor.entity_id,
                             reason=f"CHECK:{ctx.source}:unmaking", mode=typed_executor.check_mode(actor, str(numbers.get("key_ability") or "INT").upper()[:3], engine=engine))
    engine._record_roll(roll)
    success = roll.total >= dc
    engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(obj.object_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success, "skill": "Unmaking Check"})
    dice = row.get("dice") or {"count": 8, "sides": 10}
    damage = engine.roller.roll(DiceSpec(count=int(dice["count"]), sides=int(dice["sides"]), modifier=0), actor_id=actor.entity_id,
                                reason=f"DAMAGE:{ctx.source}:object")
    engine._record_roll(damage)
    amount = int(damage.total) if success else int(damage.total) // 2
    overdraw = row.get("overdraw_dice") and any(c.condition_id == unmaking.OVERDRAW for c in actor.conditions.values()) \
        and not actor.turn_flags.get("overdrawn")
    if overdraw:
        actor.turn_flags["overdrawn"] = True
        extra = engine.roller.roll(DiceSpec(count=int(row["overdraw_dice"]["count"]), sides=int(row["overdraw_dice"]["sides"]), modifier=0),
                                   actor_id=actor.entity_id, reason=f"OVERDRAW:{ctx.source}:object")
        engine._record_roll(extra)
        amount += int(extra.total)
    objects.deal(engine, actor, obj, [(amount, "FORCE")], ctx.source)
    if overdraw:
        pb, cl = int(numbers.get("pb") or 2), int(numbers.get("cl") or 1)
        self_roll = engine.roller.roll(DiceSpec(count=unmaking._OVERDRAW_SELF[unmaking.realm_index(cl)], sides=6, modifier=pb), actor_id=actor.entity_id,
                                       reason=f"OVERDRAW_SELF:{ctx.source}")
        engine._record_roll(self_roll)
        unmaking.self_damage(engine, actor, int(self_roll.total), f"{ctx.source}.overdraw")
        unmaking.gain_strain_checked(ctx, 1, f"{ctx.source}.overdraw")
    if success:
        if row.get("success_note"):
            ctx.rider(str(row["success_note"]))
        if row.get("margin_note") and roll.total >= dc + 5:
            ctx.rider(str(row["margin_note"]))
    else:
        if row.get("fail_cost"):
            unmaking_channels.pay(ctx, list(row["fail_cost"]), name=action.display_name)
        if row.get("fail_backlash"):
            unmaking.self_damage(engine, actor, unmaking.backlash(engine, actor, ctx.source), f"{ctx.source}.ruin_backlash")
    return True


@effect("unmaking_object_check")
def unmaking_object_check(ctx: Any, eff: dict[str, Any]) -> None:
    """Runs from object_check_action above (an object candidate); aimed at a creature it does nothing."""
