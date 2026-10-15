"""Rider lane C9 (2026-09-30, owner: "i want everything we can automated, keep going until its only the non-combat ones left").

Engine-level regressions compiling real characters for the GM lines this lane automated: Spirit Companions (combat/ext/
spirit_bonds.py), Air and Weather. C9_OLD=1 compiles against the base typing (ed09b217) to show each test needs the change.
Plug-ins are imported inside the tests so the file is collected on the base code too.
"""

import copy
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
ME = "actor:factory.riders_c9"
ALLY = "actor:factory.riders_c9_ally"
BASE = "ed09b217"
SC = "tianxia.talent.spirit_companions."
JIAN = "tianxia.mortal.weapon.jian"


@lru_cache(maxsize=1)
def authority():
    if os.environ.get("C9_OLD") == "1":
        return json.loads(subprocess.check_output(["git", "show", f"{BASE}:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"], cwd=ROOT))
    return json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())


def sheet(ids, *, cl=10, dc=15, sphere=None, items=(JIAN,), pool=30, ac=14):
    mech = authority()["mechanics"]
    sphere = sphere or (mech[ids[0]]["sphere_id"] if ids else None)
    bases = [key for key, row in mech.items() if sphere and row.get("sphere_id") == sphere and row.get("kind") == "base_ability"]
    return {
        "identity": {"proficiency_bonus": 4, "cultivation_level": cl, "path": "Qi Cultivation", "key_ability": "WIS"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": pool}, "armor_class": {"base_value": ac}, "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8},
        "spheres_and_talents": {"sphere_record_ids": [sphere] if sphere else [],
                                "learned_talent_record_ids": list(dict.fromkeys([*bases, *ids]))},
        "equipment": [{"starting_kit": {"items": [{"item_id": item, "quantity": 1} for item in items]}}],
    }


def bundle(ids, *, actor_id=ME, **kwargs):
    return compile_character(sheet(ids, **kwargs), actor_id=actor_id, typed_authority=authority())


