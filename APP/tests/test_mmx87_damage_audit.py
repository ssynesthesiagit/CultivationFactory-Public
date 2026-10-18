"""MMX87 (owner playtest, round 24, live 42e43e14): three damage bugs in one fight.

Each test fails without the fix it names.

  Bug 1  Axe-Kick Descent added 2d6 to every unarmed hit because its "fall at least
         10 feet, jump down, or descend" condition was display-only free text. The
         rider is one packet: the 2d6 AND "If the target was already Opened, it makes
         a Strength saving throw" (Prone on a failure). Both are gated by the descent.
  Bug 2  A save-area zone rolled 6d6+4: the area's stored numbers carry the caster's
         Qi Technique Potency, which the executor grants to the first damage roll of
         an activation -- the zone's start-of-turn save is a later activation.
  Bug 3  Magma Glob's Molten Terrain patch repeated a paid on-hit rider (Eruption
         Strike, 2 CP, once per turn, "Trigger: You hit a creature") to every creature
         that later entered, with no attack and no cost. The terrain's OWN save damage
         stays: combat/rules/terrain.json gives Molten Terrain a Dexterity save
         "against the creating ability's own damage", half on a success.

The descent tests move the fighter for real (combat/falling) rather than calling the
listener, so they fail if the movement never reaches the engine's event dispatch.
"""

from __future__ import annotations

import importlib
import pytest

L2 = importlib.import_module("tests.test_riders_lane2")
C13 = importlib.import_module("tests.test_riders_c13")
R = importlib.import_module("tests.test_review_sw-lightning")

from combat import ext, zones
from combat.ext import magma_crust
from combat.ext import axe_kick_descent as AX
from combat.gate2_runtime_models import Position

AXE = "TAL_IRON_FIST_AXE_KICK_DESCENT"
STRIKE = "Unarmed Strike (Iron Fist)"
ERUPTION = "TAL_MAGMA_ERUPTION_STRIKE"


def _axe_kick_rolls(events):
    return [e for e in events
            if e.event_type == "DAMAGE_ROLLED" and e.payload.get("damage_label") == "Axe-Kick Descent"]


def _prone(actor):
    return any(c.condition_id.removeprefix("condition:") == "prone" for c in actor.conditions.values())


def _saves(events):
    """The saves a punch asked for. The rider's only save is "If the target was already Opened, it makes a
    Strength saving throw", so the count says whether the whole packet ran or only its damage."""
    return [e for e in events if e.event_type == "SAVE_ROLLED"]


