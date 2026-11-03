"""The sealed Tool Proficiency Registry types Origin tool options end to end.

The campaign has no published tool list, so the registry is the set of tool,
kit, supplies, utensils and vehicle names printed in the bundled Backgrounds
book, Origin Insights book and ItemBook.  Every entry is bound to where it is
printed; the catalog re-verifies those bindings when it installs the records,
and every contract carries the registry hash so a different registry fails
closed at validation.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from app.core import sha256_json
from catalog.service import BACKGROUND_PACK_ID, BACKGROUND_PACK_VERSION, _markdown_heading_sections
from character_creation.starting_proficiency_authority import (
    TOOL_REGISTRY_PATH,
    _origin_entry,
    _tool_key,
    build_starting_proficiency_choice_contract,
    tool_proficiency_registry,
    validate_starting_proficiency_choices,
)
from projector.v3_bridge import _project_starting_proficiency_skills

AUTHORITY_ROOT = Path(__file__).parents[1] / "non_sphere_authority" / "authority"
BACKGROUND_SOURCE = AUTHORITY_ROOT / "Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md"
PATH_ID = "tianxia.path.qi_cultivation"
ORPHAN = "tianxia.background.abandoned_orphan"
HERMIT = "tianxia.background.forest_hermit"
QUICK_HANDS = "tianxia.origin_insight.quick_hands"
STEADY_HANDS = "tianxia.origin_insight.steady_hands"
QUICK_HANDS_TEXT = (
    "You gain proficiency in Sleight of Hand or thieves' tools. "
    "If you already have proficiency in the chosen option, gain expertise in it."
)
STEADY_HANDS_TEXT = (
    "You gain proficiency in Medicine, herbalism kit, or one artisan's tool. "
    "If you already have proficiency in the chosen option, gain expertise in it."
)


def _origin_row(origin_id: str, name: str, text: str) -> dict:
    return {
        "choice_id": origin_id,
        "name": name,
        "summary": text,
        "source_evidence": [{
            "source_path": "09_RULES/Source_Text/Tianxia_PHB_Origin_Insights_v0_4_READABILITY_SELF_CONTAINED.md",
            "source_hash": "b" * 64,
            "source_anchor": f"heading:{origin_id.rsplit('.', 1)[-1]}",
        }],
    }


def _build(background_id: str, origin_id: str, origin_name: str, origin_text: str) -> dict:
    paths_master = json.loads((AUTHORITY_ROOT / "Tianxia_Path_Index_Master_P2A.json").read_text())
    path_profiles = {}
    for row in paths_master["paths"]:
        profile = json.loads((AUTHORITY_ROOT / row["index_file"]).read_text())
        path_profiles[profile["canonical_id"]] = profile
    backgrounds_doc = json.loads((AUTHORITY_ROOT / "Background_Core_Authority_v1.json").read_text())
    backgrounds = {row["background_id"]: row for row in backgrounds_doc["backgrounds"]}
    source_text = BACKGROUND_SOURCE.read_text()
    return build_starting_proficiency_choice_contract(
        path_profiles=path_profiles,
        backgrounds=backgrounds,
        choices_by_slot={
            "path_choice": {PATH_ID: {"choice_id": PATH_ID, "name": "Qi Cultivation"}},
            "background_choice": {background_id: {"choice_id": background_id, "name": background_id}},
            "origin_insight_choice": {origin_id: _origin_row(origin_id, origin_name, origin_text)},
        },
        allowed_choice_ids_by_slot={
            "path_choice": [PATH_ID],
            "background_choice": [background_id],
            "origin_insight_choice": [origin_id],
        },
        campaign_language_source_text=source_text,
        campaign_language_source={
            "path": "09_RULES/Source_Text/Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md",
            "source_hash": hashlib.sha256(source_text.encode()).hexdigest(),
        },
    )


def _validate(contract: dict, background_id: str, origin_id: str, origin_value: str, language: str | None = "Classical") -> dict:
    bounded = {
        "path_skill_choices_by_path_id": {PATH_ID: ["Arcana", "Medicine"]},
        "origin_skill_choices_by_origin_id": {origin_id: [origin_value]},
    }
    if language is not None:
        bounded["background_language_choices_by_background_id"] = {background_id: [language]}
    return validate_starting_proficiency_choices(
        contract=contract,
        selected_by_slot={
            "path_choice": [PATH_ID],
            "background_choice": [background_id],
            "origin_insight_choice": [origin_id],
        },
        bounded_choices=bounded,
    )


def test_registry_is_sealed_and_every_binding_is_printed_in_the_bundled_sources(catalog_environment) -> None:
    registry = tool_proficiency_registry()
    assert registry is not None
    assert registry["registry_sha256"] == hashlib.sha256(TOOL_REGISTRY_PATH.read_bytes()).hexdigest()
    assert registry["offered_set_complete"] is False
    tools = registry["tools"]
    assert len(tools) == 29
    assert len({row["tool_id"] for row in tools}) == len(tools)
    assert len({_tool_key(row["display_name"]) for row in tools}) == len(tools)
    assert set(registry["artisan_display_names"]) == {
        "alchemist's supplies", "calligrapher's supplies", "carpenter's tools", "cartographer's tools",
        "cook's utensils", "jeweler's tools", "leatherworker's tools", "mason's tools", "painter's supplies",
        "smith's tools", "tinker's tools", "weaver's tools", "woodcarver's tools",
    }
    root = catalog_environment["root"]
    sections_by_path: dict[str, dict[str, str]] = {}
    for row in tools:
        assert row["printed_in"], row["tool_id"]
        for evidence in row["printed_in"]:
            path = root / evidence["source_path"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["source_hash"], (row["tool_id"], evidence)
            sections = sections_by_path.setdefault(
                evidence["source_path"], _markdown_heading_sections(path.read_text(encoding="utf-8"))
            )
            assert _tool_key(row["display_name"]) in _tool_key(sections[evidence["source_anchor"]]), (row["tool_id"], evidence)


def test_catalog_installs_one_tool_proficiency_record_per_registry_tool(catalog_environment) -> None:
    registry = tool_proficiency_registry()
    with catalog_environment["db"].connection() as conn:
        rows = [
            dict(row) for row in conn.execute(
                "SELECT record_id, display_name, source_path, source_hash, source_anchor, data_json "
                "FROM catalog_records WHERE content_type='tool_proficiency' AND pack_id=? AND pack_version=?",
                (BACKGROUND_PACK_ID, BACKGROUND_PACK_VERSION),
            )
        ]
    by_id = {row["record_id"]: row for row in rows}
    assert set(by_id) == {row["tool_id"] for row in registry["tools"]}
    for tool in registry["tools"]:
        record = by_id[tool["tool_id"]]
        first = tool["printed_in"][0]
        assert record["display_name"] == tool["display_name"]
        assert (record["source_path"], record["source_hash"], record["source_anchor"]) == (
            first["source_path"], first["source_hash"], first["source_anchor"],
        )
        raw = json.loads(record["data_json"])["compatibility"]["factory"]["raw_projection"]["raw_record"]
        assert raw["registry_id"] == registry["registry_id"]
        # Registry-wide identity stays out of the record so trade and
        # language additions never rebind unchanged tool records.
        assert "registry_sha256" not in raw
        assert raw["artisan"] is tool["artisan"]
    assert by_id["tianxia.tool_proficiency.thieves_tools"]["source_anchor"] == "heading:abandoned_orphan"
    assert by_id["tianxia.tool_proficiency.forgery_kit"]["source_anchor"] == "heading:20-paper_trail"
    assert by_id["tianxia.tool_proficiency.jeweler_s_tools"]["source_anchor"] == "heading:skills_and_tools"


def test_tool_bearing_origin_entry_carries_option_typing_and_the_registry_binding() -> None:
    contract = _build(ORPHAN, QUICK_HANDS, "Quick Hands", QUICK_HANDS_TEXT)
    entry = contract["fields"]["origin_skill_choices_by_origin_id"][QUICK_HANDS]
    assert entry["allowed_values"] == ["Sleight of Hand", "thieves' tools"]
    assert entry["option_kinds"] == {"Sleight of Hand": "skill", "thieves' tools": "tool"}
    assert entry["tool_authority"]["registry_sha256"] == tool_proficiency_registry()["registry_sha256"]
    assert entry["tool_authority"]["tool_ids"] == {"thieves' tools": "tianxia.tool_proficiency.thieves_tools"}
    assert "category_expansions" not in entry
    assert contract["unresolved"] == []


def test_one_artisan_s_tool_expands_to_the_registry_artisan_set_and_folds_named_tools() -> None:
    row = {
        "record_id": "o.tool_memory",
        "summary": (
            "You gain proficiency in one artisan's tool, smith's tools, carpenter's tools, or tinker's tools. "
            "If you already have proficiency in the chosen tool, gain expertise in it."
        ),
        "source_evidence": [{"source_path": "x.md", "source_anchor": "a", "source_hash": "0" * 64}],
    }
    entry = _origin_entry("o.tool_memory", row)
    assert entry is not None
    assert entry["allowed_values"] == tool_proficiency_registry()["artisan_display_names"]
    assert set(entry["option_kinds"].values()) == {"tool"}
    assert entry["category_expansions"] == {"one artisan's tool": entry["allowed_values"]}
    assert len(entry["allowed_values"]) == len(set(entry["allowed_values"]))


def test_tool_pick_becomes_a_tool_proficiency_and_a_background_duplicate_becomes_expertise() -> None:
    # Forest Hermit grants the herbalism kit outright; Abandoned Orphan does not.
    contract = _build(ORPHAN, QUICK_HANDS, "Quick Hands", QUICK_HANDS_TEXT)
    result = _validate(contract, ORPHAN, QUICK_HANDS, "thieves' tools")
    assert result["blockers"] == [] and result["valid"] is True
    origin = result["normalized_mechanics"]["origin"]
    assert origin == {
        "origin_id": QUICK_HANDS,
        "selected_skill": None,
        "selected_tool": "thieves' tools",
        "selected_tool_id": "tianxia.tool_proficiency.thieves_tools",
        "result": "expertise",
    }
    proficiencies = result["normalized_mechanics"]["proficiencies"]
    assert proficiencies["tools"] == ["thieves' tools"]
    assert proficiencies["tool_expertise"] == ["thieves' tools"]
    assert proficiencies["expertise"] == []
    assert proficiencies["skills"] == ["Arcana", "Medicine", "Deception", "Sleight of Hand"]

    contract = _build(HERMIT, STEADY_HANDS, "Steady Hands", STEADY_HANDS_TEXT)
    result = _validate(contract, HERMIT, STEADY_HANDS, "smith's tools", language=None)
    assert result["blockers"] == []
    proficiencies = result["normalized_mechanics"]["proficiencies"]
    assert proficiencies["tools"] == ["the herbalism kit", "smith's tools"]
    assert proficiencies["tool_expertise"] == []
    assert result["normalized_mechanics"]["origin"]["result"] == "proficiency"
    duplicate = _validate(contract, HERMIT, STEADY_HANDS, "herbalism kit", language=None)
    assert duplicate["blockers"] == []
    assert duplicate["normalized_mechanics"]["origin"]["result"] == "expertise"
    assert duplicate["normalized_mechanics"]["proficiencies"]["tools"] == ["the herbalism kit"]
    assert duplicate["normalized_mechanics"]["proficiencies"]["tool_expertise"] == ["herbalism kit"]


def test_skill_pick_on_a_tool_bearing_origin_keeps_the_v1_mechanics_shape() -> None:
    contract = _build(ORPHAN, QUICK_HANDS, "Quick Hands", QUICK_HANDS_TEXT)
    result = _validate(contract, ORPHAN, QUICK_HANDS, "Sleight of Hand")
    assert result["blockers"] == []
    assert result["normalized_mechanics"]["origin"] == {
        "origin_id": QUICK_HANDS,
        "selected_skill": "Sleight of Hand",
        "result": "expertise",
    }
    assert set(result["normalized_mechanics"]["proficiencies"]) == {"skills", "tools", "languages", "expertise"}


def _resealed(contract: dict) -> dict:
    unsigned = {key: contract[key] for key in ("schema", "fields", "unresolved", "policy")}
    return {**contract, "contract_sha256": sha256_json(unsigned)}


def test_entry_typing_is_checked_structurally_and_by_membership_under_the_same_registry() -> None:
    contract = _build(ORPHAN, QUICK_HANDS, "Quick Hands", QUICK_HANDS_TEXT)
    # An unprinted tool smuggled into a contract sealed against this registry
    # is refused by membership.
    smuggled = deepcopy(contract)
    entry = smuggled["fields"]["origin_skill_choices_by_origin_id"][QUICK_HANDS]
    entry["allowed_values"].append("glassblower's tools")
    entry["option_kinds"]["glassblower's tools"] = "tool"
    entry["tool_authority"]["tool_ids"]["glassblower's tools"] = "tianxia.tool_proficiency.glassblower_s_tools"
    result = _validate(_resealed(smuggled), ORPHAN, QUICK_HANDS, "glassblower's tools")
    assert result["valid"] is False
    assert any(row["code"] == "CONTRACT_ENTRY_TOOL_AUTHORITY_INVALID" for row in result["blockers"])
    # A request sealed against an earlier registry edition stays valid: the
    # entry is coherent with itself (ids are the canonical ids of the names).
    earlier = deepcopy(contract)
    earlier["fields"]["origin_skill_choices_by_origin_id"][QUICK_HANDS]["tool_authority"]["registry_sha256"] = "f" * 64
    result = _validate(_resealed(earlier), ORPHAN, QUICK_HANDS, "thieves' tools")
    assert result["valid"] is True
    # ...but an id that is not the canonical id of its name is refused even then.
    forged = deepcopy(earlier)
    forged["fields"]["origin_skill_choices_by_origin_id"][QUICK_HANDS]["tool_authority"]["tool_ids"]["thieves' tools"] = "tianxia.tool_proficiency.other"
    result = _validate(_resealed(forged), ORPHAN, QUICK_HANDS, "thieves' tools")
    assert result["valid"] is False
    assert any(row["code"] == "CONTRACT_ENTRY_TOOL_AUTHORITY_INVALID" for row in result["blockers"])


LISTEN_WHILE_SERVING = "tianxia.origin_insight.listen_while_serving"
LISTEN_WHILE_SERVING_TEXT = (
    "You gain proficiency in Insight, Perception, or one service trade proficiency. "
    "If you already have proficiency in the chosen option, gain expertise in it."
)
BREATH_BEFORE_THOUGHT_TEXT = (
    "You gain proficiency in Insight, Perception, or meditation, breath, or discipline practice as a trade proficiency. "
    "If you already have proficiency in the chosen option, gain expertise in it."
)
FAMILY_NAME = "tianxia.origin_insight.family_name"
FAMILY_NAME_TEXT = (
    "You gain proficiency in Persuasion, History, or one language tied to your family, clan, or region. "
    "If you already have proficiency in the chosen option, gain expertise in it."
)
SECT_SERVANT = "tianxia.background.sect_servant"


def test_printed_trade_phrases_and_language_categories_type_the_last_five_origins() -> None:
    registry = tool_proficiency_registry()
    assert [row["display_name"] for row in registry["trades"]] == ["service trade", "meditation, breath, or discipline practice"]
    assert set(registry["language_categories"]) == {
        "one court or formal campaign language",
        "one language tied to your family, clan, or region",
    }
    breath = _origin_entry("o.breath", {
        "record_id": "o.breath", "summary": BREATH_BEFORE_THOUGHT_TEXT,
        "source_evidence": [{"source_path": "x.md", "source_anchor": "a", "source_hash": "0" * 64}],
    })
    # The phrase's own commas and "or" do not split it into fake options.
    assert breath["allowed_values"] == ["Insight", "Perception", "meditation, breath, or discipline practice"]
    assert breath["option_kinds"]["meditation, breath, or discipline practice"] == "trade"
    assert breath["tool_authority"]["trade_ids"] == {
        "meditation, breath, or discipline practice": "tianxia.trade_proficiency.meditation_breath_or_discipline_practice",
    }
    family = _origin_entry("o.family", {
        "record_id": "o.family", "summary": FAMILY_NAME_TEXT,
        "source_evidence": [{"source_path": "x.md", "source_anchor": "a", "source_hash": "0" * 64}],
    })
    assert family["allowed_values"] == ["Persuasion", "History", "ancestral liturgical language", "regional ritual language"]
    assert family["option_kinds"]["regional ritual language"] == "language"
    assert family["tool_authority"]["language_categories"] == {
        "one language tied to your family, clan, or region": ["ancestral liturgical language", "regional ritual language"],
    }
    assert family["category_expansions"] == family["tool_authority"]["language_categories"]


def test_trade_and_language_picks_become_typed_proficiencies() -> None:
    contract = _build(SECT_SERVANT, LISTEN_WHILE_SERVING, "Listen While Serving", LISTEN_WHILE_SERVING_TEXT)
    result = _validate(contract, SECT_SERVANT, LISTEN_WHILE_SERVING, "service trade", language=None)
    assert result["blockers"] == []
    assert result["normalized_mechanics"]["origin"] == {
        "origin_id": LISTEN_WHILE_SERVING,
        "selected_skill": None,
        "selected_trade": "service trade",
        "selected_trade_id": "tianxia.trade_proficiency.service_trade",
        "result": "proficiency",
    }
    proficiencies = result["normalized_mechanics"]["proficiencies"]
    assert proficiencies["trades"] == ["service trade"]
    assert proficiencies["trade_expertise"] == []
    projected = _project_starting_proficiency_skills(
        result["normalized_mechanics"], path_ids=[PATH_ID], background_id=SECT_SERVANT, origin_id=LISTEN_WHILE_SERVING,
        final_mods={"STR": 0, "DEX": 2, "CON": 1, "INT": 4, "WIS": 3, "CHA": 5}, final_pb=2,
    )
    assert projected["origin_trade"] == "service trade" and projected["origin_skill"] is None
    assert projected["trade_proficiencies"] == ["service trade"]

    contract = _build(ORPHAN, FAMILY_NAME, "Family Name", FAMILY_NAME_TEXT)
    result = _validate(contract, ORPHAN, FAMILY_NAME, "regional ritual language")
    assert result["blockers"] == []
    assert result["normalized_mechanics"]["origin"]["selected_language"] == "regional ritual language"
    assert result["normalized_mechanics"]["proficiencies"]["languages"] == ["Classical", "regional ritual language"]
    projected = _project_starting_proficiency_skills(
        result["normalized_mechanics"], path_ids=[PATH_ID], background_id=ORPHAN, origin_id=FAMILY_NAME,
        final_mods={"STR": 0, "DEX": 2, "CON": 1, "INT": 4, "WIS": 3, "CHA": 5}, final_pb=2,
    )
    assert projected["origin_language"] == "regional ritual language"
    assert projected["language_proficiencies"] == ["Classical", "regional ritual language"]
    # A language the Background already granted becomes expertise, as printed.
    duplicate = _validate(contract, ORPHAN, FAMILY_NAME, "ancestral liturgical language", language="ancestral liturgical language")
    assert duplicate["blockers"] == []
    assert duplicate["normalized_mechanics"]["origin"]["result"] == "expertise"
    assert duplicate["normalized_mechanics"]["proficiencies"]["language_expertise"] == ["ancestral liturgical language"]


def test_projector_projects_a_tool_pick_as_a_tool_not_a_skill() -> None:
    contract = _build(ORPHAN, QUICK_HANDS, "Quick Hands", QUICK_HANDS_TEXT)
    validated = _validate(contract, ORPHAN, QUICK_HANDS, "thieves' tools")
    result = _project_starting_proficiency_skills(
        validated["normalized_mechanics"],
        path_ids=[PATH_ID],
        background_id=ORPHAN,
        origin_id=QUICK_HANDS,
        final_mods={"STR": 0, "DEX": 2, "CON": 1, "INT": 4, "WIS": 3, "CHA": 5},
        final_pb=2,
    )
    assert result["origin_skill"] is None
    assert result["origin_tool"] == "thieves' tools"
    assert result["origin_result"] == "expertise"
    assert result["tool_proficiencies"] == ["thieves' tools"]
    assert result["tool_expertise"] == ["thieves' tools"]
    assert result["proficient_skills"] == ["Arcana", "Deception", "Medicine", "Sleight of Hand"]
    assert all(multiplier == 1 for multiplier in result["skill_proficiency_multipliers"].values())


def test_validated_background_duplicate_tool_projects_through_the_projector() -> None:
    # Owner build 2026-10-10: Forest Hermit grants "the herbalism kit"; an Origin
    # "herbalism kit" pick becomes expertise and must project, not block.
    contract = _build(HERMIT, STEADY_HANDS, "Steady Hands", STEADY_HANDS_TEXT)
    validated = _validate(contract, HERMIT, STEADY_HANDS, "herbalism kit", language=None)
    assert validated["blockers"] == []
    result = _project_starting_proficiency_skills(
        validated["normalized_mechanics"],
        path_ids=[PATH_ID],
        background_id=HERMIT,
        origin_id=STEADY_HANDS,
        final_mods={"STR": 0, "DEX": 2, "CON": 1, "INT": 4, "WIS": 3, "CHA": 5},
        final_pb=2,
    )
    assert result["origin_tool"] == "herbalism kit"
    assert result["origin_result"] == "expertise"
    assert result["tool_proficiencies"] == ["the herbalism kit"]
    assert result["tool_expertise"] == ["herbalism kit"]
