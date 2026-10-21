"""Concrete GM scene input through the public, persisted table fact producer."""
from tests.worker2_support import OWNER, ALLY


def duty(combat, table, mid, *, kind='ally', subject=ALLY, record_id=None,
         meaningful=True, status='defending', witnesses=None, distance=5, pressures=(),
         power_states=(), appeared_round=None):
    engine = combat._load_session(mid).engine
    point = engine.state.actors[subject].position.model_dump(mode='json') if subject in engine.state.actors else {'x': 4, 'y': 6}
    document = {
        'record_id': record_id or subject, 'subject_id': subject,
        'subject_name': engine.state.actors[subject].display_name if subject in engine.state.actors else 'The eastern gate',
        'subject_kind': 'creature' if kind in {'ally', 'helpless_creature'} else 'object' if kind == 'object' else 'location',
        'position': point, 'source_reference': 'campaign:gate-defense-scene:GM-assessment',
        'witness_ids': witnesses if witnesses is not None else [OWNER],
        'valid_through_round': engine.state.round_number + 10, 'answers': {},
        'defenses': [{'defender_id': OWNER, 'subject_kind': kind, 'meaningful': meaningful,
                      'status': status, 'reason': 'The bearer holds the eastern approach against the invading creature.',
                      'appeared_round': appeared_round or engine.state.round_number,
                      'maximum_distance_ft': distance, 'requires_sight': True}],
        'subject_pressures': list(pressures), 'power_states': list(power_states),
    }
    result = table.record_fact(mid, document, expected_state_version=engine.state.state_version)
    assert result['status'] == 'COMMITTED'
    return document
