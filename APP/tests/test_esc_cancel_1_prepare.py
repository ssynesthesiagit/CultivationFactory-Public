"""A composed action prepares through the same draft check as commit, and saves nothing."""
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from combat.tabletop import TabletopError
from tests.hunt12_support import ME
from tests.test_esc_cancel_composed_choices import composed_choice, footwork_registration  # noqa: F401 (fixtures)


@pytest.fixture
def drafted(composed_choice):  # noqa: F811
    combat, table, mid, payload, _ = composed_choice
    options = [o for g in table.preview_composition(mid, payload)["menu"]["actions"] for o in g["options"]]
    position = combat._load_session(mid).engine.state.actors[ME].position
    chosen = next(o for o in options if (o.get("destination") or {}).get("x") == position.x
                  and (o.get("destination") or {}).get("y") == position.y)
    return combat, table, mid, payload, chosen


def test_prepare_accepts_the_live_composed_candidate_and_journals_nothing(drafted):
    combat, table, mid, payload, chosen = drafted
    path = combat._load_session(mid).store.journal_path
    before = path.read_bytes()
    assert table.prepare_composition(mid, payload, chosen["candidate_id"], None) == {"status": "PREPARED"}
    assert path.read_bytes() == before, "preparation must not journal settings or an action"


def test_prepare_refuses_an_unknown_target_or_stale_draft_and_saves_nothing(drafted):
    combat, table, mid, payload, chosen = drafted
    path = combat._load_session(mid).store.journal_path
    before = path.read_bytes()
    with pytest.raises(TabletopError) as unknown:
        table.prepare_composition(mid, payload, "candidate:made-up", None)
    assert unknown.value.status_code == 422
    with pytest.raises(TabletopError):
        table.prepare_composition(mid, {**payload, "state_version": payload["state_version"] + 1},
                                  chosen["candidate_id"], None)
    assert path.read_bytes() == before


def test_http_prepare_with_composition_returns_prepared_and_saves_nothing(drafted, tmp_path, monkeypatch):
    from app.api import create_app
    from app.core import Settings
    from tests.h1_support import ROOT
    combat, _table, mid, payload, chosen = drafted
    monkeypatch.setattr(Draft202012Validator, "check_schema", classmethod(lambda cls, schema, format_checker=None: None))
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    path = combat._load_session(mid).store.journal_path
    before = path.read_bytes()
    body = {"candidate_id": chosen["candidate_id"], "decision_id": payload["decision_id"],
            "state_version": payload["state_version"], "after": 0, "composition": payload}
    with TestClient(app) as client:
        headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
        reply = client.post(f"/api/tabletop/matches/{mid}/prepare", json=body, headers=headers)
    assert reply.status_code == 200, reply.text
    assert reply.json() == {"status": "PREPARED"}
    assert path.read_bytes() == before, "the HTTP preparation must save nothing"
