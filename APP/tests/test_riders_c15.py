"""Rider lane C15 (owner 2026-09-30: "i want everything we can automated, keep going until its only the non-combat ones
left"): the next shared systems from the blocked-line census (/var/tmp/auto-audit/fix/BLOCKED_CENSUS.md) and the lines they
unblock. Every system runs on real compiled characters on a Gate4 engine; the table cases (manual and AI turns) go through the
combat service, commit, reload the saved fight from disk and check its mechanical replay. C15_OLD=1 swaps in the authority of
the base commit (riders/c15 after its merges, 3d5fedfe): the typing cases then fail, because the base typing has none of the
new rows.

Overrides: authority/typed_mechanics/reviewed_final.d/riders_c15.json, combat/rules/feature_blocks.d/riders_c15.json.
Row 31 (why a hold ended; Chains Bound, Tethers, Chain Objects, Prisoner's Bell): combat/ext/hold_escapes.py,
combat/ext/chains_sphere.py, the tether limit in combat/ext/move_limits.py.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

import combat.factory_compiler as compiler
from combat import typed_executor as te
from combat.ext import bound_objects, escape_options, hold_escapes
from combat.gate2_runtime_models import Position
from tests import test_riders_c4 as C4
from tests.h1_support import ROOT

BASE_COMMIT = "3d5fedfe"
ME, FOE, ALLY = C4.ME, C4.FOE, C4.ALLY
FAIL, PASS = C4.FAIL, C4.PASS
CH = "tianxia.talent.chains."
TETHER, PRISON, SHACKLE, MANACLE = "TAL_CHAINS_SET_TETHER_BASE", CH + "chain_prison", CH + "shackling_chain", CH + "manacle_method"
BELL, HOOK = CH + "prisoner_s_bell", CH + "restraining_hook"
BOUND = "condition:typed.bound"


@pytest.fixture(autouse=True, scope="session")
def base_typing(tmp_path_factory):
    if os.environ.get("C15_OLD"):
        path = tmp_path_factory.mktemp("authority") / "base.json"
        path.write_bytes(subprocess.check_output(["git", "show", f"{BASE_COMMIT}:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"], cwd=ROOT))
        compiler.TYPED_AUTHORITY = path


def mech(key):
    return json.loads(compiler.TYPED_AUTHORITY.read_bytes())["mechanics"][key]


def force_d20(engine, natural, *, actor_id=None, reason=None):
    """Every d20 rolled from now on (by ``actor_id``, for a reason starting with ``reason``) shows ``natural``."""
    original = getattr(engine.roller, "_real_d20", None) or engine.roller.d20
    engine.roller._real_d20 = original

    def d20(**kwargs):
        wanted = natural if (actor_id in (None, kwargs.get("actor_id"))
                             and (reason is None or str(kwargs.get("reason") or "").startswith(reason))) else None
        while True:
            roll = original(**kwargs)
            if wanted is None or int(roll.natural_result) == wanted:
                return roll

    engine.roller.d20 = d20


def notes(events):
    return [str((e.payload or {}).get("log") or "") for e in events if e.event_type == "PASSIVE_TRIGGERED"]


def bound(actor):
    return [c for c in actor.conditions.values() if c.condition_id == BOUND]


def chains(*talents, cl=12, dc=FAIL, actor_id=ME):
    return C4.bundle(*talents, cl=cl, dc=dc, actor_id=actor_id)


def tethered(**kw):
    """ME Set the Tether on FOE (failed save): Bound, 30-foot tether to ME."""
    engine = C4.fight(chains(TETHER, BELL, HOOK, **kw), foe_at=(5, 6))
    C4.use(engine, "Set the Tether", target=FOE)
    return engine


# ======================================================================================= row 31: Chains Bound and Tethers
def test_set_the_tether_typing_carries_the_tether_and_drops_its_gm_lines():
    row = mech(TETHER)["effects"][0]["on_fail"][0]
    assert row["condition"] == "bound" and row["condition_data"] == {"tether_ft": 30}
    assert not [r for r in mech(TETHER)["riders"] if r.startswith(("The Tether has a maximum length", "Failed Save: The target becomes Bound"))]


def test_bound_is_speed_ten_lower_no_dash_and_it_cannot_walk_past_its_tether():
    engine = tethered()
    foe = engine.state.actors[FOE]
    (held,) = bound(foe)
    assert held.data["tether_ft"] == 30 and held.source_actor_id == ME
    C4.turn(engine, FOE)
    assert engine._effective_speed(foe) == 20  # 30 - 10
    names = C4.legal(engine)
    assert "Dash" not in names
    me = engine.state.actors[ME]
    moves = [c for c in engine.legal_candidates() if getattr(c.kind, "value", c.kind) == "MOVE" and c.destination is not None]
    assert moves and all(engine.grid.distance_ft(c.destination, me.position) <= 30 for c in moves)


def test_an_unbound_creature_moves_as_before():
    engine = C4.fight(chains(TETHER), foe_at=(5, 6))
    C4.turn(engine, FOE)
    assert engine._effective_speed(engine.state.actors[FOE]) == 30 and "Dash" in C4.legal(engine)


def test_a_push_past_the_tether_breaks_it_and_the_bell_hears_forced_movement():
    engine = tethered()
    foe = engine.state.actors[FOE]
    me = engine.state.actors[ME]
    ctx = te.Context(engine, me, next(iter(engine.action_catalog.values())), None, {"numbers": {"pb": 4}}, [foe], foe, {})
    before = len(engine.events)
    te.block_forced_movement(ctx, {"type": "forced_movement", "distance_ft": 40, "direction": "away", "applies_to": "target"})
    assert engine._distance_actor_to_actor(me, foe) > 30
    assert not bound(foe)
    removed = [e.payload for e in engine.events[before:] if e.event_type == "CONDITION_REMOVED" and e.payload.get("condition_id") == BOUND]
    assert removed and removed[0]["reason"] == "TETHER_BROKEN"
    lines = notes(engine.events[before:])
    assert any("tether between" in line and "breaks" in line for line in lines)
    assert any(line.startswith("Prisoner's Bell: ") and "escaped" in line and "Set the Tether by being moved out of it" in line for line in lines)


def test_a_teleport_past_the_tether_breaks_it_as_a_teleport_escape():
    engine = tethered()
    foe = engine.state.actors[FOE]
    ctx = te.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {}}, [], None, {})
    before = len(engine.events)
    te._teleport(ctx, Position(x=13, y=6))  # 50 feet from ME
    assert not bound(foe)
    assert any("Set the Tether by teleporting away" in line for line in notes(engine.events[before:]))


def test_a_teleport_inside_the_tether_keeps_it():
    engine = tethered()
    foe = engine.state.actors[FOE]
    ctx = te.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {}}, [], None, {})
    te._teleport(ctx, Position(x=7, y=6))  # 20 feet from ME
    assert bound(foe)


def test_bound_gives_disadvantage_on_its_escape_check_and_manacle_offers_athletics_or_acrobatics():
    engine = C4.fight(chains(MANACLE), foe_at=(4, 6))
    C4.use(engine, "Manacle Method", target=FOE)
    foe = engine.state.actors[FOE]
    assert bound(foe)
    ((key, record),) = escape_options.options(foe)
    assert record.data["abilities"] == ["STR", "DEX"] and record.data["skills"] == {"STR": "Athletics", "DEX": "Acrobatics"}
    assert "Strength (Athletics) or Dexterity (Acrobatics) check" in record.data["label"]
    C4.turn(engine, FOE)
    events = C4.use(engine, "Break free")
    (check,) = C4.payloads(events, "CHECK_ROLLED")
    assert check["actor"]["mode"] == "DISADVANTAGE"
    assert "(Athletics)" in check["check"] or "(Acrobatics)" in check["check"]


# ============================================================================================== row 31: Chain Objects
def test_chain_prison_is_a_chain_object_of_ac_17_and_eight_times_cl():
    engine = C4.fight(chains(PRISON, cl=12), foe_at=(6, 6))
    C4.use(engine, "Chain Prison", target=FOE)
    (obj,) = [o for o in engine.state.objects.values() if bound_objects.bound(o)]
    assert (obj.ac, obj.maximum_hp) == (17, 96) and obj.object_kind == "BOUND_CHAIN"
    assert set(obj.component["resist"]) == {"BLUDGEONING", "PIERCING", "SLASHING"}
    assert {"POISON", "PSYCHIC"} <= set(obj.damage_immunities)


def test_shackle_has_the_default_chain_object_numbers():
    engine = C4.fight(chains(SHACKLE, cl=12), foe_at=(6, 6))
    C4.use(engine, "Shackling Chain", target=FOE)
    (obj,) = [o for o in engine.state.objects.values() if bound_objects.bound(o)]
    assert (obj.ac, obj.maximum_hp) == (15 + 4 // 2, 5 * 12)
    ((key, record),) = escape_options.options(engine.state.actors[FOE])
    assert record.data["name"] == "Shackling Chain"


@pytest.mark.parametrize("talent,name", [(PRISON, "Chain Prison"), (SHACKLE, "Shackling Chain")])
def test_a_successful_initial_save_leaves_it_bound_until_the_start_of_its_next_turn(talent, name):
    engine = C4.fight(chains(talent, dc=PASS), foe_at=(6, 6))
    C4.use(engine, name, target=FOE)
    foe = engine.state.actors[FOE]
    assert bound(foe) and not [c for c in foe.conditions.values() if c.condition_id.endswith("restrained")]
    objects = [o for o in engine.state.objects.values() if bound_objects.bound(o)]
    # "The shackle is a Chain Object. Destroying it ends the effect."
    # This applies to the successful-save Bound branch too.
    assert bool(objects) == (talent == SHACKLE)
    C4.turn(engine, FOE)
    assert not bound(foe)


def test_chain_prisons_repeat_save_success_leaves_it_bound_until_the_start_of_its_next_turn():
    engine = C4.fight(chains(PRISON), foe_at=(6, 6))
    C4.use(engine, "Chain Prison", target=FOE)
    foe = engine.state.actors[FOE]
    C4.turn(engine, FOE)
    foe.saving_throws["STR"] = 100  # its end-of-turn repeat save succeeds
    engine.end_turn()
    assert not [c for c in foe.conditions.values() if c.condition_id.endswith("restrained")]
    assert bound(foe)
    while engine.state.current_actor_id != FOE:
        engine.end_turn()
    assert not bound(foe)


@pytest.mark.parametrize("breaker,how", [(FOE, "by physical effort"), (ALLY, "with outside help")])
def test_destroying_the_chain_prison_frees_the_prisoner_and_the_bell_names_who_broke_it(breaker, how):
    engine = C4.fight(chains(PRISON, BELL, HOOK), foe_at=(6, 6),
                      ally=C4.bundle(actor_id=ALLY, cl=5), ally_at=(7, 6))
    engine.state.actors[ALLY].team_id = "team:b"  # the prisoner's friend
    C4.use(engine, "Chain Prison", target=FOE)
    (obj,) = [o for o in engine.state.objects.values() if bound_objects.bound(o)]
    from combat.ext import objects

    before = len(engine.events)
    objects.deal(engine, engine.state.actors[breaker], obj, [(500, "FORCE")], "test:break")
    foe = engine.state.actors[FOE]
    assert not [c for c in foe.conditions.values() if c.condition_id.endswith("restrained")]
    lines = notes(engine.events[before:])
    assert any(line.startswith("Prisoner's Bell: ") and f"Chain Prison {how}" in line for line in lines), lines
    assert any("destroyed the Chain Object" in line for line in lines) == (breaker == ALLY)


# ============================================================================================ row 31: the escape report
def test_no_listener_no_report_and_no_event(monkeypatch):
    """Inert: a fight with no Prisoner's Bell writes nothing extra when a grapple is escaped."""
    seen = []
    engine = C4.fight(chains(SHACKLE, dc=16), foe_at=(6, 6))
    force_d20(engine, 1, actor_id=FOE, reason="SAVE:")
    C4.use(engine, "Shackling Chain", target=FOE)
    monkeypatch.setattr(hold_escapes, "run", lambda point, *a: seen.append(a) or [])
    C4.turn(engine, FOE)
    force_d20(engine, 20, actor_id=FOE, reason="CHECK:")
    events = C4.use(engine, "Break free")
    assert seen and seen[0][1]["how"] == "physical" and seen[0][1]["way"] == "check"
    assert not [line for line in notes(events) if "Prisoner's Bell" in line]


