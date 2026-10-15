"""Second Furnace Core: opt-in Devil Qi substitution and evented Furnace Motion.

Uses the general payment substitution receipt. The player's setting specifies
how many points of each ordinary Qi cost to pay with Devil Qi; zero uses Qi.
Continuity reads committed source-scoped interference through furnace_runtime.
"""
from . import effect, hook

CORE = 'tianxia.subpath.qi.devil_heart_second_furnace.feature.second_furnace_core'
QI, DEVIL = 'resource:core.qi', 'resource:named.devil_qi'
SETTING = 'condition:typed.furnace_payment'
CHECK = 'condition:typed.furnace_motion_check'
BLOCK = 'furnace_core'


@hook('compile_passives')
def ownership(rows, info):
    if CORE not in info['owned_ids']:
        return rows
    return [*rows, {'block': BLOCK, 'feature_id': CORE, 'numbers': dict(info['numbers'])}]


@hook('compile_resources')
def resource(info):
    if 'tianxia.subpath.qi.devil_heart_second_furnace.feature.demon_seed_overdraw' not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ResourceDefinition
    return [ResourceDefinition(resource_id=DEVIL, initial=0, maximum=int(info["numbers"]["pb"])),
            ResourceDefinition(resource_id="resource:named.corruption", initial=0, maximum=10)]


@hook('compile_actions')
def payment_settings(info):
    if CORE not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.furnace_payment",
        display_name='Second Furnace: choose Qi payment', owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='SELF', parameters={'player_only': True, 'setting_only': True,
        'setting_description': 'Choose how many points of each ordinary Qi cost to pay with Devil Qi. Choose zero to use ordinary Qi. This choice costs no action or resource.',
        'typed': {'source': CORE, 'numbers': dict(info['numbers']), 'duration': {'kind':'instant'},
                  'effects': [{'type':'furnace_payment_setting'}], 'riders': []}})]


@effect('furnace_core_ownership')
def passive(ctx, row):
    pass  # compiled ownership only, never an active resource grant


@effect('furnace_payment_setting')
def setting(ctx, row):
    from .needle import ask, checkpoint_id
    values = [str(n) for n in range(int(ctx.actor.resource_maximums.get(DEVIL,ctx.numbers["pb"])) + 1)]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'furnace_payment'), ctx.actor,
        'choice:needle.furnace_payment', values, preferred=['0'],
        labels={n: 'Use ordinary Qi' if n == '0' else f'Pay up to {n} Qi with Devil Qi per activation' for n in values},
        name='Second Furnace Core', feature_id=CORE,
        prompt='Second Furnace Core: choose the number of ordinary Qi points to replace with Devil Qi, one for one. The rest is paid with Qi. You can change this free setting before each activation.')
    if chosen:
        ctx.engine._remove_condition(ctx.actor, SETTING, ctx.source)
        ctx.engine._apply_condition(ctx.actor, SETTING, ctx.source, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'amount':int(chosen[0]), 'label':f'Second Furnace: replace up to {chosen[0]} Qi with Devil Qi'})


def owned_row(engine, actor):
    return next((r for r in engine.typed_passive_rows.get(actor.entity_id, []) if r.get('block') == BLOCK), None)


def eligible(action, actor):
    return action is not None and action.owner_id==actor.entity_id


@hook('payment_substitution')
def substitute(engine, actor, source, costs, missing):
    from ..alternative_payments import PaymentAlternative
    from . import furnace_runtime as f
    if not devil_payment_permitted(engine,actor,source):return None
    if any(r!=QI for r in missing):return None
    held=next((c for c in actor.conditions.values() if c.condition_id==SETTING),None)
    maximum=min(costs.get(QI,0),actor.resources.get(DEVIL,0))
    if held:maximum=min(maximum,int(held.data.get('amount',0)))
    minimum=max(1,missing.get(QI,0),costs.get(QI,0) if f.ordinary_suppressed(actor) else 0)
    return tuple(PaymentAlternative(CORE,'Second Furnace Core',((QI,count),),costs=((DEVIL,count),))
        for count in range(minimum,maximum+1)) or None


