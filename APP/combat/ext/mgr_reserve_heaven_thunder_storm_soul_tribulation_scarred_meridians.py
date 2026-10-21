"""Heaven-Thunder Storm Soul's source-owned Spark and Thunder Seal runtime.

The native acquisition adapter grants the five replacement features. This
provider consumes only those acquired rows, never names or cosmetic damage.
Activation provenance comes from combat.activation_settlement, the contract
owned by the Mercurial lane. Counted seals use stacking_marks' public helpers.
"""
from __future__ import annotations

from dataclasses import replace

from . import hook, effect

SUBPATH = 'tianxia.subpath.qi.heaven_thunder_storm_soul'
PREFIX = SUBPATH + '.feature.'
MERIDIANS = PREFIX + 'tribulation_scarred_meridians'
REPRISAL = PREFIX + 'heaven_punishing_reprisal'
CLOUD = PREFIX + 'tribulation_cloud_core'
SENTENCE = PREFIX + 'ninefold_heavenly_sentence'
LIVING = PREFIX + 'living_heavenly_tribulation'
FEATURES = (MERIDIANS, REPRISAL, CLOUD, SENTENCE, LIVING)
SPARK = 'resource:named.tribulation_spark'
QI = 'resource:core.qi'
BLOCK = 'heaven_thunder_storm_soul'
SEAL = 'Thunder Seal'


def hostile(engine, owner, target):
    from ..relations import relation
    return relation(engine, owner, target) == 'ENEMY'


def owned_row(engine, actor, feature=MERIDIANS):
    """Return the compiled acquisition row, or None for an unrelated actor."""
    row = next((r for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ())
                 if r.get('block') == BLOCK and r.get('feature_id') == feature), None)
    if row is not None:
        from .activation_requirements import source_suppressed
        if source_suppressed(engine, actor, feature, row):
            return None
    return row


def numbers(engine, actor):
    row = next((r for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ())
                if r.get('block') == BLOCK and r.get('feature_id') == MERIDIANS), None)
    if row is None:
        return {}
    profile = dict(row['numbers'])
    from .activation_requirements import effective_cl
    level = effective_cl(actor, int(profile.get('cl') or 1))
    if level < int(profile.get('cl') or 1):
        profile['cl'] = level
        profile['pb'] = min(int(profile.get('pb') or 2), 2 + max(0, level - 1)//4)
        profile['save_dc'] = 8 + profile['pb'] + int(profile.get('key_mod') or 0)
        profile['attack_bonus'] = profile['pb'] + int(profile.get('key_mod') or 0)
    return profile


def acquired_progression(info):
    """A copied leaf alone never grants this Variant's resource engine."""
    paths = (info.get('owner_sheet') or {}).get('path_and_subpath') or {}
    return any(p.get('subpath_id') == SUBPATH and p.get('owning_path_id') == 'tianxia.path.qi_cultivation'
               for p in paths.get('subpaths') or [] if isinstance(p, dict)) or any(
        p.get('path_id') == 'tianxia.path.qi_cultivation' and p.get('subpath_or_tradition_id') == SUBPATH
        and (p.get('subpath_or_tradition_acquisition_provenance') or {}).get('recorded') is True
        for p in paths.get('paths') or [] if isinstance(p, dict))


@hook('compile_passives')
def acquired_rows(rows, info):
    if not acquired_progression(info) or not set(FEATURES).intersection(info['owned_ids']):
        return rows
    from ..activation_settlement import path_numbers
    profile = path_numbers(info, 'tianxia.path.qi_cultivation')
    return [*(r for r in rows if r.get('feature_id') not in FEATURES),
            *({'block': BLOCK, 'feature_id': feature, 'numbers': profile,
               'trigger_owner': BLOCK}
                    for feature in FEATURES if feature in info['owned_ids'])]


@hook('compile_resources')
def spark_pool(info):
    if not acquired_progression(info) or MERIDIANS not in info['owned_ids']:
        return []
    from ..activation_settlement import path_numbers
    from ..gate2_runtime_models import ResourceDefinition
    pb = int(path_numbers(info, 'tianxia.path.qi_cultivation')['pb'])
    return [ResourceDefinition(resource_id=SPARK, initial=0,
                               maximum=pb * (2 if SENTENCE in info['owned_ids'] else 1))]


@hook('damage_defenses')
def meridian_resistance(engine, actor, kind, typed, source_actor_id):
    if owned_row(engine, actor):
        kind = str(kind).upper()
        if living(engine, actor):
            if kind in {'LIGHTNING', 'THUNDER'}:
                return [{'kind': 'immunity', 'damage_types': [kind]}]
            if kind not in {'FORCE', 'PSYCHIC', 'VOID'}:
                return [{'kind': 'resistance', 'damage_types': [kind]}]
        if kind in {'LIGHTNING', 'THUNDER'}:
            return [{'kind': 'resistance', 'damage_types': [kind]}]
    return None


def seal_count(engine, owner, target):
    from .stacking_marks import count
    return count(engine, owner, target, SEAL)


def add_seal(engine, owner, target, source, amount=1):
    from .stacking_marks import add
    if not owned_row(engine, owner) or target is None:
        return
    maximum = int(numbers(engine, owner).get('pb') or 2) + (3 if living(engine, owner) else 0)
    room = max(0, maximum - seal_count(engine, owner, target))
    if room:
        add(engine, owner, target, SEAL, min(room, amount), source)


def gain_spark(engine, actor, source, *, normal=True, amount=1):
    """Store a source-authorized grant; normal triggers share one round clock."""
    if not owned_row(engine, actor) or SPARK not in actor.resources:
        return 0
    key = '_round_heaven_thunder_spark'
    if normal and actor.turn_flags.get(key) == engine.state.round_number:
        return 0
    amount = min(amount, max(0, actor.resource_maximums[SPARK] - actor.resources[SPARK]))
    if amount <= 0:
        return 0
    if normal:
        actor.turn_flags[key] = int(engine.state.round_number)
    engine._gain_resource(actor, SPARK, amount, source)
    spark_step(engine, actor, source)
    return amount


@hook('activation_settlement')
def first_seal(ctx, receipt):
    """After actual Qi damage, choose one affected hostile, once each turn."""
    if not owned_row(ctx.engine, ctx.actor) or not receipt['qi_powered']:
        return
    if not set(receipt['damage_types']) & {'LIGHTNING', 'THUNDER', 'lightning', 'thunder'}:
        return
    spark_step(ctx.engine, ctx.actor, ctx.source)
    key = '_round_heaven_thunder_first_seal'
    if ctx.actor.turn_flags.get(key) == turn_clock(ctx.engine):
        return
    targets = [ctx.engine.state.actors[tid] for tid in receipt['damaged_ids']
               if tid in ctx.engine.state.actors
               and hostile(ctx.engine, ctx.actor, ctx.engine.state.actors[tid])]
    if not targets:
        return
    from .needle import ask, checkpoint_id
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, key, ctx.source),
                 ctx.actor, 'choice:needle.heaven_thunder_first_seal',
                 [t.entity_id for t in targets], labels={t.entity_id: t.display_name for t in targets},
                 name='First Thunder Seal', prompt=f'First Thunder Seal: {ctx.action.display_name} dealt Qi-powered Lightning or Thunder damage. Choose one affected hostile creature to bear your visible heavenly script until the scene ends. No cost.')
    if chosen:
        ctx.actor.turn_flags[key] = turn_clock(ctx.engine)
        add_seal(ctx.engine, ctx.actor, ctx.engine.state.actors[chosen[0]], MERIDIANS)


@hook('speed')
def seal_speed(engine, actor):
    return -10 if any(owned_row(engine, owner, REPRISAL) and seal_count(engine, owner, actor) >= 2
                      for owner in engine.state.actors.values()) else None


@hook('resource_gain_allowed')
def seal_recovery(engine, actor, resource_id, amount, source_id):
    from .cp_pools import all_of
    if resource_id in all_of(actor) and amount > 0 and any(
            owned_row(engine, owner, REPRISAL) and seal_count(engine, owner, actor) >= 3
            for owner in engine.state.actors.values()):
        return False
    return None


@hook('technique_cost_floor')
def seal_cost(engine, actor, source_id, listed, reduced):
    from .cp_pools import all_of
    if not any(owned_row(engine, owner, REPRISAL) and seal_count(engine, owner, actor) >= 4
               for owner in engine.state.actors.values()):
        return None
    return {pool: value + 1 for pool, value in listed.items() if value > 0 and pool in all_of(actor)}


ACTIVE = 'condition:typed.heaven_thunder_living'


def living(engine, actor):
    return next((c for c in actor.conditions.values() if c.condition_id == ACTIVE), None)


def context(engine, owner, target, source):
    from ..typed_reactions import triggered_context
    from ..typed_numbers import authority_mechanics
    return triggered_context(engine, owner, target, {
        'feature_id': source, 'name': (authority_mechanics().get(source) or {}).get('name', 'Heaven-Thunder Storm Soul'),
        'numbers': numbers(engine, owner), 'effects': [],
        'range_ft': 120 if source == LIVING else 90 if source in (REPRISAL, SENTENCE) else None}, getattr(engine, '_active_intent', None))


def choose(ctx, key, labels, prompt, *, optional=False, preferred=None, count=1, automatic_options=None):
    from .needle import ask, checkpoint_id
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, key, ctx.actor.entity_id, ctx.source),
        ctx.actor, 'choice:needle.heaven_thunder_' + key, list(labels), labels=labels,
        prompt=prompt, name=ctx.action.display_name, allow_decline=optional,
        minimum=0 if optional else count, maximum=count, preferred=preferred,
        default='decline' if optional else 'first', automatic_options=automatic_options)


