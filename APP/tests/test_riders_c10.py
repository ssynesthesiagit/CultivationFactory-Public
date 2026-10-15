"""Rider lane C10 (2026-09-30, owner: "i want everything we can automated, keep going until its only the non-combat ones left").

Engine- and table-level regressions compiling real characters for the GM lines this lane automated, sphere by sphere in the
lane's order (Alchemy, Ash, Axes, Barrage, Beastmastery, Beauty, Blacksmith, Chains, Death, Drunken Style, Dual Wielding,
Flowing River, Iron Fist, Lightning). C10_OLD=1 compiles against the base typing (a9d0770f) to show a test needs the change.
Plug-ins are imported inside the tests so the file is collected on the base code too.
"""

import json
import os
import subprocess
import zipfile
from functools import lru_cache
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.riders_c10"
ALLY = "actor:factory.riders_c10_ally"
BASE = "a9d0770f"
JIAN = "tianxia.mortal.weapon.jian"
BOW = "tianxia.mortal.weapon.gong_jian"


@lru_cache(maxsize=1)
def authority():
    if os.environ.get("C10_OLD") == "1":
        return json.loads(subprocess.check_output(["git", "show", f"{BASE}:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"], cwd=ROOT))
    return json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())


def sheet(ids, *, cl=10, dc=15, sphere=None, items=(JIAN,), pool=30, ac=14, pb=4, score=14, key="WIS", bases=True):
    mech = authority()["mechanics"]
    sphere = sphere or (mech[ids[0]]["sphere_id"] if ids else None)
    bases = [k for k, row in mech.items() if bases and sphere and row.get("sphere_id") == sphere and row.get("kind") == "base_ability"]
    return {
        "identity": {"proficiency_bonus": pb, "cultivation_level": cl, "path": "Qi Cultivation", "key_ability": key},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": score, "modifier": (score - 10) // 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": pool}, "armor_class": {"base_value": ac}, "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8},
        "spheres_and_talents": {"sphere_record_ids": [sphere] if sphere else [],
                                "learned_talent_record_ids": list(dict.fromkeys([*bases, *ids]))},
        "equipment": [{"starting_kit": {"items": [{"item_id": item, "quantity": 1} for item in items]}}],
    }


def bundle(ids, *, actor_id=ME, **kwargs):
    return compile_character(sheet(ids, **kwargs), actor_id=actor_id, typed_authority=authority())


