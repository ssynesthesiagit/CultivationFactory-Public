from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Settings
from combat.gate3_storage import Gate3MatchStore
from combat.canonical import canonical_sha256
from combat.diagnostics import CombatGate1Error
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN, BAI, CUI, LEE, LING
from combat.gate2_runtime_models import ActionIntent, CandidateKind, Position
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate4_policy import PolicyLibrary
from combat.gate4_runner import NoProgressTracker
from combat.gate5_service import CombatService

ROOT = Path(__file__).resolve().parents[1]
LIVE_SEED = "GATE5-LIVE-FIGHT-2026-07-21-A"
COMMAND_CUI = "action:bai_meizhen.command_cui"


def prepared_engine(seed: str = "GATE5.1-CANDIDATES") -> Gate2Engine:
    engine = Gate2Engine(ROOT, match_seed=seed)
    engine.state.current_actor_id = BAI
    engine.state.current_slot_index = engine.state.initiative_order.index(BAI)
    bai = engine.state.actors[BAI]
    bai.action_available = True
    bai.bonus_action_available = True
    bai.reaction_available = True
    bai.movement_remaining_ft = bai.speed_ft
    return engine


def intent_for(candidate, *, target_ids=None, options=None, intent_id="gate5.1-test") -> ActionIntent:
    return ActionIntent(
        intent_id=intent_id,
        decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id,
        state_version=candidate.state_version,
        actor_id=candidate.actor_id,
        target_ids=tuple(candidate.target_ids if target_ids is None else target_ids),
        destination=candidate.destination,
        option_ids=tuple(candidate.option_ids if options is None else options),
        reaction_decisions=(),
    )


def command_candidates(engine: Gate2Engine):
    return tuple(row for row in engine.legal_candidates() if row.source_definition_id == COMMAND_CUI)


def test_command_cui_candidates_are_mode_specific_and_deterministic() -> None:
    first = prepared_engine("GATE5.1-CANDIDATE-DOMAIN")
    second = prepared_engine("GATE5.1-CANDIDATE-DOMAIN")
    rows = command_candidates(first)
    assert rows
    assert [(row.candidate_id, row.target_ids, row.destination, row.option_ids) for row in rows] == [
        (row.candidate_id, row.target_ids, row.destination, row.option_ids)
        for row in command_candidates(second)
    ]
    assert all(len(row.option_ids) == 1 for row in rows)

    by_mode = {mode: [row for row in rows if row.option_ids == (mode,)] for mode in ("STRIKE", "DODGE", "DASH", "HOLD")}
    assert all(by_mode.values())

    cui = first.state.actors[CUI]
    for row in by_mode["STRIKE"]:
        assert len(row.target_ids) == 1
        target = first.state.actors[row.target_ids[0]]
        assert target.active
        assert target.team_id != cui.team_id
        assert target.entity_id not in {BAI, LING, CUI}
        assert row.destination is None
        assert row.metadata["target_domain"] == "ACTIVE_HOSTILE"

    assert len(by_mode["DODGE"]) == 1
    assert by_mode["DODGE"][0].target_ids == (CUI,)
    assert by_mode["DODGE"][0].destination is None
    assert len(by_mode["HOLD"]) == 1
    assert by_mode["HOLD"][0].target_ids == ()
    assert by_mode["HOLD"][0].destination is None

    for row in by_mode["DASH"]:
        assert len(row.target_ids) == 1
        target = first.state.actors[row.target_ids[0]]
        assert target.active and target.entity_id != CUI
        assert row.destination == target.position

    assert len({row.candidate_id for row in rows}) == len(rows)


