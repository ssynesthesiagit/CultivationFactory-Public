"""Regression: the lighting fixtures' printed-rules substitution reaches the compiler.

MUTUALKO1F15R2 blocking 1: the compiler reads status_text.RULES_TEXT_PATH, but the
lighting fixtures patched the removed factory_compiler._RULES_TEXT_CACHE. The
fixtures then errored at setup, or (if the patch were tolerant) the synthetic
headings never reached the compiler. This test fails on the pre-fix fixture and
passes once the fixture writes the rules to the live reader's file.
"""
from combat import factory_compiler, status_text
from tests.lighting_darkness_support import synthetic_darkness_rules


def test_synthetic_darkness_headings_reach_the_compiler(tmp_path, monkeypatch):
    real_path = status_text.RULES_TEXT_PATH
    with synthetic_darkness_rules(tmp_path, monkeypatch):
        rules = factory_compiler._rules_text()
        assert status_text.RULES_TEXT_PATH != real_path
        assert rules["TAL_DARK_PURE_DARKNESS"].startswith("### Pure Darkness - Darkness")
        assert rules["TAL_DARK_PITCH_BLACK"].startswith("### Pitch Black - Augment")
    assert status_text.RULES_TEXT_PATH == real_path


def test_no_lighting_fixture_patches_the_removed_cache():
    import pathlib
    for name in ("lighting_darkness_support.py", "test_lighting_f13_regressions.py"):
        text = (pathlib.Path(__file__).parent / name).read_text()
        assert "_RULES_TEXT_CACHE" not in text
