"""Final-stage checks and compiler translation for controller-built Immortal Arts.

The creative controller constructs, refines and compiles every Immortal Art
while it builds the character (``character_creation.constructed_arts``).  The
final-character stage creates nothing: it re-checks each sealed Art against
the compiled rules and translates it into the pinned compiler's ledger shape.

Rules enforced here (docs/rules/TIANXIA_RULES_AS_WRITTEN.md):

* RAW-182 / Q34 — Immortal Arts exist only from CL 15; a complete CL 15+
  character has at least one.
* RAW-183 / Q35 — at most one new Art per CL from 15.  Factory-built
  characters additionally keep the construction engine's tier ceiling.
* RAW-187 — Mandate Complexity, Sphere Count Modifier, tier threshold and
  Heaven Pressure.
* RAW-188 — Factor Escalation, Refinement DC and Activation Cost.
* RAW-189 — Refinement Check history, research days and material cost.
* RAW-191 — every Art has one executable Action on the sealed surfaces.

Every translated field is copied or derived from the sealed Art; no text or
mechanic is authored here.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from app.core import FoundryError, sha256_json
from character_creation.constructed_arts.immortal_art import (
    IMMORTAL_ART_REFINEMENT_MAX_ATTEMPTS,
    immortal_art_count_ceiling,
    immortal_art_tier_for_cl,
)


IMMORTAL_ART_CLASSIFICATION = "immortal_art"
CONSTRUCTED_IMMORTAL_ART_SCHEMA = "TianxiaFoundry.ImmortalArt.v1"
CONSTRUCTED_IMMORTAL_ART_BINDING_SCHEMA = "TianxiaFoundry.ConstructedImmortalArtBinding.v1"
IMMORTAL_ART_MINIMUM_CL = 15
_MANDATE_THRESHOLD_BY_TIER = {"Nascent Soul": 3, "Immortal": 6}
_FACTOR_ESCALATION = {0: 0, 1: 1, 2: 3, 3: 7, 4: 15, 5: 31}
_LEDGER_PATH = "Build/Character_Master_Ledger.json"
_IMMORTAL_ARTS_PATH = "Build/Immortal_Arts.json"
_SURFACE_PATHS = ("Build/Complete_Action_Surface.json", "Command_4/Complete_Action_Surface.json")


def _error(message: str, *, details: Any = None) -> FoundryError:
    return FoundryError("FINAL_CHARACTER_IMMORTAL_ART_INVALID", message, details=details, status_code=409)


def _read(root: Path, relative: str) -> Any:
    path = Path(root) / relative
    if path.is_symlink() or not path.is_file():
        raise _error("A sealed Immortal Art source file is missing or unsafe.", details={"path": relative})
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error("A sealed Immortal Art source file is unreadable.", details={"path": relative}) from exc


def _write(root: Path, relative: str, value: Any) -> None:
    (Path(root) / relative).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _int(value: Any) -> bool:
    return type(value) is int


def _check_construction(art: Mapping[str, Any], *, cl_created: int) -> None:
    """Recompute every construction figure from the compiled rules."""

    art_id = art.get("immortal_art_id")

    def fail(message: str, **details: Any) -> FoundryError:
        return _error(message, details={"immortal_art_id": art_id, **details})

    aspect = art.get("dao_aspect")
    factors = art.get("factors")
    burdens = art.get("burdens")
    correspondence = art.get("correspondence")
    if (
        not isinstance(aspect, Mapping)
        or not _int(aspect.get("mandate_cost"))
        or not _int(aspect.get("cp_modifier"))
        or not isinstance(factors, list)
        or not factors
        or any(not isinstance(row, Mapping) or not _int(row.get("mandate_cost")) or not _int(row.get("cp_cost")) for row in factors)
        or not isinstance(burdens, list)
        or any(not isinstance(row, Mapping) or not _int(row.get("stability_credit")) or not _int(row.get("cp_credit")) for row in burdens)
        or not isinstance(correspondence, list)
        or any(not isinstance(row, Mapping) or not _int(row.get("bridge_factor_count")) for row in correspondence)
    ):
        raise fail("The Immortal Art has an incomplete Aspect, Factor, Burden or correspondence record.")
    bridge_count = sum(row["bridge_factor_count"] for row in correspondence)
    factor_cost = sum(row["mandate_cost"] for row in factors)
    factor_cp = sum(row["cp_cost"] for row in factors)
    stability_credit = sum(row["stability_credit"] for row in burdens)
    burden_cp_credit = sum(row["cp_credit"] for row in burdens)

    packages = art.get("source_packages_used")
    if not isinstance(packages, list) or not packages or len(set(packages)) != len(packages):
        raise fail("The Immortal Art has no distinct source package list.")
    sphere_modifier = min(len(packages) - 1, 3)  # RAW-187 Sphere Count Modifier

    breakdown = art.get("mandate_complexity_breakdown")
    if not isinstance(breakdown, Mapping) or any(
        not _int(breakdown.get(key))
        for key in ("aspect_cost", "factor_cost", "bridge_factor_cost", "source_package_modifier", "special_scale_cost", "final")
    ):
        raise fail("The Immortal Art has no complete Mandate Complexity breakdown.")
    complexity = (
        aspect["mandate_cost"] + factor_cost + bridge_count + sphere_modifier + breakdown["special_scale_cost"]
    )
    expected_breakdown = {
        "aspect_cost": aspect["mandate_cost"],
        "factor_cost": factor_cost,
        "bridge_factor_cost": bridge_count,
        "source_package_modifier": sphere_modifier,
        "final": complexity,
    }
    if any(breakdown.get(key) != value for key, value in expected_breakdown.items()) or art.get("mandate_complexity") != complexity:
        raise fail("The Immortal Art Mandate Complexity does not follow RAW-187.", expected=expected_breakdown)

    tier = immortal_art_tier_for_cl(cl_created)
    threshold = _MANDATE_THRESHOLD_BY_TIER.get(tier or "")
    pressure = 2 * max(0, complexity - threshold) if threshold is not None else None
    if art.get("mandate_threshold") != threshold or art.get("heaven_pressure") != pressure:
        raise fail("The Immortal Art threshold or Heaven Pressure does not follow RAW-187.", tier=tier)

    factor_count = len(factors) + bridge_count
    if factor_count not in _FACTOR_ESCALATION and art.get("gm_review_required") is not True:
        raise fail("Six or more Factors require GM review (RAW-188).")
    escalation = _FACTOR_ESCALATION.get(factor_count)
    if escalation is not None and art.get("factor_escalation") != escalation:
        raise fail("The Immortal Art Factor Escalation does not follow RAW-188.")
    spheres_used = art.get("source_spheres_used")
    if not _int(spheres_used) or spheres_used < 1:
        raise fail("The Immortal Art does not record the spheres it uses.")
    dc_floor = 10 + complexity + spheres_used + 1  # one Dao Aspect per Factory-built Art
    expected_dc = max(dc_floor, dc_floor + art["factor_escalation"] + pressure - stability_credit)
    if art.get("refinement_dc") != expected_dc:
        raise fail("The Immortal Art Refinement DC does not follow RAW-188.", expected=expected_dc)

    cp = art.get("activation_cp_breakdown")
    if not isinstance(cp, Mapping) or not _int(cp.get("base_source_cp")):
        raise fail("The Immortal Art has no Activation Cost breakdown.")
    expected_cp = max(1, cp["base_source_cp"] + aspect["cp_modifier"] + factor_cp + bridge_count - burden_cp_credit)
    if (
        cp.get("aspect_cp") != aspect["cp_modifier"]
        or cp.get("factor_cp") != factor_cp
        or cp.get("bridge_cp") != bridge_count
        or cp.get("burden_cp_credit") != burden_cp_credit
        or cp.get("final") != expected_cp
        or art.get("activation_cp") != expected_cp
    ):
        raise fail("The Immortal Art Activation Cost does not follow RAW-188.", expected=expected_cp)

    if art.get("research_days") != 5 * complexity or art.get("material_cost_gp") != 250 * complexity * complexity:
        raise fail("The Immortal Art research or material cost does not follow RAW-189.")

    refinement = art.get("refinement")
    attempts = refinement.get("attempts") if isinstance(refinement, Mapping) else None
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= IMMORTAL_ART_REFINEMENT_MAX_ATTEMPTS:
        raise fail("The Immortal Art has no bounded Refinement Check history (RAW-189).")
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, Mapping):
            raise fail("A Refinement Check attempt is malformed.", attempt=index)
        die, pb, modifier = attempt.get("check_die_result"), attempt.get("pb"), attempt.get("ability_modifier")
        if not all(_int(value) for value in (die, pb, modifier)) or not 1 <= die <= 20:
            raise fail("A Refinement Check attempt has no bounded d20, PB and ability modifier.", attempt=index)
        total = die + pb + modifier
        success = total >= expected_dc
        final = index == len(attempts) - 1
        if (
            attempt.get("dc") != expected_dc
            or attempt.get("computed_check_total") != total
            or attempt.get("result") != ("success" if success else "failure")
            or success != final
        ):
            raise fail("The Refinement Check history does not follow RAW-189.", attempt=index)


def _surface_actions(root: Path) -> list[dict[str, Any]]:
    surfaces = []
    for relative in _SURFACE_PATHS:
        document = _read(root, relative)
        actions = document.get("actions") if isinstance(document, Mapping) else None
        if not isinstance(actions, list):
            raise _error("A sealed action surface has no actions list.", details={"path": relative})
        surfaces.append(actions)
    if surfaces[0] != surfaces[1]:
        raise _error("The Build and Command 4 action surfaces diverge.")
    return surfaces[0]


def read_constructed_immortal_arts(root: Path | str) -> list[dict[str, Any]]:
    """Return the sealed Immortal Arts with their Actions after the rules check."""

    root = Path(root)
    ledger = _read(root, _LEDGER_PATH)
    character = ledger.get("character") if isinstance(ledger, Mapping) else None
    character_cl = character.get("cl") if isinstance(character, Mapping) else None
    if not _int(character_cl) or character_cl < 1:
        raise _error("The sealed ledger has no character CL.")
    ledger_arts = ledger.get("immortal_arts")
    ledger_arts = [] if ledger_arts is None else ledger_arts
    projection = _read(root, _IMMORTAL_ARTS_PATH)
    projected_arts = projection.get("immortal_arts") if isinstance(projection, Mapping) else None
    if not isinstance(ledger_arts, list) or projected_arts != ledger_arts:
        raise _error("The ledger and Build Immortal Art records diverge.")

    if character_cl < IMMORTAL_ART_MINIMUM_CL:
        if ledger_arts:
            raise _error("Immortal Arts exist only from CL 15 (RAW-182).", details={"cl": character_cl})
        return []
    if not ledger_arts:
        raise _error("A CL 15+ character requires its controller-built Immortal Art (RAW-182).", details={"cl": character_cl})
    ceiling = immortal_art_count_ceiling(character_cl)
    if len(ledger_arts) > ceiling:
        raise _error("The character holds more Immortal Arts than the Factory ceiling.", details={"count": len(ledger_arts), "ceiling": ceiling})

    actions = _surface_actions(root)
    seen_ids: set[str] = set()
    seen_levels: set[int] = set()
    result: list[dict[str, Any]] = []
    for art in ledger_arts:
        if not isinstance(art, Mapping) or art.get("schema") != CONSTRUCTED_IMMORTAL_ART_SCHEMA:
            raise _error("A sealed Immortal Art is not a constructed Art record.")
        art_id = art.get("immortal_art_id")
        if (
            not isinstance(art_id, str)
            or not art_id
            or art.get("record_id") != art_id
            or art.get("art_id") != art_id
            or art_id in seen_ids
            or art.get("state") != "known"
            or not isinstance(art.get("name"), str)
            or not art["name"].strip()
        ):
            raise _error("A sealed Immortal Art has an invalid or duplicated identity.", details={"immortal_art_id": art_id})
        seen_ids.add(art_id)
        cl_created = art.get("cl_created")
        if not _int(cl_created) or not IMMORTAL_ART_MINIMUM_CL <= cl_created <= character_cl:
            raise _error("An Immortal Art was not created between CL 15 and the character's CL (RAW-182).", details={"immortal_art_id": art_id, "cl_created": cl_created})
        if cl_created in seen_levels:
            raise _error("Only one new Immortal Art may be gained at each CL (RAW-183).", details={"cl": cl_created})
        seen_levels.add(cl_created)
        if art.get("realm") != immortal_art_tier_for_cl(cl_created):
            raise _error("An Immortal Art records the wrong tier for its creation CL.", details={"immortal_art_id": art_id})
        refs = art.get("source_packet_ids")
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref for ref in refs):
            raise _error("An Immortal Art has no source packet references.", details={"immortal_art_id": art_id})
        _check_construction(art, cl_created=cl_created)
        matches = [row for row in actions if isinstance(row, Mapping) and row.get("record_id") == art_id]
        if len(matches) != 1 or not isinstance(matches[0].get("action_id"), str):
            raise _error("An Immortal Art has no single executable Action (RAW-191).", details={"immortal_art_id": art_id, "matches": len(matches)})
        result.append({"art": deepcopy(dict(art)), "action": deepcopy(dict(matches[0]))})
    return sorted(result, key=lambda row: (row["art"]["cl_created"], row["art"]["immortal_art_id"]))


def constructed_immortal_art_binding(root: Path | str) -> dict[str, Any]:
    """Summarize the checked Arts for a reviewed binding or receipt."""

    arts = [
        {
            "immortal_art_id": row["art"]["immortal_art_id"],
            "name": row["art"]["name"],
            "cl_created": row["art"]["cl_created"],
            "action_id": row["action"]["action_id"],
            "art_sha256": sha256_json(row["art"]),
            "action_sha256": sha256_json(row["action"]),
        }
        for row in read_constructed_immortal_arts(root)
    ]
    binding = {"schema_version": CONSTRUCTED_IMMORTAL_ART_BINDING_SCHEMA, "arts": arts}
    binding["binding_sha256"] = sha256_json(binding)
    return binding


def _text_list(values: Any) -> list[str]:
    return [value.strip() for value in values if isinstance(value, str) and value.strip()] if isinstance(values, list) else []


def compiler_immortal_art_row(art: Mapping[str, Any], action: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Translate one checked Art into the pinned compiler's ledger row and allocation."""

    art_id = art["immortal_art_id"]
    surface = art.get("action_surface") if isinstance(art.get("action_surface"), Mapping) else {}
    aspect = art["dao_aspect"]
    aspect_name = aspect.get("display_name")
    if not isinstance(aspect_name, str) or not aspect_name.strip():
        raise _error("An Immortal Art Dao Aspect has no display name.", details={"immortal_art_id": art_id})
    limitations = _text_list(surface.get("limits"))
    frequency = surface.get("trigger_frequency")
    if isinstance(frequency, str) and frequency.strip():
        limitations.append(f"Trigger frequency: {frequency.strip()}.")
    hooks = [
        f"{label}: {value.strip()}"
        for label, value in (("Trigger", surface.get("trigger")), ("Counterplay", surface.get("counterplay")), ("Cleanup", surface.get("cleanup")))
        if isinstance(value, str) and value.strip()
    ]
    if not limitations or not hooks:
        raise _error("An Immortal Art action surface has no printed limits or adjudication text.", details={"immortal_art_id": art_id})
    summary_parts = [
        str(surface.get(key)).strip()
        for key in ("activation", "range", "target", "duration")
        if isinstance(surface.get(key), str) and str(surface.get(key)).strip()
    ]
    execution_summary = "; ".join([*summary_parts, f"{art['activation_cp']} {surface.get('resource_name') or 'CP'}"])
    attempts = art["refinement"]["attempts"]
    acquisition_record = (
        f"Constructed at CL {art['cl_created']} ({art['realm']}) from {art.get('source_record_id')} "
        f"with the {aspect_name} Dao Aspect; Refinement DC {art['refinement_dc']} met after "
        f"{len(attempts)} attempt(s); {art['research_days']} research days and {art['material_cost_gp']} gp materials."
    )
    allocation_id = "allocation.immortal_art." + sha256_json({"immortal_art_id": art_id, "event_id": art.get("acquisition_event_id")})[:32]
    row = {
        "immortal_art_id": art_id,
        "record_id": art_id,
        "name": art["name"],
        "dao_aspect": aspect_name.strip(),
        "status": "learned",
        "evolution_state": "initial expression",
        "classification": IMMORTAL_ART_CLASSIFICATION,
        "allocation_id": allocation_id,
        "gained_at_cl": art["cl_created"],
        "cl": art["cl_created"],
        "realm": art["realm"],
        "action_ids": [action["action_id"]],
        "limitations": limitations,
        "behavior_hooks": hooks,
        "execution_summary": execution_summary,
        "acquisition_record": acquisition_record,
        "source_packet_ids": list(art["source_packet_ids"]),
        "constructed_art_sha256": sha256_json(art),
    }
    allocation = {
        "allocation_id": allocation_id,
        "channel": IMMORTAL_ART_CLASSIFICATION,
        "grant_type": IMMORTAL_ART_CLASSIFICATION,
        "grant_id": art_id,
        "immortal_art_id": art_id,
        "name": art["name"],
        "cl": art["cl_created"],
        "at_cl": art["cl_created"],
        "realm": art["realm"],
        "slot_cost": 0,
        "consumes_talent_slot": False,
        "authority": "constructed_immortal_art",
        "source_packet_ids": list(art["source_packet_ids"]),
    }
    return row, allocation


