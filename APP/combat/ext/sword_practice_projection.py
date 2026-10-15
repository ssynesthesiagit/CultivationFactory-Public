"""Sword learning choices and the printed pre-roll Sword Qi Wave declaration.

TabletopService owns acquisition authority and storage. This source plug-in
owns only Sword's choice validation/projection. Legacy sealed sheets and saved
catalogs without a table acquisition remain unchanged. No combat-time grant is
inferred from an attack name, item, Path resource or declared intent.
"""
from copy import deepcopy
from . import hook
from ..tabletop import TabletopError

SPHERE = 'tianxia.sphere.sword'
HAND = 'SWORD_BASE_SWORD_IN_HAND'
WAVE = 'SWORD_BASE_SWORD_BEYOND_HAND'
DUAL = 'TAL_SWORD_DUAL_PRACTICE'


def body_refiner(sheet):
    identity = sheet.get('identity') or {}
    paths = sheet.get('path_and_subpath') or {}
    return ('tianxia.path.body_refining' in (identity.get('path_ids') or paths.get('path_record_ids') or [])
            or paths.get('path_record_id') == 'tianxia.path.body_refining'
            or str(identity.get('path') or '').lower() == 'body refining')


def projected_grant(choices, info):
    """Validate an explicit outside grant; the table must state its actual rule.

    Appropriate inheritance and another explicit feature are subjective source
    inputs. Only the existing GM acquisition authority may admit those inputs.
    A declaration names the source, its rule text and the exact permission; it
    never silently turns an arbitrary item or a successful attack into a grant.
    """
    grant = choices.get('projection_grant')
    if grant is None:
        return None
    if not isinstance(grant, dict) or set(grant) != {'source_kind', 'source_id', 'rule_text', 'permission'}:
        raise TabletopError('SWORD_PROJECTION_SOURCE', 'Name the source, its kind, its exact rule, and the projected Sword permission.', 400)
    if (grant.get('source_kind') not in ('inheritance', 'feature', 'forged_technique')
            or grant.get('permission') != 'projected_sword'
            or any(not isinstance(grant.get(k), str) or not grant[k].strip() or len(grant[k]) > 4000
                   for k in ('source_id', 'rule_text'))):
        raise TabletopError('SWORD_PROJECTION_SOURCE', 'The projected Sword source declaration is incomplete.', 400)
    if not info.get('gm'):
        raise TabletopError('SWORD_PROJECTION_AUTHORITY', 'The GM must record the explicit projected Sword source rule.', 409)
    return dict(grant)


@hook('acquisition_prepare')
def choose_practice(choices, info):
    if info['record_id'] not in (SPHERE, DUAL, 'tianxia.talent.sword.dual_practice'):
        return None
    if set(choices) - {'practice', 'projection_grant'}:
        raise TabletopError('SWORD_PRACTICE_CHOICE', 'Choose a Sword Practice and, when needed, its explicit projected source.', 400)
    grant = projected_grant(choices, info)
    if info['record_id'] == SPHERE:
        if choices.get('practice') not in ('hand', 'beyond_hand'):
            raise TabletopError('SWORD_PRACTICE_REQUIRED', 'Sword Practice: choose Sword in Hand or Sword Beyond Hand when learning Sword.', 409)
        if body_refiner(info['sheet']) and choices['practice'] == 'beyond_hand' and not grant:
            raise TabletopError('SWORD_BODY_PROJECTION_SOURCE', 'A Body Refiner needs an explicit feature, inheritance or Forged Technique to learn Sword Beyond Hand.', 409)
    return {**choices, **({'projection_grant': grant} if grant else {})}


def selection(sheet):
    acquisitions = [*(sheet.get('source_acquisitions') or []), *(sheet.get('table_acquisitions') or [])]
    row = next((r for r in acquisitions if r.get('id') == SPHERE), None)
    if row is None:
        return None
    choices = row.get('choices') or {}
    practice = choices.get('practice')
    if practice not in ('hand', 'beyond_hand'):
        raise ValueError('Sword Practice is missing from the committed acquisition.')
    grant = choices.get('projection_grant') or next((r.get('choices', {}).get('projection_grant') for r in acquisitions
        if r.get('id') in (DUAL, 'tianxia.talent.sword.dual_practice') and r.get('choices', {}).get('projection_grant')), None)
    block = sheet.get('spheres_and_talents') or {}
    dual = any(k in (block.get('learned_talent_record_ids') or []) for k in (DUAL, 'tianxia.talent.sword.dual_practice'))
    allowed = {HAND} if practice == 'hand' else {WAVE}
    if dual:
        allowed |= {HAND, WAVE}
    if body_refiner(sheet) and not grant:
        allowed.discard(WAVE)
    return allowed


