"""Mounted combat (combat/ext/mounts.py; owner 2026-09-29: "a mount is a larger token; its rider's token shares the space and sits on
top").  Each case compiles a real Rider Package character (Beastmastery, the base ability carried by the sheet's automatic components),
builds the fight with the engine and plays it: the steed is a 2x2 Warhorse the rider starts on, the mount follows the rider's move, mounting
and dismounting cost half the rider's Speed, a mount moved against its will or knocked Prone makes the rider save DC 10 Dexterity or fall
off Prone, Skillful Riding takes the mount's half-damage saves to none, the mount Dashes, Disengages, Dodges, Shoves and Overruns, and
Trampling Line, Shared Saddle Rhythm and Mounted Offense each do what their text says.  Every rule's source is in the plug-in's docstring.
"""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind
from combat.ext import mounts

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bm_helpers", ROOT / "tests" / "test_review_sw-beastmastery.py")
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

ME, FOE, MOUNT = bm.ME, bm.AN, "actor:factory.probe.summon.mount.warhorse.1"
TALENTS = ["TAL_BEASTMASTERY_MOUNTED_MANEUVERS", "TAL_BEASTMASTERY_SKIRMISH_RIDER", "TAL_BEASTMASTERY_RUN_DOWN", "TAL_BEASTMASTERY_TRAMPLING_LINE",
           "TAL_BEASTMASTERY_SHARED_SADDLE_RHYTHM", "tianxia.talent.beastmastery.mounted_offense", "tianxia.talent.beastmastery.acrobatic_mount"]


def rider_bundle(talents=(), dc=bm.FAILS, plan=None):
    stats = {**bm.SHEET["ability_scores_and_statistics"], "technique_save_dc": dc}
    sheet = {**bm.SHEET, "equipment": [], "ability_scores_and_statistics": stats,
             "spheres_and_talents": {"sphere_record_ids": [bm.BEASTMASTERY], "learned_talent_record_ids": list(talents),
                                     "automatic_sphere_component_record_ids": ["BEASTMASTERY_BASE_RIDER_PACKAGE"]}}
    return compile_character(sheet, actor_id=ME, summon_plan=plan)


@pytest.fixture(scope="module")
def plain_bundle():
    return rider_bundle()


@pytest.fixture(scope="module")
def full_bundle():
    return rider_bundle(TALENTS)


def fight(b, foe_at=(4, 6), seed="MOUNTS"):
    return bm.engine(b, foe_at=foe_at, seed=seed)


def actors(e):
    return e.state.actors[ME], e.state.actors[MOUNT], e.state.actors[FOE]


def cells(e, actor):
    return set(e._actor_cells(actor))


def names(e):
    return {c.display_name for c in e.legal_candidates()}


def take(e, name, target=None):
    picks = [c for c in e.legal_candidates() if c.display_name == name and (target is None or c.target_ids == (target,))]
    assert picks, f"{name} is not offered: " + ", ".join(sorted(n for n in names(e) if not n.startswith("Move to")))
    c = picks[0]
    e.execute_intent(ActionIntent(intent_id=name, decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                  actor_id=e.state.current_actor_id, target_ids=c.target_ids, destination=c.destination))
    return c


def walk(e, dest):
    c = next(c for c in e.legal_candidates() if c.display_name == f"Move to {dest[0]},{dest[1]}")
    e.execute_intent(ActionIntent(intent_id="walk", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                  actor_id=ME, target_ids=c.target_ids, destination=c.destination))


def riders(e, since=0):
    # Resolved mount effects use plain notices; skipped mechanics retain GM riders.
    return [ev.payload.get("rider") or ev.payload.get("text", "") for ev in e.events[since:]
            if ev.event_type in {"GM_RIDER", "PASSIVE_TRIGGERED"}]


def saves(e, total):
    """The fall save (and only that) totals ``total``."""
    real = e._roll_save

    def roll(target, ability, dc, source_id, *args, **kwargs):
        if source_id == mounts.SRC:
            return SimpleNamespace(total=total, natural_result=total)
        return real(target, ability, dc, source_id, *args, **kwargs)

    e._roll_save = roll


def push_mount(e, distance=5):
    me, mount, foe = actors(e)
    action = ActionDefinition(source_definition_id="action:test.shove", display_name="Test push", owner_id=FOE, economy=EconomyKind.NONE,
                              resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5)
    intent = ActionIntent(intent_id="t", decision_id="d", candidate_id="c", state_version=0, actor_id=FOE, target_ids=(MOUNT,), destination=None)
    ctx = typed_executor.Context(e, foe, action, intent, {"numbers": {"save_dc": 10}}, [mount], mount)
    typed_executor.run_effects(ctx, [{"type": "forced_movement", "distance_ft": distance, "direction": "away", "applies_to": "target"}])


def failed_lines(e):
    return [line for line in riders(e) if " failed: " in line]


# ---------------------------------------------------------------- the pair
def test_the_rider_starts_on_a_2x2_mount_sharing_its_space(plain_bundle):
    e = fight(plain_bundle)
    me, mount, _ = actors(e)
    assert len(cells(e, mount)) == 4 and cells(e, me) < cells(e, mount)
    assert mounts.mount_of(e, me) is mount and mounts.rider_of(e, mount) is me and mounts.controlled(mount)
    e._assert_invariants()
    assert not failed_lines(e)


