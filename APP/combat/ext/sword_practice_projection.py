"""Sword Qi Wave's printed damage-type choice, before each attack roll.

The existing reviewed attack owns damage, range, cost and Intent. This module
adds only its missing declaration choice through attack_damage_type_choice,
documented in ext/__init__.py. It does not grant a Practice or infer a Body
Refiner's projection permission. Other Sword rows retain their own providers.
"""
from typing import Any

from . import hook
from .choice_prompt import action_context
from .needle import CHOICE, ask, checkpoint_id

WAVE = 'SWORD_BASE_SWORD_BEYOND_HAND'


@hook('attack_damage_type_choice')
def wave_damage_type(ctx: Any, attack: dict, target: Any,
                     kinds: list[str], attack_index: int) -> str | None:
    """Ask this owned wave's caster; automatic seats use printed order.

    The automatic preference reads only the owner's available damage types,
    never target defenses, traits, or another creature's private knowledge.
    Native choice transport handles manual/Ask-me and automatic owners on
    either side of a turn boundary, and journals the accepted declaration.
    """
    source = ctx.typed.get('option_of') or ctx.typed.get('source')
    if (source != WAVE or ctx.action.owner_id != ctx.actor.entity_id
            or target is None or len(kinds) < 2):
        return None
    picked = ask(
        ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, 'sword_qi_wave_type', ctx.actor.entity_id,
                      target.entity_id, attack_index),
        ctx.actor, CHOICE + 'sword_qi_wave_type', list(kinds),
        labels={kind: f'{kind.title()} damage' for kind in kinds},
        preferred=[kinds[0]], target_id=target.entity_id,
        name='Sword Qi Wave', feature_id=WAVE,
        prompt=f'Sword Qi Wave: choose the damage type of '
               f'{ctx.action.display_name} against {target.display_name}. '
               'Choosing the type costs nothing. Only the damage type changes; '
               'a hit also marks this creature for your Sword techniques '
               '(Sword Intent) until the start of your next turn.',
        prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target),
    )
    return picked[0] if picked else kinds[0]
