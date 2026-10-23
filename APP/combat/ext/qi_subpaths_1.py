"""Source-qualified Heartmend and Tea Sage combat choices.

The general next_d20_mode and source_condition_relief effects are opt-in rows.
They preserve native roll modes, original save provenance and exact-instance
cleanup. Feature-specific handlers stay here, outside the core engine.
"""
from dataclasses import replace
from . import effect, hook

PULSE = 'tianxia.subpath.qi.emotion_cultivator.feature.emotional_pulse'
HEART = 'tianxia.subpath.qi.emotion_cultivator.feature.heartbreak_and_heartmend'
TEA = 'tianxia.subpath.qi.tea_sage_cultivator.feature.grandmaster_infusion'
EXPOSURE = 'condition:typed.emotional_pulse_exposure'
NEXT = 'condition:typed.next_d20_mode'
SERVICE = 'condition:typed.nine_temperature_received'
EMOTIONS = {'grief', 'panic', 'despair', 'shock', 'supernatural_agitation'}


def subjects(ctx):
    return [ctx.target] if ctx.target is not None else list(ctx.targets)


@effect('next_d20_mode')
def next_mode(ctx, row):
    from ..typed_executor import effect_expiry
    mode = row.get('mode', 'ADVANTAGE')
    kinds = row.get('kinds', ['attack', 'check', 'save'])
    if mode not in {'ADVANTAGE', 'DISADVANTAGE'} or not set(kinds) <= {'attack', 'check', 'save'}:
        raise ValueError('next_d20_mode requires valid mode and roll kinds')
    rule = {}
    if 'attack' in kinds:
        rule['attacks_have'] = mode
    if 'check' in kinds:
        rule['check_mode'] = {'ALL': mode}
    if 'save' in kinds:
        rule['save_mode'] = {a: mode for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')}
        # Death saves read a separate native rule but share the d20 checkpoint.
        rule['death_save_mode'] = {'mode': mode, 'first': False}
    for subject in subjects(ctx):
        ctx.engine._apply_condition(subject, NEXT, ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, row, subject, condition=True),
            data={'rule': rule, 'kinds': list(kinds), 'label': f'{mode.title()} on the next qualifying roll'})


@hook('d20_bonus')
def consume_next_mode(engine, roll, intent):
    # This is the actual post-draw checkpoint, never a menu/AI mode query.
    category = {'ATTACK': 'attack', 'CHECK': 'check', 'SAVE': 'save',
                'QI_HAZARD_DEX_SAVE': 'save'}.get(str(roll.reason).partition(':')[0])
    actor = engine.state.actors.get(roll.actor_id)
    if actor is None or category is None or roll.natural_result is None:
        return None
    from .condition_ownership import remove_instance
    for held in list(actor.conditions.values()):
        if held.condition_id == NEXT and category in held.data.get('kinds', []):
            remove_instance(engine, actor, held.instance_id, held.source_definition_id)
    return None


def relief_options(ctx, subject, row):
    from .end_effect import known_source_cl
    from .repeat_saves import save_of
    names = set(row.get('conditions') or [])
    categories = set(row.get('categories') or [])
    mine = int(ctx.numbers.get('cl') or 1)
    result = []
    for iid, held in subject.conditions.items():
        name = held.condition_id.removeprefix('condition:typed.')
        if not held.condition_id.startswith('condition:typed.'):
            continue
        tags = set(held.data.get('categories') or [])
        if name not in names and name not in categories and not tags.intersection(categories):
            continue
        if held.data.get('permanent') or (held.data.get('secret')
                and ctx.actor.entity_id not in held.data.get('authorized_readers', [])):
            continue
        level = known_source_cl(ctx, held)
        if level is None:
            continue
        if row.get('strictly_lower') and level >= mine:
            continue
        if row.get('equal_or_higher') and level < mine:
            continue
        if row.get('operation') == 'repeat':
            if save_of(held) is not None and (not row.get('higher_only') or level > mine):
                result.append((iid, held))
        elif level <= mine:
            result.append((iid, held))
    return result


