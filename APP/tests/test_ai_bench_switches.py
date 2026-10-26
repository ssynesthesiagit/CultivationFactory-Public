"""Ablation switches (review AIUP2F15R blocker). Offline; no model.

Every switch a configuration names is a real MastermindPlan attribute, the bench docs match the
configured switches, and no_tactics changes the MASTERMIND menu it names (it is not a silent no-op).
"""
from pathlib import Path

import pytest

from combat.ai_mastermind import MastermindPlan
from tests.ai_tiers_native_support import context_for, fight, selected
from tools import ai_bench

SWITCHES = sorted({name for overrides in ai_bench.CONFIGS.values() for name in overrides})


@pytest.mark.parametrize("name", SWITCHES)
def test_each_switch_is_declared_on_mastermind(name):
    # setattr on a missing name would silently create it; the switch must be declared on this class.
    assert name in vars(MastermindPlan), f"{name} is not declared on MastermindPlan"
    assert isinstance(vars(MastermindPlan)[name], bool)


def test_bench_docs_match_the_configured_switches():
    text = Path(ai_bench.__file__).read_text(encoding="utf-8")
    assert "no separable switch" not in text
    assert "not ablated" not in text
    assert "use_tactics" in ai_bench.CONFIGS["no_tactics"]


def _menu(tmp_path, config):
    combat, _, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"], band="rival/boss", foe_at={"x": 3, "y": 7})
    context = context_for(combat, session)
    with ai_bench.offline_and_switches(ai_bench.CONFIGS[config]):
        choice, _ = selected(context)
    return [(s.candidate_id, tuple(p.component for p in s.components)) for s in choice.record.scored_alternatives]


def test_no_tactics_changes_the_scored_menu(tmp_path):
    full = _menu(tmp_path / "full", "full")
    ablated = _menu(tmp_path / "ablated", "no_tactics")
    assert any(component.startswith("mastermind") for _, components in full for component in components), (
        "the full configuration must score MASTERMIND components for the ablation to mean anything")
    assert full != ablated
