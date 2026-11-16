"""Sealed Sniper precision actions, using existing transactional effect/roll hooks.

New catalogs opt in to named long-range provenance; old catalogs retain their
combined penalty. Far Shot and a live Hundred-Breath Wait remove that cause
before cancellation. Neither creates Advantage, changes maximum range or sight.
Perfect Shot holds one ranged-weapon roll (Qi-Line Sight also permits a ranged
spell roll), expiring at the end of this turn. Its Aimed Line is sampled before
that roll and consumed only by a real qualifying attempt.
Still-Scope samples Prone/cover before the turn-start standing transition and uses native granted movement
with only the actual target exempt from opportunity attacks. No current source
text is read during execution. Head Shot uses a held ranged/thrown weapon, gives
up the rest of that Attack action and asks for one failed-save outcome.
"""
from __future__ import annotations

import copy
from dataclasses import replace
from . import effect, hook

BLOCK = 'sniper_precision'
HEAD = 'TAL_SNIPER_HEAD_SHOT'
DEADLY = 'TAL_SNIPER_DEADLY_SHOT'
FAR = 'TAL_SNIPER_FAR_SHOT'
PERFECT = 'TAL_SNIPER_PERFECT_SHOT'
POSTURE = 'TAL_SNIPER_STILL_SCOPE_POSTURE'
QI = 'TAL_SNIPER_QI_LINE_SIGHT'
WAIT = 'TAL_SNIPER_HUNDRED_BREATH_WAIT'
KILLING = 'TAL_SNIPER_KILLING_APERTURE'
FOCUS = 'resource:core.martial_focus'
PERFECT_HELD = 'condition:typed.sniper_perfect'
POSTURE_HELD = 'condition:typed.sniper_posture'


def _typed(action):
    return (getattr(action, 'parameters', None) or {}).get('typed') or {}


def _owns(engine, actor, kind):
    return any(r.get('block') == BLOCK and r.get('kind') == kind
               for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ()))


def _held(actor, cid):
    return next((c for c in actor.conditions.values()
                 if c.condition_id == cid and c.data.get('precision_policy') == 1), None)


def _ranged(typed, effect=None):
    return bool((typed.get('range_ft') or typed.get('long_range_ft'))
                and (typed.get('weapon') or str((effect or {}).get('attack_kind', '')).endswith('ranged')))


@hook('compile_block')
def precision_block(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'kind': spec['kind'], 'precision_policy': 1}]


@hook('compile_action')
def named_range_penalty(action, info):
    if not {FAR, WAIT} & set(info.get('owned_ids', ())):
        return None
    typed = _typed(action)
    if not typed.get('long_range_ft'):
        return None
    return action.model_copy(update={'parameters': {**action.parameters,
        'typed': {**typed, 'strike_penalty_provenance': 1}}})


@hook('attack_mode_removed')
def range_only(engine, attacker, target, ranged):
    from .attack_scope import current
    frame = current(engine)
    if not frame or frame["actor_id"] != attacker.entity_id or frame["target_id"] != target.entity_id:
        return None
    action = engine.action_catalog.get(frame["source"])
    typed = _typed(action)
    if typed.get('strike_penalty_provenance') != 1 or not typed.get('weapon'):
        return None
    if _owns(engine, attacker, 'far'):
        return ['DISADVANTAGE:long_range']
    from .sniper_lines import WAIT_MARK
    mark = next((c for c in attacker.conditions.values() if c.condition_id == WAIT_MARK
                 and c.data.get('native_wait') == 1 and c.data.get('target') == target.entity_id), None)
    if mark and typed.get('maneuver') == 'snipe':
        return ['DISADVANTAGE:long_range']
    return None


