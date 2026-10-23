"""Source-specific Iron Oath consumers of the public protected_subjects contract.

Foundation combat keeps the single existing declaration, Guard and generation
providers. This module supplies their actual-duty qualification and Oath-Mark
damage riders. External meaning comes only from owner-recorded scene inputs.

These qualification helpers are shared with two consumers rather than copied:
foundation_combat (its single declaration, Guard and generation providers read
available/defending/declare/attack_or_technique here) and iron_oath_consumers
(the Boundary, Witness and Scar rows read available/declaration_matches). Keep
the one copy here; a new Iron Oath row calls these names instead of repeating
the owned-row, resource and recorded-duty checks.
"""
from . import hook
from . import foundation_combat as f
from .needle import ask, checkpoint_id, CHOICE, timed_condition
from .. import protected_subjects as subjects

POWER = 'foundation.iron_oath_skin_v0_2B'
MARK = POWER + '.oath_mark_strike'
FRAME = POWER + '.oath_skin_frame'


@hook('foundation_refined_expression_policy')
def refined_policy(foundation_id):
    if foundation_id == f.GROUPS['oath'][0]:
        # Same Foundation's original source: choose two Refined expressions.
        return {'minimum': 2, 'maximum': 2, 'allowed': [f.feature('oath', leaf) for leaf in
            ('iron_interposition', 'oath_skin_mantle', 'scar_ledger_defense', 'shield_body_forging')]}


@hook('foundation_attainment_requirements')
def integration_requirements(sheet, request):
    if request.foundation_id == f.GROUPS['oath'][0] and request.stage == 'Integrated':
        if len(request.requirements_met) < 3:
            raise ValueError('Integrate Iron Oath Skin requires three completed source-defined stabilizations.')


def available(engine, actor, *, require_resource=True):
    if FRAME + ':severance' in actor.maximum_hp_adjustments:
        return False  # A withdrawn observation cannot undo committed story severance.
    state = subjects.power_states(engine, actor).get(POWER)
    power_available = state is None or state['state'] == 'available' or state.get('scope') == 'resources'
    return power_available and (not require_resource or subjects.resource_available(engine, actor, f.pool('oath')))


@hook('foundation_attainment_allowed')
def attainment_available(engine, actor, foundation_id):
    return available(engine, actor, require_resource=False) if foundation_id == f.GROUPS['oath'][0] else None


def defending(engine, actor):
    declaration = f.held(actor, 'protected_subject')
    from . import run_strict
    entry = subjects.duties(engine, actor).get(declaration.data.get('record_id')) if declaration else None
    return ((entry is not None and declaration_matches(declaration, *entry)
             and subjects.defending(engine, actor, declaration.data.get('record_id')))
            or any(run_strict('foundation_defending', engine, actor)))


def declaration_matches(declaration, fact, defense):
    """Corrections may change defense facts, but cannot rename the player's oath."""
    return (declaration.data.get('subject') == fact.subject_id
            and declaration.data.get('subject_kind') == defense.subject_kind)


def declaration_options(engine, actor):
    if f.row(engine, actor, 'oath', 'declare_protected_subject') is None or not available(engine, actor, require_resource=False):
        return {}
    previous = f.held(actor, 'protected_subject')
    return {key: entry for key, entry in subjects.duties(engine, actor).items()
            if subjects.declaration_open(engine, actor, *entry)
            and (previous is None or previous.data.get('record_id') != key
                 or not declaration_matches(previous, *entry))}


def declare(ctx, *, options=None, triggering_action=None):
    options = declaration_options(ctx.engine, ctx.actor) if options is None else options
    if not options:
        return
    # IDs identify facts rather than claiming creature identity for doors/duties.
    pick = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'OATH_SUBJECT', ctx.actor.entity_id), ctx.actor,
        CHOICE + 'foundation_subject', list(options), allow_decline=True,
        name='Declare Protected Subject', feature_id=POWER + '.declare_protected_subject',
        labels={key: 'Defend ' + fact.subject_name for key, (fact, _) in options.items()},
        preferred=list(options), automatic_options=list(options),
        prompt=(f'Before {triggering_action}, ' if triggering_action else '') +
               'Declare Protected Subject: name one meaningful ally, object, doorway, warded place, helpless creature or duty. '
               'This costs no action. Iron Oath works only while you actually defend that subject; the GM may reject artificial duties.')
    if pick:
        key = pick[0]
        fact, defense = options[key]
        timed_condition(ctx.engine, ctx.actor, f.P + 'protected_subject', ctx.source, ctx.actor.entity_id, 'UNTIL_REMOVED',
            {'record_id': key, 'subject': fact.subject_id, 'subject_kind': defense.subject_kind,
             'label': 'Iron Oath: defending ' + fact.subject_name})


