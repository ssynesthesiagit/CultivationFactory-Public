"""Source-grounded audit regressions; no fights, actors, providers, or game writes.

The real authority supplies the positive, stale-coverage, manual, and plug-in
examples. Small explicit fixtures isolate menu and filtering edge cases without
changing the checked-in authority or claiming that those fixtures are real rules.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from tools import automation_truth as truth


ROOT = Path(__file__).resolve().parents[2]
WANING_MARK = "TAL_YIN_MARKING_A_CREATURE#mark_the_waning"
STALE_FULL = "TAL_EARTH_DEEP_ROOT_STANCE"
MANUAL_TRAINING = "AIR_BASE_WIND_HAND_TRAINING"
PLUGIN_OBJECT_DAMAGE = "RADIANCE_TAL_HEAVEN_OPENING_JUDGMENT"


class AutomationTruthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Parse the source index once; report() never imports or runs plug-ins.
        cls.audit = truth.AutomationAudit()
        cls.report = cls.audit.report()
        cls.by_id = {row["mechanic_id"]: row for row in cls.report["mechanics"]}

    def fixture(self, **updates):
        mechanic = copy.deepcopy(self.audit.mechanics[WANING_MARK])
        mechanic.update({"mechanic_id": "test:automation-truth", "name": "Audit fixture",
                         "activation": {"economy": "action"}, "coverage": "FULL"})
        mechanic.update(updates)
        return mechanic

    def classify_fixture(self, **updates):
        mechanic = self.fixture(**updates)
        return self.audit.classify(mechanic["mechanic_id"], mechanic=mechanic)

    def codes(self, row):
        return {issue["code"] for issue in row["issues"]}

    def test_actual_waning_mark_is_real_full(self):
        row = self.by_id[WANING_MARK]
        self.assertEqual(row["classification"], "REAL_FULL")
        self.assertTrue(row["direct_route_proved"])
        self.assertEqual(row["effect_counts"], {"supported": 1, "manual": 0, "unknown": 0})
        self.assertEqual(row["gm_lines"], [])
        self.assertEqual(row["issues"], [])
        self.assertTrue(row["variants"][0]["effects"][0]["evidence"])

    def test_real_stale_full_contains_an_explicit_unimplemented_clause(self):
        mechanic = self.audit.mechanics[STALE_FULL]
        # The printed optional Burden Mark remains a real manual clause; the
        # reviewed authority now labels this explicitly rather than claiming FULL.
        self.assertEqual(mechanic["coverage"], "CORE_WITH_RIDERS")
        self.assertTrue(mechanic["effects"])
        self.assertTrue(any(effect["type"] == "rider" for effect in mechanic["effects"]))
        row = self.by_id[STALE_FULL]
        self.assertNotEqual(row["classification"], "REAL_FULL")
        self.assertIn("retained_gm_lines", self.codes(row))
        self.assertTrue(any("Burden Mark" in line for line in row["gm_lines"]))
        self.assertIn("explicit_rider", self.codes(row))
        self.assertGreater(row["effect_counts"]["manual"], 0)

    def test_real_manual_mechanic_retains_its_reminders(self):
        row = self.by_id[MANUAL_TRAINING]
        self.assertEqual(row["classification"], "MANUAL")
        self.assertTrue(row["gm_lines"])
        self.assertFalse(row["direct_route_proved"])
        self.assertEqual(row["direct_action_gm_line_count"], 0)
        self.assertIn("projection_only", row["gm_emission"])

    def test_real_plugin_coverage_has_evidence_without_automatic_full(self):
        row = self.by_id[PLUGIN_OBJECT_DAMAGE]
        self.assertNotEqual(row["stored_coverage"], "FULL")
        self.assertEqual(row["feature_block"], "object_damage")
        self.assertTrue(row["plugin_claims"])
        self.assertTrue(any(claim.get("block") == "object_damage" for claim in row["plugin_claims"]))
        self.assertTrue(all(claim["evidence"] for claim in row["plugin_claims"]))
        self.assertNotIn(row["classification"], {"REAL_FULL", "MANUAL"})
        self.assertIn("feature_block_context", self.codes(row))
        self.assertEqual(row["classification"], "PARTIAL")
        self.assertTrue(row["verified_plugin_components"])
        # The authority already omits the covered object-damage sentence. Do
        # not fabricate a currently suppressed sentence from the declaration.
        self.assertEqual(row["sentences_suppressed_by_covers"], [])

    def test_empty_typed_grounding_record_has_verified_plugin_component(self):
        row = self.by_id["TAL_LIGHTNING_GROUNDING_BREATH"]
        self.assertEqual(row["classification"], "PARTIAL")
        self.assertEqual(row["effect_counts"], {"supported": 0, "manual": 0, "unknown": 0})
        self.assertTrue(row["verified_plugin_components"])
        self.assertEqual(row["verified_plugin_components"][0]["block"], "grounding_breath")

    def test_partitioned_json_is_complete_hash_checked_and_deterministic(self):
        root = Path("audit-output")
        args = (root / "truth.json", root / "summary.md", root / "audit.md")
        first = truth.report_outputs(self.report, *args)
        self.assertEqual(first, truth.report_outputs(self.report, *args))
        outputs = {path: text for path, text in first}
        index = json.loads(outputs[args[0]])
        reconstructed = []
        for part in index["detail_parts"]:
            content = outputs[root / part["path"]]
            self.assertEqual(hashlib.sha256(content.encode()).hexdigest(), part["sha256"])
            detail = json.loads(content)
            self.assertEqual(detail["input_sha256"], self.report["input_sha256"])
            self.assertEqual(len(detail["mechanics"]), part["mechanics"])
            self.assertEqual(detail["mechanics"][0]["mechanic_id"], part["first_id"])
            self.assertEqual(detail["mechanics"][-1]["mechanic_id"], part["last_id"])
            reconstructed.extend(detail["mechanics"])
        self.assertEqual(reconstructed, self.report["mechanics"])
        self.assertEqual(len(index["mechanics"]), len(reconstructed))
        self.assertEqual({row["details"] for row in index["mechanics"]}, {part["path"] for part in index["detail_parts"]})

    def test_exact_cover_suppression_does_not_prove_implementation(self):
        mechanic = copy.deepcopy(self.audit.mechanics[PLUGIN_OBJECT_DAMAGE])
        covered = self.audit.features[PLUGIN_OBJECT_DAMAGE]["covers"][0]
        retained = "The GM chooses the remaining special outcome."
        mechanic["riders"] = [covered + " " + retained]
        row = self.audit.classify(PLUGIN_OBJECT_DAMAGE, mechanic=mechanic)
        self.assertEqual(row["sentences_suppressed_by_covers"], [covered])
        self.assertEqual(row["gm_lines"], [retained])
        self.assertIn("covers_without_proof", self.codes(row))
        self.assertNotEqual(row["classification"], "REAL_FULL")

    def test_shared_option_reminder_counts_once_per_mechanic(self):
        base = self.fixture()
        shared = "The GM decides whether the unusual creature is eligible."
        row = self.classify_fixture(riders=[shared], options=[
            {"label": "First", "effects": base["effects"]},
            {"label": "Second", "effects": base["effects"]},
        ])
        self.assertEqual(row["gm_lines"], [shared])
        self.assertEqual(row["gm_line_count"], 1)
        self.assertEqual(row["variant_gm_line_instances"], 2)
        self.assertEqual(row["direct_action_gm_line_count"], 1)
        self.assertEqual(row["classification"], "PARTIAL")

    def test_option_riders_replace_shared_list_and_filter_other_labels(self):
        base = self.fixture()
        row = self.classify_fixture(riders=["Shared caveat.", "Second: GM resolves this choice."], options=[
            {"label": "First", "effects": base["effects"], "riders": []},
            {"label": "Second", "effects": base["effects"]},
        ])
        self.assertEqual(row["variants"][0]["gm_lines"], [])
        self.assertEqual(row["variants"][1]["gm_lines"], ["Shared caveat.", "Second: GM resolves this choice."])
        row = self.classify_fixture(riders=["First: GM resolves one.", "Second: GM resolves two."], options=[
            {"label": "First", "effects": base["effects"]},
            {"label": "Second", "effects": base["effects"]},
        ])
        self.assertEqual([v["gm_lines"] for v in row["variants"]],
                         [["First: GM resolves one."], ["Second: GM resolves two."]])

    def test_post_cap_option_requires_explicit_menu_inclusion(self):
        base = self.fixture()
        cap = truth.compiler.MAX_OPTIONS_PER_ABILITY
        options = [{"label": f"Choice {i}", "effects": base["effects"], "riders": []}
                   for i in range(cap + 2)]
        options[cap]["riders"] = ["The omitted option must not inflate the menu count."]
        options[cap + 1].update(include_in_menu=True, riders=["This opted-in choice retains a caveat."])
        row = self.classify_fixture(options=options)
        self.assertEqual([v["option"] for v in row["variants"]], [*range(cap), cap + 1])
        self.assertEqual(row["gm_lines"], ["This opted-in choice retains a caveat."])
        self.assertEqual(len([i for i in row["issues"] if i["code"] == "capped_option"]), 1)
        self.assertNotEqual(row["classification"], "REAL_FULL")

    def test_one_option_action_ignores_option_effects_but_reaction_merges_them(self):
        option_effect = {"type": "healing", "flat": 3}
        base = self.fixture(options=[{"label": "Only", "effects": [option_effect]}])
        action = self.audit.classify(base["mechanic_id"], mechanic=base)
        self.assertEqual([effect["kind"] for effect in action["variants"][0]["effects"]], ["mark"])
        self.assertIn("single_option_ignored", self.codes(action))
        reaction = copy.deepcopy(base)
        reaction["activation"] = {"economy": "reaction", "trigger": "When you take damage"}
        row = self.audit.classify(reaction["mechanic_id"], mechanic=reaction)
        self.assertEqual([effect["kind"] for effect in row["variants"][0]["effects"]], ["mark", "healing"])
        self.assertNotIn("single_option_ignored", self.codes(row))
        self.assertEqual(row["direct_action_gm_line_count"], 0)
        self.assertNotEqual(row["classification"], "REAL_FULL")

    def test_included_empty_option_cannot_borrow_a_siblings_effects(self):
        base = self.fixture()
        row = self.classify_fixture(options=[
            {"label": "Implemented", "effects": base["effects"]},
            {"label": "Empty", "effects": []},
        ])
        self.assertEqual(len(row["variants"]), 2)
        self.assertNotEqual(row["classification"], "REAL_FULL")
        self.assertIn("empty_variant", self.codes(row))

    def test_option_specific_area_keeps_geometry_uncertainty_visible(self):
        base = self.fixture()
        row = self.classify_fixture(area=None, options=[
            {"label": "One target", "effects": base["effects"]},
            {"label": "An area", "effects": base["effects"],
             "area": {"kind": "sphere", "radius_ft": 10}},
        ])
        self.assertNotEqual(row["classification"], "REAL_FULL")
        self.assertIn("area_or_trigger_context", self.codes(row))

    def test_supported_nested_effect_does_not_rescue_unknown_container(self):
        row = self.classify_fixture(effects=[{"type": "unknown_container", "effects": [
            {"type": "healing", "flat": 3}]}])
        self.assertEqual(row["classification"], "UNKNOWN")
        self.assertEqual(row["effect_counts"]["supported"], 0)
        self.assertGreaterEqual(row["effect_counts"]["unknown"], 2)

    def test_contextual_requirements_block_full_despite_supported_effects(self):
        cases = [
            {"cost": [{"resource": "qi", "amount": 1}]},
            {"use_limit": "once_per_rest"},
            {"area": {"kind": "sphere", "radius_ft": 10}},
            {"activation": {"economy": "action", "requirement": "Only when aligned."}},
            {"activation": {"economy": "action", "trigger": "When a nearby object breaks."}},
            {"target": "One unattended object"},
            {"range": {"kind": "feet", "feet": 0}},
            {"range": {"kind": "self", "feet": 60}},
        ]
        for updates in cases:
            with self.subTest(updates=updates):
                row = self.classify_fixture(**updates)
                self.assertNotEqual(row["classification"], "REAL_FULL")
                self.assertTrue(row["issues"])

    def test_stored_coverage_never_changes_execution_classification(self):
        for mid in (WANING_MARK, STALE_FULL, MANUAL_TRAINING, PLUGIN_OBJECT_DAMAGE):
            expected = copy.deepcopy(self.by_id[mid])
            expected.pop("stored_coverage")
            for label in ("FULL", "RIDERS_ONLY", "CORE_WITH_RIDERS", "invented_label", None):
                with self.subTest(mechanic=mid, label=label):
                    fixture = copy.deepcopy(self.audit.mechanics[mid])
                    fixture["coverage"] = label
                    row = self.audit.classify(mid, mechanic=fixture)
                    self.assertEqual(row.pop("stored_coverage"), label)
                    self.assertEqual(row, expected)

    def test_classifier_does_not_mutate_inputs_or_leak_result_aliases(self):
        mid = PLUGIN_OBJECT_DAMAGE
        fixture = copy.deepcopy(self.audit.mechanics[mid])
        before = copy.deepcopy(fixture)
        features_before = copy.deepcopy(self.audit.features[mid])
        expected = self.audit.classify(mid, mechanic=fixture)
        result = self.audit.classify(mid, mechanic=fixture)
        result["gm_lines"].append("mutated result")
        result["plugin_claims"][0]["evidence"].append("mutated result")
        result["variants"][0]["effects"].clear()
        self.assertEqual(fixture, before)
        self.assertEqual(self.audit.mechanics[mid], before)
        self.assertEqual(self.audit.features[mid], features_before)
        self.assertEqual(self.audit.classify(mid, mechanic=fixture), expected)

    def test_missing_plugin_evidence_blocks_positive_and_negative_certainty(self):
        plugin_index = copy.deepcopy(self.audit.plugins)
        plugin_index.diagnostics.append({"status": "UNKNOWN", "category": "unreadable_source",
                                         "evidence": ["APP/combat/ext/missing.py:1"]})
        with patch.object(self.audit, "plugins", plugin_index):
            for mid in (WANING_MARK, MANUAL_TRAINING):
                with self.subTest(mechanic=mid):
                    row = self.audit.classify(mid)
                    self.assertEqual(row["classification"], "UNKNOWN")
                    self.assertIn("incomplete_plugin_index", self.codes(row))

    def test_every_authority_mechanic_has_one_explicit_result(self):
        rows = self.report["mechanics"]
        ids = [row["mechanic_id"] for row in rows]
        self.assertEqual(len(ids), 4942)  # P13 adds the approved Insight records.
        self.assertEqual(ids, sorted(self.audit.mechanics))
        self.assertEqual(len(ids), len(set(ids)))
        counts = Counter(row["classification"] for row in rows)
        self.assertEqual(set(counts), set(truth.STATUSES))
        for status in truth.STATUSES:
            self.assertEqual(counts[status], self.report["totals"][status])
        self.assertEqual(sum(counts.values()), self.report["totals"]["mechanics"])

    def test_group_totals_and_top_twenty_reconcile_with_all_rows(self):
        groups = self.report["groups"]
        self.assertEqual(len([g for g in groups if g["kind"] == "sphere"]), 85)
        for key in self.report["totals"]:
            self.assertEqual(sum(g[key] for g in groups), self.report["totals"][key], key)
        by_group = {group["id"]: group for group in groups}
        for row in self.report["mechanics"]:
            self.assertIn(row["group_id"], by_group)
            self.assertEqual(row["group"], by_group[row["group_id"]]["name"])
            self.assertEqual(row["gm_line_count"], len(set(row["gm_lines"])))
            self.assertLessEqual(row["direct_action_gm_line_count"], row["gm_line_count"])
            self.assertLessEqual(row["gm_line_count"], row["variant_gm_line_instances"])
        self.assertEqual(self.report["top_20_by_gm_lines"],
                         sorted(groups, key=lambda g: (-g["gm_reminder_lines"], g["id"]))[:20])

    def test_real_record_provenance_resolves_to_existing_source_lines(self):
        references = set(self.report["engine_evidence"].values())
        for row in self.report["mechanics"]:
            references.add(row["source"])
            self.assertEqual(row["source_pointer"], "/mechanics/" + row["mechanic_id"].replace("~", "~0").replace("/", "~1"))
            if row["feature_source"]:
                references.add(row["feature_source"])
            for issue in row["issues"]:
                self.assertTrue(issue["evidence"], (row["mechanic_id"], issue))
                references.update(issue["evidence"])
            for claim in row["plugin_claims"]:
                references.update(claim["evidence"])
            for variant in row["variants"]:
                for effect in variant["effects"]:
                    self.assertTrue(effect["evidence"])
                    references.update(effect["evidence"])
        line_counts = {}
        for reference in sorted(references):
            with self.subTest(reference=reference):
                relative, line = reference.rsplit(":", 1)
                self.assertFalse(Path(relative).is_absolute())
                if relative not in line_counts:
                    line_counts[relative] = len((ROOT / relative).read_text(encoding="utf-8-sig").splitlines())
                self.assertGreater(int(line), 0)
                self.assertLessEqual(int(line), line_counts[relative])

    def test_a_mark_flag_the_executor_ignores_cannot_reach_real_full(self):
        # block_mark reads duration["kind"] only, so a concentration flag beside another kind states
        # a lifecycle nothing ends the mark on. An otherwise complete action carrying that flag must
        # lose its full credit instead of certifying a mark that outlives losing Concentration.
        def mark(duration):
            return [{"type": "mark", "mark": "Audit Mark", "applies_to": "target", "duration": duration}]

        clean = self.classify_fixture(effects=mark({"kind": "until_removed"}))
        self.assertEqual(clean["classification"], "REAL_FULL")
        self.assertEqual(clean["component_counts"], {"supported": 1, "manual": 0, "unknown": 0})
        for duration in ({"kind": "until_removed", "concentration": True},
                         {"kind": "until_end_of_your_next_turn", "concentration": True},
                         {"kind": "concentration", "concentration": False}):
            with self.subTest(duration=duration):
                row = self.classify_fixture(effects=mark(duration))
                self.assertNotEqual(row["classification"], "REAL_FULL")
                self.assertIn("effect_parameters_unproven", self.codes(row))
                self.assertEqual(row["component_counts"]["supported"], 0)

    def test_report_repeatability_and_input_fingerprint(self):
        again = self.audit.report()
        self.assertEqual(truth.stable_json(self.report), truth.stable_json(again))
        self.assertEqual(truth.render_summary(self.report), truth.render_summary(again))
        self.assertEqual(truth.render_audit(self.report), truth.render_audit(again))
        expected = hashlib.sha256(truth.stable_json(self.report["inputs"]).encode("utf-8")).hexdigest()
        self.assertEqual(self.report["input_sha256"], expected)
        for relative, digest in self.report["inputs"].items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), digest, relative)
        self.assertNotIn(str(ROOT), truth.stable_json(self.report))
        self.assertTrue(self.report["plugin_gm_reminders"])

    def test_every_committed_report_byte_is_free_of_machine_and_clock_values(self):
        # The owner re-runs --check on another machine and interpreter (lead acceptance 2026-10-05).
        # Nothing a report renders may carry a path, a timestamp, or a host value; the only
        # environment-bound number is the fingerprint of the audited sources named in "inputs".
        root = Path("audit-output") / "machine-free"
        outputs = truth.report_outputs(self.report, root / "truth.json", root / "summary.md", root / "audit.md")
        by_path = dict(outputs)
        self.assertEqual(len(outputs), 3 + -(-len(self.report["mechanics"]) // 200))
        for path, text in outputs:
            with self.subTest(path=path.name):
                self.assertNotIn(str(ROOT), text)
                self.assertNotIn(sys.prefix, text)
                self.assertNotIn(sys.version, text)
                self.assertIsNone(re.search(r"\b(19|20)\d{2}-\d{2}-\d{2}[T ]\d{2}:\d{2}", text))
                self.assertIsNone(re.search(r'"(generated_at|timestamp|created_at|modified_at|host|user|machine)"', text))
        for path in (root / "summary.md", root / "audit.md"):
            self.assertIn(self.report["input_sha256"], by_path[path])

    def test_check_names_the_audited_inputs_that_moved(self):
        # "Every report differs" is the normal symptom of one changed, missing, or extra audited
        # source file, because the fingerprint is stamped into all of them. --check must say which.
        inputs = dict(self.report["inputs"])
        stale = {key: value for key, value in inputs.items() if key != "APP/combat/typed_executor.py"}
        stale["APP/combat/ext/example.py"] = "0" * 64
        stale["APP/tools/automation_truth.py"] = "1" * 64
        message = "\n".join(truth.check_drift_lines(stale, inputs))
        self.assertIn("APP/combat/ext/example.py", message)
        self.assertIn("APP/combat/typed_executor.py", message)
        self.assertIn("missing from this checkout", message)
        self.assertIn("content changed", message)
        self.assertEqual(truth.check_drift_lines(inputs, inputs), [])
        self.assertEqual(truth.check_drift_lines({}, {}), [])


class CommittedReportReproducibilityTests(unittest.TestCase):
    def test_a_fresh_process_with_another_hash_seed_reproduces_the_committed_reports(self):
        """The owner's acceptance check: a second interpreter reproduces every committed byte.

        PYTHONHASHSEED changes set and dict iteration order, so a fresh process with a fixed,
        different seed proves the reports carry no hash-order, clock, or machine dependence, and that
        the checked-in files still match the audited sources they name.
        """
        env = dict(os.environ, PYTHONHASHSEED="20261005", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, "-m", "tools.automation_truth", "--check"],
                                cwd=ROOT / "APP", env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["mechanics"])


class CompilerReaderIsolationTests(unittest.TestCase):
    def test_compact_json_keys_have_real_source_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "authority.json").write_text('{"schema":"fixture","mechanics":{"A":{"name":"One"},"B":{"name":"Two"}}}\n')
            evidence = truth.Evidence(root)
            self.assertEqual(evidence.key("authority.json", "A"), "authority.json:1")
            self.assertEqual(evidence.key("authority.json", "B"), "authority.json:1")
            with self.assertRaises(ValueError):
                evidence.key("authority.json", "not_present")

    def test_missing_reader_definition_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / truth.COMPILER
            target.parent.mkdir(parents=True)
            original = (ROOT / truth.COMPILER).read_text(encoding="utf-8")
            target.write_text(original.replace("def _gm_lines(", "def _renamed_gm_lines(", 1), encoding="utf-8")
            with patch.object(truth, "ROOT", root), self.assertRaisesRegex(ValueError, "_gm_lines"):
                truth._compiler_readers()

    def test_new_unavailable_reader_dependency_is_not_silently_substituted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / truth.COMPILER
            target.parent.mkdir(parents=True)
            original = (ROOT / truth.COMPILER).read_text(encoding="utf-8")
            target.write_text(original.replace('    labels = {str(option.get("label")',
                                               '    _new_audit_dependency()\n    labels = {str(option.get("label")', 1),
                              encoding="utf-8")
            with patch.object(truth, "ROOT", root), self.assertRaisesRegex(ValueError, "_new_audit_dependency"):
                truth._compiler_readers()

    def test_new_helpers_and_constants_are_resolved_transitively(self):
        source = '''
raise AssertionError("The full compiler module must not execute")
BASE = "flowers"
PREFIX: str = BASE + ": "
# Keep the old extractor's fixed constant list satisfied, so its failure is
# specifically the missing new helper rather than an unrelated missing seed.
_STAT_SEGMENT = _PLAIN_COST = _CL_DAMAGE_LINE = _TYPING_HISTORY = None
_TYPING_NOTE = _STILL_THE_GMS = _NOT_A_WEAPON_LINE = _CHOICE_CUE = _CHOICE_HEAD = None
MAX_OPTIONS_PER_ABILITY = 6
HANDLED_IN_CODE = frozenset()
def _typed_stat_line(*args): return False
def _printed_choices(*args): return set()
def _rules_text(): return {}
def _walk(effects): return iter(effects)
def _gm_lines(riders, mechanic, effects, option_label=None):
    return [_new_helper(line) for line in riders]
def _new_helper(line):
    def nested(value):
        return _another_helper(value)
    return PREFIX + nested(line)
def _another_helper(value):
    local_only = value.upper()
    return local_only
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / truth.COMPILER
            target.parent.mkdir(parents=True)
            target.write_text(source, encoding="utf-8")
            with patch.object(truth, "ROOT", root):
                readers = truth._compiler_readers()
            self.assertEqual(readers._gm_lines(["new prerequisite"], {}, []), ["flowers: NEW PREREQUISITE"])
            self.assertEqual(readers.PREFIX, "flowers: ")

    def test_service_import_dependency_is_rejected_without_importing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / truth.COMPILER
            target.parent.mkdir(parents=True)
            original = (ROOT / truth.COMPILER).read_text(encoding="utf-8")
            target.write_text('from imaginary_service import service_reader\n' + original.replace(
                '    labels = {str(option.get("label")',
                '    service_reader()\n    labels = {str(option.get("label")', 1), encoding="utf-8")
            with patch.object(truth, "ROOT", root), self.assertRaisesRegex(ValueError, "service_reader"):
                truth._compiler_readers()

    def test_import_does_not_load_runtime_or_authoring_services(self):
        code = (
            "import sys; from tools import automation_truth; "
            "assert not {'combat.factory_compiler','combat.typed_executor','combat.gate4_engine',"
            "'factory_authoring.service','app.core'} & set(sys.modules)"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "APP", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
