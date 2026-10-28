"""Native builder acquisition -> authenticated feature projection -> saved table.

Only ability scores/equipment use a compact fixture sheet. Feature identity and
Starting Element come from the production builder and source-backed projector;
the tests never inject an ownership marker, known list, or success receipt.
"""
from copy import deepcopy
from pathlib import Path

import pytest

from app.core import FoundryError
from character_builder import CharacterBuilderService
from character_creation.choice_snapshot import materialize_choice_snapshot
from character_creation.service import CharacterCreationExecutionService
from project_store.service import ProjectStore
from projector.v3_bridge import _build_earned_feature_occurrences
from stage1.service import Stage1ClipboardService
from combat import ext
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import mgr_t14_cycle_rebirth as R
from tests.h1_support import sheet
from tests.test_earned_path_feature_occurrences import (
    BODY_PATH, QI_PATH, CULTIVATION_INSIGHT_ID, _event, _history, _stage2,
)

ROOT = Path(__file__).resolve().parents[1]
ME, FOE = "actor:factory.left", "actor:factory.right"
TECHNIQUES = ["FIRE_BASE_IGNITE", "FIRE_TAL_BURNING_WEAPON", "EARTH_BASE_WEIGHT_SEEKING_CLOD",
              "TAL_METAL_CONDUCTOR_S_PALM", "WATER_BASE_WATER_LASH"]


def acquire(environment, starting="fire", cl=6):
    db = environment["db"]
    created = CharacterBuilderService(db).create_project(
        working_name="Cycle cultivator", concept="Five Elements acquisition regression", target_cl=cl,
        power_band="standard", source_reference=None, creation_mode="detailed", ability_scores={},
        selections={"path_choice": [BODY_PATH, QI_PATH], "subpath_choice": [R.PARENT],
                    "insight_priorities": [CULTIVATION_INSIGHT_ID]},
        generation_route="ai_bootstrap", acquisition_choices={"five_elements_start": starting})
    project = ProjectStore(db).get_project(created["project_id"])["project"]
    creator = CharacterCreationExecutionService(db, stage1=Stage1ClipboardService(db), provider=None,
                                               project_store=ProjectStore(db))
    records = creator._locked_records_for_project(created["project_id"])
    case = {"project": project, "records": records, "subpath_id": R.PARENT, "factory_root": environment["root"]}
    history = _history(case, body_level=0, qi_level=cl, include_subpath=False)
    # Actual selected, locked parent acquired at the character's current Path
    # attainment (late selection is legal). Future features remain unearned.
    parent = _event("cycle.acquire", "subpath_acquisition", records[R.PARENT],
                    len(history["events"]) + 1, cl, outputs={"granted_feature_record_ids": [
                        r["canonical_id"] for r in _stage2(records[R.PARENT])["feature_progression"]]})
    history["event_records"][parent["event_id"]] = records[R.PARENT]
    history["packet_by_event"][parent["event_id"]] = "packet.cycle.acquire"
    occurrences = _build_earned_feature_occurrences(
        path_events=history["path_events"], level_events=history["level_events"],
        score_change_events=history["score_changes"], insight_events=history["insight_events"],
        subpath_events=[parent], event_records=history["event_records"], locked_records=records,
        packet_by_event=history["packet_by_event"], selected_path_ids=[BODY_PATH, QI_PATH],
        factory_root=environment["root"])
    doc = sheet(TECHNIQUES, cl=cl, name="Cycle cultivator")
    doc["identity"]["proficiency_bonus"] = 3
    doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
    doc["ability_scores_and_statistics"]["initiative"] = {"bonus": 100}
    doc["path_and_subpath"] = {"earned_feature_occurrences": [r for r in occurrences if r["feature_id"] in (R.FIVE, R.CYCLE)],
                               "paths": [{"path_id": QI_PATH, "effective_cl": cl}]}
    doc["advancement_history"] = {"typed_choice_snapshot": materialize_choice_snapshot(project)}
    return doc


@pytest.fixture(scope="module")
def acquired(catalog_environment):
    class Cases(dict):
        def __missing__(self, element):
            self[element] = acquire(catalog_environment, element)
            return self[element]
    return Cases()


