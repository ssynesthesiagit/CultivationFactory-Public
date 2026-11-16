"""The Unmaking sphere's runtime (owner 2026-09-28: "we need to automate every aspect before another playtest"): Black
Vein Strain and what it costs, Ruin Channel's charged hit, Overdraw, Black Trace's Mark, and "cannot take Reactions
against you" (Sting, Saint-Body Rebuke).

mind wave-2 additions (owned characters other than Tabik Damu who also have Unmaking): Bitter Release (bigger Overdraw
damage against an already-hurting target), Black-Vein Step (free movement after an Overdraw), Wound That Refuses (a
healing lock on a Ruin Channel or Black Trace hit), Last Inch Control (a save to trade a Black Vein Strain for
self-damage) and Black Star Vessel (a bigger, riskier Ruin Backlash).

Ruin damage is Force here (the sphere's default choice when a talent is learned). Self-damage from Unmaking is its own
type ("RUIN"), which nothing resists; the table does not let it bypass temporary hit points.
"""

from __future__ import annotations

from typing import Any

STRAIN = "resource:named.black_vein_strain"
CHANNEL = "condition:typed.ruin_channel"
OVERDRAW = "condition:typed.overdraw_ready"
NO_REACTIONS_AGAINST = "condition:typed.no_reactions_against"
TRACE_MARK = "Black Trace Mark"
UNMAKING = "tianxia.sphere.unmaking"
BLACK_STAR_ARMED = "condition:typed.black_star_vessel_armed"
BLACK_STAR_ACTIVE = "condition:typed.black_star_vessel_active"
_BANDS = ((1, 4), (5, 9), (10, 14), (15, 20))
_OVERDRAW_ADD = (3, 6, 10, 14)   # d6 of added Ruin damage by Realm
_OVERDRAW_SELF = (1, 2, 4, 6)    # d6 of self-damage by Realm, + PB
# "Bloodied, impaired, cracked, restrained, stunned, incapacitated, or unable to take Reactions" (Bitter Release):
# "impaired" and "cracked" are printed adjectives with no tracked condition of their own on this table (Impaired is a
# Black Vein Strain state on the *attacker*, not a target condition; Cracked applies to objects, not creatures), so
# only the conditions the table actually tracks are checked here.
_BITTER_CONDITIONS = ("restrained", "stunned", "incapacitated", "reaction_denied")


def realm_index(cl: int) -> int:
    return next((index for index, (low, high) in enumerate(_BANDS) if low <= cl <= high), len(_BANDS) - 1)


def self_damage(engine: Any, actor: Any, amount: int, source: str) -> None:
    if amount > 0 and actor.active:
        engine._commit_damage(actor, int(amount), "RUIN", source, actor.entity_id, None, reaction_depth=0)


def cultivation_level(engine: Any, actor: Any) -> int:
    for action in engine.action_catalog.values():
        if action.owner_id == actor.entity_id:
            cl = (((action.parameters or {}).get("typed") or {}).get("numbers") or {}).get("cl")
            if cl:
                return int(cl)
    return 1


def gain_strain(engine: Any, actor: Any, amount: int, source: str, cl: int | None = None) -> None:
    if STRAIN in actor.resources and amount > 0:
        engine._gain_resource(actor, STRAIN, amount, source)  # Ruin Backlash follows the event (after_strain_gained)


def kinds(engine: Any, actor: Any) -> set[Any]:
    """The Unmaking talents this actor owns, by their compiled "unmaking" block kind (public: combat/ext/unmaking_*.py)."""
    return _kinds(engine, actor)


def _kinds(engine: Any, actor: Any) -> set[Any]:
    from . import typed_reactions

    return {row.get("kind") for row in typed_reactions._rows(engine, actor.entity_id, "unmaking")}


def gain_strain_checked(ctx: Any, amount: int, source: str) -> None:
    """Last Inch Control: before gaining Strain, a Constitution save against your own Unmaking Save DC (once per turn).
    Success: take Proficiency-Bonus Ruin self-damage instead of the Strain. Failure: gain the Strain normally."""
    engine, actor = ctx.engine, ctx.actor
    if amount <= 0 or STRAIN not in actor.resources:
        return
    if "last_inch_control" in _kinds(engine, actor) and not actor.turn_flags.get("last_inch_control_used") and _last_inch_wanted(ctx, amount, source):
        actor.turn_flags["last_inch_control_used"] = True
        dc = int(ctx.numbers.get("save_dc") or 10)
        roll = engine._roll_save(actor, "CON", dc, "passive:TAL_UNMAKING_LAST_INCH_CONTROL")
        if roll is not None and roll.total >= dc:
            self_damage(engine, actor, int(ctx.numbers.get("pb") or 2), f"{source}.last_inch_control")
            return
    from .ext.choice_prompt import resource_gain_scope

    with resource_gain_scope(ctx, source):
        gain_strain(engine, actor, amount, source, cultivation_level(engine, actor))