def test_a_riderless_character_has_no_mount():
    b = bm.bundle(bm.BEASTMASTERY, [])
    e = bm.engine(b)
    assert not [a for a in e.state.actors.values() if (a.summon or {}).get("mountable")]


def test_the_mount_follows_the_riders_move_at_the_mounts_speed(plain_bundle):
    e = fight(plain_bundle)
    me, mount, _ = actors(e)
    assert me.movement_remaining_ft == 60  # the Warhorse's Speed, not the rider's 30
    walk(e, (3, 9))
    assert (me.position.x, me.position.y) == (3, 9) and cells(e, me) < cells(e, mount)
    assert me.movement_remaining_ft == 45
    e._assert_invariants()
    assert not failed_lines(e)


def test_a_route_the_mount_cannot_take_is_not_offered(plain_bundle):
    e = fight(plain_bundle)
    me, mount, _ = actors(e)
    assert "Move to 3,0" in names(e) or "Move to 3,1" in names(e)
    assert "Move to 0,6" not in names(e)  # the mount's 2x2 body would leave the map's left edge
    assert not failed_lines(e)


def test_a_frightened_rider_selects_a_legal_dismount_space(plain_bundle):
    e = fight(plain_bundle)
    me, mount, foe = actors(e)
    spot = mounts._landing(e, me, mount)
    assert spot is not None
    source = next((x, y) for x in range(e.grid.width) for y in range(e.grid.height)
                  if e.grid.distance_ft(spot, (x, y)) < e.grid.distance_ft(me.position, (x, y)))
    foe.position = type(me.position)(x=source[0], y=source[1])
    e._apply_condition(me, "condition:typed.frightened", "test:mount-fear", foe.entity_id,
                       expires_on="UNTIL_REMOVED")
    candidate = SimpleNamespace(target_ids=())
    action = next(a for a in e.action_catalog.values() if a.source_definition_id.endswith(".mount.down"))
    selected = mounts._landing(e, me, mount, fear_legal=True)
    assert selected is not None
    assert mounts.fear_allows_saddle_choice(e, me, candidate, action) is True
    assert e.grid.distance_ft(selected, foe.position) >= e.grid.distance_ft(me.position, foe.position)


def test_a_controlled_mount_takes_no_turn_of_its_own(plain_bundle):
    e = fight(plain_bundle)
    order = []
    for _ in range(4):
        order.append(bm.next_turn(e))
    assert MOUNT not in order


# ---------------------------------------------------------------- mount and dismount
def test_dismounting_and_mounting_cost_half_the_riders_speed(plain_bundle):
    e = fight(plain_bundle)
    me, mount, _ = actors(e)
    take(e, "Dismount")
    assert mounts.mount_of(e, me) is None and not (cells(e, me) & cells(e, mount))
    assert me.movement_remaining_ft == 15  # min(60, 30) - 15
    e._assert_invariants()
    assert any("half of its Speed: 15 ft" in line for line in riders(e))
    take(e, "Mount")
    assert mounts.mount_of(e, me) is mount and cells(e, me) < cells(e, mount)
    assert me.movement_remaining_ft == 60  # a Controlled Mount: the mount's Speed
    e._assert_invariants()


def test_mounting_needs_half_a_move_left(plain_bundle):
    e = fight(plain_bundle)
    me, mount, _ = actors(e)
    take(e, "Dismount")
    me.movement_remaining_ft = 14
    assert "Mount" not in names(e)
    me.movement_remaining_ft = 15
    assert "Mount" in names(e)


# ---------------------------------------------------------------- falling off
def test_a_mount_pushed_against_its_will_drops_a_rider_who_fails_the_dc10_save(plain_bundle):
    e = fight(plain_bundle)
    me, mount, _ = actors(e)
    saves(e, 9)
    push_mount(e)
    assert mounts.mount_of(e, me) is None
    assert any(c.condition_id == mounts.PRONE for c in me.conditions.values())
    assert not (cells(e, me) & cells(e, mount))
    assert e.grid.distance_between_cell_sets_ft(cells(e, me), cells(e, mount)) <= 5
    e._assert_invariants()
    assert any("fails the DC 10 Dexterity save" in line for line in riders(e)) and not failed_lines(e)


def test_a_rider_who_passes_the_save_is_carried_along(plain_bundle):
    e = fight(plain_bundle)
    me, mount, _ = actors(e)
    before = (mount.position.x, mount.position.y)
    saves(e, 10)
    push_mount(e)
    assert mounts.mount_of(e, me) is mount and (mount.position.x, mount.position.y) != before
    assert cells(e, me) < cells(e, mount) and not any(c.condition_id == mounts.PRONE for c in me.conditions.values())
    e._assert_invariants()
    assert any("makes the DC 10 Dexterity save" in line for line in riders(e)) and not failed_lines(e)


def test_a_mount_knocked_prone_makes_its_rider_save(plain_bundle):
    e = fight(plain_bundle)
    me, mount, _ = actors(e)
    saves(e, 3)
    e._apply_condition(mount, mounts.PRONE, "test", FOE, expires_on="STAND_UP")
    assert mounts.mount_of(e, me) is None and any(c.condition_id == mounts.PRONE for c in me.conditions.values())
    e._assert_invariants()


