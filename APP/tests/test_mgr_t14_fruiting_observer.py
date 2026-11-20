"""Source-qualified Fruiting delivery through paid native sessions and cold reload."""

import pytest

from combat import senses, target_knowledge
from combat.ext.mushroom_dreamwalker import FRUIT, field_of, fruiting_qualified
from combat.gate2_runtime_models import ActionIntent, ActionDefinition, EconomyKind
from combat.gate4_persistence import Gate4Persistence
from tests.test_riders_c8 import ROOT, ME, FOE, MW_ALL, RES, bundle

UNQUALIFIED = "actor:fruit.unqualified"


def fixture_action(compiled, name, effects, target_kind="ANY_CREATURE"):
    """Ordinary typed fixture actions commit setup; the Fruiting action is unchanged."""
    action = ActionDefinition(source_definition_id=f"action:test.fruit.{name}", display_name=name,
        owner_id=compiled["actor_template"]["entity_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind=target_kind,
        range_ft=60, parameters={"free_primary": True, "typed": {"source": f"test:{name}", "effects": effects,
                                          "numbers": {}, "duration": {"kind": "until_removed"}, "riders": []}})
    compiled["action_catalog"].append(action.model_dump(mode="json"))
    compiled["actor_template"]["action_ids"].append(action.source_definition_id)


def condition(name, applies_to="target"):
    return {"type": "condition", "condition": name, "applies_to": applies_to,
            "duration": {"kind": "until_removed"}, "harmful": False}


def commit(session, name, target=None):
    candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name
                     and (target is None or target in c.target_ids))
    return session.mechanical.execute_intent(ActionIntent(
        intent_id=f"fruit-{len(session.engine.events)}", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))


def session_at(tmp_path, qualification="Dream-Spore Mark", mark_owner=ME, independent=0):
    persistence = Gate4Persistence(ROOT, tmp_path)
    walker, foe, other = bundle(MW_ALL), bundle([], actor_id=FOE), bundle([], actor_id=UNQUALIFIED)
    conceal = [condition("hidden"), condition("invisible")]
    fixture_action(walker, "Fixture conceal", conceal)
    if qualification != "none":
        effects = ([{"type": "mark", "mark": qualification, "applies_to": "target",
                     "duration": {"kind": "until_removed"}}]
                   if qualification in ("Resonance", "Dream-Spore Mark") else [condition(qualification)])
        fixture_action(walker if mark_owner == ME else other, "Fixture qualify", effects)
    fixture_action(walker, "Fixture blind", [condition("blinded", "self")], "SELF")
    if independent:
        walker.setdefault("senses", {}).setdefault("rows", []).append(
            {"feature_id": "test:independent", "sense": "blindsight", "range_ft": independent, "when": "always"})
    session = persistence.create_match(match_seed="MGR-T14-FRUIT", typed_bundles=(walker, foe, other),
        roster_setup={"primary_actor_ids": [ME, FOE, UNQUALIFIED],
                      "team_by_actor": {ME: "team:a", FOE: "team:b", UNQUALIFIED: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6},
                                             UNQUALIFIED: {"x": 6, "y": 7}}})
    if qualification != "none":
        while session.engine.state.current_actor_id != mark_owner:
            commit(session, "End turn")
        commit(session, "Fixture qualify", FOE)
    while session.engine.state.current_actor_id != ME:
        commit(session, "End turn")
    commit(session, "Fixture conceal", UNQUALIFIED)
    commit(session, "Fixture conceal", FOE)
    commit(session, "Fixture blind")
    return persistence, session


def test_paid_activation_delivers_owned_spore_to_blinded_observer_after_cold_reload(tmp_path):
    persistence, session = session_at(tmp_path)
    engine = session.engine
    viewer, target = engine.state.actors[ME], engine.state.actors[FOE]
    assert not senses.perceives(engine, viewer, target)
    before = viewer.resources[RES]
    commit(session, "Fruiting Body of the Dream")
    assert viewer.resources[RES] == before - 10
    grants = [c for c in viewer.conditions.values() if c.condition_id == senses.SENSE]
    assert grants and all(c.source_actor_id == ME for c in grants)
    assert all(engine.action_catalog[c.source_definition_id].parameters["typed"]["source"] == FRUIT
               and c.data["source"] == c.source_definition_id for c in grants)
    assert not senses.of(engine, viewer, unrestricted_only=True).get("blindsight")
    loaded = persistence.load_match(session.match_id)
    engine = loaded.engine
    viewer, target = engine.state.actors[ME], engine.state.actors[FOE]
    assert senses.perceives(engine, viewer, target)
    projection = senses.perception(engine, viewer)
    assert projection["sensed_creatures"][FOE] == ["blindsight"]
    assert UNQUALIFIED not in projection["creatures"]
    assert senses.finds(engine, viewer, target)
    other = engine.state.actors[UNQUALIFIED]
    assert not senses.of(engine, other).get("blindsight")
    assert not senses.perceives(engine, other, target)
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("qualification,mark_owner,expected", [
    ("poisoned", ME, True), ("frightened", ME, True), ("charmed", ME, True),
    ("Resonance", ME, True), ("Dream-Spore Mark", ME, True),
    ("Resonance", UNQUALIFIED, False), ("Dream-Spore Mark", UNQUALIFIED, False),
    ("none", ME, False),
], ids=["poisoned", "frightened", "charmed", "owned-resonance", "owned-spore",
        "wrong-owner-resonance", "wrong-owner-spore", "unqualified"])
