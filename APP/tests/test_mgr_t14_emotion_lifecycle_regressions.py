"""Regression coverage for Emotion Cultivator source classification and lifecycle seams."""
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_provoked_rage_save_is_an_emotional_escalation():
    pulse = (ROOT / "combat/ext/qi_subpaths_1.py").read_text()
    weather = (ROOT / "combat/ext/emotion_cultivator.py").read_text()
    assert "'save_categories': ['mind', 'emotion', 'emotional_escalation']" in pulse
    assert "'save_categories': ['mind', 'emotion', 'emotional_escalation']" in weather


def test_ended_declaration_receipts_prevent_reopen_and_short_rest_reads_continuations():
    cultivator = (ROOT / "combat/ext/emotion_cultivator.py").read_text()
    continuation = (ROOT / "combat/ext/emotion_continuation.py").read_text()
    assert "ended_declaration_receipts" in cultivator
    assert "continued.get('records', [])" in cultivator
    assert "ended_declaration_receipts" in continuation
    assert "active_instances" in continuation
