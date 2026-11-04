"""Explicit rescue ownership must not depend on a free-text trigger parser."""
from copy import deepcopy

import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.test_mgr_t14_sol_subpath_ferry_wounded import FERRY, QI


@pytest.mark.parametrize("plan", [{"ask": True}, {"off": [FERRY]}, {}])
def test_ferry_seals_one_explicit_row_without_a_classifiable_trigger(plan):
    doc = sheet([FERRY], cl=6, primary="Qi")
    # A synthetic typed record, not a private authority/proposal or a parser
    # monkeypatch. The explicit provider owns this after-damage trigger.
    mechanic = {
        "mechanic_id": FERRY, "name": "Ferry the Wounded",
        "activation": {"economy": "reaction", "trigger": "Explicit settled-damage rescue."},
        "effects": [], "riders": [], "duration": {"kind": "instant"},
    }
    bundle = compile_character(doc, actor_id="actor:ferry", reaction_plan=plan,
                               typed_authority={"mechanics": {FERRY: mechanic}})
    rows = [r for r in bundle["typed_reactions"] if r["feature_id"] == FERRY]
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "ally_damaged"
    assert row["effects"] == []
    assert row["costs"] == [{"resource_id": QI, "amount": 2}]
    assert row["once"] == "round"
    assert row["numbers"]["cl"] == 6
    assert row["reaction_attack"] is False
    assert row["target_kind"] == "ALLY_OR_SELF"
    assert bool(row.get("ask")) == bool(plan.get("ask"))
    assert bool(row.get("held_back")) == bool(plan.get("off"))
    assert any(r["block"] == "opportunity" for r in bundle["typed_reactions"])


def test_ferry_provider_replaces_old_generic_payload_and_is_inert_for_nonowners():
    from combat.ext.riverway_passage import ferry_reaction
    rows = [{"feature_id": "other", "effects": [{"type": "damage"}]},
            {"feature_id": FERRY, "effects": [{"type": "forced_movement"}]}]
    original = deepcopy(rows)
    # A CL11/PB 4 character whose Riverway is attained to CL6: the row keeps
    # the attainment level but the character's own Proficiency Bonus.
    info = {"owned_ids": [], "numbers": {"cl": 11, "pb": 4},
            "numbers_by_source": {FERRY: {"cl": 6, "pb": 4}}}
    assert ferry_reaction(rows, info) is rows
    info["owned_ids"] = [FERRY]
    result = ferry_reaction(rows, info)
    assert result[0] == rows[0]
    assert len(result) == 2
    assert result[1]["numbers"] == {"cl": 6, "pb": 4}
    assert result[1]["effects"] == []
    assert rows == original
