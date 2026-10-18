"""Printed mechanic text and identity for every typed mechanic (no model logs named here, so public tests may import it).

Sources: the canonical catalog, Cultivation Insights, base-ability fixes, Path / Subpath / Foundation features, and the owner's text edits.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from factory_authoring.insight_sources import catalog_insight_sources  # noqa: E402

CATALOG = APP / "catalog_authority/cat3/generated/catalog_authority.v1.json"
BASE_ABILITY_SOURCES = APP / "authority/typed_mechanics/base_ability_sources.json"  # docket 2026-09-28: Dreamscape, Fragrance
OWNER_TEXT_EDITS = APP / "authority/typed_mechanics/owner_text_edits.json"  # owner 2026-09-29: printed lines struck


def _source(provenance: dict, text: str) -> dict:
    return {
        "path": provenance.get("source_path"),
        "line": provenance.get("source_line"),
        "file_sha256": provenance.get("source_file_sha256"),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def sources() -> list[dict]:
    """Every typed mechanic's printed text and identity, gathered one way for the builder,
    the MiMo tool and the review tool: Sphere talents and base abilities (canonical
    catalog), Cultivation Insights (the selected canonical source occurrence),
    Path features (path index sections) and Subpath / Tradition features (printed
    line ranges of the bundled compendia, checked against their file hashes)."""
    import zipfile

    catalog = json.loads(CATALOG.read_bytes())
    rows: list[dict] = []
    for row in catalog["talents"]:
        text = row.get("full_exact_source_text")
        if text:
            rows.append({"id": row["canonical_talent_id"], "name": row["display_name"], "kind": "talent", "text": text,
                         "sphere_id": row.get("owning_canonical_sphere_id"), "source": _source(row.get("source_provenance") or {}, text)})
    for row in catalog["sphere_base_ability_authority"]:
        text = row.get("effect") or ""
        rows.append({"id": row["candidate_record_id"], "name": row["display_name"], "kind": "base_ability", "text": text,
                     "sphere_id": row.get("mapped_canonical_sphere_id"), "source": _source(row.get("source_matrix_provenance") or {}, text)})
    rows.extend(catalog_insight_sources(catalog))
    # Base abilities the catalog read from the wrong heading or left out (docket 2026-09-28: Dreamscape, the Flower sphere's
    # Fragrance): their printed text from the compendium, with its path, line and hash.
    fixes = json.loads(BASE_ABILITY_SOURCES.read_text(encoding="utf-8")).get("abilities") or {} if BASE_ABILITY_SOURCES.is_file() else {}
    for record_id, fix in fixes.items():
        text = fix["text"]
        fixed = {"id": record_id, "name": fix["name"], "kind": "base_ability", "text": text, "sphere_id": fix.get("sphere_id"),
                 "source": {**_source({"source_path": fix["source"]["path"], "source_line": fix["source"]["line"],
                                       "source_file_sha256": fix["source"]["file_sha256"]}, text)},
                 **({"granted_with": list(fix["granted_with"])} if fix.get("granted_with") else {})}
        rows = [row for row in rows if row["id"] != record_id] + [fixed]
    for index_path in sorted((APP / "non_sphere_authority/authority").glob("*.path_index.p2a.json")):
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for feature in index.get("features") or []:
            text = "\n".join(section.get("source_markdown") or "" for section in feature.get("source_sections") or [])
            if not text.strip():
                continue
            section = (feature.get("source_sections") or [{}])[0]
            rows.append({"id": feature["canonical_id"], "name": feature["display_name"], "kind": "path_feature", "text": text,
                         "sphere_id": None, "path_id": index.get("canonical_id"),
                         "source": {"path": (index.get("source") or {}).get("path") or index_path.name, "line": section.get("source_line_start"),
                                    "file_sha256": (index.get("source") or {}).get("sha256"), "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}})
    bundle = zipfile.ZipFile(APP / "BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip")
    files: dict[str, list[str] | None] = {}
    index = json.loads((APP / "non_sphere_authority/authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json").read_text(encoding="utf-8"))
    for entry in index["entries"]:
        for feature in entry.get("feature_progression") or []:
            source = feature.get("source") or {}
            member = "HF05ZVK_R1H_Phase2I_HF2/" + str(source.get("factory_source_path") or "")
            if member not in files:
                try:
                    raw = bundle.read(member)
                    files[member] = raw.decode("utf-8").splitlines() if hashlib.sha256(raw).hexdigest() == source.get("source_file_sha256") else None
                except KeyError:
                    files[member] = None
            lines = files[member]
            if not lines or not source.get("line_start"):
                continue
            text = "\n".join(lines[int(source["line_start"]) - 1:int(source.get("line_end") or source["line_start"])])
            rows.append({"id": feature["canonical_id"], "name": feature["display_name"], "kind": "subpath_feature", "text": text,
                         "sphere_id": None, "subpath_id": entry.get("canonical_id"),
                         "source": {"path": source.get("factory_source_path"), "line": source.get("line_start"),
                                    "file_sha256": source.get("source_file_sha256"), "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}})
    # Optional owner-authored progressions share the builder's catalog source and
    # then pass through the same owner text edit/review pipeline as sealed rows.
    from non_sphere_authority.owner_subpaths import owner_feature_sources
    additions = owner_feature_sources(APP)
    if {row["id"] for row in rows} & {row["id"] for row in additions}:
        raise ValueError("Owner-authored Subpath feature collides with a sealed mechanic")
    rows.extend(additions)
    # Foundation features (owner 2026-09-25): the 30 playable Foundations' printed features,
    # by stage (non_sphere_authority/foundation_features.py reads the same verified catalog
    # records foundation_mechanics.py uses for initial/passive mechanics).
    from non_sphere_authority import foundation_features as ff

    for foundation_id, record, feature in ff.iter_all_features():
        text = "\n".join(f"**{key}:** {value}" for key, value in feature["fields"].items())
        text = f"#### {feature['name']}\n\n{text}\n"
        rows.append({"id": ff.feature_id(foundation_id, feature["name"]), "name": feature["name"], "kind": "foundation_feature",
                     "text": text, "sphere_id": None, "foundation_id": foundation_id, "stage": feature["stage"],
                     "source": {"path": "non_sphere_authority/authority/" + record["source"]["artifact"], "line": record["source"]["section_number"],
                                "file_sha256": record["source"]["artifact_sha256"], "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}})
    # The owner's own edits to printed text (factory_authoring/owner_text_edits.py): "remove" lines struck (owner 2026-09-29,
    # Meld: "remove that text"), then "replace" pairs (owner 2026-09-30, Qi Armor +3 -> +5). The sealed catalog keeps the old
    # wording until the next catalog release. A row with "replace" pairs keeps the text they were applied to (typing_text):
    # build() types that text and carries the typing onto the edited one.
    from factory_authoring.owner_text_edits import apply_edit, replacements

    edits = owner_text_edits()
    for row in rows:
        edit = edits.get(row["id"])
        if not edit:
            continue
        removed, text, problems = apply_edit(row["text"], edit)
        row["text"] = text
        row["source"] = {**row["source"], "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
        if text != removed:
            row["typing_text"], row["owner_replace"] = removed, replacements(edit)
            row["owner_retype"] = bool(edit.get("retype"))
        if problems:
            row["owner_edit_problems"] = problems
    return rows


def owner_text_edits() -> dict[str, dict]:
    return (json.loads(OWNER_TEXT_EDITS.read_text(encoding="utf-8")).get("records") or {}) if OWNER_TEXT_EDITS.is_file() else {}


def source_texts() -> dict[str, str]:
    return {row["id"]: row["text"] for row in sources()}
