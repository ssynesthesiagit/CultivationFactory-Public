"""MGR-T14 base row BEASTMASTERY_BASE_BEASTMASTERY_TRAINING (owner text 2026-10-15).

The row prints three clauses. This file pins the one combat behavior this packet
delivers -- the first clause, proficiency in Wisdom (Animal Handling) on learn --
at the compile seam and at the real engine/service seam, and pins the two
unchanged surroundings: characters without the row, and sheets that already
carry a rank (no stacking, no downgrade). The other two clauses are build
grants: the acquisition pipeline has a new-sphere bonus-talent entitlement
(stage2/service.py new_sphere_bonus_talent_acquisition), whose printed "already
proficient" condition this packet does not verify, and no producer records
a single Rider/Tamer Package choice yet; neither is implemented here, so the
row must never be marked handled (diagnostics.skipped.build keeps naming it).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from combat import table_advance
from combat.canonical import canonical_bytes
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate4_models import DecisionContext
from combat.gate5_service import CombatService
from combat.typed_executor import Context, resolve_opposed_check
from combat.ability_checks import skill_bonus
from tests.test_auto_docket import ME, _my_turn, _sheet

ROOT = Path(__file__).resolve().parents[1]
LEFT, RIGHT = "actor:factory.left", "actor:factory.right"
AN = "an_eui_early_book1_cl5"
TRAINING = "BEASTMASTERY_BASE_BEASTMASTERY_TRAINING"
RIDER = "BEASTMASTERY_BASE_RIDER_PACKAGE"
TAMER = "BEASTMASTERY_BASE_TAMER_PACKAGE"
SPHERE = "tianxia.sphere.beastmastery"
TRAINER = "tianxia.talent.beastmastery.trainer"
SKILL = "Animal Handling"
MECHANICS = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]


def sheet(talents=(), skills=()):
    value = copy.deepcopy(_sheet(list(talents), []))
    value["spheres_and_talents"]["sphere_record_ids"] = []
    value["identity"]["cultivation_level"] = 17
    stats = value["ability_scores_and_statistics"]
    stats["primary_resource"]["maximum"] = 50
    stats["skills"] = copy.deepcopy(list(skills))
    return value


def learned(value):
    """The sheet after the real table's Sphere acquisition (combat/table_advance.apply)."""
    return table_advance.apply(value, {"spheres": [{"id": SPHERE}]}, MECHANICS)


def fight(value, seed):
    engine = Gate4ControllerEngine(
        ROOT, match_seed=seed,
        typed_bundles=(compile_character(value, actor_id=ME),),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 14, "y": 6}}},
    )
    _my_turn(engine)
    return engine


def context(engine, actor_id):
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == actor_id and a.parameters.get("typed"))
    actor = engine.state.actors[actor_id]
    return Context(engine, actor, action, None, action.parameters["typed"], [])


def portable(root, project, value):
    import zipfile

    folder = root / "portable_characters" / project
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(value))


def submit(service, match_id, session, decision, candidate):
    return service.submit_intent(match_id, {
        "intent_id": "beastmastery-training-commit", "decision_id": decision.decision_id,
        "candidate_id": candidate.candidate_id, "state_version": decision.state_version,
        "actor_id": decision.active_actor_id, "target_ids": list(candidate.target_ids),
        "destination": candidate.destination.model_dump(mode="json") if candidate.destination else None,
    }, [], None, session=session)


def service_match(root, left_sheet):
    portable(root, "left", left_sheet)
    portable(root, "right", sheet())
    service = CombatService(ROOT, root)
    match_id = service.create_factory_match(
        project_ids=["left"], opponent_actor_ids=[RIGHT], match_seed="BEASTMASTERY-TRAINING-COMMIT",
        control_modes={LEFT: "MANUAL", RIGHT: "MANUAL"},
    )["match_id"]
    session = service._load_session(match_id)
    for _ in range(2):
        decision = DecisionContext.model_validate(service.decision(match_id, session=session)["context"])
        if decision.active_actor_id == LEFT:
            return service, match_id, session, decision
        end = next(c for c in decision.legal_candidates if c.kind == "END_TURN")
        submit(service, match_id, session, decision, end)
    raise AssertionError("The two-actor fixture must reach the owner's turn")


