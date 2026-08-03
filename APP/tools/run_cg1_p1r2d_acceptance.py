from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core import Database, Settings, canonical_json, sha256_file
from catalog.service import CatalogService
from character_builder import CharacterBuilderService
from character_creation import CharacterCreationExecutionService
from character_creation.current_fixture import complete_plan, create_fresh_project
from character_creation.production_release import CharacterProductionReleaseAdapter
from character_sheet import CharacterSheetService
from factory_authoring import FactoryAuthoringWorkspaceService
from gm_export import GMCharacterExportService
from portable_character import PortableCharacterPackageService
from project_store.service import ProjectStore
from projector.service import ProjectionService
from security.local_identity import BoundPrincipalProvider, ProcessPrincipalProvider
from stage1.service import Stage1ClipboardService
from stage2 import Stage2AdvancementService
from tests.r4v_harness import provision_external_test_key
from vendor_adapter.service import FactoryAdapter


class NoTransmissionProvider:
    def status(self) -> dict:
        return {"ready": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = ROOT
    factory_zip = root / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cg1-p1r2d-current-", ignore_cleanup_errors=True) as td:
        data = Path(td) / "data"
        settings = Settings.from_env(root, data)
        provision_external_test_key(data)
        db = Database(settings)
        db.migrate()
        factory = FactoryAdapter(db)
        configured = factory.configure(factory_zip)
        catalog = CatalogService(db).rebuild_core(Path(configured["factory_root"]))
        principal = ProcessPrincipalProvider().current_principal()
        bound = BoundPrincipalProvider(principal)
        created = create_fresh_project(db)
        project_id = created["project_id"]
        plan = complete_plan(db, project_id)
        release = CharacterProductionReleaseAdapter(db)
        stage1 = Stage1ClipboardService(db)
        stage2 = Stage2AdvancementService(db, principal_provider=bound)
        service = CharacterCreationExecutionService(
            db,
            stage1=stage1,
            provider=NoTransmissionProvider(),
            project_store=ProjectStore(db),
            stage2=stage2,
            character_sheets=CharacterSheetService(db),
            gm_exports=GMCharacterExportService(db),
            portable_characters=PortableCharacterPackageService(db),
            factory_authoring=FactoryAuthoringWorkspaceService(db),
            projections=ProjectionService(db),
            production_release=release,
            owner_principal=principal.principal_id,
        )
        run = service.start(project_id, execution_mode="MANUAL_CHAT", idempotency_key="cg1.p1r2d.manual.production")
        request_name, request_zip = service.complete_request_zip(run["run_id"])
        plan["request_sha256"] = run["request"]["request_sha256"]
        plan_text = canonical_json(plan)
        run = service.submit_manual(
            run["run_id"],
            response_text=plan_text,
            request_sha256=run["request"]["request_sha256"],
        )
        if run["status"] != "READY_FOR_REVIEW":
            raise RuntimeError(canonical_json({"status": run["status"], "blockers": run["blockers"], "warnings": run["warnings"]}))
        run = service.finalize(run["run_id"])
        report = {
            "schema": "Tianxia.CG1P1R2DProductionAcceptance.v1",
            "status": "CG1_CHARACTER_CREATION_EXECUTION_MODES_READY",
            "scope": "BOUNDED_FIRE_QI_PRODUCTION_SLICE",
            "project_id": project_id,
            "fresh_character_builder_project": True,
            "factory_sha256": sha256_file(factory_zip),
            "catalog_build_id": catalog.get("catalog_build_id"),
            "owner_principal_hash": service.owner_principal_hash,
            "complete_request_zip": {"filename": request_name, "bytes": len(request_zip)},
            "scratch_builds": run["dry_run"]["independent_compilations"],
            "candidate_identity": run["dry_run"]["candidate_identity"],
            "final_status": run["status"],
            "commit": run["commit"],
            "outputs": run["outputs"],
            "combat_readiness": "NOT_REQUESTED_OR_NOT_SUPPORTED_FOR_THIS_NEW_IDENTITY",
        }
        args.output.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
