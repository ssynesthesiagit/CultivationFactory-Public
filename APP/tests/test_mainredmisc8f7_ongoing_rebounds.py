"""Focused regression for Ten Thousand Rebounds' ongoing-damage exclusion."""

from tests.test_riders_lane10 import test_ten_thousand_rebounds_excludes_ongoing_damage_but_answers_a_fresh_blow


def test_ongoing_tick_does_not_consume_rebound_and_fresh_hit_does():
    test_ten_thousand_rebounds_excludes_ongoing_damage_but_answers_a_fresh_blow()
