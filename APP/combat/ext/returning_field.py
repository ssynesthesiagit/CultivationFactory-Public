"""Origin-Spirit Returning Field: settled Dew receipts, never activation grants.

The existing native zone owns movement, lifetime and persistence. Deferred
choices use rollback-enrolled activation queues; only committed primitive
resource/HP events and the pressure clock survive a save or replay.
"""
from . import hook
from .ability_source import mechanic_at, source_label
from .needle import ask, checkpoint_id, option_spec
from ..paid_relocation import preserve_pending
from ..relations import relation, ALLY, ENEMY

FIELD = 'foundation.origin_spirit_body_v0_2B.perfected_origin_spirit_returning_field'
DEW = 'resource:foundation.spirit_source_dew'
CHOICE = 'choice:returning_field.'
PENDING = '_returning_field_pending'
SCOPES = {'drain', 'hostile_drain', 'backlash', 'curse', 'cursed', 'curse_pressure',
          'frightened', 'fear_pressure', 'spiritual_exhaustion'}


def fields(engine):
    from ..zones import typed_zones
    return [z for z in typed_zones(engine) if mechanic_at(engine, z.source_definition_id) == FIELD]


def in_field(engine, subject, zone):
    from ..spatial_areas import zone_contains
    # Suppression removes stored columns; volume membership still checks height
    # and actual walls rather than replacing the emanation with a distance test.
    return (zone_contains(engine, subject, zone) and
            any((x, y) in {(p.x, p.y) for p in zone.affected_cells}
                for x, y, _ in engine._actor_volume(subject)))


@hook('choice_reactors')
def reactors(engine):
    return tuple(z.owner_id for z in fields(engine))


@hook('choice_options')
def options(engine, intent, checkpoint, reactor_id, choice_id, context):
    return option_spec(choice_id, context, CHOICE)


def enqueue(engine, receipt):
    preserve_pending(engine, PENDING)
    engine.__dict__.setdefault(PENDING, []).append(receipt)


def pressure_success(engine, subject, source_actor, source, named):
    """Queue only a sealed allied success against a named hostile consequence."""
    from .source_categories import categories
    tags = {str(t).lower().removeprefix('category:') for t in named}
    tags.update(categories(engine.action_catalog.get(source)))
    if not tags.intersection(SCOPES) or source_actor is None or relation(engine, source_actor, subject) != ENEMY:
        return
    for zone in fields(engine):
        owner = engine.state.actors[zone.owner_id]
        if (subject.entity_id != owner.entity_id and relation(engine, subject, owner) == ALLY
                and in_field(engine, subject, zone)):
            enqueue(engine, {'kind': 'pressure', 'owner': owner.entity_id,
                             'subject': subject.entity_id, 'source': source,
                             'round': engine.state.round_number, 'owner_turn': owner.turns_started,
                             'sequence': engine.state.event_sequence})


@hook('save_final')
def successful_save(ctx, subject, ability, named, failed):
    if not failed:
        pressure_success(ctx.engine, subject, ctx.actor, ctx.source, named)


@hook('repeat_save_final')
def successful_repeat(engine, resolution):
    if resolution['success']:
        pressure_success(engine, engine.state.actors[resolution['holder_id']],
                         engine.state.actors.get(resolution['source_actor_id']),
                         resolution['source_definition_id'],
                         [*resolution['named'], *resolution['source_categories']])


@hook('opposed_check_final')
def successful_check(ctx, target, result, actor_spec, target_spec, failure_effects, success_effects):
    if target_spec.get('kind') != 'cultivation' or result.success:
        return
    # The native resolver supplies the consequences this defender resisted.
    # Only printed condition/category facts qualify; unknown pressure is unknown.
    def facts(rows):
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get('type') == 'condition':
                yield str(row.get('condition') or '').removeprefix('condition:')
            yield from row.get('save_categories') or []
            for value in row.values():
                if isinstance(value, list) and any(isinstance(v, dict) for v in value):
                    yield from facts(value)
    pressure_success(ctx.engine, target, ctx.actor, ctx.source, facts(failure_effects))


