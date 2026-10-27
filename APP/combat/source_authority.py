"""Owning-Path Source CL sealing for native projections and the portable compiler.

Applied before action transforms derive zones/authority profiles, and again to
the completed bundle for generated child rows. Character-level scaling stays
separate; sheets without recorded per-feature authority are unchanged.
"""


def stamp_source_levels(node, levels):
    """Stamp typed numbers recursively from a feature -> owning-Path CL map."""
    if isinstance(node, list):
        for child in node:
            stamp_source_levels(child, levels)
    elif isinstance(node, dict):
        feature = node.get("option_of") or node.get("feature_id") or node.get("source")
        if isinstance(feature, str) and isinstance(node.get("numbers"), dict):
            level = levels.get(feature.split("#", 1)[0])
            if level is not None:
                node["numbers"] = {**node["numbers"], "source_cl": level}
        for child in node.values():
            stamp_source_levels(child, levels)
