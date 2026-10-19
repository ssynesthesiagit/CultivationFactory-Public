"""Regression for the Second Furnace's printed PB-sized journey reinforcement."""

from types import SimpleNamespace

from combat.ext import furnace_runtime as furnace
from combat.ext.furnace_journey import options, command


def test_journey_seed_reinforcement_grants_and_advertises_proficiency_bonus(monkeypatch):
    aid = "actor:factory.seed-owner"
    actor = {
        "name": "Furnace owner",
        "position": {"x": 0, "y": 0},
        "incapacitated": 0,
        "resources": {},
        "encounter_snapshot": {"temporary_hp": 0},
        "source_states": {
            furnace.PARENT: {"seed_reinforcement_pending": 1},
        },
        "bundle": {
            "action_catalog": [{
                "parameters": {
                    "typed": {
                        "source": furnace.ENGINE,
                        "numbers": {"pb": 4, "cl": 18},
                    },
                },
            }],
            "owned_ids": [furnace.PREFIX + "demon_seed_overdraw"],
        },
    }
    session = SimpleNamespace(
        state={"phase": "travel", "actors": {aid: actor}},
        adjacent=lambda _aid: [],
        clock=lambda: 0,
        emit=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(furnace, "publish", lambda *_args: None)

    offered = options(session, aid)
    choice = next(row for row in offered if row["payload"] == {"benefit": "temp_hp"})
    assert "Gain 4 Temporary Hit Points" in choice["label"]

    command(session, aid, "furnace_seed_reinforcement", choice["payload"])
    assert actor["encounter_snapshot"]["temporary_hp"] == 4
    assert furnace.PARENT not in actor["source_states"] or not actor["source_states"][furnace.PARENT].get("seed_reinforcement_pending")
