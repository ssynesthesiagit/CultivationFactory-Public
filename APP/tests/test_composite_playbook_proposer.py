"""Deterministic proposer: template filling, budget, capacity, fallback, validation (synthetic records)."""
from __future__ import annotations

import pytest

from factory_authoring.composite_playbook.proposer import ProposalResult, propose_playbooks
from factory_authoring.composite_playbook.registry import ActionRecord, ActionRegistry
from factory_authoring.composite_playbook.rules import load_rules
from factory_authoring.composite_playbook.templates import TemplateSet, load_templates
from factory_authoring.composite_playbook.validator import validate_playbook

P = "RES_TEST"
REQUIRED = ("composite_id", "name", "execution_role", "when_to_use", "do_not_use_when", "resource_budget",
            "temporal_feasibility", "fallback", "dao_hook", "i_ching_hook", "sequence")
STEP_REQUIRED = ("step", "action_id", "round_offset", "economy", "requires_states", "external_preconditions")


def rec(action_id, name, economy, cost=0, base=False, parsed=True, pre=()):
    raw = {"base": base, "cost_parsed": parsed, "external_preconditions": tuple(pre),
           "cost_text": f"{cost} CP" if cost else None}
    if not base:
        raw["record_id"] = action_id
    return ActionRecord(action_id=action_id, display_name=name, economy=economy,
                        resource_costs=((P, cost),) if cost else (), raw=raw)


RECORDS = [
    rec("ACT_BIG", "Big Strike", "action", 4),
    rec("ACT_MID", "Mid Strike", "action", 2, pre=("Prerequisite: CL 5+",)),
    rec("ACT_FREE", "Free Strike", "action"),
    rec("ACT_FOCUS", "Focus Strike", "action", parsed=False),
    rec("BON_FREE", "Quick Step", "bonus_action"),
    rec("REA_GUARD", "Guard", "reaction", pre=("Trigger: an ally is hit",)),
    rec("base.5e.dodge", "Dodge", "action", base=True),
    rec("base.5e.dash", "Dash", "action", base=True),
]
POOLS = {P: {"name": "Test Points", "current": 6, "maximum": 10}}


def slot(offset, economy, prefer="any", **extra):
    return {"round_offset": offset, "economy": economy, "prefer": prefer, **extra}


def tmpl(template_id, *slots, category="test"):
    return {"template_id": template_id, "category": category, "execution_role": f"{template_id} role", "slots": list(slots)}


def templates(*rows, fraction=0.5, fallback_economy="action"):
    return TemplateSet.from_mapping({
        "schema_version": "TianxiaFoundry.CompositePlaybookTemplates.v1",
        "budget_fraction": fraction, "fallback_economy": fallback_economy,
        "hooks": {"dao_hook_default": "Dao text.", "i_ching_hook_default": "I Ching text."},
        "templates": list(rows)})


def propose(rows, *, records=RECORDS, pools=POOLS, primary=P, fraction=0.5, fallback_economy="action", **kwargs):
    registry = ActionRegistry(records)
    return propose_playbooks(registry, templates=templates(*rows, fraction=fraction, fallback_economy=fallback_economy),
                             resource_pools=pools, primary_resource_id=primary, **kwargs)


def ids(row):
    return [step["action_id"] for step in row["sequence"]]


OPENING = tmpl("opening", slot(0, "bonus_action", "zero_cost", optional=True),
               slot(0, "action", "highest_cost"), slot(1, "action", "highest_cost"))


def test_highest_cost_prefers_the_costliest_action_that_fits_the_budget():
    result = propose([OPENING])  # budget = int(6 * 0.5) = 3
    assert not result.skipped and not result.rejected and len(result.composites) == 1
    row = result.composites[0]
    assert ids(row) == ["BON_FREE", "ACT_MID", "ACT_FREE"]
    assert [s["step"] for s in row["sequence"]] == [1, 2, 3]
    assert [s["round_offset"] for s in row["sequence"]] == [0, 0, 1]
    assert row["sequence"][1]["external_preconditions"] == ["Prerequisite: CL 5+"]
    assert "Prerequisite: CL 5+" in row["when_to_use"]
    assert row["resource_totals"] == {P: 2}
    assert "below 2" in row["do_not_use_when"] and "2 Test Points" in row["resource_budget"]
    assert "cap 3 of 6" in row["resource_budget"]
    assert row["validation"]["ok"] is True
    wide = propose([OPENING], fraction=1.0).composites[0]  # budget 6
    assert ids(wide) == ["BON_FREE", "ACT_BIG", "ACT_MID"] and wide["resource_totals"] == {P: 6}


