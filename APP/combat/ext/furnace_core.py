"""Second Furnace Core: opt-in Devil Qi substitution and evented Furnace Motion.

Uses the general payment substitution receipt. The player's setting specifies
how many points of each ordinary Qi cost to pay with Devil Qi; zero uses Qi.
Suppression authority and consecrated ward passage remain explicit partials.
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
    if not any(str(k).startswith('tianxia.subpath.qi.devil_heart_second_furnace.feature.') for k in info['owned_ids']):
        return None
    from ..gate2_runtime_models import ResourceDefinition
    return [ResourceDefinition(resource_id=DEVIL, initial=0, maximum=int(info["numbers"]["pb"]))]


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
    values = [str(n) for n in range(int(ctx.numbers["pb"]) + 1)]
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
    if action is None or action.owner_id != actor.entity_id:
        return False
    typed = action.parameters.get('typed') or {}
    source = str(typed.get('source') or '')
    # Explicit exclusions, not a permissive generic cost substitution.
    text = ' '.join([source, action.display_name, str(typed.get('tags') or ''), str(typed.get('cost_restrictions') or '')]).lower()
    if any(word in text for word in ('artifact', 'immortal', 'secret', 'permanent', 'sacrifice', 'lifespan', 'material')):
        return False
    return (source.startswith(('tianxia.path.qi_cultivation.', 'tianxia.subpath.qi.',
                              'tianxia.talent.', 'tianxia.recorded_art.', 'tianxia.forged_technique.',
                              'recorded_art.', 'forged_technique.', 'TAL_'))
            or bool(typed.get('sphere')) or bool(action.parameters.get('armament')))


@hook('payment_substitution')
def substitute(engine, actor, source, costs, missing):
    from ..alternative_payments import PaymentAlternative
    if owned_row(engine, actor) is None or not eligible(engine.action_catalog.get(source), actor):
        return None
    held = next((c for c in actor.conditions.values() if c.condition_id == SETTING), None)
    if held is None or any(r != QI for r in missing):
        return None
    count = min(int(held.data.get('amount', 0)), costs.get(QI, 0), actor.resources.get(DEVIL, 0))
    if count <= 0 or missing.get(QI, 0) > count:
        return None
    return PaymentAlternative(CORE, 'Second Furnace Core', ((QI, count),), costs=((DEVIL, count),))


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
    if row is None:
        return None
    from .states import context
    from .needle import ask, checkpoint_id
    from .. import typed_executor as te
    from . import qi_path
    from .devil_heart_second_furnace import move_armament_choice
    ctx = context(engine, actor, source, [actor], row['numbers'])
    ctx.intent = intent
    trigger_action = ctx.action
    available = ['temp_hp', 'move', 'check']
    if qi_path.armament_condition(actor) is not None:
        available.append('armament')
    if any(c.condition_id == 'condition:typed.prone' for c in actor.conditions.values()):
        available.append('stand')
    available = [k for k in available if not actor.turn_flags.get('typed_once_turn:furnace_motion:' + k)]
    labels = {'temp_hp':f'Gain Temporary Hit Points equal to your Proficiency Bonus ({row["numbers"]["pb"]})', 'move':'Move up to 10 feet without provoking',
              'check':f'Add your Proficiency Bonus ({row["numbers"]["pb"]}) to your next Cultivation Check before your next turn ends',
              'armament':'Move your Domain Armament up to 20 feet', 'stand':'Stand from Prone without spending movement'}
    if available:
        from .choice_prompt import action_context
        pick = ask(engine, intent, checkpoint_id(engine, 'furnace_motion', source), actor,
            'choice:needle.furnace_motion', available, labels={k:labels[k] for k in available},
            allow_decline=True, name='Furnace Motion', feature_id=CORE,
            prompt=f'Furnace Motion: {actor.display_name} spent Devil Qi using {trigger_action.display_name}. Choose one benefit, each available once per turn. No extra action or resource cost.',
            prompt_context=action_context(engine, actor, source, actor, action=trigger_action))
        if pick:
            kind = pick[0]
            used = False
            if kind == 'temp_hp':
                te.run_effects(ctx, [{'type':'temp_hp', 'applies_to':'self', 'formula':'pb'}])
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
        moved = move_armament_choice(ctx, actor, 10, feature_id=CORE, name='Domain Armament Furnace Link')
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
