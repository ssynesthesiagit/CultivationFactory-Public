"""Turn decisions through the table's commit, reload and replay boundary."""
import pytest
from tests.legacy_fight_support import legacy_zero_hp

pytestmark = pytest.mark.usefixtures("legacy_zero_hp")

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY, RIGHT, HOLD
from tests.test_lock2_persistence import act

PLAGUE = "tianxia.talent.disease.living_plague"


def reload_table(combat, data, mid):
    fresh = CombatService(combat.source_root, data)
    session = fresh._load_session(mid)
    assert session.verify()["status"] == "PASS"
    return session.engine, TabletopService(fresh, data)


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO", "API_AUTO"])
def test_defeated_current_actor_ends_without_a_player_or_provider_decision(tmp_path, monkeypatch, mode):
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    def defeat(engine):
        engine._commit_damage(engine.state.actors[LEFT], 60, "FORCE", "test:defeat", RIGHT, None, reaction_depth=0)
    on_hold(monkeypatch, defeat)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode=mode)
    engine, fresh = reload_table(combat, tmp_path, mid)
    assert not engine.state.actors[LEFT].active
    state = fresh.state(mid)
    assert state["menu"]["actor_id"] == LEFT
    assert state["menu"]["manual"] is False
    assert state["menu"]["control_mode"] == "LOCAL_AUTO"
    assert state["unavailable_reasons"] == {}
    result = fresh.auto_step(mid, state["last_sequence"])
    assert result["status"] == "COMMITTED"
    engine, _ = reload_table(combat, tmp_path, mid)
    assert engine.state.current_actor_id != LEFT
    assert any(e.event_type == "TURN_ENDED" and e.actor_id == LEFT for e in engine.events)
    session = combat._load_session(mid)
    assert combat._read_metadata(mid, session)["participant_control_modes"][LEFT] == mode


@pytest.mark.parametrize("life", [None, "STABLE"])
def test_unable_actor_keeps_expiry_boundaries_but_never_gets_a_blank_menu(tmp_path, monkeypatch, life):
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    if life:
        from tests.test_lock_choices import install
        install(monkeypatch, "zero_hp", lambda engine, target, *args: life if target.entity_id == ALLY else None)
    def defeat(engine):
        target = engine.state.actors[ALLY]
        engine._apply_condition(target, "condition:typed.sol112_start", "test:expiry", LEFT,
                                expires_on="START_OF_SELF_NEXT_TURN")
        engine._apply_condition(target, "condition:typed.sol112_end", "test:expiry", LEFT,
                                    expires_on="END_OF_HOLDER_NEXT_TURN")
        engine._commit_damage(target, 60, "FORCE", "test:defeat", RIGHT, None, reaction_depth=0)
    on_hold(monkeypatch, defeat)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    before = combat._load_session(mid).engine.state.event_sequence
    for _ in range(4):
        state = table.state(mid)
        assert state["menu"]["actor_id"] != ALLY
        assert act(table, mid, "end")["status"] == "COMMITTED"
    engine, _ = reload_table(combat, tmp_path, mid)
    actor = engine.state.actors[ALLY]
    assert actor.turns_started >= 1
    assert not any(c.source_definition_id == "test:expiry" for c in actor.conditions.values())
    events = [e for e in engine.events if e.sequence > before and e.actor_id == ALLY]
    assert any(e.event_type == "TURN_STARTED" for e in events)
    assert any(e.event_type == "TURN_ENDED" for e in events)


def test_conscious_zero_hp_actor_keeps_its_manual_decisions(tmp_path, monkeypatch):
    from tests.test_lock_choices import install
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    install(monkeypatch, "zero_hp", lambda engine, target, *args: "CONSCIOUS" if target.entity_id == LEFT else None)
    def damage(engine):
        engine._commit_damage(engine.state.actors[LEFT], 60, "FORCE", "test:damage", RIGHT, None, reaction_depth=0)
    on_hold(monkeypatch, damage)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    engine, table = reload_table(combat, tmp_path, mid)
    actor = engine.state.actors[LEFT]
    assert actor.current_hp == 0 and actor.active and actor.life_state == "CONSCIOUS"
    assert table.state(mid)["menu"]["manual"] is True


@pytest.mark.parametrize("natural", [10, 20])
def test_death_save_runs_before_skip_and_recovery_keeps_the_players_turn(tmp_path, monkeypatch, natural):
    from tests.test_lock_choices import install
    from tests.h1_support import script
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    install(monkeypatch, "zero_hp", lambda engine, target, *args: "DYING" if target.entity_id == ALLY else None)
    def roll_on_boundary(engine, actor):
        if actor.entity_id == ALLY:
            script(engine, [natural])
    install(monkeypatch, "turn_boundary_start", roll_on_boundary)
    def damage(engine):
        engine._commit_damage(engine.state.actors[ALLY], 60, "FORCE", "test:damage", RIGHT, None, reaction_depth=0)
    on_hold(monkeypatch, damage)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    for _ in range(4):
        assert act(table, mid, "end")["status"] == "COMMITTED"
        engine, table = reload_table(combat, tmp_path, mid)
        if any(e.event_type == "CHECK_ROLLED" and e.source_definition_id == "system:death_save" for e in engine.events):
            break
    check = next(e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.source_definition_id == "system:death_save")
    assert check.payload["actor"]["natural_result"] == natural
    if natural == 20:
        assert engine.state.current_actor_id == ALLY
        assert engine.state.actors[ALLY].current_hp == 1
        assert engine.state.actors[ALLY].action_available
        assert table.state(mid)["menu"]["manual"] is True
    else:
        assert engine.state.current_actor_id != ALLY
        assert engine.state.actors[ALLY].life_state == "DYING"


def test_waiting_plague_is_not_present_and_commanded_plague_acts_with_ai_after_reload(tmp_path):
    combat, table, mid = table_fight(tmp_path, [PLAGUE], ally_talents=[])
    engine = combat._load_session(mid).engine
    plague = next(a for a in engine.state.actors.values() if a.summon and a.summon["owner"] == LEFT)
    pid = plague.entity_id
    assert not plague.active and plague.summon["status"] == "waiting"
    state = table.state(mid)
    group = next(g for g in state["menu"]["actions"] if g["label"] == "Living Plague")
    source = group["source_definition_id"]
    assert act(table, mid, source)["status"] == "COMMITTED"
    engine, table = reload_table(combat, tmp_path, mid)
    assert engine.state.actors[pid].active and engine.state.actors[pid].summon["status"] == "present"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    engine, table = reload_table(combat, tmp_path, mid)
    assert engine.state.current_actor_id != pid
    assert any(e.event_type == "COMPANION_DEFAULT_APPLIED" and e.actor_id == pid for e in engine.events)
    for _ in range(5):
        if table.state(mid)["menu"]["actor_id"] == LEFT:
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    menu = table.state(mid)["menu"]
    command = next(g["source_definition_id"] for g in menu["actions"] if g["label"].startswith("Command") and "Plague" in g["label"])
    assert act(table, mid, command)["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    engine, table = reload_table(combat, tmp_path, mid)
    assert engine.state.current_actor_id == pid
    assert engine.state.actors[pid].summon["commanded"]
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    for _ in range(15):
        state = table.state(mid)
        assert state["menu"]["manual"] is False
        result = table.auto_step(mid, state["last_sequence"])
        assert result["status"] == "COMMITTED"
        engine, table = reload_table(combat, tmp_path, mid)
        if engine.state.current_actor_id != pid:
            break
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == pid for e in engine.events)
