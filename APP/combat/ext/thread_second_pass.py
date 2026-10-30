"""Source-sealed Thread control and movement, A2THREAD.

New data/effects opt in; historical actions and unannotated conditions are inert.
No runtime prose matching or saved-fight policy changes.
"""
from . import effect, hook, note
from .thread_common import LINE, mark_held_by

LOCK = 'tianxia.talent.thread.meridian_lock'
NET = 'tianxia.talent.thread.heaven_net_casting'
SILK = 'tianxia.talent.thread.silk_step'
CROWD = 'TAL_THREAD_THREAD_THROUGH_THE_CROWD'
REEL = 'TAL_THREAD_REELING_SILK_BODY'
PASSAGE = 'condition:typed.thread_passage'
FOCUS = 'resource:core.martial_focus'


def source(action):
    return ((getattr(action, 'parameters', None) or {}).get('typed') or {}).get('source')


def rows(value):
    if isinstance(value, dict):
        if 'type' in value:
            yield value
        for child in value.values():
            yield from rows(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from rows(child)


def qi_connected(engine, actor, target):
    from .thread_weaving import QI_THREAD
    if not mark_held_by(target, actor.entity_id, LINE):
        return False
    if any(c.condition_id == QI_THREAD for c in actor.conditions.values()):
        return True
    for c in target.conditions.values():
        if c.condition_id == mark_held_by(target, actor.entity_id, LINE):
            action = engine.action_catalog.get(c.source_definition_id)
            if ((getattr(action, 'parameters', None) or {}).get('thread_twin') or {}).get('qi'):
                return True
    return False


@hook('candidate_allowed')
def lock_allowed(engine, actor, candidate, action):
    if action is None:
        return None
    typed = (action.parameters or {}).get('typed') or {}
    if any(r.get('type') == 'thread_meridian_lock' for r in rows(typed.get('effects'))):
        return bool(candidate.target_ids) and all(t in engine.state.actors and qi_connected(engine, actor, engine.state.actors[t])
                   for t in candidate.target_ids)
    if not any((c.data or {}).get('thread_meridian_lock') == 1 for c in actor.conditions.values()
               if c.condition_id == 'condition:typed.restrained'):
        return None
    from ..typed_executor import CP_POOLS
    paid = any(pool in CP_POOLS and amount > 0 for pool, amount in action.costs)
    effects = list(rows(typed.get('effects')))
    paid |= any(r.get('type') == 'spend_resource' and r.get('resource_id') in CP_POOLS
                and r.get('applies_to', 'self') == 'self'
                and (int(r.get('flat') or 0) > 0 or r.get('formula') not in (None, '', 'none')
                     or int((r.get('dice') or {}).get('count') or 0) > 0)
                for r in effects)
    from .movement_semantics import technique_categories
    if paid and any(technique_categories(r).intersection({'movement', 'escape'}) for r in effects):
        return False
    from .movement_semantics import primary_moves_user
    if paid and primary_moves_user(typed):
        return False
    return None


@hook('paid_relocation_guard')
def meridian_lock_paid_relocation(engine, actor, previous, destination):
    """Return CP restrictions for the general transactional assignment observer."""
    if not any(c.condition_id == 'condition:typed.restrained'
               and (c.data or {}).get('thread_meridian_lock') == 1
               for c in actor.conditions.values()):
        return None
    from ..paid_relocation import Restriction
    from ..typed_executor import CP_POOLS
    return Restriction(
        'Meridian Lock prevents spending Cultivation Points to move, teleport, or escape.',
        frozenset(CP_POOLS),
    )


@effect('thread_meridian_lock', harmful=True)
def meridian_lock(ctx, row):
    from .. import typed_executor as te
    if ctx.target is None or not qi_connected(ctx.engine, ctx.actor, ctx.target):
        return
    te.block_save(ctx, {'type': 'save', 'ability': 'con', 'on_fail': [{
        'type': 'condition', 'condition': 'restrained', 'applies_to': 'target',
        'duration': 'until_end_of_your_next_turn', 'repeat_save': {'ability': 'CON', 'when': 'end'},
        'condition_data': {'thread_meridian_lock': 1, 'label': 'Meridian Lock: Restrained; cannot spend CP on movement, teleportation, forced movement or escape techniques.'},
        'evidence': 'Restrained until the end of your next turn; cannot spend CP on movement, teleportation, forced movement or escape techniques.'}],
        'on_success': [{'type': 'speed', 'halved': True, 'applies_to': 'target',
                        'duration': 'until_end_of_your_next_turn'}]})


@hook('turn_start_choice')
def maintain_lock(engine, actor):
    from .d20_rewrite import pool_id
    from .needle import ask, checkpoint_id
    from .condition_ownership import remove_instance
    from .effect_durations import token
    from .choice_costs import Payment
    held = [(target, iid, c) for target in engine.state.actors.values() if target.active
            for iid, c in target.conditions.items() if c.condition_id == 'condition:typed.restrained'
            and c.source_actor_id == actor.entity_id and (c.data or {}).get('thread_meridian_lock') == 1]
    for target, iid, c in held:
        pool = pool_id(actor, 'cp')
        if pool is None or actor.resources.get(pool, 0) < 1:
            return
        payment = Payment(pool, 1)
        selected = ask(engine, getattr(engine, '_active_intent', None),
            checkpoint_id(engine, 'thread_lock_maintain', iid), actor, 'choice:needle.thread.lock_maintain',
            ['maintain'], labels={'maintain': f'Keep {target.display_name} locked (1 CP)'},
            allow_decline=True, name='Meridian Lock', target_id=target.entity_id, payment=payment,
            prompt=f'Meridian Lock: spend 1 CP (cultivation point) to keep {target.display_name} Restrained and unable to spend CP on movement, teleportation, forced movement or escape techniques until the end of your next turn? It still repeats its Constitution save at the end of each of its turns.')
        if selected:
            payment.pay(engine, actor, LOCK)
            data = dict(c.data)
            remove_instance(engine, target, iid, LOCK)
            engine._apply_condition(target, c.condition_id, c.source_definition_id, actor.entity_id,
                expires_on=token('end', actor.entity_id, actor.turns_started + 1), data=data)
            note(engine, LOCK, actor, f'Meridian Lock: {actor.display_name} spends 1 CP to maintain the lock on {target.display_name}.', (target,))


@effect('thread_heaven_net', harmful=True)
def heaven_net(ctx, row):
    from dataclasses import replace
    from .. import typed_executor as te, flight
    from ..falling import supported
    # The printed save applies once when cast, to flying creatures of either team.
    area = {**ctx.typed['area'], 'recipients': 'all', 'include_self': True, 'exclude_self': False}
    flyers = [t for t in te._area_targets(ctx.engine, ctx.actor, ctx.destination, area, include_self=True)
              if t.position.z > 0 and not supported(ctx.engine, t) and ((capability := flight.profile(ctx.engine, t)).speed_ft > 0 or capability.hover)]
    # Freeze the whole casting roster before any loss of flight can settle a
    # lethal fall. Individual saves retain their targeting/self provenance, but
    # victory settles only after every flyer has resolved.
    with te.simultaneous(ctx, flyers):
        for target in flyers:
            te.block_save(replace(ctx, target=target, targets=[target],
                typed={**ctx.typed, 'area': {}}, explicit_self_recipient=target is ctx.actor), {
                'type': 'save', 'ability': 'str', 'applies_to': 'target',
                'on_fail': [{'type': 'condition', 'condition': 'thread_net_flight',
                    'applies_to': 'target', 'duration': 'until_start_of_next_turn',
                    'condition_data': {'fly_speed_zero': 1, 'label': 'Heaven-Net: Fly Speed 0 until the start of your next turn.'},
                    'evidence': 'Fly Speed becomes 0 until the start of its next turn; without Hover it falls.'}],
                'on_success': [{'type': 'condition', 'condition': 'thread_net_flight',
                    'applies_to': 'target', 'duration': 'until_start_of_next_turn',
                    'condition_data': {'fly_speed_reduction_ft': 20, 'fly_speed_reduction_key': 'thread_heaven_net',
                                       'label': 'Heaven-Net: Fly Speed reduced by 20 feet until the start of your next turn.'},
                    'evidence': 'Fly Speed reduced by 20 feet until the start of its next turn.'}]})


def net_zone(engine, zone):
    action = engine.action_catalog.get(zone.source_definition_id)
    return source(action) == NET and any(r.get('type') == 'thread_heaven_net' for r in rows(
        ((getattr(action, 'parameters', None) or {}).get('typed') or {}).get('effects')))


@hook('difficult_zone_exempt')
def net_air(engine, actor, zone):
    if net_zone(engine, zone) and actor.position.z > 0:
        from ..falling import supported
        return not supported(engine, actor)
    return None


@hook('ability_check_hazards')
def net_escape(engine, actor, ability, skill, hazards):
    if ability != 'DEX' or skill != 'Acrobatics' or not set(hazards).intersection({'grappled', 'restrained', 'thread'}):
        return None
    from .. import zones
    from ..falling import supported
    if not supported(engine, actor):
        return None
    if any(net_zone(engine, zone) and zones._hostile(engine, zone, actor) and engine._in_zone(actor, zone)
           for zone in zones.typed_zones(engine)):
        return 'DISADVANTAGE'
    return None


@effect('thread_line_passage', harmful=False)
def passage(ctx, row):
    ctx.engine._apply_condition(ctx.actor, PASSAGE, ctx.source, ctx.actor.entity_id,
        expires_on='END_OF_CURRENT_TURN', data={'crowd': int(bool(row.get('crowd'))),
        'label': 'Pass through creatures connected to your Thread Lines as Difficult Terrain.'})


@hook('pass_through')
def through(engine, mover, occupant):
    if any(c.condition_id == PASSAGE for c in mover.conditions.values()) and mark_held_by(occupant, mover.entity_id, LINE):
        return 'difficult'
    return None


@hook('opportunity_allowed')
def crowd_oa(engine, reactor, mover):
    if any(c.condition_id == PASSAGE and (c.data or {}).get('crowd') == 1 for c in mover.conditions.values()) and mark_held_by(reactor, mover.entity_id, LINE):
        return False
    return None


@hook('action_completed')
def internal_tension(engine, actor, economy, source_definition_id):
    if source_definition_id != 'system:combat.dodge' or actor.resources.get(FOCUS, 0) >= 1:
        return
    if not any(r.get('block') == 'thread_internal_tension' for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, [])):
        return
    if not any(mark_held_by(t, actor.entity_id, LINE) for t in engine.state.actors.values() if t.active):
        return
    from .needle import ask, checkpoint_id
    if ask(engine, getattr(engine, '_active_intent', None), checkpoint_id(engine, 'thread_internal_tension', actor.entity_id),
           actor, 'choice:needle.thread.internal_tension', ['regain'], labels={'regain': 'Regain Martial Focus'},
           allow_decline=True, name='Internal Tension',
           prompt='Reeling Silk Body — Internal Tension: you used Dodge while maintaining a Thread Line. Regain Martial Focus (no CP or extra action)?'):
        engine._gain_resource(actor, FOCUS, 1, REEL)


