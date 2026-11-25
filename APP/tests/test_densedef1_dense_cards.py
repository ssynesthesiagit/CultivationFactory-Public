"""DENSEDEF1: the Smoke cards that use "Dense" define it, and Dense Veil's timing matches play.

Repro through the card path: tools.card_lint.catalogue() -> build_player_text -> project_player_card.
Display text only. The rules, typing and source hashes are pinned, not changed.
"""
import json
from pathlib import Path

from tools.card_lint import catalogue, lint_card

APP = Path(__file__).resolve().parents[1]
TYPED = APP / "authority" / "typed_mechanics"
CARDS = ("TAL_SMOKE_DENSE_VEIL", "TAL_SMOKE_WALL_OF_SMOKE",
         "TAL_SMOKE_SMOKE_DOMAIN_COURT_OF_HIDDEN_WITNESSES")
WHY = "DENSEDEF1: owner-asked display-only clarity; preserve all mechanics."
HEAVY = "Heavily Obscured"
LAPSE = "start of your next turn"
DENSE_VEIL_HASHES = {
    "source_sha256": "589c84c75aceaed99543a2dcfa1b32b998c166cb8951361a1e3541c3f635b8da",
    "rules_sha256": "780c15cf093cb3a6325a8ddd2b770e4f873a9acd54779f1c8450084243acbfb7",
}


def _shown(card):
    """Every display string the card shows, not the printed source in card['rules']."""
    parts = [card.get("summary", ""), card.get("player_text", "")]
    for items in (card.get("groups") or {}).values():
        parts.extend(items)
    return parts


def _card(key):
    cards = catalogue()
    assert key in cards, f"{key} missing from catalogue"
    return cards[key]


def test_each_dense_card_defines_dense_where_it_uses_the_word():
    for key in CARDS:
        shown = _shown(_card(key))
        blob = "\n".join(shown)
        if "Dense" in blob:
            assert HEAVY in blob, f"{key} uses 'Dense' without defining it; card said: {blob!r}"


def test_dense_veil_card_drops_the_lapse_timing():
    card = _card("TAL_SMOKE_DENSE_VEIL")
    blob = "\n".join(_shown(card))
    assert LAPSE not in blob, f"Dense Veil still states lapse timing; card said: {blob!r}"
    assert HEAVY in blob, f"Dense Veil does not define Dense; card said: {blob!r}"


def test_dense_veil_typed_effect_still_smoke_dense_veil():
    auto = json.loads((TYPED / "reviewed_final.d" / "auto_smoke.json").read_text(encoding="utf-8"))
    record = auto["mechanics"]["TAL_SMOKE_DENSE_VEIL"]
    types = [effect["type"] for effect in record["modifier"]["effects"]]
    assert types == ["smoke_dense_veil"], f"typed effects changed: {types!r}"


def test_dense_veil_hashes_unchanged():
    owner = json.loads((TYPED / "owner_text_edits.json").read_text(encoding="utf-8"))["records"]
    card = owner["TAL_SMOKE_DENSE_VEIL"]["player_card"]
    for name, value in DENSE_VEIL_HASHES.items():
        assert card[name] == value, f"{name} changed: {card[name]!r}"


def test_edited_records_carry_the_brief_why():
    owner = json.loads((TYPED / "owner_text_edits.json").read_text(encoding="utf-8"))["records"]
    for key in CARDS:
        assert owner[key]["why"] == WHY, f"{key} why: {owner[key]['why']!r}"


def test_edited_cards_lint_clean():
    cards = catalogue()
    for key in CARDS:
        assert lint_card(cards[key]) == [], (key, lint_card(cards[key]))
