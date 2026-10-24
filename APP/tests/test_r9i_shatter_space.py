"""Shatter Space uses normal saves/damage and asks its owner through the table."""
import pytest

from combat import typed_executor as X
from combat.ext import ice_fracture as I, fate_riders as F
from tests.test_riders_lane9 import _ice_fight, _lattice_under, ME, THEM
from tests.h1_support import ROOT


def setup(dc=99):
    engine = _ice_fight([], dc=dc)
    _lattice_under(engine, THEM)
    return engine, engine.state.actors[ME], engine.state.actors[THEM]


def test_shatter_space_respects_save_against_prone():
    engine, caster, target = setup()
    X.block_advantage(I._ctx(engine, target, target, "test:brace", "Brace"), {
        "type": "advantage", "applies_to": "self", "expires_on": "UNTIL_REMOVED",
        "on": "saving throws against being knocked Prone"})
    I._shatter(engine, caster, target, 15, 4)
    save = next(e for e in engine.events if e.event_type == "SAVE_ROLLED")
    assert save.payload["mode"] == "ADVANTAGE"


def test_shatter_space_uses_pending_fate_reaction():
    engine, caster, target = setup()
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    bundle = compile_character(sheet(["TAL_FATE_TWIST_OF_FATE"], cl=15), actor_id=ME)
    engine.typed_reaction_rows[ME] = bundle["typed_reactions"]
    I._shatter(engine, caster, target, 15, 4)
    assert any(e.event_type == "REACTION_WINDOW_OPENED" and e.payload.get("checkpoint") == "D20_PENDING"
               for e in engine.events)


def test_shatter_space_allows_normal_paid_damage_response():
    import copy
    from combat.gate2_runtime_models import ActionIntent
    from combat.factory_compiler import compile_character
    from tests.test_generic_reactions import AUTHORITY, REACTOR_SHEET
    engine, caster, target = setup()
    # Reuse the existing generic-reaction fixture; this verifies dispatch,
    # without changing or inventing any ability's production rules.
    authority = copy.deepcopy(AUTHORITY)
    authority["mechanics"]["IRON_SKIN"]["effects"][0]["damage_types"] = ["cold"]
    bundle = compile_character(REACTOR_SHEET, actor_id=THEM, typed_authority=authority)
    engine.typed_reaction_rows[THEM] = bundle["typed_reactions"]
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == ME)
    engine._active_intent = ActionIntent(intent_id="test:shatter", decision_id=candidate.decision_id,
                                        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ME)
    before = target.resources["resource:core.qi"]
    I._shatter(engine, caster, target, 15, 4)
    assert target.resources["resource:core.qi"] == before - 2
    assert not target.reaction_available
    resolved = next(e for e in engine.events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == "IRON_SKIN")
    assert resolved.payload["pending_after"] == resolved.payload["pending_before"] // 2


@pytest.mark.parametrize("success", [False, True])
def test_shatter_space_respects_empty_bank_evasion(success):
    from combat.ext import flowing_river
    engine, caster, target = setup(-100 if success else 99)
    engine.typed_passive_rows[THEM].append({"block": "flowing_river", "kind": "empty_bank_evasion"})
    target.resources[flowing_river.FOCUS] = 1
    hp = target.current_hp
    I._shatter(engine, caster, target, 15, 4)
    assert target.resources[flowing_river.FOCUS] == 0
    if success:
        assert target.current_hp == hp
    else:
        rolled = next(e.payload["total"] for e in engine.events if e.event_type == "DAMAGE_ROLLED")
        assert hp - target.current_hp == rolled // 2
        assert any("prone" in c.condition_id for c in target.conditions.values())


