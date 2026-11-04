"""Generic passive-trait contracts; the lead runs these after source integration.

These fixtures are arbitrary feature IDs, not substituted Insight effects.
Printed Insight ownership and full saved-table replay are covered separately
by test_auto_insights. Here the focus is schema rejection, pure queries, the
existing movement/posture/size callers, and exact selected-hold ownership.
"""

from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from combat import ext, posture, typed_reactions
from combat.ext import effective_size, passive_traits
from combat.gate2_runtime_models import ConditionInstance


ROOTED = "test:feature.rooted"
QUICK_STAND = "test:feature.quick_stand"
LARGE_GRAPPLE = "test:feature.large_grapple"
FIRM_GRIP = "test:feature.firm_grip"
LOOSE_GRIP = "test:feature.loose_grip"
OWNER, OTHER, ESCAPER, HELPER = "owner", "other", "escaper", "helper"


@pytest.fixture
def trait_hooks(monkeypatch):
    """Use the real dispatcher with just the generic providers under review."""
    monkeypatch.setattr(ext, "_LOADED", True)
    for point, callbacks in {
        "compile_passives": [passive_traits.compile_passives],
        "forced_distance": [passive_traits.forced_distance],
        "stand_cost": [passive_traits.stand_cost],
        # Keep the pure quote fixture isolated from previously loaded sphere hooks.
        "stand_cost_offer": [],
        "stand_extra_cost": [],
        "stand_allowed": [],
        "stand_extra_cost": [],
        "size_steps": [passive_traits.size_steps],
        "escape_mode": [passive_traits.escape_check_advantage, passive_traits.escape_check_disadvantage],
        "escape_save_mode": [passive_traits.escape_save_advantage, passive_traits.escape_save_disadvantage],
    }.items():
        monkeypatch.setitem(ext._HOOKS, point, callbacks)


def _row(feature_id, kind, **config):
    return {"feature_id": feature_id, "block": "passive_trait", "kind": kind, **config}


def _engine(rows=None):
    actors = {actor_id: SimpleNamespace(
        entity_id=actor_id, conditions={}, active=True, life_state=None,
        movement_remaining_ft=30, speed_ft=30, width_cells=1,
    ) for actor_id in (OWNER, OTHER, ESCAPER, HELPER)}
    return SimpleNamespace(
        state=SimpleNamespace(actors=actors), typed_passive_rows=deepcopy(rows or {}),
        typed_actor_ids=set(), events=[],
        _effective_speed=lambda actor: actor.speed_ft,
        _footprint=lambda actor: SimpleNamespace(width_cells=actor.width_cells),
    )


def _hold(engine, holder=OWNER, target=ESCAPER, *, key="hold", condition="condition:typed.grappled", data=None):
    held = ConditionInstance(
        instance_id=key, condition_id=condition, source_definition_id="test:action.grapple",
        source_actor_id=holder, target_id=target, applied_sequence=1,
        data={"escape_dc": 17, **(data or {})},
    )
    engine.state.actors[target].conditions[key] = held
    return held


def _snapshot(engine):
    return deepcopy((engine.typed_passive_rows, engine.events,
                     {key: vars(actor) for key, actor in engine.state.actors.items()}))


def test_owned_traits_coexist_with_defense_and_compile_without_mutating_inputs(monkeypatch, trait_hooks):
    features = {
        ROOTED: {"block": "defense", "defenses": [{"kind": "resistance", "damage_types": ["cold"]}],
                 "passive_traits": [{"kind": "forced_movement_reduction", "distance_ft": 10}]},
        LARGE_GRAPPLE: {"block": "passive_traits", "passive_traits": [
            {"kind": "effective_size", "steps": 1, "roles": ["act"], "purposes": ["grapple"]},
        ]},
        "test:feature.unowned_bad": {"block": "passive_traits", "passive_traits": {"not": "a list"}},
    }
    monkeypatch.setattr(typed_reactions, "rules", lambda: {"features": features})
    source_before = deepcopy(features)
    owned_ids = [ROOTED, LARGE_GRAPPLE, ROOTED]
    blocks = typed_reactions.compile_blocks(owned_ids, pb=3, key_mod=2, saves={}, resource_ids={}, mechanics={})
    original = deepcopy(blocks["passives"])
    info = {"owned_ids": owned_ids, "numbers": {"pb": 3, "cl": 8}}
    info_before = deepcopy(info)
    result = ext.transform("compile_passives", blocks["passives"], info)
    assert result is not blocks["passives"]
    assert blocks["passives"] == original
    assert info == info_before and features == source_before
    assert len(original) == 1 and original[0]["block"] == "defense"
    assert result[0] == original[0]
    assert result[1:] == [
        _row(ROOTED, "forced_movement_reduction", distance_ft=10),
        _row(LARGE_GRAPPLE, "effective_size", steps=1, roles=["act"], purposes=["grapple"]),
    ]
    # Copied nested config must not alias the cached feature-block source.
    result[2]["roles"].append("resist")
    assert features == source_before and blocks["passives"] == original


