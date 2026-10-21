"""A2BLACKSMIr9: persisted defense interactions for Quench's outcome seam."""
import pytest

from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.ext.blacksmith_forge import mark_count
from tests.worker2_support import fixture, reload, OWNER, FOE, ROOT
from tests.test_a2_blacksmith import press
from tests.test_a2_blacksmith_second_pass import setup, declare, die, QUENCH


def add_reaction(bundles, *, kind, effects=(), ac=None, index=2, feature="test:r9:defense"):
    row = {"block": "hit_ac" if kind == "hit_ac" else "generic", "feature_id": feature, "name": "Measured Guard",
           "kind": kind, "ask": True, "range_ft": 30, "costs": [],
           "numbers": {"pb": 4}, "effects": list(effects)}
    if ac is not None:
        row.update(ac=ac, resource_id="resource:core.qi", cost=1)
    bundles[index]["typed_reactions"].append(row)
    bundles[index].pop("bundle_sha256", None)
    bundles[index]["bundle_sha256"] = canonical_sha256(bundles[index])


@pytest.mark.parametrize("natural", [10, 1])
def test_quench_paid_hit_survives_reduction_only_self_response(tmp_path, monkeypatch, natural):
    """A reduction-only hit response cannot re-compare Quench's replaced outcome to the old AC."""
    die(monkeypatch, natural=natural)
    def configure(bundles):
        setup(3 if natural != 1 else 12)(bundles)
        add_reaction(bundles, kind="hit", effects=[{"type": "damage_modifier", "applies_to": "self", "flat": 2}])
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=configure)
    declare(combat, table, mid, "weapon")
    before = combat._load_session(mid).engine.state.actors[FOE].current_hp
    prompts = press(combat, table, mid, "Sword", FOE,
                    picks={"choice:needle.blacksmith_quench": ["quench"],
                           "reaction:typed.test:r9:defense": ["USE"]})
    e = reload(tmp_path, mid)
    assert any(p.get("context", {}).get("reaction_source_id") == "choice:needle.blacksmith_quench" for p in prompts)
    assert e.state.actors[FOE].current_hp < before
    raw, = [x.payload['total'] for x in e.events if x.event_type == 'DAMAGE_ROLLED' and x.actor_id == OWNER]
    assert before - e.state.actors[FOE].current_hp == raw - 2
    assert not e.state.actors[OWNER].reaction_available
    assert not e.state.actors[FOE].reaction_available
    assert mark_count(e.state.actors[OWNER], OWNER) == 0
    assert sum(x.source_definition_id == QUENCH and x.event_type == "REACTION_RESOLVED" for x in e.events) == 1
    assert sum(x.source_definition_id == "test:r9:defense" and x.event_type == "REACTION_RESOLVED" for x in e.events) == 1
    defense = next(x for x in e.events if x.source_definition_id == "test:r9:defense" and x.event_type == "REACTION_RESOLVED")
    assert defense.payload["pending_damage_reduction"] == 2
    assert defense.payload["hit_after_recheck"] is True


@pytest.mark.parametrize("margin,use", [(1, True), (2, True), (1, False), (3, True)])
def test_quench_is_offered_once_after_typed_ac_defense_creates_close_miss(tmp_path, monkeypatch, margin, use):
    """The general post-defense checkpoint offers only a newly created qualifying AC miss."""
    die(monkeypatch)
    def configure(bundles):
        # Attack total is 18 - margin: initially a hit against AC 14, then a
        # genuine AC defense raises the threshold to 18.
        setup(8 - margin)(bundles)
        add_reaction(bundles, kind="hit_ac", ac=4)
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=configure)
    declare(combat, table, mid, "weapon")
    before = combat._load_session(mid).engine.state.actors[FOE].current_hp
    qi_before = combat._load_session(mid).engine.state.actors[FOE].resources["resource:core.qi"]
    prompts = press(combat, table, mid, "Sword", FOE,
                    picks={"reaction:typed.test:r9:defense": ["USE"],
                           "choice:needle.blacksmith_quench": ["quench"] if use else None})
    e = reload(tmp_path, mid)
    offered = [p for p in prompts if p.get("context", {}).get("reaction_source_id") == "choice:needle.blacksmith_quench"]
    expected = margin <= 2 and use
    assert bool(offered) == (margin <= 2)
    assert (e.state.actors[FOE].current_hp < before) == expected
    assert e.state.actors[OWNER].reaction_available == (not expected)
    assert not e.state.actors[FOE].reaction_available
    assert e.state.actors[FOE].resources["resource:core.qi"] == qi_before - 1
    assert mark_count(e.state.actors[OWNER], OWNER) == int(not expected)
    defense = next(x for x in e.events if x.source_definition_id == "test:r9:defense" and x.event_type == "REACTION_RESOLVED")
    assert defense.payload["ac_bonus"] == 4
    assert defense.payload["new_ac"] == 18
    assert sum(x.source_definition_id == QUENCH and x.event_type == "REACTION_RESOLVED" for x in e.events) == int(expected)
    assert sum(x.source_definition_id == "test:r9:defense" and x.event_type == "REACTION_RESOLVED" for x in e.events) == 1
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"