def _last_inch_wanted(ctx: Any, amount: int, source: str) -> bool:
    """Last Inch Control is optional ("you may make a Constitution saving throw"): a player is asked; the built-in AI rolls."""
    from .ext.choice_prompt import action_context
    from .ext.needle import CHOICE, ask, checkpoint_id

    pb = int(ctx.numbers.get("pb") or 2)
    labels = {"roll": f"Roll the Constitution save: on a success take {pb} Ruin damage instead of the Strain",
              "strain": f"Gain the {amount} Black Vein Strain"}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "LAST_INCH_CONTROL", source, ctx.actor.entity_id), ctx.actor,
                 CHOICE + "last_inch_control", ["roll", "strain"], labels=labels, name="Last Inch Control",
                 prompt=f"Last Inch Control: {ctx.action.display_name} would give you {amount} Black Vein Strain (once per turn).",
                 prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, ctx.actor))
    return (picked or ["roll"])[0] == "roll"


def backlash(engine: Any, actor: Any, source: str) -> int:
    """Ruin Backlash itself: 2d6 + Cultivation Level Ruin self-damage (the Strain reduction belongs to reaching 6 Strain)."""
    from .gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=2, sides=6, modifier=cultivation_level(engine, actor)), actor_id=actor.entity_id,
                              reason=f"RUIN_BACKLASH:{source}")
    engine._record_roll(roll)
    from . import ext

    ext.run_strict("ruin_backlash", engine, actor, source)
    return int(roll.total)


def after_strain_gained(engine: Any, actor: Any, source: str) -> None:
    """At 6 Black Vein Strain -- from any source -- Ruin Backlash: 2d6 + CL self-damage, and the Strain falls back to 3.

    Black Star Vessel (CL 15+, Fourth Ruin Form): armed ahead of time (a free toggle, combat/ext/mind_unmaking.py), a Backlash
    instead makes the holder a Black Star Vessel until the end of its next turn: the triggering Backlash is suffered but the
    Strain is not reduced after it, the next Unmaking hit before the state ends adds 8d10 Ruin damage once, the holder
    cannot regain HP, its Ruin damage ignores Resistance (combat/ext/unmaking_forms.py) and it has Disadvantage on death
    saving throws (combat/ext/life_state.py). When the state ends it suffers Ruin Backlash again (black_star_ends).
    Setting the Strain to 6 when a player keeps 1 HP there (BLACK_STAR_REMAIN) is not a new Backlash."""
    if actor.resources.get(STRAIN, 0) < 6 or source.endswith(BLACK_STAR_REMAIN):
        return
    armed = next((iid for iid, c in actor.conditions.items() if c.condition_id == BLACK_STAR_ARMED), None)
    if armed is not None and "black_star_vessel" in _kinds(engine, actor) and not any(
            c.condition_id == BLACK_STAR_ACTIVE for c in actor.conditions.values()):
        _drop(engine, actor, armed, source)
        until = f"END_OF_SOURCE_TURN_AT:{int(actor.turns_started) + 1}"
        engine._apply_condition(actor, BLACK_STAR_ACTIVE, source, actor.entity_id, expires_on=until,
                                data={"bonus_pending": True, "label": "Black Star Vessel: its Ruin damage ignores Resistance, +8d10 Ruin "
                                                                       "damage once on an Unmaking hit, no healing, Disadvantage on death "
                                                                       "saving throws; a second Ruin Backlash when it ends"})
        engine._add_modifier(actor, f"{source}.black_star_vessel", "healing_reduction", "ADD", "none", "ALWAYS", expires_on=until)
        self_damage(engine, actor, backlash(engine, actor, source), f"{source}.ruin_backlash")
        return  # "you do not reduce Black Vein Strain after the triggering Ruin Backlash"
    amount = backlash(engine, actor, source)
    engine._spend_resource(actor, STRAIN, actor.resources[STRAIN] - 3, f"{source}.ruin_backlash")
    self_damage(engine, actor, amount, f"{source}.ruin_backlash")


BLACK_STAR_REMAIN = ".black_star_remain"


