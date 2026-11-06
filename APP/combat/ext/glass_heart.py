"""Glass Heart's declared scope and committed Reflection producer.

Reuses table_facts from Read the Thread, rather than a second fact journal.
Only the owner/GM supplies subjective source facts. A declaration binds one
bearer, one exact action and an immediate horizon; it never grants ownership,
Sphere access, success, payment, a damage rider or a roll bonus. Unknown facts
stay unknown. Numerical benefits absent from the source are not invented here.
"""
from . import hook, note
from .foundation_resources import affinity_spheres

FOUNDATION_ID = 'glass_heart_meridian_v0_2A'
PREFIX = 'foundation.' + FOUNDATION_ID + '.'
POOL = 'resource:foundation.glass_reflection'
CP_POOLS = frozenset({'resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'})
KEY = 'glass_heart.'
EXPRESSIONS = frozenset({
    'emotional_truth', 'reflection_without_denial', 'revealed_falsehood',
    'beauty_without_self_erasure', 'protected_vulnerability', 'mirror_defense',
    'trust_repair',
})
PRESSURES = frozenset({
    'illusion', 'charm', 'fear', 'deception', 'gaze', 'beauty_pressure',
    'emotional_manipulation', 'radiant_reflection', 'glass_reflection',
    'falsehood_psychic',
})
VALUES = {
    'scope': EXPRESSIONS,
    'pressure': PRESSURES,
    # Genuine trust repair need not involve a threat. This affirms the printed
    # exclusions, not a new combat or danger prerequisite for a paid technique.
    'anti_farming': frozenset({'genuine_unarranged_event'}),
    'scene': frozenset({'major_combat', 'emotionally_decisive'}),
}


@hook('table_fact_validate')
def validate_declaration(engine, fact):
    """Validate Glass's view of the shared, owner-authored fact contract."""
    selected = {k.removeprefix(KEY): v for k, v in fact.answers.items() if k.startswith(KEY)}
    if not selected:
        return
    if fact.subject_kind != 'creature' or fact.subject_id not in fact.witness_ids:
        raise ValueError('Glass Heart declarations must identify the bearer and include that bearer as a witness.')
    for purpose, answer in selected.items():
        action = engine.action_catalog.get(answer.condition)
        if purpose not in VALUES or answer.category != KEY + purpose or answer.fact not in VALUES[purpose]:
            raise ValueError('Choose a printed Glass Heart expression, pressure or scene; excluded farming never qualifies.')
        if action is None:
            raise ValueError('Bind the declaration to an actual action in this fight.')
        if purpose in {'scope', 'scene'} and action.owner_id != fact.subject_id:
            raise ValueError('A technique expression or Refraction scene must belong to the bearer.')
    for purpose in ('scope', 'pressure'):
        if purpose in selected and ('anti_farming' not in selected
                or selected[purpose].condition != selected['anti_farming'].condition):
            raise ValueError('Record why this exact event is not a staged lie, harmless performance, training illusion, repeated non-threatening prompt, self-inflicted drama, farmed social check or arranged deception.')


def declaration(engine, bearer, source_id, purpose):
    """(record_id, value) of the current positive declaration for this exact source, or None.

    Visible only to its named bearer. Spend it with spend() once its declared
    event has actually happened; a spent record is no longer current.
    """
    from ..table_facts import records
    for record_id, fact in records(engine, bearer).items():
        answer = fact.answers.get(KEY + purpose)
        if (fact.subject_kind != 'creature' or fact.subject_id != bearer.entity_id
                or answer is None or answer.condition != source_id
                or answer.category != KEY + purpose or answer.fact not in VALUES.get(purpose, ())):
            continue
        if purpose in {'scope', 'pressure'}:
            anti = fact.answers.get(KEY + 'anti_farming')
            if (anti is None or anti.condition != source_id or anti.category != KEY + 'anti_farming'
                    or anti.fact != 'genuine_unarranged_event'):
                continue
        return record_id, answer.fact
    return None


def declared(engine, bearer, source_id, purpose):
    """Current source-bound positive fact value, visible only to its named bearer.

    Used by Glass generation and Refraction admission. No team-wide knowledge
    propagation or absent-metadata inference is permitted.
    """
    found = declaration(engine, bearer, source_id, purpose)
    return found[1] if found else None


