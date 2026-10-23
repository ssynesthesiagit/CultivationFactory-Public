"""Source-backed post-acquisition Foundation attainment at the owner/GM table.

The native creator owns initial acquisition. This adapter records later actual
campaign attainment: a sourced assessment of requirements, time, cost and
outcomes, bound to an already committed successful Foundation Challenge roll.
It never invents a stage, a CL threshold, a DC or a benefit. The published stage
order controls admission; the existing source compiler projects its benefits
when the character enters the next scene. Active fights are not rewritten.
"""
from typing import Literal
from pydantic import Field, StrictStr
from .models import StrictModel


class Attainment(StrictModel):
    foundation_id: StrictStr
    previous_stage: StrictStr
    stage: Literal['Common Expression', 'Awakened', 'Integrated', 'Refined', 'Perfected']
    source_reference: str = Field(min_length=1)
    requirements_met: tuple[StrictStr, ...] = Field(min_length=1)
    time_spent: str = Field(min_length=1)
    costs_paid: tuple[StrictStr, ...] = Field(min_length=1)
    success_result: str = Field(min_length=1)
    failure_result: str = Field(min_length=1)
    proof_match_id: StrictStr
    proof_project_record_id: StrictStr
    selected_expression_ids: tuple[StrictStr, ...] = ()


def validate_transition(sheet, document):
    """Validate ownership and the next published stage without guessing CL gates."""
    from non_sphere_authority.foundation_features import STAGE_ORDER
    from non_sphere_authority.foundation_mechanics import verified_foundation_records, resolve_initial_foundation_mechanics
    from .canonical import canonical_sha256
    request = Attainment.model_validate(document)
    foundation = sheet.get('foundation') or {}
    if foundation.get('available') is False:
        raise ValueError('An unavailable Foundation cannot attain another stage before its source is restored or replaced.')
    if (foundation.get('foundation_id') != request.foundation_id
            or request.foundation_id not in verified_foundation_records()
            or not foundation.get('mechanics')):
        raise ValueError('Record how this character first gained this Foundation before adding a later stage.')
    mechanics = foundation['mechanics']
    initial = mechanics.get('initial_state') or {}
    expected = resolve_initial_foundation_mechanics(verified_foundation_records()[request.foundation_id],
        initial.get('active_expression_path_ids') or [], stage=initial.get('stage'))
    if canonical_sha256(mechanics) != canonical_sha256(expected):
        raise ValueError('The original Foundation benefits do not match its published rules. Recheck its acquisition record.')
    current = foundation.get('stage')
    if (current != request.previous_stage or current not in STAGE_ORDER
            or STAGE_ORDER.index(request.stage) != STAGE_ORDER.index(current) + 1):
        raise ValueError('Record the next published Foundation stage after the character’s current attained stage.')
    if any(not value.strip() for value in (*request.requirements_met, *request.costs_paid)):
        raise ValueError('Describe the requirements you met and what you paid.')
    if any(value.strip().lower() in {'done', 'approved', 'yes', 'complete', 'completed'}
           for value in request.requirements_met):
        raise ValueError('Describe the completed source requirements, rather than a generic approval marker.')
    if any(not value.strip() for value in (request.source_reference, request.time_spent,
                                           request.success_result, request.failure_result)):
        raise ValueError('Record the actual source, scene time and success/failure outcomes.')
    from . import ext
    policies = ext.run_strict('foundation_refined_expression_policy', request.foundation_id)
    if len(policies) > 1:
        raise ValueError('A Foundation must have one Refined expression policy.')
    policy = policies[0] if policies else None
    choices = request.selected_expression_ids
    if request.stage == 'Refined' and policy:
        if (len(set(choices)) != len(choices) or not set(choices) <= set(policy['allowed'])
                or not policy['minimum'] <= len(choices) <= policy['maximum']):
            raise ValueError('Choose the printed number of Refined expressions, the Foundation’s upgraded benefits, from its own list.')
    elif choices:
        raise ValueError('Record new Refined expression choices only at their source-authorized attainment.')
    return request