def spark_step(engine, owner, source):
    if not owned_row(engine, owner) or owner.turn_flags.get('_round_heaven_thunder_step') == turn_clock(engine):
        return
    from .rider_movement import step
    from .frightened_movement import path_allowed
    from .needle import cell_id
    from ..gate2_runtime_models import Position
    paths = {}
    if engine._effective_speed(owner) <= 0:
        return
    origin = owner.position
    occupied = engine._occupied_volumes_except(owner.entity_id)
    footprint = engine._footprint(owner)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if (dx, dy, dz) == (0, 0, 0) or min(origin.x + dx, origin.y + dy, origin.z + dz) < 0:
                    continue
                cell = Position(x=origin.x + dx, y=origin.y + dy, z=origin.z + dz)
                route = (origin, cell)
                if engine.grid.volume_legal(cell, footprint=footprint, occupied_cells=occupied) and engine.grid.volume_step_legal(
                        origin, cell, footprint=footprint, occupied_cells=occupied) and path_allowed(engine, owner, route):
                    paths[cell_id(cell)] = route
    if not paths:
        return
    ctx = context(engine, owner, owner, MERIDIANS)
    picked = choose(ctx, 'step', {k: 'Move 5 feet to ' + k.removeprefix('cell:') for k in paths},
        f'Heaven-Spark Step: {owner.display_name} gained a Tribulation Spark or dealt Qi-powered Lightning or Thunder damage. Move 5 feet without provoking Opportunity Attacks; finish in a legal space. No cost, once per turn.', optional=True)
    if picked:
        owner.turn_flags['_round_heaven_thunder_step'] = turn_clock(engine)
        step(engine, owner, paths[picked[0]], MERIDIANS)


@hook('choice_reactors')
def choice_owners(engine):
    return tuple(a.entity_id for a in engine.state.actors.values() if owned_row(engine, a))


@hook('activation_effects_resolved')
def thunder_edge(ctx, receipt):
    if not owned_row(ctx.engine, ctx.actor) or not receipt['qi_powered'] or ctx.actor.turn_flags.get('_round_heaven_thunder_edge') == turn_clock(ctx.engine):
        return
    cost = 0 if living(ctx.engine, ctx.actor) else 1
    if ctx.actor.resources.get(SPARK, 0) < cost:
        return
    if not receipt['damaged_ids']:
        return
    target_ids = list(dict.fromkeys([*receipt['recipient_ids'], *(a.entity_id for a in ctx.targets if a is not None)]))
    targets = [ctx.engine.state.actors[tid] for tid in target_ids if tid in ctx.engine.state.actors]
    count = 2 + int(int(ctx.numbers.get('cl') or 1) >= 11) + int(int(ctx.numbers.get('cl') or 1) >= 17)
    picked = choose(ctx, 'edge', {t.entity_id: t.display_name for t in targets},
        f'Thunder Edge: {ctx.action.display_name} dealt Qi-powered damage. Choose one affected creature for {count}d8 Lightning or Thunder damage. Cost: {cost} Tribulation Spark; once per turn. With two of your Thunder Seals, it also loses Reactions until its next turn starts.', optional=True)
    if not picked:
        return
    target = ctx.engine.state.actors[picked[0]]
    ctx.actor.turn_flags['_round_heaven_thunder_edge'] = turn_clock(ctx.engine)
    if cost:
        ctx.engine._spend_resource(ctx.actor, SPARK, cost, MERIDIANS)
    from ..typed_executor import run_effects
    edge = context(ctx.engine, ctx.actor, target, MERIDIANS)
    run_effects(edge, [damage_row(count), *([denied_row()] if seal_count(ctx.engine, ctx.actor, target) >= 2 else [])])


def damage_row(count, kinds=None):
    # Printed judgments name one damage type each (Judgment of Thunder: "4d8 Thunder damage"); only an
    # unspecified row keeps both, and the executor then picks the type that lands hardest.
    return {'type': 'damage', 'applies_to': 'target', 'dice': {'count': count, 'sides': 8},
            'damage_types': list(kinds or ['lightning', 'thunder'])}


def denied_row():
    return {'type': 'condition', 'applies_to': 'target', 'condition': 'reaction_denied',
            'duration': 'until_start_of_next_turn'}


def bolt(ctx, target, count, *, ability='dex', seal=True, conditions=(), kinds=None, geometry=None):
    from ..typed_executor import run_effects
    damaging = damage_row(count, kinds)
    fail = [damaging]
    if seal:
        fail.append({'type': 'heaven_thunder_seal'})
    fail.extend(conditions)
    targets = target if isinstance(target, list) else [target]
    cache = {k: ctx.damage_cache[k] for k in ('_potency_used', '_checkpoint_aim') if k in ctx.damage_cache}
    current = replace(ctx, target=None if isinstance(target, list) else target, targets=targets, damage_cache=cache,
        typed={**ctx.typed, 'area': {'harmful_recipient_override': 'all', 'include_self': True, 'include_allies': True}},
        explicit_self_recipient=ctx.actor in targets, save_geometry=geometry or ctx.save_geometry)
    first_event = len(ctx.engine.events)
    run_effects(current,
        [{'type': 'save', 'applies_to': 'creatures_in_area' if isinstance(target, list) else 'target', 'ability': ability,
          'dc': 'technique_save_dc', 'on_fail': fail,
          'on_success': [{'type': 'half_damage', **{k: v for k, v in damaging.items() if k != 'type'}}]}])
    from ..activation_settlement import settle
    settle(current, first_event)


@effect('heaven_thunder_seal', harmful=True)
def seal_effect(ctx, row):
    add_seal(ctx.engine, ctx.actor, ctx.target, ctx.source)


def action_label(engine, source):
    action = engine.action_catalog.get(source)
    return action.display_name if action else ''


DEFENSE_BROKEN = {'condition:typed.shield_broken', 'condition:typed.guard_broken'}


def defenses_broken(target):
    # Printed exception: Sentence's shorter cap does not apply once the target's defenses are specifically broken.
    # Defenses are specifically broken when the engine has recorded a Shield or Guard break on the target.
    return any(c.condition_id in DEFENSE_BROKEN for c in target.conditions.values())


def named_pools(ctx, target, sources):
    # Blocks only the Path pools the chosen named systems actually spend; passive regeneration of those pools is gated too.
    from .cp_pools import all_of
    held = set(all_of(target))
    pools = set()
    for source in sources:
        action = ctx.engine.action_catalog.get(source)
        pools.update(pool for pool, _ in (getattr(action, 'costs', None) or ()) if pool in held)
    return pools


def living_exposes(engine, viewer, target):
    # Living Heavenly Tribulation: three or more Seals expose a creature's cultivation structure to its owner,
    # unless its concealment has higher Source CL and succeeds against the owner's Cultivation Check.
    if not owned_row(engine, viewer) or living(engine, viewer) is None or seal_count(engine, viewer, target) < 3:
        return False
    from .passive_rows import known_level
    from .ability_source import cultivation_check
    own = numbers(engine, viewer)
    other = known_level(engine, target)
    if other is None or other <= int(own.get('cl') or 1):
        return True
    return not cultivation_check(engine, target, numbers(engine, target), int(own.get('save_dc') or 10), LIVING,
                                 'Cultivation Check (concealment)')


def reprisal(engine, owner, source_actor, trigger, action_name=''):
    if not owned_row(engine, owner, REPRISAL) or source_actor is None or source_actor is owner:
        return
    if int(numbers(engine, owner).get('cl') or 1) < 6:
        return
    if engine.grid.distance_ft(owner.position, source_actor.position) > 90 or owner.turn_flags.get('_round_heaven_thunder_reprisal') == engine.state.round_number:
        return
    from ..typed_reactions import can_react, open_reaction
    if not can_react(engine, owner):
        return
    prices = {}
    qi_price = 0 if living(engine, owner) else sum(n for pool, n in engine.effective_costs(owner, REPRISAL, ((QI, 2),)) if pool == QI)
    if living(engine, owner):
        prices['qi'] = 'Use your Reaction: no Qi cost while Living Heavenly Tribulation lasts'
    elif owner.resources.get(QI, 0) >= qi_price:
        prices['qi'] = f'Use your Reaction and spend {qi_price} Qi'
    if owner.resources.get(SPARK, 0) >= 1:
        prices['spark'] = 'Use your Reaction and spend 1 Tribulation Spark'
    if not prices:
        return
    ctx = context(engine, owner, source_actor, REPRISAL)
    detail = f' with {action_name}' if action_name else ''
    picked = choose(ctx, 'reprisal', prices,
        f'Heaven-Punishing Reprisal: {source_actor.display_name} {trigger}{detail}. Use your Reaction to punish it with a Dexterity save, Lightning or Thunder damage, and on failure one Thunder Seal and no Reactions until its next turn starts. Once per round.', optional=True)
    if not picked:
        return
    pool, price = (QI, qi_price) if picked[0] == 'qi' else (SPARK, 1)
    action = ctx.action.model_copy(update={'costs': ((pool, price),) if price else ()})
    from ..gate2_runtime_models import CandidateKind
    from ..technique_interception import activation, frame
    candidate = engine._candidate(CandidateKind.REACTION, owner, REPRISAL, action.display_name,
                                  target_ids=(source_actor.entity_id,))
    with activation(engine, owner, action, candidate, ctx.intent, caller_pays=True) as (declared, _, canceled):
        current = frame(engine, owner.entity_id, REPRISAL)
        if canceled and not current.get('spend_activation'):
            return
        if not can_react(engine, owner) or owner.resources.get(pool, 0) < price:
            return
        owner.turn_flags['_round_heaven_thunder_reprisal'] = int(engine.state.round_number)
        if price:
            engine._spend_resource(owner, pool, price, REPRISAL)
        from .needle import checkpoint_id
        open_reaction(engine, {'feature_id': REPRISAL}, owner, (source_actor.entity_id,),
                      checkpoint_id(engine, 'heaven_thunder_reprisal_used', owner.entity_id))
        if not canceled and engine.grid.distance_ft(owner.position, source_actor.position) <= int(declared.range_ft or 90):
            bolt(replace(ctx, action=declared, typed=declared.parameters['typed']), source_actor,
                 6 if int(ctx.numbers.get('cl') or 1) >= 17 else 4, conditions=[denied_row()])


