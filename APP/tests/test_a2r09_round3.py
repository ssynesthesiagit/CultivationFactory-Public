"""Revision-3 review regressions: committed tables, no GUI or live models."""
import pytest

from combat.ext import tabik_ninpo as ninpo
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE
from tests.test_a2r09_review_fixes import add_fixture_action, NINPO


def held(actor, name):
    return [c for c in actor.conditions.values() if c.condition_id == "condition:typed." + name]


def vanishing_table(tmp_path):
    def setup(bundles):
        add_fixture_action(bundles[0], "Harmful probe", [{"type": "condition", "condition": "prone",
                           "applies_to": "target"}], target="ANY_CREATURE")
        add_fixture_action(bundles[0], "Lose Concentration", [{"type": "condition", "condition": "incapacitated",
                           "applies_to": "self", "expires_on": "END_OF_CURRENT_TURN"}])
    combat, table, mid = fixture(tmp_path, [], owner_path="Qi Cultivation", seed="A2R09F3-VANISH",
                               owner_features=[NINPO + "vanishing_technique"], bundle_transform=setup,
                               battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    settle(table, mid, candidate(combat, mid, "Vanishing Technique").candidate_id)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    state = held(actor, "vanishing_state")[0]
    assert state.source_definition_id == actor.concentration.source_definition_id
    return combat, table, mid


@pytest.mark.parametrize("restored", [False, True])
def test_vanishing_loss_of_concentration_table_reload(tmp_path, restored):
    combat, table, mid = vanishing_table(tmp_path)
    settle(table, mid, candidate(combat, mid, "Harmful probe", target=FOE).candidate_id)
    assert not held(reload(tmp_path, mid).state.actors[OWNER], "invisible")
    if restored:
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
        turn(table, mid, OWNER)
        actor = reload(tmp_path, mid).state.actors[OWNER]
        invisible = held(actor, "invisible")[0]
        assert invisible.source_definition_id == actor.concentration.source_definition_id
        assert invisible.data["concentration_started_sequence"] == actor.concentration.started_sequence
    settle(table, mid, candidate(combat, mid, "Lose Concentration").candidate_id)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert actor.concentration is None
    assert not held(actor, "vanishing_state") and not held(actor, "invisible")
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, OWNER)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert not held(actor, "vanishing_state") and not held(actor, "invisible")


def test_vanishing_natural_duration_table_reload(tmp_path):
    combat, table, mid = vanishing_table(tmp_path)
    settle(table, mid, candidate(combat, mid, "Harmful probe", target=FOE).candidate_id)
    for _ in range(9):
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
        turn(table, mid, OWNER)
    assert held(reload(tmp_path, mid).state.actors[OWNER], "invisible")
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, OWNER)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert actor.concentration is None
    assert not held(actor, "vanishing_state") and not held(actor, "invisible")


def test_vanishing_restoration_keeps_older_copy_ownership():
    from tests.test_auto_ninpo_residual import _ninja, _act, ME
    from combat import concentration
    engine = _ninja(with_array=False)
    _act(engine, "Vanishing Technique")
    actor = engine.state.actors[ME]
    source = actor.concentration.source_definition_id
    first = actor.concentration.started_sequence
    _act(engine, "Unarmed Strike", bonus=100)
    # A second copy beginning while the first is revealed must not acquire
    # the first copy's restored effect merely because its event is newer.
    engine._start_concentration(actor, source)
    ninpo.vanishing_restore(engine, actor)
    invisible = held(actor, "invisible")[0]
    assert invisible.data["concentration_started_sequence"] == first
    engine._end_concentration(actor, "VOLUNTARY")
    assert held(actor, "invisible")
    concentration.end_copy(engine, actor, first, "VOLUNTARY")
    assert not held(actor, "invisible") and not held(actor, "vanishing_state")


