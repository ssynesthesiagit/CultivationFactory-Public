"""Sound second pass using existing effect, save and packet hooks.

Name-Striking Tone asks for damage type, then for its failed-save rider. The
caster's next Sound save penalty is instance-bound and consumed only after an
actual resolved save. Players confirm the printed name/voice qualification;
AI only qualifies a target whose voiced action it has observed in this fight.

Silence zones opt in with an inside rule ``sound_hostile_thunder`` (check/zero).
The final packet hook scopes the rule to targets inside that live zone and
sources hostile to its owner. No blanket immunity is granted to recipients.
The check uses the source's Sound Cultivation Check or spellcasting key ability,
with real d20/choice transport, against the zone's sealed Sound Save DC.
"""
from typing import Any

from . import effect, hook
from .needle import ask, checkpoint_id, numbers_of
from ..typed_executor import Context, run_effects

SOUND = 'tianxia.sphere.sound'
NAME = 'TAL_SOUND_NAME_STRIKING_TONE'
PENALTY = 'condition:typed.sound_name_save'


def heard_voice(engine: Any, owner: Any, target: Any) -> bool:
    """Only recorded, perceived voice use; names in a roster are not knowledge."""
    # Historical observation cannot be reconstructed from current geometry.
    # A qualifying receipt below records the observers at the voiced action.
    return any(e.event_type == 'PASSIVE_TRIGGERED' and e.payload.get('sound_voice_observed') and e.actor_id == target.entity_id
               and owner.entity_id in e.target_ids for e in engine.events)


@hook('technique_start')
def voice_observation(engine: Any, actor: Any, action: Any) -> None:
    from .. import speech
    from ..senses import perceives
    from ..typed_executor import condition_rules
    if not speech.needs_voice(action):
        return
    listeners = [a.entity_id for a in engine.state.actors.values()
                 if a.active and a.entity_id != actor.entity_id
                 and perceives(engine, a, actor)
                 and engine._distance_actor_to_actor(a, actor) <= 60
                 and not any(r.get('cant_hear') for r in condition_rules(a))
                 and any(((engine.action_catalog.get(s).parameters or {}).get('typed') or {}).get('source') == NAME
                         for s in a.action_ids if engine.action_catalog.get(s))]
    if listeners:
        engine._append_event('PASSIVE_TRIGGERED', action.source_definition_id, actor_id=actor.entity_id,
                             target_ids=tuple(listeners), payload={'sound_voice_observed':True, 'trigger':'Voice heard', 'text':'The listed listeners heard this voiced action.'})


@hook('candidate_allowed')
def name_knowledge(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    from .needle import answerable
    if ((getattr(action,'parameters',None) or {}).get('typed') or {}).get('source') != NAME or answerable(engine,actor):
        return None
    return all(t in engine.state.actors and heard_voice(engine,actor,engine.state.actors[t])
               for t in candidate.target_ids)



@hook('technique_declared')
def name_prerequisite(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> dict | None:
    typed=(action.parameters or {}).get('typed') or {}
    if typed.get('source')!=NAME or not candidate.target_ids:
        return None
    target=engine.state.actors.get(candidate.target_ids[0])
    if target is None or heard_voice(engine,actor,target):
        return None
    confirmed=ask(engine,intent,checkpoint_id(engine,'sound_name_known',action.source_definition_id,target.entity_id),
        actor,'choice:needle.sound_name_known',['known'],automatic=False,default='decline',allow_decline=True,
        name='Name-Striking Tone',target_id=target.entity_id,
        labels={'known':'I know a meaningful name or heard this creature’s voice in the last 24 hours'},
        prompt=f'Name-Striking Tone: confirm that {actor.display_name} knows a meaningful name for {target.display_name}, or heard its voice in the last 24 hours.')
    if not confirmed:
        return {'cancel':True,'source_id':NAME,'label':'Name-Striking Tone requires a known meaningful name or a recently heard voice; no action or cultivation points are spent.'}
    return None


@effect('sound_name_tone')
def name_tone(ctx: Context, eff: dict) -> None:
    if ctx.target is None:
        return
    target=ctx.target
    damage_type = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'sound_name_damage', ctx.source, target.entity_id),
        ctx.actor, 'choice:needle.sound_name_damage', ['psychic', 'thunder'], name='Name-Striking Tone',
        target_id=target.entity_id, labels={'psychic':'Psychic damage', 'thunder':'Thunder damage'},
        prompt=f'Name-Striking Tone against {target.display_name}: choose Psychic or Thunder damage.')
    kind = damage_type[0] if damage_type else 'psychic'
    damage = {'applies_to':'target','dice':{'count':6,'sides':8},'damage_types':[kind]}
    run_effects(ctx, [{'type':'save','ability':'wis','applies_to':'target',
        'on_fail':[dict(damage,type='damage'),{'type':'sound_name_failure'}],
        'on_success':[dict(damage,type='half_damage')]}])