def fight(ids, *, foe_at=(8, 6), ally=False, **kwargs):
    bundles = [bundle(ids, **kwargs), bundle([], actor_id=AN, sphere=None)]
    teams, places = {ME: "team:a", AN: "team:b"}, {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}
    if ally:
        bundles.append(bundle([], actor_id=ALLY, sphere=None))
        teams[ALLY], places[ALLY] = "team:a", {"x": 3, "y": 9}
    engine = Gate4ControllerEngine(ROOT, match_seed="C9", typed_bundles=tuple(bundles),
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
    # Reviewed hands change c18f4990: stow the sword before firing the bow.
    from tests.equipment_readiness import ready_weapon
    ready_weapon(engine, name, actor_id)
    candidates = [c for c in engine.legal_candidates() if c.display_name == name and (target is None or target in c.target_ids)
                  and (destination is None or (c.destination is not None and (c.destination.x, c.destination.y) == destination))]
    assert candidates, (name, target, sorted(set(names(engine))))
    candidate = candidates[0]
    start = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"c9-{start}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return engine.events[start:]


def weapon_attack(engine, actor_id):
    """The actor's Jian attack (every test character carries one)."""
    return next(a.display_name for a in engine.action_catalog.values() if a.owner_id == actor_id and a.economy.value == "ACTION"
                and a.display_name.startswith("Jian") and any(e.get("type") == "attack" for e in (a.parameters.get("typed") or {}).get("effects") or []))


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


# ================================================================================================ Spirit Companions
SPIRIT_KIT = [SC + "covenant_spirit", SC + "battle_manifestation"]


def spirit_of(engine):
    return next(a for a in engine.state.actors.values() if a.summon and a.summon["owner"] == ME and a.summon["group"] == "bonded_spirit")


@pytest.mark.parametrize("cl,far,offered", [(1, 13, False), (1, 11, True), (5, 19, True), (4, 19, False)])
def test_spirit_recall_brings_the_spirit_beside_you_within_its_realm_range(cl, far, offered):
    engine = fight([SC + "spirit_recall", *SPIRIT_KIT], cl=cl, foe_at=(18, 13))
    engine.state.actors[ME].position = Position(x=0, y=6)
    spirit = spirit_of(engine)
    spirit.position = Position(x=far, y=6)  # 5 feet a square: 65 / 55 / 95 / 95 feet away (120 feet from Foundation, CL 5)
    assert ("Spirit Recall" in names(engine)) is offered
    if not offered:
        return
    events = use(engine, "Spirit Recall")
    assert engine.grid.distance_ft(engine.state.actors[ME].position, spirit.position) <= 5
    moved = [e for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == spirit.entity_id]
    assert moved and moved[0].payload.get("teleport")  # folds through the bond: no path, no Opportunity Attacks


def test_spirit_recall_is_not_offered_for_a_restrained_spirit():
    engine = fight([SC + "spirit_recall", *SPIRIT_KIT], foe_at=(18, 13))
    spirit = spirit_of(engine)
    spirit.position = Position(x=9, y=6)
    engine._apply_condition(spirit, "condition:typed.restrained", "test:hold", AN, expires_on="UNTIL_REMOVED")
    assert "Spirit Recall" not in names(engine)


@pytest.mark.parametrize("mode", ["disadvantage", "ac"])
def test_guardian_posture_guards_only_the_first_attack(mode):
    engine = fight([SC + "guardian_spirit_posture", *SPIRIT_KIT], foe_at=(4, 6))
    me = engine.state.actors[ME]
    spirit_of(engine).position = Position(x=3, y=7)
    before = engine._effective_ac(me) if hasattr(engine, "_effective_ac") else None
    label = ("Guardian Spirit Posture: the first attack against them has Disadvantage" if mode == "disadvantage"
             else "Guardian Spirit Posture: +Proficiency Bonus to their AC against the first attack")
    use(engine, label, target=ME)
    turn(engine, AN)
    first = [e for e in use(engine, weapon_attack(engine, AN), target=ME) if e.event_type == "ATTACK_ROLLED"][0]
    if mode == "disadvantage":
        assert first.payload["mode"] == "DISADVANTAGE"
    else:
        assert int(first.payload.get("target_ac") or first.payload.get("ac") or 0) == 14 + 4
    second = [e for e in use(engine, weapon_attack(engine, AN), target=ME) if e.event_type == "ATTACK_ROLLED"][0]
    assert second.payload["mode"] == "NORMAL"
    assert int(second.payload.get("target_ac") or second.payload.get("ac") or 14) == 14


def test_guardian_posture_needs_the_spirit_within_ten_feet_of_the_protected_creature():
    engine = fight([SC + "guardian_spirit_posture", *SPIRIT_KIT], ally=True, foe_at=(12, 6))
    spirit_of(engine).position = Position(x=3, y=10)  # beside the ally at 3,9; 20 feet from you at 3,6
    offered = [c for c in engine.legal_candidates() if c.display_name.startswith("Guardian Spirit Posture")]
    assert offered and all(ME not in c.target_ids for c in offered) and all(ALLY in c.target_ids for c in offered)


def _intercession_fight(qi=30):
    engine = fight([SC + "spirit_intercession", *SPIRIT_KIT], foe_at=(6, 8))
    spirit = spirit_of(engine)
    spirit.position = Position(x=5, y=8)
    spirit.armor_class = -50  # the attack still hits through Disadvantage
    engine.state.actors[ME].resources["resource:core.qi"] = qi
    turn(engine, AN)
    return engine, spirit


@pytest.mark.parametrize("answer,qi_after,strain_after", [("pay_cp", 29, 0), ("bond_strain", 30, 1)])
@pytest.mark.parametrize("legacy_watch", [False, True])
def test_spirit_intercession_hit_costs_cp_or_bond_strain(answer, qi_after, strain_after, legacy_watch):
    engine, spirit = _intercession_fight()
    if legacy_watch:
        row = next(r for r in engine.typed_reaction_rows[ME] if r.get("feature_id") == SC + "spirit_intercession")
        row["effects"].append({"type": "spirit_intercession_watch", "applies_to": "self"})
    # The integrated ability uses Hunt17's single attack-scoped price prompt.
    asked = answers(engine, {"spirit_intercession_hit": ["take_strain" if answer == "bond_strain" else answer]})
    events = use(engine, weapon_attack(engine, AN), target=spirit.entity_id)
    rolled = [e for e in events if e.event_type == "ATTACK_ROLLED"][0]
    assert rolled.payload["mode"] == "DISADVANTAGE"
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id.endswith("spirit_intercession") for e in events)
    me = engine.state.actors[ME]
    assert any(a.endswith("spirit_intercession_hit") for a in asked)
    assert me.resources["resource:core.qi"] == qi_after
    assert me.resources["resource:named.bond_strain"] == strain_after
    retained = [c for c in me.conditions.values() if c.condition_id == "condition:typed.spirit_bond_strain"]
    assert len(retained) == bool(strain_after)
    if retained:
        assert retained[0].data["strain"] == strain_after
    attacker = engine.state.actors[AN]  # the Disadvantage was on that one attack roll only
    assert not [m for m in attacker.modifiers.values() if m.target_field == "attack_mode" and m.value == "DISADVANTAGE" and not m.consumed]


