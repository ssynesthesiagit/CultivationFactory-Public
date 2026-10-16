"""GM-authored intrinsic object facts, shared by source-owned object consumers.

Selective public-contract reuse from 74cc00e4:fact_consent_admission.py.
Only the map-object producer/reader is admitted here; no subjective declarations
or world-knowledge consumers are enabled. Facts stay in the sealed battlefield
input, never in public object events or model history.
"""
import copy
import hashlib
import json
from .journey import require
from .ext import query

KEY = "fact_consent_admission"

def public_map_objects(rows):
    """Public rendering geometry without trusted source declarations.

    Used by the table map projection; authored maps and sealed native input
    retain their original declarations. No declarations means unchanged data.
    """
    return [{key: value for key, value in row.items() if key != KEY} for row in rows]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def plain(value, depth=0):
    if depth > 12:
        return False
    if type(value) in (str, int):
        return not isinstance(value, str) or len(value) <= 16000
    if isinstance(value, list):
        return len(value) <= 100 and all(plain(v, depth+1) for v in value)
    if isinstance(value, dict):
        return len(value) <= 100 and all(type(k) is str and plain(v, depth+1) for k,v in value.items())
    return False

def map_object_declarations(value, object_number, *, subject_prefix="map-object"):
    """Validate GM-authored intrinsic object facts before a map is saved.

    Source schemas use the same fact_admission_schema contract with session=None
    and subject='map-object:<number>'. They must explicitly declare authority
    'gm:map'. Facts cannot supply actor willingness or mechanical event receipts.
    Each saved map and its native object genesis retain the exact declaration.
    This pure function returns [] without declarations; no old map is modified.
    """
    require(isinstance(value,list) and len(value)<=16,'An object admits at most sixteen source declarations.')
    result=[]
    for payload in value:
        if isinstance(payload,dict) and 'receipt_id' in payload:
            require(set(payload)=={'source','kind','value','subject','authority','receipt_id'}
                    and payload['authority']=='gm:map' and payload['subject']==f'{subject_prefix}:{object_number}'
                    and payload['receipt_id']==digest({k:v for k,v in payload.items() if k!='receipt_id'}),
                    'The saved object fact failed its authority or commitment check.')
            payload={k:payload[k] for k in ('source','kind','value')}
        require(isinstance(payload,dict) and set(payload)=={'source','kind','value'},
                'Object declarations require source, kind and typed value.')
        source,kind=payload['source'],payload['kind']
        require(all(type(v) is str and 0<len(v)<=240 for v in (source,kind)), 'Use bounded declaration names.')
        subject=f'{subject_prefix}:{object_number}'
        specs=[s for s in query('fact_admission_schema',None,source,subject,kind) if s is not None]
        require(len(specs)==1 and specs[0].get('authority')=='gm:map', 'This source does not admit a GM object declaration.')
        spec=specs[0];typed=payload['value']
        require(spec.get('value_type')=='document' and isinstance(typed,dict) and plain(typed) and len(canonical(typed))<=32000, 'Use the source’s typed object document.')
        validate=spec.get('validate')
        require(callable(validate) and validate(typed), 'The source rejected the object declaration fields.')
        body={**copy.deepcopy(payload),'subject':subject,'authority':'gm:map'}
        body['receipt_id']=digest(body)
        result.append(body)
    require(len({(r['source'],r['kind']) for r in result})==len(result), 'Declare each object fact once.')
    return result


def object_fact(obj, source, kind, *, engine=None):
    """Read a sealed map fact for a real native object, with its commitment.

    The declaration format/validation is the public 74cc00e4 contract. Reading
    the immutable map rather than copying values into OBJECT_UPDATED keeps GM
    inputs out of player/model history. Object results remain ordinary events.
    """
    if engine is None:
        # Preserve the predecessor's public reader for other source consumers.
        declarations = (obj.component or {}).get(KEY, [])
    else:
        # A newly created unattended object is still a legal target. No map
        # declaration for it means unknown vulnerability, never rejection.
        if not obj.object_id.startswith('object:map.'):
            return None
        number = int(obj.object_id.removeprefix('object:map.'))
        subjects = [row for row in (engine.battlefield_document or {}).get('map_objects', [])
                    if int(row['id']) == number]
        require(len(subjects) <= 1, 'The object fact needs one sealed map subject.')
        if not subjects:
            return None
        declarations = map_object_declarations(subjects[0].get(KEY, []), number)
    rows=[r for r in declarations if r['source']==source and r['kind']==kind]
    if not rows:
        return None
    require(len(rows)==1,'Object fact identity is ambiguous.')
    record=rows[0]
    expected='map-object:'+obj.object_id.removeprefix('object:map.')
    require(obj.object_id.startswith('object:map.') and record.get('subject')==expected,
            'The object fact belongs to a different native object.')
    require(record.get('authority')=='gm:map' and record.get('receipt_id')==digest({k:v for k,v in record.items() if k!='receipt_id'}),
            'The object declaration failed its authority or replay commitment check.')
    return copy.deepcopy(record['value'])
