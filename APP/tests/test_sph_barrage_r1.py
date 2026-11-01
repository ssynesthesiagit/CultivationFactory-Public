"""Barrage review regressions, including real table commits and fresh service reloads."""
from combat import carry
import pytest
from combat.ext import ammunition
from combat.gate5_service import CombatService
from tests.test_tabletop_hunt6 import LEFT, RIGHT, ALLY, PROJECTS, table_fight, answer_action
from tests.test_auto58_barrage_projectiles import NEEDLE_RAIN, ARROW_KIT, ROOT

JAVELIN = "tianxia.mortal.weapon.biao_qiang"
STAIR = "TAL_BARRAGE_STAIR_SHOT"
SKY = "TAL_BARRAGE_SKY_NET_SUPPRESSION"


def _action(engine, name):
    return next(a for a in engine.action_catalog.values() if a.display_name == name)


def test_projectile_cost_commits_reloads_and_replays(tmp_path):
    combat, table, mid = table_fight(tmp_path, [NEEDLE_RAIN], cl=17, kit=ARROW_KIT)
    assert answer_action(table, mid, NEEDLE_RAIN)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert ammunition.projectiles_available(loaded.engine, actor, _action(loaded.engine, "Needle-Rain Burst"))[0] == 35
    assert sum(v for k, v in actor.turn_flags.items() if k.startswith(ammunition._SPENT_PREFIX)) == 5
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_exhausted_thrown_stock_stays_zero_and_cannot_be_used_as_a_weapon(tmp_path):
    kit = {"starting_kit": {"items": [{"item_id": JAVELIN, "quantity": 5}]}}
    combat, table, mid = table_fight(tmp_path, [NEEDLE_RAIN], cl=17, kit=kit)
    assert answer_action(table, mid, NEEDLE_RAIN)["status"] == "COMMITTED"
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    actor = engine.state.actors[LEFT]
    stock = ammunition.projectiles_available(engine, actor, _action(engine, "Needle-Rain Burst"))
    assert stock is not None and stock[0] == 0
    assert not carry.holds(engine, actor, JAVELIN)
    assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine, actor = loaded.engine, loaded.engine.state.actors[LEFT]
    assert ammunition.projectiles_available(engine, actor, _action(engine, "Needle-Rain Burst"))[0] == 0
    assert not any("NEEDLE_RAIN" in c.source_definition_id or "biao_qiang" in c.source_definition_id
                   for c in engine.legal_candidates())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_stair_shot_rejects_thrown_weapons_and_stones(tmp_path):
    kit = {"starting_kit": {"items": [{"item_id": JAVELIN, "quantity": 10},
        {"item_id": "tianxia.mortal.gear.bullets_sling_20", "quantity": 1}]}}
    combat, table, mid = table_fight(tmp_path, [STAIR], cl=17, kit=kit)
    assert not any("STAIR_SHOT" in g["source_definition_id"] for g in table.state(mid)["menu"]["actions"])
    engine = combat._load_session(mid).engine
    action = _action(engine, "Stair Shot")
    text = ammunition.projectile_description(action.model_dump(mode="json"))
    assert "thrown weapons" not in text
    assert "embedding" in text and "10" in text


def test_stair_shot_only_spends_embedding_ammunition(tmp_path):
    kit = {"starting_kit": {"items": [{"item_id": JAVELIN, "quantity": 10},
        {"item_id": "tianxia.mortal.gear.bullets_sling_20", "quantity": 1},
        {"item_id": "tianxia.mortal.gear.bolts_20", "quantity": 1}]}}
    combat, table, mid = table_fight(tmp_path, [STAIR], cl=17, kit=kit)
    assert answer_action(table, mid, STAIR)["status"] == "COMMITTED"
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    flags = engine.state.actors[LEFT].turn_flags
    spent = {k: v for k, v in flags.items() if k.startswith((ammunition._SPENT_PREFIX, ammunition._THROWN_SPENT_PREFIX))}
    assert sum(spent.values()) == 10
    assert all("bolts_20" in k for k in spent)
    assert not any("bullets_sling" in k or k.startswith(ammunition._THROWN_SPENT_PREFIX) for k in spent)


def test_ceaseless_supplies_whole_volley_without_spending(tmp_path):
    combat, table, mid = table_fight(tmp_path, [NEEDLE_RAIN, ammunition._CEASELESS], cl=17, kit=ARROW_KIT)
    assert answer_action(table, mid, NEEDLE_RAIN)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert ammunition.projectiles_available(loaded.engine, actor, _action(loaded.engine, "Needle-Rain Burst"))[0] == 40
    assert not any(k.startswith(ammunition._SPENT_PREFIX) for k in actor.turn_flags)
    assert loaded.mechanical.replay()["status"] == "PASS"