def test_a_rider_knocked_prone_makes_the_save_too(plain_bundle):
    e = fight(plain_bundle)
    me, mount, _ = actors(e)
    saves(e, 10)
    e._apply_condition(me, mounts.PRONE, "test", FOE, expires_on="STAND_UP")
    assert mounts.mount_of(e, me) is mount
    saves(e, 1)
    e._apply_condition(me, mounts.PRONE, "test", FOE, expires_on="STAND_UP")
    assert mounts.mount_of(e, me) is None
    e._assert_invariants()


def test_a_riderless_mount_pushed_makes_no_save(plain_bundle):
    e = fight(plain_bundle)
    me, mount, _ = actors(e)
    take(e, "Dismount")
    n = len(e.events)
    push_mount(e)
    assert not [line for line in riders(e, n) if "Dexterity save to stay" in line]


def test_the_mounts_defeat_leaves_the_rider_on_foot(plain_bundle):
    e = fight(plain_bundle)
    me, mount, _ = actors(e)
    e._defeat(mount, "test")
    assert mounts.mount_of(e, me) is None and not [c for c in me.conditions.values() if c.condition_id == mounts.MOUNTED]
    e._assert_invariants()


# ---------------------------------------------------------------- Skillful Riding
def dex_save(e, dc, half=True):
    me, mount, foe = actors(e)
    action = ActionDefinition(source_definition_id="action:test.blast", display_name="Test blast", owner_id=FOE, economy=EconomyKind.ACTION,
                              resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60)
    intent = ActionIntent(intent_id="t", decision_id="d", candidate_id="c", state_version=0, actor_id=FOE, target_ids=(MOUNT,), destination=None)
    row = {"type": "save", "ability": "DEX", "on_fail": [{"type": "damage", "flat": 12, "damage_types": ["fire"]}],
           "on_success": [{"type": "half_damage"}] if half else []}
    ctx = typed_executor.Context(e, foe, action, intent, {"effects": [row], "numbers": {"save_dc": dc}}, [mount], mount)
    hp = mount.current_hp
    typed_executor.run_effects(ctx, [row])
    return hp - mount.current_hp


def test_skillful_riding_a_passed_half_damage_save_takes_none_and_a_failed_one_half(plain_bundle):
    e = fight(plain_bundle)
    assert dex_save(e, bm.PASSES) == 0
    e = fight(plain_bundle)
    assert dex_save(e, bm.FAILS) == 6
    assert any("Skillful Riding" in line for line in riders(e))


def test_a_save_that_is_all_or_nothing_is_left_alone(plain_bundle):
    e = fight(plain_bundle)
    assert dex_save(e, bm.FAILS, half=False) == 12


def test_without_the_rider_the_mount_takes_the_ordinary_half(plain_bundle):
    e = fight(plain_bundle)
    take(e, "Dismount")
    assert dex_save(e, bm.PASSES) == 6


# ---------------------------------------------------------------- the mount's own actions
def test_mount_dash_disengage_and_dodge_are_offered_once_and_the_riders_own_dash_is_not(full_bundle):
    e = fight(full_bundle)
    me, mount, _ = actors(e)
    menu = names(e)
    assert {"Mount: Dash", "Mount: Disengage", "Mount: Dodge", "Mount: Disengage (Bonus Action)"} <= menu
    assert "Dash" not in menu and "Disengage" not in menu
    before = me.movement_remaining_ft
    take(e, "Mount: Dash")
    assert me.movement_remaining_ft == before + 60
    menu = names(e)
    assert not {"Mount: Dash", "Mount: Disengage", "Mount: Dodge"} & menu  # one action a turn
    assert "Mount: Disengage (Bonus Action)" in menu
    take(e, "Mount: Disengage (Bonus Action)")
    assert me.turn_flags.get("disengaged") and "Mount: Disengage (Bonus Action)" not in names(e)


def test_mount_dodge_puts_dodge_on_the_mount(full_bundle):
    e = fight(full_bundle)
    _, mount, _ = actors(e)
    take(e, "Mount: Dodge")
    assert any(c.condition_id == "condition:core.dodge" for c in mount.conditions.values())


def test_shove_from_the_saddle_uses_the_mounts_strength(full_bundle):
    e = fight(full_bundle)
    me, mount, foe = actors(e)
    for ability in ("STR", "DEX"):
        foe.saving_throws[ability] = -40  # the save cannot be passed, so the Shove lands
    assert "Mount: Shove (Prone)" in names(e)
    take(e, "Mount: Shove (Prone)")
    dc = 8 + int(me.proficiency_bonus) + mounts._str_mod(mount)
    assert any(f"{mount.display_name} shoves {foe.display_name} (DC {dc})" in line for line in riders(e)), riders(e)
    assert any(c.condition_id == mounts.PRONE for c in foe.conditions.values())
    assert not failed_lines(e)


def test_a_mount_that_is_not_the_riders_to_command_takes_no_mount_actions(full_bundle):
    e = fight(full_bundle)
    _, mount, _ = actors(e)
    mount.summon["trained"] = False  # an independent mount goes its own way
    menu = names(e)
    assert not {"Mount: Dash", "Mount: Dodge", "Mount: Disengage"} & menu and not [n for n in menu if n.startswith("Move to")]