@hook('compile_actions')
def precision_actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .weapon_actions import weapon_attacks
    kinds = {r.get('kind') for r in info.get('passives', ()) if r.get('block') == BLOCK}
    out = []
    if DEADLY in info['owned_ids']:
        from .special_attacks import replacement_actions, special_ids
        if not (special_ids() & set(info['owned_ids'])):
            out.extend(replacement_actions(info) or [])
    if 'perfect' in kinds:
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.sniper_perfect",
            display_name='Perfect Shot', owner_id=info['actor_id'], economy=EconomyKind.BONUS_ACTION,
            resolution_kind='TYPED', target_kind='SELF', costs=((FOCUS, 1),), parameters={
                'description': 'Bonus Action: expend Martial Focus. Your next ranged weapon attack' + (' or ranged spell attack' if QI in info['owned_ids'] else '') + ' this turn has Advantage. If it is a Snipe Shot, it has an Aimed Line.',
                'expected_damage': 1, 'typed': {'source': PERFECT, 'numbers': info['numbers'],
                    'effects': [{'type': 'sniper_perfect', 'spell': QI in info['owned_ids']}],
                    'duration': {'kind': 'instant'}, 'riders': []}}))
    if 'head' not in kinds:
        return out or None
    for base, typed, attack, kind in weapon_attacks(info['actions'], info['actor_id']):
        if kind not in ('ranged', 'thrown'):
            continue
        surrendered = max(0, int(attack.get('count') or 1) - 1)
        shot = copy.deepcopy(typed)
        hit = [*copy.deepcopy(attack.get('on_hit') or []),
               {'type': 'sniper_head_save', 'applies_to': 'target'}]
        shot.update(source=HEAD, maneuver='snipe', weapon_source_id=base.source_definition_id,
                    variant_of=base.source_definition_id, sniper_head=1,
                    sniper_surrendered_attacks=surrendered, sniper_aperture=KILLING in info['owned_ids'],
                    effects=[{**copy.deepcopy(attack), 'count': 1, 'on_hit': hit}],
                    numbers={**typed.get('numbers', {}), 'save_dc': info['numbers']['save_dc']},
                    riders=['Head Shot: the drop-to-0 option and anatomy/legendary exceptions require represented creature eligibility; this table automates Stunned or Prone with no Reactions.'])
        for deadly in (False, True) if DEADLY in info['owned_ids'] else (False,):
            row = copy.deepcopy(shot)
            strike = row['effects'][0]
            if deadly:
                strike['first_roll_bonus'] = int(strike.get('first_roll_bonus') or 0) - 5
                row['sniper_deadly_bonus'] = 10
            out.append(base.model_copy(update={
                'source_definition_id': base.source_definition_id + '.sniper_head' + ('.deadly' if deadly else ''),
                'display_name': 'Head Shot: ' + base.display_name.removesuffix(' attack') + (' + Deadly Shot' if deadly else ''),
                'parameters': {**base.parameters, 'typed': row,
                    'expected_damage': int(base.parameters.get('expected_damage') or 0) // max(1, int(attack.get('count') or 1)) + surrendered * 4 + (10 if deadly else 0),
                    'description': 'Action: make one ranged weapon attack.' + (' Take -5 to the attack roll and add +10 damage on a hit.' if deadly else '') + ' Give up your additional attacks from Extra Attack, adding 1d8 damage for each.' + (' With Killing Aperture and an Aimed Line, add 1d10 instead of 1d8 for each.' if KILLING in info['owned_ids'] else '') + ' After dealing at least half the target’s current HP, you may expend Martial Focus to force a Constitution save. On failure, choose Stunned or Prone and no Reactions until the end of your next turn.'}}))
    return out or None


@effect('sniper_perfect', harmful=False)
def perfect_setup(ctx, row):
    ctx.engine._apply_condition(ctx.actor, PERFECT_HELD, ctx.source, ctx.actor.entity_id,
        expires_on=f'END_OF_SOURCE_TURN_AT:{ctx.actor.turns_started}',
        data={'precision_policy': 1, 'spell': bool(row.get('spell')),
              'label': 'Perfect Shot: Advantage on your next ranged weapon attack' + (' or ranged spell attack' if row.get('spell') else '') + ' this turn; a Snipe Shot has an Aimed Line'})


@hook('attack_mode')
def perfect_roll(ctx, target):
    held = _held(ctx.actor, PERFECT_HELD)
    if not held or not _ranged(ctx.typed, ctx.attack_effect) or not (ctx.typed.get('weapon') or held.data.get('spell')):
        return None
    ctx.damage_cache['sniper_perfect_attempt'] = target.entity_id
    if ctx.typed.get('maneuver') == 'snipe':
        ctx.damage_cache['sniper_aimed'] = target.entity_id
    return 'ADVANTAGE'


