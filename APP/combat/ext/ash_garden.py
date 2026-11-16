"""Perfected Ash Garden consumers of native zones and public Ash facts.

The compiler seals ownership; the native moving zone owns activation/expiry.
Confirmed-hit receipts preserve actual pre-hit HP and field membership.
Ash source/scene policy belongs to foundation_context, not this consumer.
Generation uses pressure's existing resource cap, round allowance and expiry.
Shared helper: owns_zero_drop(engine, owner, event) is the pure zero-drop ownership query
used by foundations3 damage/drop settlement; it grants nothing by itself.
"""
from . import hook, note
from .needle import ask, checkpoint_id, CHOICE

GARDEN = 'foundation.red_lotus_ash_returning_v0_2B.perfected_ninefold_red_lotus_ash_garden'
NAME = 'Ninefold Red Lotus Ash Garden'
KINDS = ('fire', 'necrotic', 'poison', 'slashing')


@hook('compile_passives')
def seal_garden(rows, info):
    if GARDEN not in info['owned_ids']:
        return rows
    return [*rows, {'block': 'ash_garden', 'feature_id': GARDEN}]


def owned(engine, actor):
    return actor is not None and any(r.get('block') == 'ash_garden'
        and r.get('feature_id') == GARDEN
        for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ()))


def active_garden(engine, owner, subject=None):
    """Public Garden membership query for Ash generation/ending consumers.

    Only the owner's actual, still-active compiled Garden emanation qualifies;
    absent ownership/zone leaves other Foundation actors unchanged.
    """
    if not owned(engine, owner):
        return None
    from ..zones import typed_zones
    from ..spatial_areas import zone_contains
    return next((z for z in typed_zones(engine) if z.active and z.owner_id == owner.entity_id
        and (z.trigger_profile.get('source_profile') or {}).get('mechanic_id') == GARDEN
        and (subject is None or zone_contains(engine, subject, z))), None)


@hook('confirmed_hit_damage_bonus')
def choose_garden_hit(engine, attacker, target, spec, intent, source, critical):
    if not owned(engine, attacker):
        return None
    from ..relations import relation, ENEMY
    if not (active_garden(engine, attacker, target) and relation(engine, attacker, target) == ENEMY
            and 0 < target.current_hp < target.maximum_hp):
        return
    from .foundation_context import adjudicated_event_context, ash_aligned
    # Cover can change the recipient after ATTACK_ROLLED. The native resolver
    # carries this hit's identity even when the original target differs.
    roll_id = spec['attack_roll_id']
    # This receipt is produced only by the native final-confirmed-hit callback.
    # It is not a damage packet, and does not claim that any damage occurred.
    receipt = engine._append_event('PASSIVE_TRIGGERED', source, actor_id=attacker.entity_id,
        target_ids=(target.entity_id,), payload={'fact_kind': 'ash_garden_confirmed_hit',
            'hp_before': int(target.current_hp), 'garden_owner': attacker.entity_id,
            'target_active_before': int(target.active),
            'target_conditions_before': sorted(c.condition_id for c in target.conditions.values()),
            'roll_id': roll_id})
    facts = adjudicated_event_context(engine, attacker, receipt, intent, route='outgoing',
        ability_name=NAME, feature_id=GARDEN, alignment_only=True)
    if not ash_aligned(engine, attacker, receipt, facts):
        return
    action = engine.action_catalog[source]
    selected = ask(engine, intent, checkpoint_id(engine, 'ASH_GARDEN_DAMAGE', target.entity_id),
        attacker, CHOICE + 'ash_garden.damage', list(KINDS),
        labels={k: k.title() for k in KINDS}, allow_decline=False, preferred=['fire'],
        target_id=target.entity_id, feature_id=GARDEN, name=NAME,
        prompt_context={'action_name': action.display_name, 'cost': 'No extra action or resource cost'},
        prompt=f'{NAME}: {action.display_name} hit wounded enemy {target.display_name} inside your active garden. '
               'Choose Fire, Necrotic, Poison, or Slashing for additional damage equal to your Proficiency Bonus. '
               'This costs no extra action or resource and lasts only while the one-minute garden is active.')
    engine._append_event('PASSIVE_TRIGGERED', source, actor_id=attacker.entity_id,
        target_ids=(target.entity_id,), payload={'fact_kind': 'ash_garden_damage_choice',
            'roll_id': roll_id, 'damage_type': selected[0],
            'amount': int(attacker.proficiency_bonus)})


def owns_zero_drop(engine, owner, event):
    """Garden owns optional generation for this native in-field hostile drop.

    The base Foundation consumer uses the same query to avoid granting Ash
    through a second route after the player declines Garden's choice.
    Receipt membership preserves the field at damage time, including reload.
    """
    from .foundation_context import hostile_zero_drop
    return bool(owned(engine, owner)
        and owner.entity_id in event.payload.get('ash_garden_owners_before', ())
        and hostile_zero_drop(engine, owner, event))


def hit_choice(engine, attack):
    if any(e.payload.get('fact_kind') == 'ash_garden_damage_delivered'
           and e.payload.get('roll_id') == attack.roll_id for e in engine.events):
        return None
    return next((e for e in reversed(engine.events)
        if e.payload.get('fact_kind') == 'ash_garden_damage_choice'
        and e.actor_id == attack.attacker_id and attack.target_id in e.target_ids
        and e.payload.get('roll_id') == attack.roll_id), None)


