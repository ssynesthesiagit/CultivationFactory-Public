"""Round17 integration: owned rider choices and exact saved effect instances."""
import copy
import json
import zipfile

import pytest

from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_riders_lane13 import ROOT, BOJUTSU, STAFF, PREFIX, engine, attack_name, use
from tests.test_factory_combat_compiler import SHEET


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("auto_owner", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
@pytest.mark.parametrize("rider", ["sweep", "frame"])
def test_paid_rider_table_choice_decline_and_reload(monkeypatch, tmp_path, auto_turn, auto_owner, selection, rider):
    actors = [FACTORY_ACTOR_PREFIX + s for s in ("left", "right")]
    for side in ("left", "right"):
        sheet = copy.deepcopy(SHEET)
        sheet["path_and_subpath"] = {"path_feature_record_ids": [BOJUTSU + "sweeping_strike" if rider == "sweep" else PREFIX + "adamant_frame"]}
        if rider == "frame":
            sheet["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.iron_fist"],
                "automatic_sphere_component_record_ids": ["TAL_IRON_FIST_IRON_FIST_TRAINING"]}
        sheet["equipment"] = [{"starting_kit": {"items": [{"item_id": STAFF}]}}]
        sheet["ability_scores_and_statistics"]["armor_class"] = {"base_value": 0}
        folder = tmp_path / "portable_characters" / side
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "R13 integration yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    mid = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[actors[1]],
        control_modes={a: "MANUAL" for a in actors}, arena_id="battlefield:map.r13-integration-yard",
        match_seed="R13-INTEGRATION")["match_id"]
    table = TabletopService(combat, tmp_path)
    state = table.state(mid)
    menu = state["menu"]
    owner = menu["actor_id"]
    if rider == "frame":
        from combat import ext
        ext.effects()
        def charge(fight, event_type, kwargs):
            if event_type == "HOLD_POSITION_COMMITTED":
                actor = fight.state.actors[kwargs["actor_id"]]
                fight._gain_resource(actor, "resource:named.thunder_charge", 4, "test:charge")
        monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), charge])
        hold = next(g for g in menu["actions"] if g["source_definition_id"] == "system:combat.hold_position")
        assert table.act(mid, hold["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
        state = table.state(mid)
        menu = state["menu"]
    attack = next(g for g in menu["actions"] if (g["source_definition_id"].endswith(".weapon.gun")
        if rider == "sweep" else "Unarmed" in g["label"]))
    cid = attack["options"][0]["candidate_id"]
    resource = "resource:core.stamina" if rider == "sweep" else "resource:named.thunder_charge"
    name = "Sweeping Strike" if rider == "sweep" else "Adamant Frame"
    before = combat._load_session(mid).engine.state.actors[owner].resources[resource]
    if auto_owner and not auto_turn:
        combat.set_controller_mode(mid, actor_id=owner, controller_mode="LOCAL_AUTO")
    if auto_turn:
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
        state = table.state(mid)
        menu = state["menu"]
        real = combat.controller
        class Attack:
            def choose_primary_action(self, context):
                position = combat._load_session(mid).engine.state.actors[owner].position
                candidates = [c for c in context.legal_candidates if c.source_definition_id == "system:combat.movement"]
                chosen = max(candidates, key=lambda c: max(abs(c.destination.x - position.x), abs(c.destination.y - position.y)))
                return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Attack()
        combat.set_controller_mode(mid, actor_id=menu["actor_id"], controller_mode="LOCAL_AUTO")
        if auto_owner:
            combat.set_controller_mode(mid, actor_id=owner, controller_mode="LOCAL_AUTO")
    elif auto_owner:
        real = combat.controller
        class Attack:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Attack()
    def send(replies=()):
        return (table.auto_step(mid, state["last_sequence"], list(replies)) if auto_turn or auto_owner else
                table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(replies)))
    result = send()
    replies = []
    if not auto_owner:
        assert result["status"] == "REACTION_REQUIRED"
        assert name in result["reaction"]["moment"]
        assert "hit" in result["reaction"]["moment"]
        victim = menu["actor_id"] if auto_turn else attack["options"][0]["target_ids"][0]
        assert combat._load_session(mid).engine.state.actors[victim].display_name in result["reaction"]["moment"]
        replies.append({**result["reaction"]["context"], "selection": selection,
                        "option_ids": ["Use Sweeping Strike" if rider == "sweep" else "Temporary Hit Points"] if selection == "USE" else []})
        result = send(replies)
        while result["status"] == "REACTION_REQUIRED":
            prompt = result["reaction"]
            assert name in prompt["moment"]
            replies.append({**prompt["context"], "selection": "USE",
                            "option_ids": [prompt["choice"]["options"][0]["id"]]})
            result = send(replies)
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[owner].resources[resource] == before - int(auto_owner or selection == "USE")
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_next_save_consumes_only_selected_source():
    from combat.ext.path_riders import NEXT_SAVE, consume_next_save
    from combat import typed_executor
    fight = engine([PREFIX + "adamant_frame"])
    from tests.test_riders_lane13 import ME
    actor = fight.state.actors[ME]
    for source in ("test:first", "test:second"):
        fight._apply_condition(actor, NEXT_SAVE, source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                              data={"abilities": ["CON"], "bonus": 4})
    action = next(a for a in fight.action_catalog.values() if a.owner_id == ME)
    ctx = typed_executor.Context(fight, actor, action, None, action.parameters.get("typed") or {}, [], actor, {})
    assert consume_next_save(ctx, actor, "CON", []) == {"bonus": 4, "modes": []}
    assert [c.source_definition_id for c in actor.conditions.values() if c.condition_id == NEXT_SAVE] == ["test:second"]


def test_knuckle_ac_penalty_does_not_stack_across_casters():
    from combat.ext.path_riders import ac
    from tests.test_riders_lane13 import AN
    fight = engine([])
    target = fight.state.actors[AN]
    for source in ("test:first", "test:second"):
        fight._apply_condition(target, "condition:typed.path_ac.heaven_breaking_knuckle", source, source,
                              expires_on="START_OF_SOURCE_NEXT_TURN", data={"amount": -2})
    assert ac(fight, target) == -2


def test_thorn_refresh_preserves_other_caster():
    from combat.ext.thorn_bleeding import BLEEDING, apply
    from combat import typed_executor
    from tests.test_riders_lane13 import ME, AN
    fight = engine([])
    target = fight.state.actors[AN]
    fight._apply_condition(target, BLEEDING, "test:other", AN, expires_on="START_OF_SOURCE_NEXT_TURN",
                          data={"thorn_bleeding": {"pb": 2, "damage_type": "PIERCING", "moved_ft": 0}})
    old = next(c.instance_id for c in target.conditions.values() if c.source_definition_id == "test:other")
    action = next(a for a in fight.action_catalog.values() if a.owner_id == ME)
    ctx = typed_executor.Context(fight, fight.state.actors[ME], action, None,
        {"numbers": {"pb": 4}, "duration": {"kind": "until_start_of_next_turn"}}, [target], target, {})
    apply(ctx, {"damage_type": "SLASHING"})
    apply(ctx, {"damage_type": "PIERCING"})
    assert old in target.conditions
    assert len([c for c in target.conditions.values() if c.condition_id == BLEEDING]) == 2
    from combat.ext.thorn_bleeding import after_attack
    before = target.current_hp
    ctx.actor = target
    after_attack(ctx, fight.state.actors[ME], False, {})
    assert target.current_hp == before
    assert not any(c.condition_id == BLEEDING for c in target.conditions.values())
    pending = [e for e in fight.events if e.event_type == "GM_RIDER" and "nonstacking delayed packet" in e.payload.get("rider", "")]
    assert len(pending) == 1 and "2 Piercing" in pending[0].payload["rider"] and "4 Piercing" in pending[0].payload["rider"]


@pytest.mark.parametrize("kind", ["save", "advantage", "bleeding", "bleeding_overlap", "ac"])
def test_owned_instances_survive_table_commit_reload(monkeypatch, tmp_path, kind):
    from combat import typed_executor
    from combat.ext import path_riders, thorn_bleeding
    from tests.test_lock_choices import install
    from tests.test_lock2_persistence import table_match, act
    from combat.prepared_actions import SOURCE

    install(monkeypatch, "prepare_options", lambda *a: [{"option_id": "stored", "source_id": "test:stored",
        "label": "Stored rider probe", "trigger": "HOLD_POSITION_COMMITTED"}])
    install(monkeypatch, "prepared_trigger", lambda *a: True)
    def resolve(fight, actor, option, event, intent):
        other = fight.state.actors[event.actor_id]
        action = next(a for a in fight.action_catalog.values() if a.owner_id == actor.entity_id)
        ctx = typed_executor.Context(fight, actor, action, intent,
            {"numbers": {"pb": 4}, "duration": {"kind": "until_start_of_next_turn"},
             "effects": [{"type": "attack", "attack_kind": "unarmed"}]}, [other], other, {})
        if kind == "save":
            for source in ("test:older", "test:newer"):
                fight._apply_condition(actor, path_riders.NEXT_SAVE, source, actor.entity_id,
                    expires_on="UNTIL_REMOVED", data={"abilities": ["CON"], "bonus": 4})
            assert path_riders.consume_next_save(ctx, actor, "CON", []) == {"bonus": 4, "modes": []}
        elif kind == "advantage":
            for source in ("test:older", "test:newer"):
                fight._apply_condition(actor, path_riders.NEXT_UNARMED, source, actor.entity_id,
                    expires_on="UNTIL_REMOVED", data={})
            assert path_riders.consume_unarmed_advantage(ctx, other) == "ADVANTAGE"
        elif kind.startswith("bleeding"):
            fight._apply_condition(other, thorn_bleeding.BLEEDING, "test:older", other.entity_id,
                expires_on="UNTIL_REMOVED", data={"thorn_bleeding": {"pb": 2, "damage_type": "PIERCING", "moved_ft": 0}})
            thorn_bleeding.apply(ctx, {"damage_type": "PIERCING"})
            thorn_bleeding.apply(ctx, {"damage_type": "PIERCING"})
            if kind == "bleeding_overlap":
                before = other.current_hp
                ctx.actor = other
                thorn_bleeding.after_attack(ctx, actor, False, {})
                assert other.current_hp == before
        else:
            fight._apply_condition(other, "condition:typed.path_ac.heaven_breaking_knuckle", "test:older", other.entity_id,
                expires_on="UNTIL_REMOVED", data={"amount": -2})
            path_riders.ac_penalty(ctx, {"family": "heaven_breaking_knuckle", "amount": -2, "expires_on": "START_OF_SOURCE_NEXT_TURN"})
            path_riders.ac_penalty(ctx, {"family": "heaven_breaking_knuckle", "amount": -2, "expires_on": "START_OF_SOURCE_NEXT_TURN"})
            assert path_riders.ac(fight, other) == -2
        return True
    install(monkeypatch, "prepared_action", resolve)
    combat, table, mid = table_match(tmp_path)
    owner = table.state(mid)["menu"]["actor_id"]
    assert act(table, mid, SOURCE)["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    result = act(table, mid, "system:combat.hold_position")
    prompt = result["reaction"]
    menu = result["state"]["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == "system:combat.hold_position")
    result = table.act(mid, cid, menu["decision_id"], menu["state_version"], result["state"]["last_sequence"],
        [{**prompt["context"], "selection": "USE"}])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[owner if kind in {"save", "advantage"} else menu["actor_id"]]
    if kind in {"save", "advantage"}:
        condition_id = path_riders.NEXT_SAVE if kind == "save" else path_riders.NEXT_UNARMED
        assert [c.source_definition_id for c in target.conditions.values() if c.condition_id == condition_id] == ["test:newer"]
    elif kind.startswith("bleeding"):
        assert len([c for c in target.conditions.values() if c.condition_id == thorn_bleeding.BLEEDING]) == (0 if kind == "bleeding_overlap" else 2)
        if kind == "bleeding_overlap":
            assert len([e for e in loaded.engine.events if e.event_type == "GM_RIDER" and
                        "nonstacking delayed packet" in e.payload.get("rider", "")]) == 1
    else:
        assert len([c for c in target.conditions.values() if c.condition_id.startswith("condition:typed.path_ac.")]) == 2
        assert path_riders.ac(loaded.engine, target) == -2
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("stay", [False, True])
def test_thunder_reaction_movement_is_player_owned_offturn(monkeypatch, tmp_path, auto_turn, stay):
    from tests import test_hunt5_player_choices as h5
    from tests.test_hunt5_player_choices import fixture, PLAYER, FOE
    original_sheet = h5.sheet
    def staff_sheet(*args, **kwargs):
        kwargs["primary"] = "Stamina"
        document = original_sheet(*args, **kwargs)
        document["equipment"] = [{"starting_kit": {"items": [{"item_id": STAFF}]}}]
        return document
    monkeypatch.setattr(h5, "sheet", staff_sheet)
    combat, table, mid, cid, act = fixture(tmp_path, PREFIX + "thunder_runs_through_bone")
    roller_type = type(combat._load_session(mid).engine.roller)
    original = roller_type.d20
    def hit(self, **kwargs):
        roll = original(self, **kwargs)
        if kwargs.get("actor_id") == FOE and str(kwargs.get("reason")).startswith("ATTACK:"):
            return roll.model_copy(update={"natural_result": 19, "dice": (19,), "total": 19 + roll.modifier, "discarded": ()})
        return roll
    monkeypatch.setattr(roller_type, "d20", hit)
    original_roll = roller_type.roll
    def reduction(self, dice, **kwargs):
        roll = original_roll(self, dice, **kwargs)
        if "thunder_runs_through_bone" in str(kwargs.get("reason")):
            return roll.model_copy(update={"dice": (10, 10), "total": 20 + roll.modifier})
        return roll
    monkeypatch.setattr(roller_type, "roll", reduction)
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    def send(replies=()):
        return table.auto_step(mid, 0, list(replies)) if auto_turn else act(cid, replies)
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    first = result["reaction"]
    assert "thunder_runs_through_bone" in first["context"]["reaction_source_id"]
    replies = [{**first["context"], "selection": "USE"}]
    result = send(replies)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == "choice:needle.path_reaction_step"
    assert prompt["context"]["reactor_id"] == PLAYER
    assert "Thunder Runs Through Bone" in prompt["moment"]
    assert combat._load_session(mid).engine.state.actors[PLAYER].display_name in prompt["moment"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    choice = "Stay put" if stay else next(o["id"] for o in prompt["choice"]["options"] if o["id"].startswith("cell:"))
    replies.append({**prompt["context"], "selection": "USE", "option_ids": [choice]})
    assert send(replies)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    player, foe = loaded.engine.state.actors[PLAYER], loaded.engine.state.actors[FOE]
    assert (player.position.model_dump(mode="json") == before["actors"][PLAYER]["position"]) == stay
    assert player.movement_remaining_ft == before["actors"][PLAYER]["movement_remaining_ft"]
    assert foe.movement_remaining_ft == before["actors"][FOE]["movement_remaining_ft"]
    assert loaded.mechanical.replay()["status"] == "PASS"