def test_absent_traits_preserve_old_passive_bytes_and_empty_ownership_reads_no_source(monkeypatch, trait_hooks):
    old = [{"feature_id": "old:defense", "block": "defense", "kind": "resistance", "damage_types": ["FIRE"]}]
    encoded = json.dumps(old, separators=(",", ":"))
    monkeypatch.setattr(typed_reactions, "rules", lambda: {"features": {"old:defense": {"block": "defense"}}})
    result = ext.transform("compile_passives", old, {"owned_ids": ["old:defense"], "numbers": {}})
    assert result is not old and json.dumps(result, separators=(",", ":")) == encoded

    def forbidden_read():
        raise AssertionError("An empty ownership set must not load feature data")

    monkeypatch.setattr(typed_reactions, "rules", forbidden_read)
    empty = []
    assert ext.transform("compile_passives", empty, {"owned_ids": [], "numbers": {}}) == []
    assert empty == []


@pytest.mark.parametrize("traits", [
    None, {}, [None],
    [{"kind": "unreviewed_trait", "distance_ft": 10}],
    [{"kind": "forced_movement_reduction"}],
    [{"kind": "forced_movement_reduction", "distance_ft": True}],
    [{"kind": "forced_movement_reduction", "distance_ft": -1}],
    [{"kind": "forced_movement_reduction", "distance_ft": "pb"}],
    [{"kind": "forced_movement_reduction", "distance_ft": 10, "requires": ["armored"]}],
    [{"kind": "standing_cost", "cost_ft": 2.5}],
    [{"kind": "effective_size", "steps": 0, "roles": ["act"], "purposes": ["grapple"]}],
    [{"kind": "effective_size", "steps": 1, "roles": [], "purposes": ["grapple"]}],
    [{"kind": "effective_size", "steps": 1, "roles": ["act", "act"], "purposes": ["grapple"]}],
    [{"kind": "effective_size", "steps": 1, "roles": ["all"], "purposes": ["grapple"]}],
    [{"kind": "effective_size", "steps": 1, "roles": ["act"], "purposes": ["unsupported"]}],
    [{"kind": "grapple_escape_mode", "mode": "NORMAL", "checks": True, "saves": False}],
    [{"kind": "grapple_escape_mode", "mode": "DISADVANTAGE", "checks": 1, "saves": True}],
    [{"kind": "grapple_escape_mode", "mode": "DISADVANTAGE", "checks": False, "saves": False}],
    [{"kind": "standing_cost", "cost_ft": 0}, {"kind": "standing_cost", "cost_ft": 5}],
])
def test_malformed_owned_trait_fails_closed_without_partial_input_changes(monkeypatch, trait_hooks, traits):
    spec = {"block": "passive_traits", "passive_traits": traits}
    before = deepcopy(spec)
    monkeypatch.setattr(typed_reactions, "rules", lambda: {"features": {ROOTED: spec}})
    old = [{"feature_id": "old:row", "block": "already_applied"}]
    old_before = deepcopy(old)
    with pytest.raises(ValueError, match="passive trait"):
        ext.transform("compile_passives", old, {"owned_ids": [ROOTED], "numbers": {}})
    assert old == old_before and spec == before


