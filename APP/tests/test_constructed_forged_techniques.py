"""Factory-constructed Forged Techniques: sealed tables, seeded construction, re-derivation."""
from __future__ import annotations

import hashlib
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import FoundryError  # noqa: E402
from character_creation.constructed_arts.forged_technique import (  # noqa: E402
    compile_forged_technique,
    construct_forged_technique,
)
from character_creation.constructed_arts.forging_authority import load_forging_authority  # noqa: E402
from character_creation.constructed_arts.records import (  # noqa: E402
    FORGED_TECHNIQUE_PACK_ID,
    build_forged_technique_record,
    validate_forged_technique_record,
)
from contracts.registry import SchemaRegistry  # noqa: E402

SOURCE = {"source_id": "source.test", "path": "09_RULES/Source_Text/Compendium.md", "anchor": "line:10:column:1", "source_hash": "a" * 64}


def _talent(tid: str, sphere: str, name: str) -> dict:
    return {"talent_id": tid, "sphere_id": sphere, "display_name": name, "record_hash": "b" * 64, "source": SOURCE, "published_text": f"#### {name}\nPrinted effect of {name}."}


def _request(cl: int = 10, pb: int = 4, **overrides) -> dict:
    request = {
        "seed": "test-seed",
        "project_id": "project-1",
        "cl": cl,
        "pb": pb,
        "path_id": "tianxia.path.body_refining",
        "key_ability": "CON",
        "known_spheres": [
            {"sphere_id": "tianxia.sphere.blood", "display_name": "Blood"},
            {"sphere_id": "tianxia.sphere.athletics", "display_name": "Athletics"},
            {"sphere_id": "tianxia.sphere.brute", "display_name": "Brute"},
        ],
        "known_talents": [
            _talent("tianxia.talent.blood.crimson_mark", "tianxia.sphere.blood", "Crimson Mark"),
            _talent("TAL_ATHLETICS_MOBILITY", "tianxia.sphere.athletics", "Mobility"),
            _talent("TAL_BRUTE_BREAK_DEFENSES", "tianxia.sphere.brute", "Break Defenses"),
        ],
        "concept": {},
    }
    request.update(overrides)
    return request


@pytest.fixture(scope="module")
def authority():
    return load_forging_authority(ROOT)


def test_sealed_authority_carries_the_core_11_tables(authority):
    forms = {row["form_id"]: row for row in authority["base_forms"]}
    assert forms["strike"]["starting_cp"] == 1 and forms["zone"]["complexity"] == 3 and forms["ritual"]["starting_cp"] is None
    limits = {row["realm"]: row["maximum_complexity"] for row in authority["realm_complexity_limits"]}
    assert limits == {"Mortal": 2, "Foundation": 4, "Core Formation": 6, "Nascent Soul": 8, "Immortal": 10}
    augments = {row["augment_id"]: row for row in authority["augments"]}
    assert augments["bonus_action_activation"] == {"augment_id": "bonus_action_activation", "display_name": "Bonus-Action Activation", "tier": "advanced", "complexity": 2, "cp": 3, "minimum_realm": "Core Formation"}
    drawbacks = {row["drawback_id"]: row["cp_reduction"] for row in authority["drawbacks"]}
    assert drawbacks["once_per_long_rest"] == 2 and drawbacks["exhausting"] == 2 and drawbacks["backlash"] == 1
    assert authority["forging_check"]["dc"] == {"base": 10, "per_complexity": 1, "per_sphere": 1}
    assert authority["access"]["minimum_cl"] == 5


def test_construction_is_deterministic_and_within_realm_limits(authority):
    first = construct_forged_technique(authority, _request())
    second = construct_forged_technique(authority, _request())
    assert first == second
    assert first["realm"] == "Core Formation"
    assert first["complexity"]["final"] <= 6
    assert first["spheres_used"] <= 3
    assert first["cp_cost"]["final"] >= 1
    assert first["cp_cost"]["drawback_reduction"] <= 4
    assert first["technique_forging_dc"] == 10 + first["complexity"]["final"] + first["spheres_used"]
    assert first["research_days"] == max(3, 3 * first["complexity"]["final"])
    assert first["material_cost_gp"] == 100 * first["complexity"]["final"] ** 2
    assert first["effect"]["primary_effect_text"].startswith("#### ")
    different = construct_forged_technique(authority, _request(seed="another-seed"))
    assert different["technique_id"] != first["technique_id"]


