"""Coagulate's recipient consent.

Extends the existing typed options, source-owned Thread gate and Life-state
stabilization rather than supplying a second ability. compile_action wraps
only Coagulate's owned options in the public willing_targets consent effect;
its any-creature compiler retains both allied and hostile willing recipients.
The native compile_actions phase precedes compile_action transforms, so the
hostile sibling is built explicitly through the same public helper. The later
transform is idempotent and preserves the already wrapped sibling.
No new engine hook or persisted state. Unknown circulation is not inferred.
"""
import copy

from . import hook

COAGULATE = "BLOOD_BASE_COAGULATE"


@hook("compile_action")
def coagulate_consent(action, info):
    original = (action.parameters or {}).get("typed") or {}
    if (original.get("option_of") or original.get("source")) != COAGULATE:
        return None
    if any(row.get("type") == "choose_willing" for row in original.get("effects") or []):
        return None
    parameters = copy.deepcopy(action.parameters or {})
    typed = parameters.get("typed") or {}
    rows = typed.get("effects") or []
    gate = [row for row in rows if row.get("type") == "requires_thread"]
    benefits = [row for row in rows if row.get("type") != "requires_thread"]
    for row in benefits:
        if row.get('type')=='remove_condition' and row.get('condition')=='bleeding':
            row.update(type='clinical_treatment',category='ordinary_bleeding',operation='end')
    typed['manual_inline_choice']=True
    typed["effects"] = gate + [{
        "type": "choose_willing", "target_only": True, "allow_hostile_target": True,
        "range_ft": 30, "effects": benefits, "variant_suffix": " (any creature)",
        "consent_text": "The caster spends a Bonus Action and 1 CP (Cultivation Point) on this Coagulate treatment. "
                        "You must bear their Blood Thread. The treatment takes effect immediately; refusing grants no benefit.",
    }]
    return action.model_copy(update={"parameters": parameters})


@hook("compile_actions")
def coagulate_willing_non_allies(info):
    """Add willing hostile recipients before the late per-action transform.

    Original allied actions are transformed by compile_action. Existing
    already-consented authority rows remain the generic willing hook's job.
    """
    from .willing_targets import willing_non_allies

    prepared = [made for action in info["actions"]
                if (made := coagulate_consent(action, info)) is not None]
    return willing_non_allies({**info, "actions": prepared}) or None

@hook('compile_actions')
def unwilling_allied_thread(info):
    result=[]
    for action in info.get('actions') or []:
        typed=action.parameters.get('typed') or {}
        if typed.get('source')=='BLOOD_BASE_BLOOD_THREAD' and action.target_kind=='HOSTILE_ENTITY':
            result.append(action.model_copy(update={'source_definition_id':action.source_definition_id+'#allied',
                'display_name':action.display_name+' (any creature)', 'target_kind':'ANY_CREATURE'}))
        if typed.get('source')=='POISON_BASE_INGRAIN_THE_TOXIN' and action.target_kind=='HOSTILE_ENTITY':
            result.append(action.model_copy(update={'source_definition_id':action.source_definition_id+'#allied',
                'display_name':action.display_name+' (any creature)', 'target_kind':'ANY_CREATURE'}))
    return result or None


@hook('compile_action')
def thread_recipient_answer(action,info):
    params=copy.deepcopy(action.parameters or {}); typed=params.get('typed') or {}
    if typed.get('source')!='BLOOD_BASE_BLOOD_THREAD':return None
    rows=typed.get('effects') or []
    if not any(r.get('type')=='attack' for r in rows):return None
    typed['manual_inline_choice']=True
    typed['effects']=[{'type':'blood_thread_attempt','effects':rows}]
    return action.model_copy(update={'parameters':params})


from . import effect

@effect('blood_thread_attempt',harmful=True)
def thread_attempt(ctx,row):
    """The recipient's answer selects automatic Thread or the printed attack."""
    if ctx.typed.get('source')!='BLOOD_BASE_BLOOD_THREAD' or ctx.target is None:return
    from .willing_targets import asks_consent
    from ..typed_executor import run_effects
    target=ctx.target
    willing=target is ctx.actor or asks_consent(ctx.engine,ctx.intent,target,'Blood Thread',
        f'{ctx.actor.display_name} uses Blood Thread on {target.display_name}. Accept a harmless Thread for 1 minute? '
        'Refusing requires the caster to make the printed ranged Cultivation Attack; a hit deals Piercing or Necrotic damage and applies a shorter Thread.',
        prefer_accept=target.team_id==ctx.actor.team_id,asker=ctx.actor)
    if willing:
        run_effects(ctx,[{'type':'mark','mark':'Blood Thread','applies_to':'target','duration':{'kind':'minutes','amount':1}}])
    else:
        from .needle import ask,checkpoint_id,CHOICE
        chosen=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'blood_thread_damage',target.entity_id),ctx.actor,
            CHOICE+'blood_thread_damage',['piercing','necrotic'],labels={'piercing':'Piercing','necrotic':'Necrotic'},
            preferred=['piercing'],prompt=f'Blood Thread: choose Piercing or Necrotic damage before attacking {target.display_name}.')
        rows=copy.deepcopy(row['effects'])
        def seal(items):
            for item in items:
                if item.get('type') in ('damage','extra_damage') and set(item.get('damage_types') or [])=={'piercing','necrotic'}:item['damage_types']=(chosen or ['piercing'])
                for key in ('effects','on_hit','on_fail','on_success'):seal(item.get(key) or [])
        seal(rows)
        run_effects(ctx,rows)


@hook('compile_action')
def any_willing_blood_recipient(action,info):
    typed=action.parameters.get('typed') or {}
    source=str(typed.get('source') or '')
    if (COAGULATE in (source,typed.get('option_of')) or source.startswith('BLOOD_BASE_BLOOD_THREAD')) and action.source_definition_id.endswith('#willing_non_ally'):
        return action.model_copy(update={'target_kind':'ANY_CREATURE'})
    return None
