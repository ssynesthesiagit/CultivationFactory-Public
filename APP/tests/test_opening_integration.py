from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Database, FoundryError, Settings
from opening_ui import server as server_module
from opening_ui.server import CampaignService, UiError, asdict_item
from portable_character.level0 import build_mortal_level0_package
import portable_character.service as portable_service_module
from portable_character.service import PortableCharacterPackageService
from product_bootstrap import ProductBootstrapService
from services.factory_dm_v0 import CampaignController, CampaignIdentity, DeterministicClock
from services.factory_dm_v0.domain import Faction, Location
from services.factory_dm_v0.gameplay.character_adapter import (
    AdmissionError,
    admission_from_trusted_portable_package,
    validate_level0_admission,
)
from services.factory_dm_v0.gameplay.integration import resolve, rule_refs
from services.factory_dm_v0.gameplay.models import EngineError, Item
from services.factory_dm_v0.gameplay.profile import (
    LEGACY_PROFILE_V9_IDENTITY,
    LEGACY_PROFILE_V9_MANIFEST_DIGEST,
    RELEASED_CURRENT_PROFILE_V9_IDENTITY,
    RELEASED_CURRENT_PROFILE_V9_MANIFEST_DIGEST,
    PREVIOUS_CREATOR_PROFILE_V9_IDENTITY,
    PREVIOUS_CREATOR_PROFILE_V9_MANIFEST_DIGEST,
    PREVIOUS_PROFILE_V9_IDENTITY,
    PREVIOUS_PROFILE_V9_MANIFEST_DIGEST,
    digest,
    manifest,
    profile_identity_is_compatible,
    validate_profile,
)
from services.factory_dm_v0.gameplay.trusted_producer import (
    LEGACY_PORTABLE_AUDIT_SOURCE_SHA256,
    LEGACY_PRODUCER_SOURCE_MANIFEST_SHA256,
    RELEASED_CURRENT_LINEAR_PROMPT_SOURCE_SHA256,
    RELEASED_CURRENT_PRODUCER_SOURCE_MANIFEST_SHA256,
    PREVIOUS_CREATOR_LINEAR_PROMPT_SOURCE_SHA256,
    PREVIOUS_CREATOR_PRODUCER_SOURCE_MANIFEST_SHA256,
    PREVIOUS_LINEAR_PROMPT_SOURCE_SHA256,
    PREVIOUS_PRODUCER_SOURCE_MANIFEST_SHA256,
    PRODUCER_SOURCE_MANIFEST,
    _manifest_digest,
    audit_exact_package,
    source_manifest_is_compatible,
)


ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mortal_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("opening-package") / "mortal.zip"
    report = build_mortal_level0_package(
        output,
        character_id="opening-integration-mortal",
        display_name="Opening Integration Mortal",
    )
    assert report["valid"] is True
    return output


def service(tmp_path: Path, package: Path, *, allow_local_tests: bool = False) -> CampaignService:
    return CampaignService(
        data_root=tmp_path / "campaign",
        package_path=package,
        producer_root=ROOT,
        allow_local_tests=allow_local_tests,
    )


def test_current_creator_package_is_freshly_audited_and_admitted(mortal_package: Path) -> None:
    checked = audit_exact_package(mortal_package, producer_root=ROOT)
    assert checked["producer_profile"] == {"id": "factory-current-creator-level0", "version": 1}
    assert checked["manifest"]["build_profile"] == "MORTAL_LEVEL0_SOURCE_VALIDATED"
    assert checked["authority"]["identity"]["cultivation_level"] == 0
    assert all(value == 0 for value in checked["authority"]["paths"]["attainment"].values())

    admission = admission_from_trusted_portable_package(str(mortal_package), producer_root=str(ROOT))
    assert admission["authority_kind"] == "validated_portable_export"
    assert admission["character_id"] == "opening-integration-mortal"
    assert admission["contract"]["profile"]["version"] == 9


