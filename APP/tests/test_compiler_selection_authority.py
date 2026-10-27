from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from app.core import CORE_PACK_ID, CORE_PACK_VERSION, Database, FoundryError, Settings, sha256_json
from character_creation.compiler_selection_authority import (
    CompilerSelectionAuthoritySnapshot,
    NOT_COMPILER_BACKED_CODE,
    PINNED_ACTIVE_SOURCE_INDEX_SHA256,
    PINNED_COMPILER_SHA256,
    PINNED_CORPUS_SHA256,
    PINNED_CORE_PACK_HASH,
    PINNED_FACTORY_ROOT_TREE_SHA256,
    build_compiler_selection_authority,
    normalize_canonical_option_name,
    verify_compiler_selection_authority,
)
from character_creation.delegated_choice_authority import (
    build_delegated_choice_envelope,
    legal_slot_replacement_ids,
    validate_delegated_choice_plan,
)
from character_creation.service import CharacterCreationExecutionService
from character_creation import method_corpus_release
from factory_authoring.final_character_materializer import FINAL_CHARACTER_DEFAULT_STATE_ROOT
from non_sphere_authority import NonSphereAuthorityService
from path_method_authority import CANONICAL_PATH_IDS


APP_ROOT = Path(__file__).resolve().parents[1]
VENDOR = FINAL_CHARACTER_DEFAULT_STATE_ROOT / "vendor"


def _content_lock() -> dict:
    return {
        "catalog_build_id": "CG1-AUTHORITY-TEST",
        "lock_hash": "a" * 64,
        "packs": [{
            "pack_id": CORE_PACK_ID,
            "version": CORE_PACK_VERSION,
            "content_hash": PINNED_CORE_PACK_HASH,
        }],
    }


def _test_settings(data: Path) -> Settings:
    return Settings(
        root_dir=APP_ROOT,
        data_dir=data,
        db_path=data / "foundry.sqlite3",
        inbox_dir=data / "inbox",
        exports_dir=data / "exports",
        packs_dir=data / "packs",
        vendor_dir=VENDOR,
        logs_dir=data / "logs",
        backups_dir=data / "backups",
        security_dir=data / "security",
    )


@pytest.fixture(scope="module")
def pinned_authority() -> dict:
    with TemporaryDirectory(prefix="cg1-selection-authority-") as temporary:
        data = Path(temporary)
        settings = Settings(
            root_dir=APP_ROOT,
            data_dir=data,
            db_path=data / "foundry.sqlite3",
            inbox_dir=data / "inbox",
            exports_dir=data / "exports",
            packs_dir=data / "packs",
            vendor_dir=VENDOR,
            logs_dir=data / "logs",
            backups_dir=data / "backups",
            security_dir=data / "security",
        )
        db = Database(settings)
        non_sphere = NonSphereAuthorityService(db)
        yield build_compiler_selection_authority(
            VENDOR,
            include_complete_foundations=False,
            content_lock=_content_lock(),
            method_records=non_sphere.method_catalog(initial_creation=True)["records"],
            foundation_records=non_sphere.foundation_catalog()["orthodox"],
        )


def _choice(choice_id: str, name: str, **fields: object) -> dict:
    return {
        "choice_id": choice_id,
        "name": name,
        "initial_creation_selectable": True,
        "availability": {"available": True},
        **fields,
    }


def _production_prompt(non_sphere: NonSphereAuthorityService) -> dict:
    methods = non_sphere.method_catalog(initial_creation=True)["records"]
    foundations = non_sphere.foundation_catalog()["orthodox"]
    return {
        "prompt_id": "CG1-AUTHORITY-PROMPT",
        "prompt_sha256": "c" * 64,
        "envelope": {
            "schema_version": "TianxiaFoundry.Stage1Prompt.v1",
            "response_schema_version": "TianxiaFoundry.Stage1Response.v1",
            "decision_slots": [
                {
                    "slot_id": "path_choice",
                    "min_selections": 1,
                    "max_selections": 3,
                    "allow_none": False,
                    "choices": [_choice(path_id, path_id) for path_id in CANONICAL_PATH_IDS],
                },
                {
                    "slot_id": "method_choice",
                    "min_selections": 0,
                    "max_selections": 1,
                    "allow_none": True,
                    "choices": [
                        _choice(row["method_id"], row["name"], initial_creation_selectable=row["initial_creation_selectable"])
                        for row in methods
                    ],
                },
                {
                    "slot_id": "foundation_choice",
                    "min_selections": 0,
                    "max_selections": 1,
                    "allow_none": True,
                    "choices": [_choice(row["foundation_id"], row["display_name"]) for row in foundations],
                },
            ],
            "path_method_authority": {
                "all_path_ids": list(CANONICAL_PATH_IDS),
                "method_granted_path_ids": {},
                "method_access_by_id": {},
            },
        },
    }


