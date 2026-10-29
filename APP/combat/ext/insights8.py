"""Source-bound Insights; execution reads only sealed owned rows.

Escape receipts identify the chosen hold. Maneuver aftermath observes actual
outcomes after a save/Slam/throw. Sword-Bone retains shared hit defenses.
"""
from contextlib import contextmanager
from . import hook
from .passive_rows import row_of
from .needle import ask, checkpoint_id

BLOCK = 'insights8'
GRIP = 'insight.unyielding-grip'
WRESTLING = 'insight.wrestling-body-adept'
BONE = 'insight.sword-bone-insight'
WINE = 'insight.wine-gourd-immortal'


def owned(engine, actor, feature):
    return row_of(engine, actor.entity_id, BLOCK, feature)


def turn(engine):
    return f'{engine.state.round_number}:{engine.state.current_actor_id}'


def spend(engine, actor, feature, round_only=False):
    stamp = str(engine.state.round_number) if round_only else turn(engine)
    key = '_round_insights8:' + feature
    if actor.turn_flags.get(key) == stamp:
        return False
    actor.turn_flags[key] = stamp
    return True


@hook('compile_block')
def compile_rows(block, spec, row, numbers):
    if block == BLOCK:
        outcomes = {
            GRIP: 'A creature escaping your Grapple has Disadvantage; a failed escape takes your Proficiency Bonus in Bludgeoning damage once per turn',
            WRESTLING: 'Count as one size larger for Grappling, carrying a Grappled creature and Wrestling comparisons; a successful hostile Grapple, throw or Pin deals your Proficiency Bonus in Bludgeoning damage once per turn',
            BONE: 'After one unarmed or sword hit per turn, choose a 5-foot step, a 5-foot Speed reduction, no Reactions until its next turn, or your Proficiency Bonus in extra Slashing damage; Iron Fist attacks may deal Slashing damage',
            WINE: 'After an attack misses you, you may move 5 feet without provoking Opportunity Attacks once per round',
            'insight.tempered-reflexes': 'Reroll one failed Dexterity saving throw per fight; Stomping Step Disengage grants Advantage on your next Dexterity save before your next turn',
            'insight.two-moons-focus': 'Once per fight, retain Martial Focus instead of spending it on a Dual Wielding talent',
        }
        return [{**row, 'player_outcome': outcomes[row['feature_id']], 'kind': row['feature_id'], 'pb': int(numbers['pb']),
                 'cl': int(numbers['cl']), 'choice_owner': 1}]


@hook('escape_roll_resolved')
def failed_escape(engine, escaper, grips, success, way, source):
    if success:
        return
    from .passive_traits import is_grapple
    from ..typed_executor import Context, _deal
    from ..gate2_runtime_models import ActionDefinition
    holders = {c.source_actor_id for c in grips if c.target_id == escaper.entity_id and is_grapple(c)}
    for aid in sorted(holders):
        holder = engine.state.actors.get(aid)
        row = owned(engine, holder, GRIP) if holder is not None else None
        if not row or not holder.active or not spend(engine, holder, GRIP):
            continue
        action = ActionDefinition(source_definition_id=GRIP, display_name='Unyielding Grip',
            owner_id=aid, economy='NONE', resolution_kind='TYPED', target_kind='HOSTILE_ENTITY')
        ctx = Context(engine, holder, action, getattr(engine, '_active_intent', None),
                      {'source': GRIP, 'numbers': {'pb': row['pb'], 'cl': row['cl']}}, [escaper], escaper, {})
        _deal(ctx, escaper, int(row['pb']), 'BLUDGEONING')


def wrestling(typed):
    return typed.get('sphere') == 'tianxia.sphere.wrestling' or str(typed.get('source') or '').startswith(('TAL_WRESTLING_', 'WRESTLING_BASE_'))


@hook('size_context_purposes')
def wrestling_comparisons(ctx, role, purposes):
    return {'wrestling'} if wrestling(ctx.typed) else None


