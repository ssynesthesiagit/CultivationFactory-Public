"""Lightning's Charge, spent (owner 2026-09-28, "automate every aspect before another playtest", wave 3).

Gather Charge places a tracked "Charged" mark (combat/ext/elements_marks.py's sibling module,
authority/typed_mechanics/reviewed_final.d/elements.json's TAL_LIGHTNING_GATHER_CHARGE), but nothing spent
it: every Lightning record that reads or consumes a Charge (Conductive Strike, Static Guard, Crackling
Arrow, Charged Needle, Charged Countermeasure, Arc Primer, One Circuit Under Heaven, Sky-Fire Nerve Net,
Lightning Lash's own Charge/Arc riders) is retyped in reviewed_final.d/charge.json to use typed_executor's
mark / spend_mark / if_marked / if_not_marked blocks instead.

This module carries the two pieces that data alone cannot express:

- The base sphere rule "You can maintain a number of Charges at one time equal to your Proficiency Bonus"
  (Tianxia_Sphere_Compendium's Lightning "Charge" section) -- wired the same way elements_marks.py wires
  Faultline Mark and Waning Mark's printed caps, via combat/rules/feature_blocks.d/charge.json's
  "mark_caps" block on First Circuit Method (an econ=passive base ability every Lightning character has --
  NOT Gather Charge itself: a feature_blocks entry marks its mechanic "automated", which excludes it from
  action-building entirely, so attaching this to a real bonus_action silently dropped Gather Charge from
  the action catalog -- caught by tests/test_auto_elements.py's own regression test failing). Realm Evolutions and
  temporary domains that raise this limit further (Current Beyond the Skin +1, Court of Charged Paths +Proficiency Bonus while
  active, Lightning Sovereign Incarnation doubles it) are layered on by combat/ext/lightning_riders.py through block_mark's
  ``mark_cap`` hook (rider lane 1, 2026-09-29), the two timed ones through the named states of combat/ext/states.py.
- Storm-Heart Engine ("Once per turn when you consume a Charge to empower a Lightning talent, choose one: gain Temporary HP equal to
  your Proficiency Bonus; move 5 feet without provoking Opportunity Attacks; add +1 to your next Lightning Check; impose Disadvantage on
  the next Opportunity Attack against you", two in Lightning-God Body): nothing in the shared engine told a plug-in that a mark was
  actually spent (as opposed to placed, or expiring on its own) until typed_executor.block_spend_mark's "mark_spent" hook call was added.
  Rider lane 1 (2026-09-29) made the choice real (combat/ext/needle.py's ask, so a fight nobody answers takes the first, Temporary HP)
  and reads Lightning-God Body from combat/ext/states.py; "+1 to the next Lightning Check" is left out because no Lightning Check is
  made on this table.
- Conductive Strike's own two Charge pieces ("the target becomes Conductive"; "At CL 5, if the target is
  already Charged, you may consume the Charge to increase the additional lightning damage to 1d8 + your
  Proficiency Bonus") could not be added as a typed "modifier" on the mechanic itself: combat/rules/
  feature_blocks.json already gives it an "on_hit_damage" block (its base +Proficiency Bonus on a weapon
  hit, once per turn -- deliberately weapon-only, "unarmed strikes need a Charge, so they are left to the
  GM"), which marks the mechanic "automated" and so excluded from the typed-modifier pass entirely (a
  modifier on an already-automated feature is silently never applied, combat/factory_compiler.py's
  apply_modifiers). The alternative -- dropping the block and using an "any_attack" scoped modifier instead
  -- fired on Lightning Lash and Chain Bolt too (any Lightning-sphere attack, not just this weapon/unarmed
  strike), a real over-application the base block's own attack_kinds filter had correctly avoided. This
  module's after_hit hook rides the SAME weapon hits the base block already fires on, adding only the two
  missing pieces, sharing the "once per turn" limit (its own turn flag, reset each turn like the block's).
- Gather Charge's targets (rider lane C13, 2026-09-30): "Yourself, ... one weapon you are holding, one willing creature you can see ...
  or one unoccupied 5-foot space you can see" -- its options in reviewed_final.d/elements.json (it was aimed at an enemy). Two need
  code: ``lightning_charge_weapon`` ("If you Charge a weapon you are holding, the next time you hit with that weapon before the Charge
  ends, you may consume the Charge to deal additional lightning damage equal to your Proficiency Bonus": the weapon is asked when you
  hold several; the next hit with it asks whether to consume it) and ``lightning_charge_discharge`` (the Charged space: "The first time a
  creature enters that space before the Charge ends, you may end the Charge to deal lightning damage equal to your Proficiency Bonus to
  that creature": the space's enter trigger asks you; the AI spends it on a hostile creature, never its own side).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note


@hook("compile_block")
def _compile_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "storm_heart_engine":
        return None
    return [dict(row)]


@hook("after_hit")
def _conductive_strike_after_hit(ctx: Any, target: Any, kind: str) -> None:
    if kind != "weapon":
        return  # Conductive Strike's own base bonus (feature_blocks.json's on_hit_damage) is weapon-only too.
    from .. import typed_reactions

    owner = ctx.actor
    if not any(row.get("feature_id") == "TAL_LIGHTNING_CONDUCTIVE_STRIKE"
              for row in typed_reactions._rows(ctx.engine, owner.entity_id, "on_hit_damage")):
        return
    key = "typed_modifier_once:TAL_LIGHTNING_CONDUCTIVE_STRIKE:charge"
    if owner.turn_flags.get(key):
        return  # "You may use Conductive Strike once per turn."
    owner.turn_flags[key] = True
    from .. import typed_executor

    effects: list[dict[str, Any]] = [
        {"type": "mark", "mark": "Conductive", "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"},
         "evidence": "the target becomes Conductive until the start of your next turn"},
    ]
    if int(ctx.numbers.get("cl") or 1) >= 5:
        effects.append({"type": "if_marked", "mark": "Charged", "effects": [
            {"type": "spend_mark", "mark": "Charged", "applies_to": "target", "evidence": "consume the Charge"},
            {"type": "extra_damage", "applies_to": "target", "dice": {"count": 1, "sides": 8}, "damage_types": ["lightning"],
             "duration": "instant", "evidence": "increase the additional lightning damage to 1d8 + your Proficiency Bonus "
             "(the +Proficiency Bonus is the base block's own damage; this is the further +1d8)"},
        ], "evidence": "At CL 5, if the target is already Charged, you may consume the Charge"})
    inner = typed_executor.Context(ctx.engine, owner, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    typed_executor.run_effects(inner, effects)
    from ..attack_notifications import is_melee_hit
    if is_melee_hit(ctx):
        from .lightning_riders import meridian_hit_choice
        from dataclasses import replace
        meridian_hit_choice(replace(ctx, target=target, targets=[target]), {})


@hook("mark_spent")
def _mark_spent(ctx: Any, name: str, subject: Any) -> None:
    if name.strip().lower() != "charged":
        return
    from .. import typed_reactions

    owner = ctx.actor
    if not typed_reactions._rows(ctx.engine, owner.entity_id, "storm_heart_engine"):
        return
    key = "typed_modifier_once:storm_heart_engine"
    if owner.turn_flags.get(key):
        return  # "Once per turn"
    owner.turn_flags[key] = True
    # Rider lane 1 (2026-09-29): the printed choice.  "Choose one" of the benefits (two in Lightning-God Body or True Lightning-God
    # Mantle); a fight nobody is answering takes the first, Temporary HP, as it always did.  "+1 to the next Lightning Check" is not
    # offered: no Lightning Check is made on this table.
    from . import needle, states
    options = {"temp_hp": "Temporary HP equal to your Proficiency Bonus", "move": "Move 5 feet without provoking Opportunity Attacks",
               "oa_disadvantage": "Disadvantage on the next Opportunity Attack made against you"}
    count = 2 if states.active(ctx.engine, owner, "lightning_god_body") else 1
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "storm_heart", subject.entity_id), owner, needle.CHOICE + "storm_heart",
                        list(options), labels=options,
                        prompt=f"Storm-Heart Engine: {ctx.action.display_name} consumes the Charge on {subject.display_name}; "
                               f"choose {count} benefits for {owner.display_name}",
                        minimum=count, maximum=count, target_id=subject.entity_id,
                        name="Storm-Heart Engine", feature_id="TAL_LIGHTNING_STORM_HEART_ENGINE")
    for choice in picked[:count]:
        if choice == "temp_hp":
            amount = int(ctx.numbers.get("pb") or 0)
            if amount > 0:
                ctx.engine._grant_temp_hp(owner, amount, "TAL_LIGHTNING_STORM_HEART_ENGINE", owner.entity_id)
        elif choice == "move":
            storm_heart_step(ctx, subject)
        elif choice == "oa_disadvantage":
            ctx.engine._remove_condition(owner, OA_DISADVANTAGE, "TAL_LIGHTNING_STORM_HEART_ENGINE")
            ctx.engine._apply_condition(owner, OA_DISADVANTAGE, "TAL_LIGHTNING_STORM_HEART_ENGINE", owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                        data={"label": "Storm-Heart Engine: the next Opportunity Attack against it has Disadvantage"})


def storm_heart_step(ctx: Any, subject: Any) -> None:
    """Resolve Storm-Heart's immediate step through the actor-specific movement path.

    The temporary budget and OA exemption cannot be banked; terrain, occupancy,
    movement events and hazards use the ordinary resolver, including off-turn.
    """
    from . import needle
    from .movement_steps import immediate_step_budget

    engine, actor = ctx.engine, ctx.actor
    allowance = immediate_step_budget(engine, actor, 5)
    if allowance <= 0:
        return
    budget = actor.movement_remaining_ft
    free = actor.turn_flags.get("oa_free_ft")
    actor.movement_remaining_ft = allowance
    try:
        options = {needle.cell_id(c.destination): c for c in engine._movement_candidates(actor)}
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "storm_heart_step", subject.entity_id), actor,
                            needle.CHOICE + "storm_heart_step", list(options), minimum=0, allow_decline=True,
                            labels={key: f"Move to ({c.destination.x}, {c.destination.y}), {c.movement_cost_ft} feet"
                                    for key, c in options.items()},
                            prompt=f"Storm-Heart Engine: after {ctx.action.display_name} consumes the Charge on "
                                   f"{subject.display_name}, move {actor.display_name} 5 feet without provoking Opportunity Attacks",
                            target_id=subject.entity_id, name="Storm-Heart Engine", feature_id="TAL_LIGHTNING_STORM_HEART_ENGINE")
        if chosen:
            actor.turn_flags["oa_free_ft"] = 5
            engine._resolve_movement(actor, options[chosen[0]], ctx.intent)
    finally:
        actor.movement_remaining_ft = budget
        if free is None:
            actor.turn_flags.pop("oa_free_ft", None)
        else:
            actor.turn_flags["oa_free_ft"] = free


OA_DISADVANTAGE = "condition:typed.storm_heart_oa_disadvantage"


@hook("attack_mode")
def _storm_heart_oa_disadvantage(ctx: Any, target: Any) -> str | None:
    if getattr(ctx.engine, "_typed_oa_attacker", None) == ctx.actor.entity_id and any(c.condition_id == OA_DISADVANTAGE for c in target.conditions.values()):
        return "DISADVANTAGE"
    return None


@hook("event")
def _storm_heart_oa_used_up(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"the next Opportunity Attack": the first one made against the holder uses the Disadvantage up."""
    if event_type != "ATTACK_ROLLED" or not (
            "opportunity" in str((kwargs.get("payload") or {}).get("reason") or "").lower()
            or getattr(engine, "_typed_oa_attacker", None) == kwargs.get("actor_id")):
        return
    for target_id in kwargs.get("target_ids") or ():
        holder = engine.state.actors.get(target_id)
        if holder is not None and any(c.condition_id == OA_DISADVANTAGE for c in holder.conditions.values()):
            engine._remove_condition(holder, OA_DISADVANTAGE, "TAL_LIGHTNING_STORM_HEART_ENGINE")


