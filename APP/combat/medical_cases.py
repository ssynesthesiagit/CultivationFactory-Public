"""Typed GM clinical facts, shared by Life recognition and Medicine resolution.

Unknown causes remain unknown. DCs and treatment applicability are explicit GM
rulings, not guessed from damage or a nearby ability. Bundles seal cases for
deterministic combat replay; public logs omit causes. Only the examining actor's
knowledge receipt contains a successfully identified cause.
"""
import re
import json

from .tabletop import TabletopError

CATEGORIES = ("bleeding", "suffocation", "poisoning", "disease", "dying", "shock",
              "spiritual drift", "broken meridian flow", "wound", "condition")


def active_cases(base, declarations):
    """Merge sealed character cases and later native scene corrections."""
    rows = [*base, *declarations]
    ended = {r.get("fact_id") for r in rows if r.get("type") == "clinical_case_retraction"}
    return [r for r in rows if r.get("type") == "clinical_case" and r.get("id") not in ended]


def validate_case(case):
    keys = {"id", "category", "cause", "obvious", "living", "dc", "treatment_ids", "source_note", "economy", "seconds", "range_ft"}
    valid = (isinstance(case, dict) and set(case) == keys
             and isinstance(case["id"], str) and re.fullmatch(r"[a-z0-9_-]{1,60}", case["id"])
             and case["category"] in CATEGORIES and type(case["obvious"]) is int and case["obvious"] in (0, 1)
             and type(case["living"]) is int and case["living"] in (0, 1)
             and type(case["dc"]) is int and case["dc"] >= 0
             and case["economy"] in ("ACTION", "BONUS_ACTION", "NONE")
             and type(case["seconds"]) is int and case["seconds"] >= 0
             and type(case["range_ft"]) is int and case["range_ft"] >= 0
             and isinstance(case["treatment_ids"], list) and all(isinstance(t, str) and t for t in case["treatment_ids"])
             and all(isinstance(case[k], str) and 0 < len(case[k]) <= 1000 and case[k].strip() for k in ("cause", "source_note")))
    if not valid:
        raise TabletopError("CLINICAL_CASE_INVALID", "Supply a medical category, cause, visible signs, living status, whole-number DC, examination distance and timing; choose treatment talents and explain the GM's source or ruling.", 422)
    from .factory_compiler import TYPED_AUTHORITY
    mechanics = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]
    sources = {}
    for talent_id in case["treatment_ids"]:
        row = mechanics.get(talent_id) or {}
        from .ext import run_strict
        if row.get("kind") != "talent" or not any(result is True for result in run_strict("clinical_treatment_allowed", talent_id, row)):
            raise TabletopError("CLINICAL_TREATMENT_INVALID", "Choose a printed talent that can treat this medical case and record the GM's source ruling.", 422)
        sources[talent_id] = row["source"]["text_sha256"]
    return {**case, "type": "clinical_case", "authority": "GM", "treatment_sources": sources}


def knowledge(engine, actor_id):
    """Private read for the examining seat; callers must use their own actor ID.

    No target's unexamined clinical cases are returned. The game owner controls
    seats, as with the existing manual/Ask-me choice transport.
    """
    actor = engine.state.actors.get(actor_id)
    if actor is None:
        raise TabletopError("CLINICAL_ACTOR_UNKNOWN", "Choose an examining creature in this fight.", 404)
    return [{"case_id": c.data["case_id"], "subject": c.data["subject"], "cause": c.data["cause"]}
            for c in actor.conditions.values() if c.condition_id.startswith("condition:typed.clinical_knowledge.")]


def retract_case(records, request):
    """Append a GM correction without rewriting a historical clinical fact."""
    valid = (isinstance(request, dict) and set(request) == {"id", "source_note"}
             and isinstance(request["id"], str) and re.fullmatch(r"[a-z0-9_-]{1,60}", request["id"])
             and isinstance(request["source_note"], str) and 0 < len(request["source_note"]) <= 1000 and request["source_note"].strip())
    if not valid:
        raise TabletopError("CLINICAL_RETRACTION_INVALID", "Choose a recorded case and explain the GM's correction or change in the scene.", 422)
    ended = {r.get("fact_id") for r in records if r.get("type") == "clinical_case_retraction"}
    if request["id"] in ended or not any(r.get("id") == request["id"] and r.get("type") == "clinical_case" for r in records):
        raise TabletopError("CLINICAL_CASE_UNKNOWN", "That medical case is not active on this creature.", 404)
    return {"id": "retract-" + request["id"], "type": "clinical_case_retraction", "authority": "GM",
            "fact_id": request["id"], "source_note": request["source_note"]}


def scene_distance(session, aid, tid, *, physical=True):
    """Visible scene distance between the actors' actual bound footprints.

    Life's scene recognition and Medicine consumers share native size/footprint
    rules, including altitude. A blocked path remains unknown/unavailable.
    """
    if aid == tid:
        return 0
    from .gate2_runtime_models import Position
    from .footprints import standard_actor_footprint
    from .footprint_registry import resolve_actor_footprint
    from .dynamic_size import shape, category_name
    def cells(actor_id):
        actor = session.state["actors"][actor_id]
        template = actor["bundle"]["actor_template"]
        record = template.get("summon") or {}
        if record.get("size") or record.get("footprint"):
            footprint, _ = resolve_actor_footprint(actor_id, summon_record=record)
        else:
            footprint = shape(standard_actor_footprint(), category_name(actor.get("size")))
        origin = Position.model_validate(actor["position"])
        return [Position(x=x, y=y, z=origin.z) for x, y in session.grid.footprint_cells(origin, footprint)]
    distances = [session.grid.distance_ft(a, b) for a in cells(aid) for b in cells(tid)
                 if session.grid.line_of_sight(a, b)
                 and (not physical or session.grid.line_of_physical_transmission(a, b))]
    return min(distances, default=None)