def test_real_acquisition_puts_the_training_on_the_sheet_and_compiles_the_printed_proficiency():
    plain = sheet([], [{"skill": SKILL, "bonus": 3, "proficiency_multiplier": 0},
                       {"skill": "History", "bonus": 17, "proficiency_multiplier": 1}])
    value = learned(plain)
    automatic = value["spheres_and_talents"]["automatic_sphere_component_record_ids"]
    assert TRAINING in automatic and RIDER in automatic and TAMER in automatic
    original = copy.deepcopy(value)
    bundle = compile_character(value, actor_id=ME)
    assert value == original  # the compiler never edits its input
    assert bundle["skills"][SKILL] == 7  # explicit rank-0 total 3 + this character's Proficiency Bonus
    assert bundle["skill_proficiency"][SKILL] == 1
    assert bundle["skills"]["History"] == 17
    # The row is not claimed automated: two of its clauses are build grants this packet does not deliver.
    assert "Beastmastery Training" in bundle["diagnostics"]["skipped"]["build"]


def test_a_character_without_the_row_keeps_its_skill_total_and_rank():
    plain = sheet([], [{"skill": SKILL, "bonus": 3, "proficiency_multiplier": 0}])
    bundle = compile_character(plain, actor_id=ME)
    assert bundle["skills"][SKILL] == 3 and bundle["skill_proficiency"][SKILL] == 0
    # No row is invented for a character who never learned the Sphere.
    empty = compile_character(sheet([]), actor_id=ME)
    assert SKILL not in (empty.get("skills") or {})


def test_gain_proficiency_never_stacks_on_proficiency_or_downgrades_expertise():
    already = learned(sheet([], [{"skill": SKILL, "bonus": 5, "proficiency_multiplier": 1}]))
    bundle = compile_character(already, actor_id=ME)
    assert bundle["skills"][SKILL] == 5 and bundle["skill_proficiency"][SKILL] == 1
    # Trainer's printed Expertise (combat/ext/general_flight_skills) is rank 2 and must survive.
    expert = learned(sheet([TRAINER], [{"skill": SKILL, "bonus": 3, "proficiency_multiplier": 0}]))
    ranked = compile_character(expert, actor_id=ME)
    assert ranked["skills"][SKILL] == 11 and ranked["skill_proficiency"][SKILL] == 2


def test_a_total_without_an_explicit_rank_stays_unchanged_with_a_diagnostic():
    legacy = learned(sheet([], [{"skill": SKILL, "bonus": 6, "proficient": True}]))
    bundle = compile_character(legacy, actor_id=ME)
    assert bundle["skills"][SKILL] == 6 and SKILL not in bundle.get("skill_proficiency", {})
    assert any(SKILL in note and "explicit proficiency rank" in note and "unchanged" in note
               for note in bundle["diagnostics"]["notes"])


def test_a_sheet_with_no_animal_handling_row_gains_ability_modifier_plus_proficiency_bonus():
    value = learned(sheet([]))
    bundle = compile_character(value, actor_id=ME)
    # The printed grant is the ability modifier plus the Proficiency Bonus, nothing inferred.
    assert bundle["skills"][SKILL] == 2 + 4 and bundle["skill_proficiency"][SKILL] == 1