def _drop(engine, feet=10, source="test:jump-down", actor_id=None):
    """A real committed descent: the fighter starts ``feet`` up and steps down through
    combat/falling, which emits the engine's own MOVEMENT_COMMITTED. The fighter gets up again
    afterwards so the next hit is a legal Unarmed Strike; only the descent is under test."""
    from combat.falling import displace

    actor = engine.state.actors[actor_id or L2.ME]
    steps = max(1, feet // 5)
    actor.position = actor.position.model_copy(update={"z": actor.position.z + steps})
    before = len(engine.events)
    displace(engine, actor, -steps, source)
    for condition in list(actor.conditions.values()):
        if condition.condition_id.removeprefix("condition:") == "prone":
            engine._remove_condition(actor, condition.condition_id, source)
    return [e for e in engine.events[before:] if e.event_type == "MOVEMENT_COMMITTED"]


# --------------------------------------------------------------------------- bug 1


def test_axe_kick_punch_without_a_descent_adds_nothing():
    """"When you fall at least 10 feet, jump down, or descend from a higher space and hit a creature with an
    Unarmed Strike before the end of the turn, add 2d6 Bludgeoning or Force damage." Live #579 and #593 added it
    twice on a turn with no fall, jump or drop at all."""
    engine = L2._duel([AXE])
    assert not _axe_kick_rolls(L2.A._use(engine, STRIKE, L2.FOE)), "an ordinary punch added the 2d6"


@pytest.mark.parametrize("feet", [5, 10])
def test_axe_kick_gates_the_whole_rider_on_one_real_descent(feet):
    """The 2d6 and the Strength save/Prone are one rider, so a target that is already Opened gets neither from
    an ordinary punch. The descent pays for exactly one hit: the second punch of the same descent gets nothing."""
    engine = L2._duel([AXE])
    foe = engine.state.actors[L2.FOE]
    L2._open(engine)  # "If the target was already Opened, it makes a Strength saving throw"

    events = L2.A._use(engine, STRIKE, L2.FOE)
    assert not _axe_kick_rolls(events), "an ordinary punch added the 2d6"
    assert not _saves(events), "an ordinary punch still made the Opened target save for the rider's Strength throw"
    assert not _prone(foe), "an ordinary punch still knocked the Opened target Prone"

    assert _drop(engine, feet), "the test's own descent committed no movement"
    L2.A._ready(engine)
    events = L2.A._use(engine, STRIKE, L2.FOE)
    assert len(_axe_kick_rolls(events)) == 1, "a real descent added nothing"
    assert len(_saves(events)) == 1, "a real descent did not run the rider's Opened-target Strength save"
    assert engine.state.actors[L2.ME].turn_flags[AX.SPENT] == AX._turn_stamp(engine)
    assert AX.SPENT not in foe.turn_flags

    L2.A._ready(engine)
    events = L2.A._use(engine, STRIKE, L2.FOE)
    assert not _axe_kick_rolls(events), "one descent paid for a second hit"
    assert not _saves(events), "one descent paid for a second Opened-target save"


def test_axe_kick_descent_expires_at_the_next_turn():
    engine = L2._duel([AXE])
    _drop(engine)
    assert engine.state.actors[L2.ME].turn_flags[AX.FLAG] == AX._turn_stamp(engine)
    engine.state.round_number += 1
    engine._system_start_turn()
    assert AX.FLAG not in engine.state.actors[L2.ME].turn_flags
    assert not _axe_kick_rolls(L2.A._use(engine, STRIKE, L2.FOE))


def test_axe_kick_descent_is_inert_for_a_fighter_without_the_form():
    """The gate answers only for the rider's own rows, so nobody else loses (or gains) the 2d6."""
    engine = L2._duel([])
    _drop(engine)
    assert not _axe_kick_rolls(L2.A._use(engine, STRIKE, L2.FOE))


def test_axe_kick_ignores_walking_along_the_ground():
    """"fall at least 10 feet, jump down, or descend from a higher space": a fighter who only walked never
    descended. (A step DOWN from a ledge is a descent whatever its height -- the printed rule names three
    alternatives, and "descend from a higher space" is the third -- so only level travel is inert here.)"""
    engine = L2._duel([AXE])
    before = len(engine.events)
    engine._append_event("MOVEMENT_COMMITTED", "test:walk", actor_id=L2.ME,  # the engine's own walk payload
                         payload={"destination": {"x": 2, "y": 6, "z": 0}, "path": [{"x": 3, "y": 6, "z": 0}, {"x": 2, "y": 6, "z": 0}],
                                  "cost_ft": 5, "forced": False, "fall_distance_ft": 0})
    assert [e for e in engine.events[before:] if e.event_type == "MOVEMENT_COMMITTED"], "the test's walk committed no movement"
    assert not _axe_kick_rolls(L2.A._use(engine, STRIKE, L2.FOE))


def test_axe_kick_observes_a_descent_committed_inside_another_hook():
    """A real descent is often committed while the engine is already dispatching an event: ending Featherfall
    during the turn-start hook removes the flight condition and settles the fall inside that cascade. A
    root-only subscriber never sees that movement, so the next qualifying hit was refused."""
    assert AX.record_descent in ext._NESTED_HOOKS["event"], "the descent listener is not subscribed to nested events"

    engine = L2._duel([AXE])
    actor = engine.state.actors[L2.ME]

    saved_hooks, saved_nested = list(ext._HOOKS["turn_start"]), set(ext._NESTED_HOOKS["turn_start"])

    @ext.hook("turn_start")
    def _drop_inside_the_cascade(current_engine, current_actor):
        if current_actor.entity_id != actor.entity_id or getattr(current_engine, "_mmx87_dropped", False):
            return
        current_engine._mmx87_dropped = True
        from combat.falling import displace

        current_actor.position = current_actor.position.model_copy(update={"z": current_actor.position.z + 2})
        displace(current_engine, current_actor, -2, "test:nested-descent")

    try:
        L2.A._ready(engine)
        engine._system_start_turn()
    finally:
        ext._HOOKS["turn_start"][:] = saved_hooks
        ext._NESTED_HOOKS["turn_start"] = saved_nested
    assert ext._HOOKS["turn_start"] == saved_hooks
    assert ext._NESTED_HOOKS["turn_start"] == saved_nested
    assert actor.turn_flags.get(AX.FLAG) is not None, "a descent committed inside a hook was not observed"
    assert len(_axe_kick_rolls(L2.A._use(engine, STRIKE, L2.FOE))) == 1, "the nested descent paid for nothing"


def test_axe_kick_keeps_its_descent_when_a_hit_carries_no_rider():
    """The use is spent when the hit that carried the rider is over, not when eligibility is asked. A punch that
    misses never enters the rider's block, so the descent is still there for the next real hit."""
    engine = L2._duel([AXE])
    _drop(engine)
    engine.state.actors[L2.FOE].armor_class = 1000  # the first punch misses
    assert not _axe_kick_rolls(L2.A._use(engine, STRIKE, L2.FOE))
    engine.state.actors[L2.FOE].armor_class = -50
    L2.A._ready(engine)
    assert len(_axe_kick_rolls(L2.A._use(engine, STRIKE, L2.FOE))) == 1, "a missed punch spent the descent"


def test_axe_kick_eligibility_is_a_pure_query():
    """combat/ext/__init__.py requires effect_allowed handlers to be pure queries. Asking twice without running
    any damage must give the same answer both times."""
    engine = L2._duel([AXE])
    _drop(engine)
    actor = engine.state.actors[L2.ME]
    rider = {"type": "extra_damage", "source_modifier": AXE, "dice": {"count": 2, "sides": 6}}

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.engine, ctx.actor = engine, actor
    first = AX.descent_needs_one(ctx, rider)
    second = AX.descent_needs_one(ctx, rider)
    assert first is second is None, "asking the gate changed its own answer"
    assert AX.SPENT not in actor.turn_flags, "asking the gate spent the descent"

    actor.turn_flags[AX.SPENT] = AX._turn_stamp(engine)
    assert AX.descent_needs_one(ctx, rider) is False, "a spent descent still allows the rider"
    assert AX.descent_needs_one(ctx, rider) is False, "asking a spent gate changed its own answer"


def test_denied_axe_kick_packet_preserves_descent_for_an_allowed_hit(monkeypatch):
    engine = L2._duel([AXE])
    _drop(engine)
    actor = engine.state.actors[L2.ME]
    # A later plug-in vetoes the whole packet, after Axe-Kick has answered eligibility.
    def deny(ctx, row):
        return False if row.get("source_modifier") == AXE else None
    with monkeypatch.context() as patch:
        patch.setitem(ext._HOOKS, "effect_allowed", [*ext._HOOKS["effect_allowed"], deny])
        assert not _axe_kick_rolls(L2.A._use(engine, STRIKE, L2.FOE))
    assert AX.SPENT not in actor.turn_flags
    L2.A._ready(engine)
    assert len(_axe_kick_rolls(L2.A._use(engine, STRIKE, L2.FOE))) == 1
    assert actor.turn_flags[AX.SPENT] == AX._turn_stamp(engine)


def test_another_actors_hit_cannot_spend_the_descent(monkeypatch):
    engine = L2._duel([AXE])
    _drop(engine)
    owner, foe = engine.state.actors[L2.ME], engine.state.actors[L2.FOE]
    # Interrupt between this packet's resolution and its attack's final checkpoint.
    # The ordinary other-actor punch supplies its own explicit AttackDamage receipt.
    from combat.typed_executor import block_attack, Context
    from combat.gate2_runtime_models import ActionIntent
    action = next(a for a in engine.action_catalog.values() if a.owner_id == L2.FOE and a.display_name == "Unarmed Strike")
    intent = ActionIntent(intent_id="test:intervening-punch", actor_id=L2.FOE,
                          decision_id="test:intervening", candidate_id="test:intervening", state_version=engine.state.state_version)
    seen = []
    def intervene(current, actor, target, provenance, intent):
        if actor.entity_id != L2.ME:
            return
        foe.armor_class = owner.armor_class = -50
        ctx = Context(current, foe, action, intent, action.parameters["typed"], [owner], owner)
        block_attack(ctx, action.parameters["typed"]["effects"][0])
        seen.append((AX.SPENT in foe.turn_flags, AX.SPENT in owner.turn_flags))
    monkeypatch.setitem(ext._HOOKS, "attack_damage_final", [intervene, *ext._HOOKS["attack_damage_final"]])
    assert len(_axe_kick_rolls(L2.A._use(engine, STRIKE, L2.FOE))) == 1
    assert seen == [(False, False)]
    assert owner.turn_flags[AX.SPENT] == AX._turn_stamp(engine)
    assert AX.SPENT not in foe.turn_flags


def test_failed_completion_rolls_back_the_accepted_rider_receipt(monkeypatch):
    engine = L2._duel([AXE])
    _drop(engine)
    def pause(*args):
        raise ValueError("test:completion-refused")
    with monkeypatch.context() as patch:
        patch.setitem(ext._HOOKS, "attack_damage_final", [pause, *ext._HOOKS["attack_damage_final"]])
        with pytest.raises(ValueError, match="test:completion-refused"):
            L2.A._use(engine, STRIKE, L2.FOE)
    actor = engine.state.actors[L2.ME]
    assert AX.SPENT not in actor.turn_flags
    assert not any(key.startswith(AX.PENDING) for key in actor.turn_flags)
    assert len(_axe_kick_rolls(L2.A._use(engine, STRIKE, L2.FOE))) == 1
    assert actor.turn_flags[AX.SPENT] == AX._turn_stamp(engine)


def test_axe_kick_stays_gated_across_a_table_commit_and_reload(monkeypatch, tmp_path):
    """Real up/down table moves commit eligibility; the first punch commits spending.

    The fixture grants flight through a scoped turn-start hook, without replacing engine
    methods. All movement and both punches use ordinary table candidates and disk reloads.
    """
    import json
    import zipfile

    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from combat.factory_compiler import compile_character
    from tests.h1_support import ROOT

    me, foe = FACTORY_ACTOR_PREFIX + "mmx87-me", FACTORY_ACTOR_PREFIX + "mmx87-foe"
    bundles = []
    for actor_id, talents in ((me, [AXE, L2.FLURRY]), (foe, [])):
        doc = L2.A._sheet(L2.IRON_FIST, talents, L2.KIT, cl=10, dc=50)
        doc["identity"]["display_name"] = actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
        folder = tmp_path / "portable_characters" / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=actor_id))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    ext.effects()
    def flight_fixture(engine, actor):
        if actor.entity_id == me:
            engine._apply_condition(actor, "condition:typed.test_flight", "test:flight", me,
                                    expires_on="END_OF_CURRENT_TURN", data={"fly_speed_ft": 30, "flight_hover": 1})
    monkeypatch.setitem(ext._HOOKS, "turn_start", [*ext._HOOKS["turn_start"], flight_fixture])
    mid = combat._finish_factory_match(
        bundles, [me, foe], {me: "team:a", foe: "team:b"}, {me: {"x": 3, "y": 6}, foe: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [me], [],
        control_modes={me: "MANUAL", foe: "MANUAL"}, match_seed="MMX87F1",
        display_name="Axe-Kick descent reload", maximum_rounds=10)["match_id"]

    def act(candidate_id):
        for _ in range(16):
            menu = table.state(mid)["menu"]
            result = table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], 0, [])
            if result["status"] == "COMMITTED":
                return result
            raise AssertionError(f"the table asked for a reaction instead of committing: {result['status']}")

    def strike(label=STRIKE):
        return next(option["candidate_id"] for group in table.state(mid)["menu"]["actions"]
                    if group["label"] == label for option in group["options"])

    while table.state(mid)["menu"]["actor_id"] != me:
        act(table.state(mid)["menu"]["end_turn"])

    def move(z):
        loaded = combat._load_session(mid).engine
        destination = loaded.state.actors[me].position.model_copy(update={"z": z})
        candidate = next(c for c in loaded.legal_candidates() if c.kind == "MOVE" and c.destination == destination)
        act(candidate.candidate_id)

    move(2)
    move(0)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    stamp = AX._turn_stamp(engine)
    assert engine.state.actors[me].turn_flags[AX.FLAG] == stamp
    assert AX.SPENT not in engine.state.actors[me].turn_flags
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == me
               and (e.payload.get("path") or [{}])[0].get("z") == 2 for e in engine.events)
    act(strike())

    def axe_kick_damage():
        engine = combat._load_session(mid).engine
        return [e for e in engine.events if e.event_type == "DAMAGE_ROLLED"
                and e.payload.get("damage_label") == "Axe-Kick Descent"]

    assert len(axe_kick_damage()) == 1
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = session.engine
    assert engine.state.actors[me].turn_flags[AX.SPENT] == stamp
    assert type(engine.state.actors[me].turn_flags[AX.FLAG]) is int
    assert type(engine.state.actors[me].turn_flags[AX.SPENT]) is int
    assert not any(key.startswith(AX.PENDING) for key in engine.state.actors[me].turn_flags)
    act(strike(L2.FLURRY_STRIKE))
    assert len(axe_kick_damage()) == 1, "a second hit after table reload reused the descent"
    assert combat._load_session(mid).mechanical.replay()["status"] == "PASS"


