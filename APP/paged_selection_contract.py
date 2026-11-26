"""The frozen contract for a selection slot whose options arrive as pages.

An ordinary menu step shows three pages of options.  A slot that publishes a
chain of option windows needs more, otherwise a later window is unreachable
while the character is being created: the controller asks for the next page,
hits the ordinary three-page ceiling, and the whole run is failed.

Stage 1 publishes the contract on a decision slot as ``selection_semantics``.
The delegated choice envelope copies it into ``paged_selection_slots``, and
the AI controller reads that frozen map before serving a page.  Nothing here
reads the live catalog, so a saved run keeps the contract it was frozen with.

Used by ``stage1.service`` (publish), ``character_creation.delegated_choice_authority``
(freeze), and the creation controller (serve).
"""
from __future__ import annotations

from typing import Any, Mapping

#: ``selection_semantics`` value for a slot that offers a bounded chain of
#: option windows instead of one fixed list.
PAGED_WINDOW_SEMANTICS = "paged_insight_windows"

#: Minimum ceiling retained for requests using the original window contract.
MAX_PAGES_PER_PAGED_SLOT = 6

#: Key carrying ``{slot_id: {"max_pages": int}}`` in the frozen envelope.
PAGED_SELECTION_SLOTS_KEY = "paged_selection_slots"


def paged_slot_contract(slot: Any) -> dict[str, Any] | None:
    """Return the sealed paging contract for one Stage 1 decision slot.

    ``None`` for every ordinary slot, which keeps the controller's behaviour
    unchanged for prompts frozen before this contract existed.
    """
    if not isinstance(slot, Mapping) or slot.get("selection_semantics") != PAGED_WINDOW_SEMANTICS:
        return None
    # Each continuation page uses eleven choices plus its Other options button.
    # Include room for the optional Skip choice. This is a finite bound derived
    # from the authenticated frozen catalog, rather than a truncation ceiling.
    return {"max_pages": max(MAX_PAGES_PER_PAGED_SLOT, (len(slot.get("choices") or []) + 10) // 11)}


def paged_max_pages(request: Any, envelope: Any, slot_id: str, default: int) -> int:
    """Pages this slot may serve, read only from frozen request authority.

    ``default`` is the caller's ordinary page ceiling.  A request frozen
    before the paged-window contract carries no such entry and keeps it.
    """
    for source in (envelope, request):
        contracts = source.get(PAGED_SELECTION_SLOTS_KEY) if isinstance(source, Mapping) else None
        if not isinstance(contracts, Mapping):
            continue
        contract = contracts.get(slot_id)
        pages = contract.get("max_pages") if isinstance(contract, Mapping) else None
        if type(pages) is int and pages >= 1:
            return pages
    return default


__all__ = [
    "MAX_PAGES_PER_PAGED_SLOT",
    "PAGED_SELECTION_SLOTS_KEY",
    "PAGED_WINDOW_SEMANTICS",
    "paged_max_pages",
    "paged_slot_contract",
]
