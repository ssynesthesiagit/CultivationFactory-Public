"""C15 healing seam proofs; the test providers are not shipped ability ports."""
from types import SimpleNamespace

import pytest

from combat import ext, typed_executor as te
from combat.ext import life_state, needle
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, ME, FOE, duel
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, on_hold, HOLD, LEFT, RIGHT
from tests.r10_fixup_support import answer

WOUND = "TAL_YIN_WOUND_THAT_REFUSES_DAWN"
PULSE = "tianxia.talent.pressure_points.reversing_pulse"
MARK = "condition:typed.lock9_healing_proof"


def install(monkeypatch, *providers):
    ext._load()
    monkeypatch.setitem(ext._HOOKS, "healing_pending", list(providers))


@pytest.mark.parametrize("kind,typed", [(k, t) for k in ("hp", "temp_hp") for t in (False, True)])
def test_native_and_typed_grants_query_once_with_provenance(monkeypatch, kind, typed):
    engine = duel([])
    healer, target = engine.state.actors[ME], engine.state.actors[FOE]
    target.current_hp = 1
    seen = []
    def reduce(e, recipient, amount, owner, source, grant_kind):
        seen.append((recipient.entity_id, amount, owner.entity_id, source, grant_kind))
        assert recipient.current_hp == 1 and recipient.temporary_hp == 0
        return 3
    install(monkeypatch, reduce)
    if typed:
        ctx = SimpleNamespace(engine=engine, actor=healer, target=target, targets=[target], source="test:heal",
                              numbers={}, dice=lambda *a, **k: None)
        monkeypatch.setattr(te, "_roll", lambda *a: 10)
        monkeypatch.setattr(te, "_default_subject", lambda *a, **k: [target])
        (te.block_healing if kind == "hp" else te.block_temp_hp)(ctx, {"flat": 10})
    elif kind == "hp":
        engine._heal(target, 10, "test:heal", ME)
    else:
        engine._grant_temp_hp(target, 10, "test:heal", ME)
    assert seen == [(FOE, 10, ME, "test:heal", kind)]
    assert (target.current_hp if kind == "hp" else target.temporary_hp) == (8 if kind == "hp" else 7)


def test_stored_reduction_precedes_interception_and_zero_is_inert(monkeypatch):
    engine = duel([])
    target = engine.state.actors[ME]
    engine._add_modifier(target, "test:curse", "healing_reduction", "SET", "half", "self", expires_on="UNTIL_REMOVED")
    seen = []
    install(monkeypatch, lambda e, t, n, *a: seen.append(n) or 3, lambda *a: 4)
    assert te._reduced_healing(engine, target, 20) == 3
    assert seen == [10]
    assert te.healing_pending(engine, target, 0, None, "test:zero", "temp_hp") == 0
    assert seen == [10]


@pytest.mark.parametrize("reply", [True, -1, "2", 1.5])
def test_invalid_provider_cannot_apply_healing(monkeypatch, reply):
    engine = duel([])
    target = engine.state.actors[ME]
    target.current_hp = 1
    install(monkeypatch, lambda *a: reply)
    with pytest.raises(ValueError, match="nonnegative integers"):
        engine._heal(target, 10, "test:heal", ME)
    assert target.current_hp == 1


def test_denied_revival_preserves_soul_and_death_record(monkeypatch):
    engine = duel([])
    target = engine.state.actors[ME]
    target.current_hp = 0
    engine._apply_condition(target, life_state.SOUL, "test:death", ME, expires_on="UNTIL_REMOVED")
    engine._apply_condition(target, life_state.SEAL, "test:seal", ME, expires_on="UNTIL_REMOVED")
    target.turn_flags[life_state.RECORD] = {"ok": 0, "bad": 3}
    before = set(target.conditions)
    seen = []
    install(monkeypatch, lambda *a: seen.append(a[2]) or 99)
    assert life_state._revive(engine, target, 5, "test:return", actor_id=FOE) is False
    assert target.current_hp == 0 and set(target.conditions) == before
    assert target.turn_flags[life_state.RECORD] == {"ok": 0, "bad": 3}
    assert seen == [5]
    install(monkeypatch, lambda *a: seen.append(a[2]) or 2)
    assert life_state._revive(engine, target, 5, "test:return", actor_id=FOE) is True
    assert target.current_hp == 3 and not life_state.is_dead(target)
    assert seen == [5, 5]


