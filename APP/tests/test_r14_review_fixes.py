"""Focused R14 review interactions, including persisted observation provenance."""
import json

import pytest

from combat import stealth, zones
from combat.ext.eye_common import passive_perception
from combat.ext.mind_hidden_eye import FOCUS, mark_analyzed
from combat.ext.riders14_research import KNOWN
from combat.typed_executor import Context
from test_auto_lane1 import ME, AN, _engine, _payloads, _ready, _use
from test_auto_lane4 import _script
from test_riders_lane14 import PREFIX, attack, bundle, mark


def test_shared_search_views_preserve_a_d20_replacement():
    from combat.gate2_rolls import DeterministicRollAuthority

    raw = DeterministicRollAuthority("review").d20(modifier=2, actor_id=ME, reason="CHECK:Search", mode="DISADVANTAGE")
    replaced = raw.model_copy(update={"natural_result": 20, "total": 22})
    assert stealth.search_roll_view(replaced, "DISADVANTAGE") is replaced
    assert stealth.search_roll_view(replaced, "NORMAL").total == 22
    assert stealth.search_roll_view(replaced, "ADVANTAGE").natural_result == 20


def test_paid_deadly_strike_retains_light_obscurement_eligibility():
    e = _engine(bundle(PREFIX + "DEADLY_STRIKE", PREFIX + "GREATER_STALKER"))
    _use(e, "Deadly Strike: first hidden attack: spend Martial Focus before rolling; on hit, +PBd6 instead of +PB")
    me = e.state.actors[ME]
    action = next(iter(e.action_catalog.values()))
    zones.create(Context(e, me, action, None, {"numbers": {}}, []),
                 {"shape": "sphere", "size_ft": 5, "obscured": "light", "centered_on_self": True,
                  "duration": {"kind": "minutes", "amount": 1}})
    assert not stealth.hidden(me)
    assert not any(c.condition_id == "condition:typed.invisible" for c in me.conditions.values())
    _script(e, [15, 2, 3, 4, 5, 6])
    events = attack(e)
    assert me.resources[FOCUS] == 0
    assert any(x.event_type == "DAMAGE_COMMITTED" and x.source_definition_id.endswith(".deadly_strike_empowered") for x in events)
    assert not me.turn_flags["eye_deadly_paid"]


@pytest.mark.parametrize("natural", [20, 15])
def test_modify_characteristics_reads_current_attack_with_exploit_damage(natural, monkeypatch):
    from combat import ext

    e = _engine(bundle(PREFIX + "MODIFY_CHARACTERISTICS", PREFIX + "EXPLOIT_WEAKNESS"))
    # Exercise production's alphabetical plugin order even if other test
    # modules imported Research early during collection.
    monkeypatch.setitem(ext._HOOKS, "after_hit", sorted(ext._HOOKS["after_hit"], key=lambda hook: hook.__module__))
    me, foe = e.state.actors[ME], e.state.actors[AN]
    mark(e)
    e._apply_condition(me, KNOWN, "test:learned", ME, expires_on="UNTIL_REMOVED",
                       data={"target_id": AN, "name": "Armor Class", "value": 10})
    from r14_reaction_answers import answers
    answers(e, {"modify_maximum": ["Armor Class"], "eye_exploit_weakness": ["exploit"]})
    # An old critical against the same target must not leak into this attack.
    e._append_event("DAMAGE_ROLLED", "test:previous", actor_id=ME, target_ids=(AN,), payload={"critical": True})
    # The native optional choice must be answered explicitly.
    from combat.gate2_runtime_models import ReactionDecision
    def choose(request):
        selected = request["reaction_source_id"] == "choice:needle.modify_maximum"
        if not selected:
            return None, None  # Preserve existing defaults for Exploit Weakness.
        return ReactionDecision(**{k: request[k] for k in ("checkpoint", "reactor_id", "reaction_source_id")},
                                selection="USE" if selected else "DECLINE",
                                option_ids=("Armor Class",) if selected else ()), None
    e.set_reaction_provider(choose)
    _script(e, [natural, 1, 1, 1, 1, 1])
    events = attack(e)
    assert any(x.source_definition_id.endswith(".exploit_weakness") for x in events if x.event_type == "DAMAGE_COMMITTED")
    assert me.resources[FOCUS] == (0 if natural == 20 else 1)
    assert [m.value for m in foe.modifiers.values() if m.target_field == "armor_class"] == ([-2] if natural == 20 else [])


@pytest.mark.parametrize("action", ["Search", "Thousand-Lantern Sweep"])
def test_incarnation_search_cancels_all_native_opposing_modes(action):
    from combat.ext.riders14_eye import INCARNATION

    e = _engine(bundle(PREFIX + "THOUSAND_LANTERN_SWEEP", PREFIX + "SOVEREIGN_HIDDEN_EYE_INCARNATION"))
    me, foe = e.state.actors[ME], e.state.actors[AN]
    # Outside Incarnation's sense range, so this exercises the Search roll.
    foe.position = foe.position.model_copy(update={"x": 12})
    e._apply_condition(me, INCARNATION, "test:incarnation", ME, expires_on="UNTIL_REMOVED")
    for mode in ("ADVANTAGE", "DISADVANTAGE"):
        e._apply_condition(me, "condition:typed.check_mode", "test:" + mode, ME, expires_on="UNTIL_REMOVED",
                           data={"rule": {"check_mode": {"WIS": mode}}})
    e._apply_condition(foe, stealth.HIDDEN, "test:hidden", AN, expires_on="UNTIL_REMOVED", data={"stealth_total": 40})
    _script(e, [10, 20])
    before = e.roller.counter
    events = _use(e, action)
    rolls = [p["actor"] for p in _payloads(events, "CHECK_ROLLED") if p.get("actor")]
    assert rolls and all(r["mode"] == "NORMAL" for r in rolls)
    assert e.roller.counter == before + 1
    assert stealth.hidden(foe)


