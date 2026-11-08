"""Regression for a grapple ending when its source becomes Incapacitated."""

from tests.hunt51_grapple_support import fight, grapple, on_turn, send, verify_reloaded


def test_stunned_grappler_releases_hold_on_condition_event(tmp_path):
    user, service, table, match, ids = fight(tmp_path, "stunned-grappler", heavenquake=True)
    on_turn(table, match, ids[0])
    send(table, match, grapple(ids[2]))
    send(table, match)
    on_turn(table, match, ids[3])
    send(table, match, lambda option: "One-Inch Heavenquake" in str(option.get("label", ""))
         and option.get("target_ids") == [ids[0]])
    engine = service._load_session(match).engine
    assert any(row.condition_id == "condition:typed.stunned" for row in engine.state.actors[ids[0]].conditions.values())
    assert not any(row.condition_id == "condition:typed.grappled" for row in engine.state.actors[ids[2]].conditions.values())
    verify_reloaded(user, service, match)