@hook('acquisition_projection')
def project_practice(sheet, document):
    allowed = selection(sheet)
    if allowed is None:
        return None
    out = deepcopy(sheet)
    block = out.setdefault('spheres_and_talents', {})
    for field in ('automatic_sphere_component_record_ids', 'learned_talent_record_ids'):
        block[field] = [key for key in block.get(field) or [] if key not in {HAND, WAVE} or key in allowed]
    return out


@hook('compile_owned_ids')
def seal_practice(ids, info):
    allowed = selection(info['owner_sheet'])
    return None if allowed is None else [k for k in ids if k not in {HAND, WAVE} or k in allowed]


@hook('attack_damage_type_choice')
def wave_damage_type(ctx, attack, target, kinds, attack_index):
    if str(ctx.typed.get('source') or '') != WAVE or ctx.action.owner_id != ctx.actor.entity_id:
        return None
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context
    options = [k for k in ('SLASHING', 'FORCE') if k in kinds]
    chosen = ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, 'sword_wave_type', ctx.actor.entity_id, target.entity_id, attack_index),
        ctx.actor, 'choice:needle.sword_wave_type', options,
        labels={k: k.title() + ' damage' for k in options}, preferred=options[:1],
        name='Sword Qi Wave', feature_id=WAVE, target_id=target.entity_id,
        prompt=f'Sword Qi Wave: choose Slashing or Force damage for your attack against {target.display_name}. No cultivation points.',
        prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target))
    return chosen[0] if chosen else options[0]


@hook('compile_action')
def body_projected_payment(action,info):
    """Body's admitted projected Sword techniques spend Stamina, including multipath.

    A native cultivation-ranged attack is projected; a carried/thrown weapon,
    weapon-delivered technique or natural attack never gains that classification
    from range or item names. Explicit future source typing can also mark the
    projected Practice. No receipt leaves historical builds unchanged.
    """
    sheet=info['owner_sheet']
    allowed=selection(sheet)
    if allowed is None or WAVE not in allowed or not body_refiner(sheet):
        return None
    typed=(action.parameters or {}).get('typed') or {}
    source=typed.get('option_of') or typed.get('source')
    record=info['mechanics'].get(source) or {}
    if record.get('sphere_id')!=SPHERE or typed.get('weapon') or typed.get('delivered_by'):
        return None
    projected=(source==WAVE or typed.get('sword_practice')=='beyond_hand'
               or any(r.get('attack_kind')=='cultivation_ranged' for r in typed.get('effects') or []))
    if not projected:
        return None
    pools={'resource:core.qi','resource:core.resonance'}
    costs=tuple(('resource:core.stamina' if key in pools else key,amount) for key,amount in action.costs)
    return action.model_copy(update={'costs':costs,'parameters':{**action.parameters,
        'typed':{**typed,'sword_practice':'beyond_hand'}}})


@hook('acquisition_choices')
def practice_fields(sheet, kind, record_id):
    if record_id not in (SPHERE,DUAL,'tianxia.talent.sword.dual_practice'):
        return None
    fields=[]
    if record_id==SPHERE:
        fields.append({'path':'practice','label':'Sword Practice','options':[
            {'value':'hand','label':'Sword in Hand — martial expression'},
            {'value':'beyond_hand','label':'Sword Beyond Hand — projected Sword Qi'}]})
    if body_refiner(sheet):
        fields.extend([
            {'path':'projection_grant.source_kind','label':'Explicit projected Sword source (GM records its actual rule)',
             'options':[{'value':v,'label':label} for v,label in [('inheritance','Appropriate inheritance'),('feature','Explicit feature'),('forged_technique','Forged Technique')]]},
            {'path':'projection_grant.source_id','label':'Name or identity of that source','type':'text'},
            {'path':'projection_grant.rule_text','label':'The exact rule permitting projected Sword techniques','type':'textarea'},
            {'path':'projection_grant.permission','value':'projected_sword','type':'hidden'}])
    return fields
