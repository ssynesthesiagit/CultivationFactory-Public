"""Source-owned Hundred-Venom exposure collection using the native GM contract.

The table owner supplies unknown source categories, delivery and duration. No
creature controller can fabricate that authority. Collection binds the current
receipt; a later declaration, expiry or scene change invalidates it. The actual
exposure still requires a native accepted table intent, ordinary dice, reaction
choices and committed damage/save/condition events. These are source encounters,
not poison inventory items or harvestable body venom.
"""
from copy import deepcopy
from . import hook, effect
from .hundred_venom import PREFIX
from ..journey import require, integer
from ..fact_consent_admission import read
from ..canonical import canonical_sha256

FAMILY = PREFIX.removesuffix('.feature.')
KIND = 'external_exposure'
SCOPE = 'current_scene'
COLLECT = 'hundred_venom_collect_exposure'
BUNDLE_KEY = 'hundred_venom_exposures'
USE = 'condition:typed.hundred_venom_exposure_used'


def owns(actor):
    return any(str(r.get('feature_id') or '').startswith(PREFIX)
               for r in actor['bundle'].get('typed_passives', ()))


@hook('fact_admission_schema')
def schema(session, source, subject, kind):
    if (source, kind) != (FAMILY, KIND) or not any(owns(a) for a in session.state['actors'].values()):
        return None
    fields = {
        'name':{'type':'string','minLength':1,'maxLength':120},
        'source_actor':{'enum':[aid for aid in session.state['actors'] if aid != subject]},
        'delivery':{'enum':['damage','save','poisoned']},
        'category':{'enum':['acid','poison','disease','ordinary_disease']},
        'authority':{'enum':['ordinary','tribulation','curse','foundation','secret','conceptual','higher_authority','special_cure','permanent']},
        'amount':{'type':'integer','minimum':0,'maximum':100000},
        'dc':{'type':'integer','minimum':1,'maximum':100},
        'duration_seconds':{'type':'integer','minimum':6,'maximum':86400,'multipleOf':6},
        'source_cl':{'type':'integer','minimum':1,'maximum':100},
        'duration_kind':{'enum':['seconds','source_next_start','holder_next_end','current_turn_end']}}
    return {'value_type':'document','authority':'table_owner','maximum_seconds':86400,
            'document_schema':{'type':'object','properties':fields,'required':[k for k in fields if k!='duration_kind'],'additionalProperties':False},
            'description':'An actual external poison, Acid exposure, disease or Poisoned source; record its creature, authority, save, damage and duration explicitly.'}


def record(session, aid):
    r = read(session, FAMILY, aid, KIND, SCOPE, aid)
    if r is None:
        return None
    d = r['value']
    require(set(d)-{'duration_kind'} == {'name','source_actor','delivery','category','authority','amount','dc','duration_seconds','source_cl'},
            'Record the exposure name, source creature, delivery, category, authority, amount, DC, duration and Source CL.')
    require(type(d['name']) is str and 0 < len(d['name'].strip()) <= 120, 'Name the actual exposure plainly.')
    require(d['source_actor'] in session.state['actors'] and d['source_actor'] != aid,
            'Choose the actual external source creature in this scene.')
    require(d['source_actor'] in r['readers'], 'Authorize the source creature to read this exposure before it can deliver it.')
    require(d['delivery'] in ('damage','save','poisoned') and d['category'] in ('acid','poison','disease','ordinary_disease'),
            'Choose the printed exposure delivery and category.')
    require(d['authority'] in ('ordinary','tribulation','curse','foundation','secret','conceptual','higher_authority','special_cure','permanent'),
            'Record the actual source authority, including any special cure or permanent disease.')
    require(all(integer(d[k],1) for k in ('dc','duration_seconds','source_cl')) and integer(d['amount']),
            'Exposure amounts, save DC, duration and Source CL must be whole numbers.')
    require(d['dc'] <= 100 and d['source_cl'] <= 100 and d['amount'] <= 100000 and d['duration_seconds'] <= 86400,
            'Exposure statistics exceed the native source bounds.')
    require(d.get('duration_kind','seconds') in ('seconds','source_next_start','holder_next_end','current_turn_end'),
            'Choose a native counted duration or its printed turn boundary.')
    require(d['delivery'] != 'damage' or d['category'] in ('acid','poison'), 'Damage must name its actual Acid or Poison portion.')
    require(d['delivery'] != 'poisoned' or d['category'] == 'poison', 'An impending Poisoned exposure must be poison.')
    return r


@hook('journey_options')
def options(session, aid):
    if not owns(session.state['actors'][aid]):
        return None
    r = record(session, aid)
    if r is None:
        return None
    return [{'id':COLLECT,'kind':COLLECT,'payload':{},'auto_select':0,
             'label':f"Record {r['value']['name']} affecting {session.state['actors'][aid]['name']} for native resolution; no Stamina or poison dose is created."}]