def test_seeded_generator_successor_preserves_valid_legacy_record_bytes(authority):
    legacy = construct_forged_technique(authority, _request(), generator_version=1)
    assert "generator_version" not in legacy["construction"]
    record = build_forged_technique_record(legacy)
    assert validate_forged_technique_record(record, root_dir=ROOT) == legacy
    current = construct_forged_technique(authority, _request())
    assert current["construction"]["generator_version"] == 2
    assert current["technique_id"] != legacy["technique_id"]
    assert validate_forged_technique_record(build_forged_technique_record(current), root_dir=ROOT) == current


@pytest.mark.parametrize("version", [0, 4, True, "2"])
def test_unsupported_generator_versions_fail_closed(authority, version):
    with pytest.raises(FoundryError) as error:
        construct_forged_technique(authority, _request(), generator_version=version)
    assert error.value.code == "FORGING_GENERATOR_VERSION_UNSUPPORTED"


def test_explicit_design_does_not_invent_optional_components(authority):
    concept = {"name": "Measured Form", "base_form": "projection", "primary_talent_id": "tianxia.talent.blood.crimson_mark", "secondary_talent_ids": [], "augment_ids": [], "drawback_ids": []}
    for seed in ("explicit-one", "explicit-two", "explicit-three"):
        technique = construct_forged_technique(authority, _request(cl=20, pb=6, seed=seed, concept=concept), generator_version=3)
        assert technique["secondary_sphere_effects"] == []
        assert technique["augments"] == []
        assert technique["drawbacks"] == []
        assert technique["cp_cost"]["final"] == 1
        assert technique["complexity"]["final"] == 1
        assert technique["construction"]["generator_version"] == 3
        assert validate_forged_technique_record(build_forged_technique_record(technique), root_dir=ROOT) == technique


@pytest.mark.parametrize("missing", ["primary_talent_id", "base_form"])
def test_explicit_design_requires_primary_source_and_shape(authority, missing):
    concept = {"base_form": "projection", "primary_talent_id": "tianxia.talent.blood.crimson_mark"}
    concept.pop(missing)
    with pytest.raises(FoundryError) as error:
        construct_forged_technique(authority, _request(concept=concept), generator_version=3)
    assert error.value.code == "FORGING_EXPLICIT_CONCEPT_REQUIRED"


def test_concept_is_honoured_when_legal(authority):
    concept = {
        "name": "Crimson Counter",
        "base_form": "counter",
        "primary_talent_id": "tianxia.talent.blood.crimson_mark",
        "secondary_talent_ids": ["TAL_BRUTE_BREAK_DEFENSES"],
        "augment_ids": ["increased_damage"],
        "drawback_ids": ["backlash", "once_per_long_rest"],
    }
    technique = construct_forged_technique(authority, _request(concept=concept))
    assert technique["name"] == "Crimson Counter"
    assert technique["base_form"]["form_id"] == "counter"
    assert technique["action_type"] == "reaction"
    assert technique["complexity"]["final"] == 3 + 1 + 1
    assert technique["cp_cost"] == {"base_form": 3, "augments": 1, "drawback_reduction": 3, "final": 1}
    assert technique["backlash"] is not None
    assert technique["technique_forging_dc"] == 10 + 5 + 2


