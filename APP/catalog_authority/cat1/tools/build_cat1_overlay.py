from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"


def canonical_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(obj))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def registry_schema(schema_id: str, required_record_fields: list[str]) -> dict[str, Any]:
    return {
        "$schema": SCHEMA_URI,
        "$id": schema_id,
        "type": "object",
        "required": ["schema", "records", "registry_commitment_sha256"],
        "properties": {
            "schema": {"type": "string"},
            "records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": required_record_fields + ["record_commitment_sha256"],
                    "properties": {"record_commitment_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
                    "additionalProperties": True,
                },
            },
            "registry_commitment_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
        "additionalProperties": True,
    }


def install_schemas(catroot: Path) -> None:
    sdir = catroot / "schemas"
    schemas = {
        "canonical_sphere_registry.schema.json": registry_schema("urn:tianxia:cat1:canonical-sphere-registry:v1", ["canonical_sphere_id", "display_name", "source_provenance"]),
        "sphere_alias_registry.schema.json": registry_schema("urn:tianxia:cat1:sphere-alias-registry:v1", ["label", "label_classification", "canonical_sphere_id", "source_provenance"]),
        "canonical_talent_registry.schema.json": registry_schema("urn:tianxia:cat1:canonical-talent-registry:v1", ["canonical_talent_id", "display_name", "owning_canonical_sphere_id", "selection_disposition", "source_provenance"]),
        "mixed_candidate_classification.schema.json": registry_schema("urn:tianxia:cat1:mixed-candidate-classification:v1", ["candidate_record_id", "cat1_classification", "owner_selectable_output", "source_provenance"]),
        "selection_disposition.schema.json": registry_schema("urn:tianxia:cat1:selection-disposition:v1", ["record_id", "selection_disposition", "source_evidence"]),
        "prerequisite_projection.schema.json": registry_schema("urn:tianxia:cat1:prerequisite-projection:v1", ["record_id", "prerequisite_evaluation_status", "creator_selectability_can_be_evaluated_safely", "source_provenance"]),
        "owner_readable_projection.schema.json": registry_schema("urn:tianxia:cat1:owner-readable-projection:v1", ["record_id", "record_type", "display_name", "description_status", "source_provenance"]),
        "unresolved_authority_decisions.schema.json": registry_schema("urn:tianxia:cat1:unresolved-authority-decisions:v1", ["decision_packet_id", "topic"]),
    }
    schemas["overlay_manifest.schema.json"] = {
        "$schema": SCHEMA_URI,
        "$id": "urn:tianxia:cat1:overlay-manifest:v1",
        "type": "object",
        "required": ["schema", "checkpoint", "result", "output_mode", "counts", "files", "runtime_integration", "ui_integration", "source_modification"],
        "properties": {
            "schema": {"const": "TianxiaCAT1.OverlayManifest.v1"},
            "checkpoint": {"const": "CAT1"},
            "result": {"enum": ["CAT1_CANONICAL_AUTHORITY_OVERLAY_READY", "CAT1_BLOCKED_MATERIAL_AUTHORITY_DECISION"]},
            "output_mode": {"const": "NEW_FILES_ONLY_OVERLAY"},
            "counts": {"type": "object"},
            "files": {"type": "array", "items": {"type": "object", "required": ["path", "sha256", "bytes"]}},
            "runtime_integration": {"const": False},
            "ui_integration": {"const": False},
            "source_modification": {"const": False},
        },
        "additionalProperties": True,
    }
    for name, schema in schemas.items():
        write_json(sdir / name, schema)


