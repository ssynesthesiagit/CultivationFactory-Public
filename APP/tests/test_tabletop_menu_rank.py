"""TabletopService._rank_menu (EMBEDMENU, owner 2026-10-13): the quick-bar
ranking seam in combat/tabletop_service.py, exercised directly against the
real method with a lightweight stand-in engine/actor -- this is the actual
service-level integration point (see combat/menu_rank.py for the pure logic).
Presentation only: candidate ids and counts must survive untouched.
"""
from types import SimpleNamespace

from combat import embedding_rank as er
from combat import menu_rank
from combat.tabletop_service import TabletopService


def _actor(current_hp=20, maximum_hp=20):
    return SimpleNamespace(current_hp=current_hp, maximum_hp=maximum_hp)


def _engine(actor_id="p1", **actors):
    return SimpleNamespace(state=SimpleNamespace(actors={actor_id: _actor(), **actors}))


def _menu():
    return {
        "manual": True, "actor_id": "p1",
        "moves": [
            {"candidate_id": "m-hazard-1", "destination": {"x": 1, "y": 1}, "hazard_exposure": True},
            {"candidate_id": "m-safe", "destination": {"x": 2, "y": 1}, "hazard_exposure": False},
            {"candidate_id": "m-hazard-2", "destination": {"x": 3, "y": 1}, "hazard_exposure": True},
        ],
        "actions": [
            {"source_definition_id": "ability:brace", "label": "Brace", "options": [
                {"candidate_id": "a-brace", "target_ids": [], "target_names": [], "expected_damage": 0, "label": None},
            ]},
            {"source_definition_id": "ability:strike", "label": "Strike", "options": [
                {"candidate_id": "a-miss-no-target", "target_ids": [], "target_names": [], "expected_damage": 0, "label": "stance"},
                {"candidate_id": "a-hit-foe", "target_ids": ["foe"], "target_names": ["a visible foe"], "expected_damage": 8, "label": "strike a visible foe"},
            ]},
        ],
    }


def _down_client():
    # No real network in a unit test: an unreachable endpoint exercises the
    # documented graceful fallback (tier-only, ties keep source order).
    return er.EmbeddingClient(transport=lambda *a: (_ for _ in ()).throw(OSError("offline")))


def test_rank_menu_prefers_the_safe_move_and_keeps_every_candidate(monkeypatch):
    monkeypatch.setattr(menu_rank, "_CLIENT", _down_client())
    menu = _menu()
    before_candidates = {m["candidate_id"] for m in menu["moves"]}
    TabletopService._rank_menu(menu, _engine(foe=_actor(5, 20)), known={"p1", "foe"})
    assert [m["candidate_id"] for m in menu["moves"]] == ["m-safe", "m-hazard-1", "m-hazard-2"]
    assert {m["candidate_id"] for m in menu["moves"]} == before_candidates
    assert menu["moves_shown"] == 3


def test_rank_menu_ranks_the_hostile_hitting_option_first_in_its_group(monkeypatch):
    monkeypatch.setattr(menu_rank, "_CLIENT", _down_client())
    menu = _menu()
    strike = next(g for g in menu["actions"] if g["label"] == "Strike")
    before_candidates = {o["candidate_id"] for o in strike["options"]}
    TabletopService._rank_menu(menu, _engine(foe=_actor(5, 20)), known={"p1", "foe"})
    strike = next(g for g in menu["actions"] if g["label"] == "Strike")
    assert strike["options"][0]["candidate_id"] == "a-hit-foe"
    assert {o["candidate_id"] for o in strike["options"]} == before_candidates
    assert strike["options_shown"] == 2
    brace = next(g for g in menu["actions"] if g["label"] == "Brace")
    assert brace["options_shown"] == 1  # a single option is never reordered or hidden


def test_rank_menu_caps_options_shown_at_the_quick_bar_size_but_keeps_the_rest(monkeypatch):
    monkeypatch.setattr(menu_rank, "_CLIENT", _down_client())
    menu = _menu()
    many = [{"candidate_id": f"a-{i}", "target_ids": ["foe"], "target_names": ["a visible foe"],
             "expected_damage": 0, "label": f"mode {i}"} for i in range(8)]
    menu["actions"].append({"source_definition_id": "ability:many", "label": "Many Modes", "options": many})
    TabletopService._rank_menu(menu, _engine(foe=_actor(5, 20)), known={"p1", "foe"})
    group = next(g for g in menu["actions"] if g["label"] == "Many Modes")
    assert len(group["options"]) == 8  # nothing becomes unreachable
    assert group["options_shown"] == menu_rank.QUICK_BAR_SIZE


def test_rank_menu_is_a_no_op_for_an_automatic_or_missing_menu():
    TabletopService._rank_menu(None, _engine())
    automatic = {"manual": False, "actor_id": "p1", "moves": [], "actions": []}
    TabletopService._rank_menu(automatic, _engine())
    assert "moves_shown" not in automatic


