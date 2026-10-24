"""Sealed Qi Subpaths 5 effects. No live authority reads or core ability branches.

Sound delivery uses hearing, or an explicit shared sound_medium marker for
alternate vibration delivery. A vibration_blocked rule denies that route.
Native saves, damage, movement, concentration and exact-instance clocks remain
responsible for their ordinary state/events. All new behavior is row opt-in.
"""
from dataclasses import replace
from types import SimpleNamespace
from . import effect, hook
from .condition_ownership import remove_instance

SOUND = 'tianxia.subpath.qi.sound_cultivator.feature.'
CLOUD = 'tianxia.subpath.qi.cloud_walker.feature.'
PENALTY = 'condition:typed.qi5_note_penalty'
FEATHER = CLOUD + 'light_as_a_feather'


def qi_path_numbers(info):
    """Owning Qi Path numbers for Cloud Walker compilation and Feather's passive.

    Explicit multi-Path rows take precedence over the primary chassis. Older
    single-Path bundles keep their compiled numbers; no new ownership is inferred.
    """
    numbers=dict(info['numbers'])
    paths=(info.get('owner_sheet',{}).get('path_and_subpath') or {}).get('paths') or []
    qi=next((p for p in paths if p.get('path_id')=='tianxia.path.qi_cultivation'),None)
    if qi is not None:
        numbers['cl']=int(qi.get('effective_cl',qi.get('attainment',0)) or 0)
        key=str(qi.get('key_ability') or 'INT').upper()[:3]
        numbers['key_mod']=int(info.get('mods',{}).get(key,0))
        numbers['attack_bonus']=int(numbers['pb'])+numbers['key_mod']
        numbers['save_dc']=8+numbers['attack_bonus']
    return numbers


def concentration_presentation(source):
    """Plain text for the two printed scopes of the source-timed save penalty."""
    if source == SOUND + 'shattering_note':
        return ('Disadvantage on Concentration saves from this damage only',
                "This temporary penalty applies only to Shattering Note's damage and ends when that damage resolves.")
    return ('Disadvantage on Concentration saves',
            "You have Disadvantage on Concentration saves until the end of the source's next turn.")


def _rules(actor):
    from ..typed_executor import condition_rules
    return condition_rules(actor)


def _hears(actor):
    return not any(c.condition_id == 'condition:typed.deafened' for c in actor.conditions.values()) and not any(
        r.get('sound_blocked') for r in _rules(actor))


def _vibrates(actor):
    return not any(r.get('vibration_blocked') for r in _rules(actor))


def _medium(actor):
    return {c.data['sound_medium'] for c in actor.conditions.values() if c.data.get('sound_medium')}


@hook('effect_subject_allowed')
def sound_delivery(ctx, row, subject):
    delivery = row.get('qi5_delivery')
    if delivery == 'vibration':
        return _vibrates(subject)
    if delivery == 'hearing':
        return _hears(subject)
    if delivery == 'either':
        from ..flight import profile
        floor_vibration = (subject.position.z == ctx.actor.position.z == 0
                           and not profile(ctx.engine, subject).hover
                           and not profile(ctx.engine, ctx.actor).hover)
        return _hears(subject) or (_vibrates(subject) and _vibrates(ctx.actor)
                                  and (bool(_medium(subject) & _medium(ctx.actor)) or floor_vibration))
    return None


@effect('qi5_note_penalty', harmful=True)
def note_penalty(ctx, row):
    from ..typed_executor import effect_expiry, _roll
    from ..gate2_runtime_models import DiceSpec
    if ctx.target is None:
        return
    value = _roll(ctx, DiceSpec(count=1, sides=4), 'RESONANT_NOTE_PENALTY')
    ctx.engine._apply_condition(ctx.target, PENALTY, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, ctx.target, condition=True),
        data={'penalty': value, 'label': f'Resonant Note: subtract {value} from the next attack roll'})


@hook('attack_bonus')
def attack_penalty(ctx, actor):
    return -sum(int(c.data['penalty']) for c in actor.conditions.values() if c.condition_id == PENALTY) or None


@hook('event', nested=True)
def consume_attack_penalty(engine, event_type, kwargs):
    if event_type != 'ATTACK_ROLLED':
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor:
        for c in list(actor.conditions.values()):
            if c.condition_id == PENALTY:
                remove_instance(engine, actor, c.instance_id, c.source_definition_id)