# ------------------------------------------------------------------------------------------------ Gather Charge: weapon and space
CHARGED_WEAPON = "condition:typed.charged_weapon"
GATHER = "TAL_LIGHTNING_GATHER_CHARGE"


def charge_count(engine: Any, actor: Any) -> int:
    """All maintained creature, held-weapon and space Charges count toward the same limit."""
    from ..typed_executor import mark_condition_id
    from .. import zones

    cid = mark_condition_id("Charged", actor.entity_id)
    creatures = sum(c.condition_id == cid for a in engine.state.actors.values() for c in a.conditions.values())
    weapons = sum(c.condition_id == CHARGED_WEAPON for c in actor.conditions.values())
    spaces = sum(z.active and z.owner_id == actor.entity_id and GATHER in z.source_definition_id
                 for z in zones.typed_zones(engine))
    return creatures + weapons + spaces


def charge_limit(ctx: Any) -> int:
    from ..typed_executor import mark_capacity

    limit = mark_capacity(ctx, "Charged")
    return int(limit if limit is not None else ctx.numbers.get("pb") or 2)


@hook("mark_apply")
def mixed_charge_cap(ctx: Any, row: dict[str, Any], subject: Any, expires: str, data: dict[str, Any]) -> None:
    """Later Lightning marks cannot silently exceed a limit occupied by weapon/space Charges.

    Preserve the core's oldest-Charge replacement rule, including the other
    two stored forms. Creature-only fights retain the core's existing path.
    """
    from ..typed_executor import mark_condition_id, mark_capacity
    from .. import zones
    from .condition_ownership import remove_instance

    if str(row.get("mark") or "").lower() != "charged":
        return
    cid = mark_condition_id("Charged", ctx.actor.entity_id)
    if any(c.condition_id == cid for c in subject.conditions.values()):
        return  # Refreshing the same Charge adds no new one.
    weapons = [(c.applied_sequence, holder, iid) for holder in [ctx.actor]
               for iid, c in holder.conditions.items() if c.condition_id == CHARGED_WEAPON]
    spaces = [z for z in zones.typed_zones(ctx.engine) if z.active and z.owner_id == ctx.actor.entity_id
              and GATHER in z.source_definition_id]
    if not weapons and not spaces:
        return
    limit = mark_capacity(ctx, "Charged")
    if limit is None:
        limit = int(ctx.numbers.get("pb") or 2)
    creatures = [(c.applied_sequence, holder, iid) for holder in ctx.engine.state.actors.values()
                 for iid, c in holder.conditions.items() if c.condition_id == cid]
    created = {str((e.payload.get("zone") or {}).get("zone_id")): e.sequence
               for e in ctx.engine.events if e.event_type == "ZONE_CREATED"}
    stored = [(seq, "condition", (holder, iid)) for seq, holder, iid in creatures + weapons]
    stored += [(created.get(z.zone_id, 0), "zone", z) for z in spaces]
    for _seq, kind, item in sorted(stored, key=lambda r: r[0])[:max(0, len(stored) - limit + 1)]:
        if kind == "zone":
            zones.remove(ctx.engine, item, "CHARGE_LIMIT")
        else:
            holder, iid = item
            remove_instance(ctx.engine, holder, iid, ctx.source)


