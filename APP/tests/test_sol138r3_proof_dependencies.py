"""Area policy drift must invalidate both bounded proofs after SOL138r3 review."""
import json
import os
from pathlib import Path
import shutil

import pytest

from tools.automation_truth_effects import _REVIEWED_SHA256, analyze_effects
from tools.automation_truth_plugin_proofs import _COMMON, _FAMILY_FILES, verified_components

ROOT = Path(__file__).resolve().parents[2]
DEPENDENCIES = (
    "APP/combat/area_recipients.py", "APP/combat/area_recipient_rules.py",
    "APP/combat/effect_harm.py", "APP/combat/rules/area_recipient_overrides.json",
)


@pytest.mark.parametrize("relative", DEPENDENCIES)
def test_recipient_policy_drift_invalidates_atomic_and_component_proofs(tmp_path, relative):
    key = "TAL_LIGHTNING_GROUNDING_BREATH"
    mechanic = json.loads((ROOT / "APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"][key]
    feature = None
    directory = ROOT / "APP/combat/rules"
    for path in [directory / "feature_blocks.json", *sorted((directory / "feature_blocks.d").glob("*.json"))]:
        feature = json.loads(path.read_text()).get("features", {}).get(key, feature)
    assert feature is not None
    paths = set(_REVIEWED_SHA256) | set(_COMMON) | set(_FAMILY_FILES[feature["block"]]) | set(DEPENDENCIES)
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    (tmp_path / "APP/combat/rules/feature_blocks.json").write_text(json.dumps({"features": {key: feature}}))
    effect = {"type": "healing", "flat": 3}
    assert analyze_effects([effect], repo_root=tmp_path)["all_supported"]
    assert verified_components(key, mechanic, feature, tmp_path)
    path = tmp_path / relative
    before = path.stat()
    content = path.read_bytes()
    # Change executable text (or JSON bytes), preserving size and timestamps.
    changes = {
        "area_recipients.py": (b"ignore_self=True", b"ignore_self=None"),
        "area_recipient_rules.py": (b"maxsize=1", b"maxsize=2"),
        "effect_harm.py": (b"yield child", b"yield Child"),
        "area_recipient_overrides.json": (b'"enemies"', b'"Enemies"'),
    }
    old, new = changes[path.name]
    assert old in content and len(old) == len(new)
    path.write_bytes(content.replace(old, new, 1))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    result = analyze_effects([effect], repo_root=tmp_path)
    assert not result["all_supported"]
    assert relative in result["issues"][0]["reason"]
    assert result["issues"][0]["code"] == "reviewed_source_drift"
    assert verified_components(key, mechanic, feature, tmp_path) == []
