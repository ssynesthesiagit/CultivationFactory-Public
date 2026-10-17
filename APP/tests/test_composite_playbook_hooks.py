"""Dao / I Ching hooks are derived from data (Aspect keyword evidence, real costs, authored themes), not defaults."""
from __future__ import annotations

import pytest

from factory_authoring.composite_playbook.hooks import (
    AspectTable, aspect_hits, build_dao_hook, build_i_ching_hook, load_aspects, themes_from_surface,
)
from factory_authoring.composite_playbook.proposer import propose_playbooks
from factory_authoring.composite_playbook.registry import ActionRecord, ActionRegistry
from factory_authoring.composite_playbook.templates import TemplateSet, load_templates

TABLE = {"schema_version": "TianxiaFoundry.CompositePlaybookDaoAspects.v1", "max_aspects_per_playbook": 2,
         "aspects": [{"aspect_id": "a.destruction", "display_name": "Destruction", "keywords": ["damage"]},
                     {"aspect_id": "a.transport", "display_name": "Transport", "keywords": ["move"]},
                     {"aspect_id": "a.time", "display_name": "Time", "restricted": True, "keywords": ["time"]}]}
P = "tianxia.resource.qi"
POOLS = {P: {"name": "Qi", "current": 6, "maximum": 6}}


def _rec(action_id, name, economy, *, cost=0, text="", base=False, forged=False):
    return ActionRecord(action_id=action_id, display_name=name, economy=economy,
                        resource_costs=((P, cost),) if cost else (),
                        raw={"base": base, "forged": forged, "cost_parsed": True, "external_preconditions": (),
                             "cost_text": f"{cost} CP" if cost else None, "rules_text": text, "record_id": action_id})


def _templates(*rows):
    return TemplateSet.from_mapping({"schema_version": "TianxiaFoundry.CompositePlaybookTemplates.v1", "budget_fraction": 0.5,
                                     "fallback_economy": "action", "templates": list(rows)})


OPENING = {"template_id": "open", "category": "opening", "execution_role": "Open",
           "i_ching": {"tendency": "Restraint", "shift_to": "sustain", "shift_when": "resource_low"},
           "slots": [{"round_offset": 0, "economy": "action", "prefer": "highest_cost"},
                     {"round_offset": 1, "economy": "action", "prefer": "highest_cost"}]}
SUSTAIN = {"template_id": "sustain", "category": "sustain", "execution_role": "Sustain",
           "i_ching": {"tendency": "Patience", "shift_to": "open", "shift_when": "resource_recovered"},
           "slots": [{"round_offset": 0, "economy": "action", "prefer": "zero_cost"},
                     {"round_offset": 1, "economy": "action", "prefer": "zero_cost"}]}
RECORDS = [_rec("A_BURST", "Burst", "action", cost=2, text="Deals 3d8 damage and pushes the target."),
           _rec("A_STEP", "Step", "action", cost=1, text="You move 20 feet."),
           _rec("A_TRICK", "Trick", "action", text="Nothing here matches."),
           _rec("base.5e.dodge", "Dodge", "action", base=True)]


def test_default_table_is_the_seventeen_active_aspects():
    table = load_aspects()
    assert len(table.aspects) == 17 and sum(a.restricted for a in table.aspects) == 4
    assert {a.display_name for a in table.aspects if a.restricted} == {"Fate", "Time", "Soul", "Heaven"}


def test_hits_are_word_prefix_matches_and_restricted_is_off_by_default():
    table = AspectTable.from_mapping(TABLE)
    assert aspect_hits(table, "Move 30 feet; the movement deals 2d8 damage each time.") == {
        "a.destruction": {"damage": 1}, "a.transport": {"move": 2}}
    assert aspect_hits(AspectTable.from_mapping({**TABLE, "match_restricted": True}), "each time")["a.time"] == {"time": 1}


