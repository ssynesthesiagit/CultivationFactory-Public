"""Native declaration intent transport; schemas/consumers own their Source Rules."""
from . import hook
from ..fact_consent_admission import declare


@hook('journey_command')
def admission_command(session, actor_id, kind, payload):
    if kind != 'declare_fact':
        return None
    declare(session,actor_id,payload)
    return True


@hook('presentation_hidden_conditions')
def private_declarations(engine,actor):
    from ..fact_consent_admission import CONDITION
    return [c.instance_id for c in actor.conditions.values() if c.condition_id==CONDITION]


@hook('fact_admission_schema')
def native_scene_owner_schema(session,source,subject,kind):
    """Second production consumer: the native table-owner scene boundary.

    This is system authority over this persisted scene, never a creature's
    ability grant or private consent. Merely declaring this fact cannot end the
    scene; JourneyStore.end_scene owns that mechanical operation.
    """
    if source!='system:journey.scene' or kind!='scene_end' or subject not in session.state['actors']:return None
    return {'value_type':'text','maximum_seconds':1,'authority':'table_owner',
        'description':'The native table owner records why this meaningful scene ended.'}


@hook('journey_combat_bundle')
def snapshot_world_inputs(bundle,session,actor_id):
    """Seal the existing admitted history, not a second source/fact schema."""
    from copy import deepcopy
    from ..fact_consent_admission import read,KEY
    latest={}
    for row in session.state.get(KEY,()):
        if row.get('authority')=='table_owner':
            latest[(row['source'],row['subject'],row['kind'],row['scope'])]=row
    if not latest:
        return None
    selected=[]
    for row in latest.values():
        current=read(session,row['source'],row['subject'],row['kind'],row['scope'],row['subject'])
        # Retain expired latest records as negative knowledge; never revive an
        # older fact from a prior encounter's permanent private-history record.
        selected.append(deepcopy(current or row))
    existing={r['receipt_id']:r for r in bundle.get('scene_field_facts',())}
    existing.update({r['receipt_id']:r for r in selected})
    return {**bundle,'scene_field_facts':list(existing.values()),
        'scene_field_clock':{'num':session.clock().numerator,'den':session.clock().denominator},
        'scene_field_sequence_floor':max((r['sequence'] for r in session.state.get(KEY,())),default=0)}


@hook('journey_encounter_settled')
def retain_world_inputs(session,actor_id,engine,actor):
    from copy import deepcopy
    from ..combat_world_facts import records
    from ..fact_consent_admission import KEY
    incoming=[r for r in records(engine) if r['subject']==actor_id and r.get('authority')=='table_owner']
    if not incoming:return
    history=session.state.setdefault(KEY,[])
    existing={r['receipt_id'] for r in history}
    history.extend(deepcopy(r) for r in incoming if r['receipt_id'] not in existing)
    history.sort(key=lambda r:r['sequence'])


@hook('presentation_hidden_conditions')
def private_world_inputs(engine,actor):
    from ..combat_world_facts import HISTORY
    return [iid for iid,c in actor.conditions.items() if c.condition_id==HISTORY] or None


@hook('presentation_hidden_history_conditions')
def private_world_input_history(events):
    from ..combat_world_facts import HISTORY
    return [e.payload['instance_id'] for e in events if not isinstance(e,dict)
            and e.payload.get('condition_id')==HISTORY and e.payload.get('instance_id')] or None
