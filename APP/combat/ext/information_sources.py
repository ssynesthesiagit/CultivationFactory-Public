"""General native information producers; no opt-in means no behavior.

Reviewed ``information_source`` effect: tags (list of exact classifications),
save_ability, full_control, permanent, authority and duration describe this
source's real ongoing effect. source_cl/save_dc are derived from the creating
Context, never from player answers. ``requires_declaration`` asks the source
owner to confirm a subjective fact through Needle, including on AI turns;
AI cannot invent that fact. Missing consent creates no source.
Existing typed conditions can opt into the same profile using
``information_profile``. Both paths persist through ordinary conditions.
"""
from . import effect, hook
from ..observer_information import SOURCE


def profile(ctx, row):
    spec = row.get('information_profile') or row
    tags = spec.get('tags')
    if not isinstance(tags, list) or not tags or any(not isinstance(t,str) or not t for t in tags):
        raise ValueError('Information sources require explicit authored tags')
    ability = spec.get('save_ability')
    if ability is not None and ability.upper() not in {'STR','DEX','CON','INT','WIS','CHA'}:
        raise ValueError('Information source has an invalid saving throw')
    return {'tags':sorted(set(tags)), 'source_cl':int(ctx.numbers.get('cl') or 1),
        'save_dc':int(ctx.numbers.get('save_dc') or 10), 'save_ability':ability,
        'full_control':int(bool(spec.get('full_control'))), 'permanent':int(bool(spec.get('permanent'))),
        'authority':str(spec.get('authority') or 'ordinary')}


@effect('information_source')
def create_source(ctx, row):
    from ..typed_executor import effect_subjects, effect_expiry
    from .rider_choices import pick
    data = profile(ctx, row)
    if row.get('requires_declaration'):
        answer = pick(ctx.engine, ctx.actor, 'information_declaration', ctx.action.display_name,
            ['confirm'], subject=ctx.actor, automatic=False, optional=True,
            labels={'confirm':'Confirm this source-scoped fact'},
            prompt=str(row.get('declaration_prompt') or 'Confirm the declared fact for this effect.'))
        if not answer:
            return
    for subject in effect_subjects(ctx,row,harmful=bool(row.get('harmful'))):
        ctx.engine._apply_condition(subject,SOURCE,ctx.source,ctx.actor.entity_id,
            expires_on=effect_expiry(ctx,row,subject,condition=True) or 'UNTIL_REMOVED',
            data={'information_profile':data, 'authority_actor_id':ctx.actor.entity_id,
                  'declaration':int(bool(row.get('requires_declaration'))),
                  'label':ctx.action.display_name})


@hook('condition_state')
def classify_condition(ctx, subject, row):
    if row.get('information_profile'):
        return {'data':{'information_profile':profile(ctx,row)}}
    return None


@hook('presentation_hidden_conditions')
def private_readings(engine, subject):
    from ..observer_information import READING
    return [c.instance_id for c in subject.conditions.values() if c.condition_id == READING]


@hook('journey_combat_setup')
def carry_observations(session,aid):
    from copy import deepcopy
    rows=[deepcopy(row) for row in session.state['actors'][aid].get('observer_information',[])
        if row.get('expires_at') is None or session.state['seconds']<row['expires_at']]
    return {'observer_information':rows,'observer_scene_seconds':session.state['seconds']} if rows else None


@hook('match_initialize')
def restore_observations(engine):
    from ..observer_information import publish
    from .effect_durations import round_token
    for bundle in getattr(engine,'typed_bundle_documents',()):
        setup=bundle.get('journey_setup',{})
        viewer=engine.state.actors.get(bundle['actor_id'])
        if viewer is None:
            continue
        for row in setup.get('observer_information',[]):
            if row.get('viewer_id')!=viewer.entity_id:
                raise ValueError('A transferred reading must belong to its native observer.')
            remaining=None if row.get('expires_at') is None else row['expires_at']-setup['observer_scene_seconds']
            if remaining is not None and remaining<=0:
                continue
            owner=engine.state.actors.get(row['authority_actor_id'])
            if owner is None:
                raise ValueError('A transferred reading needs its source owner in the native scene.')
            expiry='UNTIL_REMOVED' if remaining is None else round_token(engine,(remaining+5)//6)
            publish(engine,viewer,row['source_id'],owner,row['kind'],row['details'],expiry)
