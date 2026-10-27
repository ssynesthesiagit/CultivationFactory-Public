"""Returning Source Guard's paid, source-bound next maintenance roll.

The native pending packet is the admission receipt. Native Concentration saves
identify their purpose through SYSTEM_CONCENTRATION; other callers must supply
explicit hazards, never an action-name or sphere guess. Queries are pure and
the finalized d20 consumes the allowance even when opposing modes cancel.
"""
from . import hook
from .effect_durations import token

GUARD = 'foundation.origin_spirit_body_v0_2B.returning_source_guard'
DEW = 'resource:foundation.spirit_source_dew'
CONDITION = 'condition:typed.returning_source_guard'
MAINTENANCE = frozenset({'maintain:concentration', 'maintain:technique_rhythm',
                         'maintain:manifestation', 'maintain:formation',
                         'maintain:spiritual_control'})


def allowances(subject):
    """Every independently paid donor/source promise; modes still union once."""
    return [c for c in subject.conditions.values() if c.condition_id == CONDITION]


def allowance(subject):
    """First allowance for callers displaying a single-condition receipt."""
    return next(iter(allowances(subject)), None)


@hook('reaction_geometry_allowed')
def admission(engine, reactor, source, subject, row):
    if row.get('feature_id') != GUARD:
        return None
    from ..pending_damage import current
    from ..senses import perceives
    packet = current(engine)
    if packet is None or packet.target_id != subject.entity_id:
        return False
    # The third trigger admits damage that threatens a maintained technique,
    # even when that damage is not hostile. Do not invent maintenance for a
    # character without an actual native Concentration state.
    return bool((packet.hostile or subject.concentration is not None) and packet.amount > 0
                and reactor.team_id == subject.team_id
                and engine._distance_actor_to_actor(reactor, subject) <= 30
                and (reactor is subject or perceives(engine, reactor, subject, sight_only=True)))


def eligible(condition, kind, ability, source_id, source_actor_id, hazards):
    """Match explicit maintenance purpose or the exact protected pressure source."""
    if kind not in {'save', 'check'}:
        return False
    if kind == 'save' and str(ability).upper() != 'CON':
        return False
    tags = {str(tag).removeprefix('pressure:').removeprefix('category:')
            for tag in hazards or ()}
    if (kind == 'save' and str(ability).upper() == 'CON'
            and source_id == 'system:combat.concentration'):
        return True
    if tags & MAINTENANCE:
        return True
    data = condition.data or {}
    return bool(tags & {'backlash', 'drain'}
                and source_id == data.get('pressure_source_id')
                and source_actor_id == data.get('pressure_actor_id'))


@hook('event', nested=True)
def grant(engine, event_type, kwargs):
    if event_type != 'REACTION_RESOLVED' or kwargs.get('source_definition_id') != GUARD:
        return
    from ..pending_damage import current
    packet = current(engine)
    owner = engine.state.actors.get(kwargs.get('actor_id'))
    subject = engine.state.actors.get((kwargs.get('payload') or {}).get('protects'))
    if owner is None or subject is None or subject is owner or packet is None:
        return
    engine._apply_condition(subject, CONDITION, GUARD, owner.entity_id,
        expires_on=token('start', owner.entity_id, owner.turns_started + 1),
        data={'pressure_source_id': packet.source_id,
              'pressure_actor_id': packet.source_actor_id or '',
              'pressure_kind': packet.pressure_kind,
              'temporary_benefit': 1,
              'label': f'Returning Source Guard: Advantage on your next Constitution saving throw or eligible check to maintain a technique or resist this source of backlash or drain; expires at the start of {owner.display_name}\'s next turn.'})


@hook('save_mode')
def save_advantage(engine, subject, ability, dc, source_id, context):
    if any(eligible(c, 'save', ability, source_id, context.get('source_actor_id'),
                    context.get('named')) for c in allowances(subject)):
        return 'ADVANTAGE'
    return None


@hook('save_roll_tags')
def pressure_save_tags(ctx, subject, ability, named):
    if allowance(subject):
        return sorted(named)
    return None


@hook('contest_check_mode')
def contest_advantage(ctx, subject, opponent, spec):
    if any(eligible(c, 'check', spec.get('ability'), ctx.source, ctx.actor.entity_id,
                    spec.get('hazards')) for c in allowances(subject)):
        return 'ADVANTAGE'
    return None


@hook('ability_check_hazard_mode')
def check_advantage(engine, actor, ability, skill, against, hazards):
    if allowances(actor) and set(hazards or ()) & MAINTENANCE:
        return 'ADVANTAGE'
    return None


@hook('support_roll_sources')
def support_sources(engine, subject, context):
    """Publish the paid grant before its native finalized-roll consumption.

    Only represented Concentration, rhythm or same-source pressure qualifies
    as scalar support. Other maintenance checks retain Guard's own benefit.
    """
    from ..support_values import SupportRollSource
    hazards = [*(context.get('named') or ()), *(context.get('hazards') or ())]
    tags = {str(tag).removeprefix('pressure:').removeprefix('category:') for tag in hazards}
    if (context.get('source_id') == 'system:combat.concentration'
            or 'maintain:concentration' in tags):
        purpose = 'concentration'
    elif 'maintain:technique_rhythm' in tags:
        purpose = 'rhythm'
    else:
        purpose = next((kind for kind in ('backlash', 'drain') if kind in tags), None)
    if purpose is None:
        return None
    return [SupportRollSource(c.source_actor_id, c.source_definition_id, purpose)
            for c in allowances(subject)
            if eligible(c, context.get('kind'), context.get('ability'),
                        context.get('source_id'), context.get('source_actor_id'), hazards)]


@hook('d20_finalized')
def consume(engine, roll, intent):
    subject = engine.state.actors.get(roll.actor_id)
    if subject is None:
        return
    context = engine.d20_context(roll) or {}
    for condition in allowances(subject):
        if eligible(condition, context.get('kind'), context.get('ability'),
                    context.get('source_id'), context.get('source_actor_id'),
                    [*(context.get('named') or ()), *(context.get('hazards') or ())]):
            engine._remove_condition_instance(subject, condition.instance_id, GUARD, expected=condition)
    # Suppression hides the benefit rather than postponing its printed next
    # eligible roll. Use the public stored-condition consumption transport.
    from types import SimpleNamespace
    from .benefit_suppression import SUPPRESSED
    for held in tuple(subject.conditions.values()):
        data = held.data or {}
        model = data.get('model') or {}
        if (held.condition_id == SUPPRESSED and data.get('kind') == 'condition'
                and model.get('condition_id') == CONDITION
                and eligible(SimpleNamespace(data=model.get('data') or {}),
                             context.get('kind'), context.get('ability'),
                             context.get('source_id'), context.get('source_actor_id'),
                             [*(context.get('named') or ()), *(context.get('hazards') or ())])):
            # Another donor may protect a different source or expire later.
            engine._remove_condition_instance(subject, held.instance_id, GUARD, expected=held)
