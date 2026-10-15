"""Typed external vocabulary for the five appraisal rows and Read the Sky.

Only printed question-sized facts are admitted; full statistics, formulae,
identities, secret techniques and storage inventories have no input key.
Consumer rules still enforce range, access, checks and question counts.
"""
from . import hook

TEXT = {
 'item.public_name','qi.nature', 'qi.expression', 'qi.ward',
 'trace.nature', 'trace.contents', 'trace.age', 'trace.hand', 'trace.alteration',
 'vessel.safe', 'vessel.resists', 'vessel.nature', 'vessel.bonus', 'vessel.enhancement',
 'poison.kind', 'poison.timing', 'poison.sphere',
 'metal.material', 'metal.nature', 'metal.structure', 'metal.properties',
}
BOOL = {'trace.present','item.visible','item.touchable','qi.impurity', 
 'trace.concealed', 'trace.hostile', 'trace.high_realm',
 'vessel.mandate', 'vessel.backlash', 'poison.burden', 'poison.ingrained', 'poison.present', 'poison.antidote', 'poison.safe',
 'metal.bearing', 'weather.air', 'weather.interference', 'weather.sealed', 'weather.divine', 'weather.narrative'}
SUBJECT_KINDS = {'creature','corpse','meal','ingredient','beast_core','spiritual_dish','residue','container',
 'text','mark','seal','rune','painting','inscription','talisman','formation_mark','ink_mark',
 'object','weapon','armor','tool','construct','vessel','wound','food','drink','sample','terrain','contamination',
 'restraint','gate','lock','bell','ore','mineral','construct_part','formation_node','metal_creature'}

@hook('source_fact_validate')
def validate(key, value, role):
    if role == 'actor' and key not in {'qi.unwilling','qi.concealing'}:
        return False
    if key == 'qi.fallback':
        return isinstance(value,str) and value in {'nourishing','dangerous','both nourishing and dangerous','neither nourishing nor dangerous','unknown'}
    if key in {'qi.suitable','metal.suitable'}:
        if not isinstance(value,dict) or not value or not all(isinstance(k,str) and type(v) is bool for k,v in value.items()):
            return False
        from ..factory_compiler import TYPED_AUTHORITY
        import json
        mechanics=json.loads(TYPED_AUTHORITY.read_bytes())['mechanics']
        sphere='tianxia.sphere.hunger' if key.startswith('qi.') else 'tianxia.sphere.metal'
        return all(mechanics.get(k,{}).get('sphere_id')==sphere and mechanics[k].get('kind')=='talent' for k in value)
    if key=='vessel.exceptional_facts':
        return isinstance(value,dict) and set(value)<={'statistics','secret_technique','owner_identity','command_word','hidden_curse','artifact_history'} and all(isinstance(v,str) and 0<len(v)<=1000 for v in value.values())
    if key in {'trace.tools','vessel.tools'}:
        abilities=('INT','WIS','CHA') if key=='vessel.tools' else ('STR','DEX','CON','INT','WIS','CHA')
        return isinstance(value,dict) and all(isinstance(k,str) and isinstance(v,list) and bool(v) and len(v)==len(set(v)) and all(a in abilities for a in v) for k,v in value.items())
    if key in TEXT:
        return isinstance(value, str) and 0 < len(value) <= 300
    if key in BOOL or key.startswith('weather.vulnerable.') and key.rsplit('.',1)[-1] in ('wind','rain','cold','heat','dry','thunder'):
        return type(value) is bool
    if key.startswith('weather.object_effect.') and key.rsplit('.',1)[-1] in ('wind','rain','cold','heat','dry','thunder'):
        if isinstance(value,str):
            return 0<len(value)<=300
        if not isinstance(value,dict) or not value or set(value)-{'state','damage','destination','ignited'}:
            return False
        if 'state' in value and (not isinstance(value['state'],str) or not 0<len(value['state'])<=300):
            return False
        if 'ignited' in value and type(value['ignited']) is not bool:
            return False
        if 'damage' in value:
            damage=value['damage']
            if not isinstance(damage,dict) or set(damage)!={'amount','type'} or type(damage['amount']) is not int or damage['amount']<0 or damage['type'] not in ('ACID','BLUDGEONING','COLD','FIRE','FORCE','LIGHTNING','NECROTIC','PIERCING','POISON','PSYCHIC','RADIANT','SLASHING','THUNDER'):
                return False
        if 'destination' in value:
            pos=value['destination']
            if not isinstance(pos,dict) or not {'x','y'}<=set(pos) or set(pos)-{'x','y','z'} or any(type(v) is not int or v<0 for v in pos.values()):
                return False
        return True
    if key == 'subject.kind':
        return isinstance(value,str) and value in SUBJECT_KINDS
    if key in {'trace.dc','vessel.dc','vessel.exceptional_threshold','weather.cultivation_cl'}:
        return type(value) is int and 0 <= value <= 1000
    if key == 'qi.defense':
        return value in ('CHA','CON')
    if key == 'weather.origin':
        return isinstance(value, list) and bool(value) and all(isinstance(v,str) for v in value) and len(value) == len(set(value)) and all(
            v in {'natural','supernatural','cultivation-made','concentration'} for v in value)
    if key == 'weather.categories':
        return isinstance(value, dict) and set(value) == {'wind','precipitation','cold','heat','aridity','storm'} and all(type(v) is int and 0 <= v <= 4 for v in value.values())
    if key == 'weather.forecast':
        if not isinstance(value,list) or not value or not all(isinstance(r,dict) and set(r)=={'hour','categories'}
                and type(r['hour']) is int and 0<=r['hour']<=48
                and validate('weather.categories',r['categories'],role) for r in value):
            return False
        return value[0]['hour']==0 and value[-1]['hour']==48 and all(value[i]['hour']<value[i+1]['hour'] for i in range(len(value)-1))
    if key in {'weather.categories_radius_ft','weather.origin_radius_ft','weather.forecast_radius_ft'}:
        return type(value) is int and value >= 0
    return None