@hook("compile_action")
def gather_second_action(action: Any, info: dict[str, Any]) -> Any:
    """The second placement uses existing typed target/area effects, never a second economy payment."""
    import copy

    typed = (action.parameters or {}).get("typed") or {}
    if GATHER not in info["owned_ids"] or typed.get("option_of") != GATHER:
        return None
    typed = copy.deepcopy(typed)
    if not any(e.get("type") == "lightning_gather_second" for e in typed["effects"]):
        typed["effects"].append({"type": "lightning_gather_second"})
    return action.model_copy(update={"parameters": {**action.parameters, "typed": typed}})


@hook("effect_allowed")
def gather_capacity(ctx: Any, row: dict[str, Any]) -> bool | None:
    if ctx.typed.get("option_of") != GATHER or row.get("type") not in ("mark", "zone", "lightning_charge_weapon"):
        return None
    if charge_count(ctx.engine, ctx.actor) >= charge_limit(ctx):
        ctx.rider("Gather Charge: your Charge limit is full; no additional Charge is created.")
        return False
    return None


@effect("lightning_gather_second")
def gather_second(ctx: Any, row: dict[str, Any]) -> None:
    from dataclasses import replace
    import copy
    from ..typed_executor import run_effects, mark_condition_id
    from .needle import ask, checkpoint_id, CHOICE
    from .. import ext

    engine, actor = ctx.engine, ctx.actor
    if int(ctx.numbers.get("cl") or 1) < 10 or charge_count(engine, actor) >= charge_limit(ctx):
        return
    options = {}
    labels = {}
    cid = mark_condition_id("Charged", actor.entity_id)
    for action in engine.action_catalog.values():
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id != actor.entity_id or typed.get("option_of") != GATHER or typed.get("modifier"):
            continue
        label = typed.get("option_label")
        free = action.model_copy(update={"economy": "NONE"})
        for candidate in engine._action_candidates(actor, free):
            if ext.any_false("candidate_allowed", engine, actor, candidate, free):
                continue
            targets = [engine.state.actors[t] for t in candidate.target_ids]
            if label in ("Charge Yourself", "Charge Your Weapon"):
                targets = [actor]
            if label == "Charge a Willing Creature" and any(t.entity_id == actor.entity_id for t in targets):
                continue  # Self-placement uses Charge Yourself, including its printed saving-throw benefit.
            if any(any(c.condition_id == cid for c in target.conditions.values()) for target in targets) and label != "Charge Your Weapon":
                continue
            if label == "Charge a 5-foot Space" and candidate.destination is not None:
                from .. import zones
                if any(z.active and z.owner_id == actor.entity_id and GATHER in z.source_definition_id
                       and candidate.destination in z.affected_cells for z in zones.typed_zones(engine)):
                    continue
            key = candidate.candidate_id
            if label == "Charge Your Weapon":
                charged = {(c.data or {}).get("weapon") for c in actor.conditions.values() if c.condition_id == CHARGED_WEAPON}
                for weapon, profile in gather_weapons(engine, actor).items():
                    if weapon in charged:
                        continue
                    weapon_key = key + ":" + weapon
                    options[weapon_key] = (action, candidate, targets, weapon)
                    labels[weapon_key] = f"Charge Your Weapon: {profile.display_name.removesuffix(' attack')} held by {actor.display_name}; " \
                                         "its next hit may consume the Charge for lightning damage equal to your Proficiency Bonus"
                continue
            options[key] = (action, candidate, targets, None)
            aim = ", ".join(t.display_name for t in targets)
            if candidate.destination is not None:
                aim = f"space ({candidate.destination.x}, {candidate.destination.y})"
            benefit = {"Charge Yourself": "Advantage on your next Dexterity save against lightning, thunder, paralysis, forced movement or being knocked Prone",
                       "Charge a Willing Creature": "store lightning power for your Lightning talents",
                       "Charge a 5-foot Space": "you may consume it when a creature first enters, dealing lightning damage equal to your Proficiency Bonus"}
            labels[key] = f"{label}: {aim or actor.display_name}; {benefit.get(label, '')}"
    if not options:
        return
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, "gather_second", actor.entity_id), actor,
                 CHOICE + "gather_second", list(options), labels=labels, minimum=0, allow_decline=True,
                 preferred=[next(iter(options))], name="Gather Charge",
                 prompt=f"Gather Charge: after {ctx.action.display_name}, {actor.display_name} may place a second Charge "
                        "within range with the same Bonus Action, at no resource cost. Both Charges end at the start of your next turn.")
    if not chosen:
        return
    action, candidate, targets, weapon = options[chosen[0]]
    if ext.any_false("candidate_allowed", engine, actor, candidate, action):
        return
    typed = copy.deepcopy(action.parameters["typed"])
    effects = [e for e in typed["effects"] if e.get("type") != "lightning_gather_second"]
    if weapon is not None:
        effects = [{**e, "weapon": weapon} if e.get("type") == "lightning_charge_weapon" else e for e in effects]
    extra = replace(ctx, action=action, typed=typed, targets=targets,
                    target=targets[0] if len(targets) == 1 else None, destination=candidate.destination, damage_cache={},
                    intent=ctx.intent.model_copy(update={"destination": candidate.destination}) if ctx.intent is not None else None)
    run_effects(extra, effects)


