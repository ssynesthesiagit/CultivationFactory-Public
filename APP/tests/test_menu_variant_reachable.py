"""Every issued legal candidate survives rider decoration and seat pagination.

Synthetic owner sheets only; embedding transport is offline, never a live model.
"""
from collections import Counter

import pytest

from agent_seats.menu_pages import RankedPages
from agent_seats.runner import SeatRunner
from combat import embedding_rank, menu_rank
from combat.ext.attack_modifiers import variant_replaced
from combat.placement_menu import query as placement_query
from tests.hunt36_support import LEFT, RIGHT, fight, turn, send


@pytest.mark.parametrize("mode", ["MANUAL", "SUGGESTED"])
@pytest.mark.parametrize("owned", [
    ["WATER_BASE_WATER_LASH", "TAL_WATER_PULL_OF_THE_RIVER"],
    ["tianxia.path.body_refining.feature.iron_fist", "TAL_VOID_NULLIFYING_STRIKE"],
])
def test_all_legal_candidates_reachable_in_table_and_seat_pages(tmp_path, monkeypatch, mode, owned):
    def offline(*args, **kwargs):
        raise OSError("test transport: offline")
    monkeypatch.setattr(menu_rank, "_CLIENT", embedding_rank.EmbeddingClient(transport=offline))
    combat, table, mid = fight(tmp_path, owned, primary="Stamina", cl=5,
                               seed="MENUVARIANT", positions={
                                   LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 6, "y": 6}})
    turn(combat, table, mid)
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode=mode)
    # Exact paid variants are reachable when their owning rider is enabled.
    # A disabled rider must not silently reappear through a paid variant.
    engine = combat._load_session(mid).engine
    toggles = [a.source_definition_id for a in engine.action_catalog.values()
               if a.owner_id == LEFT and (a.parameters.get("attack_modifier_setting") or {}).get("field") == "on"]
    assert toggles
    for source in toggles:
        engine = combat._load_session(mid).engine
        send(combat, table, mid, next(c.candidate_id for c in engine.legal_candidates()
                                    if c.source_definition_id == source))
    engine = combat._load_session(mid).engine
    native_sources = {c.source_definition_id for c in engine.legal_candidates()}
    # Table menus issue lazy square pickers; compare the same complete query
    # representation, not eagerly expanded square candidate identities.
    with placement_query():
        candidates = engine.legal_candidates()
    assert {c.source_definition_id for c in candidates} == native_sources
    expected = {c.candidate_id for c in candidates}
    variants = {c.candidate_id for c in candidates if variant_replaced(
        engine.action_catalog.get(c.source_definition_id), engine.action_catalog.values())}
    assert variants, "fixture must exercise the formerly removed candidates"

    state = table.state(mid)
    menu = state["menu"]
    # These are the rows used by the human quick bar and all-choices pages.
    issued = [o["candidate_id"] for g in menu["actions"] for o in g["options"]]
    issued += [o["candidate_id"] for o in menu["moves"]]
    issued += [menu["end_turn"]]
    assert set(issued) == expected
    assert all(count == 1 for count in Counter(issued).values())
    # On-hit settings remain available, but they are separate free decisions:
    # their selectors cannot stand in for an exact target/move+attack candidate.
    modifiers = [m for e in state["shapes"][LEFT] for m in e.get("modifiers", [])]
    assert modifiers
    selector_ids = {o["candidate_id"] for m in modifiers for s in m["selectors"] for o in s["options"]}
    assert variants.isdisjoint(selector_ids)

    seat = SeatRunner._menu(None, state, {LEFT, RIGHT})
    assert {row["candidate_id"] for row in seat.values()} == expected
    legal = {key: {**row["description"], "candidate_id": row["candidate_id"]}
             for key, row in seat.items()}
    by_id = {row["candidate_id"]: key for key, row in legal.items()}
    ranked = [by_id[cid] for ids in menu["ranked_slots"].values() for cid in ids]
    pages = RankedPages(legal, ranked, ranked[0], cap=5)
    reached = set()
    for _ in range(len(legal) + 1):
        offered = pages.menu()
        reached.update(row["candidate_id"] for row in offered.values())
        if not pages.has_more(offered):
            break
        pages.advance(offered)
    else:
        pytest.fail("seat pagination did not finish")
    assert reached == expected