def test_engine_rejects_malformed_allied_cui_strike_without_mutation() -> None:
    engine = prepared_engine("GATE5.1-ENGINE-REJECT")
    legal_strike = next(row for row in command_candidates(engine) if row.option_ids == ("STRIKE",))
    malicious = legal_strike.model_copy(update={
        "candidate_id": "candidate:malformed-allied-cui-strike",
        "target_ids": (BAI,),
        "destination": None,
    })
    before = {
        "state": engine.export().canonical_state_sha256,
        "events": canonical_sha256([row.model_dump(mode="json") for row in engine.events]),
        "rolls": canonical_sha256([row.model_dump(mode="json") for row in engine.rolls]),
        "version": engine.state.state_version,
        "sequence": engine.state.event_sequence,
        "counter": engine.state.roll_counter,
    }
    engine.legal_candidates = lambda: (malicious,)  # type: ignore[method-assign]
    with pytest.raises(CombatGate1Error) as exc:
        engine.execute_intent(intent_for(malicious, target_ids=(BAI,), options=("STRIKE",)))
    assert exc.value.diagnostic.code == "GATE5_CUI_STRIKE_TARGET_NOT_HOSTILE"
    after = {
        "state": engine.export().canonical_state_sha256,
        "events": canonical_sha256([row.model_dump(mode="json") for row in engine.events]),
        "rolls": canonical_sha256([row.model_dump(mode="json") for row in engine.rolls]),
        "version": engine.state.state_version,
        "sequence": engine.state.event_sequence,
        "counter": engine.state.roll_counter,
    }
    assert after == before


def _controller_context(engine: Gate4ControllerEngine):
    policy, _ = PolicyLibrary(ROOT).for_actor(engine.state.current_actor_id)
    return build_decision_context(engine, policy)


def test_controller_never_scores_allied_strike_and_selects_hostile_strike() -> None:
    engine = Gate4ControllerEngine(ROOT, match_seed="GATE5.1-CONTROLLER-STRIKE")
    engine.state.current_actor_id = BAI
    bai = engine.state.actors[BAI]
    bai.action_available = False
    bai.bonus_action_available = True
    cui = engine.state.actors[CUI]
    cui.position = Position(x=10, y=8)
    engine.state.actors[AN].position = Position(x=11, y=8)
    engine.state.actors[LEE].position = Position(x=12, y=8)

    context = _controller_context(engine)
    choice = LocalDeterministicController().choose_primary_action(context)
    selected = next(row for row in context.legal_candidates if row.candidate_id == choice.intent.candidate_id)
    assert selected.source_definition_id == COMMAND_CUI
    assert choice.intent.option_ids == ("STRIKE",)
    target = engine.state.actors[choice.intent.target_ids[0]]
    assert target.active and target.team_id != cui.team_id

    end_turn = next(row for row in context.legal_candidates if row.kind == CandidateKind.END_TURN)
    malformed = selected.model_copy(update={
        "candidate_id": "candidate:controller-allied-strike",
        "target_ids": (BAI,),
        "destination": None,
    })
    malformed_context = context.model_copy(update={"legal_candidates": (malformed, end_turn)})
    safe_choice = LocalDeterministicController().choose_primary_action(malformed_context)
    assert safe_choice.intent.candidate_id == end_turn.candidate_id
    assert all(row.candidate_id != malformed.candidate_id for row in safe_choice.record.scored_alternatives)


def test_controller_uses_cui_dodge_when_no_useful_strike_or_dash_exists() -> None:
    engine = Gate4ControllerEngine(ROOT, match_seed="GATE5.1-CONTROLLER-DODGE")
    engine.state.current_actor_id = BAI
    bai = engine.state.actors[BAI]
    bai.action_available = False
    bai.bonus_action_available = True
    engine.state.actors[AN].active = False
    engine.state.actors[LEE].active = False
    shared = Position(x=10, y=8)
    engine.state.actors[CUI].position = shared
    engine.state.actors[BAI].position = shared
    engine.state.actors[LING].position = shared

    context = _controller_context(engine)
    first = LocalDeterministicController().choose_primary_action(context)
    second = LocalDeterministicController().choose_primary_action(context)
    assert first == second
    selected = next(row for row in context.legal_candidates if row.candidate_id == first.intent.candidate_id)
    assert selected.source_definition_id == COMMAND_CUI
    assert first.intent.option_ids == ("DODGE",)
    assert first.intent.target_ids == (CUI,)