def black_star_ends(engine: Any, actor: Any, source: str, intent: Any = None) -> None:
    """"When the state ends, suffer Ruin Backlash again. If this second Backlash would reduce you to 0 HP, you may remain at 1 HP
    instead, but your Black Vein Strain becomes 6 and you gain one level of Exhaustion." A player is asked; the AI keeps 1 HP."""
    if not actor.active:
        return
    amount = backlash(engine, actor, source)
    if amount >= actor.current_hp + actor.temporary_hp and actor.current_hp > 0:
        from .ext.needle import CHOICE, ask, checkpoint_id

        labels = {"remain": "Remain at 1 HP: your Black Vein Strain becomes 6 and you gain 1 level of Exhaustion",
                  "fall": f"Take all {amount} Ruin damage"}
        picked = ask(engine, intent, checkpoint_id(engine, "BLACK_STAR_ENDS", actor.entity_id), actor, CHOICE + "black_star_ends",
                     ["remain", "fall"], labels=labels, name="Black Star Vessel",
                     prompt=f"Black Star Vessel ends: its second Ruin Backlash ({amount} damage) would drop {actor.display_name} to 0 HP.")
        if (picked or ["remain"])[0] == "remain":
            self_damage(engine, actor, actor.current_hp + actor.temporary_hp - 1, f"{source}.black_star_second_backlash")
            if actor.resources.get(STRAIN, 0) < 6:
                engine._gain_resource(actor, STRAIN, 6 - actor.resources.get(STRAIN, 0), f"{source}{BLACK_STAR_REMAIN}")
            from .ext import forged_exhaustion

            forged_exhaustion.add(engine, actor, 1, f"{source}.black_star_vessel")
            return
    self_damage(engine, actor, amount, f"{source}.black_star_second_backlash")


def _drop(engine: Any, actor: Any, instance_id: str, source: str) -> None:
    condition = actor.conditions.pop(instance_id, None)
    if condition is not None:
        engine._append_event("CONDITION_REMOVED", source, actor_id=condition.source_actor_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": instance_id})


def impaired_cost(engine: Any, actor: Any, pb: int, source: str) -> None:
    """At 3 or more Black Vein Strain a channel is Impaired: the first Unmaking use each turn costs PB self-damage."""
    if actor.resources.get(STRAIN, 0) >= 3 and not actor.turn_flags.get("unmaking_impaired_paid"):
        actor.turn_flags["unmaking_impaired_paid"] = True
        self_damage(engine, actor, pb, f"{source}.impaired_channel")


def _roll(engine: Any, actor: Any, count: int, sides: int, bonus: int, reason: str) -> int:
    from .gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=bonus), actor_id=actor.entity_id, reason=reason)
    engine._record_roll(roll)
    return roll.total


NEEDLE_WORDS = ("needle", "dart", "hairpin", "spike", "biao")  # Ruin Needle: "needles, darts, hairpins, bone spikes" (Fei Biao: flying dart)


def charged_hit(ctx: Any, target: Any) -> None:
    """Ruin Channel: the next hit adds the Realm's d8s of Ruin damage, then its cost: an External Channel (a weapon) gains 1
    Crack, an Internal Channel (an unarmed strike) gives 1 Black Vein Strain, or the user takes 1d6 + PB Ruin self-damage
    instead (the owner's choice, combat/ext/unmaking_channels.py). Black-Vein Palm, Meridian Ruin Shock and Ruin Needle ride
    the same hit."""
    charge = next((c for c in ctx.actor.conditions.values() if c.condition_id == CHANNEL), None)
    if charge is None or not target.active:
        return
    data = charge.data or {}
    from factory_authoring.typed_mechanics import dice_for_cl

    dice = dice_for_cl(data.get("dice_by_cl"), int(ctx.numbers.get("cl") or 1)) or {"count": 2, "sides": 8}
    ctx.engine._remove_condition(ctx.actor, CHANNEL, ctx.source)
    from . import stances
    from .ext import unmaking_channels

    weapon_id = unmaking_channels.channel_weapon_identity(ctx)
    internal = weapon_id is None
    weapon = ctx.engine.action_catalog.get(weapon_id) if weapon_id else None
    needle = weapon is not None and any(word in str(weapon.display_name).lower() for word in NEEDLE_WORDS)
    kinds = _kinds(ctx.engine, ctx.actor)
    bonus = stances.ruin_channel_bonus(ctx.actor, int(ctx.numbers.get("pb") or 2)) if internal else 0
    # Black-Vein Palm: on an Internal Channel, +1d8 to the Ruin Channel damage; a choice on a hit; then 1 more Strain.
    palm = internal and "black_vein_palm" in kinds
    count, sides = int(dice["count"]), int(dice["sides"])
    amount = _roll(ctx.engine, ctx.actor, count + (1 if palm and sides == 8 else 0), sides, bonus, f"RUIN_CHANNEL:{ctx.source}")
    if palm and sides != 8:
        amount += _roll(ctx.engine, ctx.actor, 1, 8, 0, f"BLACK_VEIN_PALM:{ctx.source}")
    ctx.engine._commit_damage(target, amount, str(data.get("damage_type") or "FORCE"), f"{ctx.source}.ruin_channel", ctx.actor.entity_id, None, reaction_depth=0)
    from . import ext

    ext.run_strict("channel_delivered", ctx, target, weapon_id)
    self_cost = {"self": {"count": 1, "sides": 6, "bonus": "pb"}}
    unmaking_channels.pay(ctx, [{"strain": 1}, self_cost] if internal else [{"crack": 1, "weapon": weapon_id}, self_cost],
                          name="Ruin Channel", target=target)
    if target.active:
        _wound_that_refuses(ctx, target, kinds, ruin_channel=True)
    if palm:
        if target.active:
            _palm_rider(ctx, target)
        gain_strain_checked(ctx, 1, "passive:black_vein_palm")
    if needle and "ruin_needle" in kinds:
        _ruin_needle(ctx, target, weapon_id)
    if ctx.typed.get("sphere") != UNMAKING:
        after_unmaking_damage(ctx, target)  # "You may Overdraw when a Ruin Channel attack hits" (an Unmaking technique does it after)