def spend(engine, bearer, source_id, purpose):
    """Consume the declaration that the qualifying event just used, if any.

    A declaration answers one exact event, so a later use of the same action
    with no new declaration cannot reuse it (including after a reload).
    """
    found = declaration(engine, bearer, source_id, purpose)
    if found is not None:
        from ..table_facts import consume
        consume(engine, found[0])
    return found is not None


# Plain-language scene choices for the GM control; the record stores the same value.
SCENE_LABELS = {'major_combat': 'a major combat', 'emotionally_decisive': 'an emotionally decisive scene'}


def scene_document(engine, bearer_id, scene):
    """The GM's scene declaration for Refraction, built from the bearer's own action.

    The owner's table input contract (table_facts) validates and journals it. It
    holds for this round only and is spent when Refraction is used.
    """
    if scene not in SCENE_LABELS:
        raise ValueError('Choose a major combat or an emotionally decisive scene.')
    bearer = engine.state.actors.get(bearer_id)
    if bearer is None:
        raise ValueError('Choose a creature present in this fight.')
    source = next((a.source_definition_id for a in engine.action_catalog.values()
                   if a.owner_id == bearer_id and ((a.parameters or {}).get('typed') or {}).get('source') == PREFIX + 'perfected_glass_heart_refraction'), None)
    if source is None:
        raise ValueError(f'{bearer.display_name} does not have Glass Heart Refraction.')
    from .needle import numbers_of
    return {'record_id': f'glass-scene:{bearer_id}:{engine.state.round_number}:{scene}', 'subject_id': bearer_id,
            'subject_name': bearer.display_name, 'subject_kind': 'creature', 'position': bearer.position.model_dump(mode='json'),
            'source_reference': f'GM scene declaration: {SCENE_LABELS[scene]}', 'witness_ids': [bearer_id],
            'valid_through_round': engine.state.round_number,
            'answers': {KEY + 'scene': {'category': KEY + 'scene', 'fact': scene, 'condition': source,
                                        'visible_sign': f'The GM declares {SCENE_LABELS[scene]} for Glass Heart Refraction.',
                                        'source_cl': int(numbers_of(engine, bearer).get('cl') or 0)}}}


def owns(engine, bearer, leaf):
    return any(r.get('feature_id') == PREFIX + leaf for r in
               (getattr(engine, 'typed_passive_rows', {}) or {}).get(bearer.entity_id, []))


def generate(engine, bearer, source_id, reason):
    from ..pressure import generate as gain
    if not owns(engine, bearer, 'generate_glass_reflection') or not gain(engine, bearer, reason):
        return
    bearer.turn_flags['glass_round_generation_sequence'] = engine.state.event_sequence
    note(engine, source_id, bearer, f'{bearer.display_name} gains Glass Reflection (maximum 1; expires at the end of their next turn).')


def preexisting_reflection(engine, bearer, trigger_sequence):
    """Public consumer guard, given the native triggering event's sequence.

    Bind a specific hit/roll, not a whole action: later hits in a multiattack
    can use Reflection from an earlier event. A refresh has provenance too.
    """
    if type(trigger_sequence) is not int or trigger_sequence < 1:
        raise ValueError('Bind Glass Reflection spending to an actual triggering event.')
    generated = bearer.turn_flags.get('glass_round_generation_sequence')
    return (bearer.resources.get(POOL, 0) > 0 and bearer.active
            and type(generated) is int and generated < trigger_sequence)


@hook('after_save_resolved')
def resolved_save(ctx, subject, ability, named, failed):
    # Settled outcome, including Banner and other native rescues. The source
    # does not require different teams: a genuine betrayal is not a staged lie.
    # Qualifying pressure and anti-farming remain explicit source facts.
    if (failed or not subject.active
            or not owns(ctx.engine, subject, 'generate_glass_reflection')):
        return
    if declared(ctx.engine, subject, ctx.source, 'pressure'):
        generate(ctx.engine, subject, ctx.source, 'glass_reflection_save')
        spend(ctx.engine, subject, ctx.source, 'pressure')