def build(tmp_path, doc):
    bundles = [compile_character(deepcopy(doc), actor_id=ME),
               compile_character(sheet([], cl=6, name="Opponent"), actor_id=FOE)]
    combat = CombatService(ROOT, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    mid = combat._finish_factory_match(bundles, [ME, FOE], {ME: "team:a", FOE: "team:b"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 5, "y": 6}}, arena, [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed="CYCLE-NATIVE", maximum_rounds=10,
        display_name="Cycle of Rebirth regression")["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def commit(table, mid, candidate_id, *, active=None, alignment=None):
    view = table.state(mid)
    menu, answers, prompts = view["menu"], [], []
    for _ in range(12):
        result = table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], view["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        options = prompt.get("choice", {}).get("options", [])
        selected = alignment if "alignment" in prompt["context"]["reaction_source_id"] else active
        if options:
            option = next((o for o in options if o["id"] == selected), options[0])
            answers.append({**prompt["context"], "selection": "USE", "option_ids": [option["id"]]})
        else:
            answers.append({**prompt["context"], "selection": "DECLINE", "option_ids": []})
    raise AssertionError("choice did not settle")


def ready(combat, table, mid, active):
    for _ in range(8):
        engine = combat._load_session(mid).engine
        candidates = engine.legal_candidates()
        setup = next((c for c in candidates if c.source_definition_id == "system:combat.fight_setup"), None)
        if setup:
            commit(table, mid, setup.candidate_id, active=active)
            continue
        if table.state(mid)["menu"]["actor_id"] == ME:
            return
        commit(table, mid, table.state(mid)["menu"]["end_turn"], active=active)
    raise AssertionError("owner turn unavailable")


def use(combat, table, mid, source, **choices):
    engine = combat._load_session(mid).engine
    action_ids = {a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == ME and (a.parameters.get("typed") or {}).get("source") == source}
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id in action_ids
                     and (not c.target_ids or c.target_ids == (FOE,) or c.target_ids == (ME,)))
    return commit(table, mid, candidate.candidate_id, **choices)


def cold(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded.engine


@pytest.mark.parametrize("starting,active,technique,following", [
    ("wood", "earth", "EARTH_BASE_WEIGHT_SEEKING_CLOD", "wood"),
    ("fire", "metal", "TAL_METAL_CONDUCTOR_S_PALM", "fire"),
    ("earth", "water", "WATER_BASE_WATER_LASH", "earth"),
    ("metal", "metal", "TAL_METAL_CONDUCTOR_S_PALM", "water"),
    ("water", "fire", "FIRE_BASE_IGNITE", "water"),
])
def test_native_all_starts_shift_skip_wrap_commit_cold_replay(tmp_path, acquired, starting, active, technique, following):
    combat, table, mid = build(tmp_path, acquired[starting])
    ready(combat, table, mid, active)
    engine = combat._load_session(mid).engine
    before = R.state(engine.state.actors[ME])
    assert before.data["active"] == active
    known = [R.ELEMENTS[(R.ELEMENTS.index(starting) + i) % 5] for i in range(3)]
    assert before.data["known"].split(",") == known
    original = {k: a.model_dump(mode="json") for k, a in engine.action_catalog.items()}
    use(combat, table, mid, technique)
    engine = cold(tmp_path, mid)
    assert R.state(engine.state.actors[ME]).data["active"] == following
    assert {k: a.model_dump(mode="json") for k, a in engine.action_catalog.items()} == original
    shifted = next(e for e in engine.events if e.source_definition_id == R.CYCLE and e.event_type == "PASSIVE_TRIGGERED")
    packets = [e for e in engine.events if e.event_type in {"DAMAGE_COMMITTED", "CONDITION_APPLIED"}
               and e.source_definition_id != R.CYCLE]
    assert packets and all(e.sequence < shifted.sequence for e in packets)


def test_once_per_real_turn_and_wrong_alignment(tmp_path, acquired):
    combat, table, mid = build(tmp_path, acquired["fire"])
    ready(combat, table, mid, "fire")
    use(combat, table, mid, "TAL_METAL_CONDUCTOR_S_PALM")
    assert R.state(combat._load_session(mid).engine.state.actors[ME]).data["active"] == "fire"
    use(combat, table, mid, "FIRE_BASE_IGNITE")
    engine = cold(tmp_path, mid)
    assert R.state(engine.state.actors[ME]).data["active"] == "earth"
    assert len([e for e in engine.events if e.source_definition_id == R.CYCLE and e.event_type == "PASSIVE_TRIGGERED"]) == 1


def test_second_matching_activation_waits_for_next_creature_turn(tmp_path, acquired):
    combat, table, mid = build(tmp_path, acquired["fire"])
    ready(combat, table, mid, "fire")
    use(combat, table, mid, "FIRE_TAL_BURNING_WEAPON")
    use(combat, table, mid, "EARTH_BASE_WEIGHT_SEEKING_CLOD")
    engine = cold(tmp_path, mid)
    assert R.state(engine.state.actors[ME]).data["active"] == "earth"
    commit(table, mid, table.state(mid)["menu"]["end_turn"], active="earth")
    ready(combat, table, mid, "earth")
    use(combat, table, mid, "EARTH_BASE_WEIGHT_SEEKING_CLOD")
    engine = cold(tmp_path, mid)
    assert R.state(engine.state.actors[ME]).data["active"] == "metal"


@pytest.mark.parametrize("mode", ["unowned", "no_parent", "below_cl6", "missing_choice", "tampered_choice"])
def test_wrong_owner_and_acquisition_boundaries(tmp_path, acquired, mode):
    doc = deepcopy(acquired["fire"])
    rows = doc["path_and_subpath"]["earned_feature_occurrences"]
    if mode == "unowned": rows[:] = [r for r in rows if r["feature_id"] != R.CYCLE]
    if mode == "no_parent": rows[:] = [r for r in rows if r["feature_id"] != R.FIVE]
    if mode == "below_cl6": doc["path_and_subpath"]["paths"][0]["effective_cl"] = 5
    if mode == "missing_choice": doc.pop("advancement_history")
    if mode == "tampered_choice":
        doc["advancement_history"]["typed_choice_snapshot"]["snapshot_sha256"] = "0" * 64
    combat, table, mid = build(tmp_path, doc)
    ready(combat, table, mid, "fire")
    use(combat, table, mid, "FIRE_BASE_IGNITE")
    engine = cold(tmp_path, mid)
    assert not any(e.source_definition_id == R.CYCLE and e.event_type == "PASSIVE_TRIGGERED" for e in engine.events)


@pytest.mark.parametrize("phase", ["cancel", "counter", "veto", "refund", "exception"])
def test_unsuccessful_or_refunded_activation_never_shifts(tmp_path, acquired, monkeypatch, phase):
    combat, table, mid = build(tmp_path, acquired["fire"])
    ready(combat, table, mid, "fire")
    ext.effects()
    def on(point, callback):
        monkeypatch.setitem(ext._HOOKS, point, [*ext._HOOKS.get(point, []), callback])
    if phase == "cancel":
        on("technique_declared", lambda *a: {"source_id": "test:cancel", "label": "Canceled", "cancel": True})
    elif phase == "counter":
        import combat.typed_executor as executor
        monkeypatch.setattr(executor, "activation_reactions", lambda ctx: False)
    elif phase == "veto": on("technique_start", lambda *a: True)
    elif phase == "refund":
        def refund(ctx):
            for resource, amount in ctx.action.costs:
                ctx.engine._gain_resource(ctx.actor, resource, amount, "test:refund", cost_source_id=ctx.source)
        on("technique_used", refund)
    else:
        def fail(*a): raise ValueError("regression: resolution failed")
        on("resolution_final", fail)
    if phase == "exception":
        with pytest.raises(Exception): use(combat, table, mid, "FIRE_TAL_BURNING_WEAPON")
    else:
        use(combat, table, mid, "FIRE_TAL_BURNING_WEAPON")
    engine = combat._load_session(mid).engine
    assert R.state(engine.state.actors[ME]).data["active"] == "fire"
    assert not any(e.source_definition_id == R.CYCLE and e.event_type == "PASSIVE_TRIGGERED" for e in engine.events)


def test_builder_requires_owner_choice_and_refuses_unowned_or_unknown():
    from character_creation.acquisition_choices import validate, for_acquisition, FIELD
    for parents, choices, code in [([R.PARENT], {}, "ACQUISITION_CHOICE_REQUIRED"),
            ([], {"five_elements_start": "fire"}, "ACQUISITION_CHOICE_UNOWNED"),
            ([R.PARENT], {"five_elements_start": "ice"}, "ACQUISITION_CHOICE_INVALID")]:
        with pytest.raises(FoundryError) as error: validate(parents, choices)
        assert error.value.code == code
    with pytest.raises(FoundryError) as error:
        for_acquisition({"user_locks": []}, R.PARENT)
    assert error.value.code == "ACQUISITION_CHOICE_REQUIRED"
    assert for_acquisition({"user_locks": [{"field": FIELD, "value": {"five_elements_start": "water"}}]}, R.PARENT) == {"five_elements_start": "water"}


def test_alignment_uses_only_source_sphere_printed_tags_and_explicit_alignment():
    from combat.technique_alignment import eligible
    assert eligible({"sphere": "tianxia.sphere.fire"}) == ("fire",)
    assert eligible({"tags": ["Wood", "Water"]}) == ("wood", "water")
    assert eligible({"elemental_alignments": ["earth", "metal"]}) == ("earth", "metal")
    assert eligible({"name": "Fire Sword", "damage_types": ["fire"]}) == ()


def test_stamina_powered_elemental_technique_does_not_cycle(tmp_path, acquired):
    doc = deepcopy(acquired["fire"])
    doc["ability_scores_and_statistics"]["primary_resource"]["name"] = "Stamina"
    combat, table, mid = build(tmp_path, doc)
    ready(combat, table, mid, "fire")
    use(combat, table, mid, "FIRE_BASE_IGNITE")
    assert R.state(cold(tmp_path, mid).state.actors[ME]).data["active"] == "fire"
