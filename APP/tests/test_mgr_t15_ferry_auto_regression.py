"""Automatic Ferry must answer the same known after-damage rescue as a player."""
from tests.test_mgr_t14_sol_subpath_ferry_wounded import (
    acquired, test_local_auto_ferry_answers_off_turn_without_model_server as check_auto,
)


def test_automatic_ferry_commits_known_after_damage_rescue(tmp_path, acquired):
    # With the stale generic forced-movement payload still used for admission,
    # AI's friendly-fire guard vetoes this rescue; the native assertion fails.
    check_auto(tmp_path, acquired)
