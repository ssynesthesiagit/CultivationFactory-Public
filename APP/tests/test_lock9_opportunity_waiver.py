"""Native OA proofs for C15 grant contracts, using test-only entitlement providers."""
import pytest

from combat import ext, typed_reactions as tr
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService, CombatServiceError
from tests.h1_support import ROOT, ME, FOE, duel, script
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, on_hold, HOLD, LEFT, RIGHT
from tests.test_tabletop_hunt6_weapon_availability import STAFF

STAFF_FEATURE = "tianxia.subpath.body.bojutsu.feature.heavenly_staff_barrier"
ADAMANT = "TAL_GUARDIAN_ADAMANT_GUARDIAN_INCARNATION"
USED = "test:lock9.extra_reaction_round"


def install(monkeypatch, *providers):
    ext._load()
    monkeypatch.setitem(ext._HOOKS, "reaction_spend", list(providers))


def extra(feature, owner, commits, *, staff_only=False):
    def provider(engine, actor, row, commit):
        if actor.entity_id != owner or actor.reaction_available or actor.turn_flags.get(USED) == engine.state.round_number:
            return None
        if row.get("reaction_kind") != "opportunity_attack":
            return None
        if staff_only:
            typed = engine.action_catalog[row["action_id"]].parameters["typed"]
            if not typed.get("opportunity_of", "").endswith(".weapon.gun"):
                return None
        if commit:
            commits.append((actor.entity_id, row["reaction_kind"]))
            actor.turn_flags[USED] = engine.state.round_number
            ext.note(engine, feature, actor, f"{actor.display_name} uses an additional Reaction for an Opportunity Attack.")
        return "free"
    return provider


def trigger(engine, reactor_id=ME, mover_id=FOE, intent=None):
    reactor, mover = engine.state.actors[reactor_id], engine.state.actors[mover_id]
    row = tr.opportunity_reaction_row(engine, reactor)
    reach = int(row.get("reach_ft") or 5)
    previous = Position(x=reactor.position.x + reach // 5, y=reactor.position.y)
    nxt = Position(x=previous.x + 1, y=previous.y)
    before = len(engine.events)
    engine._resolve_leave_reach(mover, previous, nxt, intent)
    return [e for e in engine.events[before:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == reactor_id]


@pytest.mark.parametrize("feature,kit,staff_only", [(STAFF_FEATURE, STAFF, True), (ADAMANT, None, False)])
def test_ordinary_then_one_extra_oa_and_preview_is_pure(monkeypatch, feature, kit, staff_only):
    engine = duel([feature], cl=20, kit=kit)
    actor = engine.state.actors[ME]
    commits = []
    install(monkeypatch, extra(feature, ME, commits, staff_only=staff_only))
    script(engine, [12] * 50)
    assert trigger(engine)
    assert not actor.reaction_available and not commits
    for _ in range(3):
        assert tr.opportunity_reach(engine, actor) is not None
    assert not commits and USED not in actor.turn_flags
    assert trigger(engine)
    assert len(commits) == 1 and not actor.reaction_available
    assert not trigger(engine)
    assert len(commits) == 1


def test_staff_grant_rejects_nonstaff_and_no_reactions(monkeypatch):
    engine = duel([STAFF_FEATURE])
    actor = engine.state.actors[ME]
    actor.reaction_available = False
    install(monkeypatch, extra(STAFF_FEATURE, ME, [], staff_only=True))
    assert tr.opportunity_reach(engine, actor) is None
    install(monkeypatch, lambda *args: "free")
    engine._apply_condition(actor, "condition:typed.incapacitated", "test:stop", FOE, expires_on="UNTIL_REMOVED")
    assert tr.opportunity_reach(engine, actor) is None
    assert not trigger(engine)


def test_only_first_provider_spends_and_free_preserves_ordinary_reaction(monkeypatch):
    engine = duel([])
    actor = engine.state.actors[ME]
    calls = []
    install(monkeypatch, lambda *args: calls.append("first") or "free", lambda *args: calls.append("second") or "free")
    tr.spend_reaction(engine, actor, tr.opportunity_reaction_row(engine, actor))
    assert calls == ["first"] and actor.reaction_available


@pytest.mark.parametrize("reply", [True, 1, "yes"])
def test_invalid_waiver_is_strict(monkeypatch, reply):
    engine = duel([])
    actor = engine.state.actors[ME]
    install(monkeypatch, lambda *args: reply)
    with pytest.raises(ValueError, match="reaction_spend"):
        tr.spend_reaction(engine, actor, tr.opportunity_reaction_row(engine, actor))
    assert actor.reaction_available


@pytest.mark.parametrize("use", [True, False])
def test_extra_oa_choice_commit_reload_and_replay(monkeypatch, tmp_path, use):
    combat, table, mid = table_fight(tmp_path, [STAFF_FEATURE], cl=20, kit=STAFF, ask=True, ally_talents=[])
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    commits = []
    install(monkeypatch, extra(STAFF_FEATURE, LEFT, commits, staff_only=True))
    def leave(engine):
        actor = engine.state.actors[LEFT]
        actor.reaction_available = False
        engine._append_event("REACTION_RESOLVED", "test:prior", actor_id=LEFT, target_ids=(RIGHT,))
        trigger(engine, LEFT, RIGHT, engine._active_intent)
    on_hold(monkeypatch, leave)
    state = table.state(mid)
    menu = state["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == HOLD)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    def send(answers=()):
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))
    paused = send()
    assert paused["status"] == "REACTION_REQUIRED"
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert commits == []
    response = {**paused["reaction"]["context"], "selection": "USE" if use else "DECLINE", "option_ids": []}
    assert send([response])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert (USED in actor.turn_flags) is use
    assert not actor.reaction_available
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_legacy_oa_uses_the_same_waiver(monkeypatch):
    from types import SimpleNamespace
    engine = duel([])
    engine.state.actors[FOE].reaction_available = False
    commits = []
    install(monkeypatch, extra(ADAMANT, FOE, commits))
    monkeypatch.setattr(engine, "_reaction_decision", lambda *a, **k: SimpleNamespace(selection="USE", option_ids=[]))
    script(engine, [12] * 50)
    assert trigger(engine, FOE, ME)
    assert commits == [(FOE, "opportunity_attack")]
    assert not engine.state.actors[FOE].reaction_available


def test_failed_commit_rolls_back_grant_receipt(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [])
    def invalid(engine, actor, row, commit):
        if commit:
            engine._apply_condition(actor, "condition:typed.test_waiver", "test:waiver", actor.entity_id, expires_on="UNTIL_REMOVED")
            raise ValueError("test grant failed")
        return "free"
    install(monkeypatch, invalid)
    on_hold(monkeypatch, lambda e: tr.spend_reaction(e, e.state.actors[LEFT], tr.opportunity_reaction_row(e, e.state.actors[LEFT])))
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    with pytest.raises(CombatServiceError):
        act(table, mid, HOLD)
    assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json") == before
