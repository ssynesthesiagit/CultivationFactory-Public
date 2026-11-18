"""Deterministic per-level counts and compatibility with sealed v1 contracts."""
from copy import deepcopy

from creation_training_authority import (
    build_creation_training_contract,
    required_choices,
    validate_creation_training_contract,
)


def test_supporting_counts_are_seeded_and_frozen():
    def build(seed, band="supporting"):
        return build_creation_training_contract({}, target_cl=10, power_band=band, seed=seed)

    first = build("project-one")
    assert not validate_creation_training_contract(first)
    assert first == build("project-one")
    assert set(first["required_choices_by_cl"].values()) <= {1, 2}
    assert set(first["required_choices_by_cl"]) == {str(i) for i in range(1, 11)}
    assert {required_choices(build(str(seed)), cl) for seed in range(20) for cl in range(1, 11)} == {1, 2}
    assert all(required_choices(build("boss", "rival/boss"), cl) == 3 for cl in range(1, 11))
    assert build("none", None)["required_choices_by_cl"] is None

    legacy = deepcopy(first)
    del legacy["required_choices_by_cl"]
    legacy["required_choices_per_cl"] = 3
    assert not validate_creation_training_contract(legacy)
    assert all(required_choices(legacy, cl) == 3 for cl in range(1, 11))
    legacy["required_choices_by_cl"] = {str(i): 2 for i in range(1, 11)}
    assert validate_creation_training_contract(legacy)
    for bad in ({"1": 1}, {str(i): True for i in range(1, 11)}, {str(i): 4 for i in range(1, 11)}):
        contract = deepcopy(first)
        contract["required_choices_by_cl"] = bad
        assert validate_creation_training_contract(contract)