@pytest.mark.parametrize("rest_ids", [
    ["once_per_short_rest", "once_per_long_rest"],
    ["once_per_long_rest", "once_per_short_rest"],
])
def test_redundant_rest_limits_are_rejected_by_constructor_and_compiler(authority, rest_ids):
    concept = {"base_form": "zone", "augment_ids": ["increased_damage"], "drawback_ids": rest_ids}
    with pytest.raises(FoundryError) as invalid_request:
        construct_forged_technique(authority, _request(concept=concept))
    assert invalid_request.value.code == "FORGING_DRAWBACK_REDUNDANT"

    # Reproduce a stored candidate with internally consistent numeric costs:
    # compilation must reject the redundant restriction independently.
    concept["drawback_ids"] = [rest_ids[0]]
    technique = construct_forged_technique(authority, _request(concept=concept))
    technique["drawbacks"] = [deepcopy(next(row for row in authority["drawbacks"] if row["drawback_id"] == did)) for did in rest_ids]
    technique["cp_cost"].update(drawback_reduction=3, final=1)
    known = {row["talent_id"] for row in [technique["primary_sphere_effect"], *technique["secondary_sphere_effects"]]}
    with pytest.raises(FoundryError) as invalid_candidate:
        compile_forged_technique(authority, technique, cl=10, pb=4, known_talent_ids=known, known_forged_technique_count=0)
    assert invalid_candidate.value.code == "FORGING_DRAWBACK_REDUNDANT"


def test_generated_rest_limits_do_not_stack_and_each_still_occurs(authority):
    seen = set()
    for seed in range(200):
        technique = construct_forged_technique(authority, _request(cl=20, pb=6, seed=f"rest-limit-{seed}"))
        rest_ids = {row["drawback_id"] for row in technique["drawbacks"]} & {"once_per_short_rest", "once_per_long_rest"}
        assert len(rest_ids) <= 1
        seen.update(rest_ids)
    assert seen == {"once_per_short_rest", "once_per_long_rest"}


def test_multiple_activation_modes_are_not_silently_collapsed(authority):
    concept = {"base_form": "strike", "augment_ids": ["bonus_action_activation", "reaction_activation"], "drawback_ids": ["once_per_short_rest"]}
    with pytest.raises(FoundryError) as invalid_request:
        construct_forged_technique(authority, _request(cl=20, pb=6, concept=concept))
    assert invalid_request.value.code == "FORGING_ACTIVATION_AMBIGUOUS"
    concept["augment_ids"] = ["bonus_action_activation"]
    technique = construct_forged_technique(authority, _request(cl=20, pb=6, concept=concept))
    technique["augments"].append(deepcopy(next(row for row in authority["augments"] if row["augment_id"] == "reaction_activation")))
    known = {row["talent_id"] for row in [technique["primary_sphere_effect"], *technique["secondary_sphere_effects"]]}
    with pytest.raises(FoundryError) as invalid_candidate:
        compile_forged_technique(authority, technique, cl=20, pb=6, known_talent_ids=known, known_forged_technique_count=0)
    assert invalid_candidate.value.code == "FORGING_ACTIVATION_AMBIGUOUS"


def test_generated_activation_choices_remain_distinct(authority):
    seen = set()
    for seed in range(200):
        technique = construct_forged_technique(authority, _request(cl=20, pb=6, seed=f"activation-{seed}"))
        modes = {row["augment_id"] for row in technique["augments"]} & {"bonus_action_activation", "reaction_activation"}
        assert len(modes) <= 1
        if modes:
            mode = modes.pop()
            assert technique["action_type"] == {"bonus_action_activation": "bonus action", "reaction_activation": "reaction"}[mode]
            seen.add(mode)
    assert seen == {"bonus_action_activation", "reaction_activation"}


def test_forging_refuses_mortal_realm_known_limit_and_unknown_talents(authority):
    with pytest.raises(FoundryError) as too_early:
        construct_forged_technique(authority, _request(cl=4, pb=2))
    assert too_early.value.code == "FORGING_NOT_AVAILABLE"
    with pytest.raises(FoundryError) as full:
        construct_forged_technique(authority, _request(known_forged_technique_count=4))
    assert full.value.code == "FORGING_KNOWN_LIMIT_REACHED"
    with pytest.raises(FoundryError) as high:
        construct_forged_technique(authority, _request(cl=6, pb=3, concept={"augment_ids": ["domain_effect"]}))
    assert high.value.code == "FORGING_AUGMENT_REALM_TOO_LOW"
    with pytest.raises(FoundryError) as over:
        construct_forged_technique(authority, _request(cl=6, pb=3, concept={"base_form": "zone", "augment_ids": ["major_condition"]}))
    assert over.value.code == "FORGING_COMPLEXITY_EXCEEDED"
    technique = construct_forged_technique(authority, _request())
    with pytest.raises(FoundryError) as unknown:
        compile_forged_technique(authority, technique, cl=10, pb=4, known_talent_ids={"somebody.elses.talent"}, known_forged_technique_count=0)
    assert unknown.value.code == "FORGING_TALENT_NOT_KNOWN"


