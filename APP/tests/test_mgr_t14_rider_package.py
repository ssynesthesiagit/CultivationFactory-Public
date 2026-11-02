"""MGR-T14 base ability BEASTMASTERY_BASE_RIDER_PACKAGE ("Rider Package" -> "Gain Skillful Riding"), whole row.

Owner rules (authority/typed_mechanics/rules_text.json, decoded SHA256
20a585e040d274de91b75afede3ae8654ba6b4b458fa0904fd944c7487647951):

    #### Rider Package
    You cultivate partnership through the saddle, harness, rein, knee, breath, and shared momentum.
    Gain Skillful Riding.
    ##### Skillful Riding
    While you ride a willing mount, when the mount makes a Dexterity saving throw to take half damage:
    it takes no damage on a success;
    it takes half damage on a failure.

Printed clauses under test, one case each:
  * ownership/acquisition -- the ability is a Beastmastery base ability (an automatic sphere component, not a learned
    talent), so owning it compiles the ``mounts``/``rider_package`` passive row and the Large steed the rider starts
    in the saddle of (combat/rules/feature_blocks.d/mounts.json, combat/summons.py).
  * trigger/recipient -- the *mount*, not the rider: a riderless or unbonded mount keeps the ordinary half, and the
    rider's own half-damage save is never touched.
  * numerical branch -- no damage on a passed save, half on a failed one.
  * limitation -- only a Dexterity save (a Strength, or a Strength-or-Dexterity the mount fails with Strength, is
    left alone) and only one that would otherwise halve (an all-or-nothing Dexterity save keeps its full damage).
  * lapse -- while you ride: the rider thrown off the mount loses the benefit on the same save path.
  * choice -- none is printed, so none is asked: the reduction settles during an AI turn with no question put to
    the player.
  * persistence -- the bond is stored state, so it must survive a cold table commit + reload.

Producers under test (existing, reused, not duplicated): combat/ext/mounts.py ``compile_mount_block`` /
``mount_actions`` / ``rider_of`` and the ``evasion`` subscriber ``skillful_riding``; the core's documented
``evasion`` dispatch in combat/typed_executor.py.  Every case here compiles a real Rider Package character and
runs the real engine (or a real table/session transaction), so a direct plug-in call alone proves nothing.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from combat import typed_executor
from combat.ext import mounts
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("mgr_t14_bm", ROOT / "tests" / "test_review_sw-beastmastery.py")
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

ME, FOE, ALLY, MOUNT = bm.ME, bm.AN, bm.ALLY, "actor:factory.probe.summon.mount.warhorse.1"
PACKAGE = "BEASTMASTERY_BASE_RIDER_PACKAGE"


# ---------------------------------------------------------------------------- real source: a sheet with or without the base ability
def rider_bundle(components=(PACKAGE,), talents=(), actor=bm.ME, plan=None):
    """Compile one real Factory character from the Beastmastery sphere.

    ``components`` is the sheet's ``automatic_sphere_component_record_ids``: the base abilities the sphere grants
    every member.  That list is the only thing separating an owner of this row from a character without it.
    """
    stats = {**bm.SHEET["ability_scores_and_statistics"], "technique_save_dc": bm.FAILS}
    sheet = {**bm.SHEET, "equipment": [], "ability_scores_and_statistics": stats,
             "spheres_and_talents": {"sphere_record_ids": [bm.BEASTMASTERY], "learned_talent_record_ids": list(talents),
                                     "automatic_sphere_component_record_ids": list(components)}}
    return compile_character(sheet, actor_id=actor, summon_plan=plan)


def fight(bundle, **kwargs):
    return bm.engine(bundle, foe_at=(4, 6), seed="MGR-T14-RIDER", **kwargs)


def mount_of(e):
    return e.state.actors[MOUNT]


def owner_rows(e, who=ME):
    """The compiled passive rows of the ``mounts`` block this character owns, by kind."""
    return {str(row.get("kind")) for row in (getattr(e, "typed_passive_rows", {}) or {}).get(who, [])
            if row.get("block") == mounts.BLOCK}


def rider_lines(e, since=0):
    return [ev.payload.get("rider") or ev.payload.get("text", "") for ev in e.events[since:]
            if ev.event_type in {"GM_RIDER", "PASSIVE_TRIGGERED"}]


def take(e, name, target=None):
    picks = [c for c in e.legal_candidates()
             if c.display_name == name and (target is None or c.target_ids == (target,))]
    assert picks, f"{name} is not offered: " + ", ".join(sorted({c.display_name for c in e.legal_candidates()}))
    c = picks[0]
    e.execute_intent(ActionIntent(intent_id=name, decision_id=c.decision_id, candidate_id=c.candidate_id,
                                  state_version=c.state_version, actor_id=e.state.current_actor_id,
                                  target_ids=c.target_ids, destination=c.destination))
    return c


# ---------------------------------------------------------------------------- the delivered packet: a real Dexterity save for half damage
def half_damage_save(e, subject, ability="DEX", dc=bm.FAILS, halves=True, flat=12):
    """The mount makes a real saving throw; the engine's own save path decides damage.

    ``dc=bm.FAILS``/``bm.PASSES`` are the harness's guaranteed-outcome DCs (the foe's saves total 0 to 24), so the
    branch under test is reached without faking the die or the outcome.
    """
    foe = e.state.actors[FOE]
    action = ActionDefinition(source_definition_id="action:test.half_damage_save", display_name="Half-damage save",
                              owner_id=FOE, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                              target_kind="HOSTILE_ENTITY", range_ft=60)
    intent = ActionIntent(intent_id="t", decision_id="d", candidate_id="c", state_version=0, actor_id=FOE,
                          target_ids=(subject.entity_id,), destination=None)
    row = {"type": "save", "ability": ability, "dc": dc,
           "on_fail": [{"type": "damage", "flat": flat, "damage_types": ["fire"]}],
           "on_success": [{"type": "half_damage"}] if halves else []}
    ctx = typed_executor.Context(e, foe, action, intent, {"effects": [row], "numbers": {"save_dc": dc}},
                                 [subject], subject)
    before = subject.current_hp
    typed_executor.run_effects(ctx, [row])
    return before - subject.current_hp


# ---------------------------------------------------------------------------- ownership / acquisition / build grants
def test_the_base_ability_is_a_sphere_component_that_grants_the_steed_the_rider_starts_mounted():
    """Ownership: this is a base ability, so the sphere grants it -- no talent learned, nothing to pick."""
    e = fight(rider_bundle())
    rider, mount = e.state.actors[ME], mount_of(e)
    assert "rider_package" in owner_rows(e), owner_rows(e)
    assert mount.active and mounts.mount_of(e, rider) is mount and mounts.rider_of(e, mount) is rider
    # "Gain Skillful Riding" is a passive: nothing to choose, nothing to spend, no action in the menu.
    assert not [c for c in e.legal_candidates() if "Skillful" in c.display_name]
    e._assert_invariants()


def test_a_character_the_sphere_did_not_grant_this_row_gets_no_steed_and_no_riding():
    """Wrong owner: the same sheet without the automatic sphere component owns neither half of the row."""
    e = fight(rider_bundle(components=()))
    assert "rider_package" not in owner_rows(e)
    assert MOUNT not in e.state.actors
    assert mounts.mount_of(e, e.state.actors[ME]) is None


# ---------------------------------------------------------------------------- the numerical branch
def test_a_passed_half_damage_save_costs_the_mount_nothing_and_a_failed_one_half():
    """The printed branch: "it takes no damage on a success; it takes half damage on a failure"."""
    passed = fight(rider_bundle())
    assert half_damage_save(passed, mount_of(passed), dc=bm.PASSES) == 0
    assert any("Skillful Riding" in line and "no damage" in line for line in rider_lines(passed))

    failed = fight(rider_bundle())
    assert half_damage_save(failed, mount_of(failed), dc=bm.FAILS) == 6
    assert any("Skillful Riding" in line and "half damage" in line for line in rider_lines(failed))


# ---------------------------------------------------------------------------- limitations and boundaries
def test_only_a_dexterity_save_that_would_halve_is_changed():
    """"a Dexterity saving throw to take half damage": not a Strength save, and not an all-or-nothing save."""
    strength = fight(rider_bundle())
    assert half_damage_save(strength, mount_of(strength), ability="STR", dc=bm.FAILS) == 12

    all_or_nothing = fight(rider_bundle())
    assert half_damage_save(all_or_nothing, mount_of(all_or_nothing), dc=bm.FAILS, halves=False) == 12

    # A Strength-or-Dexterity save the mount answers with its Strength is a Strength saving throw, and the
    # engine's own STR_OR_DEX normalisation picks Strength for this mount (STR +4 over DEX +1).
    either = fight(rider_bundle())
    mount = mount_of(either)
    assert max("STR", "DEX", key=lambda option: mount.saving_throws.get(option, 0)) == "STR"
    assert half_damage_save(either, mount, ability="STR_OR_DEX", dc=bm.FAILS) == 12


def test_the_rider_is_not_the_recipient():
    """"when the mount makes a Dexterity saving throw": the rider's own half-damage save is untouched."""
    e = fight(rider_bundle())
    rider = e.state.actors[ME]
    assert half_damage_save(e, rider, dc=bm.PASSES) == 6
    assert not [line for line in rider_lines(e) if "Skillful Riding" in line]