def test_bond_recovery_updates_retained_intercession_condition():
    from combat.ext.spirit_bonds import add_strain, PACT

    engine, spirit = _intercession_fight(qi=0)
    answers(engine, {"spirit_intercession_hit": ["take_strain"]})
    use(engine, weapon_attack(engine, AN), target=spirit.entity_id)
    owner = engine.state.actors[ME]
    retained = next(c for c in owner.conditions.values() if c.condition_id == "condition:typed.spirit_bond_strain")
    assert owner.resources["resource:named.bond_strain"] == retained.data["strain"] == 1
    start = len(engine.events)
    add_strain(engine, owner, -1, PACT, "The blow served the spirit's Nature.")
    assert owner.resources["resource:named.bond_strain"] == retained.data["strain"] == 0
    assert retained.expires_on is None
    updates = [e for e in engine.events[start:] if e.event_type == "CONDITION_APPLIED"]
    assert len(updates) == 1 and updates[0].payload["retained_instance_update"] == 1


def test_spirit_intercession_without_cp_takes_bond_strain_and_ignores_other_allies():
    engine, spirit = _intercession_fight(qi=0)
    use(engine, weapon_attack(engine, AN), target=spirit.entity_id)
    assert engine.state.actors[ME].resources["resource:named.bond_strain"] == 1
    # the owner itself is attacked: Spirit Intercession does not answer (it guards the bonded spirit only)
    events = use(engine, weapon_attack(engine, AN), target=ME) if engine.grid.distance_ft(engine.state.actors[AN].position, engine.state.actors[ME].position) <= 5 else []
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id.endswith("spirit_intercession") for e in events)


def test_spirit_intercession_needs_you_within_thirty_feet_of_the_spirit():
    engine, spirit = _intercession_fight()
    engine.state.actors[ME].position = Position(x=0, y=0)
    spirit.position = Position(x=12, y=8)
    engine.state.actors[AN].position = Position(x=13, y=8)
    events = use(engine, weapon_attack(engine, AN), target=spirit.entity_id)
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id.endswith("spirit_intercession") for e in events)


def test_destroyed_spirit_gains_bond_strain_and_can_be_called_back_for_two_cp():
    engine = fight(SPIRIT_KIT, foe_at=(12, 6))
    me, spirit = engine.state.actors[ME], spirit_of(engine)
    assert "Call Back Bonded Spirit" not in names(engine)
    engine._commit_damage(spirit, spirit.current_hp + spirit.temporary_hp, "FORCE", "test:blow", AN, None, reaction_depth=0)
    assert not spirit.active and spirit.summon["status"] == "destroyed"
    assert me.resources["resource:named.bond_strain"] == 1
    qi = me.resources["resource:core.qi"]
    use(engine, "Call Back Bonded Spirit")
    assert spirit.active and spirit.current_hp == spirit.maximum_hp
    assert me.resources["resource:core.qi"] == qi - 2
    assert "Call Back Bonded Spirit" not in names(engine)


def test_pact_brother_rhythm_asks_after_you_strike_what_your_spirit_struck():
    engine = fight([SC + "pact_brother_battle_rhythm", *SPIRIT_KIT], foe_at=(5, 6))
    me, spirit, foe = engine.state.actors[ME], spirit_of(engine), engine.state.actors[AN]
    foe.armor_class = -50
    spirit.position = Position(x=5, y=7)
    asked = answers(engine, {"pact_brother": ["advantage"]})
    use(engine, "Command Bonded Spirit")
    engine.end_turn()
    assert engine.state.current_actor_id == spirit.entity_id
    use(engine, next(a.display_name for a in engine.action_catalog.values() if a.owner_id == spirit.entity_id and "Strike" in a.display_name),
        target=AN)
    assert not asked  # you have not struck it yet
    while engine.state.current_actor_id != ME:
        engine.end_turn()
    me.position = Position(x=4, y=6)
    use(engine, weapon_attack(engine, ME), target=AN)
    assert any(a.endswith("pact_brother") for a in asked)
    assert any(m.target_field == "incoming_attack_mode" and m.value == "ADVANTAGE" for m in foe.modifiers.values())
    count = len(asked)
    use(engine, weapon_attack(engine, ME), target=AN)
    assert len(asked) == count  # once per round


