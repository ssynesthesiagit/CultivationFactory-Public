"""Equipment sphere armour talents whose printed lines were left to the GM (rider lane 9, 2026-09-29; owner: "i want everything we can
automated").  Sphere Compendium, Equipment (owner's text: authority/typed_mechanics/rules_text.json).  The armour a fighter wears is its
Fitted Armor (combat/rules/feature_status.json EQUIPMENT_BASE_FITTED_ARMOR_DESIGNATION).  Rows: feature block "lane9_equipment"
(combat/rules/feature_blocks.d/riders_lane9.json), each carrying the worn armour's category from the compile.

  Mountain-Pattern Grand Shell  "Once per round while wearing medium or heavy Fitted Armor, when you take bludgeoning, piercing, or
                                slashing damage, reduce that damage by your Proficiency Bonus ... If another passive Equipment feature
                                would also reduce the same damage, choose one ... does not apply while you are Incapacitated."
  Circuit Armor                 a Bonus Action, 2 CP: for 1 minute "once per round when you take damage, reduce the damage by your
                                Equipment key ability modifier, minimum 1"; "The circuit ends early if you ... become Incapacitated".
  Beast-Hide Harness Scripture  Padded Layers "may trigger when you take slashing damage instead of bludgeoning damage" while wearing
                                leather, hide, scale, lamellar, padded or robe-style armor; "You still use Padded Layers only once per round".
  Qi-Conductive Lacing          "Once per turn, when you spend CP on an Equipment talent while wearing your Fitted Armor, you gain Temporary
                                Hit Points equal to your Proficiency Bonus."
  Black Armor Legion Scripture  "When you roll initiative while wearing your Fitted Armor and you are not surprised" (surprise is not on the
                                table): Temporary Hit Points equal to PB + key modifier, minimum 1, when the fight begins.
  Walking Fortress Scripture    "The stance ends early if you ... become Incapacitated, or choose to end it": its modifiers go when an
                                incapacitating condition lands, and "End Walking Fortress" (no action) ends it.
  Mountain-Pattern Shell        "You lose this bonus while Incapacitated": -1 AC while an incapacitating condition holds.
  Mirror-Bright Armor           "choose one creature within 30 feet that can see you ... A creature that cannot see your armor is unaffected":
                                only a creature that sees the fighter is offered.
  Padded Layers                 "If the damage comes from falling or collision with an object or surface, reduce the damage by twice your
                                Proficiency Bonus instead": the same once-per-round reduction at twice the bonus. The fall's rolled damage
                                claims that use for the fighter (an AI fighter claims it for itself, a player is asked), the ordinary
                                Bludgeoning row is marked spent so it cannot also answer the same packet, this plug-in's falling_damage
                                hook takes the doubled amount after the ordinary defenses, and no other Equipment reduction answers that
                                fall, as the printed "choose one" requires. A fall that deals no damage is never claimed and
                                spends nothing, and a refusal -- the offered "decline" answer or no answer at all -- claims
                                nothing either, so the ordinary Bludgeoning reduction still answers that packet.
  Reinforced Robes              "While you are wearing no armor and not using a shield, your AC equals 10 + your Dexterity modifier + your
                                Equipment key ability modifier": an alternate Armor Class calculation, not a bonus, in
                                combat/rules/feature_blocks.d/auto68_equipment.json; combat/armour.alternate_ac_calculations resolves it and
                                combat/armour.armor_class uses one calculation instead of adding one to another (owner amendment R1).
Removing or destroying armour mid-fight is not on this table (the worn armour is fixed when the fighter is compiled).
Shared public helper: can_see(engine, viewer, seen), used here by Mirror-Bright
Armor and by reaction_eligibility for Air guards. It checks line of sight,
obscurement, Blinded/Invisible conditions and senses without changing state.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .needle import CHOICE, ask, checkpoint_id

BLOCK = "lane9_equipment"
T = "tianxia.talent.equipment."
CIRCUIT = "condition:typed.circuit_armor"
PHYSICAL = ("BLUDGEONING", "PIERCING", "SLASHING")
FALL_USE, FALL_DECLINE = "use", "decline"   # the two answers the fall's printed "may" offers


@hook("compile_action")
def armor_ease_choice_rider(action: Any, info: dict[str, Any]) -> Any:
    """Keep Armor Ease's unsupported build choice visible without granting it.

    Shared compile_action seam with Ridiculous Weapon: category/proficiency
    need an owner-sheet contract before this can change a check's mechanics.
    """
    if T + "armor_ease" not in info["owned_ids"] or not action.source_definition_id.endswith(".hide"):
        return None
    import copy

    params = copy.deepcopy(action.parameters)
    params["typed"]["riders"].append("GM: Armor Ease — choose light, medium or heavy armor; proficiency in that category is required. Only armor of the chosen category ignores its Stealth Disadvantage; repeated choices must differ. No category or proficiency is inferred automatically.")
    return action.model_copy(update={"parameters": params})
MATERIALS = ("leather", "hide", "scale", "lamellar", "padded", "robe")  # Beast-Hide Harness Scripture's armour
PADDED = T + "padded_layers"
PADDED_ROUND_FLAG = f"defense_round_used:{PADDED}"
FALLING_CLAIM = f"equipment_falling_claim:{PADDED}"   # turn flag: what this fall already claimed, cleared on every exit


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "armor": numbers.get("armor"), "pb": int(numbers.get("pb") or 2),
             "key_mod": int(numbers.get("key_mod") or 0), "keeps_compiling": bool(spec.get("keeps_compiling"))}]


def rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


@hook("stand_cost")
def breath_aligned_standing(engine: Any, actor: Any, normal_cost: int) -> int | None:
    """Breath-Aligned Armor uses the compiler's represented Fitted Armor only."""
    if any(row.get("armor") for row in rows(engine, actor, "breath_aligned")):
        return 5
    return None