def test_how_for_reads_the_printed_kinds():
    assert hold_escapes.how_for("STR", ME) == "physical" and hold_escapes.how_for("CHA", ME) == "spiritual"
    assert hold_escapes.how_for("STR", ME, ALLY) == "outside_assistance"
    assert hold_escapes.movement_how({"teleport": True}) == "teleportation"
    assert hold_escapes.movement_how({"forced": True}) == "forced_movement"


# ================================================================== row 31: Prisoner's Bell at the table (commit, reload)
def _bell_table(tmp_path, monkeypatch):
    from combat.gate2_rolls import DeterministicRollAuthority
    from tests.r1i_service_support import FOE as T_FOE, OWNER, SECOND, candidate, fixture

    real_d20 = DeterministicRollAuthority.d20

    def dice(roller, **kwargs):
        # Test-only dice: the foe fails every save and passes every check; adjudication and recorded rolls stay real.
        reason = str(kwargs.get("reason") or "")
        wanted = (1 if reason.startswith("SAVE:") else 20 if reason.startswith("CHECK:") else None) if kwargs.get("actor_id") == T_FOE else None
        while True:
            roll = real_d20(roller, **kwargs)
            if wanted is None or roll.natural_result == wanted:
                return roll

    monkeypatch.setattr(DeterministicRollAuthority, "d20", dice)
    combat, table, mid, send, commit = fixture(tmp_path, [SHACKLE, BELL, HOOK], owner_dc=16,
                                               positions={OWNER: {"x": 3, "y": 6}, T_FOE: {"x": 4, "y": 6}, SECOND: {"x": 8, "y": 6}})
    commit(candidate(table, mid, "Shackling Chain", T_FOE))
    while table.state(mid)["menu"]["actor_id"] != T_FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    return combat, table, mid, send, commit, candidate


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("accept", [True, False])
def test_prisoners_bell_rings_and_offers_a_free_restraining_hook_at_the_table(tmp_path, monkeypatch, auto_turn, accept):
    from tests.r1i_service_support import FOE as T_FOE, OWNER, force_ai_candidate
    from tests.test_r1i_round3 import reload, resolve

    combat, table, mid, send, commit, candidate = _bell_table(tmp_path, monkeypatch)
    engine = reload(tmp_path, mid)
    assert escape_options.options(engine.state.actors[T_FOE])
    assert [o for o in engine.state.objects.values() if bound_objects.bound(o) and not o.destroyed]
    qi = dict(engine.state.actors[OWNER].resources)
    assert engine.state.actors[OWNER].reaction_available
    cid = candidate(table, mid, "Break free")
    if auto_turn:
        force_ai_candidate(combat, mid, T_FOE, cid)
    before = len(engine.events)
    _, prompts = resolve(combat, mid, send, cid, {"choice:needle.escape_ability": "STR",
                                                  "choice:needle.prisoners_bell": T_FOE if accept else None}, auto=auto_turn)
    bell = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.prisoners_bell"]
    assert len(bell) == 1  # the owner is a player: asked, on the foe's manual turn and on its AI turn alike
    assert "Restraining Hook" in json.dumps(bell[0])
    assert "without spending cultivation points (your Path resource)" in json.dumps(bell[0])
    assert all("no cultivation points (your Path resource)" in option["label"]
               and " CP" not in option["label"] for option in bell[0]["choice"]["options"])
    engine = reload(tmp_path, mid)
    foe, owner = engine.state.actors[T_FOE], engine.state.actors[OWNER]
    new = engine.events[before:]
    assert not [c for c in foe.conditions.values() if c.condition_id.endswith("restrained")]
    assert not [o for o in engine.state.objects.values() if bound_objects.bound(o) and not o.destroyed]
    lines = notes(new)
    assert any(line.startswith("Prisoner's Bell: ") and "Shackling Chain by physical effort" in line
               and "hears the chain-bell" in line for line in lines), lines
    hooked = [e for e in new if e.event_type == "SAVE_ROLLED" and e.actor_id == T_FOE and "restraining_hook" in str(e.payload.get("reason"))]
    assert bool(hooked) == accept
    assert owner.reaction_available == (not accept)
    assert dict(owner.resources) == qi  # no CP for the hook
    assert bool(owner.turn_flags.get("_round_prisoners_bell_free_hook")) == accept