def gather_weapons(engine: Any, actor: Any) -> dict[str, Any]:
    """Held usable weapons for both Gather Charge placements; a gated improvised attack is not a held object."""
    from .weapon_hits import available_weapons
    from .hand_occupancy import weapon_allowed

    return {key: action for key, action in available_weapons(engine, actor).items()
            if (not action.parameters.get("requires_condition")
                or engine._has_condition(actor, action.parameters["requires_condition"]))
            and weapon_allowed(engine, actor, action) is not False}


@effect("lightning_charge_weapon")
def charge_weapon(ctx: Any, eff: dict[str, Any]) -> None:
    from .needle import CHOICE, ask, checkpoint_id

    engine, me = ctx.engine, ctx.actor
    weapons = gather_weapons(engine, me)
    if not weapons:
        ctx.rider("Gather Charge: you hold no weapon to Charge.")
        return
    ids = sorted(weapons, key=lambda key: (-int(weapons[key].parameters.get("expected_damage") or 0), key))
    if eff.get("weapon") in weapons:
        picked = [eff["weapon"]]
    elif len(ids) > 1:
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "GATHER_CHARGE_WEAPON", me.entity_id), me, CHOICE + "gather_charge_weapon", ids,
                     labels={key: weapons[key].display_name.removesuffix(" attack") for key in ids}, preferred=[ids[0]], name="Gather Charge",
                     prompt="Gather Charge: which held weapon takes the Charge?")
    else:
        picked = ids
    weapon = (picked or ids)[0]
    for iid, row in list(me.conditions.items()):
        if row.condition_id == CHARGED_WEAPON and (row.data or {}).get("weapon") == weapon:
            from .condition_ownership import remove_instance

            remove_instance(engine, me, iid, ctx.source)
    engine._apply_condition(me, CHARGED_WEAPON, ctx.source, me.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"weapon": weapon, "label": f"Charged {weapons[weapon].display_name.removesuffix(' attack')}: its next hit "
                                                             f"may spend the Charge for lightning damage equal to your Proficiency Bonus"})