@hook('source_fact_context_validate')
def context_validate(key,fact,row,battlefield,actor_ids):
    if key.startswith('weather.object_effect.') and isinstance(fact['value'],dict):
        destination=fact['value'].get('destination')
        if destination:
            return destination['x']<battlefield['width_squares'] and destination['y']<battlefield['height_squares']
    return None


@hook('fact_admission_subjects')
def knowledge_subjects(session,source,kind):
    from ..encounter_sources import SOURCE
    if source!=SOURCE:return None
    battlefield=session.state.get('battlefield',{})
    return ['scene',*[f"object:map.{int(r['id'])}" for r in battlefield.get('map_objects',[])],
            *session.state.get('runtime_objects',{})]


@hook('fact_admission_schema')
def knowledge_schema(session,source,subject,kind):
    from ..encounter_sources import SOURCE
    if source!=SOURCE or session is None:return None
    return {'value_type':'document','lifetime':'scene','maximum_seconds':0,'authority':'table_owner',
        'private_to_table':True,'description':'A question-sized world fact for this actual scene source.'}


@hook('fact_admission_validate')
def knowledge_value(session,source,subject,kind,value):
    from ..encounter_sources import SOURCE,validate_fact
    if source!=SOURCE:return None
    import json
    if not isinstance(value,dict) or set(value)!={'fact'} or not isinstance(value['fact'],str):return False
    try:
        validate_fact(kind,json.loads(value['fact']),subject,session.state['battlefield'],tuple(session.state['actors']))
    except (ValueError,TypeError):return False
    return True


@hook('match_start')
def knowledge_native_inputs(engine):
    if getattr(engine,'scene_mode',False):return
    from ..encounter_sources import admit_setup
    admit_setup(engine)


@hook('journey_initialized')
def knowledge_journey_inputs(session):
    from ..encounter_sources import admit_setup
    admit_setup(session)


@hook('journey_combat_battlefield')
def current_world_inputs(battlefield,session):
    from ..encounter_sources import SOURCE
    from ..fact_consent_admission import KEY,world_records
    import json
    pairs={(r['subject'],r['scope']) for r in session.state.get(KEY,[]) if r['source']==SOURCE}
    if not pairs and not battlefield.get('encounter_sources'):return None
    rows=[]
    for subject,scope in sorted(pairs):
        active=world_records(session,SOURCE,subject,scope)
        if active:rows.append({'subject_id':subject,'scope':scope,'facts':{k:json.loads(r['value']['fact']) for k,r in active.items()}})
    return {**battlefield,'encounter_sources':rows}


@hook('fact_admission_scope_validate')
def knowledge_scope(session,source,subject,kind,scope,value):
    from ..encounter_sources import SOURCE
    if source!=SOURCE:return None
    if scope=='scene':
        if kind!='subject.kind' or subject not in session.state['actors']:return True
        import json
        try:corpse=json.loads(value['fact'])['value']=='corpse'
        except (ValueError,TypeError,KeyError):return False
        if not corpse:return True
        if hasattr(session,'engine'):engine=session.engine
        else:
            from ..native_scene import engine_for
            engine=engine_for(session)
        from .life_state import is_deceased
        return is_deceased(engine.state.actors[subject])
    if not scope.startswith('item:') or subject not in session.state['actors']:return False
    from ..carry import carrying_of,item_of
    if hasattr(session,'engine'):engine=session.engine
    else:
        from ..native_scene import engine_for
        engine=engine_for(session)
    return item_of(carrying_of(engine,subject),key=scope[5:]) is not None
