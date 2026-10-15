"""Source-bound combat clauses from Cultivation Insights, Living Siege to Portable Workshop.

Ownership is sealed by hash-reviewed feature blocks, never inferred from an
ability name or the live sheet. Optional reactions use the shared d20 transport.
Actual payment snapshots exclude independent reactions and explicit refunds.
"""
from . import hook, note
from .passive_rows import row_of
from .ability_source import mechanic_of, mechanic_at
from .d20_rewrite import Rule, register

BLOCK = 'insights6'
PREFIX = 'insight.'
QI = 'resource:core.qi'
STAMINA = 'resource:core.stamina'
BREATH = PREFIX + 'meridian-breath-discipline'
ECONOMY = PREFIX + 'meridian-economy'
PINCER = PREFIX + 'meridian-pincer-method'
ONE = PREFIX + 'one-breath-discipline'
FRAME = PREFIX + 'mountain-forged-frame'
LOG = PREFIX + 'logging-breath-body'
NULL = PREFIX + 'null-script-adept'
MOUNTAIN = PREFIX + 'mountain-core-stability'
NIGHTMARE = PREFIX + 'nightmare-feaster'
GUARD = 'condition:typed.insights6_frame'
PINCER_HOLD = 'condition:typed.insights6_pincer'
HAZARDS = {'forced_movement', 'prone', 'grappled', 'restrained'}
OUTCOMES = {
    BREATH: 'Advantage on Constitution saves against suffocation, smoke, altitude, inhaled hazards and pressure; after a completed Stomping Step, regain 1 Stamina once per scene',
    ECONOMY: 'After successfully resolving a feature during your turn with at least 2 Qi actually paid, regain 1 Qi once per turn',
    PINCER: 'A failed Joint Lock also sets Speed to 0 and gives Disadvantage on Concentration saves until your next turn; immunity to Joint Lock still applies',
    ONE: 'If you have moved voluntarily no more than 5 feet this turn, your first unarmed hit adds your Constitution modifier and grants +1 AC until your next turn',
    FRAME: 'After Stamina Guard, gain Advantage on your next saving throw against displacement, Prone, Grappled or Restrained before your next turn. The printed Athletics bonus and ability-check benefit are not automated.',
    LOG: 'Hewing Strike on a creature already bearing Bite grants Temporary HP equal to your Proficiency Bonus; the object-hit trigger remains unresolved; once per scene while wielding an axe, choose success on a failed Strength save against displacement, Prone or Disarm',
    NULL: 'Erode Technique, Return to Zero and Cause-Emptying Reversal have 30 feet more range; Erode Technique’s inherited temporary-benefit delivery remains unresolved',
    MOUNTAIN: 'Advantage against forced movement, Prone, unwilling teleportation and crushing pressure; reduce forced movement by 10 feet, or once per round stop one forced move caused by a rule with a lower Cultivation Level than yours (such as a Path, Sphere or item)',
    NIGHTMARE: 'Once per round, gain Temporary HP equal to your Proficiency Bonus after a creature fails against your Dream, Nightmare, Sleep, Fear or dream-illusion effect',
}


def owns(engine, actor, feature):
    return row_of(engine, getattr(actor, 'entity_id', ''), BLOCK, feature)


def stamp(engine):
    return int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)


@hook('compile_block')
def compile_rows(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'kind': row['feature_id'], 'pb': int(numbers['pb']),
             'cl': int(numbers['cl']), 'choice_owner': 1,
             'player_outcome': OUTCOMES[row['feature_id']]}]


@hook('activation_accounting')
def account(engine):
    return True if any(owns(engine, actor, ECONOMY) for actor in engine.state.actors.values()) else None