@pytest.mark.parametrize("decline", [False, True])
def test_isolated_clone_owner_asks_on_enemy_ai_turn_after_reload(tmp_path, decline):
    from tests.r1i_service_support import force_ai_candidate
    from combat.canonical import canonical_sha256
    def setup(bundles):
        add_fixture_action(bundles[2], "Enemy attack", [{"type": "attack", "attack_kind": "melee",
                           "no_damage": True, "on_hit": []}], target="HOSTILE_ENTITY")
        bundles[2]["action_catalog"][-1]["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        bundles[2].pop("bundle_sha256", None)
        bundles[2]["bundle_sha256"] = canonical_sha256(bundles[2])
    # Ordinary reactions are automatic: they must not enroll the defender on
    # behalf of its independently player-owned, no-action Array decision.
    combat, table, mid = fixture(tmp_path, [], cl=18, ask=False, owner_path="Qi Cultivation", seed="A2R09F3-ARRAY",
                               owner_features=[NINPO + "shadow_clone_array"], bundle_transform=setup,
                               positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 2, "y": 6}, FOE: {"x": 4, "y": 6}})
    settle(table, mid, candidate(combat, mid, "Shadow Clone Array").candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert not any(row.get("ask") for row in engine.typed_reaction_rows.get(OWNER, []))
    assert not any(row.get("choice_owner") and row.get("kind") != "shadow_clone_array"
                   for row in engine.typed_passive_rows.get(OWNER, []))
    assert held(actor, "shadow_clone_array")[0].data["clones"] == 2
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, FOE)
    cid = candidate(combat, mid, "Enemy attack", target=OWNER).candidate_id
    force_ai_candidate(combat, mid, FOE, cid)
    prompts = settle(table, mid, cid, auto=True,
                     picks={"choice:needle.clone_interposition": None if decline else "interpose"})
    choices = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.clone_interposition"]
    assert len(choices) == 1
    assert choices[0]["context"]["reactor_id"] == OWNER
    assert "Shadow Clone Array" in choices[0]["moment"]
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert held(actor, "shadow_clone_array")[0].data["clones"] == (2 if decline else 1)
    assert (actor.turn_flags.get(ninpo.INTERPOSE_KEY) is not None) == (not decline)


def falcon_engine(picks, *, foe_at=(4, 6), items=()):
    from tests.test_auto_a2r11_residual import _beasts, _record_aspects
    engine, actor, foe = _beasts(["beast_scripture_initiate", "beast_king_s_technique"], foe_at=foe_at, items=items,
                               picks={"beast_aspects": ["Falcon"], "beast_king": ["Falcon"],
                                      "beast_king_falcon": [picks]})
    _record_aspects(engine, ["Falcon", "Wolf", "Serpent"])
    return engine, actor, foe


def test_falcon_is_willing_despite_deep_root_and_runs_movement_callbacks(monkeypatch):
    from combat import typed_reactions
    from combat.ext.earth_responses import STANCE
    from tests.test_auto_a2r11_residual import use, unarmed
    engine, actor, foe = falcon_engine("cell:3,10")
    engine._apply_condition(actor, STANCE, "test:root", actor.entity_id, expires_on="UNTIL_REMOVED", data={"cl": 10})
    moved = []
    original = typed_reactions.on_creature_event
    def observe(e, subject, event, **kwargs):
        if subject.entity_id == actor.entity_id and event == "moved":
            moved.append(kwargs.get("moved_ft"))
        return original(e, subject, event, **kwargs)
    monkeypatch.setattr(typed_reactions, "on_creature_event", observe)
    use(engine, unarmed(engine), target=foe.entity_id)
    assert (actor.position.x, actor.position.y, actor.position.z) == (3, 10, 0)
    events = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == actor.entity_id]
    assert len(events) == 4 and sum(moved) == 20
    assert all(e.payload.get("without_provoking") and not e.payload.get("forced") for e in events)


def test_falcon_fear_filters_routes_and_commit_rechecks(monkeypatch):
    from combat.ext import needle
    from tests.test_auto_a2r11_residual import use
    from tests.test_lock_choices import install
    from combat.ext.rider_movement import vertical_options, step
    from combat.gate2_runtime_models import Position
    engine, actor, foe = falcon_engine("cell:3,10", foe_at=(6, 6), items=("tianxia.mortal.weapon.bi_shou",))
    thrown = next(a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                  and a.display_name == "Bi Shou (Dagger) thrown")
    thrown.parameters["typed"]["numbers"]["attack_bonus"] = 100
    install(monkeypatch, "d20_result", lambda *a: {"source_id": "test:falcon-hit", "operation": "replace", "natural_result": 10})
    destination = Position(x=4, y=5)
    engine._apply_condition(actor, "condition:typed.frightened", "test:fear", foe.entity_id,
                            expires_on="UNTIL_REMOVED", data={})
    assert "cell:4,5" in vertical_options(engine, actor, 20)
    assert "cell:4,5" not in vertical_options(engine, actor, 20, willing=True)
    offered = []
    original = needle.ask
    def observe(*args, **kwargs):
        if args[4] == "choice:needle.beast_king_falcon":
            offered.extend(args[5])
        return original(*args, **kwargs)
    monkeypatch.setattr(needle, "ask", observe)
    use(engine, "Bi Shou (Dagger) thrown", target=foe.entity_id)
    assert offered and "cell:4,5" not in offered
    # A route planned before fear is acquired must also be rejected at commit.
    actor.position = Position(x=3, y=6)
    before = actor.position
    step(engine, actor, [before, destination], "test:falcon", volume=True)
    assert actor.position == before
