"""Integration counterexamples at accepted table commits, fresh reload and replay.

No browser is launched; the lead runs existing browser opt-ins outside the sandbox.
"""
import pytest

from combat import ext, typed_executor as te
from combat.ext import cai_clan as cai, life_state as life
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_cai_clan_subpath import _fight, _loaded, _turn, _use, ROOT, LEFT, ALLY, RIGHT
from tests.test_tabletop_hunt6 import on_hold, HOLD


def hold(table, mid):
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["source_definition_id"] == HOLD)
    option = group["options"][0]
    answers = []
    for _ in range(10):
        result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        answers.append({**prompt["context"], "selection": "USE",
                        "option_ids": [prompt["choice"]["options"][0]["id"]] if prompt.get("choice") else []})
    raise AssertionError("too many hold choices")


def pin_confirmed_hit(monkeypatch, *, base=5, censure=6, critical=False):
    """Force ALLY's attack to land and pin the printed base and Censure dice, keeping one real
    attack and the normal defenses and zero-HP path."""
    previous = list(ext.subscribers("d20_result"))
    def attack_roll(engine, roll, intent):
        if roll.actor_id == ALLY and roll.reason.startswith("ATTACK:"):
            return {"source_id": "test:r25x2f.attack", "operation": "replace", "natural_result": 20 if critical else 15}
        return next((answer for callback in previous if (answer := callback(engine, roll, intent)) is not None), None)
    monkeypatch.setitem(ext._HOOKS, "d20_result", [attack_roll])
    from combat.gate2_rolls import DeterministicRollAuthority
    original = DeterministicRollAuthority.roll
    def dice(self, spec, *args, **kw):
        reason = kw.get("reason", "")
        if reason == "Censure radiant opening":
            kw["fixed_damage"] = censure
        elif reason.startswith("DAMAGE:") and kw.get("actor_id") == ALLY:
            kw["fixed_damage"] = base
            spec = spec.model_copy(update={"modifier": 0})
        return original(self, spec, *args, **kw)
    monkeypatch.setattr(DeterministicRollAuthority, "roll", dice)


def _event_subscriber(monkeypatch, function, priority, *, nested=False):
    """Register one ordered, test-local 'event' subscriber at ``priority``.

    combat/ext/hook keeps the registry sorted by (lower first) and delivers events raised
    inside another event only to its nested subscribers; this test helper appends to copies
    of both registries so monkeypatch restores the real ones afterwards.
    """
    monkeypatch.setitem(ext._HOOK_PRIORITIES, ("event", function), priority)
    order = [*ext.subscribers("event"), function]
    order.sort(key=lambda row: ext._HOOK_PRIORITIES.get(("event", row), 0))
    monkeypatch.setitem(ext._HOOKS, "event", order)
    if nested:
        monkeypatch.setitem(ext._NESTED_HOOKS, "event", {*ext._NESTED_HOOKS.get("event", ()), function})