@hook('technique_final', priority=1000)
def recovery(ctx):
    engine, actor = ctx.engine, ctx.actor
    if (owns(engine, actor, ECONOMY) and actor.active
            and engine.state.current_actor_id == actor.entity_id
            and actor.turn_flags.get('insights6_economy_round_turn') != stamp(engine)):
        from ..paid_relocation import current_activation
        payment = current_activation(engine)
        if (payment is not None and payment.actor_id == actor.entity_id and payment.source_id == ctx.source
                and dict(payment.net_payments).get(QI, 0) >= 2):
            # Reserve before gain callbacks; this recovery cannot pay for itself.
            actor.turn_flags['insights6_economy_round_turn'] = stamp(engine)
            engine._gain_resource(actor, QI, 1, ECONOMY)
    if (owns(engine, actor, BREATH) and mechanic_of(ctx.action) == 'tianxia.path.body_refining.feature.stomping_step'
            and actor.active and STAMINA in actor.resources
            and not actor.turn_flags.get('insights6_breath_round_scene')
            and (actor.turn_flags.get('disengaged') or any(
                e.event_type == 'MOVEMENT_GRANTED' and e.actor_id == actor.entity_id and e.source_definition_id == ctx.source
                for e in engine.events))):
        actor.turn_flags['insights6_breath_round_scene'] = 1
        engine._gain_resource(actor, STAMINA, 1, BREATH)


@hook('compile_action')
def null_range(action, info):
    if NULL not in info['owned_ids'] or mechanic_of(action) not in (
            'TAL_VOID_ERODE_TECHNIQUE', 'TAL_VOID_RETURN_TO_ZERO', 'TAL_VOID_CAUSE_EMPTYING_REVERSAL'):
        return action
    typed = dict(action.parameters.get('typed') or {})
    feet = int(typed.get('range_ft') or action.range_ft or 0) + 30
    typed['range_ft'] = feet
    return action.model_copy(update={'range_ft': feet, 'parameters': {**action.parameters, 'typed': typed}})


@hook('save')
def saves(ctx, subject, ability, named):
    named = set(named or ())
    breath_advantage = (str(ability).upper()[:3] == 'CON' and owns(ctx.engine, subject, BREATH) and bool(named & {
            'category:suffocation', 'category:smoke', 'category:altitude', 'category:inhaled_hazard',
            'category:environmental_pressure'}))
    held = next((c for c in subject.conditions.values() if c.condition_id == GUARD), None)
    if held is not None and named & HAZARDS:
        # Spend Frame on its first qualifying save even if another feature
        # would independently grant Advantage on that same save.
        ctx.engine._remove_condition(subject, GUARD, FRAME)
        return {'bonus': 0, 'modes': ['ADVANTAGE']}
    if breath_advantage:
        return {'bonus': 0, 'modes': ['ADVANTAGE']}
    if owns(ctx.engine, subject, MOUNTAIN) and named & {
            'forced_movement', 'prone', 'category:unwilling_teleportation', 'category:crushing_pressure'}:
        return {'bonus': 0, 'modes': ['ADVANTAGE']}


@hook('save_roll_tags')
def rewrite_tags(ctx, subject, ability, named):
    if owns(ctx.engine, subject, LOG) and named & {'forced_movement', 'prone', 'disarmed'}:
        return list(named & {'forced_movement', 'prone', 'disarmed'})


def axe_wielded(engine, holder, rc):
    from ..weapon_delivery import available_weapons
    from .hand_occupancy import weapon_allowed
    return bool(set(rc.named) & {'forced_movement', 'prone', 'disarmed'}) and any(
        weapon_allowed(engine, holder.actor, action) is not False
        for action in available_weapons(engine, holder.actor, words=('axe', 'hatchet', 'francisca', 'tomahawk')).values())



register(Rule('insights6_rooted_hewing', 'Rooted Hewing', rolls=('save',), abilities=('STR',),
              feature=LOG, guard=axe_wielded, limit='fight', op='choose',
              choose=lambda engine, holder, rc: rc.natural, outcome='success'))


@hook('save_mode')
def native_saves(engine, subject, ability, dc, source, roll_context):
    # Typed saves already entered the save hook; do not consume a grant twice.
    from ..typed_executor import active_save_pending
    if active_save_pending(engine, source, subject.entity_id):
        return None
    named = set((roll_context or {}).get('named') or ())
    if source == 'system:combat.concentration' and any(c.condition_id == PINCER_HOLD for c in subject.conditions.values()):
        return 'DISADVANTAGE'
    breath_advantage = (str(ability).upper()[:3] == 'CON' and owns(engine, subject, BREATH) and bool(named & {
            'category:suffocation', 'category:smoke', 'category:altitude', 'category:inhaled_hazard', 'category:environmental_pressure'}))
    held = next((c for c in subject.conditions.values() if c.condition_id == GUARD), None)
    if held is not None and named & HAZARDS:
        engine._remove_condition(subject, GUARD, FRAME)
        return 'ADVANTAGE'
    if breath_advantage:
        return 'ADVANTAGE'
    if owns(engine, subject, MOUNTAIN) and named & {
            'forced_movement', 'prone', 'category:unwilling_teleportation', 'category:crushing_pressure'}:
        return 'ADVANTAGE'