def test_dao_hook_names_the_evidence_or_claims_nothing():
    table = AspectTable.from_mapping(TABLE)
    text, aspects = build_dao_hook([("Sky Road", "You move up to 60 feet."), ("Seal", "It takes 1d8 damage.")], table)
    assert [a["display_name"] for a in aspects] == ["Destruction", "Transport"]  # equal counts: ordered by aspect_id
    assert "Transport (Sky Road: move x1)" in text and "Destruction (Seal: damage x1)" in text and "direct" in text
    none_text, none_aspects = build_dao_hook([("Trick", "Nothing matches here.")], table)
    assert none_aspects == [] and none_text.startswith("No active Dao Aspect keyword")
    for banned in ("unknown", "placeholder", "TBD", "unnamed"):
        assert banned not in text and banned not in none_text


def test_themes_prefer_authored_over_provisional():
    provisional = themes_from_surface({"dao": {"authoring_id": "gm.dao.project.1", "core_theme": "generic"},
                                       "i_ching": {"authoring_id": "gm.iching.project.1", "core_theme": "generic"}})
    assert provisional.dao_phrase is None and "provisional" in provisional.dao_note and provisional.i_ching_phrase is None
    actual = themes_from_surface({"dao_i_ching": {"dao": {"authoring_id": "gm.dao.actual.1", "display_name": "Banked Furnace",
                                                          "core_theme": "Measure the flame.", "tactical_expression": "Release one line."}}})
    assert actual.dao_phrase == "Banked Furnace: Measure the flame. Release one line." and actual.dao_source == "gm.dao.actual.1"
    assert themes_from_surface(None).to_dict()["dao"]["phrase"] is None
    hook, _ = build_dao_hook([], AspectTable.from_mapping(TABLE), actual)
    assert hook.startswith("Dao: Banked Furnace: Measure the flame.")


@pytest.mark.parametrize(("kind", "spent", "expected"), [
    ("resource_low", 3, "Change when Qi falls below 3 of 20: this line can no longer be paid; shift to Line B."),
    ("resource_low", 0, "This line costs no Qi, so a low pool is not its change signal; shift to Line B only when a step is denied."),
    ("resource_recovered", 0, "Change when Qi is at or above 2 of 20 and an opening is present: shift to Line B to commit."),
    ("step_denied", 1, "Change when a step of this line is denied (its slot already spent, its trigger absent, or its target out of reach): shift to Line B."),
])
def test_i_ching_hook_reads_real_numbers(kind, spent, expected):
    text = build_i_ching_hook(tendency="Patience", shift_when=kind, shift_to="Line B", shift_to_proposed=True,
                              shift_to_spent=2, spent=spent, pool_name="Qi", limit=20, fallback_name="Trick")
    assert text == f"Tendency: Patience. {expected}"


def test_i_ching_hook_falls_back_when_the_target_was_not_proposed():
    text = build_i_ching_hook(tendency=None, shift_when="resource_low", shift_to="forged signature", shift_to_proposed=False,
                              shift_to_spent=0, spent=3, pool_name="Qi", limit=None, fallback_name="Trick")
    assert text == ("Change when Qi falls below 3: this line can no longer be paid; hold the zero-cost fallback Trick "
                    "(forged signature is not proposed for this character).")
    with pytest.raises(ValueError):
        build_i_ching_hook(tendency=None, shift_when="never", shift_to=None, shift_to_proposed=False, shift_to_spent=0,
                           spent=0, pool_name="Qi", limit=None, fallback_name=None)


