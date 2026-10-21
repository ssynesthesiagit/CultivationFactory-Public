"""Public, source-owned activity state for maintained chants and performances.

Consumers: Foundation Mantras and Great Mantra. begin/current/end/active are
the public interface. A real typed activation creates the condition; ownership
alone never creates an activity. Suppression is queried from actual condition
rules, so recovery resumes the same activity without extending its deadline.
No participant count or permission is inferred from narrative examples.
"""
from . import effect, hook

STATE = 'condition:typed.maintained_activity'


def current(actor, channel):
    return next((c for c in actor.conditions.values() if c.condition_id == STATE
                 and c.source_actor_id == actor.entity_id and c.data.get('channel') == channel), None)


def end(engine, actor, channel, source):
    from .condition_ownership import remove_instance
    for c in list(actor.conditions.values()):
        if c.condition_id == STATE and c.source_actor_id == actor.entity_id and c.data.get('channel') == channel:
            remove_instance(engine, actor, c.instance_id, source)
            if type(c.data.get('concentration_started')) is int:
                from ..concentration import end_copy
                end_copy(engine, actor, c.data['concentration_started'], 'MAINTENANCE_ENDED')


def unconscious(actor):
    return actor.life_state in {'DYING','STABLE','DEAD'} or any(c.condition_id in {
        'condition:typed.unconscious', 'condition:typed.life_unconscious', 'condition:core.unconscious'}
        for c in actor.conditions.values())


def active(engine, actor, channel):
    """Return the actual activity instance, or None while its channel is blocked."""
    c = current(actor, channel)
    if c is None or c.data.get('suppressed') or not actor.active or unconscious(actor):
        return None
    from .activation_requirements import effective_cl
    if effective_cl(actor, c.data.get('available_cl',c.data['source_cl'])) < c.data.get('min_cl', 0):
        return None
    from ..speech import can_speak
    if c.data.get('audible', 1) and not can_speak(actor, engine=engine):
        return None
    if c.data.get('audible', 1):
        from ..sound_transmission import boundaries
        rows = boundaries(engine,actor,actor)
        if rows is None or any(r['kind'] in {'soundproof','sealed'} for r in rows):
            return None
    return c


def snapshots(engine, actor):
    """Actual active source/mode at a delivery boundary, never inferred ownership."""
    from .activation_requirements import effective_numbers
    return [{'channel':c.data['channel'], 'mode':c.data['mode'],
             'source':c.source_definition_id,
             **{key:effective_numbers(actor,{'cl':c.data['source_cl'],'pb':c.data.get('pb',actor.proficiency_bonus),
                 'available_cl':c.data.get('available_cl',c.data['source_cl']),
                 'available_pb':c.data.get('available_pb',c.data.get('pb',actor.proficiency_bonus)),
                 'attained_cl':c.data.get('attained_cl',c.data['source_cl'])},engine=engine)[field]
                for key,field in (('source_cl','cl'),('pb','pb'))}}
            for c in actor.conditions.values() if c.condition_id == STATE
            and active(engine,actor,c.data['channel']) is c]


@hook('damage_origin_activities')
def damage_activities(ctx):
    return snapshots(ctx.engine,ctx.actor) or None


@hook('save_final')
def save_activities(ctx, subject, ability, named, failed):
    if not ctx.typed.get('track_damage_provenance') or ctx.save_result is None:
        return
    rows = snapshots(ctx.engine,ctx.actor)
    event = next((e for e in reversed(ctx.engine.events) if e.event_type=='SAVE_ROLLED'
                  and e.actor_id==subject.entity_id and e.source_definition_id==ctx.source
                  and e.payload.get('roll_id')==ctx.save_result.roll_id),None)
    if event:
        if rows:event.payload['activities'] = rows
        event.payload['resolved_failure'] = int(failed)


@hook('event',nested=True)
def native_save_activities(engine,event_type,kwargs):
    if event_type!='SAVE_ROLLED':
        return
    from ..paid_relocation import current_activation
    activation=current_activation(engine)
    event=kwargs.get('originating_event')
    if activation is None or event is None or activation.source_id!=event.source_definition_id:
        return
    actor=engine.state.actors.get(activation.actor_id)
    if actor is None:
        return
    rows=snapshots(engine,actor)
    if rows:
        event.payload['activities']=rows
        event.payload['resolved_failure']=int(event.payload.get('success') is False)


@hook('event', nested=True)
def object_activities(engine,event_type,kwargs):
    if event_type!='OBJECT_UPDATED' or int((kwargs.get('payload') or {}).get('damage',{}).get('taken') or 0)<=0:
        return
    actor=engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None:
        return
    rows=snapshots(engine,actor)
    event=kwargs.get('originating_event')
    if rows and event is not None:
        event.payload['activities']=rows


def begin(ctx, *, channel, mode, ends_unconscious, expires='UNTIL_REMOVED'):
    if not channel or not mode:
        raise ValueError('A maintained activity requires a channel and a selected mode')
    end(ctx.engine, ctx.actor, channel, ctx.source)
    concentration = ctx.actor.concentration
    scope = ({'concentration_started':int(concentration.started_sequence)}
             if concentration is not None and concentration.source_definition_id == ctx.source else {})
    ctx.engine._apply_condition(ctx.actor, STATE, ctx.source, ctx.actor.entity_id,
        expires_on=expires, data={'channel': channel, 'mode': mode, 'audible': 1,
            'ends_unconscious': int(ends_unconscious), 'source_cl': int(ctx.numbers['cl']),
            'feature_id': str(ctx.typed.get('option_of') or ctx.typed.get('source') or ''),
            'min_cl': int(ctx.typed.get('min_cl') or 0),
            'pb':int(ctx.numbers.get('pb') or ctx.actor.proficiency_bonus),
            'attained_cl':int(ctx.numbers.get('attained_cl') or ctx.numbers['cl']),
            'available_cl':int(ctx.numbers.get('available_cl') or ctx.numbers['cl']),
            'available_pb':int(ctx.numbers.get('available_pb') or ctx.numbers.get('pb') or ctx.actor.proficiency_bonus),
            'label': ctx.action.display_name, **scope})


@effect('maintained_activity')
def start(ctx, row):
    from ..typed_executor import effect_expiry
    begin(ctx, channel=str(row['channel']), mode=str(row['mode']),
          ends_unconscious=bool(row.get('ends_unconscious')),
          expires=effect_expiry(ctx, row, ctx.actor, condition=True) or 'UNTIL_REMOVED')


@hook('event', nested=True)
def activity_lifecycle(engine, event_type, kwargs):
    if event_type not in {'CONDITION_APPLIED', 'DAMAGE_COMMITTED', 'LIFE_STATE_CHANGED','ENTITY_DEFEATED'}:
        return
    for actor in engine.state.actors.values():
        from .activation_requirements import effective_cl
        for c in list(actor.conditions.values()):
            if c.condition_id != STATE:
                continue
            defeated=event_type=='ENTITY_DEFEATED' and kwargs.get('actor_id')==actor.entity_id
            if (((unconscious(actor) or defeated) and c.data.get('ends_unconscious')) or
                    effective_cl(actor, c.data.get('available_cl',c.data['source_cl'])) < c.data.get('min_cl', 0)):
                end(engine, actor, c.data['channel'], c.source_definition_id)