@hook("damage_response_reduction")
def iron_rain_area(engine: Any, target: Any, amount: int, damage_type: str,
                   source_id: str, source_actor_id: str | None) -> int | None:
    """The failed-area save alternative; the existing ranged-hit route stays separate.

    New compiled ownership rows opt in. Query the actual selecting save rather
    than a recent save event or enclosing area action. Nothing is parked on the
    creature, so refusal and later unsaved packets cannot inherit a reduction.
    """
    if amount <= 0 or not rows(engine, target, "iron_rain_area"):
        return None
    from ..save_context import damage_save, damage_response_state
    from ..typed_reactions import can_use_reaction, open_reaction
    from ..activation_payments import reaction_completed
    from ..gate2_runtime_models import DiceSpec
    from .choice_costs import Payment

    saved = damage_save(engine, target.entity_id, source_id, source_actor_id)
    if saved is None or saved.ability != "DEX" or not saved.failed or not saved.area:
        return None
    feature_id = T + "iron_rain_readiness"
    response = damage_response_state(engine, saved, feature_id)
    if "remaining" in response:
        absorbed = min(amount, response["remaining"])
        response["remaining"] -= absorbed
        return absorbed
    if response.get("declined"):
        return None
    row = next((r for r in (getattr(engine, "typed_reaction_rows", {}) or {}).get(target.entity_id, [])
                if r.get("feature_id") == feature_id), None)
    attacker = engine.state.actors.get(source_actor_id)
    if row is None or not can_use_reaction(engine, target, attacker, row):
        return None
    # The generic compiler owns CP pool selection (including powering choices).
    costs = row.get("costs") or []
    if not costs or any(target.resources.get(c["resource_id"], 0) < int(c["amount"]) for c in costs):
        return None
    checkpoint = checkpoint_id(engine, "iron_rain_area", target.entity_id, source_id)
    chosen = ask(engine, None, checkpoint, target, CHOICE + "iron_rain_area", ["use"],
                 labels={"use": "Use Iron Rain Readiness"}, allow_decline=True,
                 name="Iron Rain Readiness", feature_id=feature_id, target_id=target.entity_id,
                 payment=Payment(costs[0]["resource_id"], int(costs[0]["amount"])),
                 prompt=f"Iron Rain Readiness: {target.display_name} failed the Dexterity save against "
                        f"{saved.action_name}'s area effect. Spend your Reaction and 2 CP (ability energy) to reduce its "
                        f"damage to you by 2d8 + your Proficiency Bonus? This protects you from this damage only.")
    if not chosen:
        response["declined"] = True
        return None
    for cost in costs:
        engine._spend_resource(target, cost["resource_id"], int(cost["amount"]), feature_id)
    if not reaction_completed(engine, target, feature_id):
        return None
    open_reaction(engine, row, target, (target.entity_id,), checkpoint)
    roll = engine.roller.roll(DiceSpec(count=2, sides=8, modifier=int(row["numbers"]["pb"])),
                              actor_id=target.entity_id, reason=f"DAMAGE_REDUCTION:{feature_id}")
    engine._record_roll(roll)
    reduced = max(0, amount - max(0, int(roll.total)))
    response["remaining"] = max(0, int(roll.total) - amount)
    engine._append_event("REACTION_RESOLVED", feature_id, actor_id=target.entity_id,
                         target_ids=(target.entity_id,), payload={"checkpoint": checkpoint,
                         "reduction": amount - reduced, "pending_before": amount, "pending_after": reduced,
                         "log": f"Iron Rain Readiness: {target.display_name} reduces "
                                f"{saved.action_name}'s damage by {amount - reduced}."})
    return amount - reduced


