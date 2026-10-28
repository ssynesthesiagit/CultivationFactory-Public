"""Review acceptance after removing unrelated historical fixture dependencies.

Import the original cases intact. This fresh entry point lets the publisher
re-evaluate their repaired dependency closure without changing its shared cache.
"""
from tests.test_mgr_t14_goruden_aura_benefits import (
    test_cross_team_ally_gets_owner_choice_at_off_turn_benefit,
    test_radiant_fist_source_binding_cannot_grant_an_unowned_rider,
)
from tests.test_mgr_t14_goruden_resume import (
    test_fresh_and_replaced_fact_spends_combat_lifetime,
    test_acquired_commands_reach_ai_and_finish_free_preparation,
    test_acquired_aura_keeps_activation_clock_and_recipients_between_encounters,
    test_acquired_aura_uses_committed_allies_across_team_boundaries,
    test_acquired_ai_executes_family_preparation_and_finishes_its_turn,
)