@hook('journey_command')
def collect(session, aid, kind, payload):
    if kind != COLLECT:
        return None
    require(owns(session.state['actors'][aid]) and not payload, 'Only an acquired Hundred-Venom practitioner may collect its admitted exposure.')
    r = record(session, aid)
    require(r is not None, 'Record a current exposure through the native table-owner input first.')
    session.state['actors'][aid].setdefault('source_states',{}).setdefault(FAMILY,{}).update({
        'exposure_receipt':r['receipt_id'], 'scene':session.state.get('scene_id',session.state['journey_id'])})
    session.emit('HUNDRED_VENOM_EXPOSURE_COLLECTED',aid,receipt_id=r['receipt_id'],source=FAMILY)
    return True


def source_id(r):
    return 'source:hundred_venom.exposure.' + r['receipt_id']


@hook('journey_combat_bundle')
def project(bundle, session, aid):
    admitted = []
    for subject, actor in session.state['actors'].items():
        if not owns(actor):
            continue
        held = actor.get('source_states',{}).get(FAMILY,{})
        if held.get('scene') != session.state.get('scene_id',session.state['journey_id']):
            continue
        r = record(session, subject)
        if r and held.get('exposure_receipt') == r['receipt_id'] and r['value']['source_actor'] == aid:
            admitted.append(r)
    if not admitted:
        return None
    from ..gate2_runtime_models import ActionDefinition
    b = deepcopy(bundle)
    b[BUNDLE_KEY] = admitted
    b['hundred_venom_exposure_deadlines'] = {source_id(r): int(r['expires_at'] - session.clock()) for r in admitted}
    for r in admitted:
        d = r['value']; src = source_id(r)
        categories = [d['category'], *([] if d['authority'] == 'ordinary' else [d['authority']])]
        duration = {'kind':'rounds','amount':max(1,(d['duration_seconds']+5)//6)}
        condition = {'type':'condition','applies_to':'target','condition':'poisoned' if d['category']=='poison' else 'diseased',
                     'duration':duration,'source_categories':categories}
        kind=d.get('duration_kind','seconds')
        if kind!='seconds':
            condition.pop('duration',None)
            condition['expires_on']={'source_next_start':'START_OF_SOURCE_NEXT_TURN',
                'holder_next_end':'END_OF_HOLDER_NEXT_TURN','current_turn_end':'END_OF_CURRENT_TURN'}[kind]
        if d['authority']=='permanent':
            condition.pop('duration',None)
            condition['expires_on']='UNTIL_REMOVED'
        effects = ([{'type':'damage','applies_to':'target','flat':d['amount'],'damage_types':[d['category']]}] if d['delivery']=='damage'
                   else [{'type':'save','ability':'con','save_categories':categories,'on_fail':[condition],'on_success':[]}] if d['delivery']=='save'
                   else [condition])
        row = ActionDefinition(source_definition_id=src,display_name=d['name']+' — resolve recorded exposure',
              owner_id=aid,economy='NONE',resolution_kind='TYPED',target_kind='ANY_CREATURE',range_ft=120,
              parameters={'free_primary':True,'player_only':True,'typed':{'source':src,'manual_inline_choice':True,
                  'effects':[{'type':'hundred_venom_recorded_exposure','effects':effects}],'numbers':{'cl':d['source_cl'],'save_dc':d['dc'],'pb':b['actor_template'].get('proficiency_bonus',2)},
                  'duration':{'kind':'instant'},'riders':[]}})
        b['action_catalog'].append(row.model_dump(mode='json'))
        b['actor_template']['action_ids'].append(src)
    b.pop('bundle_sha256',None); b['bundle_sha256'] = canonical_sha256(b)
    return b


@hook('candidate_allowed')
def exposure_candidate(engine, actor, candidate, action):
    if action is None:
        return None
    src = action.source_definition_id
    if not src.startswith('source:hundred_venom.exposure.'):
        return None
    bundle = next((b for b in engine.typed_bundle_documents if b['actor_id']==actor.entity_id),{})
    r = next((r for r in bundle.get(BUNDLE_KEY,()) if source_id(r)==src),None)
    return bool(r and (engine.state.round_number-1)*6 < bundle.get('hundred_venom_exposure_deadlines',{}).get(src,0)
                and candidate.target_ids == (r['subject'],) and not any(
        c.condition_id==USE and c.source_definition_id==src for c in actor.conditions.values()))


@effect('hundred_venom_recorded_exposure')
def exposure_used(ctx, row):
    if not ctx.source.startswith('source:hundred_venom.exposure.'):
        raise ValueError('A recorded exposure requires its native source receipt.')
    bundle = next((b for b in ctx.engine.typed_bundle_documents if b['actor_id']==ctx.actor.entity_id),{})
    r = next((r for r in bundle.get(BUNDLE_KEY,()) if source_id(r)==ctx.source),None)
    require(r is not None and ctx.target is not None and ctx.target.entity_id==r['subject'],
            'Resolve the recorded exposure only on its declared creature.')
    require(not any(c.condition_id==USE and c.source_definition_id==ctx.source for c in ctx.actor.conditions.values()),
            'This exposure has already resolved.')
    ctx.engine._apply_condition(ctx.actor,USE,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
                               data={'label':'This recorded exposure has resolved'})
    from ..typed_executor import run_effects
    run_effects(ctx,row['effects'])
