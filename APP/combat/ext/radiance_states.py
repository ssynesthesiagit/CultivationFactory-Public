"""Timed Radiance halos and their source-aware Unclean clauses."""
from dataclasses import replace
from . import effect, hook, note
from .creature_kinds import is_unclean
from .placed import context
from .. import typed_executor

STATE = 'condition:typed.radiance_state'
STRIKE = 'RADIANCE_BASE_STRIKE'
PURIFY = 'tianxia.talent.radiance.purifying_radiance'
HEAVENLY = 'tianxia.talent.radiance.heavenly_radiance'
HEAVENLY_FORM = 'condition:typed.radiance_heavenly_flight'  # the typed condition its 1-minute form runs on


def states(actor, kind):
    return [c for c in actor.conditions.values() if c.condition_id == STATE and c.data.get('kind') == kind]


def turn_key(engine):
    current = engine.state.actors[engine.state.current_actor_id]
    return [engine.state.round_number, current.entity_id, current.turns_started]


@hook('compile_actions')
def burning_purification(info):
    if PURIFY not in info['owned_ids']:
        return None
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    count = 8 if info['numbers']['cl'] >= 17 else 6 if info['numbers']['cl'] >= 11 else 4
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.burning_purification",
        display_name='Burning Purification', owner_id=info['actor_id'], economy=EconomyKind.ACTION,
        resolution_kind='TYPED', target_kind='HOSTILE_ENTITY', range_ft=5,
        costs=((RESOURCE_IDS[info['primary']], 3),), parameters={'expected_damage': count * 9 // 2,
            'description': f'Melee Cultivation Attack against an Unclean creature: {count}d8 Radiant damage; '
                           'on a hit, its attacks have Disadvantage until your next turn starts.',
            'typed': {'source': PURIFY, 'requires_kind': 'Unclean', 'numbers': info['numbers'],
                'duration': {'kind': 'instant'}, 'riders': [], 'effects': [{
                    'type': 'attack', 'attack_kind': 'cultivation_melee', 'count': 1,
                    'on_hit': [{'type': 'damage', 'applies_to': 'target', 'damage_types': ['RADIANT'],
                                'dice': {'count': count, 'sides': 8}}, {'type': 'burning_purification'}]}]}})]


@hook('recipient_allowed')
def burning_target(engine, actor, target, action):
    if action.parameters.get('typed', {}).get('requires_kind') == 'Unclean':
        return is_unclean(target)
    return None


@effect('burning_purification')
def burning_hit(ctx, eff):
    for target in ctx.targets:
        ctx.engine._apply_condition(target, 'condition:typed.burning_purification', ctx.source, ctx.actor.entity_id,
            expires_on='START_OF_SOURCE_NEXT_TURN', data={'rule': {'attacks_have': 'DISADVANTAGE'},
                'label': 'Burning Purification: attacks have Disadvantage until the caster’s next turn'})


def once(engine, actor, key):
    now = turn_key(engine)
    if actor.turn_flags.get(key) == now:
        return False
    actor.turn_flags[key] = now
    return True


@effect('radiance_state')
def apply_state(ctx, eff):
    subjects = [ctx.actor] if eff.get('applies_to') == 'self' else (
        [ctx.target] if ctx.target is not None else list(ctx.targets) or
        ([ctx.actor] if ctx.action.target_kind in ('SELF', 'ALLY_OR_SELF') else []))
    # Only one maintained Merciful Halo per caster. End all effects of its old
    # activation, including its native resistance/save modifiers, before replacing it.
    if eff['kind'] == 'merciful_halo':
        for target in ctx.engine.state.actors.values():
            for old in list(states(target, 'merciful_halo')):
                if old.source_actor_id != ctx.actor.entity_id:
                    continue
                for iid, c in list(target.conditions.items()):
                    if c.source_definition_id == old.source_definition_id and c.source_actor_id == ctx.actor.entity_id:
                        del target.conditions[iid]
                        ctx.engine._append_event('CONDITION_REMOVED', ctx.source, actor_id=ctx.actor.entity_id,
                            target_ids=(target.entity_id,), payload={'instance_id': iid, 'condition_id': c.condition_id})
                for mid, m in list(target.modifiers.items()):
                    if m.source_definition_id == old.source_definition_id and m.source_actor_id == ctx.actor.entity_id:
                        del target.modifiers[mid]
                        ctx.engine._append_event('MODIFIER_REMOVED', ctx.source, actor_id=ctx.actor.entity_id,
                            target_ids=(target.entity_id,), payload={'modifier_id': mid})
    for subject in subjects:
        ctx.engine._apply_condition(subject, STATE, ctx.source, ctx.actor.entity_id,
            expires_on=typed_executor.effect_expiry(ctx, eff, subject, condition=True),
            data={'kind': eff['kind'], 'numbers': dict(ctx.numbers), 'label': eff['label']})