# --------------------------------------------------------------------------- bug 2


def test_a_zone_save_does_not_reuse_the_caster_activation_potency():
    """Live #950 rolled "6d6+4" for Blackglass River. Printed: "Take 6d6 Fire damage and 2d6 Slashing damage" --
    no ability modifier. Qi Technique Potency is "once per activation, when a Qi-powered feature deals damage";
    the area's start-of-turn save is a later activation, not the one that placed the area."""
    _, engine, me, _ = R._fight("TAL_MAGMA_BLACKGLASS_RIVER")
    R._cast(engine, "Blackglass River")
    zone = next(z for z in __import__("combat.zones", fromlist=["x"]).typed_zones(engine)
                if z.trigger_profile.get("name") == "Blackglass River")
    # The compiled area keeps the creator's numbers, potency included.
    zone.trigger_profile["numbers"]["potency"] = 4
    engine.end_turn()
    assert R._damage(engine) == ["6d6", "2d6"], "the area's save borrowed the placing activation's key modifier"


# --------------------------------------------------------------------------- bug 3


def _terrain_damage_rows(zone):
    rows = []
    for trigger in zone.trigger_profile.get("triggers") or []:
        for effect in trigger.get("effects") or []:
            rows.extend(r for r in (effect.get("on_fail") or []) if r.get("type") in ("damage", "extra_damage"))
    return rows


