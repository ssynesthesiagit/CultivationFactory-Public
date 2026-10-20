"""Regression: Journey menu for an acquired Second Furnace must build its payment options.

Before the fix, options() read the owned-feature set before it was assigned and
raised NameError for any eligible furnace owner with no pending reinforcement.
"""

from types import SimpleNamespace

from combat.ext import furnace_runtime as furnace
from combat.ext.furnace_journey import options


def _session(owned_ids, qi=8, devil=0, corruption=0):
    aid = "actor:factory.furnace-owner"
    actor = {
        "name": "Furnace owner",
        "position": {"x": 0, "y": 0},
        "incapacitated": 0,
        "resources": {furnace.QI: qi, furnace.DEVIL: devil, furnace.CORRUPTION: corruption},
        "encounter_snapshot": {"temporary_hp": 0},
        "source_states": {furnace.PARENT: {"acquired_sheet": "{}"}},
        "bundle": {
            "action_catalog": [{
                "parameters": {
                    "typed": {
                        "source": furnace.ENGINE,
                        "numbers": {"pb": 4, "cl": 18},
                    },
                },
            }],
            "owned_ids": list(owned_ids),
        },
    }
    session = SimpleNamespace(
        state={"phase": "travel", "actors": {aid: actor}},
        adjacent=lambda _aid: [],
        clock=lambda: 0,
        emit=lambda *_args, **_kwargs: None,
    )
    return session, aid


def test_acquired_furnace_owner_is_offered_engine_payment_options():
    session, aid = _session([furnace.PREFIX + "second_furnace_core",
                             furnace.PREFIX + "demon_seed_overdraw"], qi=8, devil=3)
    ids = {row["id"] for row in options(session, aid) or []}
    assert furnace.ENGINE + ":ordinary" in ids
    assert furnace.ENGINE + ":core:1" in ids
    assert furnace.ENGINE + ":seed" in ids


def test_owner_without_core_or_overdraw_gets_only_ordinary_payment():
    session, aid = _session([], qi=8, devil=3)
    ids = {row["id"] for row in options(session, aid) or []}
    assert ids == {furnace.ENGINE + ":ordinary"}
