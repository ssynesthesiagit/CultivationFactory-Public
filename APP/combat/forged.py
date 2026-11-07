"""Forged Techniques in combat (PHB ch. 18 "Forged Techniques"; owner 2026-09-27: "we should allow composite
techniques to be created and added").

A Forged Technique is a Base Form carrying a Primary Sphere Effect -- the typed effect of a talent the character
knows -- with Secondary Sphere Effects, Augments and Drawbacks (character_creation/constructed_arts/forged_technique.py
builds and checks the record). ``mechanic_for`` writes it as one more typed mechanic, in the shape of
authority/Tianxia_Typed_Mechanics_Authority_R1.json, so the compiler delivers it like a printed talent: a Strike uses
the character's weapon, a Burst is an area save, an Aura or a Zone stays on the map. The numbers the PHB leaves to the GM
are owner-editable in combat/rules/forged_techniques.json.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterator

from .effect_harm import classify_effect

RULES_PATH = Path(__file__).resolve().parent / "rules" / "forged_techniques.json"
_NOT_PAYLOAD = {"spend_resource", "gain_resource", "zone", "summon", "command_summons", "movement", "teleport"}
# Portable zone-trigger contract: delivery changes may carry only these ordinary
# creature effects. Extension handlers must not be assumed independent of their
# owning zone (they may query, spend or remove it). Expand this allowlist only
# with a table regression proving independence from separately placed state.
_PORTABLE_ZONE_EFFECTS = {"save", "damage", "extra_damage", "half_damage", "condition",
                          "reaction_denied", "deny_temp_hp"}
# These keys describe delivery/presentation, which a Base Form replaces. Every
# other trigger key is a predicate or state contract we cannot express here;
# fail closed, including for future predicates, rather than discarding it.
_PORTABLE_TRIGGER_KEYS = {"on", "event", "who", "id", "name", "effects"}


def rules() -> dict[str, Any]:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def _walk(effects: Any) -> Iterator[dict[str, Any]]:
    for effect in effects or []:
        if isinstance(effect, dict):
            yield effect
            for key in ("on_hit", "on_fail", "on_success", "effects", "then"):
                yield from _walk(effect.get(key))


def payload(mechanic: dict[str, Any]) -> dict[str, Any]:
    """What a talent does to the creature it affects: its attack's on-hit effects, or its save's failure effects
    (``half``: half damage on a success), or its other effects on a target; ``own``: what it does for its user.
    Portable zone saves additionally expose ``success`` for non-damage success outcomes; delivery must preserve
    both branches or reject the selection. Source mechanics are never mutated."""
    effects = [effect for effect in mechanic.get("effects") or [] if isinstance(effect, dict)]
    own = [copy.deepcopy(effect) for effect in effects if effect.get("applies_to") == "self" and effect.get("type") not in _NOT_PAYLOAD]
    for effect in effects:
        if effect.get("type") == "attack":
            hits = [hit for hit in effect.get("on_hit") or [] if isinstance(hit, dict)
                    and not (hit.get("type") == "damage" and hit.get("weapon_damage"))]
            return {"effects": copy.deepcopy(hits), "ability": None, "half": False, "own": own}
        if effect.get("type") == "save":
            return {"effects": copy.deepcopy(effect.get("on_fail") or []), "ability": str(effect.get("ability") or "").upper() or None,
                    "half": any(row.get("type") == "half_damage" for row in effect.get("on_success") or [] if isinstance(row, dict)), "own": own}
    # A persistent source's creature effect belongs to its trigger, not to the
    # zone placement. Base Forms replace delivery geometry. Carry an unambiguous
    # repeated payload (entry/start often share identical rows), without carrying
    # the source's zone or guessing between distinct trigger outcomes.
    triggers = [trigger for effect in effects if effect.get('type') == 'zone'
                for trigger in effect.get('triggers') or []
                if isinstance(trigger, dict) and trigger.get('effects')]
    if any(set(trigger) - _PORTABLE_TRIGGER_KEYS
           or any(row.get('type') not in _PORTABLE_ZONE_EFFECTS for row in _walk(trigger['effects']))
           for trigger in triggers):
        return {'effects': [], 'ability': None, 'half': False, 'own': own,
                'rejected': 'The zone trigger requires eligibility or zone state that this delivery cannot carry.'}
    triggered = {json.dumps(trigger['effects'], sort_keys=True): trigger['effects'] for trigger in triggers}
    if len(triggered) == 1:
        rows = next(iter(triggered.values()))
        carried = payload({'effects': rows})
        # The ordinary save extractor historically retains only half damage.
        # Newly portable zone saves must also carry their other success effects,
        # with their scopes and expiry intact. Keep this contract zone-specific
        # so pre-existing top-level saved techniques retain their interpretation.
        saved = next((row for row in rows if row.get('type') == 'save'), None)
        if saved:
            success = [copy.deepcopy(row) for row in saved.get('on_success') or []
                       if row.get('type') != 'half_damage']
            if success:
                carried['success'] = success
        # A zone's affected creature becomes the delivery target. Older trigger
        # rows use SELF for its next turn; make that explicit for the executor's
        # exact target-turn expiry instead of the source/holder early sweep.
        for row in _walk([*carried['effects'], *carried.get('success', [])]):
            if (row.get('expires_on') == 'START_OF_SELF_NEXT_TURN'
                    and row.get('duration') == 'until_start_of_next_turn'
                    and row.get('applies_to') in ('target', 'creatures_in_area', 'enemies_in_area')):
                row['expires_on'] = 'START_OF_TARGET_NEXT_TURN'
        if carried['effects']:
            return {**carried, 'own': own}
    rest = [copy.deepcopy(effect) for effect in effects if effect.get("type") not in _NOT_PAYLOAD and effect.get("applies_to") != "self"]
    return {"effects": rest, "ability": None, "half": False, "own": own}


def _damage(effects: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((effect for effect in _walk(effects) if effect.get("type") in ("damage", "extra_damage")), None)


def _saved(effect: dict[str, Any], ability: str) -> dict[str, Any]:
    """"Hostile conditions require saving throws against the Cultivation Save DC" (PHB ch. 18)."""
    return {"type": "save", "ability": ability.lower(), "dc": "technique_save_dc", "on_fail": [effect], "on_success": []}


def mechanic_for(technique: dict[str, Any], mechanics: dict[str, Any], table: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The technique as a typed mechanic, or None when its Primary Sphere Effect has no typed effect to carry."""
    table = table or rules()
    primary_id = str((technique.get("primary_sphere_effect") or {}).get("talent_id") or "")
    primary = mechanics.get(primary_id)
    if not primary:
        return None
    base_form = technique.get("base_form") or {}
    form_id = str(base_form.get("form_id") or str(base_form.get("display_name") or "strike").strip().lower())
    form = table["forms"].get(form_id) or table["forms"]["strike"]
    base = payload(primary)
    if base.get('rejected'):
        return None  # Never offer/pay for a primary whose actual effect cannot be carried.
    success = base.get('success') or []
    if success and (_damage(success) or form['delivery'] not in ('weapon', 'attack', 'area', 'zone')):
        # Independent success damage cannot share the failure damage cache or
        # the Base Form's default half damage. Other forms discard save branches.
        return None
    hits, ability, half = base["effects"], base["ability"], base["half"]
    riders: list[str] = []  # "Choose one effect from a Sphere base ability or talent": not the talent's other riders
    text = [form["text"]]

    # Secondary Sphere Effects: their conditions join the technique; their damage types become choices of its damage.
    for secondary in technique.get("secondary_sphere_effects") or []:
        mechanic = mechanics.get(str(secondary.get("talent_id") or ""))
        if not mechanic:
            riders.append(f"{secondary.get('talent_name') or 'Secondary effect'} (GM)")
            continue
        extra = payload(mechanic)
        if extra.get('rejected') or extra.get('success'):
            return None  # Dropping a selected secondary silently also misrepresents the technique.
        damage = _damage(hits)
        for effect in extra["effects"]:
            if effect.get("type") in ("damage", "extra_damage") and damage is not None:
                damage["damage_types"] = list(dict.fromkeys([*(damage.get("damage_types") or []), *(effect.get("damage_types") or [])]))
            else:
                hits.append(effect)
        ability = ability or extra["ability"]

    augments = {str(row.get("augment_id")) for row in technique.get("augments") or [] if isinstance(row, dict)}
    choices = technique.get("table_choices") or {}
    rule = table["augments"]
    damage = _damage(hits)
    if "increased_damage" in augments and damage is not None:
        extra = int(rule["increased_damage"]["extra_dice"])
        if damage.get("dice_by_cl"):
            # A CL-scaled damage row is rolled from this table, which outranks "dice" (typed_executor._effect_dice), so the extra die
            # has to be in every tier or it is never rolled (Lava Spit's 2d8 / 3d8 / 5d8 / 7d8 by Cultivation Level).
            damage["dice_by_cl"] = [[low, high, int(count) + extra, sides] for low, high, count, sides in damage["dice_by_cl"]]
        if damage.get("dice"):
            damage["dice"] = {**damage["dice"], "count": int(damage["dice"].get("count") or 0) + extra}
        elif not damage.get("dice_by_cl"):
            damage["dice"] = {"count": extra, "sides": int(rule["increased_damage"]["default_sides"])}
    if "ignore_resistance" in augments and damage is not None:
        # "The damage ignores Resistance": this technique's damage and no other, the executor reads it from the action's own
        # effects when the damage lands (Targeted Assault's shape). Nothing is put on the target, so nothing has to expire --
        # a suppress_resistance modifier with a made-up expiry name stayed on the target for the rest of the fight (hunt 2).
        hits.insert(0, {"type": "ignore_resistance", "applies_to": "target", "damage_types": list(damage.get("damage_types") or [])})
    hostile: list[dict[str, Any]] = []  # effects an Augment adds, each behind its own save
    save_for = table.get("save_for") or {}
    if "forced_movement" in augments:
        distance = int(rule["forced_movement"]["distance_ft"])
        hostile.append(_saved({"type": "forced_movement", "applies_to": "target", "flat": distance, "distance_ft": distance}, rule["forced_movement"]["save"]))
    if "minor_hindrance" in augments:
        pick = rule["minor_hindrance"]["choices"].get(str(choices.get("minor_hindrance") or rule["minor_hindrance"]["default"]))
        pick = pick or rule["minor_hindrance"]["choices"][rule["minor_hindrance"]["default"]]
        hostile.append(_saved({key: value for key, value in pick.items() if key != "save"} | {"applies_to": "target"}, pick["save"]))
    for key in ("major_condition", "severe_hindrance"):
        if key in augments:
            condition = str(choices.get(key) or rule[key]["default"])
            condition = condition if condition in rule[key]["choices"] else rule[key]["default"]
            save = save_for.get(condition, "CON")
            effect = {"type": "condition", "condition": condition, "applies_to": "target"}
            if rule[key].get("repeat_save"):
                effect["repeat_save"] = {"ability": save, "when": "end"}
            if rule[key].get("duration"):  # the printed words ("until_end_of_next_turn"); the executor names the turn (effect_expiry)
                effect["duration"] = rule[key]["duration"]
            if rule[key].get("expires_on"):
                effect["expires_on"] = rule[key]["expires_on"]
            hostile.append(_saved(effect, save))
    for key in ("additional_target", "lingering_effect", "domain_effect", "conceptual_effect"):
        if key in augments:
            riders.append(rule[key]["text"])

    duration = copy.deepcopy(primary.get("duration") or {"kind": "instant", "amount": None, "concentration": False})
    drawbacks = {str(row.get("drawback_id")) for row in technique.get("drawbacks") or [] if isinstance(row, dict)}
    area, reach, effects = None, copy.deepcopy(primary.get("range") or {"kind": "feet", "feet": 5}), []
    delivery, feet = form["delivery"], int((primary.get("range") or {}).get("feet") or 0)
    if "extended_range" in augments:
        feet = max(feet, int(form.get("range_ft") or 30)) * int(rule["extended_range"]["multiplier"])
    grow = int(rule["expanded_area"]["add_ft"]) if "expanded_area" in augments else 0
    save_ability = (ability or table.get("default_save") or "DEX").lower()
    weapon_delivery = None
    if delivery in ("weapon", "attack") and ability:
        # A save-based effect carried by a hit: the damage lands with the hit; what it does beyond damage keeps the
        # talent's own save ("Hostile conditions require saving throws", PHB ch. 18).
        direct = [effect for effect in hits if effect.get("type") in ("damage", "extra_damage", "ignore_resistance")]
        rest = [effect for effect in hits if effect.get("type") not in ("damage", "extra_damage", "ignore_resistance")]
        hits = [*direct, *([{"type": "save", "ability": save_ability, "dc": "technique_save_dc", "on_fail": rest, "on_success": success}] if rest or success else [])]
    if delivery == "weapon":
        effects = [{"type": "attack", "attack_kind": "weapon", "count": 1, "on_hit": [*hits, *hostile]}]
        weapon_delivery = {"kind": "any", "family": None, "special_attack": False}
        reach = {"kind": "feet", "feet": 5}
    elif delivery == "attack":
        effects = [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1, "on_hit": [*hits, *hostile]}]
        reach = {"kind": "feet", "feet": max(feet, int(form["range_ft"]))}
    elif delivery in ("area", "zone"):
        size = int(form["size_ft"]) + grow
        area = {"shape": form["shape"], "size_ft": size, "centered_on_self": bool(form.get("self"))}
        reach = {"kind": "self"} if form.get("self") else {"kind": "feet", "feet": max(feet, int(form.get("range_ft") or 60))}
        on_success = [*([{"type": "half_damage", "applies_to": "target"}]
                        if (half or delivery == "area") and _damage(hits) else []), *success]
        # A primary with no creature payload (e.g. a campaign-scale project)
        # has nothing for a delivery save to decide. Augments retain their own
        # saves; do not add a second, outcome-free roll before them.
        # The Forge authority names geometry, not recipients. Harmful forged
        # areas use the owner's enemies-only default; the primary payload's
        # old delivery scope must not widen this new enclosing save.
        harmful_hits = [row for row in hits if classify_effect(row) is not False]
        benefits = [row for row in hits if classify_effect(row) is False] if harmful_hits else []
        # A friendly payload is not contingent on an enemy failing the delivery
        # save. Keep explicit printed scopes; a carried target benefit defaults
        # to the user/allies in this new area, separately from hostile delivery.
        benefits = [{**row, "applies_to": "allies_in_area"}
                    if row.get("applies_to") in (None, "target") else row for row in benefits]
        recipient_scope = "enemies_in_area" if harmful_hits else "creatures_in_area"
        saved_hits = harmful_hits if harmful_hits else hits
        effects = [*([{"type": "save", "applies_to": recipient_scope, "ability": save_ability, "dc": "technique_save_dc", "on_fail": saved_hits,
                      "on_success": on_success}] if hits or on_success else []), *hostile]
        effects += benefits
        if delivery == "zone":
            duration = copy.deepcopy(form["duration"])
        if "persistent_zone" in augments and delivery == "area":
            duration = copy.deepcopy(rule["persistent_zone"]["duration"])
            text.append(rule["persistent_zone"]["text"])
    elif delivery == "ward":
        damage = _damage(hits)
        effects = [{"type": "temp_hp", "applies_to": "target", "formula": form.get("temp_hp_formula") or "pb"},
                   *([{"type": "resistance", "applies_to": "target", "damage_types": list(damage.get("damage_types") or []),
                       "duration": "until_start_of_next_turn"}] if damage else []),
                   *[{**effect, "applies_to": "target"} for effect in base["own"]]]
        reach = {"kind": "feet", "feet": int(form["range_ft"]) * (int(rule["extended_range"]["multiplier"]) if "extended_range" in augments else 1)}
    elif delivery == "movement":
        reach = {"kind": "self"}
        effects = [{"type": "movement", "applies_to": "self", "distance_ft": int(form["distance_ft"]) + grow, "no_opportunity_attacks": True}]
        riders.append(f"{primary.get('name')}: {', '.join(str(row.get('evidence') or row.get('type')) for row in hits[:3])} (GM)")
    else:  # counter: the GM resolves the trigger
        effects = [*([{"type": "save", "ability": save_ability, "dc": "technique_save_dc", "on_fail": hits,
                      "on_success": []}] if hits else []), *hostile]
    if not hits and delivery != "ward":  # a talent that only helps its user carries that help
        effects += base["own"]
    if "mobility_rider" in augments:
        effects.append({"type": "movement", "applies_to": "self", "distance_ft": int(rule["mobility_rider"]["distance_ft"]), "no_opportunity_attacks": True})
    if "self_damage" in drawbacks:
        effects.append({"type": "damage", "applies_to": "self", "flat": 0, "formula": table["drawbacks"]["self_damage"]["formula"],
                        "damage_types": [table["drawbacks"]["self_damage"]["damage_type"]]})
    if "exhausting" in drawbacks:
        # "An Exhausting technique gives you 1 level of Exhaustion after the technique resolves" (PHB ch. 18) -- was
        # a GM-only line (the table had no Exhaustion at all); combat/ext/forged_exhaustion.py makes it a real,
        # leveled condition (-1 per level to d20 Tests, -5 ft Speed per level, dead at 6) so an AI that spams an
        # Exhausting technique actually pays for it, the same as self_damage above.
        effects.append({"type": "exhaustion", "applies_to": "self", "amount": 1,
                        "evidence": "Exhausting: 1 level of Exhaustion after the technique resolves."})
    if "concentration" in drawbacks:
        duration = {**duration, "concentration": True, "kind": duration.get("kind") if duration.get("kind") not in (None, "instant") else "minutes",
                    "amount": duration.get("amount") or 1}
    for row in technique.get("drawbacks") or []:
        if isinstance(row, dict) and row.get("drawback_id") not in ("self_damage", "exhausting", "concentration", "once_per_short_rest", "once_per_long_rest"):
            riders.append(f"{row.get('display_name')}: {row.get('restriction')}")
    if form.get("follows"):
        text.append("It moves with you.")
    economy = str(technique.get("action_type") or "action").lower().replace(" ", "_")
    # A reaction Forged Technique ("Counter" base form) "expresses" its Primary Sphere Effect's own trigger (gu
    # 2026-09-28: Gu's own Brute-Gravity Counter/Berserker-Sand Counter, built to trigger exactly when Break
    # Defenses/Bone-Breaker do) -- this was hardcoded to None, so classify_trigger (combat/reaction_triggers.py)
    # could never recognize any reaction Forged Technique's trigger at all, for any character.
    trigger = primary.get("activation", {}).get("trigger") if economy == "reaction" else None
    mechanic = {
        "schema": "TianxiaFoundry.TypedMechanic.v1", "mechanic_id": str(technique.get("technique_id") or technique.get("name")),
        "kind": "forged_technique", "name": str(technique.get("name") or "Forged Technique"), "sphere_id": primary.get("sphere_id"),
        "activation": {"economy": economy if economy in ("action", "bonus_action", "reaction") else "action", "trigger": trigger},
        "cost": [[{"resource": "cp", "amount": int((technique.get("cp_cost") or {}).get("final") or 0), "amount_formula": None}]],
        "range": reach, "area": area, "target": None, "duration": duration, "effects": effects, "options": [],
        "riders": riders, "description": text, "typing_status": "forged", "coverage": "CORE" if riders else "FULL",
        "forged_from": primary_id, "base_form": form_id,
    }
    if weapon_delivery:
        mechanic["weapon_delivery"] = weapon_delivery
    if hostile:
        mechanic["augment_effects"] = copy.deepcopy(hostile)  # what its Augments add, each behind its own save (as_reaction)
    if technique.get("design_policy") == "single_resolution_v1":
        # New designs opt into the creation policy. Existing character records
        # retain their interpretation until the owner chooses to refresh them.
        from character_creation.constructed_arts.forge_design import restructure
        mechanic = restructure(mechanic)
    return mechanic