def _cp_pool(actor):
    from combat.ext.rider_support import cp_pool

    return cp_pool(actor)


@pytest.mark.parametrize("trigger", ["enter", "start"])
def test_magma_glob_patch_keeps_its_terrain_save_and_fires_no_eruption_strike(trigger):
    """Live #961-966: walking onto the patch ran Eruption Strike 2d8 with no attack roll and no 2 CP. The rider is
    the rider's own rule, with its own trigger and cost, and the ground it leaves is not a hit. The patch still
    keeps Molten Terrain's own printed save: combat/rules/terrain.json -- "a creature entering it ... makes a
    Dexterity saving throw -- the talent's damage on a failure, half on a success"."""
    engine, me, foe = C13._fight(C13.MAGMA, talents=(ERUPTION,), cl=10, foe_at=(8, 6))
    C13._use(engine, "Magma Glob: Molten Terrain Patch", contains=True)
    pool = _cp_pool(me)
    me.resources[pool] = 5

    (patch,) = magma_crust.patches(engine, me, "molten")
    rows = _terrain_damage_rows(patch)
    assert [r for r in rows if r.get("dice_by_cl")], "the patch lost Molten Terrain's own save damage"
    assert not [r for r in rows if r.get("source_modifier")], "the patch repeated a paid rider's damage"

    # Printed Magma Glob is a single-target attack, not a separate cast area.
    assert not [z for z in engine.state.zones.values() if z.trigger_profile.get("name") == "Magma Glob"]

    before_hp, before_events = foe.current_hp, len(engine.events)
    cell = patch.affected_cells[0]
    foe.position = cell if isinstance(cell, Position) else Position(x=cell["x"], y=cell["y"], z=0)
    zones.fire_trigger(engine, patch, foe, trigger)
    terrain_events = engine.events[before_events:]
    assert foe.current_hp < before_hp, "walking onto Molten Terrain dealt no damage at all"
    assert not [e for e in terrain_events if e.event_type == "DAMAGE_ROLLED"
                and ERUPTION in str(e.payload.get("display_source_id"))], "Eruption Strike fired from the terrain"
    assert me.resources[pool] == 5, "the terrain spent the caster's CP"


