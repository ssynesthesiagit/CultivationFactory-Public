"""Iron Oath consumers of protected_subjects and the existing Foundation provider.

No declaration, damage generation or Guard payment is implemented here. Those
remain owned by the companion producer. All distances use native 3D geometry.
"""
from . import hook, effect, run_strict
from . import foundation_combat as f
from .needle import ask, checkpoint_id, CHOICE, timed_condition

BOUNDARY = f.feature('oath', 'iron_oath_boundary')
SCAR = f.feature('oath', 'scar_ledger_defense')
FORGING = f.feature('oath', 'shield_body_forging')
PRESSURE = {'forced_movement', 'frightened', 'charmed', 'domination', 'disarm', 'bypass'}
SCAR_BAR = f.P + 'scar_ledger_passage'
SCAR_PENDING = 'iron_scar_pending'   # persisted per-owner Witness receipts awaiting their final roll outcome
FIXED_SPHERES = {'tianxia.sphere.' + name for name in (
    'metal', 'protection', 'guardian', 'shield', 'iron_fist', 'wrestling',
    'athletics', 'karma', 'warleader', 'retribution', 'chains')}


@hook('source_scope_matches')
def printed_fixed_scope(engine, owner, source, power_id, scope, project):
    """Use actual Sphere identity; narrative interpretations stay explicit."""
    if (power_id != f.feature('oath', '').rstrip('.') or scope != 'fixed_scope'
            or f.row(engine, owner, 'oath', 'stand_fast_witness') is None):
        return None
    if project is not None:
        check = project.project_check
        if (FIXED_SPHERES.intersection(check.sphere_ids)
                or check.kind in {'technique_forging', 'foundation_challenge'}
                and check.limitation_kind in {'protected_subject', 'ward'} and check.limitation.strip()):
            return True
        return None
    from .ability_source import sphere_at
    return True if sphere_at(engine, source) in FIXED_SPHERES else None


def oath_context(engine, owner):
    """Read the single declared duty from the companion's public scene contract."""
    from .. import protected_subjects
    from .iron_oath import available, declaration_matches
    if not available(engine, owner):
        return None
    declaration = f.held(owner, 'protected_subject')
    if declaration is None:
        return None
    record_id = declaration.data.get('record_id')
    entry = protected_subjects.duties(engine, owner).get(record_id)
    if (entry is None or not declaration_matches(declaration, *entry)
            or not protected_subjects.defending(engine, owner, record_id)
            or not protected_subjects.resource_available(engine, owner, f.pool('oath'))):
        return None
    fact, defense = entry
    return fact, protected_subjects.position(engine, fact)


def active_boundary(engine, owner):
    """A live Emanation follows its bearer; defense/subject corrections are live."""
    boundary = f.held(owner, 'iron_oath_boundary')
    from .. import protected_subjects as subjects
    from .iron_oath import available, declaration_matches
    if boundary is None or not available(engine, owner, require_resource=False) or f.row(engine, owner, 'oath', 'iron_oath_boundary') is None:
        return None
    record_id = boundary.data.get('record_id')
    entry = subjects.duties(engine, owner).get(record_id)
    if (entry is None or not declaration_matches(boundary, *entry)
            or not subjects.defending(engine, owner, record_id)):
        return None
    fact, _defense = entry
    point = subjects.position(engine, fact)
    # The subject must remain in or adjacent to the 15-foot Emanation.
    return boundary if engine.grid.distance_ft(owner.position, point) <= 20 else None


def boundary_subjects(engine, owner):
    from .. import protected_subjects as subjects
    return {key: fact for key, (fact, _defense) in subjects.duties(engine, owner).items()
            if subjects.defending(engine, owner, key)
            and engine.grid.distance_ft(owner.position, subjects.position(engine, fact)) <= 20}


@hook('foundation_defending')
def additional_boundary_duty(engine, owner):
    return True if active_boundary(engine, owner) else None


@hook('foundation_expression_options')
def expressions(info):
    return [fid for fid in (SCAR, FORGING) if fid in info['owned_ids']] or None


@hook('project_check_access')
def project_access(info):
    return True if f.feature('oath', 'stand_fast_witness') in info['owned_ids'] else None


