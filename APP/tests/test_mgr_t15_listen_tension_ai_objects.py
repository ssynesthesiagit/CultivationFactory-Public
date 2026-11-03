"""Native automatic access to physical object connections and Listen.

Runtime inputs: authority/typed_mechanics/rules_text.json,
authority/Tianxia_Typed_Mechanics_Authority_R1.json,
authority/Tianxia_Forged_Technique_Authority_R1.json,
authority/Tianxia_Immortal_Art_Authority_R1.json,
catalog_authority/cat3/generated/catalog_authority.v1.json,
authority/typed_mechanics/reviewed_final.d/review_sw-thread.json,
authority/Tianxia_Sphere_Path_Access_R1.json,
catalog_authority/cat1/data/prerequisite_projection.v1.json.
"""
import pytest

from combat.ext.thread_common import maintained_lines
from tests.test_mgr_t15_listen_tension import (
    P, S, QI, fight, cold, candidate, grants, private,
)
from tests.test_r4_integration import auto_candidate


@pytest.mark.parametrize("qi", [False, True], ids=["mundane", "qi"])
def test_auto_can_commit_object_connection_then_private_listen(tmp_path, qi):
    combat, table, mid = fight(tmp_path, objects=[
        {"id": 1, "kind": "custom", "name": "Bell", "x": 7 if qi else 5, "y": 5,
         "blocks": False, "ac": 10, "hp": 30},
    ])
    name = "Draw the Line: Guide" + (" (Qi Thread)" if qi else "") + " (at an object)"
    cid = candidate(table, mid, name, "object:map.1")
    session = combat._load_session(mid)
    before = session.engine.state.actors[P].resources[QI]
    hp = session.engine.state.objects["object:map.1"].current_hp
    source = next(c.source_definition_id for c in session.engine.legal_candidates()
                  if c.candidate_id == cid)
    # Compare the entire legal object-connection set, not a ranked top-N. Both
    # normal suggestions/model seats and Local Auto's guarded context must keep it.
    expected = {c.candidate_id for c in session.engine.legal_candidates()
                if c.source_definition_id.endswith(".connected_object")}
    assert cid in expected
    auto_candidate(combat, mid, P, cid)  # deterministic fake; never a live model
    session = combat._load_session(mid)
    for guarded in (False, True):
        context = combat.ai_decision_context(session, progress_guard=guarded)
        assert expected <= {c.candidate_id for c in context.legal_candidates}
    assert table.auto_step(mid, 0)["status"] == "COMMITTED"
    engine = cold(tmp_path, mid)  # fresh service plus full mechanical replay
    owner = engine.state.actors[P]
    rows = maintained_lines(engine, owner)
    assert len(rows) == 1 and rows[0][1].object_id == "object:map.1"
    assert rows[0][3].data["thread_medium"] == ("qi" if qi else "mundane")
    assert owner.resources[QI] == before - int(qi)
    assert not owner.action_available
    assert engine.state.objects["object:map.1"].current_hp == hp
    assert any(ev.event_type == "ATTACK_ROLLED" and ev.actor_id == P
               and ev.target_ids == ("object:map.1",)
               and ev.source_definition_id == source for ev in engine.events)

    # Automatic seats intentionally have no manual table action menu. Select
    # the follow-up from their actual observed context, not that player-only UI.
    context = combat.ai_decision_context(combat._load_session(mid))
    listen_id = next(c.candidate_id for c in context.legal_candidates
                     if c.display_name == "Listen Through Tension")
    auto_candidate(combat, mid, P, listen_id)
    assert table.auto_step(mid, 0)["status"] == "COMMITTED"
    engine = cold(tmp_path, mid)
    assert len(grants(engine)) == 1
    assert grants(engine)[0].data["line_id"] == rows[0][0]
    assert grants(engine)[0].data["benefit"] == "motion"
    assert not engine.state.actors[P].bonus_action_available
    assert engine.state.actors[P].resources[QI] == before - int(qi)
    assert private(table, mid)[0]["motion"] == "still"
    assert private(table, mid)[0]["text"] == "Bell is staying still."
    assert private(table, mid, S) == []