def _project() -> dict:
    return {
        "project_id": "CG1-SELECTION-PROJECT",
        "revision": 3,
        "working_name": "Compiler Gate Fixture",
        "user_locks": [{"field": "target_cl", "value": 1, "source": "test"}],
        "content_lock": _content_lock(),
        "event_stream": {"count": 0, "head_hash": None},
    }


def test_real_pinned_index_is_compiler_backed_and_excludes_known_unbacked_choices(pinned_authority: dict) -> None:
    assert isinstance(pinned_authority, CompilerSelectionAuthoritySnapshot)
    assert pinned_authority["factory"]["compiler_sha256"] == PINNED_COMPILER_SHA256
    assert pinned_authority["factory"]["corpus_sha256"] == PINNED_CORPUS_SHA256
    assert pinned_authority["factory"]["factory_root_tree_sha256"] == PINNED_FACTORY_ROOT_TREE_SHA256
    assert pinned_authority["source_authority"]["active_source_index_sha256"] == method_corpus_release.ACTIVE_SOURCE_INDEX_SHA256

    methods = pinned_authority["method_choice"]
    foundations = pinned_authority["foundation_choice"]
    assert "METHOD-002" in methods["compiler_backed_ids"]
    assert "heavenly_body_v0_2F" in foundations["compiler_backed_ids"]
    method = methods["records"]["METHOD-002"]
    assert method["source_path"] == "Needed/Tianxia_Methods_Master_v0_1.md"
    assert method["normalized_canonical_name"] in normalize_canonical_option_name(method["source_text"])
    assert method["source_excerpt_sha256"] == sha256(method["source_text"].encode("utf-8")).hexdigest()
    foundation = foundations["records"]["heavenly_body_v0_2F"]
    assert foundation["source_path"] in {
        row["source_path"] for row in pinned_authority["source_authority"]["active_source_index"]
    }
    assert foundation["classification"] == "tianxia_rules"
    assert "METHOD-081" in methods["compiler_backed_ids"]
    assert "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR" not in foundations["compiler_backed_ids"]
    assert methods["records"]["METHOD-081"]["source_path"] == method_corpus_release.SOURCE_MEMBER
    assert foundations["records"]["FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR"]["reason_code"] == NOT_COMPILER_BACKED_CODE


def test_forged_source_path_or_file_hash_cannot_pass_sealed_index(pinned_authority: dict) -> None:
    for field, value in (("source_path", "../../outside.md"), ("source_file_sha256", "0" * 64)):
        forged = deepcopy(pinned_authority)
        forged["method_choice"]["records"]["METHOD-001"][field] = value
        forged["authority_sha256"] = sha256_json({key: item for key, item in forged.items() if key != "authority_sha256"})
        with pytest.raises(FoundryError) as caught:
            verify_compiler_selection_authority(forged)
        assert caught.value.code == "CG1_DELEGATED_COMPILER_AUTHORITY_PROJECTION_MISMATCH"