@hook('event', nested=True)
def dew_receipt(engine, event_type, kwargs):
    payload = kwargs.get('payload') or {}
    if payload.get('resource_id') != DEW:
        return
    if event_type == 'RESOURCE_GAINED':
        if int(payload.get('gained') or 0) <= 0:
            return
        # Refunds and transfers are not generation. The native pressure producer
        # names the compiled generation row in its actual resource receipt.
        rows = engine.typed_passive_rows.get(kwargs.get('actor_id'), [])
        if not any(r.get('block') == 'generate' and r.get('resource_id') == DEW
                   and kwargs.get('source_definition_id') == 'passive:' + str(r.get('feature_id'))
                   for r in rows):
            return
    elif event_type == 'RESOURCE_SPENT':
        # Expiry is removal, not a printed spend opportunity.
        if int(payload.get('amount') or 0) <= 0 or kwargs.get('source_definition_id') == 'passive:resource_clock.expired':
            return
    else:
        return
    owner_id = kwargs.get('actor_id')
    for zone in fields(engine):
        if zone.owner_id != owner_id:
            continue
        owner = engine.state.actors[owner_id]
        allies = [a.entity_id for a in engine.state.actors.values()
                  if a.entity_id != owner_id and relation(engine, a, owner) == ALLY and a.active
                  and in_field(engine, a, zone)]
        if allies:
            enqueue(engine, {'kind': 'grant', 'owner': owner_id, 'allies': allies,
                             'source': kwargs.get('source_definition_id'),
                             'sequence': engine.state.event_sequence})


@hook('intent_settled')
def settle(engine, actor, candidate, intent):
    # A complete event resolves before it grants Dew/HP. In particular a save
    # cannot spend the point its own success will generate.
    if not engine.__dict__.get(PENDING):
        return
    preserve_pending(engine, PENDING)
    pending = engine.__dict__.setdefault(PENDING, [])
    while pending:
        receipt = pending.pop(0)
        owner = engine.state.actors[receipt['owner']]
        if receipt['kind'] == 'pressure':
            from .. import pressure
            entry = (owner.turn_flags.get(pressure.CLOCK) or {}).get(DEW) or {}
            if (not owner.active or owner.current_hp <= 0 or int(owner.resources.get(DEW) or 0) >= 1
                    or entry.get('round') == receipt['round']):
                continue
            subject = engine.state.actors[receipt['subject']]
            trigger = source_label(engine, receipt['source']) or 'the hostile pressure'
            selected = ask(engine, None, checkpoint_id(engine, 'RETURNING_FIELD_GENERATION',
                           owner.entity_id, receipt['sequence']), owner, CHOICE + 'generate', ['generate'],
                           labels={'generate': 'Gain 1 Spirit-Source Dew (maximum 1; expires at the end of your next turn)'},
                           allow_decline=True, feature_id=FIELD, name='Origin-Spirit Returning Field',
                           target_id=subject.entity_id,
                           prompt=f'Origin-Spirit Returning Field — {subject.display_name} resisted {trigger}: '
                                  'gain 1 Spirit-Source Dew after this event? Once per round; '
                                  'it cannot pay for this event. No additional action or resource cost. '
                                  'Dew pays for your Foundation support and protection abilities on later events.')
            if selected:
                pressure.generate(engine, owner, 'foundations3_spirit', trigger_round=receipt['round'],
                                  trigger_owner_turn=receipt['owner_turn'])
            continue
        allies = [engine.state.actors[aid] for aid in receipt['allies']]
        ids = [a.entity_id for a in allies]
        trigger = source_label(engine, receipt['source']) or 'the completed Dew event'
        selected = ask(engine, None, checkpoint_id(engine, 'RETURNING_FIELD', owner.entity_id,
                       receipt['sequence']), owner, CHOICE + 'ally', ids,
                       labels={a.entity_id: f'{a.display_name}: gain {owner.proficiency_bonus} temporary Hit Points'
                               for a in allies},
                       preferred=sorted(ids, key=lambda aid: engine.state.actors[aid].temporary_hp),
                       feature_id=FIELD, name='Origin-Spirit Returning Field',
                       prompt=f'Origin-Spirit Returning Field — {trigger}: choose one ally in the field '
                              f'to gain {owner.proficiency_bonus} temporary Hit Points. No additional cost.')
        if selected:
            engine._grant_temp_hp(engine.state.actors[selected[0]], int(owner.proficiency_bonus),
                                  FIELD, owner.entity_id)


@hook('turn_effects_settled')
def settle_turn_effects(engine, actor):
    settle(engine, actor, None, getattr(engine, '_active_intent', None))
