"""Source-clocked Heavenly restrictions, sharing one fixed feature predicate.

Native source writers use ``heavenly_body_state`` with kind
``heavenly_vessel_strain`` and severity1/2/3, or
``suppressed_heavenly_integrity`` and severity0. The effect or parent technique
must supply its printed duration/expires_on. Ordinary condition events, source attribution and expiry
remain the engine's, not a second state/resource engine.

``states_for`` and ``blocks_feature`` are shared with heavenly_body_source's
private, audience-scoped GM journal adapter. Private declarations are never
copied into public conditions. This module does not implement injury/check DCs
or sibling features outside the eight assigned conversions/evolutions.
"""
from typing import Literal

from pydantic import StrictInt, model_validator

from ..models import StrictModel
from . import effect
from .foundation_combat import held

CONDITION = 'condition:foundation.heavenly_body_source_state'


class SourceState(StrictModel):
    kind: Literal['heavenly_vessel_strain', 'suppressed_heavenly_integrity']
    severity: StrictInt = 0

    @model_validator(mode='after')
    def printed_severity(self):
        if self.kind == 'heavenly_vessel_strain' and self.severity not in (1, 2, 3):
            raise ValueError('Heavenly Vessel Strain requires severity 1, 2 or 3.')
        if self.kind == 'suppressed_heavenly_integrity' and self.severity != 0:
            raise ValueError('Suppressed Heavenly Integrity has no severity or extra feature suppression.')
        return self


def states_for(actor, facts, state_key):
    """Native conditions plus already audience-filtered source declarations.

    Invalid/unknown metadata is not a mechanical fact. Admission rejects it at
    either real producer; unrelated conditions and other actors remain inert.
    """
    for condition in actor.conditions.values():
        if condition.condition_id != CONDITION:
            continue
        data = condition.data or {}
        try:
            yield SourceState(kind=data.get('state_kind'), severity=data.get('severity'))
        except (ValueError, TypeError):
            continue
    for fact in facts:
        answer = fact.answers.get(state_key)
        if fact.subject_id != actor.entity_id or answer is None:
            continue
        try:
            yield SourceState(kind=answer.fact, severity=(int(answer.condition)
                if answer.fact == 'heavenly_vessel_strain' else 0))
        except (ValueError, TypeError):
            continue


def blocks_feature(actor, feature_id, states):
    """Pure fixed printed table; caller has already checked owned source scope."""
    leaf = feature_id.rsplit('.', 1)[-1]
    selected = held(actor, 'expression')
    for state in states:
        if leaf == 'generate_heavenly_integrity':
            return True
        if state.kind != 'heavenly_vessel_strain':
            continue
        if (state.severity >= 2 and selected and selected.data.get('feature') == feature_id
                and leaf in {'jade_gold_guard', 'heaven_rejecting_marrow', 'orthodox_answering_strike'}):
            return True
        if state.severity >= 3 and leaf == 'heaven_recognized_vessel':
            return True
    return False


@effect('heavenly_body_state', harmful=True)
def apply_source_state(ctx, row):
    """Actual source resolution -> ordinary target condition, no invented clock."""
    from ..typed_executor import effect_subjects, effect_expiry
    from .heavenly_body_source import admission

    targets = [target for target in effect_subjects(ctx, row, harmful=True)
               if admission(ctx.engine, target) is not None]
    if not targets:
        return
    state = SourceState(kind=row.get('kind'), severity=row.get('severity', 0))
    timings = [(target, effect_expiry(ctx, row, target, condition=True)) for target in targets]
    if any(not expiry for _, expiry in timings):
        raise ValueError('The Heavenly source restriction has no resolvable expiry.')
    limits = 'Cannot gain Heavenly Integrity; held Integrity still pays for base conversions (1 Integrity each).'
    if state.kind == 'heavenly_vessel_strain' and state.severity >= 2:
        limits += ' The selected Refined Guard, Rejection or Strike improvement is unavailable.'
    if state.kind == 'heavenly_vessel_strain' and state.severity >= 3:
        limits += ' Heaven-Recognized Vessel is unavailable.'
    name = (f'Heavenly Vessel Strain {state.severity}' if state.kind == 'heavenly_vessel_strain'
            else 'Suppressed Heavenly Integrity')
    for target, expiry in timings:
        ctx.engine._apply_condition(target, CONDITION, ctx.source, ctx.actor.entity_id,
            expires_on=expiry, data={'state_kind': state.kind, 'severity': state.severity,
                'label': f'{name}: {limits}'})