def as_reaction(technique: dict[str, Any], mechanic: dict[str, Any], mechanics: dict[str, Any]) -> dict[str, Any] | None:
    """A Reaction Forged Technique (a Counter, "reaction against a trigger", or one forged with Reaction Activation) as a
    reaction the table can run (docket 2026-09-28; owner 2026-09-27: "Reaction/Counter Forged Techniques (skipped as GM
    today)"). Its trigger: the one written on the record ("trigger"), else the Primary Sphere Effect's own printed trigger
    when that effect is itself a Reaction (Arrow-Turning Breath: "A creature you can see within 30 feet is hit by an
    ordinary ranged weapon attack"). A Counter expressing a Reaction does what that Reaction prints, plus what its
    Augments add. None when no trigger is known: the GM's (the records do not name one)."""
    primary = mechanics.get(str((technique.get("primary_sphere_effect") or {}).get("talent_id") or "")) or {}
    activation = primary.get("activation") or {}
    trigger = str(technique.get("trigger") or (technique.get("table_choices") or {}).get("trigger") or "").strip()
    # A Counter elevates ANY Primary Sphere Effect into a reaction (that is what choosing the "counter" Base Form, or
    # a Reaction Activation augment, means) -- the technique's own activation is already "reaction" by then
    # (mechanic_for's ``economy``), whatever the primary talent's own printed economy is. Gu's Brute-Gravity Counter
    # borrows Break Defenses' printed "Whenever you successfully shove a creature" even though Break Defenses itself
    # is a passive; only a Counter that borrows an already-Reaction primary (Arrow-Turning Breath) also borrows that
    # primary's own effects (below) instead of the save wrapped around its payload by mechanic_for.
    has_trigger = bool(activation.get("trigger"))
    reacts = activation.get("economy") == "reaction" and has_trigger  # primary is itself a Reaction we can express directly
    borrowed = not trigger and has_trigger
    if borrowed:
        trigger = str(activation["trigger"])
    if not trigger:
        return None
    out = copy.deepcopy(mechanic)
    out["activation"] = {"economy": "reaction", "trigger": trigger, "source": "forged"}
    if borrowed:
        out["mechanic_id"] = primary.get("mechanic_id")  # the reviewed reading of that trigger (combat/reaction_triggers.py)
    if mechanic.get("base_form") == "counter" and reacts and not technique.get("trigger"):
        out["effects"] = [*copy.deepcopy(primary.get("effects") or []), *copy.deepcopy(mechanic.get("augment_effects") or [])]
        out["options"] = copy.deepcopy(primary.get("options") or [])
    if technique.get("design_policy") == "single_resolution_v1":
        from character_creation.constructed_arts.forge_design import restructure
        out = restructure(out)
    return out


