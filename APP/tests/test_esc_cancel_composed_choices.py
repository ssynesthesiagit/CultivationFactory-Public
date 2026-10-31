"""Composed attacks collect real Ask-me choices before saving settings or combat."""
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from combat.ext import blossom
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_reactions import rules
from tests.h1_support import ROOT, sheet
from tests.hunt12_support import ME, FOE


@pytest.fixture
def footwork_registration(monkeypatch):
    """Exercise the real Footwork hooks without an optional rules-data file."""
    monkeypatch.setitem(rules()["features"], "TAL_FENCING_FOOTWORK",
                        {"block": "needle", "kind": "footwork"})


@pytest.fixture
def composed_choice(tmp_path, monkeypatch, footwork_registration):
    monkeypatch.setenv("CF_EMBED_MENU", "0")
    documents = [
        sheet(["TAL_FLOWERS_CULTIVATE_BLOSSOM", blossom.SEED, blossom.GARDEN, blossom.THORN],
              cl=18, primary="Stamina", score=18),
        sheet(["TAL_FENCING_FOOTWORK"], cl=18, primary="Stamina"),
    ]
    bundles = [compile_character(doc, actor_id=who, reaction_plan={"ask": True})
               for doc, who in zip(documents, [ME, FOE])]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [ME, FOE], {ME: "team:factory", FOE: "team:opponents"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed="ESC-COMPOSED-CHOICE",
        display_name="Composed choice regression", maximum_rounds=10)["match_id"]
    menu = table.state(mid)["menu"]
    if menu["actor_id"] != ME:
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)["status"] == "COMMITTED"
        menu = table.state(mid)["menu"]
    sources = []
    for suffix in ("blossom.seed.poison", "blossom.pick.seed", "blossom.garden.off"):
        matches = [row["source"] for row in menu["composition"].values() if row["source"].endswith(suffix)]
        assert matches, f"Missing draft setting {suffix}: {menu['composition']}"
        sources.append(matches[0])
    # Drafted settings can change legality; select the owned sheet activation.
    source = next(source for source in combat._load_session(mid).engine.action_catalog
                  if source.endswith("blossom.cultivate_bloom"))
    payload = dict(actor_id=ME, decision_id=menu["decision_id"], state_version=menu["state_version"],
                   sources=sources, source_definition_id=source, request_id="cancel-composed-choice")
    options = [o for g in table.preview_composition(mid, payload)["menu"]["actions"] for o in g["options"]]
    # Cultivate Blossom is a CELL action: the occupant is resolved during
    # execution, not recorded in candidate.target_ids.
    chosen = next((o for o in options if (o.get("destination") or {}).get("x") == 4
                   and (o.get("destination") or {}).get("y") == 6), None)
    assert chosen is not None, "The composed menu must offer the enemy's square"
    return combat, table, mid, payload, chosen


def test_composed_prepare_abandon_reload_saves_no_settings_journal_or_pending_action(composed_choice, tmp_path):
    combat, table, mid, payload, chosen = composed_choice
    session = combat._load_session(mid)
    before = session.engine.state.model_dump(mode="json")
    journal = session.store.journal_path.read_bytes()
    after = session.engine.state.event_sequence
    feed = table.events(mid, 0)
    result = table.prepare_composition(mid, payload, chosen["candidate_id"])
    assert result["status"] == "REACTION_REQUIRED", result
    assert result["reaction"]["reaction"] == "Footwork"
    assert result["reaction"]["context"]["reactor_id"] == FOE
    assert result["events"] == feed, "draft settings must not leak into the event feed"
    assert result["events"]["last_sequence"] == after
    # Escape abandons this unsent request. No cleanup endpoint should be needed.
    assert not table._pending_action_path(mid).exists()
    assert session.store.journal_path.read_bytes() == journal
    cold = CombatService(ROOT, tmp_path)
    reopened = TabletopService(cold, tmp_path)
    assert reopened.state(mid)["pending_action"] is None
    assert cold._load_session(mid).engine.state.model_dump(mode="json") == before
    assert session.store.journal_path.read_bytes() == journal


def test_http_composed_prepare_answers_then_explicit_commit(composed_choice, tmp_path, monkeypatch):
    from app.api import create_app
    from app.core import Settings

    combat, table, mid, payload, chosen = composed_choice
    monkeypatch.setattr(Draft202012Validator, "check_schema",
                        classmethod(lambda cls, schema, format_checker=None: None))
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    session = combat._load_session(mid)
    before = session.engine.state.model_dump(mode="json")
    journal = session.store.journal_path.read_bytes()
    after = session.engine.state.event_sequence
    body = {"candidate_id": chosen["candidate_id"], "decision_id": payload["decision_id"],
            "state_version": payload["state_version"], "after": after, "composition": payload}
    with TestClient(app) as client:
        headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
        url = f"/api/tabletop/matches/{mid}"
        reply = client.post(url + "/prepare", json=body, headers=headers)
        assert reply.status_code == 200, reply.text
        first = reply.json()
        assert first["status"] == "REACTION_REQUIRED", first
        assert first["events"]["last_sequence"] == after
        assert first["events"]["events"] == []
        prompt = first["reaction"]
        assert prompt["reaction"] == "Footwork"
        stay = next(o["id"] for o in prompt["choice"]["options"] if "Stay put" in o["label"])
        body["reactions"] = [{**prompt["context"], "selection": "USE", "option_ids": [stay]}]
        reply = client.post(url + "/prepare", json=body, headers=headers)
        assert reply.status_code == 200, reply.text
        assert reply.json() == {"status": "PREPARED"}
        assert session.store.journal_path.read_bytes() == journal
        cold = CombatService(ROOT, tmp_path)
        assert cold._load_session(mid).engine.state.model_dump(mode="json") == before
        assert TabletopService(cold, tmp_path).state(mid)["pending_action"] is None
        reply = client.post(url + "/act", json=body, headers=headers)
        assert reply.status_code == 200, reply.text
        assert reply.json()["status"] == "COMMITTED", reply.json()
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.store.journal_path.read_bytes() != journal
    settings = next(c.data for c in loaded.engine.state.actors[ME].conditions.values()
                    if c.condition_id == blossom.SETUP)
    assert (settings["seed"], settings["bloom"], settings["garden"]) == ("poison", "seed", "off")
    assert loaded.engine.state.actors[FOE].resources["resource:core.martial_focus"] == (
        before["actors"][FOE]["resources"]["resource:core.martial_focus"] - 1)
    assert not table._pending_action_path(mid).exists()
    assert loaded.verify()["status"] == "PASS"
