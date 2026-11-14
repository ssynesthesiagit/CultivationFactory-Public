"""Static truth-classifier regressions; no character build, fight, or model call."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tools.automation_truth_effects import _REVIEWED_SHA256, analyze_effects


ROOT = Path(__file__).resolve().parents[2]


class EffectTruthTests(unittest.TestCase):
    def inspect(self, effects, **kwargs):
        return analyze_effects(effects, repo_root=ROOT, **kwargs)

    def test_explicit_mark_has_source_backed_supported_form(self):
        effect = {"type": "mark", "mark": "Waning Mark", "applies_to": "target",
                  "duration": {"kind": "until_end_of_your_next_turn"}}
        result = self.inspect([effect])
        self.assertTrue(result["all_supported"])
        self.assertEqual(result["supported_count"], 1)
        self.assertTrue(result["records"][0]["evidence"])

    def test_real_waning_mark_is_not_classified_from_stored_coverage(self):
        path = ROOT / "APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"
        mechanics = json.loads(path.read_text(encoding="utf-8"))["mechanics"]
        mechanic = mechanics["TAL_YIN_MARKING_A_CREATURE#mark_the_waning"]
        modified = {**mechanic, "coverage": "MANUAL", "typing_status": "untrusted"}
        result = self.inspect(modified["effects"], mechanic=modified)
        self.assertTrue(result["all_supported"])

    def test_a_mark_duration_the_mark_route_cannot_reach_is_not_supported(self):
        # block_mark resolves only its own duration kind and falls through to until removed for
        # anything else, so these spellings must not earn the credit the effect reader gives them.
        for kind in ("instant", "end_of_turn", "this_attack", "special"):
            with self.subTest(kind=kind):
                result = self.inspect([{"type": "mark", "mark": "Burden Mark", "applies_to": "target",
                                        "duration": {"kind": kind}}])
                self.assertEqual(result["supported_count"], 0)
                self.assertEqual(result["records"][0]["status"], "UNKNOWN")
                self.assertEqual(result["issues"][0]["code"], "effect_parameters_unproven")
                self.assertIn(kind, result["issues"][0]["reason"])

    def test_a_mark_is_not_judged_by_the_duration_of_its_ability(self):
        # block_mark reads the mark's own duration only. "Burden Mark" is a name the rules give an
        # end-of-your-next-turn default (typed_conditions.json mark_durations), so this fixture is
        # judged on that named default; what it must never be judged against is the ability's own
        # clock or the ability's Concentration.
        mark = {"type": "mark", "mark": "Burden Mark", "applies_to": "target"}
        result = self.inspect([mark], mechanic={"duration": {"kind": "minutes", "amount": 1,
                                                             "concentration": True}})
        self.assertTrue(result["all_supported"])
        self.assertEqual(result["issues"], [])
        for kind in ("concentration", "until_end_of_scene"):
            with self.subTest(kind=kind):
                result = self.inspect([{**mark, "duration": {"kind": kind}}])
                self.assertEqual(result["supported_count"], 1)
                self.assertEqual(result["issues"], [])

    def test_a_mark_concentration_flag_the_engine_never_reads_is_not_supported(self):
        # block_mark resolves duration["kind"] and nothing else. A mark ends with its bearer's
        # Concentration only when that kind is "concentration", so a true flag beside any other
        # kind promises a lifecycle nothing reads and must earn no credit; a flag that contradicts
        # the kind the executor does read is unresolved rather than honoured.
        for kind in ("until_removed", "until_end_of_your_next_turn", "one_minute", "minutes"):
            with self.subTest(kind=kind):
                result = self.inspect([{"type": "mark", "mark": "Audit Mark", "applies_to": "target",
                                        "duration": {"kind": kind, "concentration": True}}])
                self.assertEqual(result["supported_count"], 0)
                self.assertEqual(result["records"][0]["status"], "UNKNOWN")
                self.assertEqual(result["issues"][0]["code"], "effect_parameters_unproven")
                self.assertIn("concentration", result["issues"][0]["reason"])
        for flag in (None, True):
            with self.subTest(kind="concentration", flag=flag):
                duration = {"kind": "concentration"}
                if flag is not None:
                    duration["concentration"] = flag
                self.assertTrue(self.inspect([{"type": "mark", "mark": "Qi Bond", "applies_to": "target",
                                               "duration": duration}])["all_supported"], duration)
        for duration in ({"kind": "concentration", "concentration": False},
                         {"kind": "until_removed", "concentration": "yes"},
                         {"kind": "until_removed", "concentration": 1}):
            with self.subTest(duration=duration):
                result = self.inspect([{"type": "mark", "mark": "Audit Mark", "applies_to": "target",
                                        "duration": duration}])
                self.assertEqual(result["supported_count"], 0, duration)
                self.assertEqual(result["issues"][0]["code"], "effect_parameters_unproven")
                self.assertIn("concentration", result["issues"][0]["reason"])

    def test_weapon_damage_does_not_honor_row_type_override(self):
        result = self.inspect([{"type": "damage", "weapon_damage": True,
                                "damage_types": ["radiant"]}])
        self.assertFalse(result["all_supported"])
        self.assertEqual(result["issues"][0]["code"], "weapon_damage_override")

    def test_supported_child_cannot_rescue_unknown_parent(self):
        result = self.inspect([{"type": "not_a_core_container", "effects": [
            {"type": "healing", "flat": 3}]}])
        self.assertEqual(result["supported_count"], 0)
        self.assertEqual(result["unknown_count"], 2)
        self.assertEqual(result["records"][1]["path"], "effects[0].effects[0]")

    def test_registered_plugin_is_not_execution_proof(self):
        plugin = SimpleNamespace(effects={"custom_heal": [{"evidence": ["APP/combat/ext/example.py:10"]}]})
        result = self.inspect([{"type": "custom_heal", "flat": 3}], plugin_index=plugin)
        self.assertFalse(result["all_supported"])
        self.assertEqual(result["records"][0]["status"], "UNKNOWN")
        self.assertIn("APP/combat/ext/example.py:10", result["records"][0]["evidence"])

    def test_deferred_healing_cannot_count_as_direct_healing(self):
        result = self.inspect([{"type": "healing", "formula": "pb", "deferred": True}])
        self.assertEqual(result["supported_count"], 0)
        self.assertEqual(result["issues"][0]["code"], "deferred_route_unproven")

    def test_bare_passive_effect_requires_entry_point(self):
        result = self.inspect([{"type": "healing", "flat": 4}], route="passive")
        self.assertFalse(result["all_supported"])
        self.assertEqual(result["supported_count"], 0)

    def test_half_damage_only_in_its_save_success_context(self):
        damage = {"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["fire"]}
        half = {"type": "half_damage"}
        self.assertFalse(self.inspect([half])["all_supported"])
        result = self.inspect([{"type": "save", "ability": "DEX", "on_fail": [damage], "on_success": [half]}])
        self.assertTrue(result["all_supported"])
        self.assertEqual(result["supported_count"], 1)
        self.assertEqual(result["structural_count"], 2)

    def test_formula_and_flat_stat_fields_are_not_interchangeable(self):
        self.assertFalse(self.inspect([{"type": "ac_bonus", "formula": "pb"}])["all_supported"])
        self.assertFalse(self.inspect([{"type": "speed", "flat": 10, "amount": 20}])["all_supported"])
        self.assertFalse(self.inspect([{"type": "damage", "flat": 2, "flat_by_cl": [[1, 20, 8]],
                                       "damage_types": ["fire"]}])["all_supported"])

    def test_unknown_formula_and_unconsumed_field_block_full(self):
        self.assertFalse(self.inspect([{"type": "healing", "formula": "text:pb plus mystery"}])["all_supported"])
        self.assertFalse(self.inspect([{"type": "healing", "flat": 5, "only_when_new_rule": True}])["all_supported"])
        self.assertFalse(self.inspect([{"type": "temp_hp", "flat": 5, "duration": "one_minute"}])["all_supported"])

    def test_attack_flat_damage_exposes_weapon_fallback(self):
        result = self.inspect([{"type": "attack", "attack_kind": "cultivation_melee", "on_hit": [
            {"type": "damage", "flat": 5, "damage_types": ["force"]}]}])
        self.assertFalse(result["all_supported"])
        self.assertIn("attack_flat_damage_fallback", {row["code"] for row in result["issues"]})

    def test_malformed_tree_and_noop_cannot_be_full(self):
        self.assertFalse(self.inspect({"type": "healing", "flat": 2})["all_supported"])
        self.assertFalse(self.inspect([])["all_supported"])
        self.assertFalse(self.inspect([{"type": "hold_at_1hp"}])["all_supported"])
        self.assertFalse(self.inspect([{"type": "condition", "condition": "invented_unknown_condition"}])["all_supported"])

    def test_rider_keeps_partial_components_visible(self):
        result = self.inspect([{"type": "healing", "flat": 3}, {"type": "rider", "evidence": "GM resolves the clause."}])
        self.assertEqual(result["supported_count"], 1)
        self.assertEqual(result["manual_count"], 1)
        self.assertFalse(result["all_supported"])

    def test_inspection_does_not_import_combat_runtime(self):
        before = {name for name in sys.modules if name == "combat" or name.startswith("combat.")}
        self.inspect([{"type": "healing", "flat": 3}])
        after = {name for name in sys.modules if name == "combat" or name.startswith("combat.")}
        self.assertEqual(before, after)

    def test_same_size_same_mtime_handler_edit_invalidates_cached_proof(self):
        paths = tuple(_REVIEWED_SHA256)
        effect = {"type": "mark", "mark": "Waning Mark", "applies_to": "target",
                  "duration": {"kind": "until_end_of_your_next_turn"}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in paths:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
            self.assertTrue(analyze_effects([effect], repo_root=root)["all_supported"])
            path = root / paths[0]
            before = path.stat()
            original = path.read_bytes()
            head, body = original.split(b"def block_mark(", 1)
            old = b"owner = ctx.actor.entity_id"
            replacement = b"owner = ctx.actor.owner_id "
            self.assertEqual(len(old), len(replacement))
            self.assertIn(old, body)
            changed = head + b"def block_mark(" + body.replace(old, replacement, 1)
            self.assertEqual(len(original), len(changed))
            path.write_bytes(changed)
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertEqual(path.stat().st_size, before.st_size)
            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
            result = analyze_effects([effect], repo_root=root)
            self.assertFalse(result["all_supported"])
            self.assertEqual(result["supported_count"], 0)
            self.assertEqual(result["issues"][0]["code"], "reviewed_source_drift")
            self.assertIn(paths[0], result["issues"][0]["reason"])
            self.assertEqual(analyze_effects(["free text"], repo_root=root)["records"][0]["status"], "UNKNOWN")

    def test_missing_amount_dependency_cannot_keep_atomic_positive(self):
        paths = tuple(path for path in _REVIEWED_SHA256 if path != "APP/combat/typed_amounts.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in paths:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
            result = analyze_effects([{"type": "healing", "flat": 3}], repo_root=root)
            self.assertFalse(result["all_supported"])
            self.assertEqual(result["issues"][0]["code"], "reviewed_source_drift")
            self.assertIn("typed_amounts.py", result["issues"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
