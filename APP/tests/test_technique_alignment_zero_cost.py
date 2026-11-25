from types import SimpleNamespace

import pytest

from combat.technique_alignment import powering_resource


QI = "resource:core.qi"
STAMINA = "resource:core.stamina"


@pytest.mark.parametrize(
    ("explicit_path", "primary_path", "expected"),
    [(QI, STAMINA, QI), (STAMINA, QI, STAMINA)],
)
def test_zero_cost_explicit_path_beats_other_primary_path(
    explicit_path, primary_path, expected
):
    action = SimpleNamespace(costs=((explicit_path, 0),))
    owner_sheet = {
        "ability_scores_and_statistics": {
            "primary_resource": {
                "name": "Qi" if primary_path == QI else "Stamina"
            }
        }
    }

    assert powering_resource(action, owner_sheet) == expected
