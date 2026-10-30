"""Healing interception through real table transactions and persisted replay.

Test-only compiled Mend actions prepare a wound/mark and offer a fixed 20 HP
or Temporary HP. They isolate recipient choice from healing dice and target
adapters; the actual healing, reactions, decisions and persistence are real.
"""
import copy

import pytest

from combat import typed_executor as te
from combat.canonical import canonical_sha256
from combat.ext import healing_interception as healing
from tests.r1i_service_support import OWNER, FOE, SECOND, candidate, fixture, force_ai_candidate
from tests.test_r1i_round3 import reload, resolve
from tests.test_riders_c15 import MEND, REVERSING, WOUND, _scripted_d20


def healing_table(tmp_path, ability, kind, relation, *, own_turn=False):
    mark = "Pressure Point" if ability == REVERSING else "Waning Mark"

    def prepare(bundles):
        for bundle in bundles:
            for action in list(bundle["action_catalog"]):
                if action["parameters"].get("typed", {}).get("source") != MEND:
                    continue
                is_owner = bundle["actor_id"] == OWNER
                action["target_kind"] = ("HOSTILE_ENTITY" if relation == "foe" else "ALLY_OR_SELF") if is_owner else (
                    "ALLY_OR_SELF" if relation == "foe" else "HOSTILE_ENTITY")
                action["range_ft"] = 30
                typed = action["parameters"]["typed"]
                typed["range_ft"] = 30
                applies = "self" if (is_owner and relation == "self" or not is_owner and relation == "foe") else "target"
                typed["effects"] = ([
                    {"type": "damage", "flat": 40, "damage_type": "UNTYPED", "applies_to": applies},
                    {"type": "mark", "mark": mark, "applies_to": applies},
                ] if bundle["actor_id"] == OWNER else [
                    {"type": "healing" if kind == "hp" else "temp_hp", "flat": 20, "applies_to": applies},
                ])
                if is_owner and own_turn:
                    # Prepare a self mark with a Bonus Action, then heal in the
                    # same player turn through a separate real typed Action.
                    heal = copy.deepcopy(action)
                    heal["source_definition_id"] += ".test_self_heal"
                    heal["display_name"] = "Test self healing"
                    heal["target_kind"] = "SELF"
                    heal["parameters"]["typed"]["effects"] = [
                        {"type": "healing" if kind == "hp" else "temp_hp", "flat": 20, "applies_to": "self"}]
                    bundle["action_catalog"].append(heal)
                    bundle["actor_template"]["action_ids"].append(heal["source_definition_id"])
                    action["economy"] = "BONUS_ACTION"
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    return fixture(tmp_path, [ability, MEND], foe_talents=[MEND], allies=[SECOND], bundle_transform=prepare)


CASES = [(ability, kind, relation) for ability in (REVERSING, WOUND)
         for kind in ("hp", "temp_hp") for relation in ("foe", "ally", "self")]


@pytest.mark.parametrize("ability,kind,relation", CASES)
@pytest.mark.parametrize("auto_turn", [False, True])
def test_player_can_intercept_marked_foe_ally_or_self_on_either_turn(tmp_path, monkeypatch, ability, kind, relation, auto_turn):
    _scripted_d20(monkeypatch, lambda actor, reason: 1 if reason.startswith("SAVE:") else None)
    combat, table, mid, send, commit = healing_table(tmp_path, ability, kind, relation)
    target = {"foe": FOE, "ally": SECOND, "self": OWNER}[relation]
    commit(candidate(table, mid, "Mend the Pulse", target))
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Mend the Pulse", target)
    if auto_turn:
        force_ai_candidate(combat, mid, FOE, cid)
    initial = reload(tmp_path, mid)
    hp = initial.state.actors[target].current_hp
    choice = "choice:needle.reversing_pulse" if ability == REVERSING else "choice:needle.diminish_recovery"
    _, prompts = resolve(combat, mid, send, cid, {choice: "use" if ability == REVERSING else "spend"}, auto=auto_turn)
    asked = [p for p in prompts if p["context"]["reaction_source_id"] == choice]
    assert len(asked) == 1 and asked[0]["context"]["reactor_id"] == OWNER
    prompt = asked[0]
    assert prompt["action"] == "Mend the Pulse"
    assert prompt["trigger_actor"] == "Foe"
    assert prompt["affected"] == {"foe": "Foe", "ally": "Second", "self": "Owner"}[relation]
    assert "from Foe using Mend the Pulse" in prompt["moment"]
    label = prompt["choice"]["options"][0]["label"]
    if ability == REVERSING:
        assert "your Reaction" in label and "on a failure" in label and "on a success" in label
    else:
        assert "no action" in label and "Once a round" in prompt["moment"]
    if ability == WOUND and relation != "foe":
        assert "only if it benefits that creature" in prompt["moment"]
    engine = reload(tmp_path, mid)
    subject, owner = engine.state.actors[target], engine.state.actors[OWNER]
    cut = 10 if ability == REVERSING else min(20, next(
        r["pb"] + r["key_mod"] for r in engine.typed_passive_rows[OWNER] if r.get("block") == healing.DIMINISH))
    expected = 20 - cut
    assert subject.current_hp == hp + (expected if kind == "hp" else 0)
    assert subject.temporary_hp == (expected if kind == "temp_hp" else 0)
    if ability == REVERSING:
        assert not owner.reaction_available
    else:
        assert not te.bears_mark(subject, OWNER, "Waning Mark")
        assert owner.turn_flags[healing.ONCE] == engine.state.round_number
        record, = [c for c in subject.conditions.values() if c.condition_id == healing.RECORD]
        assert record.data["reduce"] == 4 and record.data["each"] == 1
    assert combat._load_session(mid).mechanical.replay()["status"] == "PASS"
    logs = [str(e.payload.get("log") or "") for e in engine.events[len(initial.events):]]
    assert any("from Foe using Mend the Pulse" in line for line in logs)


