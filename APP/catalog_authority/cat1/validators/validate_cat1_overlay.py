from __future__ import annotations
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