THROWS = frozenset({'TAL_WRESTLING_HARD_WHIP', 'TAL_WRESTLING_HEAVEN_LIFTING_THROW',
                   'TAL_WRESTLING_LIVING_WEAPON', 'TAL_WRESTLING_MOUNTAIN_CRASHING_SUPLEX',
                   'TAL_WRESTLING_TOMBSTONE_BURIAL'})


def maneuver_damage(ctx, subject):
    row = owned(ctx.engine, ctx.actor, WRESTLING)
    if (not row or subject.team_id == ctx.actor.team_id or not subject.active
            or not spend(ctx.engine, ctx.actor, WRESTLING)):
        return
    from ..typed_executor import _deal
    _deal(ctx.on_hit_context(subject, effect_source=WRESTLING, attack_damage_context=None,
                             damage_cache={'_bonus': True}), subject, int(row['pb']), 'BLUDGEONING')


@hook('effect_resolution_scope')
def maneuver_scope(ctx, effect):
    if not owned(ctx.engine, ctx.actor, WRESTLING):
        return None
    source = ctx.typed.get('source')
    normal = ctx.typed.get('unarmed_option') == 'grapple' or ctx.source.endswith('.unarmed.grapple')
    hold = (normal or wrestling(ctx.typed)) and effect.get('type') in {'save', 'condition'}
    throw = source in THROWS and effect.get('type') in {'apply_slam', 'forced_movement'}
    if hold or throw:
        return maneuver_aftermath(ctx)


@contextmanager
def maneuver_aftermath(ctx):
    engine = ctx.engine
    # Nested condition/forced-movement effects belong to the enclosing maneuver.
    # Keep the depth transient and unwind it even when a choice pauses execution.
    depths = getattr(engine, '_insights8_maneuver_depths', {})
    engine._insights8_maneuver_depths = depths
    key = (ctx.actor.entity_id, ctx.source)
    depth = depths.get(key, 0)
    depths[key] = depth + 1
    first = len(engine.events)
    try:
        yield
    finally:
        if depth:
            depths[key] = depth
        else:
            depths.pop(key, None)
    if depth:
        return
    subjects = []
    for event in engine.events[first:]:
        if event.source_definition_id != ctx.source:
            continue
        payload = event.payload or {}
        if (event.event_type == 'MOVEMENT_COMMITTED' and payload.get('forced')
                and payload.get('path') and ctx.typed.get('source') in THROWS):
            subjects.append(event.actor_id)
        elif event.event_type == 'CONDITION_APPLIED':
            condition = payload.get('condition_id')
            if (condition == 'condition:typed.grappled'
                    or condition == 'condition:typed.restrained' and ctx.typed.get('source') == 'TAL_WRESTLING_PIN_2'):
                subjects.extend(event.target_ids)
    for aid in subjects:
        subject = engine.state.actors.get(aid)
        if subject is not None and subject.team_id != ctx.actor.team_id and subject.active:
            maneuver_damage(ctx, subject)
            break


