"""Sight-only Search extends the existing compiled Search action and numbers."""
from copy import deepcopy
from . import hook


@hook('match_initialize')
def sight_search_action(engine):
    if (getattr(engine,'battlefield_document',None) or {}).get('ambient_illumination') is None:
        return
    for actor in engine.state.actors.values():
        for aid in actor.action_ids:
            action=engine.action_catalog.get(aid)
            if action is None:continue
            typed=(action.parameters or {}).get('typed') or {}
            if not any(row.get('type')=='search' for row in typed.get('effects',())):continue
            parameters=deepcopy(action.parameters)
            parameters['typed']['effects']=[{**row,'sight_only':True} if row.get('type')=='search' else row
                for row in parameters['typed']['effects']]
            parameters['sight_search']=True
            engine.action_catalog[aid+'.sight']=action.model_copy(update={'source_definition_id':aid+'.sight',
                'display_name':'Search by sight','parameters':parameters})


@hook('additional_actions')
def offer_sight_search(engine,actor):
    from ..stealth import can_search
    if can_search(engine,actor):
        return [sid for sid,a in engine.action_catalog.items() if a.owner_id==actor.entity_id and a.parameters.get('sight_search')]
