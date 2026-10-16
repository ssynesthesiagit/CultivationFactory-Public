"""Real compiler output must retain the dynamically loaded Athletics rules.

These exercise the input that the failed public acceptance export omitted,
without depending on publication tooling that is itself outside APP/.
"""
import pytest

from tests.test_auto_athletics import _bundle


@pytest.mark.parametrize("feature,kind", [
    ("TAL_ATHLETICS_MERIDIAN_THREADING_DASH", "meridian_threading"),
    ("TAL_ATHLETICS_SPEED_BOOST", "speed_boost"),
    ("TAL_ATHLETICS_MIGHTY_CONDITIONING", "mighty_conditioning"),
    ("TAL_ATHLETICS_HEAVEN_TREADING_BODY", "heaven_treading"),
    ("TAL_ATHLETICS_SPIDER_S_TOUCH", "spider_touch"),
])
def test_real_compiler_keeps_the_shipped_athletics_passive(feature, kind):
    bundle = _bundle([feature])
    assert any(row.get("feature_id") == feature and row.get("block") == "athletics"
               and row.get("kind") == kind for row in bundle["typed_passives"]), \
        "Acceptance needs the shipped compiler row, never a test-injected substitute"


def test_real_compiler_keeps_the_unyielding_damage_trigger_row():
    feature = "TAL_BERSERKER_UNYIELDING_ADVANCE"
    bundle = _bundle([feature], extra_spheres=("tianxia.sphere.berserker",))
    assert any(row.get("feature_id") == feature and row.get("block") == "berserker"
               and row.get("kind") == "unyielding_advance" for row in bundle["typed_passives"]), \
        "Open-Hand cross-feature acceptance needs the real Unyielding damage-trigger row"
