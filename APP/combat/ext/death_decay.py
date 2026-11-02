"""Rotting Grasp's printed unattended-object attack and optional maximum damage."""
from . import hook

GRASP = "TAL_DEATH_ROTTING_GRASP"
FLAG = "death_rotting_object"
DECAYING = {"wood", "cloth", "leather", "bone", "rope", "paper"}


def typed(action):
    return (getattr(action, 'parameters', None) or {}).get('typed') or {}


@hook('compile_action')
def grasp_attack(action, mechanic):
    if typed(action).get('source') != GRASP:
        return None
    return action.model_copy(update={'range_ft':5, 'parameters':{
        **action.parameters, 'replaces_attack':1,
        'typed':{**typed(action), FLAG:1}}})


def legal_object(obj):
    return (not obj.destroyed and obj.unattended and obj.ac is not None and obj.current_hp is not None
            and not (obj.component or {}).get('magical') and not (obj.component or {}).get('artifact'))


@hook('object_targets')
def grasp_objects(engine, actor, action):
    if not typed(action).get(FLAG):
        return None
    return [obj.object_id for obj in engine.state.objects.values() if legal_object(obj)]


@hook('candidate_allowed')
def grasp_target(engine, actor, candidate, action):
    if not typed(action).get(FLAG) or not candidate.metadata.get('object_target'):
        return None
    obj=engine.state.objects.get(next(iter(candidate.target_ids),None))
    return bool(obj and legal_object(obj))


@hook('object_action')
def grasp_damage(engine, actor, action, obj, candidate, intent):
    data=typed(action)
    if not data.get(FLAG):
        return None
    from ..typed_executor import Context, resolve_attack_damage
    from .objects import attack_object_roll, deal
    from .needle import ask
    ctx=Context(engine,actor,action,intent,data,[],None)
    if not legal_object(obj):
        return True
    hit,natural=attack_object_roll(ctx,obj)
    if not hit:
        return True
    attack = next(row for row in data['effects'] if row.get('type') == 'attack')
    dice, kinds, _, _, _ = resolve_attack_damage(ctx, attack)
    component=obj.component or {}
    material=str(component.get('material') or '').lower()
    # Unknown material never qualifies; explicit decaying metadata covers other
    # owner-described organic material. Normal object damage is still legal.
    decays=material in DECAYING or component.get('decaying') is True
    chosen=ask(engine,intent,'ROTTING_OBJECT_DAMAGE',actor,'choice:needle.rotting_object_damage',
        ['roll','maximum'],labels={'roll':'Roll Withering Hand damage','maximum':'Deal maximum Withering Hand damage'},
        preferred=['maximum'], name='Rotting Grasp',
        prompt=f'Rotting Grasp hit {component.get("name") or "the object"}. Roll damage, or deal maximum damage to this decaying material?',
        feature_id=GRASP) if decays else ['roll']
    if chosen and chosen[0]=='maximum':
        amount=dice.count*dice.sides*(2 if natural==20 else 1)+dice.modifier
    else:
        roll=engine.roller.roll(dice,actor_id=actor.entity_id,
            reason=f'DAMAGE:{ctx.source}:object',critical=natural==20)
        engine._record_roll(roll)
        amount=roll.total
    deal(engine,actor,obj,[(amount,kinds[0])],ctx.source)
    return True