# ---------------------------------------------------------------- Run Down / Overrun / Trampling Line
def rig(e, mount_bonus=None, foe_bonus=None):
    me, mount, foe = actors(e)
    if mount_bonus is not None:
        mount.saving_throws["STR"] = mount_bonus
    if foe_bonus is not None:
        foe.saving_throws["STR"] = foe_bonus
        foe.skills["Athletics"] = foe_bonus
    return me, mount, foe


def test_run_down_overrun_carries_the_pair_through_the_hostiles_space(full_bundle):
    e = fight(full_bundle)
    me, mount, foe = rig(e, foe_bonus=-40)
    start, pool = (mount.position.x, mount.position.y), me.movement_remaining_ft
    take(e, "Mount: Overrun (Action)")
    assert (mount.position.x, mount.position.y) != start and cells(e, me) < cells(e, mount)
    assert not (cells(e, mount) & cells(e, foe)) and me.movement_remaining_ft < pool
    assert me.turn_flags.get("mount_overrun_target") == FOE
    e._assert_invariants()
    assert not failed_lines(e)


def test_a_failed_overrun_moves_nothing(full_bundle):
    e = fight(full_bundle)
    me, mount, foe = rig(e, mount_bonus=-60)
    me.skills["Animal Handling"] = -60  # Acrobatic Mount: the rider's Animal Handling stands in for the mount's Athletics
    start = (mount.position.x, mount.position.y)
    take(e, "Mount: Overrun (Action)")
    assert (mount.position.x, mount.position.y) == start and not me.turn_flags.get("mount_overrun_target")


def test_acrobatic_mount_swaps_in_the_riders_animal_handling(full_bundle, plain_bundle):
    e = fight(full_bundle)
    me, mount, foe = rig(e, mount_bonus=-60)  # the mount alone would always lose
    me.skills["Animal Handling"] = 60
    take(e, "Mount: Overrun (Action)")
    assert me.turn_flags.get("mount_overrun_target") == FOE
    assert "Mount: Overrun (Action)" not in names(fight(plain_bundle))  # the talent, not the Package, gives the Overrun


def test_overrun_is_a_bonus_action_when_the_mount_has_taken_its_action(full_bundle):
    e = fight(full_bundle)
    rig(e, foe_bonus=-40)
    take(e, "Mount: Dodge")
    assert "Mount: Overrun (Action)" not in names(e)
    assert "Mount: Overrun (Bonus Action)" in names(e)


def test_trampling_line_offers_its_four_choices_once_after_a_won_overrun(full_bundle):
    e = fight(full_bundle)
    me, mount, foe = rig(e, foe_bonus=-40)
    assert not [n for n in names(e) if n.startswith("Trampling Line")]
    take(e, "Mount: Overrun (Action)")
    menu = [n for n in names(e) if n.startswith("Trampling Line")]
    assert len(menu) == 4
    hp = foe.current_hp
    take(e, "Trampling Line: Bludgeoning damage")
    assert foe.current_hp == hp - 4  # PB
    assert not [n for n in names(e) if n.startswith("Trampling Line")]  # once per turn


# ---------------------------------------------------------------- Shared Saddle Rhythm
def test_shared_saddle_rhythm_follows_a_mount_action_once_a_round(full_bundle):
    e = fight(full_bundle)
    me, mount, _ = actors(e)
    assert not [n for n in names(e) if n.startswith("Shared Saddle Rhythm")]
    take(e, "Mount: Dodge")
    picks = [n for n in names(e) if n.startswith("Shared Saddle Rhythm")]
    assert len(picks) == 3
    take(e, "Shared Saddle Rhythm: mount gains Temporary HP")
    assert mount.temporary_hp == 4
    assert not [n for n in names(e) if n.startswith("Shared Saddle Rhythm")]


# ---------------------------------------------------------------- Mounted Offense
def test_mounted_offense_gives_advantage_against_a_smaller_unmounted_creature(full_bundle, plain_bundle):
    def modes(b):
        e = fight(b)
        me, mount, foe = actors(e)
        attack = next(a for a in e.action_catalog.values() if a.owner_id == ME and a.economy == EconomyKind.ACTION
                      and (a.parameters or {}).get("typed", {}).get("effects", [{}])[0].get("type") == "attack")
        ctx = typed_executor.Context(e, me, attack, ActionIntent(intent_id="t", decision_id="d", candidate_id="c", state_version=0, actor_id=ME,
                                                                target_ids=(FOE,), destination=None), attack.parameters["typed"], [foe], foe)
        return mounts.mounted_offense(ctx, foe)

    assert modes(full_bundle) == "ADVANTAGE"
    assert modes(plain_bundle) is None  # the talent is what grants it


def test_the_plug_in_never_logs_a_failure(full_bundle):
    e = fight(full_bundle)
    take(e, "Mount: Dodge")
    take(e, "Shared Saddle Rhythm: mount gains Temporary HP")
    walk(e, (3, 9))
    push_mount(e)
    take(e, "Dismount") if mounts.mount_of(e, e.state.actors[ME]) else None
    assert not failed_lines(e)


