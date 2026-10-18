"""Current sheet rules reflect owner edits without rewriting sealed records."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.test_sheet_talent_rules_text import _service, _talent_card, _snapshot
from factory_authoring.owner_text_edits import apply_edit
from tools.typed_mechanics_sources import sources

APP = Path(__file__).resolve().parents[1]
EDITS = json.loads((APP / "authority/typed_mechanics/owner_text_edits.json").read_text())["records"]
CURRENT = json.loads((APP / "authority/typed_mechanics/rules_text.json").read_text())


@pytest.fixture(scope="module")
def printed_rows():
    return {row["id"]: row for row in sources() if row["id"] in EDITS}


@pytest.mark.parametrize("record_id", sorted(EDITS))
@pytest.mark.parametrize("complete", [False, True], ids=["short-card", "complete-card"])
def test_sheet_current_rules_apply_each_owner_edit(record_id, complete, printed_rows, monkeypatch):
    source = printed_rows[record_id]
    # Numeric/word replacements retain the actual unedited source section.
    # For removal edits, restore the removed line to model an old sealed card.
    printed = source.get("typing_text", source["text"])
    for line in EDITS[record_id].get("remove", []):
        printed += "\n" + line
    kind = "path_features" if record_id.startswith("tianxia.path.") else "talents"
    card = {"record_id": record_id, "record_hash": "sealed-record-hash",
            "source": {"path": "sealed.md", "anchor": "line:1", "sha256": "sealed-source-hash"},
            "full_description": printed if complete else "Action Type: Action"}
    snapshot = {"selected_record_sections": {kind: [card]}, "sheet_id": "sealed-sheet-id"}
    sealed = deepcopy(snapshot)
    service = _service(APP)
    # Only authentication I/O is stubbed; the real view-time overlay runs on
    # the owner's actual rules and edit data, including path-feature cards.
    monkeypatch.setattr(service, "_authenticated_rules_block", lambda locator, root: (printed.strip(), "sealed.md::line:1"))
    out = service._with_authenticated_rules_text(snapshot)
    row = out["selected_record_sections"][kind][0]
    assert row["full_description"].strip() == apply_edit(printed, EDITS[record_id])[1].strip()
    for pair in EDITS[record_id].get("replace", []):
        # A released source may already have the owner's Action header without
        # the older optional Canonical Action Type line. Only assert literal
        # replacements present in this authenticated source.
        if pair["old"] not in printed and pair["new"] not in printed:
            # Keep the changed action economy checked even when the optional
            # second header line is absent in the current authenticated source.
            header = pair['new'].splitlines()[0]
            assert header in row['full_description'] and header in CURRENT[record_id]
            continue
        assert pair["new"] in row["full_description"]
        if pair['new'] not in CURRENT[record_id]:
            # Reviewed Meld economy is Action; the current published text omits
            # only the optional duplicate Canonical Action Type header.
            lines = pair['new'].splitlines()
            assert lines[0] in CURRENT[record_id]
            assert len(lines) > 1 and all(line.startswith('Canonical Action Type:') for line in lines[1:])
    assert row["full_description_source"] == "Owner-edited current rules"
    assert row["record_hash"] == card["record_hash"]
    assert row["source"] == card["source"]
    assert snapshot == sealed
    assert service._with_authenticated_rules_text(out) == out


def test_owner_overlay_does_not_guess_when_a_short_card_source_cannot_be_verified(tmp_path):
    record_id = "tianxia.path.qi_cultivation.feature.qi_armor"
    snapshot = {"selected_record_sections": {"path_features": [{"record_id": record_id,
                "full_description": "Action Type: Reaction", "source": {}}]}}
    assert _service(tmp_path)._with_authenticated_rules_text(snapshot) is snapshot


@pytest.mark.parametrize("record_id", sorted(EDITS))
def test_already_current_rules_are_not_edited_twice(record_id):
    snapshot = {"selected_record_sections": {"talents": [{"record_id": record_id,
                "full_description": CURRENT[record_id]}]}}
    service = _service(None)
    out = service._with_authenticated_rules_text(snapshot)
    row = out["selected_record_sections"]["talents"][0]
    assert row["full_description"] == CURRENT[record_id]
    if any(pair["new"] in CURRENT[record_id] for pair in EDITS[record_id].get("replace", [])):
        assert row["full_description_source"] == "Owner-edited current rules"
    assert service._with_authenticated_rules_text(out) == out


def test_owner_edit_uses_a_real_authenticated_source_without_changing_its_bytes(tmp_path):
    card, root = _talent_card(tmp_path, text="Gain +3 AC until the start of your next turn, including against the triggering attack.")
    card["record_id"] = "tianxia.path.qi_cultivation.feature.qi_armor"
    snapshot = _snapshot(card)
    source = root / card["source"]["path"]
    sealed_bytes = source.read_bytes()
    out = _service(root)._with_authenticated_rules_text(snapshot)
    row = out["selected_record_sections"]["talents"][0]
    assert "Gain +5 AC until the start of your next turn" in row["full_description"]
    assert row["full_description_source"] == "Owner-edited current rules"
    assert source.read_bytes() == sealed_bytes
    assert snapshot["selected_record_sections"]["talents"][0] == card
