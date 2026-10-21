"""Optional spends and willing companions through actual casts and table pauses."""
import pytest
from combat.ext import disease, monkey, shadow
from combat.gate5_service import CombatService
from combat.gate4_adapters import ManualControllerAdapter
from combat.tabletop import ButtonStore
from tests.h1_support import ROOT
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, HOLD, PROJECTS, table_fight, on_hold
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import fixed_dice, cast_sender, commit, answer


@pytest.mark.parametrize("use", [False, True])
@pytest.mark.parametrize("auto_turn", [False, True])
def test_actual_plague_eruption_asks_before_spending_a_token(monkeypatch, tmp_path, use, auto_turn):
    combat, table, mid = table_fight(tmp_path, [disease.ERUPTION], cl=20, ask=True, ally_talents=[])
    fixed_dice(monkeypatch, [1] * 60)
    # Build the existing token using its production counted-mark API.
    on_hold(monkeypatch, lambda e: disease.add_tokens(e, e.state.actors[LEFT], e.state.actors[RIGHT], 1, "test:seed"))
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    commit(cast_sender(combat, table, mid, "Plague Eruption", at=(4, 4)))
    for _ in range(4):
        state = table.state(mid)
        menu = state["menu"]
        send = lambda answers=(): table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))
        if auto_turn and menu["actor_id"] != LEFT:
            combat.set_controller_mode(mid, actor_id=menu["actor_id"], controller_mode="LOCAL_AUTO")
            real = combat.controller
            cid = menu["end_turn"]
            class EndController:
                def choose_primary_action(self, context):
                    return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
                def __getattr__(self, name):
                    return getattr(real, name)
            combat.controller = EndController()
            send = lambda answers=(): table.auto_step(mid, 0, list(answers))
        result = send()
        if result["status"] == "REACTION_REQUIRED":
            break
        assert result["status"] == "COMMITTED"
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == LEFT
    assert "Plague Eruption" in prompt["moment"] and "Right" in prompt["moment"] and "failed" in prompt["moment"]
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    assert send()["reaction"] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send([answer(prompt, use=use)])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    e = loaded.engine
    assert disease.tokens(e, e.state.actors[LEFT], e.state.actors[RIGHT]) == (0 if use else 1)
    assert bool([r for r in e.rolls if r.reason.endswith(":token")]) == use
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("use", [False, True])
def test_actual_monkey_special_attack_asks_for_its_optional_finish(monkeypatch, tmp_path, use):
    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon." + name, "quantity": 1}
                                        for name in ("jian", "gun", "gong_jian")]}}
    combat, table, mid = table_fight(tmp_path, ["TAL_MONKEY_STYLE_STONE_SKIPPING_STRIKE"],
                                    cl=20, ask=True, ally_talents=[], kit=kit)
    fixed_dice(monkeypatch, [15, 15] + [1] * 60)
    on_hold(monkeypatch, lambda e: monkey.create(e, e.state.actors[LEFT], "test:opener", "test", counted=False))
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    send = cast_sender(combat, table, mid, "Stone-Skipping Strike", target=RIGHT)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert "Stone-Skipping Strike" in prompt["moment"] and "Right" in prompt["moment"]
    assert prompt["context"]["reactor_id"] == LEFT
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    prompts = commit(send, lambda p: (None, use if p["context"]["reaction_source_id"].endswith("monkey_talent_finish") else False))
    assert prompts
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert bool(monkey.links(loaded.engine.state.actors[LEFT])) == (not use)
    assert loaded.mechanical.replay()["status"] == "PASS"


def willing_fight(monkeypatch, tmp_path, talents, *, kit=None):
    original = CombatService.create_factory_match
    def create(service, *args, **kwargs):
        ButtonStore(service.userdata_root / "tabletop_buttons").save_reactions(PROJECTS["ally"], {"mode": "ask"}, {"opportunity_attack"})
        return original(service, *args, **kwargs)
    monkeypatch.setattr(CombatService, "create_factory_match", create)
    return table_fight(tmp_path, talents, cl=20, ask=True, ally_talents=[], kit=kit)


def next_owner_turn(table, mid):
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"


@pytest.mark.parametrize("road", [False, True])
@pytest.mark.parametrize("invite,consent", [(False, False), (True, False), (True, True)])
def test_actual_shadow_travel_asks_caster_and_companion(monkeypatch, tmp_path, road, invite, consent):
    feature = shadow.LONG_ROAD if road else "TAL_SHADOW_TWO_SHADOWS_CROSSING"
    combat, table, mid = willing_fight(monkeypatch, tmp_path, [shadow.STEP, shadow.SECOND, feature])
    if road:
        commit(cast_sender(combat, table, mid, "Second Silhouette: Shadow Anchor", at=(3, 4)))
        next_owner_turn(table, mid)
        commit(cast_sender(combat, table, mid, "Second Silhouette: Shadow Anchor", at=(8, 4)))
        next_owner_turn(table, mid)
    name = "Long Road Between Lanterns" if road else "Shadow Step + Two Shadows Crossing"
    send = cast_sender(combat, table, mid, name, at=(8, 5) if road else (6, 4))
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == LEFT
    assert name in prompt["moment"] and "Left" in prompt["moment"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    prompts = commit(send, lambda p: (ALLY, invite) if p["context"]["reactor_id"] == LEFT else ("travel", consent))
    if invite:
        assert len(prompts) == 2
        assert prompts[1]["context"]["reactor_id"] == ALLY
        assert name in prompts[1]["moment"] and "Ally" in prompts[1]["moment"]
    else:
        assert len(prompts) == 1
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    e = loaded.engine
    assert (e.state.actors[ALLY].position.x != 3) == (invite and consent)
    assert e.state.actors[LEFT].position.x != 3
    assert loaded.mechanical.replay()["status"] == "PASS"