@hook('after_save_resolved')
def save_triggers(ctx, subject, ability, named, failed):
    if subject is None or not owned_row(ctx.engine, subject):
        return
    if failed:
        reprisal(ctx.engine, subject, ctx.actor, 'forced you to fail a saving throw')
    elif hostile(ctx.engine, subject, ctx.actor) and {str(t).lower() for t in ctx.typed.get('tags') or []} & {'weather', 'lightning', 'thunder', 'tribulation', 'heavenly'}:
        gain_spark(ctx.engine, subject, ctx.source)


@hook('event', nested=True)
def committed_triggers(engine, event_type, kwargs):
    if event_type not in {'DAMAGE_COMMITTED', 'RESOURCE_SPENT'}:
        return
    payload = kwargs.get('payload') or {}
    source_actor = engine.state.actors.get(kwargs.get('actor_id'))
    if source_actor is None:
        return
    original = kwargs.get('originating_event') or (engine.events[-1] if engine.events else None)
    source = original.source_definition_id if original is not None else ''
    if event_type == 'DAMAGE_COMMITTED':
        positive = int(payload.get('hp_damage') or 0) + int(payload.get('temporary_hp_absorbed') or 0) > 0
        for tid in kwargs.get('target_ids') or ():
            owner = engine.state.actors.get(tid)
            if owner is not None and owned_row(engine, owner) and positive:
                # Meaningfulness is declared by the world owner, never inferred from damage or team.
                if str(payload.get('damage_type') or '').upper() in {'LIGHTNING', 'THUNDER'} and meaningful_source(engine, owner, source_actor, source):
                    gain_spark(engine, owner, source)
                reprisal(engine, owner, source_actor, 'damaged you', action_name=action_label(engine, source))
    elif event_type == 'RESOURCE_SPENT' and int(payload.get('amount') or 0) > 0:
        from .cp_pools import all_of
        if payload.get('resource_id') not in all_of(source_actor):
            return
        for owner in engine.state.actors.values():
            if not owned_row(engine, owner) or seal_count(engine, owner, source_actor) < 1:
                continue
            if hostile(engine, owner, source_actor) and engine.grid.distance_ft(owner.position, source_actor.position) <= 60:
                gain_spark(engine, owner, source)
            reprisal(engine, owner, source_actor, 'spent Cultivation Points while bearing your Thunder Seal', action_name=action_label(engine, source))
        from ..zones import actor_inside_zone, fire_trigger
        for zone in clouds(engine):
            if actor_inside_zone(engine, source_actor, zone):
                fire_trigger(engine, zone, source_actor, 'cp_spent')


@hook('activation_settlement')
def paid_storm_spark(ctx, receipt):
    if not owned_row(ctx.engine, ctx.actor):
        return
    tags = {str(t).lower() for t in ctx.typed.get('tags') or []}
    if not tags & {'lightning', 'thunder', 'air', 'weather'}:
        return
    paid = sum(int(e.payload.get('amount') or 0) for e in ctx.engine.events[receipt['first_sequence']:receipt['last_sequence']]
               if e.event_type == 'RESOURCE_SPENT' and e.actor_id == ctx.actor.entity_id
               and e.source_definition_id == ctx.source and e.payload.get('resource_id') == QI)
    # Native payment precedes the settlement window. Use the enclosing accepted intent boundary.
    if paid < 3:
        for e in reversed(ctx.engine.events[:receipt['first_sequence']]):
            if e.event_type == 'INTENT_ACCEPTED':
                break
            if e.event_type == 'RESOURCE_SPENT' and e.actor_id == ctx.actor.entity_id and e.source_definition_id == ctx.source and e.payload.get('resource_id') == QI:
                paid += int(e.payload.get('amount') or 0)
    if paid >= 3:
        gain_spark(ctx.engine, ctx.actor, ctx.source)


@hook('compile_actions')
def progression_actions(info):
    if not acquired_progression(info) or not set(FEATURES).intersection(info['owned_ids']):
        return []
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..activation_settlement import path_numbers
    profile = path_numbers(info, 'tianxia.path.qi_cultivation')
    rows = []
    specifications = [
        (CLOUD, 'cloud', 'Tribulation Cloud Core', 'BONUS_ACTION', 5, 'SELF', None),
        (SENTENCE, 'flash', 'Ninefold Flash', 'BONUS_ACTION', 0, 'SELF', None),
        (SENTENCE, 'sentence', 'Sentence the Core', 'ACTION', 4, 'ANY_CREATURE', 90),
        (LIVING, 'living', 'Living Heavenly Tribulation', 'BONUS_ACTION', 8, 'SELF', None)]
    for feature, mode, name, economy, qi, target, reach in specifications:
        if feature not in info['owned_ids']:
            continue
        typed = {'source': feature,
                 'heaven_thunder_mode': mode, 'numbers': profile, 'manual_inline_choice': True,
                 'min_cl': {CLOUD: 10, SENTENCE: 14, LIVING: 18}[feature],
                 'cloud_text_sha256': (info['mechanics'].get(CLOUD, {}).get('source') or {}).get('text_sha256', ''),
                 'qi_powered': True, 'tags': ['Heavenly', 'Tribulation'],
                 'duration': {'kind': 'minutes', 'amount': 1, 'concentration': mode == 'cloud'},
                 'effects': [{'type': 'heaven_thunder_activation', 'mode': mode}], 'riders': []}
        if mode == 'living':
            # Living's field is the Cloud Core around the caster. The engine
            # leaves one area on the map for a lasting typed action; this
            # provider supplies the general zone_spec seam so that area carries
            # its printed 30-foot radius, height, difficult terrain, follows the
            # caster, and uses this provider's per-turn pulse.
            typed['zone_spec'] = {
                'name': 'Tribulation Cloud Core', 'height_ft': 30, 'difficult': 'hostile',
                'centered_on_self': True, 'follows_owner': True, 'size_ft': 30,
                'profile': {'heaven_thunder_cloud': 1, 'source_cl': int(profile.get('cl') or 1),
                            'tags': ['Qi', 'Heavenly', 'Tribulation']},
                'triggers': [{'id': 'heaven_thunder_cloud_pulse', 'name': 'Tribulation Cloud Core',
                    'on': ['enter', 'start', 'cp_spent'], 'who': 'hostile', 'once_per_turn': True,
                    'choice_owner': 'source', 'effects': [{'type': 'heaven_thunder_cloud_pulse'}]}]}
        rows.append(ActionDefinition(source_definition_id='action:typed.' + info['short'] + '.heaven_thunder.' + mode,
            owner_id=info['actor_id'], display_name=name, economy=EconomyKind(economy),
            resolution_kind='TYPED', target_kind=target, range_ft=reach,
            costs=((QI, qi),) if qi else (), concentration=mode == 'cloud',
            parameters={'expected_damage': 0, 'typed': typed}))
    return rows


@hook('candidate_allowed')
def progression_ready(engine, actor, candidate, action):
    mode = ((getattr(action, 'parameters', None) or {}).get('typed') or {}).get('heaven_thunder_mode')
    if not mode:
        return None
    if mode == 'living':
        return not actor.turn_flags.get('_round_heaven_thunder_living_used')
    if mode == 'flash':
        return actor.resources.get(SPARK, 0) >= 1
    if mode == 'sentence':
        target = engine.state.actors.get(next(iter(candidate.target_ids), ''))
        return target is not None and seal_count(engine, actor, target) >= 3
    return None


def pick_cell(ctx, feet, key, *, predicate=lambda cell: True, optional=False, landing=True, anchors=None):
    from .needle import cell_id
    from .teleport_steps import destinations
    if landing:
        available = destinations(ctx.engine, ctx.actor, feet, volume=True)
    else:
        from ..gate2_runtime_models import Position
        grid, origin = ctx.engine.grid, ctx.actor.position
        reach = feet // grid.square_size_ft
        available = [Position(x=x, y=y, z=z)
            for z in range(max(0, origin.z - reach), origin.z + reach + 1)
            for y in range(max(0, origin.y - reach), min(grid.height, origin.y + reach + 1))
            for x in range(max(0, origin.x - reach), min(grid.width, origin.x + reach + 1))
            if grid.distance_ft(origin, Position(x=x, y=y, z=z)) <= feet
            and ctx.engine._line_of_sight_actor_to_cell(ctx.actor, Position(x=x, y=y, z=z))]
    cells = {cell_id(c): c for c in available if predicate(c)}
    labels = {k: 'Legal space ' + k.removeprefix('cell:') for k in cells}
    for identity, (point, label) in (anchors or {}).items():
        if ctx.engine.grid.distance_ft(ctx.actor.position, point) <= feet and predicate(point):
            cells[identity] = point
            labels[identity] = label
    picked = choose(ctx, key, labels,
        f'{ctx.action.display_name}: choose a legal space you can perceive within {feet} feet.', optional=optional) if cells else []
    return cells[picked[0]] if picked else None