@effect('source_condition_relief')
def condition_relief(ctx, row):
    from .needle import ask, checkpoint_id, CHOICE
    from .end_effect import remove_instance
    from .repeat_saves import save_of
    for subject in subjects(ctx):
        options = relief_options(ctx, subject, row)
        if not options:
            continue
        labels = {iid: held.data.get('label') or held.condition_id.rsplit('.', 1)[-1].replace('_', ' ').title()
                  for iid, held in options}
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'source_relief', ctx.source, subject.entity_id),
            ctx.actor, CHOICE + 'source_relief', list(labels), labels=labels, minimum=1, maximum=1,
            preferred=list(labels)[:1], target_id=subject.entity_id,
            prompt=f'{ctx.action.display_name}: choose one effect on {subject.display_name} to '
                   + ('repeat its saving throw with Advantage.' if row.get('operation') == 'repeat' else 'end.'))
        for iid, held in options:
            if iid not in chosen or iid not in subject.conditions:
                continue
            if row.get('operation') == 'repeat':
                save = save_of(held)
                roll = ctx.engine._roll_save(subject, str(save['ability']).upper(), int(save['dc']), ctx.source,
                    'ADVANTAGE', roll_context={'source_actor_id': held.source_actor_id,
                        'named': [held.condition_id.removeprefix('condition:typed.')]})
                if roll is None or roll.total < int(save['dc']):
                    continue
            remove_instance(ctx, subject, 'condition', iid, held)


@hook('candidate_allowed')
def heartbreak_target(engine, actor, candidate, action):
    if action is None:
        return None
    typed = action.parameters.get('typed') or {}
    if typed.get('source') != HEART or not any(r.get('type') == 'qi_heartbreak' for r in typed.get('effects') or []):
        return None
    return all(any(c.condition_id == EXPOSURE and c.source_actor_id == actor.entity_id
                   for c in engine.state.actors[who].conditions.values()) for who in candidate.target_ids)


@effect('qi_heartbreak')
def heartbreak(ctx, row):
    from ..typed_executor import run_effects
    for subject in subjects(ctx):
        from ..typed_executor import condition_immune
        if condition_immune(ctx.engine, subject, 'emotion') or condition_immune(ctx.engine, subject, 'mind'):
            continue
        if not any(c.condition_id == EXPOSURE and c.source_actor_id == ctx.actor.entity_id
                   for c in subject.conditions.values()):
            continue
        bonus = int(ctx.numbers.get('pb') or 0) if any(c.source_actor_id == ctx.actor.entity_id
            and c.condition_id in {'condition:typed.charmed', 'condition:typed.frightened'}
            for c in subject.conditions.values()) else 0
        damage = {'type': 'damage', 'applies_to': 'target', 'dice': {'count': 8, 'sides': 8},
                  'flat': bonus, 'damage_types': ['psychic']}
        run_effects(replace(ctx, target=subject, targets=[subject]), [{
            'type': 'save', 'ability': 'wis', 'applies_to': 'target', 'save_categories': ['mind', 'emotion'],
            'on_fail': [damage, {'type': 'reaction_denied', 'applies_to': 'target',
                                'expires_on': 'END_OF_HOLDER_NEXT_TURN'}],
            'on_success': [{'type': 'half_damage'}, {'type': 'reaction_denied', 'applies_to': 'target',
                                'expires_on': 'START_OF_TARGET_NEXT_TURN'}]}])


