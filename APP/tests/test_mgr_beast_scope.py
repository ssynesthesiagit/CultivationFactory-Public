"""Public prerequisite tests, not evidence of delivered Beast combat behavior.

No fabricated Echo, passive/source ledger or free activation is installed.
Native compilation supplies the action/ownership rows tested by the extraction.
There is deliberately no assertion that a hit can generate or spend Pack Echo:
that delivery awaits selected-expression ownership and the native consumers.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat.ext.beast_echo_marrow import qualify_compiled_source, refined_pair_in_range
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate2_runtime_models import ActionDefinition

ACTOR = "actor:factory.beast_scope"
PALM = "TAL_BRUTE_MOUNTAIN_MOVING_PALM"
IRON = "tianxia.path.body_refining.feature.iron_fist"
SOURCES = (PALM, "TAL_BERSERKER_WORLD_BREAKING_RAMPAGE",
           "TAL_BEASTMASTERY_BEAST_TAMER", "tianxia.talent.blood.blood_mending")


@pytest.fixture(scope="module")
def mechanics():
    return json.loads(Path(TYPED_AUTHORITY).read_text())["mechanics"]


def sheet(ids, mechanics):
    """Synthetic owner sheet using only shipped authority and public schema."""
    spheres = sorted({mechanics[mid]["sphere_id"] for mid in ids if mechanics[mid].get("sphere_id")})
    return {
        "identity": {"name": "Beast scope test", "proficiency_bonus": 6,
                     "cultivation_level": 17, "path": "Body Refining", "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 18, "modifier": 4}
                          for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Stamina", "maximum": 40},
            "armor_class": {"base_value": 14}, "hit_points": {"maximum": 90},
            "speed": {"walking_ft": 30}, "technique_save_dc": 18,
            "technique_attack_bonus": 10,
        },
        "spheres_and_talents": {"sphere_record_ids": spheres,
            "learned_talent_record_ids": [mid for mid in ids if mechanics[mid].get("sphere_id")]},
        "path_and_subpath": {"path_feature_record_ids": [mid for mid in ids
                                                         if mechanics[mid].get("path_id")]},
    }


@pytest.fixture(scope="module")
def compiled(mechanics):
    ids = (*SOURCES, IRON)
    return compile_character(sheet(ids, mechanics), actor_id=ACTOR), ids


def action_for(bundle, source):
    return next(ActionDefinition.model_validate(row) for row in bundle["action_catalog"]
                if (row.get("parameters", {}).get("typed") or {}).get("source") == source)


def qualify(action, compiled, mechanics, **changes):
    bundle, ids = compiled
    args = {"actor_id": ACTOR, "owned_ids": ids, "mechanics": mechanics,
            "passive_rows": bundle["typed_passives"]}
    args.update(changes)
    return qualify_compiled_source(action, **args)


@pytest.mark.parametrize("source", SOURCES)
def test_real_compiled_tal_and_dotted_sources_keep_canonical_provenance(compiled, mechanics, source):
    bundle, _ = compiled
    action = action_for(bundle, source)
    facts = qualify(action, compiled, mechanics)
    assert facts == {"mechanic_id": source,
        "text_sha256": mechanics[source]["source"]["text_sha256"],
        "sphere_id": mechanics[source]["sphere_id"], "membership": "technique_family"}
    assert action.economy.value in {"ACTION", "BONUS_ACTION"}
    if source == PALM:
        assert action.costs  # the extraction does not waive Martial Focus


def test_owned_native_natural_weapon_uses_compiled_row_not_embedded_name(compiled, mechanics):
    bundle, _ = compiled
    action = action_for(bundle, IRON)
    assert qualify(action, compiled, mechanics)["membership"] == "natural_weapon"
    assert qualify(action, compiled, mechanics, passive_rows=()) is None
    assert qualify(action, compiled, mechanics, owned_ids=()) is None


@pytest.mark.parametrize("label", ["Mountain-Moving Palm", "Natural Weapon", "TAL_BRUTE_Fake"])
def test_wrong_sphere_same_name_and_embedded_words_do_not_qualify(compiled, mechanics, label):
    # A negative source packet is not injected into a service or source ledger.
    action = action_for(compiled[0], PALM)
    alien = "tianxia.talent.fire.natural_weapon_lookalike"
    row = deepcopy(mechanics[PALM])
    row.update(mechanic_id=alien, name=label, sphere_id="tianxia.sphere.fire")
    parameters = deepcopy(action.parameters)
    parameters["typed"]["source"] = alien
    altered = action.model_copy(update={"display_name": label,
        "source_definition_id": "action:typed.foreign.natural.TAL_BRUTE_lookalike",
        "parameters": parameters})
    assert qualify(altered, compiled, {**mechanics, alien: row}, owned_ids=(alien,)) is None


def test_wrong_owner_unknown_and_unowned_sources_are_rejected(compiled, mechanics):
    action = action_for(compiled[0], PALM)
    assert qualify(action, compiled, mechanics, actor_id="actor:someone_else") is None
    assert qualify(action, compiled, mechanics, owned_ids=()) is None
    assert qualify(action, compiled, {}) is None
    row = deepcopy(mechanics[PALM])
    row["mechanic_id"] = "other"
    assert qualify(action, compiled, {PALM: row}) is None
    row["mechanic_id"] = PALM
    row["source"] = {}
    assert qualify(action, compiled, {PALM: row}) is None


def test_query_does_not_mutate_native_bundle_or_publish_beast_rows(compiled, mechanics):
    bundle, _ = compiled
    before = deepcopy(bundle)
    qualify(action_for(bundle, PALM), compiled, mechanics)
    assert bundle == before
    assert not any(str(row.get("feature_id", "")).startswith("foundation.beast_echo_marrow_v0_2A.")
                   for row in bundle["typed_passives"])


@pytest.mark.parametrize("feet,expected", [(25, True), (30, True), (35, False)])
def test_refined_range_prerequisite_includes_exact_thirty(feet, expected):
    # Geometry-only extraction control: no hit/damage/spend claim is made here.
    owner = SimpleNamespace(entity_id="owner", team_id="ours", active=True)
    hitter = SimpleNamespace(entity_id="ally", team_id="ours", active=True)
    engine = SimpleNamespace(state=SimpleNamespace(relations=None),
                             _distance_actor_to_actor=lambda a, b: feet)
    assert refined_pair_in_range(engine, owner, hitter) is expected


@pytest.mark.parametrize("case", ["self", "enemy", "neutral", "inactive", "relation_override"])
def test_refined_range_is_not_ownership_or_base_pair_eligibility(case):
    owner = SimpleNamespace(entity_id="owner", team_id="ours", active=True)
    hitter = SimpleNamespace(entity_id="ally", team_id="ours", active=True)
    engine = SimpleNamespace(state=SimpleNamespace(relations=None),
                             _distance_actor_to_actor=lambda a, b: 5)
    if case == "self":
        hitter = owner
    elif case == "enemy":
        hitter.team_id = "theirs"
    elif case == "neutral":
        hitter.team_id = "team:neutral"
    elif case == "inactive":
        hitter.active = False
    else:
        engine.state.relations = SimpleNamespace(actors={"ally": {"owner": "ENEMY"}}, teams={})
    assert not refined_pair_in_range(engine, owner, hitter)