def test_an_ai_owner_uses_the_bells_free_hook_without_being_asked(tmp_path, monkeypatch):
    from tests.r1i_service_support import FOE as T_FOE, OWNER
    from tests.test_r1i_round3 import reload, resolve

    combat, table, mid, send, commit, candidate = _bell_table(tmp_path, monkeypatch)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    cid = candidate(table, mid, "Break free")
    _, prompts = resolve(combat, mid, send, cid, {"choice:needle.escape_ability": "STR"})
    assert not [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.prisoners_bell"]
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].turn_flags.get("_round_prisoners_bell_free_hook")
    assert not engine.state.actors[OWNER].reaction_available


def test_the_bells_free_hook_is_once_a_fight():
    engine = C4.fight(chains(SHACKLE, BELL, HOOK, dc=16), foe_at=(5, 6))
    force_d20(engine, 1, actor_id=FOE, reason="SAVE:")
    force_d20(engine, 20, actor_id=FOE, reason="CHECK:")
    me = engine.state.actors[ME]
    for _ in range(2):
        C4.turn(engine, ME)
        C4.use(engine, "Shackling Chain", target=FOE)
        C4.turn(engine, FOE)
        me.reaction_available = True
        events = C4.use(engine, "Break free")
        assert any(line.startswith("Prisoner's Bell: ") for line in notes(events))
    hooks = [line for line in notes(engine.events) if "uses Restraining Hook" in line]
    assert len(hooks) == 1


