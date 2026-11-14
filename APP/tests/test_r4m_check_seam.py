"""The shared check seam combines creature provenance and named hazards."""
from types import SimpleNamespace

import pytest

from combat import ext, typed_executor as te


@pytest.fixture(autouse=True)
def no_stored_rule_rows(monkeypatch):
    """Read the core combination alone: no stored rule row and no plug-in row answers.

    These tests stand in for the fight engine with ``object()`` because they read ``check_modes``'
    own combination of the creature's declared mode and one condition's named hazard. The seam
    reads the engine for stored rule rows and dispatches the strict hazard seams
    (``ability_check_hazard_mode``, ``ability_check_hazards`` and ``check_hazard_mode``), each of
    which belongs to a real engine and creature, so every one of them answers nothing here and the
    condition's own ``check_against`` rule is the only hazard source. Stub ``run_strict`` alone:
    ``run_checkpoint`` dispatches through it.
    """
    monkeypatch.setattr(te, "condition_rules", lambda _, *, engine=None: [])
    monkeypatch.setattr(te, "condition_rule_instances", lambda _, *, engine=None: [])
    monkeypatch.setattr(ext, "run_strict", lambda *args, **kwargs: [])


@pytest.mark.parametrize("creature_mode,hazard_mode,expected", [
    ("DISADVANTAGE", "ADVANTAGE", "NORMAL"),
    ("ADVANTAGE", "DISADVANTAGE", "NORMAL"),
    ("ADVANTAGE", "ADVANTAGE", "ADVANTAGE"),
])
def test_creature_and_hazard_sources_combine_before_cancellation(
        monkeypatch, creature_mode, hazard_mode, expected):
    actor = SimpleNamespace(conditions={"buff": SimpleNamespace(
        condition_id=te.CONDITION_PREFIX + "check_against",
        data={"rule": {"check_against": {"abilities": ["STR"],
              "against": ["grappled"], "mode": hazard_mode}}})})
    engine, opponent = object(), object()

    def contribution(name, actual_engine, subject, ability, skill, against):
        assert (name, actual_engine, subject, ability, skill, against) == (
            "ability_check_mode", engine, actor, "STR", "Athletics", opponent)
        return [creature_mode]

    monkeypatch.setattr(ext, "run", contribution)
    kwargs = {"engine": engine, "against_creature": opponent, "hazards": ("grappled",)}
    assert te.check_modes(actor, "STR", "Athletics", **kwargs) == {creature_mode, hazard_mode}
    assert te.check_mode(actor, "STR", "Athletics", **kwargs) == expected


@pytest.mark.parametrize("condition_name,hazards,ability,expected", [
    ("check_against", ("grappled",), "STR", "ADVANTAGE"),
    ("check_against", (), "STR", "NORMAL"),
    ("check_against", ("frightened",), "STR", "NORMAL"),
    ("check_against", ("grappled",), "DEX", "NORMAL"),
    ("suppressed.check_against", ("grappled",), "STR", "NORMAL"),
])
def test_hazards_are_explicit_and_suppressed_scopes_are_inert(
        monkeypatch, condition_name, hazards, ability, expected):
    actor = SimpleNamespace(conditions={"buff": SimpleNamespace(
        condition_id=te.CONDITION_PREFIX + condition_name,
        data={"rule": {"check_against": {"abilities": ["STR"],
              "against": ["grappled"], "mode": "ADVANTAGE"}}})})

    def unexpected_hook(*args):
        pytest.fail("Creature hooks require both engine and opposing creature")

    monkeypatch.setattr(ext, "run", unexpected_hook)
    assert te.check_mode(actor, ability, hazards=hazards) == expected
    assert te.check_mode(actor, ability, engine=object(), hazards=hazards) == expected
    assert te.check_mode(actor, ability, against_creature=object(), hazards=hazards) == expected