def test_proposer_computes_hooks_from_evidence_and_siblings():
    result = propose_playbooks(ActionRegistry(RECORDS), templates=_templates(OPENING, SUSTAIN),
                               resource_pools=POOLS, primary_resource_id=P)
    assert [row["composite_id"] for row in result.composites] == ["gm.playbook.proposed.open", "gm.playbook.proposed.sustain"]
    opening, sustain = result.composites
    assert [a["display_name"] for a in opening["dao_aspects"]] == ["Destruction", "Transport"]
    assert "Burst: damage x1" in opening["dao_hook"] and "Step: move x1" in opening["dao_hook"]
    assert opening["i_ching_hook"] == ("Tendency: Restraint. Change when Qi falls below 3 of 6: this line can no longer be paid; "
                                       "shift to Trick -> Dodge.")
    assert opening["i_ching_shift"] == {"kind": "resource_low", "to_template_id": "sustain",
                                        "to_composite_id": "gm.playbook.proposed.sustain"}
    assert sustain["dao_aspects"] == [] and sustain["dao_hook"].startswith("No active Dao Aspect keyword")
    assert sustain["i_ching_hook"] == ("Tendency: Patience. Change when Qi is at or above 3 of 6 and an opening is present: "
                                       "shift to Burst -> Step to commit.")
    assert all(row["validation"]["ok"] for row in result.composites)


def test_verbatim_hook_overrides_still_win_but_evidence_is_kept():
    result = propose_playbooks(ActionRegistry(RECORDS), templates=_templates(OPENING, SUSTAIN), resource_pools=POOLS,
                               primary_resource_id=P, hooks={"dao_hook": "Custom dao.", "i_ching_hook": "Custom change."})
    assert result.composites[0]["dao_hook"] == "Custom dao." and result.composites[0]["i_ching_hook"] == "Custom change."
    assert result.composites[0]["dao_aspects"]


def test_change_guidance_never_points_to_a_rejected_playbook():
    rejected = {**SUSTAIN, "execution_role": "Unknown"}
    result = propose_playbooks(ActionRegistry(RECORDS), templates=_templates(OPENING, rejected),
                               resource_pools=POOLS, primary_resource_id=P)
    assert [row["composite_id"] for row in result.composites] == ["gm.playbook.proposed.open"]
    assert [row["composite_id"] for row in result.rejected] == ["gm.playbook.proposed.sustain"]
    opening = result.composites[0]
    assert opening["validation"]["ok"] is True
    assert opening["i_ching_shift"]["to_composite_id"] is None
    assert "sustain is not proposed for this character" in opening["i_ching_hook"]
    assert "shift to Trick -> Dodge" not in opening["i_ching_hook"]


def test_forged_only_slot_uses_a_forged_technique_and_skips_honestly_without_one():
    forged = {"template_id": "sig", "category": "signature", "execution_role": "Signature",
              "i_ching": {"tendency": "Release", "shift_to": "sustain", "shift_when": "resource_low"},
              "slots": [{"round_offset": 0, "economy": "action", "prefer": "highest_cost", "forged_only": True},
                        {"round_offset": 1, "economy": "action", "prefer": "any", "own_only": True}]}
    sustain = {**SUSTAIN, "i_ching": {"tendency": "Patience", "shift_to": "sig", "shift_when": "resource_recovered"}}
    templates = _templates(forged, sustain)
    without = propose_playbooks(ActionRegistry(RECORDS), templates=templates, resource_pools=POOLS, primary_resource_id=P)
    assert [s["template_id"] for s in without.skipped] == ["sig"] and "no eligible action" in without.skipped[0]["reason"]
    records = RECORDS + [_rec("F_CUT", "Gale Cut", "action", cost=2, forged=True, text="Deals damage.")]
    row = propose_playbooks(ActionRegistry(records), templates=templates, resource_pools=POOLS, primary_resource_id=P).composites[0]
    assert row["composite_id"] == "gm.playbook.proposed.sig" and row["sequence"][0]["action_id"] == "F_CUT"
    assert row["sequence"][0]["source"] == "forged technique" and row["sequence"][1]["source"] == "character record"
    assert row["validation"]["ok"] is True
    shipped = load_templates().templates[-1]
    assert shipped.template_id == "forged_signature" and shipped.slots[1].forged_only and shipped.shift_to == "sustained_pressure"
