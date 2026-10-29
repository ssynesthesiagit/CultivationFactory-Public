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


def test_a_pair_enemy_override_counts_as_hostile_damage(monkeypatch):
    """Same team, pair relation ENEMY: the damage is hostile in the printed sense.

    ``relations.py`` tells callers to ask ``relation()``, never to compare team
    identifiers. Heavenly Body's generator requires a hostile attacker, so a
    creature turned against its own side (a GM relation override) must reach
    ``generate`` and let the row's own hook decide. Fails when the trigger only
    compares team identifiers.
    """
    from combat import relations

    source = SimpleNamespace(team_id="team:heroes", entity_id="source")
    target = SimpleNamespace(team_id="team:heroes", entity_id="target")
    engine = SimpleNamespace(state=SimpleNamespace(actors={"source": source, "target": target}))
    event = SimpleNamespace(actor_id="source", target_ids=("target",), payload={
        "hp_damage": 1, "temporary_hp_absorbed": 0,
    })
    calls = []
    monkeypatch.setattr(pressure, "generate", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(relations, "relation", lambda *args: relations.ENEMY)

    pressure.after_damage(engine, event)

    assert len(calls) == 1
    assert calls[0][1]["event"] is event
    assert calls[0][1]["require_opt_in"] is True


def test_non_heavenly_row_gains_nothing_for_same_team_enemy_override(monkeypatch):
    """The same-team ENEMY exception is reserved for opted-in rows."""
    from combat import relations

    source = SimpleNamespace(team_id="team:heroes", entity_id="source")
    target = SimpleNamespace(
        team_id="team:heroes", entity_id="target", active=True, current_hp=5,
        resources={"foundation": 0}, resource_maximums={"foundation": 1},
        turn_flags={},
    )
    row = {"block": "generate", "feature_id": "legacy.row", "resource_id": "foundation",
           "on": ["damaged"], "max": 1}
    state = SimpleNamespace(actors={"source": source, "target": target}, round_number=1,
                            current_actor_id="source")
    engine = SimpleNamespace(state=state, typed_passive_rows={"target": [row]})
    engine._gain_resource = lambda actor, resource, amount, source: actor.resources.__setitem__(
        resource, actor.resources[resource] + amount)
    event = SimpleNamespace(actor_id="source", target_ids=("target",), payload={
        "hp_damage": 1, "temporary_hp_absorbed": 0,
    })
    monkeypatch.setattr(relations, "relation", lambda *args: relations.ENEMY)
    from combat import feature_availability
    monkeypatch.setattr(feature_availability, "available", lambda *args: True)
    from combat.ext import ext
    monkeypatch.setattr(ext, "run_strict", lambda *args: [])

    pressure.after_damage(engine, event)

    assert target.resources["foundation"] == 0


def test_same_team_allies_never_generate_a_resource(monkeypatch):
    """An ally on the same side is not a hostile attacker: no generation."""
    from combat import relations

    source = SimpleNamespace(team_id="team:heroes", entity_id="source")
    target = SimpleNamespace(team_id="team:heroes", entity_id="target")
    engine = SimpleNamespace(state=SimpleNamespace(actors={"source": source, "target": target}))
    event = SimpleNamespace(actor_id="source", target_ids=("target",), payload={
        "hp_damage": 1, "temporary_hp_absorbed": 0,
    })
    calls = []
    monkeypatch.setattr(pressure, "generate", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(relations, "relation", lambda *args: relations.ALLY)

    pressure.after_damage(engine, event)

    assert calls == []