# ===================================== merge reconciliation: one size_steps contract (riders/c7 + rider lane C12)
def test_constellation_circuit_counts_one_size_larger_resisting_a_push_under_the_unified_role_names():
    """nine_star answered role "target", which neither caller passes; the unified contract's resisting role is "subject"."""
    from tests import test_riders_c7 as C7

    engine, me, foe = C7._nine(["constellation_circuit"], marks=3)
    ctx = te.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {"pb": 4}}, [me], me, {})
    push = {"type": "forced_movement", "distance_ft": 10, "direction": "away", "applies_to": "target"}
    assert te.size_width(ctx, me, "subject", push) == engine._footprint(me).width_cells + 1
    assert te.size_width(ctx, me, "subject", {"type": "save", "on_fail": [push]}) == engine._footprint(me).width_cells + 1
    assert te.size_width(ctx, me, "actor", push) == engine._footprint(me).width_cells  # its own push: no step


def test_body_heavying_and_a_c7_step_add_up_on_one_comparison():
    """Different features combine (D&D 5.5e): Gravity's Body Heavying (C12) and a C7 owner's step on the same creature."""
    from combat import ext
    from tests import test_riders_c2 as C2

    engine = C2._fight(C2._bundle(["TAL_GRAVITY_WEIGHT_SHIFT_BASE"]))
    C2._act(engine, "Weight Shift: Body Heavying")
    me, foe = engine.state.actors[C2.ME], engine.state.actors[C2.L1.AN]
    ctx = te.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {"pb": 4}}, [me], me, {})
    push = {"type": "forced_movement", "distance_ft": 10, "direction": "away", "applies_to": "target"}
    assert te.size_width(ctx, me, "subject", push) == engine._footprint(me).width_cells + 1
    extra = lambda engine, creature, role, purposes: 1 if creature is me and role == "resist" else None  # noqa: E731
    ext._HOOKS.setdefault("size_steps", []).append(extra)
    try:
        assert te.size_width(ctx, me, "subject", push) == engine._footprint(me).width_cells + 2
    finally:
        ext._HOOKS["size_steps"].remove(extra)


# ================================================================================ row 17: reaction economy
from combat import typed_reactions  # noqa: E402
from combat.ext import reaction_economy  # noqa: E402

SOV, STATIC = "TAL_LIGHTNING_LIGHTNING_SOVEREIGN_INCARNATION", "TAL_LIGHTNING_STATIC_GUARD"
ADAMANT, SCOUNDREL_SOV = "TAL_GUARDIAN_ADAMANT_GUARDIAN_INCARNATION", "TAL_SCOUNDREL_SOVEREIGN_OF_TEN_THOUSAND_EMPTY_SLEEVES"
FATE_SOV, TWIST = "TAL_FATE_FATE_SOVEREIGN_INCARNATION", "TAL_FATE_TWIST_OF_FATE"


def guarded(*talents, state=None):
    """ME (Static Guard + ``talents``, AC 1) next to an axe-armed FOE; ``state``: ME starts that incarnation first."""
    engine = C4.fight(C4.bundle(STATIC, *talents, cl=17), foe=C4.armed_foe(), foe_at=(4, 6))
    me = engine.state.actors[ME]
    if state:
        C4.use(engine, state)
    me.armor_class = 1
    force_d20(engine, 15, actor_id=FOE, reason="ATTACK")
    return engine, me


def foe_hits(engine):
    """FOE makes one axe attack on ME (a fresh Action each time, the same round); the Static Guard answers it returns."""
    events = C4.foe_attacks(engine, ME)
    return [e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == STATIC]


def test_row17_lines_are_typed_and_no_longer_gm_riders():
    for key, line in [(SOV, "You may use Static Guard without spending"), (ADAMANT, "gain one additional Reaction each round"),
                      (FATE_SOV, "Once per round, you may use Twist of Fate without spending CP")]:
        assert not [r for r in mech(key)["riders"] if r.startswith(line)]
    assert any(e.get("type") == "state" and e.get("name") == "adamant_guardian_incarnation" for e in mech(ADAMANT)["effects"])


def test_static_guard_is_free_once_a_round_under_lightning_sovereign_incarnation():
    engine, me = guarded(SOV, state="Lightning Sovereign Incarnation")
    assert foe_hits(engine)
    assert me.reaction_available  # the first Static Guard this round did not spend it
    assert me.turn_flags[reaction_economy.FLAG + SOV] == engine.state.round_number
    assert any("without spending its Reaction" in line for line in notes(engine.events))
    engine.state.actors[FOE].action_available = True
    assert foe_hits(engine)  # the second spends the Reaction
    assert not me.reaction_available
    engine.state.actors[FOE].action_available = True
    assert not foe_hits(engine)  # nothing left this round


def test_without_the_incarnation_static_guard_spends_the_reaction():
    engine, me = guarded(SOV)
    assert foe_hits(engine) and not me.reaction_available
    engine.state.actors[FOE].action_available = True
    assert not foe_hits(engine)


def test_adamant_guardian_gives_one_additional_reaction_each_round():
    engine, me = guarded(ADAMANT, state="Adamant Guardian Incarnation")
    assert foe_hits(engine) and not me.reaction_available  # the ordinary Reaction first
    engine.state.actors[FOE].action_available = True
    events_before = len(engine.events)
    assert foe_hits(engine)  # the additional one
    assert any("additional Reaction" in line for line in notes(engine.events[events_before:]))
    engine.state.actors[FOE].action_available = True
    assert not foe_hits(engine)  # one additional a round, no more


def test_scoundrel_sovereigns_extra_reaction_is_only_for_scoundrel_talents():
    engine, me = guarded(SCOUNDREL_SOV)
    engine._apply_condition(me, "condition:typed.state.sovereign_of_ten_thousand_empty_sleeves", SCOUNDREL_SOV, ME, expires_on="UNTIL_REMOVED")
    me.reaction_available = False
    static_row = next(r for r in typed_reactions._rows(engine, ME, "generic") if r["feature_id"] == STATIC)
    assert not typed_reactions.reaction_waived(engine, me, static_row)  # Lightning: not a Scoundrel talent
    scoundrel_row = {**static_row, "feature_id": "TAL_SCOUNDREL_COUNTER_THEFT"}
    assert reaction_economy._sphere("TAL_SCOUNDREL_COUNTER_THEFT") == "tianxia.sphere.scoundrel"
    assert typed_reactions.reaction_waived(engine, me, scoundrel_row)
    me.reaction_available = True
    assert not typed_reactions.reaction_waived(engine, me, scoundrel_row)  # the ordinary Reaction first