def test_compile_fails_closed_on_drifted_figures(authority):
    technique = construct_forged_technique(authority, _request())
    known = {row["talent_id"] for row in [technique["primary_sphere_effect"], *technique["secondary_sphere_effects"]]}
    drifted = deepcopy(technique)
    drifted["cp_cost"]["final"] = 0
    with pytest.raises(FoundryError) as excinfo:
        compile_forged_technique(authority, drifted, cl=10, pb=4, known_talent_ids=known, known_forged_technique_count=0)
    assert excinfo.value.code == "FORGED_TECHNIQUE_FIGURES_DRIFTED"
    assert "cp_cost" in excinfo.value.details["drift"]
    for field, mutate in (
        ("cp_cost_breakdown", lambda value: value.__setitem__("augments", value["augments"] + 1)),
        ("complexity_breakdown", lambda value: value.__setitem__("base_form", value["base_form"] + 1)),
    ):
        nested_drifted = deepcopy(technique)
        mutate(nested_drifted["cp_cost"] if field == "cp_cost_breakdown" else nested_drifted["complexity"])
        with pytest.raises(FoundryError) as excinfo:
            compile_forged_technique(
                authority,
                nested_drifted,
                cl=10,
                pb=4,
                known_talent_ids=known,
                known_forged_technique_count=0,
            )
        assert excinfo.value.code == "FORGED_TECHNIQUE_FIGURES_DRIFTED"
        assert field in excinfo.value.details["drift"]
    action_drifted = deepcopy(technique)
    action_drifted["action_type"] = "not-a-published-action"
    with pytest.raises(FoundryError) as excinfo:
        compile_forged_technique(
            authority,
            action_drifted,
            cl=10,
            pb=4,
            known_talent_ids=known,
            known_forged_technique_count=0,
        )
    assert excinfo.value.code == "FORGED_TECHNIQUE_FIGURES_DRIFTED"
    assert "action_type" in excinfo.value.details["drift"]


def test_record_is_schema_valid_and_re_derives(authority):
    technique = construct_forged_technique(authority, _request())
    record = build_forged_technique_record(technique)
    assert record["content_type"] == "forged_technique_component"
    assert record["content_binding"]["pack_id"] == FORGED_TECHNIQUE_PACK_ID
    report = SchemaRegistry(ROOT).report(record, "TianxiaFoundry.RulesCatalogRecord.v1")
    assert report["valid"], report["diagnostics"]
    assert validate_forged_technique_record(record, root_dir=ROOT)["technique_id"] == technique["technique_id"]
    assert build_forged_technique_record(technique) == record
    tampered = deepcopy(record)
    tampered["compatibility"]["factory"]["constructed_art"]["technique"]["cp_cost"]["final"] = 0
    with pytest.raises(FoundryError) as excinfo:
        validate_forged_technique_record(tampered, root_dir=ROOT)
    assert excinfo.value.code == "CONSTRUCTED_ART_RECORD_INVALID"
    renamed = deepcopy(record)
    renamed["display_name"] = "Something else"
    with pytest.raises(FoundryError) as excinfo:
        validate_forged_technique_record(renamed, root_dir=ROOT)
    assert excinfo.value.code == "CONSTRUCTED_ART_RECORD_INVALID"
    arbitrary_id = deepcopy(technique)
    arbitrary_id["technique_id"] = "tianxia.constructed.forged_technique.arbitrary"
    arbitrary_id_record = build_forged_technique_record(arbitrary_id)
    with pytest.raises(FoundryError) as excinfo:
        validate_forged_technique_record(arbitrary_id_record, root_dir=ROOT)
    assert excinfo.value.code == "CONSTRUCTED_ART_RECORD_INVALID"


