"""Native observational receipts must replay without mutating combat state."""
import pytest

from combat.gate2_runtime_models import CombatEvent
from combat.gate3_reducer import Gate3EventReducer
from tests.worker2_support import fixture, reload, OWNER

RECEIPTS = (
    'ATTACK_DECLARED', 'CONTEST_DECLARED', 'MOVEMENT_BEGUN',
    'MOVEMENT_STEP_COMMITTED', 'SPEECH_BEGUN', 'SPEECH_FINISHED',
    'HELP_DELIVERED', 'CONTESTED_ATTACK_ROLLED', 'CONTESTED_ATTACK_FAILED',
)


@pytest.mark.parametrize('kind', RECEIPTS)
def test_committed_receipt_only_advances_the_replay_journal(tmp_path, kind):
    _, _, mid = fixture(tmp_path, [])
    before = reload(tmp_path, mid).state
    event = CombatEvent(sequence=before.event_sequence + 1,
        state_version=before.state_version, event_type=kind,
        source_definition_id='system:combat.receipt_regression',
        trigger_or_intent_id='receipt-regression', transaction_id='receipt-regression',
        actor_id=OWNER, payload={})
    restored = Gate3EventReducer().apply_events(before, [event.model_dump(mode='json')])
    expected = before.model_copy(deep=True)
    expected.event_sequence += 1
    assert restored.model_dump(mode='json') == expected.model_dump(mode='json')


def test_unknown_journal_receipt_is_still_rejected(tmp_path):
    _, _, mid = fixture(tmp_path, [])
    before = reload(tmp_path, mid).state
    event = CombatEvent(sequence=before.event_sequence + 1,
        state_version=before.state_version, event_type='UNREGISTERED_RECEIPT',
        source_definition_id='system:combat.receipt_regression',
        trigger_or_intent_id='receipt-regression', transaction_id='receipt-regression', actor_id=OWNER)
    with pytest.raises(ValueError, match='unsupported reducer event type'):
        Gate3EventReducer().apply_events(before, [event.model_dump(mode='json')])