def tagged_immortal_action(action: Mapping[str, Any], art_id: str) -> dict[str, Any]:
    tagged = deepcopy(dict(action))
    tagged["classification"] = IMMORTAL_ART_CLASSIFICATION
    tagged["immortal_art_id"] = art_id
    return tagged


def translate_constructed_immortal_arts(workspace: Path | str) -> dict[str, Any]:
    """Rewrite a copied workspace so the pinned compiler sees each checked Art.

    Only the materializer's private copy is changed: ledger Immortal Art rows
    become compiler rows, each Art gains its zero-cost allocation at the CL it
    was created, and its existing Action is tagged and listed in the ledger.
    """

    root = Path(workspace)
    checked = read_constructed_immortal_arts(root)
    binding = constructed_immortal_art_binding(root)
    ledger = _read(root, _LEDGER_PATH)
    levels = (ledger.get("advancement") or {}).get("levels") if isinstance(ledger.get("advancement"), Mapping) else None
    if not isinstance(levels, list):
        raise _error("The copied ledger has no advancement levels.")
    rows: list[dict[str, Any]] = []
    allocations_by_cl: dict[str, list[dict[str, Any]]] = {}
    tagged_by_id: dict[str, dict[str, Any]] = {}
    for item in checked:
        art, action = item["art"], item["action"]
        row, allocation = compiler_immortal_art_row(art, action)
        rows.append(row)
        level_rows = [level for level in levels if isinstance(level, Mapping) and level.get("cl") == art["cl_created"]]
        if len(level_rows) != 1:
            raise _error("The copied ledger has no single advancement row for an Art's CL.", details={"cl": art["cl_created"]})
        existing = level_rows[0].get("allocations")
        if existing is None:
            existing = []
        if not isinstance(existing, list) or any(isinstance(entry, Mapping) and entry.get("allocation_id") == allocation["allocation_id"] for entry in existing):
            raise _error("The copied advancement allocations are malformed or already translated.", details={"cl": art["cl_created"]})
        level_rows[0]["allocations"] = [*existing, allocation]
        allocations_by_cl.setdefault(str(art["cl_created"]), []).append(allocation)
        tagged_by_id[action["action_id"]] = tagged_immortal_action(action, art["immortal_art_id"])

    ledger["immortal_arts"] = rows
    ledger.pop("immortal_arts_none_state", None)
    ledger_actions = ledger.get("actions")
    ledger_actions = [] if ledger_actions is None else ledger_actions
    if not isinstance(ledger_actions, list):
        raise _error("The copied ledger actions field is neither absent nor a list.")
    present = {row.get("action_id") for row in ledger_actions if isinstance(row, Mapping)}
    ledger_actions = [tagged_by_id.get(row.get("action_id"), row) if isinstance(row, Mapping) else row for row in ledger_actions]
    ledger_actions.extend(tagged for action_id, tagged in tagged_by_id.items() if action_id not in present)
    ledger["actions"] = ledger_actions
    _write(root, _LEDGER_PATH, ledger)
    for relative in _SURFACE_PATHS:
        document = _read(root, relative)
        document["actions"] = [tagged_by_id.get(row.get("action_id"), row) if isinstance(row, Mapping) else row for row in document["actions"]]
        _write(root, relative, document)
    return {
        "binding": binding,
        "arts": rows,
        "allocations_by_cl": allocations_by_cl,
        "action_ids": sorted(tagged_by_id),
        "actions": [tagged_by_id[action_id] for action_id in sorted(tagged_by_id)],
    }
