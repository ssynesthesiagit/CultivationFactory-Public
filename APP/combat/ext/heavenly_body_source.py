"""Heavenly Body source admission; one resource engine remains in pressure.

Compiled acquisition establishes ownership/stage. Explicit owner/GM facts use
the shared table_facts journal, not damage tags or AI declarations. A fact with
answer key ``foundation.heavenly_body_v0_2F``, category foundation_availability,
fact available/suppressed/unavailable, and condition equal to an effective
Foundation stage records an externally adjudicated suppression/Realm limit.
The source reference identifies the actual ruling/effect, not a grant of power.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Literal
from pydantic import Field, StrictInt, StrictStr
from ..models import StrictModel

from . import hook
from ..feature_availability import available

FOUNDATION = 'heavenly_body_v0_2F'
SOURCE = 'foundation.' + FOUNDATION
PREFIX = SOURCE + '.'
POOL = 'resource:foundation.heavenly_integrity'
BODY_SOURCE = PREFIX + 'integrity_rejection.body_source'
BODY_FAMILIES = {'poison', 'sickened', 'exhaustion', 'body_corruption', 'body_seizure',
                 'forced_transformation', 'internal_disruption'}
STAGES = ('Latent', 'Common Expression', 'Awakened', 'Integrated', 'Refined', 'Perfected')
FRAME = ContextVar('heavenly_body_damage_source', default=None)


class Attainment(StrictModel):
    """The GM's external, source-specific Foundation Challenge findings."""
    stage: Literal['Refined', 'Perfected']
    challenge: Literal['Purify Without Arrogance']
    scene_reference: StrictStr = Field(min_length=1)
    bodily_integrity_demonstrated: StrictStr = Field(min_length=1)
    treatment_of_wounded_ordinary_deviant_or_impure_lives: StrictStr = Field(min_length=1)
    active_severity: StrictInt = Field(ge=0)
    adjudication_reference: StrictStr = Field(min_length=1)


class Installation(StrictModel):
    kind: Literal['foundation_installation']
    reference: StrictStr = Field(min_length=1)
    classification: Literal['Foundation']
    authority: Literal['GM']
    attainments: tuple[Attainment, ...] = ()
    refined_expression: Literal['', 'jade_gold_guard', 'heaven_rejecting_marrow', 'orthodox_answering_strike'] = ''


@hook('feature_access_policy')
def acquisition_policy(feature_id):
    if feature_id != SOURCE:
        return None
    return {'paths': ['tianxia.path.body_refining', 'tianxia.path.qi_cultivation'],
            'minimum_cl': 5, 'classification': 'Foundation',
            'source_kinds': ['foundation_installation']}


@hook('feature_access_projection')
def acquired_source(sheet, feature_id, source):
    if feature_id != SOURCE:
        return None
    declaration = Installation.model_validate(source)
    if any(not value.strip() for value in (declaration.reference,)):
        raise ValueError('Record the actual installation source reference.')
    existing = sheet.get('foundation') or {}
    if existing.get('foundation_id') not in (None, '', FOUNDATION):
        raise ValueError('A character cannot install a second Foundation.')
    from non_sphere_authority.foundation_mechanics import (
        verified_foundation_records, resolve_initial_foundation_mechanics, installed_foundation_state)
    record = verified_foundation_records()[FOUNDATION]
    identity, paths = sheet.get('identity') or {}, sheet.get('path_and_subpath') or {}
    owned_paths = list(dict.fromkeys([*(paths.get('path_record_ids') or []), *(identity.get('path_ids') or [])]))
    mechanics = resolve_initial_foundation_mechanics(record, owned_paths, stage='Awakened')
    # Initial stage/resource/max come only from the canonical installation;
    # progression cannot be inferred from CL or from a selected expression.
    state = installed_foundation_state(mechanics, FOUNDATION, declaration.reference)
    stage = 'Awakened'
    for expected, attainment in zip(('Refined', 'Perfected'), declaration.attainments):
        if attainment.stage != expected or any(not value.strip() for value in (
                attainment.scene_reference, attainment.bodily_integrity_demonstrated,
                attainment.treatment_of_wounded_ordinary_deviant_or_impure_lives,
                attainment.adjudication_reference)):
            raise ValueError('Record each Foundation Challenge in order with its actual findings and adjudication.')
        stage = expected
    if len(declaration.attainments) > 2:
        raise ValueError('Heavenly Body has only Awakened, Refined and Perfected progression.')
    if existing.get('stage') in STAGES and STAGES.index(stage) < STAGES.index(existing['stage']):
        raise ValueError('Preserve the attained Foundation stage; suppression is recorded separately.')
    if declaration.refined_expression and stage == 'Awakened':
        raise ValueError('A Refined expression requires Refined attainment.')
    previous = (sheet.get('feature_access') or {}).get(SOURCE)
    if previous and (previous.get('reference') != declaration.reference or
            list(source.get('attainments') or [])[:len(previous.get('attainments') or [])] != list(previous.get('attainments') or [])):
        raise ValueError('Preserve the installed source and completed Foundation Challenges.')
    state.update(stage=stage, stage_origin='recorded Foundation Challenge' if declaration.attainments else 'published_initial_stage',
                 refined_expression=declaration.refined_expression,
                 acquisition_event_id=declaration.reference)
    out = deepcopy(sheet)
    out['foundation'] = state
    out.setdefault('feature_access', {})[SOURCE] = declaration.model_dump(mode='json')
    return out


