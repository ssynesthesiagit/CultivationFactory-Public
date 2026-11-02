"""Spirit check riders through accepted table actions, cold reload and replay."""
import pytest

from combat.gate5_service import CombatService
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.typed_executor import Context, resolve_opposed_check
from combat.ext.needle import numbers_of
from tests.h1_support import ROOT, script
from tests.r10_fixup_support import cast_sender, commit, fixed_dice
from tests.test_lock2_persistence import act
from tests import test_tabletop_hunt6 as support

P = "tianxia.talent.spirit_companions."
COUNSEL = P + "independent_counsel"
ETHICAL = "insight.ethical-exorcist"
CRUEL = P + "break_the_cruel_seal"
MERCY = P + "exorcist_s_mercy"
USED = "condition:typed.spirit_counsel_used"
LEFT, RIGHT, HOLD = support.LEFT, support.RIGHT, support.HOLD


def fight(tmp_path, monkeypatch, talents, rank=0):
    original = support.sheet

    def sheet(*args, **kwargs):
        doc = original(*args, **kwargs)
        doc["ability_scores_and_statistics"]["skills"] = [
            {"skill": "Arcana", "bonus": 2 + 4 * rank, "proficiency_multiplier": rank}]
        return doc

    monkeypatch.setattr(support, "sheet", sheet)
    return support.table_fight(tmp_path, talents, ally_talents=[], ask=True)


def reload(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


def check_action(owner):
    return ActionDefinition(source_definition_id=HOLD, display_name="Synthetic check",
        owner_id=owner, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="ANY_CREATURE")


def check_on_hold(monkeypatch, spec, *, owner=LEFT, procedure=None):
    def check(engine):
        actor = engine.state.actors[owner]
        action = check_action(owner)
        typed = {"source": HOLD, "numbers": numbers_of(engine, actor)}
        if procedure:
            typed["spirit_procedure"] = procedure
        target = engine.state.actors[RIGHT if owner == LEFT else LEFT]
        ctx = Context(engine, actor, action, engine._active_intent, typed, [target], target, {})
        script(engine, [7, 17, 7, 17])
        resolve_opposed_check(ctx, target, spec, {"kind": "dc", "dc": 15})

    support.on_hold(monkeypatch, check)


def receipts(engine, owner=LEFT):
    return [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.actor_id == owner]


@pytest.mark.parametrize("rank,bonus", [(0, 4), (1, 2), (2, 2)])
def test_counsel_adds_full_or_half_pb_and_survives_reload(tmp_path, monkeypatch, rank, bonus):
    combat, table, mid = fight(tmp_path, monkeypatch, [COUNSEL], rank)
    check_on_hold(monkeypatch, {"kind": "check", "ability": "INT", "skill": "Arcana"})
    prompts = commit(cast_sender(combat, table, mid, "Hold position"),
                     lambda p: ("nature", True))
    assert any(p["reaction"] == "Independent Counsel" for p in prompts)
    engine = reload(tmp_path, mid)
    roll = receipts(engine)[-1].payload["actor"]
    assert roll["modifier"] == 2 + 4 * rank + bonus
    assert any(c.condition_id == USED for c in engine.state.actors[LEFT].conditions.values())
    # Another accepted action after a cold service reload cannot spend it twice.
    combat = CombatService(ROOT, tmp_path)
    from combat.tabletop_service import TabletopService
    table = TabletopService(combat, tmp_path)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    assert commit(cast_sender(combat, table, mid, "Hold position")) == []
    assert receipts(reload(tmp_path, mid))[-1].payload["actor"]["modifier"] == 2 + 4 * rank


def test_counsel_uses_the_printed_short_rest_limit(tmp_path, monkeypatch):
    # Combat has no short-rest transition; the spent marker lasts for the fight.
    import json
    combat, table, mid = fight(tmp_path, monkeypatch, [COUNSEL])
    check_on_hold(monkeypatch, {"kind": "check", "ability": "INT", "skill": "Arcana"})
    prompts = commit(cast_sender(combat, table, mid, "Hold position"), lambda p: ("nature", True))
    assert "once per short rest" in json.dumps(prompts)
    engine = reload(tmp_path, mid)
    used = [c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == USED]
    assert len(used) == 1
    assert used[0].expires_on == "UNTIL_REMOVED"
    label = used[0].data.get("label", "")
    assert "once per short rest" in label


@pytest.mark.parametrize("kind,expected", [("cultivation", 8), ("key_ability", 6)])
def test_counsel_understands_checks_without_a_skill(tmp_path, monkeypatch, kind, expected):
    combat, table, mid = fight(tmp_path, monkeypatch, [COUNSEL])
    check_on_hold(monkeypatch, {"kind": kind})
    commit(cast_sender(combat, table, mid, "Hold position"), lambda p: ("nature", True))
    assert receipts(reload(tmp_path, mid))[-1].payload["actor"]["modifier"] == expected


@pytest.mark.parametrize("owns,accept", [(False, True), (True, False)])
def test_counsel_is_inert_without_ownership_or_when_declined(tmp_path, monkeypatch, owns, accept):
    combat, table, mid = fight(tmp_path, monkeypatch, [COUNSEL] if owns else [])
    check_on_hold(monkeypatch, {"kind": "check", "ability": "INT", "skill": "Arcana"})
    prompts = commit(cast_sender(combat, table, mid, "Hold position"), lambda p: ("nature", accept))
    assert bool(prompts) == owns
    engine = reload(tmp_path, mid)
    assert receipts(engine)[-1].payload["actor"]["modifier"] == 2
    assert not any(c.condition_id == USED for c in engine.state.actors[LEFT].conditions.values())


def test_counsel_asks_the_defending_owner_on_another_creatures_turn(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, monkeypatch, [COUNSEL])
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"

    def defend(engine):
        source = check_action(RIGHT)
        actor, target = engine.state.actors[RIGHT], engine.state.actors[LEFT]
        ctx = Context(engine, actor, source, engine._active_intent,
                      {"source": HOLD, "numbers": numbers_of(engine, actor)}, [target], target, {})
        script(engine, [7, 17])
        resolve_opposed_check(ctx, target, {"kind": "key_ability"},
                             {"kind": "check", "ability": "INT", "skill": "Arcana"})
    support.on_hold(monkeypatch, defend)
    prompts = commit(cast_sender(combat, table, mid, "Hold position"), lambda p: ("nature", True))
    assert len(prompts) == 1 and prompts[0]["reaction"] == "Independent Counsel"
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == USED for c in engine.state.actors[LEFT].conditions.values())
    assert receipts(engine, RIGHT)[-1].payload["target"]["modifier"] == 6