def _fallen_marked_target(tmp_path, monkeypatch, pre_state, extra_features=(), failures=0, after=None):
    """A marked target that has already fallen: 10 HP maximum, at 0 HP and DYING or STABLE
    before the hit, with ``failures`` damage failures already counted. 1 HP of damage each
    keeps every setup hit under the massive-damage threshold of 10. ``after`` runs on every
    later Hold, so a test can keep playing; the engine may replay a Hold after a rollback,
    so it guards its own state."""
    combat, table, mid = _fight(tmp_path, extra_features=extra_features)
    _use(table, mid, "Judgment Saber", target=RIGHT)
    _turn(table, mid, ALLY)
    def setup(engine):
        target = engine.state.actors[RIGHT]
        if target.maximum_hp == 10:
            # This Hold's own setup is already committed; a replayed Hold lands here too.
            if after is not None:
                after(engine)
            return
        from combat.maximum_hp import change
        change(engine, target, "test:low_max", -290, "test:setup", RIGHT,
               label="Test low maximum", current_delta=10 - target.current_hp, current_floor=1)
        engine._commit_damage(target, target.current_hp, "FORCE", "test:down", LEFT, None, reaction_depth=0)
        for _ in range(failures):
            engine._commit_damage(target, 1, "FORCE", "test:failure", LEFT, None, reaction_depth=0)
        if pre_state == "STABLE":
            assert life.stabilize(engine, target, "test:stabilize")
    on_hold(monkeypatch, setup)
    hold(table, mid)
    fresh = CombatService(ROOT, tmp_path)
    fallen = fresh._load_session(mid).engine.state.actors[RIGHT]
    assert fallen.current_hp == 0 and fallen.life_state == pre_state and fallen.active
    assert fallen.maximum_hp == 10
    assert (fallen.turn_flags.get(life.RECORD) or {}) == {"ok": 0, "bad": failures}
    return fresh, TabletopService(fresh, tmp_path), mid


@pytest.mark.parametrize("same_resolution", [False, True])
def test_fresh_zero_rewards_survive_reload_healing_redrop_and_later_death(tmp_path, monkeypatch, same_resolution):
    combat, table, mid = _fight(tmp_path, extra_features=["TAL_DAEMONIC_CULTIVATION_DEMON_MARK"])
    def notify(engine, target, attacker, source):
        engine._append_event("PASSIVE_TRIGGERED", "test:zero_receipt", actor_id=attacker,
                             target_ids=(target.entity_id,), payload={"source": source})
    monkeypatch.setitem(ext._HOOKS, "fresh_zero_hp", [*ext.subscribers("fresh_zero_hp"), notify])

    def damage(engine):
        owner, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        stage = sum(e.source_definition_id == "test:zero_receipt" for e in engine.events)
        action = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.display_name == "Demon Mark")
        ctx = te.Context(engine, owner, action, engine._active_intent, action.parameters["typed"], [target], target,
                         {"_bonus": True, "_potency_used": True})
        if stage < 2:
            with te._defeat_chain(ctx):
                for drop in range(2 if same_resolution and stage == 0 else 1):
                    if stage or drop:
                        life.restore_hp(engine, target, 5, "test:heal", LEFT)
                    te.run_effects(ctx, action.parameters["typed"]["effects"][0]["on_fail"])
                    te._deal(ctx, target, target.current_hp + 1, "FORCE")
        else:
            engine._commit_damage(target, target.maximum_hp, "FORCE", "test:death", LEFT, None, reaction_depth=0)
    on_hold(monkeypatch, damage)
    initial = _loaded(combat, mid).engine
    seq = initial.state.event_sequence
    for step in range(2 if same_resolution else 3):
        hold(table, mid)
        loaded = _loaded(combat, mid)
        owner, target = loaded.engine.state.actors[LEFT], loaded.engine.state.actors[RIGHT]
        gains = [e for e in loaded.engine.events if e.sequence > seq and e.event_type == "RESOURCE_GAINED" and e.actor_id == LEFT
                 and "DEMON_MARK" in e.source_definition_id]
        expected = min((step + 1) * (2 if same_resolution else 1), 2)
        assert len(gains) == expected
        assert any(e.event_type == "RESOURCE_GAINED" and e.source_definition_id == "TAL_DAEMONIC_CULTIVATION_DEVOUR_ESSENCE"
                   for e in loaded.engine.events if e.sequence > seq)
        assert sum(e.source_definition_id == "test:zero_receipt" for e in loaded.engine.events) == expected
        if step < (1 if same_resolution else 2):
            assert target.active and target.life_state == "DYING"
        else:
            assert life.is_deceased(target)
        assert loaded.mechanical.replay()["status"] == "PASS"
        fresh = CombatService(ROOT, tmp_path)
        table = TabletopService(fresh, tmp_path)
        combat = fresh