@hook('attack_result')
def consume_perfect(ctx, target, hit, critical):
    from .condition_ownership import remove_instance
    if ctx.damage_cache.get('sniper_perfect_attempt') != target.entity_id:
        return
    held = _held(ctx.actor, PERFECT_HELD)
    if held:
        remove_instance(ctx.engine, ctx.actor, held.instance_id, PERFECT)
    ctx.damage_cache.pop('sniper_perfect_attempt', None)


@hook('turn_boundary_start', priority=-10)
def begin_posture(engine, actor):
    if not _owns(engine, actor, 'posture'):
        return
    from .sniper_angles import current_cover
    from ..posture import prone_conditions
    # Eligibility samples physical cover, independently of perception. The
    # marker carries no hostile identity or direction; targeting/AI retain
    # their normal perception checks when choosing the later shot.
    covered = any(other.active and other.team_id != actor.team_id
                  and current_cover(engine, other, actor) > 0 for other in engine.state.actors.values())
    if prone_conditions(actor) or covered:
        engine._apply_condition(actor, POSTURE_HELD, POSTURE, actor.entity_id,
            expires_on=f'END_OF_SOURCE_TURN_AT:{actor.turns_started}',
            data={'precision_policy': 1, 'label': 'Still-Scope Posture: turn began Prone or behind cover'})


@hook('attack_result')
def posture_result(ctx, target, hit, critical):
    if ctx.typed.get('maneuver') != 'snipe' or not _held(ctx.actor, POSTURE_HELD):
        return
    from .hold_still import moved_ft
    if moved_ft(ctx.engine, ctx.actor):
        return
    if hit:
        from .rider_step import step
        step(replace(ctx, target=target, targets=[target]), {'distance_ft': 5,
             'label': 'Still-Scope Posture', 'no_oa_from_target': True, 'after_attack': True})
    elif ctx.actor.resources.get(FOCUS, 0) < 1:
        from .needle import ask, checkpoint_id
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'sniper_posture', ctx.actor.entity_id, target.entity_id),
            ctx.actor, 'choice:needle.sniper.posture_focus', ['focus'], allow_decline=True,
            labels={'focus': 'Regain Martial Focus'}, name='Still-Scope Posture', target_id=target.entity_id,
            prompt='Still-Scope Posture: your Snipe Shot missed before you moved. Regain Martial Focus? No action or resource is spent.')
        if picked:
            ctx.engine._gain_resource(ctx.actor, FOCUS, 1, POSTURE)


@hook('confirmed_hit_damage_bonus')
def surrendered_dice(engine, attacker, target, spec, intent, source, critical):
    from ..gate2_runtime_models import DiceSpec
    typed = spec.get('typed') or {}
    if typed.get('sniper_head') != 1 and not typed.get('sniper_deadly_bonus'):
        return None
    bonus = int(typed.get('sniper_deadly_bonus') or 0)
    attacks = int(typed.get('sniper_surrendered_attacks') or 0)
    if not attacks:
        return bonus
    from .attack_scope import current
    frame = current(engine)
    aimed = bool(frame and frame['context'].damage_cache.get('sniper_aimed') == target.entity_id)
    sides = 10 if typed.get('sniper_aperture') and aimed else 8
    roll = engine.roller.roll(DiceSpec(count=attacks, sides=sides, modifier=0),
        actor_id=attacker.entity_id, reason=f'DAMAGE:{source}:surrendered_attacks', critical=critical)
    engine._record_roll(roll)
    engine._append_event('DAMAGE_ROLLED', source, actor_id=attacker.entity_id,
        target_ids=(target.entity_id,), payload={**roll.model_dump(mode='json'),
            'critical': critical, 'bonus_component': 'surrendered_attacks'})
    return roll.total + bonus


