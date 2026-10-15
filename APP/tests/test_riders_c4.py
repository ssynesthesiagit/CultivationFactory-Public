"""Rider lane C4 (owner 2026-09-29: "i want everything we can automated, keep going until its only the non-combat ones
left"): the printed lines of Sand, Void, Ink, Dark, Brute, Protection and Trap abilities that reached the GM only as riders.
Every line automated here is compiled on a real character and run through the engine (a few through the table service,
with a commit and reload). C4_OLD=1 swaps in the authority of the base commit, so each typing test fails there; plug-in
behaviour is shown failing on the base commit by running this file there (see the lane report).

Overrides: authority/typed_mechanics/reviewed_final.d/riders_c4.json plus in-place edits to the files that already held the
entry (review_sw-sabers.json, ...). Plug-ins: combat/ext/sand_terrain.py (shared Sand Terrain queries),
combat/ext/sand_burial.py (the Buried state), combat/ext/sand_riders.py.
"""
import os
import subprocess

import pytest

import combat.factory_compiler as compiler
from combat import typed_executor, zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import ROOT, sheet

BASE_COMMIT = "2f68a85c"
ME, ALLY, FOE = "actor:factory.c4_me", "actor:factory.c4_ally", "actor:factory.c4_foe"
FAIL, PASS = 50, -40  # technique save DC that makes every save fail / succeed


@pytest.fixture(autouse=True, scope="session")
def base_typing(tmp_path_factory):
    if os.environ.get("C4_OLD"):
        path = tmp_path_factory.mktemp("authority") / "base.json"
        path.write_bytes(subprocess.check_output(["git", "show", f"{BASE_COMMIT}:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"], cwd=ROOT))
        compiler.TYPED_AUTHORITY = path


# ------------------------------------------------------------------------------------------------------- harness
def bundle(*mids, cl=15, dc=16, actor_id=ME, score=14, kit=None):
    return compile_character(sheet(list(mids), cl=cl, dc=dc, score=score, kit=kit), actor_id=actor_id)


def fight(me, *, foe=None, ally=None, me_at=(3, 6), foe_at=(6, 6), ally_at=(3, 8), seed="C4"):
    foe = foe or bundle("SAND_BASE_SCOURING_HAND", actor_id=FOE, cl=5)
    bundles = [me, foe] + ([ally] if ally else [])
    ids = [b["actor_id"] for b in bundles]
    teams = {ME: "team:a", FOE: "team:b", ALLY: "team:a"}
    spots = {ME: me_at, FOE: foe_at, ALLY: ally_at}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles), roster_setup={
        "primary_actor_ids": ids, "team_by_actor": {i: teams[i] for i in ids},
        "starting_positions": {i: {"x": spots[i][0], "y": spots[i][1]} for i in ids}})
    turn(engine, ME)
    return engine


def turn(engine, actor_id):
    """Make it ``actor_id``'s turn, fresh economy."""
    while engine.state.current_actor_id != actor_id:
        engine.end_turn()
    actor = engine.state.actors[actor_id]
    actor.action_available, actor.bonus_action_available, actor.reaction_available = True, True, True
    return actor


def legal(engine):
    return {c.display_name for c in engine.legal_candidates()}


def use(engine, name, *, target=None, at=None, actor_id=None):
    actor_id = actor_id or engine.state.current_actor_id
    rows = [c for c in engine.legal_candidates() if (c.display_name == name or c.display_name.startswith(name + " at "))
            and (target is None or target in (c.target_ids or ()))
            and (at is None or (c.destination is not None and (c.destination.x, c.destination.y) == tuple(at)))]
    assert rows, f"{name!r} is not legal here; legal: {sorted({n.split(' at ')[0] for n in legal(engine)})[:60]}"
    c = rows[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{before}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                       state_version=c.state_version, actor_id=actor_id,
                                       target_ids=c.target_ids or ((target,) if target else ()), destination=c.destination))
    return engine.events[before:]


def held(actor, name):
    return [c for c in actor.conditions.values() if c.condition_id == f"condition:typed.{name}"]


def payloads(events, kind):
    return [e.payload or {} for e in events if e.event_type == kind]


def ctx_of(engine, user_id, target_id, source, *, dc=16, pb=4, cl=15):
    """A typed context of ``source`` (a compiled action of ``user_id``) aimed at ``target_id``."""
    user, target = engine.state.actors[user_id], engine.state.actors[target_id]
    action = engine.action_catalog[source]
    typed = {**action.parameters["typed"], "numbers": {**action.parameters["typed"]["numbers"], "save_dc": dc, "pb": pb, "cl": cl}}
    return typed_executor.Context(engine, user, action, None, typed, [target], target, {})


def action_id(engine, owner, name):
    """The compiled action named ``name`` (or its first option, "Scouring Hand: ...")."""
    ids = engine.state.actors[owner].action_ids
    return next((a for a in ids if engine.action_catalog[a].display_name == name), None) or \
        next(a for a in ids if engine.action_catalog[a].display_name.startswith(name + ":"))


def mech(key):
    import json

    return json.loads(compiler.TYPED_AUTHORITY.read_bytes())["mechanics"][key]


# ================================================================================================= SAND
BURIAL, QUICKSAND, MOUTH, DRAG = ("TAL_SAND_BURIAL_OF_THE_NAMELESS_ARMY", "TAL_SAND_QUICKSAND_GATE",
                                  "TAL_SAND_DEVOURING_DUNE_MOUTH", "TAL_SAND_SAND_DRAG")
GRIP, SCOUR = "TAL_SAND_THOUSAND_GRAIN_GRIP", "SAND_BASE_SCOURING_HAND"


def bury(engine, *, by=ME, target=FOE, dc=16, restrain="always", move=None, source=None):
    """``target`` Buried (and Restrained) by ``by`` through the typed sand_bury row."""
    source = source or action_id(engine, by, "Scouring Hand")
    row = {"type": "sand_bury", "applies_to": "target", "until_escape": True, "restrain": restrain,
           **({"condition_data": {"escape_move": move}} if move else {})}
    typed_executor.run_effects(ctx_of(engine, by, target, source, dc=dc), [row])


def test_buried_is_a_real_state_speed_minus_ten_and_sand_dex_saves_at_disadvantage():
    """Sphere of Sand, Burial: "the creature's Speed is reduced by 10 feet ... Disadvantage on ... Dexterity saving throws made
    to avoid being knocked Prone or moved by Sand talents". Before, "buried" was a label the rules file did not know."""
    engine = fight(bundle(SCOUR))
    foe = engine.state.actors[FOE]
    speed = engine._effective_speed(foe)
    bury(engine, restrain=None)
    assert held(foe, "buried") and engine._effective_speed(foe) == speed - 10
    ctx = ctx_of(engine, ME, FOE, action_id(engine, ME, "Scouring Hand"))
    from combat import ext

    assert {"modes": ["DISADVANTAGE"]} in ext.run("save", ctx, foe, "DEX", {"forced_movement"})
    assert not [r for r in ext.run("save", ctx, foe, "DEX", {"blinded"}) if r]  # not a push or Prone: no penalty
    assert not [r for r in ext.run("save", ctx, foe, "STR", {"forced_movement"}) if r]


def test_buried_creature_cannot_benefit_from_invisible():
    """"the creature cannot benefit from being invisible against creatures that can perceive the sand covering it"."""
    from combat import senses

    engine = fight(bundle(SCOUR))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    engine._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    assert not senses.masked_conditions(engine, me, foe).get(FOE)
    bury(engine, restrain=None)
    invisible = {k for k, c in foe.conditions.items() if c.condition_id == "condition:typed.invisible"}
    assert senses.masked_conditions(engine, me, foe)[FOE] >= invisible  # attacks against it
    assert senses.masked_conditions(engine, foe, me)[FOE] >= invisible  # its own attacks
    engine._apply_condition(me, "condition:typed.blinded", "test", FOE, expires_on="UNTIL_REMOVED")
    assert not (senses.masked_conditions(engine, me, foe).get(FOE, set()) & invisible)  # a Blinded attacker cannot see the sand


def test_quicksand_burial_at_the_table_survives_commit_and_reload(tmp_path):
    """At the table: Quicksand Gate buries the foe as its turn starts in the gate; after a commit and a reload the Buried
    state keeps its DC and "until it escapes", and the foe's menu offers "Dig free of the sand" (an Action check against the
    burier's DC: "A creature can use an Action to make a Strength (Athletics) or Dexterity (Acrobatics) check ...")."""
    from tests.r1i_service_support import FOE as TFOE, fixture
    from tests.test_r1i_round3 import reload

    combat, table, mid, send, commit = fixture(tmp_path, [QUICKSAND], owner_dc=50)
    menu = table.state(mid)["menu"]
    cid = next(o["candidate_id"] for g in menu["actions"] if g["label"] == "Quicksand Gate"
               for o in g["options"] if o.get("destination") == {"x": 4, "y": 6})
    commit(cid)
    while table.state(mid)["menu"]["actor_id"] != TFOE:
        commit(table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    (buried,) = held(engine.state.actors[TFOE], "buried")
    assert buried.data["escape_dc"] == 50 and buried.expires_on == "UNTIL_REMOVED" and isinstance(buried.data["label"], str)
    labels = [g["label"] for g in table.state(mid)["menu"]["actions"]]
    assert "Dig free of the sand" in labels


def test_dig_free_on_the_engine_ends_buried_and_restrained_and_grants_half_speed():
    engine = fight(bundle(SCOUR, dc=16))
    bury(engine, dc=1, move="half_speed")
    foe = turn(engine, FOE)
    assert "Dig free of the sand" in legal(engine)
    before = foe.movement_remaining_ft
    events = use(engine, "Dig free of the sand")
    check = payloads(events, "CHECK_ROLLED")[-1]
    assert check["dc"] == 1 and check["success"]
    assert not held(foe, "buried") and not held(foe, "restrained")
    # Native restraint removal also restores the unspent allowance withheld at
    # turn start (20 feet while Buried), separately from Dig Free's extra 15.
    restored = payloads(events, "MOVEMENT_ALLOWANCE_RESTORED")
    assert [p["restored_ft"] for p in restored] == [20]
    # Observation snapshots are existing event metadata. Keep the exact
    # movement assertion and also verify what each side actually observed.
    assert payloads(events, "MOVEMENT_GRANTED") == [{
        "distance_ft": 15,
        "observations_after": {
            "team:b": {ME: {"x": 3, "y": 6}},
            "team:a": {FOE: {"x": 6, "y": 6}},
        },
    }]
    assert foe.movement_remaining_ft == before + 20 + engine._effective_speed(foe) // 2
    assert "Dig free of the sand" not in legal(engine)


def test_dig_free_failure_keeps_the_burial():
    engine = fight(bundle(SCOUR, dc=16))
    bury(engine, dc=60)
    foe = turn(engine, FOE)
    events = use(engine, "Dig free of the sand")
    assert not payloads(events, "CHECK_ROLLED")[-1]["success"]
    assert held(foe, "buried") and held(foe, "restrained")


def test_thousand_grain_grip_worsens_the_escape_and_cuts_on_failure():
    """Thousand-Grain Grip: "A creature Buried by your Sand talent attempts to escape ... The creature makes its escape check
    ... with Disadvantage. If it fails, it takes Slashing damage equal to your Proficiency Bonus + your key ability modifier."
    Before, its generic row fired on any creature moving 5 feet and did nothing."""
    engine = fight(bundle(SCOUR, GRIP, dc=16))
    bury(engine, dc=60)
    foe = turn(engine, FOE)
    me = engine.state.actors[ME]
    me.reaction_available = True
    hp = foe.current_hp
    events = use(engine, "Dig free of the sand")
    rolled = [e.payload for e in events if e.event_type == "CHECK_ROLLED"][-1]
    assert rolled["actor"]["mode"] == "DISADVANTAGE" and not rolled["success"]
    grip = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == GRIP]
    assert grip and foe.current_hp < hp
    assert not me.reaction_available


def test_thousand_grain_grip_no_longer_fires_on_bare_movement():
    engine = fight(bundle(SCOUR, GRIP, dc=16), foe_at=(8, 6))
    foe = turn(engine, FOE)
    engine.state.actors[ME].reaction_available = True
    moves = [c for c in engine.legal_candidates() if c.destination is not None and c.display_name.lower().startswith("move")]
    if not moves:
        pytest.skip("no move candidate")
    c = moves[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id="mv", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                       state_version=c.state_version, actor_id=FOE, target_ids=(), destination=c.destination))
    assert not [e for e in engine.events[before:] if e.source_definition_id == GRIP]
    assert engine.state.actors[ME].reaction_available


def test_burial_of_the_nameless_army_buries_restrains_and_grinds_at_turn_start():
    """"On a failed save, a creature is Buried and Restrained ... While the effect lasts, a hostile creature that starts its turn
    Buried in the area takes 3d8 Bludgeoning damage and cannot take Reactions until the start of its next turn."""
    engine = fight(bundle(BURIAL, dc=FAIL), foe_at=(10, 6))
    events = use(engine, "Burial of the Nameless Army", at=(10, 6))
    foe = engine.state.actors[FOE]
    assert held(foe, "buried") and held(foe, "restrained")
    (restrained,) = held(foe, "restrained")
    assert restrained.data.get("parent_hold") in foe.conditions
    assert [z for z in zones.typed_zones(engine) if z.source_definition_id.endswith(BURIAL) or BURIAL in z.source_definition_id]
    assert not [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]  # casting deals none of it
    hp = foe.current_hp
    turn(engine, FOE)
    assert foe.current_hp < hp and held(foe, "reaction_denied")
    denied = held(foe, "reaction_denied")[0]
    assert denied.expires_on != "START_OF_SOURCE_NEXT_TURN"  # the start of *its* next turn


def test_burial_of_the_nameless_army_escape_moves_half_speed():
    engine = fight(bundle(BURIAL, dc=FAIL), foe_at=(10, 6))
    use(engine, "Burial of the Nameless Army", at=(10, 6))
    foe = engine.state.actors[FOE]
    (buried,) = held(foe, "buried")
    assert buried.data["escape_move"] == "half_speed" and buried.data["escape_dc"] == FAIL


def test_burial_success_is_buried_until_the_start_of_your_next_turn():
    engine = fight(bundle(BURIAL, dc=PASS), foe_at=(10, 6))
    use(engine, "Burial of the Nameless Army", at=(10, 6))
    foe = engine.state.actors[FOE]
    assert held(foe, "buried") and not held(foe, "restrained")


def _quicksand(dc):
    engine = fight(bundle(QUICKSAND, dc=dc), foe_at=(10, 6))
    use(engine, "Quicksand Gate", at=(10, 6))
    return engine, engine.state.actors[FOE]


def test_quicksand_gate_buries_until_escape_and_restrains_only_the_already_buried():
    """"On a failed save, it is Buried until it escapes. If it was already Buried, it is Buried and Restrained" (GM line)."""
    engine, foe = _quicksand(FAIL)
    turn(engine, FOE)  # starts its turn in the gate: fails, Buried
    assert held(foe, "buried") and not held(foe, "restrained")
    assert held(foe, "buried")[0].expires_on == "UNTIL_REMOVED"
    turn(engine, ME)
    turn(engine, FOE)  # again, already Buried: now Restrained too
    assert held(foe, "restrained") and held(foe, "restrained")[0].data["parent_hold"] in foe.conditions


def test_devouring_dune_mouth_restrains_an_already_buried_creature():
    engine = fight(bundle(MOUTH, dc=FAIL), foe_at=(10, 6))
    use(engine, "Devouring Dune Mouth", at=(10, 6))
    foe = engine.state.actors[FOE]
    turn(engine, FOE)
    assert held(foe, "buried")
    first_restrained = bool(held(foe, "restrained"))
    turn(engine, ME)
    turn(engine, FOE)
    assert not first_restrained and held(foe, "restrained")


