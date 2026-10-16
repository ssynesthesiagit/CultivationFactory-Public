"""Shared helper and owning Twin Tie-Up plug-in for paired physical grapples.

Consumer gu_wrestling calls public slam_targets for Work-the-Hold sharing.

Reviewed marker opts newly compiled actions in. The existing hand allocator,
save resolver and grapple lifecycle remain the only owners of those rules.
"""
import copy
from . import effect, hook, ai_controlled
from .rider_choices import pick

SOURCE = 'TAL_WRESTLING_TWIN_TIE_UP'
GRAPPLED = 'condition:typed.grappled'
GROUP = 'wrestling_twin_group'
START = 'wrestling_twin_start'


def paired(engine, actor, group):
    return [a for a in engine.state.actors.values() if a.active and any(
        c.condition_id == GRAPPLED and c.source_actor_id == actor.entity_id and c.data.get(GROUP) == group
        for c in a.conditions.values())]


def eligible(engine, actor, target, reach):
    from ..relations import relation, ENEMY
    from .. import stealth
    from ..targeting import line_of_effect
    return (target is not None and target.active and target is not actor
            and relation(engine, actor, target) == ENEMY
            and engine._distance_actor_to_actor(actor, target) <= reach
            and engine._line_of_sight_actor_to_actor(actor, target)
            and line_of_effect(engine, actor, target=target)
            and (not ai_controlled(engine, actor) or stealth.sees(engine, actor, target)))


@effect('wrestling_twin')
def twin(ctx, row):
    from ..typed_executor import Context, run_effects
    first = ctx.target
    reach = int(ctx.action.range_ft or ctx.action.reach_ft or 5)
    if not eligible(ctx.engine, ctx.actor, first, reach):
        return
    options = [a for a in ctx.engine.state.actors.values() if a is not first and eligible(ctx.engine, ctx.actor, a, reach)]
    if not options:
        return
    chosen = pick(ctx.engine, ctx.actor, 'twin_second', 'Twin Tie-Up', [a.entity_id for a in options],
                  subject=first, optional=False, automatic=ai_controlled(ctx.engine, ctx.actor),
                  labels={a.entity_id:f'Also attempt to Grapple {a.display_name}' for a in options},
                  preferred=[options[0].entity_id],
                  prompt=f'Twin Tie-Up: {first.display_name} is your first target. Choose a different creature within reach. '
                         'Each chooses a Strength or Dexterity save; each failed save needs one free hand or eligible body part.')
    second = next((a for a in options if a.entity_id in chosen), None)
    if second is None:
        return
    group = f'{ctx.source}:{ctx.engine.state.event_sequence}'
    for target in (first, second):
        if eligible(ctx.engine, ctx.actor, target, reach):
            child = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, {GROUP:group})
            save = copy.deepcopy(row['save'])
            for condition in save.get('on_fail') or []:
                if condition.get('condition') == 'grappled':
                    condition['condition_data'] = {**condition.get('condition_data', {}), GROUP: group}
            run_effects(child, [save])


