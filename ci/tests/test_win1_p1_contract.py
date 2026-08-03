from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIN1 = ROOT / "win1_p1"
PACKAGE = WIN1 / "package"
WORKFLOW = ROOT / ".github" / "workflows" / "win1-p1-owner-test.yml"


class Win1P1ContractTests(unittest.TestCase):
    def test_accepted_app_is_not_replaced_by_a_second_application(self) -> None:
        delta = (WIN1 / "BOUNDED_DELTA.md").read_text(encoding="utf-8")
        self.assertIn("candidate `APP/` tree contains the issue #8 repair", delta)
        self.assertIn("does not mutate it at build time", delta)
        self.assertFalse((WIN1 / "APP").exists())

    def test_supported_launchers_force_only_owner_test_roots(self) -> None:
        primary = (PACKAGE / "LAUNCH_TIANXIA_OWNER_TEST.cmd").read_text(encoding="utf-8")
        clean = (PACKAGE / "LAUNCH_CLEAN_IMPORT_TEST.cmd").read_text(encoding="utf-8")
        self.assertIn('set "OWNER_TEST_ROOT=%~dp0OwnerTestData"', primary)
        self.assertIn('set "OWNER_TEST_ROOT=%~dp0OwnerTestData\\CleanFactory"', clean)
        for launcher in (primary, clean):
            self.assertIn('set "TIANXIA_FOUNDRY_DATA=%OWNER_TEST_ROOT%"', launcher)
            self.assertIn("%~dp0Application\\Tianxia Factory.exe", launcher)
            self.assertNotIn("%LOCALAPPDATA%", launcher)
            self.assertNotIn("\\UserData", launcher)

    def test_owner_docs_cover_full_bounded_workflow_and_removal(self) -> None:
        checklist = (PACKAGE / "OWNER_TEST_CHECKLIST.md").read_text(encoding="utf-8")
        for phrase in (
            "normal Character Builder wizard",
            "Save the project",
            "export the Character ZIP",
            "LAUNCH_CLEAN_IMPORT_TEST.cmd",
            "Import Character ZIP",
            "OPEN_EXACT_GM_SCREEN.cmd",
            "Save, close, reopen",
            "REMOVE_OWNER_TEST_BUILD.md",
        ):
            self.assertIn(phrase, checklist)
        removal = (PACKAGE / "REMOVE_OWNER_TEST_BUILD.md").read_text(encoding="utf-8")
        self.assertIn("Delete only the complete extracted", removal)
        self.assertIn("production `UserData`", removal)

    def test_exact_gm_screen_launcher_is_commitment_bound(self) -> None:
        expected = hashlib.sha256(
            (ROOT / "APP" / "gm_screen" / "HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip").read_bytes()
        ).hexdigest()
        launcher = (PACKAGE / "Tools" / "Open-ExactGMScreen.ps1").read_text(encoding="utf-8")
        self.assertEqual(expected, "c281c80e96c718a2c629b65c762b1c053a82eff7201d018a6acca1110c1c0f8f")
        self.assertIn(expected, launcher)
        self.assertIn("OwnerTestData\\ExactGMScreen", launcher)

    def test_workflow_is_bounded_and_has_no_schedule(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertIn('contents: read', workflow)
        self.assertIn('persist-credentials: false', workflow)
        self.assertIn("work/win1-p1", workflow)
        self.assertIn("Invoke-Win1P1Build.ps1", workflow)
        self.assertIn("retention-days: 14", workflow)

    def test_delivery_verifier_and_isolation_proof_are_wired(self) -> None:
        build = (WIN1 / "Invoke-Win1P1Build.ps1").read_text(encoding="utf-8")
        self.assertIn("Verify-OwnerTestIsolation.ps1", build)
        self.assertIn("verify_delivery.py", build)
        self.assertIn("production_userdata_untouched=$true", build)
        self.assertIn("final_release_readiness_claimed=$false", build)
        self.assertIn("Stage-AcceptedRuntimeData.ps1", build)
        stager = (WIN1 / "Stage-AcceptedRuntimeData.ps1").read_text(encoding="utf-8")
        self.assertIn("canonical_spheres.v1.json", stager)
        self.assertIn("background_origin_talent_routes.v1.json", stager)
        self.assertIn("Get-FileHash", stager)
        self.assertIn("app_source_modified=$false", stager)

    def test_final_application_checksum_inventory_is_regenerated_and_exact(self) -> None:
        build = (WIN1 / "Invoke-Win1P1Build.ps1").read_text(encoding="utf-8")
        verifier = (WIN1 / "verify_delivery.py").read_text(encoding="utf-8")
        self.assertLess(build.index("Write-Json $Version $VersionPath"), build.index("final_application_checksum_generation"))
        self.assertLess(build.index("native_isolation_verification"), build.index("post_isolation_application_checksum_verification"))
        self.assertIn("clean_extraction", verifier)
        self.assertIn("extracted_delivery = clean_root / delivery.name", verifier)
        self.assertIn("clean-extracted delivery differs from staged final delivery", verifier)
        with tempfile.TemporaryDirectory() as temporary:
            application = Path(temporary) / "Application"
            application.mkdir()
            (application / "VERSION.json").write_text('{"status":"final"}\n', encoding="utf-8")
            (application / "payload.bin").write_bytes(b"final payload")
            output = Path(temporary) / "receipt.json"
            result = subprocess.run(
                [sys.executable, str(WIN1 / "application_checksum.py"), "--application", str(application), "--generate", "--output", str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            receipt = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["declared_count"], 2)
            self.assertEqual(receipt["checked_count"], 2)
            self.assertEqual(receipt["missing_count"], 0)
            self.assertEqual(receipt["unexpected_count"], 0)
            self.assertEqual(receipt["hash_mismatch_count"], 0)
            self.assertTrue(receipt["deterministic_path_order"])
            self.assertTrue(receipt["version_json"]["matches"])
            sums = (application / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual([line[66:] for line in sums], ["VERSION.json", "payload.bin"])

    def test_windows_baseline_disposition_is_exactly_one_accepted_node(self) -> None:
        plugin = (WIN1 / "pytest_windows_baseline.py").read_text(encoding="utf-8")
        build = (WIN1 / "Invoke-Win1P1Build.ps1").read_text(encoding="utf-8")
        node = (
            "tests/test_r6_6_7_1_character_builder_owner_feedback.py::"
            "test_complete_fixture_exports_exact_gm_zip_and_passes_bundled_importer"
        )
        self.assertIn(f'NODE_ID = (', plugin)
        self.assertEqual(plugin.count("item.add_marker(pytest.mark.skip"), 1)
        self.assertIn("os.name != \"nt\"", plugin)
        self.assertIn(node, build)
        self.assertIn("windows-baseline-disposition.json", build)
        self.assertIn("accepted_full_product_run=30687338858", build)
        self.assertIn("app_source_modified=$true", build)
        self.assertIn("win1_p1r2_changed_surfaces_covered_by_prior_receipt=$false", build)
        self.assertIn("win1_p1r2_native_receipt", build)
        self.assertIn("win1_p1r2_authority=$false", build)
        self.assertNotIn("APP and executable product/test bodies are unchanged", build)
        self.assertNotIn("$env:PYTHONPATH =", build)
        self.assertIn("win1_pytest_windows_baseline", build)
        self.assertIn("failed-launcher-state.json", build)
        self.assertIn("failed-startup.log", build)
        self.assertIn("accepted-verifier-compatibility.json", build)
        self.assertIn("-TempRoot $NativeTempRoot", build)
        self.assertIn("[char]0x03B2", build)
        self.assertIn("$_['elapsed_seconds']", build)
        self.assertNotIn("Measure-Object -Property elapsed_seconds", build)
        plugin_stager = (WIN1 / "Stage-PytestBaselinePlugin.ps1").read_text(encoding="utf-8")
        self.assertIn("temporary_build_venv_only=$true", plugin_stager)
        self.assertIn("packaged_runtime_modified=$false", plugin_stager)


if __name__ == "__main__":
    unittest.main()
