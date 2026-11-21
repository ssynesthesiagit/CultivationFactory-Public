"""An anchored teleport's landings are generated from its anchor, not filtered out of every square in reach (AISTEPONCE1).

Blood River Passage lands only next to a creature bearing your Blood Thread. Its landing rule used to be a
candidate_allowed veto run after Gate4 built a row for every square in 60 feet, for each of its variants (125,179
offered rows on one DEPLOYPLAY1 turn of draw a16ada36ac). teleport_landing_cells now names the anchor's cells, so the
landing query, the AI menu and the canonical menu walk only those. The offered rows and the no-bearer refusal must
stay exactly what the veto produced.
"""
from combat.action_legality import query as availability
from combat.candidate_knowledge import query
from combat.ext import teleport_steps
from combat.typed_executor import teleport_reach
from tests.test_riders_c5 import _bleeder, _thread


def _passage(L1, engine):
    L1._ready(engine)
    return next(a for a in engine.action_catalog.values() if a.display_name == "Blood River Passage")


def _rows(engine, source, *, ai):
    if ai:
        with query(engine):
            menu = engine.legal_candidates()
    else:
        menu = engine.legal_candidates()
    variants = {}
    for c in menu:
        if c.source_definition_id == source and c.destination is not None:
            variants.setdefault(tuple(c.option_ids), []).append((c.destination.x, c.destination.y, c.destination.z))
    return variants


def test_blood_river_passage_generates_only_the_thread_bearers_adjacent_squares(monkeypatch):
    L1, engine, me, ally, foe = _bleeder(["rivers_run_red", "blood_river_passage"], cl=15)
    passage = _passage(L1, engine)
    reach = teleport_reach(engine, me, passage)

    assert teleport_steps.landings(engine, me, reach, action=passage) == []
    assert _rows(engine, passage.source_definition_id, ai=True) == {}
    assert _rows(engine, passage.source_definition_id, ai=False) == {}
    assert availability(engine, me.entity_id, passage.source_definition_id) == {
        "available": False, "code": "CANDIDATE_UNAVAILABILITY",
        "reason": "This action has no eligible choice under its current restrictions."}

    _thread(engine, me, foe)
    L1._ready(engine)
    with monkeypatch.context() as patch:  # every square the landing rules allow, ignoring the anchor
        patch.setattr(teleport_steps, "landing_cells", lambda *args: None, raising=False)
        unanchored = teleport_steps.landings(engine, me, reach, action=passage)
    adjacent = [(c.x, c.y, c.z) for c in unanchored
                if max(abs(c.x - foe.position.x), abs(c.y - foe.position.y)) <= 1]
    assert adjacent and len(adjacent) < len(unanchored)

    assert [(c.x, c.y, c.z) for c in teleport_steps.landings(engine, me, reach, action=passage)] == adjacent
    for ai in (True, False):
        variants = _rows(engine, passage.source_definition_id, ai=ai)
        assert variants, "the bearer's neighbours must be offered"
        for option_ids, cells in variants.items():
            assert sorted(cells) == sorted(adjacent), f"variant {option_ids} (ai={ai}) must offer exactly the adjacent squares"
