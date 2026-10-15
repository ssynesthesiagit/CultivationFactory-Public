"""Source-instance clinical provenance, shared by Life, Blood and Poison.

Native effects supply classifications through typed clinical metadata; source
categories reuse qi_path.affliction_category. Explicit external sources are
admitted through fact_consent_admission's table-owner boundary. No condition
name, damage type, ally relationship or receipt implies an excluded diagnosis.
All operations address original instances; suppressing never ends their source.
"""
from __future__ import annotations
from copy import deepcopy
import json
from .journey import require, integer

EXCLUDED = {'curse', 'instantaneous', 'missing_limb', 'exhaustion', 'ability_reduction',
            'hp_max_reduction', 'spiritual_binding'}
SUPPRESSION = 'condition:typed.clinical_suppression'


OWNED_SOURCE_ROWS={'PROTECTION_BASE_SUCCOR','DISEASE_BASE_RAISE_THE_QUARANTINE_VEIL',
    'LIFE_BASE_PURIFY_THE_PULSE','POISON_BASE_INGRAIN_THE_TOXIN',
    'BLOOD_BASE_BLOOD_THREAD','BLOOD_BASE_COAGULATE'}


def enabled(engine):
    """Only encounters with admitted clinical consumers opt into provenance."""
    for action in engine.action_catalog.values():
        if action.owner_id not in engine.state.actors:continue
        typed=action.parameters.get('typed') or {}
        if (typed.get('source') in OWNED_SOURCE_ROWS or typed.get('option_of') in OWNED_SOURCE_ROWS
                or str(typed.get('source') or '').startswith('BLOOD_BASE_BLOOD_THREAD.')
                or typed.get('clinical') or action.parameters.get('clinical_protocol') or typed.get('sphere')=='tianxia.sphere.protection'):
            return True
    return False


def metadata(engine, holder, condition, *, retained=False):
    """Read sealed native provenance. Old unclassified saves stay unknown."""
    value = condition.data.get('clinical') or (condition.data.get('clinical_retained_source') if retained else None)
    return deepcopy(value) if isinstance(value, dict) else None


def native_metadata(ctx, subject, effect):
    """Capture actual source identity, concentration instance and reviewed tags."""
    if not enabled(ctx.engine):
        return None
    from .ext.qi_path import affliction_source_metadata
    reviewed = affliction_source_metadata(ctx.engine, ctx.source) or {}
    category = reviewed.get('category', '')
    if not category and ctx.typed.get('sphere') in ('tianxia.sphere.disease','tianxia.sphere.poison'):
        category = 'disease' if ctx.typed['sphere']=='tianxia.sphere.disease' else 'poison'
    supplied = effect.get('clinical') or ctx.typed.get('clinical') or {}
    if not supplied and not category and not reviewed:
        return None
    conc = ctx.actor.concentration
    duration=ctx.typed.get('duration') or {}
    bounded=duration.get('kind') in ('rounds','minutes','hours','days','until_start_of_your_next_turn',
                                   'until_end_of_your_next_turn','until_start_of_next_turn','until_end_of_next_turn')
    ongoing = bool(conc is not None and conc.source_definition_id == ctx.source or bounded)
    zone_id = getattr(ctx, 'damage_cache', {}).get('_clinical_zone_instance')
    zone = ctx.engine.state.zones.get(zone_id) if zone_id else None
    from .stances import active as active_stances
    anchors=[c for c in active_stances(ctx.actor) if c.source_definition_id==ctx.source and c.source_actor_id==ctx.actor.entity_id]
    stance=anchors[0] if len(anchors)==1 else None
    group = (zone.zone_id if zone else stance.instance_id if stance is not None else
             f'{ctx.source}:{ctx.actor.entity_id}:concentration:{conc.started_sequence}' if conc is not None and conc.source_definition_id==ctx.source else
             f'{ctx.source}:{ctx.actor.entity_id}:{ctx.intent.intent_id}' if ctx.intent else
             f'{ctx.source}:{ctx.actor.entity_id}:{ctx.engine.state.event_sequence + 1}')
    return {'source_instance': group, 'source': ctx.source, 'owner': ctx.actor.entity_id,
            'rule': str(ctx.typed.get('source') or ctx.source), 'category': str(supplied.get('category') or category),
            'ongoing': int(bool(zone or stance is not None or ongoing or supplied.get('ongoing'))),
            'excluded': sorted(set(supplied.get('excluded') or []) | (set(reviewed.get('tags', [])) & EXCLUDED)),
            'readers': list(supplied.get('readers') or []), 'private': int(bool(supplied.get('private') or supplied.get('readers'))),
            'label': str(supplied.get('label') or ctx.action.display_name),
            **({'dc': int(ctx.numbers['save_dc'])} if type(ctx.numbers.get('save_dc')) is int and ctx.numbers['save_dc']>0 else {})}


