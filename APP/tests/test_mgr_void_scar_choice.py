"""The Void Scar is free text: every path that carries it must carry the owner's words.

The Void-Touched Cultivator records a permanent Void Scar when the Secret Law
is acquired. That choice is free text, so the Subpath catalog must publish it,
the sealed builder lock must transport it, the compiled Void Step must carry it
and a reloaded fight must still show it.

This file uses only the repository's own authority data and a synthetic owner
sheet: no owner data, no live service, no private fixture.
"""
from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings
from non_sphere_authority import NonSphereAuthorityService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, fixture, reload

QI = "tianxia.path.qi_cultivation"
PARENT = "tianxia.subpath.qi.void_touched_cultivator"
STEP = PARENT + ".feature.void_step"
SCAR = "My reflection no longer appears."
VOID_SPHERE = "tianxia.sphere.void"


def test_the_subpath_catalog_publishes_what_the_owner_must_supply(tmp_path):
    """The bounded panel can only ask for the Scar and the Void Sphere if the
    catalog publishes them; without these fields it has nothing to render."""
    settings = Settings.from_env(ROOT, tmp_path / "data")
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    catalog = service.subpath_catalog(QI)
    row = next(item for item in catalog["records"] if item["canonical_id"] == PARENT)
    assert row["required_spheres"] == [VOID_SPHERE]
    assert row["acquisition_choices"]["void_scar"]["value_type"] == "text"
    assert row["acquisition_choices"]["void_scar"]["maximum_length"] == 500
    other = next(item for item in catalog["records"] if item["canonical_id"] != PARENT)
    assert other["required_spheres"] == []


def test_the_owner_text_scar_survives_the_builder_lock_and_a_cold_reload(tmp_path):
    """The Void Scar is free text: the sealed builder lock, the compiled Void
    Step and a reloaded fight must all carry the owner's own words."""
    from character_creation.acquisition_choices import (FIELD, for_acquisition, from_sheet,
                                                        recorded, validate)
    from character_creation.choice_snapshot import materialize_choice_snapshot
    from combat.factory_compiler import compile_character

    assert validate([PARENT], {"void_scar": SCAR}) == {"void_scar": SCAR}
    with pytest.raises(FoundryError) as error:
        validate([PARENT], {"void_scar": "   "})
    assert error.value.code == "ACQUISITION_CHOICE_INVALID"

    project = {"project_id": "void-scar-builder", "revision": 1,
               "user_locks": [{"field": FIELD, "value": {"void_scar": SCAR}}]}
    assert for_acquisition(project, PARENT) == {"void_scar": SCAR}
    snapshot = materialize_choice_snapshot(project)
    doc = sheet([], cl=3, name="Void cultivator")
    doc["path_and_subpath"] = {"path_feature_record_ids": [STEP]}
    doc["advancement_history"] = {"typed_choice_snapshot": snapshot}
    assert from_sheet(doc) == {"void_scar": SCAR}
    assert recorded(doc, PARENT) == {"void_scar": SCAR}

    compiled = compile_character(doc, actor_id=OWNER)
    void_rows = [row for row in compiled["action_catalog"]
                 if ((row.get("parameters") or {}).get("typed") or {}).get("source") == STEP]
    assert void_rows, "the sealed builder lock compiled no Void Step"
    for row in void_rows:
        assert row["parameters"]["typed"]["void_scar"] == SCAR

    combat, table, mid = fixture(tmp_path, [], cl=3, owner_bundle=compiled, named=True,
                                 seed="VOID-SCAR-BUILDER")
    engine = reload(tmp_path, mid)
    action = next(row for row in engine.action_catalog.values()
                  if ((row.parameters or {}).get("typed") or {}).get("source") == STEP)
    assert action.parameters["typed"]["void_scar"] == SCAR
