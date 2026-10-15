"""Life learning and typed GM cases through native table and journey transactions."""
import copy
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.canonical import canonical_sha256
from combat.gate2_runtime_content import AN
from combat.gate5_service import CombatService, DEFAULT_FACTORY_ARENA
from combat.medical_cases import knowledge
from combat.tabletop_service import TabletopService
from combat.tabletop import TabletopError
from tests.h1_support import sheet
from tests.test_learning_training_native import ROOT, PID, AID, ARENA, native, acquire
from tests.test_r5i_integration import act, turn, candidate, answer, seed, pin_ai

PATIENT = "0badc0de-0000-4000-8000-000000000015"
TARGET = "actor:factory." + PATIENT
TREAT = "tianxia.talent.life.wound_closing_palm"


def case(**changes):
    return {"id": "wound-one", "category": "wound", "cause": "A concealed splinter beneath the skin",
            "living": 1, "obvious": 0, "dc": 1, "treatment_ids": [TREAT],
            "source_note": "GM examination ruling: Wound-Closing Palm can treat this wound.",
            "economy": "ACTION", "seconds": 60, "range_ft":5, **changes}


def clinic(tmp_path, *, learned=True, trained=True, fact=None, key="INT"):
    combat, table = native(tmp_path, skills=["Medicine"], mods={"INT": 5, "WIS": 1}, key=key)
    doc = sheet([], name="Patient")
    folder = tmp_path / "portable_characters" / PATIENT
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    if learned:
        acquire(table, "life")
        if trained:
            table.add_advancement(PID, "talent", TREAT)
    table.declare_medical_case(PATIENT, fact or case(), gm=True)
    return combat, table


def fight(combat, *, harm=False):
    docs = [combat._factory_owner_sheet(pid) for pid in (PID, PATIENT)]
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True}) for doc, aid in zip(docs, (AID, TARGET))]
    if harm:
        seed(bundles[0], "Clinical fixture injury", [{"type": "damage", "applies_to": "target", "formula": "none", "flat": 60, "damage_types": ["force"]}], target="ANY_CREATURE")
        bundles[0]["action_catalog"][-1]["parameters"]["free_primary"] = True
        bundles[0]["bundle_sha256"] = canonical_sha256({k: v for k, v in bundles[0].items() if k != "bundle_sha256"})
    return combat._finish_factory_match(bundles, [AID, TARGET, AN], {AID: "team:a", TARGET: "team:b" if harm else "team:a", AN: "team:b"},
        {AID: {"x": 3, "y": 6}, TARGET: {"x": 4, "y": 6}, AN: {"x": 4, "y": 7}},
        combat.factory_arenas(include_retired=True)[ARENA], [AID, TARGET], [AN],
        control_modes={a: "MANUAL" for a in (AID, TARGET, AN)}, match_seed="LIFE-NATIVE:" + canonical_sha256(bundles)[:16], display_name="Clinical test", maximum_rounds=15)["match_id"]


def resolve_choices(table, mid, cid, selected="Wisdom"):
    replies = []
    result = act(table, mid, cid)
    for _ in range(5):
        if result["status"] == "COMMITTED":
            return result
        options = [r["id"] for r in result["reaction"]["choice"]["options"]]
        choice = selected if selected in options else options[0]
        replies.append(answer(result, "USE", [choice]))
        result = act(table, mid, cid, replies)
    raise AssertionError(result)