@effect('sound_name_failure')
def name_failure(ctx: Context, eff: dict) -> None:
    target = ctx.target
    options = {
        'frightened': {'type':'condition','condition':'frightened'},
        'distance': {'type':'condition','condition':'no_approach'},
        'save': {'type':'sound_name_penalty'},
        'resonance': {'type':'mark','mark':'Resonance'},
    }
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine,'sound_name_failure',ctx.source,target.entity_id),
        ctx.actor,'choice:needle.sound_name_failure',list(options), name='Name-Striking Tone',target_id=target.entity_id,
        labels={'frightened':'Frightened of you until your next turn ends',
                'distance':'Cannot willingly move closer to you until your next turn ends',
                'save':'Disadvantage on its next save against your Sound talents before your next turn ends',
                'resonance':'Resonance: your Sound mark, which enables extra Sound effects, until your next turn ends'},
        prompt=f'Name-Striking Tone: {target.display_name} failed its Wisdom save. Choose one penalty.')
    if picked:
        run_effects(ctx,[{**options[picked[0]],'applies_to':'target','duration':{'kind':'until_end_of_your_next_turn'}}])


@effect('sound_name_penalty')
def name_penalty(ctx: Context, eff: dict) -> None:
    ctx.engine._apply_condition(ctx.target,PENALTY,ctx.source,ctx.actor.entity_id,
        expires_on=f'END_OF_SOURCE_TURN_AT:{ctx.actor.turns_started+1}',data={'label':'Disadvantage on the next save against this caster’s Sound talents',
                                                  'after_sequence':ctx.engine.events[-1].sequence})


def save_source(engine: Any, source: str) -> tuple[str, str]:
    action=engine.action_catalog.get(source)
    typed=(action.parameters or {}).get('typed') or {} if action else {}
    return str(typed.get('sphere') or ''), str(action.owner_id if action else '')


def penalty_consumed(engine: Any, subject: Any, condition: Any) -> bool:
    for event in reversed(engine.events):
        if event.sequence <= int(condition.data.get('after_sequence',0)):
            break
        if event.event_type=='SAVE_ROLLED' and event.actor_id==subject.entity_id:
            sphere,owner=save_source(engine,event.source_definition_id)
            if sphere==SOUND and owner==condition.source_actor_id:
                return True
    return False


def pending_penalties(engine: Any, subject: Any, actor_id: str) -> list:
    return [c for c in subject.conditions.values() if c.condition_id==PENALTY and c.source_actor_id==actor_id
            and not penalty_consumed(engine,subject,c)]


@hook('save_mode')
def next_sound_save(engine: Any, subject: Any, ability: str, dc: int, source: str, context: dict) -> str | None:
    sphere,owner=save_source(engine,source)
    owner=str(context.get('source_actor_id') or owner)
    if sphere==SOUND and pending_penalties(engine,subject,owner):
        return 'DISADVANTAGE'
    return None


@hook('event')
def consume_sound_save(engine: Any, event_type: str, kwargs: dict) -> None:
    if event_type=='SAVE_ROLLED':
        subject=engine.state.actors.get(kwargs.get('actor_id'))
        if subject is not None:
            clear_penalties(engine,subject)


def clear_penalties(engine: Any, subject: Any) -> None:
    from .riders_shared import remove_benefit_condition
    for condition in list(subject.conditions.values()):
        if condition.condition_id==PENALTY and penalty_consumed(engine,subject,condition):
            remove_benefit_condition(engine,subject,condition,'CONSUMED')


@hook('turn_start')
@hook('turn_end')
def sweep_penalties(engine: Any, actor: Any) -> None:
    # Repeat saves can occur inside an event callback, where nested callbacks
    # are suppressed. The pure event reader still ignores their consumed grant.
    for subject in engine.state.actors.values():
        clear_penalties(engine,subject)


