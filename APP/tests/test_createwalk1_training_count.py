"""Guided creation must interleave each CL's training and ordinary Talent."""
import pytest

from character_creation.creative_controller import CommittedState
from character_creation.creative_controller.linear_walk import LinearWalkError, commit_option, next_step
from creation_training_authority import CREATION_TRAINING_MAX_PER_CL
from tests.creation_training_support import _menu_fixture, _route


@pytest.mark.parametrize("counts", [(1, 2, 1), (3, 3, 3)])
def test_training_timeline_uses_each_level_count(counts):
    request, envelope, routes = _menu_fixture(target_cl=3, required=3)
    contract = envelope["creation_training_contract"]
    if counts[0] != CREATION_TRAINING_MAX_PER_CL:
        contract["power_band"] = "standard"
        del contract["required_choices_per_cl"]
        contract["required_choices_by_cl"] = {str(i): n for i, n in enumerate(counts, 1)}
    request.pop("owner_planning_preferences", None)
    envelope["ordinary_talent_count"] = 3
    # Supply enough distinct legal synthetic talents for all training and
    # ordinary choices, regardless of the order the walk presents them.
    for i in range(20):
        name = f"talent.synthetic{i:02}"
        routes[name] = _route(name, content_type="talent", choice_type="known_sphere_talent", owning_sphere_id="sphere.z")
        envelope["choices_by_slot"]["advancement_skeleton"][name] = {"choice_id": name, "name": name, "content_type": "talent"}
        envelope["allowed_choices_by_slot"]["advancement_skeleton"].append(name)
        envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"][name] = {
            "authority_complete": True,
            "allowed_kinds": ["creation_training_talent_acquisition", "level_talent_acquisition", "new_sphere_bonus_talent_acquisition"],
            "allowed_channels": ["creation-training-known-sphere-talent", "level-choice", "new-sphere-bonus"],
            "sphere_id": "sphere.z",
        }
    state = CommittedState.empty().with_bounded("identity", {"name": "Example", "title": "Student", "concept": "Training."})
    events, seen = [], []
    for _ in range(100):
        try:
            step = next_step(request, envelope, state, events)
        except LinearWalkError as exc:
            pytest.fail(f"walk failed: {exc.code} {exc.details}; steps={seen}")
        if step.action == "COMPLETE":
            break
        seen.append(step.step_id)
        if step.action == "AUTOCOMMITTED":
            state = step.committed
            events.append(step.event)
        else:
            options = [o for o in step.options if not o.is_continuation and o.choice_ids]
            assert options, f"no selectable option at {step.step_id}; steps={seen}"
            # Choose the sphere with a plentiful supply of talents.
            option = next((o for o in options if "sphere.z" in o.choice_ids), options[0])
            state = commit_option(step.menu, option.option_id, state)
            events.append({"event_type": "STEP_COMMITTED", "step_id": step.step_id})
    else:
        pytest.fail(f"walk did not finish; steps={seen}")
    for cl, count in enumerate(counts, 1):
        training = [s for s in seen if s.startswith(f"creation_training:{cl}:")]
        assert training == [f"creation_training:{cl}:{slot}" for slot in range(1, count + 1)], f"steps={seen}"
        assert seen.index(f"ordinary_talent:{cl}") == seen.index(training[-1]) + 1, f"steps={seen}"
        assert sum(row["cl"] == cl for row in state.trained_choices) == count, f"steps={seen}; rows={state.trained_choices}"
        assert str(cl) in state.ordinary_by_cl, f"steps={seen}; talents={state.ordinary_by_cl}"
