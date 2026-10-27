"""Persisted-table regressions for hunt 47 summon behavior (commit, reload, verify and replay)."""

import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

OWNER, FOE, SECOND = [FACTORY_ACTOR_PREFIX + "h47-" + name for name in ("owner", "foe", "second")]
BONE = "tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation"
SPIRIT = "tianxia.talent.talismans.talisman_spirit"
LAVA = "TAL_MAGMA_LAVA_FLOW"
FATE = "TAL_FATE_REWRITE_THE_DISASTER"


def table_fixture(tmp_path, *, wide=False, saves=None, foe_talents=(), owner_talents=(BONE,),
                  second_talents=(), allied_second=False, foe_kit=None):
    ids = [OWNER, FOE, SECOND]
    docs = [sheet(owner_talents, cl=17, primary="Qi" if SPIRIT in owner_talents else "Stamina"),
            sheet(foe_talents, cl=17, dc=50, kit=foe_kit, score=50 if foe_kit else 14),
            sheet(second_talents, cl=17)]
    for actor_id, doc in zip(ids, docs):
        doc["identity"]["display_name"] = actor_id.rsplit("-", 1)[-1].title()
        doc["identity"]["proficiency_bonus"] = 4
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
        if actor_id == OWNER and saves is not None:
            doc["ability_scores_and_statistics"]["saving_throws"] = saves
        folder = tmp_path / "portable_characters" / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    bundles = [compile_character(doc, actor_id=actor_id,
               reaction_plan={"ask": True} if actor_id == OWNER or
               (actor_id == SECOND and second_talents) or (actor_id == FOE and foe_kit) else None)
               for actor_id, doc in zip(ids, docs)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena_id = "battlefield:factory_pillar_arena"
    if wide:
        arena = combat.tabletop_maps.save({"display_name": "H47 follow test", "width_squares": 40,
                                           "height_squares": 20, "walls": [],
                                           "starts": {"team1": [[3, 6]], "team2": [[4, 6], [5, 6]]}})
        arena_id = "battlefield:map." + arena["map_id"]
    mid = combat._finish_factory_match(
        bundles, ids, {actor_id: "team:a" if actor_id == OWNER or (allied_second and actor_id == SECOND)
                      else "team:b" for actor_id in ids},
        {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 5, "y": 6}},
        combat.factory_arenas(include_retired=True)[arena_id], [OWNER, SECOND] if allied_second else [OWNER],
        [FOE] if allied_second else ids[1:],
        control_modes={actor_id: "MANUAL" for actor_id in ids}, match_seed="H47-TABLE",
        display_name="H47 summon regression", maximum_rounds=15)["match_id"]

    def send(candidate_id, answers=()):
        menu = table.state(mid)["menu"]
        return table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], 0, list(answers))

    def commit(candidate_id, square=None):
        answers = []
        for _ in range(16):
            result = send(candidate_id, answers)
            if result["status"] == "COMMITTED":
                return result
            assert result["status"] == "REACTION_REQUIRED", result
            prompt = result["reaction"]
            choice = prompt.get("choice") or {}
            # SQUAREPICK1 (938f1759): a printed area is aimed on the table, so its
            # square arrives as a second-stage map choice instead of one menu row
            # per destination cell.
            spatial = [option for option in choice.get("options", []) if option.get("cell")]
            if square is not None and spatial:
                wanted = [option for option in spatial if same_square(option["cell"], square)]
                assert wanted, f"{square} is not one of the offered squares: {spatial[:6]}"
                answers.append({**prompt["context"], "selection": "USE", "option_ids": [wanted[0]["id"]]})
                continue
            answer = {**prompt["context"], "selection": "DECLINE"}
            if choice and not choice.get("allow_decline"):
                answer.update(selection="USE", option_ids=(choice.get("preferred") or
                                                              [choice["options"][0]["id"]])[:1])
            answers.append(answer)
        raise AssertionError("too many reaction prompts")

    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    return combat, table, mid, send, commit


def candidate(table, mid, label, target=None):
    return next(option["candidate_id"] for group in table.state(mid)["menu"]["actions"] if label in group["label"]
                for option in group["options"] if target is None or target in option.get("target_ids", []))


