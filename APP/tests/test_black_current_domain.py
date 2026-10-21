"""Black River Domain decisions use admitted source actors and table replay."""
import pytest
from combat.ext import black_current_walker as bc
from tests.test_black_current_parent import fixture, settle, action
from tests.test_c2_review import until_turn, reload
from tests.test_riders_c2 import ME, ATK, ALLY


def recipient_turn(table, mid):
    """Decline optional turn-start steps while advancing to the recipient."""
    for _ in range(10):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == ALLY:
            return
        settle(table, mid, menu["end_turn"])
    pytest.fail("recipient never received its native turn")


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


@pytest.mark.parametrize("designated", [True, False])
def test_allied_current_native_surface_movement_is_designated_and_domain_bounded(tmp_path, designated):
    from combat.gate2_runtime_models import Position
    from combat.terrain_materials import supported
    _, table, mid = fixture(tmp_path, cl=18, owner_at=(3, 8), ally_at=(3, 6, 1), surface="water")
    until_turn(table, mid, ME)
    settle(table, mid, action(table, mid, "Procession of the Black River"), {
        "choice:needle.black_current.domain_recipients": ALLY if designated else ME,
    })
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    recipient_turn(table, mid)
    before = reload(tmp_path, mid)
    actor = before.state.actors[ALLY]
    end = Position(x=1, y=6, z=1)
    assert supported(before, actor, end) is designated
    assert not supported(before, actor, Position(x=18, y=6, z=1)), "actual water outside the Domain grants no support"
    moves = [c for c in before.legal_candidates() if c.kind == "MOVE" and c.destination == end]
    assert bool(moves) is designated
    if designated:
        settle(table, mid, moves[0].candidate_id)
        assert reload(tmp_path, mid).state.actors[ALLY].position == end
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
        assert reload(tmp_path, mid).state.actors[ALLY].position == Position(x=1, y=6)


def test_allied_current_native_passage_is_free_and_never_an_occupied_endpoint(tmp_path):
    from combat.gate2_runtime_models import Position
    from combat.granted_movement import native_path_cost
    _, table, mid = fixture(tmp_path, cl=18, owner_at=(2, 6), ally_at=(3, 6), foe_at=(10, 8))
    until_turn(table, mid, ME)
    settle(table, mid, action(table, mid, "Procession of the Black River"), {
        "choice:needle.black_current.domain_recipients": ALLY,
    })
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    recipient_turn(table, mid)
    before = reload(tmp_path, mid)
    actor = before.state.actors[ALLY]
    path = tuple(Position(x=x, y=6) for x in (3, 2, 1))
    assert native_path_cost(before, actor, path) == 10
    assert not any(c.kind == "MOVE" and c.destination == Position(x=2, y=6) for c in before.legal_candidates())
    # The explicit native route exercises the occupied allied cell, rather
    # than trusting the automatic pathfinder to select this equal-cost path.
    menu = table.state(mid)["menu"]
    waypoints = [p.model_dump(mode="json") for p in path]
    preview = table.preview_move_path(mid, menu["decision_id"], menu["state_version"], ALLY, waypoints)
    assert preview["authoritative_state_unchanged"]
    candidate = preview["candidate"]
    result = table.commit_move_path(mid, candidate["candidate_id"], menu["decision_id"], menu["state_version"], ALLY, waypoints)
    assert result["status"] == "COMMITTED", result
    after = reload(tmp_path, mid)
    assert after.state.actors[ALLY].position == path[-1]


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


@pytest.mark.parametrize("automatic,answer", [(False, "accept"), (False, "refuse"), (True, "accept")])
def test_tributary_exchange_uses_actual_rooftop_volumes_and_recipient_consent(tmp_path, automatic, answer):
    combat, table, mid = fixture(tmp_path, cl=18, ally_at=(2, 5, 2), vertical_wall=True)
    until_turn(table, mid, ME)
    settle(table, mid, action(table, mid, "Procession of the Black River"))
    if automatic:
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode="LOCAL_AUTO")
    before = reload(tmp_path, mid)
    prompts = settle(table, mid, action(table, mid, "Ten Thousand Tributaries: Exchange two creatures", ME), {
        "choice:needle.black_current.exchange2": ALLY,
        "choice:willing.consent": answer,
    })
    after = reload(tmp_path, mid)
    accepted = automatic or answer == "accept"
    assert after.state.actors[ME].position == before.state.actors[ALLY if accepted else ME].position
    assert after.state.actors[ALLY].position == before.state.actors[ME if accepted else ALLY].position
    consent = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:willing.consent"]
    assert bool(consent) is not automatic
    if consent:
        assert consent[0]["context"]["reactor_id"] == ALLY
    assert after.state.actors[ME].resources[bc.RESONANCE] == before.state.actors[ME].resources[bc.RESONANCE]
    assert bool(after.state.actors[ME].turn_flags.get("black_river_tributary")) is accepted
    offered = any(c.source_definition_id.endswith("black_river_tributary.exchange") for c in after.legal_candidates())
    assert offered is (not accepted), "a refused offer performs no operation and leaves the legal choice reachable"


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
