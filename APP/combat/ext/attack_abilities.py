"""Select printed attack options; shared by natural weapons, finesse and sphere DCs.

Rules grants add options only for their owners. Sheet combat_ability_choices maps
a source or grant scope to an ability abbreviation; a legal recorded choice wins.
Ties retain the printed option order. Shared option_scopes serves compiler selection
and Wrong-Hand Strike's sealed ordinary-ability allocation. Old compiled fight bundles are never changed.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

from . import hook, run_strict


@lru_cache(maxsize=1)
def rules():
    return json.loads((Path(__file__).resolve().parents[1] / "rules/attack_abilities.json").read_text())


def grants():
    return rules()["grants"]


def option_scopes(options, info):
    """Legal ordinary abilities and recorded-choice scopes, without selecting one.

    Used by select and Drunken Style; owning grants and weapon properties follow
    exactly the same precedence as ordinary compiler attack selection.
    """
    allowed = list(options)
    if info["kind"] == "weapon":
        from factory_authoring.starting_kits import _authorities

        weapon = _authorities()[1].get(info["source"], {})
        properties = str(weapon.get("properties") or "").lower()
        weapon_class = str(weapon.get("proficiency_class") or "").lower()
        # A thrown melee weapon retains its melee options. Finesse also applies
        # to ranged weapons; its row therefore precedes the class defaults.
        # A catalog weapon usable in melee and at range retains its melee ability.
        for row in rules()["weapon_options"]:
            if (row.get("property") and row["property"] in properties
                    or row.get("class") and row["class"] in weapon_class):
                allowed = list(row["abilities"])
                break
    scopes = [(info["source"], allowed)]
    for grant in grants():
        if grant["owner"] in info["owned_ids"] and grant["attack_kind"] == info["kind"]:
            allowed.extend(a for a in grant["abilities"] if a not in allowed)
            scopes.append((grant["scope"], grant["abilities"]))
    return allowed, scopes


@hook("compile_attack_ability")
def select(options, info):
    allowed, scopes = option_scopes(options, info)
    choices = info["owner_sheet"].get("combat_ability_choices") or {}
    for scope, legal in scopes:
        choice = str(choices.get(scope) or "").upper()
        if choice in legal:
            return choice
    return max(allowed, key=lambda ability: info["mods"].get(ability, 0))


@hook("compile_action")
def sphere_numbers(action, info):
    typed = action.parameters.get("typed") or {}
    source = str(typed.get("source") or "")
    modifier = str((typed.get("modifier") or {}).get("id") or "")
    for grant in grants():
        if grant["owner"] not in info["owned_ids"]:
            continue
        # Typed source namespaces identify the sphere; the training grant supplies
        # its ability for its talents and Unarmed Strike control options.
        prefix = grant["source_prefix"]
        sphere_action = source.startswith(prefix) or modifier.startswith(prefix)
        natural = ".natural." in action.source_definition_id and not typed.get("modifier")
        if not (sphere_action or typed.get("unarmed_option") or natural):
            continue
        ability = select(grant["abilities"], {**info, "source": grant["scope"], "kind": grant["attack_kind"]})
        bonus = info["mods"].get(ability, 0)
        changed = copy.deepcopy(typed)
        changed["numbers"] = {**changed["numbers"], "save_dc": 8 + info["pb"] + bonus, "key_mod": bonus}
        if sphere_action and not changed.get("weapon"):
            changed["numbers"]["attack_bonus"] = info["pb"] + bonus
        return action.model_copy(update={"parameters": {**action.parameters, "typed": changed}})
    return None


def strike_options(ctx, ordinary):
    """Return currently legal ordinary ability modifiers from substitution providers.

    ``attack_ability_options(ctx)`` returns an ability->integer-modifier mapping,
    or None when ineligible. Providers own runtime ownership/delivery checks.
    Collection is transient, before a choice; it never changes sealed metadata.
    """
    options = dict(ordinary)
    for extra in run_strict("attack_ability_options", ctx):
        if extra is None:
            continue
        for ability, modifier in extra.items():
            if ability not in {"STR", "DEX", "CON", "INT", "WIS", "CHA"} or type(modifier) is not int:
                raise ValueError("invalid ordinary attack ability option")
            options[ability] = modifier
    return options


def strike_attack_only_options(ctx):
    """Transient named alternatives that replace attack ability but leave damage.

    Providers return {option_id: {modifier: int, label: str}} or None, with
    their own ownership and runtime eligibility checks. Named options remain
    distinct even when the same ability has a separate attack/damage grant.
    """
    options = {}
    for extra in run_strict("attack_only_ability_options", ctx):
        if extra is None:
            continue
        for option, value in extra.items():
            if (not isinstance(option, str) or not option or option in options
                    or not isinstance(value, dict) or type(value.get("modifier")) is not int
                    or not isinstance(value.get("label"), str) or not value["label"]):
                raise ValueError("invalid attack-only ability option")
            options[option] = dict(value)
    return options


def resolved_strike_ability(ctx):
    """Whether this strike already resolved its attack ability substitution.

    Substitution providers must not add another ability delta once resolved.
    Additive bonuses remain independent. This is private strike metadata only.
    """
    return bool(ctx.typed.get("resolved_attack_ability"))


def select_strike_ability(ctx, spec, ability, modifier, *, fixed_unarmed=False, original_modifier=0, damage_modifier=None):
    """Replace one prepared weapon ability, preserving every other component.

    ``original_modifier`` supplies the compiled ability component for fixed
    unarmed rows that omit weapon ability metadata. A recorded weapon modifier
    takes precedence, including zero.
    An explicit damage_modifier preserves the separate damage scope of an
    attack-only substitution. Omission applies the selected modifier to both.
    Called before flat attack/damage bonus providers. The executor exposes this
    private typed copy in the current strike Context, including hit riders; the
    next strike starts again from the sealed action. No catalog or sequence edit.
    """
    typed = copy.deepcopy(spec["typed"])
    weapon = typed["weapon"]
    original = int(weapon.get("ability_modifier", original_modifier))
    delta = modifier - original
    damage_modifier = modifier if damage_modifier is None else damage_modifier
    damage_delta = damage_modifier - original
    spec["attack_bonus"] += delta
    typed["resolved_attack_ability"] = ability
    weapon["ability"], weapon["ability_modifier"] = ability, modifier
    typed["numbers"] = {**typed.get("numbers", {}), "attack_bonus": spec["attack_bonus"]}
    if fixed_unarmed and "fixed_damage" in spec:
        spec["fixed_damage"] = max(0, 1 + damage_modifier)
        weapon["fixed_damage"] = spec["fixed_damage"]
    elif not weapon.get("omits_ability_damage") and ctx.weapon_damage_dice and spec.get("damage") is not None:
        spec["damage"] = spec["damage"].model_copy(update={"modifier": spec["damage"].modifier + damage_delta})
        weapon["damage"]["modifier"] = int(weapon["damage"].get("modifier") or 0) + damage_delta
    spec["typed"] = typed
