"""Printed Punchline names in actual player menus and economy logs."""
import pytest

from combat.ext import reaction_economy
from tests.r1i_service_support import OWNER, FOE, SECOND, candidate, fixture, force_ai_candidate
from tests.test_r1i_round3 import reload, resolve
from tests.test_riders_c15 import _scripted_d20

J = "tianxia.talent.jester."


@pytest.mark.parametrize("kind,name", [("a_fine_display", "A Fine Display"), ("banquet_escape", "Banquet Escape")])
@pytest.mark.parametrize("auto_turn", [False, True])
def test_free_punchline_uses_printed_name_after_table_reload(tmp_path, monkeypatch, kind, name, auto_turn):
    _scripted_d20(monkeypatch, lambda actor, reason: 19 if actor == FOE and reason.startswith("ATTACK") else None)
    combat, table, mid, send, commit = fixture(tmp_path, [J + kind, J + "court_of_words_without_offense"],
        owner_ac=1, foe_talents=["TAL_IRON_FIST_IRON_FIST_TRAINING"],
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 8, "y": 6}})
    commit(candidate(table, mid, "Court of Words Without Offense"))
    commit(candidate(table, mid, "Set the Scene (free): Strike the Fool", FOE))
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Unarmed Strike (Iron Fist)", OWNER)
    if auto_turn:
        force_ai_candidate(combat, mid, FOE, cid)
    before = len(reload(tmp_path, mid).events)
    pick = "fine_display" if kind == "a_fine_display" else kind
    _, prompts = resolve(combat, mid, send, cid, {"choice:needle.strike_the_fool": pick}, auto=auto_turn)
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.strike_the_fool")
    assert any(o["label"].startswith(name + ":") for o in prompt["choice"]["options"])
    engine = reload(tmp_path, mid)
    events = engine.events[before:]
    windows = [e for e in events if e.event_type == "REACTION_WINDOW_OPENED" and e.payload.get("checkpoint") == "JESTER_PUNCHLINE"]
    assert len(windows) == 1 and windows[0].source_definition_id == J + pick
    logs = [str(e.payload.get("log") or "") for e in events]
    assert any(f"Owner uses {name} without spending its Reaction (once this round)." in line for line in logs)
    assert not any("uses fine_display" in line or "uses a_fine_display" in line or "uses banquet_escape" in line for line in logs)
    owner = engine.state.actors[OWNER]
    assert owner.reaction_available
    assert owner.turn_flags[reaction_economy.FLAG + J + "court_of_words_without_offense"] == engine.state.round_number
