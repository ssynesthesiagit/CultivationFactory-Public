"""Morning Breath uses the actual source after damage reductions are final.

Known Unclean and Necrotic triggers are executable. Curses and possession need
explicit source provenance. Movement/suppression follow-ups remain manual.
"""
from . import hook
from .creature_kinds import is_unclean
from .needle import ask, checkpoint_id, CHOICE
from .placed import context, note

FEATURE = 'tianxia.talent.radiance.resurrection_of_the_morning_breath'
CHECKPOINT = 'MORNING_BREATH'
PENDING = 'condition:typed.morning_breath_followup'


@hook('row_allowed')
def replace_generic(engine, reactor, row):
    if row.get('feature_id') == FEATURE and row.get('native_checkpoint') != CHECKPOINT:
        return False
    return None


@hook('lethal_damage')
def rescue(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    if target.current_hp <= 0 or amount < target.current_hp + target.temporary_hp:
        return None
    attacker = engine.state.actors.get(source_actor_id)
    if str(damage_type).upper() != 'NECROTIC' and not is_unclean(attacker):
        return None
    from ..typed_reactions import checkpoint_response, commit_checkpoint_response
    action = engine.action_catalog.get(source_id)
    source_name = action.display_name if action is not None else 'the damaging effect'
    trigger = f'{attacker.display_name} using {source_name}' if attacker is not None else f'{source_name} (a hazard or environmental source)'
    for owner in sorted(engine.state.actors.values(), key=lambda a:a.entity_id):
        # Allied subjects are the table's willing-creature contract; do not make
        # an unwilling enemy accept a save, cleanse or displacement.
        if owner.team_id != target.team_id:
            continue
        row = checkpoint_response(engine, owner, target, attacker, FEATURE, CHECKPOINT)
        if row is None:
            continue
        labels = {}
        if attacker is not None and engine._distance_actor_to_actor(owner, attacker) <= 60 and engine._line_of_sight_actor_to_actor(owner, attacker):
            labels['damage'] = 'Keep them at 1 Hit Point and deal 4d8 Radiant damage to the attacker'
        for condition in ['frightened', 'charmed']:
            if any(c.condition_id == 'condition:typed.'+condition for c in target.conditions.values()):
                labels[condition] = 'Keep them at 1 Hit Point and end '+condition.title()
        labels['manual'] = 'Keep them at 1 Hit Point; resolve the chosen movement or suppression with the GM'
        chosen = ask(engine, intent, checkpoint_id(engine, CHECKPOINT, target.entity_id), owner,
            CHOICE+'morning_breath', list(labels), labels=labels, allow_decline=True,
            prompt=f'Resurrection of the Morning Breath: {trigger} would reduce {target.display_name} to 0 Hit Points. '
                   'Spend your Reaction, 8 Cultivation Points and your use until a long rest to keep them at 1? '
                   'Confirm that they are willing, then choose the follow-up.',
            name='Resurrection of the Morning Breath', feature_id=FEATURE, target_id=target.entity_id,
            default='decline')
        if not chosen:
            continue
        commit_checkpoint_response(engine, owner, target, row, CHECKPOINT)
        engine._apply_condition(target, PENDING, FEATURE, owner.entity_id, expires_on='UNTIL_REMOVED',
            data={'choice':chosen[0], 'attacker':source_actor_id, 'damage_source':source_id, 'numbers':dict(row['numbers'])})
        return 1
    return None


@hook('event', nested=True)
def follow_up(engine, event_type, kwargs):
    if event_type != 'DAMAGE_COMMITTED':
        return
    from .. import typed_executor
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    for aid in kwargs.get('target_ids') or ():
        target = engine.state.actors.get(aid)
        if target is None:
            continue
        for c in list(target.conditions.values()):
            if c.condition_id != PENDING or c.data.get('damage_source') != kwargs.get('source_definition_id') or c.data.get('attacker') != kwargs.get('actor_id'):
                continue
            owner = engine.state.actors.get(c.source_actor_id)
            engine._remove_condition(target, PENDING, FEATURE)
            if owner is None:
                continue
            action = ActionDefinition(source_definition_id=FEATURE, display_name='Resurrection of the Morning Breath',
                owner_id=owner.entity_id, economy=EconomyKind.REACTION, resolution_kind='TYPED', target_kind='ENTITY')
            if c.data['choice'] == 'manual':
                note(engine, FEATURE, owner, 'Morning Breath kept the willing creature at 1 Hit Point. The GM must now resolve the chosen 20-foot movement or possession/corruption suppression.')
                continue
            if c.data['choice'] == 'damage':
                other = engine.state.actors.get(c.data.get('attacker'))
                if other is not None and other.active and other.current_hp > 0:
                    sub = context(engine, owner, FEATURE, c.data['numbers'], [other], action=action)
                    typed_executor.run_effects(sub, [{'type':'damage','applies_to':'target','dice':{'count':4,'sides':8},'damage_types':['RADIANT']}])
            else:
                sub = context(engine, owner, FEATURE, c.data['numbers'], [target], action=action)
                typed_executor.run_effects(sub, [{'type':'remove_condition','applies_to':'target','condition':c.data['choice']}])
