"""Sight-only Search extends the existing compiled Search action and numbers.

Registered at the documented ``match_start`` seam, which runs once for every
engine build -- a fresh fight and a reloaded save alike (combat/ext/__init__.py).
Registration reads the action catalog, never the live roster: a saved fight is
loaded by building an engine from its typed bundles and only then installing the
saved state, so at ``match_start`` the roster is still the constructor's default
one. Every compiled Search belongs to exactly one owner and ``additional_actions``
offers a fighter only its own variant, so the derived entries stay inert for
characters that do not own the printed Search.
"""
from copy import deepcopy
from . import hook


@hook('match_start')
def sight_search_action(engine):
    if (getattr(engine,'battlefield_document',None) or {}).get('ambient_illumination') is None:
        return
    for aid,action in list(engine.action_catalog.items()):
        parameters=action.parameters or {}
        if parameters.get('sight_search') or not action.owner_id:continue
        typed=parameters.get('typed') or {}
        if not any(row.get('type')=='search' for row in typed.get('effects',())):continue
        derived=deepcopy(parameters)
        derived['typed']['effects']=[{**row,'sight_only':True} if row.get('type')=='search' else row
            for row in derived['typed']['effects']]
        derived['sight_search']=True
        engine.action_catalog[aid+'.sight']=action.model_copy(update={'source_definition_id':aid+'.sight',
            'display_name':'Search by sight','parameters':derived})


@hook('additional_actions')
def offer_sight_search(engine,actor):
    from ..stealth import can_search
    if can_search(engine,actor):
        return [sid for sid,a in engine.action_catalog.items() if a.owner_id==actor.entity_id and a.parameters.get('sight_search')]