@hook('save_mode')
def halo_fear_save(engine, subject, ability, dc, source_id, context):
    source = engine.state.actors.get(context.get('source_actor_id'))
    if states(subject, 'searing_halo') and is_unclean(source) and 'frightened' in {str(n).lower() for n in context.get('named') or ()}:
        return 'ADVANTAGE'
    return None


@hook('final_damage')
def merciful_halo_damage(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    if not is_unclean(engine.state.actors.get(source_actor_id)):
        return None
    bonuses = [int(c.data['numbers'].get('pb') or 0) for c in states(target, 'merciful_halo')]
    if bonuses:
        return {'amount': max(0, amount - max(bonuses))}
    return None


@hook('save_final')
def crown_failed_save(ctx, subject, ability, named, failed):
    source = str(ctx.typed.get('source') or ctx.source)
    if not failed or not is_unclean(subject) or 'radiance' not in source.lower():
        return
    if states(ctx.actor, 'crown'):
        typed_executor.run_effects(replace(ctx, targets=[subject], target=subject), [
            {'type': 'reaction_denied', 'applies_to': 'target', 'expires_on': 'START_OF_TARGET_NEXT_TURN',
             'evidence': 'Crown of the Unblinking Sun: an Unclean creature failed a save against your Radiance'}])


@hook('hit_final')
def halo_hit(ctx, target, kind):
    engine, owner = ctx.engine, ctx.actor
    attack = ctx.attack_damage_context
    if attack is None:
        return
    # Retaliation is tied to an actual hit, not to damage amount or a recent log scan.
    receipt = ctx.hit_snapshots.get('radiance_states') or {}
    for held in receipt.get('retaliations') or []:
        flat = held['kind'] == 'searing_halo'
        sub = context(engine, target, held['source'], held['numbers'], [owner])
        typed_executor.run_effects(sub, [{'type': 'damage', 'applies_to': 'target', 'damage_types': ['RADIANT'],
            **({'formula': 'pb'} if flat else {'dice': {'count': 2, 'sides': 6}})}])
    if ctx.typed.get('source') != STRIKE:
        return
    for name in ['searing_halo', 'solar_form']:
        held = [c for c in receipt.get('strikes') or [] if c['kind'] == name]
        if not held:
            continue
        c = held[-1]
        sub = replace(context(engine, owner, c['source'], c['numbers'], [target], action=ctx.action),
                      attack_damage_context=attack)
        if name == 'solar_form' or once(engine, owner, 'searing_halo_hit_turn'):
            note(engine, c['source'], owner, f'{ctx.action.display_name}: the halo adds 1d8 Radiant damage.')
            if target.active and target.current_hp > 0:
                typed_executor.run_effects(sub, [{'type': 'damage', 'applies_to': 'target', 'damage_types': ['RADIANT'],
                                                  'dice': {'count': 2 if attack.critical else 1, 'sides': 8}}])
        if name == 'solar_form' and target.active and once(engine, owner, 'solar_radiance_save_turn'):
            typed_executor.run_effects(sub, [{'type': 'save', 'ability': 'con', 'applies_to': 'target',
                'disadvantage_if_kind': ['Unclean'],
                'on_fail': [{'type': 'condition', 'condition': 'blinded', 'applies_to': 'target',
                             'expires_on': 'START_OF_SOURCE_NEXT_TURN'}],
                'on_success': [{'type': 'reaction_denied', 'applies_to': 'target',
                                'expires_on': 'START_OF_SOURCE_NEXT_TURN'}]}])


@hook('hit_snapshot')
def halo_snapshot(engine, actor, target, attack_context, intent):
    from .radiance import legacy_strike_states
    spec = (engine.d20_context() or {}).get('spec') or {}
    action = engine.action_catalog.get(attack_context.source_id)
    melee = spec.get('reach_ft') is not None if spec else action is not None and action.reach_ft is not None
    rows = []
    if melee:
        distance = engine._distance_actor_to_actor(actor, target)
        for name, reach in [('searing_halo', 5), ('solar_form', 10)]:
            for held in states(target, name)[-1:]:
                if distance <= reach:
                    rows.append({'kind': name, 'source': held.source_definition_id, 'numbers': dict(held.data['numbers'])})
    strikes = [{'kind': name, 'source': c.source_definition_id, 'numbers': dict(c.data['numbers'])}
               for name in ['searing_halo', 'solar_form'] for c in states(actor, name)[-1:]]
    strikes.extend(legacy_strike_states(engine, actor))
    return {'radiance_states': {'retaliations': rows, 'strikes': strikes}} if rows or strikes else None


# ------------------------------------------------------------------------------------------------ Heavenly Radiance's price
PRICED = '_round_radiance_form_priced:'  # a "_round_" key, so the once-per-form guard outlives the turn it was written in


def _half_or_more_ends_it(engine, holder):
    """"unless you ended the encounter with at least half your maximum CP remaining", as two tests the table can
    actually make: the encounter has to be over (the printed words are about ending it), and the reserve has to be
    at least half of the maximum. Half of an odd maximum is compared by doubling, so 50 of 101 is below half
    (``maximum // 2`` would call it half)."""
    receipt = holder.turn_flags.get('_round_radiance_encounter_end')
    if not isinstance(receipt, dict):
        return False, 'the encounter has not ended while this transformation was active'
    current, maximum = int(receipt['current']), int(receipt['maximum'])
    return maximum > 0 and 2 * current >= maximum, f'{current} of {maximum} maximum CP'


def heavenly_form_end(engine, holder, instance_id, why):
    """One printed level of Exhaustion when Heavenly Radiance's transformation ends, and only then.

    Priced once per form instance, so both ways the transformation can end -- the printed 1-minute clock and an
    effect that ends it early -- are heard without paying twice. Nothing is done for a creature that is not the
    one in the form, and the flag lives on that creature's own record."""
    key = PRICED + str(instance_id)
    if holder.turn_flags.get(key):
        return
    holder.turn_flags[key] = 1
    receipt = holder.turn_flags.get('_round_radiance_encounter_end')
    if isinstance(receipt, dict) and receipt.get('instance') != str(instance_id):
        holder.turn_flags.pop('_round_radiance_encounter_end', None)
    exempt, because = _half_or_more_ends_it(engine, holder)
    if exempt:
        note(engine, HEAVENLY, holder, f'Heavenly Radiance: {why}, and you kept at least half your maximum CP '
             f'({because}) to the end of the encounter, so you gain no Exhaustion.')
        return
    from . import forged_exhaustion
    forged_exhaustion.add(engine, holder, 1, HEAVENLY)
    note(engine, HEAVENLY, holder, f'Heavenly Radiance: {why}'
         + (f' and {because}' if because else '') + ', so you gain 1 level of Exhaustion.')


@hook('effect_expiring')
def heavenly_form_minute_ends(engine, holder, row):
    """The printed form's own 1-minute clock reaching zero is "the transformation ends". This lifecycle hook is
    what receives that: the timed sweep announces a due condition here, before it takes it off."""
    if getattr(row, 'condition_id', None) == HEAVENLY_FORM:
        heavenly_form_end(engine, holder, getattr(row, 'instance_id', None), 'the minute runs out')


@hook('event', nested=True)
def heavenly_form_removed(engine, event_type, kwargs):
    """The form condition leaving the creature by any other route (an effect that ends it) is the same ending."""
    if event_type == 'MATCH_ENDED':
        from .rider_support import cp_pool
        for holder in engine.state.actors.values():
            for condition in holder.conditions.values():
                if condition.condition_id != HEAVENLY_FORM:
                    continue
                pool = cp_pool(holder)
                holder.turn_flags['_round_radiance_encounter_end'] = {
                    'instance': str(condition.instance_id),
                    'current': int(holder.resources.get(pool, 0)),
                    'maximum': int(holder.resource_maximums.get(pool, 0)),
                }
        return
    if event_type != 'CONDITION_REMOVED' or (kwargs.get('payload') or {}).get('condition_id') != HEAVENLY_FORM:
        return
    for entity_id in kwargs.get('target_ids') or ():
        holder = engine.state.actors.get(entity_id)
        if holder is not None and holder.active:
            heavenly_form_end(engine, holder, (kwargs.get('payload') or {}).get('instance_id'), 'the transformation ends early')
