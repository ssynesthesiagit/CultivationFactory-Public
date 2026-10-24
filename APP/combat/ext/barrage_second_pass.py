"""Printed Covering Volley, Suppressing Fire and Mobile Barrage choices.

Reviewed declarations opt new catalogs in. Choices belong to the archer, the
suppressed creature, or the protected ally. All movement uses native routes.
"""
from copy import deepcopy
from dataclasses import replace

from . import effect, hook, ai_controlled
from . import needle
from ..relations import ALLY, ENEMY, relation
from ..target_knowledge import can_see
from ..targeting import line_of_effect

PREFIX = 'TAL_BARRAGE_'
COVER = PREFIX + 'COVERING_VOLLEY'
SUPPRESS = PREFIX + 'SUPPRESSING_FIRE'
MOBILE = PREFIX + 'MOBILE_BARRAGE'
DECL = 'barrage_second_pass'
PROTECTED = 'condition:typed.barrage_covering_volley'
PRESSURE = 'condition:typed.barrage_suppressing_fire'


def declared(mechanics, mid):
    return any(r.get('type') == DECL for r in (mechanics.get(mid) or {}).get('effects') or [])


@hook('maneuvers')
def suppression_actions(info):
    """One Blitz primary opens a replacement Bonus Action, not another Action."""
    if SUPPRESS not in info['owned'] or not declared(info['mechanics'], SUPPRESS):
        return None
    from .weapon_actions import weapon_attacks
    from .barrage_common import follow_up
    out = []
    for base, typed, attack, kind in weapon_attacks(info['actions'], info['actor_id']):
        if kind not in ('ranged', 'thrown'):
            continue
        flag = 'barrage_suppression:' + base.source_definition_id
        name = base.display_name.removesuffix(' attack')
        primary = deepcopy(typed)
        primary.update(maneuver='barrage', maneuver_of=base.source_definition_id,
                       weapon_source_id=base.source_definition_id, opens=[flag],
                       barrage_owned=[m for m in info['owned'] if m.startswith(PREFIX)],
                       modifier={'id': SUPPRESS, 'name': 'Suppressing Fire', 'precondition': ''})
        out.append(base.model_copy(update={
            'source_definition_id': base.source_definition_id + '.barrage+' + SUPPRESS,
            'display_name': 'Barrage: ' + name + ' + Suppressing Fire',
            'parameters': {**base.parameters, 'typed': primary}}))
        bonus = follow_up(base, typed, base.source_definition_id, flag, info['owned'],
                          base.source_definition_id + '.barrage_suppression', 'Suppressing Fire: ' + name,
                          'After the primary Barrage attack, replace its Bonus Action attack with two wild shots. The target chooses to evade or face both shots with Disadvantage.')
        data = deepcopy(bonus.parameters['typed'])
        # Seal the complete compiled follow-up packet before replacing its resolver.
        # Weapon enchantments, passives and hit/miss branches remain weapon attacks.
        data['effects'] = [{'type': DECL, 'kind': 'suppress',
                            'weapon_effects': deepcopy(data['effects'])}]
        out.append(bonus.model_copy(update={'parameters': {**bonus.parameters, 'typed': data}}))
    return {'actions': out, 'rows': []} if out else None


def pick_step(ctx, mover, feet, name, *, ignored=(), ordinary=False):
    from .granted_moves import destinations, commit
    budget = min(feet, mover.movement_remaining_ft) if ordinary else feet
    routes = [r for r in destinations(ctx.engine, mover, budget, lambda cell: True) if r[0] != mover.position]
    if not routes:
        return
    ids = [f'step:{p.x},{p.y},{p.z}' for p, _, _ in routes]
    selected = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, name, mover.entity_id),
        mover, 'choice:needle.barrage_step', ids,
        labels={i: f'Move to {r[0].x},{r[0].y} ({r[2]} feet)' for i, r in zip(ids, routes)},
        name=name, allow_decline=True, target_id=mover.entity_id,
        prompt=f'{name}: choose a legal route of up to {budget} feet, or stay.'
               + (' This uses your remaining movement.' if ordinary else ' This movement does not provoke Opportunity Attacks.'))
    if selected:
        route = routes[ids.index(selected[0])][1]
        if ordinary:
            from ..granted_movement import resolve_path, movement_mode
            resolve_path(ctx.engine, mover, route, ctx.source, feet=budget, provokes=True,
                         ignore_oa_from=ignored, intent=ctx.intent, use_movement=True,
                         mode=movement_mode(ctx.engine, mover, route))
        else:
            commit(ctx.engine, mover, route, ctx.source, budget_ft=budget, provokes=False, intent=ctx.intent)