@effect('qi_heartmend')
def heartmend(ctx, row):
    from ..typed_executor import run_effects
    from .rider_outcomes import menu
    for subject in subjects(ctx):
        from ..relations import relation
        if subject is not ctx.actor:
            from .willing_targets import asks_consent
            accepted = asks_consent(ctx.engine, ctx.intent, subject, ctx.action.display_name,
                f'{subject.display_name}: accept Heartmend from {ctx.actor.display_name}?',
                prefer_accept=relation(ctx.engine, ctx.actor, subject) == 'ALLY', asker=ctx.actor)
            if not accepted:
                continue
        local = replace(ctx, target=subject, targets=[subject])
        from ..typed_executor import condition_immune
        if condition_immune(ctx.engine, subject, 'emotion') or condition_immune(ctx.engine, subject, 'mind'):
            continue
        run_effects(local, [{'type': 'healing', 'applies_to': 'target', 'dice': {'count': 4, 'sides': 8},
                            'formula': 'key_ability_modifier'}])
        options = [{'id': 'temporary_hp', 'label': 'Gain Temporary Hit Points equal to twice your Proficiency Bonus',
                    'effects': [{'type': 'temp_hp', 'applies_to': 'target', 'formula': 'double_pb'}]}]
        for name in ('charmed', 'frightened'):
            relief = {'type': 'source_condition_relief', 'conditions': [name], 'operation': 'end'}
            if relief_options(local, subject, relief):
                options.append({'id': name, 'label': f'End one {name.title()} effect created by a creature whose Cultivation Level (the number on its character sheet) is no higher than yours', 'effects': [relief]})
        emotional = {'type': 'source_condition_relief', 'categories': sorted(EMOTIONS), 'operation': 'end'}
        if relief_options(local, subject, emotional):
            options.append({'id': 'emotional', 'label': 'End one ordinary emotional impairment created by a creature whose Cultivation Level (the number on its character sheet) is no higher than yours', 'effects': [emotional]})
        repeated = {'type': 'source_condition_relief', 'conditions': ['charmed', 'frightened'],
                    'categories': sorted(EMOTIONS), 'operation': 'repeat', 'higher_only': True}
        if relief_options(local, subject, repeated):
            options.append({'id': 'repeat', 'label': 'Repeat one emotional save against an effect created by a creature whose Cultivation Level (the number on its character sheet) is higher than yours, with Advantage', 'effects': [repeated]})
        menu(local, {'id': 'heartmend', 'label': 'Heartmend additional benefit', 'options': options})


@effect('qi_nine_temperature')
def nine_temperature(ctx, row):
    from .needle import ask, checkpoint_id, CHOICE
    from ..target_knowledge import located
    from ..targeting import line_of_effect
    from ..relations import relation
    from ..zones import uses_default_shape
    automatic = uses_default_shape(ctx.engine, ctx.actor)
    pool = [s for s in ctx.engine.state.actors.values() if s.active
            and ctx.engine._distance_actor_to_actor(ctx.actor, s) <= 30
            and line_of_effect(ctx.engine, ctx.actor, target=s)
            and not any(c.condition_id == SERVICE for c in s.conditions.values())
            and (s is ctx.actor or located(ctx.engine, ctx.actor, s))
            and (not automatic or s is ctx.actor or relation(ctx.engine, ctx.actor, s) == 'ALLY')]
    maximum = min(int(ctx.numbers.get('pb') or 0), len(pool))
    if not maximum:
        return
    preferred = [s.entity_id for s in pool if relation(ctx.engine, ctx.actor, s) == 'ALLY'][:maximum]
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'nine_temperature', ctx.source), ctx.actor,
        CHOICE + 'nine_temperature_targets', [s.entity_id for s in pool],
        labels={s.entity_id: s.display_name for s in pool}, minimum=0, maximum=maximum, allow_decline=True,
        preferred=preferred, default_count=len(preferred),
        prompt=f'Nine-Temperature Service: choose up to {maximum} willing creatures within 30 feet. Spend 5 Qi and your Action; each receives a different benefit, once this scene.')
    used = set()
    for subject in pool:
        if subject.entity_id not in picked:
            continue
        if subject is not ctx.actor:
            from .willing_targets import asks_consent
            accepted = asks_consent(ctx.engine, ctx.intent, subject, ctx.action.display_name,
                f'{subject.display_name}: accept Nine-Temperature Service from {ctx.actor.display_name}?',
                prefer_accept=relation(ctx.engine, ctx.actor, subject) == 'ALLY', asker=ctx.actor)
            if not accepted:
                continue
        local = replace(ctx, target=subject, targets=[subject])
        options = [
            {'id': 'heal', 'label': 'Restore 3d8 + key ability modifier Hit Points', 'effects': [
                {'type': 'healing', 'applies_to': 'target', 'dice': {'count': 3, 'sides': 8}, 'formula': 'key_ability_modifier'}]},
            {'id': 'temporary_hp', 'label': 'Gain Temporary Hit Points equal to three times Proficiency Bonus', 'effects': [
                {'type': 'temp_hp', 'applies_to': 'target', 'formula': 'triple_pb'}]},
            {'id': 'move', 'label': 'Move up to 15 feet without Opportunity Attacks', 'effects': [
                {'type': 'movement', 'applies_to': 'target', 'distance_ft': 15, 'choose_subject_destination': True,
                 'no_opportunity_attacks': True}]},
            {'id': 'advantage', 'label': 'Advantage on the next attack, check or save before the end of the next turn', 'effects': [
                {'type': 'next_d20_mode', 'expires_on': 'END_OF_HOLDER_NEXT_TURN'}]},
        ]
        relief = {'type': 'source_condition_relief', 'operation': 'end', 'conditions': ['charmed', 'frightened', 'poisoned']}
        if relief_options(local, subject, relief):
            options.append({'id': 'end', 'label': 'End one Charmed, Frightened or Poisoned effect created by a creature whose Cultivation Level (the number on its character sheet) is no higher than yours', 'effects': [relief]})
        repeat = {'type': 'source_condition_relief', 'operation': 'repeat',
                  'conditions': ['possessed', 'dream_sleep', 'diseased', 'altered_memory', 'meridian_suppression'],
                  'categories': ['possession', 'dream', 'altered_memory', 'disease', 'meridian_suppression']}
        if relief_options(local, subject, repeat):
            options.append({'id': 'repeat', 'label': 'Repeat one possession, Dream, memory, disease or meridian save with Advantage', 'effects': [repeat]})
        options = [o for o in options if o['id'] not in used]
        if not options:
            break
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'nine_temperature_benefit', subject.entity_id),
            ctx.actor, CHOICE + 'nine_temperature_benefit', [o['id'] for o in options],
            labels={o['id']: o['label'] for o in options}, minimum=1, maximum=1, preferred=[options[0]['id']],
            prompt=f'Nine-Temperature Service: choose one different benefit for {subject.display_name}. No extra cost.')
        from ..typed_executor import run_effects
        for option in options:
            if option['id'] in chosen:
                used.add(option['id'])
                run_effects(local, option['effects'])
                ctx.engine._apply_condition(subject, SERVICE, ctx.source, ctx.actor.entity_id,
                    expires_on='UNTIL_REMOVED', data={'label': 'Received Nine-Temperature Service this scene'})


