"""Source-effective passive compilation for native mixed-attainment characters.

Used by factory_compiler for compile_passives providers (e.g. Terrain Attunement
and Wind Walker). Providers remain pure transforms with the entire ownership
set, so prerequisites and combinations are never hidden. Numeric variants run
only at character compilation, never during combat or menu enumeration.
"""
from copy import deepcopy


def compile_passives(rows, info, numbers_by_source):
    """Seal each feature's rows using its own numbers, preserving default rows.

    Existing pure hooks need not understand a new numeric-map API. Evaluate one
    isolated variant per distinct nondefault number set, then take only that
    variant's source-owned rows. The default pass controls unrelated/source-less
    rows. Preserve default order and retain newly admitted variant-only rows.
    """
    from . import ext

    variants = []
    for source, numbers in numbers_by_source.items():
        if numbers == info["numbers"]:
            continue
        group = next((group for group in variants if group[0] == numbers), None)
        if group is None:
            group = (numbers, set())
            variants.append(group)
        group[1].add(source)
    if not variants:
        return ext.transform("compile_passives", rows, info)

    defaults = ext.transform("compile_passives", deepcopy(rows), deepcopy(info))
    replacements = {}
    for numbers, sources in variants:
        variant_info = deepcopy(info)
        variant_info["numbers"] = dict(numbers)
        compiled = ext.transform("compile_passives", deepcopy(rows), variant_info)
        for source in sorted(sources):
            replacements[source] = [row for row in compiled if row.get("feature_id") == source]

    # Replace in place rather than grouping all rows of a source together:
    # different providers can append interleaved rows whose priority matters.
    last = {row.get("feature_id"): index for index, row in enumerate(defaults)}
    remaining = {source: iter(replacement) for source, replacement in replacements.items()}
    result = []
    for index, row in enumerate(defaults):
        source = row.get("feature_id")
        if source not in replacements:
            result.append(row)
            continue
        replacement = next(remaining[source], None)
        if replacement is not None:
            result.append(replacement)
        if index == last[source]:
            result.extend(remaining[source])
    for source, replacement in remaining.items():
        if source not in last:
            result.extend(replacement)
    return result
