from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from functools import lru_cache

AUTH_SHA = "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385"
C3B_SHA = "79bdf65ebb84a0e34853842a26c1b439d701c47dd278673c67a6a1168b956daa"
C3B_SOURCE_SHA = "35b547829dfa6576486691d628a19e9d66e6788697aaf2eacaf5b9d12cc2419d"
QA2_SHA = "c2e9722d9e330d2491259c7369015ea5d99cf46ed57a0c1a537918594b1a5774"
RULING_ID = "OWNER-CATALOG-2026-07-25-001"
SOURCE_PACK = "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2"
SOURCE_VERSION = "HF05ZVK-R1H Phase 2I HF2 / Canon Corpus P2A"
SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"


def canonical_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@lru_cache(maxsize=None)
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(obj))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for row in rows:
            cooked = {}
            for k in fieldnames:
                v = row.get(k, "")
                if isinstance(v, (dict, list, bool)) or v is None:
                    cooked[k] = json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                else:
                    cooked[k] = v
            w.writerow(cooked)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def norm_key(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).replace("’", "'").replace("‘", "'")
    return re.sub(r"[^a-z0-9]+", "_", folded.casefold()).strip("_")


def norm_name(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).replace("’", "'").replace("‘", "'")
    return re.sub(r"[^a-z0-9]+", " ", folded.casefold()).strip()


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).casefold() == "true"


