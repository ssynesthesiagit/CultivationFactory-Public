"""Shared acceptance policy for effects explicitly delivered by a Help action.

Default-inert; ordinary buffs are not Help. Producers check this before offering
or delivering assistance, including an ability's specialized Help variant.
Consumers: needle_feint, spirit_bonds, beastmastery_riders and escape_options.
"""
from . import run_strict


def allowed(engine, helper, recipient):
    """Whether the represented helper may grant Help to this recipient."""
    replies = run_strict('help_benefit_allowed', engine, helper, recipient)
    if any(type(reply) is not bool for reply in replies):
        raise ValueError('help_benefit_allowed requires a boolean')
    return not any(reply is False for reply in replies)