VALIDATOR = r'''from __future__ import annotations
import argparse, hashlib, json, os, re, unicodedata
from pathlib import Path

def canonical_bytes(o): return (json.dumps(o,sort_keys=True,ensure_ascii=False,separators=(",",":"))+"\n").encode("utf-8")
def sha_file(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def load(p): return json.loads(p.read_text(encoding="utf-8"))
def fold(s): return unicodedata.normalize("NFKC",s).casefold()
def record_ok(r):
 b={k:v for k,v in r.items() if k!="record_commitment_sha256"}
 return hashlib.sha256(canonical_bytes(b)).hexdigest()==r.get("record_commitment_sha256")
def registry_ok(o):
 b={k:v for k,v in o.items() if k!="registry_commitment_sha256"}
 return hashlib.sha256(canonical_bytes(b)).hexdigest()==o.get("registry_commitment_sha256")
def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("root")
 ap.add_argument("--authority-root")
 ap.add_argument("--baseline-root")
 a=ap.parse_args(); root=Path(a.root).resolve(); cat=root/"catalog_authority/cat1"; d=cat/"data"
 names={
  "spheres":"canonical_spheres.v1.json","talents":"canonical_talents.v1.json","edges":"sphere_talent_memberships.v1.json",
  "labels":"sphere_aliases_and_labels.v1.json","mixed":"mixed_candidate_classification.v1.json","background":"background_origin_talent_routes.v1.json",
  "prereqs":"prerequisite_projection.v1.json","readable":"owner_readable_projection.v1.json","dispositions":"selection_dispositions.v1.json",
  "decisions":"unresolved_authority_decisions.v1.json"}
 regs={k:load(d/v) for k,v in names.items()}; r={k:v["records"] for k,v in regs.items()}
 assert len(r["spheres"])==85 and len(r["talents"])==1748 and len(r["edges"])==1748 and len(r["mixed"])==3180 and len(r["background"])==77
 assert len(r["prereqs"])==1748 and len(r["readable"])==1833 and len(r["dispositions"])==1833
 assert all(registry_ok(v) for v in regs.values())
 assert all(record_ok(x) for rows in r.values() for x in rows)
 sphere_ids=[x["canonical_sphere_id"] for x in r["spheres"]]; talent_ids=[x["canonical_talent_id"] for x in r["talents"]]
 assert len(sphere_ids)==len(set(sphere_ids)); assert len(talent_ids)==len(set(talent_ids))
 assert len({fold(x) for x in sphere_ids})==len(sphere_ids); assert len({fold(x) for x in talent_ids})==len(talent_ids)
 assert len({fold(x["display_name"]) for x in r["spheres"]})==85
 assert "Fencing" not in {x["display_name"] for x in r["spheres"]}
 piercing=next(x for x in r["spheres"] if x["display_name"]=="The Piercing Needle")
 assert piercing["confirmed_selectable_talent_count"]==39 and piercing["confirmed_membership_count"]==39
 fencing=next(x for x in r["labels"] if x["label"]=="Fencing")
 assert fencing["canonical_sphere_id"]==piercing["canonical_sphere_id"] and fencing["owner_ruling_id"]=="OWNER-CATALOG-2026-07-25-001"
 ft=[x for x in r["talents"] if x["legacy_source_sphere_label"]=="Fencing"]
 assert len(ft)==39 and all(x["owning_canonical_sphere_id"]==piercing["canonical_sphere_id"] for x in ft)
 harvest=next(x for x in r["spheres"] if x["display_name"]=="Harvesting Gathering")
 assert sum(x["display_name"]=="Harvesting Gathering" for x in r["spheres"])==1
 assert next(x for x in r["labels"] if x["label"]=="Harvesting-Gathering")["canonical_sphere_id"]==harvest["canonical_sphere_id"]
 valid_spheres=set(sphere_ids); assert all(x["owning_canonical_sphere_id"] in valid_spheres for x in r["talents"])
 edge_pairs={(x["canonical_talent_id"],x["canonical_sphere_id"]) for x in r["edges"]}; assert len(edge_pairs)==1748
 assert {x["canonical_talent_id"] for x in r["edges"]}==set(talent_ids)
 owner={x["canonical_talent_id"]:x["owning_canonical_sphere_id"] for x in r["talents"]}; assert all(owner[t]==s for t,s in edge_pairs)
 assert all(x["record_type"]=="CONFIRMED_SELECTABLE_TALENT" for x in r["talents"])
 assert sum(bool(x["background_only"]) for x in r["talents"])==0
 assert all(x["background_only"] and x["ordinary_training_presentation"] is False and x["selection_disposition"]=="BACKGROUND_ORIGIN_ONLY" for x in r["background"])
 allowed={"alias","route_label","content_family_label","historical_label","generated_coverage_grouping","invalid_unresolved_label"}
 assert len(r["labels"])==13 and all(x["label_classification"] in allowed for x in r["labels"])
 assert all(x["canonical_sphere_id"] in valid_spheres for x in r["labels"] if x["canonical_sphere_id"] is not None)
 assert all(x["canonical_sphere_id"] in valid_spheres for x in r["labels"] if x["label_classification"]=="alias")
 assert len({fold(x["label"]) for x in r["labels"]})==len(r["labels"])
 assert not any(x["cat1_classification"]=="AMBIGUOUS_REQUIRES_AUTHORITY_DECISION" and x["owner_selectable_output"] for x in r["mixed"])
 assert not ({x["candidate_record_id"] for x in r["mixed"] if x["cat1_classification"]=="AMBIGUOUS_REQUIRES_AUTHORITY_DECISION"}&set(talent_ids))
 assert all(x["record_id"] in set(talent_ids) for x in r["prereqs"])
 assert all(isinstance(x["creator_selectability_can_be_evaluated_safely"],bool) for x in r["prereqs"])
 assert {x["record_id"] for x in r["readable"]}==set(sphere_ids)|set(talent_ids)
 manifest=load(cat/"OVERLAY_MANIFEST.json"); inventory=load(cat/"OVERLAY_FILE_HASHES.json")
 files={p.relative_to(root).as_posix():p for p in root.rglob("*") if p.is_file() and p.name!="OVERLAY_FILE_HASHES.json"}
 listed={x["path"]:x for x in inventory["files"]}; assert set(files)==set(listed)
 assert all(sha_file(p)==listed[n]["sha256"] and p.stat().st_size==listed[n]["bytes"] for n,p in files.items())
 assert manifest["runtime_integration"] is False and manifest["ui_integration"] is False and manifest["source_modification"] is False
 if a.authority_root:
  ar=Path(a.authority_root).resolve(); prov=load(cat/"evidence/SOURCE_PROVENANCE_REPORT.json")
  for x in prov["sources"]:
   p=ar/x["source_path"]; assert p.is_file() and sha_file(p)==x["sha256"]
 if a.baseline_root:
  br=Path(a.baseline_root).resolve(); overlaps=[n for n in files if (br/n).exists()]; assert not overlaps, overlaps
 print(json.dumps({"result":"PASS","spheres":85,"talents":1748,"edges":1748,"mixed":3180,"background_only":77,"labels":13,"ambiguous_quarantined":sum(x["cat1_classification"]=="AMBIGUOUS_REQUIRES_AUTHORITY_DECISION" for x in r["mixed"]),"external_source_checks":bool(a.authority_root),"baseline_overlap_checks":bool(a.baseline_root)},sort_keys=True))
if __name__=="__main__": main()
'''

