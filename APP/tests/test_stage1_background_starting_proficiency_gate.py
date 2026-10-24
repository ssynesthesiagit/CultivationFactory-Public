"""Stage 1 presents only Backgrounds with complete frozen starting-proficiency authority.

Catalog release 0.6.1 gave every Background a Sphere-and-talent package, so all
31 became presentable. Three of them carry an unresolved tools line in the
Background authority ("one artisan's tool of your choice"), and request
assembly refuses the whole request when any presented Background lacks a
complete starting-proficiency contract entry. The presentation predicate and
the contract entry builder must agree exactly.
"""
from __future__ import annotations

import json
from pathlib import Path

from character_creation.starting_proficiency_authority import (
    _background_entry,
    _origin_entry,
    background_starting_proficiency_unresolved_reason,
    origin_starting_proficiency_unresolved,
)

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "non_sphere_authority" / "authority" / "Background_Core_Authority_v1.json"
LANGUAGE_AUTHORITY = {"offered_display_names": ["Classical", "Trade Pidgin"], "resolved": True}


def _backgrounds() -> dict[str, dict]:
    rows = json.loads(AUTHORITY.read_text(encoding="utf-8"))["backgrounds"]
    return {row["background_id"]: row for row in rows}


def test_authority_file_has_exactly_the_known_unresolved_backgrounds() -> None:
    backgrounds = _backgrounds()
    assert len(backgrounds) == 31
    unresolved = {
        background_id: background_starting_proficiency_unresolved_reason(background_id, row)
        for background_id, row in backgrounds.items()
    }
    # Owner 2026-09-28 ("Fix the rules"): the artisan's tool is named at the table, so the printed phrase stands as the
    # proficiency; Imperial Scholar knows Classical and chooses one more language. Every Background is presentable.
    assert {k: v for k, v in unresolved.items() if v is not None} == {}
    assert backgrounds["tianxia.background.artisan_s_child"]["tools_languages_trades"]["fixed_proficiencies"] == ["one artisan\u2019s tool of your choice"]
    scholar = _background_entry("tianxia.background.imperial_scholar", backgrounds["tianxia.background.imperial_scholar"], LANGUAGE_AUTHORITY)
    assert scholar["fixed_tool_proficiencies"] == ["calligrapher's supplies", "Classical (language)"] and scholar["language_choice_count"] == 1


def test_presentation_predicate_agrees_with_contract_entry_builder() -> None:
    for background_id, row in _backgrounds().items():
        reason = background_starting_proficiency_unresolved_reason(background_id, row)
        entry = _background_entry(background_id, row, LANGUAGE_AUTHORITY)
        assert (entry is None) == (reason is not None), background_id
        if entry is not None:
            assert entry["resolved"] is True
            assert entry["choice_id"] == background_id


def test_predicate_reasons_are_specific() -> None:
    row = _backgrounds()["tianxia.background.abandoned_orphan"]
    assert background_starting_proficiency_unresolved_reason(row["background_id"], row) is None
    assert background_starting_proficiency_unresolved_reason("other.id", row) == "authority_missing"
    broken = json.loads(json.dumps(row))
    broken["skills"]["resolved"] = False
    assert background_starting_proficiency_unresolved_reason(row["background_id"], broken) == "skills_unresolved"
    broken = json.loads(json.dumps(row))
    broken["tools_languages_trades"]["free_choice_count_detected"] = 2
    assert (
        background_starting_proficiency_unresolved_reason(row["background_id"], broken)
        == "language_choice_count_unsupported"
    )
    broken = json.loads(json.dumps(row))
    broken["skills"]["fixed_skill_names"] = ["Not A Skill"]
    assert background_starting_proficiency_unresolved_reason(row["background_id"], broken) == "fixed_skills_invalid"


def _origin(record_id: str, summary: str) -> dict:
    return {
        "record_id": record_id,
        "summary": summary,
        "source_evidence": [{"source_path": "x.md", "source_anchor": "a", "source_hash": "0" * 64}],
    }


