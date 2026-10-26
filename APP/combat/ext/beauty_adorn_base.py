"""Shared helper module: combat/ext/beauty_adorn.py uses aura_choices and willing_delivery.

Adorn's printed aura choice and creature recipient delivery.

Shared public helper: consumed by beauty_adorn.py. Its exported functions are
the stable cross-plugin API; private helpers stay private.

Uses compile_action/compile_actions, choose_willing and the ordinary condition
clock. The existing check and memory effects remain their original providers;
their scene/check/observer semantics are not certified by this module. Aura
presentation never grants a combat modifier or invents a social circumstance.
"""
from . import effect, hook

ADORN = 'BEAUTY_BASE_ADORN_THE_MOMENT'
AURA = 'condition:typed.adorn_aura'
TONES = ('soft', 'graceful', 'haunting', 'radiant', 'refined', 'tragic', 'elegant', 'terrible')


def is_adorn(source):
    """Identify this base row's compiled options, including its existing riders."""
    return ADORN in str(source).split('+')[0].split('#')[0]


def replace_use(ctx, subject):
    """Remove only previous Adorn benefits on this creature, from any caster."""
    for held in list(subject.conditions.values()):
        if held.condition_id == AURA or is_adorn(held.source_definition_id):
            ctx.engine._remove_condition(subject, held.condition_id, held.source_definition_id)


def willing_delivery(rows, range_ft):
    """Base Adorn and Shared Spotlight: replace only after this recipient consents."""
    return {'type': 'choose_willing', 'range_ft': range_ft, 'target_only': True,
            'consent_text': 'Adorn the Moment replaces your previous adornment and lasts up to 1 minute; 0 CP.',
            'effects': [{'type': 'adorn_replace'}, *rows]}


@hook('compile_action')
def creature_delivery(action, info):
    if ADORN not in info['owned_ids']:
        return None
    typed = (action.parameters or {}).get('typed') or {}
    # Shared Spotlight owns its own multi-recipient delivery. Do not replace it
    # with a single-recipient wrapper or add a second copy of that talent.
    if typed.get('option_of') != ADORN or action.parameters.get('shared_spotlight'):
        return None
    rows = list(typed.get('effects') or [])
    return action.model_copy(update={
        'target_kind': 'ANY_CREATURE', 'range_ft': 5,
        'parameters': {**action.parameters, 'typed': {**typed, 'range_ft': 5,
            'manual_inline_choice': True,
            'effects': [willing_delivery(rows, 5)]}}})


@hook('compile_actions')
def aura_choices(info):
    """Public raw aura actions, shared with Beauty's existing Spotlight provider.

    compile_actions hooks see the original catalog, not sibling hook outputs.
    The later compile_action pass supplies ordinary single-recipient delivery.
    """
    if ADORN not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..action_variants import choice, with_variant
    return [with_variant(ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.{ADORN}#aura_{tone}",
        display_name=f'Adorn the Moment: {tone.title()} aura', owner_id=info['actor_id'],
        economy=EconomyKind.BONUS_ACTION, resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=5,
        parameters={'expected_damage': 0,
            'description': f'Bonus Action, 0 CP: give yourself or one willing creature within touch a {tone} aura for 1 minute. '
                           'Replaces its previous Adorn the Moment. No direct combat effect; social possibilities depend on the actual scene.',
            'typed': {'source': ADORN, 'option_of': ADORN, 'option_label': f'{tone.title()} aura',
                'manual_inline_choice': True, 'numbers': info['numbers'],
                'duration': {'kind': 'minutes', 'amount': 1}, 'riders': [],
                'effects': [{'type': 'adorn_aura', 'tone': tone}]}}),
        f"action:typed.{info['short']}.{ADORN}", 'Adorn the Moment',
        [choice('aura', tone, f'{tone.title()} aura')])
        for tone in TONES]


@effect('adorn_replace', harmful=False)
def clear_previous(ctx, row):
    replace_use(ctx, ctx.target or ctx.actor)


@effect('adorn_self', harmful=False)
def self_delivery(ctx, row):
    """Shared Spotlight's caster receives the same public recipient delivery."""
    from dataclasses import replace
    from ..typed_executor import run_effects
    run_effects(replace(ctx, target=ctx.actor, targets=[ctx.actor]),
                [willing_delivery(row['effects'], 0)])


@effect('adorn_aura', harmful=False)
def aura(ctx, row):
    from ..typed_executor import effect_expiry
    subject = ctx.target or ctx.actor
    ctx.engine._apply_condition(subject, AURA, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, subject, condition=True),
        data={'tone': row['tone'], 'label': f"Adorn the Moment: {row['tone']} aura (1 minute; no direct combat effect)"})
