"""Printed alignment review and artifact authority through compilation/table reload."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from tests.h1_support import sheet
from tests.test_mgr_t14_ash_strike import setup, strike
from tests.worker2_support import OWNER, FOE, candidate, settle, turn, reload

APP = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("source,file", [
    ("FIRE_BASE_IGNITE", "review_sw-fire.json"),
    ("tianxia.talent.poison.coated_weapon", "review_sw-monkey_style.json"),
])
def test_alignment_has_exact_printed_review_and_compiled_provenance(source, file):
    reviewed = json.loads((APP / "authority/typed_mechanics/reviewed_final.d" / file).read_text())
    row = reviewed.get("mechanics", reviewed)[source]
    texts = json.loads((APP / "authority/typed_mechanics/rules_text.json").read_text())
    # Existing text_sha256 pins the unsanitized catalog source; rules_text omits
    # bookkeeping lines. Pin both representations rather than changing that hash.
    generated = json.loads(TYPED_AUTHORITY.read_text())["mechanics"][source]
    assert row["text_sha256"] == generated["source"]["text_sha256"]
    review = row["foundation_alignment_review"]
    assert review["printed_rules_sha256"] == hashlib.sha256(texts[source].encode()).hexdigest()
    assert review["source_id"] == source
    assert review["foundation_source_id"] == "foundation.red_lotus_ash_returning_v0_2B.ash_returning_meridian"
    assert "printed alignment review" in row["reviewed_by"]
    assert "hostile creature below its Hit Point maximum" in review["rationale"]
    bundle = compile_character(sheet([source]), actor_id=OWNER)
    actions = [a for a in bundle["action_catalog"]
               if a.get("parameters", {}).get("typed", {}).get("source") == source]
    assert actions
    assert all("ash" in a["parameters"]["typed"]["foundation_alignment"] for a in actions)


@pytest.mark.parametrize("artifact", [True, False])
def test_reviewed_artifact_healing_overrides_strike_after_cold_reload(tmp_path, artifact):
    # Synthetic reviewed catalog: no real artifact's printed powers are invented.
    # The production compiler must seal its authority, then the table must persist
    # and consume that provenance, rather than infer authority from the healer.
    authority = copy.deepcopy(json.loads(TYPED_AUTHORITY.read_text()))
    authority["mechanics"]["LIFE_BASE_MEND_THE_PULSE"]["healing_authority"] = {"artifact": artifact}
    combat, table, mid = setup(tmp_path, healer_authority=authority)
    strike(combat, table, mid, "slashing")
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == "condition:typed.foundations3_ash_healing_denied"
               for c in engine.state.actors[FOE].conditions.values())
    turn(table, mid, FOE)
    healing = candidate(combat, mid, "Mend the Pulse", target=FOE)
    engine = reload(tmp_path, mid)
    action = engine.action_catalog[healing.source_definition_id]
    assert action.parameters["typed"]["healing_authority"] == {"artifact": artifact}
    before = engine.state.actors[FOE].current_hp
    settle(table, mid, healing.candidate_id)
    engine = reload(tmp_path, mid)
    assert (engine.state.actors[FOE].current_hp > before) is artifact
    assert any(c.condition_id == "condition:typed.foundations3_ash_healing_denied"
               for c in engine.state.actors[FOE].conditions.values())