def test_mortal_level0_preview_is_valid_but_opening_only(tmp_path: Path, mortal_package: Path) -> None:
    settings = Settings.from_env(APP_ROOT, tmp_path / "factory-data")
    ProductBootstrapService(settings).run()
    preview = PortableCharacterPackageService(Database(settings)).preview_for_factory(mortal_package)

    assert preview["package_valid"] is True
    assert preview["environment_ready"] is True
    assert preview["can_import"] is False
    assert preview["blocking_prerequisites"] == [{
        "code": "MORTAL_LEVEL0_OPENING_ONLY",
        "message": "This valid mortal level-0 package is available through the server-owned /opening route; ordinary Character import requires a complete project package.",
    }]
    assert "/opening" in preview["owner_message"]
    assert "complete project package" in preview["owner_message"]


def _database_rows(db: Database) -> dict[str, list[tuple[object, ...]]]:
    with db.connection() as conn:
        table_names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        quoted = {name: name.replace('"', '""') for name in table_names}
        return {
            name: [tuple(row) for row in conn.execute(f'SELECT * FROM "{quoted[name]}"').fetchall()]
            for name in table_names
        }


def test_mortal_level0_direct_import_is_opening_only_and_non_mutating(
    tmp_path: Path, mortal_package: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.from_env(APP_ROOT, tmp_path / "factory-data")
    ProductBootstrapService(settings).run()
    db = Database(settings)
    importer = PortableCharacterPackageService(db)
    before = _database_rows(db)

    def unexpected_product_readiness(*_args, **_kwargs):
        pytest.fail("opening-only import must reject before product readiness or project work")

    monkeypatch.setattr(portable_service_module.ProductReadinessService, "report", unexpected_product_readiness)
    with pytest.raises(FoundryError) as failure:
        importer.import_into_factory(mortal_package)

    assert failure.value.code == "MORTAL_LEVEL0_OPENING_ONLY"
    assert failure.value.status_code == 409
    assert _database_rows(db) == before


def test_legacy_v9_profile_and_portable_manifest_replay_without_digest_rewrite(
    tmp_path: Path, mortal_package: Path,
) -> None:
    """A retained v9 binding replays byte-for-byte across the creator refresh."""

    # These are the exact historical v9 profile and producer transition pins;
    # the package itself is the ordinary current test fixture above.
    previous_manifest = dict(PRODUCER_SOURCE_MANIFEST)
    previous_manifest["character_creation/creative_controller/linear_prompt.py"] = PREVIOUS_LINEAR_PROMPT_SOURCE_SHA256
    assert _manifest_digest(previous_manifest) == PREVIOUS_PRODUCER_SOURCE_MANIFEST_SHA256
    legacy_manifest = dict(previous_manifest)
    legacy_manifest["portable_character/service.py"] = LEGACY_PORTABLE_AUDIT_SOURCE_SHA256
    assert _manifest_digest(legacy_manifest) == LEGACY_PRODUCER_SOURCE_MANIFEST_SHA256
    current_digest = _manifest_digest(PRODUCER_SOURCE_MANIFEST)
    assert source_manifest_is_compatible(
        dict(PRODUCER_SOURCE_MANIFEST),
        current_digest,
        previous_manifest,
        PREVIOUS_PRODUCER_SOURCE_MANIFEST_SHA256,
    ) is True
    assert source_manifest_is_compatible(
        dict(PRODUCER_SOURCE_MANIFEST),
        current_digest,
        legacy_manifest,
        LEGACY_PRODUCER_SOURCE_MANIFEST_SHA256,
    ) is True
    tampered_manifest = dict(previous_manifest)
    tampered_manifest["character_creation/creative_controller/linear_walk.py"] = "0" * 64
    assert source_manifest_is_compatible(
        dict(PRODUCER_SOURCE_MANIFEST),
        current_digest,
        tampered_manifest,
        PREVIOUS_PRODUCER_SOURCE_MANIFEST_SHA256,
    ) is False

    legacy_profile = manifest()
    legacy_profile["producer_profile"]["source_manifest_sha256"] = LEGACY_PRODUCER_SOURCE_MANIFEST_SHA256
    legacy_profile["producer_profile"]["portable_audit_source_sha256"] = LEGACY_PORTABLE_AUDIT_SOURCE_SHA256
    legacy_profile["admission_dependencies"]["portable_character_audit"]["source_sha256"] = LEGACY_PORTABLE_AUDIT_SOURCE_SHA256
    legacy_profile["admission_dependencies"]["portable_producer_closure"]["source_manifest"] = legacy_manifest
    legacy_profile["admission_dependencies"]["portable_producer_closure"]["source_manifest_sha256"] = LEGACY_PRODUCER_SOURCE_MANIFEST_SHA256
    legacy_profile["handler_sources"].update({
        "engine.py": "83a2eaa88f501e8bacceb55850bfad5cee5fab3e7ced527d03d030c2accf3e14",
        "gameplay/character_adapter.py": "ab9f07a8a0c3aacef5e2804dba61168ae74e521a7a92c55afa9c50add17f6707",
        "gameplay/integration.py": "4af92a541e268b28430c3cae648752908e3a5542ae2a1d3e694b5c10b8039e15",
        "gameplay/profile.py": "c8c6796c5c65e187d2f551ed7bb7b05bae4440479df5c3051364b1565c9e8c26",
        "gameplay/trusted_producer.py": "6065de7a76fe3e4b3599c4958b099fdb7d1c6b22c5aa408993751d18c22e89a7",
    })
    legacy_profile["digest"] = LEGACY_PROFILE_V9_IDENTITY["digest"]
    assert digest(legacy_profile) == LEGACY_PROFILE_V9_MANIFEST_DIGEST
    validate_profile(legacy_profile)

    admission = deepcopy(
        admission_from_trusted_portable_package(str(mortal_package), producer_root=str(ROOT))
    )
    admission["portable_evidence"]["source_manifest"] = deepcopy(legacy_manifest)
    admission["portable_evidence"]["source_manifest_sha256"] = LEGACY_PRODUCER_SOURCE_MANIFEST_SHA256
    admission["contract"]["profile"] = deepcopy(LEGACY_PROFILE_V9_IDENTITY)
    admission["contract"]["source"]["validation_chain"]["source_sha256"] = LEGACY_PORTABLE_AUDIT_SOURCE_SHA256
    admission["digest"] = digest({key: value for key, value in admission.items() if key != "digest"})
    _, actor, _, retained_contract = validate_level0_admission(admission)
    assert retained_contract["profile"] == LEGACY_PROFILE_V9_IDENTITY

    controller = CampaignController.new()
    controller.create_campaign(
        CampaignIdentity("legacy-v9-test", "Legacy v9", 20260908, DeterministicClock())
    )
    controller.add_location(Location("mortal-start", "Porcelain gate", "rest"))
    controller.add_faction(Faction("party", "Party", "Test"))
    actor_id = admission["character_id"]
    controller.bind_gameplay(
        profile=legacy_profile,
        admissions=[admission],
        locations={"mortal-start": {"rest_allowed": True, "cultivation_allowed": False}},
        members={
            "host": {"role": "gm", "actor_ids": []},
            "player": {"role": "player", "actor_ids": [actor_id]},
        },
        items={
            "starter-token": asdict_item(
                Item("starter-token", "Woven gate token", "items", scene_id="mortal-start")
            )
        },
    )

    # The public new-command boundary intentionally requires the current
    # profile.  Use the controller's internal commit only to synthesize one
    # historical persisted event for the replay compatibility check.
    command = {
        "principal_id": "player",
        "actor_id": actor_id,
        "kind": "take_item",
        "payload": {"item_id": "starter-token"},
        "expected_revision": controller.event_count(),
        "request_id": "legacy-take",
        "profile": LEGACY_PROFILE_V9_IDENTITY,
    }
    _, effects = resolve(controller._state, command, lambda sides: 1)
    controller._commit(
        "gameplay_command",
        {"command": command, "rolls": [], "effects": effects, "rules": rule_refs("take_item")},
    )
    before_state_digest = controller.state_digest()
    before_events = controller.events_view()

    save_dir = tmp_path / "legacy-v9-revision"
    controller.save(save_dir)
    snapshot_bytes = (save_dir / "snapshot.json").read_bytes()
    events_bytes = (save_dir / "events.jsonl").read_bytes()
    snapshot = json.loads(snapshot_bytes)
    saved_events = [json.loads(line) for line in events_bytes.splitlines()]

    loaded = CampaignController.load(save_dir)
    assert loaded.state_digest() == before_state_digest == snapshot["state_digest"]
    assert loaded.events_view() == before_events == saved_events
    assert loaded.view()["gameplay"]["profile"] == legacy_profile
    assert loaded.events_view()[-1]["payload"]["command"]["profile"] == LEGACY_PROFILE_V9_IDENTITY
    assert (save_dir / "snapshot.json").read_bytes() == snapshot_bytes
    assert (save_dir / "events.jsonl").read_bytes() == events_bytes
    assert actor.actor_id == actor_id

    wrong_service_hash = deepcopy(admission)
    wrong_service_hash["contract"]["source"]["validation_chain"]["source_sha256"] = "0" * 64
    wrong_service_hash["digest"] = digest({key: value for key, value in wrong_service_hash.items() if key != "digest"})
    with pytest.raises(AdmissionError) as admission_failure:
        validate_level0_admission(wrong_service_hash)
    assert admission_failure.value.code == "PORTABLE_EXPORT_ADMISSION_MISMATCH"

    wrong_profile_digest = deepcopy(legacy_profile)
    wrong_profile_digest["digest"] = "0" * 64
    with pytest.raises(EngineError) as profile_failure:
        validate_profile(wrong_profile_digest)
    assert profile_failure.value.code == "PROFILE_OR_HANDLER_MISMATCH"


def test_released_current_v9_profile_is_exactly_compatible_after_schema_repair() -> None:
    """The immediately prior opening binding accepts only the prompt repair."""

    released_manifest = dict(PRODUCER_SOURCE_MANIFEST)
    released_manifest["character_creation/creative_controller/linear_prompt.py"] = (
        RELEASED_CURRENT_LINEAR_PROMPT_SOURCE_SHA256
    )
    assert _manifest_digest(released_manifest) == RELEASED_CURRENT_PRODUCER_SOURCE_MANIFEST_SHA256
    current_digest = _manifest_digest(PRODUCER_SOURCE_MANIFEST)
    assert source_manifest_is_compatible(
        dict(PRODUCER_SOURCE_MANIFEST),
        current_digest,
        released_manifest,
        RELEASED_CURRENT_PRODUCER_SOURCE_MANIFEST_SHA256,
    ) is True
    tampered_manifest = dict(released_manifest)
    tampered_manifest["character_creation/creative_controller/linear_walk.py"] = "0" * 64
    assert source_manifest_is_compatible(
        dict(PRODUCER_SOURCE_MANIFEST),
        current_digest,
        tampered_manifest,
        RELEASED_CURRENT_PRODUCER_SOURCE_MANIFEST_SHA256,
    ) is False

    released_profile = manifest()
    released_profile["producer_profile"]["source_manifest_sha256"] = RELEASED_CURRENT_PRODUCER_SOURCE_MANIFEST_SHA256
    released_profile["admission_dependencies"]["portable_producer_closure"]["source_manifest"] = deepcopy(released_manifest)
    released_profile["admission_dependencies"]["portable_producer_closure"]["source_manifest_sha256"] = RELEASED_CURRENT_PRODUCER_SOURCE_MANIFEST_SHA256
    released_profile["handler_sources"].update({
        "gameplay/profile.py": "97bb761c63f941d16b68975117f7f2eafe8a2462e52a496a9391c2d85ea44219",
        "gameplay/trusted_producer.py": "a3602717f033e2649f92db10db447eed1f8b44d0dca84a35295b159da4b23324",
    })
    released_profile["digest"] = RELEASED_CURRENT_PROFILE_V9_IDENTITY["digest"]
    assert digest(released_profile) == RELEASED_CURRENT_PROFILE_V9_MANIFEST_DIGEST
    validate_profile(released_profile)
    assert profile_identity_is_compatible(RELEASED_CURRENT_PROFILE_V9_IDENTITY) is True

    tampered_profile = deepcopy(released_profile)
    tampered_profile["handler_sources"]["gameplay/trusted_producer.py"] = "0" * 64
    with pytest.raises(EngineError) as failure:
        validate_profile(tampered_profile)
    assert failure.value.code == "PROFILE_OR_HANDLER_MISMATCH"


def test_previous_current_v9_profile_is_exactly_compatible_after_creator_refresh() -> None:
    previous_manifest = dict(PRODUCER_SOURCE_MANIFEST)
    previous_manifest["character_creation/creative_controller/linear_prompt.py"] = PREVIOUS_LINEAR_PROMPT_SOURCE_SHA256
    assert _manifest_digest(previous_manifest) == PREVIOUS_PRODUCER_SOURCE_MANIFEST_SHA256

    previous_profile = manifest()
    previous_profile["producer_profile"]["source_manifest_sha256"] = PREVIOUS_PRODUCER_SOURCE_MANIFEST_SHA256
    previous_profile["admission_dependencies"]["portable_producer_closure"]["source_manifest"] = previous_manifest
    previous_profile["admission_dependencies"]["portable_producer_closure"]["source_manifest_sha256"] = PREVIOUS_PRODUCER_SOURCE_MANIFEST_SHA256
    previous_profile["handler_sources"].update({
        "gameplay/profile.py": "ae43e6f402060a288cac759640ce296b94028e6c9feb57e9e3272c9a1e48f2b7",
        "gameplay/trusted_producer.py": "b30b45075819cff6c78635e60dbb32ea57ce2983d13c67c9fc1daadb2f8bed57",
    })
    previous_profile["digest"] = PREVIOUS_PROFILE_V9_IDENTITY["digest"]
    assert digest(previous_profile) == PREVIOUS_PROFILE_V9_MANIFEST_DIGEST
    validate_profile(previous_profile)
    assert profile_identity_is_compatible(PREVIOUS_PROFILE_V9_IDENTITY) is True

    tampered = deepcopy(previous_profile)
    tampered["handler_sources"]["gameplay/trusted_producer.py"] = "0" * 64
    with pytest.raises(EngineError) as failure:
        validate_profile(tampered)
    assert failure.value.code == "PROFILE_OR_HANDLER_MISMATCH"


def test_previous_creator_refresh_profile_survives_descriptive_lock_repair() -> None:
    previous_manifest = dict(PRODUCER_SOURCE_MANIFEST)
    previous_manifest["character_creation/creative_controller/linear_prompt.py"] = PREVIOUS_CREATOR_LINEAR_PROMPT_SOURCE_SHA256
    assert _manifest_digest(previous_manifest) == PREVIOUS_CREATOR_PRODUCER_SOURCE_MANIFEST_SHA256

    previous_profile = manifest()
    previous_profile["producer_profile"]["source_manifest_sha256"] = PREVIOUS_CREATOR_PRODUCER_SOURCE_MANIFEST_SHA256
    previous_profile["admission_dependencies"]["portable_producer_closure"]["source_manifest"] = previous_manifest
    previous_profile["admission_dependencies"]["portable_producer_closure"]["source_manifest_sha256"] = PREVIOUS_CREATOR_PRODUCER_SOURCE_MANIFEST_SHA256
    previous_profile["handler_sources"].update({
        "gameplay/profile.py": "13325fae8c4dc182c934b2cecb76975c073bbdd86a185084ae79e762fce92e02",
        "gameplay/trusted_producer.py": "df6aef8fc5d9dee03c823b4407684cfe3aeca097c605b87c594320475cda3996",
    })
    previous_profile["digest"] = PREVIOUS_CREATOR_PROFILE_V9_IDENTITY["digest"]
    assert digest(previous_profile) == PREVIOUS_CREATOR_PROFILE_V9_MANIFEST_DIGEST
    validate_profile(previous_profile)
    assert source_manifest_is_compatible(
        dict(PRODUCER_SOURCE_MANIFEST),
        _manifest_digest(PRODUCER_SOURCE_MANIFEST),
        previous_manifest,
        PREVIOUS_CREATOR_PRODUCER_SOURCE_MANIFEST_SHA256,
    ) is True
    assert profile_identity_is_compatible(PREVIOUS_CREATOR_PROFILE_V9_IDENTITY) is True

    tampered = deepcopy(previous_profile)
    tampered["handler_sources"]["gameplay/trusted_producer.py"] = "0" * 64
    with pytest.raises(EngineError) as failure:
        validate_profile(tampered)
    assert failure.value.code == "PROFILE_OR_HANDLER_MISMATCH"


def test_namespaced_route_uses_app_session_and_server_authority(
    tmp_path: Path, mortal_package: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIANXIA_OPENING_PACKAGE", str(mortal_package))
    monkeypatch.setenv("TIANXIA_OPENING_PRODUCER_ROOT", str(ROOT))
    settings = Settings.from_env(APP_ROOT, tmp_path / "factory-data")
    app = create_app(settings)

    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert "/opening" in client.get("/").text
        assert client.get("/opening").status_code == 200
        session = client.get("/api/opening/session")
        assert session.status_code == 200
        assert session.json()["configured"] is True
        token = client.get("/api/session").json()["token"]

        denied = client.post("/api/opening/launch", json={}, headers={"X-Foundry-Token": "wrong"})
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "CSRF_TOKEN_REQUIRED"

        launched = client.post("/api/opening/launch", json={}, headers={"X-Foundry-Token": token})
        assert launched.status_code == 200
        state = launched.json()["state"]
        assert state["actor"]["hp"] == 7
        assert "paths" not in state["actor"]
        profile = app.state.opening_runtime.service.controller.view()["gameplay"]["profile"]
        assert profile["producer_profile"]["id"] == "factory-current-creator-level0"
        assert profile["producer_profile"]["version"] == 1
        assert profile["producer_profile"]["source_manifest_sha256"]

        forged = client.post(
            "/api/opening/action",
            json={
                "action": "take_starter_item",
                "request_id": "opening-forged",
                "expected_revision": state["revision"],
                "actor_id": "other",
            },
            headers={"X-Foundry-Token": token},
        )
        assert forged.status_code == 400
        assert forged.json()["error"]["code"] == "INVALID_REQUEST_FIELDS"

        accepted = client.post(
            "/api/opening/action",
            json={
                "action": "take_starter_item",
                "request_id": "opening-route-take",
                "expected_revision": state["revision"],
            },
            headers={"X-Foundry-Token": token},
        )
        assert accepted.status_code == 200
        assert accepted.json()["state"]["inventory"][0]["instance_id"] == "starter-token"


def test_save_pointer_failure_keeps_canonical_state_retryable(tmp_path: Path, mortal_package: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    campaign = service(tmp_path, mortal_package)
    initial = campaign.launch()["state"]
    original_atomic = server_module._atomic_json
    failed = {"value": True}

    def fail_latest(path: Path, value: dict) -> None:
        if path == campaign.latest_path and failed["value"]:
            failed["value"] = False
            raise OSError("injected pointer write failure")
        original_atomic(path, value)

    monkeypatch.setattr(server_module, "_atomic_json", fail_latest)
    with pytest.raises(UiError) as failure:
        campaign.action({
            "action": "take_starter_item",
            "request_id": "opening-save-retry",
            "expected_revision": initial["revision"],
        })
    assert failure.value.code == "SAVE_FAILED"
    assert campaign.player_projection()["revision"] == initial["revision"]
    assert campaign.player_projection()["inventory"] == []
    assert len(list(campaign.revisions_root.glob("event-*"))) >= 2

    monkeypatch.setattr(server_module, "_atomic_json", original_atomic)
    retry = campaign.action({
        "action": "take_starter_item",
        "request_id": "opening-save-retry",
        "expected_revision": initial["revision"],
    })
    assert retry["duplicate"] is False
    assert retry["state"]["inventory"] == [{
        "instance_id": "starter-token", "label": "Woven gate token", "quantity": 1,
    }]
    reopened = service(tmp_path, mortal_package)
    assert reopened.player_projection() == retry["state"]


def test_request_log_failure_recovers_controller_receipt_after_reopen(
    tmp_path: Path, mortal_package: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = service(tmp_path, mortal_package)
    initial = campaign.launch()["state"]
    original_atomic = server_module._atomic_json
    failed = {"value": True}

    def fail_request_log(path: Path, value: dict) -> None:
        if path == campaign.requests_path and failed["value"]:
            failed["value"] = False
            raise OSError("injected request-log write failure")
        original_atomic(path, value)

    monkeypatch.setattr(server_module, "_atomic_json", fail_request_log)
    first = campaign.action({
        "action": "take_starter_item",
        "request_id": "opening-request-log-retry",
        "expected_revision": initial["revision"],
    })
    assert first["duplicate"] is False
    assert first["request_log_persisted"] is False

    monkeypatch.setattr(server_module, "_atomic_json", original_atomic)
    reopened = service(tmp_path, mortal_package)
    recovered = reopened.action({
        "action": "take_starter_item",
        "request_id": "opening-request-log-retry",
        "expected_revision": initial["revision"],
    })
    assert recovered["duplicate"] is True
    assert recovered["state"] == first["state"]
