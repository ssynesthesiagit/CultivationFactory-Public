"""Persisted selector descriptions shared by every setting ability.

Reuse the public table button builder's owner-rule descriptions rather than
duplicate ability implementations. Only an owned, explicitly setting-only
action can describe its stored condition. This query never changes fight state.
"""
import re
from typing import Any
from . import hook
from .setting_choices import is_setting_action


def _words(text: str) -> str:
    """Match printed names across punctuation without interpreting ability ids."""
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def selector_rule_section(text: str, name: str) -> str:
    """Keep an unambiguous named subsection and its upgrades, not sibling/build rules.

    Used by persisted setting descriptions, including older sealed actions.
    Ambiguous or absent headings retain the full source rather than guess.
    """
    lines = text.splitlines()
    headings = [(index, len(match[1]), _words(match[2]))
                for index, line in enumerate(lines)
                if (match := re.match(r"^(#{1,6})\s+(.+)$", line))]
    wanted = _words(name)
    matches = [(index, level) for index, level, title in headings
               if wanted and (title == wanted or title.startswith(wanted + " "))]
    if len(matches) != 1:
        return text
    start, level = matches[0]
    end = next((index for index, depth, _ in headings if index > start and depth <= level), len(lines))
    return "\n".join(lines[start:end]).strip()


def selector_source_rules(bundle: dict[str, Any], action: Any, data: dict[str, Any],
                          source_record: str | None = None) -> tuple[list[str], bool]:
    """Resolve owned selector text and whether a named subsection narrows it.

    Shared by this setting hook and generated_status_text, which defers its
    parent-feature fallback when the setting hook supplies a specific section.
    """
    from ..status_text import printed_rules

    rules = printed_rules()
    owned = set()
    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)
        elif isinstance(value, str) and value in rules:
            owned.add(value)
    collect(bundle.get("typed_passives") or [])
    collect(bundle.get("typed_reactions") or [])
    for item in bundle.get("action_catalog") or []:
        collect(str(item.get("source_definition_id") or "").split(".", 2)[-1].split("#", 1)[0])
        typed = (item.get("parameters") or {}).get("typed") or {}
        collect({key: typed.get(key) for key in ("source", "option_of", "forged_from")})
    selected = set()
    def references(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                references(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                references(child)
        elif isinstance(value, str) and value in rules:
            selected.add(value)
    references(action.parameters)
    references(data)
    name = re.sub(r"^(Shape|Augment|Choose)\s+", "", action.display_name.partition(":")[0])
    # The generated catalog supplies missing provenance for older actions only
    # when it identifies a specific selector section. Leave other fallbacks alone.
    if source_record in rules and selector_rule_section(rules[source_record], name) != rules[source_record]:
        references(source_record)
    wanted = _words(name)
    matches = [key for key in sorted(owned) if wanted and wanted in _words(rules[key].splitlines()[0])]
    if not matches:
        # Several selectors name a procedure inside their owning ability.
        matches = [key for key in sorted(owned) if wanted and wanted in _words(rules[key])]
    sources = [rules[key] for key in dict.fromkeys([*matches, *sorted(selected)])]
    scoped = [selector_rule_section(text, name) for text in sources]
    return scoped, scoped != sources


@hook("status_description")
def setting_status_description(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    source = row.get("source_definition_id")
    action = engine.action_catalog.get(source)
    if holder is None or action is None or action.owner_id != holder.entity_id:
        return None
    if not is_setting_action(action):
        return None
    bundle = next((b for b in engine.typed_bundle_documents if b.get("actor_id") == holder.entity_id), None)
    if bundle is None:
        return None
    from ..tabletop import setting_button_description
    from ..decision_text import plain

    description = setting_button_description(action.model_dump(mode="json"), bundle)
    feature = action.display_name.partition(":")[0]
    from .generated_status_text import SOURCES
    key = str(row.get("condition_id") or "").removeprefix("condition:typed.")
    printed, scoped = selector_source_rules(bundle, action, data, SOURCES.get(key))
    # Generic button descriptions can include the entire parent feature too.
    # A named subsection is the selector's source-backed description instead.
    from ..status_text import markup
    parts = [] if scoped else [plain(description)]
    labelled: list[str] = []
    for index, rule in enumerate(printed):
        rule = plain(rule)
        if rule not in "\n\n".join(parts):
            parts.append(rule)
            labelled.append(markup(printed[index]))
    text = "\n\n".join(parts).replace("CP", "cultivation points (your Path resource)")
    label = action.display_name if scoped else (data.get("label") or action.display_name)
    # The same scoped rules with their printed "**Label:**" fields intact, so the
    # shared hover layout shows this selector's own fields instead of the parent
    # ability's whole printed card (which would offer the other options and the
    # parent's permanent-choice limit as if they applied to this one). The card is
    # led by the player-facing label rather than the source heading, which is the
    # internal choice id ("Mountain-Rending: deny_reactions") and must never be
    # shown to a player.
    card = "\n\n".join(line for block in labelled
                       for line in block.split("\n") if not line.lstrip().startswith("#"))
    card = "\n\n".join(part for part in (f"Selected setting: {label}.", card) if part) \
        .replace("CP", "cultivation points (your Path resource)")
    # An ability's supplied choice text includes its own lifetime restrictions;
    # older sealed bundles retain this text too. Only ordinary selectors use
    # the shared changeable-setting explanation.
    handling = action.parameters.get("setting_description") or (
        "Choosing this setting costs no action or resource. It stays selected until you change it; "
        "the ability's own cost and limits apply when triggered.")
    return {"text": f"Selected setting: {label}." + ("" if scoped else f" {text}"),
            # Replace earlier whole-feature readings only when the selector
            # identifies its own printed section; preserve other status text.
            **({"rules": text, "markup": card} if scoped else {}),
            "source_ability": feature,
            "handling": plain(handling).replace("CP", "cultivation points (your Path resource)")}
