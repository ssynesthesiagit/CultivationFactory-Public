"""Legacy Aspect labels still resolve after CAT1 display strings are renamed."""
import json

from catalog_authority.sphere_identity import resolve_sphere_id
from tools.aspect_terms import TERMS, aspect_terms


def test_old_labels_resolve_against_renamed_registry(tmp_path):
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "catalog_authority/cat1/data"
    target = tmp_path / "catalog_authority/cat1/data"
    target.mkdir(parents=True)
    registry = json.loads((source / "canonical_spheres.v1.json").read_text(encoding="utf-8"))
    labels = json.loads((source / "sphere_aliases_and_labels.v1.json").read_text(encoding="utf-8"))
    originals = [(old, full, resolve_sphere_id(full))
                 for old, full in TERMS["names"].items()]
    assert {sphere_id for _, _, sphere_id in originals} == {
        row["canonical_sphere_id"] for row in registry["records"]
    }

    def rename(value):
        return TERMS["short_lists"].get(value, aspect_terms(value))

    for row in registry["records"]:
        row["display_name"] = rename(row["display_name"])
        row["aliases"] = [rename(alias) for alias in row["aliases"]]
    for row in labels["records"]:
        row["label"] = rename(row["label"])
    (target / "canonical_spheres.v1.json").write_text(json.dumps(registry), encoding="utf-8")
    (target / "sphere_aliases_and_labels.v1.json").write_text(json.dumps(labels), encoding="utf-8")

    for old, full, sphere_id in originals:
        short = TERMS["short_lists"].get(old, old)
        for label in (f"Sphere of {old}", old, full, short):
            assert resolve_sphere_id(label, root=tmp_path) == sphere_id, label
