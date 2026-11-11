"""Canonical Background-Origin acquisition for the combat Origin plug-in.

The sheet's selected Background and Origin must agree with the bundled native
Background authority. Public and Background-scoped IDs bind only by that exact
selection, as in character_builder.origin_insight_route_binding. This reader
does not accept cultivation Insights, Foundation Origins, names or prose.
"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import zipfile

APP = Path(__file__).resolve().parents[1]
PREFIX = "tianxia.origin_insight."
SOURCE = "09_RULES/Source_Text/Tianxia_PHB_Origin_Insights_v0_4_READABILITY_SELF_CONTAINED.md"


@lru_cache(maxsize=1)
def source_records():
    """Bundled authored sections; hashes exclude headings and strip outer space."""
    archive = APP / "BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
    with zipfile.ZipFile(archive) as bundle:
        names = [name for name in bundle.namelist() if name.endswith('/' + SOURCE)]
        if len(names) != 1:
            raise ValueError("Origin source must have one bundled authority")
        text = bundle.read(names[0]).decode("utf-8-sig")
    result = {}
    for title, section in re.findall(r"^## \d+\. ([^\n]+)\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        result[PREFIX + slug] = {"name": title, "source_path": SOURCE,
                               "section_sha256": hashlib.sha256(section.strip().encode()).hexdigest()}
    return result


@lru_cache(maxsize=1)
def background_options():
    authority = json.loads((APP / "non_sphere_authority/authority/Background_Core_Authority_v1.json").read_text())
    return {row["background_id"]: frozenset(
        PREFIX + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        for name in row["origin_insight"]["suggested_options"])
        for row in authority["backgrounds"]}


def selected_origin(owner_sheet):
    """Return one exact selected canonical acquisition, or None on any mismatch."""
    block = owner_sheet.get("background_and_origin") or {}
    if not isinstance(block, dict):
        return None
    background = block.get("background") or {}
    origin = block.get("origin_insight") or {}
    if not all(isinstance(row, dict) for row in (block, background, origin)):
        return None
    backgrounds = [value for value in (block.get("background_record_id"), background.get("background_id")) if value]
    if not backgrounds or any(value != backgrounds[0] for value in backgrounds):
        return None
    background_id = backgrounds[0]
    if not isinstance(background_id, str) or background_id not in background_options():
        return None
    selected = [value for value in (block.get("origin_record_id"), origin.get("origin_insight_id")) if value]
    if not selected or any(not isinstance(value, str) for value in selected):
        return None
    native_prefix = background_id + ".origin_insight."
    canonical = []
    for value in selected:
        if value.startswith(native_prefix):
            value = PREFIX + value[len(native_prefix):]
        if value not in background_options()[background_id] or value not in source_records():
            return None
        canonical.append(value)
    if any(value != canonical[0] for value in canonical):
        return None
    return {"feature_id": canonical[0], "background_id": background_id, **source_records()[canonical[0]]}
