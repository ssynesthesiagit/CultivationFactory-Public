"""Shared synthetic Golden Mandate character for acquisition and native tests."""

from non_sphere_authority.foundation_mechanics import (
    installed_foundation_state, resolve_initial_foundation_mechanics, verified_foundation_records,
)
from tests.h1_support import sheet

IDENTITY = 'golden_mandate_seal_v0_2B'
POOL = 'resource:foundation.edict_seal'


def source_sheet(status='active', stage='Awakened', talents=()):
    record = verified_foundation_records()[IDENTITY]
    mechanics = resolve_initial_foundation_mechanics(record, ['tianxia.path.qi_cultivation'], stage=stage)
    doc = sheet(list(talents), cl=5, name='Mandate cultivator')
    doc['identity']['proficiency_bonus'] = 3
    doc['foundation'] = {**installed_foundation_state(mechanics, IDENTITY, 'starting-source-acquisition'),
                         'mechanics': mechanics, 'status': status}
    # A legal deterministic starting character: creation has already included
    # its one PB contribution. The causal acquisition test below proves it.
    doc['ability_scores_and_statistics']['hit_points']['maximum'] = 63
    return doc

