"""Authority-bound base Sphere Effects shared by creation-time and table forging.

These use the same stable mechanic IDs as combat, with published text and source
hashes from the typed authority. Knowing a Sphere grants its base abilities.
"""
from typing import Any, Iterable


def base_effect_rows(sphere_ids: Iterable[str], mechanics: dict[str, Any],
                     printed: dict[str, str]) -> list[dict[str, Any]]:
    known = set(sphere_ids)
    rows = []
    for effect_id, mechanic in sorted(mechanics.items()):
        if (mechanic.get("kind") != "base_ability" or mechanic.get("sphere_id") not in known
                or not mechanic.get("effects")):
            continue
        binding = mechanic.get("source") or {}
        source_hash = binding.get("text_sha256") or binding.get("file_sha256")
        if not binding.get("path") or not source_hash:
            continue
        rows.append({
            "talent_id": effect_id, "sphere_id": mechanic["sphere_id"],
            "display_name": mechanic.get("name") or effect_id,
            "record_hash": source_hash,
            "source": {"source_id": "typed_mechanics_authority", "path": binding["path"],
                       "source_hash": source_hash},
            "published_text": printed.get(effect_id, ""),
        })
    return rows