@hook("after_hit")
def charged_weapon_hit(ctx: Any, target: Any, kind: str) -> None:
    me = ctx.actor
    from .weapon_hits import weapon_identity

    identity = weapon_identity(ctx)
    held = next(((iid, row) for iid, row in me.conditions.items()
                 if row.condition_id == CHARGED_WEAPON and (row.data or {}).get("weapon") == identity), None)
    if held is None or kind not in ("weapon", "unarmed"):
        return
    from .weapon_hits import weapon_identity

    if weapon_identity(ctx) != (held[1].data or {}).get("weapon"):
        return
    from .condition_ownership import remove_instance
    from .rider_choices import pick

    remove_instance(ctx.engine, me, held[0], held[1].source_definition_id)  # "the next time you hit with that weapon"
    pb = int(ctx.numbers.get("pb") or 2)
    if target is not None and target.active and pick(ctx.engine, me, "charged_weapon", "Gather Charge", ["spend"], subject=target, preferred=["spend"],
                                                    labels={"spend": f"Spend the weapon's Charge: +{pb} lightning damage"},
                                                    trigger=f"your Charged weapon hits {target.display_name}"):
        from ..typed_executor import run_effects

        run_effects(ctx, [{"type": "damage", "applies_to": "target", "flat": pb, "formula": "none", "damage_types": ["lightning"],
                           "evidence": "consume the Charge to deal additional lightning damage equal to your Proficiency Bonus"}])