@effect(DECL)
def resolve(ctx, row):
    if row['kind'] == 'mobile':
        # The primary's actual settled hits, not its originally selected aim.
        from .barrage_hits import STATE
        state = (ctx.actor.turn_flags.get(STATE) or {}).get(ctx.typed.get('maneuver_of')) or {}
        pick_step(ctx, ctx.actor, 10, 'Mobile Barrage', ignored=tuple(state.get('hits') or {}), ordinary=True)
    elif row['kind'] == 'cover':
        allies = [a for a in ctx.engine.state.actors.values() if a.active and a is not ctx.actor
                  and relation(ctx.engine, ctx.actor, a) == ALLY
                  and ctx.engine._distance_actor_to_actor(ctx.actor, a) <= 30
                  and can_see(ctx.engine, ctx.actor, a)
                  and line_of_effect(ctx.engine, ctx.actor, target=a)]
        for flag in ctx.typed.get('opens') or []:
            ctx.actor.turn_flags[flag] = False
        picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, COVER, ctx.actor.entity_id),
            ctx.actor, 'choice:needle.covering_volley', [a.entity_id for a in allies],
            labels={a.entity_id: a.display_name for a in allies}, name='Covering Volley', feature_id=COVER,
            allow_decline=True, prompt=f"Covering Volley: forgo the Barrage Bonus Action attack and protect one ally within 30 feet until the start of {ctx.actor.display_name}'s next turn. The first Opportunity Attack against that ally has Disadvantage; on a miss, the ally may move 5 feet without provoking.")
        if picked:
            ally = ctx.engine.state.actors[picked[0]]
            ctx.engine._apply_condition(ally, PROTECTED, COVER, ctx.actor.entity_id,
                expires_on='START_OF_SOURCE_NEXT_TURN', data={'label': f"Covering Volley: the first Opportunity Attack against you has Disadvantage until the start of {ctx.actor.display_name}'s next turn", 'choice_owner': True})
    elif row['kind'] == 'suppress':
        suppress(ctx, row)
    elif row['kind'] == 'quick':
        quick_draw(ctx)


def suppress(ctx, row):
    from ..typed_executor import run_effects
    target = ctx.target
    if target is None or not target.active:
        return
    if ai_controlled(ctx.engine, ctx.actor) and (relation(ctx.engine, ctx.actor, target) != ENEMY or not can_see(ctx.engine, ctx.actor, target)):
        return
    for flag in ctx.typed.get('uses') or []:
        ctx.actor.turn_flags[flag] = False
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, SUPPRESS, ctx.actor.entity_id, target.entity_id),
        target, 'choice:needle.suppressing_fire', ['evade', 'ignore'],
        labels={'evade': 'Evade: fired shots miss; if both fire, Speed halved, attacks and Perception checks at -2 through the end of your next turn',
                'ignore': 'Ignore the Pressure: face two attacks with Disadvantage; no suppression penalties'},
        name='Suppressing Fire', feature_id=SUPPRESS, target_id=target.entity_id,
        prompt=f'Suppressing Fire: {target.display_name} chooses how to face two wild shots from {ctx.actor.display_name}.')
    if 'evade' in picked:
        from .weapon_actions import unrolled_weapon_misses
        shot = {'type': 'attack', 'attack_kind': 'weapon_ranged', 'count': 1}
        fired = unrolled_weapon_misses(ctx, target, shot, 2)
        if fired != 2:
            text = ('1 wild shot fires and automatically misses' if fired == 1 else 'No wild shots fire')
            needle.say(ctx.engine, SUPPRESS, ctx.actor,
                f'Suppressing Fire: {text}. Two shots are required, so no suppression penalties apply.',
                (target.entity_id,), details={'shots_fired': fired, 'shots_required': 2})
            return
        from .effect_durations import token
        expires = token('end', target.entity_id, target.turns_started + 1)
        needle.say(ctx.engine, SUPPRESS, ctx.actor, 'Suppressing Fire: both wild shots automatically miss.', (target.entity_id,))
        run_effects(ctx, [{'type': 'speed', 'applies_to': 'target', 'halved': True, 'expires_on': expires}])
        ctx.engine._apply_condition(target, PRESSURE, SUPPRESS, ctx.actor.entity_id,
            expires_on=expires, data={'label': 'Suppressing Fire: attacks and Perception checks at -2'})
    elif 'ignore' in picked:
        shot = deepcopy(ctx.typed)
        shot['disadvantage'] = True
        shot['effects'] = deepcopy(row['weapon_effects'])
        for packet in shot['effects']:
            if packet.get('type') == 'attack':
                packet.update(count=2, mode='DISADVANTAGE')
        run_effects(replace(ctx, typed=shot), shot['effects'])


def protection(target):
    return next((c for c in target.conditions.values() if c.condition_id == PROTECTED), None)