def test_controller_prefers_end_turn_and_suppresses_repeated_hold() -> None:
    engine = Gate4ControllerEngine(ROOT, match_seed="GATE5.1-HOLD")
    actor_id = engine.state.current_actor_id
    actor = engine.state.actors[actor_id]
    actor.action_available = False
    actor.bonus_action_available = False
    actor.movement_remaining_ft = 0

    context = _controller_context(engine)
    choice = LocalDeterministicController().choose_primary_action(context)
    selected = next(row for row in context.legal_candidates if row.candidate_id == choice.intent.candidate_id)
    assert selected.kind == CandidateKind.END_TURN

    hold = next(row for row in engine.legal_candidates() if row.kind == CandidateKind.HOLD_POSITION)
    engine.execute_intent(intent_for(hold, options=(), intent_id="manual-hold"))
    after_hold = _controller_context(engine)
    assert any(row.kind == CandidateKind.HOLD_POSITION for row in after_hold.legal_candidates)
    choice_after = LocalDeterministicController().choose_primary_action(after_hold)
    selected_after = next(row for row in after_hold.legal_candidates if row.candidate_id == choice_after.intent.candidate_id)
    assert selected_after.kind == CandidateKind.END_TURN
    assert all(
        row.candidate_id != next(candidate.candidate_id for candidate in after_hold.legal_candidates if candidate.kind == CandidateKind.HOLD_POSITION)
        for row in choice_after.record.scored_alternatives
    )


def _api(tmp_path: Path):
    user_data = tmp_path / "UserData"
    settings = Settings.from_env(ROOT, user_data)
    client = TestClient(create_app(settings))
    client.__enter__()
    token = client.get("/api/session").json()["token"]
    return client, {"x-foundry-token": token}, user_data