def test_a_saved_mounted_fight_reloads_with_its_2x2_mount_and_replays(tmp_path):
    """The service creates a fight through the persistence layer (base engine, no plug-in events) and rebuilds the engine from the
    compiled bundle on reload: the bond is in the saved starting state, the mount is still 2x2 after the reload, and the replay of a
    move and a dismount verifies."""
    from combat.gate4_persistence import Gate4Persistence

    b = rider_bundle(TALENTS)
    session = Gate4Persistence(ROOT, tmp_path).create_match(
        match_seed="MOUNT-SAVED", typed_bundles=(copy.deepcopy(b),),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 12, "y": 6}}})
    e = session.engine
    assert mounts.mount_of(e, e.state.actors[ME]) is e.state.actors[MOUNT]
    assert e._footprint(MOUNT).width_cells == 2
    while e.state.current_actor_id != ME:
        take_on(session, "End turn")
    take_on(session, "Move to 5,6")
    take_on(session, "Dismount")
    reloaded = Gate4Persistence(ROOT, tmp_path).load_match(session.match_id)
    assert reloaded.engine._footprint(MOUNT).width_cells == 2
    assert reloaded.engine.state.actors[MOUNT].position == e.state.actors[MOUNT].position
    assert mounts.mount_of(reloaded.engine, reloaded.engine.state.actors[ME]) is None
    reloaded.engine._assert_invariants()
    assert reloaded.verify()["status"] == "PASS"
    assert not [text for text in riders(reloaded.engine) if " failed: " in text]


def take_on(session, name):
    e = session.engine
    c = next(c for c in e.legal_candidates() if c.display_name == name)
    session.mechanical.execute_intent(ActionIntent(
        intent_id=f"{name}-{e.state.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
        actor_id=e.state.current_actor_id, target_ids=c.target_ids, destination=c.destination))


def test_the_sheets_mount_pick_chooses_the_steed_or_none(tmp_path):
    """The Companions panel's Mount pick (combat/tabletop.py save_summons): a listed steed is kept and used in the next fight,
    "" is a rider on foot, an unlisted one is refused."""
    from combat.tabletop import ButtonStore, TabletopError

    stats = {**bm.SHEET["ability_scores_and_statistics"], "technique_save_dc": bm.FAILS}
    sheet = {**bm.SHEET, "equipment": [], "ability_scores_and_statistics": stats,
             "spheres_and_talents": {"sphere_record_ids": [bm.BEASTMASTERY], "learned_talent_record_ids": [],
                                     "automatic_sphere_component_record_ids": ["BEASTMASTERY_BASE_RIDER_PACKAGE"]}}
    options = compile_character(sheet, actor_id=ME)["summon_options"]
    assert options["mount"] == "warhorse" and {row["key"] for row in options["mounts"]} >= {"warhorse", "tiger"}
    store = ButtonStore(tmp_path)
    saved = store.save_summons("0123abcd-0123", {"counts": {}, "mount": "tiger"}, options)["summons"]
    assert saved["mount"] == "tiger"
    tiger = compile_character(sheet, actor_id=ME, summon_plan=saved)
    assert tiger["summon_options"]["mount"] == "tiger" and [row["summon"]["group"] for row in tiger["summons"]] == ["mount.tiger"]
    afoot = compile_character(sheet, actor_id=ME, summon_plan=store.save_summons("0123abcd-0123", {"counts": {}, "mount": ""}, options)["summons"])
    assert afoot["summon_options"]["mount"] == "" and not afoot["summons"]
    with pytest.raises(TabletopError):
        store.save_summons("0123abcd-0123", {"counts": {}, "mount": "dragon"}, options)
    # A save that says nothing about the mount keeps the saved one.
    assert store.save_summons("0123abcd-0123", {"counts": {}}, options)["summons"]["mount"] == ""


# ---------------------------------------------------------------- One Rider, One Beast / Beastback Relay / Great Beast Charge
def load_athletics():
    spec = importlib.util.spec_from_file_location("ath_helpers", ROOT / "tests" / "test_review_sw-athletics.py")
    ath = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ath)
    return ath


def sure_hit(e, name):
    """Every attack roll of the action called ``name`` is made to hit."""
    for action in e.action_catalog.values():
        if action.display_name == name and isinstance(action.parameters.get("typed"), dict):
            action.parameters["typed"]["numbers"] = {**action.parameters["typed"]["numbers"], "attack_bonus": 40}


