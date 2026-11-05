"""Turning Wheel modifies normal damage rolls, before halving and defenses."""
import pytest

from combat import typed_executor as X
from combat.ext import fate_riders as F
from tests.test_auto_lane4 import _script
from tests.test_riders_lane9 import _fate_fight, _act, _turn, ME, THEM, ALLY


def wheel(face=2):
    engine = _fate_fight(["TURNING_WHEEL_AUSPICE"])
    _script(engine, [face])
    _act(engine, "Turning Wheel Auspice", ALLY)
    return engine


@pytest.mark.parametrize("resistant", [False, True])
def test_wheel_attack_is_one_normal_packet_before_resistance(resistant):
    engine = wheel()
    target = engine.state.actors[THEM]
    target.armor_class = -50
    if resistant:
        for kind in ("PIERCING", "SLASHING"):
            engine._add_modifier(target, "test:resistance", "damage_resistance", "SET", kind, "ALL", expires_on="UNTIL_REMOVED")
    _turn(engine, ALLY)
    _script(engine, [10, 3])
    start = len(engine.events)
    _act(engine, "Bi Shou (Dagger) attack", THEM, actor=ALLY)
    events = engine.events[start:]
    packets = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and THEM in e.target_ids]
    assert len(packets) == 1
    rolled = next(e.payload for e in events if e.event_type == "DAMAGE_ROLLED")
    action = engine.action_catalog[packets[0].source_definition_id]
    modifier = action.parameters["typed"]["weapon"]["damage"]["modifier"]
    assert rolled["total"] == 3 + modifier + 2
    assert packets[0].payload["hp_damage"] == (rolled["total"] // 2 if resistant else rolled["total"])
    assert not any(e.source_definition_id == F.WHEEL_ID and e.event_type == "DAMAGE_COMMITTED" for e in events)


@pytest.mark.parametrize("success", [False, True])
@pytest.mark.parametrize("face,bonus", [(2, 2), (4, 0), (6, 0)])
def test_wheel_save_damage_shares_one_roll_and_halves_the_bonus(success, face, bonus):
    engine = wheel(face)
    actor = engine.state.actors[ALLY]
    targets = [engine.state.actors[THEM], engine.state.actors[ME]]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ALLY and a.display_name == "Bi Shou (Dagger) attack")
    ctx = X.Context(engine, actor, action, None, {"numbers": {"save_dc": -100 if success else 99}}, targets)
    before = [a.current_hp for a in targets]
    start = len(engine.events)
    _script(engine, [20 if success else 1, 3, 20 if success else 1])
    X.run_effects(ctx, [{"type": "save", "ability": "dex", "on_fail": [
        {"type": "damage", "dice": {"count": 1, "sides": 8}, "damage_types": ["force"], "applies_to": "target"}],
        "on_success": [{"type": "half_damage"}]}])
    assert [hp - a.current_hp for hp, a in zip(before, targets)] == [(3 + bonus) // 2 if success else 3 + bonus] * 2
    rolls = [e for e in engine.events[start:] if e.event_type == "DAMAGE_ROLLED"]
    assert len(rolls) == 1 and rolls[0].payload["total"] == 3 + bonus


def test_wheel_does_not_bonus_fixed_damage_or_non_damage_rolls():
    engine = wheel()
    actor, target = engine.state.actors[ALLY], engine.state.actors[THEM]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ALLY and a.display_name == "Bi Shou (Dagger) attack")
    ctx = X.Context(engine, actor, action, None, {}, [target], target)
    before, start = target.current_hp, len(engine.events)
    X.run_effects(ctx, [{"type": "damage", "flat": 4, "damage_types": ["force"], "applies_to": "target"}])
    assert before - target.current_hp == 4
    assert not any(e.event_type == "DAMAGE_ROLLED" for e in engine.events[start:])
    from combat.gate2_runtime_models import DiceSpec
    _script(engine, [3])
    assert X._roll(ctx, DiceSpec(count=1, sides=8, modifier=0), "HEAL") == 3


