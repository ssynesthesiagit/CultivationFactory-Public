"""Native Foundation Mantra selection, maintenance and Resonant benefits.

One activity owns the chosen mode. Trigger riders consume real committed Qi
damage/save results, never inferred participant flags or unconditional modifiers.
All choices use the source owner's transport, including off-turn activations.
"""
from dataclasses import replace
from contextlib import contextmanager
from . import effect, hook
from . import maintained_activity as activity

PREFIX = 'tianxia.subpath.qi.mantra_cultivator.feature.'
FOUNDATION = PREFIX + 'three_foundation_mantras'
RESONANT = PREFIX + 'resonant_chanting'
CHANNEL = 'foundation_mantra'


def turn_stamp(engine):
    s = engine.state
    a = s.actors.get(s.current_actor_id)
    return f'{s.round_number}:{s.current_actor_id}:{a.turns_started if a else 0}'


def mode(engine, actor):
    c = activity.active(engine, actor, CHANNEL)
    return c.data['mode'] if c else None


def resonant(engine, actor):
    from .activation_requirements import effective_cl
    c = activity.current(actor, CHANNEL)
    if c is None or effective_cl(actor, c.data.get('available_cl',c.data['source_cl'])) < 6:
        return False
    return any(a.parameters.get('mantra_resonant') for aid in actor.action_ids
               if (a := engine.action_catalog.get(aid)) is not None)


@hook('compile_actions')
def actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .path_numbers import numbers_for
    owned = info['owned_ids']
    numbers = numbers_for(info, 'tianxia.path.qi_cultivation')
    dismissal = []
    if any(key in owned for key in (PREFIX + 'great_mantra', PREFIX + 'mantra_of_silence')):
        dismissal.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.mantra.end_concentration",
            display_name='End Concentration', owner_id=info['actor_id'], economy=EconomyKind.NONE,
            resolution_kind='TYPED', target_kind='SELF', parameters={'mantra_end_concentration':True,
                'typed': {'source': FOUNDATION, 'numbers': numbers, 'riders': [], 'duration': {'kind':'instant'},
                          'effects':[{'type':'mantra_end_concentration'}]}}))
    if FOUNDATION not in owned or int(numbers['cl']) < 3:
        return dismissal or None
    enhanced = RESONANT in owned and int(numbers['cl']) >= 6
    result = dismissal
    for free in (False, True) if enhanced else (False,):
        for kind in ('stability', 'flame', 'attraction'):
            result.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.foundation_mantra.{kind}.{int(free)}",
                display_name=('Resonant Chanting: change to ' if free else 'Begin ') + 'Mantra of ' + kind.title(),
                owner_id=info['actor_id'], economy=EconomyKind.NONE if free else EconomyKind.BONUS_ACTION,
                resolution_kind='TYPED', target_kind='SELF', parameters={
                    'foundation_mantra': kind, 'mantra_free_change': free, 'mantra_resonant': enhanced,
                    'typed': {'source': FOUNDATION, 'numbers': numbers, 'riders': [],
                        'duration': {'kind': 'instant'},
                        'effects': [{'type': 'foundation_mantra', 'mode': kind, 'free': int(free)}]}}))
    result.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.foundation_mantra.end",
        display_name='End Foundation Mantra', owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='SELF', parameters={'foundation_mantra': 'end',
            'typed': {'source': FOUNDATION, 'numbers': numbers, 'riders': [], 'duration': {'kind': 'instant'},
                      'effects': [{'type': 'foundation_mantra', 'mode': 'end'}]}}))
    return result


