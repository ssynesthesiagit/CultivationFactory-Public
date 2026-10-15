"""Source-owned typed input on an actual accepted native intent.

This transports selections/declarations that cannot be enumerated as fixed
option IDs. It grants no fact, feature, target or activation authority. Each
source must uniquely validate its payload against the actual actor, candidate
and state. Unknown sources reject atomically. Values use the shared fact
admission's bounded integer/string/document representation; no scripts,
callbacks, floats or client-supplied mechanical event receipts are admitted.
"""
from . import ext
from .fact_consent_admission import plain, canonical


def validate(engine, actor, candidate, values):
    if (not isinstance(values, dict) or len(values) > 16 or not plain(values)
            or len(canonical(values)) > 16000):
        raise ValueError('Source choices need bounded typed data.')
    for source, value in values.items():
        if not source or len(source) > 240 or not isinstance(value, dict):
            raise ValueError('Choose a source and its structured choice payload.')
        replies = ext.run_strict('source_choice_admission', engine, actor, candidate, source, value)
        if len(replies) != 1 or replies[0] is not True:
            raise ValueError('This source does not admit that choice for the accepted action.')
