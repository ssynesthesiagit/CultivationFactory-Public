"""Read-only selector presentation shared by action, sheet and status surfaces."""
import re
import json
from pathlib import Path
from functools import lru_cache

from factory_authoring.record_display import record_display

# Default free-selection contract; owning plug-ins can replace its lifetime.
CHOICE_LINE = "Choosing this option takes no action and costs nothing; it stays selected until you change it."


@lru_cache(maxsize=1)
def _names():
    from .status_text import printed_rules
    names = {}
    for key, text in printed_rules().items():
        for heading in re.findall(r"(?m)^#+\s+(.+)$", text):
            names.setdefault(_name(heading), []).append(key)
    return names


def _name(text):
    text = re.sub(r"^CL\s*\d+\s*[-—–]\s*", "", text.strip())
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


@lru_cache(maxsize=1)
def _effect_sources():
    return json.loads((Path(__file__).parent / "rules/option_text_sources.json").read_text())


def setting_display(row, record=None):
    """Resolve ONE option record, preferring explicit provenance to unique headings.

    No ownership, selection, execution or AI candidate is changed. A missing
    source leaves the control's own handling instructions intact.
    """
    from .status_text import printed_rules
    params = row.get("parameters") or {}
    typed = params.get("typed") or {}
    feature, _, option = str(row.get("display_name") or row.get("label") or "").partition(":")
    section = option.strip()
    option = option.split(" — ", 1)[0].strip()
    rules = printed_rules()
    candidates = [f"printed_option:{option}", *list(params.get("shape_talents") or []),
                  params.get("augment_key"), (params.get("attack_modifier_setting") or {}).get("modifier"),
                  params.get("meld_talent"), typed.get("forged_from"), typed.get("source"), typed.get("option_of"),
                  record]
    candidates += [(_effect_sources().get(effect.get("type")) or {}).get("record")
                   for effect in typed.get("effects") or []]
    for key in candidates:
        display = record_display(key, section)
        if display:
            return display
    for name in (option, feature.strip()):
        matches = list(dict.fromkeys(_names().get(_name(name), [])))
        if len(matches) == 1:
            return record_display(matches[0], section)
    return None


def setting_context(row, own=""):
    """Builder handling plus one free-selection line; references never promise a choice."""
    from .ext import query
    from .ext.setting_choices import is_setting_action
    if not is_setting_action(row):
        return ""
    params = row.get("parameters") or {}
    parts = [str(params.get("setting_description") or ""), str(params.get("description") or own or "")]
    if params.get("inert"):
        if not parts[0]:
            parts.insert(0, "Rules reference only: this button does not select or store an option.")
    else:
        if params.get("zone_shape") and not params.get("shape_talents"):
            parts.append(f"Use {params.get('zone_name') or 'this area'} without any optional area talents.")
        lifetime = params.get("setting_lifetime") or next(
            (text for text in query("setting_lifetime", row) if isinstance(text, str) and text), "")
        parts.append("Choosing this option takes no action and costs nothing. " + lifetime if lifetime else CHOICE_LINE)
    return "\n\n".join(dict.fromkeys(part for part in parts if part))


def setting_text(row, fallback="", *, with_markup=False):
    """One shared card with the selector's own handling instructions first."""
    from .ext.setting_choices import is_setting_action
    if not is_setting_action(row):
        return fallback
    display = setting_display(row)
    if display:
        from .action_text import action_card_text
        return action_card_text(row, display)[0]
    return setting_context(row, fallback) or fallback