@hook('compile_passives')
def choice_owners(passives, info):
    owners = {REEL: ('thread_internal_tension', 'Internal Tension'),
              LOCK: ('thread_lock_owner', 'Meridian Lock'),
              'insight.silk-reeling-foundation': ('thread_foundation_owner', 'Silk-Reeling Foundation')}
    return [*passives, *[{'feature_id': mid, 'block': block, 'name': name, 'choice_owner': True}
                         for mid, (block, name) in owners.items() if mid in set(info['owned_ids'])]]


@effect('thread_foundation_step', harmful=False)
def foundation_step(ctx, row):
    from .rider_step import step
    key = 'once_per_round:thread_silk_reeling_foundation'
    if ctx.actor.turn_flags.get(key) == ctx.engine.state.round_number:
        return
    start = ctx.actor.position
    step(ctx, {'type': 'rider_step', 'distance_ft': 5,
               'label': 'Silk-Reeling Foundation', 'no_oa_from_target': True,
               'trigger': 'using Draw the Line or Threaded Strike'})
    if ctx.actor.position != start:
        ctx.actor.turn_flags[key] = ctx.engine.state.round_number
        note(ctx.engine, 'insight.silk-reeling-foundation', ctx.actor,
             'Silk-Reeling Foundation: the free 5-foot step is used for this round.')


