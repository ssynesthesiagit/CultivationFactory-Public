"""Wave 2 paths worker (owner 2026-09-28, "automate every aspect before another playtest"): every Foundation
(foundation.*), Subpath (tianxia.subpath.*) and Tradition (tianxia.tradition.*) feature, across every
character who has one, except Ancient Desolate Sacred Body, Karma Knot Root, the Shinobi/Ninpo Adept
Subpaths and Empty Bowl Soul Anchor (already owned by other workers).

Generate Tyrant Form Pulse, Generate Moon-Sea Radiance and Generate Edict Seal, Generate Pack Echo, Generate
Severance Edge and Generate Mirror Trace are all "No Action / Triggered" Foundation features: before this
pass nothing in factory_compiler/typed_executor ever executed them (confirmed live: Lan Hongmu -- Heaven
Tyrant Body -- landed hits across four seeded fights and never gained a single Tyrant Form Pulse). Five of
the seven Foundations' Generate records were already recognized by the compiler's generic reaction-trigger
classifier (combat/reaction_triggers.py, matching printed trigger text to a runnable "kind" like own_hit or
own_save_failed) and just needed live confirmation; two needed their `activation.trigger` text simplified so
that classifier could read them at all:
  - Heaven Tyrant Body's Generate Tyrant Form Pulse has a three-way OR the classifier could not parse at all
    (it was in the compiler's own skipped-passive list). Reviewed to just its "you hit a hostile creature
    within reach" clause -- the character's core repeated action -- with the other two OR-branches (damage
    taken within 10 ft; a Strength/Constitution contest success) left as a GM-only rider.
  - Divine King Body's Generate Moon-Sea Radiance printed "fails a saving throw or ability check against
    your...", and the classifier's own_save_failed phrase needs "saving throw against your" adjacent; the
    inserted "or ability check" broke that match and let it fall through to the much broader
    creature_save_failed pattern (which fires off ANY creature's failed save anywhere, not only this
    character's own technique) -- a real scope-too-broad bug. Reviewed to the clean "fails a save against
    your technique" clause so it reads as own_save_failed instead.

Golden Mandate Vessel, Tyrant-Blood Frame and Sacred-Dao Embryo Frame (Frame passives) were fully unautomated
(the compiler's skipped-passive list): each prints a doubled/PB'd max-HP line already folded into the sheet's
own hit_points at creation (non_sphere_authority/foundation_mechanics.py, hp_maximum_modifiers) -- retyping
it here would double it -- plus a printed Advantage on saves this table can automate through the existing
generic "defense" block (kind save_advantage, already read for any owner by combat/pressure.py's
save_advantage(), not only Ancient Desolate). combat/rules/feature_blocks.d/paths.json adds that block; no
new Python was needed for the three Frame passives.

Built like tests/test_auto_shi.py (Gate4ControllerEngine fixture, tests/test_zones.SHEET's stats)."""

from pathlib import Path

from combat import pressure
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.paths"

HEAVEN_TYRANT = {"foundation_id": "heaven_tyrant_body_v0_2D", "stage": "Awakened",
                 "resource": {"name": "Tyrant Form Pulse", "resource_id": "foundation.resource.heaven_tyrant_body_v0_2D", "maximum": 1, "current": 0}}
DIVINE_KING = {"foundation_id": "divine_king_body_v0_2B", "stage": "Awakened",
               "resource": {"name": "Moon-Sea Radiance", "resource_id": "foundation.resource.divine_king_body_v0_2B", "maximum": 1, "current": 0}}
GOLDEN_MANDATE = {"foundation_id": "golden_mandate_seal_v0_2B", "stage": "Awakened",
                  "resource": {"name": "Edict Seal", "resource_id": "foundation.resource.golden_mandate_seal_v0_2B", "maximum": 1, "current": 0}}
SACRED_EMBRYO = {"foundation_id": "innate_sacred_body_dao_embryo_v0_2B", "stage": "Awakened",
                 "resource": {"name": "Origin Bell Tone", "resource_id": "foundation.resource.innate_sacred_body_dao_embryo_v0_2B", "maximum": 1, "current": 0}}
DAO = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao"}]}}


def _bundle(foundation, *, sphere="tianxia.sphere.iron_fist", talents=(), equipment=(DAO,)):
    sheet = {**SHEET, "equipment": list(equipment), "foundation": foundation,
             "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": list(talents)}}
    return compile_character(sheet, actor_id=ME)


def _engine(bundle):
    engine = Gate4ControllerEngine(ROOT, match_seed="PATHS", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _hit_with(engine, name_prefix, *, attempts=10):
    me = engine.state.actors[ME]
    for attempt in range(attempts):
        strike = next((c for c in engine.legal_candidates() if c.display_name.startswith(name_prefix)), None)
        assert strike is not None, f"{name_prefix!r} should be a legal candidate"
        before = len([e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"])
        engine.execute_intent(ActionIntent(intent_id=f"hit{attempt}", decision_id=strike.decision_id, candidate_id=strike.candidate_id,
                                           state_version=strike.state_version, actor_id=ME, target_ids=strike.target_ids))
        if len([e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]) > before:
            return True
        engine.state.current_actor_id = ME
        me.action_available = True
    return False


def test_generate_tyrant_form_pulse_fires_on_a_hit_and_was_skipped_before():
    bundle = _bundle(HEAVEN_TYRANT)
    assert "foundation.heaven_tyrant_body_v0_2D.generate_tyrant_form_pulse" not in bundle["diagnostics"]["skipped"].get("passive", [])
    engine = _engine(bundle)
    me = engine.state.actors[ME]
    resource = "resource:foundation.tyrant_form_pulse"
    assert me.resources.get(resource, 0) == 0
    assert _hit_with(engine, "Dao ")
    assert me.resources.get(resource, 0) == 1


def test_generate_moon_sea_radiance_fires_from_own_technique_not_any_creatures_save():
    """The scope-too-broad fix: it must key off THIS character's own technique (own_save_failed), not any
    creature's failed save anywhere (creature_save_failed) -- so another creature's own failed save must not
    generate it for a bystander who owns the Foundation."""
    from combat import typed_reactions

    bundle = _bundle(DIVINE_KING, sphere="tianxia.sphere.water")
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    resource = "resource:foundation.moon_sea_radiance"
    assert me.resources.get(resource, 0) == 0
    typed_reactions.on_creature_event(engine, foe, "creature_save_failed")  # someone else's failed save nearby
    assert me.resources.get(resource, 0) == 0
    typed_reactions.on_own_event(engine, me, foe, "own_save_failed")  # her own technique made a hostile creature fail
    assert me.resources.get(resource, 0) == 1


def test_frame_passives_grant_save_advantage_and_no_longer_skipped():
    bundle = _bundle(GOLDEN_MANDATE, sphere="tianxia.sphere.talismans")
    assert "Golden Mandate Vessel" not in bundle["diagnostics"]["skipped"].get("passive", [])
    engine = _engine(bundle)
    me = engine.state.actors[ME]
    assert pressure.save_advantage(engine, me, "CHA", {"frightened"})
    assert not pressure.save_advantage(engine, me, "CHA", {"poisoned"})

    bundle2 = _bundle(SACRED_EMBRYO, sphere="tianxia.sphere.iron_fist")
    assert "Sacred-Dao Embryo Frame" not in bundle2["diagnostics"]["skipped"].get("passive", [])
    engine2 = _engine(bundle2)
    me2 = engine2.state.actors[ME]
    assert pressure.save_advantage(engine2, me2, "STR", {"grappled"})
    assert not pressure.save_advantage(engine2, me2, "STR", {"poisoned"})
