"""PUPPETRY_BASE_PUPPET_INITIATION: the printed Puppetry kit a puppeteer really receives.

Puppet Initiation is the Sphere's acquisition row. Its fourth printed clause -- "learn Raise
the Vessel, Puppet Strike, and the basic Tension Responses" -- is the part that means something
at the table, so this file plays it through TabletopService/CombatService on a real match and
reads the buttons the owner is actually offered, before and after a cold commit+reload.

Clause three's "create or designate one basic puppet vessel" is covered too, as far as the table
can honestly carry it: the owner designates the vessel's form through a real setting button and
the choice survives the reload. The vessel itself is a prepared object supplied by the player,
which the peer's PUPPETRY_BASE_RAISE_THE_VESSEL row already states to the GM.

Clauses one and two -- the tool-proficiency choice and the already-proficient bonus-talent
branch -- are acquisition facts, not fight facts. This file deliberately does NOT pretend to
deliver them; see the lane report. Nothing here writes a proficiency or a talent receipt.
"""
import pytest

from tests.auto28_puppetry_support import resolve, turn
from tests.auto_worker1_support import LEFT, RIGHT, reload
from tests.test_auto105_puppetry_movement import OWNED, SPHERE, _bundle

BASIC_RESPONSES = ("Tug the Joint", "Cross the Limb", "Guarding Vessel", "Snap the Thread")


def match(tmp_path, *, spheres):
    """A real two-creature match; the owner compiles the two Puppetry base rows we hand it."""
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT

    bundles = [_bundle(tmp_path, LEFT, list(OWNED), spheres=list(spheres), mark=True),
               _bundle(tmp_path, RIGHT, [], spheres=[])]
    combat = CombatService(ROOT, tmp_path)
    positions = {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}}
    mid = combat._finish_factory_match(
        bundles, [LEFT, RIGHT], {LEFT: "team:a", RIGHT: "team:b"}, positions,
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [LEFT], [RIGHT], control_modes={LEFT: "MANUAL", RIGHT: "MANUAL"}, match_seed="mgr_t14_initiation",
        display_name="Puppetry Initiation regression", maximum_rounds=6)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def labels(engine, actor_id=LEFT):
    return {c.display_name for c in engine.legal_candidates() if c.actor_id == actor_id}


def raise_vessel(table, combat, mid):
    """Raise the printed vessel through the owner's real activation, declining the free move."""
    engine = combat._load_session(mid).engine
    state = table.state(mid)
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.startswith("Raise the Vessel") and c.destination
                     and (c.destination.x, c.destination.y) == (5, 6))
    result, _prompts = resolve(lambda answers: table.act(mid, candidate.candidate_id, state["menu"]["decision_id"],
                                                         state["menu"]["state_version"],
                                                         state["last_sequence"], answers),
                               {"choice:needle.vessel_raise_move": []})
    assert result["status"] == "COMMITTED"


def test_owner_learns_raise_the_vessel_and_can_designate_one(tmp_path):
    """Clause three and the first half of clause four: Raise the Vessel and its designation."""
    combat, table, mid = match(tmp_path, spheres=[SPHERE])
    turn(table, mid, LEFT)
    offered = labels(reload(combat, mid))

    assert any(n.startswith("Raise the Vessel") for n in offered), sorted(offered)
    for form in ("Bludgeoning", "Piercing", "Slashing"):
        assert f"Vessel form: {form}" in offered, sorted(offered)

    raise_vessel(table, combat, mid)
    # The vessel really was created: its printed Move/Dismiss buttons are now offered, and the
    # paid Raise button is withdrawn because its Action is spent.
    raised = labels(reload(combat, mid))
    assert "Dismiss Vessel" in raised, sorted(raised)
    assert any(n.startswith("Move Vessel") for n in raised), sorted(raised)
    assert not any(n.startswith("Raise the Vessel") for n in raised), sorted(raised)


def test_the_owner_is_compiled_the_printed_puppet_strike_and_basic_tension_responses(tmp_path):
    """"learn ... Puppet Strike, and the basic Tension Responses" for a puppeteer."""
    combat, table, mid = match(tmp_path, spheres=[SPHERE])
    turn(table, mid, LEFT)
    raise_vessel(table, combat, mid)

    compiled = {a.display_name for a in reload(combat, mid).action_catalog.values()
                if a.owner_id == LEFT}
    assert "Puppet Strike (from the vessel)" in compiled, sorted(compiled)
    for response in BASIC_RESPONSES:
        assert f"Tension Response: {response}" in compiled, (response, sorted(compiled))


def test_a_character_without_the_puppetry_sphere_is_offered_no_vessel_kit(tmp_path):
    """Wrong-owner control: the producer stays inert for anyone who does not learn Puppetry."""
    combat, table, mid = match(tmp_path, spheres=[])
    turn(table, mid, LEFT)
    offered = labels(reload(combat, mid))

    assert not any(n.startswith("Raise the Vessel") for n in offered), sorted(offered)
    assert not any("Tension Response" in n for n in offered), sorted(offered)
    assert not any(n.startswith("Vessel form") for n in offered), sorted(offered)
    assert not any("from the vessel" in n for n in offered), sorted(offered)

    compiled = {a.display_name for a in reload(combat, mid).action_catalog.values() if a.owner_id == LEFT}
    assert not any("Tension Response" in n for n in compiled), sorted(compiled)


def test_the_designated_vessel_form_survives_a_cold_reload(tmp_path):
    """Clause three's designation is the owner's own recorded choice, not a fixture fact."""
    combat, table, mid = match(tmp_path, spheres=[SPHERE])
    turn(table, mid, LEFT)

    engine = reload(combat, mid)
    form = next(c for c in engine.legal_candidates()
                if c.actor_id == LEFT and c.display_name == "Vessel form: Piercing")
    state = table.state(mid)
    result, _prompts = resolve(lambda answers: table.act(mid, form.candidate_id, state["menu"]["decision_id"],
                                                         state["menu"]["state_version"],
                                                         state["last_sequence"], answers))
    assert result["status"] == "COMMITTED"

    after = reload(combat, mid)
    config = next((c.data or {}) for c in after.state.actors[LEFT].conditions.values()
                  if c.condition_id == "condition:typed.vessel_setup")
    assert config["form"] == "piercing"
    assert "Piercing" in config["label"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))