def incapacitated(actor: Any) -> bool:
    from ..typed_executor import condition_rules

    return any(row.get("no_actions") for row in condition_rules(actor))


def _round_used(engine: Any, actor: Any, key: str) -> bool:
    return actor.turn_flags.get(key) == engine.state.round_number


def _padded_row(engine: Any, actor: Any) -> dict[str, Any] | None:
    """The compiled Padded Layers reduction row (combat/rules/feature_blocks.json "defense"), present only while armored."""
    return next((row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
                 if row.get("feature_id") == PADDED and row.get("kind") == "reduction"), None)


def _padded_available(engine: Any, actor: Any) -> bool:
    return _padded_row(engine, actor) is not None and not _round_used(engine, actor, PADDED_ROUND_FLAG)


def _worn_armor_name(engine: Any, actor: Any) -> str:
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if bundle.get("actor_id") == actor.entity_id:
            return next((str(item.get("name") or "") for item in (bundle.get("carrying") or {}).get("items") or [] if item.get("worn")), "")
    return ""


def _choices(engine: Any, target: Any, kind: str) -> dict[str, int]:
    """The Equipment reductions this damage could take: {key: amount}."""
    out: dict[str, int] = {}
    if incapacitated(target):
        return out
    for row in rows(engine, target, "grand_shell"):
        if row.get("armor") in ("medium", "heavy") and kind in PHYSICAL and not _round_used(engine, target, "equipment_round_grand_shell"):
            out["grand_shell"] = int(row["pb"])
    for row in rows(engine, target, "circuit"):
        if any(c.condition_id == CIRCUIT for c in target.conditions.values()) and not _round_used(engine, target, "equipment_round_circuit"):
            out["circuit"] = max(1, int(row["key_mod"]))
    for row in rows(engine, target, "beast_hide"):
        name = _worn_armor_name(engine, target).lower()
        if kind == "SLASHING" and row.get("armor") and any(word in name for word in MATERIALS) and _padded_available(engine, target):
            out["beast_hide"] = int(row["pb"])
    return out