def test_recomputed_projection_cannot_admit_forged_or_remapped_records(pinned_authority: dict) -> None:
    cases: list[dict] = []

    added = deepcopy(pinned_authority)
    forged = deepcopy(added["method_choice"]["records"]["METHOD-001"])
    forged["choice_id"] = "FORGED-METHOD"
    added["method_choice"]["records"]["FORGED-METHOD"] = forged
    added["method_choice"]["compiler_backed_ids"].append("FORGED-METHOD")
    cases.append(added)

    remapped = deepcopy(pinned_authority)
    original = remapped["method_choice"]["records"]["METHOD-001"]
    source = remapped["method_choice"]["records"]["METHOD-002"]
    for key in ("canonical_name", "normalized_canonical_name", "source_path", "source_file_sha256", "source_text", "source_excerpt_sha256"):
        original[key] = source[key]
    cases.append(remapped)

    arbitrary_excerpt = deepcopy(pinned_authority)
    row = arbitrary_excerpt["method_choice"]["records"]["METHOD-002"]
    row["source_text"] = "## 999. Ash-Breath Furnace Method\n"
    row["source_excerpt_sha256"] = sha256(row["source_text"].encode("utf-8")).hexdigest()
    cases.append(arbitrary_excerpt)

    for forged_payload in cases:
        forged_payload["authority_sha256"] = sha256_json({
            key: item for key, item in forged_payload.items() if key != "authority_sha256"
        })
        with pytest.raises(FoundryError) as caught:
            verify_compiler_selection_authority(forged_payload)
        assert caught.value.code == "CG1_DELEGATED_COMPILER_AUTHORITY_PROJECTION_MISMATCH"


def test_recomputed_authority_cannot_change_core_pack_identity(pinned_authority: dict) -> None:
    forged = deepcopy(pinned_authority)
    forged["content"].update({
        "core_pack_id": "FORGED-CORE-PACK",
        "core_pack_version": "0.0.0",
        "core_pack_hash": "f" * 64,
    })
    forged["authority_sha256"] = sha256_json({key: item for key, item in forged.items() if key != "authority_sha256"})
    with pytest.raises(FoundryError) as caught:
        verify_compiler_selection_authority(forged)
    assert caught.value.code == "CG1_DELEGATED_COMPILER_AUTHORITY_CONTENT_MISMATCH"


def test_forged_name_is_rejected_when_building_production_envelope(pinned_authority: dict) -> None:
    with TemporaryDirectory(prefix="cg1-prompt-authority-") as temporary:
        data = Path(temporary)
        settings = _test_settings(data)
        non_sphere = NonSphereAuthorityService(Database(settings))
        prompt = _production_prompt(non_sphere)
        method_rows = next(row for row in prompt["envelope"]["decision_slots"] if row["slot_id"] == "method_choice")["choices"]
        next(row for row in method_rows if row["choice_id"] == "METHOD-001")["name"] = "Forged Method"
        with pytest.raises(FoundryError) as caught:
            build_delegated_choice_envelope(
                _project(),
                prompt,
                execution_mode="MANUAL_CHAT",
                idempotency_key="one-shot",
                compiler_selection_authority=pinned_authority,
            )
        assert caught.value.code == "CG1_DELEGATED_COMPILER_AUTHORITY_MISMATCH"


def test_production_prompt_rejects_plain_caller_supplied_authority(pinned_authority: dict) -> None:
    with TemporaryDirectory(prefix="cg1-prompt-authority-") as temporary:
        non_sphere = NonSphereAuthorityService(Database(_test_settings(Path(temporary))))
        with pytest.raises(FoundryError) as caught:
            build_delegated_choice_envelope(
                _project(),
                _production_prompt(non_sphere),
                execution_mode="MANUAL_CHAT",
                idempotency_key="one-shot",
                compiler_selection_authority=deepcopy(dict(pinned_authority)),
            )
        assert caught.value.code == "CG1_DELEGATED_COMPILER_AUTHORITY_MISSING"


def test_project_content_lock_drift_rejects_frozen_authority(pinned_authority: dict) -> None:
    with TemporaryDirectory(prefix="cg1-prompt-authority-") as temporary:
        non_sphere = NonSphereAuthorityService(Database(_test_settings(Path(temporary))))
        drifted = _project()
        drifted["content_lock"] = deepcopy(drifted["content_lock"])
        drifted["content_lock"]["lock_hash"] = "d" * 64
        with pytest.raises(FoundryError) as caught:
            build_delegated_choice_envelope(
                drifted,
                _production_prompt(non_sphere),
                execution_mode="MANUAL_CHAT",
                idempotency_key="one-shot",
                compiler_selection_authority=pinned_authority,
            )
        assert caught.value.code == "CG1_DELEGATED_COMPILER_AUTHORITY_CONTENT_STALE"


