"""Public, read-only action descriptions shared by compilation and tabletop UI.

The compiler uses these descriptions for pre-fight choices; tabletop menus use
the same interface for contextual plug-in help and printed rules text.
"""
from __future__ import annotations

from typing import Any, Callable
from functools import lru_cache
from copy import deepcopy


def _resolved(row: dict[str, Any], *, fallback: Callable[[dict[str, Any]], str] | None,
              with_markup: bool) -> str:
    """The one description resolution every action surface shares.

    ``with_markup`` keeps the printed ``**Label:**`` fields and their line
    structure so the shared hover layout (combat/hover_text.py) can split them
    into labelled lines; without it the text is the flattened prose every
    existing caller already receives, unchanged.
    """
    return _composition_note(row, _resolved_base(row, fallback=fallback, with_markup=with_markup))


def _composition_note(row: dict[str, Any], text: str) -> str:
    """Say which turn slot a modified/composed use spends (owner 2026-10-15: "what spent my action?").

    A modifier variant such as "Demon Mark + Daemonic Augment: Bonus Damage" is the base ability with an
    extra modifier folded into the same use; its button carries no clue that the base spends the Bonus Action
    and the augment rides along. The card names the base and the slot once, in plain words. Presentation only:
    nothing is persisted. Inert for a plain ability (no modifier, no " + " in the label).
    """
    from .action_economy import SPEND
    parameters = row.get("parameters") or {}
    typed = parameters.get("typed") or {}
    modifier = typed.get("modifier") if isinstance(typed.get("modifier"), dict) else None
    label_name = str(row.get("display_name") or row.get("label") or row.get("name") or "")
    if not modifier or not modifier.get("name") or " + " not in label_name:
        return text
    base = label_name.split(" + ", 1)[0].strip()
    slot = SPEND.get(str(row.get("economy") or ""))
    note = (f"{modifier['name']} rides on {base}: together they spend your {slot}." if slot
            else f"{modifier['name']} rides on {base}: together they need no action of their own.")
    return " ".join(part for part in (str(text).strip(), note) if part)


def _button_text(row):
    """A row's own words win over generic record prose: explicit, then plug-in."""
    from . import ext
    from .player_text import explain_cp
    explicit = (row.get("parameters") or {}).get("description")
    text = explicit or next((text for text in ext.run("button_description", row)
                             if isinstance(text, str) and text), "")
    return explain_cp(str(text or ""))


def action_card_text(row, display):
    """Return (live text, context) without changing the shared reference card.

    Replacement/explicit help describes this button, not the unmodified record.
    Keep it ahead of the card and in the DOM context, including the turn slot.
    Each part retains the charged-cost correction even if both have Cost fields.
    """
    from .ext.setting_choices import is_setting_action
    from .option_text import setting_context
    from .decision_text import cost_as_charged, reviewed_printed_cost
    from .player_text import clean, explain_cp
    own = _button_text(row)
    context = setting_context(row, own) if is_setting_action(row) else _composition_note(row, own)
    # The reference HTML explains abbreviations with <abbr>; plain consumers
    # (including model seats) need the same explanations without that markup.
    body = display["text"] + f"\n\nSource ability: {display['title']}."
    context, body = ("\n".join(clean(explain_cp(line)) for line in text.splitlines())
                     for text in (context, body))
    if "costs" in row and not is_setting_action(row):
        printed = reviewed_printed_cost(row)
        context, body = (cost_as_charged(text, row["costs"], printed) if text else text
                         for text in (context, body))
    parts = (body, context) if is_setting_action(row) else (context, body)
    return "\n\n".join(part for part in parts if part), context


def _resolved_base(row: dict[str, Any], *, fallback: Callable[[dict[str, Any]], str] | None,
                   with_markup: bool) -> str:
    from .player_text import explain_cp
    from .status_text import printed_excerpt

    parameters = row.get("parameters") or {}
    typed = parameters.get("typed") or {}
    own = _button_text(row)
    from .ext.setting_choices import is_setting_action
    if is_setting_action(row):
        from .option_text import setting_text
        help_text = own or (fallback(row) if fallback else "")
        return setting_text(row, str(help_text or ""), with_markup=with_markup)
    if own:
        return own

    # A selected Meld names a talent different from the shared action source.
    candidates = [parameters.get("meld_talent"), typed.get("forged_from"), typed.get("source"), typed.get("option_of")]
    for record in candidates:
        if record:
            text = printed_excerpt(str(record), with_markup=with_markup)
            if text:
                return explain_cp(text)
    if fallback:
        text = fallback(row)
        if text:
            return explain_cp(str(text))
    return ""


