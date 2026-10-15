"""Antidote Profile capacity, free dismissal and actual Long Rest expiry."""
from . import hook,effect
from ..antidote_profiles import profiles,dismiss,profiles_journey,dismiss_journey
from .knowledge_readings import VENOM


@hook('compile_actions')
def dismissal_actions(info):
    if VENOM not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.antidote_profile.dismiss.{slot}",
        display_name=f'Dismiss Antidote Profile {slot+1} (no action)',owner_id=info['actor_id'],economy='NONE',
        resolution_kind='TYPED',target_kind='SELF',parameters={'setting_only':True,'player_only':True,
            'antidote_profile_slot':slot,'typed':{'source':VENOM+'#dismiss_profile','numbers':info['numbers'],
            'effects':[{'type':'dismiss_antidote_profile','slot':slot}],'riders':[],'duration':{'kind':'instant'}}})
        for slot in range(info['pb'])]


@hook('settings_batch_key')
def dismissal_key(action):
    if 'antidote_profile_slot' in (getattr(action,'parameters',None) or {}):
        return ('antidote_profile',int(action.parameters['antidote_profile_slot']))


@hook('candidate_allowed')
def dismissal_available(engine,actor,candidate,action):
    if 'antidote_profile_slot' in (getattr(action,'parameters',None) or {}):
        return any(p['slot']==action.parameters['antidote_profile_slot'] for p in profiles(engine,actor))


@effect('dismiss_antidote_profile')
def discard(ctx,row):
    dismiss(ctx.engine,ctx.actor,int(row['slot']),ctx.source)


@hook('journey_options')
def journey_dismissals(session,aid):
    return [{'id':'dismiss_profile:'+str(r['slot']),'kind':'dismiss_antidote_profile','auto_select':0,
        'payload':{'slot':r['slot']},'label':'Dismiss Antidote Profile '+str(r['slot']+1)+' (no action)'}
        for r in profiles_journey(session,aid)]


@hook('journey_command')
def journey_discard(session,aid,kind,payload):
    if kind!='dismiss_antidote_profile':
        return None
    from ..journey import require
    require(set(payload)=={'slot'} and type(payload['slot']) is int and any(p['slot']==payload['slot'] for p in profiles_journey(session,aid)), 'Choose one of your Antidote Profiles.')
    dismiss_journey(session,aid,payload['slot'])
    session.emit('ANTIDOTE_PROFILE_DISMISSED',aid,slot=payload['slot'])
    return True


@hook('journey_rest')
def rest(session,aid):
    for p in profiles_journey(session,aid):
        dismiss_journey(session,aid,p['slot'])
    # A resumed encounter snapshot may also carry the same source's native
    # private condition. Remove that memory after the real eight-hour rest.
    import json
    snapshot=session.state['actors'][aid].get('encounter_snapshot')
    if snapshot:
        snapshot['conditions']={key:row for key,row in snapshot.get('conditions',{}).items()
            if json.loads(row).get('data',{}).get('details',{}).get('ability')!='Antidote Profile'}
