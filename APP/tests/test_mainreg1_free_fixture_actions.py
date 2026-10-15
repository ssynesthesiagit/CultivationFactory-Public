"""Post-compile free actions remain available through the native table contract."""

from tests.test_a2_athletics import commit, game_for
from tests.auto8f1_table_support import OWNER, candidate_id, reload_identical


def test_postcompile_free_action_commits_without_spending_turn_economy(tmp_path):
    game = game_for(tmp_path, [])
    candidate_id(game['menu'](), 'Lie down', exact=True)
    before = game['stored_engine']().state.actors[OWNER]
    commit(game, 'Lie down')
    after = game['stored_engine']().state.actors[OWNER]
    assert any(c.condition_id == 'condition:typed.prone' for c in after.conditions.values())
    assert after.action_available == before.action_available
    assert after.bonus_action_available == before.bonus_action_available
    candidate_id(game['menu'](), 'Close eyes', exact=True)
    reload_identical(game['combat'], game['match_id'], game['userdata'])