def _pick(engine: Any, target: Any, kind: str) -> tuple[str, int] | None:
    found = _choices(engine, target, kind)
    if "grand_shell" in found and (("circuit" in found) or (kind == "BLUDGEONING" and _padded_available(engine, target)) or "beast_hide" in found):
        # "If another passive Equipment feature would also reduce the same damage, choose one": the larger; Padded Layers (the same
        # Proficiency Bonus) is the defence row the table already applies, so the Grand Shell steps aside for it.
        others = {key: value for key, value in found.items() if key != "grand_shell"}
        if kind == "BLUDGEONING" and _padded_available(engine, target):
            found = others
        elif others and max(others.values()) >= found["grand_shell"]:
            found = others
        else:
            found = {"grand_shell": found["grand_shell"]}
    if not found:
        return None
    key = max(found, key=lambda name: (found[name], name))
    return key, found[key]


# ------------------------------------------------------------------------------------------------ Padded Layers, falling damage
def _falling_claimed(engine: Any, target: Any) -> int:
    """The reduction this creature's falling packet has already claimed: twice its Proficiency Bonus, or 0."""
    return int(target.turn_flags.get(FALLING_CLAIM) or 0)


def _clear_falling_claim(target: Any) -> None:
    """Drop the claim outright, so a spent fall leaves nothing behind for the next one."""
    target.turn_flags.pop(FALLING_CLAIM, None)


