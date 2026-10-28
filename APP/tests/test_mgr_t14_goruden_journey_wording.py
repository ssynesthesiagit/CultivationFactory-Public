"""Radiant Fist's journey command reads in plain player language (checklist item 13).

Synthetic actor only: the test builds a bundle that owns the Radiant Fist feature
and calls the journey_options hook directly. No services, models or private data.
"""
from types import SimpleNamespace
from combat.ext import goruden_journey


def _actor():
    feature = goruden_journey.FIST
    return {
        "name": "Test Monk",
        "bundle": {
            "typed_passives": [{"feature_id": feature}],
            "action_catalog": [],
            "typed_reactions": [],
            "actor_template": {"resources": []},
        },
    }


def test_radiant_fist_command_is_plain_and_says_effect_target_and_cost():
    session = SimpleNamespace(state={"phase": "travel", "actors": {"a": _actor()}})
    rows = goruden_journey.options(session, "a")
    collect = [row for row in rows if row["id"] == "goruden.collect"]
    assert len(collect) == 1
    label = collect[0]["label"]
    # Internal wording the player cannot act on is gone.
    assert "record" not in label.lower()
    assert "confirmations" not in label.lower()
    # The command names the ability, who it affects, the effect and the cost.
    assert label.startswith("Radiant Fist:")
    assert "daemonic corruption" in label
    assert "doubled" in label
    assert "No action or Stamina cost." in label


def test_invalid_collection_explains_gm_confirmation():
    import pytest
    from app.core import FoundryError

    session = SimpleNamespace(state={"actors": {"a": _actor()}})
    with pytest.raises(FoundryError) as error:
        goruden_journey.command(session, "a", "goruden_collect", {"invalid": 1})
    assert "GM" in str(error.value)
    assert "daemonic corruption" in str(error.value)
    assert "payload" not in str(error.value)
