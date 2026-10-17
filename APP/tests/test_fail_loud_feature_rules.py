"""FAILLOUD1: required feature-block rules data must fail loud, never compile to "no row".

combat/typed_reactions.py rules() merges combat/rules/feature_blocks.d/*.json. A glob over a missing directory is empty,
so every feature that directory declares (the Sword sphere's Sword Training, Iron Sword Body, Life-Severing Sword) used to
vanish silently: compile_blocks skips an id with no feature row, and the fighter simply has no mechanic. The check now
raises FileNotFoundError naming the directory. Synthetic fixtures only (a temporary copy of the rules root), so this runs
on public CI.
"""

import pytest

from combat import typed_reactions
from tests.test_ocf8_sword_core import LIFE_SEVERING, TRAINING, _bundle


def _rules_root_without_directory(tmp_path):
    root = tmp_path / "rules"
    root.mkdir()
    (root / "feature_blocks.json").write_text('{"schema": "test", "features": {}}', encoding="utf-8")
    return root / "feature_blocks.json"


def test_shipped_feature_rules_directory_is_present_and_declares_the_sword_features():
    features = typed_reactions.rules()["features"]
    assert typed_reactions.RULES_PATH.parent.joinpath("feature_blocks.d").is_dir()
    assert {TRAINING, LIFE_SEVERING} <= set(features)


def test_missing_feature_rules_directory_raises_naming_the_path(tmp_path, monkeypatch):
    monkeypatch.setattr(typed_reactions, "RULES_PATH", _rules_root_without_directory(tmp_path))
    with pytest.raises(FileNotFoundError, match="feature_blocks.d"):
        typed_reactions.rules()


def test_sword_bundle_fails_loud_instead_of_compiling_no_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(typed_reactions, "RULES_PATH", _rules_root_without_directory(tmp_path))
    with pytest.raises(FileNotFoundError, match="feature_blocks.d"):
        _bundle([TRAINING])