@hook('compile_actions')
def actions(info):
    if BOUNDARY not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.{BOUNDARY}.{kind}",
        display_name='Iron Oath Boundary', owner_id=info['actor_id'], economy=EconomyKind.BONUS_ACTION,
        resolution_kind='TYPED', target_kind='SELF', costs=((f.pool('oath'), 1), ('resource:core.' + kind, 2)),
        parameters={'boundary_paying_pool': 'resource:core.' + kind, 'typed': {'source': BOUNDARY,
            'numbers': info['numbers'], 'effects': [{'type': 'iron_oath_boundary'}], 'riders': [],
            'duration': {'kind': 'minute', 'amount': 1}}, 'expected_damage': 0})
        for kind in ('qi', 'stamina', 'resonance') if kind in info['pools']]


def boundary_used(engine, owner, *, exclude_transaction=None):
    """Use the actual accepted activation, including a countered paid attempt."""
    return any(event.event_type == 'INTENT_ACCEPTED' and event.actor_id == owner.entity_id
        and event.transaction_id != exclude_transaction
        and (engine.action_catalog.get(event.source_definition_id) is not None)
        and (engine.action_catalog[event.source_definition_id].parameters.get('typed') or {}).get('source') == BOUNDARY
        for event in engine.events)


def boundary_available(engine, owner):
    return (f.row(engine, owner, 'oath', 'iron_oath_boundary') is not None
            and engine.state.current_actor_id == owner.entity_id
            and not boundary_used(engine, owner)
            and oath_context(engine, owner) is not None
            and bool(boundary_subjects(engine, owner)))


@hook('candidate_allowed')
def candidate_allowed(engine, owner, candidate, action):
    if action and (action.parameters.get('typed') or {}).get('source') == BOUNDARY:
        return bool(boundary_available(engine, owner))
    return None


@effect('iron_oath_boundary')
def boundary(ctx, eff):
    pool = ctx.action.parameters.get('boundary_paying_pool')
    transaction = getattr(ctx.engine, '_transaction_id', None)
    accepted = any(event.event_type == 'INTENT_ACCEPTED' and event.actor_id == ctx.actor.entity_id
                   and event.source_definition_id == ctx.source and event.transaction_id == transaction
                   for event in ctx.engine.events)
    if (pool not in {'resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'}
            or f.row(ctx.engine, ctx.actor, 'oath', 'iron_oath_boundary') is None
            or ctx.engine.state.current_actor_id != ctx.actor.entity_id
            or ctx.typed.get('source') != BOUNDARY or not accepted
            or oath_context(ctx.engine, ctx.actor) is None
            or boundary_used(ctx.engine, ctx.actor, exclude_transaction=transaction)):
        raise ValueError('Iron Oath Boundary requires your defended subject, 1 Guarding Iron and 2 Path resource, once per scene.')
    subjects = boundary_subjects(ctx.engine, ctx.actor)
    from .choice_costs import quote
    pick = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'IRON_BOUNDARY_SUBJECT', ctx.actor.entity_id),
        ctx.actor, CHOICE + 'iron_boundary_subject', list(subjects), name='Iron Oath Boundary', feature_id=BOUNDARY,
        labels={key: 'Defend ' + fact.subject_name for key, fact in subjects.items()}, preferred=list(subjects)[:1],
        prompt=f'Iron Oath Boundary costs {quote(ctx.action.costs)} before further reductions. Name one meaningful protected subject inside or adjacent to your 15-foot boundary for 1 minute. Its benefits last only while you actually defend that subject.')
    if not pick:
        return
    fact = subjects[pick[0]]
    from .. import relations
    allies = [a for a in ctx.engine.state.actors.values() if a.active
              and relations.relation(ctx.engine, ctx.actor, a) == relations.ALLY
              and ctx.engine._distance_actor_to_actor(ctx.actor, a) <= 15]
    from ..stealth import sees
    recipients = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'IRON_BOUNDARY_ALLIES', ctx.actor.entity_id),
        ctx.actor, CHOICE + 'iron_boundary_allies', [a.entity_id for a in allies],
        maximum=len(allies), minimum=0, allow_decline=True, name='Iron Oath Boundary', feature_id=BOUNDARY,
        labels={a.entity_id: f'{a.display_name}: gain {f.values(ctx.engine, ctx.actor)[0]} temporary HP' for a in allies},
        preferred=[a.entity_id for a in allies],
        automatic_options=[a.entity_id for a in allies if a is ctx.actor or sees(ctx.engine, ctx.actor, a)],
        prompt='Iron Oath Boundary: choose allies inside 15 feet to gain Proficiency Bonus temporary HP now; temporary HP does not stack.')
    from .effect_durations import round_token
    from ..protected_subjects import duties
    _fact, defense = duties(ctx.engine, ctx.actor)[fact.record_id]
    timed_condition(ctx.engine, ctx.actor, f.P + 'iron_oath_boundary', BOUNDARY, ctx.actor.entity_id,
        round_token(ctx.engine, 10), {'record_id': fact.record_id, 'subject': fact.subject_id,
            'subject_kind': defense.subject_kind,
            'label': f'Iron Oath Boundary: defend {fact.subject_name} within 15 feet for 1 minute; Guard and Witness gain another Proficiency Bonus'})
    for aid in recipients or ():
        ctx.engine._grant_temp_hp(ctx.engine.state.actors[aid], f.values(ctx.engine, ctx.actor)[0], BOUNDARY, ctx.actor.entity_id)