def test_sand_drag_buries_only_in_deep_sand():
    """"If the movement ends in Deep Sand Terrain, the target is Buried until the start of your next turn." """
    engine = fight(bundle(DRAG, "TAL_SAND_DUNE_WALL", dc=FAIL), foe_at=(5, 6))
    foe = engine.state.actors[FOE]
    engine.state.zones["zone:test:deep"] = _sand_zone(engine, ME, ["deep sand terrain"], [(x, y) for x in range(4, 12) for y in range(3, 10)])
    use(engine, "Sand Drag", target=FOE)
    assert held(foe, "buried")
    engine2 = fight(bundle(DRAG, dc=FAIL), foe_at=(5, 6))
    engine2.state.zones["zone:test:shallow"] = _sand_zone(engine2, ME, ["shallow sand terrain"], [(x, y) for x in range(4, 12) for y in range(3, 10)])
    use(engine2, "Sand Drag", target=FOE)
    assert not held(engine2.state.actors[FOE], "buried")


def _sand_zone(engine, owner, terrain, cells, source=None):
    from combat.gate2_runtime_models import ZoneState

    return ZoneState(zone_id=f"zone:test:{terrain[0].split()[0]}", source_definition_id=source or "test:sand", owner_id=owner,
                     center=Position(x=cells[0][0], y=cells[0][1]), radius_cells=0,
                     affected_cells=tuple(Position(x=x, y=y) for x, y in cells), concentration_link=False, duration_rounds=10,
                     created_round=engine.state.round_number,
                     trigger_profile={"kind": zones.KIND, "name": "Sand", "terrain": terrain, "difficult": "hostile",
                                      "visual": {"material": "sand"}, "triggers": [], "numbers": {"pb": 4, "save_dc": 16}})


# ------------------------------------------------------------------------------------------------ Sand: reactions and gates
AXE = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}
BOW = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gong_jian", "name": "Gong Jian", "quantity": 1}]}}
DUNE_BANK, MIRAGE, COURT = "TAL_SAND_DUNE_BANK", "TAL_SAND_GLASS_MIRAGE_REFLECTION", "TAL_SAND_COURT_OF_TEN_THOUSAND_DUNES"
CELLS = [(x, y) for x in range(0, 16) for y in range(3, 10)]


def armed_foe(kit=AXE, **kw):
    return bundle(SCOUR, actor_id=FOE, cl=5, kit=kit, **kw)


def foe_attacks(engine, target, name="Fu (Short Axe) attack"):
    turn(engine, FOE)
    return use(engine, name, target=target)


def rolled_ac(events, target):
    return [p["target_ac"] if "target_ac" in p else p.get("effective_ac") for e in events if e.event_type == "ATTACK_ROLLED"
            and target in e.target_ids for p in [e.payload or {}]]


def test_dune_bank_gives_an_ally_half_cover_against_the_one_attack():
    """Dune Bank: "You or a creature within 5 feet of Sand Terrain you control is targeted by an attack roll ... The target
    gains Half Cover against the triggering attack. The sand bank collapses immediately after the attack resolves." """
    ally = bundle(SCOUR, actor_id=ALLY, cl=5)
    engine = fight(bundle(DUNE_BANK, cl=5), foe=armed_foe(), ally=ally, ally_at=(5, 6), foe_at=(6, 6))
    engine.state.zones["zone:test:shallow"] = _sand_zone(engine, ME, ["shallow sand terrain"], [(4, 6)])
    target = engine.state.actors[ALLY]
    base = target.armor_class + engine._ac_modifier(target)
    events = foe_attacks(engine, ALLY)
    assert [e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == DUNE_BANK]
    rolled = [(e.payload or {})["target_ac"] for e in events if e.event_type == "ATTACK_ROLLED" and ALLY in e.target_ids]
    assert rolled[0] == base + 2
    assert not held(target, "sand_bank") and target.armor_class + engine._ac_modifier(target) == base  # collapsed after the attack
    assert not engine.state.actors[ME].reaction_available


def test_dune_bank_three_quarters_cover_in_deep_sand_at_cl11():
    engine = fight(bundle(DUNE_BANK, cl=11), foe=armed_foe(), foe_at=(4, 6))
    engine.state.zones["zone:test:deep"] = _sand_zone(engine, ME, ["deep sand terrain"], [(3, 6)])
    me = engine.state.actors[ME]
    applied = []
    engine_apply = engine._apply_condition

    def spy(actor, condition_id, *args, **kwargs):
        if condition_id == "condition:typed.sand_bank":
            applied.append(kwargs.get("data", {}).get("amount"))
        return engine_apply(actor, condition_id, *args, **kwargs)

    engine._apply_condition = spy
    foe_attacks(engine, ME)
    assert applied == [5]


def test_dune_bank_is_not_offered_away_from_sand():
    engine = fight(bundle(DUNE_BANK, cl=5), foe=armed_foe(), foe_at=(4, 6))
    engine.state.zones["zone:test:shallow"] = _sand_zone(engine, ME, ["shallow sand terrain"], [(12, 6)])
    events = foe_attacks(engine, ME)
    assert not [e for e in events if e.source_definition_id == DUNE_BANK]
    assert engine.state.actors[ME].reaction_available


def test_glass_mirage_reflection_negates_the_attack_on_a_failed_save():
    """"On a failed save, the attack ... targets a sand-glass reflection ... and automatically misses you. On a successful save,
    you gain Half Cover against the triggering effect." Its row also no longer needs the attacker within 5 feet."""
    engine = fight(bundle(MIRAGE, cl=11, dc=FAIL), foe=armed_foe(BOW), foe_at=(10, 6))
    engine.state.zones["zone:test:shallow"] = _sand_zone(engine, ME, ["shallow sand terrain"], [(3, 7)])
    hp = engine.state.actors[ME].current_hp
    events = foe_attacks(engine, ME, "Gong Jian (Bow and Arrow) attack")
    assert [e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == MIRAGE]
    assert not [e for e in events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids]
    assert engine.state.actors[ME].current_hp == hp


def test_glass_mirage_reflection_success_is_half_cover_and_needs_sand_nearby():
    engine = fight(bundle(MIRAGE, cl=11, dc=PASS), foe=armed_foe(), foe_at=(4, 6))
    engine.state.zones["zone:test:shallow"] = _sand_zone(engine, ME, ["shallow sand terrain"], [(3, 7)])
    applied = []
    engine_apply = engine._apply_condition
    engine._apply_condition = lambda actor, cid, *a, **k: (applied.append(cid), engine_apply(actor, cid, *a, **k))[1]
    foe_attacks(engine, ME)
    assert "condition:typed.sand_bank" in applied
    far = fight(bundle(MIRAGE, cl=11, dc=PASS), foe=armed_foe(), foe_at=(4, 6))
    events = foe_attacks(far, ME)
    assert not [e for e in events if e.source_definition_id == MIRAGE]


def test_court_of_ten_thousand_dunes_free_scouring_hand_once_per_turn():
    """"once on each of your turns, you may use Scouring Hand, Sand Drag, Dust Veil ... without spending an Action"."""
    engine = fight(bundle(COURT, cl=11), foe_at=(5, 6))
    use(engine, "Court of Ten Thousand Dunes")
    free = [n for n in legal(engine) if n.startswith("Scouring Hand") and n.endswith("(free)")]
    assert free
    use(engine, free[0], target=FOE)
    assert not [n for n in legal(engine) if n.startswith("Scouring Hand") and n.endswith("(free)")]
    turn(engine, FOE)
    turn(engine, ME)
    assert [n for n in legal(engine) if n.startswith("Scouring Hand") and n.endswith("(free)")]


def test_court_cost_and_once_per_rest_are_enforced():
    engine = fight(bundle(COURT, cl=11), foe_at=(5, 6))
    me = engine.state.actors[ME]
    before = dict(me.resources)
    use(engine, "Court of Ten Thousand Dunes")
    spent = {k: before[k] - v for k, v in me.resources.items() if before.get(k, v) != v}
    assert 3 in spent.values()
    turn(engine, FOE)
    turn(engine, ME)
    assert "Court of Ten Thousand Dunes" not in legal(engine)


def test_desert_drinks_the_river_stops_or_halves_healing():
    """Dry the Body: "cannot regain Hit Points until the start of your next turn ... On a success, ... healing it receives before
    the start of your next turn is halved" (already typed; the rider copies are gone)."""
    engine = fight(bundle("TAL_SAND_DESERT_DRINKS_THE_RIVER", dc=FAIL), foe_at=(6, 6))
    use(engine, "Desert Drinks the River: Dry the Body", target=FOE)
    foe = engine.state.actors[FOE]
    assert any(m.target_field == "healing_reduction" for m in foe.modifiers.values())
    assert "cannot regain Hit Points until the start of your next turn" not in mech("TAL_SAND_DESERT_DRINKS_THE_RIVER")["riders"]


def test_sand_needle_volley_reaches_up_to_three_creatures():
    """Sand Needle Volley: "Target: Up to three creatures within range"; it struck one.

    The printed Target line also requires each target to be within 10 feet of Sand Terrain, which the
    row now reads (AUTO50's sand_nearby_targets), so both foes stand in the caster's Sand Terrain here."""
    ally = bundle(SCOUR, actor_id=ALLY, cl=5)
    engine = fight(bundle("TAL_SAND_SAND_NEEDLE_VOLLEY", dc=FAIL), ally=ally, foe_at=(6, 6), ally_at=(7, 6))
    engine.state.actors[ALLY].team_id = "team:b"  # a second foe
    engine.state.zones["zone:test:shallow"] = _sand_zone(engine, ME, ["shallow sand terrain"], [(6, 6), (7, 6)])
    events = use(engine, "Sand Needle Volley", target=FOE)
    hit = {t for e in events if e.event_type == "DAMAGE_COMMITTED" for t in e.target_ids}
    assert {FOE, ALLY} <= hit


def test_sand_drag_coffin_and_prison_follow_their_printed_targets():
    """Target lines: Sand Drag "One creature standing on Sand Terrain you control"; Sand Coffin "One Buried creature in Sand
    Terrain you control"; Glass Prison "One Buried creature or one creature standing in Deep Sand Terrain you control"."""
    engine = fight(bundle(DRAG, "TAL_SAND_SAND_COFFIN", "TAL_SAND_GLASS_PRISON", cl=11), foe_at=(6, 6))
    names = legal(engine)
    assert "Sand Drag" not in names and "Sand Coffin" not in names and "Glass Prison" not in names
    engine.state.zones["zone:test:shallow"] = _sand_zone(engine, ME, ["shallow sand terrain"], [(6, 6)])
    names = legal(engine)
    assert "Sand Drag" in names and "Sand Coffin" not in names and "Glass Prison" not in names
    bury(engine, restrain=None)
    names = legal(engine)
    assert "Sand Coffin" in names and "Glass Prison" in names


def test_glass_prison_half_cover_and_cuts_when_it_attacks():
    """"While restrained this way, it has Half Cover ... and takes Piercing damage equal to your CL the first time each turn it
    makes an attack ... or attempts to escape"."""
    engine = fight(bundle("TAL_SAND_GLASS_PRISON", cl=11, dc=FAIL), foe=armed_foe(), foe_at=(4, 6))
    bury(engine, restrain=None, dc=FAIL)
    foe = engine.state.actors[FOE]
    ac = engine._ac_modifier(foe)
    use(engine, "Glass Prison", target=FOE)
    assert held(foe, "restrained")
    assert engine._ac_modifier(foe) == ac + 2
    hp = foe.current_hp
    events = foe_attacks(engine, ME)
    cuts = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert cuts and foe.current_hp < hp
    foe.action_available = True
    events = use(engine, "Fu (Short Axe) attack", target=ME)
    assert not [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]  # once each turn


def test_devouring_dune_mouth_compresses_buried_creatures_as_a_bonus_action():
    """"As a Bonus Action while the effect lasts, you may force each hostile Buried creature in the area to repeat the save. On a
    failure, it takes 3d8 Bludgeoning damage as the dune compresses." """
    engine = fight(bundle(MOUTH, dc=FAIL), foe_at=(10, 6))
    assert "Devouring Dune Mouth: compress the dune" not in legal(engine)
    use(engine, "Devouring Dune Mouth", at=(10, 6))
    foe = engine.state.actors[FOE]
    bury(engine, restrain=None, dc=FAIL)
    hp = foe.current_hp
    engine.state.actors[ME].bonus_action_available = True
    events = use(engine, "Devouring Dune Mouth: compress the dune")
    assert payloads(events, "SAVE_ROLLED") and foe.current_hp < hp


def test_gather_sand_moves_one_square_as_a_bonus_action():
    """Gather Sand: "As a Bonus Action on later turns, you may move one square of Sand Terrain created by this use up to 10
    feet" (20 with Dune-Heart Sand)."""
    engine = fight(bundle("SAND_BASE_GATHER_SAND", cl=5), foe_at=(12, 6))
    use(engine, "Gather Sand", at=(6, 6))
    (zone,) = [z for z in zones.typed_zones(engine) if z.owner_id == ME]
    turn(engine, FOE)
    turn(engine, ME)
    use(engine, "Gather Sand: move a square of sand", at=(8, 6))
    assert (zone.center.x, zone.center.y) == (8, 6) or [(c.x, c.y) for c in engine.state.zones[zone.zone_id].affected_cells] == [(8, 6)]
    far = [c for c in engine.legal_candidates() if c.display_name.startswith("Gather Sand: move") and c.destination is not None
           and engine.grid.distance_ft(engine.state.zones[zone.zone_id].center, c.destination) > 10]
    assert not far
    heart = fight(bundle("SAND_BASE_GATHER_SAND", "TAL_SAND_DUNE_HEART_SAND", cl=5), foe_at=(12, 6))
    use(heart, "Gather Sand", at=(6, 6))
    turn(heart, FOE)
    turn(heart, ME)
    use(heart, "Gather Sand: move a square of sand", at=(10, 6))
    assert not [n for n in legal(heart) if n.startswith("Gather Sand + Dune-Heart")]  # no longer moves the caster 20 feet


def test_sandstorm_body_ranged_attacks_through_it_have_disadvantage():
    """"ranged weapon attacks that pass through the area are made with Disadvantage unless the attacker is you or a creature you
    designate"."""
    ally = bundle(SCOUR, actor_id=ALLY, cl=5, kit=BOW)
    engine = fight(bundle("TAL_SAND_THOUSAND_MILE_SANDSTORM_BODY", cl=15), foe=armed_foe(BOW), ally=ally, foe_at=(14, 6), ally_at=(3, 8))
    use(engine, "Thousand-Mile Sandstorm Body")
    events = foe_attacks(engine, ALLY, "Gong Jian (Bow and Arrow) attack")
    modes = [(e.payload or {}).get("mode") for e in events if e.event_type == "ATTACK_ROLLED"]
    assert "DISADVANTAGE" in modes
    turn(engine, ALLY)
    events = use(engine, "Gong Jian (Bow and Arrow) attack", target=FOE)
    assert "DISADVANTAGE" not in [(e.payload or {}).get("mode") for e in events if e.event_type == "ATTACK_ROLLED"]


def test_sand_step_ignores_other_creatures_sand_terrain():
    """Sand Step: "You ignore Difficult Terrain created by sand, dust, gravel, or dry loose earth." """
    engine = fight(bundle("TAL_SAND_SAND_STEP", cl=5), foe_at=(12, 6))
    engine.state.zones["zone:test:foe"] = _sand_zone(engine, FOE, ["shallow sand terrain"], [(4, 6), (5, 6)])
    assert not ({(4, 6), (5, 6)} & zones.difficult_cells(engine, engine.state.actors[ME]))
    plain = fight(bundle(SCOUR, cl=5), foe_at=(12, 6))
    plain.state.zones["zone:test:foe"] = _sand_zone(plain, FOE, ["shallow sand terrain"], [(4, 6), (5, 6)])
    assert {(4, 6), (5, 6)} <= zones.difficult_cells(plain, plain.state.actors[ME])