def test_compiler_gate_binds_to_active_request_stage1_prompt_and_request_fields(pinned_authority: dict) -> None:
    with TemporaryDirectory(prefix="cg1-request-binding-") as temporary:
        non_sphere = NonSphereAuthorityService(Database(_test_settings(Path(temporary))))
        project = _project()
        prompt = _production_prompt(non_sphere)
        envelope = build_delegated_choice_envelope(
            project,
            prompt,
            execution_mode="MANUAL_CHAT",
            idempotency_key="one-shot",
            compiler_selection_authority=pinned_authority,
        )
        assert envelope is not None

        def run_for(request: dict) -> dict:
            return {
                "project_id": project["project_id"],
                "starting_revision": project["revision"],
                "execution_mode": "MANUAL_CHAT",
                "idempotency_key": "one-shot",
                "request": request,
            }

        base_request = {
            "project_id": project["project_id"],
            "project_revision": project["revision"],
            "content_lock_hash": project["content_lock"]["lock_hash"],
            "stage1_prompt": deepcopy(prompt),
            "delegated_choice_envelope": envelope,
        }
        stale_prompt_request = deepcopy(base_request)
        stale_prompt_request["stage1_prompt"]["prompt_id"] = "STALE-PROMPT"
        with pytest.raises(FoundryError) as caught:
            validate_delegated_choice_plan(
                run_for(stale_prompt_request),
                project,
                {"canonical_selection_intent": {}},
            )
        assert caught.value.code == "CG1_DELEGATED_STAGE1_PROMPT_BINDING_MISMATCH"

        stale_envelope_request = deepcopy(base_request)
        stale_envelope = stale_envelope_request["delegated_choice_envelope"]
        stale_envelope["binding"]["stage1_prompt_sha256"] = "STALE-HASH"
        stale_envelope["envelope_sha256"] = sha256_json({
            key: value for key, value in stale_envelope.items() if key != "envelope_sha256"
        })
        with pytest.raises(FoundryError) as caught:
            validate_delegated_choice_plan(
                run_for(stale_envelope_request),
                project,
                {"canonical_selection_intent": {}},
            )
        assert caught.value.code == "CG1_DELEGATED_STAGE1_PROMPT_BINDING_MISMATCH"


def test_production_service_freezes_compiler_gate_and_never_calls_provider() -> None:
    with TemporaryDirectory(prefix="cg1-service-authority-") as temporary:
        data = Path(temporary)
        settings = _test_settings(data)
        db = Database(settings)
        # The request reads project_locked_records under the lock proof.
        db.migrate()
        non_sphere = NonSphereAuthorityService(db)
        project = _project()
        prompt = _production_prompt(non_sphere)

        class Stage1:
            def generate_prompt(self, project_id: str) -> dict:
                assert project_id == project["project_id"]
                return deepcopy(prompt)

        class Store:
            def get_project(self, project_id: str) -> dict:
                assert project_id == project["project_id"]
                return {"project": deepcopy(project)}

            def add_server_locked_records(self, project_id: str, records: list[dict]) -> None:
                assert project_id == project["project_id"]
                assert records

            def project_lock_proof(self, _conn, project_id: str) -> None:
                # The request freezes offered Methods under the project lock
                # proof (80fee3e0); this in-memory project has no locked rows.
                assert project_id == project["project_id"]

        service = CharacterCreationExecutionService(
            db,
            stage1=Stage1(),
            provider=None,
            project_store=Store(),
        )
        before = {
            path: sha256(path.read_bytes()).hexdigest()
            for path in (
                VENDOR / "factory_adapter.json",
                VENDOR / "extracted" / "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385" / "HF05ZVK_R1H_Phase2I_HF2" / "05_COMPILER" / "compile_character.py",
                VENDOR / "extracted" / "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385" / "HF05ZVK_R1H_Phase2I_HF2" / "09_RULES" / "Tianxia_Canonical_Rules_Corpus_P2A.zip",
            )
        }
        class ForbiddenProvider:
            # The controller route binding reads this static identity seam
            # without invoking provider transport; ``None`` records the
            # identity as unavailable. Every other attribute is forbidden.
            selected_ai_identity = None

            def __getattr__(self, name: str) -> object:
                raise AssertionError(f"provider surface accessed: {name}")

        service.provider = ForbiddenProvider()
        request = service._complete_request(project["project_id"], idempotency_key="one-shot")
        envelope = request["delegated_choice_envelope"]
        assert envelope["binding"]["target_cl"] == 1
        assert envelope["binding"]["compiler_selection_authority_sha256"] == envelope["compiler_selection_authority"]["authority_sha256"]
        assert "METHOD-081" in envelope["allowed_choice_ids_by_slot"]["method_choice"]
        assert "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR" in envelope["allowed_choice_ids_by_slot"]["foundation_choice"]
        assert envelope["compiler_selection_authority"]["schema"] == "TianxiaFoundry.CompilerSelectionAuthority.v3"
        assert "heavenly_body_v0_2F" in envelope["allowed_choice_ids_by_slot"]["foundation_choice"]
        assert envelope["compiler_selection_authority"]["provider_policy"]["response_prose_grants_no_authority"] is True
        assert "exact pinned compiler corpus" in request["server_owned_authority"]["method_foundation_choices"]
        provider_prompt = CharacterCreationExecutionService._provider_prompt({"request": request})
        assert "Method and Foundation IDs are a closed world backed by the exact pinned compiler corpus" in provider_prompt
        assert "Nonselectable IDs and response prose cannot grant mechanics or authority" in provider_prompt
        after = {path: sha256(path.read_bytes()).hexdigest() for path in before}
        assert after == before