def spend_cp(ctx: Any, amount: int, why: str) -> bool:
    """Pay ``amount`` CP from Qi, else Stamina (the pools a Factory character's CP comes from); False when it cannot."""
    for pool in ("resource:core.qi", "resource:core.stamina", "resource:core.resonance"):
        if int(ctx.actor.resources.get(pool, 0)) >= amount:
            ctx.engine._spend_resource(ctx.actor, pool, amount, why)
            return True
    return False


def _can_pay_cp(actor: Any, amount: int) -> bool:
    return any(int(actor.resources.get(pool, 0)) >= amount for pool in ("resource:core.qi", "resource:core.stamina", "resource:core.resonance"))


def optional_cp(ctx: Any, target: Any, name: str, amount: int, what: str) -> bool:
    """"You may spend N CP": a player is asked; the built-in AI spends it when it can. True when paid."""
    if not _can_pay_cp(ctx.actor, amount):
        return False
    from .ext.choice_prompt import action_context
    from .ext.needle import CHOICE, ask, checkpoint_id

    labels = {"use": f"Spend {amount} CP: {what}", "skip": f"Don't use {name}"}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "UNMAKING_OPTION", name, ctx.source, target.entity_id), ctx.actor,
                 CHOICE + "unmaking_option", ["use", "skip"], labels=labels, name=name,
                 prompt=f"{name}: {ctx.action.display_name} hit {target.display_name}.",
                 prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target))
    return (picked or ["use"])[0] == "use" and spend_cp(ctx, amount, f"{ctx.source}.{name.lower().replace(' ', '_')}")


RUIN_NEEDLE_OPTIONS = {"reactions": "it cannot take Reactions until the start of your next turn",
                       "cp": "it cannot regain CP until the start of your next turn",
                       "concentration": "Disadvantage on its next Concentration saving throw before the end of its next turn"}


def _ruin_needle(ctx: Any, target: Any, weapon_id: str | None) -> None:
    """Ruin Needle: a Ruin Channel hit through a needle, dart, hairpin or spike -- choose one rider; the needle gains 1 Crack."""
    from .ext import unmaking_channels
    from .ext.choice_prompt import action_context
    from .ext.needle import CHOICE, ask, checkpoint_id
    from .typed_executor import Context, run_effects

    if target.active:
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "RUIN_NEEDLE", ctx.source, target.entity_id), ctx.actor,
                     CHOICE + "ruin_needle", list(RUIN_NEEDLE_OPTIONS), labels={k: f"{target.display_name}: {v}" for k, v in RUIN_NEEDLE_OPTIONS.items()},
                     name="Ruin Needle", prompt=f"Ruin Needle: {ctx.action.display_name} hit {target.display_name}. Choose one.",
                     prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target))
        choice = (picked or ["reactions"])[0]
        row = {"reactions": {"type": "condition", "condition": "reaction_denied", "expires_on": "START_OF_SOURCE_NEXT_TURN"},
               "cp": {"type": "condition", "condition": "no_cp_regain", "expires_on": "START_OF_SOURCE_NEXT_TURN"},
               "concentration": {"type": "disadvantage", "on": "its next Concentration saving throw", "duration": "until_end_of_next_turn"}}[choice]
        run_effects(Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache),
                    [{**row, "applies_to": "target", "evidence": f"Ruin Needle: {RUIN_NEEDLE_OPTIONS[choice]}"}])
        ctx.rider(f"Ruin Needle: {target.display_name} {RUIN_NEEDLE_OPTIONS[choice]}.")
    if weapon_id:
        unmaking_channels.crack_or_pay(ctx, weapon_id, 1)