@hook('foundation_guard_bonus')
def guard_bonus(engine, owner, target, group, leaf):
    if (group == 'oath' and leaf == 'iron_oath_guard' and active_boundary(engine, owner)
            and engine._distance_actor_to_actor(owner, target) <= 15):
        return f.values(engine, owner)[0]
    return None


@hook('foundation_roll_bonus')
def witness_bonus(engine, owner, group, leaf, context):
    if group != 'oath' or leaf != 'stand_fast_witness':
        return None
    pb = f.values(engine, owner)[0]
    extra = pb if active_boundary(engine, owner) else 0
    if (f.row(engine, owner, 'oath', 'scar_ledger_defense') is not None
            and f.selected(engine, owner, SCAR)
            and scar_pressure(engine, owner, context)):
        extra += pb
    return extra


@hook('foundation_roll_spent')
def witness_spent(engine, owner, group, leaf, context, roll, bonus):
    if (group == 'oath' and leaf == 'stand_fast_witness'
            and f.row(engine, owner, 'oath', 'scar_ledger_defense') is not None
            and f.selected(engine, owner, SCAR)
            and scar_pressure(engine, owner, context)):
        # A post-roll observer runs before the final result is read. The receipt
        # lives on the paying owner's persisted turn_flags so a save/reload between
        # this roll and its final settlement keeps the passage bar pending.
        source_id = context.get('pressure_source_actor_id') or context.get('source_actor_id')
        if source_id == owner.entity_id:
            source_id = context.get('target_id') if context.get('target_id') != owner.entity_id else None
        owner.turn_flags.setdefault(SCAR_PENDING, {})[roll.roll_id] = [owner.entity_id, source_id, context.get('dc')]


@hook('state_event')
def settle_scar(engine, event):
    # Only CHECK_ROLLED is final here: an opposed check emits it after floors,
    # opposed totals and outcome overrides. SAVE_ROLLED is preliminary (it is
    # emitted before after_save/outcome rewrites), so saves settle in save_final.
    if event.event_type != 'CHECK_ROLLED':
        return
    payload = event.payload
    rolls = [(payload.get('actor') or {}, payload.get('success')),
             (payload.get('target') or {}, not payload['success'] if 'success' in payload else None)]
    for roll, success in rolls:
        settle_scar_roll(engine, roll.get('roll_id'), success)


@hook('save_final')
def scar_save_final(ctx, subject, ability, named, failed):
    """The final save outcome, after rewrites, forced outcomes and opposed overrides."""
    if ctx.save_result is not None:
        settle_scar_roll(ctx.engine, ctx.save_result.roll_id, not failed)
    return None


@hook('repeat_save_final')
def scar_repeat_save_final(engine, resolution):
    """Repeat saves settle after any failed-save rescue; the roll is None for automatic results."""
    if resolution.get('roll') is not None:
        settle_scar_roll(engine, resolution['roll'].roll_id, resolution.get('success') is True)