SUPPORT = r'''from __future__ import annotations
import hashlib, json, os, unicodedata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CAT=ROOT/"catalog_authority/cat1"; DATA=CAT/"data"
def load(name): return json.loads((DATA/name).read_text(encoding="utf-8"))
def cbytes(o): return (json.dumps(o,sort_keys=True,ensure_ascii=False,separators=(",",":"))+"\n").encode()
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def fold(s): return unicodedata.normalize("NFKC",s).casefold()
def record_ok(r): return hashlib.sha256(cbytes({k:v for k,v in r.items() if k!="record_commitment_sha256"})).hexdigest()==r["record_commitment_sha256"]
def registry_ok(o): return hashlib.sha256(cbytes({k:v for k,v in o.items() if k!="registry_commitment_sha256"})).hexdigest()==o["registry_commitment_sha256"]
'''

TEST_AUTHORITY = r'''from cat1_test_support import *
def test_exact_core_counts():
 assert len(load("canonical_spheres.v1.json")["records"])==85
 assert len(load("canonical_talents.v1.json")["records"])==1748
 assert len(load("sphere_talent_memberships.v1.json")["records"])==1748
 assert len(load("mixed_candidate_classification.v1.json")["records"])==3180
 assert len(load("background_origin_talent_routes.v1.json")["records"])==77
def test_fencing_owner_ruling():
 s=load("canonical_spheres.v1.json")["records"]; t=load("canonical_talents.v1.json")["records"]; a=load("sphere_aliases_and_labels.v1.json")["records"]
 assert not any(x["display_name"]=="Fencing" for x in s)
 p=next(x for x in s if x["display_name"]=="The Piercing Needle")
 assert len([x for x in t if x["legacy_source_sphere_label"]=="Fencing" and x["owning_canonical_sphere_id"]==p["canonical_sphere_id"]])==39
 assert next(x for x in a if x["label"]=="Fencing")["owner_ruling_id"]=="OWNER-CATALOG-2026-07-25-001"
def test_harvesting_collision():
 s=load("canonical_spheres.v1.json")["records"]; a=load("sphere_aliases_and_labels.v1.json")["records"]
 h=[x for x in s if x["display_name"]=="Harvesting Gathering"]; assert len(h)==1
 assert next(x for x in a if x["label"]=="Harvesting-Gathering")["canonical_sphere_id"]==h[0]["canonical_sphere_id"]
def test_all_extra_labels_are_typed_and_resolve():
 s={x["canonical_sphere_id"] for x in load("canonical_spheres.v1.json")["records"]}; a=load("sphere_aliases_and_labels.v1.json")["records"]
 expected={"Chains / Meridian","Chakra Imbuement","Chakra Universal","Drain","Fencing","Harvesting-Gathering","Phasing","Predator","Pressure Points / Meridian","Universal","Universal C09","Universal Martial","Vitality"}
 assert {x["label"] for x in a}==expected
 assert all(x["canonical_sphere_id"] in s for x in a if x["canonical_sphere_id"] is not None)
 assert all(x["canonical_sphere_id"] in s for x in a if x["label_classification"]=="alias")
def test_unique_ids_and_unicode_casefolds():
 s=load("canonical_spheres.v1.json")["records"]; t=load("canonical_talents.v1.json")["records"]
 assert len({x["canonical_sphere_id"] for x in s})==85==len({fold(x["canonical_sphere_id"]) for x in s})
 assert len({x["canonical_talent_id"] for x in t})==1748==len({fold(x["canonical_talent_id"]) for x in t})
def test_membership_uniqueness_and_single_owner():
 t=load("canonical_talents.v1.json")["records"]; e=load("sphere_talent_memberships.v1.json")["records"]
 pairs={(x["canonical_talent_id"],x["canonical_sphere_id"]) for x in e}; assert len(pairs)==1748
 owners={x["canonical_talent_id"]:x["owning_canonical_sphere_id"] for x in t}; assert all(owners[i]==s for i,s in pairs)
def test_background_only_separation():
 t=load("canonical_talents.v1.json")["records"]; b=load("background_origin_talent_routes.v1.json")["records"]
 assert not any(x["background_only"] for x in t) and len(b)==77
 assert all(x["background_only"] and x["ordinary_training_presentation"] is False and x["selection_disposition"]=="BACKGROUND_ORIGIN_ONLY" for x in b)
def test_no_non_talent_in_canonical_registry():
 assert all(x["record_type"]=="CONFIRMED_SELECTABLE_TALENT" for x in load("canonical_talents.v1.json")["records"])
'''

