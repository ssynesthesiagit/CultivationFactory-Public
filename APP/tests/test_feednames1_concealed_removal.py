"""A concealed removal's full receipt must not become public history."""
from combat.private_information import event_audience


def test_concealed_removal_audience_is_holder():
    event = {"event_type": "CONDITION_REMOVED", "target_ids": ["holder"],
             "payload": {"concealed": True, "gate3_condition_before": {
                 "data": {"label": "private answer", "record": "secret value"}}}}
    assert event_audience(None, event) == frozenset({"holder"})
    event["payload"].pop("concealed")
    assert event_audience(None, event) is None