def parse_int(value: Any) -> int | None:
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_jsonish(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def commit_record(record: dict[str, Any]) -> dict[str, Any]:
    base = {k: v for k, v in record.items() if k != "record_commitment_sha256"}
    out = dict(base)
    out["record_commitment_sha256"] = sha256_bytes(canonical_bytes(base))
    return out


def envelope(schema: str, records: list[dict[str, Any]], counts: dict[str, Any] | None = None) -> dict[str, Any]:
    obj = {
        "schema": schema,
        "checkpoint": "CAT1",
        "deterministic_serialization": "UTF-8 canonical JSON; sorted keys; compact separators; LF terminator",
        "source_authority_sha256": AUTH_SHA,
        "accepted_qa2_sha256": QA2_SHA,
        "records": records,
    }
    if counts is not None:
        obj["counts"] = counts
    obj["registry_commitment_sha256"] = sha256_bytes(canonical_bytes({k: v for k, v in obj.items() if k != "registry_commitment_sha256"}))
    return obj


def source_context(lines: list[str], line_number: int | None) -> dict[str, Any]:
    if not line_number or line_number < 1 or line_number > len(lines):
        return {"line": line_number, "nearest_headings": [], "excerpt": ""}
    headings = []
    for i in range(line_number - 1, max(-1, line_number - 250), -1):
        if re.match(r"^#{1,6}\s+", lines[i]):
            headings.append({"line": i + 1, "heading": lines[i].strip()})
            if len(headings) == 4:
                break
    start = max(0, line_number - 3)
    end = min(len(lines), line_number + 4)
    return {
        "line": line_number,
        "nearest_headings": headings,
        "excerpt": "\n".join(f"{i+1}: {lines[i]}" for i in range(start, end)),
    }


def parse_anchor_line(anchor: str) -> int | None:
    m = re.fullmatch(r"line:(\d+)", anchor or "")
    return int(m.group(1)) if m else None


def extract_prerequisite_text(full_description: str, short_description: str, qa2_expr: str) -> str:
    text = full_description or short_description or ""
    lines = []
    for line in text.splitlines():
        if re.match(r"^\s*(Prerequisite|Prerequisites|Classification|Access):", line, re.I):
            lines.append(line.strip())
    if lines:
        return "\n".join(lines)
    if qa2_expr:
        return qa2_expr
    return ""


def typed_prerequisite_projection(talent: dict[str, Any], sphere_name_to_id: dict[str, str]) -> dict[str, Any]:
    raw = talent.get("raw_prerequisite_prose", "")
    constraints = []
    owner_id = talent["owning_canonical_sphere_id"]
    constraints.append({"kind": "sphere_id", "target_id": owner_id, "source_basis": "canonical owning Sphere relationship"})
    if talent.get("minimum_cl") is not None:
        constraints.append({"kind": "minimum_cl", "value": talent["minimum_cl"], "source_basis": "typed or exact CL token"})
    # Only exact names already represented in the raw source are projected. No all/any operator is invented.
    for name, sid in sorted(sphere_name_to_id.items(), key=lambda x: (-len(x[0]), x[0])):
        if sid == owner_id:
            continue
        if raw and re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", raw, re.I):
            constraints.append({"kind": "sphere_id_reference", "target_id": sid, "source_basis": "exact display-name token in raw prerequisite prose"})
    complex_markers = [" or ", " one of ", "any ", "GM permission", "scripture", "inheritance", "approved", "background", "Path", "Subpath", "Tradition"]
    has_complex = any(m.casefold() in raw.casefold() for m in complex_markers)
    if not raw:
        status = "NO_EXPLICIT_PREREQUISITE_PROSE_BEYOND_OWNER_RELATIONSHIP"
        safe = True
        unresolved = ""
    elif has_complex:
        status = "PARTIALLY_TYPED_RAW_PROSE_RETAINED"
        safe = False
        unresolved = "Natural-language prerequisite contains access or logical semantics not explicitly machine-encoded."
    else:
        status = "TYPED_FIELDS_AVAILABLE_RAW_PROSE_RETAINED"
        safe = True
        unresolved = ""
    return {
        "record_id": talent["canonical_talent_id"],
        "prerequisite_evaluation_status": status,
        "typed_constraints": constraints,
        "raw_prerequisite_prose": raw,
        "display_only_or_advisory_constraints": [] if safe else [raw],
        "invalid_references": [],
        "unresolved_reason": unresolved,
        "creator_selectability_can_be_evaluated_safely": safe,
        "source_provenance": talent["source_provenance"],
    }


def classify_unresolved(
    raw: dict[str, Any], cls: dict[str, Any], comp_lines: list[str], comp_folded: list[str]
) -> tuple[str, str, dict[str, Any], bool]:
    name = raw.get("canonical_talent_name", "").strip()
    source_refs = raw.get("source_refs") or []
    role = raw.get("catalog_role") or cls.get("catalog_role")
    # Exact heading matching is intentionally literal and does not infer talent authority from suffixes.
    hits = []
    needle = name.casefold()
    for i, folded in enumerate(comp_folded, 1):
        if needle and needle in folded:
            hits.append((i, comp_lines[i-1].strip()))
    heading_hits = [(i, line) for i, line in hits if re.match(r"^#{1,6}\s+", line)]
    context = {
        "exact_name_heading_hits": [{"line": i, "heading": line} for i, line in heading_hits],
        "exact_name_nonheading_hits": [{"line": i, "text": line} for i, line in hits if (i, line) not in heading_hits][:10],
        "declared_source_refs": source_refs,
    }
    combined = " ".join(source_refs).casefold()
    generated_markers = (
        "cleanup backlog", "structural seed packet", "user-approved scope", "exact dice/source-text verification remains",
        "no source_refs", "packet", "ledger", "counterplay", "window", "contract", "source id", "lock", "boundary",
    )
    if role == "source_verified_packet_action_row":
        return "GENERATED_OR_PROJECTION_ROW", "Catalog role explicitly identifies a packet/action projection row, not a separately acquirable Talent.", context, False
    if any(marker in combined for marker in generated_markers[:4]):
        return "GENERATED_OR_PROJECTION_ROW", "Declared source reference identifies a structural/projection packet whose exact talent authority remained backlog work.", context, False
    generic_structural = {
        "adrenaline", "pair talents", "fragrance", "form talents", "sequence talents", "guard talents", "counter talents",
        "success", "shield training", "active defense", "open the gate",
    }
    if norm_name(name) in generic_structural:
        return "STRUCTURAL_HEADING", "Exact source context is a system heading or family label, not a separately named selectable Talent.", context, False
    if heading_hits:
        head_text = " ".join(x[1] for x in heading_hits).casefold()
        if "base ability" in head_text or "base technique" in head_text:
            return "BASE_SPHERE_ABILITY", "Exact source heading identifies a base Sphere ability/technique rather than a trained Talent.", context, False
        # Exact heading exists, but QA2 did not establish that this candidate stable ID is the authoritative selectable identity.
        return "AMBIGUOUS_REQUIRES_AUTHORITY_DECISION", "Exact source heading exists, but candidate-to-source identity and the accepted 1,748-talent count cannot be changed without a bounded authority ruling.", context, True
    if hits:
        return "GENERATED_OR_PROJECTION_ROW", "The phrase appears only in prose; no exact selectable heading establishes a Talent identity.", context, False
    return "GENERATED_OR_PROJECTION_ROW", "No exact current-compendium heading or text occurrence establishes this packet row as a selectable Talent.", context, False


def schema_defs() -> dict[str, dict[str, Any]]:
    source_prov = {
        "type": "object",
        "required": ["source_pack", "source_version", "source_path", "source_anchor", "source_authority_sha256"],
        "properties": {
            "source_pack": {"type": "string"}, "source_version": {"type": "string"}, "source_path": {"type": "string"},
            "source_anchor": {"type": "string"}, "source_authority_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
        "additionalProperties": True,
    }
    base = {
        "$schema": SCHEMA_URI,
        "type": "object",
        "required": ["schema", "records", "registry_commitment_sha256"],
        "properties": {
            "schema": {"type": "string"}, "records": {"type": "array"},
            "registry_commitment_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
        "additionalProperties": True,
    }
    schemas = {}
    sphere = json.loads(json.dumps(base))
    sphere["$id"] = "urn:tianxia:cat1:canonical-sphere-registry:v1"
    sphere["properties"]["records"]["items"] = {"type": "object", "required": ["canonical_sphere_id", "display_name", "record_commitment_sha256", "source_provenance"], "properties": {"canonical_sphere_id": {"type": "string"}, "display_name": {"type": "string"}, "record_commitment_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "source_provenance": source_prov}, "additionalProperties": True}
    schemas["canonical_sphere_registry.schema.json"] = sphere
    alias = json.loads(json.dumps(base)); alias["$id"] = "urn:tianxia:cat1:sphere-alias-registry:v1"
    alias["properties"]["records"]["items"] = {"type": "object", "required": ["label", "label_classification", "record_commitment_sha256"], "properties": {"label": {"type": "string"}, "label_classification": {"enum": ["alias", "route_label", "content_family_label", "historical_label", "generated_coverage_grouping", "invalid_unresolved_label"]}, "record_commitment_sha256": {"type": "string"}}, "additionalProperties": True}
    schemas["sphere_alias_registry.schema.json"] = alias
    talent = json.loads(json.dumps(base)); talent["$id"] = "urn:tianxia:cat1:canonical-talent-registry:v1"
    talent["properties"]["records"]["items"] = {"type": "object", "required": ["canonical_talent_id", "display_name", "owning_canonical_sphere_id", "selection_disposition", "record_commitment_sha256", "source_provenance"], "properties": {"canonical_talent_id": {"type": "string"}, "display_name": {"type": "string"}, "owning_canonical_sphere_id": {"type": "string"}, "selection_disposition": {"type": "string"}, "record_commitment_sha256": {"type": "string"}, "source_provenance": source_prov}, "additionalProperties": True}
    schemas["canonical_talent_registry.schema.json"] = talent
    for fn, urn in [
        ("mixed_candidate_classification.schema.json", "urn:tianxia:cat1:mixed-candidate-classification:v1"),
        ("selection_disposition.schema.json", "urn:tianxia:cat1:selection-disposition:v1"),
        ("prerequisite_projection.schema.json", "urn:tianxia:cat1:prerequisite-projection:v1"),
        ("owner_readable_projection.schema.json", "urn:tianxia:cat1:owner-readable-projection:v1"),
        ("unresolved_authority_decisions.schema.json", "urn:tianxia:cat1:unresolved-authority-decisions:v1"),
        ("overlay_manifest.schema.json", "urn:tianxia:cat1:overlay-manifest:v1"),
    ]:
        s = json.loads(json.dumps(base)); s["$id"] = urn
        s["properties"]["records"]["items"] = {"type": "object"}
        schemas[fn] = s
    return schemas


def build(args: argparse.Namespace) -> None:
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    catroot = out / "catalog_authority" / "cat1"
    data_dir = catroot / "data"
    schema_dir = catroot / "schemas"
    report_dir = catroot / "reports"
    evidence_dir = catroot / "evidence"
    for d in [data_dir, schema_dir, report_dir, evidence_dir, catroot / "validators", catroot / "tools", catroot / "integration"]:
        d.mkdir(parents=True, exist_ok=True)

    auth = Path(args.authority_root).resolve()
    qa2 = Path(args.qa2_root).resolve()
    c3b_source = Path(args.c3b_source_root).resolve()
    ruling_path = Path(args.owner_ruling).resolve()
    ruling = json.loads(ruling_path.read_text(encoding="utf-8"))
    assert ruling["ruling_id"] == RULING_ID and ruling["decision"]["canonical_sphere"] == "The Piercing Needle"

    comp_rel = "09_RULES/Source_Text/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md"
    comp_path = auth / comp_rel
    comp_lines = comp_path.read_text(encoding="utf-8-sig").splitlines()
    comp_folded = [line.casefold() for line in comp_lines]
    comp_hash = sha256_file(comp_path)
    catalog_rel = "09_RULES/Indexes/Canonical_Talent_Catalog.json"
    catalog_path = auth / catalog_rel
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    product_auth = json.loads((c3b_source / "catalog/sphere_talent_authority_v1.json").read_text(encoding="utf-8"))
    qa_spheres = read_csv(qa2 / "canonical/spheres.csv")
    qa_talents = read_csv(qa2 / "canonical/talents.csv")
    qa_memberships = read_csv(qa2 / "canonical/sphere_talent_memberships.csv")
    qa_mixed = read_csv(qa2 / "canonical/mixed_talent_candidate_classification.csv")
    qa_all = read_csv(qa2 / "canonical/canonical_records.csv")
    qa_ui = {r["record_id"]: r for r in read_csv(qa2 / "matrices/expected_future_ui_coverage.csv")}
    qa_readability = {r["record_id"]: r for r in read_csv(qa2 / "matrices/owner_readability.csv")}

    # Published Sphere sections and exact section ranges.
    headings = []
    for i, line in enumerate(comp_lines, 1):
        m = re.match(r"^#{1,4}\s+Sphere of\s+(.+?)\s*$", line.strip(), re.I)
        if m:
            headings.append((m.group(1).strip(), i))
    assert len(headings) == 85, len(headings)
    section_ranges = {}
    for idx, (name, start) in enumerate(headings):
        end = headings[idx + 1][1] - 1 if idx + 1 < len(headings) else len(comp_lines)
        section_ranges[name] = (start, end)
    sphere_name_to_id = {name: f"tianxia.sphere.{norm_key(name)}" for name, _ in headings}
    qa_sphere_by_name = {r["display_name"]: r for r in qa_spheres}

    # Explicit label classification; no extra label is promoted to a Sphere.
    extra_labels = {
        "Fencing": ("alias", "The Piercing Needle", "Owner ruling maps this legacy/content-family label to the published Sphere."),
        "Harvesting-Gathering": ("alias", "Harvesting Gathering", "Hyphenated generated/source spelling resolves to the exact published heading spelling."),
        "Chains / Meridian": ("content_family_label", "Chains", "Cross-family Meridian label; the published Sphere identity remains Chains."),
        "Pressure Points / Meridian": ("content_family_label", "Pressure Points", "Meridian content-family label under the published Pressure Points Sphere."),
        "Chakra Imbuement": ("content_family_label", "Imbuement", "Chakra route/content-family label associated with the published Imbuement Sphere."),
        "Chakra Universal": ("route_label", None, "Chakra-wide route label; not a published Sphere."),
        "Drain": ("content_family_label", None, "Chakra pack content family; not a published Sphere."),
        "Phasing": ("content_family_label", None, "Chakra pack content family; not a published Sphere."),
        "Predator": ("content_family_label", None, "Chakra pack content family; not a published Sphere."),
        "Vitality": ("content_family_label", None, "Chakra pack content family; not a published Sphere."),
        "Universal": ("generated_coverage_grouping", None, "Generated universal coverage grouping; not a published Sphere."),
        "Universal C09": ("generated_coverage_grouping", None, "Historical/generated C09 coverage grouping; not a published Sphere."),
        "Universal Martial": ("route_label", None, "Universal martial route label; not a published Sphere."),
    }

    # Parse source common-name aliases within each section.
    common_aliases = defaultdict(list)
    for name, (start, end) in section_ranges.items():
        for line in comp_lines[start - 1 : min(end, start + 80)]:
            m = re.match(r"^\s*Common Names?:\s*(.+?)\s*$", line, re.I)
            if m:
                for val in re.split(r"\s*,\s*|\s*;\s*", m.group(1)):
                    val = re.sub(r"\s+Sphere$", "", val.strip(), flags=re.I)
                    if val and val != name:
                        common_aliases[name].append(val)

    # Background relationships.
    background_rows = [r for r in qa_all if r["record_type"] == "background_talent"]
    background_counts = Counter(r.get("sphere_requirement", "") for r in background_rows)

    # Fencing mapping affects canonical counts.
    mapped_counts = Counter()
    for t in qa_talents:
        owner = "The Piercing Needle" if t["owning_sphere"] == "Fencing" else t["owning_sphere"]
        mapped_counts[owner] += 1

    sphere_records = []
    for name, start in headings:
        qa = qa_sphere_by_name[name]
        end = section_ranges[name][1]
        sid = sphere_name_to_id[name]
        aliases = sorted(set(common_aliases[name]))
        labels = []
        for label, (kind, target, reason) in extra_labels.items():
            if target == name:
                labels.append(label)
                if kind == "alias":
                    aliases.append(label)
        if name == "The Piercing Needle":
            aliases.extend(["Fencing", "Fencing Sphere"])
        if name == "Harvesting Gathering":
            aliases.extend(["Harvesting-Gathering", "Harvesting and Gathering"])
        aliases = sorted(set(a for a in aliases if a and a != name))
        ui = qa_ui.get(qa["record_id"], {})
        section_hash = sha256_bytes(("\n".join(comp_lines[start - 1 : end]) + "\n").encode("utf-8"))
        record = {
            "canonical_sphere_id": sid,
            "preserved_legacy_id": qa["record_id"],
            "proposed_canonical_id": sid,
            "deterministic_migration_alias": qa["record_id"] if qa["record_id"] != sid else None,
            "display_name": name,
            "normalized_key": norm_key(name),
            "exact_published_source_section": f"Sphere of {name}",
            "source_section_line_start": start,
            "source_section_line_end": end,
            "source_section_sha256": section_hash,
            "source_pack": SOURCE_PACK,
            "source_version": SOURCE_VERSION,
            "aliases": aliases,
            "content_family_labels": sorted(label for label, (kind, target, _) in extra_labels.items() if target == name and kind == "content_family_label"),
            "route_labels": sorted(label for label, (kind, target, _) in extra_labels.items() if target == name and kind == "route_label"),
            "deprecated_labels": [],
            "status": "PUBLISHED_CANONICAL",
            "expected_browse_rules_visibility": parse_bool(ui.get("should_appear_browse_rules", "True")),
            "expected_character_creator_disposition": qa.get("selection_disposition") or "OWNER_SELECTABLE_WITH_PREREQUISITES",
            "confirmed_selectable_talent_count": mapped_counts[name],
            "confirmed_membership_count": mapped_counts[name],
            "background_related_relationship_count": background_counts[name],
            "zero_projected_talent_status": mapped_counts[name] == 0,
            "source_provenance": {
                "source_pack": SOURCE_PACK,
                "source_version": SOURCE_VERSION,
                "source_path": comp_rel,
                "source_anchor": f"line:{start}",
                "source_authority_sha256": AUTH_SHA,
                "source_file_sha256": comp_hash,
            },
        }
        sphere_records.append(commit_record(record))
    sphere_records.sort(key=lambda r: r["canonical_sphere_id"])

    label_records = []
    published_names = set(sphere_name_to_id)
    catalog_labels = sorted({r["canonical_source_sphere"] for r in catalog["records"]})
    coverage_labels = sorted(product_auth["sphere_coverage"])
    outside = sorted((set(catalog_labels) | set(coverage_labels)) - published_names)
    assert set(outside) == set(extra_labels), (outside, sorted(extra_labels))
    for label in outside:
        kind, target, reason = extra_labels[label]
        rec = {
            "label": label,
            "normalized_key": norm_key(label),
            "label_classification": kind,
            "canonical_sphere_id": sphere_name_to_id.get(target) if target else None,
            "canonical_display_name": target,
            "appears_in_mixed_catalog": label in catalog_labels,
            "appears_in_product_coverage": label in coverage_labels,
            "owner_ruling_id": RULING_ID if label == "Fencing" else None,
            "reason": reason,
            "source_provenance": {
                "source_pack": SOURCE_PACK,
                "source_version": SOURCE_VERSION,
                "source_path": catalog_rel,
                "source_anchor": f"source-label:{label}",
                "source_authority_sha256": AUTH_SHA,
            },
        }
        label_records.append(commit_record(rec))

    qa_members_by_id = {r["talent_id"]: r for r in qa_memberships}
    canonical_talents = []
    memberships = []
    prereqs = []
    readable = []
    selection_rows = []
    for row in qa_talents:
        tid = row["record_id"]
        legacy_owner = row["owning_sphere"]
        canonical_owner = "The Piercing Needle" if legacy_owner == "Fencing" else legacy_owner
        assert canonical_owner in sphere_name_to_id, (tid, canonical_owner)
        owner_id = sphere_name_to_id[canonical_owner]
        full = row.get("full_description", "")
        short = row.get("short_description", "")
        raw_prereq = extract_prerequisite_text(full, short, row.get("prerequisite_expression", ""))
        min_cl = parse_int(row.get("minimum_cl"))
        aliases = parse_jsonish(row.get("aliases"), [])
        disposition = row.get("selection_disposition") or "OWNER_SELECTABLE_WITH_PREREQUISITES"
        # The controlling owner ruling resolves the QA2 Fencing owner-identity ambiguity.
        # Preserve the source label, but normalize the selection disposition to the
        # ordinary prerequisite-governed Sphere-talent route.
        if legacy_owner == "Fencing" and disposition == "AMBIGUOUS_REQUIRES_OWNER_RULE_DECISION":
            disposition = "OWNER_SELECTABLE_WITH_PREREQUISITES"
        if row.get("restriction") in {"secret", "forbidden", "restricted", "rare"}:
            disposition = "RESTRICTED_CONTENT"
        source_path = row.get("provenance_path") or catalog_rel
        source_anchor = row.get("source_anchor") or f"record:{tid}"
        source_line = parse_anchor_line(source_anchor)
        section = None
        if source_path == comp_rel and source_line:
            for sphere_name, (start, end) in section_ranges.items():
                if start <= source_line <= end:
                    section = f"Sphere of {sphere_name}"
                    break
        record = {
            "canonical_talent_id": tid,
            "preserved_legacy_id": tid,
            "proposed_canonical_id": tid,
            "deterministic_migration_alias": None,
            "display_name": row["display_name"],
            "owning_canonical_sphere_id": owner_id,
            "owning_canonical_sphere_name": canonical_owner,
            "legacy_source_sphere_label": legacy_owner,
            "legacy_owner_alias_applied": legacy_owner != canonical_owner,
            "owner_ruling_id": RULING_ID if legacy_owner == "Fencing" else None,
            "exact_source_path": source_path,
            "exact_source_anchor": source_anchor,
            "exact_source_section": section,
            "source_pack": SOURCE_PACK,
            "source_version": SOURCE_VERSION,
            "record_type": "CONFIRMED_SELECTABLE_TALENT",
            "acquisition_routes": [x for x in row.get("acquisition_route", "").split("|") if x],
            "background_only": False,
            "automatic_grant": False,
            "training_eligibility": "ELIGIBLE_UNDER_ACCEPTED_GENERAL_TRAINING_ROUTE",
            "free_sphere_talent_eligibility": "PENDING_EXACT_PREREQUISITE_EVALUATION" if raw_prereq else "SUPPORTED_BY_ACCEPTED_GENERAL_RULE_SUBJECT_TO_CHARACTER_STATE",
            "minimum_cl": min_cl,
            "typed_prerequisite_fields_present": bool(min_cl or canonical_owner),
            "raw_prerequisite_prose": raw_prereq,
            "prerequisite_evaluation_status": "PENDING_PROJECTION",
            "short_description": short,
            "full_description": full,
            "short_description_availability": "AVAILABLE" if short else "MISSING",
            "full_description_availability": "AVAILABLE" if full else "MISSING",
            "selection_disposition": disposition,
            "restriction_status": row.get("restriction") or "ordinary_or_unspecified",
            "historical_or_deprecated": parse_bool(row.get("generated_or_historical")),
            "aliases": aliases,
            "source_kind": row.get("source_kind"),
            "source_provenance": {
                "source_pack": SOURCE_PACK,
                "source_version": SOURCE_VERSION,
                "source_path": source_path,
                "source_anchor": source_anchor,
                "source_authority_sha256": AUTH_SHA,
                "source_file_sha256": sha256_file(auth / source_path) if (auth / source_path).is_file() else None,
                "accepted_qa2_record_id": tid,
            },
        }
        record = commit_record(record)
        canonical_talents.append(record)
        edge = {
            "membership_id": f"cat1.membership.{norm_key(tid)}",
            "canonical_talent_id": tid,
            "canonical_sphere_id": owner_id,
            "canonical_sphere_name": canonical_owner,
            "legacy_source_sphere_label": legacy_owner,
            "edge_kind": "CANONICAL_SPHERE_OWNS_TALENT",
            "owner_ruling_id": RULING_ID if legacy_owner == "Fencing" else None,
            "source_provenance": record["source_provenance"],
        }
        memberships.append(commit_record(edge))
        p = typed_prerequisite_projection(record, sphere_name_to_id)
        p = commit_record(p)
        prereqs.append(p)
        record["prerequisite_evaluation_status"] = p["prerequisite_evaluation_status"]
        record = commit_record({k: v for k, v in record.items() if k != "record_commitment_sha256"})
        canonical_talents[-1] = record
        desc_status = "SOURCE_TEXT_AVAILABLE" if full else ("ONLY_SHORT_SOURCE_TEXT_AVAILABLE" if short else "NO_ADEQUATE_SOURCE_DESCRIPTION")
        readable_rec = {
            "record_id": tid,
            "record_type": "talent",
            "display_name": row["display_name"],
            "one_line_description": short,
            "full_description": full,
            "full_description_or_source_reference": full or f"{source_path}#{source_anchor}",
            "description_status": desc_status,
            "prerequisites_readable": raw_prereq,
            "acquisition_route": record["acquisition_routes"],
            "source_attribution": f"{SOURCE_PACK}: {source_path}#{source_anchor}",
            "restriction_explanation": record["restriction_status"],
            "advanced": {"stable_id": tid, "canonical_sphere_id": owner_id, "source_authority_sha256": AUTH_SHA},
            "source_provenance": record["source_provenance"],
        }
        readable.append(commit_record(readable_rec))
        selection_rows.append(commit_record({
            "record_id": tid, "record_type": "talent", "selection_disposition": disposition,
            "source_evidence": record["source_provenance"], "owner_selectable_output": disposition not in {"DISPLAY_ONLY", "GM_ONLY", "HISTORICAL_OR_DEPRECATED", "NOT_YET_IMPLEMENTED_BY_DESIGN", "BLOCKED_MISSING_TYPED_AUTHORITY", "AMBIGUOUS_REQUIRES_OWNER_DECISION"},
        }))
    canonical_talents.sort(key=lambda r: r["canonical_talent_id"])
    memberships.sort(key=lambda r: (r["canonical_sphere_id"], r["canonical_talent_id"]))
    prereqs.sort(key=lambda r: r["record_id"])
    readable.sort(key=lambda r: r["record_id"])
    selection_rows.sort(key=lambda r: r["record_id"])

    # Add owner-readable Sphere projections and dispositions.
    for sphere in sphere_records:
        sid = sphere["canonical_sphere_id"]
        readable.append(commit_record({
            "record_id": sid, "record_type": "sphere", "display_name": sphere["display_name"],
            "one_line_description": "", "full_description": "",
            "full_description_or_source_reference": f"{comp_rel}#line:{sphere['source_section_line_start']}",
            "description_status": "SOURCE_TEXT_AVAILABLE_BUT_PROJECTION_MISSING",
            "prerequisites_readable": "Sphere acquisition prerequisites are governed by character advancement/training authority.",
            "acquisition_route": ["sphere-acquisition"],
            "source_attribution": f"{SOURCE_PACK}: {comp_rel}#line:{sphere['source_section_line_start']}",
            "restriction_explanation": "ordinary_or_unspecified",
            "advanced": {"stable_id": sid, "source_authority_sha256": AUTH_SHA},
            "source_provenance": sphere["source_provenance"],
        }))
        selection_rows.append(commit_record({
            "record_id": sid, "record_type": "sphere", "selection_disposition": sphere["expected_character_creator_disposition"],
            "source_evidence": sphere["source_provenance"], "owner_selectable_output": True,
        }))
    readable.sort(key=lambda r: (r["record_type"], r["record_id"]))
    selection_rows.sort(key=lambda r: (r["record_type"], r["record_id"]))

    # Explicitly separate the 77 background-only route records from ordinary trained talents.
    background_routes = []
    for row in background_rows:
        sphere_name = row.get("sphere_requirement", "")
        if sphere_name == "Fencing":
            sphere_name = "The Piercing Needle"
        sid = sphere_name_to_id.get(sphere_name)
        br = {
            "background_route_record_id": row["record_id"],
            "display_name": row["display_name"],
            "canonical_sphere_id": sid,
            "canonical_sphere_name": sphere_name,
            "background_only": True,
            "ordinary_training_presentation": False,
            "selection_disposition": "BACKGROUND_ORIGIN_ONLY",
            "acquisition_route": "background-talent-selection",
            "source_text": row.get("full_description") or row.get("short_description") or "",
            "source_provenance": {
                "source_pack": SOURCE_PACK,
                "source_version": SOURCE_VERSION,
                "source_path": row["provenance_path"],
                "source_anchor": row["source_anchor"],
                "source_authority_sha256": AUTH_SHA,
                "source_file_sha256": sha256_file(auth / row["provenance_path"]) if (auth / row["provenance_path"]).is_file() else None,
            },
        }
        background_routes.append(commit_record(br))
    background_routes.sort(key=lambda r: r["background_route_record_id"])

    # Mixed candidate classification with independent unresolved re-examination.
    raw_by_id = {r["canonical_talent_id"]: r for r in catalog["records"]}
    qa_mixed_by_id = {r["record_id"]: r for r in qa_mixed}
    class_map = {
        "actual_talent": "CONFIRMED_SELECTABLE_TALENT",
        "cultivation_insight": "CULTIVATION_INSIGHT",
        "path_expression": "PATH_EXPRESSION",
        "variant_expression": "VARIANT_EXPRESSION",
        "sphere_base_ability": "BASE_SPHERE_ABILITY",
        "structural_label": "STRUCTURAL_HEADING",
        "sphere_route_anchor": "ROUTE_OR_CONTENT_FAMILY_ANCHOR",
        "sphere_rule": "OTHER_CONFIRMED_NON_TALENT",
        "descriptive_or_unclassified": "OTHER_CONFIRMED_NON_TALENT",
    }
    mixed_records = []
    unresolved_report_rows = []
    remaining_ambiguous = []
    for rid in sorted(product_auth["records"]):
        cls = product_auth["records"][rid]
        raw = raw_by_id[rid]
        qa = qa_mixed_by_id[rid]
        prior = cls.get("classification")
        if prior == "unresolved_candidate":
            classification, reason, context, ambiguous = classify_unresolved(raw, cls, comp_lines, comp_folded)
        else:
            classification = class_map[prior]
            reason = cls.get("reason") or qa.get("reason") or "Accepted QA2 classification independently retained."
            context = {"declared_source_refs": raw.get("source_refs") or []}
            ambiguous = False
        source_label = raw.get("canonical_source_sphere")
        mapped_label = "The Piercing Needle" if source_label == "Fencing" else ("Harvesting Gathering" if source_label == "Harvesting-Gathering" else source_label)
        canonical_sid = sphere_name_to_id.get(mapped_label)
        record = {
            "candidate_record_id": rid,
            "display_name": raw.get("canonical_talent_name"),
            "source_label": source_label,
            "mapped_canonical_sphere_id": canonical_sid,
            "qa2_prior_classification": prior,
            "cat1_classification": classification,
            "confirmed_selectable_talent": classification == "CONFIRMED_SELECTABLE_TALENT",
            "owner_selectable_output": classification == "CONFIRMED_SELECTABLE_TALENT",
            "reason": reason,
            "packet_type": raw.get("packet_type"),
            "catalog_role": raw.get("catalog_role"),
            "source_refs": raw.get("source_refs") or [],
            "source_context": context,
            "owner_ruling_id": RULING_ID if source_label == "Fencing" else None,
            "source_provenance": {
                "source_pack": SOURCE_PACK,
                "source_version": SOURCE_VERSION,
                "source_path": catalog_rel,
                "source_anchor": f"record:{rid}",
                "source_authority_sha256": AUTH_SHA,
                "source_file_sha256": sha256_file(catalog_path),
            },
        }
        mixed_records.append(commit_record(record))
        if prior == "unresolved_candidate":
            rr = {
                "candidate_record_id": rid,
                "display_name": raw.get("canonical_talent_name"),
                "source_label": source_label,
                "cat1_classification": classification,
                "reason": reason,
                "source_context": context,
                "included_in_canonical_selectable_registry": False,
            }
            unresolved_report_rows.append(rr)
            if ambiguous:
                remaining_ambiguous.append(rr)

    # Decision packets grouped by source label for remaining ambiguous rows.
    groups = defaultdict(list)
    for row in remaining_ambiguous:
        groups[row["source_label"]].append(row)
    decision_packets = []
    for source_label, rows in sorted(groups.items()):
        affected = [r["candidate_record_id"] for r in rows]
        packet = {
            "decision_packet_id": f"CAT1-DECISION-{norm_key(source_label).upper()}",
            "topic": f"Unresolved candidate identities under {source_label}",
            "source_text_context": [{"record_id": r["candidate_record_id"], "context": r["source_context"]} for r in rows],
            "affected_ids": affected,
            "options": [
                {"option": "RATIFY_AS_SELECTABLE_TALENT", "consequence": "Adds records to the canonical talent and membership counts; requires explicit reconciliation against the accepted 1,748 count and duplicate/identity review."},
                {"option": "MAP_TO_EXISTING_CANONICAL_TALENT", "consequence": "Preserves one unique identity and records the candidate ID as an alias/migration ID."},
                {"option": "CLASSIFY_AS_BASE_OR_STRUCTURAL", "consequence": "Keeps the row outside owner-selectable output and preserves it as rule/projection metadata."},
            ],
            "recommended_smallest_ruling": "Resolve stable identity against the exact source heading before changing the accepted selectable-talent count; until then keep the row quarantined outside owner-selectable output.",
            "materiality": "NON_BLOCKING_FOR_SAFE_1748_REGISTRY; BLOCKING_FOR_PROMOTION_OF_THESE_CANDIDATES",
        }
        decision_packets.append(commit_record(packet))

    # Add the owner ruling implementation packet.
    decision_packets.append(commit_record({
        "decision_packet_id": RULING_ID,
        "topic": "Fencing sphere identity",
        "status": "RESOLVED_BY_OWNER",
        "affected_ids": [t["canonical_talent_id"] for t in canonical_talents if t["legacy_source_sphere_label"] == "Fencing"],
        "resolution": "Fencing is a legacy/content-family alias under The Piercing Needle; no additional Sphere is created.",
        "source_text_context": [{"path": comp_rel, "line": 59836, "text": comp_lines[59835]}],
    }))
    decision_packets.sort(key=lambda r: r["decision_packet_id"])

    # Registry files.
    registries = {
        "canonical_spheres.v1.json": envelope("TianxiaCAT1.CanonicalSphereRegistry.v1", sphere_records, {"canonical_spheres": len(sphere_records)}),
        "sphere_aliases_and_labels.v1.json": envelope("TianxiaCAT1.SphereAliasRegistry.v1", label_records, {"extra_labels": len(label_records)}),
        "canonical_talents.v1.json": envelope("TianxiaCAT1.CanonicalTalentRegistry.v1", canonical_talents, {"confirmed_unique_selectable_talents": len(canonical_talents), "fencing_labelled_mapped": sum(1 for t in canonical_talents if t["legacy_source_sphere_label"] == "Fencing")}),
        "sphere_talent_memberships.v1.json": envelope("TianxiaCAT1.SphereTalentMembershipRegistry.v1", memberships, {"membership_edges": len(memberships)}),
        "mixed_candidate_classification.v1.json": envelope("TianxiaCAT1.MixedCandidateClassification.v1", mixed_records, {"mixed_candidate_rows": len(mixed_records), "classification_counts": dict(sorted(Counter(r["cat1_classification"] for r in mixed_records).items()))}),
        "background_origin_talent_routes.v1.json": envelope("TianxiaCAT1.BackgroundOriginTalentRoutes.v1", background_routes, {"background_only_routes": len(background_routes)}),
        "prerequisite_projection.v1.json": envelope("TianxiaCAT1.PrerequisiteProjection.v1", prereqs, {"talents": len(prereqs), "status_counts": dict(sorted(Counter(r["prerequisite_evaluation_status"] for r in prereqs).items()))}),
        "owner_readable_projection.v1.json": envelope("TianxiaCAT1.OwnerReadableProjection.v1", readable, {"records": len(readable), "description_status_counts": dict(sorted(Counter(r["description_status"] for r in readable).items()))}),
        "selection_dispositions.v1.json": envelope("TianxiaCAT1.SelectionDispositions.v1", selection_rows, {"records": len(selection_rows), "disposition_counts": dict(sorted(Counter(r["selection_disposition"] for r in selection_rows).items()))}),
        "unresolved_authority_decisions.v1.json": envelope("TianxiaCAT1.UnresolvedAuthorityDecisions.v1", decision_packets, {"decision_packets": len(decision_packets), "remaining_ambiguous_rows": len(remaining_ambiguous)}),
    }
    for fn, obj in registries.items():
        write_json(data_dir / fn, obj)

    # CSV owner/audit projections.
    write_csv(data_dir / "canonical_spheres.v1.csv", sphere_records)
    write_csv(data_dir / "canonical_talents.v1.csv", canonical_talents)
    write_csv(data_dir / "sphere_talent_memberships.v1.csv", memberships)
    write_csv(data_dir / "mixed_candidate_classification.v1.csv", mixed_records)
    write_csv(data_dir / "background_origin_talent_routes.v1.csv", background_routes)
    write_csv(data_dir / "prerequisite_projection.v1.csv", prereqs)
    write_csv(data_dir / "owner_readable_projection.v1.csv", readable)
    write_csv(data_dir / "unresolved_220_resolution_report.v1.csv", unresolved_report_rows)

    # Schemas.
    for fn, obj in schema_defs().items():
        write_json(schema_dir / fn, obj)

    # Provenance and evidence.
    source_paths = sorted({t["exact_source_path"] for t in canonical_talents} | {comp_rel, catalog_rel})
    provenance_records = []
    for rel in source_paths:
        p = auth / rel
        provenance_records.append({"source_path": rel, "exists": p.is_file(), "sha256": sha256_file(p) if p.is_file() else None, "bytes": p.stat().st_size if p.is_file() else None})
    write_json(evidence_dir / "SOURCE_PROVENANCE_REPORT.json", {"schema": "TianxiaCAT1.SourceProvenanceReport.v1", "source_authority_sha256": AUTH_SHA, "sources": provenance_records})
    write_json(evidence_dir / "FENCING_OWNER_RULING_IMPLEMENTATION.json", {
        "schema": "TianxiaCAT1.FencingMigrationEvidence.v1", "owner_ruling_id": RULING_ID,
        "canonical_sphere_id": sphere_name_to_id["The Piercing Needle"], "canonical_sphere_name": "The Piercing Needle",
        "separate_fencing_sphere_created": False,
        "fencing_labelled_talent_count": sum(1 for t in canonical_talents if t["legacy_source_sphere_label"] == "Fencing"),
        "mapped_talent_ids": [t["canonical_talent_id"] for t in canonical_talents if t["legacy_source_sphere_label"] == "Fencing"],
        "membership_duplication": False,
    })
    write_json(evidence_dir / "HARVESTING_COLLISION_RESOLUTION.json", {
        "schema": "TianxiaCAT1.HarvestingResolution.v1", "published_spelling": "Harvesting Gathering",
        "canonical_sphere_id": sphere_name_to_id["Harvesting Gathering"],
        "aliases": ["Harvesting-Gathering", "Harvesting and Gathering", "Harvesting Sphere", "Gathering Sphere", "Herb-Gathering Sphere"],
        "canonical_sphere_record_count": 1, "source_heading_line": section_ranges["Harvesting Gathering"][0],
    })
    write_json(evidence_dir / "UNRESOLVED_220_RESOLUTION_SUMMARY.json", {
        "schema": "TianxiaCAT1.Unresolved220Resolution.v1", "input_rows": len(unresolved_report_rows),
        "classification_counts": dict(sorted(Counter(r["cat1_classification"] for r in unresolved_report_rows).items())),
        "remaining_ambiguous_rows": len(remaining_ambiguous),
        "remaining_ambiguous_ids": [r["candidate_record_id"] for r in remaining_ambiguous],
        "selectable_exposure_count": 0,
    })
    write_json(evidence_dir / "PREREQUISITE_TYPING_STATUS_MATRIX.json", {"schema": "TianxiaCAT1.PrerequisiteTypingMatrix.v1", "status_counts": dict(sorted(Counter(r["prerequisite_evaluation_status"] for r in prereqs).items())), "records": [{"record_id": r["record_id"], "status": r["prerequisite_evaluation_status"], "safe": r["creator_selectability_can_be_evaluated_safely"]} for r in prereqs]})
    write_json(evidence_dir / "READABILITY_MATRIX.json", {"schema": "TianxiaCAT1.ReadabilityMatrix.v1", "status_counts": dict(sorted(Counter(r["description_status"] for r in readable).items())), "records": [{"record_id": r["record_id"], "record_type": r["record_type"], "status": r["description_status"]} for r in readable]})

    # Reports.
    write_text(report_dir / "00_CAT1_EXECUTIVE_SUMMARY.md", f"""# CAT1 Canonical Authority Overlay

Result candidate: `CAT1_CANONICAL_AUTHORITY_OVERLAY_READY`.

- Canonical published Spheres: **{len(sphere_records)}**.
- Canonical confirmed selectable talents: **{len(canonical_talents)}**.
- Canonical membership edges: **{len(memberships)}**.
- Fencing-labelled talents mapped to The Piercing Needle: **{sum(1 for t in canonical_talents if t['legacy_source_sphere_label']=='Fencing')}**.
- Background-only route records separated from ordinary training: **{len(background_routes)}**.
- Mixed candidate rows classified: **{len(mixed_records)}**.
- QA2 unresolved rows re-examined: **{len(unresolved_report_rows)}**; remaining authority-decision rows remain quarantined from selectable output.

No runtime, bootstrap, API, UI, GM Screen, combat, encounter, or C3C integration is included.
""")
    write_text(report_dir / "01_CANONICAL_SPHERE_INVENTORY.md", "# Canonical 85-Sphere Inventory\n\nThe exact registry is `data/canonical_spheres.v1.json` and `.csv`. No Fencing Sphere exists. The Piercing Needle owns the 39 confirmed Fencing-labelled talents. Harvesting Gathering is one canonical identity with hyphenated and conjunction aliases.")
    write_text(report_dir / "02_FENCING_MIGRATION.md", "# Fencing Migration\n\n`Fencing` is preserved as a legacy source label and alias. All 39 confirmed records retain their stable `TAL_FENCING_*` IDs and exact source provenance, but their canonical owning Sphere is `tianxia.sphere.the_piercing_needle`. No record or membership is duplicated.")
    write_text(report_dir / "03_HARVESTING_RESOLUTION.md", "# Harvesting Collision Resolution\n\nThe exact published heading is `Sphere of Harvesting Gathering` at line 38361. `Harvesting-Gathering` and `Harvesting and Gathering` resolve to `tianxia.sphere.harvesting_gathering`. Only one canonical Sphere record exists.")
    write_text(report_dir / "04_MIXED_CANDIDATE_RESOLUTION.md", f"# Mixed Candidate Classification\n\nAll 3,180 mixed rows are typed. The 220 QA2-unresolved rows were re-examined against exact current-compendium text. Rows without exact selectable authority are typed as generated/projection, structural, or base-ability rows. {len(remaining_ambiguous)} exact-heading identity questions remain quarantined as `AMBIGUOUS_REQUIRES_AUTHORITY_DECISION`; none appear in owner-selectable output.")
    write_text(report_dir / "05_KNOWN_LIMITATIONS.md", "# Known Limitations\n\n- This overlay does not install or expose catalogs at runtime.\n- Natural-language prerequisite logic is not broadly reinterpreted. Complex access/logical prose remains raw and may block safe creator evaluation.\n- Some source descriptions are absent from the accepted projection; source references are retained instead of fabricated copy.\n- Remaining exact-heading identity questions are decision packets, not selectable talents.\n- Linux product and native-Windows acceptance were not performed because runtime/UI integration is outside CAT1.")
    write_text(catroot / "integration/FUTURE_INTEGRATION_PLAN.md", "# Future Integration Plan\n\n1. Receive the completed C3B-R1 source and perform exact path-overlap review.\n2. Merge only the new `catalog_authority/cat1/` and `tests/test_cat1_*` paths.\n3. Add a read-only adapter from existing operational catalog services to CAT1 registries without changing stable IDs.\n4. Gate runtime installation on CAT1 validators, explicit unresolved-decision disposition, and source-hash match.\n5. Add Browse Rules and Character Creator projections only after separate UI/runtime authorization.\n6. Re-run Linux and native-Windows source-to-UI coverage as later checkpoints.\n\nDo not combine these steps with C3B-R1 bootstrap repair.")

    # Copy deterministic builder and validator source into overlay.
    shutil.copy2(Path(__file__), catroot / "tools/build_cat1_overlay.py")
    validator_src = '''from __future__ import annotations\nimport argparse, hashlib, json, re, unicodedata\nfrom pathlib import Path\n\ndef cb(o): return (json.dumps(o,sort_keys=True,ensure_ascii=False,separators=(\",\",\":\"))+\"\\n\").encode()\ndef verify_commit(r):\n b={k:v for k,v in r.items() if k!=\"record_commitment_sha256\"}; return hashlib.sha256(cb(b)).hexdigest()==r.get(\"record_commitment_sha256\")\ndef load(p): return json.loads(p.read_text(encoding=\"utf-8\"))\ndef main():\n ap=argparse.ArgumentParser(); ap.add_argument(\"root\"); a=ap.parse_args(); root=Path(a.root); d=root/\"catalog_authority/cat1/data\"\n spheres=load(d/\"canonical_spheres.v1.json\")[\"records\"]; talents=load(d/\"canonical_talents.v1.json\")[\"records\"]; edges=load(d/\"sphere_talent_memberships.v1.json\")[\"records\"]; labels=load(d/\"sphere_aliases_and_labels.v1.json\")[\"records\"]; mixed=load(d/\"mixed_candidate_classification.v1.json\")[\"records\"]; bg=load(d/\"background_origin_talent_routes.v1.json\")[\"records\"]\n assert len(spheres)==85; assert len(talents)==1748; assert len(edges)==1748; assert len(mixed)==3180; assert len(bg)==77\n assert not any(s[\"display_name\"]==\"Fencing\" for s in spheres)\n p=next(s for s in spheres if s[\"display_name\"]==\"The Piercing Needle\"); assert p[\"confirmed_selectable_talent_count\"]==39\n f=next(x for x in labels if x[\"label\"]==\"Fencing\"); assert f[\"canonical_sphere_id\"]==p[\"canonical_sphere_id\"]\n h=next(x for x in labels if x[\"label\"]==\"Harvesting-Gathering\"); assert h[\"canonical_sphere_id\"]==\"tianxia.sphere.harvesting_gathering\"\n assert sum(t[\"legacy_source_sphere_label\"]==\"Fencing\" and t[\"owning_canonical_sphere_id\"]==p[\"canonical_sphere_id\"] for t in talents)==39\n assert len({t[\"canonical_talent_id\"] for t in talents})==1748; assert len({(e[\"canonical_talent_id\"],e[\"canonical_sphere_id\"]) for e in edges})==1748\n assert all(verify_commit(r) for r in spheres+talents+edges+labels+mixed+bg)\n assert not any(r[\"cat1_classification\"]==\"AMBIGUOUS_REQUIRES_AUTHORITY_DECISION\" and r[\"owner_selectable_output\"] for r in mixed)\n print(json.dumps({\"result\":\"PASS\",\"spheres\":85,\"talents\":1748,\"edges\":1748,\"mixed\":3180,\"background_only\":77},sort_keys=True))\nif __name__==\"__main__\": main()\n'''
    write_text(catroot / "validators/validate_cat1_overlay.py", validator_src)
    write_text(catroot / "README.md", "# CAT1 New-Files-Only Overlay\n\nThis isolated tree contains canonical Sphere/talent authority data, schemas, validators, evidence, and a future integration plan. It intentionally has no runtime registration or UI wiring. Run `python catalog_authority/cat1/validators/validate_cat1_overlay.py <MERGE_OVERLAY_ROOT>`.\n")

    # Overlay manifest generated after all data/report files exist (except file-hash inventory itself).
    files = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "OVERLAY_FILE_HASHES.json":
            files.append({"path": p.relative_to(out).as_posix(), "sha256": sha256_file(p), "bytes": p.stat().st_size})
    overlay_manifest = {
        "schema": "TianxiaCAT1.OverlayManifest.v1",
        "checkpoint": "CAT1",
        "result": "CAT1_CANONICAL_AUTHORITY_OVERLAY_READY",
        "output_mode": "NEW_FILES_ONLY_OVERLAY",
        "source_baseline_sha256": C3B_SHA,
        "source_checkpoint_sha256": C3B_SOURCE_SHA,
        "source_authority_sha256": AUTH_SHA,
        "accepted_qa2_sha256": QA2_SHA,
        "owner_ruling_id": RULING_ID,
        "counts": {
            "canonical_spheres": len(sphere_records), "canonical_talents": len(canonical_talents), "memberships": len(memberships),
            "mixed_candidates": len(mixed_records), "background_only_routes": len(background_routes),
            "fencing_mapped": sum(1 for t in canonical_talents if t["legacy_source_sphere_label"] == "Fencing"),
            "remaining_ambiguous_candidates": len(remaining_ambiguous),
        },
        "runtime_integration": False, "ui_integration": False, "source_modification": False,
        "files": files,
    }
    write_json(catroot / "OVERLAY_MANIFEST.json", overlay_manifest)
    # Final per-file hash inventory including manifest, excluding itself.
    file_hashes = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "OVERLAY_FILE_HASHES.json":
            file_hashes.append({"path": p.relative_to(out).as_posix(), "sha256": sha256_file(p), "bytes": p.stat().st_size})
    write_json(catroot / "OVERLAY_FILE_HASHES.json", {"schema": "TianxiaCAT1.OverlayFileHashes.v1", "coverage_policy": "Every regular overlay file except this inventory itself.", "files": file_hashes})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--authority-root", required=True)
    ap.add_argument("--qa2-root", required=True)
    ap.add_argument("--c3b-source-root", required=True)
    ap.add_argument("--owner-ruling", required=True)
    ap.add_argument("--out", required=True)
    build(ap.parse_args())
