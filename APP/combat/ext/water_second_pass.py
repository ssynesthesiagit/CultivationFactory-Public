"""Owned Water reaction, voluntary self-Soaked state and chosen Lash movement.

Rest uses follow the table's per-fight convention. Consent and payments are
transactional; AI protects its own side using current perception. Existing
mark/declaration/turn-boundary hooks suffice; no saved catalog is rewritten.
"""
from . import effect, hook, note, ai_controlled, run
from .needle import CHOICE, ask, checkpoint_id
from .passive_rows import row_of
from .choice_prompt import action_context

BLOCK = 'water_second_pass'
STILL = 'TAL_WATER_STILL_SURFACE_METHOD'
TIDAL = 'insight.tidal-body'
LASH = 'WATER_BASE_WATER_LASH'
USES = 'resource:uses.water_still_surface'
SOAKED = 'condition:typed.mark.soaked.'


@hook('compile_block')
def compile_owned(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'kind': spec['kind'], 'numbers': dict(numbers),
                 **({'player_outcome': spec['player_outcome']} if spec.get('player_outcome') else {})}]
    return None


@hook('compile_resources')
def free_ripples(info):
    if STILL not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ResourceDefinition
    pb = int(info['pb'])
    return [ResourceDefinition(resource_id=USES, initial=pb, maximum=pb)]


@effect('water_second_pass_owned')
def owned_marker(ctx, eff):
    """Typed ownership contract; the feature block resolves passive behavior."""
    return


def mist_basins(engine, owner):
    """Actual owned Mist Basin volumes, including dense Mist Veil variants."""
    for zone in engine.state.zones.values():
        action = engine.action_catalog.get(zone.source_definition_id)
        typed = (action.parameters.get('typed') or {}) if action else {}
        if (zone.active and zone.owner_id == owner.entity_id
                and typed.get('source') == 'WATER_BASE_SHAPE_CURRENT'
                and zone.trigger_profile.get('obscured') in {'light', 'heavy'}):
            yield zone


@hook('before_attack')
def ripple(engine, attacker, defender, intent, context):
    from .. import senses
    from ..typed_executor import condition_rules
    from .cp_pools import of
    from .choice_costs import payable
    from ..paid_relocation import activation
    action = context.get('action') or engine.action_catalog.get(context.get('source_id'))
    parameters = action.parameters if action else {}
    # Missing general declaration metadata means an ordinary sight-based attack.
    if ((context.get('effect') or {}).get('requires_sight') is False or parameters.get('requires_sight') is False
            or senses.perceives_without_sight(engine, attacker, defender)):
        return None
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        row = row_of(engine, owner.entity_id, BLOCK, 'still_surface')
        if (row is None or not owner.active or owner.life_state is not None or not owner.reaction_available
                or any(r.get('no_reactions') or r.get('no_actions') for r in condition_rules(owner))):
            continue
        if ai_controlled(engine, owner) and (defender.team_id != owner.team_id or attacker.team_id == owner.team_id
                or not senses.perceives(engine, owner, attacker) or not senses.perceives(engine, owner, defender)):
            continue
        from ..action_geometry import volume as activation_volume
        from ..space import point as cell_point
        attack_volume = set(activation_volume(engine, attacker))
        eligible = [z for z in mist_basins(engine, owner)
                    if engine._footprint_intersects(defender, z.affected_cells)
                    and not (attack_volume & {cell_point(cell) for cell in z.affected_cells})]
        # A dense-copy query asks whether a sense pierces mist, rather than
        # whether lightly obscured mist currently blocks ordinary vision.
        if not eligible or all(senses.pierces(engine, z.model_copy(update={
                'trigger_profile': {**z.trigger_profile, 'obscured': 'heavy'}}), attacker, defender) for z in eligible):
            continue
        payment = payable(owner, of(owner, at_least=1) or '', 1)
        if payment and any(r is False for r in run('cost_available', engine, owner, payment.pool, 1, {})):
            payment = None
        options, labels = [], {}
        if owner.resources.get(USES, 0) > 0:
            options.append('free')
            labels['free'] = f'Spend your Reaction and one free use ({owner.resources[USES]} remaining until a Long Rest)'
        if payment:
            options.append('cp')
            labels['cp'] = f'Spend your Reaction and {payment.quote()}; keep your free uses'
        if not options:
            continue
        chosen = ask(engine, intent, checkpoint_id(engine, 'WATER_STILL_SURFACE', owner.entity_id,
                     attacker.entity_id, defender.entity_id, context.get('source_id'), context.get('attack_index', 1)),
                     owner, CHOICE + 'water_still_surface', options, labels=labels, allow_decline=True,
                     name='Still Surface Method', feature_id=STILL, target_id=defender.entity_id,
                     prompt_context={**action_context(engine, attacker, str(context.get('source_id') or ''), defender, action=action),
                                     'cost': 'Reaction; choose a free use or pay 1 CP'},
                     prompt=f'Still Surface Method: {attacker.display_name} uses {action.display_name if action else "an attack"} '
                            f'to attack {defender.display_name} inside your Mist Basin '
                            'from outside it. Spend your Reaction to give this attack Disadvantage? Choose how to pay below.')
        if not chosen:
            continue
        with activation(engine, owner, STILL):
            if chosen[0] == 'free':
                engine._spend_resource(owner, USES, 1, STILL)
            else:
                payment.pay(engine, owner, STILL)
            owner.reaction_available = False
            engine._append_event('REACTION_RESOLVED', STILL, actor_id=owner.entity_id,
                target_ids=(defender.entity_id,), payload={'checkpoint': 'ATTACK_DECLARED', 'attack_source_id': context.get('source_id'),
                    'attack_index': context.get('attack_index', 1), 'mode': 'DISADVANTAGE', 'payment': chosen[0]})
            note(engine, STILL, owner, f'Still Surface Method gives {attacker.display_name} Disadvantage on this attack against {defender.display_name}.', (defender,))
        return {'mode': 'DISADVANTAGE'}
    return None


