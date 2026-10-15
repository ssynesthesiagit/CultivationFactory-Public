"""Equipment sphere armour talents whose printed lines were left to the GM (rider lane 9, 2026-09-29; owner: "i want everything we can
automated"). Sphere Compendium, Equipment (owner's text: authority/typed_mechanics/rules_text.json). Worn armor and the single
source-qualified fitted suit are independent; native preparation seals fitted readiness. Rows: feature block "lane9_equipment"
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
from .armor_subject import armor_identity, armor_key

BLOCK = "lane9_equipment"
T = "tianxia.talent.equipment."
CIRCUIT = "condition:typed.circuit_armor"
PHYSICAL = ("BLUDGEONING", "PIERCING", "SLASHING")
FALL_USE, FALL_DECLINE = "use", "decline"   # the two answers the fall's printed "may" offers


MATERIALS = ("leather", "hide", "scale", "lamellar", "padded", "robe")  # Beast-Hide Harness Scripture's armour
PADDED = T + "padded_layers"
PADDED_ROUND_FLAG = f"defense_round_used:{PADDED}"
FALLING_CLAIM = f"equipment_falling_claim:{PADDED}"   # turn flag: what this fall already claimed, cleared on every exit


def armor_inventory(bundle):
    """Physical suits sealed from mundane/treasure source records."""
    return {i["key"]: i for i in (bundle.get("carrying") or {}).get("items") or []
            if i.get("armor_category")}


def _record_suit(armor, purpose, item):
    """Keep a readable current-key cache beside the authoritative identity."""
    identity = armor_identity(item)
    if not identity:
        raise ValueError("Durable armor preparation requires the physical item's stable identity")
    armor[purpose + "_key"] = item["key"]
    armor[purpose + "_identity"] = identity


@hook("preparation_reconcile")
def reconcile_fitted_armor(state, bundle):
    subject = bundle.get("armor_subject") or {}
    if "EQUIPMENT_BASE_FITTED_ARMOR_DESIGNATION" not in subject.get("owned", []):
        return None
    armor = state.setdefault("armor", {"fitted_key": "", "ready": 0, "destroyed": []})
    items = armor_inventory(bundle)
    for purpose in ("fitted", "concealed", "rest_fit"):
        key = armor.get(purpose + "_key", "")
        # Older positional keys cannot identify a given suit. Resolving the
        # literal key as an identity fails closed for UID-bearing items.
        identity = armor.get(purpose + "_identity", key)
        if identity:
            armor[purpose + "_identity"] = identity
            armor[purpose + "_key"] = armor_key(bundle, identity, key)
    # Absence alone is not revocation: the designated suit may have been left
    # behind. Loss of the published category training and destruction are.
    if armor.get("fitted_identity") and (armor.get("fitted_category") not in subject.get("proficiencies", [])
                                         or armor["fitted_identity"] in armor["destroyed"]):
        armor.update(fitted_key="", fitted_identity="", fitted_category="", ready=0)
    pending = armor.get("pending")
    if pending:
        pending["key"] = armor_key(bundle, pending.get("identity", pending["key"]), pending["key"])
        item = items.get(pending["key"])
        if not item or not item.get("armor_proficient") or armor_identity(item) in armor["destroyed"]:
            armor.pop("pending")
    return True


@hook("preparation_command")
def fitted_armor_command(state, bundle, operation, parameters):
    if not operation.startswith("armor."):
        return None
    armor = state.get("armor")
    if armor is None or "EQUIPMENT_BASE_FITTED_ARMOR_DESIGNATION" not in bundle["armor_subject"]["owned"]:
        raise ValueError("Fitting armor requires the Equipment sphere")
    subject = bundle["armor_subject"]
    if operation == "armor.ease.choose":
        category = parameters.get("category")
        chosen = armor.setdefault("ease_categories", [])
        if category not in subject["proficiencies"]:
            raise ValueError("Armor Ease requires proficiency in the chosen category")
        if category in chosen or len(chosen) >= subject["armor_ease_count"]:
            raise ValueError("Each owned Armor Ease choice must be a different category")
        chosen.append(category)
        return True
    if operation == "armor.head_protection" and (set(parameters) != {"item_key", "kind"}
            or not isinstance(parameters.get("item_key"), str) or not isinstance(parameters.get("kind"), str)):
        raise ValueError("Head protection requires a physical suit key and a named kind of protection")
    item = armor_inventory(bundle).get(parameters.get("item_key"))
    if item is None:
        raise ValueError("Choose a source-qualified physical suit of armor you own")
    identity = armor_identity(item)
    if not identity:
        raise ValueError("Durable armor preparation requires the physical item's stable identity")
    if operation == "armor.destroy":
        if identity not in armor["destroyed"]:
            armor["destroyed"].append(identity)
        return True
    if operation == "armor.head_protection":
        from .armor_subject import HEAD_PROTECTION_KINDS
        kind = parameters.get("kind")
        if kind not in HEAD_PROTECTION_KINDS | {"none"}:
            raise ValueError("Record a helmet, mask, armored hood, equivalent head protection, or none")
        if not item.get("worn") or not item.get("armor_proficient") or identity in armor["destroyed"]:
            raise ValueError("Head protection requires a worn, undestroyed suit you are proficient with")
        # This records the player's equipment fact; it creates no equipment.
        # An explicit empty profile overrides any older published sheet fact.
        armor["head_protection"] = {} if kind == "none" else {"armor_key": item["key"], "kind": kind,
            **({"identity": identity} if identity != item["key"] else {})}
        return True
    if operation == "armor.conceal":
        if T + "hidden_plates" not in subject["owned"] or not item.get("worn") or not item.get("armor_proficient") \
                or item["armor_category"] not in {"light", "medium"} or identity in armor["destroyed"]:
            raise ValueError("Hidden Plates requires worn light or medium armor you are proficient with")
        disguise = parameters.get("disguise")
        if disguise not in {"ordinary clothing", "travel robes", "sect dress", "court dress", "work garments"}:
            raise ValueError("Choose one of Hidden Plates' printed clothing disguises")
        _record_suit(armor, "concealed", item)
        armor["disguise"] = disguise
        return True
    if operation != "armor.fit.start":
        return None
    if not item.get("armor_proficient") or identity in armor["destroyed"]:
        raise ValueError("Fitted Armor requires proficiency with an undestroyed suit")
    activity = ((state.get("rest_world") or {}).get("actors", {}).get(bundle["actor_id"], {}).get("activity") or {})
    if activity.get("status") == "active":
        if activity.get("kind") != "long_rest":
            raise ValueError("Armor can be fitted during a long rest or with ten minutes of preparation")
        _record_suit(armor, "rest_fit", item)
        armor["rest_fit_category"] = item["armor_category"]
    else:
        armor["pending"] = {"key": item["key"], "identity": identity, "category": item["armor_category"], "worked_seconds": 0}
    return True


@hook("preparation_options")
def fitted_armor_options(state, bundle):
    """Complete named preparation menu; no automatic player-owned choices."""
    armor = state.get("armor")
    if armor is None or "EQUIPMENT_BASE_FITTED_ARMOR_DESIGNATION" not in bundle["armor_subject"]["owned"]:
        return None
    commands = []
    def offer(operation, label, **parameters):
        commands.append({"operation": operation, "label": label, "parameters": parameters})
    activity = ((state.get("rest_world") or {}).get("actors", {}).get(bundle["actor_id"], {}).get("activity") or {})
    resting = activity.get("status") == "active"
    for item in armor_inventory(bundle).values():
        if not item.get("armor_proficient") or not armor_identity(item) or armor_identity(item) in armor["destroyed"]:
            continue
        if item.get("worn") and T + "helmet_discipline" in bundle["armor_subject"]["owned"]:
            from .armor_subject import HEAD_PROTECTION_KINDS
            for kind in sorted(HEAD_PROTECTION_KINDS):
                offer("armor.head_protection", f"Helmet Discipline: record actual {kind} worn with {item['name']}; "
                      "no cost; permits turning one critical hit into a normal hit until the next long rest",
                      item_key=item["key"], kind=kind)
            offer("armor.head_protection", f"Helmet Discipline: record no head protection with {item['name']}; no cost",
                  item_key=item["key"], kind="none")
        if not resting or activity.get("kind") == "long_rest":
            offer("armor.fit.start", f"Fit {item['name']} ({item['armor_category']} armor): "
                  + ("designate during this long rest" if resting else "begin 10 minutes of fitting"), item_key=item["key"])
        if item.get("worn") and item["armor_category"] in {"light", "medium"} \
                and T + "hidden_plates" in bundle["armor_subject"]["owned"]:
            for disguise in ("ordinary clothing", "travel robes", "sect dress", "court dress", "work garments"):
                offer("armor.conceal", f"Hidden Plates: disguise {item['name']} as {disguise} until changed; no cost",
                      item_key=item["key"], disguise=disguise)
    subject = bundle["armor_subject"]
    chosen = armor.get("ease_categories", [])
    if len(chosen) < subject["armor_ease_count"]:
        for category in subject["proficiencies"]:
            if category not in chosen:
                offer("armor.ease.choose", f"Armor Ease: choose {category} armor; ignore its Stealth Disadvantage while worn",
                      category=category)
    if armor.get("pending") and not resting:
        remaining = max(1, 600 - armor["pending"]["worked_seconds"])
        offer("time.advance", f"Spend {remaining} seconds fitting the chosen suit", seconds=remaining, observation="fitting")
    if resting:
        offer("time.advance", "Observe 8 hours of sleep for this rest"
              + (" out of armor, then put it back on" if armor.get("rest_out_of_armor") else
                 " (heavy armor needs 10 minutes of refitting afterward)"),
              seconds=28800, observation="sleep")
        offer("rest.cancel", "Cancel the current rest; no rest benefits")
    else:
        from .armor_subject import worn_item
        from services.factory_dm_v0.gameplay.rules import LONG_REST_COOLDOWN_SECONDS
        worn = worn_item(bundle)
        rest_actor = ((state.get("rest_world") or {}).get("actors") or {}).get(bundle["actor_id"], {})
        last_rest = rest_actor.get("last_long_rest_at")
        remaining = max(0, last_rest + LONG_REST_COOLDOWN_SECONDS - state["elapsed_seconds"]) if last_rest is not None else 0
        if remaining:
            offer("time.advance", f"Wait {remaining} seconds until the next long rest is available; no rest benefits while waiting",
                  seconds=remaining, observation="unobserved")
        else:
            recovery = " to regain Helmet Discipline" if T + "helmet_discipline" in subject["owned"] else ""
            if not worn or worn.get("armor_proficient") and T + "sleep_in_armor" in subject["owned"]:
                offer("rest.start", "Start a long rest: observe 8 hours of sleep" + recovery
                      + (" wearing armor; heavy armor needs 10 minutes of refitting afterward" if worn else ""),
                      kind="long_rest")
            if worn:
                offer("rest.start", f"Remove {worn['name']}, rest out of armor for 8 hours" + recovery
                      + ", then put it back on; no resource cost or post-sleep refitting",
                      kind="long_rest", armor_mode="removed")
    return commands


@hook("preparation_activity")
def fitted_armor_time(state, bundle, operation, parameters, events):
    armor = state.get("armor")
    if armor is None:
        return None
    pending = armor.get("pending")
    if pending and operation == "time.advance" and parameters.get("observation") == "fitting":
        pending["worked_seconds"] += parameters["seconds"]
    if pending and pending["worked_seconds"] >= 600:
        armor.update(fitted_key=pending["key"], fitted_identity=pending["identity"],
                     fitted_category=pending["category"], ready=1, refit_required=0)
        armor.pop("pending")
    if any(e["kind"] == "long_rest_completed" for e in events) and armor.get("rest_fit_key"):
        armor.update(fitted_key=armor.pop("rest_fit_key"), fitted_identity=armor.pop("rest_fit_identity"),
                     fitted_category=armor.pop("rest_fit_category"), ready=1)
    if any(e["kind"] == "long_rest_completed" for e in events):
        from .armor_subject import worn_item
        worn = worn_item(bundle)
        if worn and not armor.get("rest_out_of_armor") and worn["armor_category"] == "heavy" \
                and armor.get("fitted_identity") == armor_identity(worn):
            armor["ready"] = 0
            armor["refit_required"] = 1
            # Sleep in Armor requires this work after waking. A fitting task
            # begun before the rest cannot carry seconds into that refit.
            if pending and pending["identity"] == armor_identity(worn):
                pending["worked_seconds"] = 0
    if operation in {"rest.cancel", "rest.interrupt"}:
        armor.pop("rest_fit_key", None)
        armor.pop("rest_fit_identity", None)
        armor.pop("rest_fit_category", None)
    if operation in {"rest.cancel", "rest.interrupt"} or any(e["kind"] == "long_rest_completed" for e in events):
        armor.pop("rest_out_of_armor", None)


@hook("preparation_bundle")
def fitted_armor_bundle(bundle, state):
    armor = state.get("armor")
    if armor is None or "EQUIPMENT_BASE_FITTED_ARMOR_DESIGNATION" not in bundle["armor_subject"]["owned"]:
        return None
    subject = bundle["armor_subject"]
    if "head_protection" in armor:
        subject.pop("head_protection_key", None)
        subject.pop("head_protection_kind", None)
        profile = armor["head_protection"]
        item = armor_inventory(bundle).get(armor_key(bundle, profile.get("identity", profile.get("armor_key"))))
        from .armor_subject import HEAD_PROTECTION_KINDS
        if item and armor_identity(item) not in armor["destroyed"] and profile.get("kind") in HEAD_PROTECTION_KINDS:
            subject.update(head_protection_key=item["key"], head_protection_kind=profile["kind"])
    subject.update({k: armor.get(k, "" if k == "fitted_key" else 0) for k in ("fitted_key", "ready")})
    subject["ease_categories"] = armor.get("ease_categories", [])[:subject["armor_ease_count"]]
    from .armor_subject import worn_item
    worn = worn_item(bundle)
    if worn and worn.get("armor_proficient") and worn["armor_category"] in {"light", "medium"} \
            and armor_identity(worn) == armor.get("concealed_identity") and armor_identity(worn) not in armor["destroyed"]:
        subject.update(concealed_key=worn["key"], disguise=armor["disguise"])
    for item in armor_inventory(bundle).values():
        if armor_identity(item) in armor["destroyed"]:
            item["destroyed"] = 1
            if item.get("worn"):
                raise ValueError("Destroyed armor is still worn in the source inventory; update the character's equipment before a new fight")
    return bundle


@hook("preparation_before_activity")
def sleep_in_armor_rest(state, bundle, operation, parameters):
    if operation != "rest.start" or parameters.get("kind", "long_rest") != "long_rest":
        return None
    from .armor_subject import worn_item
    worn = worn_item(bundle)
    mode = parameters.get("armor_mode", "worn")
    if mode not in {"worn", "removed"}:
        raise ValueError("Choose whether to rest wearing armor or remove it for sleep")
    if worn and mode == "worn" and (not worn.get("armor_proficient") or T + "sleep_in_armor" not in bundle["armor_subject"]["owned"]):
        raise ValueError("A long rest in armor requires Sleep in Armor and proficiency with that armor")
    if state.get("armor") is not None:
        state["armor"]["rest_out_of_armor"] = int(mode == "removed")


@hook("armor_penalty_exempt")
def armor_ease_exemption(bundle, penalty, item):
    subject = bundle.get("armor_subject") or {}
    if penalty == "stealth" and T + "armor_ease" in subject.get("owned", []) and item.get("armor_proficient") \
            and item.get("armor_category") in subject.get("ease_categories", []):
        return True
    return None


@hook("equipment_speed_penalty_exempt")
def sure_harness_exemption(info, penalty):
    if penalty != "armor_strength" or T + "sure_harness" not in info["owned_ids"]:
        return None
    from .armor_subject import categories_of, item_record
    worn = next((i for i in info["carrying"]["items"] if i.get("worn")), None)
    if worn and item_record(worn, info["kit"], info["owner_items"]).get("armor_category") in categories_of(info["owner_sheet"]):
        return True
    return None


@hook("compile_actions")
def armor_search_actions(info):
    """Search a perceived creature's clothing; no concealed-state AI oracle."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.armor_search.{modality}",
        display_name=f"Search clothing ({modality})", owner_id=info["actor_id"], economy=EconomyKind.ACTION,
        resolution_kind="TYPED", target_kind="ANY_CREATURE", range_ft=5 if modality == "touch" else None,
        parameters={"basic": True, "expected_damage": 0,
            "target_by_touch": modality == "touch",
            "description": "Spend an Action to inspect a creature's clothing for concealed armor. "
                + ("Reach a known space within 5 feet, even without sight. A physical search by touch has Advantage against Hidden Plates; if nobody is there, nothing is found." if modality == "touch" else
                   "Look for armor under the clothing; Intelligence (Investigation) against its Equipment Save DC."),
            "typed": {"numbers": info["numbers"], "effects": [{"type": "equipment_armor_search", "modality": modality}],
                      "riders": [], "duration": {"kind": "instant"}}}) for modality in ("visual", "touch")]


