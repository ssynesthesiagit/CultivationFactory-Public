"""Whole-file CI selection of the existing Ryujin consumer regressions.

Re-export the original tests unchanged to avoid selecting unrelated families
or using node selectors that cannot route to public CI.
"""
from tests.test_a2_group_body_subpaths_6 import (
    test_cones_affect_every_creature_with_both_save_outcomes_after_reload,
    test_dragon_scales_ac_resistance_and_unarmed_rider_service,
    test_form_flight_hover_size_profiles_and_reload,
    test_storm_step_player_landing_enemy_only_and_declined_burst,
)
