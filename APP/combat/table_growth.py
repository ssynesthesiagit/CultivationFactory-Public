"""Campaign Insight and Immortal Art entries in the single table growth record.

Acquisition adapters only: combat benefits remain in the existing Insight/Art
compiler and plug-ins. Non-level Insights never award the level-selection +1.
Arts use the creation constructor and authenticated native source adapters; no
client-supplied source action, costs, character statistics or proof is trusted.
"""
from __future__ import annotations

import copy
import json
import tempfile
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core import FoundryError, sha256_json
from character_creation.constructed_arts.immortal_art import (
    compile_immortal_art, construct_immortal_art, immortal_art_count_ceiling,
    load_immortal_art_authority,
)
from stage2.insight_authority import compile_insight_stage2_authority
from . import table_advance as ta

ROOT = Path(__file__).resolve().parents[1]


def reject(message: str) -> None:
    raise FoundryError("TABLETOP_GROWTH_NOT_LEGAL", message, status_code=409)


def source_note(value: str) -> str:
    note = str(value or "").strip()
    if not note or len(note) > 240:
        reject("Say where this gain came from, in 1–240 characters (for example, a quest or mentor).")
    return note


def insight_ids(sheet: dict[str, Any]) -> list[str]:
    block = sheet.get("spheres_and_talents") or {}
    occurrences = [row.get("insight_id") or row.get("record_id")
                   for row in block.get("cultivation_insight_occurrences") or []]
    # The ID list and occurrence list are two views, not two acquisitions.
    return occurrences + [key for key in block.get("cultivation_insight_record_ids") or [] if key not in occurrences]


@lru_cache(maxsize=1)
def choice_rules() -> dict[str, Any]:
    """Acquisition input shapes for existing plug-ins, not another benefit implementation."""
    return json.loads((ROOT / "combat/rules/table_growth_choices.json").read_text())


def insight_choice(record_id: str, sheet: dict[str, Any], choice: str) -> dict[str, Any]:
    """Resolve a typed choice using character-owned options, never a client
    parameter dictionary. A sole legal pool is unambiguous; multiple pools
    require an explicit player choice."""
    rule = choice_rules().get(record_id)
    if rule is None:
        return {"parameters": {}, "reasons": [], "needs_choice": False}
    if rule["kind"] != "active_path_resource":
        reject("The rules for this Insight's choice are unavailable.")
    resource = (sheet.get("ability_scores_and_statistics") or {}).get("primary_resource") or {}
    active = {str(row.get("name") or "").lower() for row in resource.get("definitions") or []}
    active.add(str(resource.get("name") or "").lower())
    active &= {"qi", "stamina", "resonance"}
    selected = choice.strip().lower()
    if not selected and len(active) == 1:
        selected = next(iter(active))
    legal = selected in active
    return {"parameters": {rule["parameter"]: selected} if legal else {},
            "needs_choice": not legal,
            "reasons": [] if legal else [rule["prompt"] + " Available: " + ", ".join(v.title() for v in sorted(active))]}