def test_five_categories_observer_search_and_pairwise_agree(tmp_path, qualification, mark_owner, expected):
    persistence, session = session_at(tmp_path, qualification, mark_owner)
    commit(session, "Fruiting Body of the Dream")
    loaded = persistence.load_match(session.match_id)
    engine = loaded.engine
    viewer, target = engine.state.actors[ME], engine.state.actors[FOE]
    assert field_of(engine, viewer) is not None
    stored = [c.model_dump(mode="json") for c in viewer.conditions.values() if c.condition_id == senses.SENSE]
    assert stored and all(c["source_actor_id"] == ME and c["data"]["range_ft"] == 60 for c in stored)
    before = engine.state.model_dump(mode="json"), [e.model_dump(mode="json") for e in engine.events]
    for _ in range(2):
        assert fruiting_qualified(engine, viewer, target) is expected
        assert senses.perceives(engine, viewer, target) is expected
        assert target_knowledge.can_see(engine, viewer, target) is expected
        assert senses.finds(engine, viewer, target) is expected
        assert (engine._attack_mode(viewer, target) == "NORMAL") is expected
        projection = senses.perception(engine, viewer)
        assert (FOE in projection["creatures"]) is expected
        if expected:
            assert projection["sensed_creatures"][FOE] == ["blindsight"]
        assert UNQUALIFIED not in projection["creatures"]
        assert not senses.perceives_cell(engine, viewer, target.position)
        assert not senses.of(engine, viewer, unrestricted_only=True).get("blindsight")
        assert "against_conditions" in senses.of(engine, viewer)["blindsight"]
    assert before == (engine.state.model_dump(mode="json"), [e.model_dump(mode="json") for e in engine.events])
    commit(loaded, "End turn")
    while loaded.engine.state.current_actor_id != ME:
        commit(loaded, "End turn")
    commit(loaded, "Search")
    checks = [e for e in loaded.engine.events if e.event_type == "CHECK_ROLLED" and FOE in e.target_ids]
    assert checks and bool(checks[-1].payload.get("by_sense")) is expected
    cold = persistence.load_match(session.match_id)
    assert cold.verify()["status"] == "PASS"
    assert cold.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("boundary", ["inactive", "removed", "beyond60feet"])
def test_live_field_and_range_boundaries(tmp_path, boundary):
    persistence, session = session_at(tmp_path)
    commit(session, "Fruiting Body of the Dream")
    engine = persistence.load_match(session.match_id).engine
    viewer, target = engine.state.actors[ME], engine.state.actors[FOE]
    assert senses.finds(engine, viewer, target)
    # Boundary probes alter only this test's cold-loaded local engine. No claim
    # about an unrelated field-removal action or altitude/movement is made.
    if boundary == "inactive":
        field_of(engine, viewer).active = False
    elif boundary == "removed":
        engine.state.zones.pop(field_of(engine, viewer).zone_id)
    else:
        target.position = target.position.model_copy(update={"z": 13})
        assert engine._distance_actor_to_actor(viewer, target) > 60
    assert not senses.finds(engine, viewer, target)
    assert not target_knowledge.can_see(engine, viewer, target)
    assert FOE not in senses.perception(engine, viewer)["creatures"]
    assert engine._attack_mode(viewer, target) != "NORMAL"


@pytest.mark.parametrize("feet", [10, 90])
def test_independent_blindsight_keeps_its_own_range_and_permission(tmp_path, feet):
    persistence, session = session_at(tmp_path, independent=feet)
    commit(session, "Fruiting Body of the Dream")
    loaded = persistence.load_match(session.match_id)
    engine = loaded.engine
    viewer, qualified, unrelated = (engine.state.actors[a] for a in (ME, FOE, UNQUALIFIED))
    assert senses.reach(engine, viewer, "blindsight", qualified) == max(60, feet)
    assert senses.reach(engine, viewer, "blindsight", unrelated) == feet
    assert senses.of(engine, viewer, unrestricted_only=True)["blindsight"]["range_ft"] == feet
    assert senses.perceives(engine, viewer, unrelated) is (feet == 90)
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
