"""Qi-Tempered Concentration through CombatService table/session commits and cold replay."""
import pytest
from combat.gate5_service import CombatService
from combat.canonical import canonical_sha256
from tests.h1_support import ROOT
from tests import r1i_service_support as s

INSIGHT = "insight.qi-tempered-concentration"
MANTLE = "TAL_FORCE_FORCE_MANTLE"
TURBULENT = "TAL_QIWEAVING_TURBULENT_FIELD"
CHOICE = "choice:needle.qi_tempered_concentration.maintain"
CONCENTRATION = "system:combat.concentration"


def cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


def resolve(combat, table, mid, cid, choices=None):
    """Drive one table action to a commit, answering every question it asks."""
    choices = choices or {}
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    answers, prompts = [], []
    for _ in range(20):
        menu = table.state(mid)["menu"]
        result = table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        prompt = result["reaction"]
        prompts.append(prompt)
        ids = choices.get(prompt["context"]["reaction_source_id"])
        answer = {**prompt["context"], "selection": "DECLINE"}
        if ids is not None:
            answer.update(selection="USE", option_ids=ids)
        elif prompt.get("choice") and not prompt["choice"].get("allow_decline"):
            answer.update(selection="USE",
                          option_ids=[o["id"] for o in prompt["choice"]["options"]]
                          [:prompt["choice"].get("minimum_selections", 1)])
        answers.append(answer)
    raise AssertionError("Too many prompts")


def add_probe(bundles):
    """A 100-force probe each fighter can aim at a hostile: its damage
    puts the Concentration check's DC at 30, past any save in this fight."""
    for bundle in bundles:
        aid = bundle["actor_id"]
        action = {"source_definition_id": "test:qt.damage." + aid,
                  "display_name": "Incoming concentration damage",
                  "owner_id": aid, "economy": "ACTION", "resolution_kind": "TYPED",
                  "target_kind": "HOSTILE_ENTITY", "range_ft": 60,
                  "parameters": {"typed": {"source": "test:qt.damage", "numbers": {},
                                            "duration": {"kind": "instant"},
                                            "effects": [{"type": "damage", "applies_to": "target",
                                                         "flat": 100, "damage_types": ["force"]}]}}}
        bundle["action_catalog"].append(action)
        bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)


def fixture(monkeypatch, tmp_path, *, owned=True, technique_id=MANTLE,
            technique_name="Force Mantle", con=9, pb=20, isolate_reaction=False):
    """A duel whose left fighter concentrates on ``technique_id`` and owns the
    Insight when ``owned``. The Concentration save is pinned so the probe
    (DC 30) always fails it, while with ``con`` 9 and ``pb`` 20 the Insight's
    Proficiency Bonus turns that failure around for every natural d20."""
    original = s.sheet
    calls = []

    def sheet(mids, **kwargs):
        doc = original(mids, **kwargs)
        if not calls and owned:
            doc.setdefault("spheres_and_talents", {})["cultivation_insight_record_ids"] = [INSIGHT]
        calls.append(1)
        return doc

    monkeypatch.setattr(s, "sheet", sheet)

    def pin_save(bundles):
        add_probe(bundles)
        owner = next(b for b in bundles if b["actor_id"] == s.OWNER)
        owner["actor_template"]["saving_throws"]["CON"] = con
        if isolate_reaction:
            owner["typed_reactions"] = [r for r in owner.get("typed_reactions", [])
                                        if r.get("feature_id") != "TAL_FORCE_COUNTERPRESSURE"]
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)

    combat, table, mid, send, commit = s.fixture(
        tmp_path, [technique_id], wide=True, owner_pb=pb, bundle_transform=pin_save)
    resolve(combat, table, mid, s.candidate(table, mid, technique_name))
    return combat, table, mid, commit


def turn_to(table, mid, commit, who, *, advance=False):
    if advance:
        commit(table.state(mid)["menu"]["end_turn"])
    for _ in range(10):
        if table.state(mid)["menu"]["actor_id"] == who:
            return
        commit(table.state(mid)["menu"]["end_turn"])
    raise AssertionError("Turn not reached")


def probe(table, mid):
    return s.candidate(table, mid, "Incoming concentration damage", s.OWNER)


def test_the_bonus_turns_the_failed_concentration_save_around(tmp_path, monkeypatch):
    """The Insight's printed Reaction: 2 Qi and the Reaction add the
    owner's Proficiency Bonus to the failed Constitution Concentration
    save on a Qi-powered feature, turning the failure into success."""
    combat, table, mid, commit = fixture(monkeypatch, tmp_path)
    engine = cold(tmp_path, mid)
    owner = engine.state.actors[s.OWNER]
    assert owner.concentration is not None  # Force Mantle, concentrating
    assert owner.resources["resource:core.qi"] == 30 - 3  # the Mantle's 3 Qi
    turn_to(table, mid, commit, s.FOE, advance=True)
    prompts = resolve(combat, table, mid, probe(table, mid), {CHOICE: ["maintain"]})
    asked = next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE)
    rendered = str(asked)
    # Plain words for a player who knows only basic D&D: the ability,
    # the trigger, the creature, the roll against the DC, what it
    # does, and what it costs.
    assert "Qi-Tempered Concentration" in rendered
    assert "Constitution" in rendered
    assert "Force Mantle" in rendered
    assert "Reaction" in rendered and "2 Qi" in rendered
    assert "DC 30" in rendered
    assert "This will turn the failure into success." in asked["moment"]
    engine = cold(tmp_path, mid)
    owner = engine.state.actors[s.OWNER]
    assert owner.concentration is not None  # the turned save keeps it
    assert owner.resources["resource:core.qi"] == 30 - 3 - 2  # the Mantle's 3 Qi, then the Insight's 2
    assert not owner.reaction_available  # the Reaction is spent
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == CONCENTRATION and e.actor_id == s.OWNER]
    assert saves and saves[-1].payload["success"]
    assert saves[-1].payload["total"] >= saves[-1].payload["dc"] == 30
    rewrites = [e for e in engine.events if e.event_type == "D20_REWRITTEN"
                and e.source_definition_id == INSIGHT]
    assert len(rewrites) == 1
    assert rewrites[0].payload["operation"] == "bonus"
    assert rewrites[0].payload["bonus"] == 20
    assert rewrites[0].payload["result"]["total"] == rewrites[0].payload["original"]["total"] + 20
    assert any(e.event_type == "REACTION_WINDOW_OPENED" and e.source_definition_id == INSIGHT
               for e in engine.events)
    assert any(e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == INSIGHT
               and "Qi-Tempered Concentration" in e.payload.get("log", "")
               for e in engine.events)