@effect("equipment_armor_search")
def search_hidden_plates(ctx, effect_row):
    from .armor_subject import bundle_of, worn_item
    from ..typed_executor import resolve_opposed_check
    target = ctx.target
    if target is None or effect_row["modality"] != "touch" and not can_see(ctx.engine, ctx.actor, target):
        return
    bundle = bundle_of(ctx.engine, target)
    subject = bundle.get("armor_subject") or {}
    worn = worn_item(bundle)
    concealed = bool(worn and worn.get("armor_proficient") and subject.get("concealed_key") == worn["key"]
                     and not worn.get("destroyed") and T + "hidden_plates" in subject.get("owned", []))
    if not concealed:
        ctx.engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=ctx.actor.entity_id,
            target_ids=(target.entity_id,), payload={"armor_found": 0, "log": "The search finds no disguised armor."})
        return
    result = resolve_opposed_check(ctx, target,
        {"kind": "check", "ability": "INT", "skill": "Investigation",
         **({"mode": "ADVANTAGE"} if effect_row["modality"] == "touch" else {})}, {"kind": "dc", "basis": "sphere"})
    ctx.engine._append_event("PASSIVE_TRIGGERED", T + "hidden_plates", actor_id=ctx.actor.entity_id,
        target_ids=(target.entity_id,), payload={"armor_found": int(result.success), "modality": effect_row["modality"],
        "dc": result.resistance, "total": result.actor.total,
        "log": f"{ctx.actor.display_name} searches {target.display_name}'s {subject['disguise']}: "
               + ("the disguised armor is noticed." if result.success else "the armor remains concealed.")})


