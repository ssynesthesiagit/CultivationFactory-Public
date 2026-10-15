"""Explicit source action classifications for committed-action observers.

Native journey GM admission accepts an action's Magic action / supernatural
classification with provenance. It validates a real learned action; it cannot
create ownership, execute it, grant payment or declare that a trigger occurred.
Snapshots are immutable for an encounter. Authored action metadata may publish
the same profile; unknown sources remain unknown. Used by Set the Scene.
"""
from copy import deepcopy
from . import hook


@hook('journey_admission')
def classify(session,aid,kind,payload,reason):
    if kind!='action_source_fact':return None
    from ..journey import require
    require({'source','action_kind','supernatural'}<=set(payload)<={'source','action_kind','supernatural','thread_severing'} and payload['action_kind'] in ('magic','other')
            and type(payload['supernatural']) is int and payload['supernatural'] in (0,1), 'Record the actual action kind and supernatural classification.')
    require('thread_severing' not in payload or (type(payload['thread_severing']) is int and payload['thread_severing'] in (0,1)), 'Record explicit Qi-thread severance permission as a typed flag.')
    bundle=session.state['actors'][aid]['bundle']
    require(any(a['source_definition_id']==payload['source'] for a in bundle['action_catalog']) or any(r.get('feature_id')==payload['source'] for r in bundle.get('typed_reactions',[]) if r.get('block')=='generic'), 'Classify a real action or reaction this creature owns.')
    session.state['actors'][aid].setdefault('action_source_facts',{})[payload['source']]={**deepcopy(payload),'provenance':reason}
    session.emit('ACTION_SOURCE_FACT',aid,source=payload['source'],reason=reason)
    return True


@hook('journey_persistent_fields')
def fields():return ('action_source_facts',)


@hook('journey_combat_setup')
def snapshot(bundle,session,aid):
    facts=session.state['actors'][aid].get('action_source_facts')
    return {**bundle,'action_source_facts':deepcopy(facts)} if facts else None


def profile(engine,actor,action):
    if action is None or action.owner_id!=actor.entity_id:return {}
    if action.source_definition_id not in actor.action_ids:
        from ..typed_reactions import source_reaction_rows
        if not any(row.get('feature_id')==action.source_definition_id for row in source_reaction_rows(engine,actor)):return {}
    authored=(action.parameters or {}).get('action_source_fact')
    if authored:return authored
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==actor.entity_id),{})
    return bundle.get('action_source_facts',{}).get(action.source_definition_id,{})