@effect("lightning_charge_discharge")
def charged_space(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import zones
    from .rider_choices import pick

    engine, owner, creature = ctx.engine, ctx.actor, ctx.target
    if creature is None or not creature.active or creature is owner:
        return
    spots = {tuple(cell) if not hasattr(cell, "x") else (cell.x, cell.y)
             for cell in engine.grid.footprint_cells(creature.position, engine._footprint(creature.entity_id))}
    zone = next((z for z in zones.typed_zones(engine) if z.active and z.owner_id == owner.entity_id and "TAL_LIGHTNING_GATHER_CHARGE" in
                 z.source_definition_id and any((c.x, c.y) in spots for c in z.affected_cells)), None)
    if zone is None:
        return
    pb = int(ctx.numbers.get("pb") or 2)
    if not pick(engine, owner, "charged_space", "Gather Charge", ["discharge"], subject=creature, preferred=["discharge"],
                automatic=creature.team_id != owner.team_id,
                labels={"discharge": f"End the Charge: {pb} lightning damage to {creature.display_name}"},
                trigger=f"{creature.display_name} enters your Charged space"):
        return
    from ..typed_executor import run_effects

    run_effects(ctx, [{"type": "damage", "applies_to": "target", "flat": pb, "formula": "none", "damage_types": ["lightning"],
                       "evidence": "end the Charge to deal lightning damage equal to your Proficiency Bonus to that creature"}])
    zones.remove(engine, zone, "CHARGE_DISCHARGED")
    note(engine, ctx.source, owner, f"The Charged space discharges into {creature.display_name}.", (creature,))


@hook("candidate_allowed")
def gather_charge_on_yourself(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Self/weapon placements aim at you; space placements require an unoccupied square."""
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    if typed.get("option_of") != GATHER:
        return None
    if typed.get("option_label") == "Charge a 5-foot Space":
        if candidate.destination is None or not engine.grid.placement_legal(candidate.destination):
            return False
        point = (candidate.destination.x, candidate.destination.y, candidate.destination.z)
        return not any(point in engine._actor_volume(holder) for holder in engine.state.actors.values() if holder.active)
    if typed.get("option_label") not in ("Charge Yourself", "Charge Your Weapon"):
        return None
    targets = tuple(getattr(candidate, "target_ids", None) or ())
    return not targets or targets == (actor.entity_id,)