@effect('heaven_thunder_activation')
def activate(ctx, row):
    mode = row['mode']
    if not owned_row(ctx.engine, ctx.actor):
        raise ValueError('This creature has not acquired Heaven-Thunder Storm Soul.')
    if mode == 'cloud':
        from .qi_path import armament_condition, armament_point
        from ..gate2_runtime_models import Position
        anchors = {}
        if armament_condition(ctx.actor) is not None:
            x, y = armament_point(ctx.actor)
            anchors['domain_armament'] = (Position(x=x, y=y), 'Center the cloud on your active Domain Armament')
        cell = pick_cell(ctx, 60, 'cloud_center', landing=False, anchors=anchors)
        if cell is not None:
            create_cloud(ctx, cell, 20, concentration=True)
        else:
            replace_generic_zone(ctx)
    elif mode == 'flash':
        flash(ctx)
    elif mode == 'sentence':
        sentence(ctx)
    elif mode == 'living':
        from ..typed_executor import effect_expiry, run_effects
        ctx.actor.turn_flags['_round_heaven_thunder_living_used'] = 1
        ctx.engine._apply_condition(ctx.actor, ACTIVE, ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, {'duration': {'kind': 'minutes', 'amount': 1}}, ctx.actor, condition=True),
            data={'rebirth_used': 0, 'label': 'Living Heavenly Tribulation: Lightning/Thunder Immunity; Resistance except Force, Psychic and Void; flying and judgments for 1 minute'})
        run_effects(ctx, [{'type': 'general_flight', 'applies_to': 'self', 'speed_ft': 60,
                          'hover': True, 'duration': {'kind': 'minutes', 'amount': 1}}])
        # The engine creates the 30-foot field that follows the caster from the
        # action's zone_spec (centered_on_self + follows_owner).


def replace_generic_zone(ctx):
    """Remove the engine's auto area for this action so one field remains.

    A lasting typed action leaves its printed area on the map from its compiled
    zone_spec (combat/zones.py prospective_zone). When this provider chooses the
    cloud's centre during resolution it installs its own field; this removes the
    provisional area for the same source (and any earlier cloud) and releases
    the once-per-activation guard so the provider's field can be created.
    """
    from .. import zones
    for z in list(ctx.engine.state.zones.values()):
        if not z.active or z.owner_id != ctx.actor.entity_id:
            continue
        if z.source_definition_id == ctx.source or \
                (z.trigger_profile.get('profile') or {}).get('heaven_thunder_cloud'):
            zones.remove(ctx.engine, z, 'REPLACED')
    ctx.damage_cache.pop(('zone_created', ctx.source), None)


def create_cloud(ctx, center, radius, *, concentration, follows=False):
    from .. import zones
    replace_generic_zone(ctx)
    # Zone creation consumes the same declared point binding as ordinary native fields.
    intent = ctx.intent.model_copy(update={'destination': center}) if ctx.intent is not None else None
    zones.create(replace(ctx, intent=intent), {'name': 'Tribulation Cloud Core',
        'shape': 'cylinder', 'size_ft': radius, 'height_ft': 30,
        'duration': {'kind': 'minutes', 'amount': 1, 'concentration': concentration},
        'centered_on_self': follows, 'follows_owner': follows, 'difficult': 'hostile',
        'profile': {'heaven_thunder_cloud': 1, 'source_cl': int(ctx.numbers['cl']),
                    'tags': ['Qi', 'Heavenly', 'Tribulation']},
        'source_profile': {'schema': 'TianxiaFoundry.ZoneSource.v1', 'mechanic_id': CLOUD,
            'sphere_id': '', 'text_sha256': ctx.typed.get('cloud_text_sha256', ''),
            'source_tags': ['Qi', 'Heavenly', 'Tribulation'], 'source_cl': int(ctx.numbers['cl']),
            'save_dc': int(ctx.numbers['save_dc']), 'duration_kind': 'minutes',
            'activation_duration_kind': 'minutes', 'concentration': int(concentration), 'mundane': 0},
        'triggers': [{'id': 'heaven_thunder_cloud_pulse', 'name': 'Tribulation Cloud Core',
            'on': ['enter', 'start', 'cp_spent'], 'who': 'hostile', 'once_per_turn': True,
            'choice_owner': 'source', 'effects': [{'type': 'heaven_thunder_cloud_pulse'}]}]})


def clouds(engine):
    return [z for z in engine.state.zones.values() if z.active and
            (z.trigger_profile.get('profile') or {}).get('heaven_thunder_cloud')]


@effect('heaven_thunder_cloud_pulse', harmful=True)
def native_cloud_pulse(ctx, row):
    if ctx.target is not None:
        cloud_pulse_for(ctx.engine, ctx.target, owner_id=ctx.actor.entity_id, base_context=ctx)


@hook('zone_trigger_context')
def cloud_geometry(ctx, zone, creature, moment):
    if (zone.trigger_profile.get('profile') or {}).get('heaven_thunder_cloud'):
        ctx.save_geometry = {'zone_id': zone.zone_id}


def cloud_pulse_for(engine, target, *, owner_id, base_context):
    from ..zones import actor_inside_zone
    for zone in clouds(engine):
        if zone.owner_id != owner_id:
            continue
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or not owned_row(engine, owner, CLOUD) or not hostile(engine, owner, target) or not actor_inside_zone(engine, target, zone):
            continue
        ctx = replace(base_context, typed={**base_context.typed, 'source': CLOUD, 'qi_powered': True},
                      damage_cache={'_potency_used': True})
        first_event = len(engine.events)
        bolt(ctx, target, 4)
        packets = [e for e in engine.events[first_event:] if e.event_type == 'DAMAGE_COMMITTED'
                   and e.actor_id == owner.entity_id and e.source_definition_id == ctx.source and target.entity_id in e.target_ids]
        lightning = any(str(e.payload.get('damage_type') or '').upper() == 'LIGHTNING' for e in packets)
        damaged = any(int(e.payload.get('hp_damage') or 0) + int(e.payload.get('temporary_hp_absorbed') or 0) > 0 for e in packets)
        if lightning:
            exposure(engine, owner, target, CLOUD)
        if damaged:
            flicker(engine, owner, target)


def exposure(engine, owner, target, source):
    from ..typed_executor import run_effects
    ctx = context(engine, owner, target, source)
    run_effects(ctx, [{'type': 'condition', 'applies_to': 'target',
        'condition': 'heaven_thunder_exposure', 'duration': 'until_start_of_next_turn',
        'condition_data': {'rule': {'suppress_hide_invisibility': True},
                           'label': 'Heavenly Exposure: lightning reveals Invisible creatures; concealed cultivation flickers'}}])


def flicker(engine, owner, target):
    from ..observer_information import sources
    kinds = {'illusion': 'an active illusion', 'false_body': 'a false body',
             'disguised_transformation': 'a disguised transformation',
             'concealed_cultivation': 'concealed cultivation'}
    found = {kinds[tag] for row in sources(engine) if row.get('holder_id') == target.entity_id
             for tag in row.get('tags') or [] if tag in kinds}
    if found:
        from . import note
        note(engine, CLOUD, owner, f'Heavenly Exposure: {target.display_name} was damaged by the tribulation cloud; '
             + ', '.join(sorted(found)) + ' flickers visibly.', targets=(target.entity_id,))


@hook('observer_information_rows')
def sensed_cultivation_points(engine, viewer):
    if not owned_row(engine, viewer, CLOUD):
        return []
    from .. import senses
    if 'qi_sensing' not in senses.of(engine, viewer):
        return []
    from ..zones import actor_inside_zone
    from .cp_pools import all_of
    fields = [z for z in clouds(engine) if z.owner_id == viewer.entity_id]
    rows = []
    for target in engine.state.actors.values():
        if seal_count(engine, viewer, target) < 3 or not any(actor_inside_zone(engine, target, z) for z in fields):
            continue
        if not senses.perceives(engine, viewer, target):
            continue
        pools = {p: target.resources[p] for p in all_of(target)}
        rows.append({'kind': 'declaration', 'viewer_id': viewer.entity_id, 'source_id': CLOUD,
            'details': {'creature': target.display_name, 'cultivation_points': pools,
                'text': 'Heavenly Exposure — ' + target.display_name + ': ' + ', '.join(
                    p.rsplit('.', 1)[-1].title() + ' ' + str(n) for p, n in pools.items())
                    + '. Three of your Thunder Seals prevent concealing this total from your Qi Sensing inside the cloud.'}})
    return rows


def flash(ctx):
    maximum = min(3, ctx.actor.resources.get(SPARK, 0))
    picks = choose(ctx, 'flash_cost', {str(n): f'Spend {n} Tribulation Spark' + ('s' if n != 1 else '') for n in range(1, maximum + 1)},
        'Ninefold Flash: spend 1 to 3 Tribulation Sparks. For each, teleport up to 20 feet and choose one creature within 10 feet; Dexterity save for 2d8 Lightning or Thunder damage and a Thunder Seal on failure. Each creature can be affected once.')
    if not picks:
        return
    amount = int(picks[0])
    ctx.engine._spend_resource(ctx.actor, SPARK, amount, SENTENCE)
    affected = set()
    from .rider_support import teleport
    from ..senses import perceives
    for index in range(amount):
        cell = pick_cell(ctx, 20, f'flash_arrival_{index}')
        if cell is None or not teleport(ctx, ctx.actor, cell):
            continue
        targets = [a for a in ctx.engine.state.actors.values() if a.active and a.entity_id not in affected
                   and ctx.engine.grid.distance_ft(ctx.actor.position, a.position) <= 10]
        picked = choose(ctx, f'flash_target_{index}', {a.entity_id: a.display_name for a in targets},
            f'Ninefold Flash: choose one creature within 10 feet of {ctx.actor.display_name} after teleport {index + 1}.',
            preferred=[a.entity_id for a in targets if hostile(ctx.engine, ctx.actor, a) and perceives(ctx.engine, ctx.actor, a)],
            automatic_options=[a.entity_id for a in targets if perceives(ctx.engine, ctx.actor, a)]) if targets else []
        if picked:
            target = ctx.engine.state.actors[picked[0]]
            affected.add(target.entity_id)
            bolt(ctx, target, 2)


