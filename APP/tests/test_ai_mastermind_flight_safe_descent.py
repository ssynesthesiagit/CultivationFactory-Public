"""A measured, safe flight route remains usable while an expiring grant is active.

The regression exercises native menu/context/controller behavior for both tiers;
no flight forecast may treat the 'evaluated' marker itself as danger.
"""
import pytest

from combat.gate4_controller import _flight_descent
from tests.ai_tiers_native_support import OWNER, context_for, fight, selected


@pytest.mark.parametrize("tier", ["MASTERMIND", "TRICKY"])
def test_safe_expiring_flight_has_finite_landing_cost_without_forced_descent(
        tmp_path, monkeypatch, tier):
    from tests.test_ai_mastermind import Offline
    from combat import menu_rank

    client = Offline()
    monkeypatch.setattr(menu_rank, "default_client", lambda: client)
    monkeypatch.setattr(menu_rank, "_CLIENT", client)
    combat, _, session = fight(tmp_path, ["AIR_BASE_WIND_LASH"], flight=True,
                               foe_at={"x": 9, "y": 5})
    engine = session.engine
    actor = engine.state.actors[OWNER]
    # Replace permanent sheet flight with a one-turn native grant.
    actor.fly_speed_ft = 0
    actor.hover = False
    actor.position = actor.position.model_copy(update={"z": 4})
    engine._apply_condition(actor, "condition:typed.test_flight", "test:safe-descent",
                            OWNER, expires_on=f"END_OF_TURN_AT:{OWNER}:{actor.turns_started + 1}",
                            data={"fly_speed_ft": 30, "flight_hover": 1})
    actor.ai_tier = tier

    context = context_for(combat, session)
    moves = [candidate for candidate in context.legal_candidates if candidate.kind == "MOVE"]
    assert moves
    assert all(candidate.metadata["flight_tactics"]["landing_cost_ft"] == 20
               for candidate in moves)
    assert all(candidate.metadata["flight_tactics"]["future_movement_ft"] == [30]
               for candidate in moves)
    assert all(not candidate.metadata["flight_tactics"]["flight_ending"] for candidate in moves)
    assert all(not _flight_descent(candidate) for candidate in moves)

    _, chosen = selected(context)
    assert chosen.kind != "MOVE" or chosen.destination.z > 0