def same_square(cell, square):
    """Whether a map-pick cell (its x, y and optional altitude) is the square a fixture names."""
    return (cell is not None and cell.get("x") == square.get("x") and cell.get("y") == square.get("y")
            and int(cell.get("z") or 0) == int(square.get("z") or 0))


def guard(combat, mid):
    engine = combat._load_session(mid).engine
    return next(actor for actor in engine.state.actors.values() if actor.owner_id == OWNER and actor.summon
                and actor.summon["group"] == "bone_guard")


def verify_reload(combat, table, mid):
    session = combat._load_session(mid)
    current = session.engine.state.model_dump(mode="json")
    fresh = CombatService(combat.source_root, combat.userdata_root)._load_session(mid).engine.state.model_dump(mode="json")
    assert current == fresh
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    assert table.state(mid)["match_id"] == mid


def test_table_minute_duration_survives_recovery_and_expires(tmp_path):
    combat, table, mid, _, commit = table_fixture(tmp_path)
    commit(candidate(table, mid, "Bone Guard Manifestation"))
    duration = next(row for actor in table.state(mid)["presentation"]["actors"] for row in actor.get("conditions", [])
                    if row.get("source_definition_id") == "system:combat.summon_duration")
    assert "vanishes at the start of Owner's turn" in duration["rule_text"]
    assert duration["source_ability"] == "Bone Guard Manifestation"
    assert "It vanishes at the start of Owner's turn" in duration["detail"]
    assert "Source ability unavailable" not in duration["detail"]
    start = combat._load_session(mid).engine.state.round_number
    while combat._load_session(mid).engine.state.round_number < start + 9:
        commit(table.state(mid)["menu"]["end_turn"])
    assert guard(combat, mid).active
    while (combat._load_session(mid).engine.state.round_number < start + 10
           or table.state(mid)["menu"]["actor_id"] != OWNER):
        commit(table.state(mid)["menu"]["end_turn"])
    assert not guard(combat, mid).active
    verify_reload(combat, table, mid)


def test_table_guard_reaction_uses_manual_owners_ask_me_setting(tmp_path):
    combat, table, mid, send, commit = table_fixture(tmp_path, foe_talents=["AIR_BASE_WIND_LASH"])
    commit(candidate(table, mid, "Bone Guard Manifestation"))
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    response = table.auto_step(mid, table.state(mid)["last_sequence"])
    assert response["status"] == "REACTION_REQUIRED"
    assert response["reaction"]["reaction"] == "Guard the Sovereign"
    answer = {**response["reaction"]["context"], "selection": "USE"}
    result = table.auto_step(mid, table.state(mid)["last_sequence"], [answer])
    assert result["status"] == "COMMITTED", result
    verify_reload(combat, table, mid)


def test_table_guard_saving_throws_copy_recorded_owner_totals(tmp_path):
    saves = {"STR": 6, "DEX": 7, "CON": 8, "INT": 5, "WIS": 6, "CHA": 4}
    combat, table, mid, _, commit = table_fixture(tmp_path, saves=saves)
    commit(candidate(table, mid, "Bone Guard Manifestation"))
    session = combat._load_session(mid)
    assert session.engine.state.actors[OWNER].saving_throws == saves
    assert guard(combat, mid).saving_throws == saves
    verify_reload(combat, table, mid)


def test_table_uncommanded_guard_follows_owner_within_thirty_feet(tmp_path):
    combat, table, mid, _, commit = table_fixture(tmp_path, wide=True)
    commit(candidate(table, mid, "Bone Guard Manifestation"))
    for _ in range(4):
        engine = combat._load_session(mid).engine
        current_guard = guard(combat, mid)
        owner = engine.state.actors[OWNER]
        if engine._distance_actor_to_actor(owner, current_guard) > 60:
            break
        moves = table.state(mid)["menu"]["moves"]
        if moves:
            best = max(moves, key=lambda row: abs(row["destination"]["x"] - current_guard.position.x)
                       + abs(row["destination"]["y"] - current_guard.position.y))
            commit(best["candidate_id"])
        commit(table.state(mid)["menu"]["end_turn"])
        while table.state(mid)["menu"]["actor_id"] != OWNER:
            commit(table.state(mid)["menu"]["end_turn"])
    engine = combat._load_session(mid).engine
    assert engine._distance_actor_to_actor(engine.state.actors[OWNER], guard(combat, mid)) <= 30
    verify_reload(combat, table, mid)


