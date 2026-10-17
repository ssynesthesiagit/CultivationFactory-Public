"""Select printed attack options; shared by natural weapons, finesse and sphere DCs.

Rules grants add options only for their owners. Sheet combat_ability_choices maps
a source or grant scope to an ability abbreviation; a legal recorded choice wins.
Ties retain the printed option order. Old compiled fight bundles are never changed.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

from . import hook


@lru_cache(maxsize=1)
def rules():
    return json.loads((Path(__file__).resolve().parents[1] / "rules/attack_abilities.json").read_text())


def grants():
    return rules()["grants"]


@hook("compile_attack_ability")
def select(options, info):
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