def pop_scar_receipt(engine, roll_id):
    """Remove and return the persisted receipt for one Witness roll, wherever its owner is."""
    for actor in engine.state.actors.values():
        pending = actor.turn_flags.get(SCAR_PENDING)
        if pending and roll_id in pending:
            receipt = pending.pop(roll_id)
            if not pending:
                actor.turn_flags.pop(SCAR_PENDING, None)
            return receipt
    return None


def settle_scar_roll(engine, roll_id, success):
    """Apply the passage bar once for the Witness roll that paid for Scar-Ledger, if it finally succeeded."""
    receipt = pop_scar_receipt(engine, roll_id)
    if receipt is None or success is not True:
        return
    owner_id, source_id, _dc = receipt
    source, owner = engine.state.actors.get(source_id), engine.state.actors.get(owner_id)
    if source is None or owner is None:
        return
    from .effect_durations import token
    timed_condition(engine, source, SCAR_BAR + '.' + owner_id, SCAR, owner_id,
        token('end', source.entity_id, source.turns_started),
        {'bearer_id': owner_id, 'label': f'Scar-Ledger Defense: cannot willingly pass through {owner.display_name} until this turn ends; teleportation or two sizes larger bypasses this'})


@hook('pass_through_allowed')
def scar_passage(engine, mover, occupant):
    if not any(c.condition_id == SCAR_BAR + '.' + occupant.entity_id for c in mover.conditions.values()):
        return None
    from .effective_size import rank
    if rank(engine, mover, 'act', {'passage'}) < rank(engine, occupant, 'resist', {'passage'}) + 2:
        return False
    return None


@hook('project_check_dc')
def forging_dc(engine, owner, fact):
    from .iron_oath import available
    project = fact.project_check
    spheres = {'tianxia.sphere.' + name for name in
               ('guardian', 'protection', 'shield', 'metal', 'iron_fist', 'karma', 'chains', 'warleader')}
    if (f.row(engine, owner, 'oath', 'shield_body_forging') is not None
            and project.kind in {'technique_forging', 'foundation_challenge'}
            and f.selected(engine, owner, FORGING) and available(engine, owner, require_resource=False) and project.actor_id == owner.entity_id
            and project.limitation_kind != 'none' and project.limitation.strip()
            and spheres.intersection(project.sphere_ids)):
        return -2
    return None


def recorded_pressure(engine, owner, context, *, toward=False):
    """Match subjective purpose to the actual native roll's source and recipient."""
    from ..table_facts import records
    kind = 'save' if context.get('check_kind') == 'save' else context.get('kind')
    intent = getattr(engine, '_active_intent', None)
    bearer_recipient = (context.get('actor_id') == owner.entity_id
        or context.get('target_id') == owner.entity_id
        or (context.get('target_id') is None
            and owner.entity_id in (getattr(intent, 'target_ids', ()) or ())))
    for fact in records(engine, owner).values():
        for pressure in fact.roll_pressures:
            from ..project_checks import owns_source
            if (owns_source(engine, pressure.actor_id, pressure.source_definition_id, fact=fact)
                    and 'project:' + fact.record_id not in (context.get('hazards') or ())):
                continue  # an admitted scene pressure belongs to this actual project
            # An enemy may save against the bearer's own defensive technique
            # while trying to bypass them. That is an actual opposed recipient,
            # with an explicitly bound enemy roller, rather than a different
            # target of a reusable hostile action inheriting the same purpose.
            defensive_opponent = (context.get('source_actor_id') == owner.entity_id
                and context.get('target_id') == context.get('actor_id')
                and pressure.roll_actor_id == context.get('actor_id'))
            if not bearer_recipient and not defensive_opponent:
                continue
            if (pressure.source_definition_id == context.get('source_id')
                    and pressure.actor_id == context.get('source_actor_id')
                    and pressure.target_id == owner.entity_id
                    and (pressure.roll_actor_id is None or pressure.roll_actor_id == context.get('actor_id'))
                    and kind in pressure.kinds
                    and (not toward or pressure.toward_subject)):
                yield fact, pressure


def scar_pressure(engine, owner, context):
    return bool(f.roll_names([*(context.get('named') or ()), *(context.get('hazards') or ())]) & PRESSURE
                or any(set(pressure.categories) & PRESSURE
                       for _fact, pressure in recorded_pressure(engine, owner, context)))