def test_a_mounted_rider_keeps_their_own_slowing_on_top_of_the_mounts_speed():
    """Dragon-Felling Chop slows its target (5 ft on a saved throw): the mounted rider's Speed is the mount's less that, not the mount's."""
    from combat.gate2_runtime_models import ActionIntent as Intent
    from combat.gate4_engine import Gate4ControllerEngine

    ath = load_athletics()
    axe = ath._bundle(ath.AXES, ["TAL_AXES_DRAGON_FELLING_CHOP"], ath.AXE_KIT, dc=ath.PASS, actor_id=ath.ME)
    e = Gate4ControllerEngine(ROOT, match_seed="MOUNT-SLOWED", typed_bundles=(axe, rider_bundle([])),
                              roster_setup={"primary_actor_ids": [ath.ME, ME], "team_by_actor": {ath.ME: "team:a", ME: "team:b"},
                                            "starting_positions": {ath.ME: {"x": 3, "y": 6}, ME: {"x": 4, "y": 6}}})
    e.state.current_slot_index = e.state.initiative_order.index(ath.ME)
    e.state.current_actor_id = ath.ME
    e._system_start_turn()
    c = next(c for c in e.legal_candidates() if c.display_name == ath.STRIKE + "Drive + Dragon-Felling Chop" and c.target_ids == (ME,))
    typed = e.action_catalog[c.source_definition_id].parameters["typed"]
    typed["numbers"] = {**typed["numbers"], "attack_bonus": 40}
    start = len(e.events)
    e.execute_intent(Intent(intent_id="x", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                            actor_id=ath.ME, target_ids=c.target_ids, destination=c.destination))
    saves_made = [ev.payload for ev in e.events[start:] if ev.event_type == "SAVE_ROLLED"]
    # Owner text: "If the target is mounted, climbing, or flying by wings ... it has Disadvantage on the save."
    assert saves_made and all(p.get("mode") == "DISADVANTAGE" for p in saves_made), saves_made
    rider = e.state.actors[ME]
    assert mounts.mount_of(e, rider) is not None
    assert e._effective_speed(rider) == 55, e._effective_speed(rider)  # the Warhorse's 60 less the 5 ft
    assert not failed_lines(e)


def test_dragon_felling_chop_gives_no_disadvantage_against_an_unmounted_target():
    from combat.gate2_runtime_models import ActionIntent as Intent
    from combat.gate4_engine import Gate4ControllerEngine

    ath = load_athletics()
    axe = ath._bundle(ath.AXES, ["TAL_AXES_DRAGON_FELLING_CHOP"], ath.AXE_KIT, dc=ath.PASS, actor_id=ath.ME)
    e = Gate4ControllerEngine(ROOT, match_seed="MOUNT-ON-FOOT", typed_bundles=(axe, rider_bundle([], plan={"counts": {}, "mount": ""})),
                              roster_setup={"primary_actor_ids": [ath.ME, ME], "team_by_actor": {ath.ME: "team:a", ME: "team:b"},
                                            "starting_positions": {ath.ME: {"x": 3, "y": 6}, ME: {"x": 4, "y": 6}}})
    assert mounts.mount_of(e, e.state.actors[ME]) is None  # the same target on foot
    e.state.current_slot_index = e.state.initiative_order.index(ath.ME)
    e.state.current_actor_id = ath.ME
    e._system_start_turn()
    c = next(c for c in e.legal_candidates() if c.display_name == ath.STRIKE + "Drive + Dragon-Felling Chop" and c.target_ids == (ME,))
    typed = e.action_catalog[c.source_definition_id].parameters["typed"]
    typed["numbers"] = {**typed["numbers"], "attack_bonus": 40}
    start = len(e.events)
    e.execute_intent(Intent(intent_id="x", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                            actor_id=ath.ME, target_ids=c.target_ids, destination=c.destination))
    assert [ev.payload.get("mode") for ev in e.events[start:] if ev.event_type == "SAVE_ROLLED"] == ["NORMAL"]


def one_rider_fight(seed="MOUNT-ONE-RIDER"):
    e = fight(rider_bundle([mounts.ONE_RIDER]), seed=seed)
    me, mount, foe = actors(e)
    me.resources[mounts.FOCUS] = me.resource_maximums.get(mounts.FOCUS, 3) or 3
    return e, me, mount, foe


def test_one_rider_one_beast_binds_the_pair_in_one_rhythm():
    e, me, mount, foe = one_rider_fight()
    assert e._ac_modifier(mount) == 0
    take(e, "One Rider, One Beast")
    # Owner text: both gain +2 AC, Advantage on Dexterity saves, ignore nonmagical difficult terrain; neither provokes Opportunity Attacks
    # from movement; the higher Speed for both.
    for who in (me, mount):
        assert any(c.condition_id == mounts.RHYTHM for c in who.conditions.values()), who.entity_id
    assert e._ac_modifier(mount) == e._ac_modifier(me) == 2  # the beast gets what the rider's typed action gives the rider
    assert me.turn_flags.get("disengaged")
    assert mounts._partner(e, me) is mount and mounts._partner(e, mount) is me
    assert not failed_lines(e)
    e._assert_invariants()


def test_one_rider_one_beast_lends_the_slower_one_the_higher_speed():
    e, me, mount, foe = one_rider_fight()
    mount.summon["trained"] = False  # an independent mount steers itself, so the rider's own 30 ft is what the rhythm raises
    assert e._effective_speed(me) == 30
    take(e, "One Rider, One Beast")
    assert e._effective_speed(me) == e._effective_speed(mount) == 60