# ------------------------------------------------------------------------------------------------ Sand: lines already enforced
def test_scouring_hand_damage_scales_with_cl():
    for cl, count in ((5, 2), (11, 3), (17, 4)):
        engine = fight(bundle(SCOUR, cl=cl, dc=FAIL), foe_at=(6, 6))
        events = use(engine, "Scouring Hand: Reduce Speed", target=FOE)
        rolled = [e.payload for e in events if e.event_type == "DAMAGE_ROLLED"]
        assert rolled and any(str(count) + "d8" in str(p) or p.get("dice", {}).get("count") == count for p in rolled), rolled


def test_abrading_ward_scours_once_as_the_creature_starts_its_turn():
    engine = fight(bundle("TAL_SAND_ABRADING_WARD", cl=5), foe_at=(6, 6))
    engine.state.zones["zone:test:shallow"] = _sand_zone(engine, ME, ["shallow sand terrain"], [(6, 6)])
    start = len(engine.events)
    turn(engine, FOE)
    hits = [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == "TAL_SAND_ABRADING_WARD"]
    assert len(hits) == 1


def test_sand_coffin_and_drag_saves_are_the_targets_choice_and_coffin_silences():
    coffin, drag = mech("TAL_SAND_SAND_COFFIN")["effects"][0], mech(DRAG)["effects"][0]
    assert coffin["ability"] == "str_or_con" and drag["ability"] == "str_or_dex"
    assert any(row.get("condition") == "silenced" for row in coffin["on_fail"])
    engine = fight(bundle("TAL_SAND_SAND_COFFIN", cl=5, dc=FAIL), foe_at=(6, 6))
    engine.state.zones["zone:test:shallow"] = _sand_zone(engine, ME, ["shallow sand terrain"], [(6, 6)])
    bury(engine, restrain=None)
    use(engine, "Sand Coffin", target=FOE)
    assert held(engine.state.actors[FOE], "silenced")


def test_sand_drag_forced_movement_provokes_no_opportunity_attack_and_costs_nothing():
    ally = bundle(SCOUR, actor_id=ALLY, cl=5, kit=AXE)
    engine = fight(bundle(DRAG, cl=5, dc=FAIL), ally=ally, foe_at=(6, 6), ally_at=(6, 7))
    engine.state.actors[ALLY].team_id = "team:b"
    engine.state.zones["zone:test:shallow"] = _sand_zone(engine, ME, ["shallow sand terrain"], CELLS)
    me = engine.state.actors[ME]
    before = dict(me.resources)
    events = use(engine, "Sand Drag", target=FOE)
    assert me.resources == before
    assert not [e for e in events if e.event_type == "ATTACK_ROLLED"]


def test_dune_slide_distance_scales_with_cl():
    for cl, feet in ((1, 10), (5, 15), (11, 20), (17, 30)):
        engine = fight(bundle("TAL_SAND_DUNE_SLIDE", cl=cl), foe_at=(12, 6))
        me = engine.state.actors[ME]
        engine.state.zones["zone:test:shallow"] = _sand_zone(engine, ME, ["shallow sand terrain"], [(3, 6)])
        before = me.movement_remaining_ft
        use(engine, "Dune Slide")
        assert me.movement_remaining_ft - before == feet


def test_sandstorm_body_start_of_turn_save_is_already_typed():
    rows = mech("TAL_SAND_THOUSAND_MILE_SANDSTORM_BODY")["effects"][0]["triggers"][0]
    assert set(rows["on"]) == {"enter", "start"} and rows["who"] == "hostile"


def move(engine, actor_id, to):
    rows = [c for c in engine.legal_candidates() if c.destination is not None and (c.destination.x, c.destination.y) == tuple(to)
            and c.display_name.startswith("Move")]
    assert rows, f"no move to {to}"
    c = rows[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"mv-{before}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                       state_version=c.state_version, actor_id=actor_id, target_ids=(), destination=c.destination))
    return engine.events[before:]


def test_glass_desert_judgment_leaves_difficult_glass_that_cuts_once_per_turn():
    """"The area then becomes Glass Terrain for 1 minute. Glass Terrain is Difficult Terrain. A creature that moves more than 5
    feet through Glass Terrain on a turn takes Piercing damage equal to your CL. A creature can take this damage only once per
    turn." (casting does not deal it)."""
    engine = fight(bundle("TAL_SAND_GLASS_DESERT_JUDGMENT", cl=15, dc=PASS), foe_at=(10, 6))
    events = use(engine, "Glass Desert Judgment", at=(10, 6))
    (zone,) = [z for z in zones.typed_zones(engine) if z.owner_id == ME]
    foe = engine.state.actors[FOE]
    assert (10, 6) in zones.difficult_cells(engine, foe)
    cast_damage = sum(int((e.payload or {}).get("hp_damage") or 0) for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids)
    turn(engine, FOE)
    glass = lambda events: [int((e.payload or {}).get("hp_damage") or 0) for e in events
                            if e.event_type == "DAMAGE_COMMITTED" and "TAL_SAND_GLASS_DESERT_JUDGMENT" in e.source_definition_id]
    assert glass(move(engine, FOE, (10, 8))) == [15]  # CL Piercing
    assert glass(move(engine, FOE, (10, 9))) == []  # once per turn
    assert cast_damage > 0  # the 6d8 on casting is the save's own damage, halved on the success


def test_dune_wall_gives_three_quarters_cover_and_costs_four_feet_a_foot():
    engine = fight(bundle("TAL_SAND_DUNE_WALL", cl=5), foe=armed_foe(BOW), foe_at=(12, 6))
    use(engine, "Dune Wall", at=(7, 6))
    (wall,) = [z for z in zones.typed_zones(engine) if z.owner_id == ME]
    cells = {(c.x, c.y) for c in wall.affected_cells}
    assert (7, 6) in cells
    events = foe_attacks(engine, ME, "Gong Jian (Bow and Arrow) attack")
    covers = [(e.payload or {}).get("cover_bonus") for e in events if e.event_type == "ATTACK_ROLLED"]
    assert covers and covers[0] == 5
    assert engine.grid.base_movement_cost.get((7, 6)) == 4  # "must spend 4 feet of movement for every 1 foot moved"


def test_sand_shell_scours_the_first_melee_hitter_each_round_while_its_temporary_hp_last():
    """Sand Shell: "While any of these Temporary HP remain, the first creature that hits you with a melee attack on each round takes
    Slashing damage equal to your Proficiency Bonus. The shell ends early if you ... lose all Temporary HP from the shell." """
    engine = fight(bundle("TAL_SAND_SAND_SHELL", cl=5), foe=armed_foe(), foe_at=(4, 6))
    use(engine, "Sand Shell")
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    me.temporary_hp = 60  # enough to outlast both hits
    me.armor_class = -50
    hp = foe.current_hp
    events = foe_attacks(engine, ME)
    scour = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert scour and foe.current_hp == hp - int((scour[0].payload or {}).get("hp_damage") or 0) and foe.current_hp < hp
    foe.action_available = True
    events = use(engine, "Fu (Short Axe) attack", target=ME)
    assert not [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]  # once each round
    me.temporary_hp = 0
    turn(engine, ME)
    turn(engine, FOE)
    events = use(engine, "Fu (Short Axe) attack", target=ME)
    assert not [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]  # no Temporary HP: the shell is gone


def test_sand_clone_decoy_steps_away_on_a_miss_by_five():
    """Sand Clone Decoy: "If the attack misses you by 5 or more, you may move up to 15 feet without provoking Opportunity Attacks,
    and the decoy collapses into Storming Sand Terrain in one 5-foot square." """
    engine = fight(bundle("TAL_SAND_SAND_CLONE_DECOY", cl=11), foe=armed_foe(), foe_at=(4, 6))
    use(engine, "Sand Clone Decoy")
    me = engine.state.actors[ME]
    me.armor_class = 60
    start = (me.position.x, me.position.y)
    foe_attacks(engine, ME)
    assert (me.position.x, me.position.y) != start
    storm = [z for z in zones.typed_zones(engine) if z.owner_id == ME and "storming sand terrain" in z.trigger_profile.get("terrain", [])]
    assert storm and [(c.x, c.y) for c in storm[0].affected_cells] == [start]
    assert not [c for c in me.conditions.values() if c.condition_id.endswith("sand_clone_decoy")]  # the first miss spent it


def test_sand_sovereign_incarnation_steps_after_a_melee_miss():
    engine = fight(bundle("TAL_SAND_SAND_SOVEREIGN_INCARNATION", cl=15), foe=armed_foe(), foe_at=(4, 6))
    use(engine, "Sand-Sovereign Incarnation")
    me = engine.state.actors[ME]
    me.armor_class = 60
    start = (me.position.x, me.position.y)
    foe_attacks(engine, ME)
    assert (me.position.x, me.position.y) != start and engine.grid.distance_ft(me.position, Position(x=start[0], y=start[1])) <= 10
    assert [z for z in zones.typed_zones(engine) if z.owner_id == ME and "shallow sand terrain" in z.trigger_profile.get("terrain", [])]
    turn(engine, ME)
    assert [n for n in legal(engine) if n.startswith("Gather Sand (free)")]


def test_glass_edge_scripture_grains_cut_a_buried_creature_when_it_moves():
    """Glass Edge Scripture: "when you deal Scouring damage to a creature that is Buried, you may cause glassy grains to cling to it.
    Until the start of your next turn, the first time the creature moves 5 feet or more, it takes Piercing damage equal to your
    Proficiency Bonus + your key ability modifier." """
    engine = fight(bundle(SCOUR, "TAL_SAND_GLASS_EDGE_SCRIPTURE", cl=5, dc=FAIL), foe_at=(6, 6))
    bury(engine, restrain=None, dc=60)
    use(engine, "Scouring Hand: Reduce Speed", target=FOE)
    foe = engine.state.actors[FOE]
    assert held(foe, "sand_glass_grains")
    turn(engine, FOE)
    hp = foe.current_hp
    moves = [c for c in engine.legal_candidates() if c.display_name.startswith("Move") and c.destination is not None]
    events = move(engine, FOE, (moves[0].destination.x, moves[0].destination.y))
    cut = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id != "system:battlefield.qi_hazard" and FOE in e.target_ids]
    assert cut and not held(foe, "sand_glass_grains")


def test_erode_the_path_of_return_makes_a_teleport_fail():
    """Erode the Path of Return: "A creature you can perceive teleports ... On a failed save ... the movement fails and the triggering
    resource is spent"."""
    foe = bundle("TAL_SAND_SAND_BURROW_STEP", actor_id=FOE, cl=5)
    engine = fight(bundle("TAL_SAND_ERODE_THE_PATH_OF_RETURN", cl=15, dc=FAIL), foe=foe, foe_at=(8, 6))
    turn(engine, FOE)
    f = engine.state.actors[FOE]
    start = (f.position.x, f.position.y)
    steps = [c for c in engine.legal_candidates() if c.display_name.startswith("Sand Burrow Step") and c.destination is not None]
    assert steps
    c = steps[-1]
    engine.execute_intent(ActionIntent(intent_id="tp", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                       actor_id=FOE, target_ids=c.target_ids or (), destination=c.destination))
    assert (f.position.x, f.position.y) == start
    assert not engine.state.actors[ME].reaction_available


def test_erode_the_path_of_return_success_keeps_sand_clinging():
    foe = bundle("TAL_SAND_SAND_BURROW_STEP", actor_id=FOE, cl=5)
    engine = fight(bundle("TAL_SAND_ERODE_THE_PATH_OF_RETURN", cl=15, dc=PASS), foe=foe, foe_at=(8, 6))
    turn(engine, FOE)
    f = engine.state.actors[FOE]
    start = (f.position.x, f.position.y)
    c = [c for c in engine.legal_candidates() if c.display_name.startswith("Sand Burrow Step") and c.destination is not None][-1]
    engine.execute_intent(ActionIntent(intent_id="tp", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                       actor_id=FOE, target_ids=c.target_ids or (), destination=c.destination))
    assert (f.position.x, f.position.y) != start and held(f, "sand_clinging")


MOUNTAIN = "TAL_SAND_THE_MOUNTAIN_REMEMBERS_IT_IS_DUST"


def _mountain_name(engine, mode):
    return next(n.split(" at ")[0] for n in legal(engine) if n.startswith("The Mountain Remembers It Is Dust: " + mode))


def test_mountain_bury_the_line_buries_restrains_and_blinds_until_the_save_ends_it():
    """Bury the Line: "On a failed save, a creature is Buried and Restrained for 1 minute. While restrained this way, it is also Blinded
    by sand ... It may repeat the saving throw at the end of each of its turns, ending the effects on itself on a success. On a
    successful save, it is Buried until the start of your next turn and its Speed becomes 0 until the start of your next turn." """
    engine = fight(bundle(MOUNTAIN, cl=17, dc=FAIL), foe_at=(8, 6))
    name = _mountain_name(engine, "Bury the Line")
    use(engine, name, target=FOE) if any(c.display_name == name and FOE in (c.target_ids or ()) for c in engine.legal_candidates()) else use(engine, name, at=(8, 6))
    foe = engine.state.actors[FOE]
    (buried,) = held(foe, "buried")
    assert buried.data.get("repeat_save", {}).get("ability") == "STR"
    for name_ in ("restrained", "blinded"):
        (row,) = held(foe, name_)
        assert row.data["parent_hold"] in foe.conditions
    engine.state.actors[FOE].conditions.pop(next(k for k, c in foe.conditions.items() if c.condition_id == "condition:typed.buried"))
    from combat.ext import linked_holds

    linked_holds.reconcile(engine)
    assert not held(foe, "restrained") and not held(foe, "blinded")


def test_mountain_erode_the_giant_stops_healing():
    engine = fight(bundle(MOUNTAIN, cl=17, dc=FAIL), foe_at=(8, 6))
    engine.state.actors[FOE].maximum_hp = engine.state.actors[FOE].current_hp = 500
    name = _mountain_name(engine, "Erode the Giant")
    use(engine, name, target=FOE)
    assert any(m.target_field == "healing_reduction" for m in engine.state.actors[FOE].modifiers.values())


