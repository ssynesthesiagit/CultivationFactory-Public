"""Source-specific schemas over Soul-Collateral's public world-fact contract.

Consumers: existing material, Gathering, physical-source and threadwork admission
providers. This adapter adds no authority model: both the legacy typed facts
endpoint and native world-facts endpoint commit through declare_world. The
provider still validates and derives its state; a declaration cannot approve a
check or fabricate collection/preparation.
"""
from . import hook,run_strict
SOURCE='system:journey.admission'
KINDS=('material_source','material_source_knowledge','harvest_failure','projection_permission','earth_connection_policy','thread_sleeve','thread_task')


@hook('fact_admission_schema')
def schema(session,source,subject,kind):
    if source!=SOURCE or kind not in KINDS or subject not in session.state['actors']:return None
    return {'value_type':'document','maximum_seconds':1,'authority':'table_owner',
            'visibility':'table_owner','description':'Typed actual site, supply, physical source or ordinary work context.'}


@hook('world_fact_admitted')
def consume(session,record):
    if record['source']!=SOURCE or record['kind'] not in KINDS:return None
    from ..journey import require
    value=record['value']
    require(set(value)=={'payload','provenance'} and isinstance(value['payload'],dict)
            and isinstance(value['provenance'],str) and 0<len(value['provenance'].strip())<=1000,
            'Record typed source details and their actual provenance.')
    responses=run_strict('journey_admission',session,record['subject'],record['kind'],value['payload'],value['provenance'])
    require(sum(reply is True for reply in responses)==1,'This source input needs one native validator and consumer.')
    session.emit('SOURCE_INPUT_COMMITTED',record['subject'],kind_of_fact=record['kind'],receipt_id=record['receipt_id'])
    return True
