"""Regressions for attainment policy and Grow's saved Path projection."""
from character_creation.path_attainment import INITIAL_PATH_ATTAINMENT_POLICY
from character_creation.creative_controller.linear_menus import CommittedState, _ability_priority
from tests.test_creator_ability_priority import BODY, QI, PATH_ROWS
from tests.test_grow4a_multipath import _add_payload, _reach
from tests.test_grow3_levelup import PID, service


def test_equal_attainment_ignores_uneven_representatives():
    request = {"server_owned_authority": {"initial_path_attainment_policy": INITIAL_PATH_ATTAINMENT_POLICY}}
    envelope = {"frozen_owner_target_cl": 8, "choices_by_slot": {"path_choice": PATH_ROWS}}
    state = CommittedState(by_slot={"path_choice": [BODY, QI]})
    for cl in range(1, 9):
        state = state.with_path_progression(cl, BODY if cl in (4, 8) else QI)
    assert _ability_priority(state, request, envelope)[:2] == ("CON", "INT")
    assert _ability_priority(state, {}, envelope)[:2] == ("INT", "CON")


def test_saved_grow_path_appears_in_table_sheet_payload(tmp_path):
    s = service(tmp_path, BODY)
    assert s.sheet(PID)["summary"]["path_key_abilities"] == [
        {"path": "Body Refining", "key_ability": "CON", "modifier": 3},
    ]
    _reach(s, 5)  # Includes the CL4 +2 CON increase.
    s.level_up(PID, _add_payload(s.advancement(PID), QI))
    summary = service(tmp_path, BODY).sheet(PID)["summary"]
    assert summary["path_key_abilities"] == [
        {"path": "Body Refining", "key_ability": "CON", "modifier": 4},
        {"path": "Qi Cultivation", "key_ability": "INT", "modifier": 3},
    ]
    assert any(row["path"] == "Qi Cultivation" for row in summary["path_entries"])
