"""Full rules text on the character sheet, not the catalog's first line.

Owner request (2026-09-13, after finalizing Xin Qilong): the finalized sheet
showed "Action Type: Bonus Action" as the whole rules text for Bitter Edge.
The locked catalog record carries the complete printed entry; the sealed
display contract only carried the first line.  Both layers are covered here:

* ``projector.v3_bridge._display`` prefers the authenticated raw-record rules
  text when it is longer, so newly finalized characters project real rules
  text into their packets, ledger and display contract.
* ``CharacterSheetService._apply_authenticated_rules_text`` attaches the same
  text at view time for characters that were finalized before that change.

Neither layer changes a record hash, a sealed display contract, packet ids or
any mechanical projection.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from character_sheet.service import CharacterSheetService
from projector.v3_bridge import _display

BITTER_EDGE_SHORT = "Action Type: Bonus Action"
BITTER_EDGE_RULES = (
    "#### Bitter Edge\n\nAction Type: Bonus Action\n\nRange: Touch\n\nDuration: 1 minute\n\n"
    "Cost: 1 CP\n\nYou coat one weapon, natural weapon, or unarmed strike with hard ice."
)


def _record(*, projection_full: str, raw: dict | None) -> dict:
    record = {
        "record_id": "TAL_ICE_BITTER_EDGE",
        "display_name": "Bitter Edge",
        "display_projection": {"short_description": projection_full, "full_description": projection_full},
    }
    if raw is not None:
        record["compatibility"] = {"factory": {"raw_projection": {"raw_record": raw}}}
    return record


def test_display_prefers_the_longer_locked_raw_record_text() -> None:
    short, full = _display(_record(projection_full=BITTER_EDGE_SHORT, raw={"full_description": BITTER_EDGE_RULES}))
    assert short == BITTER_EDGE_SHORT
    assert full == BITTER_EDGE_RULES


def test_display_keeps_the_projection_when_there_is_no_raw_record() -> None:
    short, full = _display(_record(projection_full=BITTER_EDGE_SHORT, raw=None))
    assert short == BITTER_EDGE_SHORT
    assert full == BITTER_EDGE_SHORT


def test_display_never_shortens_an_already_complete_projection() -> None:
    complete = "A complete printed rules paragraph that is already the real text."
    _short, full = _display(_record(projection_full=complete, raw={"full_description": "tiny"}))
    assert full == complete


def test_display_prefers_effective_rules_text_over_the_raw_full_description() -> None:
    effective = "Effective rules text after errata. " * 6
    _short, full = _display(_record(
        projection_full=BITTER_EDGE_SHORT,
        raw={"effective_rules_text": effective, "full_description": "Older superseded text. " * 6},
    ))
    assert full.strip() == effective.strip()


def test_display_falls_back_to_full_exact_source_text() -> None:
    exact = "Exact source text with the full printed entry. " * 6
    _short, full = _display(_record(projection_full=BITTER_EDGE_SHORT, raw={"full_exact_source_text": exact}))
    assert full.strip() == exact.strip()


class _FakeProjections:
    def __init__(self, root: Path | None) -> None:
        self._root = root

    def _factory_root(self) -> Path:
        if self._root is None:
            from app.core import FoundryError

            raise FoundryError("PROJECTION_FACTORY_NOT_CONFIGURED", "no root")
        return self._root


def _service(root: Path | None) -> CharacterSheetService:
    service = object.__new__(CharacterSheetService)
    service.projections = _FakeProjections(root)
    return service


def _talent_card(tmp_path: Path, *, text: str) -> tuple[dict, Path]:
    """Write one mini source file and return (card, factory_root)."""

    source_dir = tmp_path / "09_RULES" / "Source_Text"
    source_dir.mkdir(parents=True, exist_ok=True)
    body = "\n".join([
        "#### Bitter Edge",
        "",
        "Action Type: Bonus Action",
        "",
        "You coat one weapon with hard ice and may deal extra Cold damage.",
        "",
        text,
        "",
        "#### Next Entry",
        "",
        "Unrelated.",
    ])
    (source_dir / "Compendium.md").write_text(body, encoding="utf-8")
    import hashlib

    digest = hashlib.sha256((source_dir / "Compendium.md").read_bytes()).hexdigest()
    card = {
        "record_id": "TAL_ICE_BITTER_EDGE",
        "record_hash": "a" * 64,
        "section": "talents",
        "full_description": BITTER_EDGE_SHORT,
        "source": {
            "path": "09_RULES/Source_Text/Compendium.md",
            "anchor": "line:1:column:1",
            "sha256": digest,
        },
    }
    return card, tmp_path


def _snapshot(card: dict) -> dict:
    return {
        "sheet_id": "sheet.onepage.test",
        "selected_record_sections": {"talents": [dict(card)], "path_features": [{"record_id": "P1", "full_description": "Action Type: Action"}]},
        "authority_and_artifact_identity": {"project_id": "p"},
    }


def test_view_time_overlay_attaches_rules_text_for_a_finalized_sheet(tmp_path: Path) -> None:
    card, root = _talent_card(tmp_path, text="If the target is on a Lattice Space it gains a Fracture Mark.")
    snapshot = _snapshot(card)
    sealed = deepcopy(snapshot)
    out = _service(root)._with_authenticated_rules_text(snapshot)
    enriched = out["selected_record_sections"]["talents"][0]
    assert enriched["full_description"].startswith("#### Bitter Edge")
    assert len(enriched["full_description"]) > len(BITTER_EDGE_SHORT)
    assert enriched["full_description_source"] == "locked_catalog_record_rules_text"
    assert enriched["rules_text_source_locator"] == "09_RULES/Source_Text/Compendium.md::line:1:column:1"
    # Sealed identity is untouched, and the input snapshot is not mutated.
    assert enriched["record_hash"] == card["record_hash"]
    assert enriched["source"] == card["source"]
    assert snapshot == sealed
    # Non-rule-text sections are never rewritten.
    assert out["selected_record_sections"]["path_features"][0]["full_description"] == "Action Type: Action"


def test_view_time_overlay_leaves_a_complete_card_alone(tmp_path: Path) -> None:
    card, root = _talent_card(tmp_path, text="Unused.")
    complete = "An already complete rules paragraph. " * 20
    card["full_description"] = complete
    snapshot = _snapshot(card)
    out = _service(root)._with_authenticated_rules_text(snapshot)
    enriched = out["selected_record_sections"]["talents"][0]
    assert enriched["full_description"] == complete
    assert "full_description_source" not in enriched
    # Nothing changed, so the same object is returned rather than a copy.
    assert out is snapshot


def test_view_time_overlay_requires_a_verifiable_source_hash(tmp_path: Path) -> None:
    card, root = _talent_card(tmp_path, text="Unused.")
    card["source"] = {**card["source"], "sha256": "b" * 64}
    out = _service(root)._with_authenticated_rules_text(_snapshot(card))
    assert out["selected_record_sections"]["talents"][0]["full_description"] == BITTER_EDGE_SHORT


def test_view_time_overlay_is_a_no_op_without_an_installed_pack() -> None:
    card = {
        "record_id": "TAL_ICE_BITTER_EDGE",
        "section": "talents",
        "full_description": BITTER_EDGE_SHORT,
        "source": {"path": "x.md", "anchor": "line:1:column:1", "sha256": "c" * 64},
    }
    snapshot = _snapshot(card)
    assert _service(None)._with_authenticated_rules_text(snapshot) is snapshot


def test_view_time_overlay_reaches_sphere_automatic_components(tmp_path: Path) -> None:
    card, root = _talent_card(tmp_path, text="Unused.")
    snapshot = {"selected_record_sections": {"sphere_automatic_components": [dict(card)]}}
    out = _service(root)._with_authenticated_rules_text(snapshot)
    assert out["selected_record_sections"]["sphere_automatic_components"][0]["full_description_source"] == "locked_catalog_record_rules_text"


def test_view_time_overlay_tolerates_a_snapshot_without_sections() -> None:
    service = _service(None)
    assert service._with_authenticated_rules_text(None) is None
    assert service._with_authenticated_rules_text({"sheet_id": "x"}) == {"sheet_id": "x"}


def test_surface_overlay_enriches_the_talent_ledger(tmp_path: Path) -> None:
    """The complete-character surface rows carry the printed rules text too."""

    card, root = _talent_card(tmp_path, text="If the target is on a Lattice Space it gains a Fracture Mark.")
    surfaces = {
        "spheres_talents": {
            "available": True,
            "data": {
                "Talent_Source_Ledger.json": {
                    "schema_version": "TianxiaFoundry.CharacterGMTalentSources.v1",
                    "learned_talents": [dict(card)],
                    "background_talents": [],
                },
                "Selected_Spheres.json": {"spheres": [{"sphere_id": "tianxia.sphere.ice", "display_name": "Ice"}]},
            },
        },
    }
    sealed = deepcopy(surfaces)
    out = _service(root)._with_authenticated_surface_rules_text(surfaces)
    row = out["spheres_talents"]["data"]["Talent_Source_Ledger.json"]["learned_talents"][0]
    assert row["full_description"].startswith("#### Bitter Edge")
    assert row["full_description_source"] == "locked_catalog_record_rules_text"
    # The input payload is not mutated, and unchanged rows are left alone.
    assert surfaces == sealed
    assert out["spheres_talents"]["data"]["Selected_Spheres.json"]["spheres"][0]["full_description_source"] is None if "full_description_source" in out["spheres_talents"]["data"]["Selected_Spheres.json"]["spheres"][0] else True


def test_surface_overlay_is_a_no_op_without_the_surface(tmp_path: Path) -> None:
    service = _service(None)
    assert service._with_authenticated_surface_rules_text(None) is None
    payload = {"leveling": {"available": True, "data": {}}}
    assert service._with_authenticated_surface_rules_text(payload) is payload