TEST_PROJECTION = r'''from cat1_test_support import *
def test_unresolved_rows_are_excluded_from_selectable_output():
 m=load("mixed_candidate_classification.v1.json")["records"]; t={x["canonical_talent_id"] for x in load("canonical_talents.v1.json")["records"]}
 amb=[x for x in m if x["cat1_classification"]=="AMBIGUOUS_REQUIRES_AUTHORITY_DECISION"]
 assert len(amb)==25 and all(not x["owner_selectable_output"] for x in amb) and not ({x["candidate_record_id"] for x in amb}&t)
def test_220_rows_reexamined():
 import csv
 with (DATA/"unresolved_220_resolution_report.v1.csv").open(encoding="utf-8",newline="") as f: rows=list(csv.DictReader(f))
 assert len(rows)==220 and all(x["cat1_classification"] for x in rows)
def test_decision_packets_are_grouped_and_bounded():
 d=load("unresolved_authority_decisions.v1.json")["records"]
 assert len(d)==6 and sum(len(x.get("affected_ids",[])) for x in d)>=25
def test_prerequisite_projection_complete_and_typed():
 p=load("prerequisite_projection.v1.json")["records"]
 assert len(p)==1748 and all(x["prerequisite_evaluation_status"] for x in p)
 assert all(isinstance(x["typed_constraints"],list) and isinstance(x["creator_selectability_can_be_evaluated_safely"],bool) for x in p)
def test_owner_readable_projection_complete():
 r=load("owner_readable_projection.v1.json")["records"]; s={x["canonical_sphere_id"] for x in load("canonical_spheres.v1.json")["records"]}; t={x["canonical_talent_id"] for x in load("canonical_talents.v1.json")["records"]}
 assert len(r)==1833 and {x["record_id"] for x in r}==s|t and all(x["description_status"] for x in r)
def test_selection_disposition_complete():
 r=load("selection_dispositions.v1.json")["records"]
 allowed={"OWNER_SELECTABLE_NOW","OWNER_SELECTABLE_WITH_PREREQUISITES","AUTOMATIC_GRANTED","BACKGROUND_ORIGIN_ONLY","ADVANCEMENT_GRANTED","TRAINING_ONLY","DISPLAY_ONLY","GM_ONLY","RESTRICTED_CONTENT","HISTORICAL_OR_DEPRECATED","NOT_YET_IMPLEMENTED_BY_DESIGN","BLOCKED_MISSING_TYPED_AUTHORITY","AMBIGUOUS_REQUIRES_OWNER_DECISION"}
 assert len(r)==1833 and all(x["selection_disposition"] in allowed for x in r)
def test_record_and_registry_commitments():
 for name in ["canonical_spheres.v1.json","sphere_aliases_and_labels.v1.json","canonical_talents.v1.json","sphere_talent_memberships.v1.json","mixed_candidate_classification.v1.json","background_origin_talent_routes.v1.json","prerequisite_projection.v1.json","owner_readable_projection.v1.json","selection_dispositions.v1.json","unresolved_authority_decisions.v1.json"]:
  o=load(name); assert registry_ok(o); assert all(record_ok(x) for x in o["records"])
'''

