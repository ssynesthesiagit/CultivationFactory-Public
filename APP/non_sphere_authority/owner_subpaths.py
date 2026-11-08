"""Owner-authored subpaths shared by the builder and typed-authority builder.

The sealed P2B index stays intact. Optional ``authority/owner_subpaths.d/*.json``
files supply additional complete progressions, with their original rules text.
Additions never change the sealed authority's commitment.
Records and their source commitments travel in the ordinary locked snapshots.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from app.core import FoundryError

PATHS = {"tianxia.path.qi_cultivation", "tianxia.path.body_refining", "tianxia.path.spirit_awakening"}
TIERS = (3, 6, 10, 14, 18)


def load_owner_subpaths(app: Path, existing_ids=()) -> tuple[list[dict], dict[str, str]]:
    """Validated additions plus relative-file SHA256s; reject collisions, never overwrite.

    Each document has schema ``Tianxia.OwnerSubpaths.v1``, an independent
    ``tianxia.owner.subpaths.*`` pack ID/version, and ``entries`` in P2B
    shape. Every feature carries ``source_markdown``. Source hashes are derived
    from the actual document and text, never accepted from input placeholders.
    """
    rows, commitments, seen = [], {}, set(existing_ids)
    feature_ids = set()
    for path in sorted((app / "non_sphere_authority/authority/owner_subpaths.d").glob("*.json")):
        raw = path.read_bytes()
        document = json.loads(raw)
        if (document.get("schema") != "Tianxia.OwnerSubpaths.v1"
                or not isinstance(document.get("entries"), list)
                or not str(document.get("pack_id", "")).startswith("tianxia.owner.subpaths.")
                or not isinstance(document.get("pack_version"), str) or not document["pack_version"]):
            raise FoundryError("OWNER_SUBPATH_DOCUMENT_INVALID", "An owner-authored Subpath document is incomplete.", status_code=500)
        relative = path.relative_to(app).as_posix()
        digest = hashlib.sha256(raw).hexdigest()
        commitments[relative] = digest
        for row_index, original in enumerate(document["entries"]):
            row = deepcopy(original)
            rid, parent = row.get("canonical_id"), row.get("owning_path_id")
            features = row.get("feature_progression") or []
            if (not isinstance(rid, str) or not rid.startswith("tianxia.subpath.") or rid in seen
                    or parent not in PATHS or not row.get("display_name")
                    or type(row.get("catalog_order")) is not int
                    or tuple(f.get("granted_at_cl") for f in features) != TIERS
                    or (row.get("prerequisites") or {}).get("minimum_cl") != 3
                    or not isinstance(row.get("access"), dict)):
                raise FoundryError("OWNER_SUBPATH_RECORD_INVALID", "An owner-authored Subpath has invalid identity, ownership or progression.", details={"record_id": rid}, status_code=500)
            seen.add(rid)
            for feature_index, feature in enumerate(features):
                fid, text = feature.get("canonical_id"), feature.get("source_markdown")
                if (not isinstance(fid, str) or not fid.startswith(rid + ".feature.") or fid in feature_ids
                        or not feature.get("display_name") or not isinstance(text, str) or not text.strip()):
                    raise FoundryError("OWNER_SUBPATH_FEATURE_INVALID", "An owner-authored Subpath feature has no unique identity or rules text.", status_code=500)
                feature_ids.add(fid)
                feature["source"] = {
                    "source_kind": "owner_subpath_json_text",
                    "feature_id": fid,
                    "json_pointer": f"/entries/{row_index}/feature_progression/{feature_index}/source_markdown",
                    # Bounds identify decoded Markdown lines in this exact JSON
                    # string, not physical lines in the surrounding JSON file.
                    "line_start": 1, "line_end": len(text.splitlines()),
                    "factory_source_path": relative, "corpus_path": relative,
                    "source_file_sha256": digest,
                    "section_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "excerpt": text,
                }
            rows.append(row)
    return rows, commitments


def published_owner_section(app: Path, source) -> str:
    """Projector/constructed-arts reader for an authenticated owner JSON field.

    Only validated documents in the registered owner Subpath directory qualify.
    Verify file, feature, JSON pointer, decoded text bounds and section hash.
    No source locator can redirect this reader to an arbitrary runtime file.
    """
    if source.get("source_kind") != "owner_subpath_json_text":
        return ""
    rows, _ = load_owner_subpaths(app)
    keys = ("source_kind", "feature_id", "json_pointer", "line_start", "line_end",
            "factory_source_path", "source_file_sha256", "section_sha256")
    for row in rows:
        for feature in row["feature_progression"]:
            expected = feature["source"]
            if all(source.get(key) == expected[key] for key in keys):
                return feature["source_markdown"]
    return ""


def owner_feature_sources(app: Path) -> list[dict]:
    """Typed builder sources; ordinary owner_text_edits apply after this step."""
    rows, _ = load_owner_subpaths(app)
    return [{"id": f["canonical_id"], "name": f["display_name"], "kind": "subpath_feature",
             "text": f["source_markdown"], "sphere_id": None, "subpath_id": row["canonical_id"],
             "source": {**f["source"], "path": f["source"]["factory_source_path"], "line": 1,
                        "file_sha256": f["source"]["source_file_sha256"],
                        "text_sha256": f["source"]["section_sha256"]}}
            for row in rows for f in row["feature_progression"]]
