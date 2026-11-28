"""Build the sealed Dao Divinity / Immortal Art authority.

The authority is deliberately assembled from the small published constituent
files rather than from the DM-facing combined document.  The builder checks
the manifest and every SHA sidecar before copying the exact source text into
the sealed pack.  Constructors therefore have one immutable numeric table and
one source-backed chassis for each active Divinity.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from app.core import sha256_bytes, sha256_json  # noqa: E402
from tools.aspect_terms import TERMS  # noqa: E402


ASSEMBLY_ROOT = HERE.parent / "LocalSources" / "08_immortal_arts" / "Tianxia_Dao_Aspect_Immortal_Arts_DM_Facing_Assembly_2026_07_04"
SEPARATE_ROOT = ASSEMBLY_ROOT / "01_AI_SEPARATE_SOURCES"
MANIFEST_PATH = ASSEMBLY_ROOT / "02_AUDIT_MANIFEST" / "Tianxia_Dao_Aspect_Immortal_Arts_DM_Facing_Assembly_Manifest_2026_07_04.json"
MANIFEST_SIDECAR = MANIFEST_PATH.with_name(MANIFEST_PATH.name + ".sha256.txt")
AUDIT_PATH = ASSEMBLY_ROOT / "02_AUDIT_MANIFEST" / "Tianxia_Dao_Aspect_Immortal_Arts_DM_Facing_Assembly_Audit_2026_07_04.md"
AUDIT_SIDECAR = AUDIT_PATH.with_name(AUDIT_PATH.name + ".sha256.txt")
CORE_PATH = HERE.parent / "LocalSources" / "01_core_rules" / "Tianxia_Core_Rules_Reference_v0_2C.md"

AUTHORITY_SCHEMA = "TianxiaFoundry.ImmortalArtAuthority.v1"
PACK_ID = "tianxia.immortal_art_authority.r1"

_ASPECT_ID_RE = re.compile(r"[^a-z0-9]+")
_INT_RE = re.compile(r"(?:^|[^0-9])([0-9]+)(?:[^0-9]|$)")

_ASPECT_SEMANTICS = {
    "Destruction": ["damage", "destroy", "ruin"],
    "Binding": ["bind", "restrain", "lock"],
    "Revelation": ["reveal", "detect", "identity"],
    "Concealment": ["conceal", "hide", "veil"],
    "Fortification": ["protect", "reinforce", "guard"],
    "Restoration": ["restore", "heal", "repair"],
    "Transformation": ["transform", "change", "form"],
    "Command": ["command", "control", "order"],
    "Transport": ["move", "cross", "teleport"],
    "Reflection": ["reflect", "return", "rebound"],
    "Domain": ["domain", "boundary", "field", "division", "crossing"],
    "Creation": ["create", "construct", "manifest", "body", "vessel"],
    "Entropy": ["decay", "decline", "ruin"],
    "Fate": ["fate", "branch", "prophecy"],
    "Time": ["time", "delay", "duration"],
    "Soul": ["soul", "identity", "spirit"],
    "Heaven": ["heaven", "mandate", "permission", "law"],
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sidecar_claim(path: Path) -> tuple[str, str]:
    sidecar = path.with_name(path.name + ".sha256.txt")
    if not sidecar.is_file():
        raise SystemExit(f"missing SHA sidecar: {sidecar}")
    parts = sidecar.read_text(encoding="utf-8").strip().split()
    if len(parts) < 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
        raise SystemExit(f"invalid SHA sidecar: {sidecar}")
    claimed_name = " ".join(parts[1:])
    if claimed_name != path.name:
        raise SystemExit(f"sidecar filename mismatch: {sidecar} claims {claimed_name!r}")
    return parts[0], sha256_bytes(sidecar.read_bytes())


def _slug(value: str) -> str:
    return _ASPECT_ID_RE.sub("_", value.strip().casefold()).strip("_")


def _number(value: str) -> int | None:
    match = _INT_RE.search(value.replace("+", ""))
    return int(match.group(1)) if match else None


def _table_row(line: str, source_line: int) -> dict[str, Any] | None:
    """Parse one row of a Factor cost table."""
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) < 3 or cells[0].casefold() in {"factor", "burden", "mode", "value", "size / type", "source structure"}:
        return None
    if all(re.fullmatch(r"[-: ]+", cell or " ") for cell in cells):
        return None
    mandate = _number(cells[1])
    cp = _number(cells[2])
    nonnumeric_cost = any(
        marker in " ".join(cells[1:3]).casefold()
        for marker in ("gm-set", "gm set", "variable", "unsupported")
    )
    if mandate is None and cp is None and not nonnumeric_cost:
        return None
    return {
        "factor_id": _slug(cells[0]),
        "display_name": cells[0],
        "mandate_cost": mandate,
        "cp_cost": cp,
        "published_cost": {"mandate": cells[1], "cp": cells[2]},
        "mechanical_chassis": cells[3] if len(cells) > 3 else "",
        "source_line": source_line,
        "requires_gm_review": mandate is None or cp is None,
    }


def _factor_rows(text: str) -> list[dict[str, Any]]:
    """Extract Factor rows without confusing durability/value tables for costs."""
    lines = text.splitlines()
    starts: list[int] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match and "factor" in match.group(2).casefold():
            starts.append(index)
    if not starts:
        return []
    start = starts[0]
    end = len(lines)
    # A new level-2 section ends the factor chapter; nested Factor Details
    # headings remain part of the source-backed chassis.
    for index in range(start + 1, len(lines)):
        if re.match(r"^##\s+", lines[index]):
            end = index
            break
    rows: list[dict[str, Any]] = []
    for index in range(start, end):
        line = lines[index]
        if line.startswith("|"):
            row = _table_row(line, index + 1)
            if row is not None:
                rows.append(row)
    # Other current chassis use a heading for each Factor and put the numeric
    # authority on a following ``Mandate / CP`` line.  Keep the entire exact
    # heading block as the chassis so a prose Factor cannot become a numeric
    # shortcut with no operating procedure.
    heading_indices = [
        index
        for index in range(start, end)
        if re.match(r"^###\s+", lines[index])
    ]
    for position, index in enumerate(heading_indices):
        next_index = heading_indices[position + 1] if position + 1 < len(heading_indices) else end
        next_h2 = next((candidate for candidate in range(index + 1, next_index) if re.match(r"^##\s+", lines[candidate])), next_index)
        next_index = min(next_index, next_h2)
        body = "\n".join(lines[index + 1:next_index]).strip()
        mandate_match = re.search(
            r"\*\*Mandate\s*/\s*CP:\*\*\s*(?P<mandate>\+?\d+|variable|GM-set)\s*/\s*(?P<cp>\+?\d+|variable|GM-set)",
            body,
            re.IGNORECASE,
        )
        if not mandate_match:
            continue
        heading = re.sub(r"^\d+(?:\.\d+)*\s+", "", re.sub(r"^###\s+", "", lines[index]).strip())
        mandate_raw = mandate_match.group("mandate")
        cp_raw = mandate_match.group("cp")
        parse = lambda value: int(value.lstrip("+")) if value.lstrip("+").isdigit() else None
        exact_section = "\n".join(lines[index:next_index]).strip() + "\n"
        rows.append(
            {
                "factor_id": _slug(heading),
                "display_name": heading,
                "mandate_cost": parse(mandate_raw),
                "cp_cost": parse(cp_raw),
                "published_cost": {"mandate": mandate_raw, "cp": cp_raw},
                "mechanical_chassis": exact_section,
                "source_line": index + 1,
                "source_line_end": next_index,
                "source_section_sha256": sha256_bytes(exact_section.encode("utf-8")),
            }
        )
    # Several full chassis use a prose factor header instead of a table
    # (``**Mandate / CP:** +1 / +1 CP``).  Capture that same published
    # numeric authority while retaining the complete prose in source_text.
    block = "\n".join(lines[start:end])
    prose = re.compile(
        r"(?ms)^\*\*Factor:\*\*\s*(?P<name>[^\n]+?)\s*\n\s*\*\*Mandate\s*/\s*CP:\*\*\s*\+?(?P<mandate>\d+)\s*/\s*\+?(?P<cp>\d+)\s*CP"
    )
    for match in prose.finditer(block):
        name = match.group("name").strip()
        row = {
            "factor_id": _slug(name),
            "display_name": name,
            "mandate_cost": int(match.group("mandate")),
            "cp_cost": int(match.group("cp")),
            "published_cost": {"mandate": f"+{match.group('mandate')}", "cp": f"+{match.group('cp')} CP"},
            "mechanical_chassis": "",
            "source_line": start + block[: match.start()].count("\n") + 1,
        }
        rows.append(row)
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        unique.setdefault(row["factor_id"], row)
    return list(unique.values())


def _burden_row(line: str, source_line: int) -> dict[str, Any] | None:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) < 4 or cells[0].casefold() in {"burden", "factor"} or all(re.fullmatch(r"[-: ]+", cell or " ") for cell in cells):
        return None
    def parse(value: str) -> int | None:
        value = value.strip().lstrip("+")
        return int(value) if value.isdigit() else None
    stability = parse(cells[1])
    credit = parse(cells[2])
    if stability is None and credit is None:
        return None
    return {
        "burden_id": _slug(cells[0]),
        "display_name": cells[0],
        "stability_credit": stability,
        "cp_credit": credit,
        "published_credit": {"stability": cells[1], "cp": cells[2]},
        "effect": cells[3],
        "source_line": source_line,
    }


def _burden_rows(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if (m := re.match(r"^##\s+(.+?)\s*$", line)) and "burden" in m.group(1).casefold()]
    if not starts:
        return []
    start = starts[0]
    end = next((index for index in range(start + 1, len(lines)) if re.match(r"^##\s+", lines[index])), len(lines))
    rows: list[dict[str, Any]] = []
    for index in range(start, end):
        if lines[index].startswith("|"):
            row = _burden_row(lines[index], index + 1)
            if row is not None:
                rows.append(row)
    return rows


def _table_rows(text: str, *, source_line_offset: int = 0) -> list[dict[str, Any]]:
    """Backward-compatible helper for callers that need all numeric tables."""
    lines = text.splitlines()
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not line.startswith("|") or "|" not in line[1:]:
            continue
        row = _table_row(line, index + 1 + source_line_offset)
        if row is not None:
            rows.append(row)
    return rows


def _headings(text: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            result.append({"level": len(match.group(1)), "heading": match.group(2), "source_line": number})
    return result


def _aspect_source(entry: dict[str, Any]) -> dict[str, Any]:
    path = SEPARATE_ROOT / entry["folder"] / entry["filename"]
    if not path.is_file():
        raise SystemExit(f"manifest source is missing: {path}")
    source_text = path.read_text(encoding="utf-8")
    actual = _digest(path)
    expected = entry["sha256"]
    sidecar_claim, sidecar_file_hash = _sidecar_claim(path)
    if actual != expected or sidecar_claim != expected:
        raise SystemExit(f"source hash mismatch: {path} expected={expected} actual={actual} sidecar={sidecar_claim}")
    old_header = "Dao Aspect"
    divinity_headers = "|".join(map(re.escape, (old_header, TERMS["dao_divinity"][old_header])))
    aspect_match = re.search(rf"^\*\*(?:{divinity_headers}):\*\*\s*(.+?)\s*$", source_text, re.MULTILINE)
    mandate_match = re.search(r"^\*\*Mandate Cost:\*\*\s*([0-9]+)", source_text, re.MULTILINE)
    cp_match = re.search(r"^\*\*CP Modifier:\*\*\s*\+?([0-9]+)\s*CP", source_text, re.MULTILINE)
    function_match = re.search(r"^\*\*Function:\*\*\s*(.+?)\s*$", source_text, re.MULTILINE)
    if not aspect_match or not mandate_match or not cp_match or not function_match:
        raise SystemExit(f"incomplete Aspect header: {path}")
    aspect_name = aspect_match.group(1).strip()
    sections = _headings(source_text)
    return {
        "aspect_id": "tianxia.dao_aspect." + _slug(aspect_name),
        "display_name": aspect_name,
        "category": entry["category"],
        "mandate_cost": int(mandate_match.group(1)),
        "cp_modifier": int(cp_match.group(1)),
        "function": function_match.group(1).strip(),
        "semantic_tags": list(_ASPECT_SEMANTICS.get(aspect_name, [])),
        "source": {
            "source_id": "source.dao_aspect." + _slug(aspect_name),
            "path": str(path.relative_to(HERE.parent)),
            "anchor": "document:full-text",
            "source_hash": actual,
            "sidecar_path": str(path.with_name(path.name + ".sha256.txt").relative_to(HERE.parent)),
            "sidecar_file_sha256": sidecar_file_hash,
        },
        "source_text": source_text,
        "source_text_sha256": actual,
        "sections": sections,
        "factors": _factor_rows(source_text),
        "burdens": _burden_rows(source_text),
        # Some current chassis express their Factors as prose tables with a
        # ``Mandate / CP`` line rather than a four-column ``Factor`` table.
        # The exact source text and headings are the completeness commitment;
        # parsed rows are an aid for numeric rows where the format permits it.
        "chassis_complete": bool(sections and source_text.strip()),
    }


def _unsigned_authority() -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest_claim, manifest_sidecar_hash = _sidecar_claim(MANIFEST_PATH)
    manifest_hash = _digest(MANIFEST_PATH)
    if manifest_claim != manifest_hash:
        raise SystemExit(f"manifest hash mismatch: expected={manifest_claim} actual={manifest_hash}")
    audit_claim, audit_sidecar_hash = _sidecar_claim(AUDIT_PATH)
    audit_hash = _digest(AUDIT_PATH)
    if audit_claim != audit_hash:
        raise SystemExit(f"audit hash mismatch: expected={audit_claim} actual={audit_hash}")
    if int(manifest.get("active_aspects_count", 0)) != 17 or manifest.get("retired_excluded") != ["Chaos"]:
        raise SystemExit("manifest does not describe the required seventeen active Aspects")
    source_entries = manifest.get("sources")
    if not isinstance(source_entries, list) or len(source_entries) != 18:
        raise SystemExit("manifest must contain exactly the opening plus seventeen Aspect sources")
    opening = next((entry for entry in source_entries if entry.get("category") == "opening"), None)
    if not isinstance(opening, dict):
        raise SystemExit("manifest has no opening rules source")
    # The opening has no Aspect header.  Keep its exact text and source proof
    # under the shared-rules section instead of weakening the source check.
    opening_path = SEPARATE_ROOT / opening["folder"] / opening["filename"]
    opening_text = opening_path.read_text(encoding="utf-8")
    opening_hash = _digest(opening_path)
    opening_claim, opening_sidecar_hash = _sidecar_claim(opening_path)
    if opening_hash != opening["sha256"] or opening_claim != opening_hash:
        raise SystemExit("opening source hash or sidecar mismatch")
    aspects = [_aspect_source(entry) for entry in source_entries if entry.get("category") != "opening"]
    if len(aspects) != 17 or {row["display_name"] for row in aspects} != {
        "Destruction", "Binding", "Revelation", "Concealment", "Fortification", "Restoration", "Transformation", "Command", "Transport", "Reflection", "Domain", "Creation", "Entropy", "Fate", "Time", "Soul", "Heaven"
    }:
        raise SystemExit("manifest Aspect set is incomplete or includes an inactive Aspect")
    core_hash = _digest(CORE_PATH)
    if core_hash != "07dc678e2c686e191f7da34b959964cfe535c6368019ffaf37227eb39d87ad10":
        raise SystemExit(f"Core source hash mismatch: {core_hash}")
    return {
        "schema_version": AUTHORITY_SCHEMA,
        "pack_id": PACK_ID,
        "authority_classification": "AUTHENTICATED_CANONICAL_SOURCE",
        "active_aspects": [row["aspect_id"] for row in aspects],
        "source_manifest": {
            "path": str(MANIFEST_PATH.relative_to(HERE.parent)),
            "sha256": manifest_hash,
            "sidecar_path": str(MANIFEST_SIDECAR.relative_to(HERE.parent)),
            "sidecar_file_sha256": manifest_sidecar_hash,
            "package": manifest["package"],
            "active_aspects_count": manifest["active_aspects_count"],
            "retired_excluded": list(manifest["retired_excluded"]),
        },
        "assembly_audit": {
            "path": str(AUDIT_PATH.relative_to(HERE.parent)),
            "sha256": audit_hash,
            "sidecar_path": str(AUDIT_SIDECAR.relative_to(HERE.parent)),
            "sidecar_file_sha256": audit_sidecar_hash,
            "verdict": manifest.get("verdict"),
        },
        "core_sources": {
            "core_rules": {
                "source_id": "source.core_rules_reference.v0_2c",
                "path": str(CORE_PATH.relative_to(HERE.parent)),
                "anchor": "section:17.4-17.6:lines:3858-3905",
                "source_hash": core_hash,
            }
        },
        "opening_rules": {
            "source": {
                "source_id": "source.dao_aspect.opening",
                "path": str(opening_path.relative_to(HERE.parent)),
                "anchor": "document:full-text",
                "source_hash": opening_hash,
                "sidecar_path": str(opening_path.with_name(opening_path.name + ".sha256.txt").relative_to(HERE.parent)),
                "sidecar_file_sha256": opening_sidecar_hash,
            },
            "source_text": opening_text,
            "source_text_sha256": opening_hash,
            "sections": _headings(opening_text),
        },
        "shared_rules": {
            "construction_formula": "Base Source Effect + Dao Aspect + Factors + Burdens = Immortal Art",
            "principle_correspondence": {
                "direct": {"label": "Direct", "bridge_factors": 0},
                "adjacent": {"label": "Adjacent", "bridge_factors": 1},
                "distant_unlike": {"label": "Distant / Unlike", "bridge_factors": 2},
                "contrary": {"label": "Contrary", "bridge_factors_minimum": 3, "gm_review_required": True},
                "unsupported": {"label": "Unsupported", "legal": False},
            },
            "sphere_count_modifier": {"1": 0, "2": 1, "3": 2, "4_plus": 3},
            "source_package_modifier": {"1": 0, "2": 1, "3": 2, "4_plus": 3},
            "mandate_complexity": "aspect_cost + factor_cost + bridge_factor_cost + sphere_count_modifier + special_scale_cost",
            "realm_thresholds": [
                {"realm": "Nascent Soul", "mandate_threshold": 3, "source": "opening:section:3:table:realm-thresholds"},
                {"realm": "Immortal", "mandate_threshold": 6, "source": "opening:section:3:table:realm-thresholds"},
                {"realm": "Earth Immortal", "mandate_threshold": 9, "source": "opening:section:3:table:realm-thresholds"},
                {"realm": "Heaven Immortal", "mandate_threshold": 12, "source": "opening:section:3:table:realm-thresholds"},
                {"realm": "True Immortal", "mandate_threshold": 15, "source": "opening:section:3:table:realm-thresholds"},
            ],
            "standard_cl20_realm_alias": {
                "input": "True Immortality",
                "canonical_tier": "Immortal",
                "rule_id": "tianxia.core.realm.cl20.true_immortality_to_immortal_mandate_tier.v1",
                "source": "core:section:2:realm-table-and-section:17.6",
            },
            "heaven_pressure": "2 * max(0, mandate_complexity - mandate_threshold)",
            "factor_escalation": {"0": 0, "1": 1, "2": 3, "3": 7, "4": 15, "5": 31, "6_plus": "gm_review_required"},
            "refinement_dc": {
                "minimum": "10 + mandate_complexity + source_sphere_count + aspect_count",
                "full": "10 + mandate_complexity + source_sphere_count + aspect_count + factor_escalation + heaven_pressure - stability_credit",
                "stability_floor": "10 + mandate_complexity + source_sphere_count + aspect_count",
            },
            "activation_cp": {
                "formula": "max(1, base_source_cp + aspect_cp + factor_cp + bridge_cp - burden_cp_credit)",
                "zero_requires_explicit_approval": True,
                "resource_rule_source": "source.core_rules_reference.v0_2c§3.2:lines:725-735",
                "path_resources": {
                    "body_refining": "Stamina",
                    "qi_cultivation": "Qi",
                    "spirit_awakening": "Resonance",
                },
            },
            "research_and_materials": {"research_days_per_complexity": 5, "material_gp_per_complexity_squared": 250},
            "refinement_check": {
                "formula": "d20 + proficiency_bonus + path_ability_modifier",
                "path_abilities": {"body_refining": "CON", "qi_cultivation": ["INT", "CHA"], "spirit_awakening": "WIS"},
            },
            "action_surface_fields": [
                "action_type", "range", "target", "area", "duration", "trigger", "trigger_frequency", "save_or_check", "attack_roll", "dc_basis", "effect", "success", "failure", "success_by_5", "failure_by_5", "counterplay", "cleanup", "limits", "resource_name", "resource_cost", "gm_review_required",
            ],
            "source_requirements": {
                "required_action_fields": ["action_type", "range", "target", "duration", "effect", "resource_name", "resource_cost"],
                "required_resolution_fields": ["trigger", "trigger_frequency", "save_or_check", "success", "failure", "counterplay", "cleanup"],
                "reject_placeholder_phrases": ["as primary sphere prints", "as source prints", "tbd", "unknown", "not recorded", "define later"],
                "passive_sources_allowed": False,
            },
            "universal_factors": {
                "bridge": {
                    "factor_id": "bridge",
                    "display_name": "Bridge Factor",
                    "mandate_cost": 1,
                    "cp_cost": 1,
                    "mechanical_chassis": "The source must state the bounded relation, target legality, action economy, resolution, counterplay, and cleanup that make the unlike Factor executable.",
                    "source": {"source_id": "source.dao_aspect.opening", "anchor": "section:4:principle-correspondence"},
                }
            },
            "supported_source_routes": [
                {
                    "aspect_id": "tianxia.dao_aspect.creation",
                    "factor_id": "construct_puppet_body_creation",
                    "required_source_tags": ["body", "construct", "manifest"],
                    "mode": "complete_created_subject_action_surface",
                },
                {
                    "aspect_id": "tianxia.dao_aspect.domain",
                    "factor_id": "domain_lock",
                    "required_source_tags": ["boundary", "division", "crossing"],
                    "mode": "complete_domain_boundary_action_surface",
                },
                {
                    "aspect_id": "tianxia.dao_aspect.domain",
                    "factor_id": "domain_authority",
                    "required_source_tags": ["domain", "field", "boundary"],
                    "mode": "complete_domain_action_surface",
                },
            ],
        },
        "aspects": aspects,
        "opening_source_verified": True,
        "manifest_sources_verified": True,
        "sidecars_verified": True,
        # Retain the manifest's exact rows so review can compare all 18
        # constituent paths without trusting a generated display label.
        "manifest_source_entries": manifest["sources"],
        "opening_manifest_entry": opening,
        "verified_opening_helper_sha256": sha256_bytes(opening_text.encode("utf-8")),
    }


def build() -> dict[str, Any]:
    unsigned = _unsigned_authority()
    sealed = {**unsigned, "seal_sha256": sha256_json(unsigned)}
    destination = HERE / "authority" / "Tianxia_Immortal_Art_Authority_R1.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(sealed, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{destination} {sealed['seal_sha256']}")
    return sealed


if __name__ == "__main__":
    build()
