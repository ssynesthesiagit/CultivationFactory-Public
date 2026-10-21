"""Persist character derivations of already committed, audience-scoped facts.

Table facts remain the authority. Providers return effects bound to their
native actor/acquisition; this adapter adds journal proof and reuses the table
advancement store. It never accepts a request's success or payment flag.
Settlement is idempotent and can be retried from the journal after an I/O error.
"""
from . import ext, table_advance
from .canonical import canonical_sha256


def settle(table, match_id, *, engine=None):
    from .tabletop_service import FACTORY_PREFIX
    if engine is None:
        engine = table.combat._load_session(match_id).engine
    recorded, pending = 0, []
    for event in engine.events:
        if event.event_type != 'TABLE_FACT_RECORDED':
            continue
        document = event.payload['fact']
        for proposals in ext.run_strict('character_effects_from_fact', engine, event):
            for proposal in proposals:
                state = proposal['power_state']
                actor_id = state['actor_id']
                if (state not in document.get('power_states', []) or actor_id not in document['witness_ids']
                        or actor_id not in engine.state.actors):
                    raise ValueError('A character effect must be part of its actual native fact receipt.')
                if not actor_id.startswith(FACTORY_PREFIX):
                    continue
                project_id = actor_id.removeprefix(FACTORY_PREFIX)
                acquisition = proposal['initial_acquisition_id']
                identity = canonical_sha256([actor_id, state['power_id'], acquisition, state['state']])
                receipt = {'id': identity, 'power_state': state, 'initial_acquisition_id': acquisition,
                    'proof_match_id': match_id, 'proof_event_sequence': event.sequence,
                    'proof_sha256': canonical_sha256(event.model_dump(mode='json'))}
                try:
                    saved = table_advance.normalized(table.buttons.get(project_id).get('advancement'))
                    if not any(r.get('id') == identity for r in saved['source_effects']):
                        saved['source_effects'].append(receipt)
                        table.buttons.save_advancement(project_id, saved)
                        recorded += 1
                except OSError:
                    pending.append(project_id)
    return {'status': 'PENDING' if pending else 'RECORDED', 'recorded': recorded,
            **({'message': 'The story effect resolved, but its character record could not be saved. '
                          'Retry recording the committed character effects before starting another scene.',
                'project_ids': sorted(set(pending))} if pending else {})}


def apply(sheet, receipts):
    """Source providers project durable receipts onto a copy, never a live fight."""
    for receipt in receipts:
        if (not receipt.get('proof_sha256') or type(receipt.get('proof_event_sequence')) is not int
                or not receipt.get('initial_acquisition_id')):
            raise ValueError('Character effects require their committed native source proof.')
        sheet = ext.transform('character_source_effect', sheet, receipt)
    return sheet