@hook('compile_action')
def provenance(action, info):
    if not any(str(key).startswith(PREFIX) for key in info['owned_ids']):
        return None
    typed = action.parameters.get('typed')
    if not typed:
        return None
    enriched = dict(typed)
    if FOUNDATION in info['owned_ids']:
        enriched.update(track_damage_provenance=True, known_damage_features=list(info.get('owned_activation_features', ())))
        # Domain Armament's public native attack descriptor is a Qi Path
        # technique even though that attack itself has no additional Qi cost.
        if action.parameters.get('armament') == 'attack':
            enriched['qi_powered'] = True
    feature = typed.get('option_of') or typed.get('source')
    gates = {FOUNDATION:3, RESONANT:6, PREFIX+'great_mantra':10,
             PREFIX+'mantra_of_silence':14, PREFIX+'primordial_syllable':18}
    if feature in gates and not action.parameters.get('mantra_end_concentration'):
        enriched['min_cl'] = 6 if action.parameters.get('mantra_free_change') else gates[feature]
        n=dict(enriched.get('numbers') or {})
        path=next((r for r in (info['owner_sheet'].get('path_and_subpath') or {}).get('paths',())
                   if r.get('path_id')=='tianxia.path.qi_cultivation'),{})
        n['attained_cl']=int(path.get('attainment') or n.get('cl') or 1)
        from .activation_requirements import effective_numbers
        enriched['numbers']=effective_numbers(None,n)
    if (str(feature).startswith(PREFIX) and action.parameters.get('foundation_mantra') != 'end'
            and not action.parameters.get('mantra_end_concentration')):
        enriched['audible'] = True
    if (typed.get('sphere') or typed.get('forged_from') or typed.get('immortal_from')) and not typed.get('attack_action'):
        enriched['power_resource_id'] = 'resource:core.' + str(info['powering'].get(action.source_definition_id, info['primary']))
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': enriched}})


@hook('activation_prepare')
def suppressed_numbers(action,engine,actor,candidate,intent):
    typed=action.parameters.get('typed') or {}
    feature=typed.get('option_of') or typed.get('source') or ''
    if not str(feature).startswith(PREFIX):
        return None
    from .activation_requirements import effective_numbers
    return action.model_copy(update={'parameters':{**action.parameters,
        'typed':{**typed,'numbers':effective_numbers(actor,typed.get('numbers') or {},engine=engine)}}})


@hook('compile_bundle')
def reaction_provenance(bundle,info):
    if FOUNDATION not in info.get('owned_ids',()):
        return bundle
    from copy import deepcopy
    result=deepcopy(bundle)
    for row in result.get('typed_reactions',()):
        if row.get('block')!='generic':
            continue
        feature=row.get('feature_id')
        source=info['mechanics'].get(feature) or {}
        if not source:
            continue
        row.update(track_damage_provenance=True,known_damage_features=list(info['owned_ids']))
        if source.get('sphere_id'):
            row['sphere']=source['sphere_id']
            row['power_resource_id']='resource:core.' + str(info['powering'].get(feature,info['primary']))
    return result