@hook('mark_apply')
def keep_self_soaked(ctx, eff, subject, expires, data):
    if (str(eff.get('mark') or '').lower() != 'soaked' or subject is not ctx.actor
            or not str(ctx.typed.get('source') or '').startswith(('WATER_BASE_', 'TAL_WATER_'))
            or row_of(ctx.engine, subject.entity_id, BLOCK, 'tidal_body') is None):
        return None
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'WATER_TIDAL_BODY', subject.entity_id, ctx.source),
                 subject, CHOICE + 'water_tidal_body', ['keep'], allow_decline=True, name='Tidal Body', feature_id=TIDAL,
                 target_id=subject.entity_id, labels={'keep': 'Stay willingly Soaked until your next turn starts; gain Temporary HP equal to your Proficiency Bonus then'},
                 prompt_context=action_context(ctx.engine, ctx.actor, ctx.action.source_definition_id, subject, action=ctx.action),
                 prompt=f'Tidal Body: your own Water effect, {ctx.action.display_name}, makes you Soaked. '
                        'Keep it until the start of your next turn '
                        'and gain Temporary HP equal to your Proficiency Bonus when that turn starts?')
    if not chosen:
        return None
    from ..typed_executor import mark_condition_id
    from .effect_durations import token
    condition = mark_condition_id('Soaked', subject.entity_id)
    ctx.engine._remove_condition(subject, condition, ctx.source)
    ctx.engine._apply_condition(subject, condition, ctx.source, subject.entity_id,
        expires_on=token('start', subject.entity_id, subject.turns_started + 1),
        data={'water_tidal_body': True, 'next_start': subject.turns_started + 1,
              'label': 'Willingly Soaked: gain Temporary HP equal to your Proficiency Bonus at the start of your next turn, then this Soaked state ends'})
    from . import run_strict
    run_strict('mark_applied', ctx, 'Soaked', subject)
    return True


@hook('turn_boundary_start')
def tidal_hp(engine, actor):
    row = row_of(engine, actor.entity_id, BLOCK, 'tidal_body')
    if row is None or not actor.active:
        return
    if any(c.condition_id.startswith(SOAKED) and c.source_actor_id == actor.entity_id
           and c.data.get('water_tidal_body') and c.data.get('next_start') == actor.turns_started
           for c in actor.conditions.values()):
        engine._grant_temp_hp(actor, int(row['numbers']['pb']), TIDAL, actor.entity_id)