@hook('compile_bundle')
def source_admission(bundle, info):
    foundation = info['owner_sheet'].get('foundation') or {}
    if foundation.get('foundation_id') == FOUNDATION:
        bundle['foundation_runtime_source'] = {
            'foundation_id': FOUNDATION, 'stage': str(foundation.get('stage') or ''),
            'status': str(foundation.get('status') or ''),
            'acquisition_event_id': str(foundation.get('acquisition_event_id') or foundation.get('event_id') or ''),
            'refined_expression': str(foundation.get('refined_expression') or ''),
        }
    return bundle


def admission(engine, actor):
    return next((bundle['foundation_runtime_source'] for bundle in
                 getattr(engine, 'typed_bundle_documents', ()) or ()
                 if bundle.get('actor_id') == actor.entity_id
                 and (bundle.get('foundation_runtime_source') or {}).get('foundation_id') == FOUNDATION), None)


@hook('table_fact_validate')
def validate_source_input(engine, fact):
    body = fact.answers.get(BODY_SOURCE)
    if body is not None:
        from .passive_rows import known_level
        action = engine.action_catalog.get(fact.subject_id)
        actor = engine.state.actors.get(action.owner_id) if action else None
        if (fact.subject_kind != 'event' or actor is None or body.category != 'bodily_save_source'
                or body.fact != 'bodily_effect' or body.condition not in BODY_FAMILIES
                or not body.visible_sign.strip() or body.source_cl != known_level(engine, actor)
                or not body.predictions):
            raise ValueError('Record the actual bodily effect, owning source, known source level and exact intended action.')
        for prediction in body.predictions:
            if (prediction.actor_id != actor.entity_id or prediction.source_definition_id != fact.subject_id
                    or not prediction.target_ids
                    or not set(prediction.target_ids) <= set(fact.witness_ids)
                    or not set(prediction.target_ids) <= set(prediction.aware_actor_ids)
                    or not any(admission(engine, engine.state.actors[target]) is not None
                               for target in prediction.target_ids if target in engine.state.actors)):
                raise ValueError('Bind the bodily source declaration to its actual actor, targets, options and informed cultivator.')
    answer = fact.answers.get(SOURCE)
    if answer is None:
        return
    actor = engine.state.actors.get(fact.subject_id)
    if (fact.subject_kind != 'creature' or actor is None or admission(engine, actor) is None
            or answer.category != 'foundation_availability'
            or answer.fact not in {'available', 'suppressed', 'unavailable'}
            or answer.condition not in STAGES):
        raise ValueError('Record the acquired Heavenly Body, its source status and effective Foundation stage.')
    acquired = admission(engine, actor)['stage']
    if acquired not in STAGES or STAGES.index(answer.condition) > STAGES.index(acquired):
        raise ValueError('Suppression cannot grant a higher Foundation stage.')
    if actor.entity_id not in fact.witness_ids:
        raise ValueError('The affected cultivator must know their available Foundation features.')


