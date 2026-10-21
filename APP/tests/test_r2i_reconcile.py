"""Round17 integration regressions using actual table previews and reloads."""
import importlib

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

R = importlib.import_module("tests.test_riders_lane2")


def fixture(tmp_path, talents, sphere, *, third=False, counter=False, sweep=False):
    ids = [R.ME, R.FOE, *([R.ALLY] if third else [])]
    bundles = []
    for i, aid in enumerate(ids):
        sheet = R.A._sheet(sphere if i == 0 else None, talents if i == 0 else [], R.KIT)
        if counter and i == 0:
            iron = R.A._sheet(R.IRON_FIST, [], R.KIT)["spheres_and_talents"]
            sheet["spheres_and_talents"]["sphere_record_ids"] += iron["sphere_record_ids"]
            sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"] += iron["automatic_sphere_component_record_ids"]
        bundle = compile_character(sheet,
                                   actor_id=aid, reaction_plan={"ask": True} if i == 0 else None)
        bundle["actor_template"].update(armor_class=1000 if counter and i == 0 else 0, maximum_hp=1000, speed_ft=0, initiative_bonus=100 - 100 * i)
        if sweep:
            bundle["actor_template"]["speed_ft"] = 30
            bundle["actor_template"]["saving_throws"] = {"STR": 1000, "DEX": 1000} if aid == R.FOE else {"STR": -100, "DEX": -100}
        for action in bundle["action_catalog"]:
            if action["parameters"].get("typed"):
                action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
                if sweep:
                    action["parameters"]["typed"]["numbers"]["save_dc"] = 50
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(R.ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="R2I-TABLE", typed_bundles=bundles,
        roster_setup={"primary_actor_ids": ids,
                      "team_by_actor": {R.ME: "team:a", R.FOE: "team:a" if third else "team:b", R.ALLY: "team:b"},
                      "starting_positions": {R.ME: {"x": 3, "y": 6}, R.FOE: {"x": 4, "y": 6}, R.ALLY: {"x": 4, "y": 7}}})
    table = TabletopService(combat, tmp_path)
    return combat, table, session.match_id


