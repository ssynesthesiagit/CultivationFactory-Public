from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_map_selection_does_not_mutate_independent_inspection_state() -> None:
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    start = js.index("function beginCombatMapSelection")
    end = js.index("function completeCombatMapSelection", start)
    body = js[start:end]
    assert "combatSelectedActorId =" not in body
    assert "combatFollowCurrentTurn =" not in body
    assert "combatExpandedSheetSection =" not in body
    assert "combatInteractionDraft =" in body


def test_status_metadata_preserves_m4v2_correction_lineage() -> None:
    from app.core import APP_STATUS, APP_VERSION

    assert APP_VERSION == "0.6.6.9.2-CAT2-CANONICAL-CATALOG"
    assert APP_STATUS == "CANONICAL_CATALOG_PRODUCT_INTEGRATION_READY_COMBATANT_LIBRARY_PRE_ENCOUNTER"
    version = json.loads((ROOT / "packaging/windows_portable/VERSION.json").read_text(encoding="utf-8"))
    assert version["authoritative_polished_combat_parent_sha256"] == "1896ea1d5ec61f0f8cfc42282bd84f4369ce5605cfb777d5a553efc24dea79ce"
