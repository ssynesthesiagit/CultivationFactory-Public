"""MMX96: the tabletop's ground hover (owner 2026-09-30: "hovering over the types of ground ... should
bring up the type of material and its effects on movement or anything else", then "2 seconds actually").

Two layers are checked here, at the level a player meets them:

* the state payload carries a readable name-and-effect for every material and named-terrain kind used
  by the shipped maps (the guard: a new map's material cannot be left without a description), and
* every one of those descriptions is plain English -- no internal id, no rule-file field name, no
  owner citation, no "see its source".

The client's card builder (static/tabletop/ground-text.js) and its 2-second rest are NOT covered here --
this file checks the catalog on the payload and nothing in the browser. They are covered by
tests/ground_hover_board.test.mjs (the board itself: the per-square index, the two-second rest, what
cancels it, tokens and zones) and static/tabletop/ground-text.test.mjs (the pure card builder), both run
from pytest by tests/test_ground_hover_client.py; the wording itself is pinned to the engine in
tests/test_ground_text_matches_engine.py. No fight behaviour changes here, so no replay changes.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from combat import ground_text
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_builtin_arenas import CLASSIC, IDS, ROOT, _fight

# Player-facing text must not leak the engine's own vocabulary or an owner citation.
FORBIDDEN = re.compile(
    r"combat/|\.py\b|\bOwner 20|see its source|\bevidence\b|trigger_profile|enter_start|move_through"
    r"|on_fail|difficult=|formula|damage_types|spheres?5|TAL_|\bJSON\b", re.I)


def _stock_kinds() -> set[str]:
    """Every material / named-terrain kind the shipped maps actually paint, across all stock maps."""
    with tempfile.TemporaryDirectory() as data_root:
        store = CombatService(ROOT, Path(data_root)).tabletop_maps
        kinds: set[str] = set()
        for map_id in IDS:
            for row in store.get(map_id).get("materials") or []:
                if isinstance(row, dict) and row.get("material"):
                    kinds.add(str(row["material"]))
    return kinds


def test_shipped_maps_use_materials_the_catalog_knows():
    kinds = _stock_kinds()
    assert kinds, "the shipped maps should paint at least one material"
    known = set(ground_text.catalog())
    assert kinds <= known, f"materials with no reading: {sorted(kinds - known)}"


def test_every_stock_material_has_a_readable_name_and_effects():
    for kind in sorted(_stock_kinds()):
        entry = ground_text.catalog()[kind]
        assert isinstance(entry.get("name"), str) and entry["name"].strip(), f"{kind} has no name"
        assert isinstance(entry.get("lines"), list) and entry["lines"], f"{kind} says nothing"
        for line in entry["lines"]:
            assert isinstance(line, str) and line.strip(), f"{kind} has an empty line"
            assert not FORBIDDEN.search(line), f"{kind} leaks engine vocabulary: {line!r}"


def test_every_catalog_entry_is_plain_and_speaks():
    catalog = ground_text.catalog()
    assert len(catalog) >= 30, "the catalog should cover the shipped floor styles and named terrains"
    for kind, entry in catalog.items():
        assert entry["name"].strip() and not FORBIDDEN.search(entry["name"]), f"{kind}: {entry['name']!r}"
        assert entry["lines"] and all(isinstance(line, str) and line.strip() for line in entry["lines"]), kind
        for line in entry["lines"]:
            assert not FORBIDDEN.search(line), f"{kind} leaks engine vocabulary: {line!r}"


def test_named_terrain_lines_say_what_the_rule_does():
    """A named terrain's card is assembled from its own rule, so a difficulty or a save shows up."""
    rubble = ground_text.catalog()["terrain:loose rubble"]
    assert any("Difficult terrain" in line for line in rubble["lines"]), rubble
    molten = ground_text.catalog()["terrain:molten terrain"]
    assert any("Difficult terrain" in line for line in molten["lines"]), molten
    assert any("Dexterity save" in line for line in molten["lines"]), molten
    obsidian = ground_text.catalog()["terrain:obsidian terrain"]
    assert any("Dexterity save" in line and "Slashing" in line for line in obsidian["lines"]), obsidian


@pytest.mark.parametrize("arena", CLASSIC)
def test_fight_state_carries_a_reading_for_every_stock_material(tmp_path, arena):
    """The real state payload (a live fight) carries the catalog, so the table can name any square."""
    combat, match_id = _fight(tmp_path, arena, size=2, rounds=1)
    state = TabletopService(combat, tmp_path).state(match_id)
    ground = state.get("ground")
    assert isinstance(ground, dict) and ground, "state payload must carry the ground catalog"
    kinds = _stock_kinds()
    missing = kinds - set(ground)
    assert not missing, f"state ground catalog missing readings for {sorted(missing)}"
    # A square's painted floor (when the arena has one) resolves through the same catalog.
    for floor in (state.get("map") or {}).get("floors") or []:
        key = f"floor:{floor['style']}"
        assert key in ground, f"painted floor {key} has no reading on the state payload"