@hook('compile_action')
def compile_twin(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('source') == SOURCE and any(r.get('type') == 'wrestling_twin' for r in typed.get('effects') or []):
        params = copy.deepcopy(action.parameters)
        params['typed']['physical_grapple'] = True
        params['typed']['twin_runtime'] = True
        return action.model_copy(update={'parameters':params, 'range_ft':5, 'target_kind':'HOSTILE_ENTITY'})
    if '.granted.slam.' in action.source_definition_id and SOURCE in set(info.get('owned_ids') or ()):
        mechanic = (info.get('mechanics') or {}).get(SOURCE) or {}
        if any(r.get('type') == 'wrestling_twin' for r in mechanic.get('effects') or []):
            params = copy.deepcopy(action.parameters)
            for row in params['typed'].get('effects') or []:
                if row.get('type') == 'apply_slam':
                    row['twin_runtime'] = True
            return action.model_copy(update={'parameters':params})
    return None


@hook('candidate_allowed')
def two_targets(engine, actor, candidate, action):
    typed = (action.parameters or {}).get('typed') or {} if action is not None else {}
    if not typed.get('twin_runtime'):
        return None
    first = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
    reach = int(action.range_ft or action.reach_ft or 5)
    return bool(eligible(engine,actor,first,reach) and any(a is not first and eligible(engine,actor,a,reach)
                                                         for a in engine.state.actors.values()))


@hook('escape_mode')
def paired_escape(engine, actor, grips):
    for grip in (grips.values() if isinstance(grips,dict) else grips or ()):
        group = (grip.data or {}).get(GROUP)
        holder = engine.state.actors.get(grip.source_actor_id)
        if group and holder and len(paired(engine,holder,group)) == 2:
            return 'ADVANTAGE'
    return None


@hook('turn_start')
def work_pairs(engine, actor):
    if not any(a.owner_id == actor.entity_id and ((a.parameters or {}).get('typed') or {}).get('twin_runtime')
               for a in engine.action_catalog.values()):
        return
    groups = {c.data.get(GROUP) for a in engine.state.actors.values() for c in a.conditions.values()
              if c.condition_id == GRAPPLED and c.source_actor_id == actor.entity_id and c.data.get(GROUP)}
    actor.turn_flags[START] = sorted(g for g in groups if len(paired(engine,actor,g)) == 2)


def slam_targets(ctx):
    """Current pair held since turn start, for gu_wrestling's opted-in Work the Hold."""
    if ctx.target is None or ctx.engine.state.current_actor_id != ctx.actor.entity_id:
        return [ctx.target]
    groups = {c.data.get(GROUP) for c in ctx.target.conditions.values()
              if c.condition_id == GRAPPLED and c.source_actor_id == ctx.actor.entity_id}
    for group in ctx.actor.turn_flags.get(START) or []:
        if group in groups:
            targets = paired(ctx.engine,ctx.actor,group)
            if len(targets) == 2:
                return [ctx.target] + [a for a in targets if a is not ctx.target
                                       and eligible(ctx.engine, ctx.actor, a, int(ctx.action.range_ft or ctx.action.reach_ft or 5))]
    return [ctx.target]


@hook('choice_reactors')
def reactors(engine):
    return tuple(a.owner_id for a in engine.action_catalog.values()
                 if ((a.parameters or {}).get('typed') or {}).get('twin_runtime'))


@hook('maneuvers')
def release_one(info):
    mechanic = (info.get('mechanics') or {}).get(SOURCE) or {}
    if SOURCE not in set(info.get('owned') or ()) or not any(r.get('type')=='wrestling_twin' for r in mechanic.get('effects') or []):
        return None
    base = next((a for a in info['actions'] if a.source_definition_id.endswith('.release_grapple')),None)
    if base is None:
        return None
    params = copy.deepcopy(base.parameters)
    params['typed']['effects'] = [{'type':'wrestling_release','applies_to':'target'}]
    params['twin_release_one'] = True
    return {'actions':[base.model_copy(update={'source_definition_id':base.source_definition_id.replace('.release_grapple','.twin.release_grapple'),
        'display_name':'Release one grapple','target_kind':'ANY_CREATURE','range_ft':5,'parameters':params})]}


@hook('candidate_allowed')
def release_target(engine,actor,candidate,action):
    if action is None or not action.parameters.get('twin_release_one'):
        return None
    return bool(candidate.target_ids) and all(any(c.condition_id == GRAPPLED and c.source_actor_id == actor.entity_id
        for c in engine.state.actors[tid].conditions.values()) for tid in candidate.target_ids if tid in engine.state.actors)


@hook('button_description')
def release_description(row):
    """Explain the opted-in release control at the table and on the sheet."""
    if not (row.get('parameters') or {}).get('twin_release_one'):
        return None
    return ('No action or resource cost: immediately end only your hold on the selected creature. '
            'Your other grapple stays in place, as do any holds from other creatures.')
