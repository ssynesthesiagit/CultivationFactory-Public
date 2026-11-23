#!/usr/bin/env python3
"""Offline forged-design audit. Reads supplied exports only; never live state.

Representative builds enumerate every form and every Realm-legal augment
subset under the Complexity cap, with either or both of two known sources.
Drawback discounts do not introduce rolls; each possible final cost is checked
by the validator's monotone price threshold (the undiscounted price is worst).
Use --owner-exports for read-only portable-character COPIES, never live state.
JSON goes to stdout so callers choose a private evidence location.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from itertools import combinations
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import FoundryError, sha256_json
from character_creation.constructed_arts.forge_design import POLICY, design_issues
from character_creation.constructed_arts.forged_technique import construct_forged_technique, design_mechanics
from character_creation.constructed_arts.forging_authority import load_forging_authority, realm_for_cl, realm_at_least
from combat.forged import mechanic_for


def score(mechanic):
    issues = design_issues(mechanic) if mechanic else ["unportable_primary_effect"]
    return {"score": max(0, 100 - 20 * len(issues)), "issues": issues}


def audit_generated(cls=(5, 10, 20)):
    authority = load_forging_authority(ROOT)
    mechanics = design_mechanics()
    texts = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    ids = ["AIR_BASE_WIND_LASH", "tianxia.talent.poison.coated_weapon"]
    talents = [{"talent_id": tid, "sphere_id": mechanics[tid]["sphere_id"],
                "display_name": mechanics[tid]["name"], "published_text": texts[tid],
                "record_hash": sha256_json(mechanics[tid]),
                "source": {"source_id": "offline-audit", "path": mechanics[tid]["source"]["path"],
                           "anchor": "offline-audit", "source_hash": mechanics[tid]["source"]["file_sha256"]}}
               for tid in ids]
    counts = Counter()
    rejected = Counter()
    failures = []
    scores = Counter()
    for cl in cls:
        realm = realm_for_cl(cl)
        cap = next(r["maximum_complexity"] for r in authority["realm_complexity_limits"] if r["realm"] == realm)
        augments = [a for a in authority["augments"] if realm_at_least(realm, a["minimum_realm"])]
        for form in authority["base_forms"]:
            if form.get("starting_cp") is None:
                continue
            for count in range(len(augments) + 1):
                for subset in combinations(augments, count):
                    price = sum(a["complexity"] for a in subset) + form["complexity"]
                    if price > cap:
                        continue
                    for primary in ids:
                        for secondary in ([], [i for i in ids if i != primary]):
                            if price + len(secondary) > cap:
                                continue
                            request = {"seed": "forge-design-audit", "project_id": "offline-audit", "cl": cl,
                                       "pb": 3 if cl == 5 else 4 if cl == 10 else 6,
                                       "path_id": "tianxia.path.body_refining", "key_ability": "CON",
                                       "known_spheres": [{"sphere_id": t["sphere_id"], "display_name": t["sphere_id"].rsplit(".", 1)[-1]} for t in talents],
                                       "known_talents": talents,
                                       "concept": {"base_form": form["form_id"], "primary_talent_id": primary,
                                                   "secondary_talent_ids": secondary,
                                                   "augment_ids": [a["augment_id"] for a in subset], "drawback_ids": []}}
                            counts["attempted"] += 1
                            try:
                                technique = construct_forged_technique(authority, request, generator_version=3)
                            except FoundryError as exc:
                                counts["rejected"] += 1
                                rejected[exc.code + ":" + ",".join((exc.details or {}).get("issues", []))] += 1
                                continue
                            result = score(mechanic_for(technique, mechanics))
                            scores[str(result["score"])] += 1
                            counts["produced"] += 1
                            if result["issues"]:
                                failures.append({"name": technique["name"], **result})
    return {"domain": {"cl": list(cls), "known_talents": ids, "forms": "all fixed-price forms",
                       "augments": "all legal subsets", "drawbacks": "none; maximum price is conservative",
                       "limitations": "Two representative source talents; not every sphere or source-specific table choice."},
            **counts, "scores": dict(scores), "rejections": dict(rejected), "failures": failures}


def techniques(value):
    if isinstance(value, dict):
        if "primary_sphere_effect" in value and "base_form" in value:
            yield value
        else:
            for child in value.values():
                yield from techniques(child)
    elif isinstance(value, list):
        for child in value:
            yield from techniques(child)


def alternative_design(technique, sheet, mechanics):
    """Offer an explicitly different, source-known design when flattening fails.

    This is a proposal only. It can change form/Augments and uses only sources
    named on the copied sheet. Prices and restrictions are re-derived, never
    edited on the owner's original record.
    """
    authority = load_forging_authority(ROOT)
    texts = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    ids = [technique["primary_sphere_effect"]["talent_id"],
           *[r["talent_id"] for r in technique.get("secondary_sphere_effects", [])],
           *(sheet.get("spheres_and_talents") or {}).get("learned_talent_record_ids", [])]
    ids = list(dict.fromkeys(tid for tid in ids if tid in mechanics and tid in texts))
    talents = [{"talent_id": tid, "sphere_id": mechanics[tid].get("sphere_id"),
                "display_name": mechanics[tid]["name"], "published_text": texts[tid],
                "record_hash": sha256_json(mechanics[tid]),
                "source": {"source_id": "offline-audit", "path": mechanics[tid]["source"]["path"],
                           "anchor": "offline-audit", "source_hash": mechanics[tid]["source"]["file_sha256"]}}
               for tid in ids if mechanics[tid].get("sphere_id") and mechanics[tid].get("source", {}).get("file_sha256")]
    if not talents:
        return None
    cl = int((sheet.get("identity") or {}).get("cultivation_level") or technique.get("cl_created") or 5)
    spheres = sorted({t["sphere_id"] for t in talents})
    for source in talents:
        for form in dict.fromkeys([technique["base_form"]["form_id"], "projection", "ward", "movement"]):
            for augments in ([], ["major_condition"], ["severe_hindrance"]):
                request = {"seed": "offline-refresh-proposal", "project_id": "offline-audit", "cl": cl,
                           "pb": min(6, 2 + (cl - 1) // 4), "path_id": "tianxia.path.body_refining", "key_ability": "CON",
                           "known_spheres": [{"sphere_id": sid, "display_name": sid.rsplit(".", 1)[-1]} for sid in spheres],
                           "known_talents": talents, "concept": {"name": technique.get("name") or "Refreshed Technique",
                           "primary_talent_id": source["talent_id"], "base_form": form, "secondary_talent_ids": [],
                           "augment_ids": augments, "drawback_ids": []}}
                try:
                    proposal = construct_forged_technique(authority, request, generator_version=3)
                except FoundryError:
                    continue
                mechanic = mechanic_for(proposal, mechanics)
                if mechanic and not design_issues(mechanic):
                    return {"primary_talent_id": source["talent_id"], "base_form": form,
                            "augments": augments, "cp_cost": proposal["cp_cost"]["final"],
                            "mechanic": mechanic,
                            "changes": "Replaces the old design; removes secondary effects and Drawbacks. Owner review required before any refresh."}
    return None


def audit_exports(paths):
    mechanics = design_mechanics()
    found, seen, files = [], set(), 0
    for root in paths:
        root = Path(root).resolve()
        if ".local/state" in str(root) or root == Path.home():
            raise ValueError("Use a specific read-only export copy, never live state or a home directory.")
        candidates = sorted(root.rglob("current.zip")) if root.is_dir() else [root]
        for path in candidates:
            if ".local/state" in str(path.resolve()):
                raise ValueError("An export resolves into live state.")
            if path.suffix == ".zip":
                with zipfile.ZipFile(path) as archive:
                    docs = [json.loads(archive.read(name)) for name in archive.namelist()
                            if name.endswith("Tianxia_Owner_Character_Sheet_v1.json")]
            else:
                docs = [json.loads(path.read_text())]
            files += 1
            for doc in docs:
                for technique in techniques(doc):
                    key = sha256_json(technique)
                    if key in seen:
                        continue
                    seen.add(key)
                    before = mechanic_for(technique, mechanics)
                    result = score(before)
                    if result["issues"]:
                        suggestion = deepcopy(technique)
                        suggestion["design_policy"] = POLICY
                        after = mechanic_for(suggestion, mechanics)
                        remaining = score(after)["issues"]
                        alternative = alternative_design(technique, doc, mechanics) if remaining else None
                        found.append({"export": str(path), "technique": technique.get("name"), **result,
                                      "suggested_mechanic": after,
                                      "suggestion_issues": remaining,
                                      "alternative_design": alternative,
                                      "next_action": "Owner may refresh only after reviewing the suggestion; remaining issues require a different source, form or Augment."})
    return {"export_files": files, "unique_techniques": len(seen), "flagged_count": len(found), "flagged": found}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-exports", action="append", default=[])
    args = parser.parse_args()
    generated = audit_generated()
    existing = audit_exports(args.owner_exports)
    print(json.dumps({"generated": generated, "existing": existing}, indent=2))
    return int(bool(generated["failures"]))


if __name__ == "__main__":
    raise SystemExit(main())
