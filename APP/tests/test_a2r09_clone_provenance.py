"""Shadow Clone Array remains an identifiable Qi effect after count updates."""

import pytest
from types import SimpleNamespace

from combat.canonical import canonical_sha256
from combat.ext import tabik_ninpo as ninpo
from tests.test_a2r09_review_fixes import add_fixture_action, NINPO, QI
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE


@pytest.mark.parametrize("replace_clone", [False, True])
def test_analyze_qi_after_clone_interposition_commit_and_cold_reload(tmp_path, replace_clone):
    def setup(bundles):
        foe = bundles[2]
        add_fixture_action(foe, "Enemy attack", [
            {"type": "attack", "attack_kind": "melee", "no_damage": True, "on_hit": []},
        ], target="HOSTILE_ENTITY")
        foe["action_catalog"][-1]["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        foe.pop("bundle_sha256", None)
        foe["bundle_sha256"] = canonical_sha256(foe)

    combat, table, mid = fixture(
        tmp_path, [], cl=18, ask=False, owner_path="Qi Cultivation", seed="A2R09F3-ARRAY",
        owner_features=[NINPO + "shadow_clone_array", QI + "qi_sensing"],
        bundle_transform=setup, battlefield_transform=lambda arena: arena.update(terrain_regions=[]),
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 2, "y": 6}, FOE: {"x": 4, "y": 6}})
    activation = candidate(combat, mid, "Shadow Clone Array")
    settle(table, mid, activation.candidate_id)
    engine = reload(tmp_path, mid)
    original = next(c for c in engine.state.actors[OWNER].conditions.values()
                    if c.condition_id == ninpo.CLONES)
    original_identity = (original.instance_id, original.source_definition_id,
                         original.source_actor_id, original.applied_sequence, original.expires_on)
    assert original.source_definition_id == activation.source_definition_id
    assert original.data["clones"] == 2

    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, "Enemy attack", target=OWNER).candidate_id,
                     picks={"choice:needle.clone_interposition": "interpose"})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.clone_interposition"
               for p in prompts)
    engine = reload(tmp_path, mid)
    assert ninpo.clone_count(engine, engine.state.actors[OWNER]) == 1
    assert any(e.event_type == "PASSIVE_TRIGGERED" and "destroys a Shadow Clone" in e.payload.get("log", "")
               for e in engine.events)

    turn(table, mid, OWNER)
    if replace_clone:
        settle(table, mid, candidate(combat, mid, "Replace a Clone").candidate_id)
        engine = reload(tmp_path, mid)
        assert ninpo.clone_count(engine, engine.state.actors[OWNER]) == 2
    from combat.ext import qi_sensing

    analysis = candidate(combat, mid, "Analyze Qi", target=OWNER)
    action = engine.action_catalog[analysis.source_definition_id]
    assert qi_sensing.analyze_qi_ai_candidate(
        engine, engine.state.actors[OWNER], analysis, action) is True
    settle(table, mid, analysis.candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    held = next(c for c in actor.conditions.values() if c.condition_id == ninpo.CLONES)
    rider = next(e.payload["rider"] for e in reversed(engine.events)
                 if e.event_type == "GM_RIDER" and "Analyze Qi:" in e.payload.get("rider", ""))
    # Assert the player-visible bug before the stronger provenance invariant.
    assert "supernatural effects are active (Shadow Clone Array:" in rider, rider
    assert "one active supernatural tag: Shadow Clone Array:" in rider, rider
    assert "none active" not in rider
    assert not any(c.condition_id == "condition:typed.analyze_qi_failed"
                   for c in actor.conditions.values())
    assert not any(e.event_type == "CHECK_ROLLED" and e.source_definition_id == analysis.source_definition_id
                   for e in engine.events)
    assert held.data["label"] in rider
    assert held.data["clones"] == (2 if replace_clone else 1)
    assert held.data["replaced"] is replace_clone
    assert (held.instance_id, held.source_definition_id, held.source_actor_id,
            held.applied_sequence, held.expires_on) == original_identity, (
                "Shadow Clone Array activation provenance must survive clone updates")
    updates = [e for e in engine.events if e.event_type == "CONDITION_UPDATED"
               and e.payload.get("instance_id") == original.instance_id]
    assert [e.payload["data"]["clones"] for e in updates] == ([1, 2] if replace_clone else [1])


def test_analyze_self_still_checks_explicit_qi_concealment(tmp_path, monkeypatch):
    from combat.ext import ability_source, qi_sensing

    monkeypatch.setattr(ability_source, "cultivation_check_detail", lambda *a, **kw: (0, False))

    def setup(bundles):
        add_fixture_action(bundles[0], "Conceal Qi", [
            {"type": "condition", "condition": "concealed", "applies_to": "target",
             "expires_on": "UNTIL_REMOVED", "condition_data": {"label": "Qi concealment"}},
        ], target="ANY_CREATURE")

    combat, table, mid = fixture(
        tmp_path, [], primary="Qi", owner_path="Qi Cultivation", bundle_transform=setup,
        owner_features=[QI + "qi_sensing"], seed="A2R09F7-SELF-CONCEALMENT")
    settle(table, mid, candidate(combat, mid, "Conceal Qi", target=OWNER).candidate_id)
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Analyze Qi", target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert any(c.condition_id == "condition:typed.analyze_qi_failed"
               and c.data["target"] == OWNER for c in actor.conditions.values())
    rider = next(e.payload["rider"] for e in reversed(engine.events)
                 if e.event_type == "GM_RIDER" and "Analyze Qi:" in e.payload.get("rider", ""))
    assert "its Qi concealment holds" in rider
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == "Analyze Qi")
    assert qi_sensing.analyze_qi_candidate(
        engine, actor, SimpleNamespace(target_ids=(OWNER,)), action) is False
