from cat1_test_support import *
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