def _create_api_match(client: TestClient, headers: dict[str, str], seed: str, *, local_auto: bool = False) -> str:
    catalog = client.get("/api/combat/catalog").json()
    modes = {
        row["runtime_entity_id"]: "LOCAL_AUTO"
        for row in catalog["projections"]
        if local_auto and row.get("primary_combatant")
    }
    response = client.post(
        "/api/combat/matches",
        headers=headers,
        json={
            "encounter_id": catalog["encounters"][0]["stable_id"],
            "display_name": "Gate 5.1 correction test",
            "match_seed": seed,
            "control_modes": modes,
            "maximum_rounds": 20,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["match_id"]


def _intent_payload(candidate: dict) -> dict:
    return {
        "decision_id": candidate["decision_id"],
        "state_version": candidate["state_version"],
        "candidate_id": candidate["candidate_id"],
        "actor_id": candidate["actor_id"],
        "target_ids": candidate.get("target_ids") or [],
        "destination": candidate.get("destination"),
        "option_ids": candidate.get("option_ids") or [],
    }


def _commit_without_reaction(client: TestClient, headers: dict[str, str], match_id: str, candidate: dict) -> None:
    payload = _intent_payload(candidate)
    preview = client.post(
        f"/api/combat/matches/{match_id}/preview",
        headers=headers,
        json={"intent": payload, "reaction_decisions": []},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["status"] == "PREVIEW_COMPLETE"
    commit = client.post(
        f"/api/combat/matches/{match_id}/intent",
        headers=headers,
        json={"intent": payload, "reaction_decisions": [], "preview_id": body["preview_id"]},
    )
    assert commit.status_code == 200, commit.text


def _advance_to_bai(client: TestClient, headers: dict[str, str], match_id: str) -> dict:
    for _ in range(8):
        decision = client.get(f"/api/combat/matches/{match_id}/decision").json()["context"]
        if decision["active_actor_id"] == BAI:
            return decision
        end = next(row for row in decision["legal_candidates"] if row["kind"] == "END_TURN")
        _commit_without_reaction(client, headers, match_id, end)
    raise AssertionError("Bai decision not reached")


def test_api_ai_frame_and_ui_use_corrected_candidate_authority(tmp_path: Path) -> None:
    client, headers, user_data = _api(tmp_path)
    try:
        match_id = _create_api_match(client, headers, "GATE5.1-API")
        context = _advance_to_bai(client, headers, match_id)
        command_rows = [row for row in context["legal_candidates"] if row["source_definition_id"] == COMMAND_CUI]
        assert command_rows and all(len(row["option_ids"]) == 1 for row in command_rows)
        actor_map = {row["entity_id"]: row for row in context["actors"]}
        cui_team = actor_map[CUI]["team_id"]
        strikes = [row for row in command_rows if row["option_ids"] == ["STRIKE"]]
        assert strikes
        assert all(actor_map[row["target_ids"][0]]["active"] and actor_map[row["target_ids"][0]]["team_id"] != cui_team for row in strikes)

        frame = client.get(f"/api/combat/matches/{match_id}/ai-frame").json()["frame"]
        frame_rows = [row for row in frame["legal_candidates"] if row["candidate_id"] in {item["candidate_id"] for item in command_rows}]
        assert len(frame_rows) == len(command_rows)
        assert all(len(row["option_ids"]) == 1 for row in frame_rows)

        state_before = client.get(f"/api/combat/matches/{match_id}").json()["state"]
        match_dir = Gate3MatchStore(user_data, match_id).match_dir
        journal_before = hashlib.sha256((match_dir / "Journal.ndjson").read_bytes()).hexdigest()
        controller_before = hashlib.sha256((match_dir / "ControllerJournal.ndjson").read_bytes()).hexdigest()
        malicious = _intent_payload(strikes[0])
        malicious["target_ids"] = [BAI]
        rejected = client.post(
            f"/api/combat/matches/{match_id}/ai-intent/validate",
            headers=headers,
            json={"schema": "TianxiaFactoryCombatAIResponse.v1", "action_intent": malicious},
        )
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "COMBAT_AI_INTENT_INVALID"
        state_after = client.get(f"/api/combat/matches/{match_id}").json()["state"]
        assert hashlib.sha256((match_dir / "Journal.ndjson").read_bytes()).hexdigest() == journal_before
        assert hashlib.sha256((match_dir / "ControllerJournal.ndjson").read_bytes()).hexdigest() == controller_before
        assert (state_before["state_version"], state_before["event_sequence"], state_before["roll_counter"]) == (
            state_after["state_version"], state_after["event_sequence"], state_after["roll_counter"]
        )

        old_identity = {
            "decision_id": context["decision_id"],
            "kind": "BONUS_ACTION",
            "actor_id": BAI,
            "source_definition_id": COMMAND_CUI,
            "target_ids": [BAI],
            "destination": None,
            "state_version": context["state_version"],
        }
        stale_payload = {
            "decision_id": context["decision_id"],
            "state_version": context["state_version"],
            "candidate_id": f"candidate:{canonical_sha256(old_identity)[:24]}",
            "actor_id": BAI,
            "target_ids": [BAI],
            "destination": None,
            "option_ids": ["STRIKE"],
        }
        stale = client.post(
            f"/api/combat/matches/{match_id}/ai-intent/validate",
            headers=headers,
            json={"action_intent": stale_payload},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "COMBAT_DECISION_STALE"

        dodge = next(row for row in command_rows if row["option_ids"] == ["DODGE"])
        _commit_without_reaction(client, headers, match_id, dodge)
        assert client.post(f"/api/combat/matches/{match_id}/verify", headers=headers, json={}).json()["status"] == "PASS"

        js = (ROOT / "static/app.js").read_text(encoding="utf-8")
        assert "candidate.metadata?.command_mode" in js
    finally:
        client.__exit__(None, None, None)


def test_exact_live_seed_has_only_active_hostile_cui_strikes_and_replays(tmp_path: Path) -> None:
    service = CombatService(ROOT, tmp_path / "UserData")
    catalog = service.catalog()
    modes = {
        row["runtime_entity_id"]: "LOCAL_AUTO"
        for row in catalog["projections"]
        if row.get("primary_combatant")
    }
    created = service.create_match(
        encounter_id=catalog["encounters"][0]["stable_id"],
        display_name="Gate 5.1 corrected live seed",
        match_seed=LIVE_SEED,
        control_modes=modes,
        maximum_rounds=20,
    )
    match_id = created["match_id"]
    session = service._load_session(match_id)
    tracker = NoProgressTracker(round_at_last_change=session.engine.state.round_number)
    total_steps = 0
    cui_strike_decisions: list[dict[str, object]] = []
    for _ in range(999):
        if session.engine.state.terminal_result is not None:
            break
        candidates = session.engine.legal_candidates()
        actor_id = candidates[0].actor_id
        policy, _ = service.policies.for_actor(actor_id)
        context = build_decision_context(
            session.engine,
            policy,
            no_progress_signals=tracker.signals(session),
        )
        choice = service.controller.choose_primary_action(context)
        selected = next(row for row in candidates if row.candidate_id == choice.intent.candidate_id)
        if selected.source_definition_id == COMMAND_CUI and choice.intent.option_ids == ("STRIKE",):
            assert len(choice.intent.target_ids) == 1
            cui = session.engine.state.actors[CUI]
            target = session.engine.state.actors[choice.intent.target_ids[0]]
            cui_strike_decisions.append({
                "target_id": target.entity_id,
                "target_active": target.active,
                "target_team_id": target.team_id,
                "cui_team_id": cui.team_id,
                "round_number": session.engine.state.round_number,
                "state_version": session.engine.state.state_version,
            })
            assert target.active
            assert target.team_id != cui.team_id
            assert target.entity_id not in {BAI, LING, CUI}
        session.execute_controller_choice(
            choice,
            controller=service.controller,
            policy_library=service.policies,
        )
        tracker.update(session, selected.source_definition_id)
        total_steps += 1
    else:
        raise AssertionError("exact live seed exceeded the bounded decision limit")
    assert session.engine.state.terminal_result is not None

    state = session.engine.state.model_dump(mode="json")
    assert state["terminal_result"] is not None
    assert total_steps > 0
    verify_body = session.verify()
    assert verify_body["status"] == "PASS"
    replay_body = session.mechanical.replay()
    events = replay_body["events"]
    actors = state["actors"]
    cui_team = actors[CUI]["team_id"]
    cui_attacks = [
        event for event in events
        if event["event_type"] == "ATTACK_ROLLED" and event["actor_id"] == CUI
    ]
    assert cui_attacks
    # A legal STRIKE command may spend Cui's movement toward an active hostile
    # without reaching attack range in that transaction. Every attack must come
    # from a hostile-bound Strike decision, but not every such decision must roll.
    assert len(cui_attacks) <= len(cui_strike_decisions)
    assert all(row["target_active"] and row["target_team_id"] != row["cui_team_id"] for row in cui_strike_decisions)
    for event in cui_attacks:
        assert len(event["target_ids"]) == 1
        target = actors[event["target_ids"][0]]
        assert target["team_id"] != cui_team
        assert event["target_ids"][0] not in {BAI, LING, CUI}

    match_ended = [event["sequence"] for event in events if event["event_type"] == "MATCH_ENDED"]
    assert len(match_ended) == 1
    assert all(event["sequence"] <= match_ended[0] for event in events)
    assert all(value >= 0 for actor in actors.values() for value in actor["resources"].values())

    holds_by_actor_turn: dict[tuple[str, int], int] = {}
    current_turn: dict[str, int] = {}
    for event in events:
        if event["event_type"] == "TURN_STARTED" and event.get("actor_id"):
            current_turn[event["actor_id"]] = current_turn.get(event["actor_id"], 0) + 1
        if event["event_type"] == "HOLD_POSITION_COMMITTED" and event.get("actor_id") in current_turn:
            key = (event["actor_id"], current_turn[event["actor_id"]])
            holds_by_actor_turn[key] = holds_by_actor_turn.get(key, 0) + 1
    assert all(count <= 1 for count in holds_by_actor_turn.values())

    export_hashes = session.mechanical.export()
    assert set(export_hashes) == {
        "Gate3_Current_State.json",
        "Gate3_Event_Log.json",
        "Gate3_Roll_Log.json",
        "Gate3_Replay_Result.json",
    }
    for name, digest in export_hashes.items():
        path = session.store.exports_dir / name
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