@hook('after_hit_choice')
def sword_bone(ctx, target, kind):
    row = owned(ctx.engine, ctx.actor, BONE)
    if not row or kind not in {'unarmed', 'weapon'}:
        return
    if kind == 'weapon':
        from .integrated_weapons import in_group
        if not in_group(ctx.typed, 'sword'):
            return
    if ctx.actor.turn_flags.get('_round_insights8:' + BONE) == turn(ctx.engine):
        return
    options = ['damage', 'slow', 'reactions']
    if step_paths(ctx.engine, ctx.actor, 5):
        options.append('step')
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, BONE, target.entity_id), ctx.actor,
        'choice:needle.insights8_bone', options, allow_decline=True,
        name='Sword-Bone Insight', feature_id=BONE, target_id=target.entity_id,
        labels={'damage': f"Add {row['pb']} Slashing damage to this hit", 'slow': 'Reduce Speed by 5 feet until its next turn starts',
                'reactions': 'Prevent Reactions until its next turn starts', 'step': 'Move 5 feet without provoking Opportunity Attacks'},
        prompt=f'Sword-Bone Insight: {ctx.action.display_name} hit {target.display_name}. Choose one benefit, once per turn; no action or resource cost.')
    if not picked:
        return
    from ..typed_executor import run_effects
    child = ctx.on_hit_context(target, effect_source=BONE, damage_cache={'_bonus': True, '_potency_used': True})
    selected = picked[0]
    if selected == 'step':
        choose_step(ctx.engine, ctx.actor, ctx.intent, BONE, 5, 'Sword-Bone Insight', target,
                    trigger_text=f'Your {ctx.action.display_name} hit {target.display_name}, so you can move',
                    on_accept=lambda: spend(ctx.engine, ctx.actor, BONE))
    else:
        spend(ctx.engine, ctx.actor, BONE)
        effects = {
            'damage': {'type': 'damage', 'flat': int(row['pb']), 'damage_types': ['slashing'], 'applies_to': 'target'},
            'slow': {'type': 'speed', 'amount': -5, 'applies_to': 'target', 'expires_on': 'START_OF_SELF_NEXT_TURN'},
            'reactions': {'type': 'reaction_denied', 'applies_to': 'target', 'expires_on': 'START_OF_SELF_NEXT_TURN'},
        }
        run_effects(child, [effects[selected]])


def step_paths(engine, actor, distance):
    from .rider_movement import routes
    paths = routes(engine, actor, distance)
    from . import ai_controlled
    if ai_controlled(engine, actor):
        from ..senses import perceives_cell
        paths = {key: path for key, path in paths.items()
                 if all(perceives_cell(engine, actor, cell) for cell in path[1:])}
    return paths


def choose_step(engine, actor, intent, feature, distance, name, target, trigger_text, on_accept=None,
                allowance_text=''):
    """Ask the mover to choose a legal free-step destination after a caller-described trigger."""
    from .rider_movement import step
    paths = step_paths(engine, actor, distance)
    if not paths:
        return
    picked = ask(engine, intent, checkpoint_id(engine, feature, 'step', target.entity_id), actor,
        'choice:needle.insights8_step', sorted(paths), allow_decline=True, name=name, feature_id=feature,
        target_id=actor.entity_id, labels={key: 'Move to ' + key.removeprefix('cell:') for key in paths},
        prompt=f'{name}: {trigger_text}. Choose a legal destination up to {distance} feet away without provoking Opportunity Attacks, or stay put.{allowance_text}')
    if picked:
        if on_accept is not None:
            on_accept()
        step(engine, actor, paths[picked[0]], feature)


@hook('after_miss_choice')
def wine_step(ctx, target, spec):
    row = owned(ctx.engine, target, WINE)
    if not row or target.turn_flags.get('_round_insights8:' + WINE) == str(ctx.engine.state.round_number):
        return
    choose_step(ctx.engine, target, ctx.intent, WINE, 5, 'Wine-Gourd Immortal', ctx.actor,
                trigger_text=f'{ctx.actor.display_name} missed you with {ctx.action.display_name}, so you can move',
                on_accept=lambda: spend(ctx.engine, target, WINE, True),
                allowance_text=' You can use this once per round; it costs no action or resource.')


@hook('compile_action')
@hook('compile_reaction_action')
def iron_fist_slashing(action, info):
    if BONE not in info.get('owned_ids', ()):
        return None
    typed = (action.parameters or {}).get('typed') or {}
    if (typed.get('source') not in {'tianxia.sphere.iron_fist', 'tianxia.path.body_refining.feature.iron_fist'}
            and typed.get('sphere') != 'tianxia.sphere.iron_fist') or not typed.get('weapon'):
        return None
    import copy
    params = copy.deepcopy(action.parameters)
    weapon = params['typed']['weapon']
    weapon['natural_source'] = 'tianxia.path.body_refining.feature.iron_fist'
    weapon['damage_types'] = list(dict.fromkeys([*(weapon.get('damage_types') or [weapon.get('damage_type') or 'BLUDGEONING']), 'SLASHING']))
    return action.model_copy(update={'parameters': params})


