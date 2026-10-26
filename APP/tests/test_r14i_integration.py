"""Lane 14 decisions across real table preview, commit, reload and replay."""

import pytest

from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.ext.riders14_research import KNOWN
from combat.ext.mind_hidden_eye import ANALYZED
from tests.h1_support import ROOT
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, table_fight, answer_action, on_hold

PREFIX = "TAL_THE_HIDDEN_EYE_"


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
@pytest.mark.parametrize("worthy", [False, True])
def test_incarnation_turn_start_choice_commit_reload_replay(tmp_path, auto_turn, selection, worthy):
    talents = [PREFIX + "SOVEREIGN_HIDDEN_EYE_INCARNATION"]
    if worthy:
        talents.append(PREFIX + "WORTHY_OPPONENT")
    combat, table, mid = table_fight(tmp_path, talents,
                                     ask=True, ally_talents=[])
    assert answer_action(table, mid, PREFIX + "SOVEREIGN_HIDDEN_EYE_INCARNATION")["status"] == "COMMITTED"
    real = combat.controller

    class EndController:
        def choose_primary_action(self, context):
            candidate = next(c for c in context.legal_candidates if c.kind.value == "END_TURN")
            return ManualControllerAdapter(lambda _context: (candidate.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = EndController()
    for _ in range(4):
        state = table.state(mid)
        menu = state["menu"]
        actor = menu["actor_id"]
        ai = auto_turn and actor != LEFT
        if ai:
            combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")
        before = combat._load_session(mid).engine.state.model_dump(mode="json")

        def send(answers):
            if ai:
                return table.auto_step(mid, 0, answers)
            return table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0, answers)

        result = send([])
        if result["status"] == "REACTION_REQUIRED":
            break
        assert result["status"] == "COMMITTED"
    assert result["status"] == "REACTION_REQUIRED"
    assert ai == auto_turn
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == LEFT
    assert prompt["context"]["reaction_source_id"] == "choice:needle.eye_auto"
    assert "Sovereign Hidden Eye Incarnation" in prompt["moment"]
    assert "Left" in prompt["moment"]
    assert prompt["choice"]["allow_decline"]
    assert all("actor:" not in o["label"] for o in prompt["choice"]["options"])
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send([])["reaction"] == prompt
    answers = [{**prompt["context"], "selection": selection}]
    if selection == "USE":
        answers[0]["option_ids"] = [RIGHT]
    result = send(answers)
    if selection == "USE":
        if worthy:
            assert result["status"] == "REACTION_REQUIRED"
            rival_prompt = result["reaction"]
            assert rival_prompt["context"]["reaction_source_id"] == "choice:needle.eye_rival"
            assert all(t in rival_prompt["moment"] for t in ("Worthy Opponent", "Analyze", "Right"))
            answers.append({**rival_prompt["context"], "selection": "USE", "option_ids": ["designate"]})
            result = send(answers)
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert prompt["context"]["reaction_source_id"] == "choice:needle.eye_learn"
        assert "Analyze" in prompt["moment"] and "Right" in prompt["moment"]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": ["Armor Class"]})
        result = send(answers)
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    learned = [c for c in loaded.engine.state.actors[LEFT].conditions.values() if c.condition_id == KNOWN]
    analyzed = [c for c in loaded.engine.state.actors[RIGHT].conditions.values()
                if c.condition_id == ANALYZED and c.source_actor_id == LEFT]
    assert len(learned) == len(analyzed) == (1 if selection == "USE" else 0)
    if learned:
        assert learned[0].data["name"] == "Armor Class"
    if worthy and selection == "USE":
        from combat.ext.riders14_eye import RIVAL
        assert any(c.condition_id == RIVAL and c.data["target_id"] == RIGHT
                   for c in loaded.engine.state.actors[LEFT].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_ai_incarnation_owner_chooses_automatically(tmp_path):
    combat, table, mid = table_fight(tmp_path, [PREFIX + "SOVEREIGN_HIDDEN_EYE_INCARNATION"],
                                     ask=True, ally_talents=[])
    assert answer_action(table, mid, PREFIX + "SOVEREIGN_HIDDEN_EYE_INCARNATION")["status"] == "COMMITTED"
    real = combat.controller

    class EndController:
        def choose_primary_action(self, context):
            candidate = next(c for c in context.legal_candidates if c.kind.value == "END_TURN")
            return ManualControllerAdapter(lambda _context: (candidate.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = EndController()
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    assert table.auto_step(mid, 0)["status"] == "COMMITTED"
    for _ in range(4):
        if table.state(mid)["menu"]["actor_id"] == LEFT:
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(c.condition_id == KNOWN for c in loaded.engine.state.actors[LEFT].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_discern_sharing_preserves_other_caster_through_table_reload(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [PREFIX + "DISCERN_ILLUSIONS"], ask=True)
    cid = "condition:typed.eye_discern_illusions"

    def other_share(engine):
        engine._apply_condition(engine.state.actors[ALLY], cid, "test:other-eye", RIGHT,
                                expires_on="UNTIL_REMOVED", data={"until_round": 99})

    on_hold(monkeypatch, other_share)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    assert answer_action(table, mid, ".riders14.discern", ALLY)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    shares = [c for c in loaded.engine.state.actors[ALLY].conditions.values() if c.condition_id == cid]
    assert {c.source_actor_id for c in shares} == {LEFT, RIGHT}
    assert all(type(c.data["until_round"]) is int for c in shares)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_assault_single_option_can_be_declined_on_other_turn(monkeypatch, tmp_path, auto_turn, selection):
    from combat.typed_executor import Context, block_attack
    from combat.ext.mind_hidden_eye import mark_analyzed
    from combat.gate2_runtime_models import ActionDefinition
    from tests.test_riders_lane14 import bundle
    from tests.h1_support import script

    # The synthetic off-turn attack still needs the same carried, readied dart
    # as a normal attack. A lone dart is held by the ordinary initial loadout.
    dart_kit = {"starting_kit": {"items": [
        {"item_id": "tianxia.mortal.weapon.fei_biao", "name": "Fei Biao", "quantity": 1}]}}
    combat, table, mid = table_fight(tmp_path, [PREFIX + "ASSAULT_ANALYSIS"], ask=True,
                                     ally_talents=[], kits={"left": dart_kit})
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"

    def strike(engine):
        actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        mark_analyzed(engine, actor, target, "test:analyze")
        compiled = bundle(PREFIX + "ASSAULT_ANALYSIS", actor_id=LEFT,
                          scores={"STR": 1, "DEX": 2, "CON": 5, "INT": 0, "WIS": 0, "CHA": 0})
        row = next(r for r in compiled["action_catalog"] if r["display_name"] == "Fei Biao (Flying Dart) thrown")
        action = ActionDefinition.model_validate(row)
        engine.action_catalog[action.source_definition_id] = action
        from combat.ext.hand_occupancy import weapon_allowed
        assert weapon_allowed(engine, actor, action) is True
        script(engine, [19, 19, 1, 1])
        typed = action.parameters["typed"]
        block_attack(Context(engine, actor, action, engine._active_intent, typed, [target], target), typed["effects"][0])

    on_hold(monkeypatch, strike)
    state = table.state(mid)
    menu = state["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"]
               if g["source_definition_id"] == "system:combat.hold_position")
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
        real = combat.controller

        class HoldController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = HoldController()

    def send(answers):
        if auto_turn:
            return table.auto_step(mid, 0, answers)
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers)

    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send([])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == LEFT
    assert prompt["context"]["reaction_source_id"] == "choice:needle.eye_assault"
    assert all(t in prompt["moment"] for t in ("Assault Analysis", "Right", "Fei Biao"))
    assert prompt["choice"]["allow_decline"] and len(prompt["choice"]["options"]) == 1
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answers = [{**prompt["context"], "selection": selection, "option_ids": ["substitute"] if selection == "USE" else []}]
    result = send(answers)
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    rolls = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == LEFT]
    assert rolls[-1].payload["modifier"] == (5 if selection == "USE" else 1)
    damage = [e for e in loaded.engine.events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == LEFT]
    assert damage[-1].payload["expression"].endswith("+5" if selection == "USE" else "+1")
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_cooperative_stealth_choice_preserves_other_caster(monkeypatch, tmp_path, auto_turn, selection):
    from combat.ext.eye_coordination import COOP_STEALTH_TAG
    from combat.stealth import HIDDEN

    combat, table, mid = table_fight(tmp_path, [PREFIX + "COOPERATIVE_STEALTH"], ask=True, ally_talents=[])
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"

    def hide(engine):
        engine._apply_condition(engine.state.actors[ALLY], COOP_STEALTH_TAG, "test:other-eye", RIGHT,
                                expires_on="START_OF_SOURCE_NEXT_TURN", data={"total": 25})
        engine._apply_condition(engine.state.actors[LEFT], HIDDEN, "test:hide", LEFT,
                                expires_on="UNTIL_REMOVED", data={"stealth_total": 30})

    on_hold(monkeypatch, hide)
    state = table.state(mid)
    menu = state["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"]
               if g["source_definition_id"] == "system:combat.hold_position")
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
        real = combat.controller

        class HoldController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = HoldController()

    def send(answers):
        if auto_turn:
            return table.auto_step(mid, 0, answers)
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers)

    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send([])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == LEFT
    assert prompt["choice"]["allow_decline"]
    assert all(t in prompt["moment"] for t in ("Cooperative Stealth", "Left", "Hide"))
    assert all("actor:" not in o["label"] for o in prompt["choice"]["options"])
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    result = send([{**prompt["context"], "selection": selection,
                    "option_ids": [ALLY] if selection == "USE" else []}])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    shares = [c for c in loaded.engine.state.actors[ALLY].conditions.values() if c.condition_id == COOP_STEALTH_TAG]
    assert {c.source_actor_id for c in shares} == ({LEFT, RIGHT} if selection == "USE" else {RIGHT})
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
def test_uncanny_nested_analyze_choices_count_and_reload(monkeypatch, tmp_path, auto_turn):
    """Finish the reviewed Initiative task before the off-turn trigger.

    fix/hunt24 (b174bec5, approved FIX24r2.review.md, merged 7f724b64)
    persists Rapid Analysis before turn one. Decline that separate attempt;
    the Uncanny Stalker choice/count/focus/reload assertions stay unchanged.
    """
    from combat.ext.riders14_eye import ATTEMPTS
    from combat.fight_setup import SOURCE as SETUP
    from tests.h1_support import script

    talents = [PREFIX + t for t in ("UNCANNY_STALKER", "RAPID_ANALYSIS", "GREATER_STALKER", "PERSISTENT_ANALYSIS")]
    combat, table, mid = table_fight(tmp_path, talents, ask=True, ally_talents=[])
    state = table.state(mid)
    menu = state["menu"]
    setup = next(g["options"][0]["candidate_id"] for g in menu["actions"]
                 if g["source_definition_id"] == SETUP)
    result = table.act(mid, setup, menu["decision_id"], menu["state_version"], 0)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == "choice:needle.rapid_analysis_target"
    assert table.act(mid, setup, menu["decision_id"], menu["state_version"], 0,
                     [{**prompt["context"], "selection": "DECLINE"}])["status"] == "COMMITTED"
    assert not CombatService(ROOT, tmp_path)._load_session(mid).engine.state.setup_tasks
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"

    def enter(engine):
        engine._apply_condition(engine.state.actors[LEFT], "condition:typed.invisible", "test:hidden", LEFT,
                                expires_on="UNTIL_REMOVED")
        script(engine, [19, 19])
        engine._append_event("MOVEMENT_COMMITTED", "test:enter-range", actor_id=RIGHT,
                             payload={"destination": engine.state.actors[RIGHT].position.model_dump(mode="json"),
                                      "cost_ft": 0, "footprint_step": True,
                                      "path": [{"x": 25, "y": 4}, engine.state.actors[RIGHT].position.model_dump(mode="json")]})

    on_hold(monkeypatch, enter)
    state = table.state(mid)
    menu = state["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"]
               if g["source_definition_id"] == "system:combat.hold_position")
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
        real = combat.controller

        class HoldController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = HoldController()

    def send(answers):
        if auto_turn:
            return table.auto_step(mid, 0, answers)
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers)

    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    old_used = sum(int(c.data["used"]) for c in combat._load_session(mid).engine.state.actors[LEFT].conditions.values()
                   if c.condition_id == ATTEMPTS and c.data["target_id"] == RIGHT)
    answers, choices = [], []
    for _ in range(6):
        result = send(answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert prompt["context"]["reactor_id"] == LEFT
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        source = prompt["context"]["reaction_source_id"]
        choices.append(source)
        option = {"choice:needle.eye_uncanny": "analyze", "choice:needle.eye_approach": "Investigation",
                  "choice:needle.eye_learn": "Armor Class"}[source]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [option]})
    assert result["status"] == "COMMITTED"
    assert choices == ["choice:needle.eye_uncanny", "choice:needle.eye_approach", "choice:needle.eye_learn"]
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert sum(int(c.data["used"]) for c in actor.conditions.values()
               if c.condition_id == ATTEMPTS and c.data["target_id"] == RIGHT) == old_used + 1
    assert any(c.condition_id == KNOWN and c.data["name"] == "Armor Class" and c.data["target_id"] == RIGHT
               for c in actor.conditions.values())
    assert not actor.reaction_available and actor.resources["resource:core.martial_focus"] == 0
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
def test_discern_duration_expires_when_caster_has_no_more_turns(monkeypatch, tmp_path, auto_turn):
    combat, table, mid = table_fight(tmp_path, [PREFIX + "DISCERN_ILLUSIONS"], ask=True, ally_talents=[])
    assert answer_action(table, mid, ".riders14.discern", ALLY)["status"] == "COMMITTED"
    cid = "condition:typed.eye_discern_illusions"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    shared = next(c for c in loaded.engine.state.actors[ALLY].conditions.values() if c.condition_id == cid)
    deadline = int(shared.data["until_round"])
    assert shared.expires_on.startswith("START_OF_SLOT_AT:")
    _, expiry_round, expiry_slot = shared.expires_on.split(":")
    expiry = (int(expiry_round), int(expiry_slot))
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"

    def kill(engine):
        target = engine.state.actors[LEFT]
        engine._commit_damage(target, 1000, "FORCE", "test:dead-caster", RIGHT, None, reaction_depth=0)

    on_hold(monkeypatch, kill)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    assert not CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[LEFT].active
    real = combat.controller

    class EndController:
        def choose_primary_action(self, context):
            candidate = next(c for c in context.legal_candidates if c.kind.value == "END_TURN")
            return ManualControllerAdapter(lambda _context: (candidate.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = EndController()
    for _ in range(12):
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        if (loaded.engine.state.round_number, loaded.engine.state.current_slot_index) >= expiry:
            break
        actor = table.state(mid)["menu"]["actor_id"]
        if auto_turn:
            combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")
            result = table.auto_step(mid, 0)
        else:
            result = act(table, mid, "end")
        assert result["status"] == "COMMITTED"
    assert loaded.engine.state.round_number >= deadline
    assert not any(c.condition_id == cid for c in loaded.engine.state.actors[ALLY].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"
