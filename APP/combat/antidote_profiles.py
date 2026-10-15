"""Public Antidote Profile memory, shared by appraisal and poison consumers.

Profiles are private diagnoses, not physical antidotes. Slots enforce the
printed PB cap. The existing native observer envelope and condition events own
persistence; elapsed scenes use that same envelope and an actual Long Rest.
"""
from copy import deepcopy
from .observer_information import publish,readings,readings_journey,publish_journey


def dismiss_source(engine, reader, slot):
    return next((a.source_definition_id for a in engine.action_catalog.values() if a.owner_id==reader.entity_id
        and a.parameters.get('antidote_profile_slot')==slot),'')


def instances(reader):
    return [c for c in reader.conditions.values() if c.data.get('kind')=='declaration'
        and c.data.get('details',{}).get('ability')=='Antidote Profile'
        and c.data.get('viewer_id')==reader.entity_id]


def profiles(engine, reader):
    return [deepcopy(c.data['details']) for c in instances(reader)]


def dismiss(engine,reader,slot,source):
    from .ext.condition_ownership import remove_instance
    for held in list(instances(reader)):
        if held.data['details']['slot']==slot:
            remove_instance(engine,reader,held.instance_id,source)


def create(ctx, subject_id):
    engine,reader,source_id=ctx.engine,ctx.actor,ctx.action.source_definition_id
    diagnosis=next((r['details'] for r in reversed(readings(engine,reader)) if r.get('kind')=='answer'
        and r.get('source_id')==source_id and r.get('details',{}).get('subject_id')==subject_id),None)
    if diagnosis is None:
        raise ValueError('An Antidote Profile requires the actual appraisal answer.')
    old=next((r for r in profiles(engine,reader) if r['subject_id']==subject_id),None)
    used={r['slot'] for r in profiles(engine,reader)}
    slot=old['slot'] if old else next((n for n in range(reader.proficiency_bonus) if n not in used),None)
    if slot is None:
        from .ext.needle import ask,checkpoint_id,CHOICE
        labels={'cancel':'Keep your current profiles'}
        labels.update({str(r['slot']):'Dismiss profile for '+r.get('subject_name','the examined source') for r in profiles(engine,reader)})
        chosen=ask(engine,ctx.intent,checkpoint_id(engine,'ANTIDOTE_PROFILE_CAP',reader.entity_id),reader,
            CHOICE+'antidote_profile_replace',list(labels),labels=labels,preferred=['cancel'],allow_decline=True,
            name='Antidote Profile',feature_id='Antidote Profile',
            prompt=f'You can keep {reader.proficiency_bonus} Antidote Profiles until your Long Rest. Dismiss one to keep this new profile, or keep the current profiles.')
        if not chosen or chosen[0]=='cancel':
            return False
        slot=int(chosen[0])
    dismiss(engine,reader,slot,source_id)
    publish(engine,reader,source_id,reader,'declaration',{'ability':'Antidote Profile','subject_id':subject_id,
        'subject_name':diagnosis.get('subject_name','the examined source'),'answers':deepcopy(diagnosis['answers']),
        'slot':slot,'expires_after_long_rest':1,'dismiss_action_id':dismiss_source(engine,reader,slot)},'UNTIL_REMOVED')
    return True


def profiles_journey(session, aid):
    return [deepcopy(r['details']) for r in readings_journey(session,aid) if r['kind']=='declaration'
        and r['details'].get('ability')=='Antidote Profile']


def create_journey(session,aid,source,subject,answers,replace_slot=None):
    actor=session.state['actors'][aid]
    cap=int(actor['bundle']['actor_template']['proficiency_bonus'])
    current=profiles_journey(session,aid)
    old=next((r for r in current if r['subject_id']==subject),None)
    slot=old['slot'] if old else next((n for n in range(cap) if n not in {r['slot'] for r in current}),None)
    if slot is None:
        from .journey import require
        require(type(replace_slot) is int and replace_slot in {r['slot'] for r in current},'Choose a profile to dismiss before keeping another; your limit is your Proficiency Bonus.')
        slot=replace_slot
    dismiss_journey(session,aid,slot)
    publish_journey(session,aid,source,'declaration',{'ability':'Antidote Profile','subject_id':subject,
        'answers':deepcopy(answers),'slot':slot,'expires_after_long_rest':1})


def dismiss_journey(session,aid,slot):
    actor=session.state['actors'][aid]
    actor['observer_information']=[r for r in actor.get('observer_information',[]) if not (r['kind']=='declaration'
        and r['details'].get('ability')=='Antidote Profile' and r['details'].get('slot')==slot)]

    import json
    snapshot=actor.get('encounter_snapshot')
    if snapshot:
        snapshot['conditions']={key:encoded for key,encoded in snapshot.get('conditions',{}).items()
            if not (json.loads(encoded).get('data',{}).get('details',{}).get('ability')=='Antidote Profile'
                    and json.loads(encoded)['data']['details'].get('slot')==slot)}