@pytest.mark.parametrize("critical", [False, True])
@pytest.mark.parametrize("massive", [False, True])
def test_censure_is_part_of_low_hp_hit_before_dying_settlement(tmp_path, monkeypatch, critical, massive):
    combat, table, mid = _fight(tmp_path)
    _use(table, mid, "Judgment Saber", target=RIGHT)
    _turn(table, mid, ALLY)
    def setup(engine):
        from combat.maximum_hp import change
        target = engine.state.actors[RIGHT]
        change(engine, target, "test:low_hp", -290 if massive else -1, "test:setup", RIGHT,
               label="Test low HP", current_delta=1 - target.current_hp, current_floor=1)
    on_hold(monkeypatch, setup)
    hold(table, mid)
    fresh = CombatService(ROOT, tmp_path)
    table = TabletopService(fresh, tmp_path)
    pin_confirmed_hit(monkeypatch, censure=12 if critical else 6, critical=critical)
    seq = _loaded(fresh, mid).engine.state.event_sequence
    _use(table, mid, "Wind Lash: Cut", target=RIGHT)
    loaded = _loaded(fresh, mid)
    target = loaded.engine.state.actors[RIGHT]
    rolls = [e for e in loaded.engine.events if e.sequence > seq and e.event_type == "DAMAGE_ROLLED"
             and e.source_definition_id == cai.EDICT]
    assert len(rolls) == 1 and rolls[0].payload["expression"] == ("4d8+0" if critical else "2d8+0")
    assert not any(c.condition_id == cai.CENSURE for c in target.conditions.values())
    assert not any("takes damage at 0 Hit Points" in str(e.payload) for e in loaded.engine.events if e.sequence > seq)
    assert life.is_deceased(target) is massive
    if not massive:
        assert target.active and target.life_state == "DYING"
        assert target.turn_flags[life.RECORD] == {"ok": 0, "bad": 0}
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_unrelated_nested_damage_at_zero_keeps_its_death_save_failure(tmp_path, monkeypatch):
    """Only Censure's own component shares the hit; an intervening hazard does not."""
    from combat.pending_damage import current
    combat, table, mid = _fight(tmp_path)
    _use(table, mid, "Judgment Saber", target=RIGHT)
    _turn(table, mid, ALLY)
    def down(engine):
        target = engine.state.actors[RIGHT]
        engine._commit_damage(target, target.current_hp, "FORCE", "test:down", LEFT, None, reaction_depth=0)
    on_hold(monkeypatch, down)
    hold(table, mid)
    def hazard(engine, event):
        packet = current(engine)
        if (event.event_type == "REACTION_WINDOW_OPENED" and event.payload.get("checkpoint") == "DAMAGE_APPLICATION"
                and packet is not None and life.HIT_COMPONENT_FLAG in packet.source_flags):
            engine._commit_damage(engine.state.actors[RIGHT], 1, "FIRE", "test:independent_hazard", LEFT, None, reaction_depth=0)
    monkeypatch.setitem(ext._HOOKS, "state_event", [*ext.subscribers("state_event"), hazard])
    previous = list(ext.subscribers("d20_result"))
    def hit(engine, roll, intent):
        if roll.actor_id == ALLY and roll.reason.startswith("ATTACK:"):
            return {"source_id": "test:nested.hit", "operation": "replace", "natural_result": 15}
        return next((answer for callback in previous if (answer := callback(engine, roll, intent)) is not None), None)
    monkeypatch.setitem(ext._HOOKS, "d20_result", [hit])
    fresh = CombatService(ROOT, tmp_path)
    _use(TabletopService(fresh, tmp_path), mid, "Wind Lash: Cut", target=RIGHT)
    loaded = _loaded(fresh, mid)
    target = loaded.engine.state.actors[RIGHT]
    assert target.active and target.life_state == "DYING"
    assert target.turn_flags[life.RECORD] == {"ok": 0, "bad": 2}
    assert not any(c.condition_id == cai.CENSURE for c in target.conditions.values())
    assert sum(e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == "test:independent_hazard"
               for e in loaded.engine.events) == 1
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("pre_state", ["DYING", "STABLE"])
def test_censure_massive_damage_kills_a_target_already_at_zero(tmp_path, monkeypatch, pre_state):
    """The first packet is under the massive-damage threshold and takes the hit's one failure;
    only the combined hit is lethal, so it settles the outcome while the target is already down."""
    combat, table, mid = _fallen_marked_target(tmp_path, monkeypatch, pre_state)
    pin_confirmed_hit(monkeypatch)
    seq = _loaded(combat, mid).engine.state.event_sequence
    _use(table, mid, "Wind Lash: Cut", target=RIGHT)
    session = _loaded(combat, mid)
    target = session.engine.state.actors[RIGHT]
    packets = [e for e in session.engine.events if e.sequence > seq and e.event_type == "DAMAGE_COMMITTED"
               and RIGHT in (e.target_ids or ())]
    base, component = packets[-2:]
    assert (base.payload["hp_damage"], component.payload["hp_damage"]) == (5, 6)
    assert life.is_deceased(target) and not target.active
    assert life.DOOMED not in target.turn_flags
    # The whole hit earns one failure: settling the combined damage never rolls a second.
    assert target.turn_flags[life.RECORD] == {"ok": 0, "bad": 1}
    defeated = [e for e in session.engine.events if e.sequence > component.sequence
                and e.event_type == "ENTITY_DEFEATED" and e.actor_id == RIGHT]
    assert len(defeated) == 1
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == session.engine.state.model_dump(mode="json")
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_censure_massive_damage_gives_an_owned_death_prevention_the_first_word(tmp_path, monkeypatch):
    """Funeral Candle Shelter is asked about the combined hit's death and keeps the target Stable."""
    from combat.ext import wax_candle
    combat, table, mid = _fallen_marked_target(tmp_path, monkeypatch, "DYING",
                                               extra_features=[wax_candle.FEATURE])
    pin_confirmed_hit(monkeypatch)
    seq = _loaded(combat, mid).engine.state.event_sequence
    _use(table, mid, "Wind Lash: Cut", target=RIGHT)
    session = _loaded(combat, mid)
    target = session.engine.state.actors[RIGHT]
    assert target.active and target.current_hp == 0 and target.life_state == "STABLE"
    assert not life.is_deceased(target)
    assert life.DOOMED not in target.turn_flags
    assert target.turn_flags[wax_candle.USED] == LEFT
    assert any("Funeral Candle Shelter" in str(e.payload) for e in session.engine.events
               if e.sequence > seq)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == session.engine.state.model_dump(mode="json")
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


