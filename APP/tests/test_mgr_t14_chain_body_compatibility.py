"""Only the existing C7 Chain Body cases, selected as a public-CI whole file."""
import pytest
from tests import test_riders_c7 as c7


@pytest.mark.parametrize('case', [
    c7.test_meridian_tether_on_an_unarmed_hit_limits_the_targets_moves_to_20_feet,
    c7.test_chain_body_integration_constitution_variant_and_on_turn_reach,
    c7.test_drag_the_heavens_needs_a_tether_and_pulls_on_a_failed_save,
    c7.test_thousand_link_adds_2d8_against_a_tethered_creature_and_makes_its_ground_difficult,
])
def test_existing_chain_body_cases(case):
    case()