@hook('turn_start_choice')
def start_turn(engine, actor):
    for owner in engine.state.actors.values():
        if owned_row(engine, owner, REPRISAL) and seal_count(engine, owner, actor) >= 5:
            escalate(context(engine, owner, actor, REPRISAL))
    if not owned_row(engine, actor):
        return
    if living(engine, actor):
        gain_spark(engine, actor, LIVING, normal=False)
        judgment(context(engine, actor, actor, LIVING))
    if owned_row(engine, actor, CLOUD) and actor.resources.get(SPARK, 0) >= 1:
        from ..zones import actor_inside_zone
        from .rider_support import teleport
        owned_clouds = [z for z in clouds(engine) if z.owner_id == actor.entity_id]
        sealed = [a for a in engine.state.actors.values() if seal_count(engine, actor, a) > 0
                  and engine.grid.distance_ft(actor.position, a.position) <= 90]
        cell = pick_cell(context(engine, actor, actor, CLOUD), 90, 'thunder_road', optional=True,
            predicate=lambda c: any(actor_inside_zone(engine, actor, z, position=c) for z in owned_clouds)
                or any(engine.grid.distance_ft(c, a.position) <= 5 for a in sealed))
        if cell is not None:
            ctx = context(engine, actor, actor, CLOUD)
            if teleport(ctx, actor, cell):
                engine._spend_resource(actor, SPARK, 1, CLOUD)


def active_systems(engine, viewer, target):
    """Derive currently active cultivated source groups from committed state.

    This query does not publish the target's unactivated catalog. Each source
    group consists only of techniques whose native effects are currently active.
    """
    from .ability_source import mechanic_at
    from ..senses import perceives
    if not perceives(engine, viewer, target):
        return {}
    sources = {c.source_definition_id for c in target.conditions.values()
               if c.source_actor_id == target.entity_id}
    sources.update(m.source_definition_id for m in target.modifiers.values()
                   if m.source_actor_id == target.entity_id)
    sources.update(z.source_definition_id for z in engine.state.zones.values()
                   if z.active and z.owner_id == target.entity_id)
    groups = {}
    for source in sources:
        action = engine.action_catalog.get(source)
        typed = (action.parameters or {}).get('typed') or {} if action else {}
        mechanic = mechanic_at(engine, source) or source
        if typed.get('sphere'):
            group, label = typed['sphere'], 'Sphere: ' + str(typed.get('sphere_name') or typed['sphere'].rsplit('.', 1)[-1]).replace('_', ' ').title()
        elif '.feature.' in mechanic:
            group = mechanic.split('.feature.')[0]
            label = group.rsplit('.', 1)[-1].replace('_', ' ').title()
        elif mechanic.startswith(('tianxia.method.', 'foundation.', 'tianxia.foundation.', 'tianxia.item.')):
            group, label = mechanic, action.display_name if action else mechanic.rsplit('.', 1)[-1].replace('_', ' ').title()
        else:
            continue
        row = groups.setdefault(group, {'label': label, 'sources': []})
        row['sources'].append(source)
        if mechanic not in row['sources']:
            row['sources'].append(mechanic)
    return groups


def suppress_named(ctx, target, duration, *, technique=False, repeat=False, escape=False, entire=False):
    from ..typed_executor import run_effects
    from .cp_pools import all_of
    groups = active_systems(ctx.engine, ctx.actor, target) if ctx.source == REPRISAL and not technique else known_systems(ctx.engine, ctx.actor, target)
    if technique:
        choices = {}
        for row in groups.values():
            for source in row['sources']:
                action = ctx.engine.action_catalog.get(source)
                if action:
                    choices[source] = {'label': action.display_name, 'sources': [source, (action.parameters.get('typed') or {}).get('source', source)]}
        groups = choices
    if not groups and not entire:
        return
    if entire:
        sources = [s for row in groups.values() for s in row['sources']]
        from ..activation_settlement import profile
        for action in ctx.engine.action_catalog.values():
            if action.owner_id == target.entity_id and profile(ctx.engine, target, action)['source_kind'] in {
                    'Path', 'Subpath', 'Sphere', 'Recorded', 'Forged', 'Immortal', 'item', 'Method', 'Foundation'}:
                sources.extend((action.source_definition_id, (action.parameters.get('typed') or {}).get('source', action.source_definition_id)))
        label = 'Entire active cultivation'
    else:
        picked = choose(ctx, 'suppressed_system', {k: r['label'] for k, r in groups.items()},
            f'{ctx.action.display_name}: state explicitly which active cultivation {"technique" if technique else "system"} of {target.display_name} you suppress. Duration: {duration.replace("_", " ")}.')
        if not picked:
            return
        label, sources = groups[picked[0]]['label'], groups[picked[0]]['sources']
    # Expand an identified source group to its actual owned commands. It conveys
    # no additional observations to the selecting player.
    selected = set(sources)
    if not technique:
        for action in ctx.engine.action_catalog.values():
            typed = action.parameters.get('typed') or {}
            if action.owner_id == target.entity_id and any(
                    typed.get('sphere') == group or str(typed.get('source') or '').startswith(group + '.feature.')
                    for group in (list(groups) if entire else picked)):
                selected.update((action.source_definition_id, typed.get('source') or action.source_definition_id))
        selected_groups = list(groups) if entire else picked
        for passive in [*getattr(ctx.engine, 'typed_passive_rows', {}).get(target.entity_id, ()),
                        *getattr(ctx.engine, 'typed_reaction_rows', {}).get(target.entity_id, ())]:
            feature = str(passive.get('feature_id') or '')
            if entire or any(passive.get('cultivation_source_group') == group or feature.startswith(group + '.feature.') for group in selected_groups):
                if feature:
                    selected.add(feature)
    run_effects(replace(ctx, target=target, targets=[target]), [{
        'type': 'cultivation_suppression', 'applies_to': 'target',
        'suppressed_sources': sorted(selected), 'duration': duration,
        'label': f'{ctx.action.display_name}: {target.display_name} — {label} suppressed',
        **({'all_cultivation': 1} if entire else {}),
        'blocked_pools': sorted(all_of(target)) if entire else sorted(named_pools(ctx, target, selected)),
        **({'repeat_save': {'ability': 'CON', 'dc': int(ctx.numbers['save_dc'])}} if repeat else {}),
        **({'escape_dc': int(ctx.numbers['save_dc'])} if escape else {})}])


def saving_throw(ctx, target, ability, *, mode=None):
    """Return the outcome of the complete native typed save, never a fake roll."""
    from ..typed_executor import run_effects
    current = replace(ctx, target=target, targets=[target], damage_cache={},
        typed={**ctx.typed, 'heaven_thunder_save_mode': mode}, explicit_self_recipient=target is ctx.actor)
    outcome = {'type': 'heaven_thunder_save_outcome'}
    run_effects(current, [{'type': 'save', 'applies_to': 'target', 'ability': ability,
        'dc': 'technique_save_dc', 'on_fail': [outcome], 'on_success': [outcome]}])
    return current.damage_cache.get('heaven_thunder_save_failed')


@effect('heaven_thunder_save_outcome')
def save_outcome(ctx, row):
    ctx.damage_cache['heaven_thunder_save_failed'] = bool(ctx.failed_save)


@hook('save')
def source_cl_save_mode(ctx, subject, ability, named):
    mode = ctx.typed.get('heaven_thunder_save_mode')
    return {'bonus': 0, 'modes': [mode]} if mode in {'ADVANTAGE', 'DISADVANTAGE'} else None


def source_gap(ctx, target):
    from .passive_rows import known_level
    other = known_level(ctx.engine, target)
    from .activation_requirements import effective_cl
    return int(ctx.numbers.get('cl') or 1) - effective_cl(target, other) if other is not None else 0


def escalate(ctx):
    target = ctx.target
    gap = source_gap(ctx, target)
    failed = True if gap >= 6 else saving_throw(ctx, target, 'con', mode='ADVANTAGE' if gap < 0 else None)
    if failed:
        suppress_named(ctx, target, 'until_start_of_next_turn')


def sentence(ctx, *, prison=False):
    from .stacking_marks import spend
    target = ctx.target
    if target is None:
        return
    count = seal_count(ctx.engine, ctx.actor, target)
    minimum = 6 if prison else 3
    if count < minimum:
        return
    picked = ['6'] if prison else choose(ctx, 'sentence_seals',
        {str(n): f'Remove {n} of your Thunder Seals from {target.display_name}' for n in range(3, count + 1)},
        f'Sentence the Core: choose how many Thunder Seals to remove from {target.display_name}, at least 3. The Action costs 4 Qi; more Seals extend the suppression on a failed Constitution save.')
    if not picked:
        return
    amount = int(picked[0]); gap = source_gap(ctx, target)
    ctx = replace(ctx, typed={**ctx.typed, 'tags': list(dict.fromkeys([*(ctx.typed.get('tags') or []), 'Sealing']))})
    # Resolve the save before removing Seals: if it did not run, nothing is spent and nothing is lost.
    failed = True if prison and gap >= 6 else saving_throw(ctx, target, 'con',
        mode='DISADVANTAGE' if gap >= 6 else 'ADVANTAGE' if gap <= -6 else None)
    if failed is None or not spend(ctx.engine, ctx.actor, target, SEAL, ctx.source, amount):
        return
    if not failed:
        suppress_named(ctx, target, 'until_start_of_next_turn', technique=True)
    elif prison:
        picked = choose(ctx, 'prison_scope', {'system': 'One active cultivation system', 'entire': 'Entire cultivation, while ordinary physical actions and mundane statistics remain'},
            f'Judgment of Heaven’s Prison: {target.display_name} failed its resistance. Suppress one system or its entire cultivation until its next turn ends.')
        suppress_named(ctx, target, 'until_end_of_next_turn', entire=bool(picked and picked[0] == 'entire'))
    else:
        short = amount == 3 or (gap <= -6 and not defenses_broken(target))
        suppress_named(ctx, target, 'until_end_of_next_turn' if short else 'one_minute',
                       repeat=amount == 4 and not short, escape=amount >= 5 and not short)