def fight(ids, *, foe_at=(8, 6), ally=False, ally_ids=(), ally_sphere=None, foe_ids=(), foe_sphere=None, foe_items=(JIAN,), **kwargs):
    bundles = [bundle(ids, **kwargs), bundle(list(foe_ids), actor_id=AN, sphere=foe_sphere, items=foe_items)]
    teams, places = {ME: "team:a", AN: "team:b"}, {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}
    if ally:
        bundles.append(bundle(list(ally_ids), actor_id=ALLY, sphere=ally_sphere))
        teams[ALLY], places[ALLY] = "team:a", {"x": 3, "y": 9}
    engine = Gate4ControllerEngine(ROOT, match_seed="C10", typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": list(teams), "team_by_actor": teams, "starting_positions": places})
    turn(engine, ME)
    foe = engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 1000
    return engine


def turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def names(engine):
    return [c.display_name for c in engine.legal_candidates()]


def use(engine, name, *, target=None, actor_id=None, destination=None):
    actor_id = actor_id or engine.state.current_actor_id
    actor = engine.state.actors[actor_id]
    actor.action_available = actor.bonus_action_available = True
    from tests.equipment_readiness import ready_weapon
    ready_weapon(engine, name, actor_id)
    candidates = [c for c in engine.legal_candidates() if c.display_name == name and (target is None or target in c.target_ids)
                  and (destination is None or (c.destination is not None and (c.destination.x, c.destination.y) == destination))]
    assert candidates, (name, target, sorted(set(names(engine)))[:80])
    candidate = candidates[0]
    start = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"c10-{start}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return engine.events[start:]


def answers(engine, selections):
    """Answer extension choices by the choice id's suffix; None declines, a missing key takes the first options."""
    asked = []

    def provider(request):
        spec = request.get("extension_choice")
        if spec is None:
            return ReactionDecision(**{key: request[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")},
                                    selection="USE", option_ids=()), None
        asked.append(request["reaction_source_id"])
        chosen = next((value for suffix, value in selections.items() if request["reaction_source_id"].endswith(suffix)),
                      spec["option_ids"][:max(1, spec["minimum_selections"])])
        base = {key: request[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")}
        return ReactionDecision(**base, selection="DECLINE" if chosen is None else "USE", option_ids=tuple(chosen or [])), None
    engine.set_reaction_provider(provider)
    return asked


def riders(key):
    return authority()["mechanics"][key]["riders"]


# ------------------------------------------------------------------------------------------------ table level
def _portable(tmp_path, name, ids, **kwargs):
    folder = tmp_path / "portable_characters" / name
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet(ids, **kwargs)))


def _table(tmp_path, projects, seed):
    """A MANUAL table fight of the listed portable characters against one rival; the first project's turn."""
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService

    _portable(tmp_path, "rival", [], sphere=None)
    service = CombatService(ROOT, tmp_path)
    everyone = [*projects, "rival"]
    view = service.create_factory_match(project_ids=list(projects), opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "rival"],
                                        control_modes={FACTORY_ACTOR_PREFIX + side: "MANUAL" for side in everyone}, match_seed=seed)
    mid = view["match_id"]
    table = TabletopService(service, tmp_path)
    return service, table, mid


def _to_turn(table, mid, actor_id):
    for _ in range(8):
        state = table.state(mid)
        if state["menu"]["actor_id"] == actor_id:
            return state
        table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"])
    raise AssertionError("never reached " + actor_id)


def _act(table, mid, state, option):
    menu = state["menu"]
    result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED", result
    return result


def _reload(tmp_path, mid):
    from combat.gate5_service import CombatService

    return CombatService(ROOT, tmp_path)._load_session(mid)


# ================================================================================================ Alchemy
ALCHEMY_KIT = ["ALCHEMY_BASE_FIELD_FORMULA", "ALCHEMY_BASE_REAGENT_STOCK"]
STOCK = "resource:named.reagent_stock"


@pytest.mark.parametrize("pb,score,sealed,size", [(4, 14, False, 6), (4, 14, True, 10), (2, 6, False, 1), (3, 16, False, 6)])
def test_reagent_stock_starts_with_the_uses_prepared_at_the_long_rest(pb, score, sealed, size):
    ids = [*ALCHEMY_KIT, *(["TAL_ALCHEMY_SEALED_DOSE_METHOD"] if sealed else [])]
    resources = {row["resource_id"]: row for row in bundle(ids, pb=pb, score=score)["actor_template"]["resources"]}
    assert (resources[STOCK]["initial"], resources[STOCK]["maximum"]) == (size, size)  # PB + key modifier (min 1) [+ PB]


def test_field_formula_is_usable_and_spends_one_prepared_use():
    engine = fight(ALCHEMY_KIT, ally=True)
    me = engine.state.actors[ME]
    assert me.resources[STOCK] == 6
    use(engine, "Field Formula: Medicinal Smoke", target=ALLY)
    assert me.resources[STOCK] == 5
    assert engine.state.actors[ALLY].temporary_hp > 0


def test_sealed_dose_is_administered_once_by_an_ally():
    engine = fight([*ALCHEMY_KIT, "TAL_ALCHEMY_SEALED_DOSE_METHOD"], ally=True)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    label = f"Sealed Dose from {me.display_name}: Medicinal Smoke"
    assert label not in names(engine)  # the alchemist's own turn: the dose is carried by an ally
    turn(engine, AN)
    assert label not in names(engine)  # never the other side
    turn(engine, ALLY)
    assert label in names(engine)
    events = use(engine, label, target=ALLY)
    assert ally.temporary_hp > 0 and me.resources["resource:named.sealed_dose"] == 0
    assert me.resources[STOCK] == 10  # its own dose, not a prepared Reagent Stock use
    assert any(e.event_type == "TEMP_HP_GRANTED" for e in events)
    assert label not in names(engine)  # one dose


def test_reagent_stock_and_sealed_dose_riders_moved_out():
    assert not any("prepare a number of Reagent Stock uses" in line for line in riders("ALCHEMY_BASE_REAGENT_STOCK"))
    assert not any("maximum increases by your Proficiency Bonus" in line for line in riders("TAL_ALCHEMY_SEALED_DOSE_METHOD"))


def test_sealed_dose_survives_table_commit_and_reload(tmp_path):
    from combat.gate5_service import FACTORY_ACTOR_PREFIX

    _portable(tmp_path, "brewer", [*ALCHEMY_KIT, "TAL_ALCHEMY_SEALED_DOSE_METHOD"])
    _portable(tmp_path, "friend", [], sphere=None)
    service, table, mid = _table(tmp_path, ["brewer", "friend"], "C10-SEALED-DOSE")
    friend, brewer = FACTORY_ACTOR_PREFIX + "friend", FACTORY_ACTOR_PREFIX + "brewer"
    state = _to_turn(table, mid, friend)
    group = next(g for g in state["menu"]["actions"] if g["source_definition_id"].endswith(".alchemy.sealed_dose"))
    option = next(o for o in group["options"] if friend in (o.get("target_ids") or []))
    _act(table, mid, state, option)
    loaded = _reload(tmp_path, mid)
    assert loaded.engine.state.actors[brewer].resources["resource:named.sealed_dose"] == 0
    assert loaded.engine.state.actors[friend].temporary_hp > 0
    assert loaded.mechanical.replay()["status"] == "PASS"


# ================================================================================================ Ash
def _ashfall(engine):
    return next(c.display_name for c in engine.legal_candidates() if c.display_name.startswith("Ashfall at "))


def test_lingering_ashfall_keeps_the_area_without_concentration():
    engine = fight(["ASH_BASE_ASHFALL"], foe_at=(12, 6))
    me = engine.state.actors[ME]
    assert "Lingering Ashfall (2 CP)" not in names(engine)  # nothing to keep yet
    use(engine, _ashfall(engine))
    zone = next(z for z in engine.state.zones.values() if z.active)
    assert zone.concentration_link and me.concentration is not None
    qi = me.resources["resource:core.qi"]
    use(engine, "Lingering Ashfall (2 CP)")
    assert me.resources["resource:core.qi"] == qi - 2
    assert zone.active and not zone.concentration_link and me.concentration is None
    assert "Lingering Ashfall (2 CP)" not in names(engine)
    engine._concentration_check(me, 1000)  # a lost Concentration no longer takes it
    assert zone.active


def test_lingering_ashfall_reaches_an_older_held_concentration():
    engine = fight(["ASH_BASE_ASHFALL"], foe_at=(12, 6))
    me = engine.state.actors[ME]
    use(engine, "Ashfall at 8,9")
    use(engine, "Ashfall at 12,2")  # a second copy (Factory characters hold any number); the first is now held
    first, second = sorted((z for z in engine.state.zones.values() if z.active), key=lambda z: z.zone_id)
    answers(engine, {"lingering_area": [first.zone_id]})
    use(engine, "Lingering Ashfall (2 CP)")
    assert not first.concentration_link and first.active
    assert second.concentration_link and me.concentration is not None and me.concentration.zone_id == second.zone_id


def test_ashfall_riders_are_automated():
    assert riders("ASH_BASE_ASHFALL") == []


def test_lingering_ashfall_survives_table_commit_and_reload(tmp_path):
    from combat.gate5_service import FACTORY_ACTOR_PREFIX

    _portable(tmp_path, "ashen", ["ASH_BASE_ASHFALL"])
    service, table, mid = _table(tmp_path, ["ashen"], "C10-LINGER")
    ashen = FACTORY_ACTOR_PREFIX + "ashen"
    state = _to_turn(table, mid, ashen)
    group = next(g for g in state["menu"]["actions"] if g["source_definition_id"].endswith("ASH_BASE_ASHFALL"))
    _act(table, mid, state, group["options"][0])
    state = table.state(mid)
    group = next(g for g in state["menu"]["actions"] if "lingering_area" in g["source_definition_id"])
    _act(table, mid, state, group["options"][0])
    loaded = _reload(tmp_path, mid)
    zones = [z for z in loaded.engine.state.zones.values() if z.active]
    assert len(zones) == 1 and not zones[0].concentration_link and zones[0].duration_rounds == 10
    assert loaded.engine.state.actors[ashen].concentration is None
    assert loaded.mechanical.replay()["status"] == "PASS"


# ================================================================================================ Axes
AXE = "tianxia.mortal.weapon.fu"
SPLIT_KIT = ["TAL_AXES_HEWING_STRIKE", "TAL_AXES_SPLIT_THE_CHAIN"]
RESTRAINED = "condition:typed.restrained"


def _rig_check(engine, natural, word):
    original = engine.roller.d20

    def d20(**kwargs):
        record = original(**kwargs)
        if word in str(kwargs.get("reason") or ""):
            return record.model_copy(update={"natural_result": natural, "total": natural + int(kwargs.get("modifier") or 0),
                                             "dice": (natural,)})
        return record
    engine.roller.d20 = d20


def _split_fight(source="cyclone"):
    engine = fight(SPLIT_KIT, items=(AXE,), ally=True, foe_ids=["TAL_AIR_CYCLONE_PRISON"], foe_sphere="tianxia.sphere.air", foe_at=(12, 6))
    ally = engine.state.actors[ALLY]
    ally.position = Position(x=4, y=6)
    if source == "cyclone":
        src = next(k for k, a in engine.action_catalog.items() if a.owner_id == AN and "CYCLONE_PRISON" in k)
    else:
        src = next(k for k, a in engine.action_catalog.items() if a.owner_id == AN and k.endswith("unarmed.grapple"))
    engine._apply_condition(ally, RESTRAINED, src, AN, expires_on="UNTIL_REMOVED")
    return engine, ally


@pytest.mark.parametrize("natural,left", [(10, "suppressed"), (18, "ended"), (2, "held")])  # +6 against the Cyclone's DC 15
def test_split_the_chain_axes_check_against_a_cultivated_restraint(natural, left):
    engine, ally = _split_fight()
    _rig_check(engine, natural, "Axes Check")
    use(engine, "Hewing Strike: Split the Chain", target=ALLY)
    held = any(c.condition_id == RESTRAINED for c in ally.conditions.values())
    kept = any(c.condition_id == "condition:typed.benefit_suppressed" for c in ally.conditions.values())
    assert (held, kept) == {"suppressed": (False, True), "ended": (False, False), "held": (True, False)}[left]
    turn(engine, AN)
    turn(engine, ME)  # "until the start of your next turn"
    assert any(c.condition_id == RESTRAINED for c in ally.conditions.values()) is (left != "ended")


def test_split_the_chain_needs_a_cultivated_restraint_and_a_held_axe():
    engine, ally = _split_fight(source="grapple")  # a plain Grapple is no cultivation effect
    assert "Hewing Strike: Split the Chain" not in names(engine)
    engine, ally = _split_fight()
    assert "Hewing Strike: Split the Chain" in names(engine)
    me = engine.state.actors[ME]
    axe = next(k for k, a in engine.action_catalog.items() if a.owner_id == ME and k.endswith(".weapon.fu"))
    engine._apply_condition(me, "condition:typed.disarmed", "test:disarm", AN, expires_on="UNTIL_REMOVED",
                            data={"disables_action": axe, "dropped_at": {"x": 3, "y": 6}})
    assert "Hewing Strike: Split the Chain" not in names(engine)  # "You must be wielding an axe weapon"


# ================================================================================================ Barrage
BARRAGE = "tianxia.sphere.barrage"
FOE2 = "actor:factory.riders_c10_foe2"
FOE3 = "actor:factory.riders_c10_foe3"
BOW_NAME = "Gong Jian (Bow and Arrow)"


def barrage_fight(ids, *, foes=1, items=(BOW, JIAN), foe_at=(4, 6)):
    bundles = [bundle(ids, sphere=BARRAGE, items=items), bundle([], actor_id=AN, sphere=None)]
    teams, places = {ME: "team:a", AN: "team:b"}, {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}
    for extra, spot in list(zip((FOE2, FOE3), ({"x": 6, "y": 6}, {"x": 7, "y": 8})))[:foes - 1]:
        bundles.append(bundle([], actor_id=extra, sphere=None))
        teams[extra], places[extra] = "team:b", spot
    engine = Gate4ControllerEngine(ROOT, match_seed="C10-BARRAGE", typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": list(teams), "team_by_actor": teams, "starting_positions": places})
    for foe_id in teams:
        if foe_id != ME:
            foe = engine.state.actors[foe_id]
            foe.maximum_hp = foe.current_hp = 1000
            foe.armor_class = 1  # every attack hits
    turn(engine, ME)
    return engine


def _attacks(events):
    return [(e.target_ids or (None,))[0] for e in events if e.event_type == "ATTACK_ROLLED"]


def test_mixed_barrage_replaces_the_bonus_attack_with_a_melee_attack_unarmed_strike_or_shove():
    engine = barrage_fight(["TAL_BARRAGE_MIXED_BARRAGE"])
    assert not any(n.startswith("Mixed Barrage:") for n in names(engine))  # only after the Mixed primary
    use(engine, f"Barrage: {BOW_NAME} + Mixed Barrage", target=AN)
    assert "Mixed Barrage: Jian (Straight Sword) attack" not in names(engine)  # Bow occupies both hands until stowed.
    from tests.equipment_readiness import ready_weapon
    ready_weapon(engine, "Mixed Barrage: Jian (Straight Sword) attack")
    menu = set(names(engine))
    assert {"Mixed Barrage: Jian (Straight Sword) attack", "Mixed Barrage: Unarmed Strike", "Mixed Barrage: Shove: Prone",
            "Mixed Barrage: Shove: Push 5 ft"} <= menu
    assert f"Barrage follow-up: {BOW_NAME}" not in menu  # replaced, not added
    events = use(engine, "Mixed Barrage: Jian (Straight Sword) attack", target=AN)
    damage = [e.payload for e in events if e.event_type == "DAMAGE_ROLLED"]
    assert _attacks(events) == [AN] and damage and damage[0]["modifier"] == 0  # the Barrage's Bonus Action attack: no +DEX
    assert not any(n.startswith("Mixed Barrage:") for n in names(engine))  # once


def test_mixed_barrage_shove_is_one_shove_as_a_bonus_action():
    engine = barrage_fight(["TAL_BARRAGE_MIXED_BARRAGE"])
    use(engine, f"Barrage: {BOW_NAME} + Mixed Barrage", target=AN)
    events = use(engine, "Mixed Barrage: Shove: Prone", target=AN)
    assert len([e for e in events if e.event_type == "SAVE_ROLLED"]) == 1 and not _attacks(events)
    accepted = next(e for e in events if e.event_type == "INTENT_ACCEPTED")
    assert accepted.payload["kind"] == "BONUS_ACTION"


def test_spinning_shot_two_bonus_attacks_at_different_creatures():
    engine = barrage_fight(["TAL_BARRAGE_SPINNING_SHOT"], foes=3)
    me = engine.state.actors[ME]
    use(engine, f"Barrage: {BOW_NAME} + Spinning Shot", target=AN)
    assert me.resources["resource:core.martial_focus"] == 0  # "Expend Martial Focus"
    assert f"Barrage follow-up: {BOW_NAME}" not in names(engine)
    offered = [c for c in engine.legal_candidates() if c.display_name == f"Spinning Shot: {BOW_NAME}"]
    assert offered and all(AN not in c.target_ids for c in offered)  # not the primary's creature
    answers(engine, {"spinning_shot": [FOE3]})
    events = use(engine, f"Spinning Shot: {BOW_NAME}", target=FOE2)
    assert _attacks(events) == [FOE2, FOE3]


def test_spinning_shot_has_no_second_attack_without_a_third_creature():
    engine = barrage_fight(["TAL_BARRAGE_SPINNING_SHOT"], foes=2)
    use(engine, f"Barrage: {BOW_NAME} + Spinning Shot", target=AN)
    events = use(engine, f"Spinning Shot: {BOW_NAME}", target=FOE2)
    assert _attacks(events) == [FOE2]


@pytest.mark.parametrize("focus,items,reach", [(1, (BOW,), 5), (0, (BOW,), 5), (1, (BOW, JIAN), 5)])
def test_vigilant_sharpshooter_opportunity_attacks_with_the_bow(focus, items, reach):
    from combat import typed_reactions

    engine = barrage_fight(["TAL_BARRAGE_VIGILANT_SHARPSHOOTER"], items=items)
    me = engine.state.actors[ME]
    me.resources["resource:core.martial_focus"] = focus
    assert riders("TAL_BARRAGE_VIGILANT_SHARPSHOOTER")[0].startswith("While holding Martial Focus")
    assert typed_reactions.opportunity_reach(engine, me) == reach
    action, _ = typed_reactions._opportunity_profile(engine, me, typed_reactions._opportunity_row(engine, me))
    weapon = str((action.parameters["typed"] or {}).get("opportunity_of") or "")
    assert weapon.endswith("weapon.gong_jian") is (reach == 10)


def test_barrage_martial_focus_riders_are_how_martial_focus_runs():
    assert riders("TAL_BARRAGE_MARTIAL_FOCUS") == []
    resources = {row["resource_id"]: row for row in bundle(["TAL_BARRAGE_MARTIAL_FOCUS"], sphere=BARRAGE, items=(BOW,))["actor_template"]["resources"]}
    assert resources["resource:core.martial_focus"]["maximum"] == 1  # "you may hold one Martial Focus at a time"


# ================================================================================================ Beastmastery
BEAST = "tianxia.sphere.beastmastery"


def test_mass_tame_beast_tamer_reaches_up_to_pb_creatures_each_saving():
    bundles = [bundle(["TAL_BEASTMASTERY_BEAST_TAMER", "TAL_BEASTMASTERY_MASS_TAME"], sphere=BEAST, dc=40),
               *(bundle([], actor_id=foe, sphere=None) for foe in (AN, FOE2, FOE3))]
    teams = {ME: "team:a", AN: "team:b", FOE2: "team:b", FOE3: "team:b"}
    places = {ME: {"x": 3, "y": 6}, AN: {"x": 5, "y": 6}, FOE2: {"x": 6, "y": 7}, FOE3: {"x": 7, "y": 5}}
    engine = Gate4ControllerEngine(ROOT, match_seed="C10-TAME", typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": list(teams), "team_by_actor": teams, "starting_positions": places})
    turn(engine, ME)
    answers(engine, {"beauty_targets": [AN, FOE2, FOE3]})
    events = use(engine, "Beast Tamer", target=AN)
    saved = {e.actor_id for e in events if e.event_type == "SAVE_ROLLED"}
    assert saved == {AN, FOE2, FOE3}  # each target saves separately (PB 4: up to four)
    charmed = {k for k, a in engine.state.actors.items() if any(c.condition_id == "condition:typed.charmed" for c in a.conditions.values())}
    assert charmed == {AN, FOE2, FOE3}  # DC 40


def test_beast_tamer_without_mass_tame_reaches_one_creature():
    bundles = [bundle(["TAL_BEASTMASTERY_BEAST_TAMER"], sphere=BEAST, dc=40), bundle([], actor_id=AN, sphere=None),
               bundle([], actor_id=FOE2, sphere=None)]
    teams = {ME: "team:a", AN: "team:b", FOE2: "team:b"}
    engine = Gate4ControllerEngine(ROOT, match_seed="C10-TAME", typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": list(teams), "team_by_actor": teams,
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 5, "y": 6}, FOE2: {"x": 6, "y": 7}}})
    turn(engine, ME)
    events = use(engine, "Beast Tamer", target=AN)
    assert {e.actor_id for e in events if e.event_type == "SAVE_ROLLED"} == {AN}


@pytest.mark.parametrize("lookout", [True, False])
def test_lookout_shares_the_highest_passive_perception_with_beast_allies(lookout):
    from combat.ext import eye_common

    ids = ["TAL_BEASTMASTERY_BEAST_TAMER", *(["tianxia.talent.beastmastery.lookout"] if lookout else [])]
    engine = fight(ids, sphere=BEAST, score=6)  # Wisdom 6: passive Perception 8; the wolf's is 11
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    wolf = next(a for a in engine.state.actors.values() if a.summon and a.summon.get("source") == "tamer")
    assert eye_common.passive_perception(engine, wolf, foe) == 11
    assert eye_common.passive_perception(engine, me, foe) == (11 if lookout else 8)
    for index, beast in enumerate(a for a in engine.state.actors.values() if a.summon):  # the tamed wolf and the mount
        beast.position = Position(x=12 + 2 * index, y=12)  # more than 30 feet away: no sharing
    assert eye_common.passive_perception(engine, me, foe) == 8


def test_beastmastery_lines_that_already_run_are_no_longer_gm_riders():
    for key in ("TAL_BEASTMASTERY_DEFENSIVE_RIDER", "TAL_BEASTMASTERY_MEAT_SHIELD", "TAL_BEASTMASTERY_MOUNTED_MANEUVERS",
                "TAL_BEASTMASTERY_RUN_DOWN", "TAL_BEASTMASTERY_SKIRMISH_RIDER", "tianxia.talent.beastmastery.mount_training",
                "tianxia.talent.beastmastery.lookout"):
        assert riders(key) == [], key
    assert not any(line.startswith("Commands:") for line in riders("BEASTMASTERY_BASE_TAMER_PACKAGE"))
    engine = fight(["TAL_BEASTMASTERY_MOUNTED_MANEUVERS", "TAL_BEASTMASTERY_RUN_DOWN", "TAL_BEASTMASTERY_SKIRMISH_RIDER",
                    "TAL_BEASTMASTERY_DEFENSIVE_RIDER"], sphere=BEAST)
    kinds = {row.get("kind") for row in engine.typed_passive_rows[ME] if row.get("block") == "mounts"}
    assert {"mounted_maneuvers", "run_down", "skirmish_rider"} <= kinds  # combat/ext/mounts.py runs them
    assert any(r.get("feature_id") == "TAL_BEASTMASTERY_DEFENSIVE_RIDER" for r in engine.typed_reaction_rows.get(ME, [])
               + engine.typed_passive_rows.get(ME, []))  # combat/ext/mount_guard.py
    tame = next(a for a in engine.state.actors.values() if a.summon and a.summon.get("source") == "tamer") if any(
        a.summon and a.summon.get("source") == "tamer" for a in engine.state.actors.values()) else None
    assert tame is None or tame.summon["command"] == "free"  # "Giving ordinary commands requires no Action"


# ================================================================================================ Beauty
BEAUTY = "tianxia.sphere.beauty"
CHECK_MODE = "condition:typed.check_mode"


def _script(engine, values):
    """The next dice this engine rolls come from ``values`` (in order); after that the seeded roller carries on."""
    queue, roller = list(values), engine.roller
    original = roller._die

    def _die(sides):
        if queue:
            counter = roller.counter
            roller.counter += 1
            return min(int(queue.pop(0)), sides), counter
        return original(sides)
    roller._die = _die


@pytest.mark.parametrize("answer,prone,spent", [(["use"], False, 1), (None, True, 0)])
def test_perfect_posture_is_asked_after_the_d20_and_a_decline_is_not_spent(answer, prone, spent):
    engine = fight(["tianxia.talent.beauty.perfect_posture"], sphere=BEAUTY, foe_at=(4, 6))
    me = engine.state.actors[ME]
    turn(engine, AN)
    asked = answers(engine, {"perfect_posture": answer})
    near = (8 + 4 + 2) - max(me.saving_throws["STR"], me.saving_throws["DEX"]) - 2  # the foe's Shove DC 14; the save fails by 2
    _script(engine, [near, 3])
    events = use(engine, "Shove: Prone", target=ME)
    assert any(a.endswith("perfect_posture") for a in asked)  # the player is asked on the foe's turn
    assert any(c.condition_id == "condition:typed.prone" for c in me.conditions.values()) is prone
    assert len([e for e in events if e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("d4")]) == spent


def test_shared_spotlight_adorns_you_and_one_willing_ally():
    engine = fight(["tianxia.talent.beauty.shared_spotlight"], sphere=BEAUTY, ally=True)
    label = "Adorn the Moment + Shared Spotlight: Advantage on Check"
    offered = [c for c in engine.legal_candidates() if c.display_name == label]
    assert offered and all(c.target_ids == (ALLY,) for c in offered)  # an ally, not yourself
    use(engine, label, target=ALLY)
    for actor_id in (ME, ALLY):  # the same benefit on both
        rules = [c.data["rule"]["check_mode"] for c in engine.state.actors[actor_id].conditions.values() if c.condition_id == CHECK_MODE]
        assert rules and rules[0].get("Persuasion") == "ADVANTAGE"
    engine2 = fight([], sphere=BEAUTY, ally=True)
    assert label not in names(engine2)


def test_courtly_grace_two_skills_are_already_how_adorn_runs():
    from combat import typed_executor

    assert not any("two of the listed skill options" in line for line in riders("tianxia.talent.beauty.courtly_grace"))
    engine = fight(["tianxia.talent.beauty.courtly_grace"], sphere=BEAUTY)
    me = engine.state.actors[ME]
    use(engine, "Adorn the Moment: Advantage on Check", target=ME)
    assert typed_executor.check_mode(me, "CHA", "Persuasion") == typed_executor.check_mode(me, "WIS", "Insight") == "ADVANTAGE"
    assert riders("tianxia.talent.beauty.perfect_posture") == [] and riders("tianxia.talent.beauty.shared_spotlight") == []


# ================================================================================================ Blacksmith
SMITH = "tianxia.sphere.blacksmith"
KIT = "tianxia.talent.blacksmith.portable_forge_kit"
FORGE = "condition:typed.mark.forge_mark." + ME


@pytest.mark.parametrize("kit", [True, False])
def test_portable_forge_kit_starts_the_fight_with_a_forge_mark(kit):
    engine = fight([KIT] if kit else [], sphere=SMITH)
    me = engine.state.actors[ME]
    assert any(c.condition_id == FORGE for c in me.conditions.values()) is kit
    use(engine, "Set Edge")  # a Forge Response spends it, from the first turn
    assert not any(c.condition_id == FORGE for c in me.conditions.values())
    spent = [e for e in engine.events if e.event_type == "CONDITION_REMOVED" and e.payload.get("condition_id") == FORGE]
    assert bool(spent) is kit


def test_portable_forge_kit_mark_survives_table_commit_and_reload(tmp_path):
    from combat.gate5_service import FACTORY_ACTOR_PREFIX

    _portable(tmp_path, "smith", [KIT], sphere=SMITH)
    service, table, mid = _table(tmp_path, ["smith"], "C10-FORGE-KIT")
    smith = FACTORY_ACTOR_PREFIX + "smith"
    state = _to_turn(table, mid, smith)
    before = _reload(tmp_path, mid).engine.state.actors[smith]
    assert any(c.condition_id.startswith("condition:typed.mark.forge_mark.") for c in before.conditions.values())  # saved with the fight
    group = next(g for g in state["menu"]["actions"] if g["source_definition_id"].endswith("blacksmith.set_edge"))
    _act(table, mid, state, group["options"][0])
    loaded = _reload(tmp_path, mid)
    actor = loaded.engine.state.actors[smith]
    assert not any(c.condition_id.startswith("condition:typed.mark.forge_mark.") for c in actor.conditions.values())  # spent
    assert any(c.condition_id.startswith("condition:typed.mark.set_edge_ready.") for c in actor.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


# ================================================================================================ Death
def test_corpse_servants_are_fielded_so_the_animation_line_is_not_a_gm_rider():
    # C14 retains the plain effect description and automates the shared limit.
    assert "You animate a corpse as a full Corpse Servant." in riders("TAL_DEATH_CORPSE_SERVANT")
    assert not any("Death Control Limit" in line for line in riders("TAL_DEATH_CORPSE_SERVANT"))
    engine = fight(["TAL_DEATH_CORPSE_SERVANT"], sphere="tianxia.sphere.death")
    servants = [a for a in engine.state.actors.values() if a.summon and a.summon.get("group") == "corpse_servant"]
    assert len(servants) == 4  # up to the Proficiency Bonus (the Death Control Limit), already with you


# ================================================================================================ Drunken Style
DRUNK = "tianxia.sphere.drunken_style"
IMPROVISED = "condition:typed.improvised"


def test_sleeve_bowl_and_boot_does_not_grant_general_improvised_permission():
    engine = fight(["TAL_DRUNKEN_STYLE_SLEEVE_BOWL_AND_BOOT"], sphere=DRUNK)
    assert not any(n.startswith("Reeling Step + Sleeve") for n in names(engine))
    assert len(riders("TAL_DRUNKEN_STYLE_SLEEVE_BOWL_AND_BOOT")) == 3
    use(engine, "Grab an improvised weapon")
    turn(engine, AN)
    turn(engine, ME)
    assert any(c.condition_id == IMPROVISED for c in engine.state.actors[ME].conditions.values())


# ================================================================================================ Dual Wielding
DUAL = "tianxia.sphere.dual_wielding"
DAGGER, SHORTSWORD = "tianxia.mortal.weapon.bi_shou", "tianxia.mortal.weapon.duan_jian"


def _rig_attack(engine, natural, word):
    original = engine.roller.d20

    def d20(**kwargs):
        record = original(**kwargs)
        reason = str(kwargs.get("reason") or "")
        if reason.startswith("ATTACK:") and word in reason:
            return record.model_copy(update={"natural_result": natural, "total": natural + int(kwargs.get("modifier") or 0),
                                             "dice": (natural,)})
        return record
    engine.roller.d20 = d20


@pytest.mark.parametrize("talent,offhand", [(True, True), (True, False), (False, True)])
def test_critical_follow_up_natural_19_stays_deferred_without_a_second_damage_packet(talent, offhand):
    engine = fight(["TAL_DUAL_WIELDING_CRITICAL_FOLLOW_UP"] if talent else [], sphere=DUAL, items=(DAGGER, SHORTSWORD), foe_at=(4, 6))
    engine.state.actors[AN].armor_class = 1
    _rig_attack(engine, 19, "offhand" if offhand else "weapon.bi_shou")
    first = use(engine, "Bi Shou (Dagger) attack", target=AN)
    events = use(engine, "Duan Jian (Short Sword) off-hand attack", target=AN) if offhand else first
    triggered = [e for e in events if e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("critical_follow_up_roll")]
    assert not triggered  # C15r2 explicitly defers this workaround pending a locked seam.
    committed = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and AN in (e.target_ids or ())]
    assert len(committed) == 1


def test_dual_wielding_lines_that_already_run_are_no_longer_gm_riders():
    # Following Strike and Tandem Offensive moved out of this list in AUTO94: auditing them against the
    # printed text showed they do NOT fully run, so they were honestly reclassified FULL -> CORE and
    # now carry the rider that names the gap (checked just below). Critical Follow-Up moved IN: its
    # "Not automated: your Paired Strike" rider is gone now that the Paired Strike's real 19-20 crit
    # range runs natively.
    for key in ("TAL_DUAL_WIELDING_AMBIDEXTERITY", "TAL_DUAL_WIELDING_GREATER_BLADES",
                "TAL_DUAL_WIELDING_PAIRED_RHYTHM", "TAL_DUAL_WIELDING_CRITICAL_FOLLOW_UP"):
        assert riders(key) == [], key
    assert "Use Following Strike immediately as part of the same Paired Strike action" in riders("TAL_DUAL_WIELDING_FOLLOWING_STRIKE")[0]
    assert "Choose whether your Answering Weapon uses the higher magic bonus" in riders("TAL_DUAL_WIELDING_TANDEM_OFFENSIVE")[0]
    assert riders("TAL_DUAL_WIELDING_COMBO_MANEUVERS")[0] == "a Grapple requires a free hand"  # free hands are not tracked
    catalog = {a["display_name"]: a for a in bundle(["TAL_DUAL_WIELDING_AMBIDEXTERITY", "TAL_DUAL_WIELDING_FOLLOWING_STRIKE",
                                                     "TAL_DUAL_WIELDING_GREATER_BLADES"], sphere=DUAL,
                                                    items=(JIAN, SHORTSWORD))["action_catalog"]}
    assert "Duan Jian (Short Sword) off-hand attack (Ambidexterity)" in catalog  # moved into the Attack action for Martial Focus
    assert any(name.endswith("Following Strike") for name in catalog)  # one more Answering Weapon attack, at a third creature
    assert "Jian (Straight Sword) off-hand attack" in catalog  # Greater Blades: a one-handed weapon without Two-Handed pairs


# ================================================================================================ Flowing River
RIVER = "tianxia.sphere.flowing_river"
FOCUS = "resource:core.martial_focus"
PATIENT = "TAL_FLOWING_RIVER_PATIENT_WATER"


@pytest.mark.parametrize("attacked,focus,after", [(False, 0, 1), (True, 0, 0)])
def test_patient_water_regains_focus_at_the_next_turn_only_if_nobody_attacked(attacked, focus, after):
    engine = fight([PATIENT], sphere=RIVER, bases=False, foe_at=(4, 6))  # without Gather the Current's own regain
    me = engine.state.actors[ME]
    me.resources[FOCUS] = focus
    use(engine, "Dodge")
    assert me.resources[FOCUS] == focus  # not at once: "at the start of that turn"
    turn(engine, AN)
    if attacked:
        use(engine, "Jian (Straight Sword) attack", target=ME)
    turn(engine, ME)
    assert me.resources[FOCUS] == after
    assert not any(c.condition_id == "condition:typed.patient_water" for c in me.conditions.values())


def test_flowing_river_lines_that_already_run_are_no_longer_gm_riders():
    for key in ("TAL_FLOWING_RIVER_GATHER_THE_CURRENT", "TAL_FLOWING_RIVER_PATIENT_WATER"):
        assert riders(key) == [], key
    # AUTO61: pair toggles exist, but printed trigger-specific eligibility is
    # incomplete. Keep testing the toggles below without asserting stale FULL.
    assert any("The GM checks that both talents can affect the triggering creature" in line
               for line in riders("TAL_FLOWING_RIVER_TWO_CURRENTS_MEET"))
    engine = fight(["TAL_FLOWING_RIVER_GATHER_THE_CURRENT"], sphere=RIVER, bases=False, foe_at=(9, 6))
    me = engine.state.actors[ME]
    me.resources[FOCUS] = 0
    events = use(engine, "Disengage")  # as its Action (combat/motion.py regain_focus: Action economy only)
    assert me.resources[FOCUS] == 1 and next(e for e in events if e.event_type == "INTENT_ACCEPTED").payload["kind"] == "ACTION"
    bundle_ids = {a["display_name"] for a in bundle([RESPONSE_ID, "TAL_FLOWING_RIVER_TWO_CURRENTS_MEET", "TAL_FLOWING_RIVER_HAND_ON_THE_WRIST",
                                                     "TAL_FLOWING_RIVER_EMPTY_STEP"], sphere=RIVER)["action_catalog"]}
    assert any("+" in name and name.startswith("Flowing Response:") for name in bundle_ids)  # two Response talents, Martial Focus


RESPONSE_ID = "TAL_FLOWING_RIVER_FLOWING_RESPONSE"


# ================================================================================================ Iron Fist
MEDICINE = "TAL_IRON_FIST_MEDICINE_OF_THE_CLOSED_GATE"


def _held_ally(dc):
    engine = fight([MEDICINE], sphere="tianxia.sphere.iron_fist", ally=True, foe_ids=["TAL_AIR_CYCLONE_PRISON"],
                   foe_sphere="tianxia.sphere.air", foe_at=(12, 6))
    ally = engine.state.actors[ALLY]
    ally.position = Position(x=4, y=6)
    src = next(k for k, a in engine.action_catalog.items() if a.owner_id == AN and "CYCLONE_PRISON" in k)
    engine._apply_condition(ally, RESTRAINED, src, AN, expires_on="UNTIL_REMOVED", data={"origin_save": {"ability": "STR", "dc": dc}})
    return engine, ally


@pytest.mark.parametrize("check,save_dc,freed", [(19, 1, True), (2, 1, False), (19, 40, False)])
def test_medicine_of_the_closed_gate_repeats_a_save_on_a_dc_15_medicine_check(check, save_dc, freed):
    engine, ally = _held_ally(save_dc)
    me = engine.state.actors[ME]
    _rig_check(engine, check, "Medicine")
    events = use(engine, "Medicine of the Closed Gate", target=ALLY)
    assert me.resources["resource:core.martial_focus"] == 0  # "expend Martial Focus"
    assert any(e.event_type == "CHECK_ROLLED" and e.payload.get("dc") == 15 for e in events)
    assert any(e.event_type == "SAVE_ROLLED" and e.actor_id == ALLY for e in events) is (check == 19)
    assert (not any(c.condition_id == RESTRAINED for c in ally.conditions.values())) is freed


def test_medicine_of_the_closed_gate_needs_a_bodily_condition_with_a_save():
    engine = fight([MEDICINE], sphere="tianxia.sphere.iron_fist", ally=True)
    assert "Medicine of the Closed Gate" not in names(engine)  # nothing to repeat
    assert not any(line.startswith("During combat") for line in riders(MEDICINE))


def test_patient_water_mark_survives_table_commit_and_reload(tmp_path):
    from combat.gate5_service import FACTORY_ACTOR_PREFIX

    _portable(tmp_path, "river", [PATIENT], sphere=RIVER, bases=False)
    service, table, mid = _table(tmp_path, ["river"], "C10-PATIENT-WATER")
    river = FACTORY_ACTOR_PREFIX + "river"
    state = _to_turn(table, mid, river)
    group = next(g for g in state["menu"]["actions"] if g["source_definition_id"] == "system:combat.dodge")
    _act(table, mid, state, group["options"][0])
    loaded = _reload(tmp_path, mid)
    actor = loaded.engine.state.actors[river]
    assert any(c.condition_id == "condition:typed.patient_water" for c in actor.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"
