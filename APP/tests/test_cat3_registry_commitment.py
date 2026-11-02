"""The shipped CAT3 catalog carries its own seals.

``canonical_catalog/service.py`` refuses to load the catalog unless the registry commitment matches the whole
document and every compiled record's commitment matches that record. A regenerated authority that ships without
re-sealing it (or an export that rewrites prose without re-sealing) makes every catalog-backed test fail with
"app.core.FoundryError: The compiled CAT3 registry commitment does not verify." (metal_qi awakening tests,
int-20261020x-t1.log).

This recomputes the seals the same documented way the service does -- sha256 of the canonical JSON without the
commitment field -- over the file that ships, so a stale seal fails here first and names the record.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "catalog_authority/cat3/generated/catalog_authority.v1.json"

# The groups canonical_catalog/service.py:_load() verifies one row at a time.
COMMITTED_GROUPS = (
    "spheres", "talents", "sphere_aliases_and_noncanonical_labels", "automatic_base_abilities",
    "automatic_base_ability_aliases", "sphere_base_ability_authority", "insights", "background_only_routes",
    "quarantined_decision_packets", "legacy_non_talent_findings",
)


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _commitment(value, field="record_commitment_sha256"):
    return hashlib.sha256(_canonical({key: item for key, item in value.items() if key != field})).hexdigest()


def _record_id(row):
    return (row.get("canonical_talent_id") or row.get("canonical_sphere_id") or row.get("candidate_record_id")
            or row.get("record_id") or row.get("legacy_id"))


def test_the_shipped_cat3_registry_verifies_its_registry_and_record_commitments():
    document = json.loads(AUTHORITY.read_text(encoding="utf-8"))
    assert document["registry_commitment_sha256"] == _commitment(document, "registry_commitment_sha256")
    stale = []
    for group in COMMITTED_GROUPS:
        for row in document.get(group) or []:
            if row.get("record_commitment_sha256") != _commitment(row):
                stale.append(_record_id(row))
    assert stale == [], stale
