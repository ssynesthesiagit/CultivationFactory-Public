from types import SimpleNamespace

import pytest

from combat import pressure


@pytest.mark.parametrize("source_team,target_team,relation", [
    ("team:neutral", "team:heroes", "ENEMY"),
    ("team:raiders", "team:heroes", "ALLY"),
])
def test_damage_resource_trigger_keeps_legacy_different_team_rule(
        monkeypatch, source_team, target_team, relation):
    """Non-Heavenly pressure rows keep the pre-relation-table damage trigger."""
    source = SimpleNamespace(team_id=source_team)
    target = SimpleNamespace(team_id=target_team)
    engine = SimpleNamespace(state=SimpleNamespace(actors={"source": source, "target": target}))
    event = SimpleNamespace(actor_id="source", target_ids=("target",), payload={
        "hp_damage": 1, "temporary_hp_absorbed": 0,
    })
    calls = []
    monkeypatch.setattr(pressure, "generate", lambda *args, **kwargs: calls.append((args, kwargs)))
    from combat import relations
    monkeypatch.setattr(relations, "relation", lambda *args: relation)

    # These are intentionally legacy team differences even when the relation
    # system would report a non-enemy or a different-team alliance.
    pressure.after_damage(engine, event)

    assert len(calls) == 1
    assert calls[0][0][1:3] == (target, "damaged")
    assert calls[0][1]["event"] is event