TEST_SCHEMA_PROVENANCE = r'''from cat1_test_support import *
def test_all_versioned_schemas_validate():
 import jsonschema
 pairs=[("canonical_sphere_registry.schema.json","canonical_spheres.v1.json"),("sphere_alias_registry.schema.json","sphere_aliases_and_labels.v1.json"),("canonical_talent_registry.schema.json","canonical_talents.v1.json"),("mixed_candidate_classification.schema.json","mixed_candidate_classification.v1.json"),("selection_disposition.schema.json","selection_dispositions.v1.json"),("prerequisite_projection.schema.json","prerequisite_projection.v1.json"),("owner_readable_projection.schema.json","owner_readable_projection.v1.json"),("unresolved_authority_decisions.schema.json","unresolved_authority_decisions.v1.json")]
 for s,d in pairs: jsonschema.Draft202012Validator(json.loads((CAT/"schemas"/s).read_text())).validate(load(d))
 jsonschema.Draft202012Validator(json.loads((CAT/"schemas/overlay_manifest.schema.json").read_text())).validate(json.loads((CAT/"OVERLAY_MANIFEST.json").read_text()))
def test_source_provenance_is_complete():
 for name in ["canonical_spheres.v1.json","canonical_talents.v1.json","mixed_candidate_classification.v1.json","prerequisite_projection.v1.json","owner_readable_projection.v1.json"]:
  for x in load(name)["records"]:
   p=x["source_provenance"]; assert p["source_path"] and p["source_anchor"] and len(p["source_authority_sha256"])==64
def test_external_source_paths_and_hashes_exist():
 ar=Path(os.environ["CAT1_AUTHORITY_ROOT"]); report=json.loads((CAT/"evidence/SOURCE_PROVENANCE_REPORT.json").read_text())
 assert all((ar/x["source_path"]).is_file() and sha(ar/x["source_path"])==x["sha256"] for x in report["sources"])
def test_overlay_contains_only_new_paths():
 br=Path(os.environ["CAT1_BASELINE_ROOT"])
 paths=[p.relative_to(ROOT) for p in ROOT.rglob("*") if p.is_file()]
 assert not [str(p) for p in paths if (br/p).exists()]
def test_overlay_checksum_inventory_exact():
 inv=json.loads((CAT/"OVERLAY_FILE_HASHES.json").read_text()); listed={x["path"]:x for x in inv["files"]}
 actual={p.relative_to(ROOT).as_posix():p for p in ROOT.rglob("*") if p.is_file() and p.name!="OVERLAY_FILE_HASHES.json"}
 assert set(actual)==set(listed) and all(sha(p)==listed[n]["sha256"] and p.stat().st_size==listed[n]["bytes"] for n,p in actual.items())
def test_source_no_mutation_evidence():
 e=json.loads((CAT/"evidence/NO_MUTATION_EVIDENCE.json").read_text()); assert e["result"]=="PASS" and e["all_compared_trees_identical"] is True
def test_deterministic_build_evidence():
 e=json.loads((CAT/"evidence/DETERMINISTIC_BUILD_EVIDENCE.json").read_text()); assert e["result"]=="PASS" and e["byte_identical_overlay_trees"] is True
def test_runtime_and_ui_stop_boundary():
 m=json.loads((CAT/"OVERLAY_MANIFEST.json").read_text()); assert m["runtime_integration"] is False and m["ui_integration"] is False and m["source_modification"] is False
'''