@pytest.mark.parametrize("ability,kind,relation", CASES)
def test_ai_interceptor_prefers_foes_and_preserves_allied_recovery(tmp_path, monkeypatch, ability, kind, relation):
    _scripted_d20(monkeypatch, lambda actor, reason: 1 if reason.startswith("SAVE:") else None)
    combat, table, mid, send, commit = healing_table(tmp_path, ability, kind, relation)
    target = {"foe": FOE, "ally": SECOND, "self": OWNER}[relation]
    commit(candidate(table, mid, "Mend the Pulse", target))
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    hp = reload(tmp_path, mid).state.actors[target].current_hp
    _, prompts = resolve(combat, mid, send, candidate(table, mid, "Mend the Pulse", target), {})
    assert not prompts
    engine = reload(tmp_path, mid)
    subject, owner = engine.state.actors[target], engine.state.actors[OWNER]
    hostile = relation == "foe"
    cut = (10 if ability == REVERSING else next(
        r["pb"] + r["key_mod"] for r in engine.typed_passive_rows[OWNER] if r.get("block") == healing.DIMINISH)) if hostile else 0
    assert subject.current_hp == hp + (20 - cut if kind == "hp" else 0)
    assert subject.temporary_hp == (20 - cut if kind == "temp_hp" else 0)
    assert owner.reaction_available == (not hostile or ability != REVERSING)
    if ability == WOUND:
        assert te.bears_mark(subject, OWNER, "Waning Mark") == (not hostile)
        assert bool([c for c in subject.conditions.values() if c.condition_id == healing.RECORD]) == hostile


@pytest.mark.parametrize("ability", [REVERSING, WOUND])
@pytest.mark.parametrize("relation", ["ally", "self"])
def test_player_can_decline_intercepting_allied_healing(tmp_path, ability, relation):
    combat, table, mid, send, commit = healing_table(tmp_path, ability, "hp", relation)
    target = SECOND if relation == "ally" else OWNER
    commit(candidate(table, mid, "Mend the Pulse", target))
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    initial = reload(tmp_path, mid)
    _, prompts = resolve(combat, mid, send, candidate(table, mid, "Mend the Pulse", target), {})
    choice = "choice:needle.reversing_pulse" if ability == REVERSING else "choice:needle.diminish_recovery"
    assert any(p["context"]["reaction_source_id"] == choice for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[target].current_hp == initial.state.actors[target].current_hp + 20
    assert engine.state.actors[OWNER].reaction_available
    if ability == WOUND:
        assert te.bears_mark(engine.state.actors[target], OWNER, "Waning Mark")
        assert healing.ONCE not in engine.state.actors[OWNER].turn_flags
        assert not [c for c in engine.state.actors[target].conditions.values() if c.condition_id == healing.RECORD]


@pytest.mark.parametrize("ability", [REVERSING, WOUND])
def test_player_is_asked_about_self_healing_on_their_own_turn(tmp_path, monkeypatch, ability):
    _scripted_d20(monkeypatch, lambda actor, reason: 1 if reason.startswith("SAVE:") else None)
    combat, table, mid, send, commit = healing_table(tmp_path, ability, "hp", "self", own_turn=True)
    commit(candidate(table, mid, "Mend the Pulse", OWNER))
    initial = reload(tmp_path, mid)
    assert table.state(mid)["menu"]["actor_id"] == OWNER
    choice = "choice:needle.reversing_pulse" if ability == REVERSING else "choice:needle.diminish_recovery"
    _, prompts = resolve(combat, mid, send, candidate(table, mid, "Test self healing"),
                         {choice: "use" if ability == REVERSING else "spend"})
    asked = next(p for p in prompts if p["context"]["reaction_source_id"] == choice)
    assert asked["trigger_actor"] == asked["affected"] == "Owner"
    assert asked["action"] == "Test self healing"
    engine = reload(tmp_path, mid)
    cut = 10 if ability == REVERSING else next(
        r["pb"] + r["key_mod"] for r in engine.typed_passive_rows[OWNER] if r.get("block") == healing.DIMINISH)
    assert engine.state.actors[OWNER].current_hp == initial.state.actors[OWNER].current_hp + 20 - cut