def test_the_benefit_ends_when_the_rider_is_no_longer_riding():
    """"While you ride a willing mount": a thrown-off rider's mount keeps the ordinary half."""
    e = fight(rider_bundle())
    take(e, "Dismount")
    assert mounts.rider_of(e, mount_of(e)) is None
    assert half_damage_save(e, mount_of(e), dc=bm.PASSES) == 6
    assert not [line for line in rider_lines(e) if "Skillful Riding" in line]


def test_the_benefit_ends_when_the_mount_is_forced_off_under_the_rider():
    """The rider that fails the real DC 10 stay-in-the-saddle save is no longer riding, on the same save path."""
    e = fight(rider_bundle())
    rider, mount = e.state.actors[ME], mount_of(e)
    real = e._roll_save

    def fall(target, ability, dc, source_id, *args, **kwargs):
        if source_id == mounts.SRC:  # 5.5e "must succeed on a DC 10 Dexterity saving throw or fall off"
            from types import SimpleNamespace

            return SimpleNamespace(total=1, natural_result=1)
        return real(target, ability, dc, source_id, *args, **kwargs)

    e._roll_save = fall
    push_mount_off(e)
    assert mounts.rider_of(e, mount) is None and rider.turn_flags.get("falling") is not True
    assert half_damage_save(e, mount, dc=bm.PASSES) == 6