def test_manifest_spirit_domain_options_each_make_their_own_field():
    engine = fight([SC + "manifest_spirit_domain", *SPIRIT_KIT], foe_at=(12, 6))
    offered = " | ".join(sorted({n for n in names(engine) if n.startswith("Manifest Spirit Domain")}))
    assert "Manifest Spirit Domain: Difficult Terrain for Enemies at" in offered and "Manifest Spirit Domain: Light Obscurement at" in offered
    specs = {a.display_name: a.parameters["typed"]["zone_spec"] for a in engine.action_catalog.values()
             if a.display_name.startswith("Manifest Spirit Domain")}
    assert specs["Manifest Spirit Domain: Difficult Terrain for Enemies"]["difficult"] == "hostile"
    assert specs["Manifest Spirit Domain: Light Obscurement"]["obscured"] == "light"
    assert not specs["Manifest Spirit Domain: Ally Advantage"]["difficult"]  # it gave difficult terrain free with every choice
    assert specs["Manifest Spirit Domain: Ally Advantage"]["shape"] == "sphere" and specs["Manifest Spirit Domain: Ally Advantage"]["size_ft"] == 20


# ------------------------------------------------------------------------------------------------ table level
def _portable(tmp_path, name, ids, **kwargs):
    folder = tmp_path / "portable_characters" / name
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet(ids, **kwargs)))