def test_assisted_top_five_are_across_abilities_per_slot_and_hidden_targets_never_embed(monkeypatch):
    from tests.test_menu_rank import _fake_transport, _seeded_vector
    calls = []
    def transport(*args):
        calls.append(args[1].decode())
        return _fake_transport(_seeded_vector)(*args)
    monkeypatch.setattr(menu_rank, "_CLIENT", er.EmbeddingClient(transport=transport))
    menu = _menu()
    menu["control_mode"] = "SUGGESTED"
    for i in range(9):
        menu["actions"].append({"label": f"Ability {i}", "economy": "ACTION", "options": [
            {"candidate_id": f"ability-{i}", "target_ids": [], "label": "self"}]})
    menu["actions"].append({"label": "Heal", "economy": "BONUS_ACTION", "options": [
        {"candidate_id": "heal", "target_ids": [], "label": "yourself"}]})
    menu["actions"].append({"label": "Strike", "economy": "ACTION", "options": [
        {"candidate_id": "hidden-hit", "target_ids": ["secret"], "target_names": ["Secret Dragon"], "label": "Secret Dragon"}]})
    TabletopService._rank_menu(menu, _engine(secret=SimpleNamespace(display_name="Secret Dragon")), known={"p1", "foe"})
    assert menu["turn_mode"] == "Assisted"
    assert len(menu["ranked_slots"]["Action"]) == 5
    assert menu["ranked_slots"]["Bonus action"] == ["heal"]
    assert len(calls) == 1 and "Secret Dragon" not in calls[0] and "hidden-hit" not in calls[0]
    assert "hidden-hit" not in menu["ranked_slots"]["Action"]
    assert any(o["candidate_id"] == "hidden-hit" for g in menu["actions"] for o in g["options"])


def test_flag_off_leaves_menu_identical(monkeypatch):
    import copy
    monkeypatch.setenv("CF_EMBED_MENU", "0")
    menu = _menu()
    before = copy.deepcopy(menu)
    TabletopService._rank_menu(menu, _engine())
    assert menu == before


def test_assisted_real_table_commit_reload_preserves_mode_and_menu(tmp_path, monkeypatch):
    import time
    from pathlib import Path
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from tests.test_factory_live_match import _install
    monkeypatch.setattr(menu_rank, "_CLIENT", _down_client())
    root = Path(__file__).resolve().parents[1]
    left, right = "a0000000-0000-4000-8000-000000000001", "a0000000-0000-4000-8000-000000000002"
    for project in (left, right):
        _install(tmp_path, project)
    combat = CombatService(root, tmp_path)
    table = TabletopService(combat, tmp_path)
    match = combat.create_factory_match(project_ids=[left], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + right],
        control_modes={FACTORY_ACTOR_PREFIX + left: "SUGGESTED", FACTORY_ACTOR_PREFIX + right: "SUGGESTED"},
        match_seed="EMBEDMENUS-ASSISTED")
    start = time.perf_counter()
    state = table.state(match["match_id"])
    cold_ms = (time.perf_counter() - start) * 1000
    menu = state["menu"]
    assert menu["manual"] and menu["turn_mode"] == "Assisted"
    assert all(len(keys) <= 5 for keys in menu["ranked_slots"].values())
    before_count = len(menu["moves"]) + sum(len(g["options"]) for g in menu["actions"])
    shown_count = sum(map(len, menu["ranked_slots"].values()))
    assert shown_count <= 15
    from tests.test_agent_seats import runner_for
    from agent_seats.menu_pages import slot_candidate_keys
    runner, _ = runner_for(tmp_path, table)
    session = combat._load_session(match["match_id"])
    view, known = runner.own_view(match["match_id"], state, menu["actor_id"], session)
    options = runner._menu(state, known)
    ranked = []
    # Model seats consume these exact lists; the ranking client is not called
    # a second time for a different query, and the native pick stays intact.
    with monkeypatch.context() as scoped:
        calls = []
        scoped.setattr(menu_rank, "rank_ids", lambda *a, **kw: calls.append(a) or [])
        builtin, _ = runner._builtin(match["match_id"], session, known, options,
            view["visible_cells"], ranked, ranked_slots=menu["ranked_slots"])
        assert calls == []
    assert ranked == list(dict.fromkeys([builtin, *slot_candidate_keys(menu["ranked_slots"], options, builtin)]))
    start = time.perf_counter()
    assert table.state(match["match_id"])["menu"]["ranked_slots"] == menu["ranked_slots"]
    warm_ms = (time.perf_counter() - start) * 1000
    # A real table commit, followed by a new service and disk reload. The
    # existing controller mode persists; rankings remain read-only metadata.
    result = table.act(match["match_id"], menu["end_turn"], menu["decision_id"],
                       menu["state_version"], state["last_sequence"])
    reloaded = TabletopService(CombatService(root, tmp_path), tmp_path).state(match["match_id"])
    assert reloaded["last_sequence"] == result["state"]["last_sequence"]
    assert reloaded["menu"]["turn_mode"] == "Assisted"
    print(f"EMBEDMENUS offline real-table: offered={before_count} shown={shown_count} cold={cold_ms:.3f}ms warm={warm_ms:.3f}ms fake-embedder")
    import json
    (tmp_path / "EMBEDMENUS-measurements.json").write_text(json.dumps({
        "offered": before_count, "shown": shown_count, "cold_table_ms": round(cold_ms, 3),
        "warm_table_ms": round(warm_ms, 3), "embedder": "fake offline failure"}) + "\n")
