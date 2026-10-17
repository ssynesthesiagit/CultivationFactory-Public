"""Sol review r1 regressions: late turn-end harm must not strand Invisible; custom hostile saves reveal the Vanishing owner."""
from combat import ext as plugins
from combat import typed_executor as te
from combat.ext import tabik_ninpo, weather_shroud
from tests.test_mgr_t15_vanishing_native import setup, activate, held
from tests.hunt12_support import hit_dice
from tests.worker2_support import OWNER, FOE, settle, reload


def _with_late_turn_end_harm(monkeypatch, engine_box):
    """Install a default-priority turn_end provider ahead of the restore hook, like Shroud/Unmaking upkeep.

    On the first turn end of the owner it commits 1 damage to the owner, which runs the native harm observer
    (stamping reveal_turn at the ending boundary) after the ordinary turn-end providers have already run."""
    fired = []

    def late_harm(engine, actor):
        if actor.entity_id == OWNER and not fired and held(engine.state.actors[OWNER], "vanishing_state"):
            fired.append(True)
            engine._commit_damage(engine.state.actors[OWNER], 1, "FIRE", "TEST_LATE_TURN_END_HARM", FOE, None,
                                  reaction_depth=0)

    late_harm.__name__ = "late_turn_end_harm_probe"
    hooks = [h for h in plugins._HOOKS["turn_end"] if h is not tabik_ninpo.vanishing_restore]
    hooks.append(late_harm)
    hooks.append(tabik_ninpo.vanishing_restore)
    monkeypatch.setitem(plugins._HOOKS, "turn_end", hooks)
    return fired


def test_late_turn_end_harm_still_restores_invisible(tmp_path, monkeypatch):
    combat, table, mid = setup(tmp_path)
    activate(combat, table, mid)
    fired = _with_late_turn_end_harm(monkeypatch, None)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    after = reload(tmp_path, mid)
    assert fired, "the late turn-end harm must actually run on the owner's turn end"
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.actor_id == OWNER for e in after.events)
    # Restoration settles after the late harm, at the same boundary.
    assert held(after.state.actors[OWNER], "invisible")
    assert not any(c.data.get("reveal_turn") for c in held(after.state.actors[OWNER], "vanishing_state"))


def test_custom_hostile_successful_save_reveals_owner(tmp_path):
    combat, table, mid = setup(tmp_path)
    activate(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert held(engine.state.actors[OWNER], "invisible")
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    # weather_shroud.throw's own path: a typed context, with no exact block_save packet, through settle_typed_save.
    ctx = weather_shroud._context(engine, owner, next(iter(engine.action_catalog)), foe, "")
    # The save's adverse consequence is damage, and the save succeeds: the printed trigger is forcing the save.
    named = set()
    plug_in_named = {"damaging_save", "damage:fire"}
    te.settle_typed_save(ctx, foe, "CON", None, False, named, plug_in_named, 0)
    assert not held(engine.state.actors[OWNER], "invisible")
    assert held(engine.state.actors[OWNER], "vanishing_state")