@hook('compile_action')
def foundation_strike_followup(action, info):
    """Seal the Foundation benefit on actual Threaded Strike applications.

    Named action modifiers already cover Draw the Line. Threaded Strike is a
    linked on-hit choice: its effects live in attack branches and player loadout
    options, rather than a standalone action. The public immutable compile_action
    transform adds the follow-up to those owned effect lists for both transports.
    Settings contain no such list and never count as using the feature.
    """
    if 'insight.silk-reeling-foundation' not in set(info['owned_ids']):
        return action
    import copy
    parameters = copy.deepcopy(action.parameters)

    def attach(value):
        if isinstance(value, dict):
            for child in value.values():
                attach(child)
        elif isinstance(value, list):
            for child in value:
                attach(child)
            strike = next((row for row in value if isinstance(row, dict) and row.get('type')
                           and row.get('source_modifier') == 'THREAD_BASE_THREADED_STRIKE'), None)
            if strike is not None:
                if not any(isinstance(row, dict) and row.get('type') == 'thread_foundation_step' for row in value):
                    value.append({'type': 'thread_foundation_step', 'applies_to': 'self',
                                  'source_modifier': 'insight.silk-reeling-foundation',
                                  **{key: strike[key] for key in ('modifier_once', 'modifier_once_period')
                                     if key in strike}})

    attach(parameters.get('typed', {}))
    return action.model_copy(update={'parameters': parameters})