def bodily_source(engine, target, source_actor_id, source_id):
    """An unknown subjective source stays unknown until an explicit GM input.

    Native conditions/save_categories need no declaration. External or subjective
    body intent uses the existing protected fact journal and a real accepted
    action, never a damage name, ally/willing inference, or fabricated receipt.
    """
    from ..table_facts import records, accepted_source_matches
    for fact in records(engine, target).values():
        answer = fact.answers.get(BODY_SOURCE)
        if answer is not None and fact.subject_id == source_id:
            if any(accepted_source_matches(engine, prediction, source_id, source_actor_id, target.entity_id)
                   for prediction in answer.predictions):
                return True
    return False


@hook('feature_available')
def source_available(engine, actor, feature_id):
    if not feature_id.startswith(PREFIX):
        return None
    source = admission(engine, actor)
    if source is None:
        return None  # compiled pre-contract fixtures retain their admission
    if source['status'].casefold() in {'suppressed', 'unavailable'}:
        return False
    stage = source['stage']
    from ..table_facts import records
    for fact in records(engine, actor).values():
        if fact.subject_id == actor.entity_id and SOURCE in fact.answers:
            answer = fact.answers[SOURCE]
            if answer.fact != 'available':
                return False
            # Multiple active sources cannot raise another source's limit.
            stage = min((stage, answer.condition), key=lambda s: STAGES.index(s) if s in STAGES else -1)
    minimum = ('Perfected' if feature_id.endswith('.heaven_recognized_vessel') else
               'Refined' if feature_id.rsplit('.', 1)[-1] in {
                   'jade_gold_guard', 'heaven_rejecting_marrow', 'orthodox_answering_strike'} else 'Awakened')
    return stage in STAGES and STAGES.index(stage) >= STAGES.index(minimum)


@hook('cost_available')
def source_payment(engine, actor, resource_id, amount, context):
    if resource_id == POOL:
        return available(engine, actor, PREFIX + 'generate_heavenly_integrity')
    return None


@contextmanager
def damage_source(ctx):
    token = FRAME.set(ctx)
    try:
        yield
    finally:
        FRAME.reset(token)


@hook('effect_resolution_scope')
def technique_source(ctx, effect):
    if not any(row.get('feature_id') == PREFIX + 'generate_heavenly_integrity'
               for rows in (getattr(ctx.engine, 'typed_passive_rows', {}) or {}).values() for row in rows):
        return None
    if effect.get('type') in {'damage', 'attack'}:
        return damage_source(ctx)
    return None


@hook('match_start', priority=40)
def recorded_expression(engine):
    """An explicit owner selection precedes AI defaults and survives genesis."""
    from .foundation_combat import P, held
    for actor in engine.state.actors.values():
        source = admission(engine, actor)
        expression = (source or {}).get('refined_expression')
        if expression and held(actor, 'expression') is None:
            engine._apply_condition(actor, P + 'expression', PREFIX + expression, actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'feature': PREFIX + expression,
                    'label': 'Selected Refined expression',
                    'source_reference': source['acquisition_event_id']})


@hook('resource_generation_allowed')
def generate_only_from_source(engine, actor, row, reason, event):
    if row.get('feature_id') != PREFIX + 'generate_heavenly_integrity':
        return None
    if (reason != 'damaged' or event is None or not actor.active or actor.current_hp <= 0
            or any(c.condition_id.rsplit('.', 1)[-1].lower() in {'unconscious', 'dream_sleep'}
                   for c in actor.conditions.values())):
        return False
    attack = engine.damage_context()
    if attack is not None and (attack.attacker_id, attack.target_id, attack.source_id) == (
            event.actor_id, actor.entity_id, event.source_definition_id):
        return True
    ctx = FRAME.get()
    from ..activation_settlement import profile
    # Reuse Mercurial's public native activation profile; no parallel origin
    # schema. Actual source frames distinguish techniques from unknown hazards.
    technique = (ctx is not None and profile(engine, ctx.actor, ctx.action)['source_kind'] in
                 {'Path', 'Subpath', 'Sphere', 'Recorded', 'Forged', 'Immortal'})
    return bool(technique and ctx.engine is engine
                and ctx.actor.entity_id == event.actor_id and ctx.damage_source == event.source_definition_id
                and ctx.action.owner_id == ctx.actor.entity_id)