def push_mount_off(e, distance=5):
    """A hostile forces the mount back against its will (the real mounted-combat forced-movement packet)."""
    foe = e.state.actors[FOE]
    mount = mount_of(e)
    action = ActionDefinition(source_definition_id="action:test.shove", display_name="Test push", owner_id=FOE,
                              economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5)
    intent = ActionIntent(intent_id="t", decision_id="d", candidate_id="c", state_version=0, actor_id=FOE,
                          target_ids=(mount.entity_id,), destination=None)
    ctx = typed_executor.Context(e, foe, action, intent, {"numbers": {"save_dc": 10}}, [mount], mount)
    typed_executor.run_effects(ctx, [{"type": "forced_movement", "distance_ft": distance, "direction": "away",
                                      "applies_to": "target"}])


# ---------------------------------------------------------------------------- choices: none printed, none asked
def test_nobody_is_asked_while_an_ai_creature_makes_the_mount_save():
    """The row prints no choice, so its delivery must not pause the fight -- least of all on an AI turn."""
    e = fight(rider_bundle())
    assert e.state.current_actor_id == ME
    bm.next_turn(e)  # the foe's turn: the mount's save lands inside somebody else's turn
    assert e.state.current_actor_id != ME
    before = len(getattr(e, "_gate4_reaction_cache", {}) or {})
    assert half_damage_save(e, mount_of(e), dc=bm.PASSES) == 0
    assert len(getattr(e, "_gate4_reaction_cache", {}) or {}) == before
    assert e.state.current_actor_id != ME  # the fight was never handed back to a player to answer anything