def insight_status(record: dict[str, Any], sheet: dict[str, Any], *, choice: str = "") -> dict[str, Any]:
    """CAT3 minimum, typed prerequisites, repeat maximum and explicit GM boundary.

    CAT3 preserves untyped story prerequisites. They require a recorded GM
    confirmation, never an implicit success. Alternative groups supersede
    duplicate flat relations to their members in the legacy catalogue.
    """
    have = ta.known(sheet)
    raw = record.get("raw_source_record") or {}
    rule = compile_insight_stage2_authority(record, record["canonical_insight_id"])
    picked = insight_choice(record["canonical_insight_id"], sheet, choice)
    reasons, manual = list(picked["reasons"]), []
    if not record.get("selectable"):
        reasons.append(record.get("nonselectable_reason") or "This Insight is reference-only, not a selectable Insight.")
    if have["cl"] < rule["minimum_cl"]:
        reasons.append(f"Needs cultivation level {rule['minimum_cl']}.")
    present = set(insight_ids(sheet)) | have["spheres"] | have["talents"] | set(have["paths"])
    paths = sheet.get("path_and_subpath") or {}
    present.update(paths.get("subpath_record_ids") or [])
    for key in ("subpath_record_id", "tradition_record_id"):
        if paths.get(key):
            present.add(paths[key])
    relations = rule["typed_prerequisites"]
    grouped = {key for row in relations if row.get("kind") == "any_of" for key in row.get("value") or []}
    for row in relations:
        target, kind = row.get("target_id"), row.get("kind")
        if kind != "any_of" and target in grouped:
            continue
        if kind == "any_of":
            if not present.intersection(row.get("value") or []):
                reasons.append("Needs one of: " + ", ".join(str(v).split(".")[-1].replace("_", " ") for v in row.get("value") or []))
        elif kind in {"sphere", "path", "talent", "insight", "subpath_or_tradition"}:
            if target not in present:
                reasons.append("Needs " + str(row.get("display_name") or target).split(".")[-1].replace("_", " ").replace("-", " ") + ".")
        else:
            manual.append(str(row.get("raw_text") or row.get("value") or raw.get("prerequisites") or "the printed story prerequisite"))
    # A typed relation list may cover only part of the printed prerequisites.
    # Keep unrepresented clauses behind GM confirmation even in mixed records.
    if raw.get("prerequisites"):
        from character_creation.insight_build_policy import unverified_prerequisites
        manual.extend(unverified_prerequisites({"full_rules_text": raw.get("full_rules_text")}, present))
    count = insight_ids(sheet).count(record["canonical_insight_id"])
    maximum = rule["repeatability"]["maximum"]
    if maximum is not None and count >= maximum:
        reasons.append("Already known; this Insight cannot be taken again." if maximum == 1 else f"This Insight can be taken only {maximum} times.")
    # CAT3 has no typed vocabulary for these authored selections. Require an
    # explicit choice plus GM confirmation of its printed eligibility.
    repeat_text = str(raw.get("repeatable") or "")
    if "choose" in repeat_text.lower():
        if not choice.strip():
            reasons.append("Record the choice required by this Insight: " + repeat_text)
        manual.append("Confirm this choice follows the Insight's printed rule: " + repeat_text)
        previous = (sheet.get("spheres_and_talents") or {}).get("cultivation_insight_occurrences") or []
        # Re-choosing is not itself a distinctness rule: only the printed
        # requirement to choose a different option forbids a duplicate.
        if "choose a different" in repeat_text.casefold() and choice.strip() and any(
            row.get("insight_id") == record["canonical_insight_id"]
            and row.get("choice", "").strip().casefold() == choice.strip().casefold()
            for row in previous
        ):
            reasons.append("Choose a different option for this repeated Insight.")
    return {"legal": not reasons and not manual, "gm": bool(manual) and not reasons,
            "needs_choice": picked["needs_choice"], "parameters": picked["parameters"],
            "reasons": reasons + [f"GM confirmation needed: {v}" for v in manual]}


@lru_cache(maxsize=1)
def art_authority() -> dict[str, Any]:
    return load_immortal_art_authority(ROOT)


def path_cl(sheet: dict[str, Any], path_id: str) -> int:
    """Use the producer's per-Path attainment, including modern identity.paths
    rows. A sealed Art can prove a lower bound for a legacy multi-Path sheet;
    never assume overall CL belongs to every Path."""
    have = ta.known(sheet)
    identity = sheet.get("identity") or {}
    for row in identity.get("paths") or []:
        if row.get("path_id") == path_id and type(row.get("effective_cl")) is int:
            return row["effective_cl"] if 1 <= row["effective_cl"] <= have["cl"] else 0
    levels = identity.get("path_levels") or (sheet.get("path_and_subpath") or {}).get("path_levels") or {}
    if isinstance(levels, dict) and type(levels.get(path_id)) is int:
        return levels[path_id] if 1 <= levels[path_id] <= have["cl"] else 0
    if have["paths"] == [path_id]:
        return have["cl"]
    proven = [request["owning_path_cl"] for art in arts_of(sheet)
              for request in [(art.get("construction") or {}).get("request") or {}]
              if request.get("path_id") == path_id and type(request.get("owning_path_cl")) is int
              and 1 <= request["owning_path_cl"] <= have["cl"]]
    return max(proven, default=0)