@hook('final_damage')
def hostile_thunder(engine: Any, target: Any, amount: int, damage_type: str, source_id: str,
                    source_actor_id: str, intent: Any) -> dict | None:
    if damage_type.upper() != 'THUNDER' or amount <= 0:
        return None
    from .. import zones
    from ..spatial_areas import zone_contains
    from ..relations import relation, ENEMY
    source = engine.state.actors.get(source_actor_id)
    if source is None:
        return None
    for zone in zones.typed_zones(engine):
        owner = engine.state.actors.get(zone.owner_id)
        mode = next((r.get('rule',{}).get('sound_hostile_thunder') for r in zone.trigger_profile.get('inside',[])
                     if r.get('rule',{}).get('sound_hostile_thunder')),None)
        if not mode or owner is None or relation(engine,owner,source)!=ENEMY or not zone_contains(engine,target,zone):
            continue
        if mode=='zero':
            return {'amount':0}
        from ..typed_executor import resolve_opposed_check
        action = engine.action_catalog.get(source_id)
        if action is None:
            from ..gate2_runtime_models import ActionDefinition
            action = ActionDefinition(source_definition_id=source_id or 'sound:hostile_thunder', display_name='Thunder damage',
                                      owner_id=source.entity_id,economy='NONE',resolution_kind='TYPED',target_kind='SELF')
        choices = ['spellcasting']
        if any((((engine.action_catalog.get(aid).parameters or {}).get('typed') or {}).get('sphere')==SOUND)
               for aid in source.action_ids if engine.action_catalog.get(aid)):
            choices.insert(0,'sound')
        pick = ask(engine,intent,checkpoint_id(engine,'swallowed_thunder',zone.zone_id,source.entity_id,target.entity_id),
            source,'choice:needle.swallowed_thunder',choices,name='Silence That Swallows Thunder',target_id=target.entity_id,
            labels={'sound':'Sound Cultivation Check (Proficiency Bonus + Sound key ability)',
                    'spellcasting':'Spellcasting ability check (key ability only)'},
            prompt=f'Silence That Swallows Thunder: {source.display_name} must pass a check against {owner.display_name}’s Sound Save DC to deal Thunder damage to {target.display_name}. Choose the check.')
        typed = {'numbers':numbers_of(engine,source),'source':str(source_id or ''),'effects':[]}
        check_ctx = Context(engine,source,action,intent,typed,[owner],owner,{})
        result = resolve_opposed_check(check_ctx,owner,
            {'kind':'cultivation' if pick and pick[0]=='sound' else 'key_ability','label':'Sound Check' if pick and pick[0]=='sound' else 'Spellcasting ability check'},
            {'kind':'dc','dc':int(zone.trigger_profile['numbers']['save_dc']),'label':'Sound Save DC'})
        if not result.success:
            return {'amount':0}
    return None

SILENT_STEP = 'TAL_SOUND_SILENT_STEP_BETWEEN_NOTES'
STEP_BLOCK = 'sound_silent_step'


@hook('compile_block')
def compile_step(block: str, spec: dict, row: dict, numbers: dict) -> list | None:
    if block == STEP_BLOCK:
        return [row]
    return None


def source_name(engine: Any, source: str) -> str:
    action=engine.action_catalog.get(source)
    if action is not None:
        return str(action.display_name or source)
    return {'system:combat.dodge':'Dodge','system:combat.disengage':'Disengage'}.get(source,source)