def is_oa(ctx):
    return getattr(ctx.engine, '_typed_oa_attacker', None) == ctx.actor.entity_id or bool(ctx.typed.get('opportunity_of'))


@hook('attack_mode')
def covering_mode(ctx, target):
    return 'DISADVANTAGE' if target is not None and protection(target) and is_oa(ctx) else None


@hook('native_reaction_roll_mode')
def native_covering_mode(engine, context):
    target = engine.state.actors.get(context.get('target_id'))
    if context.get('source_id') == 'system:combat.opportunity_attack' and target and protection(target):
        return {'mode': 'DISADVANTAGE', 'effect': 'Covering Volley',
                'owner': engine.state.actors.get(protection(target).source_actor_id),
                'why': 'the ally’s cover makes the first Opportunity Attack against them have Disadvantage'}
    return None


@hook('attack_completed')
def covering_finish(engine, notice, intent):
    action = engine.action_catalog.get(notice.source_id)
    typed = (action.parameters.get('typed') or {}) if action else {}
    if (notice.source_id != 'system:combat.opportunity_attack' and not typed.get('opportunity_of')
            and getattr(engine, '_typed_oa_attacker', None) != notice.attacker_id):
        return
    target = engine.state.actors.get(notice.target_id)
    if target is None:
        return
    grants = [c for c in target.conditions.values() if c.condition_id == PROTECTED]
    if not grants:
        return
    from .condition_events import drop_condition
    for grant in grants:
        drop_condition(engine, target, grant.instance_id, COVER)
    if not notice.hit and target.active:
        from ..typed_executor import Context
        from ..gate2_runtime_models import ActionDefinition, EconomyKind
        owner = engine.state.actors[grants[0].source_actor_id]
        action = ActionDefinition(source_definition_id=COVER, display_name='Covering Volley', owner_id=owner.entity_id,
            economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF')
        ctx = Context(engine, owner, action, intent, {'source': COVER}, [target], target)
        pick_step(ctx, target, 5, 'Covering Volley')


@hook('attack_bonus')
def pressure_attack(ctx, actor):
    return -2 if any(c.condition_id == PRESSURE for c in actor.conditions.values()) else None


@hook('d20_bonus')
def pressure_roll(engine, roll, intent):
    actor = engine.state.actors.get(roll.actor_id)
    if actor is None or not any(c.condition_id == PRESSURE for c in actor.conditions.values()):
        return None
    frame = engine.d20_context(roll) or {}
    if str(roll.reason).startswith('ATTACK:'):
        # Public d20_context deliberately omits transient resolver callbacks.
        # Use the same exact-strike check as barrage_sky_net, not actor kind.
        scopes = getattr(engine, '_d20_scopes', ())
        current = scopes[-1] if scopes else {}
        spec = current.get('spec') or {}
        if (current.get('kind') == 'attack' and current.get('actor_id') == roll.actor_id
                and roll.reason == f"ATTACK:{current.get('source_id')}:{current.get('attack_index', 1)}"
                and spec.get('typed') is not None and callable(spec.get('before_attack_d20'))):
            return None
        return {'source_id': SUPPRESS, 'bonus': -2}
    if str(frame.get('skill') or str(roll.reason).rpartition(':')[2]).lower() == 'perception':
        return {'source_id': SUPPRESS, 'bonus': -2}
    return None

QUICK = PREFIX + 'QUICK_DRAW_ARSENAL'
QUICK_USED = 'barrage_quick_draw_used'


@hook('compile_actions')
def quick_draw_action(info):
    if QUICK not in info['owned_ids'] or not declared(info['mechanics'], QUICK):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.barrage_quick_draw",
        display_name='Quick-Draw Arsenal: draw and optionally stow a weapon', owner_id=info['actor_id'],
        economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
        parameters={'ai_free_preparation': True, 'expected_damage': 0,
                    'description': 'Once this turn, draw one thrown weapon without an Action. You may stow one ranged or thrown weapon at the same time.',
                    'typed': {'source': QUICK, 'effects': [{'type': DECL, 'kind': 'quick'}],
                              'numbers': info['numbers'], 'riders': []}})]


@hook('candidate_allowed')
def quick_draw_available(engine, actor, candidate, action):
    if action and (action.parameters.get('typed') or {}).get('source') == QUICK:
        return False if actor.turn_flags.get(QUICK_USED) or not quick_pairs(engine, actor) else None
    return None


