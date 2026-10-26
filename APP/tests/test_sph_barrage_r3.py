"""Multiweapon Push Through regressions through table intents and cold reload."""
import pytest
from combat.gate5_service import CombatService
from tests.test_sph_barrage_r1 import _custom_table, _send, SKY, LEFT, RIGHT, ROOT
from combat.ext import ammunition


@pytest.mark.parametrize("case", ["empty", "range", "player", "player_other_turn", "ai"])
def test_push_through_usable_weapon_and_owner_choice(tmp_path, case):
    weapons = [{"item_id": "tianxia.mortal.weapon.dan_gong", "quantity": 1},
               {"item_id": "tianxia.mortal.weapon.fei_biao", "quantity": 2}]
    if case == "range":
        weapons = [{"item_id": "tianxia.mortal.weapon.bi_shou", "quantity": 1}, weapons[0]]
        # Catalogue order puts the dagger's 60-foot throw before the pellet bow's 120-foot shot.
    kit = {"starting_kit": {"items": [*weapons,
        {"item_id": "tianxia.mortal.gear.bullets_sling_20", "quantity": 0 if case == "empty" else 1}]}}
    other_turn = case in ("player_other_turn", "ai")
    foe = (20, 4) if case == "range" else (5, 4) if other_turn else (6, 4)
    combat, table, mid = _custom_table(tmp_path, [SKY], foe_at=foe, kit=kit)
    group = next(g for g in table.state(mid)["menu"]["actions"] if SKY in g["source_definition_id"])
    aim = (17, 4) if case == "range" else (10, 4) if other_turn else foe
    cid = next(o["candidate_id"] for o in group["options"] if o["destination"] == {"x": aim[0], "y": aim[1]})
    assert _send(table, mid, cid)["status"] == "COMMITTED"
    cid = table.state(mid)["menu"]["end_turn"]
    if other_turn:
        assert _send(table, mid, cid)["status"] == "COMMITTED"
        if case == "ai":
            combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
        engine = combat._load_session(mid).engine
        cid = next(c.candidate_id for c in engine.legal_candidates() if c.kind == "MOVE"
                   and c.destination.model_dump(mode="json") == {"x": 6, "y": 4})
    first = _send(table, mid, cid)
    assert first["status"] == "REACTION_REQUIRED"
    answers = [{**first["reaction"]["context"], "selection": "USE", "option_ids": ["push_through"]}]
    second = _send(table, mid, cid, answers)
    if case in ("player", "player_other_turn"):
        assert second["status"] == "REACTION_REQUIRED"
        prompt = second["reaction"]
        assert prompt["context"]["reactor_id"] == LEFT
        assert prompt["context"]["reaction_source_id"] == "choice:needle.sky_net_weapon"
        assert len(prompt["choice"]["options"]) == 2
        selected = next(o["id"] for o in prompt["choice"]["options"] if "fei_biao" in o["id"])
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [selected]})
        second = _send(table, mid, cid, answers)
    assert second["status"] == "COMMITTED", second
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    rolls = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED"]
    assert len(rolls) == 1
    assert ("dan_gong" if case in ("ai", "range") else "fei_biao") in rolls[0].source_definition_id
    actor = loaded.engine.state.actors[LEFT]
    if case in ("ai", "range"):
        assert sum(v for k, v in actor.turn_flags.items() if k.startswith(ammunition._SPENT_PREFIX)) == 1
    else:
        # Ordinary throws leave the physical copy on the map; volley payments use counters.
        assert any(c.data.get("disables_action") == rolls[0].source_definition_id.split("#")[0]
                   and c.data.get("dropped_at") for c in actor.conditions.values())
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_manual_weapon_owner_is_asked_during_an_ai_turn(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.tabletop import ButtonStore
    from tests.test_tabletop_hunt6 import table_fight, ALLY, PROJECTS
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(PROJECTS["right"], {"mode": "ask"}, {"opportunity_attack"})
    kit = {"starting_kit": {"items": [
        {"item_id": "tianxia.mortal.weapon.dan_gong", "quantity": 1},
        {"item_id": "tianxia.mortal.weapon.fei_biao", "quantity": 1},
        {"item_id": "tianxia.mortal.gear.bullets_sling_20", "quantity": 1}]}}
    combat, table, mid = table_fight(tmp_path, [SKY], cl=17, kit=kit, ask=True)
    group = next(g for g in table.state(mid)["menu"]["actions"] if SKY in g["source_definition_id"])
    cid = next(o["candidate_id"] for o in group["options"] if o["destination"] == {"x": 4, "y": 4})
    assert _send(table, mid, cid)["status"] == "COMMITTED"
    assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] == ALLY
    cid = table.state(mid)["menu"]["end_turn"]
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode="LOCAL_AUTO")
    real = combat.controller
    class EndTurnController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = EndTurnController()
    try:
        def send(answers=()):
            return table.auto_step(mid, table.state(mid)["last_sequence"], list(answers))
        first = send()
        assert first["status"] == "REACTION_REQUIRED"
        assert first["reaction"]["context"]["reactor_id"] == RIGHT
        answers = [{**first["reaction"]["context"], "selection": "USE", "option_ids": ["push_through"]}]
        second = send(answers)
        assert second["status"] == "REACTION_REQUIRED"
        assert second["reaction"]["context"]["reactor_id"] == LEFT
        option = next(o["id"] for o in second["reaction"]["choice"]["options"] if "fei_biao" in o["id"])
        answers.append({**second["reaction"]["context"], "selection": "USE", "option_ids": [option]})
        assert send(answers)["status"] == "COMMITTED"
    finally:
        combat.controller = real
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    rolls = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == LEFT]
    assert len(rolls) == 1 and "fei_biao" in rolls[0].source_definition_id
    assert loaded.mechanical.replay()["status"] == "PASS"