def record(table, project_id, document):
    """Return a persisted acquisition receipt tied to an actual native outcome.

    A GM's external/narrative assessment is explicit; the mechanical outcome is
    read from the committed journal, never accepted as a request flag. Results
    cannot be borrowed from another creature or consumed for two attainments.
    """
    from . import table_advance
    from .canonical import canonical_sha256
    from .table_facts import records
    from .tabletop_service import FACTORY_PREFIX
    sheet = table.combat._factory_owner_sheet(project_id)
    request = validate_transition(sheet, document)
    from . import ext
    ext.run_strict('foundation_attainment_requirements', sheet, request)
    actor_id = FACTORY_PREFIX + project_id
    session = table.combat._load_session(request.proof_match_id)
    engine = session.engine
    actor = engine.state.actors.get(actor_id)
    if actor is None:
        raise ValueError('The Foundation Challenge must belong to this character.')
    from . import ext
    if any(reply is False for reply in ext.run_strict('foundation_attainment_allowed', engine, actor, request.foundation_id)):
        raise ValueError('This Foundation is suppressed, severed, or otherwise unable to advance.')
    from .protected_subjects import power_states
    power = power_states(engine, actor).get('foundation.' + request.foundation_id)
    if power and power['state'] != 'available' and power.get('scope') != 'resources':
        raise ValueError('The Foundation route is suppressed or fully severed.')
    fact = records(engine, actor).get(request.proof_project_record_id)
    if (fact is None or fact.project_check is None or fact.project_check.actor_id != actor_id
            or fact.project_check.kind != 'foundation_challenge'
            or fact.source_reference != request.source_reference):
        raise ValueError('Choose a current Foundation Challenge recorded for this character, with the same rule reference.')
    event = next((event for event in reversed(engine.events)
                  if event.event_type == 'CHECK_ROLLED' and event.actor_id == actor_id
                  and event.payload.get('project_record_id') == fact.record_id
                  and event.payload.get('project_kind') == 'foundation_challenge'
                  and event.payload.get('success') is True), None)
    if event is None:
        raise ValueError('Finish a successful Foundation Challenge for this character before recording its new stage.')
    saved = table_advance.normalized(table.buttons.get(project_id).get('advancement'))
    proof = canonical_sha256([request.proof_match_id, event.model_dump(mode='json')])
    if any(row['proof_sha256'] == proof for row in saved['foundation_attainments']):
        raise ValueError('That challenge already advanced a Foundation. Finish another before advancing again.')
    receipt = {**request.model_dump(mode='json'), 'proof_sha256': proof,
               'initial_acquisition_id': str(sheet['foundation'].get('acquisition_event_id') or sheet['foundation'].get('event_id') or ''),
               'proof_event_sequence': event.sequence, 'cl': int((sheet.get('identity') or {}).get('cultivation_level') or 0)}
    saved['foundation_attainments'].append(receipt)
    table.buttons.save_advancement(project_id, saved)
    return {'status': 'RECORDED', 'foundation_id': request.foundation_id, 'stage': request.stage,
            'proof_sha256': proof, 'applies': 'next scene'}


def apply(sheet, rows):
    """Project only a valid contiguous recorded chain over the original proof."""
    from copy import deepcopy
    result = deepcopy(sheet)
    for row in rows:
        foundation = result.get('foundation') or {}
        if row.get('initial_acquisition_id') != str(foundation.get('acquisition_event_id') or foundation.get('event_id') or ''):
            continue  # A replacement Foundation cannot inherit the former one's attainment.
        applied = (result.get('foundation') or {}).get('attainment_proofs') or []
        if row.get('proof_sha256') in applied:
            continue
        request = validate_transition(result, {key: value for key, value in row.items()
            if key not in {'proof_sha256', 'proof_event_sequence', 'cl', 'initial_acquisition_id'}})
        if not row.get('proof_sha256') or type(row.get('proof_event_sequence')) is not int:
            raise ValueError('A Foundation stage requires its recorded native challenge proof.')
        result['foundation']['stage'] = request.stage
        result['foundation']['attainment_proofs'] = [*applied, row['proof_sha256']]
        if request.selected_expression_ids:
            result['foundation']['selected_refined_expression_ids'] = list(request.selected_expression_ids)
    return result