@hook('compile_actions')
def tea_service_action(info):
    if TEA not in (info.get('owned_ids') or []):
        return None
    from ..gate2_runtime_models import ActionDefinition
    from ..factory_compiler import RESOURCE_IDS
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.nine_temperature_service",
        display_name='Nine-Temperature Service', owner_id=info['actor_id'], economy='ACTION',
        resolution_kind='TYPED', target_kind='SELF', range_ft=None,
        costs=((RESOURCE_IDS['qi'], 5),), parameters={'typed': {'source': TEA,
            'effects': [{'type': 'qi_nine_temperature'}], 'numbers': dict(info['numbers']),
            'riders': [], 'duration': {'kind': 'instant'}, 'coverage': 'FULL'}, 'expected_damage': 0,
            'description': 'Spend your Action and 5 Qi to serve up to your Proficiency Bonus willing creatures within 30 feet. Each receives a different benefit, once per scene.'})]

RAGE = 'condition:typed.emotional_rage'
SORROW = 'condition:typed.emotional_sorrow'
CALM = 'condition:typed.emotional_calm'


@effect('qi_pulse')
def emotional_pulse(ctx, row):
    """Resolve real recipient choices; return whether any recipient accepted/resolved the Pulse."""
    from ..typed_executor import run_effects
    from ..relations import relation
    form = row['form']
    applied = False
    for subject in subjects(ctx):
        local = replace(ctx, target=subject, targets=[subject])
        from ..typed_executor import condition_immune
        if condition_immune(ctx.engine, subject, 'emotion') or condition_immune(ctx.engine, subject, 'mind'):
            continue
        outcome = {'type': 'emotion_pulse_outcome', 'form': form,
                   'secondary': bool(row.get('secondary'))}
        if form == 'sorrow':
            # A new Pulse replaces this caster's pending Sorrow even when the
            # target succeeds; the earlier instance must not survive the new save.
            refresh_sorrow(ctx, subject)
        if form.startswith('willing_'):
            if subject is not ctx.actor:
                from .willing_targets import asks_consent
                accepted = asks_consent(ctx.engine, ctx.intent, subject, ctx.action.display_name,
                    f'{subject.display_name}: accept {ctx.action.display_name} from {ctx.actor.display_name}?',
                    prefer_accept=relation(ctx.engine, ctx.actor, subject) == 'ALLY', asker=ctx.actor)
                if not accepted:
                    continue
            benefit = ({'type':'temp_hp','formula':'pb','applies_to':'target'} if form=='willing_joy' else
                {'type':'advantage','applies_to':'target','on':'its next saving throw against Charmed or Frightened',
                 'expires_on':'START_OF_SOURCE_NEXT_TURN'})
            run_effects(local,[benefit, {'type':'movement','applies_to':'target','distance_ft':5,
                'choose_subject_destination':True,'no_opportunity_attacks':True},
                {**outcome, 'failed': False}])
        else:
            denied={'type':'reaction_denied','applies_to':'target','expires_on':'START_OF_TARGET_NEXT_TURN'}
            if form=='fear':
                failed=[{'type':'condition','condition':'frightened','applies_to':'target',
                         'expires_on':'START_OF_SOURCE_NEXT_TURN'}]
            elif form=='rage':
                failed=[{'type':'qi_pulse_rage','expires_on':'START_OF_SOURCE_NEXT_TURN'}]
            elif form=='sorrow':
                failed=[{'type':'qi_pulse_sorrow','dice':True,'expires_on':'START_OF_SOURCE_NEXT_TURN'}]
                denied={'type':'qi_pulse_sorrow','dice':False,'expires_on':'START_OF_SOURCE_NEXT_TURN'}
            elif form=='hostile_joy':
                failed=[denied,{'type':'disadvantage','applies_to':'target','on':'its next Concentration saving throw',
                               'expires_on':'START_OF_TARGET_NEXT_TURN'}]
            elif form=='hostile_calm':
                failed=[{'type':'qi_pulse_calm','expires_on':'START_OF_SOURCE_NEXT_TURN'}]
                denied={'type':'qi_pulse_calm','only_oa':True,'expires_on':'START_OF_TARGET_NEXT_TURN'}
            else:
                raise ValueError('Unknown Emotional Pulse form')
            failed.append({**outcome, 'failed': True})
            # Fear immunity explicitly forces success, including its success rider.
            from ..typed_executor import condition_immune
            from .emotion_cultivator import source_frightened_immunity
            if form=='fear' and source_frightened_immunity(local, subject):
                run_effects(local,[denied, {**outcome, 'failed': False}])
            else:
                from .willing_targets import asks_consent
                accept = asks_consent(ctx.engine, ctx.intent, subject, ctx.action.display_name,
                    f'{subject.display_name}: choose to fail the Wisdom saving throw and accept this Emotional Pulse?',
                    prefer_accept=False, asker=ctx.actor)
                if accept:
                    run_effects(replace(local, failed_save=True, origin_save={
                        'ability': 'WIS', 'dc': int(ctx.numbers['save_dc'])}), failed)
                else:
                    run_effects(local,[{'type':'save','ability':'wis','applies_to':'target',
                        'save_categories': ['mind', 'emotion', 'emotional_escalation'],
                        'on_fail':failed,'on_success':[denied, {**outcome, 'failed': False}]}])
        applied = True
    return applied


