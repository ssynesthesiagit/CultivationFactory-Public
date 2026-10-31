"""Mortal-grade equipment catalog: Item Book stats, SRD 5.2.1 prices, low-gold pricing."""

from __future__ import annotations

import json
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "authority" / "Tianxia_Mundane_Equipment_Catalog_R1.json"


def _catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def test_catalog_covers_item_book_profiles_and_srd_attribution() -> None:
    catalog = _catalog()
    items = catalog["items"]
    book = [item for item in items if item["source"] == "item_book_r1"]
    assert sum(item["category"] == "weapon" for item in book) == 32
    assert sum(item["category"] in {"armor", "shield"} for item in book) == 13
    assert catalog["sources"]["srd"]["license"] == "CC-BY-4.0" and "SRD 5.2.1" in catalog["sources"]["srd"]["attribution"]
    assert len({item["item_id"] for item in items}) == len(items)
    assert all(item.get("cultural_name") for item in items if item["category"] == "weapon")
    assert not {"Musket", "Pistol", "Potion of Healing", "Holy Water"} & {item["name"] for item in items}


def test_low_gold_pricing_is_one_denomination_below_srd() -> None:
    by_name = {item["name"]: item for item in _catalog()["items"]}
    assert by_name["Jian (Straight Sword)"]["price_cc"] == 150  # longsword 15 GP -> 15 ST
    assert by_name["Imperial Plate Battle Dress"]["price_display"] == "150 GT"  # plate 1,500 GP
    assert by_name["Bang (Club)"]["price_cc"] == 1  # 1 SP -> 1 CC
    assert by_name["Candle"]["price_cc"] == 1  # 1 CP -> minimum 1 CC
    assert by_name["Priest’s Pack"]["price_cc"] == 80 and by_name["Priest’s Pack"]["removed_contents"] == ["Holy Water"]
    for item in _catalog()["items"]:
        srd = item["srd_price"]
        cp = srd["amount"] * {"GP": 100, "SP": 10, "CP": 1}[srd["unit"]]
        if "removed_contents" not in item:
            assert item["price_cc"] == max(1, round(cp / 10))
