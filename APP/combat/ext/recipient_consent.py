"""Recipient-owned transactional consent, shared by Predictive Step and Earth.

Unknown willingness is never inferred from teams or damage. Native Needle
answers live on the enclosing intent and replay after table commit/reload.
Manual recipients answer on any actor's turn; automatic recipients use only
the openly stated proposal and their own relation to its source.
"""
from .needle import ask, CHOICE, checkpoint_id


def willing(engine, recipient, source, feature, name, proposal, *, intent=None):
    if recipient is source:
        return True
    from ..relations import relation, ALLY
    accepted = ask(engine, intent, checkpoint_id(engine, 'recipient_consent', feature,
        source.entity_id, recipient.entity_id), recipient, CHOICE + 'recipient_consent', ['accept'],
        labels={'accept': 'Accept ' + name}, name=name + ': willingness', feature_id=feature,
        target_id=recipient.entity_id, allow_decline=True,
        default='first' if relation(engine, recipient, source) == ALLY else 'decline',
        prompt=f'{source.display_name} offers {name} to {recipient.display_name}: {proposal} Accept?',
        prompt_context={'cost': 'No cost to you'})
    return bool(accepted)