def test_fate_sovereign_makes_twist_of_fate_cost_nothing_while_it_lasts():
    engine = C4.fight(C4.bundle(FATE_SOV, TWIST, cl=17))
    price = lambda: next(r for r in typed_reactions._ordered_generic_rows(engine, ME, "creature_d20") if r["feature_id"] == TWIST)["costs"]  # noqa: E731
    assert price()  # its CP cost
    C4.use(engine, "Fate-Sovereign Incarnation: Attack Penalty")  # any option: each carries the state
    assert price() == []


def test_a_punchline_row_is_covered_by_the_courts_grant():
    grant = {"covers": {"punchline": True}}
    assert reaction_economy.covers(grant, {"feature_id": "x", "requires_mark": "Foil: Strike the Fool"})
    assert not reaction_economy.covers(grant, {"feature_id": "x", "requires_mark": None})
    from combat.ext import jester_riders

    assert reaction_economy.covers(grant, jester_riders._punchline_row(None, "tianxia.talent.jester.a_fine_display"))


def test_no_grant_no_change():
    engine, me = guarded()
    row = next(r for r in typed_reactions._rows(engine, ME, "generic") if r["feature_id"] == STATIC)
    me.reaction_available = False
    assert not typed_reactions.reaction_waived(engine, me, row) and not typed_reactions._can_trigger(engine, me, row)


@pytest.mark.parametrize("auto_turn", [False, True])
def test_free_static_guard_at_the_table_survives_commit_and_reload(tmp_path, auto_turn):
    from tests.r1i_service_support import FOE as T_FOE, OWNER, SECOND, candidate, fixture, force_ai_candidate
    from tests.test_r1i_round3 import reload

    combat, table, mid, send, commit = fixture(tmp_path, [SOV, STATIC], owner_ac=1, foe_talents=["tianxia.path.body_refining.feature.iron_fist"],
                                               positions={OWNER: {"x": 3, "y": 6}, T_FOE: {"x": 4, "y": 6}, SECOND: {"x": 3, "y": 7}})
    commit(candidate(table, mid, "Lightning Sovereign Incarnation"))
    while table.state(mid)["menu"]["actor_id"] != T_FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Iron Fist attack", OWNER)
    if auto_turn:
        force_ai_candidate(combat, mid, T_FOE, cid)
    answers = []
    for _ in range(12):  # the owner is asked whether to use Static Guard: yes
        result = send(cid, answers, auto=auto_turn)
        if result["status"] == "COMMITTED":
            break
        p = result["reaction"]
        answer = {**p["context"], "selection": "USE"}
        if p.get("choice"):
            answer["option_ids"] = (p["choice"].get("preferred") or [p["choice"]["options"][0]["id"]])[:1]
        answers.append(answer)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    guards = [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == STATIC]
    if not guards:
        pytest.skip("the foe's strike missed AC 1 (natural 1)")
    assert owner.reaction_available and owner.turn_flags[reaction_economy.FLAG + SOV] == engine.state.round_number
    assert any("uses Static Guard without spending its Reaction" in line for line in notes(engine.events))


# ======================================================================== row 23: removing only Advantage / one Disadvantage
from combat.ext import attack_mode_removal, critical_hits, healing_interception  # noqa: E402

PIERCING, STORM = "TAL_THE_HIDDEN_EYE_PIERCING_SENSES", "TAL_AIR_STORM_WITHOUT_DIRECTION"
AXE, BOW = C4.AXE, C4.BOW
BOTH = {"starting_kit": {"items": AXE["starting_kit"]["items"] + BOW["starting_kit"]["items"]}}


def attack_modes(events, attacker=ME):
    return [str((e.payload or {}).get("mode")) for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == attacker]


def strike(engine, name, target=FOE):
    C4.turn(engine, ME)
    return attack_modes(C4.use(engine, name, target=target))


def test_piercing_senses_typing_is_a_passive_without_the_parser_attacks():
    entry = mech(PIERCING)
    assert entry["effects"] == []  # the parser's two "attack" rows made the target Invisible on a hit
    assert not [r for r in entry["riders"] if r.startswith("you do not have Disadvantage on that attack roll solely because")]


@pytest.mark.parametrize("talents,expected", [((PIERCING,), "NORMAL"), ((), "DISADVANTAGE")])
def test_piercing_senses_ignores_the_disadvantage_of_an_invisible_target(talents, expected):
    engine = C4.fight(C4.bundle(*talents, cl=12, kit=AXE), foe_at=(4, 6))
    foe = engine.state.actors[FOE]
    engine._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    assert strike(engine, "Fu (Short Axe) attack") == [expected]


def test_piercing_senses_ignores_its_own_blindness_but_not_another_source():
    engine = C4.fight(C4.bundle(PIERCING, cl=12, kit=AXE), foe_at=(4, 6))
    me = engine.state.actors[ME]
    engine._apply_condition(me, "condition:typed.blinded", "test", FOE, expires_on="UNTIL_REMOVED")
    assert strike(engine, "Fu (Short Axe) attack") == ["NORMAL"]
    engine._apply_condition(me, "condition:typed.restrained", "test", FOE, expires_on="UNTIL_REMOVED")  # another Disadvantage
    assert strike(engine, "Fu (Short Axe) attack") == ["DISADVANTAGE"]