@hook('check_resolution_requested')
def scoped_check_receipt(engine, owner, source):
    if f.row(engine, owner, 'oath', 'stand_fast_witness') is None:
        return None
    # Qualification needs the actual roll frame. Request that general phase
    # for owned Witness actors, then let the post-roll provider decide scope.
    return True


@hook('foundation_roll_eligible')
def witness_eligible(engine, owner, group, leaf, context):
    if group != 'oath' or leaf != 'stand_fast_witness':
        return None
    from .iron_oath import available
    if not available(engine, owner):
        return False
    native = f.roll_names([*(context.get('named') or ()), *(context.get('hazards') or ())])
    if native & PRESSURE and f.hostile(engine.state.actors.get(context.get('source_actor_id')), owner):
        return True
    # A native admitted project roll owns its kind/DC; arbitrary checks cannot
    # become projects merely by naming a hazard.
    from .. import project_checks
    if context.get('check_kind') in {'technique_forging', 'foundation_challenge', 'scene_check'}:
        projects = project_checks.available(engine, owner)
        from ..protected_subjects import source_in_scope
        selected = [key for key in projects if 'project:' + key in (context.get('hazards') or ())]
        return bool(selected) and (any(source_in_scope(engine, owner, context.get('source_id'),
                       f.feature('oath', '').rstrip('.'), 'fixed_scope', project_record_id=key)
                   for key in selected) or any(fact.record_id in selected for fact, _ in recorded_pressure(engine, owner, context)))
    from ..protected_subjects import source_in_scope
    return (source_in_scope(engine, owner, context.get('source_id'), f.feature('oath', '').rstrip('.'), 'fixed_scope')
            or any(True for _fact, _pressure in recorded_pressure(engine, owner, context)))


def relation_enemy(engine, a, b):
    """Live ENEMY relation (pair/team overrides), never a team-roster guess."""
    from .. import relations
    return relations.relation(engine, a, b) == relations.ENEMY


def boundary_pressure(engine, owner, context):
    boundary = active_boundary(engine, owner)
    if boundary is None or owner.turn_flags.get('iron_boundary_round_pressure') == engine.state.round_number:
        return False
    # A recorded purpose that says the pressure is not toward the subject
    # overrides the native categories for this roll.
    if any(fact.record_id == boundary.data['record_id'] and not pressure.toward_subject
           for fact, pressure in recorded_pressure(engine, owner, context)):
        return False
    # Fear or control alone does not say which way it moves; only a sourced record
    # that the pressure is toward the protected subject qualifies.
    return any(fact.record_id == boundary.data['record_id'] and set(pressure.categories) & PRESSURE
               for fact, pressure in recorded_pressure(engine, owner, context, toward=True))


@hook('save_mode')
def boundary_save_mode(engine, owner, ability, dc, source_id, context):
    if boundary_pressure(engine, owner, context):
        return 'ADVANTAGE'
    # Enemy saving throws/checks caused by the bearer need their actual scope,
    # not a guess based on the name of the provoking action.
    for bearer in engine.state.actors.values():
        if relation_enemy(engine, owner, bearer) and boundary_pressure(engine, bearer, context):
            return 'DISADVANTAGE'
    return None


@hook('ability_check_mode')
def boundary_check_mode(engine, roller, ability, skill, against):
    context = engine.d20_context() or {}
    if not context:
        source = getattr(engine, '_active_action_source_id', None)
        action = engine.action_catalog.get(source)
        if action is not None:
            context = {'kind': 'check', 'actor_id': roller.entity_id, 'source_id': source,
                       'source_actor_id': action.owner_id,
                       'target_id': against.entity_id if against is not None else None}
    if context.get('kind') != 'check':
        return None
    for bearer in engine.state.actors.values():
        if relation_enemy(engine, roller, bearer) and boundary_pressure(engine, bearer, context):
            return 'DISADVANTAGE'
    return None


