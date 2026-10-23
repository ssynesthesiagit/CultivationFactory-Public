"""Flame That Welcomes All: live sanctuary membership and activation receipts.

Only the owned reviewed effect creates this field. Recovery is a recipient
choice on initial membership or late entry, never an unconditional temp-HP grant.
"""
from . import effect, hook
from .qi_hearthfire import BASE, hearths
from .qi_homefire_recovery import receive
from .rider_choices import intent_for

SOURCE = BASE + 'flame_that_welcomes_all'
THRESHOLD = 'condition:typed.hospitality_threshold'
KINDS = ['daemonic', 'demon', 'fiend', 'incorporeal', 'possessing entity', 'undead', 'hostile spirit']


@hook('compile_action')
def self_or_hearth(action, info):
    typed = action.parameters.get('typed') or {}
    if typed.get('source') == SOURCE and any(e.get('type') == 'qi_welcoming_flame' for e in typed.get('effects') or []):
        return action.model_copy(update={'target_kind': 'SELF', 'range_ft': None,
            'parameters': {**action.parameters, 'typed': {**typed, 'area': None}}})


def fields(engine):
    return [z for z in engine.state.zones.values() if z.active
            and (z.trigger_profile.get('profile') or {}).get('welcoming_flame')]


def inside(engine, zone, subject, at=None):
    from ..spatial_areas import zone_contains
    return zone_contains(engine, subject, zone, at=at)


def chosen_ally(engine, zone, subject):
    from ..relations import ALLY, relation
    owner = engine.state.actors.get(zone.owner_id)
    return (owner is not None and subject.entity_id in zone.trigger_profile['profile']['recipients']
            and relation(engine, owner, subject) == ALLY)


def protects(engine, zone, subject):
    return chosen_ally(engine, zone, subject) and inside(engine, zone, subject)


def context(engine, zone, subject, intent=None):
    from ..zones import delayed_area_effect_context
    return delayed_area_effect_context(engine, zone, subject, typed={'numbers': zone.trigger_profile['numbers']},
        owner=engine.state.actors[zone.owner_id], action=engine.action_catalog[zone.source_definition_id],
        intent=intent or intent_for(engine), moment='hospitality')


@effect('qi_welcoming_flame', harmful=False)
def create(ctx, row):
    from .. import zones
    from .needle import ask, CHOICE, checkpoint_id
    from . import ai_controlled
    from ..target_knowledge import can_see
    active = hearths(ctx.engine, ctx.actor)
    centers = {'self': ctx.actor.position, **{z.zone_id: z.center for z in active}}
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'welcome_center'), ctx.actor,
        CHOICE + 'welcome_center', list(centers), preferred=['self'], allow_decline=False,
        labels={'self': 'Center on yourself', **{z.zone_id: 'Center on your active Hearth' for z in active}},
        feature_id=SOURCE, name='Flame That Welcomes All',
        prompt='Flame That Welcomes All: spend an Action and 8 Qi, once per scene, to create a fixed 40-foot sanctuary for 1 minute with Concentration. Choose yourself or your active Hearth as its center.')
    from ..relations import ALLY, relation
    allies = [a for a in ctx.engine.state.actors.values() if a.active and relation(ctx.engine, ctx.actor, a) == ALLY]
    ids = [a.entity_id for a in allies]
    if ai_controlled(ctx.engine, ctx.actor):
        chosen = [a.entity_id for a in allies if can_see(ctx.engine, ctx.actor, a)]
    else:
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'welcome_recipients'), ctx.actor,
            CHOICE + 'welcome_recipients', ids, preferred=ids, minimum=0, maximum=len(ids),
            allow_decline=True, default='all', labels={a.entity_id: a.display_name for a in allies},
            feature_id=SOURCE, name='Flame That Welcomes All',
            prompt='Flame That Welcomes All: choose the allies protected while inside the 40-foot sanctuary for 1 minute. Each may choose one Homefire Recovery benefit, once per Long Rest, even if it enters later.')
    # Preserve the actual source, economy, cost, concentration and cadence.
    from dataclasses import replace
    intent = ctx.intent.model_copy(update={'destination': centers[selected[0]]})
    zone = zones.create(replace(ctx, intent=intent), {'name': 'Flame That Welcomes All',
        'shape': 'cylinder', 'size_ft': 40, 'height_ft': 40,
        'duration': {'kind': 'minutes', 'amount': 1, 'concentration': True},
        'profile': {'welcoming_flame': 1, 'recipients': chosen}, 'inside': [], 'triggers': [],
        'visual': {'material': 'fire'}})
    if zone:
        recover_members(ctx.engine, zone, ctx.intent)


