"""Typed external vocabulary for the five appraisal rows and Read the Sky.

Only printed question-sized facts are admitted; full statistics, formulae,
identities, secret techniques and storage inventories have no input key.
Consumer rules still enforce range, access, checks and question counts.
"""
from . import hook

TEXT = {
 'qi.nature', 'qi.expression', 'qi.ward',
 'trace.nature', 'trace.contents', 'trace.age', 'trace.hand', 'trace.alteration',
 'vessel.safe', 'vessel.resists', 'vessel.nature', 'vessel.bonus', 'vessel.enhancement',
 'poison.kind', 'poison.timing', 'poison.sphere',
 'metal.material', 'metal.nature', 'metal.structure', 'metal.properties',
}
BOOL = {'qi.impurity', 'qi.unwilling', 'qi.concealing',
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
        return isinstance(value,dict) and all(isinstance(k,str) and isinstance(v,list) and bool(v) and all(a in ('STR','DEX','CON','INT','WIS','CHA') for a in v) for k,v in value.items())
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
    if key=='subject.kind' and fact['value']=='corpse' and row['subject_id'] in actor_ids:
        return False  # a live genesis creature is not an authored corpse object
    if key.startswith('weather.object_effect.') and isinstance(fact['value'],dict):
        destination=fact['value'].get('destination')
        if destination:
            return destination['x']<battlefield['width_squares'] and destination['y']<battlefield['height_squares']
    return None
