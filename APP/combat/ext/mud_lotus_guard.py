"""Mud-Lotus Guard's owned HP and measurable-harm consumers.

Only the native packet's poison/acid type is sufficient here. Necrotic damage
does not establish rot, nor does a sphere name establish a treatment scene.
Other categories use current source-bound recovery declarations. This module
also owns measurable-harm Guard, sharing one signed reduction calculation.
The generic HP reaction
owns range, consent, costs and settlement;
prior_event_resources owns the shared same-event payment restriction.
"""
from . import hook
from ..recovery_sources import source_procedure_profile

GUARD = 'foundation.mud_lotus_dantian_v0_2A.mud_lotus_guard'


def _reduction(row, kind, bonus=0):
    numbers = row['numbers']
    pb = int(numbers['pb'])
    # One signed sum: a negative Path modifier reduces the printed amount.
    return max(0, pb + int(numbers['key_mod']) + (pb if kind == 'poison' else 0) + bonus)


@hook('damage_context_pending_reaction_rank')
def guard_damage(engine, reactor, row, packet, intent):
    """Pure, owned quote before native ranking, consent and payment."""
    if row.get('feature_id') != GUARD:
        return None
    kind = packet.damage_type.lower()
    from .mud_lotus_native import SCOPED, EXTRA_GUARD, scene, refined_bonus, environmental_source
    source_actor = engine.state.actors.get(packet.source_actor_id)
    if (source_procedure_profile(engine, source_actor, packet.source_id) or {}).get('hostility') == 'benign':
        return {'allowed': False}
    fact = scene(engine, source_actor, packet.source_id, packet.target_id) if source_actor else None
    categories = set(fact.categories) if fact else set()
    hostile = packet.hostile or source_actor is not None and environmental_source(engine, source_actor, packet.source_id, packet.target_id, hostile=True)
    if packet.pressure_kind != 'damage' or not hostile or (kind not in {'poison', 'acid'} and not categories & SCOPED):
        return {'allowed': False}
    value = _reduction(row, 'poison' if kind == 'poison' or categories & EXTRA_GUARD else kind,
                       refined_bonus(engine, reactor, packet.source_id, packet.target_id))
    return {'reduction_bonus': value}


@hook('measurable_harm_pending')
def guard_harm(ctx, subject, amount, categories):
    from .mud_lotus_native import (SCOPED, EXTRA_GUARD, scene, environmental_source,
        ownership, DEW, choose, refined_bonus)
    from ..relations import relation, ALLY, ENEMY
    if (source_procedure_profile(ctx.engine, ctx.actor, ctx.source) or {}).get('hostility') == 'benign':
        return None
    fact = scene(ctx.engine, ctx.actor, ctx.source, subject.entity_id)
    hostile = relation(ctx.engine, ctx.actor, subject) == ENEMY or environmental_source(ctx.engine, ctx.actor, ctx.source, subject.entity_id, hostile=True)
    if fact is None or not hostile or not set(categories) & SCOPED:
        return None
    from ..typed_reactions import _can_react
    for owner in ctx.engine.state.actors.values():
        row = ownership(ctx.engine, owner, GUARD)
        if not row or relation(ctx.engine, owner, subject) != ALLY or ctx.engine._distance_actor_to_actor(owner, subject) > 30:
            continue
        if owner.resources.get(DEW, 0) < 1 or not _can_react(ctx.engine, owner):
            continue
        reduction = _reduction({'numbers': row}, 'poison' if set(categories) & EXTRA_GUARD else 'other',
                               refined_bonus(ctx.engine, owner, ctx.source, subject.entity_id))
        consequence = (ctx.action.parameters.get('source_procedure') or {}).get('consequence') or {}
        protected = consequence.get('classification') == 'major' and (
            consequence.get('kind') in {'curse', 'hidden_injury', 'deviation'}
            or consequence.get('category') == 'disease')
        if protected:
            # The declared positive source ladder may be reduced, but Guard
            # alone never removes a major disease, curse, injury or Deviation.
            reduction = min(reduction, max(0, amount - 1))
        if choose(ctx.engine, owner, GUARD, 'Mud-Lotus Guard',
                f"Reduce {ctx.action.display_name}'s measurable harm to {subject.display_name} by {reduction}; "
                'costs your Reaction and 1 Lotus Dew from an earlier event. Major injuries are not cleansed.', subject,
                automatic_options=['use'] if reduction > 0 else []):
            ctx.engine._spend_resource(owner, DEW, 1, GUARD)
            owner.reaction_available = False
            ctx.engine._append_event('REACTION_RESOLVED', GUARD, actor_id=owner.entity_id,
                target_ids=(subject.entity_id,), payload={'reduction': reduction, 'checkpoint': 'MEASURABLE_HARM'})
            return reduction


@hook('decision_text')
def guard_text(engine, context, printed_rules):
    """Describe the owned quote without guessing a hidden source category."""
    if context.get('reaction_source_id') != 'reaction:typed.' + GUARD:
        return None
    row = next((r for r in engine.typed_reaction_rows.get(context.get('reactor_id'), [])
                if r.get('feature_id') == GUARD), None)
    if row is None:
        return None
    trigger = context.get('choice_trigger') or {}
    target = engine.state.actors.get(trigger.get('target_id'))
    name = target.display_name if target else 'the affected creature'
    return {
        'summary': f'Mud-Lotus Guard protects {name} against the triggering damage: '
                   f'reduce Poison damage by {_reduction(row, "poison")} or Acid damage by {_reduction(row, "acid")}.',
        'cost': 'Your Reaction and 1 Lotus Dew from an earlier event.',
        'limits': 'One creature within 30 feet; only this damage. This does not cleanse a disease, curse, or major injury.',
        'table_note': 'Declining spends nothing. Other harm requires its actual source to be established by the person running the game.',
    }
