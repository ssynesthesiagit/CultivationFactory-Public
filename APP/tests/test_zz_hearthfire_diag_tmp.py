"""TEMP diagnostic (not committed): why is there no 'Search by sight' candidate?"""
import json
from pathlib import Path

OUT = Path("/var/tmp/auto-audit/hearthfire-diag/diag.out")

from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_mgr_t14_hearthfire_native import acquired_document
from tests.test_mgr_t14_hearthfire_light import scene


def _report(combat, mid, tag, lines):
    from combat.stealth import can_search, hidden, foes
    e = combat._load_session(mid).engine
    actor = e.state.actors[e.state.current_actor_id]
    cat = {k: v.display_name for k, v in e.action_catalog.items() if "search" in (v.display_name or "").lower()}
    names = sorted({getattr(e.action_catalog.get(c.source_definition_id), "display_name", None)
                    for c in e.legal_candidates()})
    oaids = [aid for aid in e.state.actors[OWNER].action_ids
             if e.action_catalog.get(aid) and "search" in (e.action_catalog[aid].display_name or "").lower()]
    lines.append(f"--- {tag} ---")
    lines.append(f"current_actor={e.state.current_actor_id}")
    lines.append(f"owner.active={e.state.actors[OWNER].active} actor.active={actor.active}")
    lines.append(f"foe.hidden={bool(hidden(e.state.actors[FOE]))} foe.active={e.state.actors[FOE].active}")
    lines.append(f"foes(owner)={[f.entity_id for f in foes(e, e.state.actors[OWNER])]}")
    lines.append(f"can_search(owner)={can_search(e, e.state.actors[OWNER])}")
    lines.append(f"can_search(current)={can_search(e, actor)}")
    lines.append(f"catalog_search={cat}")
    lines.append(f"owner.action_ids_search={oaids}")
    lines.append(f"candidate_names={[n for n in names if n]}")
    lines.append(f"ambient_illumination={(e.battlefield_document or {}).get('ambient_illumination')}")
    lines.append("")


def test_diag(tmp_path):
    from combat.factory_compiler import compile_character
    lines = []
    arena = scene(tmp_path, level="DIM", walls=[{"shape": "rect", "points": [[7, 5], [8, 8]], "filled": True, "blocks": "sight_and_movement"}])
    foe = sheet([], cl=18, score=20)
    foe["identity"]["proficiency_bonus"] = 6
    foe["ability_scores_and_statistics"]["skills"] = [{"skill": "Stealth", "bonus": 17, "proficiency": "expertise"}]
    document = acquired_document(tmp_path, 18)
    next(a for a in document["ability_scores_and_statistics"]["abilities"] if a["ability"] == "WIS").update(score=1, modifier=-5)
    owner = compile_character(document, actor_id=OWNER, reaction_plan={"ask": True})
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=owner,
                                 owner_pb=6, foe_sheet=foe, battlefield=arena, foe_position={"x": 10, "y": 6}, seed="HEARTH-DIM-SEARCH")
    _report(combat, mid, "after fixture", lines)
    try:
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, "Hide").candidate_id)
        _report(combat, mid, "after Hide", lines)
        turn(table, mid, OWNER)
        settle(table, mid, candidate(combat, mid, "Kindled Hearth", at=(5, 6)).candidate_id,
               choices={"choice:needle.kindled_hearth_recipients": [OWNER, ALLY]})
        _report(combat, mid, "after Kindled Hearth", lines)
        e = reload(tmp_path, mid)
        moves = [c for c in e.legal_candidates() if c.kind.value == "MOVE" and c.destination
                 and (c.destination.x, c.destination.y, c.destination.z) == (6, 4, 0) and all(p.z == 0 for p in c.canonical_path)]
        lines.append(f"moves_to_6_4={len(moves)}")
        settle(table, mid, moves[0].candidate_id)
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
        turn(table, mid, OWNER)
        _report(combat, mid, "after move (6,4)", lines)
        e = reload(tmp_path, mid)
        move = next(c for c in e.legal_candidates() if c.kind.value == "MOVE" and c.destination and (c.destination.x, c.destination.y, c.destination.z) == (9, 4, 0) and all(p.z == 0 for p in c.canonical_path))
        settle(table, mid, move.candidate_id)
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
        turn(table, mid, OWNER)
        _report(combat, mid, "after move (9,4)", lines)
    except Exception as exc:  # noqa
        import traceback
        lines.append("EXCEPTION: " + repr(exc))
        lines.append(traceback.format_exc())
    OUT.write_text("\n".join(lines))
    print("\n".join(lines))