def test_legal_replacements_are_limited_to_compiler_backed_ids(pinned_authority: dict) -> None:
    with TemporaryDirectory(prefix="cg1-prompt-authority-") as temporary:
        data = Path(temporary)
        settings = _test_settings(data)
        non_sphere = NonSphereAuthorityService(Database(settings))
        envelope = build_delegated_choice_envelope(
            _project(),
            _production_prompt(non_sphere),
            execution_mode="MANUAL_CHAT",
            idempotency_key="one-shot",
            compiler_selection_authority=pinned_authority,
        )
        plan = {"target_cl": 1}
        selected = {"path_choice": [CANONICAL_PATH_IDS[0]], "method_choice": ["METHOD-001"]}
        replacements = legal_slot_replacement_ids(envelope, plan, selected, "method_choice")
        assert replacements
        assert set(replacements) <= set(pinned_authority["method_choice"]["compiler_backed_ids"])
        assert "METHOD-081" in replacements
        assert "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR" not in envelope["allowed_choice_ids_by_slot"]["foundation_choice"]


def test_exact_method_plan_that_cannot_be_selected_fails_closed_before_any_provider_call(pinned_authority: dict) -> None:
    # Corpus release makes METHOD-081 compiler-backed. An explicitly unavailable
    # route must still fail closed before a provider call, even with that backing.
    with TemporaryDirectory(prefix="cg1-exact-method-") as temporary:
        non_sphere = NonSphereAuthorityService(Database(_test_settings(Path(temporary))))
        prompt = _production_prompt(non_sphere)
        method_slot = next(row for row in prompt["envelope"]["decision_slots"] if row["slot_id"] == "method_choice")
        next(row for row in method_slot["choices"] if row["choice_id"] == "METHOD-081")["availability"] = {"available": False}
        project = _project()
        project["user_locks"] = [
            *project["user_locks"],
            {"field": "character_sheet.method_planning_mode", "value": "EXACT", "source": "test"},
            {"field": "character_sheet.planning_preferences", "value": {"method_exact_choice_id": "METHOD-081"}, "source": "test"},
        ]
        with pytest.raises(FoundryError) as caught:
            build_delegated_choice_envelope(
                project,
                prompt,
                execution_mode="MANUAL_CHAT",
                idempotency_key="one-shot",
                compiler_selection_authority=pinned_authority,
            )
        assert caught.value.code == "CG1_METHOD_EXACT_PLAN_UNAVAILABLE"
        assert caught.value.details["method_id"] == "METHOD-081"
        assert caught.value.details["reasons"]
        assert "METHOD-081" not in caught.value.details["allowed_method_ids"]