def test_required_slot_without_candidate_skips_the_template():
    result = propose([tmpl("x", slot(0, "action", "zero_cost"), slot(0, "passive"))])
    assert result.composites == [] and len(result.skipped) == 1
    assert result.skipped[0]["template_id"] == "x"
    assert "passive" in result.skipped[0]["reason"] and "no eligible action" in result.skipped[0]["reason"]


def test_optional_slot_is_skipped_but_minimum_length_still_applies():
    result = propose([tmpl("y", slot(0, "action", "zero_cost"), slot(0, "passive", optional=True))])
    assert result.composites == [] and "sequence_length.min" in result.skipped[0]["reason"]


def test_per_round_capacity_and_distinct_reuse():
    over = propose([tmpl("z", slot(0, "action", "zero_cost"), slot(0, "action", "zero_cost"))])
    assert over.composites == [] and "capacity" in over.skipped[0]["reason"]
    distinct = propose([tmpl("w", slot(0, "action", "zero_cost"), slot(1, "action", "zero_cost"))]).composites[0]
    assert ids(distinct) == ["ACT_FREE", "base.5e.dash"]
    reuse = propose([tmpl("w", slot(0, "action", "zero_cost"), slot(1, "action", "zero_cost", distinct=False))]).composites[0]
    assert ids(reuse) == ["ACT_FREE", "ACT_FREE"] and reuse["validation"]["ok"] is True


def test_whitelist_order_base_only_and_own_only():
    row = propose([tmpl("m", slot(0, "bonus_action", "zero_cost"),
                        slot(0, "action", "any", base_only=True, action_ids=["base.5e.nope", "base.5e.dodge", "base.5e.dash"]),
                        slot(1, "action", "highest_cost", own_only=True))], fraction=1.0).composites[0]
    assert ids(row) == ["BON_FREE", "base.5e.dodge", "ACT_BIG"]
    assert row["sequence"][1]["source"] == "5.5e baseline" and "record_id" not in row["sequence"][1]
    assert row["sequence"][2]["source"] == "character record" and row["sequence"][2]["record_id"] == "ACT_BIG"


def test_unparsed_cost_is_never_chosen():
    result = propose([tmpl("u", slot(0, "bonus_action"), slot(0, "action"))],
                     records=[rec("ACT_FOCUS", "Focus Strike", "action", parsed=False), rec("BON_FREE", "Quick Step", "bonus_action")])
    assert result.composites == [] and "no eligible action" in result.skipped[0]["reason"]


def test_default_templates_yield_validated_vendor_shaped_rows():
    registry = ActionRegistry(RECORDS)
    result = propose_playbooks(registry, resource_pools=POOLS, primary_resource_id=P)
    assert len(result.composites) == 4 and [item["template_id"] for item in result.skipped] == ["forged_signature"] and not result.rejected
    assert [row["composite_id"] for row in result.composites] == [
        f"gm.playbook.proposed.{t.template_id}" for t in load_templates().templates
        if t.template_id not in {s["template_id"] for s in result.skipped}]
    assert [row["priority"] for row in result.composites] == [1, 2, 3, 4]
    rules = load_rules()
    for row in result.composites:
        assert all(key in row for key in REQUIRED)
        assert all(all(key in step for key in STEP_REQUIRED) for step in row["sequence"])
        assert row["classification"] == "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY" and row["execution_authority"] is False
        assert row["capability_status"] == "SERVER_VALIDATED_PROPOSAL"
        assert row["validation"]["ok"] is True
        assert validate_playbook(row, registry=registry, rules=rules, resource_pools=POOLS).ok
    by_id = {row["composite_id"]: row for row in result.composites}
    assert ids(by_id["gm.playbook.proposed.opening_line"]) == ["BON_FREE", "ACT_MID", "ACT_FREE"]
    assert ids(by_id["gm.playbook.proposed.guarded_response"]) == ["ACT_FREE", "REA_GUARD"]
    assert ids(by_id["gm.playbook.proposed.mobility_reposition"]) == ["BON_FREE", "base.5e.dash", "ACT_MID"]


