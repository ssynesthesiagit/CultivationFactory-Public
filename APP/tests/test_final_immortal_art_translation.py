"""Final-stage rules check and compiler translation for controller-built Immortal Arts.

The synthetic Arts below follow the compiled construction rules exactly
(docs/rules/TIANXIA_RULES_AS_WRITTEN.md RAW-181..RAW-191); each negative case
breaks one rule and must be rejected.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from app.core import FoundryError, sha256_json
from factory_authoring.constructed_immortal_arts import (
    constructed_immortal_art_binding,
    read_constructed_immortal_arts,
    translate_constructed_immortal_arts,
)


def _art(cl_created: int, *, name: str = "Featherfall", die_rolls: tuple[int, ...] = (20,)) -> dict[str, Any]:
    """One Fortification Art with one direct Factor, built to the rules."""

    art_id = f"tianxia.constructed.immortal_art.synthetic.{cl_created}"
    tier = "Immortal" if cl_created >= 20 else "Nascent Soul"
    threshold = 6 if tier == "Immortal" else 3
    complexity = 2 + 2  # Aspect 2 + Factor 2, one source package, no bridge
    pressure = 2 * max(0, complexity - threshold)
    dc = 10 + complexity + 1 + 1 + 1 + pressure  # spheres, aspects, escalation(1 Factor)
    pb = 5 if cl_created <= 16 else 6
    attempts = []
    previous = None
    for index, die in enumerate(die_rolls):
        total = die + pb + 1
        attempts.append({
            "attempt_id": f"attempt.{cl_created}.{index}",
            "retry_of_attempt_id": previous,
            "check_die_result": die,
            "pb": pb,
            "ability_modifier": 1,
            "computed_check_total": total,
            "dc": dc,
            "result": "success" if total >= dc else "failure",
        })
        previous = attempts[-1]["attempt_id"]
    return {
        "schema": "TianxiaFoundry.ImmortalArt.v1",
        "immortal_art_id": art_id,
        "art_id": art_id,
        "record_id": art_id,
        "state": "known",
        "name": f"{name} — Fortification Immortal Art",
        "cl_created": cl_created,
        "realm": tier,
        "acquisition_event_id": f"event.synthetic.{cl_created}",
        "source_record_id": f"tianxia.path.qi_cultivation.feature.{name.lower().replace(' ', '_')}",
        "source_packet_ids": [f"packet.synthetic.{cl_created}"],
        "source_packages_used": ["tianxia.path.qi_cultivation"],
        "source_spheres_used": 1,
        "dao_aspect": {"aspect_id": "tianxia.dao_aspect.fortification", "display_name": "Fortification", "mandate_cost": 2, "cp_modifier": 2},
        "factors": [{"factor_id": "temporary_hp_fortification", "mandate_cost": 2, "cp_cost": 2}],
        "burdens": [],
        "correspondence": [{"factor_id": "temporary_hp_fortification", "bridge_factor_count": 0}],
        "mandate_complexity": complexity,
        "mandate_complexity_breakdown": {
            "aspect_cost": 2, "factor_cost": 2, "bridge_factor_cost": 0,
            "source_package_modifier": 0, "special_scale_cost": 0, "final": complexity,
        },
        "mandate_threshold": threshold,
        "heaven_pressure": pressure,
        "factor_escalation": 1,
        "refinement_dc": dc,
        "activation_cp": 5,
        "activation_cp_breakdown": {
            "base_source_cp": 1, "aspect_cp": 2, "factor_cp": 2, "bridge_cp": 0, "burden_cp_credit": 0, "final": 5,
        },
        "research_days": 5 * complexity,
        "material_cost_gp": 250 * complexity * complexity,
        "refinement": {"attempts": attempts},
        "action_surface": {
            "activation": "Reaction",
            "range": "60 feet",
            "target": "One falling creature",
            "duration": "1 minute",
            "resource_name": "Qi",
            "limits": ["Does not grant flight or horizontal movement."],
            "trigger": "You or a creature within 60 feet begins falling.",
            "trigger_frequency": "once per activation",
            "counterplay": "Preserve all source restrictions.",
            "cleanup": "Ends after 1 minute.",
        },
    }


def _action(art: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": f"action.synthetic.{art['cl_created']}",
        "record_id": art["record_id"],
        "name": art["name"],
        "cost": "5 Qi",
        "source_packet_ids": list(art["source_packet_ids"]),
    }


def _workspace(tmp_path: Path, *, cl: int, arts: list[dict[str, Any]], actions: list[dict[str, Any]] | None = None) -> Path:
    root = tmp_path / "workspace"
    (root / "Build").mkdir(parents=True)
    (root / "Command_4").mkdir()
    ledger = {
        "character": {"cl": cl},
        "immortal_arts": deepcopy(arts),
        "immortal_arts_none_state": {"state": "not_applicable", "source_backed": True},
        "advancement": {"levels": [{"cl": level} for level in range(1, cl + 1)]},
    }
    (root / "Build/Character_Master_Ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    (root / "Build/Immortal_Arts.json").write_text(json.dumps({"immortal_arts": deepcopy(arts)}), encoding="utf-8")
    surface = {"actions": [{"action_id": "action.other", "record_id": "talent.other"}, *(actions if actions is not None else [_action(art) for art in arts])]}
    for relative in ("Build/Complete_Action_Surface.json", "Command_4/Complete_Action_Surface.json"):
        (root / relative).write_text(json.dumps(surface), encoding="utf-8")
    return root


def test_rules_legal_arts_at_cl15_and_cl20_pass(tmp_path: Path) -> None:
    arts = [_art(15), _art(20, name="Qi Armor", die_rolls=(1, 13))]
    assert arts[0]["refinement_dc"] == 19 and arts[1]["refinement_dc"] == 17  # Heaven Pressure 2 vs 0
    checked = read_constructed_immortal_arts(_workspace(tmp_path, cl=20, arts=arts))
    assert [row["art"]["cl_created"] for row in checked] == [15, 20]
    assert [row["action"]["action_id"] for row in checked] == ["action.synthetic.15", "action.synthetic.20"]


def test_below_cl15_has_no_arts(tmp_path: Path) -> None:
    assert read_constructed_immortal_arts(_workspace(tmp_path, cl=14, arts=[])) == []


def _break(field: str) -> Any:
    def mutate(art: dict[str, Any]) -> None:
        if field == "refinement_dc":
            art["refinement_dc"] += 1
        elif field == "heaven_pressure":
            art["heaven_pressure"] = 0
        elif field == "mandate_complexity":
            art["mandate_complexity"] = 3
        elif field == "activation_cp":
            art["activation_cp"] = 4
            art["activation_cp_breakdown"]["final"] = 4
        elif field == "research_days":
            art["research_days"] = 10
        elif field == "material_cost_gp":
            art["material_cost_gp"] = 1000
        elif field == "refinement_history":
            art["refinement"]["attempts"][0]["result"] = "failure"
        elif field == "factor_escalation":
            art["factor_escalation"] = 3
        elif field == "realm":
            art["realm"] = "Immortal"
    return mutate


@pytest.mark.parametrize(
    "field",
    ["refinement_dc", "heaven_pressure", "mandate_complexity", "activation_cp", "research_days",
     "material_cost_gp", "refinement_history", "factor_escalation", "realm"],
)
def test_construction_rule_violations_are_rejected(tmp_path: Path, field: str) -> None:
    art = _art(15)
    _break(field)(art)
    with pytest.raises(FoundryError) as error:
        read_constructed_immortal_arts(_workspace(tmp_path, cl=15, arts=[art]))
    assert error.value.code == "FINAL_CHARACTER_IMMORTAL_ART_INVALID"


@pytest.mark.parametrize(
    ("cl", "levels", "reason"),
    [
        (15, [], "CL15+ character without its Immortal Art (RAW-182)"),
        (15, [14], "Art below CL15 (RAW-182)"),
        (16, [16, 16], "two Arts at one CL (RAW-183)"),
        (19, [15, 16, 17, 18], "more than the Factory Nascent Soul ceiling"),
        (16, [17], "Art created after the character's CL"),
    ],
)
def test_acquisition_rule_violations_are_rejected(tmp_path: Path, cl: int, levels: list[int], reason: str) -> None:
    arts = []
    for index, level in enumerate(levels):
        art = _art(max(level, 15))
        art["cl_created"] = level
        art["immortal_art_id"] = art["art_id"] = art["record_id"] = f"tianxia.constructed.immortal_art.case.{index}"
        arts.append(art)
    with pytest.raises(FoundryError) as error:
        read_constructed_immortal_arts(_workspace(tmp_path, cl=cl, arts=arts))
    assert error.value.code == "FINAL_CHARACTER_IMMORTAL_ART_INVALID", reason


def test_art_without_one_executable_action_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FoundryError) as error:
        read_constructed_immortal_arts(_workspace(tmp_path, cl=15, arts=[_art(15)], actions=[]))
    assert error.value.code == "FINAL_CHARACTER_IMMORTAL_ART_INVALID"


def test_diverging_action_surfaces_are_rejected(tmp_path: Path) -> None:
    root = _workspace(tmp_path, cl=15, arts=[_art(15)])
    (root / "Command_4/Complete_Action_Surface.json").write_text(json.dumps({"actions": []}), encoding="utf-8")
    with pytest.raises(FoundryError) as error:
        read_constructed_immortal_arts(root)
    assert error.value.code == "FINAL_CHARACTER_IMMORTAL_ART_INVALID"


def test_binding_changes_when_an_art_changes(tmp_path: Path) -> None:
    first = constructed_immortal_art_binding(_workspace(tmp_path / "a", cl=15, arts=[_art(15)]))
    second = constructed_immortal_art_binding(_workspace(tmp_path / "b", cl=15, arts=[_art(15, name="Qi Armor")]))
    assert first["binding_sha256"] == sha256_json({key: first[key] for key in ("schema_version", "arts")})
    assert first["binding_sha256"] != second["binding_sha256"]


def test_translation_produces_compiler_rows_allocations_and_tagged_actions(tmp_path: Path) -> None:
    arts = [_art(15), _art(20, name="Qi Armor", die_rolls=(1, 13))]
    root = _workspace(tmp_path, cl=20, arts=arts)
    translation = translate_constructed_immortal_arts(root)
    ledger = json.loads((root / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))

    rows = ledger["immortal_arts"]
    assert rows == translation["arts"]
    first = rows[0]
    for field in ("name", "dao_aspect", "status", "evolution_state", "allocation_id", "execution_summary", "acquisition_record"):
        assert isinstance(first[field], str) and first[field]
    assert first["dao_aspect"] == "Fortification"
    assert first["gained_at_cl"] == 15 and first["action_ids"] == ["action.synthetic.15"]
    assert first["limitations"] == ["Does not grant flight or horizontal movement.", "Trigger frequency: once per activation."]
    assert first["behavior_hooks"][0] == "Trigger: You or a creature within 60 feet begins falling."
    assert "Refinement DC 19" in first["acquisition_record"]
    assert "immortal_arts_none_state" not in ledger

    levels = {level["cl"]: level for level in ledger["advancement"]["levels"]}
    for art in rows:
        allocation = levels[art["gained_at_cl"]]["allocations"]
        assert len(allocation) == 1
        assert allocation[0]["allocation_id"] == art["allocation_id"]
        assert allocation[0]["channel"] == allocation[0]["grant_type"] == "immortal_art"
        assert allocation[0]["slot_cost"] == 0 and allocation[0]["name"] == art["name"]
    assert set(translation["allocations_by_cl"]) == {"15", "20"}

    tagged = [row for row in ledger["actions"] if row.get("classification") == "immortal_art"]
    assert sorted(row["action_id"] for row in tagged) == translation["action_ids"]
    for relative in ("Build/Complete_Action_Surface.json", "Command_4/Complete_Action_Surface.json"):
        surface = json.loads((root / relative).read_text(encoding="utf-8"))["actions"]
        assert [row for row in surface if row.get("classification") == "immortal_art"] == tagged
        assert {"action_id": "action.other", "record_id": "talent.other"} in surface