@effect('qi5_concentration', harmful=True)
def concentration_penalty(ctx, row):
    from ..typed_executor import effect_expiry
    if ctx.target:
        source = ctx.typed.get('source')
        label, reading = concentration_presentation(source)
        ctx.engine._apply_condition(ctx.target, 'condition:typed.qi5_concentration', ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, row, ctx.target, condition=True),
            data={'rule': {'concentration_mode': 'DISADVANTAGE'},
                  'label': label, 'reading': reading})


@effect('qi5_melody', harmful=False)
def melody(ctx, row):
    from ..typed_executor import run_effects
    from .needle import ask, checkpoint_id
    from .end_effect import source_cl
    for subject in ctx.targets:
        if sound_delivery(ctx, {'qi5_delivery': 'either'}, subject) is False:
            continue
        inner = replace(ctx, target=subject, targets=[subject])
        cl = int(ctx.numbers['cl'])
        run_effects(inner, [{'type': 'healing', 'applies_to': 'target', 'dice': {'count': 4 if cl >= 18 else 3 if cl >= 14 else 2, 'sides': 8}, 'formula': 'key_ability_modifier'}])
        removable = {name: [c for c in subject.conditions.values() if c.condition_id == 'condition:typed.' + name
                            and source_cl(inner, c) <= cl] for name in ('frightened', 'deafened')}
        charms = [c for c in subject.conditions.values() if c.condition_id == 'condition:typed.charmed' and (c.data.get('repeat_save') or c.data.get('origin_save'))]
        # Each original save is a separate effect. Keep the instance identity in
        # the transactional option key while showing players its readable source.
        charm_options = {}
        labels = {'frightened': 'End Frightened', 'deafened': 'End Deafened', 'move': 'Allow a 5-foot step without provoking'}
        for index, charm in enumerate(charms):
            option = f'charmed:{index}'
            charm_options[option] = charm
            action = ctx.engine.action_catalog.get(charm.source_definition_id)
            source = action.display_name if action else 'an unknown effect'
            applier = ctx.engine.state.actors.get(charm.source_actor_id)
            source_name = applier.display_name if applier else 'an unknown creature'
            spec = charm.data.get('repeat_save') or charm.data.get('origin_save') or {}
            ability = {'str': 'Strength', 'dex': 'Dexterity', 'con': 'Constitution', 'int': 'Intelligence',
                       'wis': 'Wisdom', 'cha': 'Charisma'}.get(str(spec.get('ability', 'save')).lower(), 'save')
            labels[option] = f'Repeat {source_name}’s {source} charm save ({ability}) with Advantage'
        options = [name for name, cs in removable.items() if cs] + list(charm_options) + ['move']
        picks = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'QI5_MELODY', subject.entity_id), ctx.actor,
            'choice:needle.qi5_melody', options, preferred=options[:1],
            labels=labels,
            name='Healing Melody', target_id=subject.entity_id,
            prompt=f'Healing Melody healed {subject.display_name}. Choose one additional benefit; no extra Qi cost.')
        chosen = picks[0] if picks else None
        if chosen in removable:
            for c in removable[chosen]:
                remove_instance(ctx.engine, subject, c.instance_id, ctx.source)
        elif chosen in charm_options:
            c = charm_options[chosen]
            spec = c.data.get('repeat_save') or c.data['origin_save']
            roll = ctx.engine._roll_save(subject, spec['ability'], spec['dc'], c.source_definition_id, extra_mode='ADVANTAGE')
            if roll and roll.total >= spec['dc']:
                remove_instance(ctx.engine, subject, c.instance_id, ctx.source)
        elif chosen == 'move':
            from .rider_step import step
            step(replace(inner, actor=subject), {'distance_ft': 5, 'no_oa': True, 'label': 'Healing Melody'})


@effect('qi5_fear_field', harmful=True)
def fear_field(ctx, row):
    from .. import zones
    zones.create(ctx, {'name': 'Song of Fear', 'shape': 'sphere', 'size_ft': 30,
        'centered_on_self': True, 'follows_owner': True,
        'duration': {'kind': 'minutes', 'amount': 1, 'concentration': True},
        'triggers': [{'on': ['enter', 'start'], 'who': 'hostile', 'once_per_turn': True,
            'effects': [{'type': 'save', 'ability': 'wis', 'applies_to': 'target', 'qi5_delivery': 'hearing',
                'on_fail': [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target',
                    'duration': 'concentration', 'repeat_save': {'ability': 'wis', 'when': 'end'}}],
                'on_success': [{'type': 'reaction_denied', 'applies_to': 'target', 'duration': 'until_start_of_next_turn'}]}]}]})


@hook('zone_recipient_allowed')
def fear_hearing(engine, zone, subject, spec):
    if zone.source_definition_id and _source(engine, zone.source_definition_id) == SOUND + 'song_of_fear':
        return _hears(subject)
    return None