def test_origin_grammar_accepts_oxford_comma_chosen_option_and_single_fixed_skill() -> None:
    three = _origin("o.grave", "You gain proficiency in Religion, History, or Medicine. If you already have proficiency in the chosen skill, gain expertise in it.")
    entry = _origin_entry("o.grave", three)
    assert entry is not None and entry["allowed_values"] == ["Religion", "History", "Medicine"]
    option = _origin("o.opt", "You gain proficiency in Deception or Perception. If you already have proficiency in the chosen option, gain expertise in it.")
    assert _origin_entry("o.opt", option)["allowed_values"] == ["Deception", "Perception"]
    single = _origin("o.one", "You gain proficiency in Intimidation. If you already have proficiency in Intimidation, gain expertise in it.")
    entry = _origin_entry("o.one", single)
    assert entry is not None and entry["allowed_values"] == ["Intimidation"] and entry["required_count"] == 1
    mismatch = _origin("o.bad", "You gain proficiency in Intimidation. If you already have proficiency in Stealth, gain expertise in it.")
    assert _origin_entry("o.bad", mismatch) is None


def test_origin_with_registry_options_is_typed_but_an_unprinted_tool_stays_unresolved() -> None:
    tool = _origin("o.tool", "You gain proficiency in Acrobatics, Athletics, or thieves' tools. If you already have proficiency in the chosen option, gain expertise in it.")
    entry = _origin_entry("o.tool", tool)
    assert entry is not None and entry["allowed_values"] == ["Acrobatics", "Athletics", "thieves' tools"]
    assert entry["option_kinds"] == {"Acrobatics": "skill", "Athletics": "skill", "thieves' tools": "tool"}
    assert entry["tool_authority"]["tool_ids"] == {"thieves' tools": "tianxia.tool_proficiency.thieves_tools"}
    assert origin_starting_proficiency_unresolved("o.tool", tool) is False
    trade = _origin("o.trade", "You gain proficiency in Insight, Perception, or one service trade proficiency. If you already have proficiency in the chosen option, gain expertise in it.")
    assert _origin_entry("o.trade", trade)["allowed_values"] == ["Insight", "Perception", "service trade"]
    unprinted = _origin("o.unprinted", "You gain proficiency in Insight, Perception, or glassblower's tools. If you already have proficiency in the chosen option, gain expertise in it.")
    assert _origin_entry("o.unprinted", unprinted) is None
    assert origin_starting_proficiency_unresolved("o.unprinted", unprinted) is True
    plain = _origin("o.plain", "You always know which way is north.")
    assert origin_starting_proficiency_unresolved("o.plain", plain) is False
    resolved = _origin("o.ok", "You gain proficiency in Deception or Perception. If you already have proficiency in the chosen skill, gain expertise in it.")
    assert origin_starting_proficiency_unresolved("o.ok", resolved) is False


def test_every_background_derives_the_single_score_ability_adjustment() -> None:
    from non_sphere_authority.service import derive_background_ability_adjustment

    backgrounds = _backgrounds()
    derived = {bid: derive_background_ability_adjustment(row) for bid, row in backgrounds.items()}
    assert all(isinstance(v, dict) for v in derived.values()), [k for k, v in derived.items() if v is None]
    assert derived["tianxia.background.ancestral_shrine_keeper"] == {"allowed_abilities": ["CHA", "INT", "WIS"], "amount": 2, "cap": 20}
    assert derived["tianxia.background.abandoned_orphan"] == {"allowed_abilities": ["CHA", "DEX", "WIS"], "amount": 2, "cap": 20}
    assert derive_background_ability_adjustment(None) is None
    assert derive_background_ability_adjustment({"ability_score_grants": {"modes": []}}) is None


def test_stat_block_records_are_not_selectable_talents() -> None:
    from pathlib import Path as _Path

    from canonical_catalog import CanonicalCatalogAuthorityService
    from app.core import FoundryError

    service = CanonicalCatalogAuthorityService(_Path(__file__).resolve().parents[1])
    data = service._load()
    assert not [row for row in data["talents"] if str(row["display_name"]).endswith(" Stat Block")]
    for talent_id in ("TAL_DEATH_CORPSE_SERVANT_STAT_BLOCK", "TAL_DEATH_GRAVE_FORMATION_STAT_BLOCK"):
        finding = data["legacy_non_talent_by_id"][talent_id]
        assert finding["finding"] == "stat_block_component_of_parent_talent"
        try:
            service.get_talent(talent_id)
        except FoundryError as exc:
            assert "not a selectable Talent" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("stat block was returned as a talent")
    assert service.get_talent("TAL_DEATH_CORPSE_SERVANT")["display_name"] == "Corpse Servant"
    assert data["counts"]["canonical_talents"] == len(data["talents"])
