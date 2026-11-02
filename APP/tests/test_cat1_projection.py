from cat1_test_support import *
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