def test_forced_movement_checkpoint_cuts_once_for_owner_and_clamps_at_zero(monkeypatch, trait_hooks):
    engine = _engine({OWNER: [_row(ROOTED, "forced_movement_reduction", distance_ft=10)]})
    owner, other = engine.state.actors[OWNER], engine.state.actors[OTHER]
    # No reaction rows: exercise the existing common forced-movement checkpoint.
    monkeypatch.setattr(typed_reactions, "_expire_marks", lambda engine: None)
    monkeypatch.setattr(typed_reactions, "_ally_candidates", lambda engine, mover: [])
    before = _snapshot(engine)
    for source in (None, other, owner):
        assert typed_reactions.on_forced_movement(engine, owner, source, 25) == 15
        assert typed_reactions.on_forced_movement(engine, owner, source, 5) == 0
        assert typed_reactions.on_forced_movement(engine, other, source, 25) == 25
    assert all(callback.__module__ != passive_traits.__name__
               for callback in ext._HOOKS.get("forced_movement_reduction", []))
    assert _snapshot(engine) == before


@pytest.mark.parametrize("cost", [0, 5])
def test_standing_quote_uses_existing_posture_gates_without_spending(cost, trait_hooks):
    engine = _engine({OWNER: [_row(QUICK_STAND, "standing_cost", cost_ft=cost)]})
    owner, other = engine.state.actors[OWNER], engine.state.actors[OTHER]
    for actor in (owner, other):
        # Prone's rule ends on standing (63f7ba7d), so the fixture needs a real
        # typed condition rather than the retired expiry token.
        actor.conditions["prone"] = ConditionInstance(
            instance_id="prone", condition_id="condition:typed.prone",
            source_definition_id="test:prone", source_actor_id=OWNER,
            target_id=actor.entity_id, applied_sequence=1)
    owner.movement_remaining_ft = cost
    before = _snapshot(engine)
    assert posture.standing_cost(engine, owner) == cost
    assert posture.standing_cost(engine, other) == 15
    assert _snapshot(engine) == before
    owner.speed_ft = 0
    assert posture.standing_cost(engine, owner) is None
    owner.speed_ft = 30
    owner.active = False
    assert posture.standing_cost(engine, owner) is None
    owner.active = True
    if cost:
        owner.movement_remaining_ft = cost - 1
        assert posture.standing_cost(engine, owner) is None
    owner.movement_remaining_ft = 30
    assert posture.standing_cost(engine, owner, cost=7) == 7
    owner.conditions.clear()
    assert posture.standing_cost(engine, owner) is None


@pytest.mark.parametrize("role,purposes,expected", [
    ("act", {"grapple"}, 2), ("act", {"grapple", "forced"}, 2),
    ("resist", {"grapple"}, 1), ("act", {"forced"}, 1),
    ("act", {"shove"}, 1), ("act", {"comparison"}, 1), ("act", set(), 1),
])
def test_effective_size_requires_both_role_and_purpose_without_changing_footprint(role, purposes, expected, trait_hooks):
    engine = _engine({OWNER: [_row(LARGE_GRAPPLE, "effective_size", steps=1, roles=["act"], purposes=["grapple"])]})
    before = _snapshot(engine)
    assert effective_size.cells(engine, engine.state.actors[OWNER], role, purposes) == expected
    assert effective_size.cells(engine, engine.state.actors[OTHER], role, purposes) == 1
    assert _snapshot(engine) == before


def test_runtime_uses_retained_bundle_rows_without_reopening_feature_specs(monkeypatch, trait_hooks):
    features = {ROOTED: {"block": "passive_traits", "passive_traits": [
        {"kind": "forced_movement_reduction", "distance_ft": 10},
        {"kind": "standing_cost", "cost_ft": 0},
    ]}}
    monkeypatch.setattr(typed_reactions, "rules", lambda: {"features": features})
    compiled = ext.transform("compile_passives", [], {"owned_ids": [ROOTED], "numbers": {}})
    retained = json.loads(json.dumps({"typed_passives": compiled}))

    def forbidden_read():
        raise AssertionError("Runtime must use the retained passive bundle")

    monkeypatch.setattr(typed_reactions, "rules", forbidden_read)
    engine = _engine({OWNER: retained["typed_passives"]})
    owner = engine.state.actors[OWNER]
    assert passive_traits.forced_distance(engine, owner, None, 25) == 10
    assert passive_traits.stand_cost(engine, owner, 15) == 0
    assert passive_traits.forced_distance(engine, engine.state.actors[OTHER], None, 25) is None


