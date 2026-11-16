"""HTTP action selections and human Ask me answers survive a service reload.

Uses in-process ASGI transport: no sockets, browsers, or real model inference.
"""
import json
import zipfile

import httpx
import pytest

from app.api import create_app
from app.core import Settings
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate3_reducer import canonical_state_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.async_support import run_asgi
from tests.h1_support import ROOT, sheet
from tests.test_agent_seats import runner_for
from tests.test_hunt5_player_choices import PLAYER, FOE, fixture


def fight(tmp_path):
    document = sheet(["TAL_FENCING_FOOTWORK"], cl=15)
    archive = tmp_path / "portable_characters" / "h5-player" / "current.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    bundle = compile_character(document, actor_id=PLAYER, reaction_plan={"ask": True})
    mid = combat._finish_factory_match(
        [bundle], [PLAYER, AN], {PLAYER: "team:factory", AN: "team:opponents"},
        {PLAYER: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [PLAYER], [AN], control_modes={PLAYER: "MANUAL", AN: "MANUAL"},
        match_seed="ACT-API-OPTIONS", display_name="Human reaction", maximum_rounds=10,
    )["match_id"]
    menu = table.state(mid)["menu"]
    if menu["actor_id"] != AN:
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)["status"] == "COMMITTED"
    return mid


@pytest.mark.parametrize("control,option_ids,ranked", [
    ("MODEL", [], False), ("MODEL", ["NEXT_ATTACK_ADVANTAGE"], False),
    ("MODEL", [], True), ("MODEL", ["NEXT_ATTACK_ADVANTAGE"], True),
    ("MANUAL", None, False), ("MANUAL", [], False), ("MANUAL", ["NEXT_ATTACK_ADVANTAGE"], False),
])
def test_http_ask_me_continuation_preserves_action_selection_after_reload(tmp_path, monkeypatch, control, option_ids, ranked):
    from combat import menu_rank, embedding_rank
    monkeypatch.setenv("CF_EMBED_MENU", "1" if ranked else "0")
    def embeddings(_url, body, _timeout):
        texts = json.loads(body)["input"]
        return json.dumps({"data": [{"index": i, "embedding": [1.0] * embedding_rank.DIMENSION}
                                    for i, _ in enumerate(texts)]}).encode()
    monkeypatch.setattr(menu_rank, "_CLIENT", embedding_rank.EmbeddingClient(transport=embeddings))
    if option_ids is None:
        _, _, mid, legacy_cid, _ = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
        attacker = FOE
    else:
        mid = fight(tmp_path)
        attacker = AN
    settings = Settings.from_env(ROOT, tmp_path)
    app = create_app(settings)
    app.state.agent_seats.background = False
    calls, plans = [], []

    def provider(_provider, prompt, _png):
        calls.append(prompt)
        legal = json.loads(prompt.split("\n", 1)[1])["legal_menu"]
        chosen = next((key for key, row in legal.items()
                      if row["source"] == "action:an_eui.scouring_destruction_blast"
                      and row["targets"] == [PLAYER] and row["options"] == option_ids), None)
        # A ranked menu is paged. The fake provider must browse just as a real
        # provider would, rather than failing when its desired step isn't on
        # the first page. MORE never executes an action or sees hidden state.
        if chosen is None:
            return "MORE", {}
        end = next(key for key, row in legal.items() if row["action"] == "End turn")
        plans.append([chosen, end])
        return json.dumps({"plan": plans[-1]}), {}

    if control == "MODEL":
        runner, _ = runner_for(tmp_path, app.state.agent_seats.table, provider, timeout=30)
        runner.set_seat(mid, AN, "MODEL", "fake")
        assert runner.drive(mid, max_steps=1) == 1
        assert calls and len(plans) == 1
        if not ranked:
            assert len(calls) == 1
        assert not runner.decisions(mid)[0]["fallback"], runner.decisions(mid)[0].get("fallback_error")

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
            token = (await client.get("/api/session")).json()["token"]
            headers = {"x-foundry-token": token}
            state = (await client.get(f"/api/tabletop/matches/{mid}/state")).json()
            if control == "MANUAL":
                menu = state["menu"]
                candidate = next(row for row in app.state.combat.decision(mid)["context"]["legal_candidates"]
                                 if (row["candidate_id"] == legacy_cid if option_ids is None else
                                     row["source_definition_id"] == "action:an_eui.scouring_destruction_blast" and row["target_ids"] == [PLAYER]))
                request = {"candidate_id": candidate["candidate_id"], "decision_id": menu["decision_id"],
                           "state_version": menu["state_version"], "after": state["last_sequence"]}
                if option_ids is not None:
                    request["option_ids"] = option_ids
                first = await client.post(f"/api/tabletop/matches/{mid}/act", headers=headers, json=request)
                assert first.status_code == 200, first.text
                assert first.json()["status"] == "REACTION_REQUIRED"

        # Recreate the app and both services; no provider survives this reload.
        reopened = create_app(settings)
        reopened.state.agent_seats.background = False
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=reopened), base_url="http://127.0.0.1:8000") as client:
            token = (await client.get("/api/session")).json()["token"]
            headers = {"x-foundry-token": token}
            response = await client.get(f"/api/tabletop/matches/{mid}/state")
            assert response.status_code == 200, response.text
            state = response.json()
            pending = state["pending_action"]
            assert pending["method"] == "act"
            if option_ids is None:
                assert "option_ids" not in pending["request"]
            else:
                assert pending["request"]["option_ids"] == option_ids
            prompt = pending["reaction"]
            assert prompt["reaction"] == "Footwork" and prompt["context"]["reactor_id"] == PLAYER
            stay = next(row["id"] for row in prompt["choice"]["options"] if "Stay put" in row["label"])
            answer = {**prompt["context"], "selection": "USE", "option_ids": [stay], "spend": 0}
            request = {**pending["request"], "after": state["last_sequence"], "reactions": [answer]}
            before = canonical_state_sha256(reopened.state.combat._load_session(mid).engine.state)
            if option_ids is not None:
                for changed in (["AC_MINUS_1"] if not option_ids else [], None):
                    altered = {**request, "option_ids": changed}
                    if changed is None:
                        altered.pop("option_ids")
                    rejected = await client.post(f"/api/tabletop/matches/{mid}/act", headers=headers, json=altered)
                    assert rejected.status_code == 409, rejected.text
                    assert rejected.json()["error"]["code"] == "TABLETOP_PENDING"
                    assert canonical_state_sha256(reopened.state.combat._load_session(mid).engine.state) == before
                    unchanged = (await client.get(f"/api/tabletop/matches/{mid}/state")).json()
                    assert unchanged["pending_action"] == pending
            done = await client.post(f"/api/tabletop/matches/{mid}/act", headers=headers, json=request)
            assert done.status_code == 200, done.text
            assert done.json()["status"] == "COMMITTED"
            assert done.json()["state"]["pending_action"] is None
            # Confirm the actual committed selection, not just an HTTP success.
            events = reopened.state.combat._load_session(mid).engine.events
            committed = next(event for event in reversed(events) if event.event_type == "INTENT_ACCEPTED" and event.actor_id == attacker)
            assert committed.payload["option_ids"] == (option_ids or [])

    run_asgi(exercise())
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    assert len(plans) == (1 if control == "MODEL" else 0)
    if control == "MANUAL":
        assert not calls
