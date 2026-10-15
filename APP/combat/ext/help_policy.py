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


def delivered(engine, helper, recipient, source, *, kind, target_id=None):
    """Notify consumers only after real Help assistance has been delivered.

    This is a producer notification, never an eligibility query. Specialized
    Help effects and ordinary Help share the same actor/recipient contract.
    Native event persistence/replay owns the receipt; no flags fabricate Help.
    """
    from . import run_strict
    if not any(run_strict('help_actions_enabled', engine)):
        return
    if engine.state.actors.get(helper.entity_id) is not helper or engine.state.actors.get(recipient.entity_id) is not recipient:
        raise ValueError('Help requires live native actors')
    if kind not in ('attack', 'check'):
        raise ValueError('Help delivery must name attack or check assistance')
    engine._append_event('HELP_DELIVERED', source, actor_id=helper.entity_id,
        target_ids=(recipient.entity_id,), payload={'kind': kind, **({'assisted_target_id': target_id} if target_id else {})})
    run_strict('help_delivered', engine, helper, recipient, source, kind)