def _source(engine, sid):
    action = engine.action_catalog.get(sid)
    return ((action.parameters or {}).get('typed') or {}).get('source') if action else None


@hook('turn_end')
def end_fear_outside(engine, actor):
    from .. import zones
    for c in list(actor.conditions.values()):
        if c.condition_id == 'condition:typed.frightened' and _source(engine, c.source_definition_id) == SOUND + 'song_of_fear':
            if not any(z.source_definition_id == c.source_definition_id and zones._inside(engine, actor, z)
                       for z in zones.typed_zones(engine)):
                remove_instance(engine, actor, c.instance_id, c.source_definition_id)


@hook('compile_action')
def melody_target(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    source = typed.get('source')
    if source in {SOUND+'healing_melody',SOUND+'instrument_of_qi'}:
        parameters = dict(action.parameters or {})
        parameters['typed'] = {**typed, 'manual_inline_choice': source == SOUND+'healing_melody'}
        return action.model_copy(update={'target_kind': 'ANY_CREATURE', 'parameters': parameters})
    if source in {SOUND+'shattering_note', SOUND+'requiem_of_the_heavens'}:
        area = typed.get('area') or {}
        if area.get('size_ft') and not area.get('explicit_harmful_recipients'):
            # Printed area: Shattering Note's cone and Requiem's "choose any
            # number of eligible creatures" include every creature in the area,
            # never only enemies. The reviewed authority rows carry no recipient
            # wording the compiler could seal, so the owning plug-in seals it.
            # Norm the full policy here: the compiler already wrote the
            # enemies-only default into this row.
            scope = 'every_creature' if source == SOUND+'requiem_of_the_heavens' else 'other_creatures'
            parameters = dict(action.parameters or {})
            parameters['typed'] = {**typed, 'area': {
                **area, 'explicit_harmful_recipients': scope,
                'recipients': 'all', 'harmful_recipients': 'all', 'harmful_recipient_override': 'all',
                'include_self': scope == 'every_creature', 'exclude_self': scope == 'other_creatures',
            }}
            return action.model_copy(update={'parameters': parameters})
    return None


@hook('compile_passives')
def feather_passive(passives, info):
    if FEATHER not in info['owned_ids']:
        return passives
    numbers=qi_path_numbers(info)
    if FEATHER in info['owned_ids'] and int(numbers['cl'])>=3:
        return [*passives, {'feature_id': FEATHER, 'block': 'qi5_feather', 'cl': int(numbers['cl'])}]
    return passives


@hook('falling_damage')
def feather_fall(engine, actor, amount, context, intent):
    rows = [r for r in engine.typed_passive_rows.get(actor.entity_id, []) if r.get('block') == 'qi5_feather']
    if rows:
        return {'amount': max(0, amount - 5 * max(int(r['cl']) for r in rows))}
    return None


@effect('qi5_clear_concentration')
def clear_concentration(ctx, row):
    if ctx.target:
        for c in list(ctx.target.conditions.values()):
            if c.condition_id == 'condition:typed.qi5_concentration' and c.source_definition_id == ctx.source:
                remove_instance(ctx.engine, ctx.target, c.instance_id, ctx.source)


@hook('d20_bonus')
def native_note_penalty(engine, roll, intent):
    if not str(roll.reason).startswith('ATTACK:'):
        return None
    actor = engine.state.actors.get(roll.actor_id)
    if actor is None:
        return None
    penalty = sum(int(c.data['penalty']) for c in actor.conditions.values() if c.condition_id == PENALTY)
    if not penalty:
        return None
    frames = getattr(engine, '_d20_scopes', ())
    frame = frames[-1] if frames else {}
    spec = frame.get('spec') or {}
    if (frame.get('kind') == 'attack' and frame.get('actor_id') == roll.actor_id
            and roll.reason == f"ATTACK:{frame.get('source_id')}:{frame.get('attack_index', 1)}"
            and spec.get('typed') is not None and callable(spec.get('before_attack_d20'))):
        return None
    return {'source_id': SOUND + 'instrument_of_qi', 'bonus': -penalty}


@hook('ai_candidate_allowed')
def melody_allies(engine,actor,candidate,action):
    source=((action.parameters or {}).get('typed') or {}).get('source') if action else None
    if source==SOUND+'instrument_of_qi':
        from ..relations import relation
        return all(t!=actor.entity_id and relation(engine,actor,engine.state.actors[t])=='ENEMY' for t in candidate.target_ids)
    if source==SOUND+'healing_melody':
        from ..relations import relation
        return all(t==actor.entity_id or relation(engine,actor,engine.state.actors[t])=='ALLY' for t in candidate.target_ids)
    return None


@hook('candidate_allowed')
def audible_targets(engine,actor,candidate,action):
    if not action:
        return None
    source=((action.parameters or {}).get('typed') or {}).get('source')
    if source==SOUND+'instrument_of_qi':
        return all(_hears(engine.state.actors[t]) for t in candidate.target_ids)
    return None


@hook('recipient_allowed')
def melody_recipient_delivery(engine, actor, target, action):
    source=((action.parameters or {}).get('typed') or {}).get('source') if action else None
    if source==SOUND+'healing_melody':
        return sound_delivery(SimpleNamespace(engine=engine, actor=actor), {'qi5_delivery': 'either'}, target) is not False
    return None


@hook('before_target_reactions',priority=-10)
def eligible_requiem(ctx):
    if ctx.typed.get('source')==SOUND+'requiem_of_the_heavens':
        ctx.targets[:]=[a for a in ctx.targets if sound_delivery(ctx,{'qi5_delivery':'either'},a)]


@effect('qi5_defensive_form')
def defensive_form(ctx,row):
    from ..typed_executor import effect_expiry
    ctx.engine._apply_condition(ctx.actor,'condition:typed.qi5_defensive_form',ctx.source,ctx.actor.entity_id,
        expires_on=effect_expiry(ctx,row,ctx.actor,condition=True),data={
            'qi5_defensive_form':1,'source_cl':int(ctx.numbers['cl']),
            'excluded_types':[str(k).upper() for k in row['excluded_types']],
            'protected_conditions':list(row.get('protected_conditions') or []),
            'label':ctx.action.display_name+': Resistance except '+', '.join(str(k).title() for k in row['excluded_types'])})


@hook('damage_defenses')
def form_defenses(engine,actor,kind,typed,source_actor_id):
    if kind and any(c.data.get('qi5_defensive_form') and str(kind).upper() not in c.data['excluded_types']
                    for c in actor.conditions.values()):
        return [{'kind':'resistance','damage_types':[str(kind).upper()]}]
    return None


@hook('defense_description')
def form_description(engine,actor):
    from ..factory_compiler import _DAMAGE_TYPES
    rows=[]
    for c in actor.conditions.values():
        if c.data.get('qi5_defensive_form'):
            excluded={str(k).upper() for k in c.data.get('excluded_types') or []}
            rows.append({'feature_id':c.source_definition_id,
                         'damage_types':[k for k in _DAMAGE_TYPES if k not in excluded],
                         'source':c.data.get('label','').split(':')[0] or None,'expires_on':c.expires_on})
    return rows or None


@hook('condition_attempt')
def lesser_possession(ctx,subject,row):
    for c in subject.conditions.values():
        protected = row.get('condition') in c.data.get('protected_conditions', [])
        # Condition rows represent involuntary effects by default. An effect
        # that the recipient has accepted may set involuntary=false; this is a
        # generic row contract consumed by any transformation effect plug-in.
        protected_involuntary = row.get('condition') != 'transformed' or row.get('involuntary', True) is not False
        if (c.data.get('qi5_defensive_form') and protected and protected_involuntary
                and type(ctx.numbers.get('cl')) is int and ctx.numbers['cl']<int(c.data['source_cl'])):
            return False
    return None


def cloud_step_protection(engine, target):
    """Only the holder's own active Cloud Step flight supplies this defense."""
    return target is not None and any(
        c.condition_id == 'condition:typed.general_flight'
        and c.source_actor_id == target.entity_id
        and _source(engine, c.source_definition_id) == CLOUD + 'cloud_step'
        for c in target.conditions.values())


@hook('attack_mode')
def cloud_opportunity(ctx,target):
    if (ctx.typed.get('opportunity_of') or 'opportunity' in str(ctx.source)) and cloud_step_protection(ctx.engine, target):
        return 'DISADVANTAGE'
    return None


@hook('native_reaction_roll_mode')
def cloud_native_opportunity(engine, context):
    # Native roster/runtime OAs bypass typed attack_mode. The accepted native
    # reaction seam composes this defense with all other d20 sources; ordinary
    # attacks and other native reactions receive no contribution.
    if context.get('source_id') == 'system:combat.opportunity_attack':
        target = engine.state.actors.get(context.get('target_id'))
        if cloud_step_protection(engine, target):
            return {'mode': 'DISADVANTAGE', 'effect': 'Cloud Step', 'owner': target,
                    'why': 'the defender’s own active Cloud Step flight gives the Opportunity Attack Disadvantage'}
    return None