def test_fallback_is_zero_cost_and_prefers_an_action_outside_the_sequence():
    row = propose([OPENING]).composites[0]
    assert row["fallback_action_id"] == "base.5e.dash" and "Dash" in row["fallback"]
    none = propose([tmpl("f", slot(0, "bonus_action"), slot(0, "action", "highest_cost"))], fraction=1.0,
                   records=[rec("ACT_BIG", "Big Strike", "action", 4), rec("BON_FREE", "Quick Step", "bonus_action")]).composites[0]
    assert "fallback_action_id" not in none and "No zero-cost fallback" in none["fallback"]
    assert none["validation"]["ok"] is True


def test_missing_pool_means_no_cap_and_a_visible_warning():
    result = propose([OPENING], pools=None)
    row = result.composites[0]
    assert ids(row) == ["BON_FREE", "ACT_BIG", "ACT_MID"]
    assert any("not budget-capped" in w for w in result.warnings)
    assert "no pool total" in row["resource_budget"]
    assert row["validation"]["ok"] is True
    assert "RESOURCE_POOL_UNKNOWN" in [d["code"] for d in row["validation"]["diagnostics"]]


def test_hooks_override_and_registry_warnings_pass_through():
    registry = ActionRegistry(RECORDS, warnings=["adapter warning"])
    result = propose_playbooks(registry, templates=templates(OPENING), resource_pools=POOLS, primary_resource_id=P,
                               hooks={"dao_hook": "Custom dao."})
    assert result.warnings[0] == "adapter warning"
    assert result.composites[0]["dao_hook"] == "Custom dao." and ("Change when" in result.composites[0]["i_ching_hook"] or "change signal" in result.composites[0]["i_ching_hook"])


def test_deterministic_and_document_shape():
    first = propose([OPENING]).to_document(source_label="t")
    second = propose([OPENING]).to_document(source_label="t")
    assert first == second
    assert first["schema_version"] == "TianxiaFoundry.CharacterGMCompositePlaybooks.v1"
    assert first["execution_authority"] is False and first["classification"] == "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY"
    assert first["generator"]["kind"] == "deterministic_template_proposer" and first["generator"]["source"] == "t"
    assert first["generator"]["skipped_templates"] == [] and first["generator"]["rejected_count"] == 0
    assert first["generator"]["rejected"] == []
    assert isinstance(ProposalResult().to_document()["composites"], list)


def test_min_own_steps_rejects_baseline_only_playbooks():
    base_only = [rec("base.5e.attack", "Attack", "action", base=True), rec("base.5e.dash", "Dash", "action", base=True)]
    template = tmpl("b", slot(0, "action"), slot(1, "action"))
    loose = propose([template], records=base_only)  # helper mapping has no min_own_steps -> 0
    assert ids(loose.composites[0]) == ["base.5e.attack", "base.5e.dash"]
    mapping = {"schema_version": "TianxiaFoundry.CompositePlaybookTemplates.v1", "budget_fraction": 0.5,
               "fallback_economy": "action", "min_own_steps": 1,
               "hooks": {"dao_hook_default": "Dao text.", "i_ching_hook_default": "I Ching text."},
               "templates": [template]}
    strict = propose_playbooks(ActionRegistry(base_only), templates=TemplateSet.from_mapping(mapping),
                               resource_pools=POOLS, primary_resource_id=P)
    assert strict.composites == [] and "min_own_steps" in strict.skipped[0]["reason"]
    assert load_templates().min_own_steps == 1
    assert TemplateSet.from_mapping(mapping).with_templates([]).min_own_steps == 1
    with pytest.raises(ValueError):
        TemplateSet.from_mapping({**mapping, "min_own_steps": -1})


def test_rejected_rows_are_reported_with_their_diagnostics():
    # "Unknown" is a word the vendor nonEmptyString schema rejects, so the row fails SCHEMA and is withheld.
    records = [rec("ACT_UNK", "Unknown Strike", "action"), rec("ACT_FREE", "Free Strike", "action")]
    result = propose([tmpl("r", slot(0, "action"), slot(1, "action"))], records=records)
    assert result.composites == [] and len(result.rejected) == 1
    assert ids(result.rejected[0]) == ["ACT_FREE", "ACT_UNK"] and result.rejected[0]["validation"]["ok"] is False
    rejected = result.to_document()["generator"]["rejected"]
    assert len(rejected) == 1 and rejected[0]["composite_id"] == "gm.playbook.proposed.r" and rejected[0]["template_id"] == "r"
    assert rejected[0]["errors"] and all({"code", "pointer", "message"} <= set(err) for err in rejected[0]["errors"])
