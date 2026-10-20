"""Owned recipes released through a base technique's native compilation.

compile_recipe_options(frozenset(owned_ids), copied_mechanics) returns None or a
list of RecipeOption. Providers supply effects/target geometry, never actions or
costs. Both records must be owned. The compiler owns IDs, base economy, payment,
range, resource resolution and optional modifiers. Contributions are sorted by
record IDs; duplicates/invalid replies fail compilation instead of disappearing.
No contribution changes an existing action. Old stored bundles are not rebuilt.
"""
from dataclasses import dataclass
from typing import Any
import copy


@dataclass(frozen=True)
class RecipeOption:
    base_id: str
    recipe_id: str
    effects: list[dict[str, Any]]
    target_kind: str
    area: dict[str, Any] | None = None


def contributions(owned, mechanics):
    from . import ext
    result, seen = [], set()
    records = {key: copy.deepcopy(mechanics[key]) for key in owned if key in mechanics}
    for rows in ext.run_strict('compile_recipe_options', frozenset(owned), records):
        if not isinstance(rows, list):
            raise ValueError('Recipe options must be a list')
        for row in rows:
            if (not isinstance(row, RecipeOption) or row.base_id not in owned or row.recipe_id not in owned
                    or row.base_id == row.recipe_id or not isinstance(row.effects, list) or not row.effects
                    or any(not isinstance(effect, dict) or not effect.get('type') for effect in row.effects)
                    or row.target_kind not in {'SELF', 'ANY_CREATURE', 'HOSTILE_ENTITY', 'ALLY_OR_SELF', 'CELL'}
                    or (row.area is not None and not isinstance(row.area, dict))):
                raise ValueError('A recipe option requires owned records, effects and a valid target')
            key = row.base_id, row.recipe_id
            if key in seen:
                raise ValueError('Duplicate recipe release')
            seen.add(key)
            result.append(copy.deepcopy(row))
    return sorted(result, key=lambda row: (row.base_id, row.recipe_id))


def compose_payment_variants(base, payments, apply_modifier):
    """A recipe's optional payment substitution can accompany another modifier.

    Each recipe variant selects at most one substitution and one other optional
    modifier. The compiler applies the full substitution after the other modifier:
    payment, effects/dice, range/reach, area, duration and economy. The chosen
    records are exported in typed.selected_modifiers for consumers. The callbacks
    return private data; neither a source variant nor its authority is mutated.
    """
    if not base['typed'].get('recipe_id'):
        return
    variants = list(base['variants'])
    substitutions = [v for v in variants if (v.get('_compose') or {}).get('modifier', {}).get('replace_cost')]
    for replacement in substitutions:
        part = replacement['_compose']
        for variant in variants:
            other = variant.get('_compose') or {}
            if not other or other['key'] == part['key'] or other['modifier'].get('replace_cost'):
                continue
            for way, costs, label in payments(part['modifier'], variant['costs']):
                changed = apply_modifier(variant, part)
                typed = changed['typed']
                typed['selected_modifiers'] = [typed['modifier'], replacement['typed']['modifier']]
                base['variants'].append({**variant, **changed,
                    'action_id': f"{variant['action_id']}+recipepay.{part['key']}.{way}",
                    'name': f"{variant['name']} + {part['name']}" + (f' ({label})' if way else ''),
                    'costs': [*costs, *part['spend']], 'typed': typed})