def _send(table, mid, cid, answers=()):
    state = table.state(mid)
    menu = state["menu"]
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("choice", ["slow_down", "push_through"])
def test_sky_net_creature_choice_commits_and_reloads(tmp_path, choice, auto_turn):
    from combat.tabletop import ButtonStore
    from combat.ext import barrage_sky_net
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(PROJECTS["right"], {"mode": "ask"}, {"opportunity_attack"})
    combat, table, mid = table_fight(tmp_path, [SKY], cl=17, kit=ARROW_KIT)
    group = next(g for g in table.state(mid)["menu"]["actions"] if SKY in g["source_definition_id"])
    cid = next(o["candidate_id"] for o in group["options"] if o["destination"] == {"x": 4, "y": 4})
    assert _send(table, mid, cid)["status"] == "COMMITTED"
    def send(cid, answers=()):
        if not auto_turn:
            return _send(table, mid, cid, answers)
        from combat.gate4_adapters import ManualControllerAdapter
        actor = table.state(mid)["menu"]["actor_id"]
        combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")
        real = combat.controller
        class SelectedController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = SelectedController()
        try:
            return table.auto_step(mid, table.state(mid)["last_sequence"], list(answers))
        finally:
            combat.controller = real
    # Ending successive turns naturally fires the zone on the hostile creature's start, inside a table transaction.
    for _ in range(3):
        state = table.state(mid)
        cid = state["menu"]["end_turn"]
        first = send(cid)
        if first["status"] == "REACTION_REQUIRED":
            break
        assert first["status"] == "COMMITTED"
    assert first["status"] == "REACTION_REQUIRED", first
    prompt = first["reaction"]
    assert prompt["context"]["reactor_id"] == RIGHT
    assert prompt["context"]["reaction_source_id"] == "choice:needle.sky_net"
    labels = " ".join(o["label"] for o in prompt["choice"]["options"])
    assert "-2" in labels and "10 feet" in labels and "next turn" in labels and "Left" in labels
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    answer = {**prompt["context"], "selection": "USE", "option_ids": [choice]}
    assert send(cid, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[RIGHT]
    if choice == "slow_down":
        assert any(c.condition_id == barrage_sky_net.SLOW for c in actor.conditions.values())
        assert not any(g["source_definition_id"] == "system:combat.dash" for g in table.state(mid)["menu"]["actions"])
    else:
        rolls = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == LEFT]
        assert len(rolls) == 1
        assert "gong_jian" in rolls[0].source_definition_id
        spent = sum(v for k, v in loaded.engine.state.actors[LEFT].turn_flags.items() if k.startswith(ammunition._SPENT_PREFIX))
        assert spent == 1
    assert before != loaded.engine.state.model_dump(mode="json")
    assert loaded.mechanical.replay()["status"] == "PASS"


def _custom_table(tmp_path, talents, *, foe_at=(4, 4), ac=14, blind=False, fly=False, kit=ARROW_KIT):
    """Compile custom initial stats and a wide map before creating a sealed service fight."""
    from combat.factory_compiler import compile_character
    from combat.tabletop_service import TabletopService
    from tests.h1_support import sheet
    owner = sheet(talents, cl=17, dc=50, kit=kit)
    owner["identity"]["display_name"] = "Archer"
    foe = sheet([], cl=17)
    foe["identity"]["display_name"] = "Defender"
    foe["ability_scores_and_statistics"]["armor_class"]["base_value"] = ac
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = 800
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True})
               for doc, aid in [(owner, LEFT), (foe, RIGHT)]]
    if blind or fly:
        aid = "test:blind_self"
        bundles[1]["actor_template"]["action_ids"].append(aid)
        bundles[1]["action_catalog"].append({"source_definition_id": aid, "display_name": "Cover your eyes",
            "owner_id": RIGHT, "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "SELF",
            "parameters": {"typed": {"effects": [{"type": "condition", "applies_to": "self",
                "condition": "blinded" if blind else "test_flight", "duration": "until_end_of_your_next_turn",
                **({"condition_data": {"fly_speed_ft": 30, "flight_hover": 1}} if fly else {})}],
                "numbers": {}, "duration": {"kind": "instant"}}}})
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Barrage regression yard", "width_squares": 64,
        "height_squares": 8, "walls": [], "starts": {"team1": [[3, 4]], "team2": [list(foe_at)]}})
    arena = combat.factory_arenas()["battlefield:map.barrage-regression-yard"]
    mid = combat._finish_factory_match(bundles, [LEFT, RIGHT], {LEFT: "team:a", RIGHT: "team:b"},
        {LEFT: {"x": 3, "y": 4}, RIGHT: {"x": foe_at[0], "y": foe_at[1]}}, arena, [LEFT], [RIGHT],
        control_modes={LEFT: "MANUAL", RIGHT: "MANUAL"}, match_seed="BARRAGE-R1",
        display_name="Barrage regression", maximum_rounds=10)["match_id"]
    table = TabletopService(combat, tmp_path)
    if blind or fly:
        while table.state(mid)["menu"]["actor_id"] != RIGHT:
            assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
        assert answer_action(table, mid, "test:blind_self")["status"] == "COMMITTED"
        assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    return combat, table, mid


