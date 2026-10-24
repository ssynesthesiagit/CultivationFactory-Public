"""Active-performance choices explain their current cost at the table boundary."""
import pytest

from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r10_fixup_support import cast_sender
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY, RIGHT, HOLD

HYMN = "tianxia.talent.music.healing_hymn"
SYMPHONY = "tianxia.talent.music.symphony_of_heaven_and_earth"


@pytest.mark.parametrize("auto,use", [(False, False), (False, True), (True, True)])
@pytest.mark.parametrize("feature,name", [(HYMN, "Healing Hymn"), (SYMPHONY, "Symphony of Heaven and Earth")])
def test_hymn_followup_cost_and_end_turn_survive_commit_reload(monkeypatch, tmp_path, auto, use, feature, name):
    combat, table, mid = table_fight(tmp_path, [feature], ask=True, ally_talents=[])
    if feature == SYMPHONY:
        assert cast_sender(combat, table, mid, "Choose Symphony", contains="Movement of Mercy")()["status"] == "COMMITTED"
    assert cast_sender(combat, table, mid, name)()["status"] == "COMMITTED"
    def hurt(engine):
        ally = engine.state.actors[ALLY]
        engine._commit_damage(ally, 10, "FORCE", HOLD, RIGHT, None, reaction_depth=0)
    on_hold(monkeypatch, hurt)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    state = table.state(mid)
    menu = state["menu"]
    engine = combat._load_session(mid).engine
    end = next(c for c in engine.legal_candidates() if c.kind.value == "END_TURN")
    if auto:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
        real = combat.controller
        class EndController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (end.candidate_id, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = EndController()
    def send(answers=()):
        return table.auto_step(mid, 0, list(answers)) if auto else table.act(
            mid, end.candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    if not auto:
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        # fix/hunt17 (merge 6ffd7ca2) explicitly names the free Hymn economy.
        if feature == HYMN:
            assert prompt["cost"] == "No additional resource or Reaction cost"
            assert prompt["table_note"] == (
                "The activation cost was paid when Healing Hymn began. This turn-end healing choice is free.")
        else:
            assert prompt["cost"] == "No additional cost; the performance is already active"
        assert prompt["action"] == "End turn"
        assert name in prompt["trigger"] and "ends its turn" in prompt["trigger"]
        assert send()["reaction"] == prompt
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        result = send([{**prompt["context"], "selection": "USE" if use else "DECLINE",
                        "option_ids": [ALLY] if use else []}])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    owner, ally = (loaded.engine.state.actors[a] for a in (LEFT, ALLY))
    assert owner.resources == before["actors"][LEFT]["resources"]
    assert owner.reaction_available == before["actors"][LEFT]["reaction_available"]
    assert (ally.current_hp > before["actors"][ALLY]["current_hp"]) == use
    if feature == HYMN:
        assert bool(owner.turn_flags.get(f"_round_music_hymn:{ALLY}")) == use
    else:
        assert any(k.startswith("_round_music_mercy:") and k.endswith(ALLY) and v
                   for k, v in owner.turn_flags.items()) == use
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_hymn_recipient_selector_is_free_after_spending_both_actions(monkeypatch, tmp_path):
    """The active hymn's recipient choice never reuses its paid activation."""
    combat, table, mid = table_fight(tmp_path, [HYMN], ask=True, ally_talents=[])
    initial = combat._load_session(mid).engine.state.actors[LEFT].resources.copy()
    assert cast_sender(combat, table, mid, "Healing Hymn")()["status"] == "COMMITTED"
    activated = combat._load_session(mid).engine.state.actors[LEFT].resources.copy()
    assert sum(initial.values()) - sum(activated.values()) == 4
    assert act(table, mid, "system:combat.dodge")["status"] == "COMMITTED"

    def hurt(engine):
        engine._commit_damage(engine.state.actors[ALLY], 10, "FORCE", HOLD, RIGHT, None, reaction_depth=0)
    on_hold(monkeypatch, hurt)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    combat = CombatService(ROOT, tmp_path)
    from combat.tabletop_service import TabletopService
    table = TabletopService(combat, tmp_path)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = act(table, mid, "end")
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["reaction"] == "Healing Hymn"
    assert prompt["action"] == "End turn"
    # fix/hunt17 (merge 6ffd7ca2) separates paid activation from this free choice.
    assert prompt["cost"] == "No additional resource or Reaction cost"
    assert prompt["table_note"] == (
        "The activation cost was paid when Healing Hymn began. This turn-end healing choice is free.")
    assert any(o["id"] == ALLY for o in prompt["choice"]["options"])
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    state = table.state(mid)
    menu = state["menu"]
    result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
        state["last_sequence"], [{**prompt["context"], "selection": "USE", "option_ids": [ALLY]}])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].resources == activated
    assert loaded.engine.state.actors[LEFT].reaction_available == before["actors"][LEFT]["reaction_available"]
    assert loaded.engine.state.actors[ALLY].current_hp > before["actors"][ALLY]["current_hp"]
    assert loaded.mechanical.replay()["status"] == "PASS"
