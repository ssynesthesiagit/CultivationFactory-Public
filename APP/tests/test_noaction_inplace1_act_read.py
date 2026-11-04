"""NOACTIONINPLACE1: a committed table action answers with the menu its client asked for (menu_read).

Service and HTTP level, on a synthetic persisted fight (no browser, no live model server).
"""

import httpx

from app.api import create_app
from app.core import Settings
from combat.table_text_pool import pack
from tests.async_support import run_asgi
from tests.h48_table_support import OWNER, fixture

READ = {"fog": True, "fog_view": "own", "fog_actor_ids": [OWNER], "compact": False}
COMPACT = {"fog": True, "fog_view": "own", "fog_actor_ids": [OWNER], "compact": True}


def _plain(value):
    """JSON-shape a snapshot the way the HTTP response will show it (tuples become lists)."""
    import json
    return json.loads(json.dumps(value, default=str))


def _end_turn_act(table, match_id, menu_read=None, defer_menu=False):
    """Commit the owner's End turn, answering any Ask me reaction with DECLINE (as the table fixture does)."""
    menu = table.state(match_id)["menu"]
    answers = []
    for _ in range(20):
        result = table.act(match_id, menu["end_turn"], menu["decision_id"], menu["state_version"], 0,
                           list(answers), menu_read=menu_read, defer_menu=defer_menu)
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    raise AssertionError("reaction loop")


def test_committed_act_returns_the_requested_fogged_menu(tmp_path):
    combat, table, match_id, _send, _commit = fixture(tmp_path, [], seed="NOACTINPLACE1-READ-SERVICE")
    result = _end_turn_act(table, match_id, menu_read=READ)
    assert result["status"] == "COMMITTED"
    menu = result["state"].get("menu")
    # The committed answer carries a fresh menu, built with the fog projection the client asked for.
    assert menu and menu.get("actor_id") and menu.get("decision_id")
    expected = table.state(match_id, fog=True, fog_view="own", fog_actor_ids=(OWNER,), include_menu=True)["menu"]
    assert _plain(menu) == _plain(expected)


def test_committed_act_without_menu_read_keeps_the_old_default(tmp_path):
    combat, table, match_id, _send, _commit = fixture(tmp_path, [], seed="NOACTINPLACE1-READ-DEFAULT")
    # /act without menu_read passes defer_menu=True: the answer says a fresh menu must be read.
    result = _end_turn_act(table, match_id, defer_menu=True)
    assert result["status"] == "COMMITTED"
    assert "menu_pending" in result["state"]


def test_http_act_with_compact_read_returns_the_packed_committed_menu(tmp_path):
    combat, table, match_id, _send, _commit = fixture(tmp_path, [], seed="NOACTINPLACE1-READ-HTTP")
    app = create_app(Settings.from_env(combat.source_root, tmp_path))
    menu = table.state(match_id)["menu"]
    body = {"candidate_id": menu["end_turn"], "decision_id": menu["decision_id"],
            "state_version": menu["state_version"], "after": 0, "menu_read": COMPACT}

    async def post():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
            token = (await client.get("/api/session")).json()["token"]
            return await client.post(f"/api/tabletop/matches/{match_id}/act",
                                     headers={"x-foundry-token": token}, json=body)

    response = run_asgi(post())
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "COMMITTED"
    # The HTTP answer is the service's committed menu, packed the way the compact state read packs it.
    expected = dict(pack(table.state(match_id, fog=True, fog_view="own", fog_actor_ids=(OWNER,),
                                     compact_moves=True, include_menu=True)))
    texts = expected.pop("table_texts", None)
    assert payload["state"]["menu"]["decision_id"] == expected["menu"]["decision_id"]
    assert _plain(payload["state"]) == _plain(expected)
    if texts:
        assert payload.get("table_texts") == texts