@effect('qi_pulse_rage')
def pulse_rage(ctx,row):
    from ..typed_executor import effect_expiry
    for subject in subjects(ctx):
        from .emotion_cultivator import pick
        from ..target_knowledge import located
        from ..relations import relation
        pool = [a for a in ctx.engine.state.actors.values() if a.active and a is not subject
            and located(ctx.engine, subject, a)]
        hostiles = pick(ctx, subject, 'rage_hostiles', [a.entity_id for a in pool],
            {a.entity_id: a.display_name for a in pool},
            f'{subject.display_name}: record which creatures you currently perceive as hostile for {ctx.action.display_name}. Rage does not compel an attack or spending a limited feature.',
            minimum=0, maximum=len(pool), known=[a.entity_id for a in pool if relation(ctx.engine, subject, a) == 'ENEMY'])
        ctx.engine._apply_condition(subject,RAGE,ctx.source,ctx.actor.entity_id,
            expires_on=effect_expiry(ctx,row,subject,condition=True),
            data={'hostile_ids': hostiles, 'label':f'Rage: attacks against anyone except the nearest hostile creature you can perceive have Disadvantage. Your voluntary movement cannot take you farther from that creature. This ends at the start of {ctx.actor.display_name}’s next turn.'})


def nearest_hostiles(engine,actor):
    from ..target_knowledge import located
    from ..relations import relation
    held = max((c for c in actor.conditions.values() if c.condition_id == RAGE), key=lambda c: c.applied_sequence, default=None)
    declared = set(held.data['hostile_ids']) if held and 'hostile_ids' in held.data else None
    foes=[s for s in engine.state.actors.values() if s.active and
          (s.entity_id in declared if declared is not None else relation(engine,actor,s)=='ENEMY') and located(engine,actor,s)]
    if not foes:
        return []
    distance=min(engine._distance_actor_to_actor(actor,s) for s in foes)
    return [s for s in foes if engine._distance_actor_to_actor(actor,s)==distance]