@effect('sniper_head_save', harmful=True)
def head_save(ctx, row):
    if ctx.target is None or not ctx.target.active or ctx.actor.resources.get(FOCUS, 0) < 1:
        return
    # Only this shot's settled packets, never a prior attack or another creature's damage.
    packets = []
    for event in reversed(ctx.engine.events):
        if event.event_type == 'ATTACK_ROLLED' and event.actor_id == ctx.actor.entity_id and event.source_definition_id == ctx.source:
            break
        if event.event_type == 'DAMAGE_COMMITTED' and event.actor_id == ctx.actor.entity_id and event.source_definition_id == ctx.source and ctx.target.entity_id in event.target_ids:
            packets.append(event.payload)
    damage = sum(int(p.get('hp_damage') or 0) + int(p.get('temporary_hp_absorbed') or 0) for p in packets)
    before = int(ctx.damage_cache.get('sniper_head_hp:' + ctx.target.entity_id, 0))
    if not damage or damage * 2 < before:
        return
    from .needle import ask, checkpoint_id
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'sniper_head_save', ctx.actor.entity_id, ctx.target.entity_id),
        ctx.actor, 'choice:needle.sniper.head_save', ['focus'], allow_decline=True,
        labels={'focus': 'Expend Martial Focus: Constitution save'}, name='Head Shot', target_id=ctx.target.entity_id,
        prompt=f'Head Shot dealt {damage} damage, at least half {ctx.target.display_name}’s {before} HP before this shot. Expend Martial Focus to force a Constitution save?')
    if not chosen:
        return
    ctx.engine._spend_resource(ctx.actor, FOCUS, 1, ctx.source)
    from ..typed_executor import run_effects
    run_effects(ctx, [{'type': 'save', 'applies_to': 'target', 'ability': 'con',
                      'on_fail': [{'type': 'sniper_head_outcome', 'applies_to': 'target'}], 'on_success': []}])


@effect('sniper_head_outcome', harmful=True)
def head_outcome(ctx, row):
    from .needle import ask, checkpoint_id
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'sniper_head_outcome', ctx.actor.entity_id, ctx.target.entity_id),
        ctx.actor, 'choice:needle.sniper.head_outcome', ['stunned', 'prone'], allow_decline=False,
        labels={'stunned': 'Stunned until the end of your next turn', 'prone': 'Prone and no Reactions until the end of your next turn'},
        name='Head Shot', target_id=ctx.target.entity_id, prompt='Head Shot: the Constitution save failed. Choose one effect.')
    if not chosen:
        return
    from ..typed_executor import run_effects
    expiry = f'END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started) + 1}'
    rows = ([{'type': 'condition', 'condition': 'stunned', 'applies_to': 'target', 'expires_on': expiry}]
            if chosen[0] == 'stunned' else [{'type': 'condition', 'condition': 'prone', 'applies_to': 'target'},
                {'type': 'reaction_denied', 'applies_to': 'target', 'expires_on': expiry}])
    run_effects(ctx, rows)


@hook('attack_damage_bonus')
def head_hp_snapshot(ctx, target, effect):
    if ctx.typed.get('sniper_head') == 1:
        ctx.damage_cache['sniper_head_hp:' + target.entity_id] = target.current_hp
        aimed = any(c.condition_id in ('condition:typed.aimed_line', 'condition:typed.sniper_wait')
                    and c.data.get('target') == target.entity_id for c in ctx.actor.conditions.values())
        if aimed or _held(ctx.actor, PERFECT_HELD):
            ctx.damage_cache['sniper_aimed'] = target.entity_id
    return None


@hook('compile_action')
def deadly_one_packet(action, info):
    typed = _typed(action)
    if typed.get('maneuver') != 'snipe' or (typed.get('modifier') or {}).get('id') != DEADLY:
        return None
    made = copy.deepcopy(typed)
    made['sniper_deadly_bonus'] = 10
    for attack in made.get('effects', ()):
        if attack.get('type') == 'attack':
            attack['count'] = 1
            attack['on_hit'] = [r for r in attack.get('on_hit', ())
                               if not (r.get('source_modifier') == DEADLY and r.get('type') == 'extra_damage')]
    return action.model_copy(update={'parameters': {**action.parameters,
        'typed': made, 'replaces_attack': 1}})