@hook('event')
def events(engine, event_type, kwargs):
    payload = kwargs.get('payload') or {}
    # Event subscribers can append nested events before this handler runs.
    # The dispatcher supplies the source for the event being delivered here;
    # never infer it from the mutable log tail.
    source = kwargs.get('source_definition_id') or ''
    actor = engine.state.actors.get(kwargs.get('actor_id') or '')
    if event_type == 'REACTION_RESOLVED' and actor is not None and owns(engine, actor, FRAME) and (
            str(source).endswith('feature.stamina_guard') or source == 'reaction:core.stamina_guard'):
        engine._remove_condition(actor, GUARD, FRAME)
        engine._apply_condition(actor, GUARD, FRAME, actor.entity_id, expires_on='START_OF_SELF_NEXT_TURN',
                                data={'label': 'Mountain-Forged Frame: Advantage on your next saving throw against movement, Prone, Grappled or Restrained. Ability checks are not automated.'})
    if event_type == 'CONDITION_APPLIED' and payload.get('condition_id') == 'condition:typed.restrained':
        subject = engine.state.actors.get(next(iter(kwargs.get('target_ids') or ()), ''))
        holder = next((c for c in subject.conditions.values() if c.instance_id == payload.get('instance_id')), None) if subject else None
        owner = engine.state.actors.get(holder.source_actor_id) if holder else None
        if holder and (holder.data or {}).get('joint_lock_grip') and owns(engine, owner, PINCER):
            engine._remove_condition(subject, PINCER_HOLD, PINCER)
            engine._apply_condition(subject, PINCER_HOLD, PINCER, owner.entity_id, expires_on='START_OF_SOURCE_NEXT_TURN',
                data={'label': 'Meridian Pincer Method: Speed 0; Disadvantage on Concentration saves', 'rule': {'speed_zero': True}})
    if actor is None or not owns(engine, actor, ONE) or engine.state.current_actor_id != actor.entity_id:
        return
    travelled = 0
    if event_type == 'MOVEMENT_COMMITTED' and not payload.get('forced') and not payload.get('falling'):
        path = payload.get('path') or []
        from ..gate2_runtime_models import Position
        travelled = sum(int(engine.grid.distance_ft(Position(**a), Position(**b))) for a, b in zip(path, path[1:]))
    elif event_type == 'STOOD_UP':
        # The printed One-Breath clause explicitly counts standing from Prone
        # as voluntary relocation, even though the actor's coordinates do not change.
        travelled = int(payload.get('cost_ft') or 0)
    if travelled:
        actor.turn_flags['insights6_one_moved'] = int(actor.turn_flags.get('insights6_one_moved') or 0) + travelled


def _one_breath_ready(engine, actor, kind):
    return (kind == 'unarmed' and owns(engine, actor, ONE) and engine.state.current_actor_id == actor.entity_id
            and int(actor.turn_flags.get('insights6_one_moved') or 0) <= 5
            and actor.turn_flags.get('insights6_one_round_turn') != stamp(engine))


def _one_breath_hit(ctx, kind):
    actor, engine = ctx.actor, ctx.engine
    if _one_breath_ready(engine, actor, kind):
        actor.turn_flags['insights6_one_round_turn'] = stamp(engine)
        from ..typed_executor import run_effects
        run_effects(ctx, [{'type': 'ac_bonus', 'applies_to': 'self', 'flat': 1, 'duration': {'kind': 'until_start_of_next_turn'}}])


@hook('object_hit')
def one_breath_object_hit(ctx, target, kind):
    _one_breath_hit(ctx, kind)