def test_terrain_damage_rows_are_independent_deep_copies():
    from combat.ext.terrain_damage import own_damage_rows
    original = [{"type": "attack", "on_hit": [
        {"type": "damage", "dice": {"count": 2, "sides": 10}, "dice_by_cl": {"5": {"count": 2}}},
        {"type": "save", "source_modifier": ERUPTION, "on_fail": [{"type": "damage", "dice": {"count": 2}}]},
    ]}]
    rows = own_damage_rows(original)
    assert len(rows) == 1
    rows[0]["dice"]["count"] = 99
    rows[0]["dice_by_cl"]["5"]["count"] = 99
    assert original[0]["on_hit"][0]["dice"]["count"] == 2
    assert original[0]["on_hit"][0]["dice_by_cl"]["5"]["count"] == 2


def test_eruption_strike_still_costs_two_cp_on_a_real_hit():
    """"Trigger: You hit a creature or object with Magma Glob ... Cost 2 CP ... Use Limit: Once per turn" -- the paid
    rider stays purchasable on a real hit, and it is the rider, not the ground, that spends the CP."""
    engine, me, foe = C13._fight(C13.MAGMA, talents=(ERUPTION,), cl=10, foe_at=(8, 6))
    pool = _cp_pool(me)
    me.resources[pool] = 5
    C13._use(engine, "Magma Glob: Molten Terrain Patch + Eruption Strike: Heat Pressure", contains=True)
    assert me.resources[pool] == 3, "a paid Eruption Strike on a real hit did not cost its 2 CP"
    assert [e for e in engine.events if e.event_type == "DAMAGE_ROLLED"
            and ERUPTION in str(e.payload.get("display_source_id"))], "the paid rider dealt no damage"
