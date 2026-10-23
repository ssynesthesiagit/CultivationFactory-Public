"""Owned Weapons choices and reach-entry reactions, using documented table hooks.

Conduit selection is an explicit, once-per-fight setup choice among the actor's
proficient carried weapons. Selection grants no proficiency or autonomous attack.
Casting-Hand is a separate attack variant: replacing the ability in its complete
weapon packet preserves ammunition, Loading, grips and ordinary action costs.
Historical compiled catalogs have neither these rows nor these variants.
"""
from __future__ import annotations

import copy

from . import effect, hook
from .passive_rows import row_of

PREFIX = 'tianxia.talent.weapons.'
INITIATE = 'TAL_WEAPONS_ARMAMENT_CONDUIT_INITIATE'
CASTING = 'TAL_WEAPONS_CASTING_HAND_WEAPON_METHOD'
CAREFUL = 'insight.careful-grip-disciple'
CORRECTION = 'insight.conduit-hand-correction'
MEASURE = PREFIX + 'long_weapon_measure'
BLOCK = 'weapons_second_pass'
CONDUIT = 'condition:typed.weapons_conduit'
CORRECTED = 'condition:typed.weapons_conduit_correction'
ROUND = '_round_weapons_measure'


def owned(engine, actor, kind):
    return row_of(engine, actor.entity_id, BLOCK, kind)


@hook('compile_block')
def compile_owned(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'block': BLOCK, 'kind': spec['kind']}]
    return None


def selected(actor):
    return next((str(c.data.get('weapon') or '') for c in actor.conditions.values()
                 if c.condition_id == CONDUIT), '')


def cultivation_stat(info):
    """The printed Path ability, sealed with the owned Conduit choice."""
    sheet = info['owner_sheet']
    paths = set((sheet.get('path_and_subpath') or {}).get('path_record_ids') or [])
    aliases = {'Body Refining':'tianxia.path.body_refining', 'Qi Cultivation':'tianxia.path.qi_cultivation',
               'Spirit Awakening':'tianxia.path.spirit_awakening'}
    identity = sheet.get('identity') or {}
    if not paths and identity.get('path') in aliases:
        paths.add(aliases[identity['path']])
    key = str(identity.get('key_ability') or '').upper()[:3]
    by_path = {'tianxia.path.body_refining':('CON',), 'tianxia.path.qi_cultivation':('INT','CHA'),
               'tianxia.path.spirit_awakening':('WIS',)}
    options = [ability for path, allowed in by_path.items() if path in paths
               for ability in ((key,) if len(allowed)>1 and key in allowed else allowed)]
    ability = max(options, key=lambda a:(info['mods'].get(a,0),a)) if options else None
    return {'ability':ability, 'modifier':int(info['mods'].get(ability,0))} if ability else None


def selected_stat(actor):
    return next((c.data.get('casting_stat') for c in actor.conditions.values() if c.condition_id==CONDUIT), None)


@hook('compile_actions')
def conduit_actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    ids = set(info['owned_ids'])
    if INITIATE not in ids:
        return []
    out = []
    stat = cultivation_stat(info)
    for action in info['actions']:
        typed = action.parameters.get('typed') or {}
        weapon = typed.get('weapon') or {}
        if (not isinstance(weapon, dict) or not typed.get('proficient')
                or not weapon.get('implement_id') or typed.get('opportunity_of')
                or str(action.economy.value) not in ('ACTION', 'BONUS_ACTION', 'NONE')
                or not any(r.get('type') == 'attack' for r in typed.get('effects') or [])):
            continue
        from ..weapon_delivery import physical_weapon_id
        identity = physical_weapon_id(action.source_definition_id, action.parameters)
        name = action.display_name.removesuffix(' attack')
        if '#' not in action.source_definition_id:
            out.append(ActionDefinition(source_definition_id=identity+'#choose_conduit',
            display_name='Choose Conduit Weapon: '+name, owner_id=info['actor_id'],
            economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
            parameters={'player_only': True, 'setting_only': True, 'weapons_conduit_choice': identity, 'weapons_casting_stat': stat,
                'description': 'Choose your proficient Conduit Weapon. This does not change its attack or damage modifier by itself.',
                'typed': {'source': INITIATE, 'numbers': info['numbers'], 'riders': [],
                          'effects': [{'type': 'weapons_choose_conduit', 'weapon': identity}]}}))
        if CASTING not in ids or stat is None:
            continue
        # Variants carry consent metadata only. The shared runtime seam is the
        # sole authority that substitutes attack and damage modifiers.
        packet = copy.deepcopy(typed)
        packet['weapons_casting_hand'] = identity
        packet['weapons_casting_hand_explicit'] = True
        out.append(action.model_copy(update={'source_definition_id': action.source_definition_id+'#conduit',
            'display_name': action.display_name+' (Casting-Hand: cultivation ability)',
            'parameters': {**copy.deepcopy(action.parameters), 'variant_of': identity, 'typed': packet,
                'description': 'Attack with your chosen Conduit Weapon using your cultivation ability for attack and damage. Ordinary weapon requirements still apply.'}}))
    return out