def describe_action(row: dict[str, Any], *, fallback: Callable[[dict[str, Any]], str] | None = None) -> str:
    """Describe an action row using plug-in context, selected printed text, then fallback.

    ``row`` is a compiled action or a presentation-only row with ``parameters``.
    The optional fallback lets tabletop add its compiled evidence without making
    compiler callers depend on tabletop internals.
    """
    return _resolved(row, fallback=fallback, with_markup=False)


def layout_action(row: dict[str, Any], *, fallback: Callable[[dict[str, Any]], str] | None = None,
                  extra: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    """One record card (or native layout) plus this use's charged cost and clocks.

    Carded rows retain the complete structured ``mechanics`` for decision seats;
    their default ``text`` and ``player_card`` remain the player-facing overview.
    Native rows use that same mechanical layout directly.
    """
    from .ext.setting_choices import is_setting_action
    from .decision_text import cost_as_charged, costs_text, reviewed_printed_cost
    display = action_display(row)
    markup = _resolved(row, fallback=fallback, with_markup=True)
    charged = "costs" in row and not is_setting_action(row)
    if charged:
        markup = cost_as_charged(markup, row["costs"], reviewed_printed_cost(row))
    subject = str(row.get("display_name") or row.get("label") or row.get("name") or "Ability")
    mechanics = deepcopy(_layout_resolved(subject, markup, tuple(extra)))
    if display:
        markup, context = action_card_text(row, display)
        from factory_authoring.record_display import record_display
        params = row.get("parameters") or {}
        modifier = ((params.get("typed") or {}).get("modifier") or {}).get("id")
        records = [modifier, *list(params.get("shape_talents") or [])]
        related = {card["record_id"]: card for key in records if key and (card := record_display(key))
                   and card["record_id"] != display["record_id"]}
        cost = costs_text(row["costs"]) if charged else ""
        return {"text": " ".join(part for part in (markup, *extra) if part),
                "player_card": display, "related_cards": list(related.values()), "mechanics": mechanics,
                "context": " ".join(part for part in (context, f"Cost: {cost}." if cost else "", *extra) if part)}
    return mechanics


def action_display(row):
    """Record presentation for every action/variant/chip, separate from compilation."""
    from factory_authoring.record_display import record_display
    from .ext.setting_choices import is_setting_action
    from .option_text import setting_display
    if is_setting_action(row):
        return setting_display(row)
    params = row.get("parameters") or {}
    typed = params.get("typed") or {}
    source = str(row.get("source_definition_id") or "")
    compiled = source.split(".", 2)[-1].split("#", 1)[0].split("+", 1)[0] if source.startswith("action:typed.") else ""
    # Native stat-block actions carry the summoning ability as provenance, not
    # as their own record. Their button provider describes the creature's use.
    if compiled.startswith("summon."):
        return None
    for record in (params.get("meld_talent"), typed.get("forged_from"), typed.get("source"), typed.get("option_of"), compiled):
        display = record_display(record, typed.get("option_label") or "")
        if display:
            return display
    label = str(row.get("display_name") or row.get("label") or row.get("name") or "")
    feature, _, option = label.partition(":")
    return record_display(feature.strip(), option.strip())


def action_digest(row):
    """Legacy audit API only; runtime cards use record_display, never digests."""
    from . import ext
    from .tooltip_digest import digest_for
    params = row.get("parameters") or {}
    typed = params.get("typed") or {}
    if params.get("description") or any(typed.get(key) for key in ("variant_of", "modifier", "replacement")):
        return None
    if any(isinstance(text, str) and text for text in ext.run("button_description", row)):
        return None
    display = action_display(row)
    label = str(row.get("display_name") or row.get("label") or row.get("name") or "")
    return digest_for(display["record_id"], label) if display else None


@lru_cache(maxsize=2048)
def _layout_resolved(subject: str, markup: str, extra: tuple[str, ...]) -> dict[str, Any]:
    """Cache formatting after live rule/plug-in/cost resolution, by all its inputs.

    No row, hook result or authority identity is cached: they resolve on every
    call. A changed cost, selected source, plug-in sentence or usage explanation
    changes the resolved strings. The public caller copies mutable hover lists.
    """
    from . import hover_text
    from .status_text import plain

    _lead, fields = hover_text.split_fields(markup)
    retain_markup = bool(fields) or hover_text.has_structural_blocks(markup)
    return hover_text.layout(
        subject=subject, kind="ability", markup=markup if retain_markup else "",
        summary=hover_text.summary_for(subject, fields),
        extra=([plain(markup)] if not retain_markup and markup.strip() else []) + list(extra))