TEST_EXTRACTION = r'''from cat1_test_support import *
def test_repeated_extraction_is_identical(tmp_path):
 import zipfile
 z=tmp_path/"overlay.zip"
 with zipfile.ZipFile(z,"w",compression=zipfile.ZIP_DEFLATED) as f:
  for p in sorted(ROOT.rglob("*")):
   if p.is_file(): f.write(p,p.relative_to(ROOT).as_posix())
 roots=[]
 for n in ("a","b"):
  d=tmp_path/n; d.mkdir()
  with zipfile.ZipFile(z) as f: f.extractall(d)
  roots.append(d)
 def digest(d):
  h=hashlib.sha256()
  for p in sorted(d.rglob("*")):
   if p.is_file(): h.update(p.relative_to(d).as_posix().encode()+b"\0"+p.read_bytes())
  return h.hexdigest()
 assert digest(roots[0])==digest(roots[1])
'''


def install_tests(out: Path) -> None:
    tests = out / "tests"
    write_text(tests / "cat1_test_support.py", SUPPORT)
    write_text(tests / "test_cat1_authority.py", TEST_AUTHORITY)
    write_text(tests / "test_cat1_projection.py", TEST_PROJECTION)
    write_text(tests / "test_cat1_schema_provenance.py", TEST_SCHEMA_PROVENANCE)
    write_text(tests / "test_cat1_repeated_extraction.py", TEST_EXTRACTION)


def regenerate_inventories(out: Path) -> None:
    cat = out / "catalog_authority" / "cat1"
    manifest_path = cat / "OVERLAY_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    excluded = {cat / "OVERLAY_MANIFEST.json", cat / "OVERLAY_FILE_HASHES.json"}
    manifest["files"] = [
        {"path": p.relative_to(out).as_posix(), "sha256": sha256_file(p), "bytes": p.stat().st_size}
        for p in sorted(out.rglob("*")) if p.is_file() and p not in excluded
    ]
    write_json(manifest_path, manifest)
    inventory_path = cat / "OVERLAY_FILE_HASHES.json"
    records = [
        {"path": p.relative_to(out).as_posix(), "sha256": sha256_file(p), "bytes": p.stat().st_size}
        for p in sorted(out.rglob("*")) if p.is_file() and p != inventory_path
    ]
    write_json(inventory_path, {"schema": "TianxiaCAT1.OverlayFileHashes.v1", "coverage_policy": "Every regular overlay file except this inventory itself.", "files": records})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--authority-root", required=True)
    ap.add_argument("--qa2-root", required=True)
    ap.add_argument("--c3b-source-root", required=True)
    ap.add_argument("--owner-ruling", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-builder", default=str(Path(__file__).with_name("build_cat1.py")))
    args = ap.parse_args()
    out = Path(args.out).resolve()
    subprocess.run([
        sys.executable, args.base_builder,
        "--authority-root", args.authority_root,
        "--qa2-root", args.qa2_root,
        "--c3b-source-root", args.c3b_source_root,
        "--owner-ruling", args.owner_ruling,
        "--out", str(out),
    ], check=True)
    cat = out / "catalog_authority" / "cat1"
    install_schemas(cat)
    write_text(cat / "validators" / "validate_cat1_overlay.py", VALIDATOR)
    install_tests(out)
    shutil.copy2(args.base_builder, cat / "tools" / "build_cat1_base.py")
    shutil.copy2(Path(__file__), cat / "tools" / "build_cat1_overlay.py")
    regenerate_inventories(out)


if __name__ == "__main__":
    main()
