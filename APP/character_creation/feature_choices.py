"""Source-bound build choices shared by creation clients and table level acquisition.

This contract records acquisition decisions, not combat effects. Choices and
derived grants are authored in rules data; callers cannot supply derived values.
"""
import copy
import json
from functools import lru_cache
from pathlib import Path

from app.core import FoundryError


@lru_cache(maxsize=1)
def contracts():
    return json.loads((Path(__file__).resolve().parents[1] / "rules/feature_build_choices.json").read_text())


def menu(features):
    return [{"feature_id": row["canonical_id"], "name": row["display_name"], **copy.deepcopy(contracts()[row["canonical_id"]])}
            for row in features if row["canonical_id"] in contracts()]


def resolve(features, selections):
    return _resolve_menu(menu(features), selections, error_code="TABLETOP_LEVEL_NOT_LEGAL")


def repeatable(record_id):
    """Only a source-authored repeatable acquisition can bypass known-talent gates."""
    return bool((contracts().get(record_id, {}).get("acquisition") or {}).get("repeatable"))


def acquisition_menu(sheet, record_id=None):
    """The same source-bound menu for Sphere gains, talent gains and missing choices.

    Acquisition data names the owning Sphere/talent and the sheet list it grants.
    Pending choices are counted from ownership, never inferred from combat options.
    One pending choice is offered at a time so repeated selections must differ.
    """
    block = sheet.get("spheres_and_talents") or {}
    spheres = block.get("sphere_record_ids") or []
    learned = block.get("learned_talent_record_ids") or []
    trained = block.get("trained_choices") or []
    due, recorded = {}, {}
    for feature_id, contract in contracts().items():
        acquisition = contract.get("acquisition")
        if not acquisition:
            continue
        field = acquisition["field"]
        aliases = {value.casefold(): o["id"] for o in contract["options"] for value in (o["id"], o["name"])}
        recorded[field] = [aliases.get(str(v).casefold(), v) for v in block.get(field) or []]
        if record_id is not None:
            count = int(record_id in (feature_id, acquisition.get("sphere_id"), acquisition.get("talent_id")))
        elif acquisition.get("sphere_id"):
            count = int(acquisition["sphere_id"] in spheres)
        else:
            tid = acquisition["talent_id"]
            # Creation's card index is deduplicated; its training ledger retains
            # repeated selections. Table growth retains repeated learned IDs.
            count = max(learned.count(tid), sum(r.get("record_id") == tid for r in trained))
            if block.get("background_talent_record_id") == tid and count == 0:
                count = 1
        due.setdefault(field, []).extend([feature_id] * count)
    result = []
    for field, features in due.items():
        if record_id is None:
            features = features[len(recorded[field]):len(recorded[field]) + 1]
        for feature_id in features:
            contract = contracts()[feature_id]
            row, = menu([{"canonical_id": feature_id, "display_name": contract["name"]}])
            row["options"] = [o for o in row["options"]
                              if not set(o["grants"][field]).intersection(recorded[field])]
            if row["options"] or record_id is not None:
                result.append(row)
    return result


def pending_for_acquisition(sheet, record_id):
    """Only an unresolved earlier choice in the same grant list blocks its next gain."""
    fields = {r["acquisition"]["field"] for r in acquisition_menu(sheet, record_id)}
    return any(r["acquisition"]["field"] in fields for r in acquisition_menu(sheet))


def resolve_acquisition(sheet, record_id, selections):
    """Validate a new gain with the feature resolver; return only offered answers."""
    rows = acquisition_menu(sheet, record_id)
    # Reuse the resolver's exact-choice validation with the filtered options.
    _resolve_menu(rows, selections)
    return [{"feature_id": row["feature_id"], "choice": selections[row["feature_id"]]} for row in rows]


def _resolve_menu(rows, selections, *, error_code=None):
    if set(selections) != {r["feature_id"] for r in rows}:
        raise FoundryError(error_code or "FEATURE_CHOICE_REQUIRED", "Choose each required learning option before recording this gain.", status_code=409)
    out = {}
    for row in rows:
        option = next((o for o in row["options"] if o["id"] == selections[row["feature_id"]]), None)
        if option is None:
            raise FoundryError(error_code or "FEATURE_CHOICE_INVALID", "Choose an offered, different option for " + row["name"] + ".", status_code=409)
        out[row["feature_id"]] = {"choice": option["id"], **copy.deepcopy(option["grants"])}
    return out


def project_acquisitions(sheet, answers=()):
    """Project validated acquisition history into its sole character-owned field.

    Used by the creation sheet producer and table growth replay. No combat option
    or separate feature-choice store is consulted to decide what is known.
    """
    block = sheet.setdefault("spheres_and_talents", {})
    for answer in answers:
        feature_id = answer["feature_id"]
        rows = [r for r in acquisition_menu(sheet) if r["feature_id"] == feature_id]
        grant = _resolve_menu(rows, {feature_id: answer["choice"]})[feature_id]
        field = contracts()[feature_id]["acquisition"]["field"]
        block.setdefault(field, []).extend(grant[field])
    pending = acquisition_menu(sheet)
    known = known_acquisitions(sheet)
    if pending or known or "pending_feature_choices" in block:
        for row in pending:
            block.setdefault(row["acquisition"]["field"], [])
        block["pending_feature_choices"] = pending
        block["known_feature_choices"] = known
    return sheet


def known_acquisitions(sheet):
    """Plain names for recorded learning grants, grouped by their source-owned field."""
    block = sheet.get("spheres_and_talents") or {}
    seen, labels = set(), []
    for contract in contracts().values():
        acquisition = contract.get("acquisition")
        if not acquisition or acquisition["field"] in seen:
            continue
        field = acquisition["field"]
        seen.add(field)
        names = {v.casefold(): o["name"] for o in contract["options"] for v in (o["id"], o["name"])}
        labels.extend(names[str(v).casefold()] for v in block.get(field) or [] if str(v).casefold() in names)
    return labels