def test_wheel_nonowner_dice_are_unchanged():
    from combat.gate2_runtime_models import DiceSpec
    engine = _fate_fight([])
    ctx = X.Context(engine, engine.state.actors[ME], None, None, {}, [])
    dice = DiceSpec(count=1, sides=8, modifier=2)
    assert X._damage_dice(ctx, dice) is dice
    assert X._damage_dice(ctx, None) is None


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("release", [False, True])
def test_wheel_damage_table_preview_commit_reload(monkeypatch, tmp_path, auto_turn, release):
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_carry import KIT
    from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY as A, RIGHT
    from tests.test_r9i_choices import action, resolve, finish_turn
    from tests.test_r9i_karma_persistence import act

    combat, table, mid = table_fight(tmp_path, [F.WHEEL_ID], ally_talents=[], kit={"starting_kit": KIT}, ask=True)

    # Fix the granted d6 face as a fixture prerequisite through an accepted
    # hold, with evented persisted state. Engine cases above test actual casting.
    def grant(engine):
        engine._apply_condition(engine.state.actors[A], F.WHEEL, F.WHEEL_ID, LEFT, expires_on="UNTIL_REMOVED",
                                data={"kind": "attack", "bonus": 2, "face": 2})
    on_hold(monkeypatch, grant)
    resolve(lambda answers: act(table, mid, action(table, mid, "Hold position"), answers), {})
    monkeypatch.undo()
    from tests.sol109_support import accurate_attacks
    accurate_attacks(monkeypatch, A)
    while table.state(mid)["menu"]["actor_id"] != A:
        finish_turn(table, mid)
    cid = action(table, mid, "Dagger", RIGHT)
    if auto_turn:
        real = combat.controller

        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

            def choose_reaction(self, context):
                if context.reaction_source_id == "choice:needle.wheel_release":
                    from combat.gate2_runtime_models import ReactionDecision
                    return ManualControllerAdapter(lambda _: (cid, ()), lambda c: ReactionDecision(
                        checkpoint=c.checkpoint, reactor_id=c.reactor_id,
                        reaction_source_id=c.reaction_source_id,
                        selection="USE" if release else "DECLINE",
                        option_ids=("release",) if release else ())).choose_reaction(context)
                return real.choose_reaction(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=A, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    start = len(combat._load_session(mid).engine.events)
    send = lambda answers: table.auto_step(mid, 0, answers) if auto_turn else act(table, mid, cid, answers)
    preview = send([])
    assert preview["status"] == "REACTION_REQUIRED", preview
    assert send([])["reaction"] == preview["reaction"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    resolve(send, {"choice:needle.wheel_release": ["release"] if release else None})
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    events = loaded.engine.events[start:]
    packets = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == A and RIGHT in e.target_ids]
    assert len(packets) == 1
    rolled = next(e.payload for e in events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == A)
    weapon = loaded.engine.action_catalog[packets[0].source_definition_id].parameters["typed"]["weapon"]
    assert rolled["modifier"] == weapon["damage"]["modifier"] + (0 if release else 2)
    assert loaded.mechanical.replay()["status"] == "PASS"
    assert bool(F._held(loaded.engine.state.actors[A], F.WHEEL)) == (not release)


def test_wheel_pre_draw_bonus_still_gets_a_post_draw_rewrite(monkeypatch):
    """A passive Wheel bonus on a roll must not skip the after-draw d20_result rewrite."""
    from combat import ext
    engine = _fate_fight(["TURNING_WHEEL_AUSPICE"])
    actor = engine.state.actors[ME]
    engine._apply_condition(actor, F.WHEEL, F.WHEEL_ID, ME, expires_on="UNTIL_REMOVED",
                            data={"kind": "check", "bonus": 2, "face": 4})
    actor.reaction_available = False
    def replace(engine, roll, intent):
        if roll.reason == "REACTION_CONTEST":
            return {"source_id": "test:duel-replace", "operation": "replace", "natural_result": 20}
        return None
    monkeypatch.setitem(ext._HOOKS, "d20_result", [*ext._HOOKS.get("d20_result", []), replace])
    _script(engine, [3])
    start = len(engine.events)
    roll = engine.roll_check(modifier=1, actor_id=ME, reason="REACTION_CONTEST")
    rewrites = [e for e in engine.events[start:] if e.event_type == "D20_REWRITTEN" and e.source_definition_id == "test:duel-replace"]
    assert len(rewrites) == 1
    assert rewrites[0].payload["original"]["modifier"] == 3
    assert roll.natural_result == 20 and roll.modifier == 3 and roll.total == 23