@pytest.mark.parametrize("cl,kind", [(10, "hp"), (11, "temp_hp")])
def test_wound_first_or_each_grant_persists_through_table(monkeypatch, tmp_path, cl, kind):
    """Wound That Refuses Dawn: first gain, or each gain at CL 11, reduced by PB."""
    combat, table, mid = table_fight(tmp_path, [WOUND], cl=cl)
    def wound(engine, target, amount, healer, source, grant_kind):
        held = next((c for c in target.conditions.values() if c.condition_id == MARK), None)
        if held is None:
            return None
        assert grant_kind == kind and healer.entity_id == LEFT
        if cl < 11:
            engine._remove_condition(target, MARK, WOUND)
        return 4
    install(monkeypatch, wound)
    def grants(engine):
        target = engine.state.actors[RIGHT]
        engine._apply_condition(target, MARK, WOUND, LEFT, expires_on="START_OF_SOURCE_NEXT_TURN")
        if kind == "hp":
            engine._commit_damage(target, 30, "FORCE", "test:injury", LEFT, None, reaction_depth=0)
        for _ in range(2):
            (engine._heal if kind == "hp" else engine._grant_temp_hp)(target, 10, "test:restore", LEFT)
    on_hold(monkeypatch, grants)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    grants = [e for e in loaded.engine.events if e.source_definition_id == "test:restore"]
    assert [e.payload["offered"] for e in grants] == ([6, 10] if cl < 11 else [6, 6])
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("use", [True, False])
def test_reversing_pulse_pauses_before_grant_and_reloads(monkeypatch, tmp_path, use):
    """A source-backed reaction contract; other Pulse clauses remain rider-owned."""
    combat, table, mid = table_fight(tmp_path, [PULSE])
    def pulse(engine, target, amount, healer, source, kind):
        owner = engine.state.actors[LEFT]
        picked = needle.ask(engine, engine._active_intent, "HEALING_PENDING", owner, "choice:needle.lock9_pulse",
                            ["use"], labels={"use": "Use Reversing Pulse"}, name="Reversing Pulse",
                            prompt=f"Use your Reaction before {target.display_name} gains {amount} Temporary Hit Points?",
                            automatic=False, allow_decline=True, target_id=target.entity_id)
        if not picked:
            return None
        owner.reaction_available = False
        engine._append_event("REACTION_RESOLVED", PULSE, actor_id=LEFT, target_ids=(target.entity_id,),
                             payload={"reaction_name": "Reversing Pulse"})
        return amount // 2
    install(monkeypatch, pulse)
    on_hold(monkeypatch, lambda e: e._grant_temp_hp(e.state.actors[RIGHT], 10, "test:pulse_grant", LEFT))
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    state = table.state(mid)
    menu = state["menu"]
    candidate = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == HOLD)
    def send(answers=()):
        return table.act(mid, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))
    paused = send()
    assert paused["status"] == "REACTION_REQUIRED"
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    prompt = paused["reaction"]
    assert "Reversing Pulse" in str(prompt)
    assert send([answer(prompt, use=use)])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[RIGHT].temporary_hp == (5 if use else 10)
    assert loaded.engine.state.actors[LEFT].reaction_available is not use
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_invalid_hook_rolls_back_earlier_evented_changes(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [])
    def invalid(engine, target, *args):
        engine._apply_condition(target, MARK, "test:invalid", LEFT, expires_on="UNTIL_REMOVED")
        return -1
    install(monkeypatch, invalid)
    on_hold(monkeypatch, lambda e: e._heal(e.state.actors[RIGHT], 10, "test:invalid", LEFT))
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    from combat.gate5_service import CombatServiceError
    with pytest.raises(CombatServiceError):
        act(table, mid, HOLD)
    assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json") == before