@hook("candidate_allowed")
def clothing_search_visibility(engine, actor, candidate, action):
    effects = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or []
    if not any(e.get("type") == "equipment_armor_search" for e in effects):
        return None
    if action.parameters.get("target_by_touch"):
        from ..target_knowledge import knowledge
        return all(knowledge(engine, actor, engine.state.actors[t], action) is not None for t in candidate.target_ids)
    return all(can_see(engine, actor, engine.state.actors[t]) for t in candidate.target_ids)


@effect("armor_maintenance_check")
def armor_maintenance_check(ctx, row):
    """Resolve the actual source-requested task; advantage is contextual only."""
    from .armor_subject import bundle_of
    from ..typed_executor import resolve_opposed_check
    item = armor_inventory(bundle_of(ctx.engine, ctx.actor)).get(row["item_key"])
    if item is None or item.get("destroyed"):
        return
    result = resolve_opposed_check(ctx, ctx.actor,
        {"kind": "check", "ability": row["ability"], "skill": row.get("skill"),
         "armor_maintenance": {"purpose": row["purpose"], "item_key": row["item_key"]}},
        {"kind": "dc", "dc": row["dc"]})
    ctx.engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=ctx.actor.entity_id,
        target_ids=(ctx.actor.entity_id,), payload={"purpose": row["purpose"], "item_key": row["item_key"],
        "success": int(result.success), "dc": result.resistance, "total": result.actor.total,
        "log": f"{ctx.actor.display_name}'s armor maintenance ({row['purpose']}): " + ("the check succeeds." if result.success else "the check fails.")})


