"""Sol review r1 regressions: late turn-end harm must not strand Invisible; custom hostile saves reveal the Vanishing owner."""
from combat import stances
from combat import typed_executor as te
from combat import unmaking
from combat.ext import weather_shroud
from tests.test_mgr_t15_vanishing_native import setup, activate, held
from tests.worker2_support import OWNER, FOE, settle, reload


def _with_native_upkeep_harm(monkeypatch):
    """Native end-of-turn upkeep that harms the owner after the whole turn_end dispatch (like Second Ruin Form's Strain
    overflow, which gate4 runs after turn_end). Eligibility is pure state (owner, round 1), so the preview and the
    authoritative commit both apply it identically and the committed damage is a real receipt."""
    native = stances.on_turn_ended

    def upkeep(engine, actor):
        native(engine, actor)
        if actor.entity_id == OWNER and engine.state.round_number == 1 and actor.active:
            unmaking.self_damage(engine, actor, 1, "TEST_NATIVE_UPKEEP_HARM")

    monkeypatch.setattr(stances, "on_turn_ended", upkeep)


def test_late_turn_end_harm_still_restores_invisible(tmp_path, monkeypatch):
    combat, table, mid = setup(tmp_path)
    activate(combat, table, mid)
    _with_native_upkeep_harm(monkeypatch)
    mark = len(reload(tmp_path, mid).events)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    after = reload(tmp_path, mid)
    owner = after.state.actors[OWNER]
    tail = [(e.event_type, e.actor_id, tuple(e.target_ids)) for e in after.events[mark:]]
    states = [(c.condition_id, dict(c.data)) for c in owner.conditions.values()]
    assert any(t == "DAMAGE_COMMITTED" and a == OWNER and OWNER in tgt for t, a, tgt in tail), f"no committed owner self-damage: {tail}"
    assert held(owner, "invisible"), f"Invisible stranded after native upkeep harm: events={tail} states={states}"
    assert not any(c.data.get("reveal_turn") for c in held(owner, "vanishing_state")), f"reveal_turn left: states={states}"


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
