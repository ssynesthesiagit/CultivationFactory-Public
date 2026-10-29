"""Real compiled Destruction releases remain strikes in the table AI's TurnPlan."""
import pytest

from combat.ai_tactics import TurnPlan, owned_profile
from combat.ext import destruction_shapes as shapes
from tests.auto_worker1_support import LEFT, fight

P = "tianxia.talent.destruction."


@pytest.mark.parametrize("talent,label,reach", [
    ("heaven_piercing_ray", "Heaven-Piercing Ray (Multi-Ray, 1 CP)", 30),
    ("calamity_form", "Calamity Form: Sphere", 30),
    ("calamity_form", "Calamity Form: Cone (1 CP)", 30),
    ("calamity_form", "Calamity Form: Line (1 CP)", 120),
    # This is the ordinary compiler + compile_action save-wrapper path.
    ("leaping_ruin", "Leaping Ruin", 30),
    ("leaping_ruin", "Leaping Ruin (Chain, 1 CP)", 30),
])
def test_compiled_release_drives_turn_range_and_offered_strikes(tmp_path, talent, label, reach):
    selected = []

    def isolated_loadout(bundle):
        if bundle["actor_id"] != LEFT:
            return
        rows = bundle["action_catalog"]
        chosen = next(row for row in rows if row["display_name"] == label)
        selected.append(chosen["source_definition_id"])
        # A synthetic loadout with this release and ordinary weaker short-range
        # weapon attacks. Keep priced pickup utilities to exercise the distinction.
        removed = {row["source_definition_id"] for row in rows
                   if row is not chosen and (row.get("parameters") or {}).get("typed", {}).get("sphere")
                   == "tianxia.sphere.destruction"}
        # Custom augment builders do not all include sphere metadata.
        removed.update(row["source_definition_id"] for row in rows
                       if row is not chosen and any(tag in row["source_definition_id"] for tag in
                          (".calamity_form.", ".heaven_piercing_ray.", ".leaping_ruin.")))
        bundle["actor_template"]["action_ids"] = [
            aid for aid in bundle["actor_template"]["action_ids"] if aid not in removed]
        bundle["action_catalog"] = [row for row in rows if row["source_definition_id"] not in removed]

    combat, table, mid = fight(tmp_path, [P + talent], cl=18, bundle_edit=isolated_loadout)
    context = combat.ai_decision_context(combat._load_session(mid), progress_guard=True)
    plan = TurnPlan(context)
    aid = selected[0]
    assert plan.actions[aid]["attack"] is True
    assert plan.actions[aid]["range"] == reach
    assert plan.best_attack_id == aid
    assert plan.attack_range == reach
    assert aid in plan.offered_strikes
    assert any(candidate.source_definition_id == aid for candidate, _ in plan.offers)
    assert plan.has_strike
    pickups = [key for key in plan.actions if key.endswith(".pickup")]
    assert pickups
    for pickup in pickups:
        assert plan.actions[pickup]["damage"] > 0
        assert plan.actions[pickup]["attack"] is False
        assert pickup not in plan.offered_strikes


@pytest.mark.parametrize("talent,suffix", [
    (shapes.CALAMITY_MANTLE, ".calamity_mantle.pulse"),
    (shapes.RUIN_BINDING_TETHER, ".ruin_binding_tether.pulse"),
    (shapes.RUIN_CROSSING, ".crossing.40.1"),
])
def test_other_custom_destruction_damage_producers_declare_strikes(talent, suffix):
    from tests.h1_support import ME, duel
    engine = duel([talent], cl=18)
    profile = owned_profile(engine, engine.state.actors[ME])["actions"]
    aid = next(key for key in profile if key.endswith(suffix))
    assert profile[aid]["damage"] > 0
    assert profile[aid]["attack"] is True
