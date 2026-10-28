"""Finite source-preserving concepts for the local-AI Forge selection step.

This contract proposes designs, never acquisitions. Construction and Stage 2
still verify the actual held sources, CL, cost, capacity and creation record.
"""
from copy import deepcopy

from app.core import FoundryError, sha256_json


DESIGNS = {
    "air.downburst.ignore_resistance": {
        "minimum_cl": 10,
        "cue": "Unbroken Downburst: Action, 4 CP; grounded area control; ignores Resistance",
        "concept": {"generator_version": 3, "name": "Unbroken Downburst", "intent": "Ground flying threats with the published Downburst effect and Ignore Resistance.", "primary_talent_id": "TAL_AIR_DOWNBURST_SEAL", "base_form": "burst", "secondary_talent_ids": [], "augment_ids": ["ignore_resistance"], "drawback_ids": []},
    },
    "air.gale.ignore_resistance": {
        "minimum_cl": 15,
        "cue": "Unbroken Gale: Action, 4 CP; long-line damage and displacement; ignores Resistance",
        "concept": {"generator_version": 3, "name": "Unbroken Gale", "intent": "Open a retreat corridor with the published Heaven-Splitting Gale effect and Ignore Resistance.", "primary_talent_id": "TAL_AIR_HEAVEN_SPLITTING_GALE", "base_form": "line", "secondary_talent_ids": [], "augment_ids": ["ignore_resistance"], "drawback_ids": []},
    },
}


def explicit_forging_contract():
    return {"schema": "TianxiaFoundry.ExplicitForgingSelection.v1", "designs": deepcopy(DESIGNS), "maximum_choices": 2, "grants_acquisition": False}


def has_explicit_forging_contract(envelope):
    if not isinstance(envelope, dict) or "explicit_forging_contract" not in envelope:
        return False
    if envelope["explicit_forging_contract"] != explicit_forging_contract():
        raise FoundryError("CG1_EXPLICIT_FORGING_CONTRACT_INVALID", "The frozen Forge design contract is not the supported source-preserving contract.")
    return True


def validate_explicit_concepts(value):
    allowed = [row["concept"] for row in DESIGNS.values()]
    if not isinstance(value, list) or len(value) > 2 or any(row not in allowed for row in value) or len({row["primary_talent_id"] for row in value}) != len(value):
        raise FoundryError("CG1_EXPLICIT_FORGING_CONCEPT_INVALID", "Forge choices must be distinct exact designs from the sealed finite contract.")
    return deepcopy(value)


def concepts_for_design_ids(ids):
    if not isinstance(ids, list) or any(not isinstance(key, str) or key not in DESIGNS for key in ids):
        raise FoundryError("CG1_EXPLICIT_FORGING_CONCEPT_INVALID", "The committed Forge choice has no declared design identity.")
    return validate_explicit_concepts([DESIGNS[key]["concept"] for key in ids])


def normalize_required_design_ids(value=None, revision_request=None):
    """One exact, finite owner constraint; omission keeps old requests unchanged."""
    brief = (revision_request or {}).get("brief") or {}
    revised = brief.get("required_forged_design_ids")
    for candidate in (value, revised):
        if candidate is not None and (
            not isinstance(candidate, list) or len(candidate) > 2
            or any(not isinstance(key, str) or key not in DESIGNS for key in candidate)
            or len(set(candidate)) != len(candidate)
        ):
            raise FoundryError("CG1_REQUIRED_FORGED_DESIGNS_INVALID", "Require at most two distinct exact Forge design IDs.", status_code=422)
    if value is not None and revised is not None and set(value) != set(revised):
        raise FoundryError("CG1_REQUIRED_FORGED_DESIGNS_CONFLICT", "Start and revision brief disagree on required Forge designs.", status_code=422)
    chosen = value if value is not None else revised
    return sorted(chosen) if chosen else []


def required_design_ids(envelope, request=None):
    required = normalize_required_design_ids(envelope.get("required_forged_design_ids"))
    if required:
        if not has_explicit_forging_contract(envelope):
            raise FoundryError("CG1_REQUIRED_FORGED_DESIGNS_INVALID", "Required designs need the frozen Forge contract.")
        # The walk adds this derived projection in memory after sealing. It
        # is not part of the persisted envelope; all owner fields still are.
        unsigned = {k: v for k, v in envelope.items() if k != "envelope_sha256"}
        frozen = (request or {}).get("delegated_choice_envelope")
        if frozen is not None and "linear_provider_payload" not in frozen:
            unsigned.pop("linear_provider_payload", None)
        if sha256_json(unsigned) != envelope.get("envelope_sha256"):
            raise FoundryError("CG1_DELEGATED_ENVELOPE_TAMPERED", "The required Forge envelope no longer matches its sealed hash.")
    if request is not None and required != normalize_required_design_ids(request.get("required_forged_design_ids"), request.get("revision_request")):
        raise FoundryError("CG1_REQUIRED_FORGED_DESIGNS_CONFLICT", "The request and frozen Forge requirement differ.")
    return required


def validate_required_design_selection(envelope, chosen, *, complete, request=None):
    required = required_design_ids(envelope, request)
    concepts_for_design_ids(chosen)
    missing = [key for key in required if key not in chosen]
    if complete and missing:
        raise FoundryError("DCC_REQUIRED_FORGED_DESIGNS_INCOMPLETE", "Required Forge designs must be selected before finishing.", details={"missing_design_ids": missing})
    return missing


def validate_required_design_concepts(envelope, concepts):
    required = required_design_ids(envelope)
    if required:
        actual = validate_explicit_concepts(concepts)
        missing = [key for key in required if DESIGNS[key]["concept"] not in actual]
        if missing:
            raise FoundryError("DCC_REQUIRED_FORGED_DESIGNS_INCOMPLETE", "The assembled intent omits required Forge designs.", details={"missing_design_ids": missing})
