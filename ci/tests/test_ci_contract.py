from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CI_ROOT = REPOSITORY_ROOT / "ci"
sys.path.insert(0, str(CI_ROOT))

from common import CLASSIFICATIONS  # noqa: E402
from run_full_product import Tee, classify_exception  # noqa: E402
from run_tier import (  # noqa: E402
    classify_failure,
    pytest_command,
    pytest_work_session,
    validate_work_root,
)
from validate_json_schemas import load_json  # noqa: E402


class CIContractTests(unittest.TestCase):
    def test_tier_failure_matrix_separates_product_harness_and_infrastructure(self) -> None:
        self.assertEqual(classify_failure("focused_tests", 1), "PRODUCT_FAILURE")
        self.assertEqual(classify_failure("focused_tests", 4), "HARNESS_FAILURE")
        self.assertEqual(classify_failure("focused_tests", 2), "INFRASTRUCTURE_BLOCKER")
        self.assertEqual(classify_failure("ci_contract", 1), "HARNESS_FAILURE")
        self.assertEqual(classify_failure("catalog_compile_a", 1), "PRODUCT_FAILURE")
        self.assertEqual(classify_failure("catalog_compile_a", 127), "HARNESS_FAILURE")
        self.assertEqual(classify_failure("catalog_compile_a", 124), "INFRASTRUCTURE_BLOCKER")

    def test_full_product_wrapper_is_stream_compatible_and_classifies_its_own_faults(self) -> None:
        class Stream:
            encoding = "utf-8"

            def write(self, value: str) -> int:
                return len(value)

            def flush(self) -> None:
                return None

            def isatty(self) -> bool:
                return False

            def fileno(self) -> int:
                return 7

        tee = Tee(Stream())
        self.assertFalse(tee.isatty())
        self.assertEqual(tee.encoding, "utf-8")
        self.assertEqual(tee.fileno(), 7)
        self.assertEqual(
            classify_exception(AttributeError("'Tee' object has no attribute 'isatty'"), {"product_started": True}),
            "HARNESS_FAILURE",
        )

    def test_full_product_working_data_is_outside_artifact_root(self) -> None:
        text = (CI_ROOT / "run_full_product.py").read_text(encoding="utf-8")
        self.assertIn('TemporaryDirectory(prefix="tianxia-ci1-p1-"', text)
        self.assertNotIn('output / "ephemeral-product-data"', text)
        self.assertIn('sys.pycache_prefix = str(pycache_root)', text)
        self.assertIn('os.environ["PYTHONPYCACHEPREFIX"] = str(pycache_root)', text)

    def test_pytest_work_root_normalizes_paths_and_rejects_all_evidence_overlaps(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "evidence"
            output.mkdir()
            unsafe_roots = (
                output,
                output / "nested-work",
                root,
            )
            for unsafe in unsafe_roots:
                with self.assertRaises(ValueError):
                    validate_work_root(output, unsafe)
                with self.assertRaises(ValueError):
                    with pytest_work_session(output, unsafe, "fast"):
                        pass

            normalized = validate_work_root(output, root / "nested" / ".." / "work")
            self.assertEqual(normalized, (root / "work").resolve())

    def test_pytest_command_rejects_basetemp_inside_evidence_output(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            output.mkdir()
            with self.assertRaises(ValueError):
                pytest_command(output, output / "pytest-tmp", "proof.xml", ("proof_test.py",))

    def test_pytest_command_keeps_junit_durable_and_working_data_external(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "evidence"
            output.mkdir()
            (output / "junit").mkdir()
            work_root = root / "work"
            work_root.mkdir()
            marker = work_root / "unrelated.txt"
            marker.write_text("preserve me", encoding="utf-8")
            proof_test = root / "proof_test.py"
            proof_test.write_text(
                "def test_external_basetemp_proof(tmp_path):\n"
                "    (tmp_path / 'transient-marker').write_text('ephemeral', encoding='utf-8')\n"
                "    assert True\n",
                encoding="utf-8",
            )

            with pytest_work_session(output, work_root, "fast") as basetemp:
                command = pytest_command(output, basetemp, "proof.xml", (str(proof_test),))
                basetemp_argument = next(part for part in command if part.startswith("--basetemp="))
                junit_argument = next(part for part in command if part.startswith("--junitxml="))
                actual_basetemp = Path(basetemp_argument.split("=", 1)[1]).resolve()
                actual_junit = Path(junit_argument.split("=", 1)[1]).resolve()
                self.assertIn(work_root.resolve(), actual_basetemp.parents)
                self.assertNotIn(output.resolve(), (actual_basetemp, *actual_basetemp.parents))
                self.assertIn(output.resolve(), actual_junit.parents)

                completed = subprocess.run(
                    command,
                    cwd=str(REPOSITORY_ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout)
                self.assertTrue(actual_junit.is_file())
                self.assertTrue(actual_basetemp.is_dir())
                owned_root = actual_basetemp.parent

            self.assertTrue(marker.is_file())
            self.assertFalse(owned_root.exists())
            self.assertTrue(actual_junit.is_file())

    def test_json_validator_preserves_accepted_windows_encodings(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-32"):
                path = root / f"record-{encoding}.json"
                path.write_text('{"status":"PASS"}', encoding=encoding)
                self.assertEqual(load_json(path), {"status": "PASS"}, encoding)

    def test_failure_classifications_are_exact(self) -> None:
        self.assertEqual(
            set(CLASSIFICATIONS),
            {"PASS", "PRODUCT_FAILURE", "HARNESS_FAILURE", "INFRASTRUCTURE_BLOCKER"},
        )

    def test_fast_workflow_has_required_triggers_and_no_schedule(self) -> None:
        text = (REPOSITORY_ROOT / ".github" / "workflows" / "ci-fast.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request:", text)
        self.assertIn("push:", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("schedule:", text)

    def test_integration_is_dispatchable_and_reusable(self) -> None:
        text = (REPOSITORY_ROOT / ".github" / "workflows" / "ci-integration.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("workflow_call:", text)
        self.assertNotIn("schedule:", text)

    def test_tier_workflows_bind_external_runner_temp_work_roots(self) -> None:
        for tier in ("fast", "integration"):
            text = (REPOSITORY_ROOT / ".github" / "workflows" / f"ci-{tier}.yml").read_text(encoding="utf-8")
            self.assertIn(f'--work-root "$RUNNER_TEMP/ci1-{tier}-work"', text, tier)

    def test_full_product_is_manual_linux_and_windows_only(self) -> None:
        text = (REPOSITORY_ROOT / ".github" / "workflows" / "ci-full-product.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("pull_request:", text)
        self.assertNotIn("push:", text)
        self.assertNotIn("schedule:", text)
        self.assertIn("ubuntu-latest", text)
        self.assertIn("windows-latest", text)

    def test_all_workflows_upload_bounded_artifacts(self) -> None:
        for name in ("ci-fast.yml", "ci-integration.yml", "ci-full-product.yml"):
            text = (REPOSITORY_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            self.assertIn("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", text, name)
            self.assertIn("retention-days: 1", text, name)
            self.assertIn("ci/finalize_artifacts.py", text, name)
            self.assertIn("stage-timings.json", text, name)


if __name__ == "__main__":
    unittest.main()