@effect('water_lash_shift')
def lash_shift(ctx, eff):
    if ctx.target is None or not ctx.target.active:
        return
    from ..target_knowledge import located
    if ai_controlled(ctx.engine, ctx.actor) and not located(ctx.engine, ctx.actor, ctx.target):
        return
    from .water_defenses import shield_routes
    from .. import movement_paths
    routes = {key: path for key, path in shield_routes(ctx.engine, ctx.target).items() if len(path) == 2}
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'WATER_LASH_SHIFT', ctx.target.entity_id, ctx.source),
                 ctx.actor, CHOICE + 'water_lash_shift', list(routes), allow_decline=True, name='Water Lash movement',
                 feature_id=LASH, target_id=ctx.target.entity_id,
                 labels={key: f'Move {ctx.target.display_name} 5 feet to square {path[-1].x},{path[-1].y}, {path[-1].z*5} feet high'
                         for key, path in routes.items()},
                 prompt=f'Water Lash hit {ctx.target.display_name}, which was already Soaked. Move it 5 feet to a legal space? '
                        'This forced movement spends no normal movement and provokes no Opportunity Attacks.')
    if chosen:
        movement_paths.resolve(ctx.engine, ctx.target, routes[chosen[0]], ctx.source, kind='forced', feet=5,
                               intent=ctx.intent, provokes=False, source_actor_id=ctx.actor.entity_id, ctx=ctx)

# Abyssal Pressure Seal owns only its activation and its failed-save gate.
ABYSSAL = 'TAL_WATER_ABYSSAL_PRESSURE_SEAL'
WHIRLPOOL = 'TAL_WATER_WHIRLPOOL_PRISON'
COURT = 'TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'
PRESSURE = 'condition:typed.mark.drowning_pressure.'
SEAL_GATE = 'condition:typed.abyssal_pressure_seal.'


def seal_source_action(engine, source):
    """Resolve a condition's catalog producer, including native zone trigger suffixes.

    A passive renewal (``passive:<feature id>``, e.g. Whirlpool Prison's restraint
    renewed at turn end) has no catalog action; its feature id is the producer
    identity, so it resolves to a typed record carrying that modifier id.
    """
    if source.startswith('passive:'):
        from types import SimpleNamespace
        return SimpleNamespace(parameters={'typed': {'modifier': {'id': source[len('passive:'):]}}})
    key = max((key for key in engine.action_catalog if source == key or source.startswith(key + ':')
               or source.startswith(key + '#')), key=len, default='')
    return engine.action_catalog.get(key)


def seal_qualifies(engine, owner, target):
    """Exact existing producer facts; Court is the caster's own active emanation.

    Whirlpool/Drowning need not belong to this caster (the record says 'by' and
    'affected by'); only Court says 'your'. Unrelated Restrained never qualifies.
    """
    from ..typed_executor import area_cells
    from .states import active
    for condition in target.conditions.values():
        action = seal_source_action(engine, condition.source_definition_id)
        typed = (action.parameters.get('typed') or {}) if action else {}
        modifier = (typed.get('modifier') or {}).get('id') or ''
        if (condition.condition_id == 'condition:typed.restrained'
                and WHIRLPOOL in modifier.split('+')):
            return True
        if condition.condition_id.startswith(PRESSURE) and str(typed.get('sphere') or '') == 'tianxia.sphere.water':
            return True
    court = active(engine, owner, 'court_of_endless_tide')
    if court is None or court.source_actor_id != owner.entity_id:
        return False
    action = seal_source_action(engine, court.source_definition_id)
    typed = (action.parameters.get('typed') or {}) if action else {}
    if typed.get('source') != COURT:
        return False
    area = typed.get('area') or {}
    if not area.get('size_ft'):
        return False
    cells = area_cells(engine, owner.position, owner.position, area, include_altitude=True)
    return engine._footprint_intersects(target, cells)


@hook('compile_action')
def seal_harmful_action(action, info):
    if (((getattr(action, 'parameters', None) or {}).get('typed')) or {}).get('source') == ABYSSAL:
        return action.model_copy(update={'parameters': {**action.parameters, 'harmful': True}})
    return None


@hook('target_eligibility')
def seal_target(engine, actor, target, action):
    if (((getattr(action, 'parameters', None) or {}).get('typed')) or {}).get('source') != ABYSSAL:
        return None
    return seal_qualifies(engine, actor, target)


