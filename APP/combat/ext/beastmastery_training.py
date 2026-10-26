"""Beastmastery Training acquisition and its non-stacking skill projection.

Printed source BEASTMASTERY_BASE_BEASTMASTERY_TRAINING is pinned in the native
regressions. Native Grow acquisition uses Learning/Life's public hooks from
commit a932ac6d and prerequisite query corrections from a210c780. A receipt
captures the pre-learning rank, zero-cost talent grants and the owner's package
choice; cold sheet projection grants only those packages. Extra Beastmastery
Package consumes its own validated choice, including when chosen as a free
talent. The original compile hook remains for imported sheets carrying Training.
Package mechanics remain in their existing providers (mounts, tamer).
"""

from __future__ import annotations

from typing import Any

from . import hook

TRAINING = "BEASTMASTERY_BASE_BEASTMASTERY_TRAINING"
SKILL = "Animal Handling"
ABILITY = "WIS"
SOURCE_LABEL = "Beastmastery Training"

SPHERE = "tianxia.sphere.beastmastery"
RIDER = "BEASTMASTERY_BASE_RIDER_PACKAGE"
TAMER = "BEASTMASTERY_BASE_TAMER_PACKAGE"
PACKAGES = {RIDER: "Rider Package", TAMER: "Tamer Package"}
EXTRA = "TAL_BEASTMASTERY_EXTRA_BEASTMASTERY_PACKAGE"


def _skill_rows(sheet):
    import json
    rows = (sheet.get("ability_scores_and_statistics") or {}).get("skills") or []
    return json.loads(rows) if isinstance(rows, str) else rows


def _prior_rank(sheet):
    from ..ability_checks import proficiency_rank
    rows = [r for r in _skill_rows(sheet) if str(r.get("skill")).casefold() == SKILL.casefold()]
    if not rows:
        return 0
    ranks = [proficiency_rank(r) for r in rows]
    return None if None in ranks else max(ranks)


@hook("learning_choices")
def training_choices(sheet, record_id, talents, draft=None):
    """Training grants use the public native learning contract, never fight flags."""
    from .. import table_advance
    have = table_advance.known(sheet)
    draft = draft or {}
    if record_id == EXTRA:
        if SPHERE not in have["spheres"]:
            return None
        return [{"id": "package", "label": "Extra Beastmastery Package: gain the package you do not possess",
                 "options": [{"id": p, "name": n} for p, n in PACKAGES.items() if p not in have["talents"]]}]
    if record_id != SPHERE or SPHERE in have["spheres"]:
        return None
    result = []
    # Learning/Life's public prerequisite evaluator is shared by ordinary,
    # free and conditional talents. Source-specific eligibility stays here.
    have["spheres"].add(SPHERE)
    have["talents"].add(TRAINING)
    package = draft.get("package")
    if package in PACKAGES:
        have["talents"].add(package)
    result.append({"id": "package", "label": "Beastmastery Training: choose one free package",
                   "options": [{"id": p, "name": n} for p, n in PACKAGES.items()]})
    for key, label in [("free", "New Sphere: choose its normal free first Beastmastery talent"),
                       *([("bonus", "Beastmastery Training: already proficient — choose a free bonus talent")]
                         if (_prior_rank(sheet) or 0) >= 1 else [])]:
        options = []
        for row in talents:
            tid = row.get("canonical_talent_id")
            if (row.get("owning_canonical_sphere_id") == SPHERE and tid not in have["talents"]
                    and not row.get("background_only") and not row.get("automatic_grant")
                    and table_advance.talent_status(row, have)["legal"]):
                options.append({"id": tid, "name": row["display_name"]})
        result.append({"id": key, "label": label, "options": options})
        if draft.get(key) in {o["id"] for o in options}:
            have["talents"].add(draft[key])
            # Extra Package is itself the free talent in this branch. Its
            # validated package choice is available before dependent options
            # (notably the conditional bonus talent) are evaluated.
            if draft[key] == EXTRA and draft.get("extra_package") in PACKAGES:
                have["talents"].add(draft["extra_package"])
    if EXTRA in (draft.get("free"), draft.get("bonus")):
        result.append({"id": "extra_package", "label": "Extra Beastmastery Package: gain the other package",
                       "options": [{"id": p, "name": n} for p, n in PACKAGES.items() if p != package]})
    return result


