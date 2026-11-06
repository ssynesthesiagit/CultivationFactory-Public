"""Generate the SOL58b compatibility oracle with the unchanged 672ec109 engine.

Run from a temporary detached worktree at 672ec109, using its APP on PYTHONPATH:
  PYTHONPATH=<base>/APP python <candidate>/APP/tests/fixtures/generate_historical_seeded_recipes.py \
      --root <base>/APP --scratch /var/tmp/auto-audit/sol58b-scratch/generation \
      --output <candidate>/APP/tests/fixtures/historical_seeded_recipes.json.gz

The scratch path must not exist. Freeze entropy/time only in this fixture process;
constructors, source loaders and creation services are the base engine's real
implementations. No AI, browser or live data is allowed.
Gzip uses mtime=0; JSON uses sorted keys. Repeat with the same scratch path
after cleanup to reproduce the fixture bytes. Do not run against the candidate.

The two helpers this script loads (tests/historical_seeded_recipes_support.py, which the
regression test shares) are the comparison bodies as they stood at 672ec109; no pin holds
them, so editing them changes what regeneration compares. Do not update them to new APIs,
or regeneration stops describing the base engine that produced the fixture. They live in
the candidate tests package and are loaded by path because the base checkout supplies its
own tests package on PYTHONPATH.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

BASE_COMMIT = "672ec109"
BASE_AUTHORITY_SHA256 = "65dbbeb1be02fe79a8f1d21c8d5dfee8d88501f4eadbbec916b2db410c6a24b2"
# The capture helpers this script compares with, spelled repo-relative from the APP folder so both the path used here
# and the public export's dependency scan read the same name: an unquoted path built with Path operators is invisible
# to that scan, which is how an earlier version shipped without the helper and failed on public CI.
SUPPORT_FILE = "tests/historical_seeded_recipes_support.py"

# The base checkout supplies the tests package; load the candidate helpers by path.
_spec = importlib.util.spec_from_file_location(
    "historical_seeded_recipes_support", Path(__file__).resolve().parents[2] / SUPPORT_FILE
)
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)
capture, missing_marker_capture = _support.capture, _support.missing_marker_capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="Export an already completed disposable base build after an export failure")
    args = parser.parse_args()
    # Identity marker for the base checkout: 672ec109's typed authority. A candidate tree fails it, so this never
    # runs the oracle against code newer than the fixture it is about to regenerate.
    base_authority = args.root / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
    assert hashlib.sha256(base_authority.read_bytes()).hexdigest() == BASE_AUTHORITY_SHA256, \
        f"--root must be a {BASE_COMMIT} base checkout"
    assert args.resume or not args.scratch.exists(), "Use an empty task-owned scratch path"
    args.scratch.mkdir(parents=True, exist_ok=args.resume)
    (args.scratch / "tmp").mkdir(exist_ok=args.resume)
    os.environ["TMPDIR"] = str(args.scratch / "tmp")
    tempfile.tempdir = os.environ["TMPDIR"]

    def no_browser(event, values):
        if event == "subprocess.Popen" and any(word in str(values[:2]).lower() for word in (
            "exact_consumer_harness.py", "run_command6.py", "chromium", "chrome", "firefox", "playwright")):
            from app.core import FoundryError
            raise FoundryError("SOL58_BROWSER_BLOCKED", "Lead must run browser acceptance outside the sandbox")
    sys.addaudithook(no_browser)

    from app.api import create_app
    from app.core import Settings
    from ai_provider.secrets import InMemorySecretStore
    from product_bootstrap.service import ProductBootstrapService
    from tests.r4v_harness import provision_external_test_key
    import character_creation.service as engine
    assert Path(engine.__file__).resolve().is_relative_to(args.root.resolve()), "PYTHONPATH must select the base engine"
    settings = Settings.from_env(args.root, args.scratch / "data")
    provision_external_test_key(settings.data_dir)
    counters = {"uuid": 0, "nonce": 0}

    def next_uuid():
        counters["uuid"] += 1
        return uuid.UUID(int=counters["uuid"])

    def next_nonce(*args):
        counters["nonce"] += 1
        return hashlib.sha256(f"SOL58b historical nonce {counters['nonce']}".encode()).hexdigest()

    from contextlib import ExitStack
    with ExitStack() as stack:
        stack.enter_context(patch("uuid.uuid4", next_uuid))
        stack.enter_context(patch("secrets.token_urlsafe", next_nonce))
        for module in list(sys.modules.values()):
            if getattr(module, "__file__", "") and str(args.root) in str(module.__file__) and hasattr(module, "utcnow"):
                stack.enter_context(patch.object(module, "utcnow", lambda: "2026-09-01T00:00:00+00:00"))
        if not args.resume:
            ProductBootstrapService(settings).run()
        def no_ai(*args, **kwargs):
            raise AssertionError("Historical seeded fixture must not use AI")
        app = create_app(settings, ai_transport=no_ai, ai_secret_store=InMemorySecretStore())
        app.state.ai_provider.configure(enabled=True, provider_id="deepseek", endpoint="https://api.deepseek.com/chat/completions", model="deepseek-v4-flash", thinking_mode="enabled", max_output_tokens=1024, timeout_seconds=30, data_sharing_acknowledged=True, acknowledged_by="test")
        service = app.state.character_creation
        if args.resume:
            with service.db.connection() as conn:
                row = conn.execute("SELECT run_id FROM character_creation_runs WHERE idempotency_key='SOL58b-historical-fixture'").fetchone()
            run = service.get(row["run_id"])
        else:
            created = app.state.character_builder.create_project(working_name="", concept="A Body Refining fighter who protects allies.", source_reference=None, target_cl=15, power_band="rival/boss", creation_mode="quick", generation_route="ai_bootstrap", ability_scores={}, selections={}, autogen_seed="Q59-CL5-P0-V1", project_id_override="00000000-0000-0000-0000-0000000058b0")
            app.state.character_builder.commit_normal_first_cycle_catalog_choices(created["project_id"])
            run = service.start(created["project_id"], execution_mode="STANDARD_API", idempotency_key="SOL58b-historical-fixture", controller_route="DETERMINISTIC_CREATIVE_CONTROLLER")
        assert {b["code"] for b in run["blockers"]} == {"SOL58_BROWSER_BLOCKED"}, run["blockers"]
        expected = capture(service, run)
        missing = missing_marker_capture(service, run)
        tables = {}
        with service.db.connection() as conn:
            for table in ("projects", "project_content_locks", "project_locked_record_refs", "character_creation_runs", "dcc_controller_run_bindings", "dcc_controller_events"):
                tables[table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table} WHERE project_id=? ORDER BY rowid", (run["project_id"],))]
            # Keep exact persisted authority/response, not disposable compiler
            # paths, timings, transport logs or unrelated validation output.
            run_columns = {"run_id", "project_id", "starting_revision", "execution_mode", "idempotency_key", "request_json", "response_json", "status", "created_at", "updated_at"}
            tables["character_creation_runs"] = [{key: value for key, value in row.items() if key in run_columns} for row in tables["character_creation_runs"]]
            tables["locked_record_blobs"] = [dict(row) for row in conn.execute("SELECT * FROM locked_record_blobs WHERE record_hash IN (SELECT record_hash FROM project_locked_record_refs WHERE project_id=?) ORDER BY record_hash", (run["project_id"],))]
        supplements = {str(path.relative_to(settings.data_dir)): path.read_text() for path in sorted(settings.data_dir.glob("creation_training_authority_supplements/**/*.json"))}
        fixture = {"base_commit": "672ec109", "run_id": run["run_id"], "tables": tables, "supplements": supplements, "expected": expected, "missing_marker": missing}
        args.output.write_bytes(gzip.compress((json.dumps(fixture, sort_keys=True, separators=(",", ":")) + "\n").encode(), mtime=0))
        print(f"Fixture {args.output}: {args.output.stat().st_size} bytes, sha256={hashlib.sha256(args.output.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
