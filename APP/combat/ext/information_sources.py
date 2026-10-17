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
from ..observer_information import SOURCE, READING

TAGS = frozenset({'illusion','visual_illusion','audible_illusion','possession',
    'spirit_manifestation','concealment','invisible','charmed','frightened',
    'deafened','supernatural_disorientation','temporary_corruption',
    'spirit','incorporeal','possessing_entity','concealed_path','concealed_door',
    'concealed_portal','formation_boundary','asset_suppression','lost',
    'direction_altering_illusion','distance_altering_illusion',
    'concealed_direction_forced_movement','corruption','involuntary_soul_movement'})


def profile(ctx, row):
    spec = row.get('information_profile') or row
    tags = spec.get('tags')
    if not isinstance(tags, list) or not tags or any(not isinstance(t,str) or t not in TAGS for t in tags):
        raise ValueError('Information sources require explicit authored tags')
    ability = spec.get('save_ability')
    if ability is not None and (not isinstance(ability,str) or ability.upper() not in {'STR','DEX','CON','INT','WIS','CHA'}):
        raise ValueError('Information source has an invalid saving throw')
    if any(type(ctx.numbers.get(k)) is not int or ctx.numbers[k]<1 for k in ('cl','save_dc')):
        raise ValueError('Information sources require the native source CL and save DC')
    if any(k in spec and type(spec[k]) is not bool for k in ('full_control','permanent')):
        raise ValueError('Information source permanence and control must be explicit boolean facts')
    authority=spec.get('authority','ordinary')
    if authority not in {'ordinary','protected'}:
        raise ValueError('Information source authority must be ordinary or protected')
    tags=set(tags)
    if tags & {'visual_illusion','audible_illusion'}:tags.add('illusion')
    return {'tags':sorted(tags), 'source_cl':ctx.numbers['cl'],
        'save_dc':ctx.numbers['save_dc'], 'save_ability':ability.upper() if ability else None,
        'full_control':int(bool(spec.get('full_control'))), 'permanent':int(bool(spec.get('permanent'))),
        'authority':authority}


@effect('information_source')
def create_source(ctx, row):
    from ..typed_executor import effect_subjects, effect_expiry
    from ..fact_consent_admission import admit_choice
    from .source_eligibility import catalog_action
    action=catalog_action(ctx.engine,ctx.source)
    if action is None or action.owner_id!=ctx.actor.entity_id:
        raise ValueError('Only the actual native source owner may establish information facts')
    data = profile(ctx, row)
    admission=None
    if row.get('requires_declaration'):
        admission = admit_choice(ctx,ctx.actor,ctx.source,'information_source',
            str(ctx.engine.state.event_sequence)+':'+','.join(data['tags']),['confirm'],
            labels={'confirm':'Confirm this source-scoped fact'},
            prompt=str(row.get('declaration_prompt') or 'Confirm the declared fact for this effect.'),
            expires_on=effect_expiry(ctx,row,ctx.actor,condition=True) or 'UNTIL_REMOVED')
        if not admission:
            return
    for subject in effect_subjects(ctx,row,harmful=bool(row.get('harmful'))):
        ctx.engine._apply_condition(subject,SOURCE,ctx.source,ctx.actor.entity_id,
            expires_on=effect_expiry(ctx,row,subject,condition=True) or 'UNTIL_REMOVED',
            data={'information_profile':data, 'authority_actor_id':ctx.actor.entity_id,
                  'source_id':ctx.source,
                  'declaration_prompt':str(row.get('declaration_prompt') or '') if row.get('requires_declaration') else '',
                  'declaration':int(bool(row.get('requires_declaration'))),
                  'declaration_receipt':admission['receipt_id'] if admission else '',
                  'label':ctx.action.display_name})


@hook('condition_state')
def classify_condition(ctx, subject, row):
    if row.get('information_profile'):
        return {'data':{'information_profile':profile(ctx,row)}}
    return None


@hook('presentation_hidden_conditions')
def private_information(engine,actor):
    return [c.instance_id for c in actor.conditions.values() if c.condition_id in {SOURCE,READING}]


@hook('compile_action')
def declaration_choices(action,info):
    def declares(value):
        if isinstance(value,dict):
            return (value.get('type')=='information_source' and value.get('requires_declaration') is True
                or any(declares(v) for v in value.values()))
        return isinstance(value,list) and any(declares(v) for v in value)
    typed=(action.parameters or {}).get('typed') or {}
    if not declares(typed.get('effects',[])):return None
    return action.model_copy(update={'parameters':{**action.parameters,
        'typed':{**typed,'manual_inline_choice':True}}})


@hook('observer_source_profile')
def native_figment_profile(engine,source,data):
    """Classify an actual created figment, never its name or narration.

    The general image's single sensory channel is unknown when its producer
    did not collect one. Only an explicit minor-detail choice or the native
    sight-and-sound setting establishes those narrower classifications.
    """
    from .source_eligibility import catalog_action
    action=catalog_action(engine,source)
    actual=data.get('placed') or {}
    if not (isinstance(actual,dict) and action is not None and action.parameters.get('figment_kit')
            and actual.get('tag')=='figment' and actual.get('state')=='figment'):return None
    tags=['illusion']
    if actual.get('senses'):tags+=['visual_illusion','audible_illusion']
    elif actual.get('minor') and actual.get('detail')=='image':tags+=['visual_illusion']
    elif actual.get('minor') and actual.get('detail')=='sound':tags+=['audible_illusion']
    result={'tags':tags,'permanent':int(bool(actual.get('permanent'))),'authority':'ordinary',
        'revision_data':{k:actual.get(k,'') for k in ('detail','size_ft','senses','phantasm','controller')}}
    for native,profile_key in (('cl','source_cl'),('save_dc','save_dc')):
        if type(actual.get(native)) is int and actual[native]>0:result[profile_key]=actual[native]
    return result
