"""Regressions for the Black-Thorn F3 review: pure defense quotes and farming-proof Spine gain.

Finding 1: preview_damage_without must never spend a Reaction, a condition or a packet, even when an
effectful incoming_damage provider is registered (Phoenix furnace_packet quotes before immunity).
Finding 2: a flagged non-hostile packet (feature_cost/training/...) from an opposing team grants no Spine.
"""
from combat import ext
from combat.ext.black_thorn_demon_body import SPINE
from combat.ext.organ_furnaces import REDUCTION
from combat.typed_reactions import preview_damage_without
from tests.worker2_support import reload
from tests.test_black_thorn_native import setup, FEATURES, OWNER, FOE
from tests.test_ns1r_non_sphere_authority import authority  # noqa: F401  (pytest fixture)


def test_defense_quote_skips_effectful_incoming_damage_providers(tmp_path, authority, monkeypatch):
    combat, table, mid = setup(tmp_path, authority, FEATURES[:1])
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    baseline = preview_damage_without(engine, owner, 7, "PIERCING", "action:test.quote", None)
    seen = []

    def spend_reaction(engine_, target, amount, damage_type, source_id, source_actor_id):
        seen.append("effectful")
        target.reaction_available = False  # what guardian_knot does to its ally, before it commits damage
        return 0

    def read_only(engine_, target, amount, damage_type, source_id, source_actor_id):
        seen.append("quote-safe")
        return 0

    monkeypatch.setitem(ext._HOOKS, "incoming_damage", [*ext._HOOKS.get("incoming_damage", ()), spend_reaction, read_only])
    monkeypatch.setattr(ext, "_QUOTE_SAFE", {*ext._QUOTE_SAFE, ("incoming_damage", read_only)})
    before = owner.reaction_available

    quoted = preview_damage_without(engine, owner, 7, "PIERCING", "action:test.quote", None)

    assert quoted == baseline
    assert "effectful" not in seen and "quote-safe" in seen
    assert owner.reaction_available == before


def test_defense_quote_does_not_consume_a_pending_reduction(tmp_path, authority):
    combat, table, mid = setup(tmp_path, authority, FEATURES[:1])
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    source = "action:test.refined.source"
    engine._apply_condition(owner, REDUCTION, source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "test reduction", "amount": 3, "from": source})

    first = preview_damage_without(engine, owner, 10, "PIERCING", source, None)
    second = preview_damage_without(engine, owner, 10, "PIERCING", source, None)

    assert first == second
    assert any(c.condition_id == REDUCTION for c in owner.conditions.values())


def test_flagged_opposing_team_packet_grants_no_demon_spine(tmp_path, authority):
    combat, table, mid = setup(tmp_path, authority, FEATURES[:1])
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    foe = engine.state.actors[FOE]
    assert foe.team_id != owner.team_id
    assert owner.resources.get(SPINE, 0) == 0
    source = "action:test.spine.provenance"

    for flag in ("feature_cost", "training", "resource_farming", "voluntary", "self_inflicted"):
        engine._commit_damage(owner, 3, "PIERCING", source, foe.entity_id, None, reaction_depth=0, source_flags=(flag,))
    assert owner.resources.get(SPINE, 0) == 0

    # Positive control: the same opposing-team hit without a non-hostile flag does grant one Spine.
    engine._commit_damage(owner, 3, "PIERCING", source, foe.entity_id, None, reaction_depth=0)
    assert owner.resources.get(SPINE, 0) == 1


def test_packet_checkpoint_calls_each_before_damage_defenses_provider_once(tmp_path, authority, monkeypatch):
    from combat.typed_reactions import defend
    combat, table, mid = setup(tmp_path, authority, FEATURES[:1])
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    calls = []

    def responder(engine_, target, amount, kind, source_id, source_actor_id):
        calls.append("responder")
        return [{"kind": "resistance"}]  # a defense row, as adaptation_response answers with

    def observer(engine_, target, amount, kind, source_id, source_actor_id):
        calls.append("observer")
        return None  # a checkpoint, as furnace_packet answers with

    monkeypatch.setitem(ext._HOOKS, "before_damage_defenses", [responder, observer])
    taken = defend(engine, owner, 10, "PIERCING", "action:test.packet", None)

    assert calls == ["responder", "observer"]
    assert taken == 5  # the returned Resistance row halves the packet