def silent_step(engine: Any, actor: Any, source: str) -> None:
    from .fight_ownership import owns_block
    from .rider_choices import intent_for
    from ..senses import perceives
    from ..relations import relation, ENEMY
    from .. import zones, granted_movement
    from ..spatial_areas import zone_contains
    if not actor.active or not owns_block(engine,actor,STEP_BLOCK):
        return
    key=[engine.state.round_number,engine.state.current_actor_id,
         engine.state.actors[engine.state.current_actor_id].turns_started]
    if actor.turn_flags.get('sound_silent_step_round_')==key:
        return
    intent=intent_for(engine)
    if intent is None:
        return
    # Hearing dependence is an optional opportunity-attack exemption, not a
    # prerequisite for the step. Players may attest one perceived enemy;
    # automatic controllers never invent hearing knowledge.
    enemies=[a for a in engine.state.actors.values() if a.active and relation(engine,actor,a)==ENEMY
             and perceives(engine,actor,a)]
    chosen=ask(engine,intent,checkpoint_id(engine,'silent_step_hearing',source,actor.entity_id),actor,
        'choice:needle.silent_step_hearing',[a.entity_id for a in enemies],automatic=False,default='decline',
        allow_decline=True,name='Silent Step Between Notes',
        labels={a.entity_id:a.display_name+' relies on hearing to track me' for a in enemies},
        prompt=f'Silent Step Between Notes: after {source_name(engine, source)}, you may move up to 5 feet without sound. Optionally choose one creature that relies on hearing to track you; it cannot make an opportunity attack against this step. Declining this choice does not cancel the step.')
    feet=10 if any(z.owner_id==actor.entity_id and zone_contains(engine,actor,z)
                  and (((engine.action_catalog.get(z.source_definition_id).parameters or {}).get('typed') or {}).get('source')=='TAL_SOUND_DAMPEN_SOUND')
                  for z in zones.typed_zones(engine) if engine.action_catalog.get(z.source_definition_id)) else 5
    paths=granted_movement.candidates(engine,actor,feet,intent,SILENT_STEP)
    picked=ask(engine,intent,checkpoint_id(engine,'silent_step_destination',source,actor.entity_id),actor,
        'choice:needle.silent_step_destination',list(paths),allow_decline=True,name='Silent Step Between Notes',
        labels={k:f'Move to {c.destination.x},{c.destination.y} ({c.movement_cost_ft} feet)' for k,c in paths.items()},
        prompt=f'Silent Step Between Notes: {actor.display_name} may move up to {feet} feet without sound. Choose a destination. The selected hearing-dependent creature, if any, cannot make an opportunity attack. No normal movement is spent.')
    if picked:
        actor.turn_flags['sound_silent_step_round_']=key
        engine._resolve_movement(actor,paths[picked[0]],intent,granted_ft=feet,ignore_oa_from=tuple(chosen or ()))


@hook('action_completed')
def step_after_defense(engine: Any, actor: Any, economy: str, source: str) -> None:
    if source in ('system:combat.dodge','system:combat.disengage'):
        silent_step(engine,actor,source)


@hook('event')
def step_after_focus(engine: Any, event_type: str, kwargs: dict) -> None:
    if event_type=='RESOURCE_SPENT' and (kwargs.get('payload') or {}).get('resource_id')=='resource:core.martial_focus':
        actor=engine.state.actors.get(kwargs.get('actor_id'))
        from .fight_ownership import owns_block
        if actor is not None and owns_block(engine,actor,STEP_BLOCK):
            actor.turn_flags['sound_focus_seen_round_']=engine.events[-1].sequence
            silent_step(engine,actor,'Spend Martial Focus')


@hook('effect_description')
def sound_description(row: dict) -> str | None:
    if row.get('type')=='sound_name_tone':
        return ('Name-Striking Tone: Resonance is your Sound mark, enabling extra Sound effects against that creature. '
                'A creature whose meaningful name or recent voice you know makes a Wisdom save. '
                'Choose Psychic or Thunder damage (6d8, half on success). On a failed save, choose Frightened, '
                'no willing approach, Disadvantage on its next save against your Sound talents, or your Resonance mark. '
                'The chosen penalty lasts until the end of your next turn.')
    if row.get('type')=='sound_silent_step':
        return ('After Dodge, Disengage, or spending Martial Focus, you may take one soundless step per turn: '
                '5 feet, or 10 feet inside your Dampen Sound. Choose one hearing-dependent tracker that cannot '
                'make an opportunity attack against this step.')
    return None


@hook('resolution_final')
def nested_focus_step(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    start=next((e.sequence for e in reversed(engine.events) if e.event_type=='INTENT_ACCEPTED'),0)
    spends=[e for e in engine.events if e.sequence>start and e.event_type=='RESOURCE_SPENT'
            and e.payload.get('resource_id')=='resource:core.martial_focus']
    for event in spends:
        owner=engine.state.actors.get(event.actor_id)
        from .fight_ownership import owns_block
        if owner is not None and owns_block(engine,owner,STEP_BLOCK) and event.sequence>int(owner.turn_flags.get('sound_focus_seen_round_',0)):
            owner.turn_flags['sound_focus_seen_round_']=event.sequence
            silent_step(engine,owner,'Spend Martial Focus')