@hook('candidate_allowed')
def offered(engine, actor, candidate, action):
    if action is not None and action.parameters.get('mantra_end_concentration'):
        from ..concentration import held
        copies = ([actor.concentration] if actor.concentration else []) + [state for _,state in held(actor)]
        return any(any(e.get('type') in {'great_mantra_aura','mantra_silence'}
                       for e in (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('effects',()))
                   for c in copies if c.source_definition_id in engine.action_catalog)
    if action is None or not action.parameters.get('foundation_mantra'):
        return None
    wanted = action.parameters['foundation_mantra']
    held = activity.current(actor, CHANNEL)
    if wanted == 'end':
        return held is not None
    if action.parameters.get('mantra_free_change'):
        return (held is not None and held.data['mode'] != wanted
                and engine.state.current_actor_id == actor.entity_id
                and actor.turn_flags.get('mantra_switch_round_used') != turn_stamp(engine))
    return True


@hook('technique_declared')
def audible_medium(engine, actor, action, candidate, intent):
    typed = action.parameters.get('typed') or {}
    feature = typed.get('option_of') or typed.get('source') or ''
    if not str(feature).startswith(PREFIX) or not typed.get('audible'):
        return None
    from ..typed_executor import Context
    from ..sound_transmission import confirm_medium, boundaries, path_allowed
    ctx = Context(engine,actor,action,intent,dict(typed),[],None)
    confirmed = confirm_medium(ctx)
    rows = boundaries(engine,actor,actor) if confirmed else None
    if typed.get('voice_exception') and rows is not None:
        rows = [r for r in rows if r['kind'] in {'soundproof','sealed'}]
    if not confirmed or rows is None or not path_allowed(ctx,rows):
        return {'source_id':action.source_definition_id,'cancel':True,
            'label':action.display_name + ': ordinary sound cannot be established here. No action or Qi is spent.'}


@effect('mantra_end_concentration')
def end_concentration(ctx, row):
    from ..concentration import held, end_copy
    from .needle import ask, checkpoint_id
    copies = ([ctx.actor.concentration] if ctx.actor.concentration else []) + [s for _,s in held(ctx.actor)]
    options = {str(c.started_sequence): c for c in copies if c.source_definition_id in ctx.engine.action_catalog
        and any(e.get('type') in {'great_mantra_aura','mantra_silence'} for e in
                (ctx.engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('effects',()))}
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine,'mantra_dismiss',ctx.actor.entity_id), ctx.actor,
        'choice:needle.mantra_dismiss', list(options),
        labels={key:'End ' + ctx.engine.action_catalog[c.source_definition_id].display_name for key,c in options.items()},
        preferred=list(options)[:1], prompt='End one maintained Mantra without using an action or spending Qi. Its aura or soundless field ends immediately.')
    if chosen:
        end_copy(ctx.engine, ctx.actor, options[chosen[0]].started_sequence, 'DISMISSED')


@effect('foundation_mantra')
def select(ctx, row):
    wanted = row['mode']
    if wanted == 'end':
        activity.end(ctx.engine, ctx.actor, CHANNEL, ctx.source)
        return
    if row.get('free'):
        ctx.actor.turn_flags['mantra_switch_round_used'] = turn_stamp(ctx.engine)
    activity.begin(ctx, channel=CHANNEL, mode=wanted, ends_unconscious=True)


@hook('button_description')
def foundation_help(row):
    p = row.get('parameters') or {}
    if p.get('mantra_end_concentration'):
        return 'End one of your maintained Great Mantras or Mantras of Silence immediately. No action or Qi cost; its field and benefits end.'
    kind = p.get('foundation_mantra')
    if kind is None:
        return None
    if kind == 'end':
        return 'End your Foundation Mantra immediately, without using an action or spending Qi. All of its benefits end.'
    timing = ('Once during your turn, change your active Foundation Mantra without using an action.'
              if p.get('mantra_free_change') else 'Use a Bonus Action to begin this Foundation Mantra.')
    benefits = {
        'stability':'Gain +1 Armor Class; this is not a shield bonus.',
        'flame':'Once per turn, after one of your Qi-powered techniques damages creatures or eligible objects, choose one damaged target to take additional Fire damage equal to your Proficiency Bonus.',
        'attraction':'Once per turn, after a creature fails a save against your Qi-powered technique and that technique finishes, choose one such creature to push or pull 5 feet.'}
    resonances = {'stability':' You have Advantage on saves against being knocked Prone and against forced movement.',
                  'flame':' You also have Fire resistance.',
                  'attraction':' Once per turn, you may increase one push or pull caused by a Qi-powered feature by 5 feet, including this Mantra’s own movement.'}
    return (timing + ' No Qi cost. ' + benefits[kind]
            + (resonances[kind] if p.get('mantra_resonant') else '')
            + ' Maintain only one Foundation Mantra. It ends when replaced, dismissed, or when you become Unconscious. Its benefits pause while you cannot speak or an effect prevents audible techniques; they resume when that suppression ends.')


