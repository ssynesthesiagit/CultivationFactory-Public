"""Shared historical recipe capture for the regression and its fixture generator."""
import json
from copy import deepcopy


def capture(service, run):
    """Compare full constructed bytes, including seeds and creator histories."""
    from character_creation.constructed_arts.records import constructed_art_contract
    response = json.loads(run["response"]["exact_response_text"])
    plan, intent, _ = service._normalize_and_materialize_response(run, response)
    service._materialize_constructed_arts(run, service.db, phase="historical-reload", plan=plan)
    with service.db.connection() as conn:
        rows = conn.execute("SELECT record_json FROM project_locked_records WHERE project_id=? ORDER BY record_id", (run["project_id"],)).fetchall()
    records = [json.loads(row["record_json"]) for row in rows]
    records = [row for row in records if constructed_art_contract(row)]
    assert {constructed_art_contract(row)["kind"] for row in records} >= {"manual", "forged_technique", "immortal_art"}
    creator_rolls = {key: [row["parameters"][key] for row in plan["stage2_proposal"]["choices"] if key in (row.get("parameters") or {})]
                     for key in ("forging_acquisition", "immortal_refinement")}
    assert all(histories and all(history["attempts"] for history in histories) for histories in creator_rolls.values())
    def seeds(value):
        if isinstance(value, dict):
            construction = value.get("construction") or {}
            found = [construction["seed"]] if isinstance(construction, dict) and "seed" in construction else []
            return found + [seed for child in value.values() for seed in seeds(child)]
        if isinstance(value, list):
            return [seed for child in value for seed in seeds(child)]
        return []
    return {"intent_hash": intent.intent_hash, "plan": plan, "records": records,
            "constructor_seeds": seeds(records), "creator_rolls": creator_rolls}


def missing_marker_capture(service, run):
    """Exercise both historical Manual fallbacks with a still-seeded project."""
    from recorded_art_authority import RECORDED_ART_CONSTRUCTION_KIND
    run = deepcopy(run)
    plan, intent, _ = service._normalize_and_materialize_response(run, json.loads(run["response"]["exact_response_text"]))
    run["request"]["server_owned_authority"].pop("manual_collection")
    project = service._project(run["project_id"])
    document = intent.as_dict()
    document["acquisition_intent"].pop("manual_collection", None)
    rows = [r for r in plan["stage2_proposal"]["choices"] if r["kind"] not in {
        "training_source_access", RECORDED_ART_CONSTRUCTION_KIND,
        "forged_technique_creation", "immortal_art_creation"}]
    records = service._locked_records_for_run(run)
    service._add_delegated_path_records(run, records, service._delegated_path_ids_from_canonical_intent(intent), db=service.db, store=service.projects)
    manual, _ = service._manual_constructions(run, project, document, rows, records, 15, intent_hash=intent.intent_hash)
    bundles, _, roll = service._manual_collection_constructions(run, project, document, rows, records, 15, intent_hash=intent.intent_hash, dice_faces=[1, 1, 1])
    return {"manual": manual, "collection": bundles, "roll": roll}