REFLEXES = 'insight.tempered-reflexes'
MOONS = 'insight.two-moons-focus'

from .d20_rewrite import Rule, register
register(Rule('insights8_reflexes', 'Reflexive Reversal', feature=REFLEXES,
              abilities=('DEX',), op='reroll', limit='fight'))


@hook('movement_action_resolved')
def stomping_disengage(ctx, movement_action):
    if (movement_action != 'disengage' or not owned(ctx.engine, ctx.actor, REFLEXES)
            or ctx.typed.get('source') != 'tianxia.path.body_refining.feature.stomping_step'):
        return
    from ..typed_executor import run_effects
    run_effects(ctx.with_source(REFLEXES), [{'type': 'advantage', 'on': 'next Dexterity saving throw', 'applies_to': 'self', 'expires_on': 'START_OF_SELF_NEXT_TURN',
        'evidence': 'Advantage on the next Dexterity saving throw before the start of your next turn.'}])


def spend_source(engine, actor, source):
    """(readable name, sphere, typed source) of what a Focus payment is for.

    A published catalog action is read from its typed parameters. A passive talent is paid from its own
    compiled row, which has no catalog action, so the actor's owned row names it and the typed authority gives its sphere.
    """
    action = engine.action_catalog.get(source)
    if action is not None:
        typed = (action.parameters or {}).get('typed') or {}
        return action.display_name, str(typed.get('sphere') or ''), str(typed.get('source') or '')
    if any(row.get('feature_id') == source for row in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, [])):
        from ..typed_numbers import authority_mechanics
        record = authority_mechanics().get(source) or {}
        return str(record.get('name') or source), str(record.get('sphere_id') or ''), source
    return '', '', ''


@hook('resource_spend_reduction')
def retain_focus(engine, actor, resource, amount, source):
    if amount <= 0 or resource != 'resource:core.martial_focus' or not owned(engine, actor, MOONS):
        return None
    if actor.turn_flags.get('_round_insights8_moons_used'):
        return None
    name, sphere, typed_source = spend_source(engine, actor, source)
    if sphere != 'tianxia.sphere.dual_wielding' and not typed_source.startswith('TAL_DUAL_WIELDING_'):
        return None
    picked = ask(engine, getattr(engine, '_active_intent', None), checkpoint_id(engine, MOONS, source), actor,
        'choice:needle.insights8_moons', ['retain'], allow_decline=True,
        name='Two-Moons Focus', feature_id=MOONS, target_id=actor.entity_id,
        labels={'retain': 'Retain Martial Focus instead of spending it'},
        prompt=f'Two-Moons Focus: {name} would spend Martial Focus. Retain it instead, once per fight? No action or extra resource cost.')
    if picked:
        actor.turn_flags['_round_insights8_moons_used'] = 'fight'
        return amount
    return None


@hook('save_mode')
def native_reflexes_boost(engine, subject, ability, dc, source_id, context):
    from ..typed_executor import active_save_pending, is_active_typed_condition
    if ability != 'DEX' or active_save_pending(engine, source_id, subject.entity_id):
        return None
    grant = next((c for c in subject.conditions.values()
                  if c.source_definition_id == REFLEXES and c.condition_id == 'condition:typed.save_against'
                  and is_active_typed_condition(c)), None)
    if grant is None:
        return None
    from .condition_ownership import remove_instance
    remove_instance(engine, subject, grant.instance_id, REFLEXES)
    return 'ADVANTAGE'