@lru_cache(maxsize=24)
def native_sources(path_id: str, cl: int) -> tuple[dict[str, Any], ...]:
    """Run creation's exact native adapters against the shipped public chapters.

    Extract only the needed chapter into an automatically removed scratch
    directory. Requires BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip,
    the same shipped chapter bundle the canonical catalog needs. No Factory DB
    or owner's private sources are needed.
    """
    from character_creation.constructed_arts.native_immortal_sources import NATIVE_SOURCE_IDS, native_source_row
    from factory_authoring.native_path_mechanics import native_path_binding

    ids = [key for key in NATIVE_SOURCE_IDS if key.startswith(path_id + ".feature.")]
    if not ids or cl < 15:
        return ()
    binding = native_path_binding(ROOT, ids[0])
    index = json.loads((ROOT / binding["source"]["path"]).read_text())
    source_path = index["source"]["factory_path"]
    parent = {"record_id": path_id, "record_hash": sha256_json(index), "content_type": "path",
              "compatibility": {"factory": {"stage2_authority": {"progression_by_cl": {
                  str(level): {"feature_record_ids": [row["canonical_id"] for row in index["features"] if level in row.get("granted_at_cl", [])]}
                  for level in range(1, cl + 1)}}}}}
    result = []
    with tempfile.TemporaryDirectory(prefix="grow2-sources-", dir="/var/tmp") as scratch:
        root = Path(scratch)
        with zipfile.ZipFile(ROOT / "BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip") as archive:
            matches = [name for name in archive.namelist() if name.endswith("/" + source_path)]
            if len(matches) != 1:
                reject("The installed source chapter for this Art is unavailable.")
            target = root / source_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(matches[0]))
        for key in ids:
            result.append(native_source_row(ROOT, root, feature_id=key, parent_record=parent,
                                            owning_path_cl=cl, construction_cl=cl))
    return tuple(result)