@hook("learning_receipt")
def training_receipt(sheet, kind, record_id, selected, talents):
    import hashlib
    import json
    from pathlib import Path
    from ..tabletop import TabletopError
    if (kind, record_id) not in (("sphere", SPHERE), ("talent", EXTRA)):
        return None
    offered = training_choices(sheet, record_id, talents, selected) or []
    if not offered or set(selected) != {r["id"] for r in offered}:
        raise TabletopError("LEARNING_CHOICES_REQUIRED", "Choose each Beastmastery training benefit before learning it.", 422)
    for row in offered:
        if selected[row["id"]] not in {o["id"] for o in row["options"]}:
            raise TabletopError("LEARNING_CHOICE_INVALID", row["label"] + ": that choice is not eligible.", 422)
    grants = [selected[k] for k in ("free", "bonus") if k in selected]
    if len(grants) != len(set(grants)):
        raise TabletopError("LEARNING_DUPLICATE_TALENT", "Choose distinct talents for the two free benefits.", 422)
    rules = json.loads((Path(__file__).resolve().parents[2] / "authority/typed_mechanics/rules_text.json").read_text())
    source = TRAINING if record_id == SPHERE else "TAL_BEASTMASTERY_EXTRA_BEASTMASTERY_PACKAGE"
    return {"source": source, "source_sha256": hashlib.sha256(rules[source].encode()).hexdigest(),
            "record_id": record_id, "choices": dict(selected), "talents": grants,
            "packages": [selected[k] for k in ("package", "extra_package") if k in selected],
            "skill_granted": int(record_id == SPHERE and _prior_rank(sheet) == 0),
            "conditional_bonus_earned": int("bonus" in selected), "slot_cost": 0,
            "gm_note": ("Animal Handling proficiency rank was not recorded; proficiency and the "
                        "already-proficient bonus talent were not granted or assumed."
                        if record_id == SPHERE and _prior_rank(sheet) is None else None),
            "before_sheet_sha256": hashlib.sha256(json.dumps(sheet, sort_keys=True).encode()).hexdigest()}


@hook("learning_projection")
def training_projection(sheet, advancement):
    """Replay acquisition receipts; a later proficiency cannot earn another bonus."""
    import copy
    receipts = [r for kind, rid in (("spheres", SPHERE), ("talents", EXTRA))
                for acquisition in advancement[kind] if acquisition.get("id") == rid
                for r in acquisition.get("learning_receipts", []) if r.get("record_id") == rid
                and r.get("source") == (TRAINING if rid == SPHERE else "TAL_BEASTMASTERY_EXTRA_BEASTMASTERY_PACKAGE")]
    if not receipts:
        return sheet
    out = copy.deepcopy(sheet)
    block = out["spheres_and_talents"]
    if SPHERE not in block.get("sphere_record_ids", []):
        return sheet
    automatic = block.setdefault("automatic_sphere_component_record_ids", [])
    # The generic base index enumerates both printed package rows. A validated
    # choice receipt, not their base_ability classification, determines ownership.
    if any(r["record_id"] == SPHERE for r in receipts):
        automatic[:] = [p for p in automatic if p not in PACKAGES]
    learned = block.setdefault("learned_talent_record_ids", [])
    for receipt in receipts:
        automatic.extend(p for p in receipt["packages"] if p not in automatic)
        learned.extend(t for t in receipt["talents"] if t not in learned)
        if receipt["skill_granted"]:
            stats = out["ability_scores_and_statistics"]
            rows = _skill_rows(out)
            existing = next((r for r in rows if str(r.get("skill")).casefold() == SKILL.casefold()), None)
            if (_prior_rank(out) or 0) < 1:
                abilities = stats.get("abilities") or []
                if isinstance(abilities, str):
                    import json
                    abilities = json.loads(abilities)
                mod = next((int(r["modifier"]) for r in abilities if r["ability"] == "WIS"), 0)
                pb = int(out["identity"]["proficiency_bonus"])
                bonus = int(existing.get("bonus", mod) if existing else mod) + pb
                if existing:
                    rows.remove(existing)
                rows.append({"skill": SKILL, "ability": ABILITY, "bonus": bonus,
                             "proficiency_multiplier": 1, "proficiency": "proficient", "sources": [SOURCE_LABEL]})
                stats["skills"] = rows
        if receipt["record_id"] == SPHERE:
            # The engine uses canonical skill names. Preserve an existing
            # proficient/expert total while normalizing its spelling once.
            rows = _skill_rows(out)
            normalized = False
            for row in rows:
                if str(row.get("skill")).casefold() == SKILL.casefold():
                    row["skill"] = SKILL
                    normalized = True
            if normalized:
                # JSON-encoded legacy skills parse to a temporary list; write
                # the canonicalized representation back for cold reload.
                out["ability_scores_and_statistics"]["skills"] = rows
    out.setdefault("learning_receipts", []).extend(copy.deepcopy(receipts))
    return out