def test_table_ai_owner_answers_guard_reaction_automatically(tmp_path):
    combat, table, mid, _, commit = table_fixture(tmp_path, foe_talents=["AIR_BASE_WIND_LASH"])
    commit(candidate(table, mid, "Bone Guard Manifestation"))
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.event_sequence
    response = table.auto_step(mid, table.state(mid)["last_sequence"])
    assert response["status"] == "COMMITTED", response
    events = combat._load_session(mid).engine.events[before:]
    assert any(e.event_type == "REACTION_RESOLVED" and e.actor_id == guard(combat, mid).entity_id
               and e.source_definition_id == "summon.bone_guard.innate_reaction" for e in events)
    assert not guard(combat, mid).reaction_available
    verify_reload(combat, table, mid)


def test_table_talisman_spirit_independent_one_minute_boundary(tmp_path):
    combat, table, mid, _, commit = table_fixture(tmp_path, owner_talents=[SPIRIT])
    start = combat._load_session(mid).engine.state
    expiry = (start.round_number + 10, start.initiative_order.index(OWNER))
    commit(candidate(table, mid, "Talisman Spirit"))
    def spirit():
        return next(a for a in combat._load_session(mid).engine.state.actors.values()
                    if a.owner_id == OWNER and a.summon and a.summon["group"] == "talisman_spirit")
    clock = next(c for c in spirit().conditions.values()
                 if c.source_definition_id == "system:combat.summon_duration")
    assert clock.expires_on == f"START_OF_SLOT_AT:{expiry[0]}:{expiry[1]}"
    saw_last_round = False
    for _ in range(40):
        state = combat._load_session(mid).engine.state
        if (state.round_number, state.current_slot_index) >= expiry:
            break
        assert spirit().active
        saw_last_round |= state.round_number == expiry[0] - 1
        commit(table.state(mid)["menu"]["end_turn"])
    else:
        pytest.fail("Spirit's ten-round expiry turn was not reached")
    assert saw_last_round
    assert (state.round_number, state.current_slot_index) == expiry
    assert not spirit().active
    dismissal = next(e for e in reversed(combat._load_session(mid).engine.events)
                     if e.event_type == "SUMMON_DISMISSED" and e.actor_id == spirit().entity_id)
    assert dismissal.payload["reason"] == "DURATION_ENDED"
    verify_reload(combat, table, mid)


def move_owner_away(combat, table, mid, commit):
    engine = combat._load_session(mid).engine
    creature = guard(combat, mid)
    move = max(table.state(mid)["menu"]["moves"], key=lambda row:
               engine.grid.distance_ft(creature.position, type(creature.position)(**row["destination"])))
    commit(move["candidate_id"])
    engine = combat._load_session(mid).engine
    assert engine._distance_actor_to_actor(engine.state.actors[OWNER], guard(combat, mid)) > 30