@pytest.mark.parametrize("checks,saves", [(True, True), (True, False), (False, True)])
def test_escape_mode_belongs_to_actual_holder_and_only_selected_grapple(checks, saves, trait_hooks):
    row = _row(FIRM_GRIP, "grapple_escape_mode", mode="DISADVANTAGE", checks=checks, saves=saves)
    engine = _engine({OWNER: [row]})
    escaper = engine.state.actors[ESCAPER]
    mine = _hold(engine, key="mine")
    other = _hold(engine, holder=OTHER, key="other")
    before = _snapshot(engine)
    for point, enabled in (("escape_mode", checks), ("escape_save_mode", saves)):
        assert ext.run(point, engine, escaper, [mine]) == (["DISADVANTAGE"] if enabled else [])
        assert ext.run(point, engine, escaper, {other.instance_id: other}) == []
        assert ext.run(point, engine, engine.state.actors[HELPER], [mine]) == []
    assert _snapshot(engine) == before
    # Owning the trait as the escaping creature does not penalize its own escape.
    engine.typed_passive_rows = {ESCAPER: [row]}
    assert ext.run("escape_mode", engine, escaper, [mine, other]) == []
    assert ext.run("escape_save_mode", engine, escaper, [mine, other]) == []


def test_stale_foreign_target_forged_source_and_plain_restraint_do_not_inherit_grapple_trait(trait_hooks):
    engine = _engine({OWNER: [_row(FIRM_GRIP, "grapple_escape_mode", mode="DISADVANTAGE", checks=True, saves=True)]})
    escaper = engine.state.actors[ESCAPER]
    actual = _hold(engine)
    foreign = _hold(engine, target=HELPER, key="foreign")
    restrained = _hold(engine, key="restraint", condition="condition:typed.restrained")
    forged_source = actual.model_copy(update={"source_actor_id": OTHER})
    for grip in (foreign, restrained, forged_source):
        assert ext.run("escape_mode", engine, escaper, [grip]) == []
        assert ext.run("escape_save_mode", engine, escaper, [grip]) == []
    del escaper.conditions[actual.instance_id]
    assert ext.run("escape_mode", engine, escaper, [actual]) == []
    assert ext.run("escape_save_mode", engine, escaper, [actual]) == []


def test_custom_complete_grapple_rule_qualifies_but_speed_zero_alone_does_not(trait_hooks):
    from combat.typed_executor import rules

    engine = _engine({OWNER: [_row(FIRM_GRIP, "grapple_escape_mode", mode="DISADVANTAGE", checks=True, saves=True)]})
    escaper = engine.state.actors[ESCAPER]
    complete = _hold(engine, key="complete", condition="condition:typed.custom_grasp",
                     data={"rule": deepcopy(rules()["conditions"]["grappled"])})
    partial = _hold(engine, key="partial", condition="condition:typed.immobilized", data={"rule": {"speed_zero": True}})
    assert ext.run("escape_mode", engine, escaper, [complete]) == ["DISADVANTAGE"]
    assert ext.run("escape_save_mode", engine, escaper, [complete]) == ["DISADVANTAGE"]
    assert ext.run("escape_mode", engine, escaper, [partial]) == []


@pytest.mark.parametrize("point", ["escape_mode", "escape_save_mode"])
def test_advantage_and_disadvantage_remain_separate_replies_for_shared_cancellation(monkeypatch, trait_hooks, point):
    engine = _engine({OWNER: [
        _row(FIRM_GRIP, "grapple_escape_mode", mode="DISADVANTAGE", checks=True, saves=True),
        _row(LOOSE_GRIP, "grapple_escape_mode", mode="ADVANTAGE", checks=True, saves=True),
    ]})
    escaper = engine.state.actors[ESCAPER]
    hold = _hold(engine)
    assert set(ext.run(point, engine, escaper, [hold])) == {"ADVANTAGE", "DISADVANTAGE"}
    # An additional Advantage cannot erase the Disadvantage by prematurely
    # collapsing this provider's conflicting modes to None.
    monkeypatch.setitem(ext._HOOKS, point, [*ext._HOOKS[point], lambda *args: "ADVANTAGE"])
    assert set(ext.run(point, engine, escaper, [hold])) == {"ADVANTAGE", "DISADVANTAGE"}