@hook("event")
def padded_claims_a_fall(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Padded Layers: "If the damage comes from falling or collision with an object or surface, reduce the damage by
    twice your Proficiency Bonus instead."

    A fall is Bludgeoning damage, so the ordinary once-per-round reduction (one Proficiency Bonus) matches the same
    packet; the printed clause wants that one use to be worth twice the Proficiency Bonus instead.  The claim is made
    when the fall's damage is rolled, which is the first moment the packet is known to be real: a fall too short to
    roll, a creature protected from falling damage, and a fall with nowhere to land all roll nothing, are never asked
    about and spend nothing.  The ordinary row is marked spent at that point so it cannot also answer the same packet,
    and the doubled amount is claimed for padded_falling_damage below to take after the ordinary defenses.  The
    fighter is asked because the printed clause is a "may" its owner decides; an AI fighter uses it (it only ever
    removes damage).  A refusal -- the offered "decline" answer or no answer at all -- reserves nothing, so the ordinary
    Bludgeoning reduction still answers that packet.  Nothing here survives a failed fall: the claim is cleared by
    falling_damage and again by the commit of whatever packet follows it, and a transaction that unwinds rolls the flag
    back with the rest of the state.
    """
    from .. import falling

    if event_type not in ("DAMAGE_ROLLED", "DAMAGE_COMMITTED"):
        return
    if str(kwargs.get("source_definition_id")) != falling.SOURCE:
        return   # only the falling source's own packets
    target = engine.state.actors.get(kwargs.get("actor_id") or "")
    if target is None:
        return
    if event_type == "DAMAGE_COMMITTED":
        _clear_falling_claim(target)    # belt and braces: the packet is resolved either way
        return
    rolled = int((kwargs.get("payload") or {}).get("total") or 0)
    if rolled <= 0 or not _padded_available(engine, target):
        _clear_falling_claim(target)
        return
    pb = int((_padded_row(engine, target) or {}).get("amount") or 0)
    chosen = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "padded_layers_fall", target.entity_id, rolled), target,
                 CHOICE + "padded_layers_fall", [FALL_USE, FALL_DECLINE],
                 labels={FALL_USE: f"Use it: take {2 * pb} off this fall",
                         FALL_DECLINE: f"Take the fall's damage ({pb} off, as for any Bludgeoning damage)"},
                 prompt=(f"Padded Layers: {target.display_name} is falling and takes {rolled} Bludgeoning damage. Use this "
                         f"reduction to take {2 * pb} off the fall -- twice your Proficiency Bonus, instead of the {pb} taken "
                         f"off Bludgeoning damage? You may use Padded Layers once per round."),
                 preferred=[FALL_USE], allow_decline=True, automatic=True, target_id=target.entity_id,
                 name="Padded Layers", feature_id=PADDED)
    # Only the option that claims the fall does. "decline" is an option in its own right, so a refusal reaches here as
    # ["decline"] exactly as an unanswered prompt reaches it as [] -- both leave the ordinary once-per-round reduction.
    if FALL_USE not in chosen:
        _clear_falling_claim(target)   # a declined claim spends nothing: the ordinary reduction still answers
        return
    target.turn_flags[FALLING_CLAIM] = 2 * pb
    target.turn_flags[PADDED_ROUND_FLAG] = engine.state.round_number   # the ordinary row must not answer it as well


@hook("damage_reduction")
def reduce(engine: Any, target: Any, damage_type: str, typed: dict[str, Any], source_actor_id: Any, applied: bool = False) -> int | None:
    kind = str(damage_type).upper()
    if kind == "BLUDGEONING" and _falling_claimed(engine, target):
        return None   # this fall is already answered by Padded Layers: "choose one", so no other reduction answers it
    picked = _pick(engine, target, kind)
    if picked is None:
        return None
    key, amount = picked
    if applied:
        flag = PADDED_ROUND_FLAG if key == "beast_hide" else f"equipment_round_{key}"
        target.turn_flags[flag] = engine.state.round_number
        from . import note

        label = {"grand_shell": "Mountain-Pattern Grand Shell", "circuit": "Circuit Armor", "beast_hide": "Beast-Hide Harness Scripture (Padded Layers)"}[key]
        note(engine, f"passive:{label}", target, f"{label}: {target.display_name} takes {amount} less {kind.lower()} damage.")
    return amount


@hook("falling_damage")
def padded_falling_damage(engine: Any, target: Any, defended: int, fall: Any, intent: Any) -> dict[str, Any] | None:
    """The reduction Padded Layers claimed for this fall (padded_claims_a_fall), taken after the ordinary defenses.

    The claim is cleared on every way out of a packet -- a fall that resolved to no damage, or another reduction having
    answered the same damage first -- so nothing is left behind for a later fall.  A fall the fighter never claimed
    spends nothing, and one whose claim was already spent on other Bludgeoning damage takes nothing.
    """
    claimed = _falling_claimed(engine, target)
    if claimed <= 0:
        return None
    _clear_falling_claim(target)
    if defended <= 0:
        return None
    from . import note

    note(engine, f"passive:{PADDED}", target,
         f"Padded Layers: {target.display_name} takes {claimed} less damage from the {int(getattr(fall, 'distance_ft', 0))}-foot "
         f"fall (twice their Proficiency Bonus, because it is falling damage).")
    return {"amount": max(0, defended - claimed)}


# ------------------------------------------------------------------------------------------------ Circuit Armor, Walking Fortress
@effect("equipment_circuit")
def equipment_circuit(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    run_effects(ctx, [{"type": "condition", "condition": "circuit_armor", "applies_to": "self", "duration": "one_minute",
                       "evidence": eff.get("evidence") or "Circuit Armor: the circuit is awake for 1 minute"}])


def _end_fortress(engine: Any, actor: Any, reason: str) -> bool:
    ended = False
    for mid, modifier in list(actor.modifiers.items()):
        if str(modifier.source_definition_id).endswith(T + "walking_fortress_scripture"):
            del actor.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"modifier_id": mid, "reason": reason})
            ended = True
    return ended


@hook("event")
def ends_on_incapacitated(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_APPLIED":
        return
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        if actor is None or not incapacitated(actor):
            continue
        if any(c.condition_id == CIRCUIT for c in actor.conditions.values()):
            engine._remove_condition(actor, CIRCUIT, "passive:circuit_armor")  # "The circuit ends early if you ... become Incapacitated"
        if _end_fortress(engine, actor, "INCAPACITATED"):
            from . import note

            note(engine, T + "walking_fortress_scripture", actor, f"Walking Fortress Scripture: {actor.display_name} is Incapacitated; the stance ends.")


@hook("compile_actions")
def end_fortress_action(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    if T + "walking_fortress_scripture" not in (info.get("owned_ids") or []):
        return None
    typed = {"effects": [{"type": "equipment_end_fortress", "evidence": "The stance ends early if you ... choose to end it."}], "numbers": dict(info["numbers"]),
             "duration": {"kind": "instant"}, "riders": [], "source": T + "walking_fortress_scripture", "coverage": "FULL"}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.equipment.end_fortress", display_name="End Walking Fortress",
                             owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                             parameters={"typed": typed, "expected_damage": 0, "player_only": True, "equipment_end": "fortress"})]


@effect("equipment_end_fortress")
def equipment_end_fortress(ctx: Any, eff: dict[str, Any]) -> None:
    if _end_fortress(ctx.engine, ctx.actor, "ENDED"):
        ctx.rider(f"{ctx.actor.display_name} ends the Walking Fortress stance.")


# ------------------------------------------------------------------------------------------------ AC, Temporary HP, targets
@hook("ac")
def shell_lost_while_incapacitated(engine: Any, target: Any) -> int | None:
    """Mountain-Pattern Shell: "You lose this bonus while Incapacitated"."""
    if not target.conditions or not incapacitated(target):
        return None
    shell = [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(target.entity_id, [])
             if row.get("feature_id") == T + "mountain_pattern_shell" and row.get("kind") == "ac"]
    return -sum(int(row.get("amount") or 0) for row in shell) or None


@hook("event")
def lacing(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Qi-Conductive Lacing: CP spent on an Equipment talent (while armoured) -> Temporary HP equal to PB, once per turn."""
    if event_type != "RESOURCE_SPENT":
        return
    source = str(engine.events[-1].source_definition_id if engine.events else "")  # (the source is not among the hook's kwargs)
    payload = kwargs.get("payload") or {}
    if ".tianxia.talent.equipment." not in source and not source.startswith(T):
        return
    if str(payload.get("resource_id")) not in ("resource:core.qi", "resource:core.stamina", "resource:core.resonance"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None:
        return
    for row in rows(engine, actor, "qi_lacing"):
        if row.get("armor") and not actor.turn_flags.get("equipment_lacing_turn"):
            actor.turn_flags["equipment_lacing_turn"] = True
            engine._grant_temp_hp(actor, int(row["pb"]), row["feature_id"], actor.entity_id)


@hook("turn_start")
def legion(engine: Any, actor: Any) -> None:
    """Black Armor Legion Scripture: Temporary HP when the fight begins -- granted at the start of the first turn of the fight (the table has
    no initiative event a plug-in can answer), for every fighter who has it, so none acts before it holds them."""
    if int(engine.state.round_number or 0) != 1 or getattr(engine, "_legion_done", False):
        return
    engine._legion_done = True
    for who in engine.state.actors.values():
        for row in rows(engine, who, "legion"):
            if who.active and row.get("armor") and not who.turn_flags.get("equipment_round_legion_done"):
                who.turn_flags["equipment_round_legion_done"] = True
                engine._grant_temp_hp(who, max(1, int(row["pb"]) + int(row["key_mod"])), row["feature_id"], who.entity_id)


@hook("candidate_allowed")
def mirror_needs_sight(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not str(action.source_definition_id).endswith(T + "mirror_bright_armor") or not candidate.target_ids:
        return None
    target = engine.state.actors.get(candidate.target_ids[0])
    return None if target is not None and can_see(engine, target, actor) else False


def can_see(engine: Any, viewer: Any, seen: Any) -> bool:
    """A clear sight line not hidden by an area (combat/stealth.py sees), the viewer not Blinded and the one it looks at not Invisible
    (unless the viewer's senses see through that: combat/senses.py sees_hidden)."""
    from .. import senses, stealth

    if not stealth.sees(engine, viewer, seen):
        return False
    held = {c.condition_id for c in viewer.conditions.values()}
    if "condition:typed.blinded" in held or "condition:core.blinded" in held:
        return senses.sees_hidden(engine, viewer, seen)
    if any(c.condition_id in ("condition:typed.invisible", "condition:core.invisible") for c in seen.conditions.values()):
        return senses.sees_hidden(engine, viewer, seen)
    return True
