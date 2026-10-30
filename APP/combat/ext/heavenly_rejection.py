"""Heavenly Body's Rejection and selected Marrow, using native save receipts.

No resource producer or body provenance is invented here. Pending typed save
conditions/categories come from typed_executor; unknown effects stay unknown.
Vessel shares foundation_round_vessel with Guard and Strike.
"""
from . import hook, note
from .passive_rows import row_of
from .foundation_combat import feature, pool, held, roll_names
from .needle import ask, checkpoint_id, CHOICE
from .choice_costs import Payment
from ..save_adjustments import payable, declared_outcome
from ..feature_availability import available
from .heavenly_integrity_vessel import vessel_ready, settle_vessel_bonus

BLOCK = 'heavenly_rejection'
REJECTION = feature('integrity', 'integrity_rejection')
MARROW = feature('integrity', 'heaven_rejecting_marrow')
# Only explicit bodily consequences, not mental possession or generic control.
BODY = {'poison', 'poisoned', 'disease', 'sickened', 'exhaustion', 'exhausted',
        'body_corruption', 'bodily_corruption', 'body_seizure', 'forced_transformation',
        'mutation', 'internal_disruption'}


@hook('compile_block')
def compile_rejection(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'kind': spec['kind'], 'pb': int(numbers.get('pb') or 2)}]
    return None


@hook('choice_reactors')
def reactors(engine):
    return tuple(aid for aid in engine.state.actors
                 if row_of(engine, aid, BLOCK, 'rejection'))


@hook('save_roll_adjustment')
def rejection(engine, target, ability, dc, roll, source_id, phase, context):
    row = row_of(engine, target.entity_id, BLOCK, 'rejection')
    if row is None or context.get('automatic_failure') or not available(engine, target, REJECTION):
        return None
    # Natural death-save outcomes stay immutable, but the printed resource
    # conversion remains a legal player choice. Automatic seats conserve it.
    immutable_death = ability == 'DEATH' and roll.natural_result in (1, 20)
    source = engine.state.actors.get(context.get('source_actor_id'))
    from ..relations import relation, ENEMY
    from .heavenly_body_source import bodily_source
    bodily = bool(roll_names(context.get('named')) & BODY) or bodily_source(
        engine, target, context.get('source_actor_id'), source_id)
    if ability not in {'CON', 'DEATH'} and not (
            source and relation(engine, source, target) == ENEMY and bodily):
        return None
    resource = pool('integrity')
    if not payable(engine, target, resource, 1, source_id=REJECTION):
        return None
    marrow = row_of(engine, target.entity_id, BLOCK, 'marrow')
    selected = held(target, 'expression')
    improved = bool(marrow and available(engine, target, MARROW) and selected and selected.data.get('feature') == MARROW)
    if phase not in ({'before_outcome', 'after_failure'} if improved else {'before_outcome'}):
        return None
    declared = declared_outcome(engine, target, roll)
    # A fixed success gives Marrow nothing to answer; declining is the same no-op.
    waiting = improved and phase == 'before_outcome' and declared != 'success'
    pb = int(row['pb'])
    vessel = vessel_ready(engine, target)
    bonus = pb * (2 if vessel else 1)
    # A default preference is not a legality filter. Before the outcome is
    # announced, use only the saver's own visible die: conserve on a high roll,
    # consider spending on a low one. Marrow can answer an announced failure.
    # Do not peek at the opposing DC, or remove legal choices from model seats.
    # A forced outcome (another provider) overrides the total, so spending cannot
    # change it: no automatic spend, but the printed option stays available.
    prefer_use = not immutable_death and declared is None and (phase == 'after_failure' or (
        roll.natural_result is not None and roll.natural_result < 10))
    intent = getattr(engine, '_active_intent', None)
    action = engine.action_catalog.get(source_id)
    action_name = action.display_name if action else ('Death saving throw' if ability == 'DEATH' else 'Saving throw')
    name = 'Integrity Rejection' + (' — Heaven-Rejecting Marrow' if improved else '')
    if improved and not waiting and declared != 'success':
        note(engine, source_id, target,
             f'{target.display_name} fails the saving throw against {action_name}; '
             'Heaven-Rejecting Marrow may answer before consequences.', (target,),
             rule='save_failure_declared', ability=ability, total=roll.total, dc=dc)
    # Base Rejection remains available even when a player wants to spend on a
    # successful or unrescuable roll. Automatic defaults preserve the full menu.
    options = ['use', 'base'] if vessel else ['use']
    labels = {'use': f'Spend 1 Heavenly Integrity: +{bonus} to this save'
                    + (' including Heaven-Recognized Vessel' if vessel else '')}
    if vessel:
        labels['base'] = f'Spend 1 Heavenly Integrity: +{pb} to this save; keep Heaven-Recognized Vessel for later this round'
    if waiting:
        options.insert(0, 'wait')
        labels['wait'] = 'Wait: Heaven-Rejecting Marrow can answer a declared failure before consequences; spend nothing now'
    chosen = ask(engine, intent, checkpoint_id(engine, 'INTEGRITY_REJECTION', target.entity_id, source_id, phase),
                 target, CHOICE + ('heavenly_rejection_timing' if waiting else 'heavenly_rejection'), options,
                 name=name, feature_id=REJECTION, target_id=target.entity_id,
                 labels=labels,
                 prompt=f'{name}: {target.display_name} is saving against {action_name}. '
                        f'The saving throw total is {roll.total}. '
                        f'Spend 1 pre-existing Heavenly Integrity to add {pb} to this roll only'
                        + (f', or {bonus} by using Heaven-Recognized Vessel this round' if vessel else '')
                        + '; no Action or Reaction. '
                        + (f'The save outcome is already fixed as a {declared}, so this bonus cannot change it. '
                           if declared else '')
                        + ('You may wait for Heaven-Rejecting Marrow after a declared failure, before consequences.' if waiting else
                           'The save has been declared a failure; consequences have not happened.' if improved and declared != 'success'
                           else '' if declared else 'The roll is complete; its outcome has not been declared.'),
                 preferred=['wait'] if waiting else None,
                 allow_decline=True, automatic=waiting or prefer_use,
                 default='first' if waiting or prefer_use else 'decline',
                 payment=Payment(resource, 1),
                 prompt_context={'action_name': action_name, 'affected_id': target.entity_id})
    if not chosen or chosen[0] == 'wait':
        return None
    use_vessel = bool(vessel and chosen[0] == 'use')
    bonus = pb * (2 if use_vessel else 1)
    Payment(resource, 1).pay(engine, target, REJECTION)
    if use_vessel:
        settle_vessel_bonus(engine, target, pb)
    note(engine, REJECTION, target, f'{target.display_name} uses {name}: spends 1 Heavenly Integrity '
         f'for +{bonus} to the saving throw against {action_name}.', (target,))
    engine._append_event('REACTION_RESOLVED', REJECTION, actor_id=target.entity_id,
                         target_ids=(target.entity_id,), payload={'checkpoint': phase, 'bonus': bonus, 'source_save': source_id})
    return bonus