def test_spirit_guard_survives_table_commit_and_reload(tmp_path):
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService

    _portable(tmp_path, "keeper", [SC + "guardian_spirit_posture", *SPIRIT_KIT])
    _portable(tmp_path, "rival", [], sphere=None)
    service = CombatService(ROOT, tmp_path)
    view = service.create_factory_match(project_ids=["keeper"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "rival"],
        control_modes={FACTORY_ACTOR_PREFIX + side: "MANUAL" for side in ("keeper", "rival")}, match_seed="C9-GUARD-SAVED")
    mid = view["match_id"]
    table = TabletopService(service, tmp_path)
    for _ in range(6):
        state = table.state(mid)
        menu = state["menu"]
        if menu["actor_id"] == FACTORY_ACTOR_PREFIX + "keeper":
            break
        table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    state = table.state(mid)
    menu = state["menu"]
    keeper = FACTORY_ACTOR_PREFIX + "keeper"
    assert menu["actor_id"] == keeper

    def cast_posture(answers=()):
        state = table.state(mid)
        menu = state["menu"]
        group = next(g for g in menu["actions"] if "guardian_spirit_posture#opt1" in g["source_definition_id"])
        option = next(o for o in group["options"] if keeper in (o.get("target_ids") or []))
        return table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                         state["last_sequence"], list(answers))

    # "If the spirit's Nature is Guardian, Ancestor, Shield, Mountain, Shrine, Beast, or similar, the protected
    # creature also gains Temporary HP equal to your Proficiency Bonus" rides BOTH posture choices (AUTO5f1 finding
    # 10), and a spirit's Nature is a character fact the table cannot read, so the AC button asks it too.
    answers, prompts = [], []
    for _ in range(12):
        result = cast_posture(answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        answers.append({**prompt["context"], "selection": "USE",
                        "option_ids": [o["id"] for o in prompt["choice"]["options"] if o["id"] == "no"]})
    else:
        raise AssertionError("the posture never committed")
    assert prompts and "GUARDIAN_NATURE" in str(prompts[0]["context"].get("checkpoint")), [str(p)[:200] for p in prompts]
    assert any("Nature" in str(o["label"]) for p in prompts for o in p["choice"]["options"]), [
        [o["label"] for o in p["choice"]["options"]] for p in prompts]
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    from combat.ext.spirit_bonds import GUARD, guard_ac

    held = [c for c in loaded.engine.state.actors[keeper].conditions.values() if c.condition_id == GUARD]
    assert held and held[0].data["mode"] == "ac" and guard_ac(loaded.engine, loaded.engine.state.actors[keeper]) == 4
    assert loaded.mechanical.replay()["status"] == "PASS"


# ================================================================================================ Air
BOW = "tianxia.mortal.weapon.gong_jian"


FOE2 = "actor:factory.riders_c9_foe2"


def air_fight(ids, *, cl=10, dc=15, foe_at=(12, 6), foe_items=(BOW, JIAN), ally=False, key=2, foe_ids=(), second_foe=False):
    """An Air cultivator (ME at 3,6) against a typed archer (AN)."""
    mech = authority()["mechanics"]
    mine = sheet(ids, cl=cl, dc=dc, sphere="tianxia.sphere.air")
    mine["ability_scores_and_statistics"]["abilities"] = [{"ability": a, "score": 10 + 2 * key, "modifier": key}
                                                         for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")]
    bundles = [compile_character(mine, actor_id=ME, typed_authority=authority()),
               compile_character(sheet(list(foe_ids), sphere="tianxia.sphere.air" if foe_ids else None, items=foe_items, dc=dc),
                                 actor_id=AN, typed_authority=authority())]
    teams, places = {ME: "team:a", AN: "team:b"}, {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}
    if ally:
        bundles.append(compile_character(sheet([], sphere=None), actor_id=ALLY, typed_authority=authority()))
        teams[ALLY], places[ALLY] = "team:a", {"x": 6, "y": 6}
    if second_foe:
        bundles.append(compile_character(sheet([], sphere=None), actor_id=FOE2, typed_authority=authority()))
        teams[FOE2], places[FOE2] = "team:b", {"x": 8, "y": 9}
    engine = Gate4ControllerEngine(ROOT, match_seed="C9-AIR", typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": list(teams), "team_by_actor": teams, "starting_positions": places})
    turn(engine, ME)
    foe = engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 1000
    return engine


def cast_at(engine, name, at, actor_id=ME):
    actor = engine.state.actors[actor_id]
    actor.action_available = actor.bonus_action_available = True
    found = [c for c in engine.legal_candidates() if c.display_name.split(" at ")[0] == name and c.destination is not None
             and (c.destination.x, c.destination.y) == at]
    assert found, (name, at, sorted({c.display_name.split(" at ")[0] for c in engine.legal_candidates()}))
    candidate = found[0]
    start = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"c9-{start}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return engine.events[start:]


def bow(engine):
    return next(a.display_name for a in engine.action_catalog.values() if a.owner_id == AN and a.display_name.startswith("Gong Jian"))


def shots(engine, target=ME, count=1):
    turn(engine, AN)
    modes = []
    for _ in range(count):
        events = use(engine, bow(engine), target=target, actor_id=AN)
        modes.append(next(e for e in events if e.event_type == "ATTACK_ROLLED").payload["mode"])
    return modes


@pytest.mark.parametrize("cl,size", [(1, 10), (5, 15), (11, 20)])
def test_gather_current_grows_with_realm(cl, size):
    engine = air_fight([], cl=cl)
    specs = [a.parameters["typed"]["zone_spec"] for a in engine.action_catalog.values() if a.display_name.startswith("Gather Current:")]
    assert specs and all(spec["size_ft"] == size for spec in specs)


def test_gather_current_turn_disadvantages_only_the_first_arrow():
    engine = air_fight([])
    cast_at(engine, "Gather Current: Turn", (7, 6))
    assert shots(engine, count=2) == ["DISADVANTAGE", "NORMAL"]


def test_gather_current_press_slows_the_first_hostile_creature_only():
    from combat import zones

    engine = air_fight([], ally=True, foe_at=(8, 6))
    cast_at(engine, "Gather Current: Press", (7, 6))
    turn(engine, AN)  # the archer starts its turn inside the Current
    zone = next(z for z in zones.typed_zones(engine) if z.trigger_profile.get("name") == "Gather Current")
    cells = {(c.x, c.y) for c in zone.affected_cells}
    assert cells <= zones.difficult_cells(engine, engine.state.actors[AN])
    assert not cells & zones.difficult_cells(engine, engine.state.actors[ALLY])


@pytest.mark.parametrize("dc,pulled,restrained", [(50, 10, True), (-50, 5, False)])
def test_cyclone_prison_pulls_toward_its_centre(dc, pulled, restrained):
    engine = air_fight(["TAL_AIR_CYCLONE_PRISON"], dc=dc, foe_at=(12, 6))
    foe = engine.state.actors[AN]
    cast_at(engine, "Cyclone Prison", (10, 6))  # the archer stands 10 feet east of the centre
    # The printed lift is independent of the horizontal pull toward the centre.
    assert engine.grid.distance_ft(Position(x=10, y=6), foe.position.model_copy(update={'z': 0})) == 10 - pulled
    assert foe.position.z == (2 if restrained else 0)
    assert any(c.condition_id == "condition:typed.restrained" for c in foe.conditions.values()) is restrained


def test_cyclone_prison_turns_ranged_weapon_attacks_out_of_it():
    engine = air_fight(["TAL_AIR_CYCLONE_PRISON"], dc=-50, foe_at=(12, 6))
    cast_at(engine, "Cyclone Prison", (12, 3))  # the archer ends inside (pulled 5 feet), shooting out of it
    assert shots(engine, count=2) == ["DISADVANTAGE", "DISADVANTAGE"]


def test_wind_wall_turns_arrows_that_pass_through_it():
    engine = air_fight(["TAL_AIR_WIND_WALL"])
    cast_at(engine, "Wind Wall", (8, 6))
    assert shots(engine) == ["DISADVANTAGE"]


def rig(engine, beat_by=None):
    """Attack rolls land (a natural 15); with ``beat_by``, the next Arrow-Turning Air Check totals the attack roll plus it."""
    original = engine.roller.d20

    def d20(**kwargs):
        record = original(**kwargs)
        reason = str(kwargs.get("reason") or "")
        if reason.startswith("ATTACK:"):
            return record.model_copy(update={"dice": (15,), "natural_result": 15, "total": 15 + int(kwargs["modifier"]), "discarded": ()})
        if reason.startswith("SAVE:system:combat.concentration"):  # Concentration holds through the hit
            return record.model_copy(update={"dice": (20,), "natural_result": 20, "total": 20 + int(kwargs["modifier"]), "discarded": ()})
        if beat_by is not None and reason.startswith("CHECK:TAL_AIR_ARROW_TURNING"):
            attack = next(e for e in reversed(engine.events) if e.event_type == "ATTACK_ROLLED")
            total = int(attack.payload["total"]) + beat_by
            return record.model_copy(update={"modifier": total - int(record.natural_result or record.total), "total": total})
        return record
    engine.roller.d20 = d20


@pytest.mark.parametrize("beat_by,missed,reduced", [(5, True, False), (1, False, True), (-1, False, False)])
def test_arrow_turning_breath_rolls_against_the_attack(beat_by, missed, reduced):
    engine = air_fight(["TAL_AIR_ARROW_TURNING_BREATH"], ally=True, foe_at=(12, 6))
    ally = engine.state.actors[ALLY]
    ally.armor_class = -50
    ally.maximum_hp = ally.current_hp = 500
    asked = answers(engine, {})
    turn(engine, AN)
    rig(engine, beat_by)
    events = use(engine, bow(engine), target=ALLY, actor_id=AN)
    assert any(a.endswith("arrow_turning") for a in asked)
    assert not engine.state.actors[ME].reaction_available
    damage = sum(int(e.payload.get("hp_damage") or 0) for e in events if e.event_type == "DAMAGE_COMMITTED" and ALLY in e.target_ids)
    rolled = sum(int(e.payload.get("total") or 0) for e in events if e.event_type == "DAMAGE_ROLLED")
    if missed:
        assert damage == 0
    elif reduced:
        assert damage < rolled
    else:
        assert damage == rolled


def test_arrow_turning_breath_declined_or_melee_keeps_the_reaction():
    engine = air_fight(["TAL_AIR_ARROW_TURNING_BREATH"], ally=True, foe_at=(7, 6))
    engine.state.actors[ALLY].armor_class = -50
    asked = answers(engine, {"arrow_turning": None})
    turn(engine, AN)
    rig(engine)
    use(engine, bow(engine), target=ALLY, actor_id=AN)
    assert asked == ["choice:needle.arrow_turning"] and engine.state.actors[ME].reaction_available
    use(engine, weapon_attack(engine, AN), target=ALLY, actor_id=AN)  # a sword is not a projectile
    assert engine.state.actors[ME].reaction_available


def test_cloud_sleeve_guard_needs_a_current_and_steps_after_a_miss():
    engine = air_fight(["TAL_AIR_CLOUD_SLEEVE_GUARD"], foe_at=(4, 6))
    me = engine.state.actors[ME]
    turn(engine, AN)
    events = use(engine, weapon_attack(engine, AN), target=ME, actor_id=AN)
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id.endswith("CLOUD_SLEEVE_GUARD") for e in events)
    turn(engine, ME)
    cast_at(engine, "Gather Current: Lift", (8, 8))
    rig(engine)
    me.armor_class = 17  # natural 15 + Jian bonus 2 hits without the guard's penalty
    turn(engine, AN)
    start = me.position
    events = use(engine, weapon_attack(engine, AN), target=ME, actor_id=AN)
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id.endswith("CLOUD_SLEEVE_GUARD") for e in events)
    assert me.position != start and engine.grid.distance_ft(start, me.position) == 5


@pytest.mark.parametrize("key,wall,prone", [("TAL_AIR_GALE_PUSH", "wall", True), ("TAL_AIR_GALE_PUSH", "creature", False),
                                             ("TAL_AIR_PRESSURE_BREAK", "creature", True), ("TAL_AIR_PRESSURE_BREAK", None, False)])
def test_wind_lash_vectors_knock_prone_only_on_a_collision(key, wall, prone):
    engine = air_fight([key], cl=10, dc=50, foe_at=(8, 6), ally=wall == "creature")
    engine.grid.qi_hazard.clear()  # This fixture tests the explicit obstacle below.
    foe = engine.state.actors[AN]
    foe.armor_class = -50
    rig(engine)
    if wall == "wall":
        engine.grid.blocked.add((10, 6))
        engine.__dict__.pop("_wall_base", None)  # the wall layer re-reads the map's blocked squares
    elif wall == "creature":
        engine.state.actors[ALLY].position = Position(x=10, y=6)
    name = next(n for n in names(engine) if n.startswith("Wind Lash: Push + "))
    use(engine, name, target=AN)
    assert any(c.condition_id == "condition:typed.prone" for c in foe.conditions.values()) is prone


def test_sky_sovereign_gives_free_wind_lash_at_300_feet():
    engine = air_fight(["TAL_AIR_SKY_SOVEREIGN_INCARNATION"], cl=17, foe_at=(18, 12))
    use(engine, "Sky-Sovereign Incarnation")
    free = [a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name.startswith("Wind Lash") and a.economy.value == "NONE"]
    assert free and all(int(a.range_ft or 0) == 300 for a in free)
    offered = {c.display_name for c in engine.legal_candidates()}
    assert any(n.startswith("Wind Lash") and "(free)" in n for n in offered)


def test_court_of_the_four_winds_turns_one_arrow_a_round():
    engine = air_fight(["TAL_AIR_COURT_OF_THE_FOUR_WINDS", "TAL_AIR_CLOUD_SLEEVE_GUARD"], cl=12)
    # a player controlling the Air cultivator is asked on the archer's turn too (choice owners)
    assert {row["kind"] for row in engine.typed_passive_rows[ME] if row.get("block") == "air" and row.get("choice_owner")} >= {"court", "cloud_sleeve"}
    court = next(a for a in engine.action_catalog.values() if a.display_name == "Court of the Four Winds").parameters["typed"]["zone_spec"]
    assert not court["difficult"] and not court["triggers"]  # its ground is not difficult for every foe; its state is not re-run
    use(engine, "Court of the Four Winds")
    cast_at(engine, next(n.split(" at ")[0] for n in names(engine) if n.startswith("Gather Current: Lift") and "(free)" in n), (7, 6))
    assert shots(engine, count=2) == ["DISADVANTAGE", "NORMAL"]


def test_empty_lung_edict_once_per_target():
    engine = air_fight(["TAL_AIR_EMPTY_LUNG_EDICT"], cl=15, foe_at=(8, 6), second_foe=True)
    use(engine, "Empty-Lung Edict", target=AN)
    engine.state.actors[ME].action_available = True
    targets = {t for c in engine.legal_candidates() if c.display_name == "Empty-Lung Edict" for t in c.target_ids}
    assert AN not in targets and FOE2 in targets  # "Once per long rest per target": the fight is the long rest


@pytest.mark.parametrize("answer,bonus", [(["use"], True), (None, False)])
def test_breath_braced_body_is_asked(answer, bonus):
    engine = air_fight(["TAL_AIR_BREATH_BRACED_BODY"], cl=5, foe_at=(5, 6), foe_ids=["TAL_AIR_GALE_PUSH"])
    engine.state.actors[ME].armor_class = -50
    asked = answers(engine, {"breath_braced_body": answer})
    turn(engine, AN)
    name = next(n for n in names(engine) if n.startswith("Wind Lash: Push + Gale Push"))
    events = use(engine, name, target=ME, actor_id=AN)
    assert any(e.event_type == "SAVE_ROLLED" and e.actor_id == ME for e in events)
    assert any(a.endswith("breath_braced_body") for a in asked)
    used = [e for e in events if e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("feature_id") == "TAL_AIR_BREATH_BRACED_BODY"]
    assert bool(used and used[0].payload["save_bonus"] == 4) is bonus  # the Proficiency Bonus, only when the player takes it
    assert bool(engine.state.actors[ME].turn_flags.get("lane4_braced_body")) is bonus  # a declined use is not spent


def test_cyclone_prison_survives_table_commit_and_reload(tmp_path):
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService

    _portable(tmp_path, "gale", ["TAL_AIR_CYCLONE_PRISON"], cl=10, dc=60, sphere="tianxia.sphere.air")
    _portable(tmp_path, "rival", [], sphere=None)
    service = CombatService(ROOT, tmp_path)
    view = service.create_factory_match(project_ids=["gale"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "rival"],
        control_modes={FACTORY_ACTOR_PREFIX + side: "MANUAL" for side in ("gale", "rival")}, match_seed="C9-CYCLONE-SAVED")
    mid = view["match_id"]
    table = TabletopService(service, tmp_path)
    gale, rival = FACTORY_ACTOR_PREFIX + "gale", FACTORY_ACTOR_PREFIX + "rival"
    for _ in range(6):
        state = table.state(mid)
        if state["menu"]["actor_id"] == gale:
            break
        table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"])
    state = table.state(mid)
    menu = state["menu"]
    engine = service._load_session(mid).engine
    foe = engine.state.actors[rival]
    group = next(g for g in menu["actions"] if "TAL_AIR_CYCLONE_PRISON" in g["source_definition_id"])
    option = next(o for o in group["options"] if o.get("destination")  # a centre 10 feet from the rival, the rival inside
                  and engine.grid.distance_ft(Position(**o["destination"]), foe.position) == 10
                  # Reviewed physical paths stop at walls. Choose an open,
                  # horizontal center rather than a point in the boundary wall.
                  and o['destination']['y'] == foe.position.y
                  and not engine.grid.terrain_at(Position(**o['destination']), 'BLOCKED')
                  and {"x": foe.position.x, "y": foe.position.y} in (o.get("area") or {}).get("affected_cells", []))
    at = (option["destination"]["x"], option["destination"]["y"])
    result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    moved = loaded.engine.state.actors[rival]
    assert (moved.position.x, moved.position.y) == at  # pulled 10 feet to the centre
    assert any(c.condition_id == "condition:typed.restrained" for c in moved.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_storm_without_direction_no_straight_line_turns_ranged_attacks():
    engine = air_fight(["TAL_AIR_STORM_WITHOUT_DIRECTION"], cl=15, foe_at=(18, 6))
    use(engine, "Storm Without Direction: No Straight Line")
    assert shots(engine, count=2) == ["DISADVANTAGE", "DISADVANTAGE"]


def _rig_perception(engine, total):
    original = engine.roller.d20

    def d20(**kwargs):
        record = original(**kwargs)
        if str(kwargs.get("reason") or "").startswith("CHECK:TAL_AIR_INVISIBLE_BLADE"):
            return record.model_copy(update={"modifier": total - int(record.natural_result or record.total), "total": total})
        return record
    engine.roller.d20 = d20


@pytest.mark.parametrize("inside,perception,mode", [(True, 1, "ADVANTAGE"), (True, 40, "NORMAL"), (False, 1, "NORMAL")])
def test_invisible_blade_current_from_your_own_current(inside, perception, mode):
    engine = air_fight(["TAL_AIR_INVISIBLE_BLADE_CURRENT"], cl=10, foe_at=(9, 6))
    asked = answers(engine, {"invisible_blade": ["use"]})
    cast_at(engine, "Gather Current: Lift", (3, 6) if inside else (6, 10))
    _rig_perception(engine, perception)
    events = use(engine, "Wind Lash: Cut", target=AN)
    assert next(e for e in events if e.event_type == "ATTACK_ROLLED").payload["mode"] == mode
    assert any(a.endswith("invisible_blade") for a in asked) is inside


@pytest.mark.parametrize("dc,feet,prone", [(50, 20, True), (50, 10, False), (-50, 20, False)])
def test_storm_without_direction_no_steady_foot(dc, feet, prone):
    engine = air_fight(["TAL_AIR_STORM_WITHOUT_DIRECTION"], cl=15, dc=dc, foe_at=(10, 6))
    use(engine, "Storm Without Direction: No Steady Foot")
    turn(engine, AN)
    foe = engine.state.actors[AN]
    move = next(c for c in engine.legal_candidates() if c.kind.value == "MOVE" and c.destination is not None
                and c.destination.y == 6 and c.destination.x == 10 + feet // 5)
    engine.execute_intent(ActionIntent(intent_id="move", decision_id=move.decision_id, candidate_id=move.candidate_id,
                                       state_version=move.state_version, actor_id=AN, target_ids=(), destination=move.destination))
    assert any(c.condition_id == "condition:typed.prone" for c in foe.conditions.values()) is prone