@hook('compile_action')
def lock_target(action, info):
    if any(r.get('type') == 'thread_meridian_lock' for r in rows(
            ((action.parameters or {}).get('typed') or {}).get('effects'))):
        return action.model_copy(update={'target_kind': 'ANY_CREATURE', 'range_ft': 30})
    return action


@hook('difficult_zone_at_exempt')
def net_air_destination(engine, actor, zone, destination):
    if not net_zone(engine, zone):
        return None
    from ..falling import supported
    return not supported(engine, actor.model_copy(update={'position': destination}))


@hook('escape_check_choice')
def net_escape_choice(ctx, row, dc, grips, hazards):
    choices = row.get('escape_check_choices') or row.get('thread_escape_choices')
    if not choices or not grips:
        return None
    # Only actual held physical bindings authorize the Thread scope, never an
    # unrelated check or a save. The original caller's removal/DC remain intact.
    scope = tuple(hazards)
    if any(c.condition_id == 'condition:typed.bound_limb' for c in grips):
        scope = (*scope, 'thread')
    if net_escape(ctx.engine, ctx.actor, 'DEX', 'Acrobatics', scope) is None:
        return None
    from .needle import ask, checkpoint_id
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'net_escape_skill', ctx.actor.entity_id),
        ctx.actor, 'choice:needle.thread.net_escape_skill', ['STR', 'DEX'],
        labels={'STR': f"Strength (Athletics), 1d20{choices['STR']['bonus']:+d}",
                'DEX': f"Dexterity (Acrobatics), 1d20{choices['DEX']['bonus']:+d}; Heaven-Net gives Disadvantage"},
        preferred=['STR'], name='Escape inside Heaven-Net',
        prompt=f"{ctx.actor.display_name} attempts to escape a physical binding inside Heaven-Net Casting. Choose Strength (Athletics) or Dexterity (Acrobatics) against DC {dc}. Heaven-Net imposes Disadvantage only on the Acrobatics check; other Advantage and Disadvantage still cancel normally.")
    ability = picked[0] if picked else 'STR'
    return {'ability': ability, **choices[ability], 'hazards': list(scope)}


@hook('condition_attempt')
def wing_replaces_grapple(ctx, subject, row):
    if row.get('condition') != 'grappled' or ctx.intent is None:
        return None
    if any(c.condition_id == 'condition:typed.bound_wing' and c.source_actor_id == ctx.actor.entity_id
           and c.data.get('binding_replacement_intent') == ctx.intent.intent_id
           for c in subject.conditions.values()):
        return False
    return None


@hook('row_allowed')
def lock_reaction_allowed(engine, actor, row):
    """The same CP technique restriction applies to off-turn reactions."""
    if not any(c.condition_id == 'condition:typed.restrained'
               and (c.data or {}).get('thread_meridian_lock') == 1
               for c in actor.conditions.values()):
        return None
    from ..resource_costs import as_dict
    from ..typed_executor import CP_POOLS
    from .movement_semantics import technique_categories
    effects = list(rows(row.get('effects')))
    paid = any(cost['resource_id'] in CP_POOLS and cost['amount'] > 0
               for raw in row.get('costs') or [] if (cost := as_dict(raw)))
    paid |= any(effect.get('type') == 'spend_resource' and effect.get('resource_id') in CP_POOLS
                and effect.get('applies_to', 'self') == 'self'
                and (int(effect.get('flat') or 0) > 0 or effect.get('formula') not in (None, '', 'none')
                     or int((effect.get('dice') or {}).get('count') or 0) > 0)
                for effect in effects)
    if paid and any(technique_categories(effect).intersection({'movement', 'escape'}) for effect in effects):
        return False
    return None