def judgment(ctx):
    engine, owner = ctx.engine, ctx.actor
    labels = {
        'lightning': 'Judgment of Lightning: a point within 120 feet; 10-foot-radius, 60-foot-high cylinder; Dexterity save, 6d8 Lightning and a Seal on failure, half on success',
        'thunder': 'Judgment of Thunder: hostile creatures within 30 feet; Constitution save, 4d8 Thunder, Prone and no Reactions on failure, half on success',
        'revelation': 'Judgment of Revelation: up to your Proficiency Bonus in sealed creatures; reveal concealment, current Cultivation Points and active systems until your next turn starts',
        'empty': 'Judgment of Empty Meridians: one creature with four Seals; Constitution save, cannot spend or regain Cultivation Points until your next turn starts on failure; next cost +2 on success',
        'prison': 'Judgment of Heaven’s Prison: remove six Seals from one creature; Sentence the Core without Action or Qi cost; may suppress its entire cultivation until its next turn ends'}
    picked = choose(ctx, 'judgment', labels,
        f'Living Heavenly Tribulation: {owner.display_name}, choose one Judgment for the start of this turn. No Action or Qi cost.')
    if not picked:
        return
    kind = picked[0]
    from ..typed_executor import run_effects
    if kind == 'lightning':
        cell = pick_cell(ctx, 120, 'judgment_lightning_point', landing=False)
        if cell is not None:
            from ..zones import prospective_zone, actor_inside_zone
            area = {'shape': 'cylinder', 'size_ft': 10, 'height_ft': 60}
            shape = prospective_zone(ctx, area, cell)
            targets = [target for target in engine.state.actors.values() if target.active and actor_inside_zone(engine, target, shape)]
            if targets:
                bolt(ctx, targets, 6, kinds=['lightning'], geometry={'point': cell.model_dump(mode='json'), 'area': area})
    elif kind == 'thunder':
        targets = [target for target in engine.state.actors.values() if target.active and hostile(engine, owner, target)
                   and engine.grid.distance_ft(owner.position, target.position) <= 30]
        if targets:
            bolt(ctx, targets, 4, ability='con', seal=False, kinds=['thunder'],
                 conditions=[{'type': 'condition', 'applies_to': 'target', 'condition': 'prone'}, denied_row()],
                 geometry={'point': owner.position.model_dump(mode='json'), 'area': {'shape': 'sphere', 'size_ft': 30}})
    else:
        minimum = 6 if kind == 'prison' else 4 if kind == 'empty' else 1
        targets = [a for a in engine.state.actors.values() if seal_count(engine, owner, a) >= minimum]
        target_ids = choose(ctx, 'judgment_targets', {a.entity_id: a.display_name for a in targets},
            f'{labels[kind]}. Choose the affected creature' + ('s.' if kind == 'revelation' else '.'),
            count=min(int(ctx.numbers.get('pb') or 2), len(targets)) if kind == 'revelation' else 1,
            optional=kind == 'revelation') if targets else []
        for tid in target_ids:
            target = engine.state.actors[tid]
            if kind == 'prison':
                sentence(replace(ctx, target=target, targets=[target]), prison=True)
            elif kind == 'empty':
                failed = saving_throw(ctx, target, 'con')
                if failed is None:
                    continue
                run_effects(replace(ctx, target=target, targets=[target]), [{'type': 'condition', 'applies_to': 'target',
                    'condition': 'heaven_thunder_empty', 'duration': 'until_start_of_your_next_turn',
                    'condition_data': {'rule': {'no_cp_regain': True, 'heaven_thunder_no_cp_spend': True} if failed else {'heaven_thunder_next_cp_cost': 2},
                                       'label': 'Empty Meridians: cannot spend or regain Cultivation Points' if failed else 'Empty Meridians: next Cultivation Point cost +2'}}])
            else:
                reveal(ctx, target)


def reveal(ctx, target):
    from ..observer_information import publish
    from ..typed_executor import effect_expiry
    expiry = effect_expiry(ctx, {'duration': 'until_start_of_your_next_turn'}, target, condition=True)
    from .cp_pools import all_of
    pools = {p: target.resources[p] for p in all_of(target)}
    systems = [r['label'] for r in active_systems(ctx.engine, ctx.actor, target).values()]
    publish(ctx.engine, ctx.actor, LIVING, ctx.actor, 'declaration',
        {'creature': target.display_name, 'cultivation_points': pools, 'active_systems': systems,
         'text': f'Judgment of Revelation — {target.display_name}: ' + ', '.join(f'{p.rsplit(".", 1)[-1].title()} {n}' for p, n in pools.items())
                 + '; active cultivation systems: ' + (', '.join(systems) or 'none currently observed') + '. Known until your next turn starts.'}, expiry)
    from ..typed_executor import run_effects
    run_effects(replace(ctx, target=target, targets=[target]), [{'type': 'condition', 'applies_to': 'target',
        'condition': 'heaven_thunder_revealed', 'duration': 'until_start_of_your_next_turn',
        'condition_data': {'viewer_id': ctx.actor.entity_id,
                           'label': 'Judgment of Revelation: concealment revealed to the judging cultivator'}}])


def meaningful_source(engine, owner, source_actor, source):
    # Only authenticated world-owner declarations projected into this encounter
    # establish the subjective meaningful-hostility clause.
    return any(c.condition_id == 'condition:typed.heaven_thunder_meaningful'
               and c.data.get('source_actor_id') == source_actor.entity_id and c.data.get('source_id') == source
               and int(c.data.get('expires_round', -1)) >= engine.state.round_number
               for c in owner.conditions.values())