# ---------------------------------------------------------------------------- persistence
def test_the_bond_and_skillful_riding_survive_a_cold_table_commit_and_reload(tmp_path):
    """The row stores no resource of its own; the stored state it reads is the bond, and it must survive a reload."""
    from combat.gate2_runtime_models import ActionIntent as AI
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(
        match_seed="MGR-T14-RIDER-COLD", typed_bundles=(rider_bundle(),),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    engine = session.engine
    # Commit a real table action before the reload.
    end = next(c for c in engine.legal_candidates() if c.display_name == "End turn")
    session.submit_intent(AI(intent_id=f"end-{end.state_version}", decision_id=end.decision_id, candidate_id=end.candidate_id,
                              state_version=end.state_version, actor_id=end.actor_id, target_ids=end.target_ids),
                          primary_decision_record=None, reaction_provider=engine._gate4_reaction_provider)

    loaded = persistence.load_match(session.match_id).engine
    rider, mount = loaded.state.actors[ME], loaded.state.actors[MOUNT]
    assert mounts.mount_of(loaded, rider) is mount and mounts.rider_of(loaded, mount) is rider
    assert "rider_package" in owner_rows(loaded)
    assert half_damage_save(loaded, mount, dc=bm.PASSES) == 0
    assert half_damage_save(loaded, mount, dc=bm.FAILS) == 6
    assert any("Skillful Riding" in line for line in rider_lines(loaded))


@pytest.mark.parametrize("owns_riding", [True, False])
@pytest.mark.parametrize("dc,passed", [(-5, True), (100, False)])
def test_learned_hostile_fireball_commits_against_a_real_owned_mount_and_cold_replays(
        tmp_path, monkeypatch, owns_riding, dc, passed):
    """Native acceptance: Tame + Mount Training supplies the non-owner's own willing steed.

    No copied bond, borrowed ownership, constructed Context, or injected save effect.
    The hostile learns Fireball Art; its printed Dexterity/half packet is the trigger.
    Only dice are controlled, equally for preview, commit and replay.
    """
    from combat.gate4_engine import Gate4ControllerEngine
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import sheet, script
    from tests.hunt12_support import candidate, send
    from tests.test_lock2_persistence import act

    mids = [PACKAGE] if owns_riding else ["TAL_BEASTMASTERY_STEADY_HANDLER",
                                             "tianxia.talent.beastmastery.mount_training"]
    doc = sheet(mids, cl=10)
    if not owns_riding:
        components = doc["spheres_and_talents"]["automatic_sphere_component_record_ids"]
        doc["spheres_and_talents"]["automatic_sphere_component_record_ids"] = [
            key for key in components if key != PACKAGE]
    rider = compile_character(doc, actor_id=ME,
                              summon_plan={"beasts": [] if owns_riding else ["warhorse"]})
    hostile = compile_character(sheet(["FIRE_TAL_FIREBALL_ART"], cl=10, dc=dc), actor_id=FOE)
    real_save = Gate4ControllerEngine._roll_save

    def roll_save(engine, *args, **kwargs):
        script(engine, [10] + [2] * 100)
        return real_save(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_roll_save", roll_save)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        [rider, hostile], [ME, FOE], {ME: "team:factory", FOE: "team:opponents"},
        # Keep the caster's sightline clear of the arena's central pillar at
        # (9, 6)/(10, 6); this fixture tests riding, not casting through cover.
        {ME: {"x": 3, "y": 6}, FOE: {"x": 3, "y": 1}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed="MGR-T15-RIDER",
        display_name="Riding acceptance", maximum_rounds=20)["match_id"]

    def cold():
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
        return loaded.engine

    while combat._load_session(mid).engine.state.current_actor_id != ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    if not owns_riding:
        mount_choice = candidate(combat, mid, lambda c: c.display_name == "Mount")
        assert send(combat, table, mid, mount_choice)["status"] == "COMMITTED"
    engine = cold()
    mount = mounts.mount_of(engine, engine.state.actors[ME])
    assert mount is not None and mounts.rider_of(engine, mount).entity_id == ME
    assert mount.summon["owner"] == ME and mount.summon["trained"]
    assert ("rider_package" in owner_rows(engine)) is owns_riding
    mount_id, hp = mount.entity_id, mount.current_hp
    while combat._load_session(mid).engine.state.current_actor_id != FOE:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    # Augmented Fireballs share the display-name prefix. Select the printed
    # base cast explicitly, rather than whichever variant sorts first.
    chosen = candidate(combat, mid, lambda c: c.source_definition_id.endswith("FIRE_TAL_FIREBALL_ART")
                       and c.destination is not None
                       and (c.destination.x, c.destination.y) == (mount.position.x, mount.position.y))
    before = len(combat._load_session(mid).engine.events)
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    engine = cold()
    events = engine.events[before:]
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == mount_id]
    assert len(saves) == 1 and "DEX" in saves[0].payload["reason"].upper()
    assert saves[0].payload["success"] is passed
    damage = [e for e in events if e.event_type == "DAMAGE_ROLLED"]
    assert len(damage) == 1
    assert damage[0].payload["expression"] == "6d6+0"
    assert damage[0].payload["dice"] == [2] * 6
    assert damage[0].payload["total"] == 12
    # Six d6, each 2: ordinary 12/6; Skillful Riding changes it to 6/0.
    expected = (0 if passed else 6) if owns_riding else (6 if passed else 12)
    assert hp - engine.state.actors[mount_id].current_hp == expected
    assert any("Skillful Riding" in line for line in rider_lines(engine, before)) is owns_riding