@hook('ac')
def stability(engine, actor):
    return 1 if mode(engine, actor) == 'stability' else None


@hook('save')
def stability_save(ctx, subject, ability, named):
    if resonant(ctx.engine, subject) and mode(ctx.engine, subject) == 'stability' and set(named or ()) & {'prone', 'forced_movement'}:
        return {'bonus': 0, 'modes': ['ADVANTAGE']}


@hook('save_mode')
def stability_native_save(engine, actor, ability, dc, source, metadata):
    if resonant(engine, actor) and mode(engine, actor) == 'stability' and set(metadata.get('named') or ()) & {'prone', 'forced_movement'}:
        return 'ADVANTAGE'


@hook('damage_defenses')
def flame_resistance(engine, actor, damage_type, typed, source_actor_id):
    if resonant(engine, actor) and mode(engine, actor) == 'flame':
        return [{'kind': 'resistance', 'damage_types': ['FIRE']}]


@hook('forced_movement_selected')
def attraction_bonus(ctx, subject, effect, chosen_ft):
    from ..damage_provenance import qi_activation
    from .rider_choices import pick
    if (mode(ctx.engine, ctx.actor) != 'attraction' or not resonant(ctx.engine, ctx.actor)
            or not qi_activation(ctx.action, ctx.typed)
            or ctx.actor.turn_flags.get('mantra_extension_round_used') == turn_stamp(ctx.engine)):
        return None
    answer = pick(ctx.engine, ctx.actor, 'mantra_extend', 'Resonant Attraction', ['extend'], subject=subject,
        intent=ctx.intent, labels={'extend': 'Increase this push or pull by 5 feet, once this turn'},
        preferred=['extend'], prompt=f'Resonant Attraction: increase {ctx.action.display_name} pushing or pulling {subject.display_name} by 5 feet? Once per turn; no additional cost.')
    if answer:
        ctx.actor.turn_flags['mantra_extension_round_used'] = turn_stamp(ctx.engine)
        return chosen_ft + 5


@hook('technique_resolution_enabled')
def completion_enabled(ctx):
    from ..damage_provenance import qi_activation
    held=activity.current(ctx.actor,CHANNEL)
    if held is not None and held.data['mode'] in {'flame','attraction'} and qi_activation(ctx.action,ctx.typed):
        return True


@hook('technique_resolved')
def completed(ctx, receipt):
    from . import CheckpointError
    try:
        return resolve_after_technique(ctx)
    except Exception as error:
        raise CheckpointError('Foundation Mantra resolution failed') from error


@contextmanager
def capture_window(ctx):
    ctx.damage_cache.setdefault('mantra_event_start',len(ctx.engine.events))
    # Generic native reaction contexts are built after the compiler's action
    # transform. Opt this owned activation into the existing packet contract;
    # the packet producer still derives the actual source and component.
    if not ctx.typed.get('track_damage_provenance'):
        ctx.typed = {**ctx.typed, 'track_damage_provenance':True}
    yield


@hook('effect_resolution_scope')
def capture_activation(ctx, effect):
    if completion_enabled(ctx):
        return capture_window(ctx)


def resolve_after_technique(ctx):
    from ..damage_provenance import qi_activation
    from ..typed_executor import run_effects
    from .rider_choices import pick
    if not qi_activation(ctx.action, ctx.typed):
        return
    first = ctx.technique_event_start if ctx.technique_event_start is not None else ctx.damage_cache.get('mantra_event_start')
    if first is None:
        return
    events = ctx.engine.events[first:]
    for selected in ('flame','attraction'):
        resolve_trigger(ctx,events,selected)


