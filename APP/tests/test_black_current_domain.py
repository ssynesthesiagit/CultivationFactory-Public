"""Black River Domain decisions use admitted source actors and table replay."""
import pytest
from combat.ext import black_current_walker as bc
from tests.test_black_current_parent import fixture, settle
from tests.test_c2_review import until_turn, action, reload
from tests.test_riders_c2 import ME, ATK, ALLY


def test_domain_designates_cross_team_recipient_and_declared_current(tmp_path):
    _, table, mid = fixture(tmp_path, cl=18)
    until_turn(table, mid, ME)
    before = reload(tmp_path, mid)
    prompts = settle(table, mid, action(table, mid, "Procession of the Black River"), {
        "choice:needle.black_current.domain_recipients": ATK,
        "choice:needle.black_current.domain_current": "east",
    })
    assert {"choice:needle.black_current.domain_recipients", "choice:needle.black_current.domain_current"} <= {
        p["context"]["reaction_source_id"] for p in prompts}
    after = reload(tmp_path, mid)
    zone = bc._domain(after, after.state.actors[ME])
    assert zone.trigger_profile["black_river_recipients"] == [ATK]
    assert zone.trigger_profile["black_river_current"] == "east"
    assert after._effective_speed(after.state.actors[ATK]) == before._effective_speed(before.state.actors[ATK]) + 10
    assert after._effective_speed(after.state.actors[ALLY]) == before._effective_speed(before.state.actors[ALLY])


def test_domain_counts_per_cell_spiritual_movement_cumulatively_once_per_round(tmp_path):
    _, table, mid = fixture(tmp_path, cl=18)
    until_turn(table, mid, ME)
    settle(table, mid, action(table, mid, "Procession of the Black River"), {
        "choice:needle.black_current.domain_recipients": ME,
        "choice:needle.black_current.domain_current": "clockwise",
    })
    before = reload(tmp_path, mid)
    settle(table, mid, action(table, mid, "River-Cut Passage: Psychic"), {"choice:needle.river_cut_route": "cell:0,6"})
    after = reload(tmp_path, mid)
    assert after.state.actors[ME].temporary_hp == 2 * before.state.actors[ME].proficiency_bonus


def test_tributary_cross_team_recipient_can_refuse_transport(tmp_path):
    _, table, mid = fixture(tmp_path, cl=18)
    until_turn(table, mid, ME)
    settle(table, mid, action(table, mid, "Procession of the Black River"))
    before = reload(tmp_path, mid)
    prompts = settle(table, mid, action(table, mid, "Ten Thousand Tributaries: Move in the current", ATK), {
        "choice:needle.tributary_move": "cell:5,6",
        "choice:willing.consent": "refuse",
    })
    consent = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:willing.consent"]
    assert consent and consent[0]["context"]["reactor_id"] == ATK
    assert reload(tmp_path, mid).state.actors[ATK].position == before.state.actors[ATK].position


@pytest.mark.parametrize("direction,expected_x", [("current", 6), ("reverse", 2)])
def test_hostile_banks_uses_declared_direction_and_target_specific_reverse(tmp_path, direction, expected_x):
    _, table, mid = fixture(tmp_path, cl=18)
    until_turn(table, mid, ME)
    settle(table, mid, action(table, mid, "Procession of the Black River"), {
        "choice:needle.black_current.domain_recipients": ME,
        "choice:needle.black_current.domain_current": "east",
    })
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    until_turn(table, mid, ATK)
    before = reload(tmp_path, mid)
    move = next(c for c in before.legal_candidates() if c.kind == "MOVE" and c.destination.x == 4 and c.destination.y == 7)
    settle(table, mid, move.candidate_id, {"choice:needle.black_current.bank_current": direction})
    after = reload(tmp_path, mid)
    assert (after.state.actors[ATK].position.x, after.state.actors[ATK].position.y) == (expected_x, 7)
    assert after.state.actors[ATK].current_hp < before.state.actors[ATK].current_hp
