"""STALEMATE1F14: the setting_only early return must not remove the AI's existing restraints.

A free setting_only selector used to return None before the concentration, zone, Temporary HP and duplicate-buff
restraints in ai_restraint._allowed. Now only a repeated declaration (its own history) skips those restraints;
a first-time setting selector that would duplicate a held concentration technique stays vetoed.
Without the fix, test_setting_selector_duplicating_held_concentration_stays_vetoed fails (returns None).
"""
from types import SimpleNamespace

from combat import concentration
from combat.ext import ai_restraint


def _actor():
    return SimpleNamespace(summon={}, movement_remaining_ft=0, turn_flags={}, entity_id="planner",
                           team_id="a", temporary_hp=0, maximum_hp=10, conditions={}, modifiers={})


def _candidate(source="fixture.setting.hold"):
    return SimpleNamespace(source_definition_id=source, target_ids=(), kind=None, metadata={},
                           destination=None)


def _action():
    return SimpleNamespace(economy="NONE", target_kind="SELF", costs=(),
                           parameters={"setting_only": True,
                                       "typed": {"duration": {"concentration": True}, "effects": []}})


def _engine():
    return SimpleNamespace(state=SimpleNamespace(zones={}), action_catalog={})


def test_setting_selector_duplicating_held_concentration_stays_vetoed(monkeypatch):
    monkeypatch.setattr(concentration, "technique_of", lambda engine, source: "shared-technique")
    monkeypatch.setattr(concentration, "sources", lambda actor: ["held.source"])
    verdict = ai_restraint._allowed(_engine(), _actor(), _candidate(), _action())
    assert verdict is False, "a free setting that duplicates a held concentration was no longer vetoed"


def test_first_free_setting_without_a_restraint_is_not_vetoed(monkeypatch):
    monkeypatch.setattr(concentration, "technique_of", lambda engine, source: "technique")
    monkeypatch.setattr(concentration, "sources", lambda actor: [])
    assert ai_restraint._allowed(_engine(), _actor(), _candidate(), _action()) is None


def test_repeated_free_setting_is_scored_not_vetoed(monkeypatch):
    monkeypatch.setattr(concentration, "technique_of", lambda engine, source: "shared-technique")
    monkeypatch.setattr(concentration, "sources", lambda actor: ["held.source"])
    actor, candidate = _actor(), _candidate()
    actor.turn_flags[ai_restraint.setting_history_key(candidate)] = 1
    engine = _engine()
    engine.action_catalog = {}
    assert ai_restraint._allowed(engine, actor, candidate, _action()) is None
