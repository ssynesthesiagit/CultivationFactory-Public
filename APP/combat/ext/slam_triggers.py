"""Source-qualified Establish/Work the Hold producers for Applying a Slam.

Hold creation records the source's real turn. Turn start snapshots existing
grips; a later unrelated Grappled condition cannot fabricate either trigger.
The reaction path consumes the exact escape resolver's tested grip list.
"""
from copy import deepcopy
from . import hook

G = 'condition:typed.grappled'
W = 'tianxia.sphere.wrestling'


@hook('compile_action')
def seal(action, info):
    if '.granted.slam.' not in action.source_definition_id:
        return action
    params = deepcopy(action.parameters)
    params['typed']['slam_trigger_contract'] = 1
    params['harmful'] = True
    return action.model_copy(update={'parameters': params, 'target_kind': 'ANY_CREATURE',
                                     'range_ft': None, 'reach_ft': None})


@hook('condition_data_additions')
def establish(ctx, subject, effect):
    if effect.get('condition') != 'grappled':
        return None
    if ctx.typed.get('unarmed_option') != 'grapple' and ctx.typed.get('sphere') != W:
        return None
    if not any(a.owner_id == ctx.actor.entity_id and (a.parameters.get('typed') or {}).get('slam_trigger_contract')
               for a in ctx.engine.action_catalog.values()):
        return None
    return {'slam_established_on_turn': ctx.actor.turns_started}


@hook('turn_start')
def work(engine, actor):
    if not any(a.owner_id == actor.entity_id and (a.parameters.get('typed') or {}).get('slam_trigger_contract')
               for a in engine.action_catalog.values()):
        return
    ids = [c.instance_id for target in engine.state.actors.values() for c in target.conditions.values()
           if c.condition_id == G and c.source_actor_id == actor.entity_id]
    actor.turn_flags['_round_slam_work_turn'] = actor.turns_started
    actor.turn_flags['_round_slam_work_holds'] = '|'.join(ids)


@hook('candidate_allowed')
def eligible(engine, actor, candidate, action):
    typed = (action.parameters.get('typed') or {}) if action else {}
    if not typed.get('slam_trigger_contract'):
        return None
    work_ids = str(actor.turn_flags.get('_round_slam_work_holds') or '').split('|')
    reaction = action.economy.value == 'REACTION'
    def permitted(target):
        return target.active and any(c.condition_id == G and c.source_actor_id == actor.entity_id
            and (reaction or c.data.get('slam_established_on_turn') == actor.turns_started
                 or actor.turn_flags.get('_round_slam_work_turn') == actor.turns_started and c.instance_id in work_ids)
            for c in target.conditions.values())
    return bool(candidate.target_ids) and all(permitted(engine.state.actors[tid]) for tid in candidate.target_ids)
