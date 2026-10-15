"""Coagulate composes the public recipient-consent and source-treatment contracts."""
from copy import deepcopy
from . import hook
ID = 'BLOOD_BASE_COAGULATE'

def composed(action):
    params = deepcopy(action.parameters or {})
    typed = params.get('typed') or {}
    if ID not in (typed.get('source'), typed.get('option_of')):
        return None
    rows = typed.get('effects') or []
    if any(r.get('type') == 'choose_willing' for r in rows):
        return None
    for row in rows:
        if row.get('type') == 'remove_condition' and row.get('condition') == 'bleeding':
            row['type'] = 'clinical_treatment'
            row['category'] = 'ordinary_bleeding'
            row['operation'] = 'end'
    typed['manual_inline_choice'] = True
    typed['effects'] = [r for r in rows if r.get('type') == 'requires_thread'] + [{
        'type': 'choose_willing', 'target_only': True, 'allow_hostile_target': True,
        'consent_text': 'Accept Coagulate: one chosen treatment; Bonus Action and 1 CP from the caster. Your own Blood Thread is required.',
        'effects': [r for r in rows if r.get('type') != 'requires_thread']}]
    return action.model_copy(update={'parameters': params})

@hook('compile_action')
def coagulate(action, info):
    return composed(action)

@hook('compile_actions')
def coagulate_recipients(info):
    from .willing_targets import willing_non_allies
    prepared = [new for action in info.get('actions', ()) if (new := composed(action)) is not None]
    return willing_non_allies({**info, 'actions': prepared})


@hook('compile_actions')
def unwilling_allied_thread(info):
    result=[]
    for action in info.get('actions') or []:
        typed=action.parameters.get('typed') or {}
        if typed.get('source')=='BLOOD_BASE_BLOOD_THREAD' and action.target_kind=='HOSTILE_ENTITY':
            result.append(action.model_copy(update={'source_definition_id':action.source_definition_id+'#allied',
                'display_name':action.display_name+' (any creature)', 'target_kind':'ANY_CREATURE'}))
        if typed.get('source')=='POISON_BASE_INGRAIN_THE_TOXIN' and action.target_kind=='HOSTILE_ENTITY':
            result.append(action.model_copy(update={'source_definition_id':action.source_definition_id+'#allied',
                'display_name':action.display_name+' (any creature)', 'target_kind':'ANY_CREATURE'}))
    return result or None


@hook('compile_action')
def thread_recipient_answer(action,info):
    params=deepcopy(action.parameters or {}); typed=params.get('typed') or {}
    if typed.get('source')!='BLOOD_BASE_BLOOD_THREAD':return None
    rows=typed.get('effects') or []
    if not any(r.get('type')=='attack' for r in rows):return None
    typed['manual_inline_choice']=True
    typed['effects']=[{'type':'blood_thread_attempt','effects':rows}]
    return action.model_copy(update={'parameters':params})


from . import effect

@effect('blood_thread_attempt',harmful=True)
def thread_attempt(ctx,row):
    """The recipient's answer selects automatic Thread or the printed attack."""
    if ctx.typed.get('source')!='BLOOD_BASE_BLOOD_THREAD' or ctx.target is None:return
    from .willing_targets import asks_consent
    from ..typed_executor import run_effects
    target=ctx.target
    willing=target is ctx.actor or asks_consent(ctx.engine,ctx.intent,target,'Blood Thread',
        f'{ctx.actor.display_name} uses Blood Thread on {target.display_name}. Accept a harmless Thread for 1 minute? '
        'Refusing requires the caster to make the printed ranged Cultivation Attack; a hit deals Piercing or Necrotic damage and applies a shorter Thread.',
        prefer_accept=target.team_id==ctx.actor.team_id,asker=ctx.actor)
    if willing:
        run_effects(ctx,[{'type':'mark','mark':'Blood Thread','applies_to':'target','duration':{'kind':'minutes','amount':1}}])
    else:
        from .needle import ask,checkpoint_id,CHOICE
        chosen=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'blood_thread_damage',target.entity_id),ctx.actor,
            CHOICE+'blood_thread_damage',['piercing','necrotic'],labels={'piercing':'Piercing','necrotic':'Necrotic'},
            preferred=['piercing'],prompt=f'Blood Thread: choose Piercing or Necrotic damage before attacking {target.display_name}.')
        rows=deepcopy(row['effects'])
        def seal(items):
            for item in items:
                if item.get('type') in ('damage','extra_damage') and set(item.get('damage_types') or [])=={'piercing','necrotic'}:item['damage_types']=(chosen or ['piercing'])
                for key in ('effects','on_hit','on_fail','on_success'):seal(item.get(key) or [])
        seal(rows)
        run_effects(ctx,rows)


@hook('compile_action')
def any_willing_blood_recipient(action,info):
    typed=action.parameters.get('typed') or {}
    source=str(typed.get('source') or '')
    if (ID in (source,typed.get('option_of')) or source.startswith('BLOOD_BASE_BLOOD_THREAD')) and action.source_definition_id.endswith('#willing_non_ally'):
        return action.model_copy(update={'target_kind':'ANY_CREATURE'})
    return None