def _shelter_spent_once(events, owner_before, owner_after):
    """The printed cost of Funeral Candle Shelter was paid exactly once."""
    from combat.ext import wax_candle
    spends = [e for e in events if e.event_type == "RESOURCE_SPENT"
              and e.source_definition_id == wax_candle.FEATURE and e.actor_id == LEFT]
    assert len(spends) == 1 and spends[0].payload["amount"] == wax_candle.COST
    pool = spends[0].payload["resource_id"]
    assert pool in te.CP_POOLS
    assert owner_after.resources[pool] == owner_before.resources[pool] - wax_candle.COST
    assert owner_before.reaction_available is True and owner_after.reaction_available is False
    assert sum(1 for e in events if "Funeral Candle Shelter" in str(e.payload)) == 1


@pytest.mark.parametrize("failures,base,censure", [(0, 10, 1), (2, 1, 9)])
def test_protection_paid_on_the_first_packet_survives_the_same_hit_component(tmp_path, monkeypatch, failures, base, censure):
    """The printed protection is spent against one damaging hit, so the Censure dice of that
    same hit cannot resolve a second death and kill the creature anyway.

    ``failures``/``base`` are the two ways the first packet is lethal on its own: damage of at
    least the creature's maximum, and a third failed death saving throw (the engine counts two,
    because the hit comes from within 5 feet of an Unconscious creature). The component's
    additional damage then carries the whole hit to the massive-damage threshold, so the
    component is where the bug shows.
    """
    from combat.ext import wax_candle
    combat, table, mid = _fallen_marked_target(tmp_path, monkeypatch, "DYING",
                                               extra_features=[wax_candle.FEATURE], failures=failures)
    owner_before = _loaded(combat, mid).engine.state.actors[LEFT]
    pin_confirmed_hit(monkeypatch, base=base, censure=censure)
    seq = _loaded(combat, mid).engine.state.event_sequence
    _use(table, mid, "Wind Lash: Cut", target=RIGHT)
    session = _loaded(combat, mid)
    owner, target = session.engine.state.actors[LEFT], session.engine.state.actors[RIGHT]
    packets = [e for e in session.engine.events if e.sequence > seq and e.event_type == "DAMAGE_COMMITTED"
               and RIGHT in (e.target_ids or ())]
    first, component = packets[-2:]
    assert (first.payload["hp_damage"], component.payload["hp_damage"]) == (base, censure)
    # One damaging hit, one resolution: the creature lives at 0 Hit Points.
    assert target.active and target.current_hp == 0 and target.life_state == "STABLE"
    assert not life.is_deceased(target)
    assert life.DOOMED not in target.turn_flags
    assert target.turn_flags[wax_candle.USED] == LEFT
    assert not any(e.sequence > component.sequence and e.event_type == "ENTITY_DEFEATED"
                   and e.actor_id == RIGHT for e in session.engine.events)
    _shelter_spent_once([e for e in session.engine.events if e.sequence > seq], owner_before, owner)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == session.engine.state.model_dump(mode="json")
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_protection_of_one_hit_does_not_reach_the_next_hit(tmp_path, monkeypatch):
    """The saved creature is not immortal: the next independent lethal hit kills it normally,
    so the shared answer belongs to its own hit only."""
    from combat.ext import wax_candle
    def next_hit(engine):
        target = engine.state.actors[RIGHT]
        if target.life_state == "STABLE" and not any(c.condition_id == cai.CENSURE for c in target.conditions.values()):
            engine._commit_damage(target, 10, "FORCE", "test:next_hit", LEFT, None, reaction_depth=0)
    combat, table, mid = _fallen_marked_target(tmp_path, monkeypatch, "DYING",
                                               extra_features=[wax_candle.FEATURE], after=next_hit)
    owner_before = _loaded(combat, mid).engine.state.actors[LEFT]
    pin_confirmed_hit(monkeypatch, base=10, censure=1)
    seq = _loaded(combat, mid).engine.state.event_sequence
    _use(table, mid, "Wind Lash: Cut", target=RIGHT)
    assert _loaded(combat, mid).engine.state.actors[RIGHT].life_state == "STABLE"
    hold(table, mid)
    session = _loaded(combat, mid)
    target = session.engine.state.actors[RIGHT]
    assert life.is_deceased(target) and not target.active
    assert life.DOOMED not in target.turn_flags
    assert target.turn_flags.get(wax_candle.USED) == LEFT
    _shelter_spent_once([e for e in session.engine.events if e.sequence > seq], owner_before,
                        session.engine.state.actors[LEFT])
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == session.engine.state.model_dump(mode="json")
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_protection_of_one_hit_does_not_reach_another_hit_of_the_same_action(tmp_path, monkeypatch):
    """The shared answer belongs to its own hit only: inside one action, a later hit of its own
    followed by a same-hit component still resolves the combined lethal damage."""
    from combat.ext import wax_candle
    def play_on_hold(engine):
        target = engine.state.actors[RIGHT]
        engine._remove_condition(target, cai.CENSURE, "test:unmark")
        # The first hit of this action is lethal on its own and spends the printed protection.
        engine._commit_damage(target, 10, "FORCE", "test:saved_hit", LEFT, None, reaction_depth=0)
        assert target.life_state == "STABLE" and target.active
        # A second, independent hit of 5, then a component sharing that hit's outcome: 5+6 is
        # lethal and nothing is left to save the creature.
        engine._commit_damage(target, 5, "FORCE", "test:next_hit", LEFT, None, reaction_depth=0)
        with life.additional_hit_component(engine, target, 0, 5):
            engine._commit_damage(target, 6, "RADIANT", "test:component", LEFT, None, reaction_depth=0,
                                  source_flags=("magical", life.HIT_COMPONENT_FLAG))
    combat, table, mid = _fallen_marked_target(tmp_path, monkeypatch, "DYING",
                                               extra_features=[wax_candle.FEATURE], after=play_on_hold)
    seq = _loaded(combat, mid).engine.state.event_sequence
    hold(table, mid)
    session = _loaded(combat, mid)
    target = session.engine.state.actors[RIGHT]
    packets = [e for e in session.engine.events if e.sequence > seq and e.event_type == "DAMAGE_COMMITTED"
               and RIGHT in (e.target_ids or ())]
    assert [e.payload["hp_damage"] for e in packets] == [10, 5, 6]
    assert life.is_deceased(target) and not target.active
    assert life.DOOMED not in target.turn_flags
    assert target.turn_flags.get(wax_candle.USED) == LEFT
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == session.engine.state.model_dump(mode="json")
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


