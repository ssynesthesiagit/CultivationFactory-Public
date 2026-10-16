"""Shipped inputs for Athletics engine/table and Berserker cross-feature tests.

The compiler discovers overlays dynamically. Naming the actual input here also
lets the public test exporter retain it through its static dependency closure.
No rows are injected into compiled characters by this helper.
"""
import json
from pathlib import Path


ATHLETICS_RULES = Path(__file__).resolve().parents[1] / "combat/rules/feature_blocks.d/auto8-athletics.json"
RELATED_RULES = (
    (Path(__file__).resolve().parents[1] / "combat/rules/feature_blocks.d/bodyb.json",
     "TAL_ATHLETICS_RAPID_MOTION"),
    (Path(__file__).resolve().parents[1] / "combat/rules/feature_blocks.d/walkable-roofs.json",
     "TAL_ATHLETICS_SPIDER_S_TOUCH"),
    (Path(__file__).resolve().parents[1] / "combat/rules/feature_blocks.d/riders_c2.json",
     "TAL_BERSERKER_UNYIELDING_ADVANCE"),
)


def require_athletics_rules():
    """Fail at the missing input, before an incomplete export mimics combat bugs."""
    assert ATHLETICS_RULES.is_file(), "Shipped Athletics passive rules are required by these tests"
    features = json.loads(ATHLETICS_RULES.read_bytes())["features"]
    meridian = features["TAL_ATHLETICS_MERIDIAN_THREADING_DASH"]
    assert meridian["block"] == "athletics"
    assert {"kind": "meridian_threading", "step_ft": 10} in meridian["rules"]
    for source, feature in RELATED_RULES:
        assert source.is_file(), f"Shipped rules for {feature} are required by these tests"
        assert feature in json.loads(source.read_bytes())["features"]