PALM_CHOICE = "condition:typed.black_vein_palm_choice"
PALM_CON = "condition:typed.black_vein_palm_con"
PALM_OPTIONS = {"reactions": "cannot take Reactions until the start of your next turn",
                "healing": "cannot regain HP until the start of your next turn",
                "con_save": "Disadvantage on the next Constitution saving throw it makes before the end of its next turn"}


def palm_choice(actor: Any) -> str:
    """Black-Vein Palm's "choose one" for the next hit, a free choice kept until changed (no Reactions until chosen)."""
    return next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == PALM_CHOICE), "reactions")


def _palm_rider(ctx: Any, target: Any) -> None:
    from .typed_executor import Context, run_effects

    choice = palm_choice(ctx.actor)
    sub = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    if choice == "healing":
        run_effects(sub, [{"type": "healing_reduction", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                           "evidence": "the target cannot regain HP until the start of your next turn"}])
    elif choice == "con_save":
        ctx.engine._apply_condition(target, PALM_CON, ctx.source, ctx.actor.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN",
                                    data={"label": "Disadvantage on its next Constitution saving throw (Black-Vein Palm)"})
    else:
        run_effects(sub, [{"type": "condition", "condition": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                           "evidence": "the target cannot take Reactions until the start of your next turn"}])
    ctx.rider(f"Black-Vein Palm: {target.display_name} {PALM_OPTIONS.get(choice, choice)}.")


def channel_fizzled(engine: Any, actor: Any, pb: int) -> None:
    """A Ruin Channel that ends unspent costs PB self-damage. Ruin Sheath Method: the owner may instead have a weapon gain 1 Crack
    or gain 1 Black Vein Strain."""
    if "ruin_sheath_method" in _kinds(engine, actor):
        source = next((key for key, action in sorted(engine.action_catalog.items()) if action.owner_id == actor.entity_id and "#" not in key
                       and any(isinstance(e, dict) and e.get("type") == "ruin_channel" for e in ((action.parameters or {}).get("typed") or {}).get("effects") or [])), None)
        if source is not None:
            from .ext import unmaking_channels
            from .ext.unmaking_forms import context_of

            unmaking_channels.pay(context_of(engine, actor, source), [{"self": {"count": 0, "bonus": pb}}, {"crack": 1}, {"strain": 1}],
                                  name="Ruin Sheath Method")
            return
    self_damage(engine, actor, pb, "passive:ruin_channel.unspent")


def my_unmaking_source(engine: Any, actor: Any, source_id: str | None) -> bool:
    """Whether a damage/modifier source is one of this actor's Unmaking talents (a catalog action of the Unmaking sphere, or a
    packet derived from one: "<action id>.overdraw", "... .ruin_channel", "wound_that_refuses:<actor id>")."""
    text = str(source_id or "")
    if text == f"wound_that_refuses:{actor.entity_id}" or text.endswith(".ruin_channel"):
        return text.startswith("wound_that_refuses:") or (engine.action_catalog.get(text[:-len(".ruin_channel")].split("#")[0]) is not None
                                                            and engine.action_catalog[text[:-len(".ruin_channel")].split("#")[0]].owner_id == actor.entity_id)
    while text:
        action = engine.action_catalog.get(text)
        if action is not None:
            typed = (action.parameters or {}).get("typed") or {}
            return action.owner_id == actor.entity_id and typed.get("sphere") == UNMAKING
        if "." not in text:
            return False
        text = text.rsplit(".", 1)[0]
    return False


def _wound_that_refuses(ctx: Any, target: Any, kinds: set[Any], *, ruin_channel: bool = False) -> None:
    """Wound That Refuses: after you damage a creature with Ruin Channel or Black Trace (including Unbound Trace), it
    cannot regain HP until the start of your next turn; if it already had healing denial from one of your Unmaking talents,
    until the end of your next turn instead."""
    if "wound_that_refuses" not in kinds or not (ruin_channel or "BLACK_TRACE" in ctx.source):
        return
    already = any(m.target_field == "healing_reduction" and my_unmaking_source(ctx.engine, ctx.actor, m.source_definition_id)
                  for m in target.modifiers.values())
    until = f"END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started) + 1}" if already else "START_OF_SOURCE_NEXT_TURN"
    ctx.engine._add_modifier(target, f"wound_that_refuses:{ctx.actor.entity_id}", "healing_reduction", "ADD", "none", "ALWAYS", expires_on=until)
    ctx.rider(f"Wound That Refuses: {target.display_name} cannot regain HP until the {'end' if already else 'start'} of your next turn"
              + (" (it already had healing denial from your Unmaking)." if already else "."))