@hook('intent_resolved')
def settled_intent(engine, actor, candidate, intent, start_sequence):
    bearers = {a.entity_id: a for a in engine.state.actors.values()
               if owns(engine, a, 'generate_glass_reflection')}
    if not bearers:
        return
    source = candidate.source_definition_id
    action = engine.action_catalog.get(source)
    typed = (action.parameters.get('typed') or {}) if action is not None else {}
    if (actor.entity_id in bearers and typed.get('sphere') in affinity_spheres(FOUNDATION_ID)
            and declared(engine, actor, source, 'scope')):
        # Observe real net CP payment, after activation settlement/refunds. A
        # planned cost, unrelated payer, or payment on another action is not CP.
        paid = {}
        for event in engine.events:
            if event.sequence <= start_sequence or event.actor_id != actor.entity_id:
                continue
            resource = str(event.payload.get('resource_id') or '')
            if resource not in CP_POOLS:
                continue
            if event.event_type == 'RESOURCE_SPENT' and event.source_definition_id == source:
                paid[resource] = paid.get(resource, 0) + int(event.payload.get('amount') or 0)
            elif event.event_type == 'RESOURCE_GAINED' and event.payload.get('cost_source_id') == source:
                paid[resource] = paid.get(resource, 0) - int(event.payload.get('gained') or 0)
        if any(n > 0 for n in paid.values()):
            generate(engine, actor, source, 'glass_scope_spend')
            spend(engine, actor, source, 'scope')
    # Snapshot: spending journals events, and this loop must see only the fight's own rolls.
    for event in list(engine.events):
        if (event.sequence <= start_sequence or event.event_type != 'CHECK_ROLLED'
                or event.source_definition_id != source):
            continue
        beneficiary = event.actor_id if event.payload.get('success') is True else None
        # An actual defending die that preserves its situation resolves in the
        # defender's favor too. A printed DC is not a defending creature's roll.
        if event.payload.get('success') is False and event.payload.get('roll_kind') == 'opposed_check':
            beneficiary = (event.payload.get('target') or {}).get('actor_id')
        bearer = bearers.get(beneficiary)
        if bearer is not None and declared(engine, bearer, source, 'pressure'):
            generate(engine, bearer, source, 'glass_reflection_save')
            spend(engine, bearer, source, 'pressure')


@hook('intent_resolved')
def refraction_used(engine, actor, candidate, intent, start_sequence):
    """Using Refraction spends its scene: the next use needs a fresh GM declaration."""
    action = engine.action_catalog.get(candidate.source_definition_id)
    if action is not None and ((action.parameters.get('typed') or {}).get('source') == PREFIX + 'perfected_glass_heart_refraction'):
        spend(engine, actor, candidate.source_definition_id, 'scene')


@hook('candidate_allowed')
def refraction_admission(engine, actor, candidate, action):
    if action is None or (action.parameters.get('typed') or {}).get('source') != PREFIX + 'perfected_glass_heart_refraction':
        return None
    # Choosing this paid Bonus Action is the bearer's decision to stand in
    # transparent clarity. Scene importance is an explicit GM-sourced fact.
    return bool(declared(engine, actor, action.source_definition_id, 'scene'))


@hook('journey_rest')
def refraction_long_rest(session, actor_id):
    """Recharge the owned use only after the native eight-hour Long Rest.

    Journey already carries actual combat balances into later encounters. Do
    not reset CP, HP, Reflection or another creature's/feature's use counter.
    """
    actor = session.state['actors'][actor_id]
    bundle = actor['bundle']
    maxima = {r['resource_id']: int(r['maximum']) for r in bundle['actor_template']['resources']}
    for action in bundle.get('action_catalog') or []:
        if ((action.get('parameters') or {}).get('typed') or {}).get('source') != PREFIX + 'perfected_glass_heart_refraction':
            continue
        for resource_id, amount in action.get('costs') or []:
            if (resource_id == 'resource:uses.' + action['source_definition_id'] and amount > 0
                    and resource_id in actor['resources'] and resource_id in maxima
                    and actor['resources'][resource_id] < maxima[resource_id]):
                actor['resources'][resource_id] = maxima[resource_id]
