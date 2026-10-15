"""Source-specific Path/expression gates over native acquisition and permission.

Uses the existing sealed physical_source_facts projection contract for external
body-script practice or explicitly permitted Body Qi Thread. A resource pool,
team, damage name or broad sphere tag cannot supply these external facts.
This module does not grant a sphere, talent, item or source acquisition.
"""
from . import hook
from .ability_source import mechanic_of
from .ink_base_actions import LIVING,LASH,PRESS
from .thread_base_line import DRAW
INK={LIVING,LASH,PRESS}


@hook('compile_bundle')
def policy(bundle,info):
    if not set(info['owned_ids']) & (INK|{DRAW}):return None
    from ..factory_compiler import RESOURCE_IDS
    return {**bundle,'scoped_source_access':{'body':int(info.get('primary')=='stamina'),
        'cp_resource':RESOURCE_IDS.get(info.get('primary'),'')}}


def access(engine,actor,source,*,qi=False):
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==actor.entity_id),{})
    policy=bundle.get('scoped_source_access')
    if not policy or not policy['body']:return True
    from .physical_source_facts import projected
    if source in INK:return bool(projected(engine,actor.entity_id,source))
    if source==DRAW and qi:return projected(engine,actor.entity_id,DRAW)
    return True


@hook('candidate_allowed')
def source_gate(engine,actor,candidate,action):
    if action is None:return None
    source=mechanic_of(action)
    if source not in INK|{DRAW}:return None
    return None if access(engine,actor,source,qi=bool(action.parameters.get('thread_twin',{}).get('qi'))) else False


def scene_access(session,aid,source,*,qi=False):
    from types import SimpleNamespace
    actor=SimpleNamespace(entity_id=aid)
    bundle=session.state['actors'][aid]['bundle']
    facts=session.state['actors'][aid].get('physical_source_facts')
    document={**bundle,**({'physical_source_facts':facts} if facts else {})}
    return access(SimpleNamespace(typed_bundle_documents=[document]),actor,source,qi=qi)


def spend_cp(session,aid,source,amount=1):
    from ..journey import require
    actor=session.state['actors'][aid]
    pool=actor['bundle'].get('scoped_source_access',{}).get('cp_resource')
    require(type(amount) is int and amount>0 and pool and actor['resources'].get(pool,0)>=amount,
        'This source requires available Cultivation Points from your actual primary Path pool.')
    actor['resources'][pool]-=amount
    session.emit('SOURCE_RESOURCE_SPENT',aid,source=source,resource=pool,amount=amount)
