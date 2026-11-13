"""Required roll selectors shared by execution, area compilation and rider previews.

Used by typed_executor, effect_harm, rider_value, factory_compiler,
typed_reactions and life_state. Text derivation belongs to the authority build;
code-built effects must supply the same field explicitly.
"""


def require_roll_target(effect, source_id=None):
    """Return the selector (possibly null), or identify an unsealed effect loudly."""
    try:
        return effect["roll_target"]
    except KeyError:
        source = source_id or effect.get("source_id") or effect.get("source_definition_id") or "<unknown source>"
        raise ValueError(f"{effect.get('type')} effect from {source} requires roll_target") from None


def roll_mode_harmful(effect, source_id=None):
    """Incoming Advantage harms; incoming Disadvantage protects. Outgoing is inverse."""
    target = require_roll_target(effect, source_id)
    incoming = target is not None and target["kind"] == "incoming_attack"
    return (effect.get("type") == "advantage") if incoming else (effect.get("type") == "disadvantage")