@pytest.mark.parametrize("procedure", [CRUEL, MERCY])
@pytest.mark.parametrize("purpose,advantage", [("free", True), ("calm", True), ("separate", True),
                                              ("release", True), ("coerce", False)])
def test_ethical_exorcist_declares_purpose_on_the_real_procedure(tmp_path, monkeypatch, procedure, purpose, advantage):
    combat, table, mid = fight(tmp_path, monkeypatch, [procedure, ETHICAL])
    fixed_dice(monkeypatch, [7, 17] * 50)
    # Select by source id/target; the question is identified by its menu name ("reaction").
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    assert any(row.get("feature_id") == ETHICAL and row.get("kind") == "ethical"
               for row in engine.typed_passive_rows.get(LEFT, []))
    candidate = next(c for c in engine.legal_candidates()
                     if c.target_ids == (RIGHT,)
                     and (engine.action_catalog[c.source_definition_id].parameters.get("typed") or {}).get("source") == procedure)
    send = lambda answers=(): table.act(mid, candidate.candidate_id, candidate.decision_id,
                                       candidate.state_version, state["last_sequence"], list(answers))
    prompts = commit(send, lambda p: (purpose, True) if p["reaction"] == "Ethical Exorcist" else (None, False))
    assert any(p["reaction"] == "Ethical Exorcist" for p in prompts)
    loaded = reload(tmp_path, mid)
    roll = receipts(loaded)[-1].payload["actor"]
    assert len(roll["dice"]) == (2 if advantage else 1)
    assert roll["total"] - roll["modifier"] == (17 if advantage else 7)


def test_ethical_exorcist_referral_uses_explicit_procedure_identity(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, monkeypatch, [ETHICAL])
    check_on_hold(monkeypatch, {"kind": "cultivation"}, procedure=P + "true_name_mercy")
    prompts = commit(cast_sender(combat, table, mid, "Hold position"), lambda p: ("release", True))
    assert any(p["reaction"] == "Ethical Exorcist" for p in prompts)
    assert len(receipts(reload(tmp_path, mid))[-1].payload["actor"]["dice"]) == 2


def test_ethical_exorcist_does_not_change_unrelated_cultivation_checks(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, monkeypatch, [ETHICAL])
    check_on_hold(monkeypatch, {"kind": "cultivation"})
    assert commit(cast_sender(combat, table, mid, "Hold position")) == []
    assert len(receipts(reload(tmp_path, mid))[-1].payload["actor"]["dice"]) == 1