@hook('lethal_damage', priority=-100)
def tribulation_rebirth(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    held = living(engine, target)
    if held is None or held.data.get('rebirth_used') or target.current_hp <= 0:
        return None
    from ..typed_executor import condition_rules
    if any(r.get('death_prevention_denied') for r in condition_rules(target)):
        return None
    from ..damage_allocation import available_temporary_hp
    after_buffer = max(0, amount - available_temporary_hp(engine, target, amount, source_actor_id,
                        source_id=source_id, damage_type=damage_type))
    if after_buffer < target.current_hp or after_buffer - target.current_hp >= target.maximum_hp:
        return None
    # Only a transient candidate is recorded here. Rebirth is spent in rebirth_discharge once
    # DAMAGE_COMMITTED confirms the hit landed, so a prevented or rolled-back hit spends nothing.
    candidates = engine.__dict__.setdefault('_storm_rebirth_candidates', {})
    candidates[target.entity_id] = source_id
    return 1


@hook('event', nested=True, priority=-1000)
def rebirth_discharge(engine, event_type, kwargs):
    if event_type != 'DAMAGE_COMMITTED':
        return
    original = kwargs.get('originating_event') or (engine.events[-1] if engine.events else None)
    if original is None:
        return
    candidates = engine.__dict__.get('_storm_rebirth_candidates') or {}
    for tid in kwargs.get('target_ids') or ():
        source_id = candidates.pop(tid, None)
        target = engine.state.actors.get(tid)
        held = living(engine, target) if target is not None else None
        if held is None or source_id != original.source_definition_id or held.data.get('rebirth_used'):
            continue
        from .retained_updates import record_instance_update
        held.data = {**held.data, 'rebirth_used': 1}
        record_instance_update(engine, target, 'condition', held.instance_id, held)
        discharge(engine, target)


def discharge(engine, target):
    ctx = context(engine, target, target, LIVING)
    from .stacking_marks import spend
    removed = 0
    for creature in list(engine.state.actors.values()):
        seals = seal_count(engine, target, creature)
        if not seals or engine.grid.distance_ft(target.position, creature.position) > 120:
            continue
        spend(engine, target, creature, SEAL, LIVING, seals)
        removed += seals
        if hostile(engine, target, creature):
            bolt(ctx, creature, min(8, seals), seal=False, kinds=['lightning'])
    gain_spark(engine, target, LIVING, normal=False, amount=removed // 2)


@hook('candidate_allowed')
def empty_meridians_actions(engine, actor, candidate, action):
    from ..typed_executor import condition_rules
    from .cp_pools import all_of
    if any(r.get('heaven_thunder_no_cp_spend') for r in condition_rules(actor)) and any(
            pool in all_of(actor) and value > 0 for pool, value in getattr(action, 'costs', ())):
        return False
    return None


@hook('row_allowed')
def empty_meridians_reactions(engine, actor, row):
    from ..typed_executor import condition_rules
    if any(r.get('heaven_thunder_no_cp_spend') for r in condition_rules(actor)) and row.get('costs'):
        from ..resource_costs import parts
        from .cp_pools import all_of
        if any(pool in all_of(actor) and amount > 0 for pool, amount in map(parts, row['costs'])):
            return False
    return None


@hook('technique_cost_floor')
def empty_meridians_cost(engine, actor, source_id, listed, reduced):
    from ..typed_executor import condition_rules
    from .cp_pools import all_of
    extra = max((int(r.get('heaven_thunder_next_cp_cost') or 0) for r in condition_rules(actor)), default=0)
    return {pool: value + extra for pool, value in listed.items() if value > 0 and pool in all_of(actor)} if extra else None


@hook('event', nested=True)
def consume_empty_meridians_cost(engine, event_type, kwargs):
    if event_type != 'RESOURCE_SPENT' or int((kwargs.get('payload') or {}).get('amount') or 0) <= 0:
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None:
        return
    from .cp_pools import all_of
    if (kwargs.get('payload') or {}).get('resource_id') not in all_of(actor):
        return
    from .condition_ownership import remove_instance
    for c in list(actor.conditions.values()):
        if (c.data.get('rule') or {}).get('heaven_thunder_next_cp_cost'):
            remove_instance(engine, actor, c.instance_id, LIVING)


@hook('fact_admission_schema')
def meaningful_schema(session, source, subject, kind):
    if source == SUBPATH and kind in {'source_access', 'conversion_environment'}:
        return {'authority': 'table_owner', 'value_type': 'document' if kind == 'source_access' else 'flag',
            'maximum_seconds': 2592000 if kind == 'source_access' else 28800,
            'description': 'Grant this exact Rare Variant through a named legal source and entry route.' if kind == 'source_access'
                else 'Confirm a reasonably calm environment with sufficient ambient spiritual energy for a two-hour Cultivation Session.'}
    if source != MERIDIANS or kind != 'meaningful_hostile_source':
        return None
    bundle = (session.state['actors'].get(subject) or {}).get('bundle') or {}
    if not any(r.get('block') == BLOCK and r.get('feature_id') == MERIDIANS for r in bundle.get('typed_passives') or []):
        return None
    return {'authority': 'table_owner', 'value_type': 'document', 'maximum_seconds': 86400,
            'description': 'Confirm a meaningful hostile source by exact creature and source identities; this does not create damage, tags or a saving throw.'}


@hook('journey_combat_setup')
def journey_setup(session, actor_id):
    actor = session.state['actors'][actor_id]
    bundle = actor['bundle']
    if not any(r.get('block') == BLOCK for r in bundle.get('typed_passives') or []):
        return None
    from ..fact_consent_admission import read
    declarations = []
    for record in session.state.get('fact_consent_admission') or []:
        if record['source'] != MERIDIANS or record['subject'] != actor_id or record['kind'] != 'meaningful_hostile_source':
            continue
        latest = read(session, MERIDIANS, actor_id, record['kind'], record['scope'], actor_id)
        if latest and latest not in declarations:
            declarations.append({**latest, 'remaining_seconds': max(0, int(latest['expires_at']) - int(session.clock()))})
    state = journey_source_state(actor)
    return {'heaven_thunder': {'sparks': int(state.get('sparks') or 0),
        'living_used': int(state.get('living_used') or 0),
        'declarations': declarations}}


@hook('match_initialize')
def encounter_setup(engine):
    for bundle in getattr(engine, 'typed_bundle_documents', ()):
        owner = engine.state.actors.get(bundle.get('actor_id'))
        setup = (bundle.get('journey_setup') or {}).get('heaven_thunder')
        if owner is None or setup is None or not owned_row(engine, owner):
            continue
        owner.resources[SPARK] = min(owner.resource_maximums[SPARK], int(setup['sparks']))
        owner.turn_flags['_round_heaven_thunder_living_used'] = int(setup['living_used'])
        for record in setup.get('declarations') or []:
            value = record['value']
            if set(value) != {'source_actor_id', 'source_id'} or any(type(v) is not str or not v for v in value.values()):
                raise ValueError('A meaningful hostile source requires exact creature and source identities.')
            engine._apply_condition(owner, 'condition:typed.heaven_thunder_meaningful', MERIDIANS,
                owner.entity_id, expires_on='UNTIL_REMOVED', data={**value,
                'authority': 'table_owner', 'receipt_id': record['receipt_id'],
                'expires_at': int(record['expires_at']),
                'expires_round': engine.state.round_number + -(-int(record.get('remaining_seconds') or 0) // 6),
                'label': 'World owner confirmed a meaningful hostile source'})


@hook('journey_encounter_settled')
def encounter_settled(session, actor_id, engine, creature):
    if not owned_row(engine, creature):
        return
    actor = session.state['actors'][actor_id]
    state = journey_source_state(actor)
    state['sparks'] = int(creature.resources.get(SPARK) or 0)
    state['living_used'] = int(creature.turn_flags.get('_round_heaven_thunder_living_used') or 0)


@hook('journey_scene_end')
def scene_end(session, previous, current):
    import json
    from ..gate2_runtime_models import ConditionInstance
    owners = {aid for aid, a in session.state['actors'].items() if any(
        r.get('block') == BLOCK for r in a['bundle'].get('typed_passives') or [])}
    for aid, actor in session.state['actors'].items():
        if aid in owners:
            state = journey_source_state(actor)
            state['sparks'] = 0
            state['living_used'] = 0
            actor['resources'][SPARK] = 0
        snapshot = actor.get('encounter_snapshot') or {}
        for key, raw in list((snapshot.get('conditions') or {}).items()):
            c = ConditionInstance.model_validate(json.loads(raw))
            if (c.source_actor_id in owners and c.condition_id.startswith('condition:typed.mark.thunder_seal')) or c.condition_id in {'condition:typed.heaven_thunder_meaningful', KNOWN_SYSTEM}:
                del snapshot['conditions'][key]


@hook('compile_bundle')
def replace_parent(bundle, info):
    if not any(r.get('block') == BLOCK for r in bundle.get('typed_passives') or []):
        return bundle
    from copy import deepcopy
    out = deepcopy(bundle)
    parent = 'tianxia.subpath.qi.storm_soul_cultivator.feature.'
    removed = {a['source_definition_id'] for a in out['action_catalog']
               if str((a.get('parameters', {}).get('typed') or {}).get('source') or '').startswith(parent)}
    out['action_catalog'] = [a for a in out['action_catalog'] if a['source_definition_id'] not in removed]
    out['actor_template']['action_ids'] = [s for s in out['actor_template']['action_ids'] if s not in removed]
    for key in ('typed_passives', 'typed_reactions'):
        out[key] = [r for r in out.get(key, []) if not str(r.get('feature_id') or '').startswith(parent)]
    out.pop('bundle_sha256', None)
    return out


def turn_clock(engine):
    return f'{engine.state.round_number}:{engine.state.current_actor_id}:{engine.state.actors[engine.state.current_actor_id].turns_started}'


@hook('presentation_hidden_conditions')
def private_information(engine, actor):
    return [c.instance_id for c in actor.conditions.values() if c.source_definition_id in FEATURES
            and (c.condition_id.startswith('condition:information.') or c.condition_id in {'condition:typed.heaven_thunder_meaningful', KNOWN_SYSTEM})]


@hook('masked_conditions')
def revealed_concealment(engine, attacker, target):
    if attacker is None or target is None:
        return None
    revealed = any(c.condition_id == 'condition:typed.heaven_thunder_revealed' and c.data.get('viewer_id') == attacker.entity_id
                   for c in target.conditions.values())
    if not revealed and not living_exposes(engine, attacker, target):
        return None
    ids = {iid for iid, c in target.conditions.items() if c.condition_id in {'condition:typed.invisible', 'condition:typed.hidden'}
           or 'false_body' in ((c.data.get('information_profile') or {}).get('tags') or [])}
    return {target.entity_id: ids} if ids else None


@hook('resource_spend_allowed')
def empty_meridians_debit(engine, actor, resource_id, amount, source_id):
    from ..typed_executor import condition_rules
    from .cp_pools import all_of
    if amount > 0 and resource_id in all_of(actor) and any(
            r.get('heaven_thunder_no_cp_spend') for r in condition_rules(actor)):
        return False
    return None


@hook('teleport_gate')
def thunder_road_sealed_formation(ctx, start, destination):
    if ctx.source != CLOUD or not owned_row(ctx.engine, ctx.actor, CLOUD):
        return None
    from .formations import arrays, gate_label
    if any(gate_label(ctx.engine, zone, ctx.actor, start, destination) is not None for zone in arrays(ctx.engine)):
        from . import note
        note(ctx.engine, CLOUD, ctx.actor, 'Thunder Road cannot cross a sealed Formation; choose a legal space on this side of the seal.')
        return False
    return None


def journey_source_state(actor):
    """Source-owned integers/strings, retained by the native journey registry."""
    return actor.setdefault('source_states', {}).setdefault(SUBPATH, {})


KNOWN_SYSTEM = 'condition:typed.heaven_thunder_known_system'


def known_systems(engine, viewer, target):
    from copy import deepcopy
    groups = active_systems(engine, viewer, target)
    for c in viewer.conditions.values():
        if c.condition_id == KNOWN_SYSTEM and c.data.get('target_id') == target.entity_id:
            groups.setdefault(c.data['group'], {'label': c.data['name'], 'sources': deepcopy(c.data['sources'])})
    return groups


@hook('activation_settlement')
def observe_resolved_source(ctx, receipt):
    """Native Qi Sensing learns only a source actually used in perception range."""
    from .. import senses
    source = receipt['source_id']
    group = ctx.typed.get('sphere') or (source.split('.feature.')[0] if '.feature.' in source else '')
    if not group:
        return
    name = group.rsplit('.', 1)[-1].replace('_', ' ').title()
    for viewer in ctx.engine.state.actors.values():
        if viewer is ctx.actor or not owned_row(ctx.engine, viewer) or 'qi_sensing' not in senses.of(ctx.engine, viewer):
            continue
        if not senses.perceives(ctx.engine, viewer, ctx.actor):
            continue
        if any(c.condition_id == KNOWN_SYSTEM and c.data.get('target_id') == ctx.actor.entity_id
               and c.data.get('group') == group for c in viewer.conditions.values()):
            continue
        ctx.engine._apply_condition(viewer, KNOWN_SYSTEM, MERIDIANS, viewer.entity_id,
            expires_on='UNTIL_REMOVED', data={'target_id': ctx.actor.entity_id, 'group': group,
                'name': name, 'sources': [ctx.source, source], 'sequence': int(ctx.engine.state.event_sequence),
                'label': 'Qi Sensing observed an activated cultivation system'})


@hook('journey_source_sheet')
def acquired_sheet_overlay(sheet, session, actor_id):
    import json
    from copy import deepcopy
    saved = ((session.state['actors'][actor_id].get('source_states') or {}).get(SUBPATH) or {}).get('acquired_sheet')
    if not saved:
        return None
    acquired = json.loads(saved)
    out = deepcopy(sheet)
    paths = out.setdefault('path_and_subpath', {})
    old = acquired['path_and_subpath']
    for key in ('subpath_record_id', 'subpath_record_ids', 'subpaths', 'subpath', 'bindings', 'subpath_acquisition'):
        if key in old:
            paths[key] = deepcopy(old[key])
    level = next((int(p.get('effective_cl', p.get('attainment', 0))) for p in paths.get('paths') or []
                  if p.get('path_id') == 'tianxia.path.qi_cultivation'), 0)
    earned = [f for f, threshold in zip(FEATURES, (3, 6, 10, 14, 18)) if threshold <= level]
    parent = 'tianxia.subpath.qi.storm_soul_cultivator.feature.'
    for field in ('path_feature_record_ids', 'source_granted_subpath_feature_record_ids', 'advancement_feature_record_ids'):
        paths[field] = list(dict.fromkeys([s for s in paths.get(field) or [] if not s.startswith(parent) and s not in FEATURES] + earned))
    paths['earned_feature_occurrences'] = [r for r in paths.get('earned_feature_occurrences') or [] if not str(r.get('feature_id') or '').startswith(parent)]
    return out


@hook('journey_acquisition')
def acquire_variant(session, actor_id, source, payload, sheet):
    if source != SUBPATH:
        return None
    import json
    from copy import deepcopy
    from ..journey import require
    from ..fact_consent_admission import read, canonical
    actor = session.state['actors'][actor_id]
    require(not actor['incapacitated'], 'An incapacitated creature cannot acquire this progression.')
    procedure = payload.get('procedure', 'complete')
    expected = {'access_scope', 'procedure', 'environment_scope'} if procedure == 'train' else {'access_scope', 'procedure'} if 'procedure' in payload else {'access_scope'}
    require(procedure in ('train', 'complete') and set(payload) == expected, 'Choose Direct Entry, completed Conversion Entry, or one conversion training session.')
    access = read(session, SUBPATH, actor_id, 'source_access', payload['access_scope'], actor_id)
    require(access is not None, 'The world owner must record access to the Rare Variant and its legal source first.')
    value = access['value']
    require(set(value) in ({'variant', 'route', 'source_rule'}, {'variant', 'route', 'source_rule', 'check_replacement'}) and value['variant'] == SUBPATH
        and value['route'] in ('direct', 'conversion') and type(value['source_rule']) is str and value['source_rule'].strip(),
        'Name Heaven-Thunder Storm Soul, Direct or Conversion Entry, and the legal rule granting access.')
    sheet = deepcopy(sheet)
    paths = sheet.get('path_and_subpath') or {}
    profile = next((p for p in paths.get('paths') or [] if p.get('path_id') == 'tianxia.path.qi_cultivation'), None)
    require(profile is not None, 'This creature must have a native attained Qi Cultivation Path.')
    level = int(profile.get('effective_cl', profile.get('attainment', 0)))
    require(level >= 3, 'This progression requires at least Qi Cultivation level 3.')
    ids = set(paths.get('path_feature_record_ids') or []) | set(paths.get('source_granted_subpath_feature_record_ids') or [])
    ids.update(r['feature_id'] for r in paths.get('earned_feature_occurrences') or [] if r.get('feature_id'))
    parent = 'tianxia.subpath.qi.storm_soul_cultivator'
    parent_features = [parent + '.feature.' + f for f in ('wind_walker', 'gale_burst', 'lightning_reflexes', 'zephyr_s_step', 'eye_of_the_storm')]
    replaced = set(parent_features) & ids
    selections = {p.get('subpath_id') for p in paths.get('subpaths') or [] if p.get('owning_path_id') == 'tianxia.path.qi_cultivation'}
    selections.update(paths.get('subpath_record_ids') or [])
    if paths.get('subpath_record_id'):
        selections.add(paths['subpath_record_id'])
    require(SUBPATH not in selections and not set(FEATURES) & ids, 'This creature already has the Variant; acquisition cannot refill resources or reset scene limits.')
    state = journey_source_state(actor)
    if procedure == 'train':
        require(value['route'] == 'conversion' and replaced and selections <= {parent}, 'Conversion training requires the attained Storm Soul parent progression.')
        environment = read(session, SUBPATH, actor_id, 'conversion_environment', payload['environment_scope'], actor_id)
        require(environment is not None and environment['value'] == 1, 'The world owner must confirm calm conditions and usable spiritual energy for this Cultivation Session.')
        session.tick(7200)
        require(read(session, SUBPATH, actor_id, 'conversion_environment', payload['environment_scope'], actor_id) is not None,
                'The confirmed cultivation conditions must remain valid through both hours.')
        state['training_sessions'] = int(state.get('training_sessions') or 0) + 1
        rest = int(actor.get('long_rests') or 0)
        if state.get('cultivation_session_rest') != rest:
            maximum = next(r['maximum'] for r in actor['bundle']['actor_template']['resources'] if r['resource_id'] == QI)
            actor['resources'][QI] = maximum
            state['cultivation_session_rest'] = rest
        session.emit('HEAVEN_THUNDER_CONVERSION_SESSION', actor_id, seconds=7200, access_receipt=access['receipt_id'])
        return {'sheet': None, 'acquisition_id': access['receipt_id']}
    if value['route'] == 'direct':
        require(not selections and not replaced and not any(s.startswith('tianxia.subpath.qi.') for s in ids), 'Direct Entry is a first Subpath selection; it cannot retain another Qi progression.')
        earned = [f for f, threshold in zip(FEATURES, (3, 6, 10, 14, 18)) if threshold <= level]
    else:
        require(replaced and selections <= {parent}, 'Conversion Entry replaces only an attained Storm Soul Cultivator progression.')
        count = len(replaced)
        require(int(state.get('training_sessions') or 0) >= count, 'Complete one uninterrupted Cultivation Session for each attained parent feature before conversion.')
        state['training_sessions'] -= count
        from ..gate2_rolls import DeterministicRollAuthority
        from ..activation_settlement import path_numbers
        profile_numbers = path_numbers(
            {'numbers': {'cl': level, 'pb': int(sheet['identity']['proficiency_bonus'])}, 'owner_sheet': sheet}, 'tianxia.path.qi_cultivation')
        pb = int(profile_numbers['pb'])
        key = sheet['identity']['key_ability']
        modifier = pb + next(int(a.get('modifier', (a['score'] - 10)//2)) for a in sheet['ability_scores_and_statistics']['abilities'] if a['ability'] == key)
        roller = DeterministicRollAuthority(session.state['journey_id'] + ':heaven_thunder_conversion', counter=int(state.get('roll_counter') or 0))
        dc = 10 + pb + count
        alternative = value.get('check_replacement')
        if alternative is not None:
            require(isinstance(alternative, dict) and set(alternative) == {'kind', 'completed', 'reason'}
                and alternative['kind'] in ('story_condition', 'tribulation', 'permanent_price', 'unavoidable_transformation')
                and type(alternative['completed']) is int and alternative['completed'] == 1
                and type(alternative['reason']) is str and alternative['reason'].strip(),
                'The world owner must identify and confirm the completed printed alternative to the conversion check.')
            session.emit('HEAVEN_THUNDER_CONVERSION_CHECK_REPLACED', actor_id, access_receipt=access['receipt_id'],
                         kind_name=alternative['kind'], reason=alternative['reason'], sessions_spent=count)
        else:
            rolled = roller.d20(modifier=modifier, actor_id=actor_id, reason='HEAVEN_THUNDER_CONVERSION_CHECK')
            state['roll_counter'] = roller.counter
            session.emit('HEAVEN_THUNDER_CONVERSION_ROLLED', actor_id, roll=canonical(rolled.model_dump(mode='json')), dc=dc, sessions_spent=count)
            if rolled.total < dc:
                return {'sheet': None, 'acquisition_id': access['receipt_id']}
        earned = [feature for old, feature in zip(parent_features, FEATURES) if old in replaced]
    for field in ('path_feature_record_ids', 'source_granted_subpath_feature_record_ids', 'advancement_feature_record_ids'):
        paths[field] = list(dict.fromkeys([s for s in paths.get(field) or [] if not s.startswith(parent + '.feature.')] + earned))
    paths['earned_feature_occurrences'] = [r for r in paths.get('earned_feature_occurrences') or [] if not str(r.get('feature_id') or '').startswith(parent + '.feature.')]
    paths['subpath_record_id'] = SUBPATH
    paths['subpath_record_ids'] = [SUBPATH]
    selected = {'subpath_id': SUBPATH, 'owning_path_id': 'tianxia.path.qi_cultivation', 'display_name': 'Heaven-Thunder Storm Soul'}
    paths['subpaths'] = [p for p in paths.get('subpaths') or [] if p.get('owning_path_id') != 'tianxia.path.qi_cultivation'] + [selected]
    paths['subpath_acquisition'] = {'access_receipt': access['receipt_id'], 'source_rule': value['source_rule'],
        'route': value['route'], 'path_level': level, 'replaced_features': sorted(replaced), 'earned_features': earned}
    sheet['path_and_subpath'] = paths
    state['acquired_sheet'] = canonical(sheet)
    state.setdefault('sparks', 0)
    old_catalog = actor['bundle']['action_catalog']
    replaced_sources = {a['source_definition_id'] for a in old_catalog if str((a.get('parameters', {}).get('typed') or {}).get('source') or '').startswith(parent + '.feature.')}
    for recipient in session.state['actors'].values():
        snapshot = recipient.get('encounter_snapshot') or {}
        for iid, raw in list((snapshot.get('conditions') or {}).items()):
            old = json.loads(raw)
            if old.get('source_actor_id') == actor_id and (old.get('source_definition_id') in replaced_sources or str(old.get('source_definition_id') or '').startswith(parent + '.feature.')):
                del snapshot['conditions'][iid]
    session.emit('HEAVEN_THUNDER_SOURCE_ACQUIRED', actor_id, access_receipt=access['receipt_id'],
                 route=value['route'], earned_features=earned, replaced_features=sorted(replaced))
    return {'sheet': sheet, 'acquisition_id': access['receipt_id']}
