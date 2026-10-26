"""Effect-owned names shared by compiler attachments and runtime plug-ins.

Call name_damage_effects when creating a source's effects, before composing
them with other sources. The compile hook is only a fallback for legacy or
plug-in effects without an owner name; it never replaces an explicit label.
"""
from . import hook


def name_damage_effects(effects, label):
    """Copy a source's effects and fill missing extra/deferred damage names."""
    def walk(value):
        if isinstance(value, list):
            return [walk(row) for row in value]
        if isinstance(value, dict):
            row = {key: walk(child) for key, child in value.items()}
            if row.get("type") == "extra_damage" or (row.get("type") == "damage" and row.get("deferred")):
                row.setdefault("damage_label", label)
            return row
        return value

    return walk(effects)


@hook("compile_action")
def label_riders(action, info):
    typed = action.parameters.get("typed") or {}
    # Only the outer action is known here. Source-owned rows were named before
    # attachment; never infer their owner from the last modifier on the action.
    replacement = name_damage_effects(typed, action.display_name)
    if replacement != typed:
        return action.model_copy(update={"parameters": {**action.parameters, "typed": replacement}})
    return None
