from cat1_test_support import *
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
