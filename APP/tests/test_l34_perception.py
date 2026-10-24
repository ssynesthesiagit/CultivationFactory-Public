"""L34 perception regressions through committed tabletop actions and reloads."""
import json
import zipfile

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

OWNER = FACTORY_ACTOR_PREFIX + "owner"
FOE = FACTORY_ACTOR_PREFIX + "foe"


def _fight(tmp_path, *, owner_talents, foe_talents, positions, seed):
    for name, talents in (("owner", owner_talents), ("foe", foe_talents)):
        document = sheet(talents, cl=17, score=30 if name == "foe" else 8)
        document["identity"]["display_name"] = name.title()
        document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        document["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
        folder = tmp_path / "portable_characters" / name
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    arena = combat.tabletop_maps.save({"display_name": "L34 Perception", "width_squares": 40, "height_squares": 20,
        "walls": [], "starts": {"team1": [[positions[OWNER]["x"], positions[OWNER]["y"]]],
                                  "team2": [[positions[FOE]["x"], positions[FOE]["y"]]]}})
    view = combat.create_factory_match(project_ids=["owner"], opponent_actor_ids=[FOE],
        control_modes={OWNER: "MANUAL", FOE: "MANUAL"}, arena_id="battlefield:map." + arena["map_id"],
        match_seed=seed)
    return combat, TabletopService(combat, tmp_path), view["match_id"]


def _act(table, match_id, label, at=None):
    answers = []
    for _ in range(16):
        state = table.state(match_id)
        menu = state["menu"]
        group = next((g for g in menu["actions"] if g["label"] == label or g["label"].startswith(label + ":")), None)
        option = None if label == "<end>" else next(option for option in group["options"]
            if at is None or option.get("destination") == {"x": at[0], "y": at[1]})
        candidate_id = menu["end_turn"] if label == "<end>" else option["candidate_id"]
        result = table.act(match_id, candidate_id, menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "DECLINE"}
        if prompt.get("choice"):
            answer.update(selection="USE", option_ids=(prompt["choice"].get("preferred")
                          or [prompt["choice"]["options"][0]["id"]])[:1])
        answers.append(answer)
    raise AssertionError(f"action did not commit: {label}")


def _turn(table, match_id, actor_id):
    for _ in range(8):
        if table.state(match_id)["menu"]["actor_id"] == actor_id:
            return
        _act(table, match_id, "<end>")
    raise AssertionError(f"missing turn for {actor_id}")


def _reloaded(combat, table, match_id):
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(match_id)
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
    assert TabletopService(CombatService(ROOT, combat.userdata_root), combat.userdata_root).state(match_id)
    return loaded


def test_truesight_cannot_see_or_search_through_volcanic_smoke_after_reload(tmp_path):
    combat, table, mid = _fight(tmp_path,
        owner_talents=["tianxia.path.qi_cultivation.feature.nine_heavens_gaze"],
        foe_talents=["TAL_MAGMA_VOLCANIC_SMOKE"],
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 10, "y": 6}}, seed="L34-SMOKE")
    _turn(table, mid, FOE)
    _act(table, mid, "Volcanic Smoke", at=(10, 6))
    _turn(table, mid, OWNER)
    _act(table, mid, "Nine Heavens Gaze")
    loaded = _reloaded(combat, table, mid)
    engine = loaded.engine
    from combat import zones
    assert zones.typed_zones(engine), engine.state.model_dump(mode="json")["zones"]
    assert not engine_can_see(engine, OWNER, FOE), [(zone.trigger_profile, zone.affected_cells) for zone in zones.typed_zones(engine)]
    _turn(table, mid, FOE)
    assert any(group["label"] == "Hide" for group in table.state(mid)["menu"]["actions"])
    _act(table, mid, "Hide")
    assert any(c.condition_id == "condition:typed.hidden"
               for c in combat._load_session(mid).engine.state.actors[FOE].conditions.values())
    _turn(table, mid, OWNER)
    _act(table, mid, "Search")
    loaded = _reloaded(combat, table, mid)
    checks = [event for event in loaded.engine.events if event.event_type == "CHECK_ROLLED"
              and event.actor_id == OWNER and FOE in event.target_ids]
    assert checks and all("by_sense" not in event.payload for event in checks)


def engine_can_see(engine, viewer_id, target_id):
    from combat.target_knowledge import can_see
    return can_see(engine, engine.state.actors[viewer_id], engine.state.actors[target_id])


def test_blinded_enemy_does_not_block_hide_after_committed_blinding_flash(tmp_path):
    combat, table, mid = _fight(tmp_path, owner_talents=["RADIANCE_TAL_BLINDING_FLASH"], foe_talents=[],
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}, seed="L34-BLIND")
    _turn(table, mid, OWNER)
    _act(table, mid, "Blinding Flash")
    _act(table, mid, "<end>")
    _turn(table, mid, OWNER)
    engine = combat._load_session(mid).engine
    assert any(c.condition_id == "condition:typed.blinded"
               for c in engine.state.actors[FOE].conditions.values())
    assert any(group["label"] == "Hide" for group in table.state(mid)["menu"]["actions"])
    _act(table, mid, "Hide")
    loaded = _reloaded(combat, table, mid)
    assert any(event.event_type == "CHECK_ROLLED" and event.actor_id == OWNER
               and event.payload.get("check") == "Stealth" for event in loaded.engine.events)
