"""Bounded source proofs must fail closed when their reviewed inputs drift."""

from __future__ import annotations

import ast
import copy
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.automation_truth_plugin_proofs import _COMMON, _FAMILY_FILES, verified_components


ROOT = Path(__file__).resolve().parents[2]


def source_reference(relative, name):
    """Independently require the evidence to point at its named handler."""
    node = next(node for node in ast.parse((ROOT / relative).read_text()).body
                if isinstance(node, ast.FunctionDef) and node.name == name)
    return f"{relative}:{node.lineno}"


class ReviewedPluginComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mechanics = json.loads((ROOT / "APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
        directory = ROOT / "APP/combat/rules"
        cls.features = {}
        for path in [directory / "feature_blocks.json", *sorted((directory / "feature_blocks.d").glob("*.json"))]:
            cls.features.update(json.loads(path.read_text()).get("features") or {})

    def fixture(self, mechanic_id):
        temp = tempfile.TemporaryDirectory(prefix="automation-component-test-", dir=ROOT)
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        feature = self.features[mechanic_id]
        for relative in (*_COMMON, *_FAMILY_FILES[feature["block"]]):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        rules = root / "APP/combat/rules"
        (rules / "feature_blocks.d").mkdir(parents=True)
        (rules / "feature_blocks.json").write_text(json.dumps({"features": {mechanic_id: feature}}))
        return root

    def test_real_grounding_has_component_despite_empty_effects(self):
        key = "TAL_LIGHTNING_GROUNDING_BREATH"
        mechanic = self.mechanics[key]
        self.assertEqual(mechanic["effects"], [])
        # The Lightning review records the optional, once-per-next-turn rider
        # explicitly. A component proof remains separate from full coverage.
        self.assertEqual(mechanic["coverage"], "CORE_WITH_RIDERS")
        self.assertTrue(mechanic["riders"])
        result = verified_components(key, mechanic, self.features[key], ROOT)
        self.assertEqual(result[0]["status"], "VERIFIED_COMPONENT")
        self.assertIn(source_reference("APP/combat/typed_executor.py", "typed_save_modifiers"), result[0]["evidence"])
        self.assertTrue(result[0]["limitations"])

    def test_real_object_damage_adds_component_to_nonfull_record(self):
        key = "STARS_TAL_FALLING_STAR"
        self.assertNotEqual(self.mechanics[key]["coverage"], "FULL")
        result = verified_components(key, self.mechanics[key], self.features[key], ROOT)
        self.assertEqual(result[0]["block"], "object_damage")
        self.assertEqual(result[0]["status"], "VERIFIED_COMPONENT")
        self.assertIn(source_reference("APP/combat/ext/objects.py", "technique_used"), result[0]["evidence"])

    def test_real_demon_bone_has_resource_healing_component(self):
        key = "TAL_DAEMONIC_CULTIVATION_DEMON_BONE_REGENERATION"
        result = verified_components(key, self.mechanics[key], self.features[key], ROOT)
        self.assertEqual(result[0]["block"], "ironroot_demon_bone_regen")
        self.assertIn(source_reference("APP/combat/typed_reactions.py", "on_turn_start"), result[0]["evidence"])

    def test_stored_coverage_does_not_change_proof_or_fingerprint(self):
        key = "RADIANCE_TAL_HEAVEN_OPENING_JUDGMENT"
        mechanic = self.mechanics[key]
        expected = verified_components(key, mechanic, self.features[key], ROOT)
        self.assertTrue(expected)
        self.assertIn("mechanic_without_coverage_sha256", expected[0]["implementation_fingerprint"])
        for coverage in ("FULL", "CORE_WITH_RIDERS", "MANUAL", None):
            with self.subTest(coverage=coverage):
                changed = {**mechanic, "coverage": coverage}
                self.assertEqual(verified_components(key, changed, self.features[key], ROOT), expected)

    def test_plugin_or_dispatcher_source_drift_invalidates_even_preserved_stat(self):
        key = "TAL_LIGHTNING_GROUNDING_BREATH"
        for relative in ("APP/combat/ext/lightning_grounding.py", "APP/combat/typed_executor.py"):
            with self.subTest(source=relative):
                root = self.fixture(key)
                self.assertTrue(verified_components(key, self.mechanics[key], self.features[key], root))
                path = root / relative
                previous = path.stat()
                content = path.read_bytes()
                # Alter one byte in the opening docstring while preserving size and timestamps.
                path.write_bytes(content[:4] + bytes([content[4] ^ 1]) + content[5:])
                os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
                self.assertEqual(verified_components(key, self.mechanics[key], self.features[key], root), [])

    def test_unrelated_and_losing_feature_rows_do_not_receive_a_proof(self):
        key = "TAL_LIGHTNING_GROUNDING_BREATH"
        self.assertEqual(verified_components(key, self.mechanics[key], {"block": "unrelated"}, ROOT), [])
        self.assertEqual(verified_components("UNRELATED_ID", self.mechanics[key], self.features[key], ROOT), [])
        root = self.fixture(key)
        (root / "APP/combat/rules/feature_blocks.d/zz_override.json").write_text(
            json.dumps({"features": {key: {"block": "already_applied"}}}))
        self.assertEqual(verified_components(key, self.mechanics[key], self.features[key], root), [])

    def test_unreviewed_spec_and_record_shapes_fail_closed(self):
        key = "STARS_TAL_FALLING_STAR"
        feature = copy.deepcopy(self.features[key])
        feature["needs_condition"] = "unreviewed"
        self.assertEqual(verified_components(key, self.mechanics[key], feature, ROOT), [])
        mechanic = copy.deepcopy(self.mechanics[key])
        mechanic["area"]["shape"] = "wall"
        self.assertEqual(verified_components(key, mechanic, self.features[key], ROOT), [])


if __name__ == "__main__":
    unittest.main()
def test_reviewed_dependency_map_covers_every_declared_family():
    """A merged dependency declaration must retain its reviewed proof pin."""
    from tools import automation_truth_plugin_proofs as proofs

    required = set(proofs._COMMON)
    for paths in proofs._FAMILY_FILES.values():
        required.update(paths)
    assert required <= set(proofs._REVIEWED_SHA256)
