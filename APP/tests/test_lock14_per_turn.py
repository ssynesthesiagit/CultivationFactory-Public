"""Per-turn counters reset on each creature's turn through saved Table actions."""
import pytest

from combat import typed_executor as te
from combat.gate3_reducer import Gate3EventReducer
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install
from tests.test_tabletop_hunt6 import table_fight, on_hold, HOLD, LEFT, RIGHT, ALLY


def test_offturn_rider_reopens_each_creature_turn_and_reloads(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    owners = (LEFT, ALLY)

    def use(engine):
        target = engine.state.actors[RIGHT]
        for owner in owners:
            actor = engine.state.actors[owner]
            action = next(a for a in engine.action_catalog.values() if a.owner_id == owner)
            ctx = te.Context(engine, actor, action, engine._active_intent, {}, [target], target)
            effect = {"type": "damage", "flat": 1, "damage_types": ["force"], "once_per_turn": "test:rider"}
            te.block_damage(ctx, effect)
            te.block_damage(ctx, effect)  # Same turn: the second use is denied.

    on_hold(monkeypatch, use)
    seen_turns = []
    for _ in range(3):
        seen_turns.append(table.state(mid)["menu"]["actor_id"])
        before = combat._load_session(mid).engine.state.actors[RIGHT].current_hp
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        assert loaded.engine.state.actors[RIGHT].current_hp == before - len(owners)
        assert all(loaded.engine.state.actors[o].turn_flags["typed_once_turn:test:rider"] for o in owners)
        prior = loaded.engine.state.model_copy(deep=True)
        count = len(loaded.engine.events)
        assert act(table, mid, "end")["status"] == "COMMITTED"
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        resets = [e for e in loaded.engine.events[count:] if e.event_type == "PER_TURN_USES_RESET"]
        assert [e.actor_id for e in resets] == sorted(owners)
        for event in resets:
            assert event.payload["keys"] == ["typed_once_turn:test:rider"]
            Gate3EventReducer().apply_event(prior, event)
        assert all("typed_once_turn:test:rider" not in prior.actors[o].turn_flags for o in owners)
        assert all("typed_once_turn:test:rider" not in loaded.engine.state.actors[o].turn_flags for o in owners)
        assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    assert len(set(seen_turns)) == 3


def test_reset_before_start_hooks_preserves_owner_turn_and_round_flags(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    def seed(engine):
        owner = engine.state.actors[LEFT]
        owner.turn_flags.update({"typed_once_turn:free": 1, "once_per_turn:runtime": owner.turns_started,
            "creature_kind_once:kind": 1, "once_per_round:round": engine.state.round_number,
            "typed_round_once:fight": 1, "own_turn_only": 1, "typed_modifier_once:legacy": 1})
        owner.reaction_available = False
    on_hold(monkeypatch, seed)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    observed = []
    def start(engine, actor):
        owner = engine.state.actors[LEFT]
        observed.append((actor.entity_id, dict(owner.turn_flags), owner.reaction_available, engine.state.round_number))
    install(monkeypatch, "turn_start", start)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert observed
    for actor_id, flags, reaction, round_number in observed:
        assert actor_id != LEFT
        assert not any(k.startswith(("typed_once_turn:", "once_per_turn:", "creature_kind_once:")) for k in flags)
        assert flags["own_turn_only"] == flags["typed_modifier_once:legacy"] == flags["typed_round_once:fight"] == 1
        assert flags["once_per_round:round"] == round_number
        assert not reaction
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_paused_turn_start_rolls_back_all_reset_events(monkeypatch, tmp_path):
    from combat.ext import ControllerPause
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    on_hold(monkeypatch, lambda e: e.state.actors[LEFT].turn_flags.update({"typed_once_turn:test": 1}))
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    session = combat._load_session(mid)
    before = session.engine.state.model_dump(mode="json")
    events = list(session.engine.events)
    def pause(*args):
        raise ControllerPause("test choice")
    install(monkeypatch, "turn_start", pause)
    with pytest.raises(ControllerPause):
        session.engine.end_turn("test:pause")
    assert session.engine.state.model_dump(mode="json") == before
    assert session.engine.events == events


@pytest.mark.parametrize("period,expected", [("turn", "typed_once_turn:modifier:test"),
    (None, "typed_modifier_once:test"), ("round", "typed_modifier_once:test")])
def test_modifier_period_only_opts_explicit_turns_into_reset(period, expected):
    from tests.h1_support import duel, ME, FOE
    engine = duel([])
    actor = engine.state.actors[ME]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME)
    ctx = te.Context(engine, actor, action, None, {}, [engine.state.actors[FOE]], engine.state.actors[FOE])
    te.run_effects(ctx, [{"type": "temp_hp", "flat": 1, "applies_to": "self",
                          "modifier_once": "test", "modifier_once_period": period}])
    assert actor.turn_flags[expected]


def test_round_namespace_survives_per_turn_cleanup():
    from combat.turn_uses import reset_at_turn_start
    from tests.h1_support import duel, ME
    engine = duel([])
    actor = engine.state.actors[ME]
    actor.turn_flags.update({'once_per_turn:_round_test': 2,
                             'once_per_turn:normal_round_ability': 1})
    reset_at_turn_start(engine)
    assert actor.turn_flags['once_per_turn:_round_test'] == 2
    assert 'once_per_turn:normal_round_ability' not in actor.turn_flags


def test_unaffected_turn_has_no_reset_event(tmp_path):
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert not any(e.event_type == "PER_TURN_USES_RESET" for e in combat._load_session(mid).engine.events)


@pytest.mark.parametrize("limit,period,trigger", [("once_per_turn", "turn", "Once per turn when you hit"),
    ("once_per_round", None, "Once per round"), ("once_per_turn", "owner_turn", "Once on each of your turns when you hit")])
def test_compiler_preserves_explicit_modifier_turn_type(limit, period, trigger):
    import copy
    from combat.factory_compiler import apply_modifiers
    from tests.test_typed_structure import AUTHORITY, LASH, _mechanic
    mechanics = {"LASH": AUTHORITY["mechanics"]["LASH"],
        "LIMITED": _mechanic("LIMITED", "Limited Current", "passive", [], {
            "targets": ["Water Lash"], "scope": "named", "when": "hit", "optional": False,
            "limit": limit, "effects": [{"type": "extra_damage", "flat": 2}]})}
    built = {"LASH": {"action_id": "a:lash", "name": "Water Lash", "economy": "action",
        "target_kind": "HOSTILE_ENTITY", "range_ft": 30, "costs": [],
        "typed": {"effects": copy.deepcopy(LASH), "riders": [], "numbers": {"pb": 4}},
        "mechanic": mechanics["LASH"], "modifiers": []}}
    mechanics['LIMITED']['activation']['trigger']=trigger
    apply_modifiers(built, list(mechanics), mechanics, "qi", {"qi": 10})
    effects = built["LASH"]["typed"]["effects"][0]["on_hit"]
    added = next(e for e in effects if e.get("modifier_once") == "LIMITED")
    assert added.get("modifier_once_period") == period
