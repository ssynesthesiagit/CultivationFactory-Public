"""Echo commitment interrupts one paid Reaction, never the responder dispatcher."""
import pytest

from combat import ext, typed_reactions as reactions
from combat.ext import drum_body, healing_interception, needle, treasure_armor
from combat.gate5_service import CombatService
from combat.typed_executor import bears_mark, mark_condition_id
from tests.h1_support import ROOT
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import ALLY, HOLD, LEFT, RIGHT, on_hold, table_fight

ECHO = drum_body.PREFIX + "internal_echo"
SHIELD = treasure_armor.PREFIX + "deflecting_shield_face"
PULSE = healing_interception.PULSE_ID


def echo(engine, reactor, source):
    engine._apply_condition(reactor, drum_body.ECHOING, ECHO, source.entity_id,
        expires_on=f"END_OF_SOURCE_TURN_AT:{int(source.turns_started) + 1}",
        data={"label": "Echoing", "pb": 4, "save_dc": 50, "cl": 15})


@pytest.mark.parametrize("lethal", [True, False])
@pytest.mark.parametrize("consumer", ["shield", "pulse"])
def test_paid_echo_interrupts_only_its_owner_and_survives_table_reload(tmp_path, monkeypatch, consumer, lethal):
    combat, table, mid = table_fight(tmp_path, [PULSE] if consumer == "pulse" else [])
    asked, at_echo = [], []

    def accept(engine, intent, checkpoint, owner, *args, **kwargs):
        asked.append(owner.entity_id)
        return ["use"]

    if consumer == "shield":
        row = {"feature_id": SHIELD, "name": "Deflecting Shield Face", "numbers": {"pb": 4}}
        monkeypatch.setattr(treasure_armor, "owned", lambda engine, actor, kind:
                            row if kind == "deflecting_shield_face" and actor.entity_id in (LEFT, ALLY) else None)
        monkeypatch.setattr(treasure_armor, "ask", accept)
    else:
        monkeypatch.setattr(needle, "ask", accept)

    def observe(engine, event_type, kwargs):
        if event_type == "DAMAGE_COMMITTED" and (kwargs.get("payload") or {}).get("damage_type") == "THUNDER":
            owner = engine.state.actors[LEFT]
            at_echo.append((owner.reaction_available, owner.resources["resource:core.qi"]))

    ext._load()
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), observe])

    def trigger(engine):
        asked_before, echo_before = len(asked), len(at_echo)
        first, second, enemy = [engine.state.actors[k] for k in (LEFT, ALLY, RIGHT)]
        if lethal:
            engine._commit_damage(first, first.current_hp - 1, "FORCE", "test:injury", RIGHT, None, reaction_depth=99)
        echo(engine, first, enemy)
        if consumer == "shield":
            from combat.damage_context import AttackDamage
            packet = AttackDamage("test:incoming", RIGHT, ALLY, 1, "roll:test:incoming", 15, 25, False)
            engine._commit_damage(second, 50, "FORCE", "test:incoming", RIGHT, engine._active_intent,
                                  reaction_depth=0, attack_context=packet)
        else:
            for owner in (first, second):
                engine._apply_condition(enemy, mark_condition_id("Pressure Point", owner.entity_id), PULSE,
                                        owner.entity_id, expires_on="END_OF_CURRENT_TURN")
            engine._grant_temp_hp(enemy, 20, "test:healing", RIGHT)
        assert asked[asked_before:] == ([LEFT, ALLY] if consumer == "shield" or lethal else [LEFT])
        assert at_echo[echo_before:] == [(False, 29 if consumer == "shield" else 30)]

    on_hold(monkeypatch, trigger)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    first, second = engine.state.actors[LEFT], engine.state.actors[ALLY]
    assert (first.current_hp == 0) is lethal
    assert first.life_state == ("DYING" if lethal else None)
    assert not first.reaction_available
    assert not any(c.condition_id == drum_body.ECHOING for c in first.conditions.values())
    assert asked and at_echo  # Each prediction/commit was checked separately above.
    resolved = [e.actor_id for e in engine.events if e.event_type == "REACTION_RESOLVED"
                and e.source_definition_id == (SHIELD if consumer == "shield" else PULSE)]
    if consumer == "shield":
        assert resolved == ([ALLY] if lethal else [LEFT, ALLY])
        assert first.resources["resource:core.qi"] == second.resources["resource:core.qi"] == 29
    else:
        assert resolved == ([ALLY] if lethal else [LEFT])
        assert 0 < engine.state.actors[RIGHT].temporary_hp < 20
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("lethal", [True, False])
def test_knot_pays_mark_before_echo_and_commits_only_surviving_effects(tmp_path, monkeypatch, lethal):
    from tests.test_auto105_puppetry_movement import (
        KNEE, OWNED, NO_OA, LEFT as KEEPER, RIGHT as WALKER, far_move, has_mark,
        move_sender, scene, turn_to, MARK_EFFECTS,
    )
    from tests.auto28_puppetry_support import resolve
    from tests.auto_worker1_support import reload

    # Seal the native kit and payment fixture explicitly: public exports do
    # not preserve every prose-derived compiler opt-in/name. The same real
    # provider, payment effects, movement and dispatcher run on both copies.
    from combat import factory_compiler
    from combat.canonical import canonical_sha256
    from combat.ext import vessel
    compile_character = factory_compiler.compile_character
    def compile_fixture(*args, **kwargs):
        bundle = compile_character(*args, **kwargs)
        if bundle["actor_id"] == KEEPER:
            # Trigger classification itself reads prose, so supply the whole
            # synthetic row rather than assuming the public compiler made one.
            row = {"feature_id": KNEE, "block": "generic", "name": "Knot the Knee",
                   "kind": "moved", "min_move_ft": 10, "range_ft": 60,
                   "requires_mark": "Tension Mark", "mark_on": "subject",
                   "numbers": {"pb": 4, "cl": 15, "save_dc": 100}, "costs": [],
                   "effects": [
                    {"type": "spend_mark", "mark": "Tension Mark", "applies_to": "target"},
                    {"type": "save", "ability": "dex", "dc": "technique_save_dc",
                     "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target"}],
                     "on_success": [{"type": "speed", "flat": -10, "applies_to": "target",
                                     "expires_on": "END_OF_CURRENT_TURN"}]},
                ]}
            bundle["typed_reactions"] = [r for r in bundle.get("typed_reactions", [])
                                         if r.get("feature_id") != KNEE] + [row]
            for action in bundle["action_catalog"]:
                params = action.get("parameters") or {}
                if params.get("vessel_kit"):
                    params["vessel_native"] = True
                    params["vessel_owned"] = sorted({*params.get("vessel_owned", []), KNEE})
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        return bundle
    monkeypatch.setattr(factory_compiler, "compile_character", compile_fixture)
    combat, table, mid, _ = scene(tmp_path, [*OWNED, KNEE], marked=False)
    # Evented fixture setup is committed separately, so both the Echo and a
    # lethal HP threshold survive a cold session before the triggering walk.
    turn_to(table, mid, KEEPER)
    def prepare(engine):
        keeper, walker = engine.state.actors[KEEPER], engine.state.actors[WALKER]
        # Use the same evented mark effect as scene's setup action. Its NONE
        # economy action is not a table menu option on this baseline.
        from combat.ext.states import context
        from combat.typed_executor import run_effects
        run_effects(context(engine, keeper, KNEE, [walker], {"pb": 4, "cl": 15, "save_dc": 100}), MARK_EFFECTS)
        if lethal:
            engine._commit_damage(keeper, keeper.current_hp - 1, "FORCE", "test:injury", WALKER, None, reaction_depth=99)
        echo(engine, keeper, walker)
    with monkeypatch.context() as setup:
        on_hold(setup, prepare)
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
    turn_to(table, mid, WALKER)
    engine = reload(combat, mid)
    assert has_mark(engine.state.actors[WALKER], KEEPER)
    kit = vessel.kit(engine, engine.state.actors[KEEPER])
    assert kit is not None and kit["native"] and KNEE in kit["owned"]
    reaction = next(row for row in engine.typed_reaction_rows[KEEPER] if row.get("feature_id") == KNEE)
    assert reaction["effects"][0] == {"type": "spend_mark", "mark": "Tension Mark", "applies_to": "target"}
    at_detonation = []

    def observe(engine, event_type, kwargs):
        if event_type == "DAMAGE_COMMITTED" and (kwargs.get("payload") or {}).get("damage_type") == "THUNDER":
            at_detonation.append((bears_mark(engine.state.actors[WALKER], KEEPER, "Tension Mark"),
                                  engine.state.actors[KEEPER].reaction_available))

    ext._load()
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), observe])
    resolve(move_sender(table, mid, far_move(engine, engine.state.actors[WALKER], 10)), NO_OA)
    after = reload(combat, mid)
    assert at_detonation and all(value == (False, False) for value in at_detonation)
    assert not has_mark(after.state.actors[WALKER], KEEPER)
    assert (after.state.actors[KEEPER].current_hp == 0) is lethal
    assert after.state.actors[KEEPER].life_state == ("DYING" if lethal else None)
    saves = [e for e in after.events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == KNEE]
    receipts = [e for e in after.events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == KNEE]
    assert len(saves) == len(receipts) == (0 if lethal else 1)


