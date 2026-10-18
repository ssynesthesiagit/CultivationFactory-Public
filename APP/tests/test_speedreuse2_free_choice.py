"""SPEEDREUSE2 / FD-6 option B, server side: a free choice asks /act for its committed state as the table reads it.

The answer must be exactly what the table's next state read returns, so the browser can keep its action bar and skip
that read (static/tabletop/tabletop.js act/keepActionBar). Synthetic fight (tests/hunt36_support.py), in-process HTTP.
"""
import json
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Settings
from tests.hunt36_support import LEFT, ROOT, fight, turn
from tests.test_sol157_presets import NULL

READ = {"fog": True, "fog_view": "own", "fog_actor_ids": [LEFT], "compact": True}


def _expand(data):
    """Python twin of static/tabletop/table-text-pool.js expandTableTexts (applied to every API answer)."""
    texts = data.get("table_texts") if isinstance(data, dict) else None
    if not isinstance(texts, list):
        return data

    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, dict):
            if len(value) == 1 and isinstance(value.get("$table_text"), int) and 0 <= value["$table_text"] < len(texts):
                return texts[value["$table_text"]]
            return {key: expand(item) for key, item in value.items()}
        return value
    return expand({key: value for key, value in data.items() if key != "table_texts"})


def _difference(a, b, where="state"):
    """The first place two JSON values differ, for a readable failure."""
    if type(a) is not type(b):
        return f"{where}: {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        for key in dict.fromkeys([*a, *b]):
            if key not in a or key not in b:
                return f"{where}.{key}: only in {'answer' if key in a else 'read'}"
            found = _difference(a[key], b[key], f"{where}.{key}")
            if found:
                return found
        return list(a) != list(b) and f"{where}: key order differs" or None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{where}: {len(a)} != {len(b)} items"
        return next((found for i, (x, y) in enumerate(zip(a, b)) if (found := _difference(x, y, f"{where}[{i}]"))), None)
    return None if a == b else f"{where}: {str(a)[:200]!r} != {str(b)[:200]!r}"


def _free_choice(state):
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g.get("shape"))
    return {"candidate_id": group["options"][0]["candidate_id"], "decision_id": menu["decision_id"],
            "state_version": menu["state_version"], "after": state["last_sequence"]}


def test_free_choice_commit_answers_with_exactly_the_next_state_read(tmp_path):
    combat, table, mid = fight(tmp_path, [NULL], seed="SPEEDREUSE2-ACT", primary="Stamina", cl=5)
    turn(combat, table, mid)
    with TestClient(create_app(Settings.from_env(ROOT, tmp_path))) as client:
        headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
        query = urlencode({"fog": "true", "fog_view": "own", "fog_actor_ids": LEFT, "compact": "true"})
        read = lambda: _expand(client.get(f"/api/tabletop/matches/{mid}/state?{query}").json())  # noqa: E731
        before = read()
        response = client.post(f"/api/tabletop/matches/{mid}/act", headers=headers,
                               json={**_free_choice(before), "menu_read": READ})
        assert response.status_code == 200, response.text
        answer = _expand(response.json())
        assert answer["status"] == "COMMITTED"
        state = answer["state"]
        assert state["menu"]["manual"] and state["menu"]["state_version"] > before["menu"]["state_version"]
        assert "menu_pending" not in state
        following = read()  # what the browser's next poll sees
        assert json.dumps(state) == json.dumps(following), _difference(state, following)
        # Without menu_read the acknowledgement is as before: no menu, the version to read next.
        plain = client.post(f"/api/tabletop/matches/{mid}/act", headers=headers, json=_free_choice(read())).json()
        assert plain["status"] == "COMMITTED" and plain["state"]["menu"] is None and plain["state"]["menu_pending"]
        # The request shape is checked like every table request.
        rejected = client.post(f"/api/tabletop/matches/{mid}/act", headers=headers,
                               json={**_free_choice(read()), "menu_read": {**READ, "extra": 1}})
        assert rejected.status_code == 422