@hook('candidate_allowed')
def conduit_candidate(engine, actor, candidate, action):
    if action is None:
        return None
    choice = action.parameters.get('weapons_conduit_choice')
    if choice:
        return not selected(actor)
    identity = (action.parameters.get('typed') or {}).get('weapons_casting_hand')
    if identity:
        return selected(actor) == identity
    return None


@effect('weapons_choose_conduit')
def choose_conduit(ctx, row):
    if selected(ctx.actor):
        return
    weapon = str(row['weapon'])
    action = ctx.engine.action_catalog.get(weapon)
    if action is None or action.owner_id != ctx.actor.entity_id or not (action.parameters.get('typed') or {}).get('proficient'):
        return
    ctx.engine._apply_condition(ctx.actor, CONDUIT, INITIATE, ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED', data={'weapon': weapon, 'casting_stat': ctx.action.parameters.get('weapons_casting_stat'), 'label': 'Conduit Weapon: '+action.display_name.removesuffix(' attack')})


def protected_weapon(engine, actor):
    """The chosen conduit in hand; a carried or dropped conduit is not held."""
    from .hand_occupancy import weapon_grips
    weapon = selected(actor)
    return weapon if weapon and weapon in weapon_grips(engine, actor) else ''


@hook('save')
def careful_save(ctx, subject, ability, named):
    if 'disarmed' not in named or owned(ctx.engine, subject, 'careful') is None:
        return None
    from ..typed_executor import _best_weapon_action
    # The ordinary disarm executor targets its best weapon, not every weapon.
    if _best_weapon_action(ctx.engine, subject) == protected_weapon(ctx.engine, subject):
        return {'bonus': 0, 'modes': ['ADVANTAGE']}
    return None


@hook('after_miss_choice')
def conduit_correction(ctx, target, spec):
    if owned(ctx.engine, ctx.actor, 'correction') is None or not protected_weapon(ctx.engine, ctx.actor):
        return
    from .weapon_hits import weapon_identity
    if weapon_identity(ctx) != selected(ctx.actor):
        return
    result = ctx.attack_result or {}
    total, ac = result.get('modified_total', result.get('total')), result.get('target_ac')
    if type(total) is not int or type(ac) is not int or ac-total not in (1, 2):
        return
    from .rider_choices import pick
    from .choice_prompt import action_context
    if not pick(ctx.engine, ctx.actor, 'conduit_correction', 'Conduit Hand Correction', ['maintain'],
        subject=target, intent=ctx.intent, labels={'maintain': 'Deal no damage; steady your weapon technique'},
        prompt_context=action_context(ctx.engine, ctx.actor, ctx.action.source_definition_id, target),
        prompt='Conduit Hand Correction: your Conduit Weapon missed by 1 or 2. Deal no damage and gain Advantage on your next save against disarm or losing weapon-technique concentration until your next turn?'):
        return
    ctx.damage_cache['weapons_no_miss_damage'] = (ctx.source, target.entity_id)
    ctx.engine._apply_condition(ctx.actor, CORRECTED, CORRECTION, ctx.actor.entity_id,
        expires_on='START_OF_SOURCE_NEXT_TURN', data={'weapon': selected(ctx.actor),
            'label': 'Conduit Hand Correction: Advantage on the next disarm or weapon-technique concentration save'})


@hook('save')
def correction_disarm(ctx, subject, ability, named):
    if 'disarmed' in named and any(c.condition_id == CORRECTED for c in subject.conditions.values()):
        return {'bonus': 0, 'modes': ['ADVANTAGE']}
    return None


@hook('save_mode')
def correction_concentration(engine, target, ability, dc, source, roll_context):
    if not any(c.condition_id == CORRECTED for c in target.conditions.values()):
        return None
    if source != 'system:combat.concentration' or target.concentration is None:
        return None
    action = engine.action_catalog.get(target.concentration.source_definition_id)
    typed = (action.parameters.get('typed') or {}) if action else {}
    if typed.get('weapon') or typed.get('weapon_source_id') or typed.get('delivered_by'):
        return 'ADVANTAGE'
    return None


@hook('save_final')
def consume_disarm_correction(ctx, subject, ability, named, failed):
    if 'disarmed' in named and any(c.condition_id == CORRECTED for c in subject.conditions.values()):
        ctx.engine._remove_condition(subject, CORRECTED, CORRECTION)


@hook('movement_step')
def entering_reach(engine, mover, previous, nxt, intent):
    from .. import typed_reactions as tr
    from ..relations import relation, ENEMY
    from ..paid_relocation import activation
    from ..movement_steps import opportunity_exempt
    for guard in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if (not guard.active or relation(engine, guard, mover) != ENEMY
                or owned(engine, guard, 'measure') is None
                or guard.turn_flags.get(ROUND) == engine.state.round_number
                or opportunity_exempt(engine, mover, guard.entity_id)):
            continue
        from ..target_knowledge import can_see
        from ..targeting import line_of_effect
        if not can_see(engine, guard, mover) or not line_of_effect(engine, guard, target=mover):
            continue
        reach = tr.opportunity_reach(engine, guard)
        if reach is None or reach <= 5:
            continue
        # The actual readied OA profile must be a Reach weapon, not a spell or a
        # talent that extended an otherwise ordinary weapon's reach.
        profile = tr.opportunity_profile(engine, guard)
        if profile is None:
            continue
        row, action, _profile_reach = profile
        weapon = ((action.parameters.get('typed') or {}).get('weapon') or {}) if action else {}
        if 'reach' not in str(weapon.get('properties') or '').lower():
            continue
        # Validate the selected, physical OA weapon before asking or paying.
        # A compiled profile can outlive a stow/disarm in the current fight.
        from ..weapon_delivery import weapon_identity
        weapon_id = (weapon_identity(engine, action.source_definition_id,
                      action.parameters.get('typed') or {}, action.parameters,
                      owner_id=guard.entity_id) if action else '')
        from .hand_occupancy import weapon_grips, weapon_capacity
        if not weapon_id or weapon_id not in weapon_grips(engine, guard):
            continue
        required_hands = max(1, int(action.parameters.get('requires_hands') or 1))
        if 'two-handed' in str(weapon.get('properties') or '').lower():
            required_hands = max(required_hands, 2)
        if weapon_capacity(engine, guard, weapon_id) < required_hands:
            continue
        before = engine._distance_actor_to_actor(mover, guard, actor_position=previous)
        after = engine._distance_actor_to_actor(mover, guard, actor_position=nxt)
        if not before > reach >= after or not tr.wants_opportunity_attack(engine, guard, mover, ask=False):
            continue
        from .rider_choices import pick
        if not pick(engine, guard, 'long_weapon_measure', 'Long Weapon Measure', ['attack'],
            subject=mover, intent=intent, labels={'attack': 'Spend your Reaction: one Opportunity Attack'},
            prompt=f'Long Weapon Measure: {mover.display_name} entered your weapon reach. Spend your Reaction for one Opportunity Attack (once per round)?'):
            continue
        from . import any_false
        if any_false('opportunity_response', engine, guard, mover):
            continue
        with activation(engine, guard, row['action_id'], independent=True):
            engine._append_event('REACTION_WINDOW_OPENED', MEASURE, actor_id=mover.entity_id,
                target_ids=(guard.entity_id,), payload={'checkpoint': 'ENTER_REACH'})
            tr.spend_reaction(engine, guard, row)
            guard.turn_flags[ROUND] = engine.state.round_number
            tr.opportunity_attack(engine, guard, mover, intent, reach_ft=reach)
            engine._append_event('REACTION_RESOLVED', MEASURE, actor_id=guard.entity_id, target_ids=(mover.entity_id,))
        if not mover.active or mover.position != nxt:
            break
    return None


@hook('attack_result')
def reset_miss_waiver(ctx, target, hit, critical):
    ctx.damage_cache.pop('weapons_no_miss_damage', None)


@hook('effect_subject_allowed')
def waive_miss_damage(ctx, row, subject):
    if (row.get('type') in ('damage', 'extra_damage', 'half_damage')
            and ctx.damage_cache.get('weapons_no_miss_damage') == (ctx.source, subject.entity_id)):
        return False
    return None


@hook('event')
def consume_concentration_correction(engine, event_type, kwargs):
    if event_type != 'SAVE_ROLLED' or kwargs.get('source_definition_id') != 'system:combat.concentration':
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor and any(c.condition_id == CORRECTED for c in actor.conditions.values()):
        if correction_concentration(engine, actor, 'CON', 0, 'system:combat.concentration', {}) == 'ADVANTAGE':
            engine._remove_condition(actor, CORRECTED, CORRECTION)


@hook('turn_start_choice')
def choose_owned_weapon(engine, actor):
    if owned(engine, actor, 'initiate') is None or selected(actor):
        return
    from ..weapon_delivery import available_weapons
    from .rider_choices import pick
    weapons = {k: a for k, a in available_weapons(engine, actor).items()
               if (a.parameters.get('typed') or {}).get('proficient')}
    if not weapons:
        return
    from .hand_occupancy import weapon_grips
    ready = weapon_grips(engine, actor)
    preferred = sorted(weapons, key=lambda k: (k not in ready, -int(weapons[k].parameters.get('expected_damage') or 0), k))
    picked = pick(engine, actor, 'conduit_weapon', 'Armament Conduit Initiate', list(weapons),
        subject=actor, optional=False, preferred=preferred[:1],
        labels={k: a.display_name.removesuffix(' attack') for k, a in weapons.items()},
        prompt='Armament Conduit Initiate: choose one of your proficient weapons as your Conduit Weapon. This choice alone does not change attack or damage rolls.')
    if picked:
        engine._apply_condition(actor, CONDUIT, INITIATE, actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'weapon': picked[0], 'casting_stat': next((a.parameters.get('weapons_casting_stat')
                for a in engine.action_catalog.values() if a.owner_id==actor.entity_id
                and a.parameters.get('weapons_conduit_choice')==picked[0]), None), 'label': 'Conduit Weapon: '+weapons[picked[0]].display_name.removesuffix(' attack')})