@hook("advancement_options")
def training_labels(options, sheet, talents):
    import copy
    names = {r["canonical_talent_id"]: r["display_name"] for r in talents}
    out = copy.deepcopy(options)
    for kind in ("spheres", "talents"):
        for acquisition in out["added"][kind]:
            labels = []
            for receipt in acquisition.get("learning_receipts", []):
                if receipt.get("source") not in (TRAINING, EXTRA):
                    continue
                if receipt["record_id"] == SPHERE:
                    if receipt.get("gm_note"):
                        labels.append("GM note: " + receipt["gm_note"])
                    else:
                        labels.append("Proficiency in Wisdom (Animal Handling)")
                labels.extend(PACKAGES[p] + " (free package)" for p in receipt["packages"])
                labels.extend(names.get(t, "Learned Beastmastery talent") + " (free talent)" for t in receipt["talents"])
            if labels:
                acquisition["learning_benefit_labels"] = labels
    return out


@hook("compile_skill_bonuses")
def beastmastery_training_proficiency(info: dict[str, Any]) -> dict[str, Any] | None:
    """Add the printed Wisdom (Animal Handling) proficiency to a new bundle.

    Returns None for a character that does not own the row, and for a sheet
    that already records Animal Handling proficient or better, so unrelated
    characters, sheets and saved fights are untouched. No feature is claimed as
    handled here: the other clauses are build grants this
    module delivers through its separate native acquisition hooks.
    """
    owned = tuple(info.get("owned_ids") or ())
    if TRAINING not in owned:
        return None
    mechanics = info.get("mechanics") or {}
    if any(effect.get("type") == "general_skill_expertise" and str(effect.get("skill")).casefold() == SKILL.casefold()
           for source in owned for effect in ((mechanics.get(source) or {}).get("effects") or [])
           if isinstance(effect, dict)):
        # Another registered projection (combat/ext/general_flight_skills,
        # compile_skill_bonuses) prints Expertise in this very skill for this
        # character. Expertise already contains proficiency, and that provider
        # preserves independent adjustments this one cannot see; its reply owns
        # the row whichever registration order the hook list ends up in.
        return None
    rows = list(info.get("skills") or [])
    by_name = {str(row.get("skill")).casefold(): row for row in rows
               if isinstance(row, dict) and row.get("skill")}
    existing = by_name.get(SKILL.casefold())
    pb = int(info.get("pb") or 0)
    if existing is None:
        # A sheet that lists no Animal Handling row at all: the printed grant is
        # the ability modifier plus the Proficiency Bonus, nothing inferred.
        return {"skills": [{"skill": SKILL, "ability": ABILITY,
                     "bonus": int((info.get("mods") or {}).get(ABILITY, 0)) + pb,
                     "proficiency": "proficient", "proficiency_multiplier": 1,
                     "sources": [SOURCE_LABEL]}], "notes": []}
    from ..ability_checks import proficiency_rank

    rank = proficiency_rank(existing)
    if rank is None or rank >= 1:
        # Proficient or Expertise already: "gain proficiency" adds nothing and
        # never lowers a higher rank. Unknown legacy totals stay unknown.
        notes = [] if (rank or 0) >= 1 else [
            f"{SOURCE_LABEL} grants {SKILL} proficiency, but this sheet records no explicit "
            f"proficiency rank for {SKILL}; the printed total is left unchanged."]
        return {"notes": notes} if notes else None
    sources = sorted({*(str(value) for value in existing.get("sources") or []), SOURCE_LABEL})
    # The strict projection contract accepts only changed rows, and skill rolls
    # use the canonical name as their bundle lookup key.
    return {"skills": [{**existing, "skill": SKILL, "bonus": int(existing.get("bonus") or 0) + pb,
                                             "proficiency": "proficient",
                                             "proficiency_multiplier": 1,
                                             "sources": sources}], "notes": []}