@pytest.mark.parametrize("protection", ["stealth_surge", "muffled"])
@pytest.mark.parametrize("incarnation", [False, True])
def test_sweep_reuses_dice_with_each_targets_search_protection(protection, incarnation):
    from combat.ext.riders14_eye import INCARNATION

    protected = "actor:review.protected"
    e = _engine(bundle(PREFIX + "THOUSAND_LANTERN_SWEEP"),
                allies=(bundle(*(["tianxia.talent.the_hidden_eye.stealth_surge"] if protection == "stealth_surge" else []),
                               actor_id=protected),))
    me, other, foe = (e.state.actors[aid] for aid in (ME, protected, AN))
    other.team_id = foe.team_id
    foe.position = foe.position.model_copy(update={"x": 12, "y": 6})
    other.position = other.position.model_copy(update={"x": 13, "y": 6})
    if incarnation:
        e._apply_condition(me, INCARNATION, "test:incarnation", ME, expires_on="UNTIL_REMOVED")
    mark_analyzed(e, other, me, "test:analyzed")
    if protection == "muffled":
        e._apply_condition(other, zones.ZONE_EFFECT, "test:muffled", protected, expires_on="UNTIL_REMOVED", data={"muffles": True})
    for target in (foe, other):
        e._apply_condition(target, stealth.HIDDEN, "test:hidden", target.entity_id, expires_on="UNTIL_REMOVED", data={"stealth_total": 15})
    _script(e, [2, 18] if incarnation else [18, 2])
    before = e.roller.counter
    events = _use(e, "Thousand-Lantern Sweep")
    assert e.roller.counter == before + 2
    assert stealth.hidden(foe) is None
    assert stealth.hidden(other)
    checks = {x.target_ids[0]: x.payload["actor"] for x in events if x.event_type == "CHECK_ROLLED" and x.target_ids}
    assert checks[AN]["mode"] == ("ADVANTAGE" if incarnation else "NORMAL")
    assert checks[protected]["mode"] == ("NORMAL" if incarnation else "DISADVANTAGE")
    assert checks[AN]["counter_start"] == checks[protected]["counter_start"]
    assert checks[AN]["dice"] == checks[protected]["dice"]


def test_unrepresented_cooperative_observation_is_a_gm_rider_without_spending():
    from combat.ext.riders14_awareness import PERCEPTION, cooperative_perception

    e = _engine(bundle(PREFIX + "COOPERATIVE_PERCEPTION"))
    e._active_intent = object()  # no choice should be reached without observation provenance
    cooperative_perception(e, "CHECK_ROLLED", {"actor_id": ME, "target_ids": (),
        "payload": {"check": "Perception", "actor": {"total": 30}}})
    assert e.state.actors[ME].resources[FOCUS] == 1
    assert not any(c.condition_id == PERCEPTION for a in e.state.actors.values() for c in a.conditions.values())
    assert any(event.event_type == "GM_RIDER" and "observation" in event.payload["rider"] for event in e.events)


def test_cooperative_observation_scope_survives_table_commit_reload(monkeypatch, tmp_path):
    from combat.ext.riders14_awareness import PERCEPTION
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_lock2_persistence import act
    from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, table_fight, on_hold, HOLD

    combat, table, mid = table_fight(tmp_path, [PREFIX + "COOPERATIVE_PERCEPTION"], ask=True, ally_talents=[])

    def observe(engine):
        # Synthetic represented Perception Analyze observation inside a real
        # accepted action; the transaction owns intent, choices and persistence.
        engine._append_event("CHECK_ROLLED", "test:analyze", actor_id=LEFT, target_ids=(RIGHT,),
            payload={"actor": {"total": 30, "roll_id": "roll:observation", "counter_start": 42,
                               "reason": "CHECK:analyze:perception"}})

    on_hold(monkeypatch, observe)
    menu = table.state(mid)["menu"]
    candidate = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == HOLD)
    result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], 0, [])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert all(name in prompt["moment"] for name in ("Cooperative Perception", "Analyze", "Right"))
    result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], 0,
                       [{**prompt["context"], "selection": "USE", "option_ids": [ALLY]}])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    ally, owner, observed = (engine.state.actors[aid] for aid in (ALLY, LEFT, RIGHT))
    condition = next(c for c in ally.conditions.values() if c.condition_id == PERCEPTION)
    assert json.loads(condition.data["observation_totals"]) == {RIGHT: 30}
    assert all(type(v) in (str, int) for v in condition.data.values())
    assert condition.data["observation_roll"] == "roll:observation"
    assert passive_perception(engine, ally, observed) == 30
    baseline = passive_perception(engine, ally)
    # The owner is visible now but was outside the single-target observation.
    assert passive_perception(engine, ally, owner) == baseline
    observed.position = observed.position.model_copy(update={"x": 11, "y": 7})
    owner.position = owner.position.model_copy(update={"x": 19, "y": 19})
    assert passive_perception(engine, ally, observed) == baseline
    assert loaded.mechanical.replay()["status"] == "PASS"