def resolve_trigger(ctx,events,selected):
    from ..typed_executor import run_effects
    from .rider_choices import pick
    key = 'mantra_' + selected + '_round_used'
    if ctx.actor.turn_flags.get(key) == turn_stamp(ctx.engine):
        return
    eligible = []
    objects = {}
    recipient_pb = {}
    for event in events:
        if event.actor_id != ctx.actor.entity_id and selected == 'flame':
            continue
        if event.source_definition_id != ctx.source:
            continue
        observed = ((event.payload.get('damage_origin') or {}).get('activities',())
                    if selected=='flame' and event.event_type=='DAMAGE_COMMITTED' else event.payload.get('activities',()))
        if not any(a.get('channel')==CHANNEL and a.get('mode')==selected for a in observed):
            continue
        pb=next((a.get('pb') for a in observed if a.get('channel')==CHANNEL and a.get('mode')==selected
                 and type(a.get('pb')) is int),int(ctx.numbers.get('pb') or ctx.actor.proficiency_bonus))
        qualifies = (event.event_type == 'DAMAGE_COMMITTED' and
                     int(event.payload.get('hp_damage') or 0) + int(event.payload.get('temporary_hp_absorbed') or 0) > 0
                     ) if selected == 'flame' else (
                         event.event_type == 'SAVE_ROLLED' and event.payload.get('resolved_failure') == 1)
        if qualifies:
            ids = list(event.target_ids) if selected == 'flame' else [event.actor_id]
            eligible.extend(ctx.engine.state.actors[aid] for aid in ids if aid in ctx.engine.state.actors)
            for aid in ids:recipient_pb.setdefault(aid,pb)
        if selected=='flame' and event.event_type=='OBJECT_UPDATED' and int(event.payload.get('damage',{}).get('taken') or 0)>0:
            for oid in event.target_ids:
                obj=ctx.engine.state.objects.get(oid)
                if obj is not None and not obj.destroyed:
                    objects[oid]=obj
                    recipient_pb.setdefault(oid,pb)
    eligible = list({a.entity_id: a for a in eligible}.values())
    if not eligible and not objects:
        return
    names = {a.entity_id: a.display_name for a in eligible}
    from ..object_rules import label
    names.update({oid:label(obj) for oid,obj in objects.items()})
    from types import SimpleNamespace
    subject=eligible[0] if eligible else SimpleNamespace(entity_id=next(iter(objects)),display_name=names[next(iter(objects))])
    chosen = pick(ctx.engine, ctx.actor, 'mantra_' + selected, 'Mantra of ' + selected.title(), list(names),
        subject=subject, intent=ctx.intent, labels=names, preferred=[subject.entity_id],
        prompt=f'Mantra of {selected.title()}: after {ctx.action.display_name}, choose one affected '
               + ('target ' if selected == 'flame' else 'creature ')
               + ('to take Fire damage equal to your Proficiency Bonus' if selected == 'flame' else 'to push or pull 5 feet')
               + '. Once per turn; no additional cost.')
    if not chosen:
        return
    if chosen[0] in objects:
        from .objects import deal
        ctx.actor.turn_flags[key] = turn_stamp(ctx.engine)
        deal(ctx.engine,ctx.actor,objects[chosen[0]],[(recipient_pb[chosen[0]],'FIRE')],FOUNDATION)
        return
    target = ctx.engine.state.actors[chosen[0]]
    scoped = replace(ctx, targets=[target], target=target, effect_source=FOUNDATION, damage_cache={})
    if selected == 'flame':
        effects = [{'type': 'damage', 'applies_to': 'target', 'flat': recipient_pb[target.entity_id], 'damage_types': ['fire']}]
    else:
        direction = pick(ctx.engine, ctx.actor, 'mantra_direction', 'Mantra of Attraction', ['away', 'toward'],
            subject=target, intent=ctx.intent, optional=False, preferred=['away'],
            labels={'away': 'Push 5 feet away from you', 'toward': 'Pull 5 feet toward you'})
        effects = [{'type': 'forced_movement', 'applies_to': 'target', 'distance_ft': 5, 'direction': direction[0]}]
    ctx.actor.turn_flags[key] = turn_stamp(ctx.engine)
    run_effects(scoped, effects)
