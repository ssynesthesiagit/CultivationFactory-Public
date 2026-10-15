"""Rider lane C12 (owner 2026-09-30: "i want everything we can automated, keep going until its only the non-combat ones
left"): shared systems that unblock lines the rider lanes left "blocked: <system>" (census: /var/tmp/auto-audit/fix/
BLOCKED_CENSUS.md). Every system is driven through real compiled characters on a Gate4 engine; the persistence cases commit
through Gate4Persistence and reload the saved fight. C12_OLD=1 swaps in the authority of the base commit (a9d0770f): the
typing cases then fail, because the base typing has none of the new rows.

Overrides: authority/typed_mechanics/reviewed_final.d/riders_c12.json (entries moved there from the files that held them).
Plug-ins: combat/ext/bound_objects.py.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

import combat.factory_compiler as compiler
from combat import typed_executor
from combat.ext import bound_objects, objects as objects_ext
from combat.gate2_runtime_models import ActionIntent
from tests import test_riders_c4 as C4
from tests.h1_support import ROOT

BASE_COMMIT = "a9d0770f"
ME, FOE = C4.ME, C4.FOE
FAIL, PASS = C4.FAIL, C4.PASS
DAO = {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]}


@pytest.fixture(autouse=True, scope="session")
def base_typing(tmp_path_factory):
    if os.environ.get("C12_OLD"):
        path = tmp_path_factory.mktemp("authority") / "base.json"
        path.write_bytes(subprocess.check_output(["git", "show", f"{BASE_COMMIT}:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"], cwd=ROOT))
        compiler.TYPED_AUTHORITY = path


def mech(key):
    return json.loads(compiler.TYPED_AUTHORITY.read_bytes())["mechanics"][key]


def force_d20(engine, low, high):
    original = getattr(engine.roller, "_real_d20", None) or engine.roller.d20
    engine.roller._real_d20 = original

    def d20(**kwargs):
        while True:
            roll = original(**kwargs)
            if low <= int(roll.natural_result) <= high:
                return roll

    engine.roller.d20 = d20


def bound(engine):
    return [obj for obj in engine.state.objects.values() if bound_objects.bound(obj) is not None]


def break_object(engine, attacker_id, obj, tries=60):
    """The attacker uses its own "Attack an object" until the object is destroyed; returns the events."""
    events = []
    force_d20(engine, 15, 19)
    for _ in range(tries):
        if engine.state.objects[obj.object_id].destroyed:
            return events
        C4.turn(engine, attacker_id)
        events += C4.use(engine, "Attack an object", target=obj.object_id, actor_id=attacker_id)
    raise AssertionError("the object was never destroyed")


def notes(events):
    return [str((e.payload or {}).get("log") or "") for e in events if e.event_type == "PASSIVE_TRIGGERED"]


# ============================================================================================ 1. effect-bound objects
OBJECT_LINES = {
    "TAL_ICE_ICE_COFFIN": "The shell is an object",
    "TAL_ICE_THOUSAND_FACET_PRISON": "The prison is an object",
    "TAL_VOID_VOID_PRISON": "The Void Prison is an object",
    "TAL_SAND_GLASS_PRISON": "The target or an adjacent creature can use an Action to attack the prison",
    "TAL_GLASS_GLASS_COFFIN_WITHOUT_DEATH": "the shell has AC",
}


def test_object_lines_are_typed_and_no_longer_gm_riders():
    for key, line in OBJECT_LINES.items():
        entry = mech(key)
        assert not [r for r in entry["riders"] if str(r).startswith(line)], key
        rows = json.dumps(entry["effects"])
        assert '"bound_object"' in rows, key


def test_void_prison_makes_a_cage_object_with_its_printed_numbers():
    engine = C4.fight(C4.bundle("TAL_VOID_VOID_PRISON", cl=10, dc=FAIL), foe=C4.void_foe(kit=DAO), foe_at=(8, 6))
    events = C4.use(engine, "Void Prison", target=FOE)
    foe = engine.state.actors[FOE]
    (cage,) = C4.held(foe, "void_prison")
    (obj,) = bound(engine)
    record = bound_objects.bound(obj)
    assert (obj.ac, obj.current_hp, obj.maximum_hp) == (15, 40, 40)  # AC 15; HP 10 x PB (PB 4)
    assert set(obj.damage_immunities) == {"POISON", "PSYCHIC"} and obj.component["resist"] == ["FORCE", "NECROTIC"]
    assert (obj.position.x, obj.position.y) == (8, 6) and not obj.component["blocks"]
    assert record["holder"] == FOE and record["conditions"] == [cage.instance_id] and record["owner"] == ME
    assert any("Void Prison: an object with AC 15 and 40 hit points" in line for line in notes(events))
    # The prisoner itself is offered "Attack an object" against its cage.
    C4.turn(engine, FOE)
    assert [c for c in engine.legal_candidates() if c.display_name == "Attack an object" and obj.object_id in (c.target_ids or ())]


def test_breaking_the_void_prison_frees_the_prisoner():
    engine = C4.fight(C4.bundle("TAL_VOID_VOID_PRISON", cl=10, dc=FAIL), foe=C4.void_foe(kit=DAO), foe_at=(8, 6))
    C4.use(engine, "Void Prison", target=FOE)
    (obj,) = bound(engine)
    events = break_object(engine, FOE, obj)
    foe = engine.state.actors[FOE]
    assert not C4.held(foe, "void_prison") and engine._effective_speed(foe) > 0
    assert any("Void Prison is destroyed, so its effect ends" in line for line in notes(events))
    removed = [e for e in events if e.event_type == "CONDITION_REMOVED" and e.payload.get("condition_id") == "condition:typed.void_prison"]
    assert len(removed) == 1


def test_the_cage_goes_when_the_prison_ends_first():
    engine = C4.fight(C4.bundle("TAL_VOID_VOID_PRISON", cl=10, dc=FAIL), foe=C4.void_foe(kit=DAO), foe_at=(8, 6))
    C4.use(engine, "Void Prison", target=FOE)
    (obj,) = bound(engine)
    engine._end_concentration(engine.state.actors[ME], "TEST")
    C4.turn(engine, FOE)
    after = engine.state.objects[obj.object_id]
    assert not C4.held(engine.state.actors[FOE], "void_prison")
    assert after.destroyed and bound_objects.bound(after)["ended"] == 1
    # It was removed, not damaged: no damage was recorded on it.
    assert not [e for e in engine.events if e.event_type == "OBJECT_UPDATED" and (e.payload or {}).get("damage")]


def test_a_saved_void_prison_cage_survives_a_table_commit_and_reload_and_still_frees_the_prisoner(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    me = C4.bundle("TAL_VOID_VOID_PRISON", cl=10, dc=FAIL)
    foe = C4.void_foe(kit=DAO)
    session = persistence.create_match(match_seed="C12-CAGE", typed_bundles=(me, foe), roster_setup={
        "primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 8, "y": 6}}})

    def submit(name, target):
        while session.engine.state.current_actor_id not in (ME, FOE) or (name == "Void Prison" and session.engine.state.current_actor_id != ME):
            c = next(c for c in session.engine.legal_candidates() if c.display_name == "End turn")
            session.submit_intent(ActionIntent(intent_id=f"end-{c.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                               state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids),
                                  primary_decision_record=None, reaction_provider=None)
        c = next(c for c in session.engine.legal_candidates() if c.display_name == name and target in (c.target_ids or ()))
        session.submit_intent(ActionIntent(intent_id=f"{name}-{c.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                           state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids),
                              primary_decision_record=None, reaction_provider=None)

    submit("Void Prison", FOE)
    (obj,) = bound(session.engine)
    loaded = persistence.load_match(session.match_id)
    (again,) = bound(loaded.engine)
    assert again.model_dump(mode="json") == obj.model_dump(mode="json")
    record = bound_objects.bound(again)
    assert all(isinstance(v, (str, int, list, dict)) and not isinstance(v, float) for v in record.values())
    # Destroying the reloaded cage (one evented object-damage instance) still ends exactly the saved prison.
    engine = loaded.engine
    objects_ext.deal(engine, engine.state.actors[FOE], again, [(999, "BLUDGEONING")], "test:break")
    assert not C4.held(engine.state.actors[FOE], "void_prison")


def test_glass_prison_breaking_frees_the_target_and_cuts_it_for_the_proficiency_bonus():
    engine = C4.fight(C4.bundle("TAL_SAND_GLASS_PRISON", cl=12, dc=FAIL), foe_at=(6, 6))
    source = C4.action_id(engine, ME, "Glass Prison")
    ctx = C4.ctx_of(engine, ME, FOE, source, dc=FAIL, pb=4, cl=12)
    typed_executor.run_effects(ctx, ctx.typed["effects"])
    foe = engine.state.actors[FOE]
    assert C4.held(foe, "restrained")
    (obj,) = bound(engine)
    assert (obj.ac, obj.current_hp) == (FAIL, 22)  # AC your Cultivation Save DC, HP 10 + CL
    hp = foe.current_hp
    before = len(engine.events)
    objects_ext.deal(engine, engine.state.actors[ME], obj, [(999, "BLUDGEONING")], "test:break")
    assert not C4.held(foe, "restrained")
    cut = [e for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED" and FOE in (e.target_ids or ())]
    assert cut and hp - foe.current_hp == 4  # Piercing damage equal to your Proficiency Bonus


def test_ice_coffin_and_thousand_facet_prison_make_their_printed_objects():
    for key, name, ac, hp in (("TAL_ICE_ICE_COFFIN", "Ice Coffin", 16, 30), ("TAL_ICE_THOUSAND_FACET_PRISON", "Thousand-Facet Prison", 19, 50)):
        engine = C4.fight(C4.bundle(key, cl=10, dc=FAIL), foe_at=(6, 6))
        ctx = C4.ctx_of(engine, ME, FOE, C4.action_id(engine, ME, name), dc=FAIL, pb=4, cl=10)
        typed_executor.run_effects(ctx, ctx.typed["effects"])
        (obj,) = bound(engine)
        assert (obj.ac, obj.maximum_hp) == (ac, hp), key  # 12 + PB / 10 + 2 x CL; 15 + PB / 20 + 3 x CL
        objects_ext.deal(engine, engine.state.actors[ME], obj, [(999, "FIRE")], "test:break")
        assert not C4.held(engine.state.actors[FOE], "restrained"), key


def test_no_object_when_the_target_saves():
    engine = C4.fight(C4.bundle("TAL_VOID_VOID_PRISON", cl=10, dc=PASS), foe=C4.void_foe(), foe_at=(8, 6))
    C4.use(engine, "Void Prison", target=FOE)
    assert not bound(engine) and C4.held(engine.state.actors[FOE], "hollowed")


def test_a_fight_without_bound_objects_is_untouched():
    engine = C4.fight(C4.bundle("TAL_VOID_EMPTY_STEP", cl=10), foe_at=(8, 6))
    before = len(engine.events)
    bound_objects._sweep(engine)
    assert len(engine.events) == before and not bound(engine)


# ============================================================================================ 2. creature kinds
from combat.ext import creature_kinds  # noqa: E402
from combat.factory_compiler import compile_character  # noqa: E402
from tests.h1_support import sheet as h1_sheet  # noqa: E402

ALLY = C4.ALLY


def kind_bundle(mids, actor_id, kind=None, cl=10, dc=16, kit=None, ac=None):
    """A real compiled character whose printed creature type is ``kind`` (Factory identity creature_type)."""
    doc = h1_sheet(list(mids), cl=cl, dc=dc, kit=kit)
    if kind:
        doc["identity"]["creature_type"] = kind
    if ac is not None:
        doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = ac
    return compile_character(doc, actor_id=actor_id)


def sure_hit(engine):
    engine.state.actors[FOE].armor_class = -50


def damage_rolls(engine, before, source_part):
    return [r for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE") and source_part in str(r.reason)]


def test_kind_lines_are_typed_and_no_longer_gm_riders():
    gone = {"LIFE_BASE_MEND_THE_PULSE": "Mend the Pulse has no effect on undead", "RADIANCE_BASE_STRIKE": "Once per turn, if Radiance Strike",
            "RADIANCE_TAL_DAWNLIT_REBUKE": "If the creature is Unclean", "RADIANCE_TAL_SUN_WHITE_JUDGMENT_SPEAR": "If the target is Unclean",
            "tianxia.talent.radiance.first_dawn_before_falsehood": "Unclean creatures have Disadvantage on the Wisdom",
            "TAL_SOUND_BODY_RESONANCE_STRIKE": "If the target is a construct",
            "tianxia.talent.life.esoteric_vitality": "Mend the Pulse, Borrowed Breath, Read the Pulse"}
    for key, line in gone.items():
        assert not [r for r in mech(key)["riders"] if str(r).startswith(line)], key
    assert mech("LIFE_BASE_MEND_THE_PULSE")["effects"][0]["unless_kind"]["kinds"] == ["undead", "construct"]
    assert mech("RADIANCE_BASE_STRIKE")["effects"][0]["on_hit"][0]["bonus_if_kind"]["kinds"] == ["unclean"]


def test_unclean_follows_the_printed_radiance_list_and_never_guesses():
    engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE"), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
    foe = engine.state.actors[FOE]
    assert creature_kinds.is_unclean(foe) and creature_kinds.matches(foe, ["undead"])
    for label, unclean in (("Fiend", True), ("Demon", True), ("Possession Entity", True), ("Construct", False), ("Humanoid", False)):
        other = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE"), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, label))
        assert creature_kinds.is_unclean(other.state.actors[FOE]) is unclean, label
    plain = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE"))
    assert not creature_kinds.labels(plain.state.actors[FOE]) and not creature_kinds.is_unclean(plain.state.actors[FOE])


def test_radiance_strike_adds_the_proficiency_bonus_once_per_turn_against_an_unclean_target():
    engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE", cl=10), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
    sure_hit(engine)
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    (first,) = damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")
    assert first.modifier == 4  # PB added to the one damage roll
    engine.state.actors[ME].action_available = True
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    (second,) = damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")
    assert second.modifier == 0  # once per turn
    C4.turn(engine, FOE)
    C4.turn(engine, ME)
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    assert damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")[0].modifier == 4  # a new turn


def test_radiance_strike_against_an_unlabelled_target_is_unchanged():
    engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE", cl=10))
    sure_hit(engine)
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    assert damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")[0].modifier == 0


def test_mend_the_pulse_is_not_offered_on_undead_or_constructs_unless_esoteric_vitality():
    for kind in ("Undead", "Construct"):
        engine = C4.fight(C4.bundle("LIFE_BASE_MEND_THE_PULSE"), ally=kind_bundle(["SAND_BASE_SCOURING_HAND"], ALLY, kind), ally_at=(4, 6))
        assert not [c for c in engine.legal_candidates() if c.display_name == "Mend the Pulse" and ALLY in (c.target_ids or ())], kind
    living = C4.fight(C4.bundle("LIFE_BASE_MEND_THE_PULSE"), ally=kind_bundle(["SAND_BASE_SCOURING_HAND"], ALLY), ally_at=(4, 6))
    assert [c for c in living.legal_candidates() if c.display_name == "Mend the Pulse" and ALLY in (c.target_ids or ())]
    engine = C4.fight(C4.bundle("LIFE_BASE_MEND_THE_PULSE", "tianxia.talent.life.esoteric_vitality"),
                      ally=kind_bundle(["SAND_BASE_SCOURING_HAND"], ALLY, "Undead"), ally_at=(4, 6))
    ally = engine.state.actors[ALLY]
    ally.current_hp = 10
    C4.use(engine, "Mend the Pulse", target=ALLY)
    assert ally.current_hp > 10  # Esoteric Vitality: Mend the Pulse can affect undead


def test_mend_the_pulse_reaching_an_undead_another_way_heals_nothing():
    engine = C4.fight(C4.bundle("LIFE_BASE_MEND_THE_PULSE"), ally=kind_bundle(["SAND_BASE_SCOURING_HAND"], ALLY, "Undead"), ally_at=(4, 6))
    ally = engine.state.actors[ALLY]
    ally.current_hp = 10
    ctx = C4.ctx_of(engine, ME, ALLY, C4.action_id(engine, ME, "Mend the Pulse"))
    typed_executor.run_effects(ctx, ctx.typed["effects"])
    assert ally.current_hp == 10


def test_dawnlit_rebuke_stops_an_unclean_creature_regaining_hp():
    for kind, denied in (("Fiend", True), (None, False)):
        engine = C4.fight(C4.bundle("RADIANCE_TAL_DAWNLIT_REBUKE"), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, kind))
        source = next(a for a in engine.state.actors[ME].reaction_ids + engine.state.actors[ME].action_ids if "DAWNLIT_REBUKE" in a) \
            if any("DAWNLIT_REBUKE" in a for a in engine.state.actors[ME].reaction_ids + engine.state.actors[ME].action_ids) else None
        rows = mech("RADIANCE_TAL_DAWNLIT_REBUKE")["effects"]
        action = engine.action_catalog.get(source) if source else next(iter(engine.action_catalog.values()))
        typed = {"numbers": {"pb": 4, "cl": 10, "key_mod": 2, "save_dc": 16}, "effects": rows, "riders": []}
        ctx = typed_executor.Context(engine, engine.state.actors[ME], action, None, typed, [engine.state.actors[FOE]], engine.state.actors[FOE], {})
        typed_executor.run_effects(ctx, rows)
        held = [m for m in engine.state.actors[FOE].modifiers.values() if m.target_field == "healing_reduction"]
        assert bool(held) is denied, kind
        if held:
            assert held[0].expires_on == "START_OF_SELF_NEXT_TURN"


def test_sun_white_judgment_spear_makes_an_unclean_target_save():
    engine = C4.fight(C4.bundle("RADIANCE_TAL_SUN_WHITE_JUDGMENT_SPEAR", cl=17, dc=FAIL), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
    sure_hit(engine)
    events = C4.use(engine, "Sun-White Judgment Spear", target=FOE)
    foe = engine.state.actors[FOE]
    assert [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert C4.held(foe, "blinded") and [m for m in foe.modifiers.values() if m.target_field == "healing_reduction"]
    passed = C4.fight(C4.bundle("RADIANCE_TAL_SUN_WHITE_JUDGMENT_SPEAR", cl=17, dc=PASS), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
    sure_hit(passed)
    C4.use(passed, "Sun-White Judgment Spear", target=FOE)
    assert C4.held(passed.state.actors[FOE], "reaction_denied") and not C4.held(passed.state.actors[FOE], "blinded")
    plain = C4.fight(C4.bundle("RADIANCE_TAL_SUN_WHITE_JUDGMENT_SPEAR", cl=17, dc=FAIL))
    sure_hit(plain)
    events = C4.use(plain, "Sun-White Judgment Spear", target=FOE)
    assert not [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]


def test_disadvantage_if_kind_on_a_save_row():
    for kind, mode in (("Undead", "DISADVANTAGE"), (None, "NORMAL")):
        engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE"), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, kind))
        ctx = C4.ctx_of(engine, ME, FOE, C4.action_id(engine, ME, "Radiance Strike"))
        before = len(engine.events)
        typed_executor.block_save(ctx, {"type": "save", "ability": "wis", "dc": "technique_save_dc", "disadvantage_if_kind": ["unclean"],
                                        "applies_to": "target", "on_fail": [], "on_success": []})
        (save,) = [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED"]
        assert save.payload["mode"] == mode, kind


def test_body_resonance_strike_resonates_a_construct_that_carries_nothing():
    from combat.ext import sound_strikes

    for kind, marked in (("Construct", True), (None, False)):
        engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE"), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, kind, kit={"items": []}))
        foe = engine.state.actors[FOE]
        action = engine.action_catalog[C4.action_id(engine, ME, "Radiance Strike")]
        typed = {"numbers": {"pb": 4, "cl": 10}, "modifier": {"id": "TAL_SOUND_BODY_RESONANCE_STRIKE"}, "effects": [], "riders": []}
        ctx = typed_executor.Context(engine, engine.state.actors[ME], action, None, typed, [foe], foe, {})
        sound_strikes.equipped_resonance(ctx, {"type": "sound_equipped_resonance", "applies_to": "target"})
        assert typed_executor.bears_mark(foe, ME, "Resonance") is marked, kind


def test_once_per_turn_kind_flag_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    me = C4.bundle("RADIANCE_BASE_STRIKE", cl=10)
    foe = kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead", ac=0)  # printed AC 0: the strike hits unless a natural 1
    session = persistence.create_match(match_seed="C12-KIND", typed_bundles=(me, foe), roster_setup={
        "primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})
    while session.engine.state.current_actor_id != ME:
        c = next(c for c in session.engine.legal_candidates() if c.display_name == "End turn")
        session.submit_intent(ActionIntent(intent_id=f"end-{c.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                           state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids),
                              primary_decision_record=None, reaction_provider=None)
    assert creature_kinds.is_unclean(session.engine.state.actors[FOE])
    c = next(c for c in session.engine.legal_candidates() if c.display_name == "Radiance Strike" and FOE in (c.target_ids or ()))
    before = len(session.engine.rolls)
    session.submit_intent(ActionIntent(intent_id="strike", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                       actor_id=ME, target_ids=c.target_ids), primary_decision_record=None, reaction_provider=None)
    (hit,) = [r for r in session.engine.rolls[before:] if str(r.reason).startswith("DAMAGE")]
    assert hit.modifier == 4  # the PB rides the strike's damage roll
    loaded = persistence.load_match(session.match_id)
    assert loaded.engine.state.actors[ME].turn_flags.get("creature_kind_once:radiance_strike_unclean") is True
    assert creature_kinds.is_unclean(loaded.engine.state.actors[FOE])


def test_daybreak_seal_makes_an_unclean_target_roll_its_save_with_disadvantage():
    """"If the target is Unclean, it has Disadvantage on the saving throw" (Daybreak Seal): the table rolls it, the GM does not."""
    for kind, mode in (("Undead", "DISADVANTAGE"), ("Fiend", "DISADVANTAGE"), ("Possession Entity", "DISADVANTAGE"),
                       ("Humanoid", "NORMAL"), ("Construct", "NORMAL"), (None, "NORMAL")):
        engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE", "tianxia.talent.radiance.daybreak_seal", cl=10, dc=FAIL),
                          foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, kind))
        sure_hit(engine)
        events = C4.use(engine, "Radiance Strike + Daybreak Seal", target=FOE)
        (save,) = [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
        assert save.payload["mode"] == mode, kind


def dawnmarked(engine, who=FOE):
    """The real mark condition this owner's Radiance talents place, applied directly so a test can start from a
    target that already bears it. The printed gate is 'a creature bearing your Dawnmark' at the moment of damage."""
    engine._apply_condition(engine.state.actors[who], typed_executor.mark_condition_id("Dawnmark", ME),
                            "test:dawnmark_scripture", ME, expires_on="UNTIL_REMOVED")


def radiant_immunity(engine, who=FOE):
    """A printed 'Immunity to Radiant damage' on ``who`` (the shape Heavenly Radiance's own benefit uses), as a
    resistance-block row: the incoming damage is fully prevented, so nothing is actually dealt."""
    engine.typed_passive_rows.setdefault(who, []).append(
        {"block": "resistance", "feature_id": "test:radiant_immunity", "name": "Immunity to Radiant damage",
         "kind": "immunity", "damage_types": ["RADIANT"]})


WAVE_MID, WAVE = "RADIANCE_TAL_DAWN_CLEANSING_WAVE", "Dawn-Cleansing Wave"
# "Qi-powered techniques deal an extra +<your key ability modifier> damage, once per activation" (Qi Cultivation path).
POTENCY = "tianxia.path.qi_cultivation.feature.qi_technique_potency"


def radiant_resistance(engine, who=FOE):
    """A printed 'Resistance to Radiant damage' on ``who``: half of each Radiant die it takes, rounded down."""
    engine.typed_passive_rows.setdefault(who, []).append(
        {"block": "resistance", "feature_id": "test:radiant_resistance", "name": "Resistance to Radiant damage",
         "kind": "resistance", "damage_types": ["RADIANT"]})


def force_damage_dice(engine, value):
    """Land every damage die on ``value``, so a halved total below is exact rather than sometimes-odd."""
    original = engine.roller.roll

    def roll(spec, **kw):
        record = original(spec, **kw)
        if str(kw.get("reason") or "").startswith("DAMAGE"):
            record = record.model_copy(update={"dice": tuple([value] * spec.count),
                                               "total": value * spec.count + spec.modifier})
        return record

    engine.roller.roll = roll


def wave_owner():
    """A real compiled character owning the talent and the cultivation feature together, because the bug only shows
    when both are on one character: the Wave's own die and the Scripture die roll inside a single activation."""
    return C4.bundle("RADIANCE_BASE_STRIKE", WAVE_MID, "tianxia.talent.radiance.dawnmark_scripture", POTENCY, cl=10)


def test_dawnmark_scripture_adds_a_die_of_radiant_damage_only_to_an_unclean_dawnmarked_target():
    """"Once per turn when you damage an Unclean creature bearing your Dawnmark, add 1d8 Radiant damage": a second
    damage roll, only for a creature both bearing the mark and labelled Unclean."""
    for kind, rolls in (("Undead", 2), ("Fiend", 2), ("Corrupted Spirit", 2), ("Humanoid", 1), ("Construct", 1), (None, 1)):
        engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE", "tianxia.talent.radiance.dawnmark_scripture", cl=10),
                          foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, kind))
        sure_hit(engine)
        dawnmarked(engine)
        before = len(engine.rolls)
        C4.use(engine, "Radiance Strike", target=FOE)
        assert len(damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")) == rolls, kind


def test_dawnmark_scripture_waits_for_the_mark_the_striking_strike_places():
    """The printed gate is 'a creature bearing your Dawnmark' when you damage it, and Radiance Strike applies the
    mark as part of that same attack -- after its damage has already landed. So the applying hit adds nothing and
    the next hit in the same turn does."""
    engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE", "tianxia.talent.radiance.dawnmark_scripture", cl=10),
                      foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
    sure_hit(engine)
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    assert len(damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")) == 1  # the mark this very strike places
    engine.state.actors[ME].action_available = True
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    assert len(damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")) == 2


def test_dawnmark_scripture_counts_damage_that_is_not_an_attack():
    """The printed trigger is "when you damage", with no attack or Sphere limit. Dawn-Cleansing Wave is a
    save-based direct-damage talent, so the typed any_attack modifier this lane started with could never see it."""
    engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE", WAVE_MID, "tianxia.talent.radiance.dawnmark_scripture", cl=10),
                      foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
    dawnmarked(engine)
    force_d20(engine, 1, 1)  # the save fails, so the Wave's save-based damage lands
    before = len(engine.rolls)
    C4.use(engine, WAVE)  # an area effect: it has no single target
    assert len(damage_rolls(engine, before, WAVE_MID)) == 2, [str(r.reason) for r in engine.rolls[before:]]


def test_dawnmark_scripture_does_not_apply_qi_technique_potency_a_second_time():
    """Qi Technique Potency is "once per activation": the activation that triggered the Scripture bonus has already
    spent it on its own damage roll. The bonus die is a separate roll added to that same activation, so it must stay
    a plain 1d8 -- with a 14 CON the Wave is 6d8+2 and the Scripture is 1d8+0, never 1d8+2."""
    engine = C4.fight(wave_owner(), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
    dawnmarked(engine)
    force_d20(engine, 1, 1)  # the save fails, so the Wave's save-based damage lands and triggers the bonus
    before = len(engine.rolls)
    C4.use(engine, WAVE)
    rolls = damage_rolls(engine, before, WAVE_MID)
    assert len(rolls) == 2, [str(r.reason) for r in engine.rolls[before:]]
    wave, scripture = rolls
    assert wave.expression == "6d8+2" and wave.modifier == 2  # the key ability modifier rides the activating roll
    assert scripture.expression == "1d8+0" and scripture.modifier == 0  # the added die never re-applies it
    assert sum(roll.modifier for roll in rolls) == 2  # exactly one potency application in the whole activation


def test_dawnmark_scripture_deals_radiant_damage():
    """"add 1d8 Radiant damage": Radiant resistance halves both dice, so the foe's total hit point loss shows the
    added die really carries the printed type. With every die forced to 7, the Wave is 44 and the Scripture 7; an
    untyped or differently-typed bonus would land its full 7 and lose 29 here instead of 25."""
    losses = {}
    for resistant in (False, True):
        engine = C4.fight(wave_owner(), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
        dawnmarked(engine)
        if resistant:
            radiant_resistance(engine)
        force_d20(engine, 1, 1)
        force_damage_dice(engine, 7)
        before = len(engine.rolls)
        C4.use(engine, WAVE)
        wave, scripture = damage_rolls(engine, before, WAVE_MID)
        assert (wave.total, scripture.total) == (44, 7)
        losses[resistant] = engine.state.actors[FOE].maximum_hp - engine.state.actors[FOE].current_hp
    assert losses[False] == 51  # 44 + 7, nothing resists Radiant
    assert losses[True] == 25  # 22 + 3: the Scripture die was halved like the Wave's, so it is Radiant too


def test_dawnmark_scripture_spends_nothing_when_the_damage_is_fully_prevented():
    """A hit that deals no damage at all is not "when you damage": the once-per-turn use must survive it, so the
    first damage that does land in the same turn still gets the die."""
    engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE", "tianxia.talent.radiance.dawnmark_scripture", cl=10),
                      foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
    sure_hit(engine)
    dawnmarked(engine)
    radiant_immunity(engine)
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    assert len(damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")) == 1  # the hit landed, its damage did not
    assert engine.state.actors[ME].turn_flags.get("_round_dawnmark_scripture_unclean") is None
    engine.state.actors[FOE].modifiers.clear()
    engine.typed_passive_rows[FOE] = [row for row in engine.typed_passive_rows[FOE] if row["block"] != "resistance"]
    engine.state.actors[ME].action_available = True
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    assert len(damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")) == 2  # the prevented hit spent nothing


def test_dawnmark_scripture_counts_damage_absorbed_by_temporary_hit_points():
    """Damage the target soaks with Temporary HP is still damage dealt, so the bonus still applies."""
    engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE", "tianxia.talent.radiance.dawnmark_scripture", cl=10),
                      foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
    sure_hit(engine)
    dawnmarked(engine)
    engine._grant_temp_hp(engine.state.actors[FOE], 500, "test:temp_hp", ME)
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    assert engine.state.actors[FOE].current_hp == engine.state.actors[FOE].maximum_hp  # nothing reached the HP pool
    assert len(damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")) == 2


def test_dawnmark_scripture_bonus_is_once_per_turn_across_the_whole_round_not_just_the_owners():
    """"Once per turn" is the current turn, whoever is acting: a second hit in the same turn adds nothing, and a hit
    on another creature's turn -- an Opportunity Attack, here -- is a new turn and does get the die. A flag cleared
    only at the owner's turn start would wrongly suppress that off-turn hit."""
    engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE", "tianxia.talent.radiance.dawnmark_scripture", cl=10),
                      foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"), me_at=(5, 6), foe_at=(6, 6))
    sure_hit(engine)
    dawnmarked(engine)
    for expected in (2, 1):  # the second strike in the same turn does not add the die again
        before = len(engine.rolls)
        C4.use(engine, "Radiance Strike", target=FOE)
        assert len(damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")) == expected
        engine.state.actors[ME].action_available = True
    C4.turn(engine, FOE)
    before = len(engine.rolls)
    C4.use(engine, "Move to 9,6", actor_id=FOE)  # leaving reach: her Opportunity Attack is a hit on the foe's turn
    assert damage_rolls(engine, before, ""), "the Opportunity Attack should have dealt damage"
    assert engine.state.actors[ME].turn_flags.get("_round_dawnmark_scripture_unclean") == f"{engine.state.round_number}:{FOE}"
    C4.turn(engine, ME)
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    assert len(damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")) == 2  # her own turn again is a new turn


def test_dawnmark_scripture_stays_spent_and_recharges_around_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    me = C4.bundle("RADIANCE_BASE_STRIKE", "tianxia.talent.radiance.dawnmark_scripture", cl=10)
    foe = kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead", ac=0)  # printed AC 0: the strike hits unless a natural 1
    session = persistence.create_match(match_seed="C12-SCRIPTURE", typed_bundles=(me, foe), roster_setup={
        "primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})
    while session.engine.state.current_actor_id != ME:
        c = next(c for c in session.engine.legal_candidates() if c.display_name == "End turn")
        session.submit_intent(ActionIntent(intent_id=f"end-{c.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                           state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids),
                              primary_decision_record=None, reaction_provider=None)
    assert creature_kinds.is_unclean(session.engine.state.actors[FOE])

    def strike(intent_id):
        c = next(c for c in session.engine.legal_candidates()
                 if c.display_name == "Radiance Strike" and FOE in (c.target_ids or ()))
        before = len(session.engine.rolls)
        session.submit_intent(ActionIntent(intent_id=intent_id, decision_id=c.decision_id, candidate_id=c.candidate_id,
                                           state_version=c.state_version, actor_id=ME, target_ids=c.target_ids),
                              primary_decision_record=None, reaction_provider=None)
        return len([r for r in session.engine.rolls[before:] if str(r.reason).startswith("DAMAGE")])

    assert strike("mark-it") == 1  # this strike places the Dawnmark
    session.engine.state.actors[ME].action_available = True
    assert strike("spend-it") == 2  # and this one damages an already-Dawnmarked Unclean
    loaded = persistence.load_match(session.match_id)
    engine = loaded.engine
    # The once-per-turn use must survive a reload as the current turn's stamp, not as a bool: a string, so it is
    # still comparable to the turn it was spent in and a different turn reads as unspent.
    stamp = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    assert engine.state.actors[ME].turn_flags.get("_round_dawnmark_scripture_unclean") == stamp
    assert creature_kinds.is_unclean(engine.state.actors[FOE])
    assert typed_executor.bears_mark(engine.state.actors[FOE], ME, "Dawnmark")
    # behaviour, not just the stored flag: the same turn is still spent after the reload...
    engine.state.actors[ME].action_available = True
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    assert len([r for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE")]) == 1
    # ...and the next turn is not.
    C4.turn(engine, FOE)
    C4.turn(engine, ME)
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    assert len([r for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE")]) == 2


def test_dawnmark_scripture_bonus_is_its_own_roll_even_on_a_critical():
    """'add 1d8 Radiant damage' is a separate benefit, not dice added to the triggering attack's roll, so a natural
    20 doubles the attack's own damage dice and leaves the bonus a single d8. (Pinned here because the first report
    for this lane claimed the opposite without evidence.)"""
    engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE", "tianxia.talent.radiance.dawnmark_scripture", cl=10),
                      foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
    sure_hit(engine)
    dawnmarked(engine)
    force_d20(engine, 20, 20)  # the attack roll is a natural 20: a landed critical
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    rolls = [r for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE") and "RADIANCE_BASE_STRIKE" in str(r.reason)]
    assert len(rolls) == 2, [str(r.reason) for r in rolls]
    attack, bonus = rolls
    assert attack.expression.startswith("4d8") and len(attack.dice) == 4, attack.expression  # the strike's own 2d8, doubled
    assert bonus.expression.startswith("1d8") and len(bonus.dice) == 1, bonus.expression  # the bonus stays one d8


def test_radiance_unclean_lines_are_typed_and_no_longer_gm_only():
    """These riders used to ask the GM to decide, and the rewrite for Daybreak Seal leaked its own code names.
    Substring membership over every rider of both records, so restoring an old rider fails here rather than
    slipping past a ``startswith`` that never matched it in the first place."""
    keys = ("tianxia.talent.radiance.daybreak_seal", "tianxia.talent.radiance.dawnmark_scripture")
    code_names = ("disadvantage_if_kind", "creature_kinds", "combat/ext", "extra_damage", "if_creature_kind", "if_marked")
    obsolete = ("GM-only: the table has no data tagging a creature as Unclean",  # the GM-only riders these replaced
                "If the target is Unclean", "Once per turn when you damage", "when your attack damages")
    for key in keys:
        riders = [str(r) for r in mech(key)["riders"]]
        # A fully typed Daybreak save has no residual GM rider to print.
        assert riders or key == 'tianxia.talent.radiance.daybreak_seal', key
        for rider in riders:
            for text in obsolete + code_names:
                assert text not in rider, f"{key}: {text!r} is still in {rider!r}"
    # Daybreak Seal: the printed Disadvantage is a save row, not a note to the GM
    save = mech("tianxia.talent.radiance.daybreak_seal")["modifier"]["effects"][0]["effects"][0]
    assert save["disadvantage_if_kind"] == ["unclean"]
    # Dawnmark Scripture: the 1d8 is no longer a typed modifier, so "when you damage" is not narrowed to an
    # attack in the talent's own Sphere. The plug-in (combat/ext/radiance_dawnmark.py) applies it on actual
    # damage. (The record still carries the builder's own model_v2 default modifier auto-read from the printed
    # text; what must be gone is the reviewed row that gated the 1d8 to an in-Sphere attack's hit.)
    scripture = mech("tianxia.talent.radiance.dawnmark_scripture")
    assert scripture["modifier"]["scope"] != "any_attack"
    assert not [row for row in scripture["modifier"]["effects"] if row.get("once_per_turn") or row.get("type") == "if_creature_kind"]
    from combat.ext import radiance_dawnmark
    assert radiance_dawnmark.SCRIPTURE_TURN_FLAG.startswith("_round_")  # the current turn, not the owner's next one


# ============================================================================================ 3. escape options (granted actions)
from combat.ext import escape_options  # noqa: E402

BREAK, HELP = "Break free", "Help a creature next to you break free"


def records(actor):
    return escape_options.options(actor)


def run_rows(engine, key, user=ME, target=FOE, dc=16, cl=15, name=None):
    """Run ``key``'s typed rows from a compiled action of the user at ``target`` (the activation itself needs its own trigger)."""
    action = engine.action_catalog[C4.action_id(engine, user, name)] if name else next(
        engine.action_catalog[a] for a in engine.state.actors[user].action_ids)
    rows = mech(key)["effects"]
    typed = {"numbers": {"pb": 4, "cl": cl, "save_dc": dc, "key_mod": 2}, "effects": rows, "riders": []}
    ctx = typed_executor.Context(engine, engine.state.actors[user], action, None, typed, [engine.state.actors[target]], engine.state.actors[target], {})
    typed_executor.run_effects(ctx, rows)
    return action.source_definition_id


def test_escape_lines_are_typed_and_no_longer_gm_riders():
    gone = {"TAL_ICE_FROZEN_MERIDIAN_BIND": "A Restrained creature can use its Action to repeat",
            "TAL_SHIELD_HEAVEN_CRUSHING_SHIELD_DESCENT": "A creature may use an Action to make a Strength (Athletics)",
            "tianxia.talent.stars.constellation_prison": "A restrained target may also use its Action",
            "tianxia.talent.illusion.substantial_phantasm": "or until it successfully Studies the illusion"}
    for key, line in gone.items():
        assert not [r for r in mech(key)["riders"] if str(r).startswith(line)], key
        assert '"escape_option"' in json.dumps(mech(key)["effects"]), key


def test_constellation_prison_gives_the_prisoner_a_strength_or_charisma_check():
    engine = C4.fight(C4.bundle("tianxia.talent.stars.constellation_prison", cl=10, dc=16), foe_at=(8, 6))
    force_d20(engine, 1, 1)  # the Charisma save fails
    C4.use(engine, "Constellation Prison", target=FOE)
    foe = engine.state.actors[FOE]
    (prison,) = C4.held(foe, "constellation_prison")
    ((key, record),) = records(foe)
    assert record.data["guards"] == [prison.instance_id] and record.data["abilities"] == ["STR", "CHA"] and record.data["dc"] == 16
    assert "Strength or Charisma check against DC 16" in record.data["label"]
    C4.turn(engine, FOE)
    assert [c for c in engine.legal_candidates() if c.display_name == BREAK and c.actor_id == FOE]
    force_d20(engine, 20, 20)
    events = C4.use(engine, BREAK, actor_id=FOE)
    check = next(e for e in events if e.event_type == "CHECK_ROLLED")
    assert check.payload["success"] and check.payload["dc"] == 16
    assert not C4.held(foe, "constellation_prison") and not records(foe)
    assert any("breaks free of Constellation Prison" in line for line in notes(events))
    # Nothing held any more: the button is gone.
    foe.action_available = True
    assert not [c for c in engine.legal_candidates() if c.display_name == BREAK and c.actor_id == FOE]


def test_a_failed_break_free_spends_the_action_and_keeps_the_prison():
    engine = C4.fight(C4.bundle("tianxia.talent.stars.constellation_prison", cl=10, dc=16), foe_at=(8, 6))
    force_d20(engine, 1, 1)
    C4.use(engine, "Constellation Prison", target=FOE)
    C4.turn(engine, FOE)
    events = C4.use(engine, BREAK, actor_id=FOE)  # natural 1s
    assert not next(e for e in events if e.event_type == "CHECK_ROLLED").payload["success"]
    foe = engine.state.actors[FOE]
    assert C4.held(foe, "constellation_prison") and records(foe) and not foe.action_available


def test_the_record_goes_when_the_prison_ends_another_way():
    engine = C4.fight(C4.bundle("tianxia.talent.stars.constellation_prison", cl=10, dc=16), foe_at=(8, 6))
    force_d20(engine, 1, 1)
    C4.use(engine, "Constellation Prison", target=FOE)
    engine._end_concentration(engine.state.actors[ME], "TEST")
    C4.turn(engine, FOE)
    foe = engine.state.actors[FOE]
    assert not C4.held(foe, "constellation_prison") and not records(foe)
    assert not [c for c in engine.legal_candidates() if c.display_name == BREAK]


def test_frozen_meridian_bind_lets_the_restrained_creature_repeat_the_save_as_an_action():
    engine = C4.fight(C4.bundle("TAL_ICE_FROZEN_MERIDIAN_BIND", cl=10), foe_at=(4, 6))
    force_d20(engine, 1, 1)
    run_rows(engine, "TAL_ICE_FROZEN_MERIDIAN_BIND", dc=16)
    foe = engine.state.actors[FOE]
    ((key, record),) = records(foe)
    assert record.data["kind"] == "save" and "repeat the Strength saving throw (DC 16)" in record.data["label"]
    C4.turn(engine, FOE)
    force_d20(engine, 20, 20)
    events = C4.use(engine, BREAK, actor_id=FOE)
    assert [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert not C4.held(foe, "restrained") and not records(foe)


def test_heaven_crushing_shield_descent_can_be_broken_by_a_creature_next_to_the_held_one():
    engine = C4.fight(C4.bundle("TAL_SHIELD_HEAVEN_CRUSHING_SHIELD_DESCENT", cl=15),
                      ally=C4.bundle("SAND_BASE_SCOURING_HAND", actor_id=ALLY, cl=5), ally_at=(3, 7), foe_at=(4, 7))
    # The printed save affects hostile creatures only. Make the held creature
    # hostile to the caster and let its own adjacent teammate help it escape.
    engine.state.actors[ALLY].team_id = engine.state.actors[FOE].team_id
    force_d20(engine, 1, 1)
    run_rows(engine, "TAL_SHIELD_HEAVEN_CRUSHING_SHIELD_DESCENT", target=ALLY, dc=16)
    held = engine.state.actors[ALLY]
    assert C4.held(held, "restrained") and records(held)[0][1].data["help"] == 1
    helper = C4.turn(engine, FOE)
    offered = [c for c in engine.legal_candidates() if c.display_name == HELP and c.actor_id == FOE]
    assert offered and all(ALLY in c.target_ids and FOE not in c.target_ids for c in offered)
    force_d20(engine, 20, 20)
    events = C4.use(engine, HELP, target=ALLY, actor_id=FOE)
    check = next(e for e in events if e.event_type == "CHECK_ROLLED")
    assert check.actor_id == FOE and check.payload["success"]
    assert not C4.held(held, "restrained") and not helper.action_available
    assert any("helps" in line and "breaks free of Heaven-Crushing Shield Descent" in line for line in notes(events))


def test_substantial_phantasm_gets_a_free_study_check_at_the_end_of_its_turn():
    engine = C4.fight(C4.bundle("tianxia.talent.illusion.substantial_phantasm", cl=10), foe_at=(4, 6))
    force_d20(engine, 1, 1)
    run_rows(engine, "tianxia.talent.illusion.substantial_phantasm", dc=16)
    foe = engine.state.actors[FOE]
    assert C4.held(foe, "grappled") and records(foe)[0][1].data["skill"] == "Investigation"
    C4.turn(engine, FOE)
    force_d20(engine, 20, 20)
    before = len(engine.events)
    engine.end_turn()  # the free Study check at the end of its turn
    check = [e for e in engine.events[before:] if e.event_type == "CHECK_ROLLED" and e.actor_id == FOE]
    assert check and check[0].payload["success"] and "Investigation" in check[0].payload["check"]
    assert not C4.held(foe, "grappled") and not records(foe)


def test_substantial_phantasm_has_one_save_and_study_ends_it_before_expiry():
    source = "tianxia.talent.illusion.substantial_phantasm"
    engine = C4.fight(C4.bundle(source, cl=10), foe_at=(4, 6))
    force_d20(engine, 1, 1)
    before = len(engine.events)
    run_rows(engine, source, dc=16)
    assert len([e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED"]) == 1
    foe = engine.state.actors[FOE]
    assert len(C4.held(foe, "grappled")) == 1
    C4.turn(engine, FOE)
    force_d20(engine, 20, 20)
    C4.use(engine, BREAK, actor_id=FOE)
    assert engine.state.current_actor_id == FOE
    assert not C4.held(foe, "grappled") and not records(foe)


def test_an_escape_record_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    me = C4.bundle("tianxia.talent.stars.constellation_prison", cl=10, dc=60)  # the Charisma save cannot succeed
    foe = C4.bundle("SAND_BASE_SCOURING_HAND", actor_id=FOE, cl=5, score=30)  # Strength/Charisma +10
    session = persistence.create_match(match_seed="C12-ESCAPE", typed_bundles=(me, foe), roster_setup={
        "primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 8, "y": 6}}})

    def submit(engine_session, name, actor, target=None):
        c = next(c for c in engine_session.engine.legal_candidates() if c.display_name == name and c.actor_id == actor
                 and (target is None or target in (c.target_ids or ())))
        engine_session.submit_intent(ActionIntent(intent_id=f"{name}-{c.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                                  state_version=c.state_version, actor_id=actor, target_ids=c.target_ids),
                                     primary_decision_record=None, reaction_provider=None)

    while session.engine.state.current_actor_id != ME:
        submit(session, "End turn", session.engine.state.current_actor_id)
    submit(session, "Constellation Prison", ME, FOE)
    (record,) = [c for _k, c in records(session.engine.state.actors[FOE])]
    assert all(type(v) in (str, int, list) for v in record.data.values())
    loaded = persistence.load_match(session.match_id)
    (again,) = [c for _k, c in records(loaded.engine.state.actors[FOE])]
    assert again.data == record.data
    while loaded.engine.state.current_actor_id != FOE:
        submit(loaded, "End turn", loaded.engine.state.current_actor_id)
    assert [c for c in loaded.engine.legal_candidates() if c.display_name == BREAK and c.actor_id == FOE]


def test_no_break_free_button_without_a_record():
    engine = C4.fight(C4.bundle("tianxia.talent.stars.constellation_prison", cl=10, dc=16), foe_at=(8, 6))
    C4.turn(engine, FOE)
    assert not [c for c in engine.legal_candidates() if c.display_name in (BREAK, HELP)]


# ============================================================================================ 4. effective size
from tests import test_riders_c2 as C2  # noqa: E402

WS = "TAL_GRAVITY_WEIGHT_SHIFT_BASE"


def shove_save(engine, target_id, *, max_larger=0, rows=None):
    """The foe makes the size-limited save of a shove at ``target_id`` ("no more than one size larger": max_larger)."""
    foe = engine.state.actors[C2.L1.AN]
    target = engine.state.actors[target_id]
    ctx = typed_executor.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {"pb": 4, "save_dc": 99}}, [target], target, {})
    before = len(engine.events)
    typed_executor.block_save(ctx, {"type": "save", "ability": "str", "max_size_larger": max_larger, "applies_to": "target",
                                    "on_fail": rows or [{"type": "forced_movement", "distance_ft": 5, "direction": "away", "applies_to": "target"}]})
    return [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == target_id]


def test_body_heavying_counts_one_size_larger_against_a_shove():
    engine = C2._fight(C2._bundle([WS]))
    assert shove_save(engine, C2.ME)  # Medium against Medium: the shove applies
    C2._act(engine, "Weight Shift: Body Heavying")
    assert not shove_save(engine, C2.ME)  # one size larger than the shover: out of its "your size" limit
    assert shove_save(engine, C2.ME, max_larger=1)  # but a "one size larger" limit still reaches it


def test_body_heavying_counts_against_a_large_or_smaller_push():
    engine = C2._fight(C2._bundle([WS]))
    C2._act(engine, "Weight Shift: Body Heavying")
    foe = engine.state.actors[C2.L1.AN]
    me = engine.state.actors[C2.ME]
    ctx = typed_executor.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {"pb": 4}}, [me], me, {})
    start = (me.position.x, me.position.y)
    typed_executor.block_forced_movement(ctx, {"type": "forced_movement", "distance_ft": 10, "direction": "away", "applies_to": "target", "max_size_cells": 1})
    assert (me.position.x, me.position.y) == start  # "Medium or smaller": a Body Heavying creature counts as Large


def test_mountain_body_makes_it_two_sizes_against_forced_movement_but_one_against_prone():
    engine = C2._fight(C2._bundle([WS, "tianxia.talent.gravity.mountain_body"], cl=5))
    C2._act(engine, "Weight Shift: Body Heavying")
    assert not shove_save(engine, C2.ME, max_larger=1)  # pushed: two sizes larger, beyond "one size larger"
    assert shove_save(engine, C2.ME, max_larger=1, rows=[{"type": "condition", "condition": "prone", "applies_to": "target"}])  # Prone: one


def test_size_without_any_step_is_the_footprint():
    engine = C2._fight(C2._bundle([WS]))
    from combat.ext import effective_size

    me = engine.state.actors[C2.ME]
    foe = engine.state.actors[C2.L1.AN]
    ctx = typed_executor.Context(engine, foe, next(iter(engine.action_catalog.values())), None, {"numbers": {"pb": 4}}, [me], me, {})
    push = {"type": "forced_movement", "distance_ft": 5, "direction": "away", "applies_to": "target"}
    assert typed_executor.size_width(ctx, me, "subject", push) == engine._footprint(me).width_cells
    assert effective_size.purposes_of([{"type": "condition", "condition": "grappled"}]) == {"grapple"}
    assert effective_size.purposes_of({"type": "save", "on_fail": [push]}) == {"forced", "shove"}


def test_the_escape_record_reads_plainly_on_the_table():
    from combat.ext import escape_options as eo

    engine = C4.fight(C4.bundle("tianxia.talent.stars.constellation_prison", cl=10, dc=16), foe_at=(8, 6))
    force_d20(engine, 1, 1)
    C4.use(engine, "Constellation Prison", target=FOE)
    ((key, record),) = records(engine.state.actors[FOE])
    row = {"condition_id": record.condition_id}
    described = eo._status(engine, engine.state.actors[FOE], row, dict(record.data))
    assert described["text"].startswith("Constellation Prison: use an Action to make a Strength or Charisma check against DC 16")
    assert "Break free" in described["handling"] and "escape_option" not in described["text"]
    assert eo._button({"parameters": engine.action_catalog[eo.SELF_ACTION].parameters}).startswith("Use your Action")