def test_rolled_back_reaction_retries_its_notification_and_payment(monkeypatch):
    from tests.test_internal_echo_movement import _echoed, FOE, ME

    engine, _ = _echoed()
    source = "test:retry_dispatch"
    rows = {"feature_id": source}
    hits = []
    ext._load()
    monkeypatch.setitem(ext._HOOKS, "reaction_committed",
                        [*ext._HOOKS.get("reaction_committed", []), lambda *args: hits.append(True)])
    before = engine.state.model_dump(mode="json")
    for attempt in range(2):
        with pytest.raises(RuntimeError, match="retry after effects"):
            with engine._transaction(source, "intent:identical_retry", FOE):
                actor = engine.state.actors[FOE]
                with reactions.reaction_resolution(engine, actor, source):
                    reactions.open_reaction(engine, rows, actor, (ME,), "TEST_RETRY")
                    # A second commitment helper in this window must not notify twice.
                    reactions.spend_reaction(engine, actor, rows)
                    assert not any(c.condition_id == drum_body.ECHOING for c in actor.conditions.values())
                    raise RuntimeError("retry after effects")
        assert engine.state.model_dump(mode="json") == before
    assert hits == [True, True]


def test_direct_commit_notification_cache_is_enrolled_in_transaction_rollback():
    from tests.test_internal_echo_movement import _echoed, FOE

    engine, _ = _echoed()
    assert "_reaction_commit_notifications" not in engine.__dict__
    with pytest.raises(RuntimeError, match="rollback direct commitment"):
        with engine._transaction("test:direct_commit", "intent:direct_commit", FOE):
            reactions._notify_reaction_committed(engine, engine.state.actors[FOE],
                                                 {"feature_id": "test:direct_commit"})
            raise RuntimeError("rollback direct commitment")
    assert "_reaction_commit_notifications" not in engine.__dict__