def rage_nearest(engine, actor, intent):
    pool = nearest_hostiles(engine, actor)
    if len(pool) < 2:
        return pool
    from .needle import ask, checkpoint_id
    held = max((c for c in actor.conditions.values() if c.condition_id == RAGE), key=lambda c: c.applied_sequence)
    key = '|'.join(sorted(a.entity_id for a in pool))
    if held.data.get('nearest_key') == key and held.data.get('nearest_id') in {a.entity_id for a in pool}:
        return [engine.state.actors[held.data['nearest_id']]]
    chosen = ask(engine, intent, checkpoint_id(engine, 'emotion_rage_tie', actor.entity_id), actor,
        'choice:needle.emotion.rage_tie', [a.entity_id for a in pool],
        labels={a.entity_id: a.display_name for a in pool}, minimum=1, maximum=1,
        prompt=f'Rage: {actor.display_name}, choose between the equally near creatures you perceive as hostile. Attacks against other creatures have Disadvantage, and you cannot willingly move farther from your choice.')
    if chosen:
        engine._update_condition_data(actor, held, {**held.data, 'nearest_key': key, 'nearest_id': chosen[0]}, held.source_definition_id)
        return [engine.state.actors[chosen[0]]]
    return []


def raging(actor):
    return any(c.condition_id==RAGE for c in actor.conditions.values())


@hook('before_attack')
def rage_attack(engine,actor,target,intent,spec):
    if not raging(actor):
        return None
    nearest=rage_nearest(engine,actor,intent)
    return {'mode':'DISADVANTAGE'} if nearest and target not in nearest else None


@hook('movement_attempt')
def rage_movement(engine,mover,previous,nxt,intent):
    if not raging(mover):
        return None
    nearest=rage_nearest(engine,mover,intent)
    if nearest and all(engine._distance_actor_to_actor(mover,s,actor_position=nxt)>engine._distance_actor_to_actor(mover,s,actor_position=previous) for s in nearest):
        return {'stop':True,'source_id':next(c.source_definition_id for c in mover.conditions.values() if c.condition_id==RAGE),
                'label':'Rage: voluntary movement cannot take you farther from the nearest hostile creature you can perceive'}
    return None


def refresh_sorrow(ctx, subject):
    """Refresh one source family's Sorrow; a different printed feature remains independent."""
    from .condition_ownership import remove_instance
    source = ctx.typed.get('source')
    for held in list(subject.conditions.values()):
        action = ctx.engine.action_catalog.get(held.source_definition_id)
        previous = (action.parameters.get('typed') or {}).get('source') if action else held.source_definition_id
        if held.condition_id == SORROW and held.source_actor_id == ctx.actor.entity_id and previous == source:
            remove_instance(ctx.engine, subject, held.instance_id, ctx.source)