def test_a_fighter_without_the_insight_loses_the_concentration(tmp_path, monkeypatch):
    """Default-inert: without the Insight's row, the failed save ends the
    Concentration and no save is rewritten."""
    combat, table, mid, commit = fixture(monkeypatch, tmp_path, owned=False)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[s.OWNER].concentration is not None
    qi = engine.state.actors[s.OWNER].resources["resource:core.qi"]
    turn_to(table, mid, commit, s.FOE, advance=True)
    prompts = resolve(combat, table, mid, probe(table, mid))
    assert not any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    engine = cold(tmp_path, mid)
    owner = engine.state.actors[s.OWNER]
    assert owner.concentration is None  # the failed save ends it
    assert owner.resources["resource:core.qi"] == qi
    assert owner.reaction_available
    assert not any(e.event_type == "D20_REWRITTEN" and e.source_definition_id == INSIGHT
                   for e in engine.events)


def test_a_concentration_on_a_feature_that_costs_no_qi_gets_nothing(tmp_path, monkeypatch):
    """The printed trigger is a Qi-powered feature: a Concentration on a
    feature whose own costs draw from no Qi pool is not offered the Bonus."""
    combat, table, mid, commit = fixture(monkeypatch, tmp_path,
                                          technique_id=TURBULENT, technique_name="Turbulent Field")
    engine = cold(tmp_path, mid)
    assert engine.state.actors[s.OWNER].concentration is not None  # Turbulent Field
    turn_to(table, mid, commit, s.FOE, advance=True)
    prompts = resolve(combat, table, mid, probe(table, mid))
    assert not any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[s.OWNER].concentration is None
    assert not any(e.event_type == "D20_REWRITTEN" and e.source_definition_id == INSIGHT
                   for e in engine.events)


def test_a_bonus_that_cannot_turn_the_save_is_declined(tmp_path, monkeypatch):
    """The Bonus only "potentially" turns failure into success: pinned so
    the Bonus can never reach DC 30 (Con 5 + PB 4 tops out at 29), the
    Reaction is still offered on the printed trigger, and declining it
    leaves the failed save standing."""
    combat, table, mid, commit = fixture(monkeypatch, tmp_path, con=5, pb=4)
    engine = cold(tmp_path, mid)
    qi = engine.state.actors[s.OWNER].resources["resource:core.qi"]
    turn_to(table, mid, commit, s.FOE, advance=True)
    prompts = resolve(combat, table, mid, probe(table, mid))
    asked = next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE)
    assert "Add your Proficiency Bonus (+4) for a total of" in asked["moment"]
    assert "This save will still fail." in asked["moment"]
    assert "to turn the failure into success?" not in asked["moment"]
    engine = cold(tmp_path, mid)
    owner = engine.state.actors[s.OWNER]
    assert owner.concentration is None
    assert owner.resources["resource:core.qi"] == qi
    assert owner.reaction_available
    assert not any(e.event_type == "D20_REWRITTEN" and e.source_definition_id == INSIGHT
                   for e in engine.events)


def test_ai_retains_legal_bonus_even_when_it_prefers_to_decline(tmp_path, monkeypatch):
    from combat.ext import qi_tempered, needle
    combat, table, mid, commit = fixture(monkeypatch, tmp_path, con=5, pb=4, isolate_reaction=True)
    turn_to(table, mid, commit, s.FOE, advance=True)
    combat.set_controller_mode(mid, actor_id=s.OWNER, controller_mode="LOCAL_AUTO")
    before = cold(tmp_path, mid).state.actors[s.OWNER].resources["resource:core.qi"]
    specs = []
    original = qi_tempered.ask
    def capture(engine, intent, checkpoint, chooser, choice_id, options, **kwargs):
        # Check the same option spec consumed by automatic/model controllers;
        # no live model is contacted. The real service still resolves it.
        assert needle.ai_controlled(engine, chooser)
        context = {"needle_options": options, "automatic": kwargs.get("automatic", True),
                   "allow_decline": kwargs["allow_decline"]}
        specs.append(needle.option_spec(choice_id, context))
        assert kwargs.get("automatic_options") is None
        return original(engine, intent, checkpoint, chooser, choice_id, options, **kwargs)
    monkeypatch.setattr(qi_tempered, "ask", capture)
    resolve(combat, table, mid, probe(table, mid))
    assert specs and all(spec["option_ids"] == ["maintain"] and not spec["automatic_use"] for spec in specs)
    owner = cold(tmp_path, mid).state.actors[s.OWNER]
    assert owner.concentration is None and owner.reaction_available
    assert owner.resources["resource:core.qi"] == before