@pytest.mark.parametrize("success", [False, True])
def test_shatter_space_wheel_and_stored_fracture_in_one_damage_roll(success):
    engine, caster, target = setup(-100 if success else 99)
    zone = I.lattice_zones(engine, ME)[0]
    cell = (target.position.x, target.position.y)
    engine._apply_condition(caster, F.WHEEL, F.WHEEL_ID, ME, expires_on="UNTIL_REMOVED",
                            data={"kind": "attack", "bonus": 2, "face": 2})
    engine._apply_condition(caster, I.STORED, I.T + "WINTER_STORES_THE_BLOW", ME, expires_on="UNTIL_REMOVED",
                            data={"amount": 5, "x": cell[0], "y": cell[1], "zone_id": zone.zone_id})
    I._shatter(engine, caster, target, 15, 4)
    rolled = next(e.payload for e in engine.events if e.event_type == "DAMAGE_ROLLED")
    assert rolled["modifier"] == 7  # no Key modifier for the base Shatter Space
    packets = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]
    assert len(packets) == 1
    assert packets[0].payload["rolled_or_pending_damage"] == (rolled["total"] // 2 if success else rolled["total"])
    assert not any(c.condition_id == I.STORED for c in caster.conditions.values())
    assert not I.lattice_cells(engine, ME)


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("damage_type", ["COLD", "PIERCING"])
@pytest.mark.parametrize("use", [False, True])
def test_shatter_space_native_turn_end_choices_preview_commit_reload(monkeypatch, tmp_path, auto_turn, damage_type, use):
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.gate5_service import CombatService
    from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, RIGHT
    from tests.test_r9i_choices import action, resolve, finish_turn
    from tests.test_r9i_karma_persistence import act

    combat, table, mid = table_fight(tmp_path, [I.T + "WINTER_STORES_THE_BLOW"], ally_talents=[], ask=True)
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        finish_turn(table, mid)

    # Establish evented trigger prerequisites during an accepted hold. The
    # tested shatter itself runs from the native END_TURN, without injection.
    def prepare(engine):
        caster, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        I._lattice_at(engine, caster, target, "ICE_BASE_CRYSTALLIZE_PATH")
        I.give_mark(engine, caster, target, I.BASE)
        X.block_advantage(I._ctx(engine, target, target, "test:brace", "Brace"), {
            "type": "advantage", "applies_to": "self", "expires_on": "UNTIL_REMOVED",
            "on": "saving throws against being knocked Prone"})
    on_hold(monkeypatch, prepare)
    resolve(lambda answers: act(table, mid, action(table, mid, "Hold position"), answers), {})
    monkeypatch.undo()
    cid = table.state(mid)["menu"]["end_turn"]
    if auto_turn:
        real = combat.controller
        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    start = len(combat._load_session(mid).engine.events)
    send = lambda answers: table.auto_step(mid, 0, answers) if auto_turn else act(table, mid, cid, answers)
    first = send([])
    assert first["status"] == "REACTION_REQUIRED", first
    assert send([])["reaction"] == first["reaction"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    target = combat._load_session(mid).engine.state.actors[RIGHT]
    seen = resolve(send, {"choice:needle.fracture_response": ["shatter"] if use else None,
                          "choice:needle.shatter_space": [f"{target.position.x},{target.position.y}"],
                          "choice:needle.shatter_type": [damage_type]})
    assert ("choice:needle.shatter_space" in seen) == use
    assert ("choice:needle.shatter_type" in seen) == use
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    events = loaded.engine.events[start:]
    packets = [e for e in events if e.event_type == "DAMAGE_COMMITTED"]
    if use:
        assert next(e for e in events if e.event_type == "SAVE_ROLLED").payload["mode"] == "ADVANTAGE"
        assert len(packets) == 1 and packets[0].payload["damage_type"] == damage_type
    else:
        assert not packets and not any(e.event_type == "SAVE_ROLLED" for e in events)
    assert I.marked(loaded.engine.state.actors[RIGHT], LEFT) == (not use)
    assert bool(I.lattice_cells(loaded.engine, LEFT)) == (not use)
    assert loaded.mechanical.replay()["status"] == "PASS"