@effect('qi_pulse_sorrow')
def pulse_sorrow(ctx,row):
    from ..typed_executor import effect_expiry
    for subject in subjects(ctx):
        refresh_sorrow(ctx, subject)
        # A later Sorrow from this caster replaces their pending one, including
        # its success/failure result. Other casters retain independent effects.
        ctx.engine._apply_condition(subject,SORROW,ctx.source,ctx.actor.entity_id,
            expires_on=effect_expiry(ctx,row,subject,condition=True),
            data={'dice':bool(row.get('dice')),'label':('Sorrow: subtract 1d4 from the next attack or saving throw, until the start of the caster\'s next turn' if row.get('dice')
                  else 'Sorrow: subtract 1 from the next attack, until the start of the caster\'s next turn')})


@hook('d20_bonus')
def sorrow_penalty(engine,roll,intent):
    category=str(roll.reason).partition(':')[0]
    if category not in {'ATTACK','SAVE','QI_HAZARD_DEX_SAVE'} or roll.natural_result is None:
        return None
    actor=engine.state.actors.get(roll.actor_id)
    if actor is None:
        return None
    from .condition_ownership import remove_instance
    from ..gate2_runtime_models import DiceSpec
    total=0
    source=None
    for held in list(actor.conditions.values()):
        if held.condition_id!=SORROW or (not held.data.get('dice') and category!='ATTACK'):
            continue
        if held.data.get('dice'):
            penalty=engine.roller.roll(DiceSpec(count=1,sides=4,modifier=0),actor_id=actor.entity_id,reason='Sorrow penalty')
            engine._record_roll(penalty)
            value=penalty.total
        else:
            value=1
        total+=value;source=held.source_definition_id
        remove_instance(engine,actor,held.instance_id,source)
    return {'bonus':-total,'source_id':source} if total else None


@effect('qi_pulse_calm')
def pulse_calm(ctx,row):
    from ..typed_executor import effect_expiry
    for subject in subjects(ctx):
        ctx.engine._apply_condition(subject,CALM,ctx.source,ctx.actor.entity_id,
            expires_on=effect_expiry(ctx,row,subject,condition=True),
            data={'rule':{'no_opportunity_attacks':True},'escalation':not row.get('only_oa'),
                  'label':(f"Calm: cannot make Opportunity Attacks or use Rage, Fury, Berserk, or Frenzy features until the start of {ctx.actor.display_name}'s next turn" if not row.get('only_oa') else
                           'Calm: cannot make Opportunity Attacks until the start of your next turn')})


@hook('opportunity_allowed')
def calm_opportunity(engine,actor,target):
    return False if any(c.condition_id==CALM for c in actor.conditions.values()) else None


@hook('candidate_allowed')
def calm_escalation(engine,actor,candidate,action):
    if action is None or not any(c.condition_id==CALM and c.data.get('escalation') for c in actor.conditions.values()):
        return None
    # The compiled action's printed category is authoritative; its label is not.
    typed = action.parameters.get('typed') or {}
    recorded = any(typed.get('source') in c.data.get('feature_ids', []) for c in actor.conditions.values()
        if c.condition_id == 'condition:typed.emotion_source_classifications')
    return False if recorded or 'emotional_escalation' in typed.get('activation_categories',[]) else None


@hook('compile_action')
def classify_emotional_escalation(action,info):
    typed=action.parameters.get('typed') or {}
    source=(info.get('mechanics') or {}).get(typed.get('source')) or {}
    # Only authored source classification grants an emotional-escalation tag.
    # A feature name, style, damage type or absence of metadata is not authority.
    if 'emotional_escalation' not in source.get('activation_categories', []):
        return None
    categories=list(dict.fromkeys([*(typed.get('activation_categories') or []),'emotional_escalation']))
    return action.model_copy(update={'parameters':{**action.parameters,'typed':{**typed,'activation_categories':categories}}})


@hook('teleport_gate')
def rage_own_teleport(ctx,start,destination):
    # Foreign teleportation is not the bearer's voluntary movement.
    if ctx.action.owner_id != ctx.actor.entity_id or not raging(ctx.actor):
        return None
    nearest=rage_nearest(ctx.engine,ctx.actor,ctx.intent)
    if nearest and all(ctx.engine._distance_actor_to_actor(ctx.actor,s,actor_position=destination)>
                       ctx.engine._distance_actor_to_actor(ctx.actor,s,actor_position=start) for s in nearest):
        ctx.rider('Choose a destination that does not move farther from the nearest hostile creature you can perceive.')
        return False
    return None
