"""Native resolution of an established ordinary narrative coincidence.

Used by table scene declarations and source-authored effects. This seam can
refuse the coincidence, never create damage, equipment loss or a new obstacle.
"""
from . import ext


def favorable_coincidence(engine, beneficiary, source_id):
    return not ext.any_false('ordinary_favorable_coincidence', engine, beneficiary, source_id)