@hook('object_hit_roll_bonus')
def one_breath_object_damage(ctx, target, kind, spec):
    if _one_breath_ready(ctx.engine, ctx.actor, kind):
        from ..ability_checks import ability_modifier
        return ability_modifier(ctx.actor, 'CON')


@hook('after_hit')
def one_breath(ctx, target, kind):
    actor, engine = ctx.actor, ctx.engine
    _one_breath_hit(ctx, kind)
    if owns(engine, actor, LOG) and mechanic_of(ctx.action) == 'TAL_AXES_HEWING_STRIKE':
        from ..typed_executor import _bore_mark
        if _bore_mark(ctx, target, actor.entity_id, 'Bite'):
            engine._grant_temp_hp(actor, int(owns(engine, actor, LOG)['pb']), LOG, actor.entity_id)


@hook('forced_movement_reduction')
def mountain(ctx, subject):
    row = owns(ctx.engine, subject, MOUNTAIN)
    if not row or ctx.actor is subject:
        return None
    remaining = int(getattr(ctx, 'forced_movement_distance_ft', None) or 0)
    if (int(ctx.numbers.get('cl') or 0) > 0 and int(ctx.numbers['cl']) < row['cl']
            and subject.turn_flags.get('insights6_mountain_round') != ctx.engine.state.round_number and remaining > 0):
        subject.turn_flags['insights6_mountain_round'] = ctx.engine.state.round_number
        return remaining
    return None  # the retained general passive trait already removes ten feet


@hook('save_final')
def rewards(ctx, subject, ability, named, failed):
    _nightmare_reward(ctx.engine, ctx.actor, subject, named, failed, ctx.typed.get('sphere'))


def _nightmare_reward(engine, actor, subject, named, failed, sphere=None):
    row = owns(engine, actor, NIGHTMARE)
    relevant = (sphere == 'tianxia.sphere.dreams' or set(named or ()) & {
        'frightened', 'category:dream', 'category:nightmare', 'category:sleep', 'category:dream_illusion'})
    if (row and failed and relevant
            and actor.turn_flags.get('insights6_nightmare_round') != engine.state.round_number):
        actor.turn_flags['insights6_nightmare_round'] = engine.state.round_number
        engine._grant_temp_hp(actor, row['pb'], NIGHTMARE, actor.entity_id)


@hook('repeat_save_final')
def repeat_save_rewards(engine, resolution):
    holder = engine.state.actors.get(resolution.get('holder_id'))
    source = engine.state.actors.get(resolution.get('source_actor_id'))
    if not holder or not source:
        return
    named = tuple(resolution.get('named') or ()) + tuple(resolution.get('source_categories') or ())
    # The engine republishes the originating save's sphere and printed categories, so a
    # repeated save is classified exactly as its initial save was (see _nightmare_reward).
    _nightmare_reward(engine, source, holder, named, not resolution.get('success'),
                      resolution.get('source_sphere'))


@hook('confirmed_hit_roll_bonus')
def one_breath_damage(engine, attacker, target, spec, intent, source):
    from .attack_scope import current
    from ..ability_checks import ability_modifier
    frame = current(engine)
    if frame and _one_breath_ready(engine, attacker, (frame.get('effect') or {}).get('attack_kind')):
        return ability_modifier(attacker, 'CON')

@hook('reaction_range_bonus')
def null_reaction_range(engine, actor, feature):
    if owns(engine, actor, NULL) and feature in (
            'TAL_VOID_ERODE_TECHNIQUE','TAL_VOID_RETURN_TO_ZERO','TAL_VOID_CAUSE_EMPTYING_REVERSAL'):
        return 30


@hook('decision_text')
def rooted_prompt(engine, context, printed_rules):
    if (str(context.get('reaction_source_id') or '').removeprefix('reaction:typed.') == LOG
            and (context.get('choice_trigger') or {}).get('d20_rewrite_name') == 'Rooted Hewing'):
        return {'summary': 'Choose to succeed on this failed Strength saving throw against being pushed, pulled, knocked Prone or Disarmed.',
                'table_note': 'Rooted Hewing: while wielding an axe, once per scene. No Action, Reaction or resource cost; declining keeps this use.'}
