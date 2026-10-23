"""Exact compatibility entrypoints for CI's per-file execution contract.

Reuse the existing assertions and native service fixtures. The source tests
need their normal ordered-roll fixture; the retained legacy automatic test
keeps its original roll setup. No game or controller behavior is replaced.
"""
from pathlib import Path
import hashlib

import pytest

from tests import test_mgr_t14_heavenly_source as source
from tests import test_mgr_t14_heavenly_rejection as retained


@pytest.fixture(autouse=True)
def complete_foundation_runtime():
    """An export without the committed providers cannot test these choices."""
    root = Path(__file__).resolve().parents[1] / 'combat/rules/feature_blocks.d'
    required = {
        'a2_foundations_2.json': '82bf2b23b02bc9254fbf65ab95360c0327353fece5ac74a92677b0ebfb6d115e',
        'zz_mgr_t14_heavenly_rejection.json': '75d614b8573275263bc730a5a0c393b4f731c6cdfde76a16143edec541bd1b49',
    }
    for name, expected in required.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize('natural', [1, 20])
def test_native_manual_death_choice(tmp_path, monkeypatch, natural):
    source.ordered_rolls(monkeypatch)
    source.test_manual_death_save_retains_legal_spend_without_changing_natural_outcome(
        tmp_path, monkeypatch, natural)


def test_native_early_marrow_choice(tmp_path, monkeypatch):
    source.ordered_rolls(monkeypatch)
    source.test_selected_marrow_preserves_the_base_preoutcome_option(tmp_path, monkeypatch)


def test_retained_automatic_rejection_choice(tmp_path, monkeypatch):
    retained.test_automatic_defender_uses_rejection_without_player_prompt(tmp_path, monkeypatch)
