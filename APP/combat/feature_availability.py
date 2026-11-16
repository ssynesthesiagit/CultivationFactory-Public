"""Default-inert runtime access for compiled features.

Shared by Foundation generation, conversions, and expression consumers.
Ownership remains the compiler's responsibility. Providers may only veto an
owned feature; this query cannot grant a row, resource, stage or expression.
"""


def available(engine, actor, feature_id):
    from . import ext
    return False not in ext.run_strict('feature_available', engine, actor, feature_id)