@pytest.mark.parametrize("ability", ["Wisdom", "Life key"])
def test_medicine_choice_hidden_knowledge_and_cold_mechanical_replay(tmp_path, ability):
    combat, table = clinic(tmp_path)
    mid = fight(combat)
    turn(table, mid, AID)
    cid = candidate(combat, mid, "Life Initiation: identify a treatable condition (Action)", TARGET)
    assert resolve_choices(table, mid, cid, ability)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert knowledge(loaded.engine, AID) == [{"case_id": "wound-one", "subject": TARGET, "cause": case()["cause"]}]
    assert knowledge(loaded.engine, TARGET) == []
    with pytest.raises(TabletopError):
        knowledge(loaded.engine, "actor:not-in-this-fight")
    public_lines = [e.payload.get("text", "") for e in loaded.engine.events]
    assert not any(case()["cause"] in text for text in public_lines)
    check = next(e for e in reversed(loaded.engine.events) if e.event_type == "CHECK_ROLLED")
    assert check.payload["ability"] == ("WIS" if ability == "Wisdom" else "INT")
    assert check.payload["actor"]["modifier"] == (5 if ability == "Wisdom" else 9)  # replace only ability; keep PB once
    own = combat.ai_decision_context(loaded).model_dump(mode="json")
    assert own["private_facts"][0]["cause"] == case()["cause"]
    turn(table, mid, TARGET)
    other = combat.ai_decision_context(combat._load_session(mid)).model_dump(mode="json")
    assert case()["cause"] not in json.dumps(other)
    assert "private_facts" not in other
    turn(table, mid, AID)
    own = CombatService(ROOT, tmp_path)
    final = own._load_session(mid)
    context = own.ai_decision_context(final).model_dump(mode="json")
    assert context["private_facts"][0]["cause"] == case()["cause"]
    assert final.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("learned,trained,living", [(False, False, 1), (True, False, 1), (True, True, 0)])
def test_wrong_owner_no_treatment_and_nonliving_guards(tmp_path, learned, trained, living):
    combat, table = clinic(tmp_path, learned=learned, trained=trained, fact=case(living=living))
    mid = fight(combat)
    turn(table, mid, AID)
    names = [c.display_name for c in combat._load_session(mid).engine.legal_candidates()]
    assert not any("identify a treatable" in n for n in names)
    if not learned:
        assert not any(n.startswith("Life Initiation:") for n in names)