def test_table_zone_save_choice_pause_reload_then_follow(tmp_path):
    combat, table, mid, _, commit = table_fixture(tmp_path, wide=True, foe_talents=[LAVA],
                                                second_talents=[FATE], allied_second=True)
    commit(candidate(table, mid, "Bone Guard Manifestation"))
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    position = guard(combat, mid).position.model_dump(mode="json")
    group = next(g for g in table.state(mid)["menu"]["actions"] if "Lava Flow" in g["label"])
    # SQUAREPICK1 (938f1759): the printed area is aimed on the table, so the guard's
    # square is answered as a second-stage map choice rather than a row of its own.
    commit(group["options"][0]["candidate_id"], position)
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    move_owner_away(combat, table, mid, commit)
    creature = guard(combat, mid)
    assert any(creature.position in z.affected_cells for z in combat._load_session(mid).engine.state.zones.values())
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    state = table.state(mid)
    menu = state["menu"]
    args = (mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    answers = []
    for _ in range(8):
        paused = table.act(*args, answers)
        assert paused["status"] == "REACTION_REQUIRED", paused
        prompt = paused["reaction"]
        if prompt["context"]["reaction_source_id"] == "choice:needle.rewrite_the_disaster":
            break
        answers.append({**prompt["context"], "selection": "DECLINE"})
    assert prompt["context"]["reaction_source_id"] == "choice:needle.rewrite_the_disaster"
    assert creature.display_name in prompt["moment"]
    assert "Lava Flow" in prompt["moment"]
    # A preview pause is not a committed partial turn. Recover the service
    # from disk, reproduce the choice, and submit its answer on the same action.
    fresh = CombatService(ROOT, tmp_path)
    table = TabletopService(fresh, tmp_path)
    assert fresh._load_session(mid).engine.state.model_dump(mode="json") == before
    assert table.act(*args, answers)["reaction"] == prompt
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["1"]}
    answers.append(answer)
    for _ in range(8):
        response = table.act(*args, answers)
        if response["status"] == "COMMITTED":
            break
        assert response["status"] == "REACTION_REQUIRED", response
        answers.append({**response["reaction"]["context"], "selection": "DECLINE"})
    assert response["status"] == "COMMITTED", response
    events = fresh._load_session(mid).engine.events[before["event_sequence"]:]
    choice = next(e for e in events if e.event_type == "D20_REWRITTEN" and e.actor_id == creature.entity_id)
    save = next(e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == creature.entity_id)
    damage = next(e for e in events if e.event_type == "DAMAGE_COMMITTED" and creature.entity_id in e.target_ids)
    move = next(e for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == creature.entity_id
                and not e.payload.get("forced"))
    assert choice.sequence < save.sequence < damage.sequence < move.sequence
    assert damage.payload["hp_damage"] > 0
    assert not move.payload["interrupted"]
    assert fresh._load_session(mid).engine.state.actors[creature.entity_id].position != creature.position
    verify_reload(fresh, table, mid)


def test_table_follow_stops_after_opportunity_attack_displaces_guard(tmp_path):
    from tests.test_auto_martial import SPEAR_KIT
    combat, table, mid, _, commit = table_fixture(tmp_path, wide=True, foe_kit=SPEAR_KIT,
                                                foe_talents=["TAL_SPEAR_SPEAR_LIGHT_INFUSION"])
    commit(candidate(table, mid, "Bone Guard Manifestation"))
    # Let the foe begin a turn so its opportunity reaction is available.
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    move_owner_away(combat, table, mid, commit)
    state = table.state(mid)
    before = combat._load_session(mid).engine.state.event_sequence
    # Decline any opportunity against the owner, but use the spear reaction
    # against the Guard during the automatically passing companion turn.
    menu = state["menu"]
    args = (mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    paused = table.act(*args)
    assert paused["status"] == "REACTION_REQUIRED", paused
    prompt = paused["reaction"]
    assert prompt["reaction"] == "Opportunity Attack"
    assert guard(combat, mid).display_name in prompt["moment"]
    fresh = CombatService(ROOT, tmp_path)
    table = TabletopService(fresh, tmp_path)
    assert table.act(*args)["reaction"] == prompt
    answers = [{**prompt["context"], "selection": "USE"}]
    for _ in range(8):
        result = table.act(*args, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    assert result["status"] == "COMMITTED", result
    combat = fresh
    events = combat._load_session(mid).engine.events[before:]
    creature = guard(combat, mid)
    forced = next(e for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == creature.entity_id
                  and e.payload.get("forced"))
    follow = next(e for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == creature.entity_id
                  and not e.payload.get("forced"))
    assert follow.payload["interrupted"]
    assert follow.payload["cost_ft"] < follow.payload["planned_cost_ft"]
    assert follow.payload["destination"] == forced.payload["destination"] == creature.position.model_dump(mode="json")
    assert forced.sequence < follow.sequence
    verify_reload(combat, table, mid)
