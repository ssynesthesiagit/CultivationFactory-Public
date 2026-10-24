"""Carried Sealed Field Rations: finite prepared items, never free combat stock.

Equipment entries may record sealed_field_rations = [{kind, count, age_hours,
maker_cl, maker_pb, maker_key_mod}]. Preparation/distribution occurs before a
fight; each carrier records only its own remaining items. compile_resources and
compile_actions seal quantities, freshness and maker statistics. Expired food
has no combat action. Consume uses a Bonus Action on self; administer uses an
Action on an adjacent willing or Unconscious creature. AI administers to allies.
One recipient can consume one ration in an actual turn, even from two carriers.
"""
from . import effect, hook

FEATURE = 'tianxia.subpath.qi.culinary_cultivator.feature.sealed_field_rations'
KINDS = ('restorative', 'fortifying', 'bitter', 'courage', 'marching', 'bracing')
POOL = 'resource:named.sealed_field_ration.'
BRACE = 'condition:typed.culinary_bracing'


def _stock(sheet):
    out = []
    for equipment in (sheet or {}).get('equipment') or []:
        if not isinstance(equipment, dict):
            continue
        for item in equipment.get('sealed_field_rations') or []:
            if not isinstance(item, dict) or item.get('kind') not in KINDS:
                raise ValueError('Sealed Field Rations require one printed ration kind')
            if set(item) != {'kind','count','age_hours','maker_cl','maker_pb','maker_key_mod'}:
                raise ValueError('Record ration count, age_hours and maker_cl, maker_pb, maker_key_mod')
            if any(type(item[f]) is not int for f in ('count','maker_cl','maker_pb','maker_key_mod')):
                raise ValueError('Ration quantities and maker statistics must be integers')
            age = item['age_hours']
            if type(age) not in (int,float) or age < 0 or item['count'] < 0 or item['maker_cl'] < 1 or item['maker_pb'] < 1:
                raise ValueError('Invalid prepared ration quantity, age or maker statistics')
            # Persist only integer time: fractional hours are rounded up to the next
            # second so a serving can never outlive its recorded freshness.
            age_seconds = int(age * 3600)
            if age * 3600 > age_seconds:
                age_seconds += 1
            if age_seconds < 86400 and item['count']:
                out.append({**{k:v for k,v in item.items() if k != 'age_hours'},
                    'age_seconds': age_seconds, 'remaining_rounds': (86400-age_seconds)//6})
    # Different makers/freshness cannot be collapsed into one item pool.
    return out


@hook('compile_resources')
def ration_resources(info):
    from ..gate2_runtime_models import ResourceDefinition
    return [ResourceDefinition(resource_id=POOL+str(i),initial=r['count'],maximum=r['count'])
            for i,r in enumerate(_stock(info.get('owner_sheet')))] or None


def _benefit(item):
    roll=f"2d8 {item['maker_key_mod']:+d}"
    repeat=f"Roll with Advantage if the effect's Source Cultivation CL is {item['maker_cl']} or lower."
    return {
        'restorative':f'The recipient regains {roll} Hit Points. ',
        'fortifying':f'The recipient gains {roll} Temporary Hit Points. ',
        'bitter':'The recipient repeats one original saving throw against poison, disease, contamination or a bodily toxin. '+repeat+' ',
        'courage':'The recipient repeats one original saving throw against Frightened or a morale effect. '+repeat+' ',
        'marching':'The recipient chooses a move of up to 15 feet without provoking Opportunity Attacks and ignores difficult terrain for the rest of this turn. ',
        'bracing':'The recipient gains Advantage on its next Strength, Constitution or death saving throw before the end of its next turn. Only the first of those saves gains this benefit. ',
    }[item['kind']]


@hook('compile_actions')
def ration_actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..action_variants import choice, with_variant
    out=[]
    for i,r in enumerate(_stock(info.get('owner_sheet'))):
        for administer in (False,True):
            label=('Administer ' if administer else 'Consume ')+r['kind'].title()+' Ration'
            numbers={**info['numbers'],'cl':r['maker_cl'],'pb':r['maker_pb'],'key_mod':r['maker_key_mod']}
            # Administer and Consume are the use axis of one ration: different economy and target, same pool and effect.
            out.append(with_variant(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.ration.{i}.{int(administer)}",
                display_name=label,owner_id=info['actor_id'],economy=EconomyKind.ACTION if administer else EconomyKind.BONUS_ACTION,
                resolution_kind='TYPED',target_kind='ANY_CREATURE' if administer else 'SELF',range_ft=5 if administer else None,
                costs=((POOL+str(i),1),),parameters={'typed':{'source':FEATURE,'qi_powered':False,'numbers':numbers,'effects':[
                    {'type':'culinary_ration','kind':r['kind']}],'riders':[],'duration':{'kind':'instant'}},
                    'culinary_ration':{**r,'pool':POOL+str(i),'administer':administer},'expected_damage':0,
                    'description':f'{label}: use one prepared serving. '+('An Action on an adjacent willing or Unconscious creature. '
                    if administer else 'A Bonus Action on yourself. ')+
                    _benefit(r)+'A creature can consume one Sealed Field Ration per turn. Sealed rations last 24 hours. Preparation requires a meal, or 10 minutes, ingredients and 2 Qi.'}),
                f"action:typed.{info['short']}.ration.{i}", 'Ration',
                [choice('use', 'administer', 'Administer')] if administer else []))
    return out or None


def _stamp(engine):
    return f'{engine.state.round_number}:{engine.state.current_actor_id}'


@hook('candidate_allowed')
def ration_allowed(engine,actor,candidate,action):
    row=(getattr(action,'parameters',None) or {}).get('culinary_ration')
    if not row:
        return None
    target=engine.state.actors.get((candidate.target_ids or (actor.entity_id,))[0])
    if target is None or target.turn_flags.get('_round_ration_consumed')==_stamp(engine):
        return False
    if engine.state.round_number > int(row['remaining_rounds']):
        return False
    return None


@hook('ai_candidate_allowed')
def ration_ai_recipients(engine,actor,candidate,action):
    if (getattr(action,'parameters',None) or {}).get('culinary_ration'):
        return all(engine.state.actors[t].team_id==actor.team_id for t in candidate.target_ids)
    return None


@effect('culinary_ration')
def consume(ctx,row):
    from ..typed_executor import run_effects
    target=ctx.target or ctx.actor
    item=ctx.action.parameters['culinary_ration']
    if item['administer'] and target is not ctx.actor:
        from ..typed_executor import condition_rules
        unconscious=any(r.get('unconscious') for r in condition_rules(target))
        if not unconscious:
            from .willing_targets import asks_consent
            if not asks_consent(ctx.engine,ctx.intent,target,ctx.action.display_name,
                    f'{ctx.actor.display_name} offers you a {row["kind"]} ration. Consume it?',
                    prefer_accept=target.team_id==ctx.actor.team_id,asker=ctx.actor):
                # The Action was spent offering the serving; an unconsumed item
                # stays with its carrier and creates no recipient turn receipt.
                ctx.engine._gain_resource(ctx.actor,item['pool'],1,ctx.source)
                return
    target.turn_flags['_round_ration_consumed']=_stamp(ctx.engine)
    kind=row['kind']
    if kind in ('restorative','fortifying'):
        run_effects(ctx,[{'type':'healing' if kind=='restorative' else 'temp_hp','applies_to':'target',
            'dice':{'count':2,'sides':8},'formula':'key_ability_modifier'}])
    elif kind=='marching':
        ctx.engine._apply_condition(target,'condition:typed.culinary_marching',ctx.source,ctx.actor.entity_id,
            expires_on='END_OF_CURRENT_TURN',data={'rule':{'ignore_difficult':True},'label':'Marching Ration: ignore difficult terrain this turn'})
        from .rider_choices import step
        step(ctx.engine,target,'marching_ration','Marching Ration',target,15,ctx.source,ctx.intent,
             trigger='you consume the ration',ignored_oa=[a.entity_id for a in ctx.engine.state.actors.values()])
    elif kind=='bracing':
        from .effect_durations import token
        ctx.engine._apply_condition(target,BRACE,ctx.source,ctx.actor.entity_id,
            expires_on=token('end',target.entity_id,target.turns_started+1),
            data={'rule':{'death_save_mode':{'mode':'ADVANTAGE','first':True}},
                  'label':'Bracing Ration: Advantage on your next Strength, Constitution or death save'})
    else:
        _repeat(ctx,target,kind)


def _repeat(ctx,target,kind):
    from .repeat_saves import save_of
    from .rider_choices import pick
    from .passive_rows import known_level
    from .condition_ownership import remove_instance
    from .qi_path import affliction_category
    eligible=[]
    for iid,c in target.conditions.items():
        category=(c.data or {}).get('ration_save_category') or affliction_category(ctx.engine,c.source_definition_id)
        name=c.condition_id.removeprefix('condition:typed.')
        allowed=(name=='frightened' or category=='morale') if kind=='courage' else (
            name=='poisoned' or category in ('poison','disease','contamination','bodily_toxin'))
        if allowed and save_of(c):
            eligible.append((iid,c))
    if not eligible:
        return
    from ..presentation import condition_label
    selected=pick(ctx.engine,target,'ration_repeat','Courage Ration' if kind=='courage' else 'Bitter Ration',
        [iid for iid,c in eligible],subject=target,labels={iid:(c.data or {}).get('label') or condition_label(c.condition_id, c.data)
        for iid,c in eligible},optional=False,intent=ctx.intent)
    if not selected:
        return
    iid,c=next(pair for pair in eligible if pair[0]==selected[0]); save=save_of(c)
    source=ctx.engine.state.actors.get(c.source_actor_id)
    cl=known_level(ctx.engine,source) if source is not None else None
    mode='ADVANTAGE' if cl is not None and cl<=int(ctx.numbers['cl']) else None
    roll=ctx.engine._roll_save(target,str(save['ability']).upper(),int(save['dc']),ctx.source,mode,
        roll_context={'source_actor_id':c.source_actor_id,'named':[c.condition_id.removeprefix('condition:typed.')]})
    if roll is not None and roll.total>=int(save['dc']):
        remove_instance(ctx.engine,target,iid,ctx.source)
        from .hold_escapes import escaped, how_for
        escaped(ctx.engine,target,[c],how_for(save['ability'],target,ctx.actor),
                by=ctx.actor,source=ctx.source,way='repeat_save')


@hook('save_mode')
def bracing_save(engine,target,ability,dc,source_id,roll_context):
    if str(ability).upper() in ('STR','CON') and any(c.condition_id==BRACE for c in target.conditions.values()):
        return 'ADVANTAGE'
    return None


@hook('event')
def bracing_spent(engine,event_type,kwargs):
    if event_type != 'SAVE_ROLLED':
        return
    payload=kwargs.get('payload') or {}
    if str(payload.get('ability') or str(payload.get('reason') or '').rsplit(':',1)[-1]).upper() not in ('STR','CON'):
        return
    target=engine.state.actors.get(kwargs.get('actor_id'))
    if target is not None:
        from .condition_ownership import remove_instance
        for iid,c in list(target.conditions.items()):
            if c.condition_id==BRACE:
                remove_instance(engine,target,iid,c.source_definition_id)