def _action_events(engine: Any, source: str) -> list[Any]:
    """This action's own events so far (back to the intent that started it)."""
    found = []
    for event in reversed(engine.events):
        if event.event_type == "INTENT_ACCEPTED":
            break
        if event.source_definition_id == source:
            found.append(event)
    return list(reversed(found))


def _overdraw_rule(ctx: Any) -> dict[str, Any]:
    return next((row for row in ctx.typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "overdraw_rule"), {})


def _overdraw_targets(ctx: Any, target: Any) -> list[Any]:
    """Who takes the Overdraw damage: the damaged target, or the failed-save targets a technique names (Ruin Wave: one of them,
    the owner's pick; Third Ruin Form: every one)."""
    rule = _overdraw_rule(ctx)
    if not rule:
        return [target] if target.active else []
    failed = []
    for event in _action_events(ctx.engine, ctx.source):
        payload = event.payload or {}
        if event.event_type == "SAVE_ROLLED" and payload.get("success") is False:
            subject = ctx.engine.state.actors.get(event.actor_id or "")  # the creature that rolled the save
            if subject is not None and subject.active and subject.team_id != ctx.actor.team_id and subject not in failed:
                failed.append(subject)
    if rule.get("targets") == "every_failed_save" or len(failed) <= 1:
        return failed
    from .ext.needle import CHOICE, ask, checkpoint_id

    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "OVERDRAW_TARGET", ctx.source), ctx.actor, CHOICE + "overdraw_target",
                 [subject.entity_id for subject in failed], labels={subject.entity_id: subject.display_name for subject in failed},
                 name="Overdraw", prompt=f"Overdraw: {ctx.action.display_name} -- choose the creature that failed its save to take the Overdraw damage.")
    chosen = (picked or [failed[0].entity_id])[0]
    return [subject for subject in failed if subject.entity_id == chosen]


def _execution_wanted(ctx: Any, target: Any) -> bool:
    from .ext.choice_prompt import action_context
    from .ext.needle import CHOICE, ask, checkpoint_id

    labels = {"execution": "Execution Through the Fault: spend 2 CP, add 10d8 Ruin damage instead of the Overdraw bonus, then Ruin Backlash",
              "overdraw": "Overdraw normally"}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "EXECUTION", ctx.source, target.entity_id), ctx.actor, CHOICE + "execution",
                 ["execution", "overdraw"], labels=labels, name="Execution Through the Fault",
                 prompt=f"Execution Through the Fault: {ctx.action.display_name} damaged {target.display_name}, who is Bloodied.",
                 prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target))
    return (picked or ["execution"])[0] == "execution"