@pytest.mark.parametrize("blind,foe_at,aim", [(True, (4, 4), (4, 4)), (False, (39, 4), (33, 4))])
def test_ten_thousand_choice_includes_blind_and_distant_area_recipient(tmp_path, blind, foe_at, aim):
    talent = "TAL_BARRAGE_TEN_THOUSAND_PROJECTILE_RAIN"
    combat, table, mid = _custom_table(tmp_path, [talent], blind=blind, foe_at=foe_at)
    group = next(g for g in table.state(mid)["menu"]["actions"] if talent in g["source_definition_id"])
    cid = next(o["candidate_id"] for o in group["options"] if o["destination"] == {"x": aim[0], "y": aim[1]})
    first = _send(table, mid, cid)
    assert first["status"] == "REACTION_REQUIRED"
    prompt = first["reaction"]
    assert RIGHT in [o["id"] for o in prompt["choice"]["options"]]
    answer = {**prompt["context"], "selection": "USE", "option_ids": [RIGHT]}
    assert _send(table, mid, cid, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[RIGHT].current_hp < 800
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ac,hit", [(0, True), (100, False)])
def test_push_through_has_real_weapon_damage_ammo_and_hit_only_speed_loss(tmp_path, ac, hit):
    combat, table, mid = _custom_table(tmp_path, [SKY], ac=ac, foe_at=(6, 4))
    group = next(g for g in table.state(mid)["menu"]["actions"] if SKY in g["source_definition_id"])
    cid = next(o["candidate_id"] for o in group["options"] if o["destination"] == {"x": 6, "y": 4})
    assert _send(table, mid, cid)["status"] == "COMMITTED"
    cid = table.state(mid)["menu"]["end_turn"]
    first = _send(table, mid, cid)
    assert first["status"] == "REACTION_REQUIRED"
    answer = {**first["reaction"]["context"], "selection": "USE", "option_ids": ["push_through"]}
    assert _send(table, mid, cid, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    rolls = [e for e in engine.events if e.event_type == "ATTACK_ROLLED"]
    assert len(rolls) == 1 and "gong_jian" in rolls[0].source_definition_id
    damage = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]
    assert bool(damage) == hit
    if hit:
        assert all(e.payload["damage_type"] == "PIERCING" for e in damage)
        weapon = _action(engine, "Gong Jian (Bow and Arrow) attack").parameters["typed"]["weapon"]
        assert any(f'd{weapon["damage"]["sides"]}' in r.expression for r in engine.rolls if "DAMAGE" in r.reason)
    assert bool([m for m in engine.state.actors[RIGHT].modifiers.values() if m.target_field == "speed_ft" and m.value == -10]) == hit
    assert sum(v for k, v in engine.state.actors[LEFT].turn_flags.items() if k.startswith(ammunition._SPENT_PREFIX)) == 1
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("mode", ["walk", "fly", "jump"])
def test_slow_down_spends_twice_the_movement_and_prevents_dash(tmp_path, mode):
    from combat.ext import barrage_sky_net
    combat, table, mid = _custom_table(tmp_path, [SKY], foe_at=(6, 4), fly=mode == "fly")
    group = next(g for g in table.state(mid)["menu"]["actions"] if SKY in g["source_definition_id"])
    cid = next(o["candidate_id"] for o in group["options"] if o["destination"] == {"x": 6, "y": 4})
    assert _send(table, mid, cid)["status"] == "COMMITTED"
    cid = table.state(mid)["menu"]["end_turn"]
    first = _send(table, mid, cid)
    assert first["status"] == "REACTION_REQUIRED"
    answer = {**first["reaction"]["context"], "selection": "USE", "option_ids": ["slow_down"]}
    assert _send(table, mid, cid, [answer])["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[RIGHT]
    before = actor.movement_remaining_ft
    assert any(c.condition_id == barrage_sky_net.SLOW for c in actor.conditions.values())
    move = next(c for c in engine.legal_candidates() if c.kind == "MOVE"
                and c.metadata.get("movement_mode", "walk") == mode)
    assert move.movement_cost_ft == 10 * (len(move.canonical_path) - 1)
    assert not any(c.source_definition_id == "system:combat.dash" for c in engine.legal_candidates())
    assert _send(table, mid, move.candidate_id)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[RIGHT].movement_remaining_ft == before - move.movement_cost_ft
    assert loaded.mechanical.replay()["status"] == "PASS"
    assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    expired = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not any(c.condition_id == barrage_sky_net.SLOW for c in expired.engine.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize("in_range", [True, False])
def test_push_through_uses_selected_weapons_range(tmp_path, in_range):
    kit = ARROW_KIT if in_range else {"starting_kit": {"items": [
        {"item_id": "tianxia.mortal.weapon.chui_jian_tong", "quantity": 1},
        {"item_id": "tianxia.mortal.gear.needles_50", "quantity": 1}]}}
    combat, table, mid = _custom_table(tmp_path, [SKY], foe_at=(25, 4), kit=kit)
    group = next(g for g in table.state(mid)["menu"]["actions"] if SKY in g["source_definition_id"])
    cid = next(o["candidate_id"] for o in group["options"] if o["destination"] == {"x": 21, "y": 4})
    assert _send(table, mid, cid)["status"] == "COMMITTED"
    cid = table.state(mid)["menu"]["end_turn"]
    first = _send(table, mid, cid)
    assert first["status"] == "REACTION_REQUIRED"
    answer = {**first["reaction"]["context"], "selection": "USE", "option_ids": ["push_through"]}
    assert _send(table, mid, cid, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert len([e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED"]) == int(in_range)
    spent = sum(v for k, v in loaded.engine.state.actors[LEFT].turn_flags.items() if k.startswith(ammunition._SPENT_PREFIX))
    assert spent == int(in_range)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_sky_net_player_chooses_on_own_movement_turn(tmp_path):
    combat, table, mid = _custom_table(tmp_path, [SKY], foe_at=(5, 4))
    group = next(g for g in table.state(mid)["menu"]["actions"] if SKY in g["source_definition_id"])
    cid = next(o["candidate_id"] for o in group["options"] if o["destination"] == {"x": 10, "y": 4})
    assert _send(table, mid, cid)["status"] == "COMMITTED"
    assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    assert engine.state.current_actor_id == RIGHT
    move = next(c for c in engine.legal_candidates() if c.kind == "MOVE" and c.destination.model_dump(mode="json") == {"x": 6, "y": 4})
    first = _send(table, mid, move.candidate_id)
    assert first["status"] == "REACTION_REQUIRED"
    assert first["reaction"]["context"]["reactor_id"] == RIGHT
    answer = {**first["reaction"]["context"], "selection": "USE", "option_ids": ["slow_down"]}
    assert _send(table, mid, move.candidate_id, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[RIGHT].position.x == 6
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_sky_net_ai_creature_decides_automatically(tmp_path):
    from combat.ext import barrage_sky_net
    combat, table, mid = _custom_table(tmp_path, [SKY], foe_at=(6, 4))
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    group = next(g for g in table.state(mid)["menu"]["actions"] if SKY in g["source_definition_id"])
    cid = next(o["candidate_id"] for o in group["options"] if o["destination"] == {"x": 6, "y": 4})
    assert _send(table, mid, cid)["status"] == "COMMITTED"
    assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(c.condition_id == barrage_sky_net.SLOW for c in loaded.engine.state.actors[RIGHT].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_dropped_recorded_ammunition_does_not_become_unlimited(tmp_path):
    combat, table, mid = table_fight(tmp_path, [NEEDLE_RAIN], cl=17, kit=ARROW_KIT)
    group = next(g for g in table.state(mid)["menu"]["actions"]
                 if ".item_drop." in g["source_definition_id"] and "arrows" in g["label"].lower())
    assert _send(table, mid, group["options"][0]["candidate_id"])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine, actor = loaded.engine, loaded.engine.state.actors[LEFT]
    stock = ammunition.projectiles_available(engine, actor, _action(engine, "Needle-Rain Burst"))
    assert stock is not None and stock[0] == 0
    assert not any(NEEDLE_RAIN in g["source_definition_id"] for g in table.state(mid)["menu"]["actions"])
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("quantity,expected", [(0, 0), (None, None)])
def test_legacy_recorded_zero_ammunition_keeps_its_stock_contract(quantity, expected):
    from types import SimpleNamespace
    arrows = "tianxia.mortal.gear.arrows_20"
    actor = SimpleNamespace(entity_id=LEFT, turn_flags={}, conditions={})
    engine = SimpleNamespace(typed_bundle_documents=({"actor_id": LEFT, "carrying": {"items": [
        {"key": arrows, "item_id": arrows, "quantity": quantity}] }},))
    assert carry.holds(engine, actor, arrows)
    assert ammunition._stock(engine, actor, {"item_id": arrows, "label": "arrow"}) == expected