def test_one_rider_one_beast_follow_up_after_a_hit_once_a_turn():
    e, me, mount, foe = one_rider_fight()
    take(e, "One Rider, One Beast")
    assert not [n for n in names(e) if "the other" in n]  # nothing has hit yet
    take(e, "Grab an improvised weapon")
    sure_hit(e, "Improvised weapon attack")
    take(e, "Improvised weapon attack")
    assert foe.current_hp < foe.maximum_hp and me.turn_flags.get("rhythm_open") == MOUNT
    menu = [n for n in names(e) if n.startswith("One Rider, One Beast: the other")]
    assert len(menu) == 2  # the foe is already at the mount's side: no nearer square to move to, so only the two Shoves
    from combat.gate2_runtime_models import Position

    foe.position = Position(x=12, y=6)  # (the foe backs away)
    assert "One Rider, One Beast: the other moves 10 ft (Reaction)" in names(e)
    before = mount.position
    take(e, "One Rider, One Beast: the other moves 10 ft (Reaction)")
    assert not mount.reaction_available and me.turn_flags.get("rhythm_used")
    assert mount.position != before and cells(e, me) < cells(e, mount)  # the mount closed on the foe, the rider still on it
    assert not [n for n in names(e) if n.startswith("One Rider, One Beast: the other")]  # once per turn
    assert not failed_lines(e)
    e._assert_invariants()


def test_the_rhythm_needs_the_beasts_reaction():
    e, me, mount, foe = one_rider_fight()
    take(e, "One Rider, One Beast")
    take(e, "Grab an improvised weapon")
    sure_hit(e, "Improvised weapon attack")
    mount.reaction_available = False
    take(e, "Improvised weapon attack")
    assert not [n for n in names(e) if n.startswith("One Rider, One Beast: the other")]


def test_the_rhythm_follow_up_can_be_the_beasts_shove():
    e, me, mount, foe = one_rider_fight()
    rig(e, foe_bonus=-40)  # the foe's Strength and Dexterity saves always fail
    foe.saving_throws["DEX"] = -40
    take(e, "One Rider, One Beast")
    take(e, "Grab an improvised weapon")
    sure_hit(e, "Improvised weapon attack")
    take(e, "Improvised weapon attack")
    take(e, "One Rider, One Beast: the other Shoves, Prone (Reaction)")
    assert any(c.condition_id == mounts.PRONE for c in foe.conditions.values())
    assert not mount.reaction_available and any("shoves" in line for line in riders(e))
    assert not failed_lines(e)


# ---- Beastback Relay
RELAY_TALENTS = ["TAL_BEASTMASTERY_BEAST_TAMER", mounts.MOUNT_TRAINING, mounts.BEASTBACK]
TIGER = "actor:factory.probe.summon.beast0.tiger.1"


def relay_fight():
    e = fight(rider_bundle(RELAY_TALENTS, plan={"mount": "warhorse", "beasts": ["tiger"]}), seed="MOUNT-RELAY")
    return e, e.state.actors[ME], e.state.actors[MOUNT], e.state.actors[TIGER]


def test_beastback_relay_moves_the_rider_to_another_willing_mount_without_an_action():
    e, me, horse, tiger = relay_fight()
    assert mounts.mount_of(e, me) is horse and mounts.rider_of(e, tiger) is None
    assert "Beastback Relay: transfer to another mount" in names(e)
    take(e, "Beastback Relay: transfer to another mount", TIGER)
    assert mounts.mount_of(e, me) is tiger and mounts.rider_of(e, horse) is None and mounts.rider_of(e, tiger) is me
    assert cells(e, me) < cells(e, tiger) and not cells(e, me) & cells(e, horse)
    assert me.action_available and me.bonus_action_available and me.reaction_available  # "without spending an Action"
    assert me.movement_remaining_ft == 40  # 60 - 15 (half the rider's Speed to get on) is more than the Tiger's own 40
    assert "Beastback Relay: transfer to another mount" not in names(e)  # once, from the start of the turn
    assert not any(ev.event_type == "REACTION_WINDOW_OPENED" for ev in e.events)  # no Opportunity Attack for the transfer
    e._assert_invariants()
    assert not failed_lines(e)


def test_beastback_relay_needs_a_turn_that_began_in_the_saddle_and_a_free_mount_in_15_feet():
    e, me, horse, tiger = relay_fight()
    me.turn_flags["relay_open"] = False
    assert "Beastback Relay: transfer to another mount" not in names(e)  # the turn did not begin ridden
    me.turn_flags["relay_open"] = True
    from combat.gate2_runtime_models import Position

    tiger.position = Position(x=12, y=12)  # out of the 15 feet
    assert "Beastback Relay: transfer to another mount" not in names(e)


def test_only_the_riders_own_mountable_creatures_can_take_the_relay():
    e, me, horse, tiger = relay_fight()
    tiger.summon["mountable"] = False
    assert "Beastback Relay: transfer to another mount" not in names(e)
    plain = fight(rider_bundle([mounts.BEASTBACK]))  # no other beast at all
    assert "Beastback Relay: transfer to another mount" not in names(plain)


# ---- Great Beast Charge
CHARGE = "Great Beast Charge"
STRIKE = "Great Beast Charge: the closing attack"
OVERRUN = "Great Beast Charge: Overrun through the target"
CHARGE_TALENTS = ["TAL_BEASTMASTERY_RUN_DOWN", "TAL_BEASTMASTERY_TRAMPLING_LINE", mounts.GREAT_CHARGE]


def charge_fight(foe_at=(10, 6)):
    e = fight(rider_bundle(CHARGE_TALENTS), foe_at=foe_at, seed="MOUNT-CHARGE")
    me, mount, foe = actors(e)
    sure_hit(e, STRIKE)
    return e, me, mount, foe


