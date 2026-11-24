"""Regression for per-level training descriptors."""
from character_creation.creative_controller.linear_walk import _step_descriptors
from character_creation.creative_controller import CommittedState


def test_training_timeline_uses_each_level_count():
    contract = {"target_cl": 3, "required_choices_by_cl": {"1": 1, "2": 2, "3": 1}}
    envelope = {"creation_training_contract": contract, "ordinary_talent_count": 3}
    state = CommittedState(trained_choices=[{"cl": 1, "slot": 1}])
    ids = [row[0] for row in _step_descriptors({}, envelope, state)]
    assert "ordinary_talent:1" in ids, f"observed descriptors: {ids}"
    assert "creation_training:1:2" not in ids, f"observed descriptors: {ids}"
