"""Heaven-Kicking consent only matters when a forced path can reach 10 feet."""
from types import SimpleNamespace

from combat.ext import needle
from combat.ext.sky_treading import kick_movement_consent


def test_consent_prompt_is_gated_by_possible_qualifying_distance(monkeypatch):
    actor = SimpleNamespace(entity_id="owner", display_name="Kicker")
    engine = SimpleNamespace(
        typed_passive_rows={"owner": [{"block": "path_rider", "kind": "sky_treading", "role": "kick"}]},
        events=[], grid=SimpleNamespace(square_size_ft=5), action_catalog={}, _active_action_source_id=None,
        state=SimpleNamespace(round_number=1, current_actor_id="owner"),
    )
    calls = []
    monkeypatch.setattr(needle, "ask", lambda *args, **kwargs: calls.append(kwargs) or ["accept"])
    monkeypatch.setattr(needle, "checkpoint_id", lambda *args: "checkpoint")

    assert kick_movement_consent(engine, actor, 5, "shove", None) is None
    assert calls == []
    assert kick_movement_consent(engine, actor, 10, "shove", None) is True
    assert calls and calls[0]["name"] == "Heaven-Kicking Leg"