def act(combat, table, mid, name, target=None, answers=()):
    menu = table.state(mid)["menu"]
    if name == "END":
        cid = menu["end_turn"]
    else:
        cid = next(c["candidate_id"] for c in combat.decision(mid)["context"]["legal_candidates"]
                   if c["display_name"] == name and (target is None or target in c["target_ids"]))
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_paid_single_option_player_choice_table_commit_reload(tmp_path, auto_turn, selection):
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_FORCE_COMPLETION", "TAL_IRON_FIST_COUNTER_PALM"], R.YANG, counter=True)
    assert act(combat, table, mid, "Kindle the Rising", R.ME)["status"] == "COMMITTED"
    assert act(combat, table, mid, "END")["status"] == "COMMITTED"
    menu = table.state(mid)["menu"]
    assert menu["actor_id"] == R.FOE
    candidate = next(c for c in combat.decision(mid)["context"]["legal_candidates"]
                     if c["display_name"] == "Fu (Short Axe) attack" and R.ME in c["target_ids"])
    if auto_turn:
        real = combat.controller

        class AttackController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (candidate["candidate_id"], ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = AttackController()
        combat.set_controller_mode(mid, actor_id=R.FOE, controller_mode="LOCAL_AUTO")

    def send(answers):
        if auto_turn:
            return table.auto_step(mid, 0, answers)
        return table.act(mid, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, answers)

    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    answers = []
    paid = None
    for _ in range(6):
        result = send(answers)
        if result["status"] == "COMMITTED":
            break
        prompt = result["reaction"]
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        answer = {**prompt["context"], "selection": "USE"}
        if prompt["context"]["reaction_source_id"].startswith("choice:paid_option."):
            paid = prompt
            assert prompt["reaction"] == "Force Completion"
            assert "Counter Palm" in prompt["moment"]
            assert "0" != prompt["choice"]["options"][0]["label"]
            assert prompt["choice"]["allow_decline"] and len(prompt["choice"]["options"]) == 1
            answer.update(selection=selection, option_ids=[] if selection == "DECLINE" else [prompt["choice"]["options"][0]["id"]])
        answers.append(answer)
    assert paid is not None and result["status"] == "COMMITTED"
    loaded = CombatService(R.ROOT, tmp_path)._load_session(mid)
    after = loaded.engine.state.model_dump(mode="json")
    assert after == combat._load_session(mid).engine.state.model_dump(mode="json")
    assert loaded.mechanical.replay()["status"] == "PASS"
    cost = before["actors"][R.ME]["resources"]["resource:core.stamina"] - after["actors"][R.ME]["resources"]["resource:core.stamina"]
    assert cost == (2 if selection == "USE" else 0)
    moved = after["actors"][R.FOE]["position"] != before["actors"][R.FOE]["position"]
    assert moved == (selection == "USE")


@pytest.mark.parametrize("auto_turn", [False, True])
def test_flowing_combination_off_turn_decline_does_not_spend_use_or_movement(tmp_path, auto_turn):
    combat, table, mid = R._empty_palm_table(tmp_path, ask=True, counter=True,
        counter_form="TAL_IRON_FIST_FLOWING_COMBINATION")
    menu = table.state(mid)["menu"]
    candidate = next(c for c in combat.decision(mid)["context"]["legal_candidates"]
                     if c["display_name"] == "Fu (Short Axe) attack" and R.ME in c["target_ids"])
    if auto_turn:
        real = combat.controller

        class AttackController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (candidate["candidate_id"], ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = AttackController()
        combat.set_controller_mode(mid, actor_id=R.FOE, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.model_dump(mode="json")

    def send(answers):
        return table.auto_step(mid, 0, answers) if auto_turn else table.act(mid, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, answers)

    first = send([])
    counter = {**first["reaction"]["context"], "selection": "USE"}
    second = send([counter])
    assert second["status"] == "REACTION_REQUIRED"
    prompt = second["reaction"]
    assert prompt["reaction"] == "Flowing Combination"
    assert "Counter Palm" in prompt["moment"]
    assert prompt["choice"]["allow_decline"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send([counter, {**prompt["context"], "selection": "DECLINE"}])["status"] == "COMMITTED"
    loaded = CombatService(R.ROOT, tmp_path)._load_session(mid)
    assert not loaded.engine.state.actors[R.ME].turn_flags.get("riders_flowing_used")
    for aid in (R.ME, R.FOE):
        assert loaded.engine.state.actors[aid].movement_remaining_ft == before["actors"][aid]["movement_remaining_ft"]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_source_owned_refresh_and_consumption_preserve_unrelated_instances():
    from combat.ext import next_attack_damage as nad, damage_taken_bonus as dtb, overstrain
    from combat.typed_executor import Context

    engine = R._trio([], sphere=R.IRON_FIST)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == R.ME and a.display_name == R.STRIKE)
    target = engine.state.actors[R.FOE]
    for module, name, effect in [(nad, nad.CONDITION, {"amount": 8}), (dtb, dtb.CONDITION, {"amount": 4})]:
        for aid in (R.ME, R.ALLY, R.ME):
            ctx = Context(engine, engine.state.actors[aid], action, None, action.parameters["typed"], [target], target)
            module.apply(ctx, {**effect, "applies_to": "target", "duration": "until_end_of_next_turn"})
        assert sorted(c.source_actor_id for c in target.conditions.values() if c.condition_id == name) == sorted([R.ME, R.ALLY])
    for owner, technique in [(R.ME, "match"), (R.ALLY, "different")]:
        engine._apply_condition(target, overstrain.WATCH, "test:watch", owner, expires_on="UNTIL_REMOVED",
                                data={"technique": technique, "first_use": "first"})
    ctx = Context(engine, target, action, None, {"source": "match", "numbers": {}}, [], None)
    overstrain.repeated(ctx)
    watches = [c for c in target.conditions.values() if c.condition_id == overstrain.WATCH]
    assert len(watches) == 1 and watches[0].source_actor_id == R.ALLY
    R._answer_options(engine, lambda req: [])
    R.A._use(engine, R.STRIKE, R.FOE)
    assert not any(c.condition_id in (dtb.CONDITION, dtb.PENDING) for c in target.conditions.values())


def test_two_bell_casters_preserve_instances_through_table_reload_and_consume_once(tmp_path):
    from combat.ext.next_attack_damage import CONDITION

    ids = [R.ME, R.ALLY, R.FOE]
    bundles = []
    for i, aid in enumerate(ids):
        owner = aid != R.FOE
        bundle = compile_character(R.A._sheet(R.IRON_FIST if owner else None, [R.BELL] if owner else [], R.KIT), actor_id=aid)
        bundle["actor_template"].update(armor_class=0, maximum_hp=1000, initiative_bonus=100 - 100 * i)
        for action in bundle["action_catalog"]:
            if action["parameters"].get("typed"):
                action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(R.ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="R2I-OWNERS", typed_bundles=bundles,
        roster_setup={"primary_actor_ids": ids, "team_by_actor": {R.ME: "team:a", R.ALLY: "team:a", R.FOE: "team:b"},
                      "starting_positions": {R.ME: {"x": 3, "y": 6}, R.ALLY: {"x": 4, "y": 7}, R.FOE: {"x": 4, "y": 6}}})
    table, mid = TabletopService(combat, tmp_path), session.match_id
    # Each caster first Opens the target with a real strike. The next round's
    # real strike uses Bell's default Softened blows option against that mark.
    for caster in (R.ME, R.ALLY):
        assert table.state(mid)["menu"]["actor_id"] == caster
        assert act(combat, table, mid, R.STRIKE, R.FOE)["status"] == "COMMITTED"
        assert act(combat, table, mid, "END")["status"] == "COMMITTED"
    assert act(combat, table, mid, "END")["status"] == "COMMITTED"
    for caster in (R.ME, R.ALLY):
        assert table.state(mid)["menu"]["actor_id"] == caster
        assert act(combat, table, mid, R.STRIKE, R.FOE)["status"] == "COMMITTED"
        loaded = CombatService(R.ROOT, tmp_path)._load_session(mid)
        owners = {c.source_actor_id for c in loaded.engine.state.actors[R.FOE].conditions.values() if c.condition_id == CONDITION}
        assert caster in owners
        if caster == R.ALLY:
            assert owners == {R.ME, R.ALLY}
        assert act(combat, table, mid, "END")["status"] == "COMMITTED"
    assert act(combat, table, mid, "Fu (Short Axe) attack", R.ME)["status"] == "COMMITTED"
    loaded = CombatService(R.ROOT, tmp_path)._load_session(mid)
    assert not any(c.condition_id == CONDITION for c in loaded.engine.state.actors[R.FOE].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_falling_leaf_speed_penalty_is_anchored_to_striker():
    from combat.ext import iron_fist_riders
    from combat.ext.effect_durations import sweep
    from combat.typed_executor import Context

    engine = R._trio(["TAL_IRON_FIST_FALLING_LEAF_SWEEP"], sphere=R.IRON_FIST, ally_at=(4, 7))
    engine.state.actors[R.ALLY].saving_throws["DEX"] = 100
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Shove: Prone")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id)
    from combat.gate2_runtime_models import ActionIntent
    intent = ActionIntent(intent_id="R2I-SWEEP", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                          state_version=candidate.state_version, actor_id=R.ME)
    R._answer_options(engine, lambda req: [R.ALLY])
    ctx = Context(engine, engine.state.actors[R.ME], action, intent, action.parameters["typed"], [engine.state.actors[R.FOE]], engine.state.actors[R.FOE])
    iron_fist_riders.sweep(ctx, engine.state.actors[R.FOE])
    speed = [m for m in engine.state.actors[R.ALLY].modifiers.values() if m.target_field == "speed_ft"]
    assert speed and all(m.expires_on == "START_OF_SOURCE_NEXT_TURN" for m in speed)
    engine.state.current_actor_id = R.ALLY
    engine.state.actors[R.ALLY].turns_started += 1
    sweep(engine, engine.state.actors[R.ALLY], "START_OF_TURN")
    assert any(m.modifier_id in engine.state.actors[R.ALLY].modifiers for m in speed)


def test_falling_leaf_source_expiry_table_preview_reload_and_real_turns(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_IRON_FIST_FALLING_LEAF_SWEEP"], R.IRON_FIST, third=True, sweep=True)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    first = act(combat, table, mid, "Shove: Prone", R.ALLY)
    assert first["status"] == "REACTION_REQUIRED"
    prompt = first["reaction"]
    assert "Falling Leaf Sweep" in prompt["reaction"] and "Shove: Prone" in prompt["moment"]
    assert any(o["id"] == R.FOE and o["label"] != R.FOE for o in prompt["choice"]["options"])
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert act(combat, table, mid, "Shove: Prone", R.ALLY,
               [{**prompt["context"], "selection": "USE", "option_ids": [R.FOE]}])["status"] == "COMMITTED"
    def held():
        return [m for m in CombatService(R.ROOT, tmp_path)._load_session(mid).engine.state.actors[R.FOE].modifiers.values()
                if m.target_field == "speed_ft"]
    assert held() and all(m.expires_on == "START_OF_SOURCE_NEXT_TURN" for m in held())
    assert act(combat, table, mid, "END")["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] == R.FOE and held()
    assert act(combat, table, mid, "END")["status"] == "COMMITTED"
    assert act(combat, table, mid, "END")["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] == R.ME and not held()
    assert CombatService(R.ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"
