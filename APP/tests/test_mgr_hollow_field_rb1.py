"""RB1 regressions for the Sol review of MGR-T14 Hollow Field (508cd6f1).

Finding 1: the Set-selection panel never sent the owned Void Sphere or the
permanent void_scar acquisition choice, so Void-Touched Cultivator was not
acquirable from the app. Finding 2: hostile Temporary HP was halved by rounding
up. Each test fails on the pre-fix code.
"""
import json
import re
from pathlib import Path

from non_sphere_authority.service import NonSphereAuthorityService  # noqa: F401
from tests.h1_support import ROOT
from tests.test_ns1r_non_sphere_authority import authority  # noqa: F401  (pytest fixture)

QI = "tianxia.path.qi_cultivation"
PARENT = "tianxia.subpath.qi.void_touched_cultivator"
VOID = "tianxia.sphere.void"


def test_subpath_catalog_exposes_the_printed_sphere_gate_and_void_scar(authority):
    service, _db = authority
    rows = {row["canonical_id"]: row for row in service.subpath_catalog(QI)["records"]}
    row = rows[PARENT]
    assert row["required_spheres"] == [VOID]
    fields = {field["choice_id"]: field for field in row["acquisition_fields"]}
    assert set(fields) == {"void_scar"}
    assert fields["void_scar"]["value_type"] == "text"
    assert fields["void_scar"]["maximum_length"] == 500
    # A Subpath with no printed Sphere or choice carries empty requirements.
    other = next(r for r in rows.values() if r["canonical_id"] != PARENT and not r["acquisition_fields"])
    assert other["required_spheres"] == []


def test_subpath_panel_sends_spheres_and_acquisition_choices_to_the_subpath_endpoint():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    start = js.index('setSubpath.onclick = () => {')
    block = js[start:js.index("subLabel.appendChild(subSelect);", start)]
    assert "/subpath`" in block
    body = re.search(r"\{path_id: path\.path_id, selection_id: subSelect\.value,[^}]*\}", block)
    assert body, block
    text = body.group(0)
    assert "spheres" in text and "acquisition_choices: acquisitionChoices" in text
    # The collected fields come from the catalog's printed requirements, not hard-coded ids.
    assert "choice.required_spheres" in js and "choice.acquisition_fields" in js
    assert "input.dataset.choiceId" in js


def test_panel_body_keys_are_accepted_by_the_request_model():
    from app.models import NS1RSubpathRequest
    body = {"path_id": QI, "selection_id": PARENT, "evidence_ids": [], "spheres": [VOID],
            "acquisition_choices": {"void_scar": "My reflection no longer appears."}}
    parsed = NS1RSubpathRequest(**body)
    assert parsed.spheres == [VOID]
    assert parsed.acquisition_choices == {"void_scar": "My reflection no longer appears."}