@hook('state_event')
def spent(engine, event):
    if event.event_type != 'RESOURCE_SPENT' or event.payload.get('resource_id') != DEVIL or int(event.payload.get('amount', 0)) <= 0:
        return None
    actor = engine.state.actors.get(event.actor_id)
    intent = getattr(engine, '_active_intent', None)
    if actor is None or intent is None:
        return None
    source = event.source_definition_id
    row = owned_row(engine, actor)
    from . import furnace_runtime as f
    if row is None or not f.owns(engine,actor,CORE) or (f.acquired(actor) and not f.usable(engine,actor)):
        return None
    from .states import context
    from .needle import ask, checkpoint_id
    from .. import typed_executor as te
    from . import qi_path
    from .devil_heart_second_furnace import move_armament_choice
    ctx = f.context(engine,actor,CORE)
    ctx.intent = intent
    from ..activation_payments import source_action
    trigger_action = source_action(engine,actor,source) or ctx.action
    available = ['temp_hp', 'move', 'check']
    if qi_path.armament_condition(actor) is not None:
        available.append('armament')
    if any(c.condition_id == 'condition:typed.prone' for c in actor.conditions.values()):
        available.append('stand')
    available = [k for k in available if not actor.turn_flags.get('typed_once_turn:furnace_motion:' + k)]
    multiplier=2 if f.engine_benefits(engine,actor) else 1
    labels = {'temp_hp':f'Gain {multiplier*int(row["numbers"]["pb"])} Temporary Hit Points', 'move':'Move up to 10 feet without provoking Opportunity Attacks',
              'check':f'Add your Proficiency Bonus ({row["numbers"]["pb"]}) to your next Cultivation Check before your next turn ends',
              'armament':'Move your Domain Armament up to 20 feet', 'stand':'Stand from Prone without spending movement'}
    if available:
        from .choice_prompt import action_context
        pick = ask(engine, intent, checkpoint_id(engine, 'furnace_motion', source), actor,
            'choice:needle.furnace_motion', available, labels={k:labels[k] for k in available},
            allow_decline=True, name='Furnace Motion', feature_id=CORE,
            prompt=f'Furnace Motion: {actor.display_name} spent Devil Qi using {trigger_action.display_name}. Choose one benefit, each available once per turn. No extra action or resource cost.',
            prompt_context={**action_context(engine, actor, source, actor, action=trigger_action),'cost':'No extra action or resource cost'})
        if pick:
            kind = pick[0]
            used = False
            if kind == 'temp_hp':
                from .furnace_runtime import temp_hp
                temp_hp(engine,actor,CORE)
                used = True
            elif kind == 'move':
                before = actor.position
                te.run_effects(ctx, [{'type':'rider_step', 'distance_ft':10, 'no_oa':True, 'label':'Furnace Motion'}])
                used = actor.position != before
            elif kind == 'armament':
                used = move_armament_choice(ctx, actor, 20, feature_id=CORE, name='Furnace Motion')
            elif kind == 'stand':
                engine._remove_condition(actor, 'condition:typed.prone', source)
                used = not any(c.condition_id == 'condition:typed.prone' for c in actor.conditions.values())
            elif kind == 'check':
                engine._remove_condition(actor, CHECK, source)
                engine._apply_condition(actor, CHECK, source, actor.entity_id,
                    expires_on=f'END_OF_SOURCE_TURN_AT:{actor.turns_started + 1}',
                    data={'bonus':int(row['numbers']['pb']), 'label':f'Furnace Motion: +{row["numbers"]["pb"]} to your next Cultivation Check before your next turn ends'})
                used = True
            if used:
                actor.turn_flags['typed_once_turn:furnace_motion:' + kind] = True
    if (qi_path.armament_condition(actor) is not None
            and not actor.turn_flags.get('typed_once_turn:furnace_link')):
        moved = move_armament_choice(ctx, actor, 10, feature_id=CORE, name='Domain Armament Furnace Link', furnace_link=True)
        if moved:
            actor.turn_flags['typed_once_turn:furnace_link'] = True


@hook('d20_bonus')
def check_bonus(engine, roll, intent):
    scope = engine.d20_context() or {}
    if scope.get('kind') != 'check' or (scope.get('check_kind') != 'cultivation' and str(scope.get('skill') or '').lower() != 'cultivation'):
        return None
    actor = engine.state.actors.get(roll.actor_id)
    if actor is None:
        return None
    held = next((c for c in actor.conditions.values() if c.condition_id == CHECK), None)
    if held is None:
        return None
    from .condition_ownership import remove_instance
    remove_instance(engine, actor, held.instance_id, held.source_definition_id)
    return {'source_id':CORE, 'bonus':int(held.data['bonus'])}


@hook('compile_actions')
def furnace_link_appearance(info):
    if CORE not in info['owned_ids']:return None
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.furnace_armament_display",
        display_name='Domain Armament Furnace Link: choose its display',owner_id=info['actor_id'],economy=EconomyKind.NONE,
        resolution_kind='TYPED',target_kind='SELF',parameters={'setting_only':True,'player_only':True,
        'typed':{'source':CORE,'numbers':dict(info['numbers']),'duration':{'kind':'instant'},
            'effects':[{'type':'furnace_armament_display'}],'riders':[]}})]


@effect('furnace_armament_display')
def furnace_link_display(ctx,row):
    from . import qi_path
    from .furnace_runtime import choose
    held=qi_path.armament_condition(ctx.actor)
    if held is None:return
    names={'black_pulse':'A black pulse','eye':'An eye','ember':'An ember','jaw':'A jaw','rotating_seal':'A rotating seal'}
    selected=choose(ctx,'furnace_armament_display',list(names),names,
        f'{ctx.actor.display_name}: choose how your Domain Armament displays the second furnace. This costs no action or resource.')
    if selected:
        data={**held.data,'furnace_display':selected[0]}
        ctx.engine._remove_condition_instance(ctx.actor,held.instance_id,CORE)
        ctx.engine._apply_condition(ctx.actor,held.condition_id,held.source_definition_id,held.source_actor_id,
            expires_on=held.expires_on,data=data)


def devil_payment_permitted(engine,actor,source):
    """Public Core eligibility shared by direct and Overdraw mixed payments.

    Only the Qi component is substituted. Lifespan, maximum reductions and
    material components retain their original resource/component payment.
    """
    from . import furnace_runtime as f
    from ..alternative_payments import owned
    if not f.owns(engine,actor,CORE) or not owned(engine,actor,source):return False
    if f.acquired(actor) and not f.usable(engine,actor):return False
    profile=f.source_profile(engine,source,actor)
    if not profile.get('ordinary_qi') or any(profile.get(k) for k in ('sacrifice','another_creature')):return False
    if profile.get('artifact_charges') and not profile.get('accepts_devil_qi'):return False
    if any(profile.get(k) for k in ('secret','secret_law','immortal','immortal_art')) and not profile.get('accepts_devil_qi'):return False
    return True