def test_the_grant_is_used_by_a_real_opposed_check_and_survives_a_cold_service_reload(tmp_path):
    value = learned(sheet([], [{"skill": SKILL, "bonus": 3, "proficiency_multiplier": 0}]))
    engine = fight(value, "BEASTMASTERY-TRAINING")
    ctx = context(engine, ME)
    opposed = resolve_opposed_check(ctx, engine.state.actors[AN],
                                    {"kind": "check", "skill": SKILL, "ability": "WIS"},
                                    {"kind": "check", "ability": "WIS"})
    assert opposed.actor.modifier == 7
    # The opponent never learned the Sphere: their roll is untouched.
    assert skill_bonus(engine, engine.state.actors[AN], SKILL, 2) == 2
    service, match_id, session, decision = service_match(tmp_path, value)
    assert skill_bonus(session.engine, session.engine.state.actors[LEFT], SKILL, 2) == 7
    end = next(c for c in decision.legal_candidates if c.kind == "END_TURN")
    result = submit(service, match_id, session, decision, end)
    assert result["match"]["state"]["state_version"] > decision.state_version
    state = session.engine.state.model_dump(mode="json")
    canonical_bytes(state)
    restored = CombatService(ROOT, tmp_path)._load_session(match_id).engine
    assert restored.state.model_dump(mode="json") == state
    assert skill_bonus(restored, restored.state.actors[LEFT], SKILL, 2) == 7
    assert skill_bonus(restored, restored.state.actors[RIGHT], SKILL, 2) == 2


@pytest.mark.parametrize("animal_rows", [[], [{"skill": SKILL, "bonus": 3, "proficiency_multiplier": 0}]])
def test_training_preserves_unrelated_numeric_string_totals_at_service_creation(tmp_path, animal_rows):
    value = learned(sheet([], [*animal_rows, {"skill": "History", "bonus": "3"}]))
    original = copy.deepcopy(value)
    # String totals are not compiled skill rows, even without Training. The
    # grant must neither propose this unrelated row to the strict hook (which
    # would reject it), nor change the compiler's existing interpretation.
    control = compile_character(sheet([], [{"skill": "History", "bonus": "3"}]), actor_id=RIGHT)
    service, match_id, session, decision = service_match(tmp_path, value)
    assert value == original
    assert "History" not in control.get("skills", {})
    owner_bundle = next(row for row in session.engine.typed_bundle_documents if row["actor_id"] == LEFT)
    assert "History" not in owner_bundle.get("skills", {})
    assert skill_bonus(session.engine, session.engine.state.actors[LEFT], "History", 0) == 0
    assert skill_bonus(session.engine, session.engine.state.actors[LEFT], SKILL, 2) == (7 if animal_rows else 6)


def test_unknown_rank_numeric_string_total_is_diagnostic_only_at_service_creation(tmp_path):
    value = learned(sheet([], [{"skill": SKILL, "bonus": "6"}]))
    original = copy.deepcopy(value)
    control = compile_character(sheet([], [{"skill": SKILL, "bonus": "6"}]), actor_id=RIGHT)
    bundle = compile_character(value, actor_id=LEFT)
    # Unknown rank grants only a diagnostic. Training must not normalize a
    # legacy string into a supported integer row or infer proficiency from it.
    assert SKILL not in control.get("skills", {})
    assert SKILL not in bundle.get("skills", {})
    assert SKILL not in bundle.get("skill_proficiency", {})
    assert any("explicit proficiency rank" in note for note in bundle["diagnostics"]["notes"])
    service, match_id, session, decision = service_match(tmp_path, value)
    assert value == original
    assert skill_bonus(session.engine, session.engine.state.actors[LEFT], SKILL, 2) == 2


@pytest.mark.parametrize("spelling", ["animal handling", "aNiMaL HaNdLiNg"])
def test_noncanonical_rank_zero_row_is_used_by_opposed_check_after_service_reload(tmp_path, spelling):
    value = learned(sheet([], [{"skill": spelling, "bonus": 3, "proficiency_multiplier": 0}]))
    service, match_id, session, decision = service_match(tmp_path, value)
    end = next(c for c in decision.legal_candidates if c.kind == "END_TURN")
    submit(service, match_id, session, decision, end)
    restored = CombatService(ROOT, tmp_path)._load_session(match_id).engine
    opposed = resolve_opposed_check(context(restored, LEFT), restored.state.actors[RIGHT],
                                    {"kind": "check", "skill": SKILL, "ability": "WIS"},
                                    {"kind": "check", "ability": "WIS"})
    assert opposed.actor.modifier == 7
    assert skill_bonus(restored, restored.state.actors[RIGHT], SKILL, 2) == 2
