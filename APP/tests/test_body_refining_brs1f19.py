"""BRS1F19 regressions: one test per BRS1F18R2 finding (and the owner addendum items that touch the rider lane).

Guard-zero attacks now resolve at their trigger (IRONGUARD1), superseding the old turn-start flag.
The remaining regressions cover Force-Tempered movement, spending one-use save Advantage,
and the printed choice's choice_options provider and choice_owner marker.
"""
from types import SimpleNamespace

import pytest

from combat.ext import br_variants as bv
from combat.ext import free_uses
from tests.test_body_refining_riders import ACTOR, make_actor, make_engine, sphere, variants


def test_guard_zero_without_an_attack_does_not_grant_a_strike_or_spend_its_round_limit():
    rows, _ = variants(sphere("tianxia.sphere.iron_fist"))
    actor = make_actor()
    engine = make_engine(rows, actor)
    engine.damage_context = lambda: None  # e.g. damage from a fall
    event = SimpleNamespace(event_type="REACTION_RESOLVED",
                            source_definition_id="tianxia.path.body_refining.feature.stamina_guard", actor_id=ACTOR,
                            payload={"pending_before": 5, "pending_after": 0, "spend": 1})
    bv.guard_zero_strike(engine, event)
    assert not engine.events and not actor.turn_flags


def test_force_tempered_push_lengthens_the_forced_movement_through_the_bonus_seam():
    """Finding 2: the chosen +5 feet arrives as a forced_movement_bonus, which the executor adds to the longest push."""
    from combat import ext

    rows, _ = variants(sphere("tianxia.sphere.force"))
    actor = make_actor()
    engine = make_engine(rows, actor, round_number=1)
    rider = next(r for r in bv._riders(engine, ACTOR, "choice") if r.get("push_option"))
    clause = rider.get("clause")
    actor.turn_flags[f"br_choice_{clause}"] = bv._turn_key(engine, actor)
    actor.turn_flags[f"br_pick_{clause}"] = "push"
    ctx = SimpleNamespace(engine=engine, actor=actor, typed={"source": "TAL_FORCE_BODY_CONDUCTED_IMPACT"})
    bonuses = [v for v in ext.run("forced_movement_bonus", ctx, actor, {}) if type(v) is int]
    assert 5 in bonuses, "the chosen push must add 5 feet to the longest forced movement"


def test_chosen_one_use_save_advantage_is_spent_by_the_first_advantage_save_only():
    """Finding 3: the second save in the window rolls normally, so the chosen Advantage is not reused."""
    actor = make_actor()
    removed = []
    actor.conditions[bv.SAVE_CONDITION] = SimpleNamespace(condition_id=bv.SAVE_CONDITION, instance_id=bv.SAVE_CONDITION,
                                                          data={}, source_definition_id="F", source_actor_id=ACTOR)

    def remove(target, instance_id, source, **kwargs):
        removed.append(instance_id)
        target.conditions.pop(instance_id, None)

    engine = SimpleNamespace(state=SimpleNamespace(actors={ACTOR: actor}), _remove_condition_instance=remove)
    bv.consume_one_use_advantage(engine, "SAVE_ROLLED", {"actor_id": ACTOR, "payload": {"mode": "NORMAL"}})
    assert removed == [], "a save that did not roll with Advantage must not spend the benefit"
    actor.conditions[bv.SAVE_CONDITION] = SimpleNamespace(condition_id=bv.SAVE_CONDITION, instance_id=bv.SAVE_CONDITION,
                                                          data={}, source_definition_id="F", source_actor_id=ACTOR)
    bv.consume_one_use_advantage(engine, "SAVE_ROLLED", {"actor_id": ACTOR, "payload": {"mode": "ADVANTAGE"}})
    assert removed == [bv.SAVE_CONDITION] and bv.SAVE_CONDITION not in actor.conditions
    bv.consume_one_use_advantage(engine, "SAVE_ROLLED", {"actor_id": ACTOR, "payload": {"mode": "ADVANTAGE"}})
    assert removed == [bv.SAVE_CONDITION], "a later Advantage save must not find a benefit to spend"


def test_printed_choice_is_offered_to_the_seat_with_its_plain_options():
    """Finding 4: choice_options returns the menu for choice:br_variant.* and the owner is marked as a choice owner."""
    rows, _ = variants(sphere("tianxia.sphere.force"))
    actor = make_actor()
    engine = make_engine(rows, actor, round_number=1)
    context = {"needle_options": ["push", "damage", "stand"], "minimum": 1, "maximum": 1, "preferred": ["push"]}
    spec = bv.choice_options(engine, None, "", ACTOR, "choice:br_variant.br_choice_5", context)
    assert spec and spec["option_ids"] == ["push", "damage", "stand"]
    assert bv.choice_options(engine, None, "", ACTOR, "choice:needle.other", context) is None


def test_choice_owner_marker_names_the_owned_choice_row(monkeypatch):
    """Finding 4 (table routing): every owned choice row is announced as a choice owner, using the variant id
    the authority row carries, and the routing row is bookkeeping only (BRS1F25 finding 1: no sheet leak)."""
    row = {"id": "tianxia.brvariant.force.force-tempered-body", "riders": [{"kind": "choice"}]}
    monkeypatch.setattr(bv.authority, "owned", lambda sheet: [row])
    info = {"owner_sheet": {}, "passives": []}
    bv.choice_owner_marker(info)
    assert info["passives"] == [{"feature_id": "tianxia.brvariant.force.force-tempered-body",
                                 "choice_owner": True, "ownership_only": True}]


def test_stale_body_refining_pin_does_not_break_the_cat3_insight_catalog(monkeypatch):
    """Non-blocking finding 1 + BRS1F25 finding 2: a hash mismatch skips the supplements in the listing
    instead of failing it for every character, while a Body Refining lookup still names the build error."""
    import factory_authoring.body_refining_variants as brv
    from app.core import FoundryError
    from canonical_catalog import service
    from tests.body_refining_support import ROOT

    def boom():
        raise ValueError("Body Refining version authority hash does not verify")

    monkeypatch.setattr(brv, "authored_insights", boom)
    catalog = service.CanonicalCatalogAuthorityService(ROOT)
    listing = catalog.list_insights()
    assert listing["count"] > 0
    assert not any(row["canonical_insight_id"] == "insight.ashen-body" for row in listing["records"])
    with pytest.raises(FoundryError) as caught:
        catalog.get_insight("insight.ashen-body")
    assert caught.value.code == "CANONICAL_BODY_REFINING_PIN_STALE"


def test_player_facing_grant_label_never_shows_the_engine_state_key():
    """Addendum item 2: a br_variant:<authority id> grant is named in plain words."""
    label = free_uses.grant_label({"state": "br_variant:tianxia.brvariant.force.force-tempered-body"})
    assert "br_variant" not in label and "tianxia" not in label and "." not in label