def after_unmaking_damage(ctx: Any, target: Any) -> None:
    """After an Unmaking talent damages a creature: Black Trace's Mark (+PB, spent) and Overdraw (once a turn, if chosen)."""
    from .typed_executor import mark_condition_id

    pb, cl = int(ctx.numbers.get("pb") or 2), int(ctx.numbers.get("cl") or 1)
    mark_id = mark_condition_id(TRACE_MARK, ctx.actor.entity_id)
    placed = next((c for c in target.conditions.values() if c.condition_id == mark_id), None)
    if placed is not None and placed.source_definition_id != ctx.source:  # not the Black Trace that just placed it
        ctx.engine._remove_condition(target, mark_id, ctx.source)
        ctx.engine._commit_damage(target, pb, "FORCE", f"{ctx.source}.black_trace_mark", ctx.actor.entity_id, None, reaction_depth=0)
    kinds = _kinds(ctx.engine, ctx.actor)
    if target.active:
        _wound_that_refuses(ctx, target, kinds)
        _black_star_bonus(ctx, target)
    if "crack_the_name" in kinds and target.active and target.summon is not None and not ctx.actor.turn_flags.get("crack_the_name"):
        # Crack the Name of the Tool: against a summoned or bound creature, a Wisdom save or Disadvantage on its attacks; then
        # 1 Black Vein Strain or 2d6 Ruin self-damage (the owner's choice).
        ctx.actor.turn_flags["crack_the_name"] = True
        from .typed_executor import run_effects, Context
        from .ext import unmaking_channels

        run_effects(Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache),
                    [{"type": "save", "ability": "wis", "applies_to": "target",
                      "on_fail": [{"type": "disadvantage", "applies_to": "target", "on": "attack rolls", "duration": "until_end_of_next_turn",
                                   "evidence": "Until the end of its next turn, it has Disadvantage on attack rolls"}],
                      "on_success": [{"type": "disadvantage", "applies_to": "target", "on": "the next attack roll", "duration": "until_start_of_your_next_turn",
                                      "evidence": "Successful Save: It has Disadvantage on the next such roll before the start of your next turn."}]}])
        unmaking_channels.pay(ctx, [{"strain": 1}, {"self": {"count": 2, "sides": 6, "bonus": 0}}], name="Crack the Name of the Tool", target=target)
    ready = any(c.condition_id == OVERDRAW for c in ctx.actor.conditions.values())
    bloodied = target.active and target.current_hp * 2 <= target.maximum_hp
    if ready and "execution" in kinds and bloodied and not ctx.actor.turn_flags.get("overdrawn") and _can_pay_cp(ctx.actor, 2) \
            and _execution_wanted(ctx, target):
        # Execution Through the Fault: against a Bloodied creature, 2 CP and 10d8 instead of the Overdraw bonus; Ruin Backlash.
        ctx.actor.turn_flags["overdrawn"] = True
        spend_cp(ctx, 2, f"{ctx.source}.execution_through_the_fault")
        added = _roll(ctx.engine, ctx.actor, 10, 8, 0, f"EXECUTION:{ctx.source}")
        ctx.engine._commit_damage(target, added, "FORCE", f"{ctx.source}.execution_through_the_fault", ctx.actor.entity_id, None, reaction_depth=0)
        self_damage(ctx.engine, ctx.actor, backlash(ctx.engine, ctx.actor, ctx.source), f"{ctx.source}.ruin_backlash")
        if not target.active and ctx.actor.resources.get(STRAIN, 0) > 0:
            ctx.engine._spend_resource(ctx.actor, STRAIN, min(2, ctx.actor.resources[STRAIN]), f"{ctx.source}.execution_through_the_fault")
        elif target.active:
            # "If it does not reduce the target to 0 HP, you cannot regain HP until the end of your next turn."
            ctx.engine._add_modifier(ctx.actor, f"{ctx.source}.execution_through_the_fault", "healing_reduction", "ADD", "none", "ALWAYS",
                                     expires_on=f"END_OF_SOURCE_TURN_AT:{ctx.actor.turns_started + 1}")
        _devouring_dregs(ctx, target, kinds)
        ctx.rider(f"Execution Through the Fault: +{added} Ruin damage, then Ruin Backlash.")
        return
    overdraw_to = _overdraw_targets(ctx, target) if ready and not ctx.actor.turn_flags.get("overdrawn") else []
    if overdraw_to:
        ctx.actor.turn_flags["overdrawn"] = True
        index = realm_index(cl)
        added = _roll(ctx.engine, ctx.actor, _OVERDRAW_ADD[index], 6, 0, f"OVERDRAW:{ctx.source}")
        for subject in overdraw_to:
            bonus = 0
            if "bitter_release" in kinds:
                # Bitter Release: +PB Ruin damage, or +2 x PB against a target that is Bloodied, Impaired (3 or more Black Vein
                # Strain), Restrained, Stunned, Incapacitated, or unable to take Reactions.
                hurting = subject.current_hp * 2 <= subject.maximum_hp or int(subject.resources.get(STRAIN, 0)) >= 3 or any(
                    c.condition_id in {f"condition:typed.{name}" for name in _BITTER_CONDITIONS} for c in subject.conditions.values())
                bonus = pb * (2 if hurting else 1)
                ctx.rider(f"Bitter Release: +{bonus} Ruin damage to {subject.display_name} ({'2x' if hurting else '1x'} Proficiency Bonus).")
            ctx.engine._commit_damage(subject, added + bonus, "FORCE", f"{ctx.source}.overdraw", ctx.actor.entity_id, None, reaction_depth=0)
        self_damage(ctx.engine, ctx.actor, _roll(ctx.engine, ctx.actor, _OVERDRAW_SELF[index], 6, pb, f"OVERDRAW_SELF:{ctx.source}"),
                    f"{ctx.source}.overdraw")
        gain_strain_checked(ctx, 1, f"{ctx.source}.overdraw")
        if _overdraw_rule(ctx).get("then_backlash"):
            self_damage(ctx.engine, ctx.actor, backlash(ctx.engine, ctx.actor, ctx.source), f"{ctx.source}.ruin_backlash")
        if "black_vein_step" in kinds:
            # Black-Vein Step: 10 feet of free movement after the triggering talent resolves (once per turn, since Overdraw
            # itself is once per turn). combat/ext/unmaking_forms.py reads the turn flag: no Opportunity Attacks from the
            # creatures the talent damaged during those 10 feet, and the extra unarmed strike for 1 more Strain.
            damaged = sorted({target_id for event in _action_events(ctx.engine, ctx.source) if event.event_type == "DAMAGE_COMMITTED"
                              for target_id in event.target_ids if target_id != ctx.actor.entity_id})
            ctx.actor.movement_remaining_ft = int(ctx.actor.movement_remaining_ft) + 10
            ctx.actor.turn_flags["black_vein_step"] = f"{int(ctx.actor.movement_remaining_ft)}|{','.join(damaged)}"
            ctx.rider("Black-Vein Step: 10 feet of free movement that the creatures this talent damaged cannot answer with Opportunity "
                      "Attacks; end it next to one of them to make an unarmed strike for 1 more Black Vein Strain.")
        for subject in overdraw_to:
            _devouring_dregs(ctx, subject, kinds)
        ctx.rider(f"Overdraw: +{added} Ruin damage, at its cost.")


