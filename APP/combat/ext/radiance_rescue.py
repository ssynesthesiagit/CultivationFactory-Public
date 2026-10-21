"""Morning Breath uses the actual source after damage reductions are final.

Known Unclean and Necrotic triggers are executable. Curses and possession need
explicit source provenance. Reviewed rows opt into native rescue movement;
possession/corruption suppression remains unresolved.
"""
from . import hook
from .creature_kinds import is_unclean
from .needle import ask, checkpoint_id, CHOICE
from .placed import context, note

FEATURE = 'tianxia.talent.radiance.resurrection_of_the_morning_breath'
CHECKPOINT = 'MORNING_BREATH'
PENDING = 'condition:typed.morning_breath_followup'


def movement_enabled(row):
    return any(e.get('rescue_movement') is True for e in row.get('effects') or [])


def move_options(engine, owner, target, intent):
    if intent is None:
        return {}
    from ..granted_movement import candidates
    from ..senses import perceives_cell
    return {key: c for key, c in candidates(engine, target, 20, intent, FEATURE).items()
            if perceives_cell(engine, owner, c.destination)}


@hook('row_allowed')
def replace_generic(engine, reactor, row):
    if row.get('feature_id') == FEATURE and row.get('native_checkpoint') != CHECKPOINT:
        return False
    return None


@hook('lethal_damage')
def rescue(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    from ..damage_allocation import lethal_threshold
    if target.current_hp <= 0 or lethal_threshold(engine, target, amount, source_actor_id, source_id=source_id, damage_type=damage_type) < target.current_hp:
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
        enabled = movement_enabled(row)
        if enabled and move_options(engine, owner, target, intent):
            labels['move'] = 'Keep them at 1 Hit Point and move them up to 20 feet to a space you can see, without Opportunity Attacks'
        labels['manual'] = ('Keep them at 1 Hit Point; resolve possession or corruption suppression with the GM' if enabled
                            else 'Keep them at 1 Hit Point; resolve the chosen movement or suppression with the GM')
        presentation = None
        if enabled:
            from .choice_prompt import action_context
            presentation = {**action_context(engine, attacker, source_id, target),
                            'cost': '8 Cultivation Points and your Reaction; once per long rest'}
        chosen = ask(engine, intent, checkpoint_id(engine, CHECKPOINT, target.entity_id), owner,
            CHOICE+'morning_breath', list(labels), labels=labels, allow_decline=True,
            prompt=f'Resurrection of the Morning Breath: {trigger} would reduce {target.display_name} to 0 Hit Points. '
                   'Spend your Reaction, 8 Cultivation Points and your use until a long rest to keep them at 1? '
                   'Confirm that they are willing, then choose the follow-up.',
            name='Resurrection of the Morning Breath', feature_id=FEATURE, target_id=target.entity_id,
            default='decline', prompt_context=presentation)
        if not chosen:
            continue
        from ..paid_relocation import activation, capture, retain

        with activation(engine, owner, FEATURE, independent=True):
            # The follow-up resolves after this accepted reaction unwinds. Keep
            # its actual payment owner in transaction scratch, never the condition.
            key = (PENDING, target.entity_id, owner.entity_id, source_id, source_actor_id)
            retain(engine, key, capture(engine))
            commit_checkpoint_response(engine, owner, target, row, CHECKPOINT)
            engine._apply_condition(target, PENDING, FEATURE, owner.entity_id, expires_on='UNTIL_REMOVED',
                data={'choice':chosen[0], 'attacker':source_actor_id, 'damage_source':source_id, 'numbers':dict(row['numbers']),
                      **({'native_movement': 1} if enabled else {})})
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
            from ..paid_relocation import causal_scope, take

            key = (PENDING, target.entity_id, c.source_actor_id, c.data.get("damage_source"), c.data.get("attacker"))
            with causal_scope(engine, take(engine, key)):
                owner = engine.state.actors.get(c.source_actor_id)
                engine._remove_condition(target, PENDING, FEATURE)
                if owner is None:
                    continue
                action = ActionDefinition(source_definition_id=FEATURE, display_name='Resurrection of the Morning Breath',
                    owner_id=owner.entity_id, economy=EconomyKind.REACTION, resolution_kind='TYPED', target_kind='ENTITY')
                if c.data['choice'] == 'manual':
                    note(engine, FEATURE, owner, 'Morning Breath kept the willing creature at 1 Hit Point. The GM must now resolve the chosen '
                         + ('possession/corruption suppression.' if c.data.get('native_movement') else '20-foot movement or possession/corruption suppression.'))
                    continue
                if c.data['choice'] == 'move':
                    from ..granted_movement import Route
                    from .granted_moves import commit
                    rows = move_options(engine, owner, target, engine._active_intent)
                    labels = {key: f'Move {target.display_name} to {row.destination.x}, {row.destination.y}, '
                              f'altitude {row.destination.z * 5} feet ({row.movement_cost_ft} feet of the 20-foot grant)' for key, row in rows.items()}
                    selected = ask(engine, engine._active_intent, checkpoint_id(engine, 'MORNING_BREATH_MOVE', target.entity_id),
                        owner, CHOICE + 'morning_breath_move', list(rows), labels=labels, allow_decline=True,
                        prompt=f'Resurrection of the Morning Breath: choose a reachable unoccupied space you can see for '
                               f'{target.display_name}. Move up to 20 feet without Opportunity Attacks or ordinary movement cost; '
                               'you may leave them where they are.', name='Resurrection of the Morning Breath',
                        feature_id=FEATURE, target_id=target.entity_id, prompt_context={'cost': 'No additional cost'}, default='decline')
                    if selected:
                        row = rows[selected[0]]
                        path = Route(tuple(row.canonical_path), row.metadata.get('movement_mode', 'walk'))
                        commit(engine, target, path, FEATURE, budget_ft=20, provokes=False, intent=engine._active_intent)
                    continue
                if c.data['choice'] == 'damage':
                    other = engine.state.actors.get(c.data.get('attacker'))
                    if other is not None and other.active and other.current_hp > 0:
                        sub = context(engine, owner, FEATURE, c.data['numbers'], [other], action=action)
                        typed_executor.run_effects(sub, [{'type':'damage','applies_to':'target','dice':{'count':4,'sides':8},'damage_types':['RADIANT']}])
                else:
                    sub = context(engine, owner, FEATURE, c.data['numbers'], [target], action=action)
                    typed_executor.run_effects(sub, [{'type':'remove_condition','applies_to':'target','condition':c.data['choice']}])