def recover_members(engine, zone, intent=None, *, arriving=None, at=None):
    """Use the committed arrival endpoint, including per-step callbacks.

    A persisted per-field offer avoids prompting again after reentry or a
    declined initial benefit. Late entry is not an activation-time snapshot.
    """
    from .retained_updates import record_zone_update
    subjects = [arriving] if arriving is not None else list(engine.state.actors.values())
    for subject in subjects:
        key = 'homefire_offered:' + subject.entity_id
        member = chosen_ally(engine, zone, subject) and inside(engine, zone, subject, at=at)
        if zone.per_turn_triggered.get(key) or not member:
            continue
        zone.per_turn_triggered[key] = 1
        record_zone_update(engine, zone)
        receive(context(engine, zone, subject, intent), subject)


@hook('choice_reactors')
def recipients(engine):
    # Enroll before activation as well: initial recipients make their own
    # recovery choice inside the same transaction that creates the field.
    owners = {a.owner_id for a in engine.action_catalog.values()
              if (a.parameters.get('typed') or {}).get('source') == SOURCE}
    from ..relations import ALLY, relation
    return [a.entity_id for a in engine.state.actors.values()
            if any(relation(engine, engine.state.actors[aid], a) == ALLY for aid in owners
                   if aid in engine.state.actors)]


@hook('zone_arrival')
def entry(engine, creature, start, end, forced):
    for zone in fields(engine):
        if inside(engine, zone, creature, at=end) and not inside(engine, zone, creature, at=start):
            recover_members(engine, zone, arriving=creature, at=end)


@hook('ac')
def armor(engine, subject):
    return 1 if any(protects(engine, z, subject) for z in fields(engine)) else None


@hook('damage_defenses')
def resistance(engine, subject, kind, typed, source_actor_id):
    if str(kind).upper() in ('FIRE', 'COLD') and any(protects(engine, z, subject) for z in fields(engine)):
        return [{'kind': 'resistance', 'damage_types': [str(kind).upper()]}]


@hook('save_effects')
def saves(ctx, subject, ability, fail_effects, success_effects, categories):
    from ..typed_executor import _walk_rows
    named = {e.get('condition') for e in _walk_rows(fail_effects)}
    protected = bool(named & {'charmed', 'frightened', 'possessing'}) or any(
        c == 'possession' or c.startswith('environmental_') for c in categories)
    if protected and any(protects(ctx.engine, z, subject) for z in fields(ctx.engine)):
        return {'modes': ['ADVANTAGE']}