@hook('ai_candidate_allowed')
def quick_draw_ai_available(engine, actor, candidate, action):
    """Free preparation before attacking, using only the chooser's own equipment.

    Preserve a usable drawn ranged/thrown weapon rather than swapping each turn.
    The shared ai_free_preparation seam sequences readiness without inventing damage;
    the once-per-turn flag and legal-pair gate also apply during execution.
    """
    if action is None or (action.parameters.get('typed') or {}).get('source') != QUICK:
        return None
    if not actor.action_available and not actor.bonus_action_available:
        return False
    from .hand_occupancy import weapon_allowed, weapon_grips
    from .ammunition import ammunition_choice
    from .weapon_actions import weapon_attacks
    from ..weapon_delivery import physical_weapon_id
    ready = weapon_grips(engine, actor)
    for weapon, typed, attack, kind in weapon_attacks(engine.action_catalog.values(), actor.entity_id):
        if (physical_weapon_id(weapon.source_definition_id, weapon.parameters) in ready
                and kind in ('ranged', 'thrown') and weapon_allowed(engine, actor, weapon) is not False
                and ammunition_choice(engine, actor, None, weapon) is not False):
            return False
    return None


def quick_pairs(engine, actor):
    from .weapon_actions import weapon_attacks
    from .weapon_hits import available_weapons
    from .hand_occupancy import weapon_grips, weapon_capacity, resting_hands, occupancy
    available = available_weapons(engine, actor)
    from ..weapon_delivery import physical_weapon_id
    by_id = {}
    for a, typed, _, kind in weapon_attacks(engine.action_catalog.values(), actor.entity_id):
        if typed.get('maneuver') or typed.get('weapon_source_id') or typed.get('delivered_by') or typed.get('opportunity_of'):
            continue
        identity = physical_weapon_id(a.source_definition_id, a.parameters)
        if kind in ('ranged', 'thrown') and identity in available:
            by_id[identity] = (engine.action_catalog[identity], kind)
    rows = list(by_id.values())
    grips = weapon_grips(engine, actor)
    drawn = [a for a, kind in rows if a.source_definition_id in grips]
    carried = [a for a, kind in rows if kind == 'thrown' and a.source_definition_id not in grips]
    occupied = occupancy(engine, actor)
    pairs = []
    for draw in carried:
        for stow in [None, *drawn]:
            after = {part: tuple(o for o in owners if stow is None or o != 'weapon:' + stow.source_definition_id)
                     for part, owners in occupied.items()}
            if weapon_capacity(engine, actor, draw.source_definition_id, occupied=after) >= resting_hands(draw):
                pairs.append((draw, stow))
    return pairs


def quick_draw(ctx):
    from .equipment_hands import set_weapon_readiness
    pairs = quick_pairs(ctx.engine, ctx.actor)
    ids = [f'swap:{i}' for i in range(len(pairs))]
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, QUICK, ctx.actor.entity_id),
        ctx.actor, 'choice:needle.barrage_draw', ids,
        labels={i: 'Draw ' + draw.display_name.removesuffix(' attack')
                   + ('; stow ' + stow.display_name.removesuffix(' attack') if stow else '')
                for i, (draw, stow) in zip(ids, pairs)},
        name='Quick-Draw Arsenal', feature_id=QUICK,
        prompt='Quick-Draw Arsenal: draw one carried thrown weapon, optionally stowing one ranged or thrown weapon at the same time. Costs no Action; once this turn.',
        allow_decline=True, automatic=True, default='first',
        # Prefer the least stowing; stable inventory IDs break ties, never hidden foes.
        preferred=sorted(ids, key=lambda i: (pairs[ids.index(i)][1] is not None,
                         pairs[ids.index(i)][0].source_definition_id,
                         pairs[ids.index(i)][1].source_definition_id if pairs[ids.index(i)][1] else '')))
    if picked:
        draw, stow = pairs[ids.index(picked[0])]
        if stow:
            set_weapon_readiness(ctx.engine, ctx.actor, stow.source_definition_id, False,
                                 source=QUICK, source_actor_id=ctx.actor.entity_id)
        set_weapon_readiness(ctx.engine, ctx.actor, draw.source_definition_id, True,
                             source=QUICK, source_actor_id=ctx.actor.entity_id)
        ctx.actor.turn_flags[QUICK_USED] = True


@hook('choice_reactors')
def suppression_choosers(engine):
    """Enroll potential targets so a manual target keeps its choice on AI turns."""
    owners = [(engine.state.actors.get(a.owner_id), a) for a in engine.action_catalog.values()
              if any(r.get('type') == DECL and r.get('kind') == 'suppress'
                     for r in (a.parameters.get('typed') or {}).get('effects') or [])]
    return {target.entity_id for owner, action in owners if owner is not None and owner.active
            for target in engine.state.actors.values() if target.active and target is not owner
            and can_see(engine, owner, target)
            and engine._distance_actor_to_actor(owner, target) <= int(action.range_ft or 5)}
