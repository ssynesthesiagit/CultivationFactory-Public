from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_provider.secrets import InMemorySecretStore
from app.api import create_app
from app.core import Settings, canonical_json
from catalog.service import CatalogService
from character_creation.current_fixture import W5_PROJECT_ID, create_fresh_project
from vendor_adapter.service import FactoryAdapter

FACTORY = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"


def provider_handler(behavior_file: Path, provider_log: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        behavior = behavior_file.read_text(encoding="utf-8").strip()
        with provider_log.open("a", encoding="utf-8") as stream:
            stream.write(f"{behavior}\n")
        if behavior == "failure":
            return httpx.Response(503, json={"error": "deterministic browser-provider outage"})
        request_payload = json.loads(request.content)
        user_prompt = next((row.get("content", "") for row in request_payload.get("messages", []) if row.get("role") == "user"), "")
        content = canonical_json({"connection": "ok"}) if '"connection":"ok"' in user_prompt else canonical_json(
            {"schema": "TianxiaFoundry.CharacterCreationPlan.v2", "request_sha256": "0" * 64}
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
        )

    return handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--behavior-file", type=Path, required=True)
    parser.add_argument("--provider-log", type=Path, required=True)
    parser.add_argument("--include-fixture", action="store_true")
    args = parser.parse_args()

    settings = Settings.from_env(ROOT, args.data_root)
    app = create_app(
        settings,
        ai_transport=httpx.MockTransport(provider_handler(args.behavior_file, args.provider_log)),
        ai_secret_store=InMemorySecretStore("browser-deepseek-key-123"),
    )
    configured = FactoryAdapter(app.state.db).configure(FACTORY)
    CatalogService(app.state.db).rebuild_core(Path(configured["factory_root"]))
    if args.include_fixture:
        create_fresh_project(app.state.db, project_id=W5_PROJECT_ID)
        app.state.projects.save_builder_draft(W5_PROJECT_ID)
    app.state.ai_provider.configure(
        enabled=True,
        model="deepseek-v4-flash",
        thinking_mode="disabled",
        max_output_tokens=8192,
        timeout_seconds=30,
        data_sharing_acknowledged=True,
        acknowledged_by="W5-P1R-R1 real browser acceptance",
    )
    app.state.ai_provider.test_connection()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