def test_great_beast_charge_is_the_riders_action_and_grants_the_mounts_speed_of_movement():
    from combat import motion

    e, me, mount, foe = charge_fight()
    assert CHARGE in names(e) and STRIKE not in names(e)  # the attack comes at the end, once the charge has begun
    assert not motion.ignores_difficult(e, me)
    before = me.movement_remaining_ft
    take(e, CHARGE, FOE)
    assert not me.action_available and me.movement_remaining_ft == before + 60  # up to the Warhorse's Speed
    assert motion.ignores_difficult(e, me)  # "ignore nonmagical difficult terrain"
    assert me.turn_flags["spark_step_ignore_oa_from"] == FOE  # "no Opportunity Attacks from one chosen creature"
    assert me.turn_flags["charge_open"] == FOE
    assert CHARGE not in names(e)
    assert not failed_lines(e)


def test_the_charge_provokes_nothing_from_the_chosen_creature_but_walking_away_does():
    def opportunity_windows(charge):
        e, me, mount, foe = charge_fight(foe_at=(4, 6))  # at the mount's side
        if charge:
            take(e, CHARGE, FOE)
        start = len(e.events)
        walk(e, (3, 10))
        return [ev for ev in e.events[start:] if ev.event_type == "REACTION_WINDOW_OPENED"]

    assert opportunity_windows(charge=False)  # the foe takes its Opportunity Attack as the pair leaves its reach
    assert not opportunity_windows(charge=True)


def test_the_charge_ends_with_one_melee_attack_with_its_damage_and_save():
    e, me, mount, foe = charge_fight(foe_at=(10, 6))
    foe.saving_throws["STR"] = -40
    take(e, CHARGE, FOE)
    walk(e, (8, 6))  # 5 ft from the foe: the pair's move
    assert STRIKE in names(e)
    hp = foe.current_hp
    take(e, STRIKE, FOE)
    assert hp - foe.current_hp >= 3  # at least 3d8's minimum of 3
    pushed = (foe.position.x, foe.position.y) != (10, 6)
    assert pushed or any(c.condition_id == mounts.PRONE for c in foe.conditions.values())  # Failed Save: Push 15 feet or knock Prone
    assert STRIKE not in names(e)  # one melee attack
    assert not failed_lines(e)
    e._assert_invariants()


def test_the_charge_pushes_five_feet_on_a_passed_save():
    e, me, mount, foe = charge_fight(foe_at=(10, 6))
    foe.saving_throws["STR"] = 40  # Successful Save: Push 5 feet
    foe.saving_throws["DEX"] = 40
    take(e, CHARGE, FOE)
    walk(e, (8, 6))
    take(e, STRIKE, FOE)
    assert (foe.position.x, foe.position.y) == (11, 6)
    assert not any(c.condition_id == mounts.PRONE for c in foe.conditions.values()) and not failed_lines(e)


def test_pack_attack_is_not_folded_into_the_charges_closing_attack():
    """Pack Attack is a line for tame creatures (its own typing); the charge's attack carries no advantage row from it."""
    import json

    e = fight(rider_bundle(CHARGE_TALENTS + ["tianxia.talent.beastmastery.pack_attack"]), foe_at=(10, 6), seed="MOUNT-CHARGE")
    rows = [a for a in e.action_catalog.values() if a.display_name == STRIKE]
    assert rows and all("pack_attack" not in json.dumps(a.parameters.get("typed")) for a in rows)


def test_the_charge_can_overrun_through_a_hostile_space_and_opens_trampling_line():
    e, me, mount, foe = charge_fight(foe_at=(4, 6))
    rig(e, foe_bonus=-40)
    assert OVERRUN not in names(e)  # only inside a charge
    take(e, CHARGE, FOE)
    assert OVERRUN in names(e) and "Mount: Overrun (Action)" in names(e)  # the charge's own, on top of the mount's action
    start = (mount.position.x, mount.position.y)
    take(e, OVERRUN, FOE)
    assert (mount.position.x, mount.position.y) != start and not cells(e, mount) & cells(e, foe) and cells(e, me) < cells(e, mount)
    assert me.turn_flags.get("mount_overrun_target") == FOE and not me.turn_flags.get("mount_action_used")
    assert OVERRUN not in names(e)  # one hostile creature's space
    assert [n for n in names(e) if n.startswith("Trampling Line")]
    assert not failed_lines(e)
    e._assert_invariants()


def test_the_charge_is_only_the_riders_while_mounted_on_a_controlled_mount():
    e, me, mount, foe = charge_fight()
    take(e, "Dismount")
    assert not {CHARGE, STRIKE, OVERRUN} & names(e)
    take(e, "Mount")
    mount.summon["trained"] = False
    assert not {CHARGE, STRIKE, OVERRUN} & names(e)


def test_the_relay_and_the_charge_are_no_longer_left_to_the_gm():
    b = rider_bundle(CHARGE_TALENTS + [mounts.BEASTBACK, mounts.ONE_RIDER, "TAL_BEASTMASTERY_DEFENSIVE_RIDER"])
    left = {name for rows in b["diagnostics"]["skipped"].values() for name in rows}
    assert not {"Great Beast Charge", "Beastback Relay", "One Rider, One Beast"} & left, left
    assert "Defensive Rider" not in left  # run since the lock round's retarget hook: combat/ext/mount_guard.py (tests/test_h2_mount_guard.py)
