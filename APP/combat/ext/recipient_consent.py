"""Recipient-owned transactional consent, shared by Predictive Step and Earth.

Unknown willingness is never inferred from teams or damage. Native Needle
answers live on the enclosing intent and replay after table commit/reload.
Manual recipients answer on any actor's turn; automatic recipients use only
the openly stated proposal and their own relation to its source.
"""
from types import SimpleNamespace


def willing(engine, recipient, source, feature, name, proposal, *, intent=None):
    if recipient is source:
        return True
    from ..relations import relation, ALLY
    from ..fact_consent_admission import admit_choice, digest
    intent = intent or getattr(engine, '_active_intent', None)
    scope = digest({'source': feature, 'actor': source.entity_id, 'recipient': recipient.entity_id,
                    'intent': intent.intent_id, 'event': engine.state.event_sequence, 'proposal': proposal})
    ctx = SimpleNamespace(engine=engine, intent=intent, action=SimpleNamespace(display_name=name))
    accepted = admit_choice(ctx, recipient, feature, 'willing', scope, ['accept'],
        labels={'accept': 'Accept ' + name},
        prompt=f'{source.display_name} offers {name} to {recipient.display_name}: {proposal} Accept? No cost to you.',
        expires_on='END_OF_CURRENT_TURN', readers=[source.entity_id],
        automatic_options=['accept'] if relation(engine, recipient, source) == ALLY else [])
    return accepted is not None and accepted['value'] == 'accept'


from . import hook


@hook('choice_reactors')
def recipients(engine):
    """Enroll controllers only when a sealed feature can ask its recipients."""
    if any(r.get('recipient_consent_choices') == 1 for rows in
           getattr(engine, 'typed_passive_rows', {}).values() for r in rows):
        return list(engine.state.actors)
    return []