def deliver_component(ctx, target, receipt, hp_before, hp_damage):
    from ..typed_executor import run_effects
    from .life_state import additional_hit_component, HIT_COMPONENT_FLAG
    ctx.engine._append_event('PASSIVE_TRIGGERED', GARDEN, actor_id=ctx.actor.entity_id,
        target_ids=(target.entity_id,), payload={'fact_kind': 'ash_garden_damage_delivered',
            'roll_id': receipt.payload['roll_id']})
    child = ctx.on_hit_context(target, effect_source=GARDEN,
        damage_source_flags=(*ctx.damage_source_flags, HIT_COMPONENT_FLAG))
    with additional_hit_component(ctx.engine, target, hp_before, hp_damage):
        run_effects(child, [{'type': 'extra_damage', 'flat': receipt.payload['amount'],
            'applies_to': 'target', 'damage_types': [receipt.payload['damage_type']]}])


@hook('event', nested=True, priority=100)
def garden_component(engine, event_type, kwargs):
    if event_type != 'DAMAGE_COMMITTED':
        return
    attack = engine.damage_context()
    if attack is None or not owned(engine, engine.state.actors.get(attack.attacker_id)):
        return
    receipt = hit_choice(engine, attack)
    if receipt is None:
        return
    from ..pending_damage import current
    from ..typed_executor import Context
    from .needle import numbers_of
    actor, target = engine.state.actors[attack.attacker_id], engine.state.actors[attack.target_id]
    action = engine.action_catalog[attack.source_id]
    typed = {**(action.parameters.get('typed') or {}), 'numbers': numbers_of(engine, actor)}
    ctx = Context(engine, actor, action, engine._active_intent, typed, [target], target,
        attack_damage_context=attack)
    packet = current(engine)
    deliver_component(ctx, target, receipt, packet.hp_before, int((kwargs.get('payload') or {}).get('hp_damage', 0)))


@hook('hit_final')
def garden_damageless_hit(ctx, target, kind):
    attack = ctx.attack_damage_context
    receipt = hit_choice(ctx.engine, attack) if attack is not None else None
    if receipt is not None:
        deliver_component(ctx, target, receipt, target.current_hp, 0)


@hook('damage_receipt_facts')
def garden_damage_membership(engine, target, source_id, source_actor_id):
    owners = [a.entity_id for a in engine.state.actors.values() if active_garden(engine, a, target)]
    return {'ash_garden_owners_before': owners} if owners else None


@hook('transaction_settled')
def garden_endings(engine, source_id, actor_id, intent, first_sequence):
    from .foundation_context import settled_execution_events, adjudicated_event_context, conscious, helpless_before, hostile_zero_drop
    from ..relations import relation, ENEMY
    from .. import pressure
    if intent is None:
        return
    owners = [a for a in engine.state.actors.values() if owned(engine, a) and conscious(a)
        and not a.resources.get('resource:foundation.funeral_ash', 0)]
    # Public human testimony for this exact event is available before automatic
    # consumers resolve; automatic owners never supply invented scene facts.
    from .needle import ai_controlled
    owners.sort(key=lambda a: (ai_controlled(engine, a), a.entity_id))
    if not owners:
        return
    events = settled_execution_events(engine, first_sequence)
    for event in events:
        payload = event.payload or {}
        zero = event.event_type == 'DAMAGE_COMMITTED' and int(payload.get('hp_before') or 0) > 0 \
            and payload.get('remaining_hp') == 0 and not helpless_before(event)
        stable = event.event_type == 'LIFE_STATE_CHANGED' and payload.get('life_state') == 'STABLE'
        if stable and engine.action_catalog.get(event.source_definition_id) is None:
            # A system death-save stabilization is not a cautery/spare action.
            continue
        if not zero and not stable:
            continue
        target = engine.state.actors.get(next(iter(event.target_ids), '') if zero else event.actor_id)
        if target is None:
            continue
        for owner in owners:
            if zero and not hostile_zero_drop(engine, owner, event):
                continue
            inside = (owner.entity_id in payload.get('ash_garden_owners_before', ()) if zero
                      else active_garden(engine, owner, target))
            if not inside or relation(engine, owner, target) != ENEMY \
                    or owner.resources.get('resource:foundation.funeral_ash', 0):
                continue
            facts = adjudicated_event_context(engine, owner, event, intent, route='zero_hp' if zero else 'ending',
                ability_name=NAME, feature_id=GARDEN)
            if facts.get('circumstances') != 'real' or facts.get('ending') not in ('zero_hp', 'defeat', 'mercy', 'cautery'):
                continue
            action = engine.action_catalog.get(event.source_definition_id)
            action_name = action.display_name if action else 'the resolved event'
            ending_text = {'zero_hp': 'reached 0 HP', 'defeat': 'was defeated',
                           'mercy': 'was genuinely spared after defeat',
                           'cautery': 'was stabilized through cautery'}[facts['ending']]
            selected = ask(engine, intent, checkpoint_id(engine, 'ASH_GARDEN_GENERATE', event.sequence, owner.entity_id),
                owner, CHOICE + 'ash_garden.generate', ['generate'], labels={'generate': 'Gain 1 Funeral Ash'},
                allow_decline=True, preferred=['generate'], target_id=target.entity_id, feature_id=GARDEN, name=NAME,
                prompt_context={'action_name': action_name, 'cost': 'No action or resource cost'},
                prompt=f'{NAME} after {action_name}: {target.display_name} {ending_text} '
                    'inside your garden. Gain 1 Funeral Ash to pay for a later Ash ability, or decline. Maximum 1; at most once '
                    'per round; expires at the end of your next turn; it cannot pay for this same event.')
            if selected and pressure.generate(engine, owner, 'foundations3_ash'):
                note(engine, GARDEN, owner, owner.display_name + ' gains 1 Funeral Ash from ' + NAME +
                    '; it expires at the end of their next turn and can be spent on a later event.')
