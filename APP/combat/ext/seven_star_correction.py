"""Seven-Star Correction uses the native miss checkpoint and existing owned marks.

The compiled passive replaces the old unconditional modifier. Star/Star Mark are
the existing typed mark spellings; only marks placed by the attacker qualify.
No roll, damage, mark or resource generation is performed by this plug-in.
"""
from . import hook
from ..choice_checkpoints import dynamic_choice
from ..typed_executor import bears_mark

FEATURE = 'foundation.seven_star_sword_heart_v0_2B.seven_star_correction'
BLOCK = 'seven_star_correction'


@hook('compile_block')
def compile_correction(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'bonus': int(numbers['pb']) + int(numbers['key_mod']),
             'bonus_damage': int(numbers['pb'])}]


@hook('attack_miss_correction')
def correct(engine, actor, target, spec, roll, intent, total, armor_class):
    row = next((r for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ())
                if r.get('block') == BLOCK), None)
    if (row is None or not actor.active or not target.active
            or actor.resources.get(row['resource_id'], 0) < 1
            or not (bears_mark(target, actor.entity_id, 'Star Mark')
                    or bears_mark(target, actor.entity_id, 'Star'))):
        return None
    bonus = int(row['bonus'])
    if bonus <= 0 or total + bonus < armor_class:
        return None
    if actor.entity_id in (getattr(engine, 'typed_ask_reactors', ()) or ()):
        _, decision = dynamic_choice(engine, intent, f'CORRECT_ATTACK:{roll.roll_id}',
            actor.entity_id, 'choice:seven_star_correction',
            {'actor_id': actor.entity_id, 'target_id': target.entity_id,
             'name': 'Seven-Star Correction', 'feature_id': FEATURE,
             'prompt': f"{actor.display_name}'s {spec['attack_name']} missed {target.display_name}, "
                       f"your Marked Star (the enemy you marked). Spend 1 Star Intent, with no action "
                       f"or Reaction, to add +{bonus} to this roll and +{row['bonus_damage']} damage if it hits?",
             'labels': {'correct': 'Spend 1 Star Intent to correct this attack'}},
            spec_override={'option_ids': ['correct'], 'automatic_use': True})
        if decision is None or decision.selection != 'USE':
            return None
    engine._spend_resource(actor, row['resource_id'], 1, f'passive:{FEATURE}')
    return {'source_id': f'passive:{FEATURE}', 'label': 'Seven-Star Correction (1 Star Intent; no action)',
            'bonus': bonus, 'bonus_damage': int(row['bonus_damage'])}
