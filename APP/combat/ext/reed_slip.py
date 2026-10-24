"""Weak Reed's paid movement conversion; no evolution policy lives here.

Public conversion_distance and settled_conversion serve the base conversion
and the Refined/Perfected shared Foundation conversion provider. Native
granted_movement owns terrain, posture, Speed,
occupancy, step hazards and source-specific opportunity attacks.
"""
from . import hook, note
from .foundation_conversion_bonus import conversion_available, conversion_bonus, settle_conversion_bonus

BLOCK = 'reed_slip'
SOURCE = 'foundation.weak_reed_tendons_v0_2B.reed_slip'
DESTINATION = 'choice:reed_slip.destination'
EXEMPTION = 'choice:reed_slip.exemption'


@hook('choice_options')
def choice_options(engine, intent, checkpoint, reactor_id, choice_id, context):
    from .needle import option_spec
    return option_spec(choice_id, context, prefix='choice:reed_slip.')


@hook('compile_block')
def compile_row(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'pb': int(numbers['pb']), 'key_mod': int(numbers['key_mod']), 'trigger_owner': BLOCK}]


def conversion_distance(engine, actor, row):
    """Pure base + additive owned evolution quotes, in integer feet.

    Consumers: Reed Slip's route offer and eventual paid receipt. Providers
    must not pay, reserve round uses or mutate state while quoting.
    """
    return 5 + conversion_bonus(engine, actor, 'reed_slip')


def settled_conversion(engine, actor, row, receipt):
    """Publish one paid conversion, including its actual movement and exemption.

    Shared Refined/Perfected round limits were settled immediately after real
    payment, before native movement/OAs. This public primitive receipt records
    the resulting movement; native movement/resource events remain authority.
    """
    note(engine, row['feature_id'], actor,
         f"{actor.display_name} spends {receipt['paid']} Reed Flex on Reed Slip, moving {receipt['moved_ft']} feet. "
         f"Only {engine.state.actors[receipt['exempt_actor_id']].display_name} cannot make opportunity attacks during this slip.",
         **receipt)


@hook('willing_movement_completed')
def during_movement(engine, actor, intent, movement_receipt, starting_resources):
    from .. import granted_movement, target_knowledge
    from .needle import ask, checkpoint_id
    row = next((r for r in engine.typed_passive_rows.get(actor.entity_id, [])
                if r.get('block') == BLOCK), None)
    if row is None:
        return
    if (not conversion_available(engine, actor, SOURCE) or engine._effective_speed(actor) <= 0
            or movement_receipt.source_definition_id == SOURCE or engine.state.terminal_result is not None):
        return
    pool = row['resource_id']
    if min(int(starting_resources.get(pool, 0)), int(actor.resources.get(pool, 0))) < 1:
        return
    feet = conversion_distance(engine, actor, row)
    routes = granted_movement.candidates(engine, actor, feet, intent, SOURCE)
    if not routes:
        return
    # Knowledge-scoped actors only: a choice must never reveal hidden enemies.
    # The mover is never a choice: a creature cannot make an opportunity attack against itself.
    creatures = [other for other in engine.state.actors.values()
                 if other.entity_id != actor.entity_id and other.active
                 and target_knowledge.knowledge(engine, actor, other) is not None]
    if not creatures:
        return
    checkpoint = checkpoint_id(engine, 'reed_slip', actor.entity_id)
    picked = ask(engine, intent, checkpoint, actor, DESTINATION, list(routes), allow_decline=True,
        name='Reed Slip', feature_id=SOURCE, target_id=actor.entity_id,
        labels={key: f"Move to square ({c.destination.x}, {c.destination.y}), {c.destination.z * 5} feet high"
                for key, c in routes.items()},
        prompt=f"Reed Slip: during {actor.display_name}'s movement, spend 1 Reed Flex to move up to {feet} feet farther? Choose a destination; your selected creature cannot make opportunity attacks during this slip.",
        prompt_context={'cost': '1 Reed Flex', 'paying_pool': pool, 'action_name': 'Movement'})
    if not picked:
        return
    hostile_known = any(other.team_id != actor.team_id for other in creatures)
    exempt = ask(engine, intent, checkpoint + ':creature', actor, EXEMPTION,
        [other.entity_id for other in creatures], allow_decline=True,
        name='Reed Slip', feature_id=SOURCE, target_id=actor.entity_id,
        labels={other.entity_id: other.display_name for other in creatures},
        preferred=[other.entity_id for other in creatures if other.team_id != actor.team_id],
        # With no hostile creature known, an automatic seat has nothing worth exempting: it is not automatic,
        # so the AI declines and spends nothing (a player still sees the allies and may choose one).
        automatic=hostile_known, default='first' if hostile_known else 'decline',
        prompt=f"Reed Slip: {actor.display_name} is moving. Choose the one creature that cannot make opportunity attacks during the slip. Other creatures can still attack. Spend 1 Reed Flex only after confirming.",
        prompt_context={'cost': '1 Reed Flex', 'paying_pool': pool, 'action_name': 'Movement'})
    if not exempt:
        return
    route = routes[picked[0]]
    payment_start = len(engine.events)
    engine._spend_resource(actor, pool, 1, SOURCE)
    payment = next(event for event in reversed(engine.events[payment_start:])
                   if event.event_type == 'RESOURCE_SPENT' and event.actor_id == actor.entity_id
                   and event.source_definition_id == SOURCE and event.payload.get('resource_id') == pool)
    bonus = settle_conversion_bonus(engine, actor, 'reed_slip', str(payment.sequence), SOURCE,
        resource_id=pool)
    feet = 5 + bonus
    paid_receipt = {'conversion': 'reed_slip', 'paid': int(payment.payload['amount']),
        'resource_id': pool, 'payment_event_sequence': payment.sequence, 'round': engine.state.round_number,
        'allowance_ft': feet, 'bonus_ft': feet - 5}
    event_start = len(engine.events)
    cost = granted_movement.resolve_path(engine, actor, route.canonical_path, SOURCE,
        feet=feet, intent=intent, ignore_oa_from=(exempt[0],),
        mode=route.metadata.get('movement_mode'))
    actual = next((event for event in reversed(engine.events[event_start:])
                   if event.event_type == 'MOVEMENT_COMMITTED' and event.actor_id == actor.entity_id
                   and event.source_definition_id == SOURCE), None)
    moved = max(0, len(actual.payload.get('path') or ()) - 1) * engine.grid.square_size_ft if actual else 0
    settled_conversion(engine, actor, row, {**paid_receipt,
        'moved_ft': moved, 'movement_cost_ft': cost, 'exempt_actor_id': exempt[0]})