@effect('weapons_second_pass_marker')
def marker(ctx, row):
    """Passive publication; the owned feature hooks resolve the mechanic."""
    return None


@hook('weapon_attack_ability')
def casting_hand_attack(ctx, effect):
    if owned(ctx.engine, ctx.actor, 'casting') is None:
        return None
    from .weapon_hits import weapon_identity
    if weapon_identity(ctx) != selected(ctx.actor):
        return None
    old = int(ctx.typed['weapon']['ability_modifier'])
    stat = selected_stat(ctx.actor)
    if not stat:
        return None
    key = stat['modifier']
    explicit = bool(ctx.typed.get('weapons_casting_hand_explicit'))
    if old == key and not explicit:
        return None
    from .rider_choices import pick
    from .choice_prompt import action_context
    if not pick(ctx.engine, ctx.actor, 'casting_hand', 'Casting-Hand Weapon Method', ['casting'],
        subject=ctx.target or ctx.actor, intent=ctx.intent, automatic=key > old and not explicit,
        labels={'casting': 'Use your cultivation ability for attack and damage'},
        prompt_context=action_context(ctx.engine, ctx.actor, ctx.action.source_definition_id, ctx.target or ctx.actor),
        prompt=f'Casting-Hand Weapon Method: use your cultivation ability for this strike with {ctx.action.display_name}?'):
        return None
    return dict(stat)


@hook('item_check_mode')
def careful_item_check(ctx, subject, purpose, weapon):
    if (purpose == 'disarm' and owned(ctx.engine, subject, 'careful') is not None
            and weapon == protected_weapon(ctx.engine, subject)):
        return 'ADVANTAGE'
    return None
