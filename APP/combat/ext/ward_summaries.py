"""Petal Ward and Ash Ward amounts in plain table decision text.

Pure presentation: read the owned compiled reduction row and its current
numbers; never roll dice, spend resources or alter saved fights. The shared
Markdown renderer is maintained by FIX18, not duplicated here.
"""
from typing import Any

from factory_authoring.typed_mechanics import dice_for_cl
from . import hook

PETAL = 'TAL_FLOWERS_PETAL_WARD'
ASH = 'tianxia.talent.ash.ash_ward'


@hook('decision_text')
def ward_amounts(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, str] | None:
    feature = str(context.get('reaction_source_id') or '').removeprefix('reaction:typed.')
    if feature not in (PETAL, ASH):
        return None
    row = next((r for r in getattr(engine, 'typed_reaction_rows', {}).get(context.get('reactor_id'), [])
                if r.get('feature_id') == feature), None)
    if row is None:
        return None
    reduction = next((e for e in row.get('effects') or [] if e.get('type') == 'damage_modifier'), None)
    if reduction is None or reduction.get('formula') != 'key_ability_modifier':
        return None
    numbers = row.get('numbers') or {}
    dice = dice_for_cl(reduction.get('dice_by_cl'), numbers.get('cl')) or reduction.get('dice')
    if not isinstance(dice, dict) or not dice.get('count') or not dice.get('sides'):
        return None
    modifier = int(numbers.get('key_mod') or 0)
    amount = f"{dice['count']}d{dice['sides']} {'+' if modifier >= 0 else '-'} {abs(modifier)}"
    summary = f'Reduce the triggering damage to you or an ally within 30 feet by {amount} (including your Path key ability modifier). '
    if feature == PETAL:
        summary += 'The protected creature also gains Advantage on its next saving throw against Poison before the start of your next turn.'
    else:
        summary += (f"Add {int(numbers.get('pb') or 0)} (your Proficiency Bonus) to the reduction if the protected creature stands "
                    'inside Ash Terrain, Smoke, or a Fire effect. This protects against this damage only.')
    return {'summary': summary}
