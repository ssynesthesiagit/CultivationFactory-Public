"""Analyze Qi reports the provenance of effects on a recipient after reload."""
import pytest

from tests.test_a2r09_review_fixes import add_fixture_action, QI
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE


@pytest.mark.parametrize("mundane_on_effect", [False, True])
def test_analyze_qi_external_effects_commit_and_cold_reload(tmp_path, mundane_on_effect):
    def setup(bundles):
        add_fixture_action(bundles[1], "External Qi", [
            {"type": "condition", "condition": "speed_bonus", "applies_to": "target",
             "condition_label": "Aether Ward", "expires_on": "UNTIL_REMOVED"},
            {"type": "condition", "condition": "no_reactions", "applies_to": "target",
             "condition_label": "Meridian Curse", "expires_on": "UNTIL_REMOVED"},
        ], target="ANY_CREATURE")
        mundane = {"type": "condition", "condition": "fatigue", "applies_to": "target",
                   "condition_label": "Mundane fatigue", "expires_on": "UNTIL_REMOVED"}
        if mundane_on_effect:
            mundane["mundane"] = True
        add_fixture_action(bundles[1], "Ordinary Exertion", [mundane], target="ANY_CREATURE")
        if not mundane_on_effect:
            bundles[1]["action_catalog"][-1]["parameters"]["typed"]["mundane"] = True
            from combat.canonical import canonical_sha256
            bundles[1].pop("bundle_sha256", None)
            bundles[1]["bundle_sha256"] = canonical_sha256(bundles[1])

    combat, table, mid = fixture(
        tmp_path, [], primary="Qi", owner_path="Qi Cultivation", seed="A2R09F1-QI",
        owner_features=[QI + "qi_sensing"], bundle_transform=setup,
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    turn(table, mid, ALLY)
    cast = candidate(combat, mid, "External Qi", target=FOE)
    settle(table, mid, cast.candidate_id)
    settle(table, mid, candidate(combat, mid, "Ordinary Exertion", target=FOE).candidate_id)
    loaded = reload(tmp_path, mid)
    effects = [c for c in loaded.state.actors[FOE].conditions.values()
               if c.source_definition_id == cast.source_definition_id]
    assert {c.data["label"] for c in effects} == {"Aether Ward", "Meridian Curse"}
    assert all(c.source_actor_id == ALLY for c in effects)
    assert loaded.action_catalog[cast.source_definition_id].owner_id != FOE
    assert any(c.data.get("label") == "Mundane fatigue"
               for c in loaded.state.actors[FOE].conditions.values())

    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Analyze Qi", target=FOE).candidate_id)
    # A cold service rebuild must replay both the external cast and the reveal.
    loaded = reload(tmp_path, mid)
    rider = next(e.payload["rider"] for e in reversed(loaded.events)
                 if e.event_type == "GM_RIDER" and "Analyze Qi:" in e.payload.get("rider", ""))
    assert loaded.state.actors[FOE].display_name in rider
    assert "supernatural effects are active (Aether Ward, Meridian Curse)" in rider, rider
    assert "one active supernatural tag: Aether Ward" in rider
    assert "none active" not in rider
    assert "Mundane fatigue" not in rider
    assert {c.data["label"] for c in loaded.state.actors[FOE].conditions.values()
            if c.source_definition_id == cast.source_definition_id} == {"Aether Ward", "Meridian Curse"}
