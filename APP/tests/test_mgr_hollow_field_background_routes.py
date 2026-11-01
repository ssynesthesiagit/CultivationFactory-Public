"""NS1R acquisition must not require source prose to resolve a named route."""
from types import SimpleNamespace

import pytest

from app.core import FoundryError
from canonical_catalog import service as catalog
from non_sphere_authority.service import NonSphereAuthorityService


@pytest.mark.parametrize("bullet, duplicate, accepted", [
    ("Lantern Ward", False, True),
    ("Lumen Sphere. You gain the Lantern Ward talent.", False, True),
    ("Lantern", False, False),
    ("Other Sphere. You gain the Lantern Ward talent.", False, False),
    ("Lantern Ward", True, False),
])
def test_background_route_without_source_prose_requires_an_exact_unique_identity(
        tmp_path, monkeypatch, bullet, duplicate, accepted):
    # Only CAT3's separate Sphere lookup is a fake; exercise the real NS1R
    # route resolver on synthetic accepted rows, including fail-closed cases.
    sphere = "tianxia.sphere.lumen"
    monkeypatch.setattr(catalog, "CanonicalCatalogAuthorityService",
                        lambda root: SimpleNamespace(resolve_sphere_id=lambda value: sphere if value == sphere else None))
    route = {
        "background_route_record_id": "test.background_talent.lantern_ward",
        "display_name": "Lantern Ward (Lumen)",
        "canonical_sphere_id": sphere,
        "canonical_sphere_name": "Lumen",
        "record_commitment_sha256": "a" * 64,
        "source_text": "[text redacted: synthetic]",
    }
    routes = [route]
    if duplicate:
        routes.append({**route, "background_route_record_id": "test.background_talent.other.lantern_ward",
                       "display_name": "Lantern Ward (Other)", "canonical_sphere_name": "Other"})
    background = {
        "background_sphere_talent_routes": {"route_bullets": [bullet]},
        "origin_insight": {"suggested_options": []},
        "ability_score_grants": {"modes": []},
    }
    service = SimpleNamespace(root=tmp_path, cat2_background_routes=routes,
                              backgrounds={"test.background": background})
    if not accepted:
        with pytest.raises(FoundryError) as error:
            NonSphereAuthorityService._build_background_route_authority(service)
        assert error.value.code == "NS1R_BACKGROUND_ROUTE_AUTHORITY_AMBIGUOUS"
        assert error.value.details["matches"] == (2 if duplicate else 0)
        return

    result = NonSphereAuthorityService._build_background_route_authority(service)
    options = result["test.background"]["route_options"]
    assert len(options) == 1
    assert options[0]["background_route_record_id"] == route["background_route_record_id"]
    assert options[0]["background_talent_choice_id"] == route["background_route_record_id"]
    assert options[0]["canonical_sphere_id"] == sphere
    assert options[0]["record_commitment_sha256"] == route["record_commitment_sha256"]