def eligible(engine, holder, viewer, category):
    """Exact known treatable instances; a concealed disease stays concealed."""
    out = []
    seen = set()
    for iid, condition in holder.conditions.items():
        facts = metadata(engine, holder, condition)
        if not facts or not facts.get('selectable',1) or condition.data.get('suppressed') or facts['source_instance'] in seen or set(facts.get('excluded', ())) & EXCLUDED:
            continue
        readers = facts.get('readers') or []
        if facts.get('private') and viewer.entity_id not in readers:
            continue
        name = condition.condition_id.removeprefix('condition:typed.')
        if category == facts['category'] or (category in ('blinded','deafened','paralyzed','poisoned') and name == category):
            seen.add(facts['source_instance'])
            out.append((iid, condition, facts))
    return out


def source_matches(facts,selector):
    """Exact instance or an explicitly admitted canonical source-rule selector.

    A rule selector declares a method appropriate for that printed source; it
    does not declare that an exposure exists, was diagnosed, or was treated.
    """
    return facts.get('rule')==selector[5:] if selector.startswith('rule:') else facts.get('source_instance')==selector


def same_source(holder, facts):
    return [(iid, c) for iid,c in holder.conditions.items()
            if (c.data.get('clinical') or {}).get('source_instance') == facts['source_instance']]


def end(engine, holder, facts, source):
    from .ext.benefit_suppression import discard_retained
    group=facts['source_instance']
    for iid,condition in list(holder.conditions.items()):
        saved=metadata(engine,holder,condition,retained=True) or {}
        if saved.get('source_instance')!=group:continue
        if condition.data.get('clinical_retained_source'):
            discard_retained(engine,holder,iid,source)
            continue
        modifier=condition.data.get('clinical_modifier')
        if modifier:engine._remove_modifier_instance(holder,modifier,source)
        engine._remove_condition_instance(holder,iid,source,expected=condition)
    for iid,c in list(holder.conditions.items()):
        if c.condition_id==SUPPRESSION and c.data.get('source_instance')==group:
            engine._remove_condition_instance(holder,iid,source,expected=c)


def active_suppressions(engine,holder):
    from .ext.effect_durations import parse_round
    now=(int(engine.state.round_number),int(engine.state.current_slot_index))
    return [c for c in holder.conditions.values() if c.condition_id==SUPPRESSION
            and (parse_round(c.expires_on) is None or now < parse_round(c.expires_on))]


def suppress(engine, healer, holder, facts, rounds, source):
    from .ext.effect_durations import round_token
    from .ext.benefit_suppression import suppress as suppress_component
    expiry = round_token(engine, rounds)
    originals = same_source(holder, facts)
    engine._apply_condition(holder, SUPPRESSION, source, healer.entity_id, expires_on=expiry,
        data={'source_instance':facts['source_instance'],'source':facts['source'],'owner':facts['owner'],
              'label':f'A clinical effect is suppressed for {max(1,rounds)} rounds'})
    # Remove manifestations from every mechanical reader while retaining their
    # actual models and original clocks. Companions go first, so native parent
    # cleanup cannot discard a companion before it has been retained.
    originals.sort(key=lambda pair: not bool(pair[1].data.get('companion_of')))
    for iid,c in originals:
        if iid not in holder.conditions:continue
        modifier = c.data.get('clinical_modifier')
        if modifier:
            if modifier in holder.modifiers:
                suppress_component(engine,healer,holder,'modifier:'+modifier,'deadline',source,deadline=expiry)
            engine._update_condition_data(holder,c,{**c.data,'suppressed':1},source)
        else:
            before=set(holder.conditions)
            suppress_component(engine,healer,holder,'condition:'+iid,'deadline',source,deadline=expiry)
            for key in set(holder.conditions)-before:
                kept=holder.conditions[key]
                engine._update_condition_data(holder,kept,{**kept.data,'clinical_retained_source':facts,**({'external_expiry':c.data['external_expiry']} if 'external_expiry' in c.data else {})},source)


def external_value(value):
    require(set(value) == {'label','category','conditions','ongoing','excluded','dc'},
            'Supply a source label, clinical category, conditions, ongoing state, exclusions and DC.')
    require(type(value['label']) is str and bool(value['label'].strip())
            and value['category'] in {'disease','poison','ordinary_bleeding','physical_impairment'}, 'Choose a clinical source category.')
    require(isinstance(value['conditions'],list) and value['conditions']
            and set(value['conditions']) <= {'blinded','deafened','paralyzed','poisoned','bleeding','sickened'}, 'Choose represented source conditions.')
    require(type(value['ongoing']) is int and value['ongoing'] in (0,1)
            and isinstance(value['excluded'],list) and set(value['excluded']) <= EXCLUDED
            and integer(value['dc'],1), 'Supply explicit ongoing state, exclusions and a positive source DC.')
    return deepcopy(value)


def biological_target(engine,owner,subject,*,spiritual_feature=None,spiritual=False):
    """Ordinary Disease/Poison baseline and explicit printed spirit exception.

    Damage type, ability scores and an ally tag establish no anatomy or soul.
    """
    from .physiology import trait
    from .ext.creature_kinds import matches,owns_modifier
    ordinary=trait(subject,'meaningful_biology') is True and not matches(subject,('construct','undead','elemental','spirit'))
    if ordinary:return True
    return bool(spiritual and spiritual_feature and owns_modifier(engine,owner,spiritual_feature)
                and trait(subject,'animating_spirit') is True)
