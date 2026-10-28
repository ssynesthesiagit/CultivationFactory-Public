"""Exact native Path mechanics bindings, independent of display-card authority.

Acquisition packets keep their original event meaning. These bindings establish
mechanical text authority only; they grant no feature or character advancement.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from app.core import FoundryError, sha256_bytes, sha256_json

_INDEXES = {
    "tianxia.path.body_refining": "body_refining.path_index.p2a.json",
    "tianxia.path.qi_cultivation": "qi_cultivation.path_index.p2a.json",
    "tianxia.path.spirit_awakening": "spirit_awakening.path_index.p2a.json",
}
_AUTHORITY = "authenticated_native_path_index"


def _invalid(message: str, record_id: Any) -> FoundryError:
    return FoundryError("COMMAND4_NATIVE_SOURCE_INVALID", message, details={"record_id": record_id})


def native_path_binding(root_dir: Path, record_id: str) -> dict[str, Any] | None:
    """Derive a feature binding from the server's authenticated P2A authority."""
    path_id = next((pid for pid in _INDEXES if record_id.startswith(pid + ".feature.")), None)
    if path_id is None:
        return None
    authority_root = root_dir / "non_sphere_authority" / "authority"
    identity_bytes = (authority_root / "NS1R_AUTHORITY_IDENTITIES.json").read_bytes()
    identity = json.loads(identity_bytes)
    if identity.get("operative_pairwise_authority_rows") != 0 or identity.get("audit_rows_runtime_consumed") is not False:
        raise _invalid("The native authority identity is not the accepted runtime contract.", record_id)
    index_name = _INDEXES[path_id]
    metadata = identity.get("files", {}).get(index_name)
    index_bytes = (authority_root / index_name).read_bytes()
    if not isinstance(metadata, Mapping) or metadata.get("sha256") != sha256_bytes(index_bytes) or metadata.get("size") != len(index_bytes):
        raise _invalid("The native Path index does not match its server authority identity.", record_id)
    index = json.loads(index_bytes)
    if index.get("canonical_id") != path_id or index.get("publication_status") != "current_canonical_player_path":
        raise _invalid("The native Path index has a conflicting identity or publication status.", record_id)
    matches = [row for row in index.get("features", []) if isinstance(row, Mapping) and row.get("canonical_id") == record_id]
    if len(matches) != 1:
        raise _invalid("The feature must resolve uniquely in its native Path index.", record_id)
    feature = matches[0]
    text = feature.get("effective_rules_text") or feature.get("source_rules_text")
    if not isinstance(text, str) or not text.strip() or not isinstance(feature.get("display_name"), str):
        raise _invalid("The native feature has no complete mechanical source text.", record_id)
    return {
        "authority": _AUTHORITY,
        "record_id": record_id,
        "owner_path_id": path_id,
        "name": feature["display_name"],
        "source": {
            "path": "non_sphere_authority/authority/" + index_name,
            "anchor": f"path-feature:{path_id}:{record_id}",
            "sha256": sha256_bytes(index_bytes),
        },
        "authority_identity_sha256": sha256_bytes(identity_bytes),
        "feature_sha256": sha256_json(feature),
        "source_text_sha256": sha256_bytes(text.strip().encode("utf-8")),
        "full_description": text.strip(),
        "published_source": index.get("source"),
        "grants_acquisition": False,
    }


def validate_native_path_candidate(root_dir: Path, candidate: Mapping[str, Any]) -> dict[str, Any] | None:
    """Re-derive producer evidence; a copied display card is never sufficient."""
    supplied = candidate.get("native_source_binding")
    if supplied is None:
        return None
    record_id = candidate.get("record_id")
    if not isinstance(record_id, str):
        raise _invalid("A native source candidate requires an exact feature ID.", record_id)
    expected = native_path_binding(root_dir, record_id)
    if expected is None or supplied != expected:
        raise _invalid("The native source binding differs from independently derived server authority.", record_id)
    if candidate.get("source") != expected["source"] or candidate.get("name") != expected["name"] or candidate.get("full_description") != expected["full_description"]:
        raise _invalid("The candidate source, name and complete text must match its native authority.", record_id)
    return expected