def test_piercing_senses_reaches_only_30_feet():
    engine = C4.fight(C4.bundle(PIERCING, cl=12, kit=BOW), foe_at=(11, 6))  # 40 feet
    engine._apply_condition(engine.state.actors[FOE], "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    assert strike(engine, "Gong Jian (Bow and Arrow) attack") == ["DISADVANTAGE"]


def stormy(*, kit=BOW, **kw):
    """FOE raises the Storm; ME holds the tested weapon with the required free hands."""
    engine = C4.fight(C4.bundle(cl=12, kit=kit), foe=C4.bundle(STORM, actor_id=FOE, cl=17), foe_at=(5, 6), **kw)
    C4.turn(engine, FOE)
    C4.use(engine, "Storm Without Direction: No Safe Breath")
    engine._apply_condition(engine.state.actors[FOE], "condition:typed.restrained", "test", ME, expires_on="UNTIL_REMOVED")
    return engine


def test_storm_takes_advantage_off_a_hostile_ranged_attack_but_not_a_melee_one():
    engine = stormy()
    assert attack_mode_removal.removed(engine, engine.state.actors[ME], engine.state.actors[FOE], True) == {"ADVANTAGE"}
    assert attack_mode_removal.removed(engine, engine.state.actors[ME], engine.state.actors[FOE], False) == set()
    assert strike(engine, "Gong Jian (Bow and Arrow) attack") == ["NORMAL"]  # Restrained target: Advantage, which the storm takes away
    melee = stormy(me_at=(4, 6), kit=AXE)
    assert strike(melee, "Fu (Short Axe) attack") == ["ADVANTAGE"]


def test_without_the_storm_the_ranged_attack_keeps_its_advantage():
    engine = C4.fight(C4.bundle(cl=12, kit=BOW), foe_at=(5, 6))
    engine._apply_condition(engine.state.actors[FOE], "condition:typed.restrained", "test", ME, expires_on="UNTIL_REMOVED")
    assert strike(engine, "Gong Jian (Bow and Arrow) attack") == ["ADVANTAGE"]


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("talents,expected", [([PIERCING], "NORMAL"), ([], "DISADVANTAGE")])
def test_piercing_senses_at_the_table_survives_commit_and_reload(tmp_path, auto_turn, talents, expected):
    """The owner's axe attack makes it Blinded first (a test-only row in the test bundle), then rolls: Piercing Senses keeps the
    Blinded Disadvantage off the roll."""
    from tests.r1i_service_support import FOE as T_FOE, OWNER, SECOND, candidate, fixture, force_ai_candidate
    from tests.test_r1i_round3 import reload
    from combat.canonical import canonical_sha256

    def blind_first(bundles):
        owner = next(b for b in bundles if b["actor_id"] == OWNER)
        for action in owner["action_catalog"]:
            if action["display_name"] == "Fu (Short Axe) attack":
                action["parameters"]["typed"]["effects"].insert(0, {"type": "condition", "condition": "blinded", "applies_to": "self",
                                                                    "expires_on": "UNTIL_REMOVED"})
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)

    combat, table, mid, send, commit = fixture(tmp_path, talents, owner_kit=AXE, bundle_transform=blind_first,
                                               positions={OWNER: {"x": 3, "y": 6}, T_FOE: {"x": 4, "y": 6}, SECOND: {"x": 8, "y": 6}})
    cid = candidate(table, mid, "Fu (Short Axe) attack", T_FOE)
    if auto_turn:
        force_ai_candidate(combat, mid, OWNER, cid)
    before = len(reload(tmp_path, mid).events)
    for _ in range(8):
        result = send(cid, [], auto=auto_turn)
        if result["status"] == "COMMITTED":
            break
    engine = reload(tmp_path, mid)
    assert attack_modes(engine.events[before:], OWNER) == [expected]


# ============================================================================================ row 28: critical range
FOLLOW_UP, SWORD_SAINT = "TAL_DUAL_WIELDING_CRITICAL_FOLLOW_UP", "tianxia.subpath.body.kensei.feature.sword_saint_incarnation"
DAGGERS = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 2}]}}


def crits(events):
    return [e.payload for e in events if e.event_type == "PASSIVE_TRIGGERED" and "critical_range" in (e.payload or {})]


def test_critical_follow_up_crits_the_paired_strike_on_19_as_one_doubled_packet():
    # AUTO94 (2026-10-05): this used to assert the opposite, that a 19 on the Paired Strike stayed an
    # ordinary hit. The printed text is "Your Paired Strike scores a Critical Hit on a roll of 19 or
    # 20 on the d20", so the row was audited, made to run, and this test now asserts that. Still ONE
    # hit and ONE doubled packet -- never a second damage packet.
    engine = C4.fight(C4.bundle(FOLLOW_UP, cl=12, kit=DAGGERS), foe_at=(4, 6))
    engine.state.actors[FOE].armor_class = 1
    force_d20(engine, 19, actor_id=ME, reason="ATTACK")
    lead = C4.use(engine, "Bi Shou (Dagger) attack", target=FOE)
    assert not crits(lead)  # the Lead attack is not the Paired Strike: it keeps the 20-only range
    answer = C4.use(engine, "Bi Shou (Dagger) (copy 2) off-hand attack", target=FOE)
    rolled = [e.payload for e in answer if e.event_type == "DAMAGE_ROLLED"]
    assert len(rolled) == 1 and rolled[0]["critical"]
    assert len(rolled[0]["dice"]) == 2  # one doubled packet, not two packets
    assert not any("Not automated: your Paired Strike" in r for r in mech(FOLLOW_UP)["riders"])


def test_no_widened_range_no_change():
    engine = C4.fight(C4.bundle(cl=12, kit=DAGGERS), foe_at=(4, 6))
    engine.state.actors[FOE].armor_class = 1
    force_d20(engine, 19, actor_id=ME, reason="ATTACK")
    C4.use(engine, "Bi Shou (Dagger) attack", target=FOE)
    assert not crits(C4.use(engine, "Bi Shou (Dagger) (copy 2) off-hand attack", target=FOE))