def test_gm_input_validation_and_recognition_do_not_reveal_hidden_cause(tmp_path):
    combat, table = clinic(tmp_path, fact=case(category="shock", obvious=1))
    with pytest.raises(TabletopError):
        table.declare_medical_case(PATIENT, case(id="not-gm"))
    with pytest.raises(TabletopError):
        table.declare_medical_case(PATIENT, case(id="float-dc", dc=1.5), gm=True)
    with pytest.raises(TabletopError):
        table.declare_medical_case(PATIENT, case(id="wrong-sphere", treatment_ids=["TAL_SPEAR_COILING_SOFT_SPEAR"]), gm=True)
    with pytest.raises(TabletopError):
        table.declare_medical_case(PATIENT, case(id="blank-ruling", source_note=" "), gm=True)
    with pytest.raises(TabletopError):
        table.declare_medical_case(PATIENT, case(id="oversized-cause", cause="wound" + " " * 1001), gm=True)
    mid = fight(combat)
    turn(table, mid, AID)
    assert act(table, mid, candidate(combat, mid, "Life Initiation: recognize obvious signs", TARGET))["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    lines = [e.payload.get("log", "") for e in loaded.engine.events]
    assert any("shock" in text for text in lines)
    assert not any(case()["cause"] in text for text in lines)
    assert knowledge(loaded.engine, AID) == []
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("seconds,dc", [(0, 0), (60, 1), (172800, 1)])
def test_outside_combat_native_learning_journey_check_and_cold_reload(tmp_path, seconds, dc):
    from combat.gate2_grid import SquareGrid
    from combat.gate2_runtime_models import Position
    distance = 10 if seconds == 172800 else 5
    combat, table = clinic(tmp_path, fact=case(seconds=seconds, dc=dc, range_ft=distance))
    grid = SquareGrid(combat.factory_arenas()[DEFAULT_FACTORY_ARENA])
    cells = [Position(x=x, y=y) for y in range(grid.height) for x in range(grid.width)
             if grid.placement_legal(Position(x=x, y=y), occupied_cells=set())]
    origin, patient = next((a, b) for a in cells for b in cells if grid.distance_ft(a, b) == distance
                           and grid.line_of_sight(a, b) and grid.line_of_physical_transmission(a, b))
    state = combat.create_journey(project_ids=[PID, PATIENT], arena_id=DEFAULT_FACTORY_ARENA,
        positions={AID: origin.model_dump(mode="json"), TARGET: patient.model_dump(mode="json")}, base_paces={AID: 10000, TARGET: 10000})
    jid = state["journey_id"]
    options = combat.journey_menu(jid, AID)["options"]
    selected = next(o for o in options if o["kind"] == "life_medicine" and o["payload"]["ability"] == "Life key")
    combat.journey_act(jid, state["revision"], AID, selected["kind"], selected["payload"])
    cold = CombatService(ROOT, tmp_path).journey_state(jid)
    assert cold["seconds"] == seconds
    assert cold["actors"][AID]["knowledge"][TARGET + ":wound-one"] == case()["cause"]
    assert "knowledge" not in cold["actors"][TARGET]
    assert case()["cause"] not in json.dumps(cold["events"])


def test_declared_examination_range_is_enforced_and_allows_self_at_zero(tmp_path):
    combat, table = clinic(tmp_path, fact=case(range_ft=0))
    mid = fight(combat)
    turn(table, mid, AID)
    assert not any("identify a treatable" in c.display_name for c in combat._load_session(mid).engine.legal_candidates())
    table.declare_medical_case(PID, case(range_ft=0), gm=True)
    mid = fight(combat)
    turn(table, mid, AID)
    cid = candidate(combat, mid, "Life Initiation: identify a treatable condition (Action)", AID)
    resolve_choices(table, mid, cid, "Life key")
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert knowledge(loaded.engine, AID)[0]["subject"] == AID
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_failed_medicine_does_not_grant_knowledge(tmp_path):
    combat, table = clinic(tmp_path, fact=case(dc=100))
    mid = fight(combat)
    turn(table, mid, AID)
    cid = candidate(combat, mid, "Life Initiation: identify a treatable condition (Action)", TARGET)
    resolve_choices(table, mid, cid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert knowledge(loaded.engine, AID) == []
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_stabilization_uses_actual_committed_dying_state_and_survives_replay(tmp_path):
    combat, table = clinic(tmp_path, trained=False, fact=case(category="dying", treatment_ids=[],
        cause="Blood loss after a serious injury", source_note="GM records the living patient's stabilization DC and timing."))
    mid = fight(combat, harm=True)
    turn(table, mid, AID)
    assert act(table, mid, candidate(combat, mid, "Clinical fixture injury", TARGET))["status"] == "COMMITTED"
    assert combat._load_session(mid).engine.state.actors[TARGET].life_state == "DYING"
    cid = candidate(combat, mid, "Life Initiation: Medicine to stabilize (Action)", TARGET)
    assert resolve_choices(table, mid, cid, "Life key")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[TARGET].life_state == "STABLE"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_all_eight_declared_obvious_signs_are_recognized_without_hidden_causes(tmp_path):
    from combat.medical_cases import CATEGORIES
    combat, table = clinic(tmp_path)
    for index, category in enumerate(CATEGORIES[:8]):
        table.declare_medical_case(PATIENT, case(id=f"sign-{index}", category=category, obvious=1,
            source_note=f"GM records the patient's observable {category}; the cause remains hidden."), gm=True)
    state = combat.create_journey(project_ids=[PID, PATIENT], arena_id=DEFAULT_FACTORY_ARENA,
        positions={AID: {"x": 3, "y": 6}, TARGET: {"x": 4, "y": 6}}, base_paces={AID: 10000, TARGET: 10000})
    state = combat.journey_act(state["journey_id"], state["revision"], AID, "life_recognize", {"target": TARGET})
    cold = CombatService(ROOT, tmp_path).journey_state(state["journey_id"])
    assert cold["events"][-1]["signs"] == sorted(CATEGORIES[:8])
    assert case()["cause"] not in json.dumps(cold["events"])


def test_ai_examiner_decides_automatically_without_live_model_requests(tmp_path):
    combat, table = clinic(tmp_path)
    mid = fight(combat)
    turn(table, mid, AID)
    cid = candidate(combat, mid, "Life Initiation: identify a treatable condition (Action)", TARGET)
    pin_ai(combat, mid, AID, cid)
    assert table.auto_step(mid, 0, [])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert knowledge(loaded.engine, AID)
    check = next(e for e in reversed(loaded.engine.events) if e.event_type == "CHECK_ROLLED")
    assert check.payload["ability"] == "INT"
    assert check.payload["actor"]["modifier"] == 9
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_unknown_life_key_does_not_default_to_intelligence(tmp_path):
    combat, table = clinic(tmp_path, key=None)
    mid = fight(combat)
    turn(table, mid, AID)
    cid = candidate(combat, mid, "Life Initiation: identify a treatable condition (Action)", TARGET)
    resolve_choices(table, mid, cid, "Life key")  # unavailable: helper must choose the real Wisdom option
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    check = next(e for e in reversed(loaded.engine.events) if e.event_type == "CHECK_ROLLED")
    assert check.payload["ability"] == "WIS"
    assert check.payload["actor"]["modifier"] == 5
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_case_retraction_affects_future_scenes_and_preserves_sealed_replay(tmp_path):
    combat, table = clinic(tmp_path)
    mid = fight(combat)
    with pytest.raises(TabletopError):
        table.retract_medical_case(PATIENT, {"id": "wound-one", "source_note": "The splinter was removed."})
    table.retract_medical_case(PATIENT, {"id": "wound-one", "source_note": "GM records that the wound has been treated."}, gm=True)
    cold = CombatService(ROOT, tmp_path)
    assert not cold._factory_owner_sheet(PATIENT).get("clinical_cases")
    facts = table.buttons.get(PATIENT)["advancement"]["facts"]
    assert [f["type"] for f in facts] == ["clinical_case", "clinical_case_retraction"]
    turn(table, mid, AID)
    cid = candidate(combat, mid, "Life Initiation: identify a treatable condition (Action)", TARGET)
    resolve_choices(table, mid, cid)
    loaded = cold._load_session(mid)
    assert knowledge(loaded.engine, AID)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_in_play_npc_case_gm_authority_retraction_and_cold_replay(tmp_path):
    combat, table = clinic(tmp_path)
    mid = fight(combat)
    turn(table, mid, AID)
    engine = combat._load_session(mid).engine
    version = engine.state.state_version
    fact = case(id="npc-wound", range_ft=10, cause="NPC wound caused by a hidden thorn")
    with pytest.raises(TabletopError, match="Only the GM"):
        table.declare_match_medical_case(mid, AN, fact, expected_state_version=version)
    with pytest.raises(TabletopError):
        table.declare_match_medical_case(mid, AN, fact, gm=True, expected_state_version=version - 1)
    table.declare_match_medical_case(mid, AN, fact, gm=True, expected_state_version=version)
    cold = CombatService(ROOT, tmp_path)
    loaded = cold._load_session(mid)
    from combat.ext.life_initiation import cases
    assert cases(loaded.engine, loaded.engine.state.actors[AN]) == [
        {**fact, "type": "clinical_case", "authority": "GM", "treatment_sources": cases(loaded.engine, loaded.engine.state.actors[AN])[0]["treatment_sources"]}]
    assert loaded.engine.state.actors[AID].action_available == engine.state.actors[AID].action_available
    assert knowledge(loaded.engine, AID) == []
    assert fact["cause"] not in json.dumps(cold.ai_decision_context(loaded).model_dump(mode="json"))
    assert fact["cause"] not in json.dumps(table.events(mid, 0))
    from combat.ext.journey_setup import encounter_snapshot
    from combat.scene_facts import records
    assert records(encounter_snapshot(loaded.engine.state.actors[AN])["conditions"], "clinical")[0]["cause"] == fact["cause"]
    with pytest.raises(TabletopError):
        table.declare_match_medical_case(mid, AN, fact, gm=True, expected_state_version=loaded.engine.state.state_version)
    cid = candidate(combat, mid, "Life Initiation: identify a treatable condition (Action)", AN)
    resolve_choices(table, mid, cid)
    loaded = cold._load_session(mid)
    assert any(r["cause"] == fact["cause"] for r in knowledge(loaded.engine, AID))
    table.declare_match_medical_case(mid, AN, {"id": fact["id"], "source_note": "The GM records that the thorn has been removed."},
        gm=True, expected_state_version=loaded.engine.state.state_version, retract=True)
    loaded = cold._load_session(mid)
    assert cases(loaded.engine, loaded.engine.state.actors[AN]) == []
    assert any(r["cause"] == fact["cause"] for r in knowledge(loaded.engine, AID))  # historical knowledge stays true to its time
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_unregistered_scene_fact_is_inert(tmp_path):
    combat, table = clinic(tmp_path, learned=False)
    mid = fight(combat)
    turn(table, mid, AID)
    session = combat._load_session(mid)
    version = session.engine.state.state_version
    with pytest.raises(ValueError, match="no matching source validator"):
        combat.declare_scene_fact(mid, declaration={"subject": AN, "kind": "unregistered", "record": {"id": "bogus"}},
                                 expected_state_version=version)
    assert combat._load_session(mid).engine.state.state_version == version
    assert not any(c.condition_id.startswith("condition:table.fact.") for c in combat._load_session(mid).engine.state.actors[AN].conditions.values())


def test_public_table_fact_observation_contract_remains_native_and_audience_scoped(tmp_path):
    combat, table = clinic(tmp_path, learned=False)
    mid = fight(combat)
    turn(table, mid, AID)
    engine = combat._load_session(mid).engine
    observation = {"record_id": "ordinary-observation", "subject_id": AN, "subject_name": "Observed opponent",
        "subject_kind": "creature", "position": engine.state.actors[AN].position.model_dump(mode="json"),
        "source_reference": "GM records the examiner's witnessed footprint in this scene.", "witness_ids": [AID],
        "valid_through_round": engine.state.round_number, "answers": {}}
    with pytest.raises(TabletopError):
        table.record_fact(mid, {**observation, "witness_ids": []}, expected_state_version=engine.state.state_version)
    assert table.record_fact(mid, observation, expected_state_version=engine.state.state_version)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    from combat.table_facts import records
    assert "ordinary-observation" in records(loaded.engine, loaded.engine.state.actors[AID])
    assert "ordinary-observation" not in records(loaded.engine, loaded.engine.state.actors[AN])
    assert "ordinary-observation" not in json.dumps(combat.ai_decision_context(loaded).model_dump(mode="json"))
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_scene_metadata_redaction_preserves_unrelated_event_information():
    from combat.scene_facts import private_event_view
    document = {"payload": {"damage": 7, "subject": "patient", "conditions_after": [
        {"condition_id": "condition:table.fact.test", "data": {"table_fact_json": json.dumps({"cause": "secret cause"})}},
        {"condition_id": "condition:typed.bleeding", "data": {"label": "Bleeding"}}]}}
    redacted = private_event_view(document)
    assert redacted["payload"]["damage"] == 7
    assert redacted["payload"]["conditions_after"][1] == document["payload"]["conditions_after"][1]
    assert "secret cause" not in json.dumps(redacted)
    assert "secret cause" in json.dumps(document)


@pytest.mark.parametrize("ability,base_bonus", [("Wisdom", 5), ("Life key", 9)])
@pytest.mark.parametrize("levels", [0, 1, 3])
def test_journey_medicine_uses_persisted_travel_exhaustion_in_menu_and_roll(
        tmp_path, monkeypatch, ability, base_bonus, levels):
    # Put the DC exactly at the unexhausted total: ignoring even one level
    # incorrectly reveals a hidden cause. Only the deterministic die is fixed.
    monkeypatch.setattr("factory_authoring.starting_kits.seeded_roll", lambda *args: 10)
    combat, _ = clinic(tmp_path, fact=case(seconds=0, dc=10 + base_bonus))
    state = combat.create_journey(project_ids=[PID, PATIENT], arena_id=DEFAULT_FACTORY_ARENA,
        positions={AID: {"x": 3, "y": 6}, TARGET: {"x": 4, "y": 6}},
        base_paces={AID: 10000, TARGET: 10000})
    jid = state["journey_id"]
    if levels:
        state = combat.journey_act(jid, state["revision"], AID, "travel_exhaustion",
                                   {"levels": levels, "ordinary": True})
    cold = CombatService(ROOT, tmp_path)
    assert cold.journey_state(jid)["actors"][AID]["exhaustion"] == levels
    option = next(o for o in cold.journey_menu(jid, AID)["options"]
                  if o["kind"] == "life_medicine" and o["payload"]["ability"] == ability)
    bonus = base_bonus - 2 * levels
    assert f"({bonus:+d}, DC {10 + base_bonus};" in option["label"]
    cold.journey_act(jid, state["revision"], AID, option["kind"], option["payload"])
    saved = CombatService(ROOT, tmp_path).journey_state(jid)
    check = saved["events"][-1]
    assert (check["kind"], check["natural"], check["bonus"], check["dc"], check["success"]) == (
        "MEDICINE_CHECK", 10, bonus, 10 + base_bonus, int(levels == 0))
    assert bool(saved["actors"][AID].get("knowledge")) == (levels == 0)
    assert case()["cause"] not in json.dumps(saved["events"])


def test_combat_condition_is_recognized_after_native_journey_resume_and_cold_reload(tmp_path):
    combat, table = clinic(tmp_path)
    bundles = [compile_character(combat._factory_owner_sheet(pid), actor_id=aid)
               for pid, aid in ((PID, AID), (PATIENT, TARGET))]
    # A fixture action supplies a real persistent condition through the typed
    # executor. No clinical declaration describes poisoning or its hidden cause.
    seed(bundles[0], "Clinical fixture poisoning", [{"type": "condition", "condition": "poisoned",
        "applies_to": "target", "duration": {"kind": "until_removed"}}], target="ANY_CREATURE")
    bundles[0]["bundle_sha256"] = canonical_sha256({k: v for k, v in bundles[0].items() if k != "bundle_sha256"})
    spots = {AID: {"x": 3, "y": 6}, TARGET: {"x": 4, "y": 6}}
    state = combat.journeys.create(bundles, combat.factory_arenas()[DEFAULT_FACTORY_ARENA],
        spots, {AID: 10000, TARGET: 10000}, {AID: "MANUAL", TARGET: "MANUAL"})
    jid = state["journey_id"]
    mid = combat.journey_start_combat(jid, state["revision"], {AID: "team:a", TARGET: "team:b"},
                                      maximum_rounds=1)["match_id"]
    turn(table, mid, AID)
    assert act(table, mid, candidate(combat, mid, "Clinical fixture poisoning", TARGET))["status"] == "COMMITTED"
    assert act(table, mid, candidate(combat, mid, "Life Initiation: recognize obvious signs", TARGET))["status"] == "COMMITTED"
    from combat.ext.life_initiation import obvious_signs
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert obvious_signs(loaded.engine, loaded.engine.state.actors[TARGET]) == ["poisoning"]
    for _ in range(4):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            break
        menu = table.state(mid)["menu"]
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)["status"] == "COMMITTED"
    cold = CombatService(ROOT, tmp_path)
    assert cold._load_session(mid).mechanical.replay()["status"] == "PASS"
    state = cold.journey_resume(jid, cold.journey_state(jid)["revision"])
    cold = CombatService(ROOT, tmp_path)
    snapshot = cold.journey_state(jid)["actors"][TARGET]["encounter_snapshot"]
    assert any(json.loads(c)["condition_id"] == "condition:typed.poisoned" for c in snapshot["conditions"].values())
    cold.journey_act(jid, state["revision"], AID, "life_recognize", {"target": TARGET})
    saved = CombatService(ROOT, tmp_path).journey_state(jid)
    assert saved["events"][-1]["signs"] == ["poisoning"]
    assert not saved["actors"][AID].get("knowledge")
    assert case()["cause"] not in json.dumps(saved["events"])
