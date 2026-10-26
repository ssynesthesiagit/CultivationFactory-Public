"""Nominal expiry counters cross real Table commits, reloads and replay."""
from combat import ext
from combat.ext import effect_durations as durations
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.hunt15_support import LEFT, ALLY, act, fight, reload, turn


def test_counted_dead_source_effect_and_destroyed_summon_survive_reload(tmp_path, monkeypatch):
    def setup(ctx, row):
        e, dead = ctx.engine, ctx.actor
        ally = e.state.actors[ALLY]
        e._apply_condition(ally, "condition:typed.sol184_clock", "test:clock", dead.entity_id,
                           expires_on=durations.token("end", dead.entity_id, dead.turns_started + 3))
        e._commit_damage(dead, dead.maximum_hp * 3, "UNTYPED", "test:death", dead.entity_id, None, reaction_depth=0)
    monkeypatch.setitem(ext.effects(), "sol184_setup", setup)
    combat, table, mid = fight(tmp_path, ["POISON_BASE_DELIVER_THE_DOSE"], ally=[], effects=[{"type": "sol184_setup"}])
    turn(table, mid, LEFT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    counts = []
    for _ in range(10):
        shown = table.state(mid)
        result = (act(table, mid, "end") if shown["menu"].get("end_turn")
                  else table.auto_step(mid, shown["last_sequence"]))
        assert result["status"] == "COMMITTED"
        e = reload(combat, mid)
        ally = e.state.actors[ALLY]
        condition = next((c for c in ally.conditions.values() if c.source_definition_id == "test:clock"), None)
        if condition:
            count = durations.skipped_expiry_slots(ally, condition)
            counts.append(count)
            assert type(count) is int
        else:
            break
        fresh = CombatService(combat.source_root, tmp_path)
        table = TabletopService(fresh, tmp_path)
    assert 1 in counts and 2 in counts
    assert condition is None
    assert not any(key.startswith("expiry_round_skipped:") for key in ally.turn_flags)
    assert not any(ev.event_type == "TURN_STARTED" and ev.actor_id == LEFT and ev.sequence > next(
        event.sequence for event in e.events if event.event_type == "ENTITY_DEFEATED" and event.actor_id == LEFT) for ev in e.events)


def test_destroyed_summon_has_no_later_turn_or_menu_after_table_reload(tmp_path, monkeypatch):
    plague_talent = "tianxia.talent.disease.living_plague"
    def destroy(ctx, row):
        e = ctx.engine
        victim = next(a for a in e.state.actors.values() if a.summon and a.summon["owner"] == LEFT)
        victim.active = True
        victim.summon["status"] = "present"
        e._commit_damage(victim, victim.maximum_hp * 3, "UNTYPED", "test:destroy", LEFT, None, reaction_depth=0)
    monkeypatch.setitem(ext.effects(), "sol184_destroy", destroy)
    combat, table, mid = fight(tmp_path, [plague_talent], ally=[], effects=[{"type": "sol184_destroy"}])
    turn(table, mid, LEFT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    e = reload(combat, mid)
    dead = next(a for a in e.state.actors.values() if a.summon and a.summon["owner"] == LEFT)
    assert not dead.active
    before, turns = e.state.event_sequence, dead.turns_started
    for _ in range(6):
        assert act(table, mid, "end")["status"] == "COMMITTED"
        shown = table.state(mid)
        assert shown["presentation"]["current_actor_id"] != dead.entity_id
        assert shown["menu"]["actor_id"] != dead.entity_id
    e = reload(combat, mid)
    assert e.state.actors[dead.entity_id].turns_started == turns
    assert not any(ev.event_type in ("TURN_STARTED", "TURN_ENDED") and ev.actor_id == dead.entity_id
                   and ev.sequence > before for ev in e.events)