@hook('state_event')
def off_turn_declaration(engine, event):
    """Offer a newly appeared duty before another actor's actual native intent.

    Fact authoring never answers the player's decision. The next native intent
    owns the ordinary resumable choice transport, even on an AI actor's turn.
    A declined opportunity is remembered without disabling the legal button.
    """
    if event.event_type != 'INTENT_ACCEPTED':
        return
    intent = getattr(engine, '_active_intent', None)
    if intent is None or intent.table_fact is not None:
        return
    triggering = engine.action_catalog.get(event.source_definition_id)
    if triggering is None:
        return
    from ..typed_executor import Context
    from ..target_knowledge import can_see
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if (owner.entity_id == event.actor_id or not owner.active
                or f.row(engine, owner, 'oath', 'declare_protected_subject') is None):
            continue
        options = declaration_options(engine, owner)
        if not options:
            continue
        source = engine.state.actors.get(event.actor_id)
        if source is not None and owner.entity_id not in event.target_ids and not can_see(engine, owner, source):
            continue
        previous = f.held(owner, 'protected_subject')
        offered = owner.turn_flags.get('iron_oath_round_declaration_offers') or {}
        first = {}
        for recorded in engine.events:
            if recorded.event_type == 'TABLE_FACT_RECORDED':
                fact = recorded.payload['fact']
                for defense in fact.get('defenses', []):
                    if defense['defender_id'] == owner.entity_id:
                        first.setdefault((fact['record_id'], defense['appeared_round']), recorded.sequence)
        options = {key: entry for key, entry in options.items()
                   if offered.get(key) != entry[1].appeared_round
                   and (previous is None or first.get((key, entry[1].appeared_round), 0) > previous.applied_sequence)}
        if not options:
            continue
        action = next((a for a in engine.action_catalog.values() if a.owner_id == owner.entity_id
                       and (a.parameters.get('typed') or {}).get('source') == POWER + '.declare_protected_subject'), None)
        if action is None:
            continue
        declare(Context(engine, owner, action, intent, action.parameters['typed'], [owner]), options=options,
                triggering_action=f'{triggering.display_name} by {source.display_name if source else "the acting creature"}')
        owner.turn_flags['iron_oath_round_declaration_offers'] = {
            **offered, **{key: defense.appeared_round for key, (_fact, defense) in options.items()}}


def attack_or_technique(engine, source, actor_id=None, target_id=None):
    from ..native_reactions import context
    reaction = context(engine, actor_id, source)
    if reaction is not None and reaction['target_id'] == target_id:
        return True
    action = engine.action_catalog.get(source)
    if action is None:
        return False
    if action.resolution_kind in {'ATTACK', 'MULTI_ATTACK'}:
        return True
    typed = action.parameters.get('typed') or {}
    return bool(typed) and not action.parameters.get('setting_only')


def qualified(engine, owner, target):
    if getattr(target, 'entity_id', None) not in engine.state.actors:
        return False  # Oath-Mark names a creature, never an object damage packet.
    declaration = f.held(owner, 'protected_subject')
    return (f.row(engine, owner, 'oath', 'oath_mark_strike') is not None and available(engine, owner)
            and declaration is not None and defending(engine, owner)
            and subjects.qualified_pressure(engine, owner, declaration.data.get('record_id'), target))


def mark_spend(engine, owner, target, action):
    from . import ai_controlled
    if ai_controlled(engine, owner):
        declaration = f.held(owner, 'protected_subject')
        if declaration is None or not subjects.qualified_pressure(
                engine, owner, declaration.data.get('record_id'), target, known_only=True):
            return None
    pb = f.values(engine, owner)[0]
    if qualified(engine, owner, target) and f.spend(engine, owner, 'oath', 'oath_mark_strike',
            f'Oath-Mark Strike: spend 1 Guarding Iron to add {pb} damage to {action.display_name} affecting {target.display_name}. '
            'The damage uses the triggering attack or technique damage type.', target):
        return pb
    return None


@hook('confirmed_hit_damage_bonus')
def mark_hit(engine, owner, target, spec, intent, source, critical):
    action = engine.action_catalog.get(source)
    if action is None or spec.get('damage') is None:
        return None
    typed = action.parameters.get('typed') or {}
    # Real weapon identity, or sealed Foundation compatibility; unarmed is not
    # automatically a weapon or an oath-compatible technique.
    if (typed.get('weapon') is None and not f.aligned(typed, 'oath')
            and not subjects.source_in_scope(engine, owner, source, POWER, 'compatible')):
        return None
    return mark_spend(engine, owner, target, action)


@hook('deal_bonus')
def mark_failed_save(ctx, target, amount):
    # Per-recipient seam after final outcome, before resistance/immunity. No
    # shared area-roll cache and no extra damage packet/rounding error.
    if (ctx.failed_save is not True or amount <= 0
            or not (f.aligned(ctx.typed, 'oath') or subjects.source_in_scope(
                ctx.engine, ctx.actor, ctx.source, POWER, 'fixed_scope'))):
        return None
    return mark_spend(ctx.engine, ctx.actor, target, ctx.action)


