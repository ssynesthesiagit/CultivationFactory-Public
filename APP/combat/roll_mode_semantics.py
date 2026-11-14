"""Required roll selectors shared by execution, area compilation and rider previews.

Used by typed_executor, effect_harm, rider_value, factory_compiler,
typed_reactions and life_state. Text derivation belongs to the authority build;
code-built effects must supply the same field explicitly.
"""


def require_roll_target(effect, source_id=None):
    """Return the selector (possibly null), or identify an unsealed effect loudly."""
    source = source_id or effect.get("source_id") or effect.get("source_definition_id") or "<unknown source>"
    def invalid(field):
        raise ValueError(f"{effect.get('type')} effect from {source} requires valid roll_target{field}")

    if "roll_target" not in effect:
        raise ValueError(f"{effect.get('type')} effect from {source} requires roll_target")
    target = effect["roll_target"]
    if target is None:
        return None
    if not isinstance(target, dict):
        invalid("")
    kinds = (None, "attack", "incoming_attack", "opportunity_attack", "check", "concentration", "save", "death_save")
    if "kind" not in target or target["kind"] not in kinds:
        invalid(".kind")

    def strings(obj, field, prefix):
        if field in obj and (not isinstance(obj[field], list) or
                             not all(isinstance(item, str) for item in obj[field])):
            invalid(prefix + field)

    for field in ("checks", "against", "abilities"):
        strings(target, field, ".")
    if target["kind"] == "check" and "checks" not in target:
        invalid(".checks")
    for field in ("next", "first"):
        if field in target and not isinstance(target[field], bool):
            invalid("." + field)
    if "preview" in target:
        preview = target["preview"]
        if not isinstance(preview, dict):
            invalid(".preview")
        if preview.get("kind") not in ("attack", "save", "check"):
            invalid(".preview.kind")
        if not isinstance(preview.get("group"), str):
            invalid(".preview.group")
    if "inside" in target:
        inside = target["inside"]
        if not isinstance(inside, dict):
            invalid(".inside")
        for field in ("saves", "checks"):
            strings(inside, field, ".inside.")
        for field in ("exclude", "muffles"):
            if field in inside and not isinstance(inside[field], bool):
                invalid(".inside." + field)
    return target


def roll_mode_harmful(effect, source_id=None):
    """Incoming Advantage harms; incoming Disadvantage protects. Outgoing is inverse."""
    target = require_roll_target(effect, source_id)
    incoming = target is not None and target["kind"] == "incoming_attack"
    return (effect.get("type") == "advantage") if incoming else (effect.get("type") == "disadvantage")
