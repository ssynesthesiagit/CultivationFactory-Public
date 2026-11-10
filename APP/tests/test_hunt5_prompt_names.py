"""Instance-qualified Shield choices through the hunt5 portable-sheet service fixture."""

from tests.test_hunt5_player_choices import fixture, PLAYER


def test_flexible_cover_choice_name_preview_answer_reload_replay(tmp_path):
    combat, table, mid, _, act = fixture(tmp_path, "TAL_SHIELD_FLEXIBLE_COVER")
    assert act(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    menu = table.state(mid)["menu"]
    assert menu["actor_id"] == PLAYER
    group = next(g for g in menu["actions"] if g["label"] == "FLEXIBLE COVER")
    cid = group["options"][0]["candidate_id"]
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = act(cid)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"].startswith("choice:shield.edge:")
    assert prompt["context"]["reaction_source_id"].endswith(PLAYER)
    assert prompt["reaction"] == "Flexible Cover"
    assert {o["label"] for o in prompt["choice"]["options"]} == {"North edge", "South edge", "East edge", "West edge"}
    assert act(cid)["reaction"] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["N"]}
    assert act(cid, [answer])["status"] == "COMMITTED"
    from combat.gate5_service import CombatService
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    from combat.ext.shield_faces import FACE
    faces = [c for c in loaded.engine.state.actors[PLAYER].conditions.values() if c.condition_id == FACE]
    assert len(faces) == 1 and faces[0].data["edge"] == "N"
    assert loaded.mechanical.replay()["status"] == "PASS"