@effect('water_abyssal_pressure_seal')
def seal_spatial_state(ctx, eff):
    from ..typed_executor import effect_expiry
    if ctx.target is None or ctx.typed.get('source') != ABYSSAL:
        return
    ctx.engine._apply_condition(ctx.target, SEAL_GATE + ctx.actor.entity_id, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, eff, ctx.target, condition=True),
        data={'abyssal_pressure_seal': True, 'dc': int(ctx.numbers['save_dc']),
              'label': 'Abyssal Pressure Seal: before teleporting, flying or spatial travel, succeed on a Water check against the sealer’s Cultivation Save DC; ends at the end of their next turn'})


def seal_attempt(engine, subject, intent, source):
    """One owned general gate, consumed by declarations, flight steps and subject teleports.

    Reads timed evented seal conditions only. No check flag or caller-owned
    permission is trusted. Each attempt rolls the traveller's own sphere check
    against every sealer's frozen DC. No seal means no roll/event/state change.
    """
    from .ability_source import cultivation_check, numbers_of
    # Event indexes already answering a seal in this call. Two sealers can share one source id
    # (two Water Courts), so each seal reuses only a roll against its own DC that no other seal used.
    used = set()
    for condition in sorted(subject.conditions.values(), key=lambda c: c.condition_id):
        if not condition.condition_id.startswith(SEAL_GATE) or not condition.data.get('abyssal_pressure_seal'):
            continue
        dc = int(condition.data['dc'])
        # Reuse only a real Water roll in this accepted intent, never a submitted flag.
        reused = None
        for index in range(len(engine.events) - 1, -1, -1):
            event = engine.events[index]
            if event.event_type == 'INTENT_ACCEPTED':
                break
            if (index not in used and event.event_type == 'CHECK_ROLLED' and event.actor_id == subject.entity_id
                    and event.source_definition_id == condition.source_definition_id
                    and event.payload.get('check') == 'Water Check' and int(event.payload.get('dc') or -1) == dc):
                reused = index
                break
        if reused is not None:
            used.add(reused)
            if not engine.events[reused].payload.get('success'):
                return False
            continue
        start = len(engine.events)
        passed = cultivation_check(engine, subject, numbers_of(engine, subject), dc,
                                   condition.source_definition_id, 'Water Check')
        used.update(range(start, len(engine.events)))
        if not passed:
            note(engine, condition.source_definition_id, subject,
                 f'Abyssal Pressure Seal stops {subject.display_name} from using {source}: the Water check failed.', (subject,))
            return False
    return True


def seal_travel_effects(rows):
    """Classify executable transport rows, never an arbitrary intent check flag."""
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get('applies_to') in (None, 'self') and (row.get('type') in {'teleport', 'general_flight'} or (row.get('type') == 'movement' and row.get('mode') in {'teleport', 'fly', 'planar', 'spatial'})):
            return True
        # Conditional hits/saves and optional follow-ups are not yet attempts
        # to travel. Their actual subject teleport/flight effect reaches the
        # same gate when selected; do not cancel an unrelated parent attack.
    return False


@hook('technique_declared')
def seal_travel_declaration(engine, user, action, candidate, intent):
    typed = (action.parameters or {}).get('typed') or {}
    if not seal_travel_effects(typed.get('effects') or []):
        return None
    if not seal_attempt(engine, user, intent, action.display_name):
        return {'source_id': ABYSSAL, 'label': 'Abyssal Pressure Seal: Water check failed; travel and payment prevented',
                'cancel': True, 'spend_activation': False}
    return None


@hook('movement_attempt')
def seal_flight_attempt(engine, mover, previous, nxt, intent):
    from ..movement_steps import context
    if context(engine, mover).get('mode') != 'fly':
        return None
    if not seal_attempt(engine, mover, intent, 'flight'):
        return {'stop': True, 'source_id': ABYSSAL, 'label': 'Abyssal Pressure Seal stops flight'}
    return None


@hook('teleport_context_check')
def seal_subject_teleport(engine, subject, start, destination, movement_context):
    # The printed trigger is the creature attempting travel. Forced hostile
    # displacement is not its own attempt. Willing passengers roll personally.
    if movement_context != 'WILLING':
        return None
    return seal_attempt(engine, subject, None, 'teleportation')


@hook('effect_allowed')
def seal_nested_flight(ctx, eff):
    if eff.get('type') == 'general_flight' and eff.get('applies_to') == 'self':
        return seal_attempt(ctx.engine, ctx.actor, ctx.intent, ctx.action.display_name)
    return None