@hook('compile_block')
def compile_oath(block, spec, record, numbers):
    if block != 'iron_oath':
        return None
    return [{**record, 'kind': spec['kind'], 'numbers': dict(numbers)}]


def initial_frame_contribution(foundation, pb):
    """Shared source formula for fight compilation and persistent story removal."""
    mechanics = foundation.get('mechanics')
    if isinstance(mechanics, dict):
        from non_sphere_authority.foundation_mechanics import resolve_initial_foundation_mechanics, verified_foundation_records
        from ..canonical import canonical_sha256
        from stage2.formulas import evaluate_formula
        initial = mechanics.get('initial_state') or {}
        expected = resolve_initial_foundation_mechanics(verified_foundation_records()['iron_oath_skin_v0_2B'],
            initial.get('active_expression_path_ids') or [], stage=initial.get('stage'))
        if canonical_sha256(mechanics) != canonical_sha256(expected):
            raise ValueError('Oath-Skin Frame requires the source-authenticated Foundation projection.')
        return sum(evaluate_formula(r['formula']['root'], {'pb': int(pb)}).value
                   for r in expected['hp_maximum_modifiers'])
    return None


@hook('compile_bundle')
def frame_provenance(bundle, info):
    frame = next((r for r in bundle.get('typed_passives', []) if r.get('feature_id') == FRAME), None)
    if frame is None:
        return bundle
    foundation = info['owner_sheet'].get('foundation') or {}
    included = initial_frame_contribution(foundation, info['numbers']['pb'])
    stage = foundation.get('stage') or ((foundation.get('mechanics') or {}).get('initial_state') or {}).get('stage')
    amount = int(info['numbers']['pb']) * (2 if stage in {'Integrated', 'Intermediate', 'Refined', 'Perfected'} else 1)
    if included is not None:
        bundle['actor_template']['maximum_hp'] += amount - included
    frame['included_hp'] = amount
    frame['initial_acquisition_id'] = str(foundation.get('acquisition_event_id') or foundation.get('event_id') or '')
    return bundle


@hook('character_effects_from_fact')
def persistent_severance(engine, event):
    document = event.payload['fact']
    if not document.get('active', True):
        return None
    result = []
    for state in document.get('power_states', []):
        if state['power_id'] != POWER or state['state'] != 'fully_severed':
            continue
        frame = next((r for r in engine.typed_passive_rows.get(state['actor_id'], []) if r.get('feature_id') == FRAME), None)
        if frame is not None and frame.get('initial_acquisition_id'):
            result.append({'power_state': state, 'initial_acquisition_id': frame['initial_acquisition_id']})
    return result or None


@hook('character_source_effect')
def severed_character(sheet, receipt):
    state = receipt['power_state']
    foundation = sheet.get('foundation') or {}
    if (state['power_id'] != POWER or state['state'] != 'fully_severed'
            or foundation.get('foundation_id') != f.GROUPS['oath'][0]
            or str(foundation.get('acquisition_event_id') or foundation.get('event_id') or '') != receipt['initial_acquisition_id']
            or foundation.get('available') is False):
        return sheet
    from copy import deepcopy
    import json
    result = deepcopy(sheet)
    included = initial_frame_contribution(foundation, int(sheet['identity']['proficiency_bonus']))
    if included is None:
        raise ValueError('Permanent Frame severance requires the native initial HP source proof.')
    raw = result['ability_scores_and_statistics']['hit_points']
    hp = json.loads(raw) if isinstance(raw, str) else dict(raw)
    hp['maximum'] = max(1, int(hp['maximum']) - included)
    if type(hp.get('current')) is int:
        hp['current'] = min(hp['current'], hp['maximum'])
    result['ability_scores_and_statistics']['hit_points'] = json.dumps(hp) if isinstance(raw, str) else hp
    result['foundation'] = {**foundation, 'available': False, 'state': 'fully_severed',
                            'resource': {**(foundation.get('resource') or {}), 'current': 0, 'maximum': 0}}
    return result


@hook('state_event')
def story_severance(engine, event):
    if event.event_type != 'TABLE_FACT_RECORDED':
        return
    document = event.payload.get('fact', {})
    if not document.get('active', True):
        return
    for effect in document.get('power_states', []):
        if effect['power_id'] != POWER or effect['state'] != 'fully_severed':
            continue
        actor = engine.state.actors[effect['actor_id']]
        frame = next((r for r in engine.typed_passive_rows.get(actor.entity_id, []) if r.get('feature_id') == FRAME), None)
        if frame is None:
            continue
        from ..maximum_hp import change
        change(engine, actor, FRAME + ':severance', -int(frame['included_hp']), FRAME, actor.entity_id,
               label='Oath-Skin Frame fully severed by an explicit story effect')
        held = actor.resources.get(f.pool('oath'), 0)
        if held:
            engine._spend_resource(actor, f.pool('oath'), held, FRAME)
