"""Shared NS1R native-acquisition builder for the Void-Touched Cultivator test files.

Builds a real acquisition (NS1R evidence, subpath selection with its permanent
Void Scar, and a full Qi resource pool) through NonSphereAuthorityService.
"""
from pathlib import Path

from app.core import Database, Settings
from non_sphere_authority import NonSphereAuthorityService
from tests.h1_support import ROOT
from tests.ns1r_evidence_helpers import ap_award, commit_authority_event, install_authority_test_pack
from tests.test_ns1r_non_sphere_authority import insert_project

QI = "tianxia.path.qi_cultivation"
PARENT = "tianxia.subpath.qi.void_touched_cultivator"
SCAR = "My reflection no longer appears."
VOID = "tianxia.sphere.void"


def build_native_acquisition(root: Path, cl: int, prefix: str, *, sphere: str = VOID):
    """Return (service, project) for a Void-Touched Cultivator acquired at `cl`."""
    settings = Settings.from_env(ROOT, root / "data")
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    project = f"{prefix}-native-{cl}"
    insert_project(db, project, cl)
    service.initialize_for_project(project, target_cl=cl, path_ids=[QI], method_id="METHOD-001")
    service.allocate_advancement(project, {QI: cl - 1},
                                 evidence_id=ap_award(db, service, project, "METHOD-001", cl, cl - 1),
                                 idempotency_key=project + "-advance")
    access = commit_authority_event(db, service, project, "subpath_access",
                                    {"selection_id": PARENT, "path_id": QI})
    service.select_subpath(project, QI, PARENT, [access],
                           acquisition_choices={"void_scar": SCAR}, spheres=[sphere])
    service.set_resource(project, QI, current=30, maximum=30)
    return service, project