def arts_of(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    """Owner sheets expose either one Art or a list; count acquisitions, not keys."""
    value = sheet.get("immortal_arts") or []
    return value if isinstance(value, list) else [value] if isinstance(value, dict) else []


def art_sources(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    """Creation-supported native actions plus authenticated sources already
    sealed in this character's constructed Arts. No arbitrary authored actions."""
    sources = {}
    have = ta.known(sheet)
    if have["cl"] < 15:
        return []
    for pid in have["paths"]:
        for source in native_sources(pid, path_cl(sheet, pid)):
            sources[source["record_id"]] = copy.deepcopy(source)
    # Existing constructed sources preserve the exact creation adapters for
    # specialized Subpaths, without manufacturing another implementation.
    for art in arts_of(sheet):
        if not isinstance(art, dict) or not art.get("construction") or art.get("table_growth_label"):
            continue
        # Projection adds acquisition packets and refinement history to the
        # pure construction. Compare its canonical fields, not those extra
        # earned-history views, when recovering a sealed source candidate.
        canonical = construct_immortal_art(art_authority(), art["construction"]["request"])
        if any(art.get(key) != value for key, value in canonical.items()):
            reject("A sealed Immortal Art no longer matches its construction rules.")
        compile_immortal_art(art_authority(), canonical)
        source = canonical["source"]
        pid = source.get("owning_path_id")
        if pid in have["paths"] and source.get("acquired_at_cl", 99) <= have["cl"]:
            sources.setdefault(source["record_id"], copy.deepcopy(source))
    return list(sources.values())


def art_menu(sheet: dict[str, Any]) -> dict[str, Any]:
    have = ta.known(sheet)
    try:
        authority = art_authority()
    except FoundryError as exc:
        # Missing optional authoring content must not disable Insights or any
        # other growth channel on a cold/portable installation.
        return {"minimum_cl": 15, "limit": immortal_art_count_ceiling(have["cl"]),
                "known": len(arts_of(sheet)), "sources": [], "aspects": [],
                "unavailable": exc.message}
    sources = art_sources(sheet)
    return {"minimum_cl": 15, "limit": immortal_art_count_ceiling(have["cl"]),
            "known": len(arts_of(sheet)),
            "sources": [{"id": row["record_id"], "name": row["display_name"]} for row in sources],
            "aspects": [{"id": row["aspect_id"], "name": row["display_name"],
                         "factors": [{"id": f["factor_id"], "name": f["display_name"], "text": f["mechanical_chassis"]} for f in row["factors"]],
                         "burdens": [{"id": b["burden_id"], "name": b["display_name"], "text": b.get("effect") or b.get("restriction") or b.get("mechanical_chassis") or ""}
                                     for b in row.get("burdens") or []]} for row in authority["aspects"]]}


def construct_art(sheet: dict[str, Any], design: dict[str, Any], project_id: str) -> dict[str, Any]:
    """Server-owned construction inputs; design contains only owner decisions."""
    have = ta.known(sheet)
    if len(arts_of(sheet)) >= immortal_art_count_ceiling(have["cl"]):
        reject("Immortal Arts need cultivation level 15 or higher and an unused Art slot for your Realm.")
    source = next((row for row in art_sources(sheet) if row["record_id"] == design.get("source_record_id")), None)
    if source is None:
        reject("Choose a known source action from this character's Immortal Art menu.")
    pid = source["owning_path_id"]
    level = path_cl(sheet, pid)
    if level < 15:
        reject("The powering Path must have reached cultivation level 15.")
    path_row = next((row for row in (sheet.get("identity") or {}).get("paths") or []
                     if row.get("path_id") == pid), {})
    key = {"tianxia.path.body_refining": "CON", "tianxia.path.spirit_awakening": "WIS"}.get(
        pid, path_row.get("key_ability") or have["key_ability"])
    score = ta.current_scores(sheet).get(key)
    if score is None:
        reject("The powering Path needs a recorded key ability score.")
    request = {"seed": "campaign:" + sha256_json(design), "project_id": project_id,
               "cl": have["cl"], "pb": have["pb"], "path_id": pid, "path_kind": pid.split(".")[-1],
               "path_name": pid.split(".")[-1].replace("_", " ").title(),
               "key_ability": key, "key_ability_modifier": ta.ability_modifier(score),
               "owning_path_cl": level, "path_realm": "Immortal" if level >= 20 else "Nascent Soul",
               "known_spheres": [{"sphere_id": key, "display_name": key} for key in sorted(have["spheres"])],
               "known_sources": [source], "source_record_id": source["record_id"],
               # Ordinal is a creation recipe selector, not the campaign count.
               # The Realm count ceiling above is the campaign acquisition rule.
               "art_ordinal": 0, "aspect_id": design.get("aspect_id"),
               "factor_ids": design.get("factor_ids") or [], "burdens": design.get("burdens") or []}
    art = construct_immortal_art(art_authority(), request)
    compile_immortal_art(art_authority(), art, known_sources=[source])
    return art


def refinement(art: dict[str, Any], proof: dict[str, Any]) -> dict[str, Any]:
    """Record an actual campaign completion, not creator-generated history.

    The same printed d20 + PB + Path modifier, research and material figures
    used by creation apply. This records the already-paid work; it does not
    claim to debit a campaign purse or simulate downtime.
    """
    die = proof.get("die")
    hours, gp = art["research_days"] * 8, art["material_cost_gp"]
    if type(die) is not int or not 1 <= die <= 20:
        reject("Record the Refinement Check's d20 result (1–20).")
    request = art["construction"]["request"]
    total = die + request["pb"] + request["key_ability_modifier"]
    if total < art["refinement_dc"]:
        reject(f"The Art is not refined: the check totals {total}, below difficulty {art['refinement_dc']}.")
    if type(proof.get("research_hours")) is not int or proof["research_hours"] < hours:
        reject(f"Refinement needs at least {hours} completed research hours.")
    if type(proof.get("materials_gp")) is not int or proof["materials_gp"] < gp:
        reject(f"Refinement needs at least {gp} gp of paid materials.")
    return {"die": die, "total": total, "dc": art["refinement_dc"],
            "research_hours": proof["research_hours"], "materials_gp": proof["materials_gp"],
            "scope": "recorded_campaign_completion"}


def art_description(art: dict[str, Any]) -> str:
    """Player-readable Art rules, without construction IDs or hash ledgers."""
    surface = art["action_surface"]
    lines = [art["name"],
             f"{surface['action_type']}; range: {surface['range']}; target: {surface['target']}; duration: {surface['duration']}.",
             f"Each use costs {art['activation_cp']} {surface['resource_name']}.",
             f"Dao Aspect (the Art's principle): {art['dao_aspect']['display_name']}.",
             "Base action:", art["source"].get("published_text") or str(surface.get("effect") or "")]
    for factor in art.get("factors") or []:
        lines.append(f"Upgrade — {factor['display_name']}: {factor['mechanical_chassis']}")
    application = surface.get("factor_application") or {}
    definitions = (application.get("factor_rules") or {}).get("text")
    if definitions:
        lines.append("Upgrade definitions and counterplay:\n" + definitions)
    refinement = (application.get("effective_effect") or {}).get("factor_refinement") or {}
    labels = {"temporary_hp": "Temporary Hit Points", "duration": "Duration",
              "stacking": "Combining protections", "cleanup": "When protection ends"}
    for key, label in labels.items():
        if key in refinement:
            lines.append(label + ": " + str(refinement[key]).replace("PB", "proficiency bonus"))
    for burden in art.get("burdens") or []:
        lines.append(f"Restriction — {burden['display_name']}: {burden.get('effect') or ''}")
    for key, label in (("trigger", "When it can be used"), ("trigger_frequency", "How often"),
                       ("counterplay", "How it can be opposed"), ("cleanup", "When it ends")):
        if surface.get(key):
            lines.append(f"{label}: {surface[key]}")
    lines.append("The fight runs the source action and supported upgrades; the Game Master resolves any unautomated clauses.")
    return "\n\n".join(lines)


def project(sheet: dict[str, Any], table: dict[str, Any]) -> None:
    """Overlay stored acquisitions onto an already copied sheet, in place."""
    block = sheet.setdefault("spheres_and_talents", {})
    sections = sheet.setdefault("selected_record_sections", {})
    for row in table["insights"]:
        key = row["id"]
        ids = block.setdefault("cultivation_insight_record_ids", [])
        if key not in ids:
            ids.append(key)
        occurrences = block.setdefault("cultivation_insight_occurrences", [])
        occurrences.append({"insight_id": key, "name": row["name"], "gained_at_cl": row["cl"],
                            "choice": row.get("choice", ""), "parameters": copy.deepcopy(row.get("parameters") or {}),
                            "source_note": row["note"],
                            "ability_change_applied": row.get("source") == "level", "acquisition_source": row.get("source") or "campaign"})
        sections.setdefault("insights", []).append(
            {"record_id": key, "display_name": row["name"], "full_description": row["text"],
             "acquisition_cl": row["cl"], "one_line_description": "Gained in play: " + row["note"]})
    for row in table["immortal_arts"]:
        art = copy.deepcopy(row["art"])
        art.update(name=row["name"], display_name=row["name"], table_growth_label=True)
        sheet["immortal_arts"] = [*arts_of(sheet), art]
        sections.setdefault("other", []).append(
            {"record_id": art["art_id"], "display_name": row["name"], "subsection": "Immortal Art",
             "acquisition_cl": art["cl_created"], "full_description": art_description(art),
             "one_line_description": "Refined in play: " + row["note"]})