# Secondary Sphere Effect fit (Grow Forge menu). Judged with the same payload() and mechanic_for() the compiler uses;
# only the delivery rules below are added, derived from each effect's applies_to recipient.
_FOE_SCOPES = {"target", "enemies_in_area", "creatures_in_area", "attacker"}
_AREA_SCOPES = {"enemies_in_area", "creatures_in_area", "allies_in_area"}


def _raw_rows(effects: Any) -> Iterator[dict[str, Any]]:
    """Every effect row of a talent as authored, including zone trigger rows that payload() may not carry."""
    for row in _walk(effects):
        yield row
        for trigger in row.get("triggers") or []:
            if isinstance(trigger, dict):
                yield from _raw_rows(trigger.get("effects"))


def secondary_fit(form_id: str, primary_id: str, candidate_id: str, mechanics: dict[str, Any],
                  table: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Whether talent candidate_id can be a Secondary Sphere Effect of Base Form form_id on Primary primary_id.

    Returns (fits, reason). reason is plain words for hover text, empty when it fits. Read-only: saved techniques
    and their compile are unchanged."""
    table = table or rules()
    form = table["forms"].get(form_id)
    if form is None:
        return False, "Unknown Base Form."
    candidate = mechanics.get(candidate_id)
    primary = mechanics.get(primary_id)
    if not candidate or not primary:
        return False, "This talent has no typed effect to carry."
    if candidate.get("sphere_id") == primary.get("sphere_id"):
        return False, "One effect per Sphere."
    from .ext import effect_forge_rejection
    for effect in _raw_rows(candidate.get("effects")):
        reason = effect_forge_rejection(str(effect.get("type") or ""))
        if reason:
            return False, reason
    carried = payload(candidate)
    if carried.get("rejected"):
        return False, str(carried["rejected"])
    if carried.get("success"):
        return False, "It needs a save branch the Forge cannot combine."
    # A secondary has to contribute at least one effect that payload() actually carries.
    # An empty carried payload is not a legal Sphere Effect just because mechanic_for()
    # can still construct a technique around the primary.
    if not carried.get("effects") and not carried.get("own"):
        return False, "This effect has nothing the Base Form can carry."
    raw = list(_raw_rows(candidate.get("effects")))
    delivery = form["delivery"]
    scopes = {str(row.get("applies_to")) for row in _walk([*carried.get("effects", []), *carried.get("own", [])])}
    if delivery == "movement" and scopes & _FOE_SCOPES:
        return False, "A Movement technique only moves its user; this effect needs a target."
    if delivery == "ward" and scopes & _FOE_SCOPES:
        return False, "A Ward protects its user and allies; this effect would reach a foe or target."
    if delivery in ("weapon", "attack", "area", "zone") and scopes == {"self"}:
        return False, "This delivery affects foes; the effect only helps its user."
    if delivery in ("weapon", "attack") and any(row.get("applies_to") in _AREA_SCOPES for row in raw):
        return False, "It affects an area; a single strike cannot carry it."
    probe_form = {"form_id": form_id, "display_name": form_id}
    technique = {"name": "Fit probe", "base_form": probe_form, "primary_sphere_effect": {"talent_id": primary_id},
                 "secondary_sphere_effects": [{"talent_id": candidate_id, "talent_name": candidate.get("name")}],
                 "augments": [], "drawbacks": [], "cp_cost": {"final": 0}, "action_type": "action"}
    # Tag a throwaway copy of the candidate's actual rows, not the mechanic or
    # rider text. This proves a row survives this delivery (Ward and Movement
    # can discard a perfectly valid extracted payload). Never mutate authority.
    tagged = copy.deepcopy(candidate)
    for effect in _raw_rows(tagged.get("effects")):
        effect["_forge_fit_probe"] = True
    compiled = mechanic_for(technique, {**mechanics, candidate_id: tagged}, table)
    if compiled is None:
        return False, "The rules do not let these Spheres combine on this Base Form."
    delivered = list(_raw_rows(compiled.get("effects")))
    survives = any(row.get("_forge_fit_probe") for row in delivered)
    # Damage rows merge into the Primary's damage-type choices (or a Ward's
    # resistance), rather than being copied as separate tagged rows.
    damage_types = {kind for row in _walk(carried.get("effects"))
                    if row.get("type") in ("damage", "extra_damage")
                    for kind in row.get("damage_types") or []}
    survives = survives or any(
        row.get("type") in ("damage", "extra_damage", "resistance")
        and damage_types.intersection(row.get("damage_types") or [])
        for row in delivered)
    if not survives:
        return False, "This Base Form drops the secondary effect instead of applying it."
    return True, ""


_PROBE_CACHE: tuple[dict[str, Any], dict[str, str]] | None = None


def _probe_by_sphere(mechanics: dict[str, Any], table: dict[str, Any]) -> dict[str, str]:
    """One stand-alone talent per Sphere, scanned over the whole catalog in sorted order (deterministic).
    Cached per loaded catalog: the scan runs once per server process, not per Grow load."""
    global _PROBE_CACHE
    cached = _PROBE_CACHE
    if cached and cached[0] is mechanics:
        return cached[1]
    found: dict[str, str] = {}
    for talent_id in sorted(mechanics):
        row = mechanics[talent_id]
        sphere = row.get("sphere_id")
        if row.get("kind") != "talent" or not row.get("effects") or sphere in found:
            continue
        solo = {"name": "Fit probe", "base_form": {"form_id": "strike", "display_name": "strike"},
                "primary_sphere_effect": {"talent_id": talent_id}, "secondary_sphere_effects": [], "augments": [],
                "drawbacks": [], "cp_cost": {"final": 0}, "action_type": "action"}
        if mechanic_for(solo, mechanics, table) is not None:
            found[sphere] = talent_id
    # Keep only the active catalog. A succession of freshly parsed catalogs must
    # not retain every 11 MB authority dictionary until process exit.
    _PROBE_CACHE = (mechanics, found)
    return found


def fit_table(candidate_ids: list[str], mechanics: dict[str, Any], table: dict[str, Any] | None = None) -> dict[str, dict[str, list[Any]]]:
    """{form_id: {talent_id: [fits, reason]}} for the Forge menu, built once at Grow load.

    The owner's Primary is not known until they pick one, so each candidate is judged against a probe Primary from
    another Sphere that stands alone. Check still runs the real construction with the owner's actual Primary."""
    table = table or rules()
    ids = [str(cid) for cid in candidate_ids if mechanics.get(str(cid))]
    probes = _probe_by_sphere(mechanics, table)
    out: dict[str, dict[str, list[Any]]] = {}
    for form_id in table["forms"]:
        row: dict[str, list[Any]] = {}
        for cid in ids:
            sphere = mechanics[cid].get("sphere_id")
            probe = next((pid for other, pid in sorted(probes.items()) if other != sphere), None)
            if probe is None:
                row[cid] = [False, "No other Sphere can stand as a Primary here."]
                continue
            row[cid] = list(secondary_fit(form_id, probe, cid, mechanics, table))
        out[form_id] = row
    return out
