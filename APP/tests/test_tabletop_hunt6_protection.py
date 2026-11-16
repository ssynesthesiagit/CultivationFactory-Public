from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, HOLD, table_fight, on_hold, answer_action


def test_bone_ward_prompt_names_the_ally_and_pending_damage(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, ["TAL_DEATH_BONE_WARD"], ask=True, ally_talents=[])
    def damage(engine):
        engine._commit_damage(engine.state.actors[ALLY], 8, "FORCE", "test:blow", RIGHT, engine._active_intent, reaction_depth=0)
    on_hold(monkeypatch, damage)
    first = act(table, mid, HOLD)
    assert first["status"] == "REACTION_REQUIRED"
    prompt = first["reaction"]
    assert prompt["reactor"] == "Left" and prompt["reaction"] == "Bone Ward"
    assert prompt["moment"] == "Ally is about to take 8 damage from Right."
    assert prompt["context"]["reactor_id"] == LEFT
    assert answer_action(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    resolved = [e for e in loaded.engine.events if e.event_type == "REACTION_RESOLVED" and e.actor_id == LEFT]
    assert resolved and resolved[-1].payload["pending_before"] == 8
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_explicit_damage_recipient_selects_its_window():
    from combat.tabletop_service import TabletopService
    table = TabletopService.__new__(TabletopService)
    table._names_for = lambda _: ({LEFT: "Left", ALLY: "Ally"}, {})
    windows = [{"event_type": "REACTION_WINDOW_OPENED", "target_ids": [actor],
                "payload": {"checkpoint": "DAMAGE_APPLICATION", "pending_damage": amount}}
               for actor, amount in [(ALLY, 8), (LEFT, 3)]]
    context = {"checkpoint": "TYPED:DAMAGE_APPLICATION@1", "reactor_id": LEFT,
               "reaction_source_id": "reaction:typed.ward", "recent_events": windows, "protected_target_id": ALLY}
    assert table._reaction_prompt("match", context)["moment"] == "Ally is about to take 8 damage."
    context["protected_target_id"] = LEFT
    assert table._reaction_prompt("match", context)["moment"] == "Left is about to take 3 damage."
    # Explicit preview damage wins over older windows, including a zero packet.
    context["pending_damage"] = 0
    assert table._reaction_prompt("match", context)["moment"] == "Left is about to take 0 damage."