@hook("contest_check_mode")
def field_maintenance_advantage(ctx, subject, opponent, spec):
    context = spec.get("armor_maintenance") or {}
    if not context or subject is not ctx.actor:
        return None
    from .armor_subject import bundle_of
    bundle = bundle_of(ctx.engine, subject)
    if T + "field_maintenance" not in (bundle.get("armor_subject") or {}).get("owned", []):
        return None
    item = armor_inventory(bundle).get(context.get("item_key"))
    if item and item.get("armor_proficient") and not item.get("destroyed") and context.get("purpose") in {
            "clean", "oil", "relace", "patch", "seal", "dry", "safely remove"}:
        return "ADVANTAGE"
    return None


@hook("candidate_allowed")
def maintenance_item_usable(engine, actor, candidate, action):
    request = (getattr(action, "parameters", None) or {}).get("armor_check")
    if not request:
        return None
    from .armor_subject import bundle_of
    item = armor_inventory(bundle_of(engine, actor)).get(request["item_key"])
    return bool(item and not item.get("destroyed"))


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "armor": numbers.get("armor"), "pb": int(numbers.get("pb") or 2),
             "key_mod": int(numbers.get("key_mod") or 0), "keeps_compiling": bool(spec.get("keeps_compiling"))}]


def rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    from .armor_subject import fitted_ready
    if kind in {"breath_aligned", "grand_shell", "circuit", "qi_lacing", "legion"} and not fitted_ready(engine, actor):
        return []
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
    from .armor_subject import proficient_worn
    from ..pending_damage import packet_scratch
    scratch = packet_scratch(engine) or {}
    return (_padded_row(engine, actor) is not None and proficient_worn(engine, actor)
            and not _round_used(engine, actor, PADDED_ROUND_FLAG) and scratch.get("padded_layers_answer") is not False)