def _survived_the_rest_of_the_hit(tmp_path, mid, combat, seq, owner_before, packets, expected_damage, notes=1):
    """One protected hit, the packets resolved inside it and its component: the creature
    survives, the printed protection was paid once, and every component that reached the
    threshold read that answer instead of settling a second death."""
    from combat.ext import wax_candle
    session = _loaded(combat, mid)
    owner, target = session.engine.state.actors[LEFT], session.engine.state.actors[RIGHT]
    assert [e.payload["hp_damage"] for e in packets] == expected_damage
    # One damaging hit, one resolution: the creature lives at 0 Hit Points.
    assert target.active and target.current_hp == 0 and not life.is_deceased(target)
    assert life.DOOMED not in target.turn_flags
    assert target.turn_flags.get(wax_candle.USED) == LEFT
    assert not any(e.sequence > packets[-1].sequence and e.event_type == "ENTITY_DEFEATED"
                   and e.actor_id == RIGHT for e in session.engine.events)
    # Each component that reached the threshold read the answer the first packet paid for
    # instead of settling a second death.
    assert sum(1 for e in session.engine.events if e.sequence > seq
               and "already saved from it" in str(e.payload)) == notes
    _shelter_spent_once([e for e in session.engine.events if e.sequence > seq], owner_before, owner)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == session.engine.state.model_dump(mode="json")
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("nested", [0, 1])
def test_protection_of_one_hit_survives_unrelated_nested_damage(tmp_path, monkeypatch, nested):
    """A packet of its own resolved inside a protected hit is a hit of its own: it neither
    inherits the outer hit's answer nor erases it.

    The nested packet is dealt after the first packet's own settlement (so the protection has
    been paid) and before the Censure component of that same hit (event priorities 0, 50 and
    100). ``nested`` is 0 for a packet reduced to nothing, which changes no Hit Points and no
    life state, and 1 for an ordinary nonlethal packet of its own.
    """
    from combat.ext import wax_candle
    from combat.pending_damage import current
    combat, table, mid = _fallen_marked_target(tmp_path, monkeypatch, "DYING",
                                               extra_features=[wax_candle.FEATURE])
    owner_before = _loaded(combat, mid).engine.state.actors[LEFT]
    def hazard(engine, event_type, kwargs):
        packet = current(engine)
        if not (event_type == "DAMAGE_COMMITTED" and packet is not None and packet.source_actor_id == ALLY
                and packet.target_id == RIGHT and packet.amount == 10
                and life.HIT_COMPONENT_FLAG not in packet.source_flags):
            return
        engine._commit_damage(engine.state.actors[RIGHT], nested, "FIRE", "test:nested_hazard",
                              LEFT, None, reaction_depth=0)
    _event_subscriber(monkeypatch, hazard, 50)
    pin_confirmed_hit(monkeypatch, base=10, censure=1)
    seq = _loaded(combat, mid).engine.state.event_sequence
    _use(table, mid, "Wind Lash: Cut", target=RIGHT)
    session = _loaded(combat, mid)
    packets = [e for e in session.engine.events if e.sequence > seq and e.event_type == "DAMAGE_COMMITTED"
               and RIGHT in (e.target_ids or ())]
    # The base packet, the unrelated packet resolved inside the same hit, then its component
    # (the component carries the attack's own damage source; Censure's radiant type is its mark).
    assert [e.payload["damage_type"] for e in packets[1:]] == ["FIRE", "RADIANT"]
    assert packets[1].source_definition_id == "test:nested_hazard"
    assert any(e.event_type == "DAMAGE_ROLLED" and e.source_definition_id == cai.EDICT
               for e in session.engine.events if e.sequence > seq)
    _survived_the_rest_of_the_hit(tmp_path, mid, combat, seq, owner_before, packets, [10, nested, 1])
    target = _loaded(combat, mid).engine.state.actors[RIGHT]
    # The nested packet kept its own lifecycle; it never inherited or spent the outer answer.
    assert (target.life_state, target.turn_flags[life.RECORD]) == (
        ("STABLE", {"ok": 0, "bad": 0}) if not nested else ("DYING", {"ok": 0, "bad": 1}))


