"""Pure additional eligibility for zone rules, triggers and terrain."""
from . import ext


def allowed(engine, zone, actor, spec):
    for reply in ext.run_strict('zone_recipient_allowed', engine, zone, actor, spec):
        if type(reply) is not bool:
            raise ValueError('zone_recipient_allowed must return None or a boolean')
        if not reply:
            return False
    return True