@hook("damage_defense_standing_eligible")
def padded_standing_qualified(engine, target, row):
    if row.get("feature_id") != PADDED:
        return None
    from .armor_subject import proficient_worn
    return proficient_worn(engine, target)


@hook("damage_defense_row_allowed")
def padded_packet_allowed(engine, target, row, kind, typed, source_actor_id):
    if row.get("feature_id") != PADDED:
        return None
    from ..pending_damage import packet_scratch
    return (packet_scratch(engine) or {}).get("padded_layers_answer") is not False


@hook("before_damage_defenses")
def padded_optional_packet(engine, target, amount, damage_type, source_id, source_actor_id):
    """One actual packet's printed 'may'; pure estimates never ask or spend."""
    if str(damage_type).upper() != "BLUDGEONING" or not _padded_available(engine, target) or _falling_claimed(engine, target):
        return None
    from ..pending_damage import packet_scratch, current
    from ..typed_reactions import damage_bonus_eligible
    scratch = packet_scratch(engine)
    from ..falling import SOURCE as FALL_SOURCE
    if scratch is not None and source_id == FALL_SOURCE and target.turn_flags.pop("equipment_padded_fall_ordinary", 0):
        scratch["padded_layers_answer"] = True
        return None  # the fall's own explicit ordinary-reduction option answered this packet
    if scratch is None or "padded_layers_answer" in scratch or not damage_bonus_eligible(engine, target, damage_type, source_id, source_actor_id):
        return None
    packet = current(engine)
    pb = int((_padded_row(engine, target) or {}).get("amount") or target.proficiency_bonus)
    collision = packet is not None and "collision_with_object_or_surface" in packet.source_flags
    reduction = pb * (2 if collision else 1)
    action = engine.action_catalog.get(source_id)
    name = getattr(action, "display_name", None) or "the triggering damage"
    chosen = ask(engine, getattr(engine, "_active_intent", None),
        checkpoint_id(engine, "padded_layers_damage", target.entity_id, source_id), target,
        CHOICE + "padded_layers_damage", ["use"], preferred=["use"], allow_decline=True,
        name="Padded Layers", feature_id=PADDED, target_id=target.entity_id,
        prompt=f"Padded Layers: {name} deals {amount} Bludgeoning damage to {target.display_name}. "
               f"Reduce this {'object or surface collision ' if collision else ''}damage by {reduction} "
               f"({'twice your ' if collision else 'your '}Proficiency Bonus)? Costs no Action or resource; once per round.")
    scratch["padded_layers_answer"] = "use" in chosen