def _manual_request(
    access_category: str = "open",
    *,
    talent_count: int = 1,
    factory_root: Path | None = None,
) -> dict:
    if factory_root is None:
        source_hash = ("d" if talent_count == 1 else "f") * 64
        mobility_source_hash = "f" * 64
        crimson_block = "#### Crimson Mark\nAction: mark a creature.\nDuration: 1 round."
        mobility_block = "#### Mobility\nAction: move with care.\nDuration: 1 round."
    else:
        factory_root.mkdir(parents=True, exist_ok=True)
        source_path = factory_root / "Compendium.md"
        source_path.write_text(
            "\n".join(
                [
                    "# Compendium",
                    "",
                    "Preface.",
                    "",
                    "Rules.",
                    "",
                    "Published Talents",
                    "",
                    "---",
                    "#### Crimson Mark",
                    "Action: mark a creature.",
                    "Duration: 1 round.",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "#### Mobility",
                    "Action: move with care.",
                    "Duration: 1 round.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        mobility_source_hash = source_hash
        crimson_block = "#### Crimson Mark\nAction: mark a creature.\nDuration: 1 round."
        mobility_block = "#### Mobility\nAction: move with care.\nDuration: 1 round."
    source_path_value = "Compendium.md" if factory_root is not None else "Compendium.md"
    spheres = [
        {"sphere_id": "tianxia.sphere.blood", "display_name": "Blood"},
        {"sphere_id": "tianxia.sphere.athletics", "display_name": "Athletics"},
    ]
    talents = [
        {
            "talent_id": "tianxia.talent.blood.crimson_mark",
            "sphere_id": "tianxia.sphere.blood",
            "display_name": "Crimson Mark",
            "record_hash": "c" * 64,
            "source": {"source_id": "source.talent.blood", "path": source_path_value, "anchor": "line:10:column:1", "source_hash": source_hash},
            "published_text": crimson_block,
            "access_category": access_category,
        },
        {
            "talent_id": "tianxia.talent.athletics.mobility",
            "sphere_id": "tianxia.sphere.athletics",
            "display_name": "Mobility",
            "record_hash": "e" * 64,
            "source": {"source_id": "source.talent.athletics", "path": source_path_value, "anchor": "line:20:column:1", "source_hash": mobility_source_hash},
            "published_text": mobility_block,
            "access_category": access_category,
        },
    ]
    return {
        "seed": "manual-test-seed",
        "project_id": "project-manual",
        "cl": 10,
        "pb": 4,
        "path_id": "tianxia.path.body_refining",
        "key_ability": "CON",
        "known_spheres": spheres,
        "known_talents": talents[:talent_count],
        "lineage_source": {"sect_trial_sphere_id": "tianxia.sphere.blood", "background_id": "background.test"},
    }


def test_lineage_manual_is_three_fixed_source_bound_arts_and_rederives(tmp_path: Path):
    from character_creation.constructed_arts.manual import construct_lineage_manual
    from character_creation.constructed_arts.records import (
        build_lineage_manual_records,
        validate_constructed_art_record,
    )

    bundle = construct_lineage_manual(_manual_request(talent_count=1, factory_root=tmp_path))
    assert len(bundle["recorded_arts"]) == 3
    assert all(art["repeated_component"] is True for art in bundle["recorded_arts"])
    records = build_lineage_manual_records(bundle)
    assert len(records) == 4
    for record in records:
        report = SchemaRegistry(ROOT).report(record, "TianxiaFoundry.RulesCatalogRecord.v1")
        assert report["valid"], report["diagnostics"]
        assert validate_constructed_art_record(record, root_dir=ROOT, factory_root=tmp_path)["record_id"] == record["record_id"]


def test_lineage_manual_difficulty_follows_source_access_category():
    from character_creation.constructed_arts.manual import construct_lineage_manual

    for category, expected in (("open", 1), ("restricted", 2), ("rare", 2), ("forbidden", 3), ("secret", 3)):
        bundle = construct_lineage_manual(_manual_request(category))
        assert {art["learning_dc"]["difficulty"] for art in bundle["recorded_arts"]} == {expected}


def test_lineage_manual_rederivation_rejects_nested_quote_or_identity_drift(tmp_path: Path):
    from character_creation.constructed_arts.manual import construct_lineage_manual
    from character_creation.constructed_arts.records import build_lineage_manual_records, validate_constructed_art_record

    records = build_lineage_manual_records(
        construct_lineage_manual(_manual_request(factory_root=tmp_path))
    )
    for mutate in ("quote", "identity"):
        tampered = deepcopy(records[1])
        contract = tampered["compatibility"]["factory"]["constructed_art"]
        if mutate == "quote":
            contract["bundle"]["recorded_arts"][0]["execution_derivation"]["source_block"] += "\nTampered"
        else:
            contract["bundle"]["recorded_arts"][0]["record_id"] = "tianxia.constructed.recorded_art.arbitrary.99"
        with pytest.raises(FoundryError) as excinfo:
            validate_constructed_art_record(tampered, root_dir=ROOT, factory_root=tmp_path)
        assert excinfo.value.code == "CONSTRUCTED_ART_RECORD_INVALID"


def test_lineage_manual_requires_explicit_factory_source_context_and_rejects_arbitrary_quote(tmp_path: Path):
    from character_creation.constructed_arts.manual import construct_lineage_manual
    from character_creation.constructed_arts.records import build_lineage_manual_records, validate_constructed_art_record

    valid_record = build_lineage_manual_records(
        construct_lineage_manual(_manual_request(factory_root=tmp_path))
    )[1]
    with pytest.raises(FoundryError) as missing_context:
        validate_constructed_art_record(valid_record, root_dir=ROOT)
    assert missing_context.value.code == "CONSTRUCTED_ART_RECORD_INVALID"

    arbitrary_record = build_lineage_manual_records(
        construct_lineage_manual(_manual_request())
    )[1]
    with pytest.raises(FoundryError) as arbitrary_quote:
        validate_constructed_art_record(arbitrary_record, root_dir=ROOT, factory_root=tmp_path)
    assert arbitrary_quote.value.code == "CONSTRUCTED_ART_RECORD_INVALID"


def test_lineage_manual_rejects_installed_source_hash_or_bytes_drift(tmp_path: Path):
    from character_creation.constructed_arts.manual import construct_lineage_manual
    from character_creation.constructed_arts.records import build_lineage_manual_records, validate_constructed_art_record

    record = build_lineage_manual_records(
        construct_lineage_manual(_manual_request(factory_root=tmp_path))
    )[1]
    (tmp_path / "Compendium.md").write_text("#### Crimson Mark\nAn altered published block.\n", encoding="utf-8")
    with pytest.raises(FoundryError) as excinfo:
        validate_constructed_art_record(record, root_dir=ROOT, factory_root=tmp_path)
    assert excinfo.value.code == "CONSTRUCTED_ART_RECORD_INVALID"


def test_lineage_manual_rejects_source_bytes_drift_even_when_hash_is_rebound(tmp_path: Path):
    from character_creation.constructed_arts.manual import construct_lineage_manual
    from character_creation.constructed_arts.records import build_lineage_manual_records, validate_constructed_art_record

    request = _manual_request(factory_root=tmp_path)
    (tmp_path / "Compendium.md").write_text(
        "\n".join(
            [
                "# Compendium",
                "",
                "Preface.",
                "",
                "Rules.",
                "",
                "Published Talents",
                "",
                "---",
                "#### Crimson Mark",
                "Action: altered published effect.",
                "Duration: 1 round.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    request["known_talents"][0]["source"]["source_hash"] = hashlib.sha256(
        (tmp_path / "Compendium.md").read_bytes()
    ).hexdigest()
    record = build_lineage_manual_records(construct_lineage_manual(request))[1]
    with pytest.raises(FoundryError) as excinfo:
        validate_constructed_art_record(record, root_dir=ROOT, factory_root=tmp_path)
    assert excinfo.value.code == "CONSTRUCTED_ART_RECORD_INVALID"