def test_erosion_scripture_armor_abrasion_stops_at_ten_plus_dexterity():
    """Armor Abrasion: "its AC is reduced by 1 until the end of your next turn. This cannot reduce AC below 10 + Dexterity modifier"."""
    engine = fight(bundle("TAL_SAND_EROSION_SCRIPTURE", cl=11, dc=FAIL), foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    base = foe.armor_class + engine._ac_modifier(foe)
    use(engine, "Erosion Scripture: Armor Abrasion", target=FOE)
    assert foe.armor_class + engine._ac_modifier(foe) == base - 1
    low = fight(bundle("TAL_SAND_EROSION_SCRIPTURE", cl=11, dc=FAIL), foe_at=(6, 6))
    foe = low.state.actors[FOE]
    from combat.ability_checks import ability_modifier

    foe.armor_class = 10 + ability_modifier(foe, "DEX") - low._ac_modifier(foe)
    use(low, "Erosion Scripture: Armor Abrasion", target=FOE)
    assert foe.armor_class + low._ac_modifier(foe) == 10 + ability_modifier(foe, "DEX")


# ================================================================================================= VOID
VOID = "TAL_VOID_"


def void_foe(*mids, cl=10, **kw):
    return bundle(*(mids or ("TAL_VOID_EMPTY_STEP",)), actor_id=FOE, cl=cl, **kw)


def foe_uses(engine, name, *, target=None, at=None):
    turn(engine, FOE)
    return use(engine, name, target=target, at=at, actor_id=FOE)


def teleport(engine, actor_id, name, to):
    rows = [c for c in engine.legal_candidates() if c.display_name.startswith(name) and c.destination is not None
            and (c.destination.x, c.destination.y) == tuple(to)]
    assert rows, f"{name} to {to} is not legal"
    c = rows[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"tp-{before}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                       state_version=c.state_version, actor_id=actor_id, target_ids=c.target_ids or (), destination=c.destination))
    return engine.events[before:]


def test_empty_palm_scripture_is_a_usable_strike_that_hollows():
    """Empty Palm Scripture: "Make one unarmed strike. Hit: Deal the attack's normal damage and the target makes a Constitution saving
    throw. Failed Save: The target becomes Hollowed until the start of your next turn. Successful Save: The target cannot gain
    Temporary HP until the start of your next turn." It compiled to nothing (a "special" economy)."""
    engine = fight(bundle(VOID + "EMPTY_PALM_SCRIPTURE", "TAL_IRON_FIST_IRON_FIST_TRAINING", cl=10, dc=FAIL), foe_at=(4, 6))
    engine.state.actors[FOE].armor_class = -50
    use(engine, "Empty Palm Scripture", target=FOE)
    (hollow,) = held(engine.state.actors[FOE], "hollowed")
    assert hollow.expires_on == "START_OF_SOURCE_NEXT_TURN"
    saved = fight(bundle(VOID + "EMPTY_PALM_SCRIPTURE", "TAL_IRON_FIST_IRON_FIST_TRAINING", cl=10, dc=PASS), foe_at=(4, 6))
    saved.state.actors[FOE].armor_class = -50
    use(saved, "Empty Palm Scripture", target=FOE)
    assert held(saved.state.actors[FOE], "no_temp_hp") and not held(saved.state.actors[FOE], "hollowed")


def test_void_lines_already_typed_hold():
    """Rider copies removed after checking the typing already does them: Hollow Touch, Heaven-Emptying Lance, Void Meridian Seal,
    Void Field (to the start of *its* next turn), Void Prison's success."""
    lance = mech(VOID + "HEAVEN_EMPTYING_LANCE")["effects"][0]["on_hit"][1]
    assert lance["on_fail"][0]["repeat_save"]["ability"] == "CON" and lance["on_success"][0]["condition"] == "hollowed"
    seal = fight(bundle(VOID + "VOID_MERIDIAN_SEAL", cl=10, dc=FAIL), foe_at=(6, 6))
    use(seal, "Void Meridian Seal", target=FOE)
    (hollow,) = held(seal.state.actors[FOE], "hollowed")
    assert hollow.expires_on == "CONCENTRATION_END" and hollow.data["repeat_save"]["ability"] == "CON"
    touch = fight(bundle(VOID + "HOLLOW_TOUCH", cl=10, dc=PASS), foe_at=(6, 6))
    use(touch, "Hollow Touch", target=FOE)
    assert held(touch.state.actors[FOE], "no_temp_hp")[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    field = fight(bundle(VOID + "VOID_FIELD", cl=10, dc=FAIL), foe_at=(10, 6))
    use(field, "Void Field", at=(10, 6))
    turn(field, FOE)
    (hollow,) = held(field.state.actors[FOE], "hollowed")
    assert hollow.expires_on not in ("START_OF_SOURCE_NEXT_TURN",)  # the start of the Hollowed creature's own next turn


def test_absolute_quiet_gap_locks_teleports_out_of_it():
    """Absolute Quiet Gap: "teleportation into or out of the area requires a successful Cultivation Check against your Cultivation Save DC"."""
    engine = fight(bundle(VOID + "ABSOLUTE_QUIET_GAP", cl=15, dc=FAIL), foe=void_foe(), foe_at=(10, 6))
    use(engine, "Absolute Quiet Gap", at=(10, 6))
    turn(engine, FOE)
    f = engine.state.actors[FOE]
    events = teleport(engine, FOE, "Empty Step", (13, 6))
    assert (f.position.x, f.position.y) == (10, 6)
    assert [p for p in payloads(events, "CHECK_ROLLED") if p["dc"] == FAIL and not p["success"]]


def test_placed_river_does_not_disable_the_void_teleport_locks():
    """A placed line (Blackglass River) on the map must not stop Absolute Quiet Gap from locking a teleport."""
    engine = fight(bundle(VOID + "ABSOLUTE_QUIET_GAP", "TAL_MAGMA_BLACKGLASS_RIVER", cl=15, dc=FAIL), foe=void_foe(), foe_at=(10, 6))
    use(engine, "Blackglass River", at=(7, 8))
    engine.end_turn()
    turn(engine, ME)
    use(engine, "Absolute Quiet Gap", at=(10, 6))
    turn(engine, FOE)
    f = engine.state.actors[FOE]
    events = teleport(engine, FOE, "Empty Step", (13, 6))
    assert (f.position.x, f.position.y) == (10, 6)
    assert [p for p in payloads(events, "CHECK_ROLLED") if p["dc"] == FAIL and not p["success"]]


def test_placed_river_gap_and_teleport_survive_a_table_commit_and_reload(tmp_path, monkeypatch):
    """The same lock through CombatService, a table commit and a cold reload: a placed line
    (Blackglass River) on the map must not stop Absolute Quiet Gap from requiring the Cultivation
    Check when the foe teleports out of the Gap."""
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.hunt12_support import fight as service_fight, reload as service_reload
    from tests.hunt12_support import FOE as SERVICE_FOE
    from tests.r10_fixup_support import fixed_dice
    from tests.test_lock2_persistence import act as end_turn

    combat, table, mid = service_fight(
        tmp_path, [VOID + "ABSOLUTE_QUIET_GAP", "TAL_MAGMA_BLACKGLASS_RIVER"],
        cl=15, dc=FAIL, foe_mids=["TAL_VOID_EMPTY_STEP"])
    fixed_dice(monkeypatch, [1] * 80)  # every die a natural 1: the Cultivation Check fails

    def candidates(name, where=None):
        engine = combat._load_session(mid).engine
        return [c for c in engine.legal_candidates() if c.display_name.startswith(name)
                and c.destination is not None
                and (where is None or (c.destination.x, c.destination.y) == where)]

    def cast(candidate):
        state = table.state(mid)
        menu = state["menu"]
        return table.act(mid, candidate.candidate_id, menu["decision_id"], menu["state_version"],
                         state["last_sequence"], [])

    # the placed line goes on the map first: its scalar stamp is what crashed the gate
    assert cast(candidates("Blackglass River")[0])["status"] == "COMMITTED"
    # the river spent the caster's action; the Gap waits for the caster's next turn
    assert end_turn(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != "actor:factory.fix12":
        assert end_turn(table, mid, "end")["status"] == "COMMITTED"
    # the Gap covers the foe's own square, so the foe's Empty Step leaves it through the gate
    foe_at = (lambda p: (p.x, p.y))(combat._load_session(mid).engine.state.actors[SERVICE_FOE].position)
    assert cast(candidates("Absolute Quiet Gap", foe_at)[0])["status"] == "COMMITTED"

    # a table commit and a cold reload keep both zones: the river's scalar stamp and the Gap
    engine = service_reload(tmp_path, mid)
    river = next(z for z in engine.state.zones.values() if z.trigger_profile.get("name") == "Blackglass River")
    assert river.trigger_profile.get("placed") == 1
    assert any(z.trigger_profile.get("name") == "Absolute Quiet Gap" for z in engine.state.zones.values())
    combat, table = CombatService(ROOT, tmp_path), TabletopService(combat, tmp_path)

    # the foe's Empty Step out of the Gap: the check fails, the teleport fails, the foe stays
    assert end_turn(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != SERVICE_FOE:
        assert end_turn(table, mid, "end")["status"] == "COMMITTED"
    step = next(c for c in combat._load_session(mid).engine.legal_candidates()
                if c.display_name.startswith("Empty Step") and c.destination is not None
                and (c.destination.x, c.destination.y) != foe_at)
    answers = []
    result = None
    for _ in range(12):
        state = table.state(mid)
        menu = state["menu"]
        result = table.act(mid, step.candidate_id, menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            break
        prompt = result["reaction"]
        context = prompt["context"]
        if context["reaction_source_id"] == "choice:needle.teleport_destination":
            cells = [o["id"] for o in prompt["choice"]["options"]
                     if o["id"].startswith("cell:") and o["id"] != f"cell:{foe_at[0]},{foe_at[1]}"]
            assert cells, prompt
            answers.append({**context, "selection": "USE", "option_ids": [cells[0]]})
        else:
            answers.append({**context, "selection": "DECLINE"})
    assert result["status"] == "COMMITTED", result

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    assert (engine.state.actors[SERVICE_FOE].position.x, engine.state.actors[SERVICE_FOE].position.y) == foe_at
    assert [e.payload for e in engine.events if e.event_type == "CHECK_ROLLED"
            and e.payload.get("dc") == FAIL and not e.payload.get("success")]
    assert not [e for e in engine.events if e.event_type == "GM_RIDER"
                and "void_teleport_locks" in (e.payload or {}).get("rider", "")]
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_void_prison_holds_the_target_in_place_and_locks_its_teleport():
    engine = fight(bundle(VOID + "VOID_PRISON", cl=10, dc=FAIL), foe=void_foe(), foe_at=(8, 6))
    use(engine, "Void Prison", target=FOE)
    f = engine.state.actors[FOE]
    (cage,) = held(f, "void_prison")
    assert cage.data["dc"] == FAIL and engine._effective_speed(f) == 0
    turn(engine, FOE)
    teleport(engine, FOE, "Empty Step", (10, 6))
    assert (f.position.x, f.position.y) == (8, 6)


def test_still_talisman_stops_the_first_hostile_teleport_then_ends():
    engine = fight(bundle(VOID + "STILL_TALISMAN", cl=5, dc=FAIL), foe=void_foe(), foe_at=(8, 6))
    use(engine, "Still Talisman", at=(4, 6))
    assert [z for z in zones.typed_zones(engine) if (z.trigger_profile.get("still_talisman") or {}).get("kind") == "void_still_talisman"]
    turn(engine, FOE)
    f = engine.state.actors[FOE]
    teleport(engine, FOE, "Empty Step", (4, 6))
    assert (f.position.x, f.position.y) == (8, 6)
    assert not [z for z in zones.typed_zones(engine) if (z.trigger_profile.get("still_talisman") or {}).get("kind") == "void_still_talisman"]


def test_void_ward_adds_its_proficiency_bonus_only_for_qualifying_damage():
    """Void Ward: "If the triggering effect is a Cultivation Attack, area talent, ... Force damage, Necrotic damage, Psychic damage, or an
    effect from a creature that is Hollowed, add your Proficiency Bonus to the reduction" (the typing added it to every reduction)."""
    from combat import typed_reactions
    from combat.ext import void_riders

    engine = fight(bundle(VOID + "VOID_WARD", cl=10), foe_at=(4, 6))
    (row,) = [r for r in typed_reactions._rows(engine, ME, "generic") if r["feature_id"] == VOID + "VOID_WARD"]
    pb_row = next(e for e in row["effects"] if e.get("formula") == "pb" and not e.get("dice"))
    engine._typed_pending_damage_type, engine._typed_damage_packet = "SLASHING", {"kind": "weapon"}
    assert void_riders.ward_bonus(engine, engine.state.actors[ME], row, pb_row) == 0
    engine._typed_pending_damage_type = "FORCE"
    assert void_riders.ward_bonus(engine, engine.state.actors[ME], row, pb_row) is None
    engine._typed_pending_damage_type, engine._typed_damage_packet = "SLASHING", {"kind": "cultivation_melee"}
    assert void_riders.ward_bonus(engine, engine.state.actors[ME], row, pb_row) is None


def test_cost_denying_needle_keeps_the_reviewed_temporary_recovery_instruction():
    engine = fight(bundle(VOID + "VOID_NEEDLE", VOID + "COST_DENYING_NEEDLE", cl=5), foe_at=(6, 6))
    engine.state.actors[FOE].armor_class = -50
    use(engine, "Void Needle: Cost Lock", target=FOE)
    assert held(engine.state.actors[FOE], "void_cost_lock")
    assert not held(engine.state.actors[FOE], "no_cp_regain")
    # Printed ban concerns ordinary temporary effects, not permanent recovery.
    # Lock7's reviewed fallback cannot distinguish those sources automatically.
    notes = [str(e.payload) for e in engine.events if 'Cost-Denying Needle' in str(e.payload)]
    assert any('temporary' in text and 'permanent' in text and
               'Recovery is not blocked automatically' in text for text in notes)


def test_void_shell_and_no_purchase_body_answer_melee_hits():
    """Void Shell: "once per turn, when a creature hits you with a melee Cultivation Attack, it takes Force damage equal to your
    Proficiency Bonus"; No-Purchase Body: "when a creature hits you with a melee attack, you may apply one Void Pressure ... once per turn"."""
    engine = fight(bundle(VOID + "VOID_SHELL", VOID + "NO_PURCHASE_BODY", cl=10), foe=armed_foe(), foe_at=(4, 6))
    use(engine, "Void Shell")
    me, f = engine.state.actors[ME], engine.state.actors[FOE]
    me.armor_class = -50
    foe_attacks(engine, ME)
    # Lock7's reviewed automatic preference is Cost Lock, now a real third option.
    assert held(f, "void_cost_lock")  # a weapon hit applies Pressure, not Void Shell damage


def test_void_shell_scours_a_melee_cultivation_attacker():
    engine = fight(bundle(VOID + "VOID_SHELL", cl=10), foe=bundle("TAL_DEATH_WITHERING_HAND", actor_id=FOE, cl=10), foe_at=(4, 6))
    use(engine, "Void Shell")
    me, f = engine.state.actors[ME], engine.state.actors[FOE]
    me.armor_class = -50
    hp = f.current_hp
    turn(engine, FOE)
    name = next(n.split(" at ")[0] for n in legal(engine) if n.startswith("Withering Hand"))
    use(engine, name, target=ME, actor_id=FOE)
    assert f.current_hp < hp


def test_void_sovereign_needle_hollows_and_a_hollowed_miss_lets_it_step():
    engine = fight(bundle(VOID + "VOID_SOVEREIGN_INCARNATION", VOID + "VOID_NEEDLE", VOID + "EMPTY_STEP", cl=15), foe=armed_foe(), foe_at=(4, 6))
    use(engine, "Void-Sovereign Incarnation")
    engine.state.actors[ME].bonus_action_available = True  # the Incarnation took this turn's Bonus Action; the copy keeps that economy
    assert any(n.startswith("Empty Step (no cost)") for n in legal(engine))
    engine.state.actors[FOE].armor_class = -50
    use(engine, "Void Needle: Empty Vitality", target=FOE)
    assert held(engine.state.actors[FOE], "hollowed")
    me = engine.state.actors[ME]
    me.armor_class = 60
    start = (me.position.x, me.position.y)
    foe_attacks(engine, ME)
    assert (me.position.x, me.position.y) != start


def test_hollow_path_step_teleports_on_a_miss_and_costs_one_against_a_hollowed_attacker():
    engine = fight(bundle(VOID + "HOLLOW_PATH_STEP", VOID + "EMPTY_STEP", cl=10), foe=armed_foe(), foe_at=(4, 6))
    me = engine.state.actors[ME]
    me.armor_class = 60
    start, qi = (me.position.x, me.position.y), me.resources["resource:core.qi"]
    foe_attacks(engine, ME)
    assert (me.position.x, me.position.y) != start and me.resources["resource:core.qi"] == qi - 2
    again = fight(bundle(VOID + "HOLLOW_PATH_STEP", VOID + "EMPTY_STEP", cl=10), foe=armed_foe(), foe_at=(4, 6))
    me = again.state.actors[ME]
    me.armor_class = 60
    again._apply_condition(again.state.actors[FOE], "condition:typed.hollowed", "test", ME, expires_on="UNTIL_REMOVED")
    qi = me.resources["resource:core.qi"]
    foe_attacks(again, ME)
    assert me.resources["resource:core.qi"] == qi - 1


def test_void_walking_guard_teleports_after_void_ward():
    ally = bundle(SCOUR, actor_id=ALLY, cl=5)
    engine = fight(bundle(VOID + "VOID_WARD", VOID + "VOID_WALKING_GUARD", VOID + "EMPTY_STEP", cl=10), foe=armed_foe(), ally=ally,
                   foe_at=(6, 6), ally_at=(5, 6))
    engine.state.actors[ALLY].armor_class = -50
    me = engine.state.actors[ME]
    start = (me.position.x, me.position.y)
    events = foe_attacks(engine, ALLY)
    assert [e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == VOID + "VOID_WARD"]
    assert (me.position.x, me.position.y) != start


def test_return_the_technique_to_nothing_contests_the_technique():
    """"Make a Cultivation Check contested by the triggering creature's Cultivation Check. You Succeed: The technique fails to take hold.
    Its resource cost is spent. ... You Fail: ... the triggering creature becomes Hollowed until the start of your next turn." (the typing
    Hollowed the caster every time)."""
    ally = bundle(SCOUR, actor_id=ALLY, cl=5)
    engine = fight(bundle(VOID + "RETURN_THE_TECHNIQUE_TO_NOTHING", cl=17), foe=bundle(VOID + "HOLLOW_TOUCH", actor_id=FOE, cl=10), ally=ally,
                   foe_at=(8, 6), ally_at=(6, 6))
    events = foe_uses(engine, "Hollow Touch", target=ALLY)
    contest = [p for p in payloads(events, "CHECK_ROLLED") if p.get("check") == "Cultivation Check contest"]
    assert contest
    f = engine.state.actors[FOE]
    if contest[0]["success"]:
        assert not held(engine.state.actors[ALLY], "hollowed") and not held(engine.state.actors[ALLY], "no_temp_hp") and not held(f, "hollowed")
    else:
        assert held(f, "hollowed")


def test_ten_thousand_empty_needles_strikes_several_creatures_with_a_pressure_each():
    ally = bundle(SCOUR, actor_id=ALLY, cl=5)
    engine = fight(bundle(VOID + "TEN_THOUSAND_EMPTY_NEEDLES", cl=15), ally=ally, foe_at=(6, 6), ally_at=(7, 7))
    engine.state.actors[ALLY].team_id = "team:b"
    for who in (FOE, ALLY):
        engine.state.actors[who].armor_class = -50
    events = use(engine, "Ten-Thousand Empty Needles", target=FOE)
    hit = {t for e in events if e.event_type == "DAMAGE_COMMITTED" for t in e.target_ids}
    assert {FOE, ALLY} <= hit
    for who in (FOE, ALLY):
        assert held(engine.state.actors[who], "void_cost_lock")
    assert not any(e.event_type == "PLUGIN_EXCEPTION" for e in events)


def _buff(engine, who, field="armor_class", value=2, expires="END_OF_HOLDER_NEXT_TURN"):
    engine._add_modifier(engine.state.actors[who], "test:buff", field, "ADD", value, "SELF", expires_on=expires)
    return next(k for k, m in engine.state.actors[who].modifiers.items() if m.source_definition_id == "test:buff")


def test_nullification_seal_suppresses_a_benefit_while_it_lasts():
    """Nullification Seal: "Failed Save: Choose one active ordinary temporary benefit affecting the target. Suppress it while this talent
    lasts ... Successful Save: Suppress the selected benefit until the start of your next turn." """
    engine = fight(bundle(VOID + "NULLIFICATION_SEAL", cl=10, dc=FAIL), foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    key = _buff(engine, FOE)
    use(engine, "Nullification Seal", target=FOE)
    assert key not in foe.modifiers and held(foe, "benefit_suppressed")
    engine._end_concentration(engine.state.actors[ME], "TEST")
    assert key in foe.modifiers and not held(foe, "benefit_suppressed")
    saved = fight(bundle(VOID + "NULLIFICATION_SEAL", cl=10, dc=PASS), foe_at=(6, 6))
    key = _buff(saved, FOE)
    use(saved, "Nullification Seal", target=FOE)
    assert key not in saved.state.actors[FOE].modifiers
    turn(saved, FOE)
    turn(saved, ME)
    assert not held(saved.state.actors[FOE], "benefit_suppressed")


def test_nullifying_strike_can_suppress_a_resistance():
    engine = fight(bundle(VOID + "VOID_NEEDLE", VOID + "NULLIFYING_STRIKE", cl=10, dc=FAIL), foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    foe.armor_class = -50
    key = _buff(engine, FOE, "damage_resistance", "FORCE")
    # Configure this attack's rider through its free settings, rather than
    # confusing a self-targeting option button with the attack it configures.
    parent = next(a for a in engine.action_catalog.values()
                  if a.owner_id == ME and a.display_name == "Void Needle: Empty Vitality")
    def setting(field, value):
        action = next(a for a in engine.action_catalog.values()
                      if (a.parameters.get("attack_modifier_setting") or {}) == {
                          "family": parent.source_definition_id, "modifier": VOID + "NULLIFYING_STRIKE",
                          "name": "Nullifying Strike", "field": field, "value": value})
        choice = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id)
        engine.execute_intent(ActionIntent(intent_id=f"c4-nullifying-{field}", decision_id=choice.decision_id,
                                           candidate_id=choice.candidate_id, state_version=choice.state_version,
                                           actor_id=ME, target_ids=choice.target_ids))
    setting("on", "toggle")
    setting("option", "3")
    setting("damage", "force")
    setting("payment", "0")
    before = engine.state.actors[ME].resources["resource:core.qi"]
    use(engine, parent.display_name, target=FOE)
    assert engine.state.actors[ME].resources["resource:core.qi"] == before - 2
    assert key not in foe.modifiers and held(foe, "benefit_suppressed")


def test_return_to_zero_undoes_a_benefit_a_foe_gives_itself():
    """Return to Zero: "A creature within 60 feet gains or activates an ordinary temporary benefit ... Failed Save: The chosen benefit does
    not take effect." (no reaction row existed: its trigger was unsupported)."""
    engine = fight(bundle(VOID + "RETURN_TO_ZERO", cl=10, dc=FAIL), foe=bundle(VOID + "VOID_SHELL", actor_id=FOE, cl=10), foe_at=(6, 6))
    events = foe_uses(engine, "Void Shell")
    foe = engine.state.actors[FOE]
    assert [e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == VOID + "RETURN_TO_ZERO"]
    shell_rows = [m for m in foe.modifiers.values() if "VOID_SHELL" in m.source_definition_id]
    assert len(shell_rows) < 3  # +1 AC, Force and Necrotic Resistance: one of them no longer took effect
    assert not engine.state.actors[ME].reaction_available


def test_cause_emptying_reversal_makes_a_benefit_fail_or_hollows_the_caster():
    engine = fight(bundle(VOID + "CAUSE_EMPTYING_REVERSAL", cl=15), foe=bundle(VOID + "VOID_SHELL", actor_id=FOE, cl=10, dc=1), foe_at=(6, 6))
    events = foe_uses(engine, "Void Shell")
    foe = engine.state.actors[FOE]
    assert [e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == VOID + "CAUSE_EMPTYING_REVERSAL"]
    check = [p for p in payloads(events, "CHECK_ROLLED") if "Cause-Emptying" in str(p.get("check"))][0]
    if check["success"]:
        assert len([m for m in foe.modifiers.values() if "VOID_SHELL" in m.source_definition_id]) < 3
    else:
        assert held(foe, "hollowed")


COURT_V = VOID + "COURT_OF_THE_EMPTY_HORIZON"


def test_court_of_the_empty_horizon_start_of_turn_save_and_enemy_rules():
    """Court of the Empty Horizon: "When an enemy starts its turn inside the Domain, it makes a Constitution saving throw. Failed Save: Choose
    one: it takes 2d8 ...; Successful Save: It cannot gain Temporary HP until the start of its next turn"; "Enemies inside the Domain ...
    cannot gain Temporary HP; treat the area as Difficult Terrain"; "Use Empty Step once on each of your turns without spending CP".
    The failed-save choice had been five separate ways of casting the Court."""
    engine = fight(bundle(COURT_V, VOID + "EMPTY_STEP", cl=17, dc=FAIL), foe_at=(5, 6))
    assert not [n for n in legal(engine) if n.startswith("Court of the Empty Horizon:")]
    use(engine, "Court of the Empty Horizon")
    foe = engine.state.actors[FOE]
    assert held(foe, "no_temp_hp") and (5, 7) in zones.difficult_cells(engine, foe)
    engine.state.actors[ME].bonus_action_available = True
    assert any(n.startswith("Empty Step (no cost)") for n in legal(engine))
    hp = foe.current_hp
    turn(engine, FOE)
    assert foe.current_hp < hp  # the owner's default choice: 2d8 damage
    turn(engine, ME)
    foe.position = Position(x=14, y=6)
    from combat.ext import void_riders

    void_riders._court_sync(engine)
    assert not held(foe, "no_temp_hp")  # it left the Court


def test_court_reduces_area_damage_to_allies_inside():
    from combat.ext import void_riders

    ally = bundle(SCOUR, actor_id=ALLY, cl=5)
    engine = fight(bundle(COURT_V, cl=17), foe=bundle(VOID + "COLLAPSING_GAP", actor_id=FOE, cl=10), ally=ally, foe_at=(12, 6), ally_at=(4, 7))
    use(engine, "Court of the Empty Horizon")
    source = action_id(engine, FOE, "Collapsing Gap")
    assert void_riders.court_ward(engine, engine.state.actors[ALLY], 10, "FORCE", source, FOE) == 4
    assert void_riders.court_ward(engine, engine.state.actors[ME], 10, "FORCE", source, FOE) is None  # the Court's owner is not its own ally
    assert void_riders.court_ward(engine, engine.state.actors[ALLY], 10, "FORCE", "action:test.not_an_area", FOE) is None


def test_world_of_nothing_costs_four_more_and_suppresses_an_enemys_first_benefit():
    engine = fight(bundle(COURT_V, VOID + "WORLD_OF_NOTHING", cl=17, dc=PASS), foe=bundle(VOID + "VOID_SHELL", actor_id=FOE, cl=10), foe_at=(5, 6))
    me = engine.state.actors[ME]
    qi = me.resources["resource:core.qi"]
    use(engine, "Court of the Empty Horizon + World of Nothing")
    assert qi - me.resources["resource:core.qi"] == 11
    foe = engine.state.actors[FOE]
    assert any((c.data or {}).get("rule", {}).get("no_cp_regain") for c in foe.conditions.values())
    turn(engine, FOE)
    use(engine, "Void Shell", actor_id=FOE)
    assert held(foe, "benefit_suppressed")


def test_consume_spellwork_checks_and_grants_advantage_or_halves_damage():
    """Consume Spellwork: "Make a Cultivation Check against: 10 + the triggering effect's CP cost ... + the triggering creature's
    Proficiency Bonus ... Successful Check: Choose one: reduce the damage against you by half; gain Advantage on one saving throw against
    the triggering effect; use Empty Step before the effect resolves" (the row had no effects the table could run)."""
    engine = fight(bundle(VOID + "CONSUME_SPELLWORK", cl=10, score=30), foe=bundle(VOID + "HOLLOW_TOUCH", actor_id=FOE, cl=10, dc=10), foe_at=(8, 6))
    events = foe_uses(engine, "Hollow Touch", target=ME)
    check = [p for p in payloads(events, "CHECK_ROLLED") if "Consume Spellwork" in str(p.get("check"))][0]
    assert check["dc"] == 10 + 2 + 4 and check["success"]
    saves = [e.payload for e in events if e.event_type == "SAVE_ROLLED" and ME in (e.target_ids or (e.actor_id,)) or
             (e.event_type == "SAVE_ROLLED" and (e.payload or {}).get("actor_id") == ME)]
    assert any(str(p.get("mode")).upper() == "ADVANTAGE" for p in saves)
    hit = fight(bundle(VOID + "CONSUME_SPELLWORK", cl=10, score=30), foe=bundle(VOID + "VOID_NEEDLE", actor_id=FOE, cl=10), foe_at=(8, 6))
    hit.state.actors[ME].armor_class = -50
    before = hit.state.actors[ME].current_hp
    events = foe_uses(hit, "Void Needle: Empty Vitality", target=ME)
    rolled = sum(int((p.get("combined_total") or p.get("total") or 0)) for p in payloads(events, "DAMAGE_ROLLED"))
    taken = before - hit.state.actors[ME].current_hp
    assert rolled and taken == rolled // 2


# ================================================================================================= INK
INK = "tianxia.talent.ink."


def ink_mark(engine, target=FOE, owner=ME):
    engine._apply_condition(engine.state.actors[target], typed_executor.mark_condition_id("ink_mark", owner), "test:ink", owner,
                            expires_on="UNTIL_REMOVED", data={"mark": "ink_mark", "label": "Ink Mark"})


def test_binding_script_is_a_bonus_action_against_a_marked_target():
    """"If the target already bears one of your Ink Marks, you may use Binding Script as a Bonus Action instead of an Action"."""
    engine = fight(bundle(INK + "binding_script", cl=5, dc=FAIL), foe_at=(6, 6))
    assert "Binding Script (marked target)" not in legal(engine)
    ink_mark(engine)
    assert "Binding Script (marked target)" in legal(engine)
    engine.state.actors[ME].action_available = False
    use(engine, "Binding Script (marked target)", target=FOE)
    assert held(engine.state.actors[FOE], "restrained") and not engine.state.actors[ME].bonus_action_available


def test_brushstroke_shield_adds_pb_only_for_a_marked_ally():
    from combat import typed_reactions
    from combat.ext import ink_riders

    ally = bundle(SCOUR, actor_id=ALLY, cl=5)
    engine = fight(bundle(INK + "brushstroke_shield", cl=10), ally=ally, foe_at=(8, 6), ally_at=(4, 6))
    (row,) = [r for r in typed_reactions._rows(engine, ME, "generic") if r["feature_id"] == INK + "brushstroke_shield"]
    pb_row = next(e for e in row["effects"] if e.get("if_protected_marked"))
    engine._typed_damage_packet = {"target": ALLY}
    assert ink_riders.shield_mark_bonus(engine, engine.state.actors[ME], row, pb_row) == 0
    ink_mark(engine, target=ALLY)
    assert ink_riders.shield_mark_bonus(engine, engine.state.actors[ME], row, pb_row) is None


def test_scripture_prison_first_save_has_disadvantage_against_a_marked_target():
    engine = fight(bundle(INK + "scripture_prison", cl=10), foe_at=(6, 6))
    ink_mark(engine)
    events = use(engine, "Scripture Prison", target=FOE)
    assert [p for p in payloads(events, "SAVE_ROLLED") if str(p.get("mode")).upper() == "DISADVANTAGE"]


@pytest.mark.parametrize("dc", [FAIL, PASS], ids=["failed-save", "successful-save"])
def test_soul_staining_ink_and_revealing_script_deny_invisible_against_you(dc):
    from combat import senses

    # lock/round6 (merge 6ee293bb) correctly rejects unseen targets for
    # "One creature you can see". Stain a visible creature, then test its
    # later Invisible/Hidden benefits; no special sense may mask them for us.
    ally = bundle(SCOUR, actor_id=ALLY, cl=5)
    engine = fight(bundle(INK + "soul_staining_ink", cl=10, dc=dc), ally=ally, foe_at=(6, 6))
    foe, me = engine.state.actors[FOE], engine.state.actors[ME]
    events = use(engine, "Soul-Staining Ink", target=FOE)
    assert payloads(events, "SAVE_ROLLED")[0]["success"] == (dc == PASS)
    (stain,) = held(foe, "ink_stain")
    assert stain.data["mode"] == ("stain" if dc == FAIL else "outline")
    engine._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    engine._apply_condition(foe, "condition:typed.hidden", "test", FOE, expires_on="UNTIL_REMOVED")
    # Failed-save Ink denies Hidden within 60 feet; the shared perception
    # query now includes that owned condition mask rather than special senses alone.
    assert senses.sees_hidden(engine, me, foe) == (dc == FAIL)
    masked = senses.masked_conditions(engine, me, foe).get(FOE, set())
    expected = {"condition:typed.invisible"} | ({"condition:typed.hidden"} if dc == FAIL else set())
    assert {c.condition_id for k, c in foe.conditions.items() if k in masked} == expected
    assert not senses.masked_conditions(engine, engine.state.actors[ALLY], foe).get(FOE)
    # Only the failed-save stain denies Hidden, and only within 60 feet.
    foe.position = Position(x=16, y=6)
    assert engine._distance_actor_to_actor(me, foe) == 65
    masked = senses.masked_conditions(engine, me, foe).get(FOE, set())
    assert {c.condition_id for k, c in foe.conditions.items() if k in masked} == {"condition:typed.invisible"}
    if dc == PASS:
        assert stain.expires_on == "START_OF_SOURCE_NEXT_TURN"
        turn(engine, FOE)
        turn(engine, ME)
        assert not held(foe, "ink_stain")
        assert not senses.masked_conditions(engine, me, foe).get(FOE)

    reveal = fight(bundle(INK + "revealing_script", cl=10, dc=dc), ally=ally, foe_at=(4, 6))
    foe, me = reveal.state.actors[FOE], reveal.state.actors[ME]
    events = use(reveal, "Revealing Script", target=FOE)
    assert payloads(events, "SAVE_ROLLED")[0]["success"] == (dc == PASS)
    reveal._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    reveal._apply_condition(foe, "condition:typed.hidden", "test", FOE, expires_on="UNTIL_REMOVED")
    assert not senses.sees_hidden(reveal, me, foe)
    masked = senses.masked_conditions(reveal, me, foe).get(FOE, set())
    expected = {"condition:typed.invisible"} if dc == FAIL else set()
    assert {c.condition_id for k, c in foe.conditions.items() if k in masked} == expected
    assert not senses.masked_conditions(reveal, reveal.state.actors[ALLY], foe).get(FOE)


def test_soul_staining_ink_requires_a_visible_target_before_it_can_stain():
    engine = fight(bundle(INK + "soul_staining_ink", cl=10), foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    assert "Soul-Staining Ink" in legal(engine)
    engine._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    engine._apply_condition(foe, "condition:typed.hidden", "test", FOE, expires_on="UNTIL_REMOVED")
    assert "Soul-Staining Ink" not in legal(engine)
    assert not held(foe, "ink_stain")


def test_true_name_calligraphy_locks_invisible_and_teleport_and_weakens_ink_saves():
    engine = fight(bundle(INK + "true_name_calligraphy", INK + "binding_script", cl=17, dc=FAIL), foe_at=(6, 6))
    use(engine, "True Name Calligraphy", target=FOE)
    foe = engine.state.actors[FOE]
    assert held(foe, "ink_true_name") and held(foe, "no_invisible") and held(foe, "cannot_teleport")
    engine.state.actors[ME].action_available = True
    events = use(engine, "Binding Script", target=FOE)
    assert [p for p in payloads(events, "SAVE_ROLLED") if str(p.get("mode")).upper() == "DISADVANTAGE"]
    turn(engine, FOE)
    turn(engine, ME)
    assert "True Name Calligraphy" not in legal(engine)  # once per week: once this fight


def test_black_seal_edict_needs_a_marked_target_and_forbids_teleporting():
    engine = fight(bundle(INK + "black_seal_edict", cl=10, dc=FAIL), foe_at=(6, 6))
    assert "Black-Seal Edict" not in legal(engine)
    ink_mark(engine)
    use(engine, "Black-Seal Edict", target=FOE)
    (lock,) = held(engine.state.actors[FOE], "cannot_teleport")
    assert lock.data.get("repeat_save", {}).get("ability") == "CHA"


def test_ink_domain_free_mark_escape_bonus_and_marked_invisible():
    from combat import senses

    engine = fight(bundle(INK + "ink_domain", cl=10), foe_at=(4, 6))  # Press Mark is a touch
    use(engine, "Ink Domain")
    assert any(n.startswith("Press Mark (free)") for n in legal(engine))
    foe, me = engine.state.actors[FOE], engine.state.actors[ME]
    ink_mark(engine)
    engine._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    assert senses.masked_conditions(engine, me, foe).get(FOE)


def test_ink_lines_already_running():
    """Painted Beast's statistics, command and single copy are its summon (combat/rules/summons.json); Ink Lash's and Thousand
    Brushstrokes' damage scale by CL; Scripture Wall's AC/HP/immunities are its wall profile."""
    engine = fight(bundle(INK + "painted_beast", cl=10), foe_at=(8, 6))
    use(engine, "Painted Beast")
    beast = next(a for a in engine.state.actors.values() if a.owner_id == ME and "painted_beast" in a.entity_id and a.active)
    assert beast.armor_class == 16 and beast.maximum_hp == 50 and beast.speed_ft == 40
    assert "Command Painted Beast" in legal(engine) or not engine.state.actors[ME].bonus_action_available
    assert mech("INK_BASE_INK_LASH")["effects"][0]["on_hit"][0]["dice_by_cl"][-1] == [17, 20, 4, 8]
    wall = fight(bundle(INK + "scripture_wall", cl=10), foe_at=(12, 6))
    use(wall, "Scripture Wall", at=(6, 6))
    (zone,) = [z for z in zones.typed_zones(wall) if z.owner_id == ME]
    assert zone.trigger_profile["wall"]["object"]["hp"] == "10*pb" and zone.trigger_profile["wall"]["blocks_movement"]


def test_heaven_sealing_writ_suppresses_teleport_on_a_marked_creature():
    engine = fight(bundle(INK + "heaven_sealing_writ", cl=17, dc=FAIL), foe_at=(6, 6))
    assert "Heaven-Sealing Writ" not in legal(engine)
    ink_mark(engine)
    use(engine, "Heaven-Sealing Writ", target=FOE)
    (lock,) = held(engine.state.actors[FOE], "cannot_teleport")
    assert lock.expires_on == "CONCENTRATION_END"


def test_ink_step_space_to_mark_lands_beside_a_marked_creature():
    engine = fight(bundle(INK + "ink_step", cl=5), foe_at=(8, 6))
    steps = [c for c in engine.legal_candidates() if c.display_name.startswith("Ink Step: Space to Mark")]
    assert not steps
    ink_mark(engine)
    steps = [c for c in engine.legal_candidates() if c.display_name.startswith("Ink Step: Space to Mark")]
    assert steps and all(engine.grid.distance_ft(c.destination, engine.state.actors[FOE].position) <= 5 for c in steps)


# ================================================================================================= DARK
DARK = "TAL_DARK_"


def darkness(engine, shape, at=(8, 6)):
    if shape:
        use(engine, f"Shape Darkness: {shape}")
    use(engine, "Darkness", at=at)
    return next(z for z in zones.typed_zones(engine) if z.owner_id == ME)


def test_black_lung_chokes_a_poisoned_creatures_spoken_ability():
    """Black Lung: "A creature Poisoned by Black Lung that attempts to activate an ability requiring clear speech must make a Constitution
    saving throw. On a failure, the activation fails and the action and any CP spent are lost." """
    from combat import speech

    foe = bundle("WARLEADER_BASE_FIERCE_SHOUT", actor_id=FOE, cl=10)
    engine = fight(bundle(DARK + "BLACK_LUNG", cl=10, dc=FAIL), foe=foe, foe_at=(8, 6))
    zone = darkness(engine, "Black Lung")
    turn(engine, FOE)
    f = engine.state.actors[FOE]
    assert held(f, "poisoned")
    action = next((engine.action_catalog[a] for a in f.action_ids if a in engine.action_catalog and speech.needs_voice(engine.action_catalog[a])), None)
    from combat.ext import dark_riders

    if action is None:
        pytest.skip("no voiced ability on the test foe")
    assert dark_riders.black_lung_speech(engine, f, action) is True
    plain = next(engine.action_catalog[a] for a in f.action_ids if a in engine.action_catalog and not speech.needs_voice(engine.action_catalog[a]))
    assert dark_riders.black_lung_speech(engine, f, plain) is None


def test_snagging_darkness_bonus_action_escape():
    """Snagging Darkness: "A Restrained creature may use a Bonus Action to make a Strength (Athletics) or Dexterity (Acrobatics) check against
    your Cultivation Save DC, ending the condition on itself on a success." """
    engine = fight(bundle(DARK + "SNAGGING_DARKNESS", cl=10, dc=FAIL), foe_at=(8, 6))
    darkness(engine, "Snagging Darkness")
    f = turn(engine, FOE)
    assert held(f, "restrained")
    assert "Tear free of the snagging darkness" in legal(engine)
    zone = next(z for z in zones.typed_zones(engine) if z.owner_id == ME)
    zone.trigger_profile["numbers"]["save_dc"] = 1  # an easy check, to see it end the Restrained
    use(engine, "Tear free of the snagging darkness", actor_id=FOE)
    assert not held(f, "restrained") and not f.bonus_action_available


def test_shadow_slick_gives_advantage_to_escape_a_grapple_inside():
    from combat.ext import dark_riders

    engine = fight(bundle(DARK + "SHADOW_SLICK", cl=10), foe_at=(8, 6))
    darkness(engine, "Shadow Slick")
    f = engine.state.actors[FOE]
    engine._apply_condition(f, "condition:typed.grappled", "test", ME, expires_on="UNTIL_REMOVED", data={"escape_dc": 10})
    grips = [c for c in f.conditions.values() if c.condition_id == "condition:typed.grappled"]
    assert dark_riders.slick_escape(engine, f, grips) == "ADVANTAGE"
    f.position = Position(x=15, y=12)
    assert dark_riders.slick_escape(engine, f, grips) is None


def test_creeping_lethargy_sleeper_can_be_woken_by_an_ally():
    ally = bundle(SCOUR, actor_id=ALLY, cl=5)
    engine = fight(bundle(SCOUR, cl=5), ally=ally, foe_at=(8, 6), ally_at=(3, 7))
    me = engine.state.actors[ME]
    engine._apply_condition(engine.state.actors[ALLY], "condition:typed.unconscious", "test", FOE, expires_on="UNTIL_REMOVED",
                            data={"sleep": "creeping_lethargy"})
    assert "Wake a sleeping ally (Creeping Lethargy)" in legal(engine)
    use(engine, "Wake a sleeping ally (Creeping Lethargy)")
    assert not held(engine.state.actors[ALLY], "unconscious")


def test_dark_lines_already_running():
    """Rider copies removed: Hungry Darkness once per round; Greater Darkness' 30-ft radius; Persistent Darkness without
    Concentration; Pure Darkness' senses; Meld as an Action and persistent; Night That Swallows the Lantern's cost and once per week."""
    engine = fight(bundle(DARK + "HUNGRY_DARKNESS", DARK + "GREATER_DARKNESS", DARK + "PERSISTENT_DARKNESS", cl=10), foe_at=(8, 6))
    b = bundle(DARK + "HUNGRY_DARKNESS", DARK + "GREATER_DARKNESS", DARK + "PERSISTENT_DARKNESS", cl=10)
    acts = {a["display_name"]: a for a in b["action_catalog"]}
    assert acts["Darkness + Greater Darkness"]["parameters"]["typed"]["zone_spec"]["size_ft"] == 30
    assert acts["Darkness + Persistent Darkness"]["concentration"] is False
    hungry = acts["Darkness"]["parameters"]["typed"]["zone_spec"]["shapes"][DARK + "HUNGRY_DARKNESS"]["triggers"][0]
    assert hungry["per_round"] is True
    night = bundle(DARK + "NIGHT_THAT_SWALLOWS_THE_LANTERN", cl=17)
    (row,) = [r for r in night["typed_reactions"] if r["feature_id"] == DARK + "NIGHT_THAT_SWALLOWS_THE_LANTERN"]
    assert {"resource_id": "resource:core.qi", "amount": 15} in row["costs"] and any("uses." in c["resource_id"] for c in row["costs"])


def test_tenebrous_legerdemain_pulls_a_weapon_away_inside_the_darkness():
    engine = fight(bundle(DARK + "TENEBROUS_LEGERDEMAIN", cl=10), foe=armed_foe(), foe_at=(8, 6))
    assert "Tenebrous Legerdemain: pull a weapon away" not in legal(engine)
    darkness(engine, "Tenebrous Legerdemain")
    f = engine.state.actors[FOE]
    f.armor_class = -50
    use(engine, "Tenebrous Legerdemain: pull a weapon away", target=FOE)
    (lost,) = held(f, "disarmed")
    assert lost.data["dropped_at"] != f.position.model_dump(mode="json")


# ================================================================================================= BRUTE
BR = "TAL_BRUTE_"


def shove_into(me_bundle, *, blocker=True, cl=10):
    """Me at (3,6) Brutal Shoves the foe at (4,6) east; a second hostile stands at (5,6) to collide with."""
    second = bundle(SCOUR, actor_id=ALLY, cl=5)
    engine = fight(me_bundle, ally=second if blocker else None, foe_at=(4, 6), ally_at=(5, 6))
    if blocker:
        engine.state.actors[ALLY].team_id = "team:b"
    for who in (FOE, ALLY):
        if who in engine.state.actors:
            engine.state.actors[who].armor_class = -50
            # Brutal Shove is the printed Athletics contest (rider lane C16), no longer an attack roll: the shoved creatures resist badly.
            engine.state.actors[who].skills = {"Athletics": -50, "Acrobatics": -50}
    engine.state.actors[ME].resources["resource:core.martial_focus"] = 1
    return engine


def test_crushing_collision_dazes_the_shoved_creature():
    """Crushing Collision: "When Hammer creates an Impact Collision, choose one: the shoved creature makes a Constitution save or becomes Dazed
    until the start of its next turn ... A Dazed creature cannot take Reactions and has Disadvantage on its next attack roll"."""
    engine = shove_into(bundle("BRUTE_BASE_BRUTAL_SHOVE", BR + "HAMMER", BR + "CRUSHING_COLLISION", cl=10, dc=FAIL))
    use(engine, "Brutal Shove", target=FOE)
    foe = engine.state.actors[FOE]
    (dazed,) = held(foe, "brute_dazed")
    assert not foe.reaction_available and dazed.expires_on != "START_OF_SOURCE_NEXT_TURN"
    assert any(m.target_field == "attack_mode" and m.value == "DISADVANTAGE" for m in foe.modifiers.values())


def test_dominoes_free_shove_knocks_the_second_creature_prone():
    """Dominoes: "When a shove pushes a creature into another creature, immediately attempt one free shove against the second creature to
    knock it Prone. The second creature need not be within your reach." """
    engine = shove_into(bundle("BRUTE_BASE_BRUTAL_SHOVE", BR + "DOMINOES", cl=10))
    use(engine, "Brutal Shove", target=FOE)
    assert held(engine.state.actors[ALLY], "prone")  # at (5,6): 10 feet away, beyond the shover's reach


def test_court_and_sovereign_weight_resist_forced_movement_and_push_farther():
    from combat.ext import brute_riders

    engine = shove_into(bundle("BRUTE_BASE_BRUTAL_SHOVE", BR + "COURT_OF_THE_MOVING_MOUNTAIN", cl=12), blocker=False)
    use(engine, "Court of the Moving Mountain")
    me = engine.state.actors[ME]
    ctx = ctx_of(engine, FOE, ME, action_id(engine, ME, "Brutal Shove"))
    assert brute_riders.resist_shoves(ctx, me) == 10
    start = engine.state.actors[FOE].position.x
    engine.state.actors[ME].action_available = True
    use(engine, "Brutal Shove", target=FOE)
    assert (engine.state.actors[FOE].position.x - start) * 5 >= 15  # 5 + the extra 5 of the typing + the Court's 5
    sov = shove_into(bundle("BRUTE_BASE_BRUTAL_SHOVE", BR + "SOVEREIGN_WEIGHT_INCARNATION", cl=15), blocker=False)
    # Isolate the replacement damage packet from native crossed-map hazards.
    sov.grid.qi_hazard = frozenset()
    use(sov, "Sovereign Weight Incarnation")
    assert brute_riders.resist_shoves(ctx_of(sov, FOE, ME, action_id(sov, ME, "Brutal Shove")), sov.state.actors[ME]) >= 10000
    hp, start = sov.state.actors[FOE].current_hp, sov.state.actors[FOE].position.x
    sov.state.actors[ME].action_available = True
    events = use(sov, "Brutal Shove", target=FOE)
    assert (sov.state.actors[FOE].position.x - start) * 5 >= 20
    # The printed damage "becomes 2d8 + Strength modifier": one replacement
    # packet, rather than the old base packet plus a separate 2d8 rider.
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert len(damage) == 1
    roll = next(e for e in events if e.event_type == "DAMAGE_ROLLED" and FOE in e.target_ids)
    assert "d8" in roll.payload["expression"]
    assert hp - sov.state.actors[FOE].current_hp == roll.payload["total"]


def test_brute_lines_already_running():
    b = bundle(BR + "EARTHQUAKE_STOMP", BR + "THUNDEROUS_CLAP", cl=17)
    acts = {a["display_name"]: a for a in b["action_catalog"]}
    assert acts["Earthquake Stomp"]["radius_ft"] == 20  # "Radius: ... 20 feet (CL 17-20)" (the CL table was not read before)
    clap = acts["Thunderous Clap"]
    assert ["resource:core.martial_focus", 1] in [list(c) for c in clap["costs"]]


# ================================================================================================= PROTECTION
PR = "tianxia.talent.protection."
AEGIS_BASE = ("PROTECTION_BASE_AEGIS", "PROTECTION_BASE_ARMORED_AEGIS", "PROTECTION_BASE_WARD", "PROTECTION_BASE_SUCCOR")


def guardian(*talents, cl=15, dc=16):
    return bundle(*AEGIS_BASE, *[PR + t for t in talents], cl=cl, dc=dc)


def protect(*talents, foe=None, cl=15, dc=16, ally_at=(3, 7), foe_at=(4, 7)):
    """Me at (3,6), my ally at (3,7), the axe-armed foe at (4,7), next to the ally."""
    return fight(guardian(*talents, cl=cl, dc=dc), ally=bundle(SCOUR, actor_id=ALLY, cl=5), foe=foe or armed_foe(), ally_at=ally_at, foe_at=foe_at)


def aegis_of(actor, persistent=None):
    from combat.ext import protection

    return protection.aegises(actor, ME, persistent=persistent)


def test_persistent_aegis_is_the_mark_bulwark_sacrifices():
    """Aegis: "Grant the target one Aegis talent you know ... Persistent Aegis - Augment 2 CP: The Aegis persists ... without Concentration";
    Shielded: "The shield functions as an ordinary shield"; Bulwark: "A protected ally is targeted by an attack roll. Sacrifice one Persistent
    Aegis on that ally. The ally gains Resistance to all damage dealt by the triggering attack." Before, no Aegis could be made at all."""
    engine = protect("shielded", "bulwark")
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    names = legal(engine)
    assert {"Aegis: Shielded", "Aegis: Shielded (Persistent)", "Aegis: Armored Aegis"} <= names
    qi = dict(me.resources)
    ac = engine._ac_modifier(ally)
    use(engine, "Aegis: Shielded (Persistent)", target=ALLY)
    assert typed_executor.bears_mark(ally, ME, "Persistent Aegis") and me.concentration is None
    assert engine._ac_modifier(ally) == ac + 2 and sum(qi.values()) - sum(me.resources.values()) == 2
    ally.armor_class = -50
    events = foe_attacks(engine, ALLY)
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == PR + "bulwark" for e in events)
    assert not aegis_of(ally)


def test_one_aegis_per_creator_and_a_concentration_aegis_ends_with_concentration():
    """"A creature may benefit from only one Aegis created by the same cultivator at a time"; Armored Aegis: "The target's base AC becomes
    equal to your Cultivation Save DC"; "An Aegis uses Concentration unless made Persistent"."""
    engine = protect("shielded", dc=19)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    ally.armor_class = 10
    use(engine, "Aegis: Shielded (Persistent)", target=ALLY)
    me.action_available = True
    use(engine, "Aegis: Armored Aegis", target=ALLY)
    (only,) = aegis_of(ally)
    assert only[1].data["aegis_talent"] == "PROTECTION_BASE_ARMORED_AEGIS" and me.concentration is not None
    assert ally.armor_class + engine._ac_modifier(ally) >= 19
    engine._end_concentration(me, "TEST")
    assert not aegis_of(ally)


def test_energy_resistance_and_protected_health_aegis_resist_damage():
    """Energy Resistance - Aegis: "The bearer gains Resistance to the chosen damage type"; Protected Health - Aegis: "Resistance to Poison
    damage; Advantage on saving throws against poison"."""
    from combat import typed_reactions as tr
    from combat.ext import protection

    engine = protect("energy_resistance", "protected_health")
    ally = engine.state.actors[ALLY]
    use(engine, "Aegis: Energy Resistance", target=ALLY)  # no answer: the preferred type, Fire
    assert tr.defend(engine, ally, 20, "FIRE", "test:hit", FOE) == 10 and tr.defend(engine, ally, 20, "COLD", "test:hit", FOE) == 20
    engine.state.actors[ME].action_available = True
    use(engine, "Aegis: Protected Health", target=ALLY)
    assert tr.defend(engine, ally, 20, "POISON", "test:hit", FOE) == 10 and tr.defend(engine, ally, 20, "FIRE", "test:hit", FOE) == 20
    ctx = ctx_of(engine, FOE, ALLY, action_id(engine, FOE, "Scouring Hand"))
    assert protection.aegis_saves(ctx, ally, "CON", {"poisoned"}) == {"modes": ["ADVANTAGE"]}


def test_slippery_and_spell_ward_aegis_save_advantage():
    """Slippery: "Advantage on: saving throws against being Restrained; saving throws against forced movement; ... checks made to escape a
    Grapple"; Spell Ward - Aegis: "Advantage on saving throws against supernatural effects" (Cost: 1 CP)."""
    from combat.ext import protection

    engine = protect("slippery", "spell_ward")
    ally = engine.state.actors[ALLY]
    use(engine, "Aegis: Slippery", target=ALLY)
    ctx = ctx_of(engine, FOE, ALLY, action_id(engine, FOE, "Scouring Hand"))
    assert protection.aegis_saves(ctx, ally, "STR", {"restrained"}) == {"modes": ["ADVANTAGE"]}
    assert protection.aegis_saves(ctx, ally, "DEX", {"damage:fire"}) is None
    assert protection.slippery_escape(engine, ally, ()) == "ADVANTAGE"
    engine.state.actors[ME].action_available = True
    use(engine, "Aegis: Spell Ward", target=ALLY)
    assert protection.aegis_saves(ctx, ally, "DEX", {"damage:fire"}) == {"modes": ["ADVANTAGE"]}


def test_punishment_aegis_and_punishment_succor_hurt_the_attacker():
    """Punishment - Aegis: "A creature that hits the bearer with an attack takes Psychic damage based on your CL" (CL 11-16: 2d6 + PB);
    Succor: "A protected ally takes damage from an attack. Sacrifice one Persistent Aegis on that ally. The attacker takes Psychic damage".
    "Punishment Succor stacks with Punishment Aegis." """
    engine = protect("punishment", cl=12)
    ally, foe = engine.state.actors[ALLY], engine.state.actors[FOE]
    use(engine, "Aegis: Punishment (Persistent)", target=ALLY)
    ally.armor_class = -50
    events = foe_attacks(engine, ALLY)
    on_foe = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert len(on_foe) == 2 and all(p["damage_type"] == "PSYCHIC" for p in on_foe)  # the Aegis's Punishment and the Succor's, which stack
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == PR + "punishment" for e in events)
    assert not aegis_of(ally)


def test_punishment_succor_needs_an_attack():
    from combat.ext import protection

    engine = protect("punishment")
    ally = engine.state.actors[ALLY]
    row = {"feature_id": PR + "punishment"}
    engine._typed_damage_packet = None
    assert protection.punishment_succor_attack_only(engine, engine.state.actors[ME], ally, row) is False
    engine._typed_damage_packet = {"source": "x", "actor": FOE, "target": ALLY}
    assert protection.punishment_succor_attack_only(engine, engine.state.actors[ME], ally, row) is False
    from combat.damage_context import AttackDamage
    engine._damage_packet_context = AttackDamage("x", FOE, ALLY, 0, "test:attack", 20, 30, False)
    assert protection.punishment_succor_attack_only(engine, engine.state.actors[ME], ally, row) is None


def test_luck_rerolls_a_protected_allys_failed_save_and_sacrifices_the_aegis():
    """Luck - Succor: "A protected creature makes a saving throw. Sacrifice one Persistent Aegis on that creature. The creature rerolls the
    saving throw and must use the new result." """
    foe = bundle(SCOUR, actor_id=FOE, cl=5, dc=FAIL)
    engine = protect("luck", foe=foe, foe_at=(6, 7))
    ally = engine.state.actors[ALLY]
    use(engine, "Aegis: Armored Aegis (Persistent)", target=ALLY)
    turn(engine, FOE)
    events = use(engine, "Scouring Hand", target=ALLY) if "Scouring Hand" in legal(engine) else \
        use(engine, next(n for n in legal(engine) if n.startswith("Scouring Hand")), target=ALLY)
    assert any(e.event_type == "D20_REWRITTEN" for e in events)
    assert not aegis_of(ally) and not engine.state.actors[ME].reaction_available


def test_peacebound_aegis_stops_an_attack_or_breaks_and_ends_when_the_bearer_attacks():
    """Peacebound - Aegis: "A creature attempting a violent action ... against the bearer makes a Wisdom saving throw. Failed Save: The
    action fails. Successful Save: The Peacebound Aegis ends immediately. If the bearer takes an offensive action, the Aegis ends." """
    engine = protect("peacebound", dc=FAIL)
    ally, foe = engine.state.actors[ALLY], engine.state.actors[FOE]
    use(engine, "Aegis: Peacebound", target=ALLY)
    ally.armor_class = -50
    hp = ally.current_hp
    events = foe_attacks(engine, ALLY)
    assert ally.current_hp == hp and aegis_of(ally)
    assert any("fails its Wisdom save" in str((e.payload or {}).get("log")) for e in events)
    broken = protect("peacebound", dc=PASS)
    b_ally = broken.state.actors[ALLY]
    use(broken, "Aegis: Peacebound", target=ALLY)
    b_ally.armor_class = -50
    hp = b_ally.current_hp
    foe_attacks(broken, ALLY)
    assert not aegis_of(b_ally) and b_ally.current_hp < hp
    # the bearer's own attack ends it
    turn(engine, ALLY)
    attack = next(n for n in legal(engine) if n.startswith("Scouring Hand"))
    use(engine, attack, target=FOE)
    assert not aegis_of(ally)


def test_peacebound_ward_stops_an_attack_from_inside_then_breaks_on_a_success():
    """Peacebound - Ward: "A creature attempting a violent action ... while inside the Ward makes a Wisdom saving throw. Failed Save: The
    action fails. Successful Save: The Peacebound Ward ends for all creatures ... creatures inside become immune to your Peacebound Ward"."""
    engine = protect("peacebound", dc=FAIL)
    ally = engine.state.actors[ALLY]
    use(engine, "Ward: Peacebound")
    assert any(z.owner_id == ME for z in zones.typed_zones(engine))
    ally.armor_class = -50
    hp = ally.current_hp
    foe_attacks(engine, ALLY)
    assert ally.current_hp == hp
    for zone in zones.typed_zones(engine):
        zone.trigger_profile["numbers"]["save_dc"] = PASS
    engine.state.actors[FOE].action_available = True
    foe_attacks(engine, ALLY)
    assert ally.current_hp < hp and not any(z.owner_id == ME for z in zones.typed_zones(engine))
    assert FOE in engine.state.actors[ME].turn_flags["protection_peace_round_immune"]


def test_energy_resistance_ward_gives_resistance_inside():
    """Energy Resistance - Ward: "Creatures inside gain Resistance to the chosen damage type while they remain inside"."""
    from combat import typed_reactions as tr

    engine = protect("energy_resistance")
    use(engine, "Ward: Energy Resistance")
    ally = engine.state.actors[ALLY]
    assert tr.defend(engine, ally, 20, "FIRE", "test:hit", FOE) == 10
    assert engine.state.actors[ME].concentration is not None


def test_community_moves_half_the_damage_to_another_aegis_bearer():
    """Community: "Whenever a creature benefiting from one of your Aegises takes damage, you may transfer up to half of that damage to
    another willing creature benefiting from one of your Aegises. No action is required." """
    engine = protect("community")
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    from combat.ext import protection

    use(engine, "Aegis: Armored Aegis (Persistent)", target=ALLY)
    me.action_available = True
    use(engine, "Aegis: Armored Aegis (Persistent)", target=ME)
    ally.current_hp = 10
    mine = me.current_hp
    left = protection.community(engine, ally, 16, "test:hit", FOE)
    assert left == 8 and me.current_hp == mine - 8


def test_heaven_sheltering_aegis_keeps_the_bearer_at_one_hp_once():
    """Heaven-Sheltering Aegis: "its base AC becomes your Cultivation Save DC + 2 ... once during the duration, when it would drop to 0 HP,
    it drops to 1 HP instead and the Aegis ends." """
    from combat import typed_reactions as tr

    engine = fight(guardian("bulwark", "luck", "heaven_sheltering_aegis", cl=15, dc=20), ally=bundle(SCOUR, actor_id=ALLY, cl=5),
                   foe=armed_foe(), ally_at=(3, 7), foe_at=(4, 7))
    ally = engine.state.actors[ALLY]
    ally.armor_class = 10
    use(engine, "Heaven-Sheltering Aegis", target=ALLY)
    assert ally.armor_class + engine._ac_modifier(ally) >= 22
    assert tr.defend(engine, ally, 20, "SLASHING", "test:hit", FOE) == 10  # "Resistance to all damage" (its typed row)
    left = tr._offer_drop_to_zero_or_bloodied(engine, ally, engine.state.actors[FOE], ally.current_hp + 30, 0, FOE)
    assert left == ally.current_hp - 1 and not aegis_of(ally)
    assert tr.defend(engine, ally, 20, "SLASHING", "test:hit", FOE) == 20  # the Aegis ended, its Resistance with it


def test_sanctuary_without_borders_needs_a_ward_and_frees_a_restrained_ally():
    """Sanctuary Without Borders: "Choose one Ward you create. When a willing creature enters the Ward for the first time on a turn or starts
    its turn inside, it may immediately end one of the following: Frightened; Grappled; Restrained ... A creature may benefit once per
    activation." """
    engine = protect("peacebound", "sanctuary_without_borders", cl=15)
    assert "Sanctuary Without Borders" not in legal(engine)
    use(engine, "Ward: Peacebound (Persistent)")
    engine.state.actors[ME].action_available = True
    use(engine, "Sanctuary Without Borders")
    ally = engine.state.actors[ALLY]
    # New relief rows require an attributable ordinary source; keep the same
    # snare and assertions while naming the foe's real compiled technique.
    snare_source = next(a.source_definition_id for a in engine.action_catalog.values()
                        if a.owner_id == FOE and ((a.parameters or {}).get("typed") or {}).get("source") == SCOUR)
    engine._apply_condition(ally, "condition:typed.restrained", snare_source, FOE, expires_on="UNTIL_REMOVED")
    turn(engine, ALLY)
    assert not held(ally, "restrained")
    engine._apply_condition(ally, "condition:typed.restrained", snare_source, FOE, expires_on="UNTIL_REMOVED")
    turn(engine, ME)
    turn(engine, ALLY)
    assert held(ally, "restrained")  # once per activation


def test_aegis_survives_a_table_commit_and_reload(tmp_path):
    from tests.r1i_service_support import OWNER, fixture
    from tests.test_r1i_round3 import reload

    combat, table, mid, send, commit = fixture(tmp_path, [*AEGIS_BASE, PR + "shielded"], owner_dc=18)
    menu = table.state(mid)["menu"]
    cid = next(o["candidate_id"] for g in menu["actions"] if g["label"] == "Aegis: Shielded (Persistent)" for o in g["options"])
    commit(cid)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    from combat.ext import protection

    (aegis,) = protection.aegises(owner, OWNER, persistent=True)
    assert aegis[1].data["aegis_talent"] == PR + "shielded" and typed_executor.bears_mark(owner, OWNER, "Persistent Aegis")
    assert protection.aegis_ac(engine, owner) == 2


# ================================================================================================= TRAP
def _trap_scene(*talents, cl=10, allies=(), focus=1, picks=()):
    from tests.test_auto_lane1 import AN as TFOE, ME as TME, _engine
    from tests.test_sys_placed_effects import _pick, _trapper

    engine = _engine(_trapper(*talents, cl=cl), allies=allies)
    # Initiative preparation now runs through the native setup candidate,
    # rather than an interactive constructor/initial-turn event.
    if engine.state.setup_tasks:
        candidate = engine.legal_candidates()[0]
        engine.execute_intent(ActionIntent(intent_id="test:trap-setup", decision_id=candidate.decision_id,
                                           candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                           actor_id=candidate.actor_id))
    engine.state.actors[TME].resources["resource:core.martial_focus"] = focus
    engine.state.actors[TFOE].saving_throws["DEX"] = -50
    for name in picks:
        _pick(engine, name)
    return engine, TME, TFOE


def _trap_zones(engine):
    from combat.ext import placed

    return placed.of(engine, "trap")


def test_court_of_the_hidden_nail_free_trap_limit_warned_allies_and_focus_back():
    """Court of the Hidden Nail: "your active trap limit increases by your Proficiency Bonus; once per turn, set one trap in an unoccupied
    space within your reach without spending an Action; a trap set this way lasts until the Court ends ...; your warned allies do not
    trigger your traps inside the Court; when one of your traps triggers, ... regain Martial Focus if it is absent"."""
    from combat.ext import states, trap
    from tests.test_auto_lane1 import ALLY as TALLY, _ally_bundle
    from tests.test_sys_placed_effects import _pick, _walk

    engine, me_id, foe_id = _trap_scene("TAL_TRAP_COURT_OF_THE_HIDDEN_NAIL", allies=(_ally_bundle(),), picks=("Trap form: Tripwire",))
    me = engine.state.actors[me_id]
    _pick(engine, "Court of the Hidden Nail")
    assert states.active(engine, me, "court_of_the_hidden_nail") and me.resources["resource:core.martial_focus"] == 0
    assert trap._limit(trap._kit(engine, me), engine, me) == 8
    _pick(engine, "Set Trap (Court, no Action)", at=(3, 5))
    assert me.action_available and len(_trap_zones(engine)) == 1
    assert "Set Trap (Court, no Action)" not in {c.display_name.split(" at ")[0] for c in engine.legal_candidates()}
    _walk(engine, TALLY, [(2, 6), (3, 5), (2, 4)])
    assert not held(engine.state.actors[TALLY], "prone")  # an ally that saw it set does not trigger it inside the Court
    _walk(engine, foe_id, [(3, 5)])
    assert held(engine.state.actors[foe_id], "prone") and me.resources["resource:core.martial_focus"] == 1
    engine._remove_condition(me, "condition:typed.state.court_of_the_hidden_nail", "test:court_ends")
    assert not _trap_zones(engine)  # "lasts until the Court ends"


def test_opportunist_and_prepared_escape_route_answer_a_sprung_trap():
    """Opportunist: "A creature you can perceive triggers one of your traps within your weapon's legal range. Make one weapon attack or
    Unarmed Strike against that creature." Prepared Escape Route: "When a trap you set triggers within 30 feet of you, use a Reaction to
    move up to half your Speed. This movement does not provoke Opportunity Attacks from the triggering creature." """
    from tests.test_sys_placed_effects import _pick, _walk

    engine, me_id, foe_id = _trap_scene("TAL_TRAP_OPPORTUNIST", picks=("Trap form: Tripwire",))
    _pick(engine, "Set Trap", at=(3, 5))
    events = _walk(engine, foe_id, [(3, 5)])
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == me_id and foe_id in e.target_ids for e in events)
    assert not engine.state.actors[me_id].reaction_available
    engine, me_id, foe_id = _trap_scene("TAL_TRAP_PREPARED_ESCAPE_ROUTE", picks=("Trap form: Tripwire",))
    _pick(engine, "Set Trap", at=(3, 5))
    me = engine.state.actors[me_id]
    start = me.position
    _walk(engine, foe_id, [(3, 5)])
    assert me.position != start and not me.reaction_available
    assert engine.grid.distance_ft(me.position, engine.state.actors[foe_id].position) > 5


def test_remote_trigger_fires_a_dart_at_an_approaching_foe_and_can_impose_disadvantage():
    """Remote Trigger: "While within 30 feet of one of your traps, use a Reaction to trigger it when one creature comes within 30 feet of
    the trap. The trap must still have a legal target ... Alternatively, when a creature makes a Dexterity saving throw against one of your
    traps within 30 feet, use a Reaction to impose Disadvantage on that saving throw." """
    from combat.gate2_runtime_models import Position
    from combat.ext import trap
    from tests.test_sys_placed_effects import _pick, _walk

    engine, me_id, foe_id = _trap_scene("TAL_TRAP_REMOTE_TRIGGER", picks=("Trap aim: north",))
    _pick(engine, "Set Trap", at=(3, 5))
    engine.state.actors[foe_id].position = Position(x=12, y=5)
    events = _walk(engine, foe_id, [(8, 3), (3, 1)])  # ends 20 feet up the dart's line, never on the trap
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == "TAL_TRAP_REMOTE_TRIGGER" for e in events)
    assert any(e.event_type == "ATTACK_ROLLED" and foe_id in e.target_ids for e in events) and not _trap_zones(engine)
    engine, me_id, foe_id = _trap_scene("TAL_TRAP_REMOTE_TRIGGER", picks=("Trap form: Tripwire",))
    _pick(engine, "Set Trap", at=(3, 5))
    zone = _trap_zones(engine)[0]
    ctx = trap._with_source(trap._ctx_for(engine, engine.state.actors[me_id], zone), f"trap:{zone.zone_id}")
    assert "DISADVANTAGE" in trap.trap_save_modes(ctx, engine.state.actors[foe_id], "DEX", set())["modes"]
    assert not engine.state.actors[me_id].reaction_available


def test_hundred_mechanism_scripture_sets_three_traps_once_a_fight():
    """Hundred-Mechanism Scripture: "When you expend Martial Focus to set one trap as an Action, set up to three traps instead. Each trap
    must occupy different legal spaces within your reach ... once per short or long rest." """
    from tests.test_sys_placed_effects import _pick

    engine, me_id, _ = _trap_scene("tianxia.talent.trap.hundred_mechanism_scripture", cl=15)
    _pick(engine, "Set Trap x3 (Hundred-Mechanism Scripture)", at=(3, 5))
    cells = {(z.center.x, z.center.y) for z in _trap_zones(engine)}
    me = engine.state.actors[me_id]
    assert len(cells) == 3 and all(engine.grid.distance_ft(me.position, Position(x=x, y=y)) <= 5 for x, y in cells)
    me.resources["resource:core.martial_focus"], me.action_available = 1, True
    assert "Set Trap x3 (Hundred-Mechanism Scripture)" not in {c.display_name.split(" at ")[0] for c in engine.legal_candidates()}


def test_trap_within_the_trap_places_a_second_trap_on_the_false_click():
    """Trap Within the Trap: "When False Trigger produces its warning sound, immediately place one additional trap in one unoccupied space
    within 5 feet of the original trap ... cannot also use Trap Within the Trap." """
    from tests.test_sys_placed_effects import _pick, _walk

    engine, _me, foe_id = _trap_scene("TAL_TRAP_FALSE_TRIGGER", "TAL_TRAP_TRAP_WITHIN_THE_TRAP", cl=15,
                                      picks=("Trap form: Tripwire", "Trap trigger: False Trigger"))
    _pick(engine, "Set Trap", at=(3, 5))
    _walk(engine, foe_id, [(3, 5)])
    zones_now = _trap_zones(engine)
    assert len(zones_now) == 2
    child = next(z for z in zones_now if (z.center.x, z.center.y) != (3, 5))
    assert engine.grid.distance_ft(child.center, Position(x=3, y=5)) <= 5


def test_noose_silences_while_it_holds():
    """Noose: "While Restrained by this noose, it also cannot speak, supply Verbal components, or breathe normally." """
    from combat import speech
    from tests.test_sys_placed_effects import _pick, _walk

    engine, _me, foe_id = _trap_scene("TAL_TRAP_NOOSE", picks=("Trap form: Noose",))
    _pick(engine, "Set Trap", at=(3, 5))
    _walk(engine, foe_id, [(3, 5)])
    foe = engine.state.actors[foe_id]
    assert held(foe, "restrained") and speech.silenced(foe)
    engine._remove_condition(foe, "condition:typed.restrained", "test:escaped")
    assert not speech.silenced(foe)


def test_stop_drop_and_control_with_pursuit_lattice_sets_two_traps_behind_a_disengage():
    """Stop, Drop, and Control: "When you take the Disengage Action, expend Martial Focus to set one trap in an unoccupied space you move
    through during that turn ... This placement does not require an additional Action." Pursuit Lattice: "set up to two traps"."""
    from tests.test_sys_placed_effects import _pick, _walk

    engine, me_id, _ = _trap_scene("TAL_TRAP_STOP_DROP_AND_CONTROL", "TAL_TRAP_PURSUIT_LATTICE")
    me = engine.state.actors[me_id]
    assert "Set Trap (Stop, Drop, and Control)" not in {c.display_name.split(" at ")[0] for c in engine.legal_candidates()}
    _pick(engine, "Disengage")
    _walk(engine, me_id, [(2, 6), (1, 6)])
    _pick(engine, "Set Trap (Stop, Drop, and Control)", at=(3, 6))
    assert me.resources["resource:core.martial_focus"] == 0
    _pick(engine, "Set Trap (Stop, Drop, and Control)", at=(2, 6))
    assert len(_trap_zones(engine)) == 2
    assert "Set Trap (Stop, Drop, and Control)" not in {c.display_name.split(" at ")[0] for c in engine.legal_candidates()}


def test_the_empty_road_places_traps_raises_the_limit_and_relocates_toward_a_mover():
    """The Empty Road Was Never Empty: "place a number of temporary traps equal to your Proficiency Bonus in legal unoccupied spaces within
    the Emanation ... your active trap limit increases by your Proficiency Bonus; once per turn, after a hostile creature moves at least 5
    feet inside the Emanation, relocate one untriggered trap you set to one legal unoccupied space within 10 feet of its previous location"."""
    from combat.ext import states, trap
    from tests.test_sys_placed_effects import _walk

    engine, me_id, foe_id = _trap_scene("TAL_TRAP_THE_EMPTY_ROAD_WAS_NEVER_EMPTY", "TAL_TRAP_COURT_OF_THE_HIDDEN_NAIL", cl=17)
    me, foe = engine.state.actors[me_id], engine.state.actors[foe_id]
    # Its Reaction ("Initiative is rolled, or one hostile creature enters a space within 60 feet") was used as the fight began.
    assert states.active(engine, me, "empty_road_was_never_empty") and len(_trap_zones(engine)) == 4
    assert trap._limit(trap._kit(engine, me), engine, me) == 8
    foe.position = Position(x=9, y=6)
    before = min(engine.grid.distance_ft(z.center, Position(x=9, y=9)) for z in _trap_zones(engine))
    me.reaction_available = True
    _walk(engine, foe_id, [(9, 7), (9, 8), (9, 9)])
    after = min(engine.grid.distance_ft(z.center, foe.position) for z in _trap_zones(engine))
    assert after < before and len(_trap_zones(engine)) == 4  # moved, and the once-a-rest Reaction did not fire again


def test_the_route_was_chosen_already_reveals_concealed_traps_at_initiative():
    """The Route Was Chosen Already: "When Initiative is rolled, reveal up to your Proficiency Bonus concealed traps ... within 60 feet"."""
    from combat.ext import placed

    engine, me_id, foe_id = _trap_scene("TAL_TRAP_THE_ROUTE_WAS_CHOSEN_ALREADY", cl=17)
    zones_now = _trap_zones(engine)
    assert len(zones_now) == 4 and all(foe_id not in (placed.data(z).get("aware") or ()) for z in zones_now)


def test_trap_launcher_sets_a_trap_at_bow_range_for_a_bonus_action():
    """Trap Launcher: "When you expend Martial Focus to set a trap as an Action, use a Bonus Action to launch the trap kit onto one physically
    viable surface within the normal range of one ranged weapon you wield." """
    me = bundle("TAL_TRAP_TRAP_LAUNCHER", cl=10, kit=BOW)
    engine = fight(me, foe_at=(12, 6))
    actor = engine.state.actors[ME]
    actor.resources["resource:core.martial_focus"] = 1
    use(engine, "Set Trap (Trap Launcher)", at=(10, 6))
    assert [(z.center.x, z.center.y) for z in _trap_zones(engine)] == [(10, 6)]
    assert not actor.bonus_action_available and actor.resources["resource:core.martial_focus"] == 0


def test_blunt_dart_can_leave_a_dying_creature_stable(monkeypatch):
    """Blunt Dart: "When this trap reduces a conscious and stable creature to 0 HP, you may choose for that creature to become Unconscious
    and stable rather than dying." """
    from combat.ext import trap
    from tests.test_sys_placed_effects import _pick

    engine, me_id, foe_id = _trap_scene("TAL_TRAP_BLUNT_DART")
    _pick(engine, "Set Trap", at=(3, 5))
    zone = _trap_zones(engine)[0]
    foe = engine.state.actors[foe_id]
    foe.current_hp, foe.life_state = 0, "DYING"
    monkeypatch.setattr(trap, "_ask", lambda *a, **k: ["stable"])
    trap._blunt_knockout(trap._ctx_for(engine, engine.state.actors[me_id], zone), zone, foe)
    assert foe.life_state == "STABLE"
