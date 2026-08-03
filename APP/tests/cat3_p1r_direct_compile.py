from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx

from ai_provider.secrets import InMemorySecretStore
from app.api import create_app
from app.core import Settings, sha256_json
from tests.cat3_p1r_browser_harness import provider_handler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument(
        "--browser",
        default=r"C:\Users\ssyne\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe",
    )
    args = parser.parse_args()
    os.environ["TIANXIA_BROWSER_EXECUTABLE"] = args.browser

    context: dict[str, Any] = {}
    app = create_app(
        Settings.from_env(args.root.resolve(), args.data.resolve()),
        ai_transport=httpx.MockTransport(provider_handler(context)),
        ai_secret_store=InMemorySecretStore("cat3-p1r-direct-compile-key"),
    )
    context["app"] = app
    app.state.ai_provider.configure(
        enabled=True,
        model="deepseek-v4-flash",
        thinking_mode="disabled",
        max_output_tokens=8192,
        timeout_seconds=60,
        data_sharing_acknowledged=True,
        acknowledged_by="CAT3-P1R deterministic direct preserved-project compiler check",
    )
    before_envelope = app.state.projects.get_project(args.project_id)
    before = {
        **before_envelope["project"],
        "project_id": before_envelope["project_id"],
        "revision": before_envelope["revision"],
        "working_name": before_envelope["working_name"],
    }
    run = app.state.character_creation.start(
        args.project_id,
        execution_mode="STANDARD_API",
        idempotency_key=args.idempotency_key,
    )
    after_envelope = app.state.projects.get_project(args.project_id)
    after = {
        **after_envelope["project"],
        "project_id": after_envelope["project_id"],
        "revision": after_envelope["revision"],
        "working_name": after_envelope["working_name"],
    }
    snapshot = run.get("request", {}).get("typed_choice_snapshot") or {}
    snapshot_evidence = {
        key: value for key, value in snapshot.items() if key != "typed_locks"
    }
    snapshot_evidence["typed_lock_count"] = len(snapshot.get("typed_locks") or [])
    snapshot_evidence["typed_lock_bindings"] = [
        {
            "lock_id": lock.get("lock_id"),
            "field": lock.get("field"),
            "typed_lock_sha256": sha256_json(lock),
        }
        for lock in snapshot.get("typed_locks") or []
    ]
    dry_run = run.get("dry_run") or {}
    report = {
        "schema": "TianxiaFactory.CAT3P1RDirectPreservedProjectCompile.v1",
        "status": run.get("status"),
        "project_id": args.project_id,
        "run_id": run.get("run_id"),
        "project_unchanged_by_scratch_compile": before == after,
        "project_revision": before.get("revision"),
        "content_lock_hash": (before.get("content_lock") or {}).get("lock_hash"),
        "typed_choice_snapshot": snapshot_evidence,
        "same_server_project_identity": snapshot.get("canonical_project_id") == args.project_id,
        "working_name_is_display_content_only": (
            snapshot.get("display_name_content") == before.get("working_name")
            and snapshot.get("canonical_project_id") == before.get("project_id")
        ),
        "dry_run": {
            key: (
                snapshot_evidence
                if key == "typed_choice_snapshot" and dry_run.get(key) == snapshot
                else dry_run.get(key)
            )
            for key in (
                "schema",
                "candidate_identity",
                "typed_choice_snapshot",
                "identities",
                "deterministic",
                "independent_compilations",
            )
        },
        "quality_report": run.get("quality"),
        "blockers": run.get("blockers"),
        "warnings": run.get("warnings"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if run.get("status") == "READY_FOR_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