def test_independent_nested_hit_components_do_not_borrow_outer_protection(tmp_path, monkeypatch):
    """Shelter saves the outer hit; a separate nested hit's lethal total still kills.

    The independent packet opens its own component scope during notification, while
    Censure's outer scope is still open. It must keep its own scratch and restore
    the outer record when it exits.
    """
    from combat.ext import wax_candle
    from combat.pending_damage import current, packet_scratch
    combat, table, mid = _fallen_marked_target(tmp_path, monkeypatch, "DYING",
                                               extra_features=[wax_candle.FEATURE])
    owner_before = _loaded(combat, mid).engine.state.actors[LEFT]

    def nested_hit(engine, event_type, kwargs):
        packet = current(engine)
        if event_type != "DAMAGE_COMMITTED" or packet is None or packet.target_id != RIGHT:
            return
        target = engine.state.actors[RIGHT]
        if packet.source_actor_id == ALLY and packet.amount == 1 and life.HIT_COMPONENT_FLAG in packet.source_flags:
            assert target.current_hp == 0 and target.maximum_hp == 10 and target.life_state == "STABLE"
            assert target.turn_flags[wax_candle.USED] == LEFT
            outer = getattr(engine, life.HIT_SCOPE)
            engine._commit_damage(target, 5, "FIRE", "test:independent_hit", LEFT, None, reaction_depth=0)
            assert getattr(engine, life.HIT_SCOPE) is outer
        elif packet.source_id == "test:independent_hit":
            outer = getattr(engine, life.HIT_SCOPE)
            scratch = packet_scratch(engine)
            with life.additional_hit_component(engine, target, 0, 5):
                engine._commit_damage(target, 6, "RADIANT", "test:independent_component", LEFT, None,
                                      reaction_depth=0, source_flags=("magical", life.HIT_COMPONENT_FLAG))
            assert getattr(engine, life.HIT_SCOPE) is outer
            assert packet_scratch(engine) is scratch

    _event_subscriber(monkeypatch, nested_hit, 150, nested=True)
    pin_confirmed_hit(monkeypatch, base=10, censure=1)
    seq = _loaded(combat, mid).engine.state.event_sequence
    _use(table, mid, "Wind Lash: Cut", target=RIGHT)
    session = _loaded(combat, mid)
    target = session.engine.state.actors[RIGHT]
    packets = [e for e in session.engine.events if e.sequence > seq and e.event_type == "DAMAGE_COMMITTED"
               and RIGHT in (e.target_ids or ())]
    assert [e.payload["hp_damage"] for e in packets] == [10, 1, 5, 6]
    assert life.is_deceased(target) and not target.active
    assert life.DOOMED not in target.turn_flags
    assert target.turn_flags[wax_candle.USED] == LEFT
    _shelter_spent_once([e for e in session.engine.events if e.sequence > seq], owner_before,
                        session.engine.state.actors[LEFT])
    assert sum(e.event_type == "ENTITY_DEFEATED" and e.actor_id == RIGHT and e.sequence > packets[-1].sequence
               for e in session.engine.events) == 1
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == session.engine.state.model_dump(mode="json")
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_protection_of_one_hit_survives_a_nested_component_scope(tmp_path, monkeypatch):
    """A component delivered inside another component's scope is the same hit again: the inner
    scope hands the hit's record back instead of discarding it, so a later component of that hit
    still finds the protection its first packet paid for."""
    from combat.ext import wax_candle
    from combat.pending_damage import current
    combat, table, mid = _fallen_marked_target(tmp_path, monkeypatch, "DYING",
                                               extra_features=[wax_candle.FEATURE])
    owner_before = _loaded(combat, mid).engine.state.actors[LEFT]
    def deeper_component(engine, event_type, kwargs):
        packet = current(engine)
        if not (event_type == "DAMAGE_COMMITTED" and packet is not None and packet.target_id == RIGHT
                and packet.source_actor_id == ALLY and packet.amount == 1
                and life.HIT_COMPONENT_FLAG in packet.source_flags):
            return
        target = engine.state.actors[RIGHT]
        # One more component inside a component scope of its own: 1+1 stays under the
        # creature's maximum, so nothing settles while the inner scope is open.
        with life.additional_hit_component(engine, target, 0, 1):
            engine._commit_damage(target, 1, "RADIANT", "test:nested_component", LEFT, None,
                                  reaction_depth=0, source_flags=("magical", life.HIT_COMPONENT_FLAG))
        # A third component of the same hit, once that inner scope has closed.
        engine._commit_damage(target, 1, "RADIANT", "test:component_after_nested", LEFT, None,
                              reaction_depth=0, source_flags=("magical", life.HIT_COMPONENT_FLAG))
    _event_subscriber(monkeypatch, deeper_component, 150, nested=True)
    pin_confirmed_hit(monkeypatch, base=10, censure=1)
    seq = _loaded(combat, mid).engine.state.event_sequence
    _use(table, mid, "Wind Lash: Cut", target=RIGHT)
    session = _loaded(combat, mid)
    packets = [e for e in session.engine.events if e.sequence > seq and e.event_type == "DAMAGE_COMMITTED"
               and RIGHT in (e.target_ids or ())]
    # The base packet, its component (which carries the attack's own damage source), the
    # component inside a nested scope, then the one after that scope closed.
    assert [e.payload["damage_type"] for e in packets[1:]] == ["RADIANT", "RADIANT", "RADIANT"]
    assert [e.source_definition_id for e in packets[2:]] == ["test:nested_component",
                                                             "test:component_after_nested"]
    # Both Censure's own component and the one after the nested scope reached the threshold
    # and found the answer the first packet paid for.
    _survived_the_rest_of_the_hit(tmp_path, mid, combat, seq, owner_before, packets, [10, 1, 1, 1], notes=2)