@pytest.mark.parametrize("legacy_row", [False, True])
def test_sword_saint_makes_19_critical_and_a_legacy_row_does_not_double_it(legacy_row):
    """AUTO1 2026-10-04 reversed this test's expectation: the printed rule is "Your critical-hit range becomes
    19-20" while the incarnation lasts, so a 19 must be one critical hit. gate2_engine resolves the threshold
    through combat/critical_attacks.py before the damage roll, so the C15 deferral no longer has a reason to
    exist; an old saved fight carrying its own compiled row must not crit twice, and still does not."""
    from tests import test_riders_c7 as C7

    engine, me, foe = C7._kensei(["sword_saint_incarnation"], picks={"sword_saint": ["Speed -10"]})
    foe.armor_class = 1
    force_d20(engine, 19, actor_id=C7.ME, reason="ATTACK")
    before = len(engine.events)
    C7.use(engine, "Unarmed Strike (Iron Fist)", target=C7.FOE)
    assert not crits(engine.events[before:])  # not yet incarnated: 20 only
    C7.turn(engine, C7.ME)
    C7.use(engine, "Sword Saint Incarnation")
    if legacy_row:
        engine.typed_passive_rows[C7.ME].append({"block": "critical_range", "feature_id": SWORD_SAINT,
                                              "lowest": 19, "while_state": "sword_saint_incarnation",
                                              "weapons": "unarmed_or_blade"})
    me.action_available = True
    before = len(engine.events)
    C7.use(engine, "Unarmed Strike (Iron Fist)", target=C7.FOE)
    answer = engine.events[before:]
    rolled = [e.payload for e in answer if e.event_type == "DAMAGE_ROLLED"]
    assert rolled and all(p.get("critical") for p in rolled)
    resolved = [e.payload for e in answer if e.event_type == "ATTACK_CRITICAL_RESOLVED"]
    assert resolved and all(p["critical_threshold"] == 19 and p["critical"] is True for p in resolved)
    # one damage packet per strike, whichever copy of the row is present
    for payload in rolled:
        assert sum(1 for e in answer if e.event_type == "DAMAGE_COMMITTED"
                   and (e.payload or {}).get("rolled_or_pending_damage") == payload["total"]) == 1
    assert any("only for your unarmed" in r for r in mech(SWORD_SAINT)["riders"])


# ======================================================================================= row 25: healing interception
REVERSING, WOUND, MEND = "tianxia.talent.pressure_points.reversing_pulse", "TAL_YIN_WOUND_THAT_REFUSES_DAWN", "LIFE_BASE_MEND_THE_PULSE"


def healer_fight(owner_talents, mark):
    """ME (owner of ``owner_talents``) next to FOE, who bears ME's ``mark``, is wounded and can Mend the Pulse on itself."""
    engine = C4.fight(C4.bundle(*owner_talents, cl=12), foe=C4.bundle(MEND, actor_id=FOE, cl=12), foe_at=(4, 6))
    foe = engine.state.actors[FOE]
    foe.current_hp = foe.maximum_hp - 40
    engine._apply_condition(foe, te.mark_condition_id(mark, ME), "test", ME, expires_on="UNTIL_REMOVED", data={"mark": mark, "label": mark})
    C4.turn(engine, FOE)
    return engine, engine.state.actors[ME], foe


def healed(events, who=FOE):
    return [e.payload for e in events if e.event_type == "HEALING_APPLIED" and who in (e.target_ids or ())]