@hook('final_damage', priority=-10)
def reduction(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    if amount <= 0:
        return
    from .retained_updates import record_zone_update
    for zone in fields(engine):
        if not protects(engine, zone, target):
            continue
        key = 'hearthward_round:' + target.entity_id
        if zone.per_turn_triggered.get(key) == engine.state.round_number:
            continue
        zone.per_turn_triggered[key] = engine.state.round_number
        record_zone_update(engine, zone)
        return {'reduction': min(amount, int(zone.trigger_profile['numbers']['pb']))}


@hook('turn_start_choice')
def start(engine, subject):
    from .needle import ask, CHOICE, checkpoint_id
    from ..typed_executor import run_effects
    from .creature_kinds import matches
    for zone in fields(engine):
        owner = engine.state.actors[zone.owner_id]
        recover_members(engine, zone)
        if subject.entity_id == zone.owner_id:
            allies = [a for a in engine.state.actors.values() if a.active and protects(engine, zone, a)]
            if allies:
                ctx = context(engine, zone, subject)
                picked = ask(engine, ctx.intent, checkpoint_id(engine, 'feed_living_flame', zone.zone_id, subject.turns_started),
                    owner, CHOICE + 'feed_living_flame', [a.entity_id for a in allies],
                    labels={a.entity_id: a.display_name for a in allies}, allow_decline=False,
                    preferred=[min(allies, key=lambda a: a.current_hp).entity_id],
                    feature_id=SOURCE, name='Feed the Living Flame',
                    prompt=f'Feed the Living Flame: at the start of {owner.display_name}’s turn, choose one ally inside the sanctuary to regain 2d8 + your key modifier Hit Points, without cost or an action.')
                run_effects(context(engine, zone, engine.state.actors[picked[0]]),
                    [{'type': 'heal', 'applies_to': 'target', 'dice': {'count': 2, 'sides': 8}, 'formula': 'key_ability_modifier'}])
        from ..relations import ENEMY, relation
        if relation(engine, owner, subject) != ENEMY or not inside(engine, zone, subject) or not matches(subject, KINDS):
            continue
        # Native typed save owns Advantage, outcomes, roll journal and replay.
        ctx = context(engine, zone, subject)
        run_effects(ctx, [{'type': 'save', 'applies_to': 'target', 'ability': 'cha',
            'on_fail': [{'type': 'qi_hospitality_threshold', 'failed': 1}],
            'on_success': [{'type': 'qi_hospitality_threshold', 'failed': 0}]}])


@effect('qi_hospitality_threshold', harmful=True)
def threshold(ctx, row):
    from ..typed_executor import effect_expiry
    z = next(z for z in fields(ctx.engine) if z.source_definition_id == ctx.source)
    ctx.engine._apply_condition(ctx.target, THRESHOLD, ctx.source, ctx.actor.entity_id,
        expires_on='START_OF_TARGET_NEXT_TURN', data={'zone_id': z.zone_id, 'failed': int(row['failed']),
            'center': z.center.model_dump(mode='json'),
            'rule': {'no_reactions': True} if row['failed'] else {},
            'label': 'Threshold of Hospitality: cannot possess creatures inside the sanctuary'
                + ('; cannot willingly move closer to its center or take Reactions until your next turn' if row['failed'] else ' until your next turn')})


def closer(engine, mover, old, nxt):
    from ..gate2_runtime_models import Position
    return any(c.condition_id == THRESHOLD and c.data.get('failed')
               and engine.grid.distance_ft(nxt, Position.model_validate(c.data['center']))
                   < engine.grid.distance_ft(old, Position.model_validate(c.data['center']))
               for c in mover.conditions.values())


@hook('movement_attempt')
def movement(engine, mover, previous, nxt, intent):
    if closer(engine, mover, previous, nxt):
        return {'stop': True, 'source_id': SOURCE, 'label': 'Threshold of Hospitality: cannot willingly move closer to the sanctuary center.'}


@hook('teleport_context_check')
def teleport(engine, actor, start, destination, movement_context):
    if movement_context != 'WILLING':
        return None
    return False if closer(engine, actor, start, destination) else None


@hook('effect_allowed')
def possession(ctx, row):
    if 'possession' not in (row.get('spiritual_categories') or []):
        return
    for c in ctx.actor.conditions.values():
        if c.condition_id != THRESHOLD:
            continue
        zone = ctx.engine.state.zones.get(c.data['zone_id'])
        if zone is not None and any(inside(ctx.engine, zone, s) for s in ctx.targets):
            return False


@hook('zero_hp')
def no_guest_dies_alone(engine, target, source_id, intent):
    from ..pending_damage import current
    packet = current(engine)
    if target.current_hp != 0 or packet is None or packet.target_id != target.entity_id or packet.source_id != source_id:
        return
    protecting = [z for z in fields(engine) if protects(engine, z, target)]
    if not protecting:
        return
    # Read the committed allocation, after Resistance, reductions and temp HP.
    damage = next((e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED'
                   and target.entity_id in e.target_ids), None)
    if damage is None or int(damage.payload['hp_before']) <= 0:
        return
    from .life_state import massive
    if int(damage.payload['hp_damage']) - int(damage.payload['hp_before']) >= massive(engine, target):
        return
    from .retained_updates import record_zone_update
    from ..typed_executor import run_effects
    for zone in protecting:
        key = 'guest_saved:' + target.entity_id
        if not protects(engine, zone, target) or zone.per_turn_triggered.get(key):
            continue
        zone.per_turn_triggered[key] = 1
        record_zone_update(engine, zone)
        ctx = context(engine, zone, target, intent)
        run_effects(ctx, [{'type': 'temp_hp', 'applies_to': 'target', 'formula': 'double_pb'}])
        # Commit the zero-HP outcome before movement can trigger another
        # sanctuary's recovery choice (which may heal this same creature).
        from .life_state import UNCONSCIOUS
        engine._apply_condition(target, UNCONSCIOUS, source_id, target.entity_id, expires_on='UNTIL_REMOVED',
                                data={'label': 'Unconscious and Stable at 0 Hit Points'})
        # The Stable outcome is evented before the printed step moves the creature (the step reads the life state).
        engine._set_life_state(target, 'STABLE', source_id)
        # Granted motion owns legality and no-op choice; no Action, Reaction or OA.
        from dataclasses import replace
        from .rider_step import step
        from ..granted_movement import speed_zero_exempt
        with speed_zero_exempt(engine, target):
            step(replace(ctx, actor=target), {'distance_ft': 5, 'no_oa': True, 'label': 'No Guest Dies Alone'})
        # A nested entry hook may have healed the creature during the step.  The
        # zero-HP resolver must not reapply its pre-step Stable result to a live
        # creature; use the ordinary conscious outcome in that case.
        return 'STABLE' if target.current_hp == 0 else 'CONSCIOUS'
