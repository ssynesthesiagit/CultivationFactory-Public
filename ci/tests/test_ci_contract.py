from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CI_ROOT = REPOSITORY_ROOT / "ci"
sys.path.insert(0, str(CI_ROOT))

from common import ACCEPTED_SOURCE_SUMS, CLASSIFICATIONS, sha256_file  # noqa: E402
from run_full_product import Tee, classify_exception  # noqa: E402
from run_tier import classify_failure  # noqa: E402
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

    def test_json_validator_preserves_accepted_windows_encodings(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-32"):
                path = root / f"record-{encoding}.json"
                path.write_text('{"status":"PASS"}', encoding=encoding)
                self.assertEqual(load_json(path), {"status": "PASS"}, encoding)

    def test_source_baseline_matches_the_current_repair_inventory(self) -> None:
        baseline = json.loads((CI_ROOT / "source-baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(
            baseline["application_source"]["source_tree_commitment_sha256"],
            sha256_file(ACCEPTED_SOURCE_SUMS),
        )
        self.assertEqual(
            baseline["catalog"]["registry_commitment_sha256"],
            "b53d36b6da5f3d8ead46e01cd07bbfc0f80e35043e7f3ef0f2e11d5fb79e35df",
        )
        self.assertEqual(baseline["application_source"]["file_count"], 1732)
        self.assertEqual(baseline["application_source"]["total_bytes"], 274091337)

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
            self.assertIn("actions/upload-artifact@v4", text, name)
            self.assertIn("ci/finalize_artifacts.py", text, name)
            self.assertIn("stage-timings.json", text, name)


if __name__ == "__main__":
    unittest.main()