@pytest.mark.parametrize("save_natural,halved", [(1, True), (20, False)])
def test_reversing_pulse_halves_or_trims_the_healing_as_it_lands(save_natural, halved):
    engine, me, foe = healer_fight([REVERSING], "Pressure Point")
    force_d20(engine, save_natural, actor_id=FOE, reason="SAVE:")
    events = C4.use(engine, "Mend the Pulse", target=FOE)
    (heal,) = healed(events)
    (resolved,) = [e.payload for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == REVERSING]
    offered = resolved["offered"]
    assert heal["offered"] == (offered - (offered - offered // 2) if halved else max(0, offered - 4))
    assert not me.reaction_available  # it is a Reaction


def test_reversing_pulse_needs_the_pressure_point():
    engine, me, foe = healer_fight([REVERSING], "Waning Mark")
    events = C4.use(engine, "Mend the Pulse", target=FOE)
    assert not [e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == REVERSING]
    assert me.reaction_available


def test_diminish_recovery_spends_the_waning_mark_and_wound_that_refuses_dawn_follows():
    engine, me, foe = healer_fight([WOUND], "Waning Mark")
    events = C4.use(engine, "Mend the Pulse", target=FOE)
    (heal,) = healed(events)
    assert any("Diminish Recovery" in line for line in notes(events))
    assert not te.bears_mark(foe, ME, "Waning Mark")  # spent
    (record,) = [c for c in foe.conditions.values() if c.condition_id == healing_interception.RECORD]
    assert record.data["reduce"] == 4 and record.data["each"] == 1  # CL 12: each healing until the start of my next turn
    foe.action_available = True
    again = C4.use(engine, "Mend the Pulse", target=FOE)
    assert any("Wound That Refuses Dawn" in line for line in notes(again))
    C4.turn(engine, ME)
    assert not [c for c in foe.conditions.values() if c.condition_id == healing_interception.RECORD]


def test_healing_without_any_interceptor_is_unchanged():
    engine = C4.fight(C4.bundle(cl=12), foe=C4.bundle(MEND, actor_id=FOE, cl=12), foe_at=(4, 6))
    foe = engine.state.actors[FOE]
    foe.current_hp = foe.maximum_hp - 40
    C4.turn(engine, FOE)
    (heal,) = healed(C4.use(engine, "Mend the Pulse", target=FOE))
    rolled = [r for r in engine.rolls if "HEALING" in str(r.reason)][-1]
    assert heal["offered"] == rolled.total


def _scripted_d20(monkeypatch, wanted_for):
    """Test-only dice: ``wanted_for(actor_id, reason)`` -> the natural to show, or None; adjudication and records stay real."""
    from combat.gate2_rolls import DeterministicRollAuthority

    real_d20 = DeterministicRollAuthority.d20

    def dice(roller, **kwargs):
        wanted = wanted_for(kwargs.get("actor_id"), str(kwargs.get("reason") or ""))
        while True:
            roll = real_d20(roller, **kwargs)
            if wanted is None or roll.natural_result == wanted:
                return roll

    monkeypatch.setattr(DeterministicRollAuthority, "d20", dice)


def _commit_all(send, cid, auto, picks=None):
    answers, prompts = [], []
    for _ in range(12):
        result = send(cid, answers, auto=auto)
        if result["status"] == "COMMITTED":
            return prompts
        p = result["reaction"]
        prompts.append(p)
        answer = {**p["context"], "selection": "USE"}
        if p.get("choice"):
            pick = (picks or {}).get(p["context"]["reaction_source_id"])
            answer["option_ids"] = [pick] if pick else (p["choice"].get("preferred") or [p["choice"]["options"][0]["id"]])[:1]
        answers.append(answer)
    raise AssertionError("too many prompts")


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("legacy_row", [False, True])
@pytest.mark.parametrize("defense", ["none", "reduction", "resistance", "helmet"])
def test_deferred_critical_at_the_table_is_one_hit_after_reload(tmp_path, monkeypatch, auto_turn, legacy_row, defense):
    from tests.r1i_service_support import FOE as T_FOE, OWNER, SECOND, candidate, fixture, force_ai_candidate
    from tests.test_r1i_round3 import reload

    _scripted_d20(monkeypatch, lambda actor, reason: 19 if actor == OWNER and reason.startswith("ATTACK") else None)
    def prepare(bundles):
        from combat.canonical import canonical_sha256

        for bundle in bundles:
            if legacy_row and bundle["actor_id"] == OWNER:
                bundle["typed_passives"].append({"block": "critical_range", "feature_id": FOLLOW_UP,
                                               "lowest": 19, "pair_role": "answer"})
            if bundle["actor_id"] == T_FOE and defense in {"reduction", "resistance"}:
                bundle["typed_passives"].append({"block": "defense", "feature_id": "test:defense",
                                               "kind": defense, "damage_types": ["PIERCING", "SLASHING"], "amount": 3})
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid, send, commit = fixture(tmp_path, [FOLLOW_UP], owner_kit=DAGGERS, foe_ac=1,
                                               foe_talents=["tianxia.talent.equipment.helmet_discipline"] if defense == "helmet" else [],
                                               bundle_transform=prepare,
                                               positions={OWNER: {"x": 3, "y": 6}, T_FOE: {"x": 4, "y": 6}, SECOND: {"x": 8, "y": 6}})
    commit(candidate(table, mid, "Bi Shou (Dagger) attack", T_FOE))
    cid = candidate(table, mid, "off-hand attack", T_FOE)
    if auto_turn:
        force_ai_candidate(combat, mid, OWNER, cid)
    initial = reload(tmp_path, mid)
    before = len(initial.events)
    hp = initial.state.actors[T_FOE].current_hp
    _commit_all(send, cid, auto_turn)
    engine = reload(tmp_path, mid)
    events = engine.events[before:]
    rolled = [e.payload for e in events if e.event_type == "DAMAGE_ROLLED" and T_FOE in e.target_ids]
    dealt = [e.payload for e in events if e.event_type == "DAMAGE_COMMITTED" and T_FOE in e.target_ids]
    # AUTO94: the Paired Strike's real 19 now scores the printed Critical Hit, still as ONE hit and
    # ONE doubled packet (never a second damage packet), with the target's own defense on the total.
    assert len(rolled) == len(dealt) == 1
    turned = any(e.payload.get("critical_turned_normal") for e in events)
    if defense == "helmet" and not auto_turn:
        # Helmet Discipline (printed): "you may turn one critical hit against you into a normal hit",
        # so the doubled packet is correctly gone again here. On the auto_turn path the attacker is
        # force-committed by the AI and that prompt is auto-declined, so the Critical Hit stands.
        assert turned, "Helmet Discipline did not turn the Critical Hit into a normal hit"
        assert not rolled[0]["critical"] and len(rolled[0]["dice"]) == 1
    else:
        assert rolled[0]["critical"] and len(rolled[0]["dice"]) == 2 and not turned
    total = rolled[0]["combined_total"]
    expected = max(0, total - 3) if defense == "reduction" else total // 2 if defense == "resistance" else total
    assert dealt[0]["hp_damage"] == expected
    assert engine.state.actors[T_FOE].current_hp == hp - expected
    assert combat._load_session(mid).mechanical.replay()["status"] == "PASS"
    assert not crits(engine.events[:before])  # the lead attack's 19 stayed an ordinary hit


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("accept", [True, False])
def test_diminish_recovery_at_the_table_asks_the_marker_and_survives_reload(tmp_path, auto_turn, accept):
    from tests.r1i_service_support import FOE as T_FOE, OWNER, SECOND, candidate, fixture, force_ai_candidate
    from tests.test_r1i_round3 import reload, resolve

    combat, table, mid, send, commit = fixture(tmp_path, [WOUND], foe_talents=[MEND],
                                               positions={OWNER: {"x": 3, "y": 6}, T_FOE: {"x": 4, "y": 6}, SECOND: {"x": 8, "y": 6}})
    commit(candidate(table, mid, "Mark the Waning", T_FOE))
    assert te.bears_mark(reload(tmp_path, mid).state.actors[T_FOE], OWNER, "Waning Mark")
    while table.state(mid)["menu"]["actor_id"] != T_FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Mend the Pulse", T_FOE)
    if auto_turn:
        force_ai_candidate(combat, mid, T_FOE, cid)
    before = len(reload(tmp_path, mid).events)
    _, prompts = resolve(combat, mid, send, cid, {"choice:needle.diminish_recovery": "spend" if accept else None}, auto=auto_turn)
    asked = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.diminish_recovery"]
    assert len(asked) == 1 and "Waning Mark" in json.dumps(asked[0])  # the marker is a player: asked on the foe's turn
    engine = reload(tmp_path, mid)
    lines = notes(engine.events[before:])
    assert any("Diminish Recovery" in line for line in lines) == accept
    assert te.bears_mark(engine.state.actors[T_FOE], OWNER, "Waning Mark") == (not accept)
    assert bool([c for c in engine.state.actors[T_FOE].conditions.values() if c.condition_id == healing_interception.RECORD]) == accept