@pytest.mark.parametrize("lethal", [True, False])
def test_native_builtin_defense_uses_the_same_paid_dispatcher(monkeypatch, lethal):
    from types import SimpleNamespace
    from combat.gate2_engine import Gate2Engine
    from combat.gate2_runtime_content import AN
    from tests.test_riders_c7 import ME, bundle, fight

    engine = fight(bundle([ECHO]))
    reactor = engine.state.actors[AN]
    reactor.current_hp = 1 if lethal else 1000
    reactor.reaction_available = True
    reactor.resources["resource:an_eui.stamina"] = 2
    reactor.resources["resource:an_eui.severance_edge"] = 0
    echo(engine, reactor, engine.state.actors[ME])
    monkeypatch.setattr(engine, "_reaction_decision", lambda *args, **kwargs:
                        SimpleNamespace(selection="USE", spend=1, option_ids=()))
    remaining = Gate2Engine._resolve_damage_reaction(engine, reactor, 20, None, 0)
    assert (remaining == 20) if lethal else (remaining < 20)
    assert reactor.resources["resource:an_eui.stamina"] == 1
    assert not reactor.reaction_available
    assert reactor.active is not lethal
    receipts = [e for e in engine.events if e.event_type == "REACTION_RESOLVED"
                and e.source_definition_id == "reaction:core.stamina_guard"]
    assert len(receipts) == (0 if lethal else 1)