def _black_star_bonus(ctx: Any, target: Any) -> None:
    """Black Star Vessel: once before the state ends, the next Unmaking hit adds 8d10 Ruin damage. Re-applies the
    condition (remove, then apply) with the bonus consumed rather than mutating its data in place, so a replay sees
    the same two events."""
    active = next((c for c in ctx.actor.conditions.values() if c.condition_id == BLACK_STAR_ACTIVE), None)
    if active is None or not (active.data or {}).get("bonus_pending"):
        return
    expires_on, data, source = active.expires_on, dict(active.data or {}), active.source_definition_id
    ctx.engine._remove_condition(ctx.actor, BLACK_STAR_ACTIVE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, BLACK_STAR_ACTIVE, source, ctx.actor.entity_id, expires_on=expires_on,
                                data={**data, "bonus_pending": False})
    added = _roll(ctx.engine, ctx.actor, 8, 10, 0, f"BLACK_STAR_VESSEL:{ctx.source}")
    ctx.engine._commit_damage(target, added, "FORCE", f"{ctx.source}.black_star_vessel", ctx.actor.entity_id, None, reaction_depth=0)
    ctx.rider(f"Black Star Vessel: +{added} Ruin damage (once before the state ends).")


def _devouring_dregs(ctx: Any, target: Any, kinds: set[Any]) -> None:
    """Devouring Dregs: an Overdraw that reduces the target to 0 HP lets you remove 1 Black Vein Strain or 1 Crack from the
    Channel used (the weapon of a weapon attack), the owner's choice."""
    if "devouring_dregs" not in kinds or target.active:
        return
    from .ext import unmaking_channels

    weapon_id = unmaking_channels.channel_weapon_identity(ctx)
    options = (["strain"] if ctx.actor.resources.get(STRAIN, 0) > 0 else []) + (["crack"] if weapon_id and unmaking_channels.cracks(ctx.actor, weapon_id) else [])
    if not options:
        return
    choice = options[0]
    if len(options) > 1:
        from .ext.needle import CHOICE, ask, checkpoint_id

        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "DEVOURING_DREGS", ctx.source), ctx.actor, CHOICE + "devouring_dregs", options,
                     labels={"strain": "Remove 1 Black Vein Strain", "crack": "Remove 1 Crack from the weapon you used"}, name="Devouring Dregs",
                     prompt=f"Devouring Dregs: {ctx.action.display_name} dropped {target.display_name}.")
        choice = (picked or options)[0]
    if choice == "strain":
        ctx.engine._spend_resource(ctx.actor, STRAIN, 1, f"{ctx.source}.devouring_dregs")
        ctx.rider("Devouring Dregs: 1 Black Vein Strain removed.")
    else:
        unmaking_channels.remove_crack(ctx.engine, ctx.actor, weapon_id, 1, f"{ctx.source}.devouring_dregs")
        ctx.rider("Devouring Dregs: 1 Crack removed from the weapon.")


def reactions_denied_against(reactor: Any, other: Any | None) -> bool:
    return other is not None and any(c.condition_id == NO_REACTIONS_AGAINST and (c.data or {}).get("against") == other.entity_id
                                     for c in reactor.conditions.values())