def padded_collision_extra(engine, target, kind):
    from ..pending_damage import current
    packet = current(engine)
    if kind == "BLUDGEONING" and packet is not None and "collision_with_object_or_surface" in packet.source_flags \
            and _padded_available(engine, target):
        return int((_padded_row(engine, target) or {}).get("amount") or 0)
    return 0


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
        if FALL_DECLINE in chosen:
            target.turn_flags["equipment_padded_fall_ordinary"] = 1
        _clear_falling_claim(target)   # a declined claim spends nothing: the ordinary reduction still answers
        return
    target.turn_flags[FALLING_CLAIM] = 2 * pb
    target.turn_flags[PADDED_ROUND_FLAG] = engine.state.round_number   # the ordinary row must not answer it as well


@hook("damage_reduction")
def reduce(engine: Any, target: Any, damage_type: str, typed: dict[str, Any], source_actor_id: Any, applied: bool = False) -> int | None:
    kind = str(damage_type).upper()
    if kind == "BLUDGEONING" and _falling_claimed(engine, target):
        return None   # this fall is already answered by Padded Layers: "choose one", so no other reduction answers it
    from ..pending_damage import packet_scratch
    scratch = packet_scratch(engine)
    receipt_key = ("equipment_reduction", target.entity_id, kind)
    if applied and scratch is not None:
        # Ordinary Padded Layers is settled before this callback. Use the exact
        # selection that contributed, rather than selecting again from spent rows.
        picked, extra = scratch.get(receipt_key, (None, 0))
    else:
        picked, extra = _pick(engine, target, kind), padded_collision_extra(engine, target, kind)
        if scratch is not None:
            scratch[receipt_key] = (picked, extra)
    if picked is None:
        return extra or None
    key, amount = picked
    if applied:
        flag = PADDED_ROUND_FLAG if key == "beast_hide" else f"equipment_round_{key}"
        target.turn_flags[flag] = engine.state.round_number
        from . import note

        label = {"grand_shell": "Mountain-Pattern Grand Shell", "circuit": "Circuit Armor", "beast_hide": "Beast-Hide Harness Scripture (Padded Layers)"}[key]
        note(engine, f"passive:{label}", target, f"{label}: {target.display_name} takes {amount} less {kind.lower()} damage.")
    return amount + extra


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