@hook('effect_check_mode')
def boundary_effect_check_mode(ctx, roller, opponent, spec):
    # Typed opposed checks query modes before entering their d20 scope. The
    # public effect checkpoint carries the real source/participants at that
    # phase; do not infer a source from an ability name.
    context = {'kind': 'save' if spec.get('kind') == 'save' else 'check',
        'actor_id': roller.entity_id, 'source_id': ctx.source, 'source_actor_id': ctx.actor.entity_id,
        'target_id': opponent.entity_id if opponent is not None else None}
    if any(relation_enemy(ctx.engine, roller, bearer) and boundary_pressure(ctx.engine, bearer, context)
           for bearer in ctx.engine.state.actors.values()):
        return 'DISADVANTAGE'
    return None


@hook('attack_roll_modes')
def boundary_attack_mode(engine, roller, target):
    context = engine.d20_context() or {}
    scoped = getattr(engine, '_iron_oath_attack_source', None)
    source_id = (scoped[2] if scoped and scoped[:2] == (roller.entity_id, target.entity_id)
                 else context.get('source_id') or getattr(engine, '_active_action_source_id', None))
    context = {**context, 'kind': 'attack', 'source_id': source_id,
               'actor_id': roller.entity_id, 'source_actor_id': roller.entity_id, 'target_id': target.entity_id}
    if relation_enemy(engine, roller, target) and boundary_pressure(engine, target, context):
        return ['DISADVANTAGE']
    return None


@hook('attack_resolution_scope')
def boundary_attack_source_scope(engine, actor, target, spec, intent):
    if not any(f.held(bearer, 'iron_oath_boundary') for bearer in engine.state.actors.values()):
        return None
    current = engine.d20_context() or {}
    source = (current.get('source_id') if current.get('kind') == 'attack'
              and current.get('actor_id') == actor.entity_id and current.get('target_id') == target.entity_id
              else spec.get('source_definition_id'))
    if source is None:
        action = engine.action_catalog.get(getattr(engine, '_active_action_source_id', None))
        source = action.source_definition_id if action is not None and action.owner_id == actor.entity_id else None
    if source is None:
        return None
    from contextlib import contextmanager
    @contextmanager
    def scope():
        old = getattr(engine, '_iron_oath_attack_source', None)
        engine._iron_oath_attack_source = (actor.entity_id, target.entity_id, source)
        try:
            yield
        finally:
            engine._iron_oath_attack_source = old
    return scope()


@hook('d20_bonus')
def consume_boundary_pressure(engine, roll, intent):
    context = engine.d20_context(roll) or {}
    roller = engine.state.actors.get(roll.actor_id)
    for bearer in engine.state.actors.values():
        if (roller is bearer or relation_enemy(engine, roller, bearer)) and boundary_pressure(engine, bearer, context):
            bearer.turn_flags['iron_boundary_round_pressure'] = engine.state.round_number
    return None


@hook('before_d20')
def clear_unsettled_scar(engine, request, intent):
    # A paused intent may be retried with the opposite decision. Clear only its
    # reused deterministic roll ID before the new draw; nested parent receipts
    # use different counters and remain intact.
    pop_scar_receipt(engine, f'roll:{engine.roller.counter:08d}')
    return None


@hook('state_event')
def boundary_abandoned(engine, event):
    if event.event_type != 'TABLE_FACT_RECORDED':
        return
    for owner in engine.state.actors.values():
        boundary = f.held(owner, 'iron_oath_boundary')
        if boundary is None:
            continue
        fact = event.payload.get('fact') or {}
        if not fact.get('active', True):
            continue
        if fact.get('record_id') != boundary.data.get('record_id'):
            continue
        if fact.get('subject_id') != boundary.data.get('subject'):
            continue
        if any(defense['defender_id'] == owner.entity_id and defense['status'] == 'abandoned'
               and defense['subject_kind'] == boundary.data.get('subject_kind')
               for defense in fact.get('defenses', [])):
            engine._remove_condition(owner, boundary.condition_id, BOUNDARY)
            # Broken Guard has no printed numerical penalty. Preserve the
            # severity for campaign recovery without inventing suppression.
            timed_condition(engine, owner, f.P + 'broken_guard_strain', BOUNDARY, owner.entity_id,
                'UNTIL_REMOVED', {'severity': 1, 'label': 'Broken Guard Strain, Severity 1: willingly abandoned your protected subject. No numerical penalty is defined. Recovery may include apology, restitution, a renewed oath, protecting without control, accepting judgment, or successfully guarding the harmed party.'})
